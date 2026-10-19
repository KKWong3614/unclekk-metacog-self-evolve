#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
操作 2：held-out 验收验证套件（v2.2.2，含 6.3 防御纵深修复）

验证目标（与新语义一致）：
  - 验收集 = 试用后产生的泛化数据 all_eps[start:]，与 proposer 自选的 cited 解耦。
  - 正常流：pre-trial 证据天然在窗外，验收只看 post-trial episode（真泛化）。
  - 防作弊(6.3)：cited 含试用窗内 episode（index>=start）属篡改，不得据此剔除验收样本，仅预警。
  - 留出集为空/不足 → HOLD，绝不回落训练集放行（即便 --force）。
  - 日志显式打印试用窗总数（6.3 日志清晰度）。

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
    tmp = Path(tempfile.mkdtemp(prefix="metacog_holdout_"))
    st = metacog.Store(tmp / ".metacog")
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


def seed_a2(st, entry_id="R-001"):
    p = st.artifact_path("A2")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# A2\n\n<!-- entry:{} status:active since:2026-09-07 src:seed -->\n初始条目\n<!-- /entry:{} -->\n".format(
            entry_id, entry_id), encoding="utf-8")


def set_baseline(st, util=0.6, vr=0.2, window=3):
    r = st.get_ratchet()
    r["baseline_utility"] = util
    r["baseline_violation_rate"] = vr
    r["window"] = window
    st.set_ratchet(r)


def make_trial_proposal(st, cited, entry_id="R-001", from_index=0):
    p = {
        "id": "P-holdout", "created": metacog.now_iso(), "artifact": "A2",
        "op": "replace", "target": entry_id, "content": "演化后条目",
        "entry_id": entry_id, "status": "trial", "requires_human": False,
        "episodes": list(cited), "reason": "操作2 held-out 测试",
        "trial_since": metacog.now_iso(), "trial_from_index": from_index,
    }
    st.save_proposal(p)
    # v2.2.3：apply 闸门写入受信任锚 apply_record；verdict 只读此值，不信提案字段
    st.record_apply(p["id"], from_index, "A2", entry_id)
    return p


def record_derived(st, eid, util):
    metacog.append_jsonl(st.episodes, {
        "id": eid, "utility": util, "utility_source": "derived", "violations": 0})


def capture_main(argv):
    out, err = io.StringIO(), io.StringIO()
    old_o, old_e = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = metacog.main(argv)
    finally:
        sys.stdout, sys.stderr = old_o, old_e
    return rc, out.getvalue(), err.getvalue()


def test_overfit_reverts_real_flow():
    """真泛化：pre-trial 引用好证据 + post-trial 泛化数据差 → REVERT。"""
    t = T()
    st, tmp = fresh_store()
    try:
        seed_a2(st)
        set_baseline(st, 0.6, 0.2, window=3)
        record_derived(st, "E1", 0.95)   # pre-trial 证据
        record_derived(st, "E2", 0.95)   # pre-trial 证据
        make_trial_proposal(st, cited=["E1", "E2"], from_index=2)
        record_derived(st, "E3", 0.40)   # post-trial 泛化（差）
        record_derived(st, "E4", 0.40)
        record_derived(st, "E5", 0.40)
        rc, out, err = capture_main(["--root", str(st.root), "verdict"])
        t.add("verdict RC=0", rc == 0, "rc={}".format(rc))
        t.add("post-trial 泛化差 → REVERT", "REVERT" in out, "out含REVERT")
        t.add("不误判 PROMOTE", "PROMOTE" not in out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_generalizes_promotes():
    """合法改进：post-trial 泛化数据优 → PROMOTE。"""
    t = T()
    st, tmp = fresh_store()
    try:
        seed_a2(st)
        set_baseline(st, 0.6, 0.2, window=3)
        record_derived(st, "E1", 0.95)
        record_derived(st, "E2", 0.95)
        make_trial_proposal(st, cited=["E1", "E2"], from_index=2)
        record_derived(st, "E3", 0.85)
        record_derived(st, "E4", 0.85)
        record_derived(st, "E5", 0.85)
        rc, out, err = capture_main(["--root", str(st.root), "verdict"])
        t.add("verdict RC=0", rc == 0, "rc={}".format(rc))
        t.add("post-trial 泛化优 → PROMOTE", "PROMOTE" in out, "out含PROMOTE")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_inwindow_cited_tamper_ineffective():
    """防御纵深(6.3)：攻击者把试用窗内坏 episode 写进 cited 想剔除 → 无效，仍 REVERT + 预警。"""
    t = T()
    st, tmp = fresh_store()
    try:
        seed_a2(st)
        set_baseline(st, 0.6, 0.2, window=3)
        record_derived(st, "E1", 0.95)   # pre-trial
        record_derived(st, "E2", 0.95)   # pre-trial
        # 作弊：把试用窗内全部坏 episode (E3/E4/E5) 也塞进 cited 想剔除
        make_trial_proposal(st, cited=["E1", "E2", "E3", "E4", "E5"], from_index=2)
        record_derived(st, "E3", 0.40)
        record_derived(st, "E4", 0.40)
        record_derived(st, "E5", 0.40)
        rc, out, err = capture_main(["--root", str(st.root), "verdict"])
        t.add("verdict RC=0", rc == 0, "rc={}".format(rc))
        t.add("作弊剔除无效 → 仍 REVERT", "REVERT" in out, "out含REVERT")
        t.add("不误判 PROMOTE", "PROMOTE" not in out)
        t.add("检出疑似篡改预警", "疑似篡改" in out or "疑似篡改" in err, "out/err含预警")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_no_citation_full_window():
    """无引用：整窗即留出集，合法改进仍 PROMOTE。"""
    t = T()
    st, tmp = fresh_store()
    try:
        seed_a2(st)
        set_baseline(st, 0.6, 0.2, window=3)
        make_trial_proposal(st, cited=[], from_index=0)
        record_derived(st, "E1", 0.85)
        record_derived(st, "E2", 0.85)
        record_derived(st, "E3", 0.85)
        rc, out, err = capture_main(["--root", str(st.root), "verdict"])
        t.add("verdict RC=0", rc == 0, "rc={}".format(rc))
        t.add("无引用整窗 → PROMOTE", "PROMOTE" in out, "out含PROMOTE")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_insufficient_window_holds():
    """post-trial 样本不足窗口 → HOLD，不回落放行。"""
    t = T()
    st, tmp = fresh_store()
    try:
        seed_a2(st)
        set_baseline(st, 0.6, 0.2, window=5)
        make_trial_proposal(st, cited=[], from_index=1)
        record_derived(st, "E2", 0.85)   # 仅 1 条 post-trial < 窗口5
        rc, out, err = capture_main(["--root", str(st.root), "verdict"])
        t.add("verdict RC=0", rc == 0, "rc={}".format(rc))
        t.add("留出集不足 → HOLD", "留出集不足" in out or "HOLD" in out)
        t.add("不回落训练集放行", "PROMOTE" not in out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_empty_window_blocks_even_force():
    """试用窗为空（无 post-trial 数据）→ 即便 --force 也 HOLD，不回落训练集。"""
    t = T()
    st, tmp = fresh_store()
    try:
        seed_a2(st)
        set_baseline(st, 0.6, 0.2, window=3)
        record_derived(st, "E1", 0.99)   # pre-trial
        record_derived(st, "E2", 0.99)
        record_derived(st, "E3", 0.99)
        # from_index=3 → 试用窗为空；即便全部 cited 也无可验收的 post-trial 数据
        make_trial_proposal(st, cited=["E1", "E2", "E3"], from_index=3)
        rc, out, err = capture_main(["--root", str(st.root), "verdict", "--force"])
        t.add("verdict RC=0", rc == 0, "rc={}".format(rc))
        t.add("试用窗空 → HOLD", "留出集为空" in out or "HOLD" in out)
        t.add("--force 也不回落训练集", "PROMOTE" not in out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_log_shows_window_total():
    """6.3 日志清晰度：验收日志打印试用窗总数。"""
    t = T()
    st, tmp = fresh_store()
    try:
        seed_a2(st)
        set_baseline(st, 0.6, 0.2, window=3)
        make_trial_proposal(st, cited=[], from_index=0)
        record_derived(st, "E1", 0.85)
        record_derived(st, "E2", 0.85)
        record_derived(st, "E3", 0.85)
        rc, out, err = capture_main(["--root", str(st.root), "verdict"])
        t.add("日志含「试用窗」字样", "试用窗" in out, "out含试用窗")
        t.add("日志含窗口条数", "试用窗 3 条" in out, "out含条数")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_trial_from_index_forge_ineffective():
    """P0 根本关闭点(v2.2.3)：即便正常 apply 流（有受信任锚 apply_record），攻击者事后篡改
    提案字段 trial_from_index=3 也毫无影响 —— verdict 只读 apply_record，REVERT 不变。"""
    t = T()
    st, tmp = fresh_store()
    try:
        seed_a2(st)
        set_baseline(st, 0.6, 0.2, window=3)
        record_derived(st, "E1", 0.95)
        record_derived(st, "E2", 0.95)
        p = make_trial_proposal(st, cited=["E1", "E2"], from_index=2)  # apply_record.trial_from_index=2
        record_derived(st, "E3", 0.40)
        record_derived(st, "E4", 0.40)
        record_derived(st, "E5", 0.40)
        # 攻击者拿到 proposal 后篡改字段（不改 apply_record）
        p["trial_from_index"] = 3
        st.save_proposal(p)
        rc, out, err = capture_main(["--root", str(st.root), "verdict"])
        t.add("verdict RC=0", rc == 0, "rc={}".format(rc))
        t.add("篡改字段无效 → 仍 REVERT", "REVERT" in out, "out含REVERT")
        t.add("不误判 PROMOTE", "PROMOTE" not in out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def _no_anchor_hold_case(t, cited, fx, label):
    """无受信任锚（绕过 apply 闸门）的手工伪造 proposal，无论 cited/fx 是否自洽，一律 HOLD，
    绝不 PROMOTE。v2.2.4 删除假防御降级闸门后，自洽向量也覆盖到（正是 v2.2.3 漏网处）。"""
    st, tmp = fresh_store()
    try:
        seed_a2(st)
        set_baseline(st, 0.6, 0.2, window=3)
        # 数据（独立验收报告向量）：E1=0.95 E2=0.95 | E3=0.20 E4=0.60 E5=0.60，容忍阈值 0.58
        record_derived(st, "E1", 0.95)
        record_derived(st, "E2", 0.95)
        # 手工伪造：status=trial，无 apply_record（不调用 record_apply）
        p = {
            "id": "P-hand", "created": metacog.now_iso(), "artifact": "A2",
            "op": "replace", "target": "R-001", "content": "演化后条目",
            "entry_id": "R-001", "status": "trial", "requires_human": False,
            "episodes": list(cited), "reason": "无锚手工伪造",
            "trial_since": metacog.now_iso(), "trial_from_index": fx,
        }
        st.save_proposal(p)   # 注意：不调用 record_apply → 无受信任锚
        record_derived(st, "E3", 0.20)
        record_derived(st, "E4", 0.60)
        record_derived(st, "E5", 0.60)
        rc, out, err = capture_main(["--root", str(st.root), "verdict"])
        t.add("[{}] verdict RC=0".format(label), rc == 0, "rc={}".format(rc))
        t.add("[{}] 无锚伪造不 PROMOTE".format(label), "PROMOTE" not in out)
        t.add("[{}] 被 HOLD 拦截".format(label), "HOLD" in out or "被拦截" in out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_handwritten_proposal_no_apply_record_holds():
    """B6 / P0(v2.2.3 复验复活点)：无受信任锚的手工伪造 proposal，含自洽向量，一律 HOLD。

    覆盖（v2.2.3 ❌ REJECTED 的漏网向量）：
    - B6 原向量：cited=[E1,E2] fx=3（与 lb=2 不自洽）→ HOLD
    - 向量A：cited=[] fx=0（自洽，窗=全部含引用证据）→ 必须 HOLD（v2.2.3 降级闸门误放 PROMOTE）
    - 向量B：cited=[E3] fx=3（自洽，把最差样本 E3 移出窗）→ 必须 HOLD（v2.2.3 降级闸门误放 PROMOTE）
    """
    t = T()
    _no_anchor_hold_case(t, ["E1", "E2"], 3, "B6原向量")
    _no_anchor_hold_case(t, [], 0, "向量A cited=[] fx=0")
    _no_anchor_hold_case(t, ["E3"], 3, "向量B cited=[E3] fx=3")
    return t


def main():
    results = []
    results.append(("真泛化过拟合 → REVERT", test_overfit_reverts_real_flow()))
    results.append(("泛化 → PROMOTE", test_generalizes_promotes()))
    results.append(("窗内 cited 作弊 → 无效+预警", test_inwindow_cited_tamper_ineffective()))
    results.append(("无引用整窗 → PROMOTE", test_no_citation_full_window()))
    results.append(("窗口不足 → HOLD", test_insufficient_window_holds()))
    results.append(("空窗 --force 仍 HOLD", test_empty_window_blocks_even_force()))
    results.append(("日志显窗口总数", test_log_shows_window_total()))
    results.append(("trial_from_index 伪造无效(P0)", test_trial_from_index_forge_ineffective()))
    results.append(("手工伪造无锚 → HOLD(B6)", test_handwritten_proposal_no_apply_record_holds()))

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
