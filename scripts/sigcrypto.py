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
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets

# v2.27.32（R-1 双密钥根信任）：根锚指纹必须为 64 位小写 hex（与 anchor_pubkey_sha256 输出一致）。
_ROOT_SEAL_FP_RE = re.compile(r"^[0-9a-f]{64}$")
# 紧凑 UTC 时间戳（与 attestation 同口径）：YYYYMMDDTHHMM = 8 位数字 + T + 4 位数字，无冒号。
_ROOT_SEAL_AT_RE = re.compile(r"^\d{8}T\d{4}$")

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
    """RSA PKCS#1 v1.5 签名（确定性）。

    v2.27.15（L-06 文档如实化 + 外部审计 N-16 披露）：本实现**无随机盐**——同一 (私钥, 消息)
    恒产生同一签名字节。副作用：配合 metacog 的一次性签名消费（consume_human_sig_atomic），
    已被消费的 attestation 无法通过"重新签名"获得不同字节；resign 路径（t0 由旧锚固定、
    chash 由提案固定）签名烧毁后该提案永久不可重签。nonce 化须与 attestation 格式迁移一并做
    （已并入 C-01 非对称化专项）。"""
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

def new_nonce() -> str:
    """生成人类闸签名 nonce（v2.27.17，L-06/防重放配套）：128-bit 随机十六进制串。"""
    return secrets.token_hex(16)


def approval_message(proposal_id: str, content_hash: str, trial_from_index=None, nonce=None) -> bytes:
    """人类签名的消息（v2.27.17 起为 v2 格式：长度前缀 + 可选 nonce）。

    v2 格式（L-06 收口）：每字段 ``{name}:{len:04d}:{value}``，字段间以 ``|`` 连接。
    长度前缀杜绝旧格式中「value 含分隔符 | 即可注入/歧义拼接」的伪造面；
    可选 nonce 字段（new_nonce() 生成）实现签名一次性绑定，防跨实例重放。
    用途前缀 v2 为 METACOG-HUMAN-APPROVAL-v2，与旧格式（METACOG-HUMAN-APPROVAL）
    互不匹配，天然防跨格式混淆。

    v2.27.20（N-4 收口）：长度前缀口径由 Python str **码点数**改为 **UTF-8 字节数**
    （``len(v.encode("utf-8"))``）——消息本身以 UTF-8 编码传输/签名，前缀描述的应是
    其编码后字节长度；否则未来实现 v2 解析器时「按前缀切字节」与「按码点切」会分叉，
    非 ASCII 字段值（如含中文的提案 id）将产生歧义注入面。ASCII 字段下两种口径数值
    相同（v2 实际字段 purpose/id/chash/t0/nonce 现网均为 ASCII，存量签名不受影响）；
    若存在含非 ASCII 字段值的 v2 存量签名，须重签（v2.27.17 引入至今无已发布的
    非ASCII v2 签名消费方，如实登记）。

    兼容性：旧格式签名仍可通过 approval_message_legacy() 构造对应消息验签
    （见 metacog.verify_human_binding 的四级回退），不强制存量重签。
    """
    parts = [
        ("purpose", "METACOG-HUMAN-APPROVAL-v2"),
        ("id", str(proposal_id)),
        ("chash", str(content_hash)),
    ]
    if trial_from_index is not None:
        parts.append(("t0", str(trial_from_index)))
    if nonce is not None:
        parts.append(("nonce", str(nonce)))
    msg = "|".join("{}:{:04d}:{}".format(k, len(v.encode("utf-8")), v) for k, v in parts)
    return msg.encode("utf-8")


def approval_message_legacy(proposal_id: str, content_hash: str, trial_from_index=None) -> bytes:
    """旧版（v2.27.16 及之前）人类签名消息格式，仅用于验签回退路径。

    v2.5.7（M-7 闭环）：trial_from_index 绑定——人类签名须覆盖试用窗起点，
    否则受信任锚的 trial_from_index 字段可被 ledger 写者单方面改写、验签仍过。"""
    msg = "METACOG-HUMAN-APPROVAL|{}|{}".format(proposal_id, content_hash)
    if trial_from_index is not None:
        msg += "|trial_from_index={}".format(trial_from_index)
    return msg.encode("utf-8")


def content_hash_of(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------
# C-1 完全非对称化（v2.27.21 阶段1）：锚状态 attestation——离线私钥签 / 进程内仅公钥验
# ----------------------------------------------------------------------------
# 威胁模型：运行期 HMAC 锚（env 对称密钥）对本进程可读属部署契约残余（C-01 诚实边界），
# 被约束进程理论上可自签。非对称层的信任根挪到**离线私钥**：人类在离线环境对
# 「信任根状态 commitment」签 RSA attestation；进程/包内只持有**公钥**（钉固树外只读），
# 被约束方事后篡改账本 → commitment 变 → attestation 失配 → fail-closed，且无法伪造新
# attestation（无私钥）。运行期 HMAC 链降级为「意外损坏检出层」，真正防篡改承诺由本层承担。

ATTEST_PURPOSE = "METACOG-ANCHOR-ATTEST-v1"


def anchor_attestation_message(commits: dict, at=None) -> bytes:
    """锚状态 attestation 签名消息（v2.27.21，C-1 阶段1）。

    commits：{name: sha256hex} 字典（键名白名单见下，防任意字段注入）；
    at：**紧凑无冒号** UTC 时间戳（YYYYMMDDTHHMM，如 20261025T1345；None → 当前 UTC）。
    格式约束：attestation 串 "v1:{at}:{b64sig}" 依赖「段内无冒号」定界（b64sig 与紧凑 at
    均不含冒号），故 at 不接受含冒号的 ISO 格式——含冒号输入 → ValueError。
    复用 v2 长度前缀格式（N-4 口径：UTF-8 字节数），purpose 前缀防跨协议复用。
    键名白名单：integrity / applies / sig_claims / frozen_hashes（与 metacog._attest_commits 对齐），
    非法键名 → ValueError。"""
    # v2.27.31（R-5）：新增 break_glass（破闸计数）——破闸使 commitment 失配 → 后续受控命令
    # fail-closed，破闸不再只是 stdout 一句话，而必然留下「须离线重签」的可检痕迹。
    _ALLOWED = ("integrity", "applies", "sig_claims", "frozen_hashes", "break_glass")
    for k in commits:
        if k not in _ALLOWED:
            raise ValueError("attestation 字段名不在白名单（{}）：{}".format(",".join(_ALLOWED), k))
    if at is not None and ":" in str(at):
        raise ValueError("at 须为紧凑无冒号 UTC 时间戳（YYYYMMDDTHHMM，如 20261025T1345）")
    if at is None:
        at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M")
    parts = [("purpose", ATTEST_PURPOSE), ("at", str(at))]
    for k in _ALLOWED:
        if k in commits:
            parts.append((k, str(commits[k])))
    return "|".join("{}:{:04d}:{}".format(k, len(v.encode("utf-8")), v)
                    for k, v in parts).encode("utf-8")


def anchor_attest(priv, commits: dict, at=None) -> str:
    """离线私钥对 commits 签名，返回 "v1:{at}:{b64sig}"（确定性签名，同输入同输出——
    attestation 本身是低频人工操作，无 use-once 消费语义，不引入 nonce）。"""
    if at is None:
        at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M")
    msg = anchor_attestation_message(commits, at=at)
    return "v1:{}:{}".format(at, base64.b64encode(sign(priv, msg)).decode("ascii"))


def anchor_attest_verify(pub, commits: dict, att: str) -> tuple:
    """树外公钥验 attestation。返回 (ok, reason)。
    att 非 "v1:{at}:{b64sig}" 格式 → (False, "attest-malformed")；验签失败 → (False, "attest-mismatch")。"""
    if not isinstance(att, str) or not att.startswith("v1:"):
        return False, "attest-malformed"
    seg = att.split(":", 2)  # at 含冒号（ISO 时间戳），最多切两刀：v1 / at / b64sig
    if len(seg) != 3:
        return False, "attest-malformed"
    _tag, at, b64sig = seg
    try:
        sig = base64.b64decode(b64sig, validate=True)
    except Exception:
        return False, "attest-malformed"
    try:
        msg = anchor_attestation_message(commits, at=at)
    except ValueError as ex:
        return False, "attest-bad-field:{}".format(ex)
    return (True, None) if verify(pub, msg, sig) else (False, "attest-mismatch")


ROOT_SEAL_PURPOSE = "METACOG-ROOT-ANCHOR-SEAL-v1"


def anchor_root_seal_message(fingerprint: str, at: str) -> bytes:
    """外部根锚「签名密封记录」的签名消息（v2.27.32，R-1 双密钥根信任）。

    绑定：purpose 前缀 + 权威指纹 + 密封时间戳。purpose 前缀防跨协议复用
    （与 attestation 消息不复用同一 purpose，密封签名不可被当作 attestation 签名）。
    指纹须 64 位小写 hex（v2.27.32 收紧：此前仅查长度 64，导致 "Z"*64 / " "*64 等
    非 hex 垃圾可签可验，R-1-a）；at 须 12 位紧凑无冒号 UTC 时间戳 YYYYMMDDTHHMM
    （v2.27.32 收紧：此前仅查无冒号，"中"/""/"xxxx" 均可，R-1-c）。"""
    _at = str(at)
    if not _ROOT_SEAL_AT_RE.match(_at):
        raise ValueError("at 须为 12 位紧凑无冒号 UTC 时间戳（YYYYMMDDTHHMM），如 20261025T1345")
    if not (isinstance(fingerprint, str) and _ROOT_SEAL_FP_RE.match(fingerprint)):
        raise ValueError("fingerprint 须为 64 位小写 hex")
    return "{}|fingerprint:{:04d}:{}|at:{:04d}:{}".format(
        ROOT_SEAL_PURPOSE, len(fingerprint.encode("utf-8")), fingerprint,
        len(_at.encode("utf-8")), _at).encode("utf-8")


def anchor_root_seal_sign(priv, fingerprint: str, at=None) -> str:
    """生成签名密封记录 "v1:<fingerprint>:<at>:<b64sig>"（R-1）。

    须由**离线私钥**签发——这正是 C-1 的授权维度修复：写入外部根锚的主体
    必须同时持有信任根私钥（同用户攻击者只有令牌对，无法伪造密封记录）。"""
    if at is None:
        at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M")
    msg = anchor_root_seal_message(fingerprint, at)
    sig = base64.b64encode(sign(priv, msg)).decode("ascii")
    return "v1:{}:{}:{}".format(fingerprint, at, sig)


def anchor_root_seal_verify(pub, record: str, max_age_days: int = 0) -> tuple:
    """校验签名密封记录。返回 (ok, reason, fingerprint)。

    reason ∈ ok / seal-unsigned / seal-malformed / seal-bad-sig / seal-expired
    - seal-unsigned：记录不是 v1 密封格式（v2.27.31 前的裸指纹遗留格式，或攻击者手写）
    - seal-malformed：段数不符 / 指纹非 hex / at 格式非法 / base64 损坏
    - seal-bad-sig：签名校验失败（攻击者改写根锚或用其他密钥签发）
    - seal-expired：密封时间戳超出 max_age_days（v2.27.32 新增；此前密封无时效可永久重放，R-1-b）

    v2.27.32：验签密钥 pub 为**根信任公钥 RK_pub**（独立于 attestation 公钥 AK_pub）；
    密封记录由 RK 私钥签名，故「被钉固的 AK」无法自签密封——攻击者无 RK 私钥即无法产出合法密封。"""
    if not isinstance(record, str) or not record.startswith("v1:"):
        return (False, "seal-unsigned", None)
    seg = record.split(":", 3)
    if len(seg) != 4:
        return (False, "seal-malformed", None)
    _tag, fp, at, b64sig = seg
    try:
        sig = base64.b64decode(b64sig, validate=True)
    except Exception:
        return (False, "seal-malformed", None)
    try:
        msg = anchor_root_seal_message(fp, at)
    except ValueError:
        return (False, "seal-malformed", None)
    if not verify(pub, msg, sig):
        return (False, "seal-bad-sig", fp)
    if max_age_days and max_age_days > 0:
        try:
            at_dt = datetime.datetime.strptime(str(at), "%Y%m%dT%H%M").replace(tzinfo=datetime.timezone.utc)
            age = (datetime.datetime.now(datetime.timezone.utc) - at_dt).days
            if age > max_age_days:
                return (False, "seal-expired", fp)
            # v2.27.33（DSH §2.5 N-3）：未来时间戳永不过期 → 拒收（age<0 即 malformed 语义）
            if age < 0:
                return (False, "seal-future", fp)
        except ValueError:
            return (False, "seal-malformed", fp)
    return (True, "ok", fp)


# ----------------------------------------------------------------------------
# 重钉授权（v2.27.32，§10 #3）：根信任公钥 RK 私钥对「repin:<新AK_fp>」签名，
# 取代原 METACOG_ATTEST_REPIN_ALLOW env 自授权。重钉 AK 公钥须持 RK 私钥签名授权，
# 调用方无法用 env 自行放行。
# ----------------------------------------------------------------------------
ROOT_REPIN_PURPOSE = "METACOG-ROOT-REPIN-v1"


def root_repin_message(new_fp: str) -> bytes:
    """重钉授权消息：绑定 purpose 前缀 + 新 AK 公钥指纹（须 64 位小写 hex）。"""
    if not _ROOT_SEAL_FP_RE.match(new_fp):
        raise ValueError("new_fp 须为 64 位小写 hex")
    return "{}|new_fp:{:04d}:{}".format(
        ROOT_REPIN_PURPOSE, len(new_fp.encode("utf-8")), new_fp).encode("utf-8")


def root_repin_sign(priv, new_fp: str) -> str:
    """RK 私钥对 repin:<new_fp> 签名，返回 base64。"""
    return base64.b64encode(sign(priv, root_repin_message(new_fp))).decode("ascii")


def root_repin_verify(pub, new_fp: str, sig_b64: str) -> bool:
    """RK 公钥验重钉授权签名。返回 bool。"""
    try:
        sig = base64.b64decode(sig_b64, validate=True)
        msg = root_repin_message(new_fp)
    except Exception:
        return False
    return verify(pub, msg, sig)


# ----------------------------------------------------------------------------
# RK 轮换授权（v2.27.33，DSH §2.5 N-2）：根信任公钥 RK 自身的轮换此前在 CLI 层无授权路径
# （重装同一把即报「空指纹不符」，换新 RK 直接硬拒且 clobber RK_pub 文件 → 自我 DoS）。
# 现补齐「旧 RK 私钥签名授权新 RK」路径：root-rotate:<新RK_fp>，由**当前** RK 私钥签署、
# 经**当前** RK_pub（与 CONTRACT.md 钉固核对后）验签。
# ----------------------------------------------------------------------------
ROOT_ROTATE_PURPOSE = "METACOG-ROOT-ROTATE-v1"


def root_rotate_message(new_fp: str) -> bytes:
    """RK 轮换授权消息：绑定 purpose 前缀 + 新 RK 公钥指纹（须 64 位小写 hex）。"""
    if not _ROOT_SEAL_FP_RE.match(new_fp):
        raise ValueError("new_fp 须为 64 位小写 hex")
    return "{}|new_fp:{:04d}:{}".format(
        ROOT_ROTATE_PURPOSE, len(new_fp.encode("utf-8")), new_fp).encode("utf-8")


def root_rotate_sign(priv, new_fp: str) -> str:
    """当前 RK 私钥对 root-rotate:<new_fp> 签名，返回 base64。"""
    return base64.b64encode(sign(priv, root_rotate_message(new_fp))).decode("ascii")


def root_rotate_verify(pub, new_fp: str, sig_b64: str) -> bool:
    """当前 RK 公钥验 RK 轮换授权签名。返回 bool。"""
    try:
        sig = base64.b64decode(sig_b64, validate=True)
        msg = root_rotate_message(new_fp)
    except Exception:
        return False
    return verify(pub, msg, sig)


def anchor_pubkey_sha256(pub_pem: str) -> str:
    """C-1 钉固闸门（v2.27.22，①）：attestation 公钥指纹 = SHA-256(序列化公钥 PEM 去空白)。

    用途：公钥钉入 CONTRACT.md 后，`anchor_attest_verify` 加载树外公钥须与本指纹一致，
    否则 fail-closed。攻击者替换树外公钥 + attestation 双文件时，因公钥指纹不匹配钉固值，
    本闸门必拒（闭环审计主发现：同用户替换 pubkey+attestation 双文件伪造）。
    指纹以「序列化公钥 PEM 去空白」为输入——与 verify 实际读取的字节一致。"""
    return hashlib.sha256(pub_pem.strip().encode("utf-8")).hexdigest()


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
    # v2.27.17：v2 长度前缀格式 + nonce 往返；恶意 value 含分隔符不再产生歧义
    n = new_nonce()
    m2 = approval_message("P-1|EVIL", content_hash_of('{"id":"P-1"}'), trial_from_index=7, nonce=n)
    assert b"METACOG-HUMAN-APPROVAL-v2" in m2 and b"id:0008:P-1|EVIL" in m2
    assert verify(pub, m2, sign(priv, m2)), "v2 格式签名往返应成功"
    assert not verify(pub, approval_message("P-1|EVIL", content_hash_of('{"id":"P-1"}'), trial_from_index=7, nonce="ff"), sign(priv, m2)), "nonce 不同应验签失败"
    # v2.27.20（N-4 收口）：长度前缀 = UTF-8 字节数（非码点数）——非 ASCII 字段值实测
    m_zh = approval_message("提案-中文-ID", content_hash_of('{"id":"x"}'))
    # "提案-中文-ID" = 提(3)+案(3)+-(1)+中(3)+文(3)+-(1)+I(1)+D(1) = 16 字节（码点数 7 会错标 0007）
    assert "id:0016:提案-中文-ID".encode("utf-8") in m_zh, "长度前缀应为 UTF-8 字节数 0016"
    assert verify(pub, m_zh, sign(priv, m_zh)), "非 ASCII 字段 v2 往返应成功"
    # 旧格式构造器仍可用（验签回退路径）
    m_legacy = approval_message_legacy("P-1", content_hash_of('{"id":"P-1"}'))
    assert verify(pub, m_legacy, sign(priv, m_legacy)), "legacy 构造器往返应成功"
    print("  v2 长度前缀 + nonce / legacy 回退 OK")
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
    # v2.27.21（C-1 阶段1）：锚状态 attestation 原语——离线私钥签 / 公钥验
    commits = {"integrity": "a" * 64, "applies": "b" * 64, "sig_claims": "c" * 64}
    att = anchor_attest(priv, commits, at="20261025T0000")
    assert att.startswith("v1:20261025T0000:"), "attestation 格式应为 v1:{at}:{b64sig}"
    ok_a, reason_a = anchor_attest_verify(pub, commits, att)
    assert ok_a and reason_a is None, "attestation 验签应通过"
    bad_commits = dict(commits, applies="d" * 64)
    ok_b, reason_b = anchor_attest_verify(pub, bad_commits, att)
    assert not ok_b and reason_b == "attest-mismatch", "commitment 被篡改应失配"
    ok_c, reason_c = anchor_attest_verify(pub, commits, "v1:20261025T0000:!!!notb64")
    assert not ok_c and reason_c == "attest-malformed", "畸形 attestation 应拒"
    try:
        anchor_attestation_message(commits, at="2026-10-25T00:00")
        raise AssertionError("含冒号 at 应 ValueError（破坏定界）")
    except ValueError:
        pass
    try:
        anchor_attestation_message({"evil": "x" * 64})
        raise AssertionError("白名单外字段应 ValueError")
    except ValueError:
        pass
    # v2.27.22（C-1 ①）：公钥指纹钉固闸门原语——同公钥恒同指纹、异公钥必异
    pem = serialize_pub(pub)
    assert anchor_pubkey_sha256(pem) == anchor_pubkey_sha256(pem.strip()), "去空白不影响指纹"
    assert anchor_pubkey_sha256(pem) != anchor_pubkey_sha256(serialize_pub(priv2)), "异公钥指纹必异"
    print("  公钥指纹钉固原语 OK")
    print("  锚状态 attestation（离线私钥签/公钥验）OK")
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
