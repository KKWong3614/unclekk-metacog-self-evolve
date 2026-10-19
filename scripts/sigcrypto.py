#!/usr/bin/env python3
"""
sigcrypto.py — 纯标准库实现的「人类闸密码学身份绑定」原语（W1）。

设计目标（见 W1-W2 设计方案）：
- 人类在自有终端用**私钥**对「提案 id + 内容哈希」签名；`apply` 仅持**公钥**验签。
- Agent 进程（apply）**永不持有私钥**，私钥以人类口令加密落盘（PBKDF2 + HMAC 流密码）。
- 无任何第三方依赖（cryptography 在运行时 python3 中不可用），故本模块只用 stdlib。

安全说明：
- RSA-2048 + PKCS#1 v1.5 签名（EMSA-PKCS1-v1_5，RFC 8017 §9.2）；公钥指数钉死 e=65537（拒 e=1 退化指数伪造及非 65537 弱指数，N8/P1-1）。
- 私钥 at-rest 加密采用「PBKDF2-SHA256(口令, salt, 200k, dklen=64) → 前 32 字节 CTR 加密密钥 + 后 32 字节 MAC 密钥」，
  基于 HMAC-SHA256-CTR 的认证加密构造，安全性依赖 SHA-256 的 PRF 假设（非形式化可证明），不依赖任何对称密码库。
- **密文带 HMAC-SHA256 认证标签**（覆盖 salt||nonce||ct），解密前恒定时间校验，杜绝静默篡改 / 坏明文（N8/P0-1）。
- **iters 钉死常量 200k**（解密不再读 blob 内 iters），杜绝弱密钥重加密降级与 iters 无上界 DoS（N8/P0-2）。
- 验签采用 hmac.compare_digest 做恒定时间比较。
"""

import base64
import hashlib
import hmac
import json
import os
import secrets

# SHA-256 的 DigestInfo（DER），用于 EMSA-PKCS1-v1_5 的 T = DigestInfo || H
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


# ----------------------------------------------------------------------------
# 基础数论（RSA 密钥生成，纯 stdlib）
# ----------------------------------------------------------------------------

def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def _modinv(a: int, m: int) -> int:
    """扩展欧几里得：求 a 在模 m 下的逆元。"""
    old_r, r = a, m
    old_s, s = 1, 0
    while r:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_s, s = s, old_s - q * s
    if old_r != 1:
        raise ValueError("modinv 不存在（a 与 m 不互素）")
    return old_s % m


def _is_prime(n: int, k: int = 40) -> bool:
    """Miller-Rabin 素性测试（40 轮 → 错误概率 < 4^-40）。"""
    if n < 2:
        return False
    # 小素数试除快速排除
    for p in (2, 3, 5, 7, 11, 13, 17,19, 23, 29, 31, 37, 41, 43, 47):
        if n % p == 0:
            return n == p
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(k):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x * x, 1, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    """生成指定位数的大概率素数（先小素数试除，再做 Miller-Rabin）。"""
    while True:
        cand = secrets.randbits(bits) | 1  # 奇数
        # 简单试除加速
        ok = True
        for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
                  53, 59, 61, 67, 71, 73, 79, 83, 89, 97):
            if cand % p == 0:
                ok = False
                break
        if not ok:
            continue
        if _is_prime(cand):
            return cand


def gen_keypair(bits: int = 2048):
    """生成 RSA 密钥对。返回 (pub, priv)，均为 (n, e) / (n, d)。"""
    e = 65537
    while True:
        p = _gen_prime(bits // 2)
        q = _gen_prime(bits // 2)
        if p == q:
            continue
        n = p * q
        phi = (p - 1) * (q - 1)
        if _gcd(e, phi) != 1:
            continue
        d = _modinv(e, phi)
        return (n, e), (n, d)


# ----------------------------------------------------------------------------
# 序列化（仅 n/e、n/d 用 base64 存于 JSON，无 PEM 依赖）
# ----------------------------------------------------------------------------

def serialize_pub(pub) -> str:
    n, e = pub
    return json.dumps({"n": base64.b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).decode(),
                       "e": e}, separators=(",", ":"))


def serialize_priv(priv) -> str:
    n, d = priv
    nb = (n.bit_length() + 7) // 8
    return json.dumps({"n": base64.b64encode(n.to_bytes(nb, "big")).decode(),
                       "d": base64.b64encode(d.to_bytes(nb, "big")).decode()}, separators=(",", ":"))


def _b64int(s: str) -> int:
    return int.from_bytes(base64.b64decode(s), "big")


def _valid_public_exponent(e: int, n: int) -> bool:
    """钉死 e==65537（P1-1 + LOW-2/LOW-1）。

    本模块密钥对仅由 gen_keypair 生成 e=65537，故验签端直接要求 e==65537：
    既排除 e=1 退化指数伪造（s^1=s 可伪造有效签名），也排除 e=3/5 等非 65537 弱指数。
    同时校验 n 为 int 且 >0，避免 verify 对非 int n（如 str）抛 TypeError、偏离其布尔契约（LOW-1）。
    """
    return isinstance(e, int) and isinstance(n, int) and n > 0 and e == 65537


def deserialize_pub(s: str):
    o = json.loads(s)
    n = _b64int(o["n"])
    e = int(o["e"])
    if not _valid_public_exponent(e, n):
        raise ValueError("非法公钥指数 e（本模块仅接受 e=65537）")
    return n, e


def deserialize_priv(s: str):
    o = json.loads(s)
    return _b64int(o["n"]), _b64int(o["d"])


# ----------------------------------------------------------------------------
# PKCS#1 v1.5 签名
# ----------------------------------------------------------------------------

def _emsa_pkcs1_v15(message: bytes, k: int) -> bytes:
    h = hashlib.sha256(message).digest()
    T = _SHA256_DIGEST_INFO + h
    if k < len(T) + 11:
        raise ValueError("密钥太短，无法容纳 PKCS#1 v1.5 结构")
    ps_len = k - len(T) - 3
    EM = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + T
    return EM


def sign(priv, message: bytes) -> bytes:
    n, d = priv
    k = (n.bit_length() + 7) // 8
    EM = _emsa_pkcs1_v15(message, k)
    m = int.from_bytes(EM, "big")
    s = pow(m, d, n)
    return s.to_bytes(k, "big")


def verify(pub, message: bytes, signature: bytes) -> bool:
    n, e = pub
    if not _valid_public_exponent(e, n):
        return False
    k = (n.bit_length() + 7) // 8
    if not isinstance(signature, bytes) or len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    m = pow(s, e, n)
    EM = m.to_bytes(k, "big")
    expected = _emsa_pkcs1_v15(message, k)
    return hmac.compare_digest(EM, expected)


# ----------------------------------------------------------------------------
# 私钥 at-rest 加密（人类口令 → PBKDF2 → 32 字节密钥 → HMAC 流密码 XOR）
# ----------------------------------------------------------------------------

_PBKDF2_ITERS = 200_000


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(4, "big"), "sha256").digest()
        counter += 1
    return out[:length]


def _auth_tag(mac_key: bytes, salt: bytes, nonce: bytes, ct: bytes) -> bytes:
    """HMAC-SHA256 认证标签，覆盖 salt||nonce||ct（恒定时间验签）。

    P0-1 修复：为密文提供完整性保护，杜绝「篡改 ct 静默解出坏明文」。
    """
    return hmac.new(mac_key, salt + nonce + ct, "sha256").digest()


def encrypt_priv(priv_json: str, passphrase: str) -> dict:
    salt = secrets.token_bytes(16)
    # 同一 PBKDF2 派生 64 字节：前 32 字节做 CTR 加密密钥，后 32 字节做 MAC 密钥（相互独立）
    derived = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, _PBKDF2_ITERS, dklen=64)
    enc_key = derived[:32]
    mac_key = derived[32:]
    nonce = secrets.token_bytes(16)
    pt = priv_json.encode("utf-8")
    ct = _xor(pt, _keystream(enc_key, nonce, len(pt)))
    mac = _auth_tag(mac_key, salt, nonce, ct)
    return {
        "algo": "pbkdf2-sha256+hmac-stream",
        "iters": _PBKDF2_ITERS,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ct).decode(),
        "mac": base64.b64encode(mac).decode(),
    }


class InvalidCiphertext(ValueError):
    """密文完整性校验失败（口令错误 / 密文被篡改 / MAC 不匹配 / 旧版无 MAC blob）。"""


def decrypt_priv(blob: dict, passphrase: str) -> bytes:
    """返回解密后的**原始字节**。

    安全修复（N8 / P0-1 + P0-2）：
    - iters 钉死为常量 _PBKDF2_ITERS：不再从 blob 读取，杜绝 C-1 下弱密钥重加密落盘 + iters 无上界 DoS。
    - 解密前恒定时间校验 HMAC 标签：标签不匹配（口令错误 / 密文被篡改 / 旧版无 MAC）一律显式拒绝，
      杜绝静默解出坏明文（P0-1）。调用方（metacog.py）以 `except Exception` 捕获本异常。
    """
    if "mac" not in blob:
        raise InvalidCiphertext("密文缺少 MAC 标签（旧版 blob 不支持，请重新 `confirm --keygen`）")
    salt = base64.b64decode(blob["salt"])
    nonce = base64.b64decode(blob["nonce"])
    ct = base64.b64decode(blob["ct"])
    stored_mac = base64.b64decode(blob["mac"])
    # iters 钉死常量（忽略 blob 中的 iters，防降级 / DoS）
    derived = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, _PBKDF2_ITERS, dklen=64)
    enc_key = derived[:32]
    mac_key = derived[32:]
    expected_mac = _auth_tag(mac_key, salt, nonce, ct)
    if not hmac.compare_digest(expected_mac, stored_mac):
        raise InvalidCiphertext("密文完整性校验失败（口令错误或密文被篡改）")
    return _xor(ct, _keystream(enc_key, nonce, len(ct)))


def decrypt_priv_str(blob: dict, passphrase: str) -> str:
    """解密并解码为 str；口令错误时得到乱码，会抛出 UnicodeDecodeError / 调用方应捕获。"""
    return decrypt_priv(blob, passphrase).decode("utf-8")


# ----------------------------------------------------------------------------
# 人类闸签名消息构造（带用途前缀，防跨协议复用）
# ----------------------------------------------------------------------------

def approval_message(proposal_id: str, content_hash: str, trial_from_index=None) -> bytes:
    """人类签名的消息：用途前缀 + 提案 id + 内容哈希 + （可选）试用窗起点。

    v2.5.7（M-7 闭环）：新增 trial_from_index 绑定——人类签名须覆盖试用窗起点，
    否则受信任锚的 trial_from_index 字段可被 ledger 写者单方面改写、验签仍过，
    重新打开 v2.2.3/v2.2.4 已封死的防过拟合保证。trial_from_index 为 None 时保持旧消息
    格式（仅 id+chash），用于兼容旧版签名与既有测试。"""
    msg = "METACOG-HUMAN-APPROVAL|{}|{}".format(proposal_id, content_hash)
    if trial_from_index is not None:
        msg += "|trial_from_index={}".format(trial_from_index)
    return msg.encode("utf-8")


def content_hash_of(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------
# 自检（独立运行：python3 sigcrypto.py）
# ----------------------------------------------------------------------------

def _selftest() -> int:
    print("=== sigcrypto 自检 ===")
    pub, priv = gen_keypair(2048)
    print("  密钥对生成 OK (RSA-2048)")
    msg = approval_message("P-1", content_hash_of('{"id":"P-1"}'))
    sig = sign(priv, msg)
    assert verify(pub, msg, sig), "正常验签应成功"
    print("  签名/验签 OK")
    # 篡改消息应失败
    bad = approval_message("P-1", content_hash_of('{"id":"P-2"}'))
    assert not verify(pub, bad, sig), "篡改哈希应验签失败"
    print("  篡改内容哈希 → 验签失败 OK")
    # 错私钥应失败
    _, priv2 = gen_keypair(2048)
    sig2 = sign(priv2, msg)
    assert not verify(pub, msg, sig2), "错误私钥应验签失败"
    print("  其他私钥签名 → 验签失败 OK")
    # at-rest 加密往返
    blob = encrypt_priv(serialize_priv(priv), "hunter2")
    back = decrypt_priv(blob, "hunter2").decode("utf-8")
    assert back == serialize_priv(priv), "私钥加解密往返应一致"
    # 错误口令 → MAC 校验失败，显式拒绝（不再静默解出坏明文）
    try:
        decrypt_priv(blob, "wrong")
        raise AssertionError("错误口令应触发 InvalidCiphertext")
    except InvalidCiphertext:
        pass
    print("  错误口令 → MAC 校验拒绝 OK")
    # 篡改密文 → MAC 校验失败（P0-1 关闭：密文不再可静默篡改）
    tampered = dict(blob)
    bad_ct = bytearray(base64.b64decode(tampered["ct"]))
    bad_ct[0] ^= 0x01
    tampered["ct"] = base64.b64encode(bytes(bad_ct)).decode()
    try:
        decrypt_priv(tampered, "hunter2")
        raise AssertionError("篡改密文应触发 InvalidCiphertext")
    except InvalidCiphertext:
        pass
    print("  篡改密文 → MAC 校验拒绝 OK")
    # e=1 退化指数伪造必须被拒（P1-1 关闭：e=1 伪造签名不可验过）
    n_val, _ = pub
    k = (n_val.bit_length() + 7) // 8
    forged_pub = (n_val, 1)
    forged_sig = _emsa_pkcs1_v15(msg, k)  # e=1 下 s^1 = s，签名=预期 EM 即可伪造
    assert not verify(forged_pub, msg, forged_sig), "e=1 伪造签名必须验签失败"
    print("  e=1 伪造签名 → 验签失败 OK")
    print("  私钥 at-rest 加密往返 OK")
    print("=== 全部通过 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
