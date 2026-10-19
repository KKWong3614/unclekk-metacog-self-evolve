# 跨领域模板规范（Phase 2.2）

> 来源：implementation-checklist-v2.0.md Phase 2.2
> 落地日期：2026-09-08
> 实现位置：`scripts/domains/__init__.py`（模板）、`scripts/domains/init.py`（初始化）、`metacog.py`（`cmd_init_domain`）

## 1. 目标

让 metacog 引擎可一键实例化到不同专业领域（代码评审 / 论文评审 / 文档编辑），
每个领域自带五制品（A1-A4 + M1）与领域定制红线建议。

## 2. 已预置领域

| 领域 key | 名称 | 红线建议主题 |
|---|---|---|
| `code_review` | 代码评审 | SQL注入/XSS/权限提升/数据泄露 |
| `paper_review` | 论文评审 | 学术不端/伦理/利益冲突 |
| `document_editing` | 文档编辑 | 事实错误/敏感信息/版权侵权 |

## 3. 关键设计决策（相对清单的修正）

- **先用 `cmd_init` 生成标准骨架，再覆盖五制品**：保证领域实例的 `ratchet.json` 是
  引擎标准 schema（`baseline_utility`/`window`/...），`episode`/`verdict`/`status`/`meta-log`
  命令在领域实例上可直接工作。清单原 `init_domain` 写入的非标准 ratchet schema 会导致引擎读不出基线。
- **领域红线仅作 advisory**：写入 `meta/domain-redlines.md`，**不修改** `metacog.py` 全局
  `REDLINES` 常量——全局红线是安全不变式（CONTRACT §3），禁止按领域削弱。
- **`--config` JSON 合并**：用户配置覆盖模板的 A1/A2_rules/A3_memories/A4_policy/M1_policy/redlines/name。

## 4. 五制品落点（与通用实例一致）

| 制品 | 路径 |
|---|---|
| A1 系统提示 | `artifacts/A1-system-prompt.md` |
| A2 规则库 | `artifacts/A2-rule-bank.md`（每条规则一个 entry） |
| A3 安全记忆 | `artifacts/A3-safety-memory.md`（append-only，每条一个 entry） |
| A4 工具策略 | `artifacts/A4-tool-policy.md` |
| M1 元层策略 | `meta/M1-evolve-policy.md` |

所有条目用标准 `<!-- entry:ID status:active since:DATE -->` 标记包裹，供 `parse_entries`/`set_entry_status` 解析。

## 5. 命令

```bash
python3 metacog.py init-domain code_review                 # 当前目录生成 .metacog
python3 metacog.py init-domain paper_review -o ./my_review # 指定输出目录
python3 metacog.py init-domain document_editing -c cfg.json  # 用户配置合并
```

## 6. 验收

- 3 领域均成功实例化五制品，且引擎兼容（ratchet 标准 schema）。
- 领域特异性内容正确（A2 含领域关键词）。
- 全局 `REDLINES` 不变（安全不变式守住）。
