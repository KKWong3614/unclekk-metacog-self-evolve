#!/usr/bin/env python3
# Phase 2.2 测试：领域初始化函数 init_domain
# 覆盖：3 领域五制品创建 / 引擎兼容（ratchet schema）/ 领域红线建议写入
# 零第三方依赖，import metacog + domains 直接单测。
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

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
from domains.init import init_domain


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def add(self, name, ok, detail=""):
        self.passed += ok
        self.failed += (not ok)
        print("  [{}] {}{}".format("PASS" if ok else "FAIL", name,
                                    (" - " + detail) if detail else ""))


def _artifact_paths(mc):
    # A1/A2/A3/A4 在 artifacts/，M1 在 meta/
    return [mc / "artifacts" / "A1-system-prompt.md",
            mc / "artifacts" / "A2-rule-bank.md",
            mc / "artifacts" / "A3-safety-memory.md",
            mc / "artifacts" / "A4-tool-policy.md",
            mc / "meta" / "M1-evolve-policy.md"]


def test_domain_creates_artifacts(domain):
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_dom_{}_".format(domain)))
    try:
        res = init_domain(domain, tmp)
        mc = tmp / ".metacog"
        arts = _artifact_paths(mc)
        exist = [p.exists() for p in arts]
        t.add("{} 五制品齐全".format(domain), all(exist), "存在 {}/5".format(sum(exist)))
        t.add("返回 artifacts 列表", res["artifacts"] == ["A1", "A2", "A3", "A4", "M1"],
              str(res["artifacts"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_engine_compatible():
    """领域实例 ratchet.json 为标准 schema，引擎可直接读"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_dom_compat_"))
    try:
        init_domain("code_review", tmp)
        st = metacog.Store(tmp / ".metacog")
        r = st.get_ratchet()
        t.add("ratchet 含 baseline_utility 字段", "baseline_utility" in r, "标准 schema")
        t.add("ratchet 含 window 字段", "window" in r, "标准 schema")
        t.add("CONTRACT 已生成", st.contract.exists(), "统一不动点契约就位")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_redlines_note_written():
    """领域红线建议写入 meta/domain-redlines.md（不修改全局 REDLINES）"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_dom_rl_"))
    try:
        init_domain("code_review", tmp)
        note = tmp / ".metacog" / "meta" / "domain-redlines.md"
        t.add("红线建议文件存在", note.exists(), str(note))
        txt = note.read_text(encoding="utf-8")
        t.add("含领域红线关键词(安全漏洞)", "安全漏洞" in txt, "领域特异性")
        # 全局 REDLINES 不变（安全不变式）
        t.add("全局 REDLINES 未被领域削弱", len(metacog.REDLINES) >= 7,
              "REDLINES 数量={}".format(len(metacog.REDLINES)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def main():
    print("=" * 60)
    print("领域初始化函数测试 (Phase 2.2, init_domain)")
    print("=" * 60 + "\n")
    groups = [test_domain_creates_artifacts("code_review"),
              test_domain_creates_artifacts("paper_review"),
              test_domain_creates_artifacts("document_editing"),
              test_engine_compatible(),
              test_redlines_note_written()]
    passed = sum(g.passed for g in groups)
    failed = sum(g.failed for g in groups)
    total = passed + failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
