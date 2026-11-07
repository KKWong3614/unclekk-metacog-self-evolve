# 参考文档索引（references/INDEX.md）

> ⚠️ **历史文件口径声明（2026-10-30，v2.27.43）**：历史审计与证据文件**含当时版本的口径**（如已废除的 `--human-ok` 旗标、`METACOG_TRUST_ROOT_ALLOW_DEFAULT=1` 兜底），仅作审计追溯，**勿照抄操作**；现行操作口径一律以 `SKILL.md` 与 `faq-deep.md` / `troubleshooting.md` / `error-glossary.md` 为准。
>
> 🗄️ **发布范围声明（2026-10-30，v2.27.48）**：自本版起，发布包仅携带**第一区「随包文档」**；逐版本审计报告 / Hermes 轮审 dossier / 修复路线图 / 运行层版本沿革 / 早期审计样本 / 旧版测试日志等**历史内容一律不随包分发**（消除「旧版说明与当前信息混淆」），全文保留于作者 dev 树 `references/` 与 `references/archive/` 作证据链；逐版收口明细以随包 `CHANGELOG.md` 为唯一权威来源。

本目录权威参考文档**总索引**，分两区：随包文档（链接在本包内有效）/ 历史审计档案（不随包，仅列名）。本索引同时作为 `unclekk-skill-spec` C11「无孤立文档」检查的互引锚点。

## 一、随包文档（链接在本包内有效）

### 1.1 新手路径（按此顺序读）

1. [端到端叙事：从 init 到第一个 PROMOTE](walkthrough-first-promote.md) — 一条真实命令链串起全部概念，叙事式上手
2. [排查手册](troubleshooting.md) — 场景化排错：症状 → 原因 → 修复
3. [报错词典](error-glossary.md) — 报错文案逐条词典：文案 → 含义 → 处置
4. [深度 FAQ](faq-deep.md) — 边缘场景 / 工具兼容 / 安全合规 / 退出码 rc 一览（Q23）
5. [反模式手册](anti-patterns.md) — 七类高频误用四段式对照 + REVERT 后处置与连续 3 次 REVERT 决策树（类别七）

### 1.2 设计与规格

- [论文映射](paper-mapping.md) — 论文逐条落地映射
- [非对称信任根设计](asymmetric-trust-root-design.md) — C-1 完全非对称化设计原理 + 诚实边界（§6 为第三方审计核对重点；v2.27.44 起随包）
- `design/` 子目录：
  - [M1 自动触发规格](design/m1-auto-trigger-spec.md)
  - [跨领域模板规格](design/domain-template-spec.md)
  - [性能 Benchmark 规格](design/benchmark-spec.md)
- `benchmark/` — 性能基准结果（`results/`、`summary.json`）

### 1.3 信任、治理与证据

- [C-1 owner 结案裁定书](c1-owner-closure-instrument.md) — v2.27.37 owner（KK）治理结案的正式裁定
- [第三方审计签核指南](third-party-audit-signoff-guide.md) — 生态外第三方审计的执行与签核流程
- [测试证据](test-evidence.md) — **当前版本测试摘要**（2026-10-30 实跑 **56/56 套件诚实 PASS**；随包清单 `scripts/test-suite-manifest.txt` 锚定分母，可独立复现）
- 版本沿革与逐版收口明细：见随包 [`CHANGELOG.md`](../CHANGELOG.md)（唯一权威来源）；更早版本的原始审计档案不随包分发

## 二、历史审计档案（**不随包分发**，dev 树 `references/` 保留）

> 以下仅列名备查（无链接 = 不在本包内）。逐版裁定摘要见随包 `CHANGELOG.md` 与 `operations-history.md`。

- **独立审计**（隔离上下文 / 独立 Agent 审计长）：`independent-audit-v2.2.6.md`、`independent-audit-v2.3.0/2.3.1/2.3.2.md`、`independent-audit-v2.4.0.md`、`independent-audit-v2.5.0.md`、`independent-audit-deep-v2.5.0.md`、`independent-audit-v2.5.8.md`、`independent-audit-hermes-N8-sigcrypto.md`、`independent-audit-hermes-v2.5.1/2.5.2/2.5.3.md`、`independent-audit-hermes-v2.6.0/2.6.1/2.6.2.md`、`independent-audit-hermes-v2.7.1.md`、`independent-audit-v2.8.11-r3.md`、`audit-r15-independent-2026-10-16.md`
- **Hermes 轮审与 dossier**：`hermes-audit-v2.25.14-15.md`、`hermes-audit-v2.25.16-17.md`、`hermes-audit-v2.26.1-r6.md`、`hermes-audit-v2.27.0-r7.md`、`hermes-audit-v2.27.28-C1-external-domain-gate.md`、`hermes-audit-v285/286/287/288-dossier.md`、`hermes-audit-v290-r7.md`
- **逐版轮审**：`audit-v2.6.6-hermes-indep.md`、`audit-v2.7.4/2.7.5/2.7.6/2.7.7/2.7.8.md`、`audit-v2.8.0/2.8.1/2.8.2/2.8.3/2.8.4.md`
- **治理与修复**：`audit-response-2.27.13.md`、`remediation-plan-v1.5.0.md`、`remediation-roadmap-v2.27.15.md`、`remediation-roadmap-v2.27.16.md`、`implementation-checklist-v2.0.md`、`audit-findings-2026-10-26.md`、`audit-handoff-package.md`、`audit-env-spec.md`
- **设计存档与杂项**：`v2.6.0-external-anchor-design-DRAFT.md`、`trace-reliability-2026-09-12.md`
- **运行层沿革与旧版日志**：`operations-history.md`（v2.2.5→v2.27.x 逐轮收口叙事，v2.27.48 起不随包）、`test-evidence-history-v2.1.1.md`（v2.1.1 时代 2026-09 实跑日志）、`independent-audit-v2.1.1.md` 与 `independent-audit-integrated-v2.1.2.md`（v2.1.x 早期审计样本）
- **目录存档**：`audit-probes-v22518/`（对抗探针，含真实攻击复现能力，v2.27.13 起不随包）、`obsolete/`（历史脚本，v2.27.14 起不随包）、`archive/`（v2.27.48 起的历史内容归档区）
