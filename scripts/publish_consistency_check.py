#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_consistency_check.py — SkillHub 发布前一致性硬闸（v2.27.43 新增）

触发背景（SkillHub TRACE 平台反馈 2026-10-30，综合 4.7/5）：
  短板「不同指南之间存在旧用法冲突，可能让用户照着过时步骤操作」；
  建议「加强发布前的一致性检查」。本脚本把历次踩坑固化为自动检查。

检查项：
  A. 版本三方一致：SKILL.md frontmatter == package.json == _skillhub_meta.json，
     且 CHANGELOG.md 存在 `## v<version>` 条目
  B/F. 禁发文件与审计档案：发布树不得含 .txt/.html/.sh/.bak/.pyc、打包元 dotfile
     (.gitignore/.specignore/.packignore)、pack.sh、dist/、audit-probes 目录
  C. 废除用法扫描（操作类 .md）：已废除用法只允许「负向提法」（同行为
     废除/已删除/硬拦/拒绝 等语境词），出现「正向教学」即 FAIL：
     - METACOG_TRUST_ROOT_ALLOW_DEFAULT=1（v2.27.17 废除）
     - --human-ok（v2.4.0 废除，改 confirm 凭证化）
     - ./skills/@<handle>（旧安装路径）
  D. INDEX.md 链接有效性：references/INDEX.md 引用的相对 .md 必须存在
  E. operations-history.md 存在且 SKILL.md 指针存在（v2.27.42 迁移约定）

用法：
  python3 scripts/publish_consistency_check.py <tree_dir>   # 检查待发布树
  python3 scripts/publish_consistency_check.py --src        # 检查本源码树
退出码：0 = 全部通过；1 = 存在 FAIL 项（附清单）
"""
import fnmatch
import json
import os
import re
import sys

# 废除用法 → 允许出现的负向语境词
ABOLISHED_PATTERNS = {
    "METACOG_TRUST_ROOT_ALLOW_DEFAULT=1": ("废除", "已删除", "废弃", "原 `", "已不存在"),
    "--human-ok": ("废除", "硬拦", "拒绝", "命中即", "已不用"),
    "confirm --approve": ("移除", "废除", "已删"),
    "一次性 token": ("移除", "废除", "已删", "旧", "已改为", "use-once"),
    "10 万轮": ("旧", "已改为", "v2.4.0"),
    "apply --token": ("移除", "废除", "已删"),
    "skills/@": (),  # 旧安装路径：任何出现都不允许
}

# 操作类文档（会被用户照抄的现行指南）
OPERATIONAL_DOCS = [
    "SKILL.md",
    "references/faq-deep.md",
    "references/anti-patterns.md",
    "references/error-glossary.md",
    "references/troubleshooting.md",
    "references/walkthrough-first-promote.md",
]

FORBIDDEN_SUFFIXES = (".html", ".sh", ".bak", ".pyc", ".pyo")
# 白名单例外：随包运行器 fail-closed 依赖的应有套件清单（服务端接受 .txt）
ALLOWED_TXT = {"scripts/test-suite-manifest.txt"}
FORBIDDEN_DOTFILES = {".gitignore", ".specignore", ".packignore"}
FORBIDDEN_DIRS = {"dist", "audit-probes-v22518", "obsolete", "__pycache__", "archive"}

fails = []
warns = []


def fail(msg):
    fails.append(msg)


def warn(msg):
    warns.append(msg)


def check_versions(tree):
    fm = None
    with open(os.path.join(tree, "SKILL.md"), encoding="utf-8") as f:
        m = re.search(r"^version:\s*([0-9.]+)\s*$", f.read(), re.M)
        fm = m.group(1) if m else None
    versions = {"SKILL.md": fm}
    for fn in ("package.json", "_skillhub_meta.json"):
        p = os.path.join(tree, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                versions[fn] = json.load(f).get("version")
        else:
            fail(f"缺失 {fn}")
    vals = set(v for v in versions.values() if v)
    if len(vals) != 1:
        fail(f"版本不一致: {versions}")
        return None
    ver = vals.pop()
    with open(os.path.join(tree, "CHANGELOG.md"), encoding="utf-8") as f:
        if f"## v{ver}" not in f.read():
            fail(f"CHANGELOG.md 缺少 v{ver} 条目")
    print(f"  [A] 版本一致: {ver}")
    return ver


def check_forbidden_files(tree):
    for root, dirs, files in os.walk(tree):
        rel = os.path.relpath(root, tree)
        parts = set(rel.split(os.sep))
        if parts & FORBIDDEN_DIRS:
            fail(f"禁发目录存在: {root}")
            dirs[:] = []
            continue
        for fn in files:
            if fn in FORBIDDEN_DOTFILES:
                fail(f"打包元 dotfile 应剔除: {os.path.join(rel, fn)}")
            if fn == "pack.sh":
                fail(f"pack.sh 应剔除: {os.path.join(rel, fn)}")
            if fn.endswith(FORBIDDEN_SUFFIXES):
                fail(f"非白名单后缀: {os.path.join(rel, fn)}")
            if fn.endswith(".txt"):
                rp = os.path.relpath(os.path.join(root, fn), tree).replace(os.sep, "/")
                if rp not in ALLOWED_TXT:
                    fail(f".txt 非例外清单文件，应剔除: {rp}")
    print("  [B] 禁发文件扫描完成")


def check_abolished_usage(tree):
    for rel in OPERATIONAL_DOCS:
        p = os.path.join(tree, rel)
        if not os.path.exists(p):
            warn(f"操作类文档缺失（跳过扫描）: {rel}")
            continue
        with open(p, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                for pat, negatives in ABOLISHED_PATTERNS.items():
                    if pat not in line:
                        continue
                    if pat == "skills/@":
                        fail(f"{rel}:{i} 旧安装路径 skills/@：{line.strip()[:80]}")
                    elif not any(n in line for n in negatives):
                        fail(
                            f"{rel}:{i} 已废除用法「{pat}」以正向语境出现"
                            f"（需含 {'/'.join(negatives)} 之一）: {line.strip()[:80]}"
                        )
    print("  [C] 废除用法扫描完成")


def check_index_links(tree):
    # D1: INDEX.md 内链接
    p = os.path.join(tree, "references", "INDEX.md")
    if not os.path.exists(p):
        warn("references/INDEX.md 缺失")
    else:
        base = os.path.dirname(p)
        with open(p, encoding="utf-8") as f:
            for m in re.finditer(r"\]\(([^)#]+?\.md)\)", f.read()):
                target = os.path.normpath(os.path.join(base, m.group(1)))
                if not os.path.exists(target):
                    fail(f"INDEX.md 指向不存在的文件: {m.group(1)}")
    # D2: SKILL.md 正文 references 引用（链接与反引号提及均查，Hermes 审计 P1 漏检修复）
    sk = os.path.join(tree, "SKILL.md")
    if os.path.exists(sk):
        with open(sk, encoding="utf-8") as f:
            body = f.read()
        for m in re.finditer(r"references/[A-Za-z0-9_./\-]+\.md", body):
            target = os.path.normpath(os.path.join(tree, m.group(0)))
            if not os.path.exists(target):
                fail(f"SKILL.md 正文引用不存在的文件: {m.group(0)}")
    print("  [D] INDEX/SKILL 引用校验完成")


FORBIDDEN_ARCHIVE_GLOBS = [
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


def check_archive_excluded(tree):
    """F: 历史审计档案不得随包分发（v2.27.44 起发布范围声明）。"""
    for root, dirs, files in os.walk(tree):
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), tree).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, g) for g in FORBIDDEN_ARCHIVE_GLOBS):
                fail(f"历史审计档案应不随包: {rel}")
    print("  [F] 审计档案剔除校验完成")


def check_validation_freshness(tree):
    """G: 「已验证」章节须与当前版本一致（版本漂移 / 陈旧实跑日期即 FAIL）。"""
    sk = os.path.join(tree, "SKILL.md")
    if not os.path.exists(sk):
        return
    with open(sk, encoding="utf-8") as f:
        body = f.read()
    m = re.search(r"^version:\s*([0-9.]+)\s*$", body, re.M)
    if not m:
        fail("SKILL.md 缺 frontmatter version")
        return
    ver = m.group(1)
    idx = body.find("## 已验证")
    if idx < 0:
        fail("SKILL.md 缺「已验证」章节（验证状态必须显式声明）")
        return
    section = body[idx: idx + 2000]
    if ver not in section:
        fail(f"「已验证」章节未标注当前版本 {ver}（验证状态与版本漂移）")
    if not re.search(r"20\d{2}-\d{2}-\d{2}", section):
        fail("「已验证」章节缺实跑日期（验证状态须可溯源）")
    print("  [G] 验证状态新鲜度校验完成")


def check_history_pointer(tree):
    """E: 版本沿革指针须指向随包权威来源（CHANGELOG.md），且不得指向已剔除文件。"""
    sk = os.path.join(tree, "SKILL.md")
    if not os.path.exists(sk):
        return
    with open(sk, encoding="utf-8") as f:
        body = f.read()
    if "operations-history.md" in body:
        fail("SKILL.md 仍指向已不随包的 operations-history.md（应指向 CHANGELOG.md）")
    if "CHANGELOG.md" not in body:
        fail("SKILL.md 缺 CHANGELOG.md 权威来源指引")
    print("  [E] 版本沿革指针校验完成")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--src":
        tree = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    elif len(args) == 1 and os.path.isdir(args[0]):
        tree = args[0]
    else:
        print(__doc__)
        return 2
    src_mode = bool(args and args[0] == "--src")
    print(f"publish_consistency_check: {tree}")
    check_versions(tree)
    if src_mode:
        print("  [B] --src 模式跳过禁发文件检查（dev 树按设计含 dotfile/dist/审计探针；该检查面向待发布树）")
        print("  [F] --src 模式跳过审计档案剔除校验（dev 树按设计保留全部档案）")
    else:
        check_forbidden_files(tree)
        check_archive_excluded(tree)
    check_abolished_usage(tree)
    check_index_links(tree)
    check_validation_freshness(tree)
    check_history_pointer(tree)
    for w in warns:
        print(f"  [WARN] {w}")
    if fails:
        print(f"\nFAIL（{len(fails)} 项）：")
        for x in fails:
            print(f"  ✗ {x}")
        return 1
    print("\nPASS：发布一致性检查全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
