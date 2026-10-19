#!/usr/bin/env python3
# Phase 2.2 测试：跨领域迁移（3 领域实例化 + 五制品 + 领域特异性内容）
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
from domains import DOMAIN_TEMPLATES
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


DOMAIN_KEYWORDS = {
    "code_review": ["命名规范", "安全检查", "参数化查询"],
    "paper_review": ["创新性", "方法论", "实验"],
    "document_editing": ["格式规范", "术语", "逻辑"],
}


def test_one_domain(domain):
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_mig_{}_".format(domain)))
    try:
        res = init_domain(domain, tmp)
        mc = tmp / ".metacog"
        artifacts = [
            mc / "artifacts" / "A1-system-prompt.md",
            mc / "artifacts" / "A2-rule-bank.md",
            mc / "artifacts" / "A3-safety-memory.md",
            mc / "artifacts" / "A4-tool-policy.md",
            mc / "meta" / "M1-evolve-policy.md",
        ]
        exist = [p.exists() for p in artifacts]
        t.add("{} 五制品存在".format(domain), all(exist), "存在 {}/5".format(sum(exist)))
        a2 = (mc / "artifacts" / "A2-rule-bank.md").read_text(encoding="utf-8")
        kws = DOMAIN_KEYWORDS.get(domain, [])
        hit = any(k in a2 for k in kws)
        t.add("{} 领域特异性内容正确".format(domain), hit, "命中关键词 {}".format(kws))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def main():
    print("=" * 60)
    print("跨领域迁移测试 (Phase 2.2)")
    print("=" * 60 + "\n")
    groups = [test_one_domain(d) for d in DOMAIN_TEMPLATES]
    passed = sum(g.passed for g in groups)
    failed = sum(g.failed for g in groups)
    total = passed + failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
