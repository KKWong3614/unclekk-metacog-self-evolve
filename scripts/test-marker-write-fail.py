#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2.21.0（Hermes r17 M-新-1 收口）边界用例：模拟 `_write_marker()` 失败 → `record()` 须 fail-closed 回滚。

验证不变量「标记存在 ⟺ (ledger 存在 & 锚匹配)」：
- marker 写入失败时，record() 必须回滚本次 ledger 追加并把锚还原到覆盖前内容，
  绝不能留下「ledger+锚在、标记缺」的不一致态（否则后续删 ledger+锚 会被误判为首次安装、绕过 RESET-BLOCKED）。
- 测试将 SKILL_ROOT/锚点重定向到临时目录，绝不触碰生产冻结态（~/.metacog_freeze_anchors/）。
"""
import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import freeze as F  # noqa: E402

fails = []


def check(name, cond):
    if cond:
        print("[PASS] %s" % name)
    else:
        print("[FAIL] %s" % name)
        fails.append(name)


base = Path(tempfile.mkdtemp(prefix="markerfail_"))  # 外层目录
td = base / "skill"      # 技能根（SKILL_ROOT）
td.mkdir(parents=True, exist_ok=True)
anchor = base / "anchor" / "test.anchor"  # 树外锚点（在技能根之外）
anchor.parent.mkdir(parents=True, exist_ok=True)
_orig_skill_root = F.SKILL_ROOT
_orig_freeze_file = F.FREEZE_FILE
_orig_marker = F._write_marker
_orig_anchor_env = os.environ.get("METACOG_FREEZE_ANCHOR")

try:
    F.SKILL_ROOT = td
    F.FREEZE_FILE = td / "frozen-hashes.jsonl"
    os.environ["METACOG_FREEZE_ANCHOR"] = str(anchor)
    (td / "a.txt").write_text("hello", encoding="utf-8")

    # ① 模拟 _write_marker 失败
    F._write_marker = lambda: False
    rc = F.record(["a.txt"])
    check("M-新-1 record 返回 -1（marker 失败 fail-closed）", rc == -1)
    check("M-新-1 ledger 已回滚（首初始化 → 删空 ledger）", not F.FREEZE_FILE.exists())
    check("M-新-1 锚点已回滚（首初始化 → 无锚）", not anchor.exists())
    check("M-新-1 标记未遗留（无 .installed 孤儿）", not list(anchor.parent.glob("*.installed")))

    # ② 还原 _write_marker 后，正常 record 应成功（证明回滚仅作用于失败那次）
    F._write_marker = _orig_marker
    rc2 = F.record(["a.txt"])
    check("恢复正常后 record 成功（返回 1）", rc2 == 1)
    check("正常 record 后 ledger 存在", F.FREEZE_FILE.exists())
    check("正常 record 后锚点存在", anchor.exists())
    check("正常 record 后标记存在", list(anchor.parent.glob("*.installed")) != [])

    # ③ 追加场景：第二次 record 时标记失败 → 须还原旧锚（而非破坏既有冻结态）
    F._write_marker = lambda: False
    (td / "b.txt").write_text("world", encoding="utf-8")
    rc3 = F.record(["b.txt"])
    check("M-新-1 追加场景 record 返回 -1", rc3 == -1)
    # 回滚后 ledger 仍只有首条 a.txt（b.txt 未追加），锚与 ledger 一致
    lines = F._load_lines() if F.FREEZE_FILE.exists() else []
    paths = [json.loads(x).get("path") for x in lines]
    check("M-新-1 追加场景 ledger 未含 b.txt（回滚生效）", "b.txt" not in paths)
    check("M-新-1 追加场景 ledger 仍含 a.txt（既有态保留）", "a.txt" in paths)
finally:
    F.SKILL_ROOT = _orig_skill_root
    F.FREEZE_FILE = _orig_freeze_file
    F._write_marker = _orig_marker
    if _orig_anchor_env is None:
        os.environ.pop("METACOG_FREEZE_ANCHOR", None)
    else:
        os.environ["METACOG_FREEZE_ANCHOR"] = _orig_anchor_env
    shutil.rmtree(base, ignore_errors=True)

total = 12 - len(fails)
print("=== %d/%d PASS ===" % (total, 12))
sys.exit(1 if fails else 0)
