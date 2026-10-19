#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
操作 1：效用内生（Utility Endogenization）验证套件（v2.2.0）

验证目标：
  - compute_utility 纯函数：由可观测事件推导效用，不读命令行数字（注水在结构上不可行）
  - eligible_eps 演进切换（牙齿）：库中存在 derived 数据后，基线/验收只取 derived，
    声明式 --utility 被架空
  - check_utility_consistency：高申报效用伴负向事件的注水嫌疑检测
  - cmd_episode 端到端：derive / declared 兜底 / derived 优先 / 未知事件 / 越界 utility
  - cmd_verdict 牙齿：验收窗口过滤掉声明式 utility，declared 不能驱动 PROMOTE

零第三方依赖，import metacog 直接单测。
"""
import io
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
    tmp = Path(tempfile.mkdtemp(prefix="metacog_util_"))
    st = metacog.Store(tmp / ".metacog")
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


def capture_main(argv):
    """运行 main() 并捕获 stdout/stderr/rc，不污染测试输出。"""
    out, err = io.StringIO(), io.StringIO()
    old_o, old_e = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = metacog.main(argv)
    finally:
        sys.stdout, sys.stderr = old_o, old_e
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------- 纯函数


def test_compute_utility():
    t = T()
    # 单负向事件
    u, prov = metacog.compute_utility({"rework": 1})
    t.add("rework=1 → 0.65", abs(u - 0.65) < 1e-9, "u={}".format(u))
    t.add("provenance 含 rework", prov.get("rework") == 1)
    # 正向事件上浮（夹紧到 1.0）
    u, _ = metacog.compute_utility({"accepted": 1, "praised": 1})
    t.add("accepted+praised 夹紧 1.0", u == 1.0, "u={}".format(u))
    # 多负向叠加夹紧到 0.0
    u, _ = metacog.compute_utility({"rework": 2, "violation": 1, "manual_fix": 3})
    t.add("重负向夹紧 0.0", u == 0.0, "u={}".format(u))
    # 不读命令行数字：事件与声明值无关
    u1, _ = metacog.compute_utility({"rework": 1})
    u2, _ = metacog.compute_utility({"rework": 1, "utility": 0.99})  # 注入非法键无效
    t.add("非法键不影响推导", u1 == u2 == 0.65, "u1={} u2={}".format(u1, u2))
    return t


def test_eligible_eps():
    t = T()
    declared_only = [{"utility_source": "declared"} for _ in range(3)]
    t.add("全声明式 → 回落为全部", metacog.eligible_eps(declared_only) == declared_only)
    mixed = [{"utility_source": "declared"}, {"utility_source": "derived"}, {"utility_source": "declared"}]
    got = metacog.eligible_eps(mixed)
    t.add("含 derived → 只取 derived", len(got) == 1 and got[0]["utility_source"] == "derived")
    t.add("空列表安全", metacog.eligible_eps([]) == [])
    return t


def test_consistency():
    t = T()
    t.add("高申报+负向事件 → 告警",
          bool(metacog.check_utility_consistency(0.9, {"rework": 1})))
    t.add("低申报+负向事件 → 无告警",
          metacog.check_utility_consistency(0.5, {"rework": 1}) is None)
    t.add("高申报无事件 → 无告警",
          metacog.check_utility_consistency(0.9, {}) is None)
    return t


# ---------------------------------------------------------------- cmd_episode 端到端


def test_episode_derive():
    t = T()
    st, tmp = fresh_store()
    try:
        rc, _, err = capture_main(
            ["--root", str(st.root), "episode", "--task", "t1",
             "--events", "rework=1", "--events", "accepted=1", "--violations", "1",
             "--attributed", "A3"])
        t.add("derive 路径 RC=0", rc == 0, "rc={}".format(rc))
        eps = metacog.read_jsonl(st.episodes)
        t.add("写了 1 条 episode", len(eps) == 1)
        t.add("utility_source=derived", eps[0]["utility_source"] == "derived")
        # rework 0.35 - accepted 0.05 = 0.70
        t.add("推导值=0.70", abs(eps[0]["utility"] - 0.70) < 1e-9, "u={}".format(eps[0]["utility"]))
        t.add("写入 events 计数", eps[0]["events"].get("rework") == 1)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_episode_declared_fallback():
    t = T()
    st, tmp = fresh_store()
    try:
        rc, _, err = capture_main(
            ["--root", str(st.root), "episode", "--task", "t2", "--utility", "0.7",
             "--attributed", "A2"])
        t.add("declared 兜底 RC=0", rc == 0, "rc={}".format(rc))
        eps = metacog.read_jsonl(st.episodes)
        t.add("utility_source=declared", eps[0]["utility_source"] == "declared")
        t.add("声明值保留", abs(eps[0]["utility"] - 0.7) < 1e-9)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_episode_derived_priority():
    t = T()
    st, tmp = fresh_store()
    try:
        rc, out, err = capture_main(
            ["--root", str(st.root), "episode", "--task", "t3",
             "--events", "rework=1", "--utility", "0.99", "--attributed", "A2"])
        t.add("同时给 → RC=0", rc == 0, "rc={}".format(rc))
        eps = metacog.read_jsonl(st.episodes)
        t.add("以 derived 为准 (0.65 非 0.99)", abs(eps[0]["utility"] - 0.65) < 1e-9,
              "u={}".format(eps[0]["utility"]))
        t.add("source=derived", eps[0]["utility_source"] == "derived")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_episode_reject():
    t = T()
    st, tmp = fresh_store()
    try:
        rc, _, _ = capture_main(
            ["--root", str(st.root), "episode", "--task", "t4", "--events", "bogus=1"])
        t.add("未知事件 RC=2", rc == 2, "rc={}".format(rc))
        rc, _, _ = capture_main(
            ["--root", str(st.root), "episode", "--task", "t5", "--utility", "1.5"])
        t.add("越界 utility RC=2", rc == 2, "rc={}".format(rc))
        rc, _, _ = capture_main(
            ["--root", str(st.root), "episode", "--task", "t6"])
        t.add("既无事件也无 utility RC=2", rc == 2, "rc={}".format(rc))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return t


# ---------------------------------------------------------------- verdict 牙齿


def _seed_a2_with_entry(st, entry_id="R-001"):
    p = st.artifact_path("A2")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# A2\n\n<!-- entry:{} status:active since:2026-09-07 src:seed -->\n初始条目\n<!-- /entry:{} -->\n".format(
            entry_id, entry_id), encoding="utf-8")


def _make_trial_proposal(st, entry_id="R-001"):
    p = {
        "id": "P-util", "created": metacog.now_iso(), "artifact": "A2",
        "op": "replace", "target": entry_id, "content": "演化后条目",
        "entry_id": entry_id, "status": "trial", "requires_human": False,
        "episodes": [], "reason": "操作1牙齿测试", "trial_since": metacog.now_iso(),
        "trial_from_index": 0,
    }
    st.save_proposal(p)
    # v2.2.4：真实试用提案必经受信任闸门（apply 写锚）。此处模拟 gated apply 写锚，
    # 否则 verdict 会因无 apply_record 一律 HOLD（与真实流程一致，牙齿测试不依赖假防御）。
    st.record_apply(p["id"], 0, "A2", entry_id)
    return p


def test_verdict_teeth_derived_only():
    """验收窗口只取 derived：声明式 episode 被架空，不能驱动 PROMOTE/REVERT。"""
    t = T()
    st, tmp = fresh_store()
    try:
        _seed_a2_with_entry(st)
        r = st.get_ratchet()
        r["baseline_utility"] = 0.6
        r["baseline_violation_rate"] = 0.2
        r["window"] = 5
        st.set_ratchet(r)
        _make_trial_proposal(st)

        # 5 条 derived 优良 (0.85) + 3 条 declared 注水 (0.99) → declared 应被排除
        for i in range(5):
            metacog.append_jsonl(st.episodes, {"id": "ED{}".format(i),
                "utility": 0.85, "utility_source": "derived", "violations": 0})
        for i in range(3):
            metacog.append_jsonl(st.episodes, {"id": "EC{}".format(i),
                "utility": 0.99, "utility_source": "declared", "violations": 0})

        rc, out, err = capture_main(["--root", str(st.root), "verdict"])
        t.add("verdict RC=0", rc == 0, "rc={}".format(rc))
        t.add("derived 优良 → PROMOTE", "PROMOTE" in out, "out含PROMOTE")
        # 若 declared 被错误计入，u 会更高但仍 promote；关键看是否 REVERT，
        # 这里 derived 优良本就该 promote，故同时验证 declared 未污染基线判定：
        # 后续负向场景才是决定性证据。
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_verdict_teeth_excludes_declared():
    """决定性证据：derived 全差 + declared 全优 → 仍 REVERT（declared 不驱动）。"""
    t = T()
    st, tmp = fresh_store()
    try:
        _seed_a2_with_entry(st)
        r = st.get_ratchet()
        r["baseline_utility"] = 0.6
        r["baseline_violation_rate"] = 0.2
        r["window"] = 5
        st.set_ratchet(r)
        _make_trial_proposal(st)

        # 5 条 derived 全差 (0.5) + 3 条 declared 全优 (0.99)
        for i in range(5):
            metacog.append_jsonl(st.episodes, {"id": "ED{}".format(i),
                "utility": 0.5, "utility_source": "derived", "violations": 0})
        for i in range(3):
            metacog.append_jsonl(st.episodes, {"id": "EC{}".format(i),
                "utility": 0.99, "utility_source": "declared", "violations": 0})

        rc, out, err = capture_main(["--root", str(st.root), "verdict"])
        t.add("verdict RC=0", rc == 0, "rc={}".format(rc))
        t.add("derived 差 → REVERT（declared 未驱动）", "REVERT" in out, "out含REVERT")
        t.add("条目被回滚", "回滚" in out or "REVERT" in out)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_verdict_teeth_declared_only_warn():
    """无 derived 数据：回落为全部（声明式仍被统计），但必须告警。"""
    t = T()
    st, tmp = fresh_store()
    try:
        _seed_a2_with_entry(st)
        r = st.get_ratchet()
        r["baseline_utility"] = 0.6
        r["baseline_violation_rate"] = 0.2
        r["window"] = 5
        st.set_ratchet(r)
        _make_trial_proposal(st)

        for i in range(5):
            metacog.append_jsonl(st.episodes, {"id": "EC{}".format(i),
                "utility": 0.99, "utility_source": "declared", "violations": 0})

        rc, out, err = capture_main(["--root", str(st.root), "verdict"])
        t.add("verdict RC=0", rc == 0, "rc={}".format(rc))
        t.add("仅声明式 → 打告警（验收窗口仅含声明式）",
              "仅含声明式" in out or "仅含声明式" in err, "out/err含告警")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def main():
    results = []
    results.append(("compute_utility 纯函数", test_compute_utility()))
    results.append(("eligible_eps 演进切换", test_eligible_eps()))
    results.append(("check_utility_consistency 注水检测", test_consistency()))
    results.append(("episode derive 路径", test_episode_derive()))
    results.append(("episode declared 兜底", test_episode_declared_fallback()))
    results.append(("episode derived 优先", test_episode_derived_priority()))
    results.append(("episode 拒绝非法输入", test_episode_reject()))
    results.append(("verdict 牙齿 · derived 优良", test_verdict_teeth_derived_only()))
    results.append(("verdict 牙齿 · 排除 declared", test_verdict_teeth_excludes_declared()))
    results.append(("verdict 牙齿 · 仅声明式告警", test_verdict_teeth_declared_only_warn()))

    total_p, total_f = 0, 0
    print("\n" + "=" * 60)
    for name, tr in results:
        print("\n【{}】 {} 通过 / {} 失败".format(name, tr.passed, tr.failed))
        total_p += tr.passed
        total_f += tr.failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(total_p, total_p + total_f))
    print("=" * 60)
    return 1 if total_f else 0


if __name__ == "__main__":
    sys.exit(main())
