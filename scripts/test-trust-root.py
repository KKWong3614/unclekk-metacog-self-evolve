#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.7.0 外部锚（破 C-1 逻辑层：离线 RSA 根）+ N1 + N2' 测试套件。

覆盖：
- trust_root 抽象：legacy 恒 pass；hsm 设备证明（缺/伪造公钥/伪造签名/合法，均由离线根私钥签名，
  Agent 仅持公钥验签）；oob 带外签名令牌 fail-closed；hsm+oob；工厂（含 corrupt/未知 backend/
  无 verifier → 恒拒 DenyTrustRoot）；契约指纹交叉核对（防止套用不同契约）。
- RSA 根验证方隔离：不同密钥无法互相伪造签名；模块不含硬编码密钥；Agent 验证方 sign() 被禁。
- metacog 集成：check_pubkey_root 默认（legacy）行为同 v2.5.8；启用 hsm/oob/hsm+oob 后外部锚成
  权威根 + fail-closed；corrupt 配置 → fail-closed（HIGH-3）；CONTRACT.md 指纹降级为次要交叉核对。
- N1：离线授权文件为符号链接 → keygen 拒（fail-closed）。
- N2'：D4 哈希链。

纪律：纯 stdlib；不依赖真实硬件令牌（真机须 TokenKeyProvider 桩，verify 恒 False → fail-closed）。
离线根私钥在测试中以变量持有仅用于**离线签名模拟**；生产部署私钥须由人类离线保管、严禁落盘。
"""

import io
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

import shutil
import sys
import json
import stat
import base64
import hmac
import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))
import metacog
import trust_root
import sigcrypto

# v2.8.1 C-9：全局允许默认（源码内嵌共享）锚密钥用于测试（本地开发显式承担风险）。
# 生产/非本地部署须以 METACOG_TRUST_ROOT_ANCHOR_KEY 覆盖；C-9 拒绝测试会临时撤销本项。
_os.environ["METACOG_TRUST_ROOT_ALLOW_DEFAULT"] = "1"

# v2.8.2 C-11：全局允许 legacy（无外部锚）回落（部署契约逃生舱），使既有 legacy 测试不误伤。
# 生产/非本地部署须显式启用外部锚或保留默认 deny；test_c11_default_failclosed_and_optout 会临时撤销本项验证默认 deny。
_os.environ["METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"] = "1"


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def add(self, name, ok, detail=""):
        self.passed += ok
        self.failed += (not ok)
        print("  [{}] {}{}".format("PASS" if ok else "FAIL", name,
                                    " - " + detail if detail else ""))

    def summary(self):
        total = self.passed + self.failed
        print("\n" + "=" * 60)
        print("v2.7.0 外部锚/N1/N2' 测试: {}/{} PASS".format(self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _new_store_inited():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_tr_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    return st, tmp


def _keygen_ns(tmp):
    nonce = Path(tmp) / "keygen_nonce.txt"
    nonce.write_text("offline-auth-nonce-9f3c2a7b", encoding="utf-8")
    return SimpleNamespace(keygen=True, init=False, approve=False, id=None,
                           nonce_file=str(nonce),
                           enable_external=None, root_pubkey=None,
                           attestation_path=None, oob_token_dir=None)


def _with_tty_and_passphrase(pw):
    old_tty, old_gp = metacog._require_tty, metacog.getpass.getpass
    old_in = metacog.builtins.input
    metacog._require_tty = lambda: True
    metacog.getpass.getpass = lambda prompt="": pw
    metacog.builtins.input = lambda prompt="": "YES"
    def restore():
        metacog._require_tty = old_tty
        metacog.getpass.getpass = old_gp
        metacog.builtins.input = old_in
    return restore


def _run(fn, *a):
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = fn(*a)
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


def _offline_root():
    """生成离线根密钥对（模拟人类离线一次性生成）；返回 (pub_serialized, priv_serialized)。"""
    return trust_root.gen_offline_root_keypair()


def _write_signed_oob_token(oobd, ch, priv_off):
    """模拟人类离线对挑战签名，写入 base64 令牌文件。"""
    sig = trust_root.sign_oob_token(ch, priv_off)
    Path(oobd, ch + ".token").write_text(base64.b64encode(sig).decode("ascii"), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. trust_root 抽象单测（v2.7.0 离线根）
# ---------------------------------------------------------------------------

def test_trust_root_abstraction():
    r = T()
    pub = '{"n":"SIM_PUB","e":65537}'
    pub_off, priv_off = _offline_root()
    verifier = trust_root.RsaRootVerifierProvider(pub_off)
    # legacy 恒 pass
    r.add("legacy attestation no-op", trust_root.TrustRoot().attestation_ok(pub) == (True, None))
    r.add("legacy oob no-op", trust_root.TrustRoot().oob_confirmed("x") is True)

    # hsm：离线根签名的设备证明（Agent 仅验签，无私钥无法自造）
    td = Path(tempfile.mkdtemp(prefix="tr_hsm_"))
    try:
        att = str(td / "attest.json")
        hsm = trust_root.HsmTrustRoot(att, verifier)
        ok, reason = hsm.attestation_ok(pub)
        r.add("hsm missing attestation fail-closed", (ok is False and reason == "no-device-attestation"))
        # 伪造证明（提交公钥不符）
        trust_root.write_root_attestation(att, "WRONG", "cf", priv_off)
        ok2, reason2 = hsm.attestation_ok(pub)
        r.add("hsm forged pubkey mismatch", (ok2 is False and reason2 == "attestation-pubkey-mismatch"))
        # 合法证明（离线私钥签名）+ 契约指纹一致
        trust_root.write_root_attestation(att, pub, "cf", priv_off)
        ok3, reason3 = hsm.attestation_ok(pub, contract_fingerprint="cf")
        r.add("hsm valid attestation pass", (ok3 is True and reason3 is None))
        # 用不同私钥伪造签名 → 拒绝（Agent 无私钥无法自造有效证明）
        _, priv_other = _offline_root()
        trust_root.write_root_attestation(att, pub, "cf", priv_other)
        ok4, reason4 = hsm.attestation_ok(pub, contract_fingerprint="cf")
        r.add("hsm forged signature (wrong key) fail-closed",
              (ok4 is False and reason4 == "attestation-forged"))
    finally:
        shutil.rmtree(td, ignore_errors=True)

    # oob：缺令牌 → fail-closed；放签名令牌 → 通过；无密钥伪造令牌 → 仍 fail-closed（N1 闭环）
    td2 = Path(tempfile.mkdtemp(prefix="tr_oob_"))
    try:
        oobd = str(td2 / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        oob = trust_root.OobTrustRoot(oobd, verifier)
        ch = oob.challenge_for(pub)
        r.add("oob requires token", oob.oob_token_required() is True)
        r.add("oob missing token fail-closed", oob.oob_confirmed(ch) is False)
        _write_signed_oob_token(oobd, ch, priv_off)
        r.add("oob signed token pass", oob.oob_confirmed(ch) is True)
        # N1 闭环：攻击者无私钥，放无签名令牌 → fail-closed
        ch2 = oob.challenge_for(pub)
        Path(oobd, ch2 + ".token").write_text(ch2, encoding="utf-8")  # 无签名
        r.add("oob no-signature token fail-closed (N1 closed)", oob.oob_confirmed(ch2) is False)
        # N1 闭环：错签名（不同私钥）
        ch3 = oob.challenge_for(pub)
        _, priv_other = _offline_root()
        Path(oobd, ch3 + ".token").write_text(
            base64.b64encode(trust_root.sign_oob_token(ch3, priv_other)).decode("ascii"), encoding="utf-8")
        r.add("oob wrong-key signature fail-closed (N1 closed)", oob.oob_confirmed(ch3) is False)
    finally:
        shutil.rmtree(td2, ignore_errors=True)

    # TokenKeyProvider 桩：verify 恒 False（HIGH-2 诚实不可达）
    tk = trust_root.TokenKeyProvider()
    r.add("token stub verify fails closed", tk.verify(pub, b"x") is False)
    try:
        tk.sign(pub)
        r.add("token stub sign raises", False)
    except NotImplementedError:
        r.add("token stub sign raises", True)

    # 工厂：legacy → None；hsm+root_pubkey → hsm（genuine）；hsm+oob+root_pubkey → hsm+oob；
    #       hsm 无 verifier → deny；oob 无 verifier → deny；corrupt → deny；未知 backend → deny；
    #       disabled → None
    r.add("factory legacy default → None",
          trust_root.build_trust_root(trust_root.TrustRootConfig()) is None)
    r.add("factory hsm + root_pubkey → hsm (genuine offline root)",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              enabled=True, backend="hsm", attestation_path="x",
              root_pubkey=pub_off)).name == "hsm")
    r.add("factory hsm+oob + root_pubkey → hsm+oob",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              enabled=True, backend="hsm+oob", attestation_path="x", oob_token_dir="y",
              root_pubkey=pub_off)).name == "hsm+oob")
    r.add("factory hsm w/o verifier → deny (external-anchor-no-verifier)",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              enabled=True, backend="hsm", attestation_path="x")).name == "deny")
    r.add("factory oob w/o verifier → deny (external-anchor-oob-no-verifier)",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              enabled=True, backend="oob", oob_token_dir="y")).name == "deny")
    r.add("factory corrupt → deny (HIGH-3)",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              corrupt=True, enabled=True, backend="hsm")).name == "deny")
    r.add("factory unknown backend → deny",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              enabled=True, backend="weird")).name == "deny")
    r.add("factory disabled → None",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              enabled=False, backend="hsm")) is None)
    return r


def test_rsa_root_verifier_isolation():
    """HIGH-1 回归（v2.7.0）：不同离线根密钥无法互相伪造签名；模块不含硬编码密钥；
    Agent 持有的 RsaRootVerifierProvider 不具签名能力（sign 必须 NotImplementedError）。"""
    r = T()
    pub = '{"n":"P","e":65537}'
    pub_a, priv_a = _offline_root()
    pub_b, priv_b = _offline_root()
    ver_a = trust_root.RsaRootVerifierProvider(pub_a)
    ver_b = trust_root.RsaRootVerifierProvider(pub_b)
    msg = b"ROOT-ATTEST|x|y|z"
    sig_a = sigcrypto.sign(sigcrypto.deserialize_priv(priv_a), msg)
    r.add("ver_a verifies its own signature", ver_a.verify(msg, sig_a) is True)
    r.add("ver_b cannot verify ver_a's signature", ver_b.verify(msg, sig_a) is False)
    # Agent 验证方 sign() 被禁（防自造证明）
    try:
        ver_a.sign(msg)
        r.add("verifier.sign raises (Agent 无签名能力)", False)
    except NotImplementedError:
        r.add("verifier.sign raises (Agent 无签名能力)", True)
    # 模块内不应再有任何模块级硬编码密钥常量（静态审计点）
    r.add("模块不含硬编码设备证明密钥常量",
          not hasattr(trust_root, "_SIM_DEVICE_ATTEST_KEY"))
    return r


# ---------------------------------------------------------------------------
# 2. metacog 集成：check_pubkey_root 外部锚门
# ---------------------------------------------------------------------------

def _enable_external(st, tmp, backend, att=None, oob=None, root_pubkey=None, root_privkey=None):
    cfg = {"enabled": True, "backend": backend}
    if att:
        cfg["attestation_path"] = att
    if oob:
        cfg["oob_token_dir"] = oob
    if root_pubkey is not None:
        cfg["root_pubkey"] = root_pubkey
    # v2.8.0 C-1 闭合：信任根配置须带内嵌锚密钥签名（与 write_trust_root_config 一致），加载时校验
    cfg["_sig"] = trust_root.sign_trust_root_config(cfg, trust_root.get_anchor_key())
    (st.root / "ledger" / "trust-root.json").write_text(json.dumps(cfg), encoding="utf-8")
    # v2.6.3 M-1：与 write_trust_root_config 一致，写启用标记 sentinel
    (st.root / "ledger" / ".external-anchor-enabled").write_text(
        json.dumps({"backend": backend}), encoding="utf-8")
    # v2.7.4：记录外部(Agent 无写权限)基线，钉固 root_pubkey + 可选离线根签名（NEW-H1 闭合）；
    # 使删除/篡改/一致化改写检出(HIGH-1/2/3/MEDIUM-1/NEW-H1)生效。
    st.record_external_anchor_integrity(root_pubkey=root_pubkey, root_privkey=root_privkey)
    return root_pubkey


def test_check_pubkey_root_default_legacy():
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    try:
        rc, _ = _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        r.add("keygen ok (rc=0)", rc == 0)
        ok, reason = st.check_pubkey_root()
        r.add("default legacy pass (行为同 v2.5.8)", ok is True and reason is None)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_check_pubkey_root_hsm_valid():
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        att = str(tmp / "attest.json")
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        pinned = st.pinned_human_pubkey_fingerprint()
        _enable_external(st, tmp, "hsm+oob", att=att, oob=oobd, root_pubkey=pub_off)
        # 离线根签名设备证明（人类离线执行，此处模拟）
        trust_root.write_root_attestation(att, pub_serialized, pinned, priv_off)
        # 离线根签名带外令牌
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok, reason = st.check_pubkey_root()
        r.add("hsm+oob 离线根证明 + 签名令牌 → 外部锚通过",
              ok is True and reason is None)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_check_pubkey_root_hsm_missing_attestation():
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        att = str(tmp / "attest.json")  # 故意不写证明文件
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        pinned = st.pinned_human_pubkey_fingerprint()
        _enable_external(st, tmp, "hsm+oob", att=att, oob=oobd, root_pubkey=pub_off)
        # 带外令牌就绪，确保失败来自 attestation 缺失而非 oob 闸门
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok, reason = st.check_pubkey_root()
        r.add("hsm+oob missing attestation → fail-closed",
              ok is False and reason == "external-anchor-no-device-attestation")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_check_pubkey_root_hsm_forged_attestation():
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        att = str(tmp / "attest.json")
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        pinned = st.pinned_human_pubkey_fingerprint()
        _enable_external(st, tmp, "hsm+oob", att=att, oob=oobd, root_pubkey=pub_off)
        # 证明文件覆盖错误公钥 → 伪造（攻击者无离线私钥，无法签合法证明）
        trust_root.write_root_attestation(att, "TAMPERED", pinned, priv_off)
        # 带外令牌就绪，确保失败来自 attestation 伪造而非 oob 闸门
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok, reason = st.check_pubkey_root()
        r.add("hsm+oob forged attestation → fail-closed (C-1 破：自举无法伪造证明)",
              ok is False and reason == "external-anchor-attestation-pubkey-mismatch")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_check_pubkey_root_oob_failclosed_and_pass():
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off)
        # 缺令牌 → fail-closed
        ok1, reason1 = st.check_pubkey_root()
        r.add("oob missing token → fail-closed", ok1 is False and reason1 == "oob-confirmation-required")
        # 放签名令牌 → 通过
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok2, reason2 = st.check_pubkey_root()
        r.add("oob present signed token → 外部锚通过", ok2 is True and reason2 is None)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_check_pubkey_root_corrupt_config_failclosed():
    """HIGH-3：配置损坏 / 未知 backend → fail-closed（绝不静默回落 legacy）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        # 情形 A：配置文件非法 JSON（解析失败）
        (st.root / "ledger" / "trust-root.json").write_text(
            "{ this is not json", encoding="utf-8")
        ok_a, reason_a = st.check_pubkey_root()
        r.add("corrupt JSON → fail-closed (HIGH-3)", ok_a is False)
        # 情形 B：合法 JSON 但未知 backend
        (st.root / "ledger" / "trust-root.json").write_text(
            json.dumps({"enabled": True, "backend": "weird"}), encoding="utf-8")
        ok_b, reason_b = st.check_pubkey_root()
        r.add("unknown backend → fail-closed (HIGH-3)", ok_b is False)
        # 对照：攻击者即使重写 human-guard + CONTRACT.md，外部锚仍拒（不回落 legacy 钉固）
        g = json.loads(st.human_guard.read_text(encoding="utf-8"))
        g["pubkey"] = '{"n":"ATTACKER","e":65537}'
        st.human_guard.write_text(json.dumps(g), encoding="utf-8")
        ok_c, _ = st.check_pubkey_root()
        r.add("corrupt-config 下篡改 human-guard 仍 fail-closed", ok_c is False)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


# ---------------------------------------------------------------------------
# 3. N1：离线授权文件符号链接 → keygen 拒
# ---------------------------------------------------------------------------

def test_n1_nonce_symlink_rejected():
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    # monkeypatch is_symlink 为 True（无需真实创建 symlink，规避 Windows 权限限制）
    old_islink = metacog.Path.is_symlink
    metacog.Path.is_symlink = lambda self: True
    try:
        ns = _keygen_ns(tmp)
        rc, out = _run(metacog.cmd_confirm, st, ns)
        r.add("N1 symlink nonce → keygen rc=2 (fail-closed)", rc == 2)
        r.add("N1 报错含 N1 标识", "N1" in out)
    finally:
        metacog.Path.is_symlink = old_islink
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


# ---------------------------------------------------------------------------
# 4. N2'：D4 哈希链
# ---------------------------------------------------------------------------

def test_n2_hash_chain():
    r = T()
    st, tmp = _new_store_inited()
    try:
        st.record_apply("P-N2", 0, "M1", "e1", "somesig", "somehash")
        r.add("applies_integrity_ok 初态 True", st.applies_integrity_ok() is True)
        ap = st.applies
        ap.write_text(ap.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        r.add("篡改 applies → applies_integrity_ok False", st.applies_integrity_ok() is False)
        st.record_apply("P-N2", 0, "M1", "e1", "somesig2", "somehash2")
        r.add("重建基线后 applies_integrity_ok True", st.applies_integrity_ok() is True)
        chain = st.root / "ledger" / "integrity-chain" / "chain.jsonl"
        lines = [l for l in chain.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(lines) >= 2:
            broken = "\n".join(lines[1:]) + "\n"
            chain.write_text(broken, encoding="utf-8")
            st.record_integrity(st.APPLIES_INTEGRITY_KEY)
            r.add("断链 → applies_integrity_ok False (链不连续)", st.applies_integrity_ok() is False)
        else:
            r.add("断链测试跳过(链过短)", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_symlink_defense():
    """MEDIUM-1：外部锚新引入的 attestation_path / oob_token_dir 均须非 symlink（防重放指向 Agent 可控路径）。"""
    r = T()
    pub = '{"n":"SIM_PUB","e":65537}'
    pub_off, priv_off = _offline_root()
    verifier = trust_root.RsaRootVerifierProvider(pub_off)
    td = Path(tempfile.mkdtemp(prefix="tr_sym_"))
    old_islink = trust_root.Path.is_symlink
    try:
        att = str(td / "attest.json")
        trust_root.write_root_attestation(att, pub, "cf", priv_off)
        hsm = trust_root.HsmTrustRoot(att, verifier)
        # 正常（真实路径）→ 通过
        r.add("hsm valid attestation (real path) pass",
              hsm.attestation_ok(pub, contract_fingerprint="cf") == (True, None))
        # 模拟 attestation_path 为 symlink → fail-closed
        trust_root.Path.is_symlink = lambda self: True
        try:
            r.add("hsm symlink attestation → fail-closed",
                  hsm.attestation_ok(pub, contract_fingerprint="cf") == (False, "attestation-symlink"))
        finally:
            trust_root.Path.is_symlink = old_islink
        # oob_token_dir symlink → fail-closed（需重新放令牌，避免被前次消费干扰）
        oobd = str(td / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        oob = trust_root.OobTrustRoot(oobd, verifier)
        ch = oob.challenge_for(pub)
        _write_signed_oob_token(oobd, ch, priv_off)
        r.add("oob real path signed token pass", oob.oob_confirmed(ch) is True)
        trust_root.Path.is_symlink = lambda self: True
        try:
            _write_signed_oob_token(oobd, ch, priv_off)
            r.add("oob symlink token_dir → fail-closed", oob.oob_confirmed(ch) is False)
        finally:
            trust_root.Path.is_symlink = old_islink
    finally:
        trust_root.Path.is_symlink = old_islink
        shutil.rmtree(td, ignore_errors=True)
    return r


def test_oob_token_content_and_consume():
    """MEDIUM-2 + LOW-1（闭环 N1）：oob 令牌须为挑战串的离线根签名；确认后一次性消费（防重放）。"""
    r = T()
    pub = '{"n":"P","e":65537}'
    pub_off, priv_off = _offline_root()
    verifier = trust_root.RsaRootVerifierProvider(pub_off)
    td = Path(tempfile.mkdtemp(prefix="tr_oobc_"))
    try:
        oobd = str(td / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        oob = trust_root.OobTrustRoot(oobd, verifier)
        ch = oob.challenge_for(pub)
        # 无签名 / 错内容 → fail-closed（且不消费）
        Path(oobd, ch + ".token").write_text("wrong-content-not-signature", encoding="utf-8")
        r.add("oob wrong content (no signature) → fail-closed", oob.oob_confirmed(ch) is False)
        r.add("oob token not consumed on wrong content", Path(oobd, ch + ".token").exists() is True)
        # 正确签名令牌 → 通过，且令牌被消费为 .used
        _write_signed_oob_token(oobd, ch, priv_off)
        r.add("oob correct signed token → pass + consume", oob.oob_confirmed(ch) is True)
        r.add("oob token consumed (.used exists)", Path(oobd, ch + ".token.used").exists() is True)
        r.add("oob token file removed after consume", Path(oobd, ch + ".token").exists() is False)
        # 二次确认（令牌已消费）→ fail-closed（防重放）
        r.add("oob replay (no token) → fail-closed", oob.oob_confirmed(ch) is False)
    finally:
        shutil.rmtree(td, ignore_errors=True)
    return r


def test_enable_external_requires_root_pubkey():
    """v2.7.0：启用外部锚必须提供 --root-pubkey（离线根公钥）；缺 → rc=2 指路。
    提供后独立 hsm / oob / hsm+oob 均允许（离线根使独立 hsm 成为真外部锚）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    try:
        nonce = Path(tmp) / "keygen_nonce.txt"
        nonce.write_text("offline-auth-nonce-9f3c2a7b", encoding="utf-8")
        # 缺 root_pubkey → rc=2
        ns = SimpleNamespace(keygen=True, init=False, approve=False, id=None,
                             nonce_file=str(nonce),
                             enable_external="hsm+oob",
                             root_pubkey=None,
                             attestation_path=str(Path(tmp) / "attest.json"),
                             oob_token_dir=str(Path(tmp) / "oob"))
        rc, out = _run(metacog.cmd_confirm, st, ns)
        r.add("enable-external 缺 root-pubkey → rc=2", rc == 2)
        r.add("缺 root-pubkey 报错含指路", ("root-pubkey" in out or "root_pubkey" in out))
        r.add("缺 root-pubkey 未写入 trust-root.json",
              not (st.root / "ledger" / "trust-root.json").exists())
        # 提供 root_pubkey → 允许（独立 hsm，v2.7.0 真外部锚）
        pub_off, _ = _offline_root()
        ns2 = SimpleNamespace(keygen=True, init=False, approve=False, id=None,
                             nonce_file=str(nonce),
                             enable_external="hsm",
                             root_pubkey=pub_off,
                             attestation_path=str(Path(tmp) / "attest.json"),
                             oob_token_dir=None)
        rc2, _ = _run(metacog.cmd_confirm, st, ns2)
        r.add("enable-external hsm + root-pubkey → rc=0", rc2 == 0)
        cfg = trust_root.TrustRootConfig.load(st.root)
        r.add("hsm 配置已写入且 enabled", cfg.enabled is True and cfg.backend == "hsm")
        r.add("root_pubkey 已写入配置", bool(cfg.root_pubkey))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_deploy_contract_check():
    """P2：部署契约运行时检测 _is_protected（WARN-only，不 fail-closed）。"""
    r = T()
    td = Path(tempfile.mkdtemp(prefix="tr_dep_"))
    old_islink = trust_root.Path.is_symlink
    try:
        # 当前进程可写的临时目录 → 契约违反 → False
        r.add("writable temp dir → not protected (False)",
              trust_root._is_protected(str(td)) is False)
        # 不存在路径 → None（由 attestation_ok 另行 fail-closed）
        r.add("nonexistent path → None",
              trust_root._is_protected(str(td / "nope")) is None)
        # symlink → False
        trust_root.Path.is_symlink = lambda self: True
        try:
            r.add("symlink path → not protected (False)",
                  trust_root._is_protected(str(td / "x")) is False)
        finally:
            trust_root.Path.is_symlink = old_islink
    finally:
        trust_root.Path.is_symlink = old_islink
        shutil.rmtree(td, ignore_errors=True)
    return r


def test_deny_reason_subtype():
    """LOW：DenyTrustRoot 按触发路径细分 reason，便于运维与审计区分。"""
    r = T()
    pub = '{"n":"P","e":65537}'
    r.add("corrupt → external-anchor-corrupt",
          trust_root.build_trust_root(
              trust_root.TrustRootConfig(corrupt=True, enabled=True, backend="hsm")
          ).reason == "external-anchor-corrupt")
    r.add("unknown backend → external-anchor-unknown-backend",
          trust_root.build_trust_root(
              trust_root.TrustRootConfig(enabled=True, backend="weird")
          ).reason == "external-anchor-unknown-backend")
    r.add("hsm no verifier → external-anchor-no-verifier",
          trust_root.build_trust_root(
              trust_root.TrustRootConfig(enabled=True, backend="hsm", attestation_path="x")
          ).reason == "external-anchor-no-verifier")
    return r


def test_delete_config_fallback_legacy():
    """MEDIUM-5 / M-1（v2.6.3）+ v2.7.2 P1（N1 修复）：删除 trust-root.json（外部锚锚文件）的处理。
    - 仅删配置（sentinel 仍在）→ fail-closed（external-anchor-deleted）：基线在外部信任域仍检出锚缺失，
      外部锚不可被静默关掉（v2.7.2 起原因统一为 deleted 而非 corrupt，因锚文件确已缺失）。
    - 删配置 + 删 sentinel（完整去启用）→ v2.7.2 起仍 fail-closed（external-anchor-deleted）：
      外部基线(外部信任域)仍检出锚缺失，关闭 Hermes N1『删配置+基线(账本)』全删绕过；
      不再静默回退 legacy（C-1 重开）。彻底去启用须同时移除外部基线（由人类在外部信任域清理）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off)
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok1, _ = st.check_pubkey_root()
        r.add("oob enabled → 外部锚通过", ok1 is True)
        # 仅删 trust-root.json（sentinel 仍在）→ 外部基线检出锚缺失 → fail-closed
        (st.root / "ledger" / "trust-root.json").unlink()
        ok2, reason2 = st.check_pubkey_root()
        r.add("仅删配置(留sentinel) → fail-closed(防静默关锚)",
              ok2 is False and reason2 == "external-anchor-deleted")
        # 再删 sentinel（完整去启用）→ v2.7.2 仍 fail-closed（外部基线仍检出锚缺失，N1 修复）
        (st.root / "ledger" / ".external-anchor-enabled").unlink()
        ok3, reason3 = st.check_pubkey_root()
        r.add("删配置+sentinel → 仍 fail-closed(N1 修复，不再静默回退 legacy)",
              ok3 is False and reason3 == "external-anchor-deleted")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_attacker_swaps_root_pubkey():
    """v2.7.1（C-1 复验证伪后补）对抗测试：模拟 Hermes 2026-10-02 指出的 C-1 攻击——攻击者仅凭
    ledger 写权限换掉 root_pubkey 并自签设备证明，企图让 check_pubkey_root 通过。
    修复后：证明存储须位于 Agent 可写域(root)之外；攻击者只能把 attestation_path 指向可写域内路径
    → 结构性 fail-closed 闸门(anchor_storage_outside_root)拒绝 → check_pubkey_root 返回 False（C-1 攻击被阻断）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        pinned = st.pinned_human_pubkey_fingerprint()
        # 攻击者生成自己的 evil 密钥对（持 evil_priv → 可自签证明）
        evil_pub, evil_priv = _offline_root()
        # 攻击者把 attestation_path 指向可写域内（ledger 下），并自签 evil 证明（committed=live pub）
        att = str(st.root / "ledger" / "evil-attest.json")
        _enable_external(st, tmp, "hsm", att=att, root_pubkey=evil_pub)
        trust_root.write_root_attestation(att, pub_serialized, pinned, evil_priv)
        ok, reason = st.check_pubkey_root()
        r.add("攻击者换 root_pubkey+自签证明(证明存储位于可写域内) → fail-closed",
              ok is False and reason == "external-anchor-inside-writable-root")
        # 对照：若证明存储位于 root 之外（合规部署），同款攻击因无可写处放伪造证明而无法得逞
        # （由 testify_hsm_valid 等用例已覆盖：外部锚在合规部署下正常通过）。
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_deletion_failclosed():
    """v2.7.1 HIGH-1 + v2.7.2 P1（N1 修复）：外部锚建立(外部基线已记录)后被删 → check_pubkey_root
    fail-closed(external-anchor-deleted)，不再静默回退 legacy。v2.7.2 起基线存于外部
    (Agent 无写权限)信任域，攻击者即便删光 ledger 全部基线文件(integrity.json/链)也无法移除
    外部基线 → 仍 fail-closed（关闭 Hermes N1『删基线+锚』全删绕过）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        att = str(tmp / "attest.json")          # 合规：位于 root 之外
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        pinned = st.pinned_human_pubkey_fingerprint()
        _enable_external(st, tmp, "hsm+oob", att=att, oob=oobd, root_pubkey=pub_off)
        trust_root.write_root_attestation(att, pub_serialized, pinned, priv_off)
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok1, _ = st.check_pubkey_root()
        r.add("外部锚已建立 → 通过", ok1 is True)
        # 模拟 cmd_confirm --enable-external 成功后记录的外部(Agent 无写权限)固定基线
        st.record_external_anchor_integrity()
        r.add("外部基线已写入固定外部位置(v2.7.3 HIGH-3)",
              st.external_anchor_baseline_path is not None
              and st.external_anchor_baseline_path.exists())
        # 攻击者静默删除信任根文件（企图回退 legacy 打开 C-1）
        (st.root / "ledger" / "trust-root.json").unlink()
        (st.root / "ledger" / ".external-anchor-enabled").unlink()
        ok2, reason2 = st.check_pubkey_root()
        r.add("外部锚已建立但被删 → fail-closed(HIGH-1)",
              ok2 is False and reason2 == "external-anchor-deleted")
        # v2.7.2 N1 修复验证：攻击者进一步删光 ledger 全部基线文件（含 integrity.json / 哈希链）
        # 外部基线仍在 Agent 无写权限域 → 仍 fail-closed（基线不在 ledger 可写域）。
        ij = st.root / "ledger" / "integrity.json"
        if ij.exists():
            ij.unlink()
        chain = st.root / "ledger" / "integrity-chain"
        if chain.exists():
            shutil.rmtree(chain, ignore_errors=True)
        ok3, reason3 = st.check_pubkey_root()
        r.add("删基线+锚+链(账本全清) → 仍 fail-closed(N1 修复)",
              ok3 is False and reason3 == "external-anchor-deleted")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_tampered_hash():
    """v2.7.2 P2（防御 in-depth）：外部锚建立后，攻击者篡改 trust-root.json 内容（非删除，哈希变化）
    → check_pubkey_root fail-closed（external-anchor-deleted，哈希比对命中篡改）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        att = str(tmp / "attest.json")
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        pinned = st.pinned_human_pubkey_fingerprint()
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off)
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok1, _ = st.check_pubkey_root()
        r.add("oob 外部锚已建立 → 通过", ok1 is True)
        st.record_external_anchor_integrity()
        # 攻击者篡改 trust-root.json 内容（保持文件存在，但哈希变化）
        (st.root / "ledger" / "trust-root.json").write_text(
            '{"enabled": true, "backend": "oob", "root_pubkey": "TAMPERED", '
            '"oob_token_dir": "%s"}' % oobd, encoding="utf-8")
        ok2, reason2 = st.check_pubkey_root()
        r.add("外部锚文件被篡改(哈希不符) → fail-closed(P2)",
              ok2 is False and reason2 == "external-anchor-deleted")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_oob_standalone_outside_root_blocked():
    """v2.7.2 P4（Hermes N3 盲区补测）：oob 单独部署时，若 oob_token_dir 位于 Agent 可写域内
    （未满足部署契约），结构性 fail-closed 闸门(anchor_storage_outside_root)同样拦截 →
    check_pubkey_root fail-closed（external-anchor-inside-writable-root）。覆盖作者此前仅测
    hsm/hsm+oob 的盲区。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        # oob_token_dir 放在可写域内（ledger 下）→ 闸门须拒绝
        oobd = str(st.root / "ledger" / "oob")
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off)
        ok, reason = st.check_pubkey_root()
        r.add("oob 单独部署且令牌目录位于可写域内 → fail-closed(闸门)",
              ok is False and reason == "external-anchor-inside-writable-root")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_high1_three_piece_deletion_failclosed():
    """v2.7.3 HIGH-1 闭环验证：复现 Hermes v2.7.2 复验 HIGH-1 攻击——删 CONTRACT.md 指针
    + trust-root.json + sentinel 三件套，企图让『外置基线』因指针 CONTRACT.md 可写未成立而静默回退 legacy。
    v2.7.3 基线位置固定（不再由 CONTRACT.md 指针推导，HIGH-3 修复）→ 删这三项不波及固定外部基线。
    两层 fail-closed 兜底（任一情形均 fail-closed，绝不静默回退 legacy，关闭 Hermes HIGH-1）：
    (1) 仅删 trust-root.json + sentinel（保留 CONTRACT.md 钉固）→ 固定基线仍在、锚缺失 → external-anchor-deleted；
    (2) 再删 CONTRACT.md（完整三件套）→ 钉固指纹缺失 → no-pinned-root。
    注意：若攻击者『额外』删掉固定外部基线本身（删 固定基线+锚+sentinel），因固定基线仍处同用户可写
    文件系统，会静默回退 legacy——此即 C-1 未真正闭合的残余（见 HANDOFF ⑦），本版如实披露、未消除。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        att = str(tmp / "attest.json")
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        pinned = st.pinned_human_pubkey_fingerprint()
        _enable_external(st, tmp, "hsm+oob", att=att, oob=oobd, root_pubkey=pub_off)
        trust_root.write_root_attestation(att, pub_serialized, pinned, priv_off)
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok1, _ = st.check_pubkey_root()
        r.add("外部锚已建立 → 通过", ok1 is True)
        # 攻击步 1：仅删 trust-root.json + sentinel（保留 CONTRACT.md 钉固）
        (st.root / "ledger" / "trust-root.json").unlink()
        (st.root / "ledger" / ".external-anchor-enabled").unlink()
        ok2, reason2 = st.check_pubkey_root()
        r.add("删 锚+sentinel(保留 CONTRACT.md) → fail-closed(external-anchor-deleted)",
              ok2 is False and reason2 == "external-anchor-deleted")
        # 固定外部基线确实未被删除（证明 HIGH-3 修复使基线不再由可写指针发现）
        r.add("固定外部基线在删锚+sentinel后仍存续",
              st.external_anchor_baseline_path is not None
              and st.external_anchor_baseline_path.exists())
        # 攻击步 2：再删 CONTRACT.md（Hermes HIGH-1 完整三件套）→ 钉固缺失 fail-closed
        cp = st.root / "CONTRACT.md"
        if cp.exists():
            cp.unlink()
        ok3, reason3 = st.check_pubkey_root()
        r.add("再删 CONTRACT.md(三件套全删) → 仍 fail-closed(no-pinned-root)",
              ok3 is False and reason3 == "no-pinned-root")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_baseline_partial_key_failclosed():
    """v2.7.3 HIGH-2 闭环：外部锚建立后，基线 JSON 被攻击者删去任一期望 key（仅留 SENTINEL 删 JSON，
    或反之）→ 残缺基线视为被破坏 → fail-closed（external-anchor-deleted）。v2.7.2 用 `and` 仅当两 key
    皆缺才 fail-closed，删单 key 留另一 key 会静默 pass（HIGH-2）；v2.7.3 改 `or`。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off)
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok1, _ = st.check_pubkey_root()
        r.add("oob 外部锚已建立 → 通过", ok1 is True)
        st.record_external_anchor_integrity()
        # 攻击者删去基线中的 JSON_KEY 项（留 SENTINEL_KEY 项），锚文件保持完好
        bp = st.external_anchor_baseline_path
        data = json.loads(bp.read_text(encoding="utf-8"))
        data.pop(st.EXTERNAL_ANCHOR_JSON_KEY, None)
        bp.write_text(json.dumps(data), encoding="utf-8")
        ok2, reason2 = st.check_pubkey_root()
        r.add("基线删单 key(留另一 key) → fail-closed(HIGH-2)",
              ok2 is False and reason2 == "external-anchor-deleted")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_sentinel_tamper_failclosed():
    """v2.7.3 MEDIUM-1 闭环：外部锚建立后，攻击者篡改 sentinel(.external-anchor-enabled)内容
    （文件仍在，但哈希变化）→ 基线记录的 sentinel 哈希不符 → fail-closed（external-anchor-deleted）。
    v2.7.2 仅比对 anchor 哈希、不比对 sentinel 哈希（MEDIUM-1）；v2.7.3 双 key 哈希比对。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off)
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok1, _ = st.check_pubkey_root()
        r.add("oob 外部锚已建立 → 通过", ok1 is True)
        st.record_external_anchor_integrity()
        # 攻击者篡改 sentinel 内容（保持文件存在，哈希变化）
        sp = st.root / "ledger" / ".external-anchor-enabled"
        sp.write_text('{"backend": "hsm", "tampered": true}', encoding="utf-8")
        ok2, reason2 = st.check_pubkey_root()
        r.add("sentinel 被篡改(哈希不符) → fail-closed(MEDIUM-1)",
              ok2 is False and reason2 == "external-anchor-deleted")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_oob_standalone_evil_priv_token_rejected():
    """v2.7.3 N3 真实对抗：oob 单独部署且令牌目录位于 root 之外（满足部署契约，绕过目录闸门），
    但攻击者持**非授信** evil 私钥对挑战签名写入令牌 → 令牌验签（对授信 root_pubkey）失败 →
    fail-closed（oob-confirmation-required）。覆盖 test_oob_standalone_outside_root_blocked 仅测
    目录闸门的盲区（未对抗『持错误密钥的伪造令牌』）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    evil_pub, evil_priv = _offline_root()  # 攻击者自生成的密钥对（非授信）
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        oobd = str(tmp / "oob")  # root(tmp/.metacog) 之外（满足部署契约）
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off)  # 授信根公钥
        st.record_external_anchor_integrity()  # 建立基线，使攻击到达 oob 验签阶段
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        # 攻击者用 evil 私钥签令牌（非授信根私钥）→ 验签失败
        _write_signed_oob_token(oobd, ch, evil_priv)
        ok, reason = st.check_pubkey_root()
        r.add("oob 令牌目录合法但令牌由 evil 私钥签名 → fail-closed(N3 对抗)",
              ok is False and reason == "oob-confirmation-required")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_signed_baseline_coherent_rewrite_detected():
    """v2.7.4 NEW-H1 收口验证：外部锚建立时提供离线根私钥 → 基线经离线根签名认证。
    攻击者一致化改写 anchor+sentinel+baseline（重算哈希使 baseline 与篡改后文件一致）→ 因无离线
    私钥无法伪造基线签名 → _external_anchor_deleted 返回 True（一致化改写被检出，fail-closed）。
    证明 Hermes v2.7.3 NEW-H1（一致化多文件改写→静默放行）已闭合。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off, root_privkey=priv_off)
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok1, _ = st.check_pubkey_root()
        r.add("oob 外部锚已建立(签名基线) → 通过", ok1 is True)
        # 攻击者一致化改写：替换 anchor + sentinel 内容，并重算 baseline 哈希使其一致
        anchor = st.root / "ledger" / "trust-root.json"
        sentinel = st.root / "ledger" / ".external-anchor-enabled"
        attacker_anchor = '{"backend": "oob", "root_pubkey": "ATTACKER", "oob_token_dir": "/tmp/evil"}'
        anchor.write_text(attacker_anchor, encoding="utf-8")
        sentinel.write_text('{"backend": "oob", "tampered": true}', encoding="utf-8")
        bp = st.external_anchor_baseline_path
        data = json.loads(bp.read_text(encoding="utf-8"))
        data[st.EXTERNAL_ANCHOR_JSON_KEY]["hash"] = st._hash_text(attacker_anchor)
        data[st.EXTERNAL_ANCHOR_SENTINEL_KEY]["hash"] = st._hash_text(sentinel.read_text(encoding="utf-8"))
        bp.write_text(json.dumps(data), encoding="utf-8")
        # baseline 仍带原签名（攻击者无私钥无法更新）→ 验签失败 → 检出
        deleted = st._external_anchor_deleted()
        r.add("签名基线 + 一致化改写 anchor+sentinel+baseline → 被检出(fail-closed)", deleted is True)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_unsigned_baseline_coherent_rewrite_not_detected():
    """v2.7.4 NEW-H1 已知残余（best-effort 变更检测层）：外部锚建立时**未提供**离线根私钥
    → 基线仅为 SHA-256 快照（非签名认证）。攻击者一致化改写 anchor+sentinel+baseline →
    _external_anchor_deleted 返回 False（未被检出）。此路径依赖部署契约（钉固 root-pubkey.pem
    不可写）兜底；提供 --root-privkey 即闭合（见 test_external_anchor_signed_baseline_...）。
    本测试显式钉住该残余，杜绝 over-claim（与 CONTRACT.md 钉固人类公钥同层级）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off)  # 不传 root_privkey → 基线无签名
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized)
        _write_signed_oob_token(oobd, ch, priv_off)
        ok1, _ = st.check_pubkey_root()
        r.add("oob 外部锚已建立(无签名基线) → 通过", ok1 is True)
        anchor = st.root / "ledger" / "trust-root.json"
        sentinel = st.root / "ledger" / ".external-anchor-enabled"
        attacker_anchor = '{"backend": "oob", "root_pubkey": "ATTACKER", "oob_token_dir": "/tmp/evil"}'
        anchor.write_text(attacker_anchor, encoding="utf-8")
        sentinel.write_text('{"backend": "oob", "tampered": true}', encoding="utf-8")
        bp = st.external_anchor_baseline_path
        data = json.loads(bp.read_text(encoding="utf-8"))
        data[st.EXTERNAL_ANCHOR_JSON_KEY]["hash"] = st._hash_text(attacker_anchor)
        data[st.EXTERNAL_ANCHOR_SENTINEL_KEY]["hash"] = st._hash_text(sentinel.read_text(encoding="utf-8"))
        bp.write_text(json.dumps(data), encoding="utf-8")
        deleted = st._external_anchor_deleted()
        r.add("无签名基线 + 一致化改写 → 未检出(KNOWN RESIDUAL, 须部署契约兜底)", deleted is False)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_delete_baseline_and_sentinel_residual():
    """v2.7.4 M-2 / 纠正 v2.7.3『三件套』+ Hermes NEW-HIGH over-statement：

    真实行为（删 baseline + sentinel 两件套，留 anchor）：
    - `_external_anchor_deleted` 返回 False：基线缺失使 `enabled=False` 在 sentinel 哈希比对
      之前短路 → 删除检出闸被绕过（即『删锚冗余』：无需删 anchor 即可让闸失效）。这是**真实残余**
      ——完整性基线可被静默移除而不触发 fail-closed。
    - 但此**不**等于『legacy fail-open』：Hermes NEW-HIGH 把 `return enabled==False` 误读为
      『静默回退 legacy 放行』。实际 `_external_anchor_deleted` 返回 False 仅表示『未判定为删除，
      继续走外部锚验证』；`check_pubkey_root` 仍须通过外部锚验证（oob 须有效令牌）。无新令牌 →
      fail-closed(oob-confirmation-required)；持有效令牌 → 外部锚照常通过（锚与令牌完好）。

    结论：删 baseline+sentinel 是**防御纵深降级**（完整性基线可被移除、不再能检出后续一致化改写），
    但**非** C-1 fail-open（外部锚密码学闸仍生效）。NEW-H1 在无签名基线下的残余由此路径体现，
    如实钉住，纠正 over-claim。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        pub_serialized, _ = st.load_human_keys()
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off)
        ext = st.external_trust_root()
        ch = ext.challenge_for(pub_serialized, op="verify")
        _write_signed_oob_token(oobd, ch, priv_off)
        ok1, _ = st.check_pubkey_root()
        r.add("oob 外部锚已建立 → 通过", ok1 is True)
        # 攻击者删 baseline + sentinel（留 anchor）
        st.external_anchor_baseline_path.unlink()
        (st.root / "ledger" / ".external-anchor-enabled").unlink()
        # 真实残余：删除检出闸被绕过（基线缺失短路在 sentinel 哈希比对之前）
        r.add("删 baseline+sentinel → _external_anchor_deleted 返回 False（删除检出闸被绕过，真实残余≠legacy 放行）",
              st._external_anchor_deleted() is False)
        # 但不静默 legacy 放行：首次 check 已一次性消费令牌，此处无新令牌 → 仍 fail-closed
        ok2, reason2 = st.check_pubkey_root()
        r.add("删 baseline+sentinel 后无新令牌 → 仍 fail-closed（oob-confirmation-required，非 legacy 静默放行）",
              ok2 is False and reason2 == "oob-confirmation-required")
        # 补写同挑战（确定性）新令牌 → 外部锚照常通过（锚完好，删基线/sentinel 不破坏锚本身）
        ext2 = st.external_trust_root()
        ch2 = ext2.challenge_for(pub_serialized, op="verify")
        _write_signed_oob_token(oobd, ch2, priv_off)
        ok3, _ = st.check_pubkey_root()
        r.add("补写有效令牌 → 外部锚仍照常通过（锚完好，删基线/sentinel 不破坏锚）", ok3 is True)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_signed_baseline_signature_stripped_failclosed():
    """v2.7.5 E1 收口：基线曾以离线根签名建立（baseline['signed']=True）。攻击者单删基线
    `signature` 字段（不动 anchor/sentinel）→ 验签分支因 sig 缺失而 fail-closed（不再静默
    回退 best-effort 残余）。证明『签名闸为强制闸』——签名被剥离即检出。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off, root_privkey=priv_off)
        bp = st.external_anchor_baseline_path
        data = json.loads(bp.read_text(encoding="utf-8"))
        r.add("基线建立为签名基线(signed=True 且含 signature)", data.get("signed") is True and "signature" in data)
        # 攻击者单删 signature 字段（保留 signed=True，模拟签名被剥离）
        data.pop("signature")
        bp.write_text(json.dumps(data), encoding="utf-8")
        deleted = st._external_anchor_deleted()
        r.add("签名基线被单删 signature → 仍 fail-closed（E1 收口）", deleted is True)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_signed_baseline_pinned_pubkey_removed_failclosed():
    """v2.7.5 C1 收口（披露精度）：基线曾签名建立。攻击者删钉固 root-pubkey.pem
    （pinned_pub=None）→ 验签分支因钉固公钥缺失而 fail-closed。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off, root_privkey=priv_off)
        proof_dir = st._external_anchor_proof_dir()
        (proof_dir / "root-pubkey.pem").unlink()  # 删钉固公钥
        deleted = st._external_anchor_deleted()
        r.add("签名基线 + 删钉固公钥 → 仍 fail-closed（C1 收口）", deleted is True)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_bad_root_privkey_warns_and_unsigned():
    """v2.7.5 D1 收口：启用外部锚传入坏 --root-privkey（非法私钥）→ 签名失败被捕获，
    基线无 signature / signed 字段（退 best-effort），且 stderr 输出 NEW-H1 未闭合告警
    （不再静默）。验证签名失败可事后区分、不谎报『已签名』。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off, root_privkey="{not-a-private-key}")
            err = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr
        bp = st.external_anchor_baseline_path
        data = json.loads(bp.read_text(encoding="utf-8"))
        r.add("坏私钥 → 基线无 signature/signed（退 best-effort）",
              "signature" not in data and data.get("signed") is not True)
        r.add("坏私钥 → stderr 输出 NEW-H1 未闭合告警", "NEW-H1 未闭合" in err)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_purge_external_anchor_idempotent():
    """v2.7.6 NEW-H1 收口：purge 删外部锚全部足迹（证明目录 + ledger trust-root.json + sentinel）。
    幂等：首次有外部锚待回收 → 'cleared'；二次（已无）→ 'none'。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off, root_privkey=priv_off)
        r.add("首次 purge 返回 'cleared'（确有外部锚待回收）", st.purge_external_anchor() == "cleared")
        r.add("二次 purge 返回 'none'（幂等，无残留）", st.purge_external_anchor() == "none")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_purge_external_anchor_clears_ledger_then_legacy():
    """v2.7.6 NEW-H1 收口：purge 补清 ledger trust-root.json + sentinel。全清后
    _external_anchor_deleted 返 False（回退『从未启用』legacy，不再 fail-closed），
    幽灵态检测闸不再误伤合法重装。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off, root_privkey=priv_off)
        r.add("启用且基线在 → _external_anchor_deleted 返 False（正常）", st._external_anchor_deleted() is False)
        r.add("purge 返回 'cleared'（全部足迹已删）", st.purge_external_anchor() == "cleared")
        r.add("purge 后 ledger/trust-root.json 已删除", not (st.root / "ledger" / "trust-root.json").exists())
        r.add("purge 后 ledger/.external-anchor-enabled 已删除", not (st.root / "ledger" / ".external-anchor-enabled").exists())
        r.add("purge 后固定外部证明目录已删除", not st._external_anchor_proof_dir().exists())
        r.add("purge 全清后 _external_anchor_deleted 返 False（legacy，不误伤合法重装）", st._external_anchor_deleted() is False)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_sentinel_present_baseline_missing_still_failclosed():
    """v2.7.6 NEW-H1 防御回归：即便 ledger 足迹（trust-root.json + sentinel）仍残留而固定外部
    基线已失（如 purge 半败 / 手工部分删除），sentinel 在 + baseline 缺失 → _external_anchor_deleted
    返 True（fail-closed，绝不静默 legacy 放行）。锁住『永不静默 fail-open』契约，确保 NEW-H1 收口
    未削弱既有防御腿。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    try:
        (st.root / "ledger" / "trust-root.json").write_text(
            json.dumps({"enabled": True, "backend": "oob"}), encoding="utf-8")
        (st.root / "ledger" / ".external-anchor-enabled").write_text(
            json.dumps({"backend": "oob"}), encoding="utf-8")
        r.add("sentinel 在 + baseline 缺失 → _external_anchor_deleted 返 True（fail-closed，非 legacy）",
              st._external_anchor_deleted() is True)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_valid_privkey_resign_baseline_passes_undetected():
    """v2.7.6 NEW-M-2 对抗测试（诚实披露）：攻击者**持有合法离线根私钥**时，可直接覆盖 baseline
    并用同 hash 重签 → _external_anchor_deleted 返回 False（未被检出）。这文档化 C-1 残余：
    离线根私钥一旦泄露/被同用户持有，签名基线的全部保护即失效——根信任锚定仍位于 Agent 可写
    域，唯一防线是『离线根私钥绝不落盘、绝不暴露给 Agent』的部署契约。本测试显式钉住该残余，
    非缺陷（属 C-1 未真正闭合的同构表现），须外部不可变存储 / TPM / 独立机方真闭合。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off, root_privkey=priv_off)
        bp = st.external_anchor_baseline_path
        data0 = json.loads(bp.read_text(encoding="utf-8"))
        r.add("基线为签名基线(signed=True 且含 signature)", data0.get("signed") is True and "signature" in data0)
        # 攻击者持合法 priv_off，直接覆盖 anchor+sentinel 为新内容，并用同私钥重签 baseline
        anchor = st.root / "ledger" / "trust-root.json"
        sentinel = st.root / "ledger" / ".external-anchor-enabled"
        anchor.write_text(json.dumps({"enabled": True, "backend": "oob", "root_pubkey": "ATTACKER_REPLACED"}),
                         encoding="utf-8")
        sentinel.write_text(json.dumps({"backend": "oob", "note": "attacker tampered"}), encoding="utf-8")
        rec = {}
        for key, p in ((st.EXTERNAL_ANCHOR_JSON_KEY, anchor), (st.EXTERNAL_ANCHOR_SENTINEL_KEY, sentinel)):
            rec[key] = {
                "hash": st._hash_text(p.read_text(encoding="utf-8")),
                "size": p.stat().st_size,
                "at": "2026-10-07T00:00:00",
            }
        payload = (rec[st.EXTERNAL_ANCHOR_JSON_KEY]["hash"] + "||"
                   + rec[st.EXTERNAL_ANCHOR_SENTINEL_KEY]["hash"]).encode("utf-8")
        sig = sigcrypto.sign(sigcrypto.deserialize_priv(priv_off), payload)
        rec["signature"] = base64.b64encode(sig).decode("ascii")
        rec["signed"] = True
        bp.write_text(json.dumps(rec), encoding="utf-8")
        deleted = st._external_anchor_deleted()
        r.add("持合法根私钥重签 baseline → 未被检出（C-1 残余：离线私钥泄即失效，文档化非缺陷）",
              deleted is False)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_external_anchor_d1_second_branch_warns_and_unsigned():
    """v2.7.7 M-2 收口：D1 第二静默分支测试覆盖。提供 --root-privkey 但 anchor 缺失（sentinel 在）
    → record_external_anchor_integrity 走 elif 分支 stderr WARN『签名跳过』，基线退 best-effort
    （无 signed）。与 except 坏私钥分支（test_external_anchor_bad_root_privkey_warns_and_unsigned）对称。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    import io, contextlib
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off, root_privkey=priv_off)
        # 删 anchor（保留 sentinel），直调 record 提供 privkey → 触发 D1 第二分支
        anchor = st.root / "ledger" / "trust-root.json"
        anchor.unlink()
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            st.record_external_anchor_integrity(root_pubkey=pub_off, root_privkey=priv_off)
        err = buf.getvalue()
        r.add("D1 第二分支 stderr 含『签名跳过』WARN", "签名跳过" in err or "anchor 或 sentinel 缺失" in err)
        bp = st.external_anchor_baseline_path
        data = json.loads(bp.read_text(encoding="utf-8"))
        r.add("基线无 signed 标记（退 best-effort）", data.get("signed") is not True)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_purge_external_anchor_partial_failure_returns_partial_and_warns():
    """v2.7.7 M-1 收口：purge 半败（外部证明目录删除异常）须返 'partial' 且 stderr WARN，
    调用方据此报『须手动补清』而非误报『无需回收』；杜绝 re-enable 覆盖钉固公钥的 C-1 绕过。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    import io, contextlib
    orig_rmtree = shutil.rmtree
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off, root_privkey=priv_off)
        # 注入：外部证明目录删除抛异常 → 半败
        def _boom(path, ignore_errors=False):
            raise PermissionError("injected")
        shutil.rmtree = _boom
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            res = st.purge_external_anchor()
        err = buf.getvalue()
        r.add("半败返回 'partial'（非 'none'）", res == "partial")
        r.add("半败 stderr 含 WARN 提示手动补清", "WARN" in err and "半败" in err)
        r.add("半败后 ledger/trust-root.json 已删", not (st.root / "ledger" / "trust-root.json").exists())
        r.add("半败后外部证明目录仍残留", st._external_anchor_proof_dir().exists())
        r.add("'partial' 与 'none' 区分（杜绝误报无需回收）", res != "none")
    finally:
        shutil.rmtree = orig_rmtree
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_purge_external_anchor_clears_readonly_ledger_and_proof():
    """v2.7.8 NEW-M 收口：模拟生产 _restrict_credential 把 ledger 文件 + 证明目录 root-pubkey.pem
    置只读（Windows 0o400 → FILE_ATTRIBUTE_READONLY），purge 须先清只读位再删除，最终返 'cleared'
    （而非恒 'partial'）。直接复现 Hermes v2.7.7 复验 NEW-M 的 Windows 只读断裂并验证修复。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    pub_off, priv_off = _offline_root()
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        oobd = str(tmp / "oob")
        Path(oobd).mkdir(parents=True, exist_ok=True)
        _enable_external(st, tmp, "oob", oob=oobd, root_pubkey=pub_off, root_privkey=priv_off)
        # 模拟生产：write_trust_root_config 对 ledger 文件置只读（Windows 0o400）
        for f in (st.root / "ledger" / "trust-root.json",
                  st.root / "ledger" / ".external-anchor-enabled"):
            if f.exists():
                try:
                    _os.chmod(str(f), 0o400)
                except OSError:
                    pass
        # 模拟生产：证明目录 root-pubkey.pem（及基线）置只读，验证 rmtree onerror 清只读
        pd = st._external_anchor_proof_dir()
        if pd is not None and pd.exists():
            for f in pd.iterdir():
                try:
                    _os.chmod(str(f), 0o400)
                except OSError:
                    pass
        r.add("只读 ledger/证明目录 → purge 返回 'cleared'（NEW-M 修复：清只读后删除）",
              st.purge_external_anchor() == "cleared")
        r.add("purge 后 ledger/trust-root.json 已删除",
              not (st.root / "ledger" / "trust-root.json").exists())
        r.add("purge 后 ledger/.external-anchor-enabled 已删除",
              not (st.root / "ledger" / ".external-anchor-enabled").exists())
        r.add("purge 后固定外部证明目录已删除", not st._external_anchor_proof_dir().exists())
        r.add("二次 purge 返回 'none'（幂等，无残留）", st.purge_external_anchor() == "none")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def main():
    all_ok = True
    grand_p = grand_f = 0
    for fn in (test_trust_root_abstraction,
               test_rsa_root_verifier_isolation,
               test_check_pubkey_root_default_legacy,
               test_check_pubkey_root_hsm_valid,
               test_check_pubkey_root_hsm_missing_attestation,
               test_check_pubkey_root_hsm_forged_attestation,
               test_check_pubkey_root_oob_failclosed_and_pass,
               test_check_pubkey_root_corrupt_config_failclosed,
               test_n1_nonce_symlink_rejected,
               test_n2_hash_chain,
               test_symlink_defense,
               test_oob_token_content_and_consume,
               test_enable_external_requires_root_pubkey,
               test_deploy_contract_check,
               test_deny_reason_subtype,
               test_delete_config_fallback_legacy,
               test_attacker_swaps_root_pubkey,
               test_external_anchor_deletion_failclosed,
               test_external_anchor_tampered_hash,
               test_oob_standalone_outside_root_blocked,
               test_external_anchor_high1_three_piece_deletion_failclosed,
               test_external_anchor_baseline_partial_key_failclosed,
               test_external_anchor_sentinel_tamper_failclosed,
               test_oob_standalone_evil_priv_token_rejected,
               test_external_anchor_signed_baseline_coherent_rewrite_detected,
               test_external_anchor_unsigned_baseline_coherent_rewrite_not_detected,
              test_external_anchor_delete_baseline_and_sentinel_residual,
              test_external_anchor_signed_baseline_signature_stripped_failclosed,
              test_external_anchor_signed_baseline_pinned_pubkey_removed_failclosed,
              test_external_anchor_bad_root_privkey_warns_and_unsigned,
              test_purge_external_anchor_idempotent,
              test_purge_external_anchor_clears_ledger_then_legacy,
              test_external_anchor_sentinel_present_baseline_missing_still_failclosed,
              test_external_anchor_valid_privkey_resign_baseline_passes_undetected,
              test_external_anchor_d1_second_branch_warns_and_unsigned,
              test_purge_external_anchor_partial_failure_returns_partial_and_warns,
              test_purge_external_anchor_clears_readonly_ledger_and_proof,
              test_deny_reason_passthrough,
               test_build_offline_root,
               test_load_json_scalar_failclosed,
               test_load_enabled_string_false,
               test_write_trust_root_config_atomic_and_perms,
               test_trust_root_config_c1_signature_closure,
              test_c9_default_anchor_key_rejected_for_external,
              test_c10_script_integrity_hotpath_gate,
              test_c10_nested_package_integrity,
              test_c10_orphan_key_cleanup,
              test_c10_script_file_deletion_current_none,
              test_c10_trust_root_strict_truthtable,
              test_c10_apply_hardgate_rejects,
              test_c10_verify_dirty_includes_script_key,
              test_c10_keygen_hardgate_rejects,
              test_c10_resign_hardgate_rejects,
              test_c10_keygen_idempotent_still_gates,
              test_c10_gate_helper_truthtable,
              test_c11_legacy_16char_baseline_compatible,
              test_c11_legacy_16char_artifact_baseline_compatible,
              test_c11_legacy_16char_guard_baseline_compatible,
              test_v2811_hash_matches_and_proof_dir_hardening,
              test_v2811_proof_dir_record_flag,
              test_v2811_external_anchor_verify_idempotent,
              test_v2811_migration_audit_hmac_coverage,
              test_v2811_integrity_chain_ok_guard,
              test_f4_manifest_integrity_domain,
              test_legacy_window_governance,
              test_c11_default_failclosed_and_optout,
               test_load_recursionerror_failclosed,
               test_attestation_ok_malformed_input_failclosed,
               test_attestation_contract_mismatch,
               test_c1_protected_anchor_strict_mode):
        print("\n--- {} ---".format(fn.__name__))
        res = fn()
        grand_p += res.passed
        grand_f += res.failed
        all_ok = res.summary() and all_ok
    print("\n" + "=" * 60)
    print("全文件总计: {}/{} PASS".format(grand_p, grand_p + grand_f))
    print("=" * 60)
    return 0 if (all_ok and grand_f == 0) else 1


def test_deny_reason_passthrough():
    """H-1（v2.6.3）：DenyTrustRoot（corrupt/no-provider/unknown-backend）在 check_pubkey_root
    中直接 fail-closed 并透传细分 reason，不被 oob 分支吞掉（oob_token_required 恒 True）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("pw1")
    try:
        _run(metacog.cmd_confirm, st, _keygen_ns(tmp))  # 钉固指纹，使 check_pubkey_root 进入外部锚分支
        # 写入未知 backend（须带签名方能触达 build_trust_root 的 unknown-backend 判定；
        # 无签名配置会被 v2.8.0 签名闸先判 corrupt，无法验证 passthrough）
        _cfg = {"enabled": True, "backend": "weird"}
        _cfg["_sig"] = trust_root.sign_trust_root_config(_cfg, trust_root.get_anchor_key())
        (st.root / "ledger" / "trust-root.json").write_text(
            json.dumps(_cfg), encoding="utf-8")
        ok, reason = st.check_pubkey_root()
        r.add("unknown backend → 透传 external-anchor-unknown-backend（非 oob-confirmation-required）",
              ok is False and reason == "external-anchor-unknown-backend")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_build_offline_root():
    """v2.7.0：离线 RSA 根 = 真外部锚。
    - hsm + root_pubkey → 允许（独立 hsm 现为真外部锚）；hsm+oob + root_pubkey → 允许。
    - hsm 无 verifier（无 root_pubkey 无真机）→ deny(external-anchor-no-verifier)。
    - oob 无 verifier → deny(external-anchor-oob-no-verifier)。
    - hsm + token_backend（桩）→ 构建允许（verify 仍 fail-closed 直至真机实现）。"""
    r = T()
    pub_off, _ = _offline_root()
    r.add("hsm + root_pubkey → 允许（独立 hsm 真外部锚）",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              enabled=True, backend="hsm", attestation_path="x",
              root_pubkey=pub_off)).name == "hsm")
    r.add("hsm+oob + root_pubkey → 允许",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              enabled=True, backend="hsm+oob", attestation_path="x", oob_token_dir="y",
              root_pubkey=pub_off)).name == "hsm+oob")
    r.add("hsm 无 verifier → deny(external-anchor-no-verifier)",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              enabled=True, backend="hsm", attestation_path="x")).reason == "external-anchor-no-verifier")
    r.add("oob 无 verifier → deny(external-anchor-oob-no-verifier)",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              enabled=True, backend="oob", oob_token_dir="y")).reason == "external-anchor-oob-no-verifier")
    r.add("hsm + token_backend → 非 deny（构建层允许，verify 桩 fail-closed）",
          trust_root.build_trust_root(trust_root.TrustRootConfig(
              enabled=True, backend="hsm", attestation_path="x", token_backend="pkcs11")).name != "deny")
    return r


def test_load_json_scalar_failclosed():
    """v2.6.4 ①：trust-root.json 为 JSON 标量(null/[]/0/true/数字)时，load 不抛未捕获异常，
    而标记 corrupt → build_trust_root 恒拒（fail-closed）。"""
    r = T()
    for bad in ("null", "[]", "0", "true", "123"):
        td = Path(tempfile.mkdtemp(prefix="tr_scalar_"))
        try:
            (td / "ledger").mkdir(parents=True, exist_ok=True)
            (td / "ledger" / "trust-root.json").write_text(bad, encoding="utf-8")
            cfg = trust_root.TrustRootConfig.load(td)
            root = trust_root.build_trust_root(cfg)
            r.add("JSON 标量 {} → corrupt 恒拒".format(bad),
                  cfg.corrupt is True and root is not None and root.name == "deny")
        finally:
            shutil.rmtree(td, ignore_errors=True)
    return r


def test_load_enabled_string_false():
    """v2.6.4 ②：enabled 为字符串 "false" 不被 bool() 强转 True；须严格 is True。"""
    r = T()
    td = Path(tempfile.mkdtemp(prefix="tr_enf_"))
    try:
        (td / "ledger").mkdir(parents=True, exist_ok=True)
        _c1 = {"enabled": "false", "backend": "oob"}
        _c1["_sig"] = trust_root.sign_trust_root_config(_c1, trust_root.get_anchor_key())
        (td / "ledger" / "trust-root.json").write_text(
            json.dumps(_c1), encoding="utf-8")
        cfg = trust_root.TrustRootConfig.load(td)
        r.add("enabled='false' 字符串 → enabled 为 False",
              cfg.enabled is False and trust_root.build_trust_root(cfg) is None)
        # 对照：enabled=true(布尔) 仍生效
        _c2 = {"enabled": True, "backend": "oob"}
        _c2["_sig"] = trust_root.sign_trust_root_config(_c2, trust_root.get_anchor_key())
        (td / "ledger" / "trust-root.json").write_text(
            json.dumps(_c2), encoding="utf-8")
        cfg2 = trust_root.TrustRootConfig.load(td)
        r.add("enabled=true(布尔) → enabled 为 True", cfg2.enabled is True)
    finally:
        shutil.rmtree(td, ignore_errors=True)
    return r


def test_write_trust_root_config_atomic_and_perms():
    """v2.6.4 ③⑤：write_trust_root_config 原子写 json(无 .tmp 残留) + 凭据文件权限收窄；
    顺序保证 sentinel 先于 json，删 json(留 sentinel) 仍 fail-closed。
    v2.6.5：权限收窄须实际生效（POSIX 0o600 / Windows 置只读防御纵深，且重写入不被卡）。"""
    r = T()
    td = Path(tempfile.mkdtemp(prefix="tr_wrt_"))
    _pub, _priv = trust_root.gen_offline_root_keypair()
    try:
        trust_root.write_trust_root_config(td, "hsm+oob", attestation_path="x",
                                           oob_token_dir="y",
                                           root_pubkey=_pub)
        json_path = td / "ledger" / "trust-root.json"
        sentinel = td / "ledger" / ".external-anchor-enabled"
        r.add("trust-root.json 已写入", json_path.is_file())
        r.add("sentinel 已写入", sentinel.is_file())
        r.add("无 .tmp 残留", not (td / "ledger" / ".trust-root.json.tmp").exists())
        # v2.6.5：权限收窄实际生效（按平台断言）
        if _os.name == "posix":
            r.add("POSIX json 权限==0o600", stat.S_IMODE(_os.stat(str(json_path)).st_mode) == 0o600)
            r.add("POSIX sentinel 权限==0o600", stat.S_IMODE(_os.stat(str(sentinel)).st_mode) == 0o600)
        else:
            r.add("Windows json 置只读", not _os.access(str(json_path), _os.W_OK))
            r.add("Windows sentinel 置只读", not _os.access(str(sentinel), _os.W_OK))
            # v2.6.6 补 Q3 广度：直查文件属性位（os.access 间接判定可能漏判 0o400 未生效）
            r.add("Windows json st_file_attributes 含 READONLY",
                  bool(_os.stat(str(json_path)).st_file_attributes & stat.FILE_ATTRIBUTE_READONLY))
            r.add("Windows sentinel st_file_attributes 含 READONLY",
                  bool(_os.stat(str(sentinel)).st_file_attributes & stat.FILE_ATTRIBUTE_READONLY))
        cfg = trust_root.TrustRootConfig.load(td)
        r.add("load 回读 enabled=True / backend=hsm+oob",
              cfg.enabled is True and cfg.backend == "hsm+oob")
        # 删 json(留 sentinel) → fail-closed（M-1 仍成立）
        if _os.name != "posix":
            try:
                _os.chmod(str(json_path), 0o600)  # 清只读以便删除（模拟攻击者先清位后删）
            except OSError:
                pass
        json_path.unlink()
        cfg2 = trust_root.TrustRootConfig.load(td)
        root2 = trust_root.build_trust_root(cfg2)
        r.add("删 json(留 sentinel) → fail-closed",
              cfg2.corrupt is True and root2 is not None and root2.name == "deny")
        # Windows：重写入不应被先前只读位卡住（re-enable 场景）
        if _os.name != "posix":
            trust_root.write_trust_root_config(td, "hsm+oob", attestation_path="x",
                                               oob_token_dir="y",
                                               root_pubkey=_pub)
            r.add("Windows 重写入不被只读卡住", json_path.is_file())
    finally:
        shutil.rmtree(td, ignore_errors=True)
    return r


def test_trust_root_config_c1_signature_closure():
    """v2.8.0 C-1 闭合专项：信任根配置须带内嵌锚密钥签名，加载时强制校验。
    - 合法签名配置 → 正常加载（root_pubkey 受信）。
    - 攻击者换 root_pubkey 但保留旧签名 → 签名不符 → fail-closed（C-1 核心：换锚被检出）。
    - 无签名配置（含 v2.8.0 前旧配置）→ fail-closed（升级迁移：须重新 --enable-external）。
    - 签名被篡改（翻转一字符）→ fail-closed。
    锚密钥位于代码（非可写 ledger），攻击者凭 ledger 写权限无密钥无法伪造 → C-1 软件层闭合。"""
    r = T()
    td = Path(tempfile.mkdtemp(prefix="tr_c1_"))
    try:
        (td / "ledger").mkdir(parents=True, exist_ok=True)
        pub_a, _pa = trust_root.gen_offline_root_keypair()
        pub_b, _pb = trust_root.gen_offline_root_keypair()
        # ① 合法签名配置（经生产写入路径）→ 正常加载
        trust_root.write_trust_root_config(td, "oob", root_pubkey=pub_a)
        cfg = trust_root.TrustRootConfig.load(td)
        r.add("合法签名配置 → 正常加载(root_pubkey 受信)",
              cfg.corrupt is False and cfg.enabled is True and cfg.root_pubkey == pub_a)
        # ② C-1 核心：攻击者换 root_pubkey 并保留旧签名 → 签名不符 → fail-closed
        p = td / "ledger" / "trust-root.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["root_pubkey"] = pub_b  # 换锚(不同合法公钥)但保留旧 _sig
        _os.chmod(str(p), 0o600)  # 清只读位（Windows NEW-M：write_trust_root_config 已置只读）
        p.write_text(json.dumps(d), encoding="utf-8")
        cfg2 = trust_root.TrustRootConfig.load(td)
        root2 = trust_root.build_trust_root(cfg2)
        r.add("换 root_pubkey(保留旧签名) → fail-closed(C-1 核心)",
              cfg2.corrupt is True and root2 is not None and root2.name == "deny")
        # ③ 无签名配置（v2.8.0 前旧配置）→ fail-closed
        _os.chmod(str(p), 0o600)  # 清只读位
        p.write_text(json.dumps({"enabled": True, "backend": "oob", "root_pubkey": "PUB_A"}),
                     encoding="utf-8")
        cfg3 = trust_root.TrustRootConfig.load(td)
        r.add("无签名配置 → fail-closed(升级迁移须重签)", cfg3.corrupt is True)
        # ④ 签名被篡改（翻转一字符）→ fail-closed
        good = {"enabled": True, "backend": "oob", "root_pubkey": "PUB_A"}
        good["_sig"] = trust_root.sign_trust_root_config(good, trust_root.get_anchor_key())
        bad = dict(good)
        bad["_sig"] = good["_sig"][:-1] + ("A" if good["_sig"][-1] != "A" else "B")
        _os.chmod(str(p), 0o600)  # 清只读位
        p.write_text(json.dumps(bad), encoding="utf-8")
        cfg4 = trust_root.TrustRootConfig.load(td)
        r.add("签名被篡改 → fail-closed", cfg4.corrupt is True)
    finally:
        shutil.rmtree(td, ignore_errors=True)
    return r


def test_c9_default_anchor_key_rejected_for_external():
    """v2.8.1 C-9 硬化：默认（源码内嵌共享）锚密钥不得用于启用外部锚；须以专属 env 密钥或显式 ALLOW_DEFAULT。
    - 未设 ALLOW_DEFAULT 且用默认密钥 → write_trust_root_config 抛 TrustRootWriteError（拒绝）。
    - 设 ALLOW_DEFAULT=1 → 允许（本地开发显式承担风险）。"""
    r = T()
    orig = _os.environ.get("METACOG_TRUST_ROOT_ALLOW_DEFAULT")
    td = Path(tempfile.mkdtemp(prefix="tr_c9_"))
    try:
        pub_a, _pa = trust_root.gen_offline_root_keypair()
        # ① 移除 ALLOW_DEFAULT（模拟生产：未显式承担风险）→ 拒绝
        _os.environ.pop("METACOG_TRUST_ROOT_ALLOW_DEFAULT", None)
        raised = False
        try:
            trust_root.write_trust_root_config(td, "oob", root_pubkey=pub_a)
        except trust_root.TrustRootWriteError:
            raised = True
        r.add("默认密钥+无 ALLOW_DEFAULT → 拒绝(TrustRootWriteError)", raised)
        # ② 显式 ALLOW_DEFAULT=1 → 允许（本地开发）
        _os.environ["METACOG_TRUST_ROOT_ALLOW_DEFAULT"] = "1"
        trust_root.write_trust_root_config(td, "oob", root_pubkey=pub_a)
        cfg = trust_root.TrustRootConfig.load(td)
        r.add("ALLOW_DEFAULT=1 → 允许(本地开发显式承担风险)",
              cfg.corrupt is False and cfg.enabled is True and cfg.root_pubkey == pub_a)
    finally:
        # 还原模块全局态（默认 "1"）
        if orig is None:
            _os.environ.pop("METACOG_TRUST_ROOT_ALLOW_DEFAULT", None)
        else:
            _os.environ["METACOG_TRUST_ROOT_ALLOW_DEFAULT"] = orig
        shutil.rmtree(td, ignore_errors=True)
    return r


def test_c1_protected_anchor_strict_mode():
    """v2.25.1 #1 L3：METACOG_REQUIRE_PROTECTED_ANCHOR=1 时，证明路径对当前进程可写
    → build_trust_root fail-closed（reason=external-anchor-path-writable）；默认模式仅 WARN 不阻断。"""
    r = T()
    orig = _os.environ.get("METACOG_REQUIRE_PROTECTED_ANCHOR")
    try:
        pub, _ = trust_root.gen_offline_root_keypair()
        # 可写证明路径（测试进程创建 → 当前进程可写 → _is_protected 返 False）
        wdir = Path(tempfile.mkdtemp(prefix="tr_prot_"))
        cfg = trust_root.TrustRootConfig(enabled=True, backend="hsm",
                                         attestation_path=str(wdir), root_pubkey=pub)
        # ① 默认模式：_deploy_warn 仅 WARN，返回 False（不阻断）
        _os.environ.pop("METACOG_REQUIRE_PROTECTED_ANCHOR", None)
        r.add("默认模式：_deploy_warn 返回 False(仅 WARN 不阻断)",
              trust_root._deploy_warn(str(wdir)) is False)
        # ② 严格模式：可写路径 → fail-closed（reason=external-anchor-path-writable）
        _os.environ["METACOG_REQUIRE_PROTECTED_ANCHOR"] = "1"
        root_strict = trust_root.build_trust_root(cfg)
        r.add("严格模式：可写路径 → fail-closed",
              root_strict is not None and root_strict.name == "deny"
              and root_strict.reason == "external-anchor-path-writable")
        # ③ 严格模式：路径不存在(_is_protected=None)不触发此闸（由 attestation_ok 另行 fail-closed）
        r.add("严格模式：路径不存在不触发 path-writable 闸",
              trust_root._deploy_warn(str(wdir / "missing.json")) is False)
    finally:
        if orig is None:
            _os.environ.pop("METACOG_REQUIRE_PROTECTED_ANCHOR", None)
        else:
            _os.environ["METACOG_REQUIRE_PROTECTED_ANCHOR"] = orig
        shutil.rmtree(wdir, ignore_errors=True)
    return r


def test_c10_script_integrity_hotpath_gate():
    """v2.8.1 C-10 硬化：受保护模式（外部锚启用）下，脚本基线漂移 → cmd_retrieve 硬闸拒绝(rc!=0)。
    基线 integrity.json 同处可写 ledger 域；本测试直接注入错误脚本基线以模拟漂移
    （不触及真实脚本文件；若攻击者改代码同时重记基线则仍不可检出——与 D4 同类残余，部署契约兜底）。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        # 启用外部锚（oob + root_pubkey）→ 受保护模式（external_trust_root() 非 None）
        _enable_external(st, tmp, "oob", root_pubkey="PUB_A")
        # 注入错误脚本基线（模拟代码篡改后未重基线）
        ij = st.integrity
        data = metacog.read_json(ij, {})
        data["script:" + st.SCRIPT_NAMES[0]] = {"hash": "deadbeef-wrong"}
        metacog.write_json(ij, data)
        ns = SimpleNamespace(artifact=None, strict=False, json=False)
        rc_deny = metacog.cmd_retrieve(st, ns)
        r.add("外部锚启用+脚本基线漂移 → cmd_retrieve 硬闸拒绝(rc!=0)", rc_deny != 0)
        # 移除注入基线 → 不再漂移 → 正常(rc==0)
        data2 = metacog.read_json(ij, {})
        data2.pop("script:" + st.SCRIPT_NAMES[0], None)
        metacog.write_json(ij, data2)
        rc_ok = metacog.cmd_retrieve(st, ns)
        r.add("移除注入基线 → cmd_retrieve 正常(rc==0)", rc_ok == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_c10_nested_package_integrity():
    """v2.8.4 M-2 扩面：C-10 基线须覆盖全部嵌套运行时包（SCRIPT_NAMES 中带 '/' 的相对路径）。
    主 agent 直读确认 record 用 self.script_dir / name（Path 除法恰好支持嵌套路径）、verify 用 'script:' + name 键，
    二者键集合对称一致即可对任一嵌套脚本逐一检出漂移（v2.8.3 高-2 实证：旧 SCRIPT_NAMES 仅含顶层路径、永不含 '/'，
    domains/ 域模板被改 = 域迁移静默漂移，正是最该监控的）。v2.8.4 起本测试参数化遍历全部 '/' 条目
    + 断言 record/verify 键集合对称（M-3 主路径遍历 script: 键的配套防护）。"""
    r = T()
    base = Path(tempfile.mkdtemp(prefix="tr_c10_nested_"))
    try:
        sd = base / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "metacog.py").write_text("print('metacog')\n", encoding="utf-8")
        st, tmp = _new_store_inited()
        try:
            st.script_dir = sd  # 重定向到构造的 scripts 布局
            # 构造全部嵌套 '/' 条目（domains/、benchmark/）占位文件——v2.8.4 L-3 起 knowledge_transfer.py 已移出基线，自动不出现
            nested = [n for n in st.SCRIPT_NAMES if "/" in n]
            r.add("SCRIPT_NAMES 含嵌套 '/' 条目（v2.8.4 = 8 个：2 domains + 6 benchmark，去 1 死代码）",
                  len(nested) == 8)
            for n in nested:
                p = sd / n
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("# nested {}\n".format(n), encoding="utf-8")
            # record → 全部嵌套键须存在（证明含 '/' 相对路径且 record 正确落盘）
            st.record_script_integrity()
            data = metacog.read_json(st.integrity, {})
            rec_keys = set(k for k in data if k.startswith("script:"))
            r.add("record 产出全部嵌套 script: 键（含 '/' 相对路径）",
                  all(("script:" + n) in rec_keys for n in nested))
            # 对称性：record 键集合 == verify 键集合（v2.8.4 M-2 新增断言）
            ver_pairs = st.verify_script_integrity()
            ver_keys = set(k for k, _ in ver_pairs)
            r.add("record 键集合 == verify 键集合（对称一致）", rec_keys == ver_keys)
            r.add("全部嵌套脚本初始 verify 通过(ok=True)", all(ok for _, ok in ver_pairs))
            # 参数化：逐一改写-检出-还原每个嵌套条目
            for n in nested:
                fp = sd / n
                orig = fp.read_text(encoding="utf-8")
                fp.write_text("# tampered {}\n".format(n), encoding="utf-8")
                vres = st.verify_script_integrity()
                drift = [(k, ok) for (k, ok) in vres if k == "script:" + n]
                r.add("篡改 {} → verify 检出漂移(ok=False)".format(n),
                      len(drift) == 1 and drift[0][1] is False)
                fp.write_text(orig, encoding="utf-8")
                vres2 = st.verify_script_integrity()
                back = [(k, ok) for (k, ok) in vres2 if k == "script:" + n]
                r.add("还原 {} → verify 通过(ok=True)".format(n),
                      len(back) == 1 and back[0][1] is True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return r


def _c10_populate_scripts(st, sd):
    """构造 SCRIPT_NAMES 全部脚本（顶层 + 嵌套）占位文件并落盘基线。"""
    for n in st.SCRIPT_NAMES:
        p = sd / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# script {}\n".format(n), encoding="utf-8")
    st.record_script_integrity()


def _c10_inject_drift(st):
    d = metacog.read_json(st.integrity, {})
    d["script:" + st.SCRIPT_NAMES[0]] = {"hash": "deadbeef-wrong"}
    metacog.write_json(st.integrity, d)


def test_c10_orphan_key_cleanup():
    """v2.8.5 H-1：record_script_integrity 须清理孤儿键——名称不在 SCRIPT_NAMES 的 script: 键
    （如 L-3 出基线的 domains/knowledge_transfer.py）在重记后须消失，使存量安装升级不再永久 dirty。
    同时须保留"文件缺失但名称仍在 SCRIPT_NAMES"的键，使删除攻击仍可被 verify 检出。"""
    r = T()
    base = Path(tempfile.mkdtemp(prefix="tr_c10_orphan_"))
    try:
        sd = base / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        st, tmp = _new_store_inited()
        try:
            st.script_dir = sd
            _c10_populate_scripts(st, sd)
            expected_keys = {"script:" + n for n in st.SCRIPT_NAMES}
            data = metacog.read_json(st.integrity, {})
            r.add("初始 record 键集合 == SCRIPT_NAMES 键集合",
                  set(k for k in data if k.startswith("script:")) == expected_keys)
            # 注入孤儿键（模拟 v2.8.3 基线含已出基线的死代码）
            orphan = "script:domains/knowledge_transfer.py"
            data[orphan] = {"hash": "0000000000000000", "size": 0, "at": "x"}
            metacog.write_json(st.integrity, data)
            r.add("注入孤儿键后基线含该键", orphan in metacog.read_json(st.integrity, {}))
            # 重记（模拟升级后 apply/keygen 落盘）→ 孤儿须被清理
            st.record_script_integrity()
            data2 = metacog.read_json(st.integrity, {})
            r.add("重记后孤儿键被清理（H-1 闭合）", orphan not in data2)
            r.add("重记后键集合仍 == SCRIPT_NAMES",
                  set(k for k in data2 if k.startswith("script:")) == expected_keys)
            # 保留性：删一个 SCRIPT_NAMES 文件后重记，键须保留（verify 仍能检出删除）
            victim = st.SCRIPT_NAMES[0]
            (sd / victim).unlink()
            st.record_script_integrity()
            data3 = metacog.read_json(st.integrity, {})
            r.add("文件缺失的 SCRIPT_NAMES 键被保留（不误删，删除攻击可检出）",
                  ("script:" + victim) in data3)
            vmap = dict(st.verify_script_integrity())
            r.add("verify_script_integrity 对缺失文件报 False（删除检出保留）",
                  vmap.get("script:" + victim) is False)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return r


def test_c10_script_file_deletion_current_none():
    """v2.8.4 M-3 / v2.8.5 H-3②：verify_integrity 主路径遍历 script: 键，文件被删须报 (ok=False, current=None)。"""
    r = T()
    base = Path(tempfile.mkdtemp(prefix="tr_c10_del_"))
    try:
        sd = base / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        st, tmp = _new_store_inited()
        try:
            st.script_dir = sd
            _c10_populate_scripts(st, sd)
            victim = st.SCRIPT_NAMES[0]
            (sd / victim).unlink()
            rows = st.verify_integrity()
            row = [x for x in rows if x[0] == "script:" + victim]
            r.add("verify_integrity 含被删脚本行", len(row) == 1)
            if row:
                _artifact, ok_flag, _stored, current = row[0]
                r.add("被删脚本 ok=False", ok_flag is False)
                r.add("被删脚本 current=None（M-3 含文件被删情形）", current is None)
            (sd / victim).write_text("# script {}\n".format(victim), encoding="utf-8")
            rows2 = st.verify_integrity()
            row2 = [x for x in rows2 if x[0] == "script:" + victim]
            r.add("还原后被删脚本 ok=True", bool(row2) and row2[0][1] is True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return r


def test_c10_trust_root_strict_truthtable():
    """v2.8.5 附加：METACOG_TRUST_ROOT_STRICT 须严格 == '1'（与 ALLOW_LEGACY_NO_EXTERNAL_ANCHOR 一致），
    =0/'false'/未设置均不触发硬闸；=1 触发。验证 cmd_apply 硬闸真值表。"""
    r = T()
    base = Path(tempfile.mkdtemp(prefix="tr_c10_strict_"))
    try:
        sd = base / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        st, tmp = _new_store_inited()
        try:
            st.script_dir = sd
            _c10_populate_scripts(st, sd)
            ns = SimpleNamespace(id=None)
            env_key = "METACOG_TRUST_ROOT_STRICT"
            orig = _os.environ.get(env_key)
            def setenv(v):
                if v is None:
                    _os.environ.pop(env_key, None)
                else:
                    _os.environ[env_key] = v
            try:
                setenv(None); _c10_inject_drift(st)
                r.add("STRICT 未设置 + 漂移 → cmd_apply 不触发硬闸(rc!=3)",
                      metacog.cmd_apply(st, ns) != 3)
                setenv("0"); _c10_inject_drift(st)
                r.add("STRICT=0 → cmd_apply 不触发硬闸(rc!=3，truthy 旧行为已修)",
                      metacog.cmd_apply(st, ns) != 3)
                setenv("false"); _c10_inject_drift(st)
                r.add("STRICT=false → cmd_apply 不触发硬闸(rc!=3)",
                      metacog.cmd_apply(st, ns) != 3)
                setenv("1"); _c10_inject_drift(st)
                r.add("STRICT=1 → cmd_apply 硬闸拒绝(rc==3)",
                      metacog.cmd_apply(st, ns) == 3)
            finally:
                setenv(orig)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return r


def test_c10_apply_hardgate_rejects():
    """v2.8.4 M-4 / v2.8.5 M-2'：受保护模式（外部锚启用）下脚本基线漂移 → cmd_apply 硬闸拒绝(rc==3)。"""
    r = T()
    base = Path(tempfile.mkdtemp(prefix="tr_c10_applygate_"))
    try:
        sd = base / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        st, tmp = _new_store_inited()
        try:
            st.script_dir = sd
            _c10_populate_scripts(st, sd)
            _enable_external(st, tmp, "oob", root_pubkey="PUB_A")  # 受保护模式
            _c10_inject_drift(st)
            ns = SimpleNamespace(id=None)
            rc = metacog.cmd_apply(st, ns)
            r.add("外部锚启用 + 脚本漂移 → cmd_apply 硬闸拒绝(rc==3)", rc == 3)
            st.record_script_integrity()  # 修正基线
            rc2 = metacog.cmd_apply(st, ns)
            r.add("修正基线后 cmd_apply 硬闸放行(rc!=3)", rc2 != 3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return r


def test_c10_verify_dirty_includes_script_key():
    """v2.8.4 M-3 / v2.8.5 H-3⑤：cmd_verify 须把脚本基线漂移纳入 dirty 计数并返回 rc=1。"""
    r = T()
    base = Path(tempfile.mkdtemp(prefix="tr_c10_verify_"))
    try:
        sd = base / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        st, tmp = _new_store_inited()
        try:
            st.script_dir = sd
            _c10_populate_scripts(st, sd)
            rc_clean = metacog.cmd_verify(st, SimpleNamespace())
            r.add("无漂移时 cmd_verify 返回 rc=0", rc_clean == 0)
            _c10_inject_drift(st)
            rc_dirty = metacog.cmd_verify(st, SimpleNamespace())
            r.add("脚本漂移时 cmd_verify 返回 rc=1（纳入 dirty）", rc_dirty == 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return r


def test_c10_keygen_hardgate_rejects():
    """v2.8.5 M-2'：cmd_confirm --keygen（受信锚落盘）前须先核验脚本完整性；漂移 → 拒绝(rc==3)。"""
    r = T()
    base = Path(tempfile.mkdtemp(prefix="tr_c10_keygen_"))
    try:
        sd = base / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        st, tmp = _new_store_inited()
        try:
            st.script_dir = sd
            _c10_populate_scripts(st, sd)
            _enable_external(st, tmp, "oob", root_pubkey="PUB_A")  # 受保护模式
            _c10_inject_drift(st)
            restore = _with_tty_and_passphrase("pw1")
            try:
                rc = metacog.cmd_confirm(st, _keygen_ns(tmp))
                r.add("外部锚启用 + 脚本漂移 → cmd_confirm --keygen 硬闸拒绝(rc==3)", rc == 3)
            finally:
                restore()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return r


def test_c10_resign_hardgate_rejects():
    """v2.8.5 M-2' + v2.8.6 N-4：cmd_resign（受信锚落盘）前须先核验脚本完整性；漂移 → 拒绝(rc==3)。
    此前该硬闸零测试覆盖，本次补上以闭合 M-2' 对称性的验证缺口。"""
    r = T()
    base = Path(tempfile.mkdtemp(prefix="tr_c10_resign_"))
    try:
        sd = base / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        st, tmp = _new_store_inited()
        try:
            st.script_dir = sd
            _c10_populate_scripts(st, sd)
            _enable_external(st, tmp, "oob", root_pubkey="PUB_A")  # 受保护模式
            _c10_inject_drift(st)
            rc = metacog.cmd_resign(st, SimpleNamespace(id=None))
            r.add("外部锚启用 + 脚本漂移 → cmd_resign 硬闸拒绝(rc==3)", rc == 3)
            st.record_script_integrity()  # 修正基线
            rc2 = metacog.cmd_resign(st, SimpleNamespace(id=None))
            r.add("修正基线后 cmd_resign 硬闸放行(rc!=3，继续到 id 校验)", rc2 != 3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return r


def test_c10_keygen_idempotent_still_gates():
    """v2.8.6 N-3：cmd_confirm --keygen 的"已建密钥"幂等早退分支也须过完整性硬闸；
    漂移 + 受保护模式 → 拒绝(rc==3)，即便不走密钥生成路径。闭合 v2.8.5 的顺序缺陷 + 绕过。"""
    r = T()
    base = Path(tempfile.mkdtemp(prefix="tr_c10_kgid_"))
    try:
        sd = base / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        st, tmp = _new_store_inited()
        try:
            st.script_dir = sd
            _c10_populate_scripts(st, sd)
            # 预置 human_guard 使 _keys_exist=True（走幂等早退分支）
            metacog.write_json(st.human_guard, {
                "pubkey": "PUB_X", "privkey_enc": "ENC", "algo": "x", "created_at": "t"})
            _enable_external(st, tmp, "oob", root_pubkey="PUB_A")  # 受保护模式
            _c10_inject_drift(st)
            # 幂等分支：keys 已存在 + enable_external=None → 旧代码早退 rc=0（绕过）；
            # 修复后须 rc==3（过闸后再早退）。cmd_confirm 须人类 TTY 在场，测试以 _with_tty_and_passphrase 模拟。
            restore = _with_tty_and_passphrase("pw1")
            try:
                rc = metacog.cmd_confirm(st, _keygen_ns(tmp))
                r.add("已建密钥 + 漂移 + 受保护模式 → cmd_confirm --keygen 幂等分支硬闸拒绝(rc==3)", rc == 3)
                st.record_script_integrity()  # 修正基线
                rc2 = metacog.cmd_confirm(st, _keygen_ns(tmp))
                r.add("修正基线后幂等分支放行(rc==0)", rc2 == 0)
            finally:
                restore()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return r


def test_c10_gate_helper_truthtable():
    """v2.8.6 N-5/N-7：集中硬闸 helper _script_integrity_drift_if_enforced 真值表 +
    外部锚异常降级（不再静默 fail-open）。4 个调用点（apply/resign/retrieve/keygen）均委托此 helper。"""
    r = T()
    base = Path(tempfile.mkdtemp(prefix="tr_c10_helper_"))
    try:
        sd = base / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        st, tmp = _new_store_inited()
        try:
            st.script_dir = sd
            _c10_populate_scripts(st, sd)
            env_key = "METACOG_TRUST_ROOT_STRICT"
            orig = _os.environ.get(env_key)
            def setenv(v):
                if v is None:
                    _os.environ.pop(env_key, None)
                else:
                    _os.environ[env_key] = v
            try:
                setenv(None)
                r.add("无 integrity.json → 不强制(未建基线)",
                      metacog._script_integrity_drift_if_enforced(st) == (False, []))
                st.record_script_integrity()
                r.add("有基线无漂移未强制 → (False, [])",
                      metacog._script_integrity_drift_if_enforced(st) == (False, []))
                _c10_inject_drift(st)
                r.add("漂移 + 未强制 → (False, [])（不误伤）",
                      metacog._script_integrity_drift_if_enforced(st) == (False, []))
                setenv("0")
                r.add("STRICT=0 → 不强制(truthy 旧行为已修)",
                      metacog._script_integrity_drift_if_enforced(st) == (False, []))
                setenv("false")
                r.add("STRICT=false → 不强制",
                      metacog._script_integrity_drift_if_enforced(st) == (False, []))
                setenv("1")
                _enf, _drift = metacog._script_integrity_drift_if_enforced(st)
                r.add("STRICT=1 → 强制且漂移非空", _enf is True and bool(_drift))
                setenv(None)
                _enable_external(st, tmp, "oob", root_pubkey="PUB_A")
                _enf2, _drift2 = metacog._script_integrity_drift_if_enforced(st)
                r.add("外部锚启用 + 漂移 → 强制且漂移非空", _enf2 is True and bool(_drift2))
                # 异常降级：external_trust_root 抛错 → 打 warn 并 (False, [])（不再静默 fail-open）
                _orig_etr = st.external_trust_root
                def _boom():
                    raise RuntimeError("boom")
                st.external_trust_root = _boom
                try:
                    _enf3, _drift3 = metacog._script_integrity_drift_if_enforced(st)
                    r.add("外部锚检测异常 → 优雅降级 (False, [])（已 warn，非崩溃）",
                          _enf3 is False and _drift3 == [])
                finally:
                    st.external_trust_root = _orig_etr
            finally:
                setenv(orig)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return r


def test_c11_legacy_16char_baseline_compatible():
    """v2.9.0 H-1 收口（原 v2.8.7 F-1 现代化）：legacy 16-char 降级向量已强制关闭——当前版本(2,9,0)
    >= 截止期(2,9) → _legacy_hash_allowed() 恒 False，命中 16-char 旧格式即判漂移（强制迁移、降级向量封堵）。

    模拟存量基线：把首个 script: 键哈希改写为「当前内容的首 16 字符」（旧 64-bit 格式），
    验证：
      (1) verify_script_integrity 命中 16-char 旧格式 → ok=False（强制迁移，H-1 降级向量封堵）；
      (2) verify_integrity（cmd_verify 非阻塞告警路径）同判 ok=False；
      (3) STRICT=1 下硬闸对 16-char 残余基线生效（drift 非空）；
      (4) record_script_integrity 自动升级基线为 128-bit（迁移完成）；
      (5) 真实篡改即便在 16-char 基线下仍判漂移（检测不退化，与 H-1 闭环一致）。"""
    r = T()
    base = Path(tempfile.mkdtemp(prefix="tr_c11_legacy_"))
    try:
        sd = base / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        st, tmp = _new_store_inited()
        try:
            st.script_dir = sd
            _c10_populate_scripts(st, sd)  # 落盘 32-char 基线
            _name = st.SCRIPT_NAMES[0]
            _skey = "script:" + _name
            _content = (sd / _name).read_text(encoding="utf-8")
            _h32 = metacog.Store._hash_text(_content)
            _legacy16 = _h32[:16]
            # 模拟存量升级：改写基线哈希为旧 64-bit 格式（当前内容首 16 字符）
            _d = metacog.read_json(st.integrity, {})
            _d[_skey]["hash"] = _legacy16
            metacog.write_json(st.integrity, _d)
            # (1) verify_script_integrity：16-char 旧格式 → ok=False（强制迁移，H-1 降级向量封堵）
            _m = dict(st.verify_script_integrity())
            r.add("verify_script_integrity 旧 16-char 基线 → 强制迁移 ok=False(H-1 闭环)",
                  _m.get(_skey) is False)
            # (2) verify_integrity：非阻塞告警路径同判 ok=False
            _m2 = {a: ok_ for (a, ok_, *_rest) in st.verify_integrity()}
            r.add("verify_integrity 旧 16-char 基线 → ok=False(H-1 闭环)", _m2.get(_skey) is False)
            # (3) STRICT=1 下硬闸对 16-char 残余基线生效（drift 非空，倒逼重基线）
            env_key = "METACOG_TRUST_ROOT_STRICT"
            _orig = _os.environ.get(env_key)
            try:
                _os.environ[env_key] = "1"
                _enf, _drift = metacog._script_integrity_drift_if_enforced(st)
                r.add("STRICT=1 + 旧 16-char 基线 → 硬闸生效(drift 非空，强制迁移)",
                      _enf is True and bool(_drift))
            finally:
                if _orig is None:
                    _os.environ.pop(env_key, None)
                else:
                    _os.environ[env_key] = _orig
            # (5) 真实篡改即便在 16-char 基线下仍应判漂移（防退化）
            (sd / _name).write_text("# script {} TAMPERED\n".format(_name), encoding="utf-8")
            _m3 = dict(st.verify_script_integrity())
            r.add("真实篡改 + 旧 16-char 基线 → 仍判漂移(ok=False)", _m3.get(_skey) is False)
            # 还原内容，验证迁移
            (sd / _name).write_text(_content, encoding="utf-8")
            # (4) record_script_integrity 自动升级为 128-bit
            st.record_script_integrity()
            _d2 = metacog.read_json(st.integrity, {})
            r.add("record_script_integrity 自动升级基线为 128-bit(32 hex)",
                  len(_d2[_skey]["hash"]) == 32 and _d2[_skey]["hash"] == _h32)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return r





def test_c11_legacy_16char_artifact_baseline_compatible():
    """v2.9.0 H-1 收口（原 v2.8.7 F-1 盲区现代化）：非 script: 制品基线命中 16-char 旧格式 →
    强制迁移 ok=False（降级向量封堵，与 script: 分支一致）。真实篡改仍判漂移（不退化）。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        a1 = st.artifact_path("A1")
        # 记录 A1 制品基线（32-char）
        st.record_integrity("A1")
        _akey = "A1"
        _content = a1.read_text(encoding="utf-8")
        _h32 = metacog.Store._hash_text(_content)
        _legacy16 = _h32[:16]
        # 模拟存量升级：把 A1 基线哈希截为旧 64-bit 格式
        _d = metacog.read_json(st.integrity, {})
        _d[_akey]["hash"] = _legacy16
        metacog.write_json(st.integrity, _d)
        # 非 script: 分支命中 16-char 旧格式 → ok=False（H-1 降级向量封堵，强制迁移）
        _m = {a: ok_ for (a, ok_, *_rest) in st.verify_integrity()}
        r.add("verify_integrity 旧 16-char 制品基线 → 强制迁移 ok=False(H-1 闭环)",
              _m.get(_akey) is False)
        # 真实篡改仍判漂移（防退化）
        a1.write_text("# A1 TAMPERED\n", encoding="utf-8")
        _m2 = {a: ok_ for (a, ok_, *_rest) in st.verify_integrity()}
        r.add("真实篡改 + 旧 16-char 制品基线 → 仍判漂移(ok=False)", _m2.get(_akey) is False)
        # 还原并验证 record 自动升级
        a1.write_text(_content, encoding="utf-8")
        st.record_integrity("A1")
        _d2 = metacog.read_json(st.integrity, {})
        r.add("record_integrity 自动升级制品基线为 128-bit(32 hex)",
              len(_d2[_akey]["hash"]) == 32 and _d2[_akey]["hash"] == _h32)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_c11_legacy_16char_guard_baseline_compatible():
    """v2.9.0 H-1 收口（原 v2.8.8 P0-1 现代化）：cmd_verify 的 GUARD_INTEGRITY_KEY（human-guard.json）
    命中 16-char 旧格式 → 强制迁移 rc!=0（降级向量封堵）；真实篡改仍判漂移 rc==1（检测不退化）。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        # 先建一个非 GUARD 基线，确保 verify_integrity 返回 rows（GUARD 专用块才会执行）
        st.record_integrity("A1")
        # 预置 human-guard 基线
        metacog.write_json(st.human_guard, {"pubkey": {"n": "SIM_GUARD_PUB", "e": 65537}})
        st.record_guard_integrity()
        # 把 A1 与 GUARD 基线哈希截为旧 64-bit（16-char）格式，模拟存量升级
        _d = metacog.read_json(st.integrity, {})
        _d["A1"]["hash"] = metacog.Store._hash_text(
            st.artifact_path("A1").read_text(encoding="utf-8"))[:16]
        _gd = "ledger/human-guard.json"
        _d[_gd]["hash"] = metacog.Store._hash_text(
            st.human_guard.read_text(encoding="utf-8"))[:16]
        metacog.write_json(st.integrity, _d)
        # (1) 16-char 旧格式 → 强制迁移 rc!=0（H-1 降级向量封堵）
        rc1, _ = _run(metacog.cmd_verify, st, SimpleNamespace())
        r.add("P0-1 旧 16-char GUARD 基线 → cmd_verify rc!=0（强制迁移，H-1 闭环）", rc1 != 0, "rc={}".format(rc1))
        # (2) 真实篡改 human-guard 内容 → 漂移检出 rc==1
        metacog.write_json(st.human_guard, {"pubkey": {"n": "TAMPERED_GUARD_PUB", "e": 65537}})
        rc2, _ = _run(metacog.cmd_verify, st, SimpleNamespace())
        r.add("P0-1 真实篡改 human-guard → cmd_verify rc==1（漂移检出，不退化）", rc2 == 1, "rc={}".format(rc2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_v2811_hash_matches_and_proof_dir_hardening():
    """v2.8.11（H-2/M-1/L-1/L-2 + H-1 收口）防御性断言。

    覆盖 Hermes v2.8.10 复验挖出的缺陷修复：
      (1) _hash_matches 类型守卫：stored=int / stored=bytes → 不崩、返回 False（H-2 前置）；
      (2) _hash_matches(None,None) → False（L-1，不再误判 True）；
      (3) 精确匹配 → True；16-char 前缀兼容(allow_legacy=True) → True；
      (4) 16-char 前缀在 allow_legacy=False 时被拒 → False（M-1 截止期闸门真实生效）；
      (5) _external_anchor_proof_dir：rename 抛 OSError 且源仍完好 → 回退 legacy 目录（不崩）；
      (6) _external_anchor_proof_dir：rename 半程失败（源被外部删）→ 返回 new_dir 且不臆造成功（H-1）；
      (7) 双目录并存（new 已存在 + legacy 残留）→ 返回 new_dir 且 legacy 孤儿被清（L-2）。"""
    r = T()

    # (1)-(4) _hash_matches 单元断言
    HM = metacog.Store._hash_matches
    r.add("H-2 类型守卫: stored=int → False 不崩", HM(12345, "a" * 32) is False)
    r.add("H-2 类型守卫: stored=bytes → False 不崩", HM(b"abcd", "a" * 32) is False)
    r.add("L-1 (None,None) → False", HM(None, None) is False)
    r.add("精确匹配 → True", HM("a" * 32, "a" * 32) is True)
    r.add("16-char 前缀兼容(allow_legacy=True) → True", HM("a" * 16, "a" * 32, allow_legacy=True) is True)
    r.add("16-char 前缀(allow_legacy=False) 被拒 → False（M-1 闸门）", HM("a" * 16, "a" * 32, allow_legacy=False) is False)
    r.add("异内容 → False", HM("a" * 32, "b" * 32) is False)

    # (5)-(7) _external_anchor_proof_dir 行为断言
    st, tmp = _new_store_inited()
    try:
        store = st.root.parent / ".metacog-external-anchor-store"
        new_dir = store / metacog.Store._hash_text(str(st.root.resolve()))
        legacy_dir = store / metacog.Store._hash_text_legacy(str(st.root.resolve()))

        _real_rename = Path.rename

        # (5) rename 抛 OSError 且源仍完好 → 回退 legacy 目录且不崩
        legacy_dir.mkdir(parents=True, exist_ok=True)
        def _boom_intact(self, target):
            raise OSError("simulated rename failure, source intact")
        Path.rename = _boom_intact
        try:
            got = st._external_anchor_proof_dir()
            r.add("H-1 rename OSError 且源完好 → 回退 legacy 目录且不崩",
                  got == legacy_dir and legacy_dir.exists())
        finally:
            Path.rename = _real_rename

        # (6) rename 半程失败（源在 rename 中被外部删）→ 返回 new_dir 且不臆造成功（H-1）
        if legacy_dir.exists():
            legacy_dir.rmdir()
        def _boom_delete(self, target):
            # 模拟迁移半程失败：源在 rename 中被外部删除，rename 抛 OSError
            try:
                if self.exists():
                    if self.is_dir():
                        self.rmdir()
                    else:
                        self.unlink()
            except Exception:
                pass
            raise OSError("simulated half-way rename failure")
        Path.rename = _boom_delete
        try:
            got2 = st._external_anchor_proof_dir()
            r.add("H-1 rename 半程失败(源已删) → 返回 new_dir 且不臆造成功（诚实 fail-closed）",
                  got2 == new_dir)
        finally:
            Path.rename = _real_rename

        # (7) 双目录并存（new 已存在 + legacy 残留[均空]）→ 返回 new_dir 且 legacy 孤儿被清（L-2）
        new_dir.mkdir(parents=True, exist_ok=True)
        legacy_dir.mkdir(parents=True, exist_ok=True)
        got3 = st._external_anchor_proof_dir()
        r.add("L-2 双目录并存(均空) → 返回 new_dir", got3 == new_dir)
        r.add("L-2 双目录并存(均空) → legacy 孤儿被清理", not legacy_dir.exists())
        # (8) D-1：双目录均含内容 / new 空 legacy 非空 → 绝不静默删非空 legacy，保基线
        new_dir.mkdir(parents=True, exist_ok=True)
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (new_dir / "root-pubkey.pem").write_text("NEW_BASELINE", encoding="utf-8")
        (legacy_dir / "root-pubkey.pem").write_text("LEGACY_BASELINE", encoding="utf-8")
        got4 = st._external_anchor_proof_dir()
        r.add("D-1 双目录均非空 → 返回 new_dir", got4 == new_dir)
        r.add("D-1 双目录均非空 → legacy 不被静默删除（保基线）", legacy_dir.exists())
        # 8b: new 空 + legacy 非空 → 优先返回 legacy，legacy 不被删
        shutil.rmtree(new_dir, ignore_errors=True)
        new_dir.mkdir(parents=True, exist_ok=True)  # 空 new
        got5 = st._external_anchor_proof_dir()
        r.add("D-1 new 空 legacy 非空 → 返回 legacy", got5 == legacy_dir)
        r.add("D-1 new 空 legacy 非空 → legacy 不被删", legacy_dir.exists())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_v2811_proof_dir_record_flag():
    """v2.8.11 补丁（D-1 幂等）：_external_anchor_proof_dir 的 record 形参控制 ledger 写入。
    record=True（写路径）→ 异常态追加 legacy_orphan_kept；record=False（verify 只读路径）→ 零写入。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        store = st.root.parent / ".metacog-external-anchor-store"
        new_dir = store / metacog.Store._hash_text(str(st.root.resolve()))
        legacy_dir = store / metacog.Store._hash_text_legacy(str(st.root.resolve()))
        new_dir.mkdir(parents=True, exist_ok=True)
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (new_dir / "root-pubkey.pem").write_text("NEW", encoding="utf-8")
        (legacy_dir / "root-pubkey.pem").write_text("LEGACY", encoding="utf-8")
        audit = st.root / "ledger" / "migration-audit.jsonl"

        def _cnt():
            if not audit.exists():
                return 0
            return len([l for l in audit.read_text().splitlines() if l.strip()])

        # record=True（写路径）→ 双目录均非空 → legacy_orphan_kept 写入 1 条
        st._external_anchor_proof_dir(record=True)
        r.add("D-1 record=True（写路径）→ 异常态追加 1 条 ledger", _cnt() == 1)
        # record=False（verify 只读路径）→ 零新增
        st._external_anchor_proof_dir(record=False)
        r.add("D-1 record=False（verify 只读）→ 零 ledger 写入", _cnt() == 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_v2811_external_anchor_verify_idempotent():
    """v2.8.11 补丁（D-1 幂等回归）：verify 只读路径 _external_anchor_deleted 连续两次调用，
    migration-audit.jsonl 条目数不变（闭合 Hermes 复验挖出的『verify 非幂等写 ledger』回归）。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        store = st.root.parent / ".metacog-external-anchor-store"
        new_dir = store / metacog.Store._hash_text(str(st.root.resolve()))
        legacy_dir = store / metacog.Store._hash_text_legacy(str(st.root.resolve()))
        new_dir.mkdir(parents=True, exist_ok=True)
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (new_dir / "root-pubkey.pem").write_text("NEW", encoding="utf-8")
        (legacy_dir / "root-pubkey.pem").write_text("LEGACY", encoding="utf-8")
        # 完整基线 + 哨兵 + 锚文件，使 _external_anchor_deleted 走通 L969 全路径
        anchor_hash = metacog.Store._hash_text("ANCHOR_CONTENT")
        sentinel_hash = metacog.Store._hash_text("SENTINEL_CONTENT")
        (new_dir / ".external-anchor-baseline.json").write_text(json.dumps({
            metacog.Store.EXTERNAL_ANCHOR_JSON_KEY: {"hash": anchor_hash, "size": 1, "at": "t"},
            metacog.Store.EXTERNAL_ANCHOR_SENTINEL_KEY: {"hash": sentinel_hash, "size": 1, "at": "t"},
        }), encoding="utf-8")
        (st.root / "ledger" / "trust-root.json").write_text("ANCHOR_CONTENT", encoding="utf-8")
        (st.root / "ledger" / ".external-anchor-enabled").write_text("SENTINEL_CONTENT", encoding="utf-8")
        audit = st.root / "ledger" / "migration-audit.jsonl"

        def _cnt():
            if not audit.exists():
                return 0
            return len([l for l in audit.read_text().splitlines() if l.strip()])

        before = _cnt()
        st._external_anchor_deleted()
        st._external_anchor_deleted()
        after = _cnt()
        r.add("D-1 verify 只读路径(_external_anchor_deleted) 两次调用 ledger 条目数不变（幂等）", before == after)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_v2811_migration_audit_hmac_coverage():
    """v2.8.11 补丁（D-2 断言）：_verify_migration_audit 逐条 HMAC + 链连续性覆盖。
    诚实边界：无外部总数锚，尾部有效子链截断不保证检出（D-2 残余，v2.9.0 签名化迁移根治）。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        audit = st.root / "ledger" / "migration-audit.jsonl"
        audit.parent.mkdir(parents=True, exist_ok=True)
        key = metacog._audit_hmac_key(st)

        def _mk(event, prev):
            e = {"at": "t", "operation": "external-anchor-proof-dir-migration",
                 "epoch": metacog.LEDGER_KEY_EPOCH,
                 "event": event, "src": "s", "dst": "d", "detail": ""}
            e["prev_hmac"] = prev
            payload = json.dumps({k: v for k, v in e.items() if k != "hmac"},
                                separators=(",", ":"), sort_keys=True)
            e["hmac"] = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
            return e

        e1 = _mk("e1", "")
        e2 = _mk("e2", e1["hmac"])

        def _write(entries):
            audit.write_text(
                "\n".join(json.dumps(e, separators=(",", ":"), sort_keys=True) for e in entries) + "\n",
                encoding="utf-8")

        _write([e1, e2])
        ok, cnt = st._verify_migration_audit()
        r.add("D-2 有效链(2条) → ok=True,count=2", ok is True and cnt == 2)

        # 篡改末条 payload：保留旧 HMAC，改 event → HMAC 不匹配
        lines = [json.dumps(e1, separators=(",", ":"), sort_keys=True),
                 json.dumps(e2, separators=(",", ":"), sort_keys=True)]
        e2c = json.loads(lines[1])
        e2c["event"] = "e2-TAMPERED"  # 改内容但 HMAC 未重算
        lines[1] = json.dumps(e2c, separators=(",", ":"), sort_keys=True)
        audit.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok2, _ = st._verify_migration_audit()
        r.add("D-2 篡改末条 payload(保留旧 HMAC) → HMAC 不匹配 → ok=False", ok2 is False)

        # 前插伪造条目（epoch 标记 + prev_hmac='' 但 HMAC 错误）→ 链首 HMAC 校验失败
        forged = {"at": "t", "operation": "x", "event": "FORGED", "src": "s",
                  "dst": "d", "detail": "", "epoch": metacog.LEDGER_KEY_EPOCH,
                  "prev_hmac": "", "hmac": "deadbeef"}
        _write([forged, e1, e2])
        ok3, _ = st._verify_migration_audit()
        r.add("D-2 前插伪造条目(错误 HMAC) → ok=False", ok3 is False)

        # 非 dict 行（JSON 数组）→ 不抛 AttributeError 且 ok=False
        _write([e1, e2])
        audit.write_text("[1,2,3]\n" + audit.read_text(), encoding="utf-8")
        ok4, _ = st._verify_migration_audit()
        r.add("D-2 非 dict 行(数组) → 不抛异常且 ok=False", ok4 is False)

        # 非法 JSON 行 → 不抛异常且 ok=False
        audit.write_text("not-json-line\n" + audit.read_text(), encoding="utf-8")
        ok5, _ = st._verify_migration_audit()
        r.add("D-2 非法 JSON 行 → 不抛异常且 ok=False", ok5 is False)

        # dict 缺 prev_hmac → 链不连续 → ok=False
        miss = {"at": "t", "operation": "x", "event": "E", "src": "s",
                "dst": "d", "detail": "", "hmac": "x"}
        _write([miss, e1, e2])
        ok6, _ = st._verify_migration_audit()
        r.add("D-2 dict 缺 prev_hmac → 链不连续 → ok=False", ok6 is False)

        # N-1 字段类型守卫（P1-1，r4 新挖）：hmac/prev_hmac 非字符串（JSON null / 数字）
        # → 经新增字符串类型守卫 fail-closed 返回 ok=False，不抛 TypeError 打穿硬闸
        for _tag, _mut in (
            ("hmac:null", lambda _e: _e.__setitem__("hmac", None)),
            ("hmac:int", lambda _e: _e.__setitem__("hmac", 123)),
            ("hmac:empty", lambda _e: _e.__setitem__("hmac", "")),
            ("prev_hmac:null", lambda _e: _e.__setitem__("prev_hmac", None)),
        ):
            e1n = json.loads(json.dumps(e1, separators=(",", ":"), sort_keys=True))
            _mut(e1n)
            _write([e1n, e2])
            try:
                ok_n1, _ = st._verify_migration_audit()
                r.add("N-1 {} → 不抛异常且 ok=False".format(_tag), ok_n1 is False, "ok={}".format(ok_n1))
            except Exception as _exc:
                r.add("N-1 {} → 不抛 TypeError".format(_tag), False, "exception={}".format(repr(_exc)))

        # M-1 写侧读点守卫（r5 新挖）：migration 末行 hmac:null → 写侧不再固化 prev_hmac=None
        audit.write_text(
            '{"at":"t","operation":"x","event":"E0","src":"s","dst":"d","detail":"",'
            '"prev_hmac":null,"hmac":null}\n', encoding="utf-8")
        st._record_migration_audit("E-M1", "s2", "d2", "")
        _m1l = [l for l in audit.read_text(encoding="utf-8").splitlines() if l.strip()]
        _m1rec = json.loads(_m1l[-1])
        r.add("M-1 写侧 hmac:null → migration 新条目 prev_hmac 为 <broken>(str,非None)",
              isinstance(_m1rec.get("prev_hmac"), str) and _m1rec.get("prev_hmac") == "<broken>",
              "prev_hmac={}".format(_m1rec.get("prev_hmac")))
        _ok_m1, _cnt_m1 = st._verify_migration_audit()
        r.add("M-1 写侧污染被下游 _verify_migration_audit 捕获 → (False,*)", _ok_m1 is False, "ok={}".format(_ok_m1))

        # 已知限制（D-2 残余）：无外部总数锚，尾部有效子链截断仍 ok=True
        _write([e1])  # 截断末条 e2
        ok7, cnt7 = st._verify_migration_audit()
        r.add("D-2[已知限制] 尾部有效子链截断 → 仍 ok=True（无外部总数锚，v2.9.0 根治）", ok7 is True and cnt7 == 1)

        # 旧版（<v2.9.0）无 epoch 链：v2.11.0 起容忍期已过 → fail-closed（H-C 收口，杜绝永久降级信任底线）。
        # 结构性损坏同样 fail-closed（见上文 N-1 / 非 dict / 非法 JSON 断言）。
        # 过渡演示：在「截止期前版本」(cutoff 覆盖为晚于当前的 (2,17)) 旧链仍容忍，证明 tolerance 仅在
        # CURRENT >= LEGACY_AUDIT_CHAIN_CUTOFF 后失效（非无条件收紧）。
        _legacy_chain = [
            json.dumps({k: v for k, v in json.loads(json.dumps(e1, separators=(",", ":"), sort_keys=True)).items()
                        if k != "epoch"}, separators=(",", ":"), sort_keys=True),
            json.dumps({k: v for k, v in json.loads(json.dumps(e2, separators=(",", ":"), sort_keys=True)).items()
                        if k != "epoch"}, separators=(",", ":"), sort_keys=True),
        ]
        audit.write_text("\n".join(_legacy_chain) + "\n", encoding="utf-8")
        ok8, cnt8 = st._verify_migration_audit()
        r.add("C-10 v2.11.0 旧版无 epoch 链(结构合法) → fail-closed ok=False [H-C 收口]", ok8 is False and cnt8 == 2)
        # 过渡演示（cutoff 覆盖为 (2,17)，模拟截止期前版本）
        ok8t, cnt8t = st._verify_migration_audit(cutoff=(2, 26))
        r.add("C-10 截止期前(cutoff=2,23) 旧链仍容忍 ok=True（过渡演示）", ok8t is True and cnt8t == 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_v2811_integrity_chain_ok_guard():
    """v2.8.11 补丁（D-3 断言）：_integrity_chain_ok 逐条 dict 守卫 + 链连续性。
    覆盖：有效链 + 尾 hash 不符 + 尾 key 不符 + 中间 prev 被改 + 非 dict 行(不抛 AttributeError) +
    非法 JSON 行 + 空链(向后兼容)。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        chain = st.root / "ledger" / "integrity-chain" / "chain.jsonl"
        chain.parent.mkdir(parents=True, exist_ok=True)

        def _mk(hashv, key, prev):
            return {"prev": prev, "hash": hashv, "key": key}

        def _write(entries):
            chain.write_text(
                "\n".join(json.dumps(e, separators=(",", ":"), sort_keys=True) for e in entries) + "\n",
                encoding="utf-8")

        e1 = _mk("h1", "k", "")
        e2 = _mk("h2", "k", "h1")
        _write([e1, e2])
        r.add("D-3 有效链且尾 key/hash 匹配 → True", st._integrity_chain_ok("k", "h2") is True)
        r.add("D-3 尾 hash 不符 → False", st._integrity_chain_ok("k", "WRONG") is False)
        r.add("D-3 尾 key 不符 → False", st._integrity_chain_ok("other", "h2") is False)

        # 中间条目 prev 被改 → 链断
        lines = [json.dumps(e1, separators=(",", ":"), sort_keys=True),
                 json.dumps(e2, separators=(",", ":"), sort_keys=True)]
        e2b = json.loads(lines[1])
        e2b["prev"] = "BROKEN"
        lines[1] = json.dumps(e2b, separators=(",", ":"), sort_keys=True)
        chain.write_text("\n".join(lines) + "\n", encoding="utf-8")
        r.add("D-3 中间条目 prev 被改 → 链断 → False", st._integrity_chain_ok("k", "h2") is False)

        # 非 dict 行（数组）→ 不抛 AttributeError 且 False
        chain.write_text("[1,2,3]\n" + chain.read_text(), encoding="utf-8")
        r.add("D-3 非 dict 行(数组) → 不抛异常且 False", st._integrity_chain_ok("k", "h2") is False)

        # 非法 JSON 行 → 不抛异常且 False
        chain.write_text("garbage-line\n" + chain.read_text(), encoding="utf-8")
        r.add("D-3 非法 JSON 行 → 不抛异常且 False", st._integrity_chain_ok("k", "h2") is False)

        # 空链文件 → True（向后兼容，v2.5.8 前无链）
        chain.write_text("", encoding="utf-8")
        r.add("D-3 空链文件 → True(向后兼容)", st._integrity_chain_ok("k", "h2") is True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_f4_manifest_integrity_domain():
    """v2.8.9 ⑤ 收口 F-4 纸面闭环（Hermes H-01）：可信清单分文件硬闸。验证：
      (1) record_script_integrity 写入 manifest: 键（含 SKILL.md@body 派生键）；
      (2) 手改 SKILL.md 正文 → verify_integrity 判 manifest:SKILL.md 漂移(ok=False)；
      (3) 该漂移进硬闸（_manifest_integrity_drift_if_enforced 在 STRICT 下含 manifest:SKILL.md）；
      (3b) 仅改 SKILL.md 版本号（正文不变）→ 硬闸豁免（不阻断、不 dirty）；
      (3c) 手改 CONTRACT.md → 硬闸阻断；手改 CHANGELOG.md → 硬闸豁免（非阻断，仅 dirty）；
      (4) 重新 record 后 manifest:SKILL.md 恢复 ok=True（迁移/重基线自愈）。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        for _mn in st.MANIFEST_NAMES:
            (st.root / _mn).write_text("# manifest {}\n".format(_mn), encoding="utf-8")
        (st.root / "SKILL.md").write_text("---\nname: x\nversion: 2.8.8\n---\n# body\n", encoding="utf-8")
        (st.root / "CHANGELOG.md").write_text("# changelog\n", encoding="utf-8")
        (st.root / "CONTRACT.md").write_text("# contract\n", encoding="utf-8")
        (st.root / "HANDOFF.md").write_text("# handoff\n", encoding="utf-8")
        (st.root / "pack.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        st.record_script_integrity()
        _d = metacog.read_json(st.integrity, {})
        r.add("F-4 record 写入 manifest:SKILL.md 键", "manifest:SKILL.md" in _d)
        r.add("F-4 record 写入 manifest:SKILL.md@body 派生键", "manifest:SKILL.md@body" in _d)
        r.add("F-4 全部 MANIFEST_NAMES 写入 manifest: 键",
              all(("manifest:" + n) in _d for n in st.MANIFEST_NAMES))
        # (2) 手改 SKILL.md 正文 → 检测漂移
        (st.root / "SKILL.md").write_text("---\nname: x\nversion: 2.8.8\n---\n# body TAMPERED\n", encoding="utf-8")
        _rows = {a: ok_ for (a, ok_, *_rest) in st.verify_integrity()}
        r.add("F-4 手改 SKILL.md 正文 → verify_integrity 判 manifest:SKILL.md 漂移(ok=False)",
              _rows.get("manifest:SKILL.md") is False)
        # (3)(3b)(3c) 硬闸行为（STRICT 下强制）
        _orig = _os.environ.get("METACOG_TRUST_ROOT_STRICT")
        try:
            _os.environ["METACOG_TRUST_ROOT_STRICT"] = "1"
            _enf, _drift = metacog._manifest_integrity_drift_if_enforced(st)
            r.add("F-4 手改 SKILL.md 正文 → 硬闸 drift 含 manifest:SKILL.md（阻断）",
                  _enf is True and "manifest:SKILL.md" in _drift)
            _se, _sdrift = metacog._script_integrity_drift_if_enforced(st)
            r.add("F-4 手改清单 → 脚本硬闸 drift 为空（不影响 script: 域）",
                  _se is True and _sdrift == [])
            # (3b) 仅版本号变更 → 硬闸豁免
            (st.root / "SKILL.md").write_text("---\nname: x\nversion: 2.8.9\n---\n# body\n", encoding="utf-8")
            _enf2, _drift2 = metacog._manifest_integrity_drift_if_enforced(st)
            r.add("F-4 仅版本号变更 → 硬闸豁免（不含 manifest:SKILL.md）",
                  _enf2 is True and "manifest:SKILL.md" not in _drift2)
            _rows_v = {a: ok_ for (a, ok_, *_rest) in st.verify_integrity()}
            r.add("F-4 仅版本号变更 → verify_integrity manifest:SKILL.md ok=True（不 dirty）",
                  _rows_v.get("manifest:SKILL.md") is True)
            # (3c) CONTRACT 阻断 / CHANGELOG 非阻断
            (st.root / "CONTRACT.md").write_text("# contract TAMPERED\n", encoding="utf-8")
            (st.root / "CHANGELOG.md").write_text("# changelog TAMPERED\n", encoding="utf-8")
            _enf3, _drift3 = metacog._manifest_integrity_drift_if_enforced(st)
            r.add("F-4 手改 CONTRACT.md → 硬闸 drift 含 manifest:CONTRACT.md（阻断）",
                  "manifest:CONTRACT.md" in _drift3)
            r.add("F-4 手改 CHANGELOG.md → 硬闸豁免（不含 manifest:CHANGELOG.md）",
                  "manifest:CHANGELOG.md" not in _drift3)
            _rows_c = {a: ok_ for (a, ok_, *_rest) in st.verify_integrity()}
            r.add("F-4 手改 CHANGELOG.md → verify_integrity 仍判漂移(ok=False, dirty 计数)",
                  _rows_c.get("manifest:CHANGELOG.md") is False)
        finally:
            if _orig is None:
                _os.environ.pop("METACOG_TRUST_ROOT_STRICT", None)
            else:
                _os.environ["METACOG_TRUST_ROOT_STRICT"] = _orig
        # (4) 重基线自愈
        (st.root / "SKILL.md").write_text("---\nname: x\nversion: 2.8.9\n---\n# body\n", encoding="utf-8")
        st.record_script_integrity()
        _rows2 = {a: ok_ for (a, ok_, *_rest) in st.verify_integrity()}
        r.add("F-4 重新 record 后 manifest:SKILL.md 恢复 ok=True", _rows2.get("manifest:SKILL.md") is True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_legacy_window_governance():
    """v2.8.9 ④：P0-1 legacy 16-char 窗口治理——硬切截止期 + 迁移计数器。
      (1) 当前版本(2.8.9) < 截止期(2.9) → _legacy_hash_allowed() 为 True（legacy 兼容生效）；
      (2) 模拟过截止期（cutoff=(2,8)）→ _legacy_hash_allowed() 为 False；
      (3) _script_hash_matches(cur, 16char, allow_legacy=False) → (False, True)（强制迁移判漂移）；
      (4) 存量 16-char 基线经 record_script_integrity 升级为 32-char → __meta__.legacy_migrated 递增、legacy_remaining 收紧；
      (5) __meta__.legacy_remaining 正确统计无文件的 16-char 残余键。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        r.add("④ 当前版本(2.9.0) >= 截止期(2.9) → legacy 拒绝(强制迁移)", metacog.Store._legacy_hash_allowed() is False)
        r.add("④ 模拟过截止期(cutoff 2.8) → legacy 拒绝", metacog.Store._legacy_hash_allowed(cutoff=(2, 8)) is False)
        r.add("④ 过截止期后 16-char 命中判漂移(False,True)",
              metacog.Store._script_hash_matches("a" * 32, "a" * 16, allow_legacy=False) == (False, True))
        for _mn in st.MANIFEST_NAMES:
            (st.root / _mn).write_text("# manifest {}\n".format(_mn), encoding="utf-8")
        st.record_script_integrity()
        _d = metacog.read_json(st.integrity, {})
        _d["manifest:CONTRACT.md"]["hash"] = metacog.Store._hash_text(
            (st.root / "CONTRACT.md").read_text(encoding="utf-8"))[:16]
        metacog.write_json(st.integrity, _d)
        st.record_script_integrity()  # 升级该 16-char 基线为 32-char
        _d2 = metacog.read_json(st.integrity, {})
        r.add("④ 16-char→32-char 迁移计数 legacy_migrated 递增", _d2.get("__meta__", {}).get("legacy_migrated", 0) >= 1)
        r.add("④ 迁移后 CONTRACT.md 基线恢复 32-char", len(_d2["manifest:CONTRACT.md"]["hash"]) == 32)
        r.add("④ legacy_remaining 不含已迁移键", _d2.get("__meta__", {}).get("legacy_remaining", 1) == 0)
        # (5) 删除 HANDOFF.md 文件 → 其 16-char 残余键不被 record 覆盖、计入 legacy_remaining
        (st.root / "HANDOFF.md").unlink()
        _d2b = metacog.read_json(st.integrity, {})
        _d2b["manifest:HANDOFF.md"]["hash"] = "c" * 16
        metacog.write_json(st.integrity, _d2b)
        st.record_script_integrity()
        _d3 = metacog.read_json(st.integrity, {})
        r.add("④ legacy_remaining 统计无文件 16-char 残余键", _d3.get("__meta__", {}).get("legacy_remaining", 0) == 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_c11_default_failclosed_and_optout():
    """v2.8.2 C-11 硬化（默认 fail-closed）：默认（无 METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR）下，
    未启用外部锚(legacy) → build_trust_root 返 DenyTrustRoot('external-anchor-required')（fail-closed 默认）。
    - ① 默认（撤销全局逃生舱）+ 空目录 legacy → DenyTrustRoot('external-anchor-required')。
    - ② 设逃生舱 METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1 → legacy 回落 None（向后兼容逃生舱生效）。
    - ③ 已启用外部锚（真实离线根公钥）→ 正常 provider（不被默认 deny 误伤）。"""
    r = T()
    env_key = "METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"
    orig = _os.environ.get(env_key)
    td = Path(tempfile.mkdtemp(prefix="tr_c11_"))
    try:
        # ① 默认：撤销全局逃生舱 → legacy 须 fail-closed
        _os.environ.pop(env_key, None)
        cfg = trust_root.TrustRootConfig.load(td)
        root = trust_root.build_trust_root(cfg)
        r.add("默认(无逃生舱) + legacy空目录 → DenyTrustRoot(required)",
              root is not None and root.name == "deny"
              and getattr(root, "reason", "") == "external-anchor-required")
        # ② 逃生舱：显式允许 legacy → 回落 None（向后兼容）
        _os.environ[env_key] = "1"
        cfg_l = trust_root.TrustRootConfig.load(td)
        root_l = trust_root.build_trust_root(cfg_l)
        r.add("逃生舱 ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1 → legacy 回落 None", root_l is None)
        # ④ 严格 == "1" 判定（Hermes v2.8.2 高-1 回归）：非 "1" 值（如 "0"/"false"/"off"）不得解除强制力
        _os.environ[env_key] = "0"
        cfg_z = trust_root.TrustRootConfig.load(td)
        root_z = trust_root.build_trust_root(cfg_z)
        r.add("逃生舱=0（非'1'）不解除强制力 → 仍 DenyTrustRoot(required)",
              root_z is not None and root_z.name == "deny"
              and getattr(root_z, "reason", "") == "external-anchor-required")
        _os.environ.pop(env_key, None)  # 还原为撤销态，继续 ③
        # ③ 正常启用（真实离线根公钥）→ 不受影响，构建正常 provider
        pub, _priv = trust_root.gen_offline_root_keypair()
        trust_root.write_trust_root_config(td, "oob", root_pubkey=pub)
        cfg2 = trust_root.TrustRootConfig.load(td)
        root2 = trust_root.build_trust_root(cfg2)
        r.add("已启用外部锚(真实公钥) → 正常 provider（不被默认 deny 误伤）",
              root2 is not None and root2.name != "deny")
    finally:
        if orig is None:
            _os.environ.pop(env_key, None)
        else:
            _os.environ[env_key] = orig
        shutil.rmtree(td, ignore_errors=True)
    return r


def test_load_recursionerror_failclosed():
    """v2.6.5 P1-④ + v2.6.6 强化：病态超深嵌套 JSON 曾令 load() 逸出未捕获 RecursionError；
    现捕获后标记 corrupt → DenyTrustRoot（fail-closed）。v2.6.6 扩展多形状参数化（[]/{}、混合、200k 层）。"""
    r = T()
    shapes = [
        ("list-50k", "[" * 50000 + "]" * 50000),
        ("dict-50k", "{" * 50000 + "}" * 50000),
        ("mixed-25k", "[" * 25000 + "{" * 25000 + "}" * 25000 + "]" * 25000),
        ("list-200k", "[" * 200000 + "]" * 200000),
    ]
    for label, deep in shapes:
        td = Path(tempfile.mkdtemp(prefix="tr_rec_"))
        try:
            (td / "ledger").mkdir(parents=True, exist_ok=True)
            (td / "ledger" / "trust-root.json").write_text(deep, encoding="utf-8")
            cfg = trust_root.TrustRootConfig.load(td)
            root = trust_root.build_trust_root(cfg)
            r.add(f"{label} → corrupt 恒拒（不逸出 RecursionError）",
                  cfg.corrupt is True and root is not None and root.name == "deny")
        finally:
            shutil.rmtree(td, ignore_errors=True)
    return r


def test_attestation_ok_malformed_input_failclosed():
    """v2.6.6（强化）+ v2.7.0：attestation_ok 须对任何损坏输入 fail-closed（返回 (False, reason)，
    不逸出异常）。覆盖：非法 base64 字符串 / 非字符串签名(None/int/list/dict/bool) /
    顶层非 dict JSON（array/string/number/null）。"""
    r = T()
    cases = [
        ("malformed-base64", {"committed_pubkey": "P", "contract_fingerprint": "cf", "signature": "not!!valid==base64"}),
        ("bad-padding", {"committed_pubkey": "P", "contract_fingerprint": "cf", "signature": "abc"}),
        ("signature-none", {"committed_pubkey": "P", "contract_fingerprint": "cf", "signature": None}),
        ("signature-int", {"committed_pubkey": "P", "contract_fingerprint": "cf", "signature": 12345}),
        ("signature-list", {"committed_pubkey": "P", "contract_fingerprint": "cf", "signature": [1, 2]}),
        ("signature-dict", {"committed_pubkey": "P", "contract_fingerprint": "cf", "signature": {"x": 1}}),
        ("signature-bool", {"committed_pubkey": "P", "contract_fingerprint": "cf", "signature": True}),
        ("top-array", ["P", "x"]),
        ("top-string", "hello"),
        ("top-number", 12345),
        ("top-null", None),
    ]
    pub_off, _ = _offline_root()
    for label, content in cases:
        td = Path(tempfile.mkdtemp(prefix="tr_att_"))
        try:
            ap = td / "attest.json"
            ap.write_text(json.dumps(content), encoding="utf-8")
            root = trust_root.HsmTrustRoot(str(ap), trust_root.RsaRootVerifierProvider(pub_off))
            try:
                res = root.attestation_ok("P")  # 任何损坏输入须返回元组，不逸出异常
                r.add(f"{label} → fail-closed 不逸出异常",
                      isinstance(res, tuple) and res[0] is False)
            except BaseException as e:
                r.add(f"{label} → 逸出异常 {type(e).__name__}", False)
        finally:
            shutil.rmtree(td, ignore_errors=True)
    return r


def test_attestation_contract_mismatch():
    """v2.7.0：设备证明的 contract_fingerprint 须与 CONTRACT.md 钉固指纹一致；不一致 → fail-closed。
    防止攻击者用合法离线根签名、但套用不同契约（换公钥 + 改契约的协同攻击）。"""
    r = T()
    pub = '{"n":"P","e":65537}'
    pub_off, priv_off = _offline_root()
    verifier = trust_root.RsaRootVerifierProvider(pub_off)
    td = Path(tempfile.mkdtemp(prefix="tr_cf_"))
    try:
        att = str(td / "attest.json")
        # 合法签名但契约指纹不符 → 拒绝
        trust_root.write_root_attestation(att, pub, "WRONG-CONTRACT-FP", priv_off)
        hsm = trust_root.HsmTrustRoot(att, verifier)
        r.add("attestation contract mismatch → fail-closed",
              hsm.attestation_ok(pub, contract_fingerprint="EXPECTED-FP") == (False, "attestation-contract-mismatch"))
        # 契约指纹一致 → 通过
        trust_root.write_root_attestation(att, pub, "EXPECTED-FP", priv_off)
        r.add("attestation contract match → pass",
              hsm.attestation_ok(pub, contract_fingerprint="EXPECTED-FP") == (True, None))
        # 不传 contract_fingerprint → 仅校公钥+签名（独立 hsm 姿态向后兼容）
        r.add("attestation w/o cf → pass (only pub+signature)",
              hsm.attestation_ok(pub) == (True, None))
    finally:
        shutil.rmtree(td, ignore_errors=True)
    return r


if __name__ == "__main__":
    sys.exit(main())
