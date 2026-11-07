#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.27.17（C-01 专项）收口回归测试套件：删除源码内嵌默认锚 + H-01 逃生舱删除 + H-05 硬闸默认开
+ M-01 锚密钥校验 + M-03 特权令牌双 env + approval_message v2 长度前缀/nonce 化。

覆盖（对应审计建议 #11 与路线图 §6）：
  1. 源码卫生：trust_root.py 无 _TRUST_ROOT_ANCHOR_KEY_DEFAULT 常量、metacog.py 无
     _LEDGER_ANCHOR_DEFAULT 常量（默认锚字面量彻底删除，「宁可装不上，不可自签」）。
  2. 锚密钥 env-only（C-1a）：未配置 → get_anchor_key() 返 None；非法 base64 / <32 字节 →
     ValueError fail-closed（M-01，不回落任何默认锚）；合法专属密钥 → 正常返回。
  3. H-01 删除：build_trust_root 对 legacy/disabled 恒返 DenyTrustRoot('external-anchor-required')，
     METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1 已无效（no-op）。
  4. check_pubkey_root 语义细分（H-01 删除的连带收口）：纯未配置回落 legacy CONTRACT 钉固分支
     （pinned==live → True）；corrupt 配置仍 fail-closed。
  5. _resolve_anchor_key 未配置 → LedgerAnchorDefaultError（fail-closed 拒绝启动）。
  6. M-03：freeze anchor-init 无 EXPECTED 令牌 → REFUSED（rc=2），令牌不再存于代码字面量。
  7. 签名 v2 格式（L-06/nonce）：bind → verify 往返；nonce 化使每次签名互异；
     已消费签名重放被拒（use-once 账本按签名串消费）。

零第三方依赖。运行需专属 METACOG_TRUST_ROOT_ANCHOR_KEY（本文件自行 setdefault 测试密钥）。
锚点定向临时文件，不污染真实树外锚。
"""
import base64
import contextlib
import io
import json
import os as _os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

TEST_ANCHOR_KEY = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"

sys.path.insert(0, str(Path(__file__).parent))
import metacog
import sigcrypto
import trust_root
import freeze as freeze_mod

# 全套件统一测试锚密钥（standalone 可跑；与 _run_all_tests.py 全局口径一致）
_os.environ.setdefault("METACOG_TRUST_ROOT_ANCHOR_KEY", TEST_ANCHOR_KEY)
# 隔离：freeze 锚点指向临时文件
_os.environ["METACOG_FREEZE_ANCHOR"] = str(Path(tempfile.gettempdir()) / "metacog_c01_test_anchor.anchor")
# ⚠️ 必须在模块级、任何 _clean_freeze_state() 调用之前重定向 FREEZE_FILE/SKILL_ROOT——
# 否则 _clean_freeze_state() 会删掉真实技能树的 frozen-hashes.jsonl（v2.27.17 开发期实测踩坑：
# 函数内重定向晚于首次清理，误删真实账本；与 test-v2170-h3-closure.py 的模块级重定向同款防御）。
freeze_mod.SKILL_ROOT = Path(tempfile.mkdtemp(prefix="c01_freeze_root_"))
freeze_mod.FREEZE_FILE = freeze_mod.SKILL_ROOT / "frozen-hashes.jsonl"


class T:
    def __init__(self, name):
        self.name = name
        self.passed = 0
        self.failed = 0

    def add(self, name, ok, detail=""):
        self.passed += ok
        self.failed += (not ok)
        print("  [{}] {}{}".format("PASS" if ok else "FAIL", name,
                                    (" - " + detail) if detail else ""))

    def summary(self):
        total = self.passed + self.failed
        print("\n  -- {}: {}/{} PASS".format(self.name, self.passed, total))
        return self.failed == 0


def _clean_freeze_state():
    freeze_mod.FREEZE_FILE.unlink(missing_ok=True)
    try:
        freeze_mod._remove_anchor()
    except Exception:
        pass
    try:
        freeze_mod._remove_marker()
    except Exception:
        pass


# ---------------------------------------------------------------- 1+2：源码卫生 + 锚密钥 env-only
def test_source_hygiene_and_env_only():
    r = T("C-1a 源码卫生 + 锚密钥 env-only")
    tr_src = (Path(__file__).parent / "trust_root.py").read_text(encoding="utf-8")
    mc_src = (Path(__file__).parent / "metacog.py").read_text(encoding="utf-8")
    r.add("trust_root.py 无内嵌默认锚常量（_TRUST_ROOT_ANCHOR_KEY_DEFAULT 已删）",
          "_TRUST_ROOT_ANCHOR_KEY_DEFAULT" not in tr_src)
    r.add("metacog.py 无内嵌默认锚常量（_LEDGER_ANCHOR_DEFAULT 已删）",
          "_LEDGER_ANCHOR_DEFAULT" not in mc_src)
    r.add("metacog.py 无已废除的 ALLOW_DEFAULT 运行时读取（仅注释提及）",
          'os.environ.get("METACOG_TRUST_ROOT_ALLOW_DEFAULT"' not in mc_src)

    orig = _os.environ.get("METACOG_TRUST_ROOT_ANCHOR_KEY")
    try:
        _os.environ.pop("METACOG_TRUST_ROOT_ANCHOR_KEY", None)
        r.add("未配置锚密钥 → get_anchor_key() 返 None",
              trust_root.get_anchor_key() is None)
        try:
            metacog._resolve_anchor_key()
            r.add("未配置锚密钥 → _resolve_anchor_key 抛 LedgerAnchorDefaultError", False)
        except metacog.LedgerAnchorDefaultError:
            r.add("未配置锚密钥 → _resolve_anchor_key 抛 LedgerAnchorDefaultError", True)
        _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "!!!not-base64!!!"
        try:
            trust_root.get_anchor_key()
            r.add("非法 base64 → ValueError（M-01 fail-closed）", False)
        except ValueError:
            r.add("非法 base64 → ValueError（M-01 fail-closed）", True)
        _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = base64.b64encode(b"short").decode()
        try:
            trust_root.get_anchor_key()
            r.add("<32 字节 → ValueError（M-01 长度校验）", False)
        except ValueError:
            r.add("<32 字节 → ValueError（M-01 长度校验）", True)
        _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = TEST_ANCHOR_KEY
        k = trust_root.get_anchor_key()
        r.add("合法专属密钥 → 返回 ≥32 字节", isinstance(k, (bytes, bytearray)) and len(k) >= 32)
    finally:
        if orig is None:
            _os.environ.pop("METACOG_TRUST_ROOT_ANCHOR_KEY", None)
        else:
            _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = orig
    return r


# ---------------------------------------------------------------- 3+4：H-01 删除 + check_pubkey_root 细分
def test_h01_removed_and_pubkey_root_semantics():
    r = T("H-01 删除 + check_pubkey_root 细分")
    env_key = "METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"
    orig = _os.environ.get(env_key)
    td = Path(tempfile.mkdtemp(prefix="c01_h01_"))
    tmp = Path(tempfile.mkdtemp(prefix="c01_pubroot_"))
    try:
        _os.environ.pop(env_key, None)
        cfg = trust_root.TrustRootConfig.load(td)
        root = trust_root.build_trust_root(cfg)
        r.add("legacy 空配置 → DenyTrustRoot(external-anchor-required)",
              isinstance(root, trust_root.DenyTrustRoot)
              and getattr(root, "reason", "") == "external-anchor-required")
        _os.environ[env_key] = "1"
        root_l = trust_root.build_trust_root(trust_root.TrustRootConfig.load(td))
        r.add("H-01 逃生舱 env=1 → no-op（仍 DenyTrustRoot）",
              isinstance(root_l, trust_root.DenyTrustRoot)
              and getattr(root_l, "reason", "") == "external-anchor-required")

        # check_pubkey_root：纯未配置（无 trust-root.json）→ legacy 钉固分支
        _os.environ.pop(env_key, None)
        st = metacog.Store(tmp / ".metacog")
        st.root.mkdir(parents=True, exist_ok=True)
        (st.root / "ledger").mkdir(parents=True, exist_ok=True)
        pub, priv = sigcrypto.gen_keypair(2048)
        blob = sigcrypto.encrypt_priv(sigcrypto.serialize_priv(priv), "c01-pass")
        metacog.write_json(st.human_guard, {"pubkey": sigcrypto.serialize_pub(pub),
                                            "privkey_enc": blob,
                                            "algo": "rsa-2048-pkcs1v15+aesctr-equiv",
                                            "created_at": "2026-01-01T00:00:00"})
        st.write_human_pubkey_fingerprint(st.human_pubkey_fingerprint())
        ok, reason = st.check_pubkey_root()
        r.add("纯未配置 + pinned==live → check_pubkey_root (True, None)（legacy 回落）",
              ok is True and reason is None, "reason={}".format(reason))
        # corrupt 配置仍 fail-closed
        (st.root / "ledger" / "trust-root.json").write_text("{not-json", encoding="utf-8")
        ok2, reason2 = st.check_pubkey_root()
        r.add("corrupt trust-root.json → fail-closed（非回落）",
              ok2 is False and reason2 not in (None, "external-anchor-required"),
              "reason={}".format(reason2))
    finally:
        if orig is None:
            _os.environ.pop(env_key, None)
        else:
            _os.environ[env_key] = orig
        shutil.rmtree(td, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
    return r


# ---------------------------------------------------------------- 6：M-03 freeze 令牌双 env
def test_m03_freeze_token_pair():
    r = T("M-03 freeze 特权令牌双 env")
    fr_src = (Path(__file__).parent / "freeze.py").read_text(encoding="utf-8")
    r.add("freeze.py 无令牌代码字面量（METACOG-ANCHOR-INIT-REQUIRED 已删）",
          "METACOG-ANCHOR-INIT-REQUIRED" not in fr_src)
    _clean_freeze_state()
    f = Path(tempfile.gettempdir()) / "c01_freeze_sample.py"
    f.write_text("c01 sample\n", encoding="utf-8")
    try:
        (freeze_mod.SKILL_ROOT / "c01_freeze_sample.py").write_text("c01 sample\n", encoding="utf-8")
        freeze_mod.record(["c01_freeze_sample.py"])
        freeze_mod._remove_anchor()  # 制造需 anchor-init 的状态
        _os.environ.pop("METACOG_ANCHOR_INIT_TOKEN", None)
        _os.environ.pop("METACOG_ANCHOR_INIT_TOKEN_EXPECTED", None)
        rc1 = freeze_mod.anchor_init()
        r.add("无令牌 anchor-init → REFUSED(rc==2)", rc1 == 2, "rc={}".format(rc1))
        _os.environ["METACOG_ANCHOR_INIT_TOKEN"] = "c01-token"
        rc2 = freeze_mod.anchor_init()
        r.add("仅提供值缺 EXPECTED → REFUSED(rc==2)", rc2 == 2, "rc={}".format(rc2))
        _os.environ["METACOG_ANCHOR_INIT_TOKEN_EXPECTED"] = "other-value"
        rc3 = freeze_mod.anchor_init()
        r.add("提供值≠期望值 → REFUSED(rc==2)", rc3 == 2, "rc={}".format(rc3))
        _os.environ["METACOG_ANCHOR_INIT_TOKEN_EXPECTED"] = "c01-token"
        rc4 = freeze_mod.anchor_init()
        r.add("成对一致 → 成功(rc==0)", rc4 == 0, "rc={}".format(rc4))
        _os.environ.pop("METACOG_ANCHOR_INIT_TOKEN", None)
        _os.environ.pop("METACOG_ANCHOR_INIT_TOKEN_EXPECTED", None)
    finally:
        _clean_freeze_state()
        shutil.rmtree(freeze_mod.SKILL_ROOT, ignore_errors=True)
    return r


# ---------------------------------------------------------------- 7：签名 v2 格式 + nonce + use-once
def test_sig_v2_nonce_and_useonce():
    r = T("签名 v2 格式 + nonce + use-once")
    tmp = Path(tempfile.mkdtemp(prefix="c01_sig_"))
    try:
        st = metacog.Store(tmp / ".metacog")
        st.root.mkdir(parents=True, exist_ok=True)
        st.quarantine.mkdir(parents=True, exist_ok=True)
        (st.root / "ledger").mkdir(parents=True, exist_ok=True)
        metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
        p = {"id": "P-C01", "status": "gated", "requires_human": True,
             "artifact": "A2", "op": "add", "content": "- c01 规则", "reason": "测试",
             "entry_id": None, "target": None, "episodes": []}
        metacog.write_json(st.quarantine / "P-C01.json", p)
        pub, priv = sigcrypto.gen_keypair(2048)
        blob = sigcrypto.encrypt_priv(sigcrypto.serialize_priv(priv), "c01-pass")
        metacog.write_json(st.human_guard, {"pubkey": sigcrypto.serialize_pub(pub),
                                            "privkey_enc": blob,
                                            "algo": "rsa-2048-pkcs1v15+aesctr-equiv",
                                            "created_at": "2026-01-01T00:00:00"})
        st.write_human_pubkey_fingerprint(st.human_pubkey_fingerprint())
        chash = metacog.proposal_content_hash(p)
        sig1 = st.bind_human_signature(p, chash, 0, passphrase="c01-pass")
        sig2 = st.bind_human_signature(p, chash, 0, passphrase="c01-pass")
        r.add("bind 返回 v2:{nonce}:{b64} 格式",
              sig1.startswith("v2:") and len(sig1.split(":")) == 3)
        r.add("nonce 化：两次绑定签名串互异（消除确定性签名重放构造面）", sig1 != sig2)
        ok_v, reason = st.verify_human_binding(p, sig1, 0)
        r.add("v2 签名 verify 往返通过", ok_v is True and reason is None,
              "reason={}".format(reason))
        # 已消费签名重放被拒（use-once 按签名串消费）
        _ok_c, _reason_c = st.consume_human_sig_atomic(sig1)
        r.add("首次消费成功", _ok_c is True, "reason={}".format(_reason_c))
        _ok_c2, _reason_c2 = st.consume_human_sig_atomic(sig1)
        r.add("同一签名串二次消费被拒（use-once）", _ok_c2 is False)
        # legacy（无 t0）签名 → verify 返 legacy-unbound（M-7 语义保留）
        old_msg = sigcrypto.approval_message_legacy("P-C01", chash)
        old_sig = base64.b64encode(sigcrypto.sign(priv, old_msg)).decode("ascii")
        ok_l, reason_l = st.verify_human_binding(p, old_sig, 0)
        r.add("legacy 无 t0 签名 → (False, legacy-unbound)",
              ok_l is False and reason_l == "legacy-unbound", "reason={}".format(reason_l))
        # legacy 带 t0 签名（M-7 绑定）→ 仍可验（四级回退②）
        legacy_t0_msg = sigcrypto.approval_message_legacy("P-C01", chash, 0)
        legacy_t0_sig = base64.b64encode(sigcrypto.sign(priv, legacy_t0_msg)).decode("ascii")
        ok_l2, reason_l2 = st.verify_human_binding(p, legacy_t0_sig, 0)
        r.add("legacy 带 t0 签名 → 验签通过（回退②）", ok_l2 is True and reason_l2 is None,
              "reason={}".format(reason_l2))
        # N-4（v2.27.20）：长度前缀 = UTF-8 字节数（非码点数）——非 ASCII 字段值
        m_zh = sigcrypto.approval_message("提案-中文-ID", chash)
        r.add("非 ASCII 字段前缀 = UTF-8 字节数（0016，码点口径会错标 0007）",
              "id:0016:提案-中文-ID".encode("utf-8") in m_zh)
        # 非 ASCII v2 消息按 metacog 四级回退①（v2+nonce=None→②确定性 v2）可验
        zh_sig = base64.b64encode(sigcrypto.sign(priv, sigcrypto.approval_message("P-C01", chash, 0))).decode("ascii")
        ok_zh, reason_zh = st.verify_human_binding(p, zh_sig, 0)
        r.add("v2（ASCII 字段现网口径）签名仍验签通过（口径变更不破坏存量）",
              ok_zh is True and reason_zh is None, "reason={}".format(reason_zh))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


# ---------------------------------------------------------------- N-1/N-2：第四轮审计两项 Low 收口
def test_n1_n2_audit_fixes():
    r = T("N-1/N-2 第四轮审计收口")
    orig = _os.environ.get("METACOG_TRUST_ROOT_ANCHOR_KEY")
    td = Path(tempfile.mkdtemp(prefix="c01_n2_"))
    try:
        # N-1：b64decode validate=True——合法密钥尾部混入非字母表字符 → ValueError（不再静默剥除）
        _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = TEST_ANCHOR_KEY + "!!!"
        try:
            trust_root.get_anchor_key()
            r.add("合法密钥尾部混入 '!!!' → ValueError（validate=True 严格字母表）", False)
        except ValueError:
            r.add("合法密钥尾部混入 '!!!' → ValueError（validate=True 严格字母表）", True)
        # 合法密钥（无杂质）仍正常
        _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = TEST_ANCHOR_KEY
        r.add("合法密钥不受 validate=True 影响", trust_root.get_anchor_key() is not None)
        # N-2：存量带 _sig 配置 + env 未配置 → corrupt（不再抛未捕获 TypeError）
        _os.environ.pop("METACOG_TRUST_ROOT_ANCHOR_KEY", None)
        (td / "ledger").mkdir(parents=True, exist_ok=True)
        (td / "ledger" / "trust-root.json").write_text(
            json.dumps({"enabled": True, "backend": "hsm", "attestation_path": "x",
                        "_sig": "a" * 64}), encoding="utf-8")
        cfg = trust_root.TrustRootConfig.load(td)
        r.add("存量带 _sig 配置 + 无 env → corrupt（fail-closed，非 TypeError）",
              cfg.corrupt is True and cfg.enabled is True)
        # 对照：无 _sig 配置 + 无 env → 同样 corrupt（原路径本就 False → corrupt）
        (td / "ledger" / "trust-root.json").write_text(
            json.dumps({"enabled": True, "backend": "hsm"}), encoding="utf-8")
        cfg2 = trust_root.TrustRootConfig.load(td)
        r.add("无 _sig 配置 + 无 env → corrupt（回归保护）",
              cfg2.corrupt is True and cfg2.enabled is True)
    finally:
        if orig is None:
            _os.environ.pop("METACOG_TRUST_ROOT_ANCHOR_KEY", None)
        else:
            _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = orig
        shutil.rmtree(td, ignore_errors=True)
    return r


# ---------------------------------------------------------------- 8：N-3 freeze 链密钥去常量化（v2.27.19）
def test_n3_freeze_key_derivation():
    r = T("N-3 freeze 链密钥 env 锚派生（v2.27.19）")
    fr_src = (Path(__file__).parent / "freeze.py").read_text(encoding="utf-8")
    # 源码卫生：代码常量种子已删
    r.add("freeze.py 无 _FREEZE_KEY_SEED 常量（源码卫生）",
          "_FREEZE_KEY_SEED" not in fr_src)
    r.add("freeze.py 链密钥经 trust_root.get_anchor_key 派生（与账本签名锚同源）",
          "trust_root.get_anchor_key()" in fr_src and "hmac.new(_anchor" in fr_src)
    # 动态：派生值与「锚密钥 + label」HMAC 一致
    import hmac as _hmac
    import hashlib as _hashlib
    _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = TEST_ANCHOR_KEY
    r.add("_freeze_key() == HMAC(锚密钥, _FREEZE_HMAC_LABEL, sha256)",
          freeze_mod._freeze_key() == _hmac.new(
              trust_root.get_anchor_key(), freeze_mod._FREEZE_HMAC_LABEL,
              _hashlib.sha256).digest())
    # 动态：无 env → record REFUSED(rc==-1)，输出含冻结链密钥未配置
    orig = _os.environ.pop("METACOG_TRUST_ROOT_ANCHOR_KEY", None)
    freeze_mod.SKILL_ROOT.mkdir(parents=True, exist_ok=True)
    (freeze_mod.SKILL_ROOT / "c01_n3_sample.py").write_text("n3 sample\n", encoding="utf-8")
    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf):
            rc_no_env = freeze_mod.record(["c01_n3_sample.py"])
        _out = _buf.getvalue()
        r.add("无 env → record REFUSED(rc==-1)", rc_no_env == -1, "rc={}".format(rc_no_env))
        r.add("无 env → 输出含 REFUSED + 冻结链密钥未配置指引",
              "REFUSED" in _out and "冻结链密钥未配置" in _out)
        # 无 env → verify 路径同样 fail-closed（_parse_chain 捕获 RuntimeError → FROZEN-KEY/FROZEN-LEDGER violation，非裸 traceback）
        _buf_vf = io.StringIO()
        with contextlib.redirect_stdout(_buf_vf):
            v_no_env = freeze_mod.verify()
        r.add("无 env → verify 也 fail-closed(ok=False，非裸 traceback 爆发)",
              isinstance(v_no_env, tuple) and v_no_env[0] is False,
              "ret={!r}".format(v_no_env))
        # 恢复 env → record 成功 + verify 通过
        _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = TEST_ANCHOR_KEY
        _buf2 = io.StringIO()
        with contextlib.redirect_stdout(_buf2):
            rc_env = freeze_mod.record(["c01_n3_sample.py"])
        # record() 直调返回追加条数（>=0 即成功；main 包装为 0/1）
        r.add("恢复 env → record 成功(rc>=0，返回追加条数)", isinstance(rc_env, int) and rc_env >= 0,
              "rc={}".format(rc_env))
        _buf3 = io.StringIO()
        with contextlib.redirect_stdout(_buf3):
            verify_ret = freeze_mod.verify()
        # verify() 直调返回 (ok, violations) 元组
        r.add("恢复 env → verify 通过(ok==True 且无 violation)",
              isinstance(verify_ret, tuple) and verify_ret[0] is True and not verify_ret[1],
              "ret={!r}".format(verify_ret if not isinstance(verify_ret, tuple) else verify_ret[0]))
    finally:
        if orig is None:
            _os.environ.pop("METACOG_TRUST_ROOT_ANCHOR_KEY", None)
        else:
            _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = orig
        _clean_freeze_state()
        shutil.rmtree(freeze_mod.SKILL_ROOT, ignore_errors=True)
    return r


def main():
    print("=" * 60)
    print("v2.27.17 C-01 专项收口回归（无默认锚/H-01 删除/H-05 默认开/M-01/M-03/nonce）")
    print("=" * 60 + "\n")
    groups = [test_source_hygiene_and_env_only(),
              test_h01_removed_and_pubkey_root_semantics(),
              test_m03_freeze_token_pair(),
              test_sig_v2_nonce_and_useonce(),
              test_n1_n2_audit_fixes(),
              test_n3_freeze_key_derivation()]
    passed = sum(g.passed for g in groups)
    failed = sum(g.failed for g in groups)
    total = passed + failed
    all_ok = all(g.summary() for g in groups)
    print("\n" + "=" * 60)
    print("全文件总计: {}/{} PASS".format(passed, total))
    print("=" * 60)
    print("SUITE: {}".format("ALL PASS" if all_ok else "HAS FAILURE"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
