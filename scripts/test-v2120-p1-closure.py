#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.12.0（Hermes r8 P1 收口）对抗回归测试套件（独立验证，非自验自收）

覆盖 Hermes r8 裁定后 v2.12.0 新收口的对抗场景：
  - P1-③：移除死字段 sig_epoch——新写入的 integrity 基线记录不再含 "sig_epoch" 键；
            H-B 真正的机制是 _anchor_sig 字段有无判定 + cutoff，而非 sig_epoch。
  - H-B 复确认：移除 sig_epoch 后，缺失 _anchor_sig 的 legacy 无签名基线在 v2.12.0 仍 fail-closed。
  - H-C 复确认：旧审计链（首条缺 epoch）在 v2.12.0 仍 fail-closed。

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
        print("v2.12.0 P1 收口回归: {}/{} PASS".format(self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _new_store():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2120_"))
    root = tmp / ".metacog"
    st = metacog.Store(root)
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


def test_sig_epoch_removed():
    """P1-③：记录基线后，记录中不得再含死字段 sig_epoch；仍须含 _anchor_sig（真机制）。"""
    r = T()
    st, tmp = _new_store()
    try:
        ap = st.root / "ledger" / "applies.jsonl"
        ap.write_text("orig\n", encoding="utf-8")
        st.record_integrity(metacog.Store.APPLIES_INTEGRITY_KEY)
        data = metacog.read_json(st.integrity, {})
        rec = data.get(metacog.Store.APPLIES_INTEGRITY_KEY, {})
        r.add("基线记录不含死字段 sig_epoch（P1-③）", "sig_epoch" not in rec, "keys={}".format(list(rec.keys())))
        r.add("基线记录仍含 _anchor_sig（真 H-B 机制）", "_anchor_sig" in rec)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_hb_still_closed():
    """H-B 复确认：移除 sig_epoch 后，无签名基线在 v2.12.0 仍 fail-closed。"""
    r = T()
    st, tmp = _new_store()
    try:
        f = st.root / "ledger" / "applies.jsonl"
        f.write_text("legacy content\n", encoding="utf-8")
        gdata = metacog.read_json(st.integrity, {})
        gdata[metacog.Store.APPLIES_INTEGRITY_KEY] = {
            "hash": st._hash_text(f.read_text(encoding="utf-8")),
            "size": f.stat().st_size, "at": "2026-01-01T00:00:00Z",
        }
        metacog.write_json(st.integrity, gdata)
        rows = st.verify_integrity()
        hit = [(a, ok) for (a, ok, *_r) in rows if a == metacog.Store.APPLIES_INTEGRITY_KEY]
        r.add("H-B 无签名基线仍 fail-closed（移除 sig_epoch 后）", bool(hit) and hit[0][1] is False, "hit={}".format(hit))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_hc_still_closed():
    """H-C 复确认：旧审计链（首条缺 epoch）在 v2.12.0 仍 fail-closed。"""
    r = T()
    st, tmp = _new_store()
    try:
        audit = st.root / "ledger" / "migration-audit.jsonl"
        old = {"at": "t", "operation": "x", "event": "E", "src": "s", "dst": "d", "detail": "",
               "prev_hmac": "", "hmac": "0" * 64}
        audit.write_text(json.dumps(old) + "\n", encoding="utf-8")
        ok_v, cnt_v = st._verify_migration_audit()
        r.add("H-C 旧链仍 fail-closed（移除 sig_epoch 后）", ok_v is False and cnt_v == 1, "ok={} cnt={}".format(ok_v, cnt_v))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def main():
    results = []
    results.append(test_sig_epoch_removed())
    results.append(test_hb_still_closed())
    results.append(test_hc_still_closed())
    all_ok = all(t.summary() for t in results)
    print("\n########## v2.12.0 P1 收口套件汇总 ##########")
    print("SUITE: {}".format("ALL PASS" if all_ok else "HAS FAILURE"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
