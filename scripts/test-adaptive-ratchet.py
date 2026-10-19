#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 1.2 棘轮自适应测试套件
覆盖：
  - compute_adaptive_threshold 三档违规率（高/中/低）纯函数
  - verdict --adaptive 集成（自适应阈值替代基线参与判定，制造非等价结果）
  - status 输出包含自适应阈值状态
  - 向后兼容：无 --adaptive 时行为完全不变（不输出自适应行）

零第三方依赖，import metacog 直接单测。
"""
import io
import os as _os
import shutil
import sys
import tempfile
from pathlib import Path

# 必须在 import metacog 之前清理 uv 环境，防止 SRE module mismatch
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

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
    tmp = Path(tempfile.mkdtemp(prefix="metacog_adapt_"))
    st = metacog.Store(tmp / ".metacog")
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


def write_a2(st, entry_id, status, body):
    p = st.artifact_path("A2")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# A2\n\n<!-- entry:{} status:{} since:2026-09-07 src:P-test -->\n{}\n<!-- /entry:{} -->\n".format(
            entry_id, status, body, entry_id),
        encoding="utf-8")


def setup_trial(st, baseline_u, baseline_v, trial_u, trial_v):
    """构造一个待裁决场景：
    - baseline: 5 个 episode 建立基线
    - 一条 A2 trial 条目 + 隔离区 proposal
    - 试用期窗口: trial_u/trial_v 的 5 个 episode
    """
    for i in range(5):
        metacog.append_jsonl(st.episodes, {"id": "B{:03d}".format(i),
                                           "utility": baseline_u, "violations": baseline_v})
    r = st.get_ratchet()
    r["baseline_utility"] = baseline_u
    r["baseline_violation_rate"] = baseline_v
    st.set_ratchet(r)

    write_a2(st, "R-AD-001", "trial", "- 候选规则")
    p = {"id": "P-adapt", "status": "trial", "entry_id": "R-AD-001", "op": "add",
         "artifact": "A2", "trial_from_index": 5}
    metacog.write_json(st.quarantine / "P-adapt.json", p)
    st.record_apply("P-adapt", 5, "A2", "R-AD-001")   # v2.2.3：受信任锚

    for i in range(5, 10):
        metacog.append_jsonl(st.episodes, {"id": "T{:03d}".format(i),
                                           "utility": trial_u, "violations": trial_v})


def test_threshold_high():
    """违规率高（0.5>0.3）→ 阈值收紧为 baseline*0.95"""
    t = T()
    base = 0.6
    got = metacog.compute_adaptive_threshold(base, 0.5)
    exp = base * (1 - metacog.ADAPTIVE_ADJUST)
    t.add("高违规率收紧", abs(got - exp) < 1e-9 and got < base,
          "got={:.4f} exp={:.4f}".format(got, exp))
    return t


def test_threshold_low():
    """违规率低（0.0<0.1）→ 阈值放宽为 baseline*1.05"""
    t = T()
    base = 0.6
    got = metacog.compute_adaptive_threshold(base, 0.0)
    exp = base * (1 + metacog.ADAPTIVE_ADJUST)
    t.add("低违规率放宽", abs(got - exp) < 1e-9 and got > base,
          "got={:.4f} exp={:.4f}".format(got, exp))
    return t


def test_threshold_mid():
    """违规率中（0.2 在 0.1~0.3）→ 保持基线"""
    t = T()
    base = 0.6
    got = metacog.compute_adaptive_threshold(base, 0.2)
    t.add("中违规率保持基线", abs(got - base) < 1e-9, "got={:.4f} base={:.4f}".format(got, base))
    return t


def test_verdict_adaptive_changes_outcome():
    """构造非等价场景：非adaptive判PROMOTE，adaptive(窗口低违规→阈值放宽)判REVERT。

    基线 utility=0.6, violation=0；试用期 utility=0.59, violation=0。
    - 非 adaptive: threshold=0.6, du=-0.01≥-0.02 → util_ok PASS
    - adaptive:     窗口 v=0 → threshold=0.63, du=-0.04<-0.02 → util_ok FAIL → REVERT
    """
    t = T()
    # 非 adaptive 分支
    st1, tmp1 = fresh_store()
    try:
        setup_trial(st1, 0.6, 0.0, 0.59, 0.0)
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        metacog.cmd_verdict(st1, type("Args", (), {"force": True, "adaptive": False})())
        sys.stdout = old
        out1 = buf.getvalue()
        t.add("非adaptive → PROMOTE", "PROMOTE" in out1 and "[自适应阈值]" not in out1,
              "out 含 PROMOTE 且无非自适应行")
    finally:
        shutil.rmtree(tmp1, ignore_errors=True)

    # adaptive 分支（同场景）
    st2, tmp2 = fresh_store()
    try:
        setup_trial(st2, 0.6, 0.0, 0.59, 0.0)
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        metacog.cmd_verdict(st2, type("Args", (), {"force": True, "adaptive": True})())
        sys.stdout = old
        out2 = buf.getvalue()
        t.add("adaptive → REVERT", "REVERT" in out2, "out 含 REVERT（阈值放宽反致 FAIL）")
        t.add("adaptive 输出阈值行", "[自适应阈值]" in out2, "out 含自适应阈值说明")
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)
    return t


def test_status_shows_adaptive():
    """status 输出包含棘轮自适应阈值状态块"""
    t = T()
    st, tmp = fresh_store()
    try:
        r = st.get_ratchet()
        r["baseline_utility"] = 0.6
        r["baseline_violation_rate"] = 0.1
        st.set_ratchet(r)
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        metacog.cmd_status(st, type("Args", (), {})())
        sys.stdout = old
        out = buf.getvalue()
        t.add("status 含自适应状态块", "棘轮自适应阈值" in out, "out 含标题")
        t.add("status 含三档阈值", "收紧阈值" in out and "保持基线" in out and "放宽阈值" in out,
              "三档齐全")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_backward_compat():
    """向后兼容：无 --adaptive 时 cmd_verdict 行为与历史一致（不改变既有 53/53 判定）"""
    t = T()
    st, tmp = fresh_store()
    try:
        # 经典 promote 场景（utility 升、violation 降）
        setup_trial(st, 0.6, 1.0, 0.8, 0.0)
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        metacog.cmd_verdict(st, type("Args", (), {"force": True})())
        sys.stdout = old
        out = buf.getvalue()
        t.add("默认无adaptive → PROMOTE", "PROMOTE" in out, "out 含 PROMOTE")
        t.add("默认不输出自适应行", "[自适应阈值]" not in out, "无自适应说明行")
        t.add("基线上移（行为不变）", st.get_ratchet()["baseline_utility"] > 0.6,
              "新基线={:.4f}".format(st.get_ratchet()["baseline_utility"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def main():
    print("=" * 60)
    print("Phase 1.2 棘轮自适应测试套件")
    print("=" * 60 + "\n")
    groups = [
        test_threshold_high(),
        test_threshold_low(),
        test_threshold_mid(),
        test_verdict_adaptive_changes_outcome(),
        test_status_shows_adaptive(),
        test_backward_compat(),
    ]
    passed = sum(g.passed for g in groups)
    failed = sum(g.failed for g in groups)
    total = passed + failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
