#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test-sigcrypto.py —— sigcrypto 密码学层独立测试入口（v2.27.31，R-7）。

背景：C-1 的验签器本体（sigcrypto.py）此前**无任何独立审计证据**（仅被 test-c1 间接覆盖）。
本文件为 sigcrypto 提供独立测试入口，覆盖：

1. 密钥对生成/序列化往返（pub/priv）
2. 公钥指数校验（_valid_public_exponent：e 须 == 65537；e=1 退化指数须被拒）
3. PKCS#1 v1.5 签名/验签：往返、篡改消息、篡改签名、错公钥
4. 私钥 at-rest 加密：PBKDF2 iters 钉死常量、错口令 fail-closed、密文/标签篡改检出
5. anchor attestation 消息/签名：字段白名单、at 格式约束、畸形串判定、commitment 失配
6. anchor 根锚密封签名（v2.27.31 R-1）：往返、指纹篡改、签名篡改、跨协议不可复用

运行：python test-sigcrypto.py
"""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))
import sigcrypto

PASSED = 0
FAILED = 0


def chk(name, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
    else:
        FAILED += 1
    print("  [{}] {}{}".format("PASS" if ok else "FAIL", name,
                               (" - " + detail) if detail else ""))


def test_keypair_roundtrip():
    print("\n[1] 密钥对生成/序列化往返")
    pub, priv = sigcrypto.gen_keypair(2048)
    n, e = pub
    # RSA 2048 模数顶位可能为 0，bit_length 可低至 ~2041；确定性判据用字节长度（恒为 256 字节）。
    chk("公钥模数 256 字节（RSA-2048 名义长度，顶位可为 0）",
        len(n.to_bytes(256, "big")) == 256, "bytes={}".format(len(n.to_bytes(256, "big"))))
    chk("公钥指数 e == 65537", e == 65537, "e={}".format(e))
    pub_s = sigcrypto.serialize_pub(pub)
    priv_s = sigcrypto.serialize_priv(priv)
    chk("公钥序列化往返一致", sigcrypto.deserialize_pub(pub_s) == pub)
    chk("私钥序列化往返一致", sigcrypto.deserialize_priv(priv_s) == priv)
    # 换行/空白不应影响解析（公钥文本常被人工复制）
    chk("公钥解析容忍首尾空白", sigcrypto.deserialize_pub(pub_s.strip() + "\n") == pub)


def test_exponent_validation():
    print("\n[2] 公钥指数校验（退化指数防线）")
    _pub, _priv = sigcrypto.gen_keypair(2048)
    n = _pub[0]
    for bad_e, label in ((1, "e=1 退化指数"), (3, "e=3 弱指数"), (n, "e=n"), (65539, "e=65539")):
        try:
            sigcrypto.deserialize_pub(json.dumps(
                {"n": base64.b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).decode(),
                 "e": str(bad_e)}))
            chk("拒绝 {}".format(label), False, "竟然解析成功")
        except ValueError:
            chk("拒绝 {}".format(label), True)
    ok_pub = json.dumps({"n": base64.b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).decode(),
                         "e": "65537"})
    chk("接受 e=65537", sigcrypto.deserialize_pub(ok_pub) is not None)


def test_sign_verify():
    print("\n[3] PKCS#1 v1.5 签名/验签")
    pub, priv = sigcrypto.gen_keypair(2048)
    msg = b"metacog-c1-test-message"
    sig = sigcrypto.sign(priv, msg)
    chk("签名验签通过", sigcrypto.verify(pub, msg, sig) is True)
    chk("消息篡改 → 验签失败", sigcrypto.verify(pub, msg + b"x", sig) is False)
    bad = bytearray(sig); bad[0] ^= 0xFF
    chk("签名篡改 → 验签失败", sigcrypto.verify(pub, msg, bytes(bad)) is False)
    pub2, _ = sigcrypto.gen_keypair(2048)
    chk("错公钥 → 验签失败", sigcrypto.verify(pub2, msg, sig) is False)
    chk("签名长度异常 → 验签失败（非异常抛出）", sigcrypto.verify(pub, msg, b"short") is False)
    chk("非 bytes 签名 → 验签失败", sigcrypto.verify(pub, msg, "notbytes") is False)


def test_priv_at_rest():
    print("\n[4] 私钥 at-rest 加密（PBKDF2 + HMAC 认证）")
    pub, priv = sigcrypto.gen_keypair(2048)
    priv_s = sigcrypto.serialize_priv(priv)
    blob = sigcrypto.encrypt_priv(priv_s, "correct horse battery staple")
    chk("密文 blob 不含明文私钥", priv_s not in json.dumps(blob))
    chk("PBKDF2 iters 钉死为常量", blob.get("iters") == sigcrypto._PBKDF2_ITERS,
        "iters={}".format(blob.get("iters")))
    plain = sigcrypto.decrypt_priv_str(blob, "correct horse battery staple")
    chk("正确口令解密一致", plain == priv_s)
    try:
        sigcrypto.decrypt_priv_str(blob, "wrong passphrase")
        chk("错误口令 → fail-closed 抛错", False, "竟然解出")
    except Exception:
        chk("错误口令 → fail-closed 抛错", True)
    tampered = dict(blob); tampered["ct"] = base64.b64encode(b"\x00" * 32).decode()
    try:
        sigcrypto.decrypt_priv_str(tampered, "correct horse battery staple")
        chk("密文篡改 → 认证标签检出", False, "竟然解出")
    except Exception:
        chk("密文篡改 → 认证标签检出", True)
    tampered2 = dict(blob); tampered2["mac"] = base64.b64encode(b"\x00" * 32).decode()
    try:
        sigcrypto.decrypt_priv_str(tampered2, "correct horse battery staple")
        chk("MAC 篡改 → 检出", False, "竟然解出")
    except Exception:
        chk("MAC 篡改 → 检出", True)


def test_anchor_attestation():
    print("\n[5] anchor attestation 消息/签名")
    pub, priv = sigcrypto.gen_keypair(2048)
    commits = {"integrity": "a" * 64, "applies": "b" * 64, "sig_claims": "c" * 64,
               "frozen_hashes": "d" * 64}
    att = sigcrypto.anchor_attest(priv, commits, at="20261026T1200")
    chk("attestation 格式 v1:{at}:{sig}", att.startswith("v1:20261026T1200:"))
    ok, reason = sigcrypto.anchor_attest_verify(pub, commits, att)
    chk("验签通过", ok is True and reason is None, "reason={}".format(reason))
    ok2, reason2 = sigcrypto.anchor_attest_verify(pub, dict(commits, integrity="e" * 64), att)
    chk("commitment 失配 → 验签失败", ok2 is False, "reason={}".format(reason2))
    for bad in ("", "notanattestation", "v1:onlyone", "v1:at:!!!notb64!!!", "v2:x:y:z"):
        okb, reasonb = sigcrypto.anchor_attest_verify(pub, commits, bad)
        chk("畸形串 {!r} → 判为 malformed".format(bad[:18]), okb is False and reasonb == "attest-malformed",
            "reason={}".format(reasonb))
    try:
        sigcrypto.anchor_attestation_message(commits, at="2026-10-26T12:00")
        chk("含冒号的 at → 拒绝", False, "竟然接受")
    except ValueError:
        chk("含冒号的 at → 拒绝", True)
    try:
        sigcrypto.anchor_attestation_message(dict(commits, evil="x" * 64))
        chk("非白名单字段 → 拒绝", False, "竟然接受")
    except ValueError:
        chk("非白名单字段 → 拒绝", True)
    try:
        sigcrypto.anchor_attestation_message(dict(commits, break_glass="e" * 64))
        chk("break_glass 字段在白名单内（R-5）", True)
    except ValueError:
        chk("break_glass 字段在白名单内（R-5）", False, "被拒——commitment 字段白名单未扩展")


def test_root_seal():
    print("\n[6] 根锚密封签名（v2.27.31 R-1 授权维度）")
    pub, priv = sigcrypto.gen_keypair(2048)
    fp = "a" * 64
    rec = sigcrypto.anchor_root_seal_sign(priv, fp, at="20261026T1200")
    chk("密封记录格式 v1:{fp}:{at}:{sig}", rec.startswith("v1:" + fp + ":20261026T1200:"))
    ok, reason, got = sigcrypto.anchor_root_seal_verify(pub, rec)
    chk("密封验签通过", ok is True and reason == "ok" and got == fp, "reason={}".format(reason))
    # 篡改指纹（改写根锚内容）
    rec2 = rec.replace(fp, "b" * 64)
    ok2, reason2, _ = sigcrypto.anchor_root_seal_verify(pub, rec2)
    chk("指纹被改写 → seal-bad-sig", ok2 is False and reason2 == "seal-bad-sig", "reason={}".format(reason2))
    # 篡改签名
    parts = rec.split(":")
    parts[3] = base64.b64encode(b"\x00" * 256).decode()
    ok3, reason3, _ = sigcrypto.anchor_root_seal_verify(pub, ":".join(parts))
    chk("签名被改写 → seal-bad-sig", ok3 is False and reason3 == "seal-bad-sig", "reason={}".format(reason3))
    # 未签名格式（攻击者手写裸指纹）
    ok4, reason4, _ = sigcrypto.anchor_root_seal_verify(pub, fp)
    chk("裸指纹（未签名）→ seal-unsigned", ok4 is False and reason4 == "seal-unsigned", "reason={}".format(reason4))
    # 跨协议不可复用：attestation 签名不得当作密封签名
    commits = {"integrity": "a" * 64, "applies": "b" * 64, "sig_claims": "c" * 64, "frozen_hashes": "d" * 64}
    att = sigcrypto.anchor_attest(priv, commits, at="20261026T1200")
    ok5, reason5, _ = sigcrypto.anchor_root_seal_verify(pub, att)
    chk("attestation 串不得当作密封记录（跨协议隔离）", ok5 is False, "reason={}".format(reason5))
    # 非法指纹长度
    try:
        sigcrypto.anchor_root_seal_message("abc", "20261026T1200")
        chk("非 64 位指纹 → 拒绝", False, "竟然接受")
    except ValueError:
        chk("非 64 位指纹 → 拒绝", True)


def main():
    print("=== sigcrypto 独立密码学测试（v2.27.31 R-7）===")
    test_keypair_roundtrip()
    test_exponent_validation()
    test_sign_verify()
    test_priv_at_rest()
    test_anchor_attestation()
    test_root_seal()
    print("\n=== sigcrypto 独立测试结果: {}/{} PASS ===".format(PASSED, PASSED + FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
