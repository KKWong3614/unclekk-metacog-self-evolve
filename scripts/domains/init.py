#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Phase 2.2 领域初始化：把预置模板实例化为一个引擎完全兼容的 .metacog 实例。
# 关键设计：先用 cmd_init 生成标准骨架（CONTRACT + 标准 ratchet schema + 目录），
# 再覆盖 5 个制品的领域特异性内容 + 写领域红线建议，确保 episode/verdict/status/meta-log
# 等命令在领域实例上可直接工作（不引入非标准 ratchet schema）。
import json
from pathlib import Path

import metacog
from . import DOMAIN_TEMPLATES


def merge_template(template, user_config):
    """把用户配置合并进模板（用户给出的字段覆盖默认）。"""
    if not user_config:
        return dict(template)
    merged = dict(template)
    for key in ("A1", "A2_rules", "A3_memories", "A4_policy", "M1_policy", "redlines", "name"):
        if key in user_config and user_config[key] is not None:
            merged[key] = user_config[key]
    return merged


def _entry(eid, status, since, body):
    """生成一条标准 entry 块（与 SEED 同构，供 parse_entries/set_entry_status 解析）。"""
    return "<!-- entry:{} status:{} since:{} -->\n{}\n<!-- /entry:{} -->".format(eid, status, since, body, eid)


def format_single(code, eid, body):
    """A1/A4/M1 单条目格式。"""
    since = metacog.today()
    header = {
        "A1": "# A1 · 系统提示 / 行为基线\n\n> 制品类型：SHE-A1。改动谨慎，需 ≥2 次独立证据。\n",
        "A4": "# A4 · 工具与权限策略\n\n> 制品类型：SHE-A4。工具选择与权限边界，需 ≥2 次证据。\n",
        "M1": "# M1 · 元层演化策略（可被演化 → 自指闭包）\n\n> 这份文件规定“如何提议修改”。它自己也是可演化对象。每次改动必须人类确认。\n",
    }.get(code, "")
    return header + "\n" + _entry(eid, "active", since, body.strip()) + "\n"


def format_rule_bank(rules):
    """A2 规则库：每条规则一个 entry。"""
    since = metacog.today()
    lines = ["# A2 · 规则库\n",
             "> 制品类型：SHE-A2。演化主战场——具体做法沉淀在这里。",
             "> 状态：candidate（证据不足）→ trial（试用期）→ active（已沉淀）→ revoked（已撤销）\n"]
    for i, rule in enumerate(rules, 1):
        eid = "R-{:03d}".format(i)
        rid = rule.get("id", eid)
        lines.append("\n" + _entry(eid, "active", since, "- {} {}".format(rid, rule.get("content", ""))))
    return "\n".join(lines) + "\n"


def format_safety_memory(memories):
    """A3 安全记忆：每条教训一个 entry（append-only）。"""
    since = metacog.today()
    lines = ["# A3 · 安全记忆（APPEND-ONLY）\n",
             "> 制品类型：SHE-A3。只增不减——教训一旦写入永不删除。\n"]
    for i, mem in enumerate(memories, 1):
        eid = "S-{:03d}".format(i)
        mid = mem.get("id", eid)
        lines.append("\n" + _entry(eid, "active", since, "- {} {}".format(mid, mem.get("content", ""))))
    return "\n".join(lines) + "\n"


def _write_redlines_note(metacog_dir, redlines):
    """领域红线建议（advisory）：不修改全局 REDLINES 安全不变式。"""
    lines = ["# 领域红线建议（advisory）\n",
             "> 以下为领域模板附带的**建议**红线，仅供人工参考。",
             "> 引擎的实际红线由 `metacog.py` 的全局 `REDLINES` 常量统一执行，",
             "> 不按领域削弱——这是安全不变式（CONTRACT §3）。\n"]
    for name, pat in redlines:
        lines.append("\n- **{}**：`{}`".format(name, pat))
    metacog.write_text(metacog_dir / "meta" / "domain-redlines.md", "\n".join(lines) + "\n")


def init_domain(domain_name, output_dir, user_config=None):
    """初始化一个领域实例（引擎兼容的 .metacog）。

    返回 {"domain", "path", "artifacts", "engine_compatible": True}
    """
    template = DOMAIN_TEMPLATES.get(domain_name)
    if not template:
        raise ValueError("未知领域: {}（可选：{}）".format(domain_name, ", ".join(DOMAIN_TEMPLATES)))

    template = merge_template(template, user_config)

    root = Path(output_dir).resolve() / ".metacog"
    st = metacog.Store(root)

    # 1) 标准骨架：CONTRACT + 目录 + 标准 ratchet schema（保证 episode/verdict 可用）
    metacog.cmd_init(st, type("Args", (), {})())

    # 2) 覆盖五制品的领域特异性内容
    metacog.write_text(st.artifact_path("A1"), format_single("A1", "A1-000", template["A1"]))
    metacog.write_text(st.artifact_path("A2"), format_rule_bank(template["A2_rules"]))
    metacog.write_text(st.artifact_path("A3"), format_safety_memory(template["A3_memories"]))
    metacog.write_text(st.artifact_path("A4"), format_single("A4", "T-000", template["A4_policy"]))
    metacog.write_text(st.artifact_path("M1"), format_single("M1", "M-000", template["M1_policy"]))

    # 3) 领域红线建议（不修改全局 REDLINES）
    _write_redlines_note(root, template.get("redlines", []))

    return {
        "domain": domain_name,
        "path": root,
        "artifacts": ["A1", "A2", "A3", "A4", "M1"],
        "engine_compatible": True,
    }
