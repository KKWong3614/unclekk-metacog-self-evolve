#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Phase 2.2 领域初始化：把预置模板实例化为一个引擎完全兼容的 .metacog 实例。
# 关键设计：先用 cmd_init 生成标准骨架（CONTRACT + 标准 ratchet schema + 目录），
# 再覆盖 5 个制品的领域特异性内容 + 写领域红线建议，确保 episode/verdict/status/meta-log
# 等命令在领域实例上可直接工作（不引入非标准 ratchet schema）。
import json
import shutil
from pathlib import Path

import metacog
from . import DOMAIN_TEMPLATES


def merge_template(template, user_config):
    """把用户配置合并进模板（用户给出的字段覆盖默认）。

    v2.27.15（N-08 收口，外部审计 v2.27.14 High）：``--config`` **不再允许覆盖安全制品内容**
    （A1 / A2_rules / A3_memories / A4_policy / M1_policy）。原实现把 --config 提供的五个制品
    字段经裸字符串拼装直写盘（不过 render_entry 转义、不过 A1/A4/M1 人类签名闸）——持普通
    命令执行权的 Agent 自写一份 cfg.json 即可注入伪造 ``status:active`` 系统提示/安全记忆/策略，
    整个门禁模型在初始化阶段被绕过。这违背本技能「人在环」设计目标：任何绕过人类闸的安全
    内容写入路径都必须被拒绝。

    现仅允许 ``name``（显示名）与 ``redlines``（advisory 参考注记，非条目、不进制品）覆盖。
    安全制品的领域定制须在 init-domain 之后经 ``propose`` 提案 + 人类签名闸完成。
    """
    if not user_config:
        return dict(template)
    _FORBIDDEN = ("A1", "A2_rules", "A3_memories", "A4_policy", "M1_policy")
    forbidden = [k for k in _FORBIDDEN if k in user_config and user_config[k] is not None]
    if forbidden:
        raise ValueError(
            "N-08 收口（v2.27.15）：--config 不允许覆盖安全制品内容：{}。"
            "定制这些制品须在 init-domain 之后用 `propose` 提案并过 A1/A4/M1 人类签名闸"
            "（人在环设计目标：拒绝一切绕过人类闸的安全内容写入路径）。".format(", ".join(forbidden)))
    merged = dict(template)
    for key in ("name", "redlines"):
        if key in user_config and user_config[key] is not None:
            merged[key] = user_config[key]
    return merged


def _entry(eid, status, since, body):
    """生成一条标准 entry 块（与 SEED 同构，供 parse_entries/set_entry_status 解析）。

    v2.27.15（N-08 收口，纵深防御）：改经 ``metacog.render_entry`` 产出——与 propose/apply
    同一转义层。即便 --config 已拒绝覆盖安全制品，内置模板与未来模板贡献者的正文若内嵌
    ``<!--``/``-->`` 也只会被转义，不再可能伪造条目（消除裸字符串拼装这一注入类根源）。
    """
    return metacog.render_entry(eid, status, since, "", body)


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
    """领域红线建议（advisory）：不修改全局 REDLINES 安全不变式。

    v2.27.16（L-7③ 收口）：redlines 格式校验——原 `for name, pat in redlines` 在传入
    非 [[name, pat], ...] 结构（如 {"redlines": ["x"]} 误传字符串列表）时抛晦涩的
    ValueError（解包失败），经 cmd_init_domain 的通用 ValueError 分支被误导为「检查 --domain
    取值」。**现显式校验**并给出指向真实原因的清晰报错。"""
    if not isinstance(redlines, (list, tuple)):
        raise ValueError(
            "redlines 须为 [[名称, 正则], ...] 形式的列表（当前类型 {}）；"
            "请修正 --config 的 redlines 字段。".format(type(redlines).__name__))
    _normalized = []
    for _i, _item in enumerate(redlines):
        if not (isinstance(_item, (list, tuple)) and len(_item) == 2):
            raise ValueError(
                "redlines 第 {} 项须为 [名称, 正则] 二元组（当前：{!r}）；"
                "请修正 --config 的 redlines 字段。".format(_i, _item))
        _normalized.append((str(_item[0]), str(_item[1])))
    lines = ["# 领域红线建议（advisory）\n",
             "> 以下为领域模板附带的**建议**红线，仅供人工参考。",
             "> 引擎的实际红线由 `metacog.py` 的全局 `REDLINES` 常量统一执行，",
             "> 不按领域削弱——这是安全不变式（CONTRACT §3）。\n"]
    for name, pat in _normalized:
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
    # v2.27.16（M-6 收口）：记录实例是否由本次新建——仅当本次新建失败时回滚半制品，
    # 既有实例（_fresh=False）绝不删除（防误删用户数据，TOCTOU 属已知限制，见路线图 L-7⑤）。
    _fresh = not root.exists()
    try:
        st = metacog.Store(root)

        # 1) 标准骨架：CONTRACT + 目录 + 标准 ratchet schema（保证 episode/verdict 可用）
        metacog.cmd_init(st, type("Args", (), {})())

        # 2) 覆盖五制品的领域特异性内容
        metacog.write_text(st.artifact_path("A1"), format_single("A1", "A1-000", template["A1"]))
        metacog.write_text(st.artifact_path("A2"), format_rule_bank(template["A2_rules"]))
        metacog.write_text(st.artifact_path("A3"), format_safety_memory(template["A3_memories"]))
        metacog.write_text(st.artifact_path("A4"), format_single("A4", "T-000", template["A4_policy"]))
        metacog.write_text(st.artifact_path("M1"), format_single("M1", "M-000", template["M1_policy"]))

        # 2.5) D4 完整性基线重记 + 领域种子实证（v2.27.16 H-2 收口）：
        # 原实现在覆盖后「unlink seed-ids.json + _write_seed_ids」无差别重采，构成洗白面
        # （攻击者在 live 实例注入条目后重跑 init-domain 即可把注入纳入种子集）。
        # 现改为：五制品刚被模板全量可信覆盖（覆盖已抹除任何注入），调用 _write_seed_ids(force=True)
        # 仅在此次可信覆盖后一次性重采领域种子（安全）；非首次/init 重跑不再静默重采（guard 已拦）。
        # v2.27.15（Hermes 三审 C-N3b 收口）：领域种子 id 实证落盘——五制品刚被模板覆盖（制品即模板纯态），
        # 须重新生成以匹配领域种子（R-001..R-0NN 等领域 id 不在骨架集里，不刷新会被 N-11 扫描误报）。
        metacog._write_seed_ids(st, force=True)
        if (st.root / "meta" / "seed-ids.json").exists():
            st.record_integrity("meta:seed-ids.json")
        for _a in ("A1", "A2", "A3", "A4", "M1"):
            st.record_integrity(_a)

        # 3) 领域红线建议（不修改全局 REDLINES）
        _write_redlines_note(root, template.get("redlines", []))

        return {
            "domain": domain_name,
            "path": root,
            "artifacts": ["A1", "A2", "A3", "A4", "M1"],
            "engine_compatible": True,
        }
    except Exception as e:
        # v2.27.16（M-6 收口）：失败回滚——仅当本次新建实例才清掉半制品（"制品已写但基线未建"的
        # 半成品：init 先写骨架制品、record_integrity 因缺信任根锚而失败，会留一个 verify 必红且
        # 含义模糊的残留）。既有实例（_fresh=False）绝不删除（防误删数据，TOCTOU 已知限制）。
        if _fresh and root.exists():
            shutil.rmtree(root, ignore_errors=True)
        # 保留原异常类型（如 LedgerAnchorDefaultError）与信息，交由 cmd_init_domain 给出准确修复提示。
        raise
