#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
操作 3：归因一致性（Attribution Consistency）验证套件（v2.2.5）

验证目标：
  - --attributed 必填（fail-closed）：缺省 → RC=2，且报错提示含 --attributed
  - 归因漂移告警：证据签名与 attributed 明显不符时给出 [归因漂移] 警示
  - 告警不阻断记账：漂移时 RC 仍 = 0，且 episode 正常写入（attribution_drift 标记）
  - 不误报：正确归因 / 相邻制品(A2↔A4) / 中性事件 不触发告警

零第三方依赖，import metacog 直接单测。
"""
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
    tmp = Path(tempfile.mkdtemp(prefix="metacog_attr_"))
    st = metacog.Store(tmp / ".metacog")
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


def capture_main(argv):
    out, err = io.StringIO(), io.StringIO()
    old_o, old_e = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = metacog.main(argv)
    finally:
        sys.stdout, sys.stderr = old_o, old_e
    return rc, out.getvalue(), err.getvalue()


def test_attributed_required():
    t = T()
    st, tmp = fresh_store()
    try:
        # 缺少 --attributed → RC=2（fail-closed）
        rc, _, err = capture_main(
            ["--root", str(st.root), "episode", "--task", "t", "--events", "rework=1"])
        t.add("缺 --attributed → RC=2", rc == 2, "rc={}".format(rc))
        t.add("报错提示含 --attributed", "--attributed" in err, err.strip()[:90])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_attributed_ok():
    t = T()
    st, tmp = fresh_store()
    try:
        rc, _, err = capture_main(
            ["--root", str(st.root), "episode", "--task", "t",
             "--events", "rework=1", "--attributed", "A2"])
        t.add("给 --attributed A2 → RC=0", rc == 0, "rc={}".format(rc))
        eps = metacog.read_jsonl(st.episodes)
        t.add("episode 写入 attributed", bool(eps) and eps[0].get("attributed") == "A2")
        t.add("episode 写入 attribution_drift 字段",
              bool(eps) and ("attribution_drift" in eps[0]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def _run_drift(attributed, events=None, violations=0):
    st, tmp = fresh_store()
    try:
        argv = ["--root", str(st.root), "episode", "--task", "t", "--attributed", attributed]
        for kv in (events or []):
            argv += ["--events", kv]
        if violations:
            argv += ["--violations", str(violations)]
        rc, out, err = capture_main(argv)
        eps = metacog.read_jsonl(st.episodes)
        drift = eps[0].get("attribution_drift") if eps else None
        return rc, out + err, drift
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_drift_violation_to_a2():
    t = T()
    # 命中红线（violations=1，附 rework 事件以使效用可推导）→ 应归 A3，但归 A2 → 告警
    rc, log, flag = _run_drift("A2", events=["rework=1"], violations=1)
    t.add("violation 归 A2 → RC=0（不阻断）", rc == 0, "rc={}".format(rc))
    t.add("violation 归 A2 → 触发漂移告警",
          ("归因漂移" in log) and (flag is True))
    return t


def test_no_drift_violation_to_a3():
    t = T()
    rc, log, flag = _run_drift("A3", events=["rework=1"], violations=1)
    t.add("violation 归 A3 → RC=0", rc == 0)
    t.add("violation 归 A3 → 不告警", ("归因漂移" not in log) and (flag is False))
    return t


def test_drift_rework_to_m1():
    t = T()
    # rework → 应归 A2，但归 M1（元层）→ 告警
    rc, log, flag = _run_drift("M1", events=["rework=1"])
    t.add("rework 归 M1 → RC=0（不阻断）", rc == 0, "rc={}".format(rc))
    t.add("rework 归 M1 → 触发漂移告警",
          ("归因漂移" in log) and (flag is True))
    return t


def test_no_drift_rework_to_a2():
    t = T()
    rc, log, flag = _run_drift("A2", events=["rework=1"])
    t.add("rework 归 A2 → RC=0", rc == 0)
    t.add("rework 归 A2 → 不告警", ("归因漂移" not in log) and (flag is False))
    return t


def test_no_false_positive_adjacent():
    t = T()
    # rework 归 A4（相邻制品）→ 不告警
    rc, log, flag = _run_drift("A4", events=["rework=1"])
    t.add("rework 归 A4（相邻）→ 不告警", ("归因漂移" not in log) and (flag is False))
    # gate_block 归 A2（相邻）→ 不告警
    rc2, log2, flag2 = _run_drift("A2", events=["gate_block=1"])
    t.add("gate_block 归 A2（相邻）→ 不告警", ("归因漂移" not in log2) and (flag2 is False))
    return t


def test_no_drift_neutral():
    t = T()
    # 中性事件（仅 accepted）→ 无建议，不告警
    rc, log, flag = _run_drift("A2", events=["accepted=1"])
    t.add("中性事件 → 不告警", ("归因漂移" not in log) and (flag is False))
    return t


def main():
    print("== 操作 3：归因一致性验证 ==")
    results = [
        test_attributed_required(),
        test_attributed_ok(),
        test_drift_violation_to_a2(),
        test_no_drift_violation_to_a3(),
        test_drift_rework_to_m1(),
        test_no_drift_rework_to_a2(),
        test_no_false_positive_adjacent(),
        test_no_drift_neutral(),
    ]
    total_p = sum(r.passed for r in results)
    total_f = sum(r.failed for r in results)
    print("\n汇总: {}/{} PASS".format(total_p, total_p + total_f))
    return 1 if total_f else 0


if __name__ == "__main__":
    sys.exit(main())
