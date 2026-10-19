#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
操作 4：元层参数化（Meta-layer Parameterization）验证套件（v2.2.6）

验证目标（参数级自指）：
  - load_meta_policy：文件缺失→回落内置默认值(source=default)；文件存在→读取值(source=file)；
    文件非法/越界→回落默认值且崩溃(fail-safe)。
  - 运行时接入：min_evidence 闸门随参数文件变化；default_window 影响基线建立；
    status 显示的阈值随参数文件变化并标注参数源。
  - 引擎代码零改动行为：改 M1-evolve-policy.json 即改机制，metacog.py 不动点不变。

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
    tmp = Path(tempfile.mkdtemp(prefix="metacog_meta_"))
    st = metacog.Store(tmp / ".metacog")
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


def write_policy(st, epsilon=0.02, default_window=5, min_evidence=2):
    mp = st.artifact_path("M1").with_suffix(".json")
    mp.parent.mkdir(parents=True, exist_ok=True)
    metacog.write_json(mp, {
        "version": 1,
        "ratchet": {"epsilon": epsilon, "default_window": default_window,
                    "min_evidence": min_evidence},
        "_comment": "test",
    })
    return mp


def capture_main(argv):
    out, err = io.StringIO(), io.StringIO()
    old_o, old_e = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = metacog.main(argv)
    finally:
        sys.stdout, sys.stderr = old_o, old_e
    return rc, out.getvalue(), err.getvalue()


def test_load_default():
    t = T()
    st, tmp = fresh_store()
    try:
        policy, src = metacog.load_meta_policy(st)
        t.add("缺失文件 → source=default", src == "default", "src={}".format(src))
        t.add("回落内置默认值", policy == {"epsilon": metacog.EPSILON,
                                            "default_window": metacog.DEFAULT_WINDOW,
                                            "min_evidence": metacog.MIN_EVIDENCE}, str(policy))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_load_file():
    t = T()
    st, tmp = fresh_store()
    try:
        write_policy(st, epsilon=0.5, default_window=3, min_evidence=1)
        policy, src = metacog.load_meta_policy(st)
        t.add("文件存在 → source=file", src == "file", "src={}".format(src))
        t.add("读取值正确", policy == {"epsilon": 0.5, "default_window": 3,
                                       "min_evidence": 1}, str(policy))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_load_invalid():
    t = T()
    st, tmp = fresh_store()
    try:
        mp = write_policy(st)
        mp.write_text("{ 这不是合法 json,,,", encoding="utf-8")
        policy, src = metacog.load_meta_policy(st)
        t.add("非法 JSON → source=default（fail-safe）", src == "default", "src={}".format(src))
        t.add("非法 JSON → 回落默认值", policy == {"epsilon": metacog.EPSILON,
                                                   "default_window": metacog.DEFAULT_WINDOW,
                                                   "min_evidence": metacog.MIN_EVIDENCE}, str(policy))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_load_out_of_range():
    t = T()
    st, tmp = fresh_store()
    try:
        # epsilon 越界（>1）→ 回落
        write_policy(st, epsilon=1.5, default_window=3, min_evidence=1)
        policy, src = metacog.load_meta_policy(st)
        t.add("参数越界 → source=default（fail-safe）", src == "default", "src={}".format(src))
        t.add("参数越界 → 回落默认值", policy == {"epsilon": metacog.EPSILON,
                                                   "default_window": metacog.DEFAULT_WINDOW,
                                                   "min_evidence": metacog.MIN_EVIDENCE}, str(policy))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def _make_proposal(episodes):
    return {"id": "P-test", "op": "add", "artifact": "A2", "content": "测试条目正文",
            "reason": "测试", "episodes": list(episodes), "status": "quarantined",
            "requires_human": False, "gate": None}


def test_min_evidence_default_blocks():
    t = T()
    st, tmp = fresh_store()
    try:
        # 默认 min_evidence=2，仅 1 个 episode → 证据不足 HOLD
        verdict, checks, _ = metacog.run_gate(st, _make_proposal(["E1"]))
        held = any(c[0] == "HOLD" and c[1] == "证据不足" for c in checks)
        t.add("默认 min_evidence=2：1 episode → HOLD", held, "verdict={}".format(verdict))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_min_evidence_policy_passes():
    t = T()
    st, tmp = fresh_store()
    try:
        write_policy(st, min_evidence=1)  # 放宽证据门槛到 1
        verdict, checks, _ = metacog.run_gate(st, _make_proposal(["E1"]))
        held = any(c[0] == "HOLD" and c[1] == "证据不足" for c in checks)
        t.add("参数 min_evidence=1：1 episode → 不 HOLD（闸门随文件变）",
              (not held) and verdict == "pass", "verdict={}".format(verdict))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_window_baseline_policy():
    t = T()
    st, tmp = fresh_store()
    try:
        write_policy(st, default_window=3)  # 窗口放宽到 3
        for i in range(3):
            capture_main(["--root", str(st.root), "episode", "--task", "t{}".format(i),
                          "--events", "rework=1", "--attributed", "A2"])
        r = st.get_ratchet()
        t.add("参数 window=3：3 个 episode 即建立基线", r["baseline_utility"] is not None,
              "base={}".format(r["baseline_utility"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_window_baseline_default():
    t = T()
    st, tmp = fresh_store()
    try:
        # 默认 window=5，仅 3 个 episode → 基线不建立（负对照）
        for i in range(3):
            capture_main(["--root", str(st.root), "episode", "--task", "t{}".format(i),
                          "--events", "rework=1", "--attributed", "A2"])
        r = st.get_ratchet()
        t.add("默认 window=5：3 个 episode 不建立基线（负对照）",
              r["baseline_utility"] is None, "base={}".format(r["baseline_utility"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_status_shows_source():
    t = T()
    st, tmp = fresh_store()
    try:
        write_policy(st, epsilon=0.5, default_window=3, min_evidence=1)
        rc, out, _ = capture_main(["--root", str(st.root), "status"])
        t.add("status RC=0", rc == 0, "rc={}".format(rc))
        t.add("status 标注参数源=file", "元层参数源: file" in out, out[:120])
        t.add("status 显示文件 epsilon=0.5", "ε: 0.5" in out, out[:160])
        t.add("status 显示文件 window=3", "window: 3" in out, out[:160])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def main():
    print("== 操作 4：元层参数化验证 ==")
    results = [
        test_load_default(),
        test_load_file(),
        test_load_invalid(),
        test_load_out_of_range(),
        test_min_evidence_default_blocks(),
        test_min_evidence_policy_passes(),
        test_window_baseline_policy(),
        test_window_baseline_default(),
        test_status_shows_source(),
    ]
    total_p = sum(r.passed for r in results)
    total_f = sum(r.failed for r in results)
    print("\n汇总: {}/{} PASS".format(total_p, total_p + total_f))
    return 1 if total_f else 0


if __name__ == "__main__":
    sys.exit(main())
