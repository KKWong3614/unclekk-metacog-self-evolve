#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_release_package.py — 确定性构建 SkillHub 发布包（v2.27.48 新增）

为什么需要它：SkillHub CLI 的 `publish` **不读 `.packignore`**（只排除 .git/.idea/.vscode/
node_modules/__pycache__ 与 .pyc/.DS_Store/Thumbs.db），因此 `.gitignore/.specignore/.packignore`
必进包 → 服务端 400「不允许的文件类型」；`dist/`（历史归档，数十 MB）也进包 → 大包上传 TLS EOF。
本脚本把「哪些文件随包、哪些剔除」固化为可复现的确定性规则，取代手工拷贝。

规则（与 publish_consistency_check.py 的 B/F 检查项一一对应）：
  - 扩展名白名单：.md / .py / .json / .jsonl / .toml
  - .txt 例外白名单：scripts/test-suite-manifest.txt
    （随包运行器 `_run_all_tests.py` 对该清单 fail-closed——缺失即 FAIL，缺它随包运行器开箱即挂）
  - 目录级剔除：dist/、.git/、__pycache__/、audit-probes-v22518/、obsolete/、archive/
  - 文件级剔除：references/audit-*、hermes-audit-*、independent-audit-*（v2.2+）、
    remediation-*、implementation-checklist-*、operations-history*、test-evidence-history-* 等
    （逐版审计档案与旧版日志不随包分发；证据链保留于作者 dev 树）
  - 其余（.bak/.tmp/.pyc/.html/.sh 等）一律不拷贝

用法：
  python3 scripts/build_release_package.py <输出目录>
  python3 scripts/build_release_package.py <输出目录> --src <源目录>   # 默认取本文件所在技能树
输出：构建统计 + 随包/剔除文件数；退出码 0 = 成功。
"""
import fnmatch
import os
import shutil
import sys

ALLOW_EXT = (".md", ".py", ".json", ".jsonl", ".toml")
ALLOWED_TXT = {"scripts/test-suite-manifest.txt"}
SKIP_DIR_PARTS = {"dist", ".git", "__pycache__", "audit-probes-v22518", "obsolete", "archive"}
ARCHIVE_GLOBS = [
    "references/audit-*",
    "references/hermes-audit-*",
    "references/independent-audit-hermes-*",
    "references/independent-audit-deep-*",
    "references/independent-audit-v2.[2-8]*",
    "references/remediation-*",
    "references/implementation-checklist-*",
    "references/v2.6.0-external-anchor-design-DRAFT.md",
    "references/trace-reliability-*",
    "references/operations-history*",
    "references/test-evidence-history-*",
]


def build(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)
    kept = []
    dropped = []
    for root, dirs, files in os.walk(src):
        rel_parts = set(os.path.relpath(root, src).replace(os.sep, "/").split("/"))
        if rel_parts & SKIP_DIR_PARTS:
            dirs[:] = []
            dropped.extend(os.path.join(root, f) for f in files)
            continue
        for fn in files:
            full = os.path.join(root, fn)
            rp = os.path.relpath(full, src).replace(os.sep, "/")
            keep = False
            if fn.endswith(ALLOW_EXT):
                keep = True
            elif fn.endswith(".txt") and rp in ALLOWED_TXT:
                keep = True
            if keep and any(fnmatch.fnmatch(rp, g) for g in ARCHIVE_GLOBS):
                keep = False
            if not keep:
                dropped.append(full)
                continue
            target = os.path.join(dst, rp)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(full, target)
            kept.append(rp)
    return kept, dropped


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    dst = sys.argv[1]
    src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "--src" in sys.argv:
        i = sys.argv.index("--src")
        if i + 1 < len(sys.argv):
            src = sys.argv[i + 1]
    kept, dropped = build(src, dst)
    print(f"源树: {src}")
    print(f"发布树: {dst}")
    print(f"随包文件: {len(kept)}  剔除文件: {len(dropped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
