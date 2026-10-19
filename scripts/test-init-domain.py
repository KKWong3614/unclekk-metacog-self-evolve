#!/usr/bin/env python3
# Phase 2.2 测试：init-domain 命令行接口
# 覆盖：默认初始化 / --output / --config 合并 / 错误处理
# 零第三方依赖，import metacog 直接单测。
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

import io
import json
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


def test_default_init():
    """init-domain code_review 在默认输出目录创建 .metacog 五制品"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_cli_def_"))
    try:
        old = sys.stdout
        sys.stdout = io.StringIO()
        rc = metacog.main(["init-domain", "code_review", "--output", str(tmp)])
        sys.stdout = old
        t.add("返回码 0", rc == 0, "rc={}".format(rc))
        mc = tmp / ".metacog"
        arts = ["A1-system-prompt.md", "A2-rule-bank.md", "A3-safety-memory.md",
                "A4-tool-policy.md", "M1-evolve-policy.md"]
        exist = sum(1 for n in arts if (mc / "artifacts" / n).exists() or (mc / "meta" / n).exists())
        # A1/A4 在 artifacts/，M1 在 meta/；统一计数
        t.add("核心制品存在", (mc / "artifacts" / "A1-system-prompt.md").exists()
              and (mc / "artifacts" / "A2-rule-bank.md").exists()
              and (mc / "meta" / "M1-evolve-policy.md").exists(), "A1/A2/M1 就位")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_output_param():
    """--output 指定自定义目录生效"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_cli_out_"))
    out = tmp / "my_domain"
    try:
        old = sys.stdout
        sys.stdout = io.StringIO()
        rc = metacog.main(["init-domain", "paper_review", "--output", str(out)])
        sys.stdout = old
        t.add("返回码 0", rc == 0, "rc={}".format(rc))
        t.add("输出目录生成 .metacog", (out / ".metacog" / "artifacts" / "A2-rule-bank.md").exists(),
              "自定义目录生效")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_config_merge():
    """--config JSON 覆盖模板字段（用户 A1 生效）"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_cli_cfg_"))
    cfg = tmp / "cfg.json"
    cfg.write_text(json.dumps({"A1": "# 自定义评审助手\n\n用户自定义 A1 内容"}, ensure_ascii=False),
                   encoding="utf-8")
    out = tmp / "dom"
    try:
        old = sys.stdout
        sys.stdout = io.StringIO()
        rc = metacog.main(["init-domain", "code_review", "--output", str(out), "--config", str(cfg)])
        sys.stdout = old
        t.add("返回码 0", rc == 0, "rc={}".format(rc))
        a1 = (out / ".metacog" / "artifacts" / "A1-system-prompt.md").read_text(encoding="utf-8")
        t.add("用户 A1 已合并", "用户自定义 A1 内容" in a1, "配置覆盖生效")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_unknown_domain_error():
    """未知领域名 → argparse choices 拦截，返回码 2（SystemExit）"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_cli_err_"))
    try:
        old = sys.stdout
        sys.stdout = io.StringIO()
        rc = None
        try:
            rc = metacog.main(["init-domain", "no_such_domain", "--output", str(tmp)])
        except SystemExit as e:
            rc = e.code or 2
        sys.stdout = old
        t.add("返回码 2", rc == 2, "rc={}".format(rc))
        t.add("未生成 .metacog", not (tmp / ".metacog").exists(), "非法领域不落盘")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def main():
    print("=" * 60)
    print("init-domain 命令测试 (Phase 2.2)")
    print("=" * 60 + "\n")
    groups = [test_default_init(), test_output_param(), test_config_merge(), test_unknown_domain_error()]
    passed = sum(g.passed for g in groups)
    failed = sum(g.failed for g in groups)
    total = passed + failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
