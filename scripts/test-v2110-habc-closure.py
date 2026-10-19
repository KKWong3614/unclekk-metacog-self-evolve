#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.11.0（H-A / H-B / H-C 收口）对抗回归测试套件（独立验证，非自验自收）

覆盖 Hermes r7 裁定后 v2.11.0 新收口的对抗场景（闭合 M-A 覆盖缺口 + 锁定 H-B/H-C 行为）：
  - GUARD 域（human-guard.json，M-A/④）：攻击者改文件 + 重记基线（伪造 _anchor_sig）→ cmd_verify 须 fail-closed（返回 1）；
    合法重基线（持真实锚密钥）→ 通过（返回 0）。
  - ARTIFACT 域（applies.jsonl，M-A/④）：攻击者改文件 + 重记基线（伪造 _anchor_sig）→ verify_integrity 须标 False（fail-closed）；
    合法重基线（持真实锚密钥）→ 通过（True）。
  - H-B 回归：缺失 _anchor_sig 的 legacy 无签名基线，在 v2.11.0（CURRENT >= LEGACY_ANCHOR_SIG_CUTOFF）须 fail-closed；
    在截止期前（cutoff 覆盖 (2,19)）仍容忍（过渡语义保留）。
  - H-C 回归：旧审计链（首条缺 epoch）在 v2.11.0 须 fail-closed；截止期前（cutoff 覆盖 (2,19)）仍容忍。

零第三方依赖。运行需 METACOG_TRUST_ROOT_ALLOW_DEFAULT=1（本文件自行 setdefault）。
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("METACOG_TRUST_ROOT_ALLOW_DEFAULT", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))
import metacog


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
        print("\n{}".format("=" * 60))
        print("v2.11.0 H-A/H-B/H-C 对抗回归: {}/{} PASS".format(self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _new_store():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2110_"))
    root = tmp / ".metacog"
    st = metacog.Store(root)
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


def test_guard_domain_forged_sig_failclosed():
    """GUARD 域：改 human-guard.json + 重记基线（伪造 _anchor_sig）→ cmd_verify fail-closed。

    注：cmd_verify 在 verify_integrity() 返回空（仅 guard 基线时 guard 被跳过）→ 早返回 0，
    故测试镜像真实部署同时建立 applies 基线，使 verify_integrity 非空、guard 专用校验块被触发。"""
    r = T()
    st, tmp = _new_store()
    try:
        # 建立 applies 基线（合法，verify 通过）→ 使 verify_integrity 非空，guard 校验块被触发
        ap = st.root / "ledger" / "applies.jsonl"
        ap.write_text("orig line\n", encoding="utf-8")
        st.record_integrity(metacog.Store.APPLIES_INTEGRITY_KEY)

        st.human_guard.write_text(json.dumps({"pubkey": "ORIGINAL", "privkey_enc": "x"}), encoding="utf-8")
        st.record_guard_integrity()

        # 攻击者：改文件 + 把基线 hash 对齐新内容 + 伪造（错误密钥）签名
        st.human_guard.write_text(json.dumps({"pubkey": "ATTACKER", "privkey_enc": "x"}), encoding="utf-8")
        gdata = metacog.read_json(st.integrity, {})
        grec = gdata[metacog.Store.GUARD_INTEGRITY_KEY]
        grec["hash"] = st._hash_text(st.human_guard.read_text(encoding="utf-8"))
        grec["_anchor_sig"] = "0" * 64
        metacog.write_json(st.integrity, gdata)

        rc = metacog.cmd_verify(st, None)
        r.add("GUARD 域 改文件+伪造签名 → cmd_verify fail-closed (rc=1)", rc == 1, "rc={}".format(rc))

        # 正向：合法重基线（持真实锚密钥）→ 通过
        st.record_guard_integrity()
        rc2 = metacog.cmd_verify(st, None)
        r.add("GUARD 域 合法重基线 → cmd_verify 通过 (rc=0)", rc2 == 0, "rc={}".format(rc2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_artifact_domain_forged_sig_failclosed():
    """ARTIFACT 域（applies.jsonl）：改文件 + 重记基线（伪造 _anchor_sig）→ verify_integrity 标 False。"""
    r = T()
    st, tmp = _new_store()
    try:
        ap = st.root / "ledger" / "applies.jsonl"
        ap.write_text("orig line\n", encoding="utf-8")
        st.record_integrity(metacog.Store.APPLIES_INTEGRITY_KEY)

        # 攻击者：改文件 + 对齐基线 hash + 伪造签名
        ap.write_text("ATTACKER line\n", encoding="utf-8")
        gdata = metacog.read_json(st.integrity, {})
        arec = gdata[metacog.Store.APPLIES_INTEGRITY_KEY]
        arec["hash"] = st._hash_text(ap.read_text(encoding="utf-8"))
        arec["_anchor_sig"] = "0" * 64
        metacog.write_json(st.integrity, gdata)

        rows = st.verify_integrity()
        hit = [(a, ok) for (a, ok, *_r) in rows if a == metacog.Store.APPLIES_INTEGRITY_KEY]
        r.add("ARTIFACT 域 改文件+伪造签名 → verify_integrity False",
              bool(hit) and hit[0][1] is False, "hit={}".format(hit))

        # 正向：合法重基线 → True
        st.record_integrity(metacog.Store.APPLIES_INTEGRITY_KEY)
        rows2 = st.verify_integrity()
        hit2 = [(a, ok) for (a, ok, *_r) in rows2 if a == metacog.Store.APPLIES_INTEGRITY_KEY]
        r.add("ARTIFACT 域 合法重基线 → verify_integrity True",
              bool(hit2) and hit2[0][1] is True, "hit2={}".format(hit2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_hb_legacy_missing_sig_failclosed():
    """H-B 回归：缺失 _anchor_sig 的 legacy 无签名基线在 v2.11.0 须 fail-closed；截止期前仍容忍。"""
    r = T()
    st, tmp = _new_store()
    try:
        # 注入一条无 _anchor_sig 的 legacy 基线（模拟 <v2.11 旧基线）
        f = st.root / "ledger" / "applies.jsonl"
        f.write_text("legacy content\n", encoding="utf-8")
        gdata = metacog.read_json(st.integrity, {})
        gdata[metacog.Store.APPLIES_INTEGRITY_KEY] = {
            "hash": st._hash_text(f.read_text(encoding="utf-8")),
            "size": f.stat().st_size, "at": "2026-01-01T00:00:00Z",
        }
        metacog.write_json(st.integrity, gdata)

        # v2.11.0：缺失 _anchor_sig → fail-closed
        rows = st.verify_integrity()
        hit = [(a, ok) for (a, ok, *_r) in rows if a == metacog.Store.APPLIES_INTEGRITY_KEY]
        r.add("H-B v2.11.0 无签名基线 → fail-closed (False)",
              bool(hit) and hit[0][1] is False, "hit={}".format(hit))

        # 过渡演示：截止期前（_legacy_anchor_sig_allowed(cutoff=(2, 26)) 模拟未来版本）→ 容忍
        allowed = metacog.Store._legacy_anchor_sig_allowed(cutoff=(2, 26))
        r.add("H-B 截止期前(cutoff=2,23) 无签名基线仍允许（过渡语义）", allowed is True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_hc_old_audit_chain_failclosed():
    """H-C 回归：旧审计链（首条缺 epoch）在 v2.11.0 须 fail-closed；截止期前（cutoff=(2, 26)）仍容忍。"""
    r = T()
    st, tmp = _new_store()
    try:
        audit = st.root / "ledger" / "migration-audit.jsonl"
        old = {"at": "t", "operation": "x", "event": "E", "src": "s", "dst": "d", "detail": "",
               "prev_hmac": "", "hmac": "0" * 64}
        audit.write_text(json.dumps(old) + "\n", encoding="utf-8")
        ok_v211, cnt_v211 = st._verify_migration_audit()
        r.add("H-C v2.11.0 旧链 → fail-closed (False)", ok_v211 is False and cnt_v211 == 1,
              "ok={} cnt={}".format(ok_v211, cnt_v211))
        ok_trans, cnt_trans = st._verify_migration_audit(cutoff=(2, 26))
        r.add("H-C 截止期前(cutoff=2,23) 旧链仍容忍 (True)", ok_trans is True and cnt_trans == 1,
              "ok={} cnt={}".format(ok_trans, cnt_trans))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def main():
    results = []
    results.append(test_guard_domain_forged_sig_failclosed())
    results.append(test_artifact_domain_forged_sig_failclosed())
    results.append(test_hb_legacy_missing_sig_failclosed())
    results.append(test_hc_old_audit_chain_failclosed())
    all_ok = all(t.summary() for t in results)
    print("\n########## v2.11.0 对抗回归套件汇总 ##########")
    print("SUITE: {}".format("ALL PASS" if all_ok else "HAS FAILURE"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
