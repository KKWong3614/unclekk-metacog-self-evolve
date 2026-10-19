#!/usr/bin/env python3
# Phase 1.1 测试：M1 自动触发机制
# 覆盖：失败模式分析 / 自动触发 / CLI --auto-m1 参数
# 零第三方依赖，import metacog 直接单测。
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

import io
import shutil
import sys
import tempfile
from pathlib import Path

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
                                    (" - " + detail) if detail else ""))


def fresh_store():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_m1_"))
    st = metacog.Store(tmp / ".metacog")
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


def three_reverts(st):
    r = st.get_ratchet()
    r["baseline_utility"] = 0.5
    r["baseline_violation_rate"] = 0.0
    r["history"] = [
        {"at": "t1", "proposal": "P-1", "action": "revert", "utility": 0.4,
         "violation_rate": 0.2, "artifact": "A2", "reason": "证据不足"},
        {"at": "t2", "proposal": "P-2", "action": "revert", "utility": 0.4,
         "violation_rate": 0.2, "artifact": "A2", "reason": "归因错误"},
        {"at": "t3", "proposal": "P-3", "action": "revert", "utility": 0.4,
         "violation_rate": 0.2, "artifact": "A1", "reason": "风格偏移"},
    ]
    st.set_ratchet(r)


def mixed_history(st):
    r = st.get_ratchet()
    r["baseline_utility"] = 0.5
    r["baseline_violation_rate"] = 0.0
    r["history"] = [
        {"at": "t1", "proposal": "P-1", "action": "promote", "utility": 0.8,
         "violation_rate": 0.0, "artifact": "A2", "reason": ""},
        {"at": "t2", "proposal": "P-2", "action": "revert", "utility": 0.4,
         "violation_rate": 0.2, "artifact": "A2", "reason": "证据不足"},
        {"at": "t3", "proposal": "P-3", "action": "promote", "utility": 0.8,
         "violation_rate": 0.0, "artifact": "A2", "reason": ""},
    ]
    st.set_ratchet(r)


def test_analyze_failure_pattern():
    """3 次连续 REVERT → revert_count=3 + 制品分布 + 原因；混合历史 → revert_count=1"""
    t = T()
    st, tmp = fresh_store()
    try:
        three_reverts(st)
        pat = metacog.analyze_failure_pattern(st.get_ratchet())
        t.add("revert_count==3", pat["revert_count"] == 3, "got {}".format(pat["revert_count"]))
        t.add("artifact_focus 含A2=2", pat["artifact_focus"].get("A2") == 2, str(pat["artifact_focus"]))
        t.add("artifact_focus 含A1=1", pat["artifact_focus"].get("A1") == 1, str(pat["artifact_focus"]))
        t.add("common_reasons 捕获3条", len(pat["common_reasons"]) == 3, str(pat["common_reasons"]))

        mixed_history(st)
        pat2 = metacog.analyze_failure_pattern(st.get_ratchet())
        t.add("混合历史 revert_count==1", pat2["revert_count"] == 1, "got {}".format(pat2["revert_count"]))
        t.add("混合历史 不误报为3", pat2["revert_count"] != 3, "got {}".format(pat2["revert_count"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_check_and_trigger_m1():
    """3 次 REVERT → 创建 M1 提议(requires_human/op/target 正确)；混合历史 → 不触发"""
    t = T()
    st, tmp = fresh_store()
    try:
        three_reverts(st)
        triggered = metacog.check_and_trigger_m1(st)
        t.add("3次REVERT 返回True", triggered is True)
        props = st.proposals()
        t.add("隔离区新增M1提议", len(props) == 1 and props[0]["artifact"] == "M1", "n={}".format(len(props)))
        if props:
            p = props[0]
            t.add("requires_human=True", p.get("requires_human") is True)
            t.add("op=replace", p.get("op") == "replace", str(p.get("op")))
            t.add("target=M-000", p.get("target") == "M-000", str(p.get("target")))
            t.add("triggered=True", p.get("triggered") is True)
            t.add("含failure_pattern", "failure_pattern" in p)

        for f in st.quarantine.glob("*.json"):
            f.unlink()
        mixed_history(st)
        triggered2 = metacog.check_and_trigger_m1(st)
        t.add("混合历史 返回False", triggered2 is False)
        t.add("混合历史 无提议", len(st.proposals()) == 0, "n={}".format(len(st.proposals())))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_cli_auto_m1():
    """verdict --auto-m1 创建M1提议；无--auto-m1 不创建但仍打印[META]提示"""
    t = T()
    st, tmp = fresh_store()
    try:
        three_reverts(st)
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        metacog.cmd_verdict(st, type("Args", (), {"force": False, "auto_m1": True})())
        sys.stdout = old
        out = buf.getvalue()
        props = st.proposals()
        t.add("CLI --auto-m1 创建M1提议", len(props) == 1 and props[0]["artifact"] == "M1",
              "n={}".format(len(props)))
        t.add("CLI 输出创建提示", "M1 自动提议已创建" in out, "")

        for f in st.quarantine.glob("*.json"):
            f.unlink()
        buf2 = io.StringIO()
        sys.stdout = buf2
        metacog.cmd_verdict(st, type("Args", (), {"force": False, "auto_m1": False})())
        sys.stdout = old
        t.add("CLI 无--auto-m1 不创建提议", len(st.proposals()) == 0, "n={}".format(len(st.proposals())))
        t.add("CLI 无参仍打印[META]提示", "[META]" in buf2.getvalue())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def main():
    print("=" * 60)
    print("Phase 1.1 测试套件: M1 自动触发")
    print("=" * 60 + "\n")
    groups = [test_analyze_failure_pattern(), test_check_and_trigger_m1(), test_cli_auto_m1()]
    passed = sum(g.passed for g in groups)
    failed = sum(g.failed for g in groups)
    total = passed + failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
