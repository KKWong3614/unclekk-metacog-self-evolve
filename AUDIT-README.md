# AUDIT-README · unclekk-metacog-self-evolve

> **审计人入口（v2.27.33 起，收口轨迹至 v2.27.36）**：本文件是送审包/技能树的根级导航。

## 从哪里开始

1. **送审对象与状态**：[`references/audit-handoff-package.md`](references/audit-handoff-package.md)
   —— 被审版本、包 SHA-256、审计人操作指引（材料清单 / 独立验签 / 复跑命令）、已知 OPEN 发现登记。
2. **发现与收口台账**：[`references/audit-findings-2026-10-26.md`](references/audit-findings-2026-10-26.md)
   —— 两轮生态外独立审计（v2.27.30 FAIL / v2.27.32 FAIL 2.5/5）的全部发现、修复轨迹与诚实残余。
3. **设计文档**：[`references/asymmetric-trust-root-design.md`](references/asymmetric-trust-root-design.md)
   —— C-1 双密钥根信任（RK/AK）的威胁模型与收口历史。

## 审计人须知（红线摘要）

- **Agent 产物不构成 Leg-2 签字**；签字须由人类本人作出并注明所审版本与包哈希。
  **v2.27.37 治理修订**：原「第三方人类签字」判据经 owner 裁定不可得（连续五轮审计方均为 AI 且合法拒签），已修订为 **Leg-2'**（多轮生态外审计全绿 + 残余全披露 + owner 人类结案裁定担责）——C-1 状态由 OPEN 改为 **CLOSED（owner 结案，附披露残余）**，见 `references/c1-owner-closure-instrument.md` 与 `third-party-audit-signoff-guide.md` §10；「Agent 不得代签」红线与审计方独立结论权不变。
- 独立复验：`audit/verify-manifest.py`（无密钥）→ `skill/scripts/_run_all_tests.py`（期望全量 PASS）→
  `anchor-attest-verify`（v2.27.33 起内置账本-实物对账，无需锚密钥）。
- 包内同生态审计报告仅作参考输入，不得引用其结论。
- 环境规格：[`references/audit-env-spec.md`](references/audit-env-spec.md)；探针骨架：`audit/probes/`。

## 版本

当前版本见 `SKILL.md` / `package.json`（应与 `scripts/metacog.py` 的 `MIN_SUPPORTED_VERSION` 一致）。
变更史见 [`CHANGELOG.md`](CHANGELOG.md)（严格版本降序）。
