#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# P2 修复验证：metacog.py 的 optimize / detect-domain 子命令已接线
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import metacog


def _cap(fn):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


def test_optimize_subcommand_wired():
    """optimize 子命令应被 dispatch 并产出 dry-run 分析（无 .metacog 时应被守卫拦截）"""
    try:
        # 用一个干净 temp 目录作 root；先 init 再 optimize
        with tempfile.TemporaryDirectory() as d:
            rc_init, _ = _cap(lambda: metacog.main(["--root", d, "init"]))
            assert rc_init in (0, None), f"init 失败 rc={rc_init}"

            rc, out = _cap(lambda: metacog.main(["--root", d, "optimize"]))
            # 空日志 → 无提案；返回 0/None 且文案包含分析结果关键字
            assert rc in (0, None), f"optimize 返回非 0/None: {rc}"
            assert ("no_changes" in out or "未发现" in out or "OPTIMIZE" in out), \
                f"optimize 输出缺少预期内容: {out!r}"
        print("✅ test_optimize_subcommand_wired PASS")
        return True
    except Exception as e:
        print(f"❌ test_optimize_subcommand_wired FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_detect_domain_code():
    """detect-domain 应无需 .metacog 即可检测 code_review 领域"""
    try:
        # 含英文关键词（function/class/bug/logic 均在检测器词表内）
        code = "def function():\n    class Foo:\n        pass\n# bug in the logic of refactor"
        rc, out = _cap(lambda: metacog.main(["detect-domain", "--text", code]))
        assert rc == 0, f"detect-domain 返回 {rc}"
        assert "code_review" in out, f"未检出 code_review: {out!r}"
        print("✅ test_detect_domain_code PASS")
        return True
    except Exception as e:
        print(f"❌ test_detect_domain_code FAIL: {e}")
        return False


def test_detect_domain_paper():
    """detect-domain 应检出 paper_review 领域"""
    try:
        paper = "Abstract: We propose a method. Introduction: ... Method: ... Result: experiments. Conclusion: ..."
        rc, out = _cap(lambda: metacog.main(["detect-domain", "--text", paper]))
        assert rc == 0, f"detect-domain 返回 {rc}"
        assert "paper_review" in out, f"未检出 paper_review: {out!r}"
        print("✅ test_detect_domain_paper PASS")
        return True
    except Exception as e:
        print(f"❌ test_detect_domain_paper FAIL: {e}")
        return False


def test_detect_domain_no_root_required():
    """detect-domain 不应要求 .metacog 目录存在（守卫豁免）"""
    try:
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                code = "def function():\n    class Foo:\n        pass\n# bug in the logic"
                rc, out = _cap(lambda: metacog.main(["detect-domain", "--text", code]))
                assert rc == 0, f"无 .metacog 时 detect-domain 返回 {rc}"
                assert "code_review" in out
            finally:
                os.chdir(str(Path(__file__).parent))
        print("✅ test_detect_domain_no_root_required PASS")
        return True
    except Exception as e:
        print(f"❌ test_detect_domain_no_root_required FAIL: {e}")
        return False


if __name__ == "__main__":
    results = [
        test_optimize_subcommand_wired(),
        test_detect_domain_code(),
        test_detect_domain_paper(),
        test_detect_domain_no_root_required(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*70}")
    print(f"CLI 接线测试: {passed}/{total} PASS")
    print(f"{'='*70}\n")
    sys.exit(0 if passed == total else 1)
