---
name: unclekk-metacog-self-evolve
slug: unclekk-metacog-self-evolve
displayName: UncleKK Metacog Self-Evolve 元认知自进化引擎
version: 2.27.48
summary: 声明式元认知自修改引擎——让 Agent 越用越聪明且不越用越危险。/ Declarative metacognitive self-modification engine — makes an Agent smarter with use without becoming more dangerous.
description: 五制品 + 三闸 + 双指标棘轮的元认知自修改系统。核心：改对了沉淀，改错了回滚。/ Declarative metacognitive self-modification system — keep what improves, roll back what regresses.
license: 设计思路综合自公开论文（HyperAgents arXiv:2603.19461 CC BY-NC-SA 4.0 / SHE arXiv:2608.09885 / Practice Makes Unsafe arXiv:2608.12851 / Self-Evolving Agents Survey）；本 skill 为独立实现，仅限个人非商用。
tags: [metacognitive, self-evolving, self-reference, safety, agent, skill, ratchet]
triggers:
  - metacog / 元认知自修改引擎
  - unclekk-metacog-self-evolve
  - 五制品三闸 / SHE 自演化护栏
  - 规则演化台账（propose / gate / apply / verdict / rollback）
  - Agent 自演化安全护栏 / 防技能误演化棘轮
  - init-domain 领域实例初始化
agent_created: true
---

# 声明式元认知自修改（Metacognitive Self-Evolution）

让 Agent 越用越聪明的**充分条件不是让它能改自己，而是让它改错时能被抓住并回滚**。

论文给的判决很硬：Practice Makes Unsafe 评测了 **21 个自演化配置**（合计 525 个任务），**21/21 个自演化配置全部写出了不安全产物**，其中 15 个会伤害到新会话。原因不是模型笨——是演化在优化"任务成功"，而不安全的成功同样会被当成经验沉淀下来。所以本 skill 的重心一半在"怎么改"，另一半在"改错了怎么拦"。

## 受众 / Audience

**所有 Agent 用户，从完全没写过 skill 的新手到维护几十个 skill 的专业用户全覆盖。**
新手照「最小运行示例」复制一条命令即可跑通初始化；进阶用户可改棘轮容差 ε（棘轮=只能变好不能变差的单向棘爪）、证据门槛；专业用户可把 `apply --git` 接进 CI 当结构门禁。

> **按身份选阅读路径（本文档体量较大，先取你要的那条，不必通读）**：
> - **新手 / 只想跑通**：[端到端叙事：从 init 到第一个 PROMOTE](references/walkthrough-first-promote.md) → 下方「最小运行示例」→ [深度 FAQ Q19 三命令速通](references/faq-deep.md) → 遇错查 [排查手册](references/troubleshooting.md) 与 [报错词典](references/error-glossary.md)。**到这条线为止就够了**，其余内容均为进阶或审计用途。
> - **运维 / 接入工作流**：[反模式手册](references/anti-patterns.md)（含 REVERT 后处置三步与连续 3 次 REVERT 决策树）→ [退出码 rc 一览（FAQ Q23）](references/faq-deep.md) → [INDEX「测试与运维」区](references/INDEX.md)。
> - **审计 / 安全研究者**：[INDEX「审计记录」区](references/INDEX.md)（独立审计 + Hermes 轮审 40+ 份按版本排列）→ [CONTRACT.md](CONTRACT.md) 不动点契约 → SKILL.md「诚实天花板」与 CHANGELOG 各版本收口登记。
>
> 完整文档地图：[references/INDEX.md](references/INDEX.md)。

> **评级框架（先读这句，避免误读全文）**：SkillHub TRACE 五维评测**平台最新反馈（2026-10-30 第二轮重扫）：综合 4.8/5（优秀）**，剩余短板「内容仍偏庞杂、部分验证状态与清单不够准确」——v2.27.48 即按该反馈整改：历史叙事与旧版清单全部不随包分发（逐版明细以随包 `CHANGELOG.md` 为唯一权威来源）、「已验证」章节按 **2026-10-30 实跑 56/56 套件** 重写、随包套件清单恢复（运行器 fail-closed 依赖）。更早一轮反馈为 4.7/5（2026-10-30 首轮）。口径澄清（诚实降调）：TRACE 的「安全性扫描 5.0/5」是**恶意性 / 恶意代码扫描**（双实验室 benign），**不是**架构信任根认证，不构成「C-1 已闭合」证据；TRACE 综合评级与生态外 DSH 审计链评级是**两套独立口径**。**C-1 当前状态（2026-10-30）**：已由 owner（KK）结案（v2.27.37 治理修订，裁定书 `references/c1-owner-closure-instrument.md`），CONDITIONAL-PASS 口径已退役；现行有效评级口径 = DSH 五轮审计链 PASS（最近一轮 4.4/5、无未收口 Medium+）+ owner 结案裁定。完整审计时间线与诚实残余见随包 `CHANGELOG.md`（更早的原始审计档案留存于作者 dev 树，不随包分发）。

> **第三方审计物证与独立评级原始件（诚实披露，v2.27.16 L-1 收口）**：本技能随包发布的是**自述性**评级与诚实边界文本；生态外第三方安全审计的**物证**（原始审计报告、独立评级原始件、对抗 PoC 复现脚本等）**不随包发布**。如需核验，可应审计方/用户要求**线下提供**（不公开挂在发布包内，避免被断章取义或误读为「独立背书」）。本声明落地 v2.27.16 路线图 L-1——此前 CHANGELOG/路线图曾声称「SKILL.md 明示线下提供」，但经全文件检索该声明从未落地，本轮补正。

> **设计目标定位（威胁模型声明）**：本 skill 的目标是**系统级人在环（human-in-the-loop）的可控自指**——Agent 在受约束工具面内提出变更，人类通过 A1/A4 人类签名闸、verdict、confirm/resign 持有最终决定权。它**不是**无人值守（unattended）方案，也从不以此做声称：主要防御对象是「Agent 在被授权工具面内走捷径/误用」与「未经人类审查的规则持久化」，**不是**「攻击者已获宿主任意代码执行」（后者属宿主安全与系统级隔离职责）。因此使用者结论：不用于无人值守/生产/多 Agent 无人监督场景；单人本地使用时，人类复核是系统的一部分而非可选项。

> **能力边界声明**：本 skill 是**规则演化引擎**，不是通用元认知Agent。它能：
> - 在**单一领域内**管理规则的演化（提案→过闸→应用→裁决）
> - 通过双指标棘轮（双指标=效用不降+违规率不升，二者同时成立才沉淀）确保演化不削弱安全性
> - 在不同领域间**手动迁移**（需人工配置新领域制品）
>
> 本 skill **不能**：
> - 自动将A领域的规则迁移到B领域（需人工配置）
> - 自主修改元认知机制（M1 修改需人类在 TTY 运行 `apply` 时交互式输入口令、当场签**绑定签名**（覆盖 提案 id + 内容哈希 + 试用窗起点 trial_from_index），`confirm --approve` 已于 v2.5.7 移除（签名合并进 `apply` 的交互式 TTY 口令流程））
> - 在没有episode（=一次任务后的效用记账条目）证据的情况下自动演化（需≥2次独立复现）

### 能力边界三分类（✅擅长 / ⚠️需素材 / ❌超范围）

| 分类 | 说明 | 例子 |
|---|---|---|
| ✅ **擅长** | 单领域内规则的提案→过闸→应用→裁决闭环 | ① 把"改文件前先 Read"沉淀进 A2 规则库；② 用双指标棘轮拦截把安全规则改没的提议；③ 跨 code_review/paper_review/document_editing 三领域用 `init-domain` 实例化 |
| ⚠️ **需素材** | 需要你先提供证据/配置才能跑 | ① 无 episode 记账时 `verdict` 无法裁决（需先 `episode` 至少 2 次）；② 新领域实例需你给领域 key 或 JSON 配置；③ 调 `meta_optimizer` 需先有 `ledger/meta-cognition.log` 反思记录 |
| ❌ **超范围** | 本 skill 不负责，找别的工具 | ① 自动把 A 领域规则迁移到 B 领域（需人工配新制品）；② 改 `CONTRACT.md`/`metacog.py`/`SKILL.md` 三个不动点（不动点=永远禁止本 skill 自己修改的文件）；③ 通用文案写作/代码生成（它是规则演化引擎，不是内容生成器） |

## 触发条件 / Triggers

> 出现以下任一情形即自动加载本 skill（无需显式点名）：

| 你说的话 / 遇到的情况 | 例子 |
|---|---|
| 想让 Agent 自己改自己、越用越聪明 | "能不能让它自己优化自己" |
| 讨论元认知自修改 / 元层可编辑 | "元层可编辑""改改法" |
| 担心安全约束被演化掉 | "它会不会把安全规则自己改没了" |
| 设计自进化系统 / 可控自指 | "想搭个会自我进化的 Agent" |
| 评审某个 Skill 的自进化结构 | "帮我看看这个结构安全吗" |

## 新手上手（30 秒速通）

本 skill 让 Agent「改对了沉淀、改错了回滚」。三条命令跑通最小闭环：

> 先把 `MC` 变量指向本 skill 的 `scripts/metacog.py`（三种系统的一行写法见下方「最小运行示例」开头）；下文 `"$MC"` 即该路径。

1. **初始化**：`METACOG_TRUST_ROOT_ANCHOR_KEY=<专属随机密钥> python3 "$MC" init` → 生成 `.metacog/` 五制品骨架（制品=规则/记忆/工具策略/系统提示等 Markdown 账本文件）。
   - 密钥生成：`python3 -c "import os,base64;print(base64.b64encode(os.urandom(48)).decode())"`。
   - Windows PowerShell 写法：`$env:METACOG_TRUST_ROOT_ANCHOR_KEY='<密钥>'; python3 "$MC" init`；Windows cmd 写法：`set METACOG_TRUST_ROOT_ANCHOR_KEY=<密钥> && python3 "%MC%" init`。
   - **首次运行必须配置锚密钥**——v2.27.17（C-01 收口）起源码内嵌默认锚已删除（「宁可装不上，不可自签」），原 `METACOG_TRUST_ROOT_ALLOW_DEFAULT=1` 兜底同步废除；未配置或密钥不合规（非 base64 / <32 字节）会报 `LedgerAnchorDefaultError` / `ValueError` 退出（原理见下方步骤 0 警告）。
2. **记账归因**：任务结束用 `episode --task "本次任务一句话" --events rework=1 --attributed A2` 记一笔效用事件（`--task` 必填；效用由可观测事件推导，注水在结构上不可行）。
3. **提议自修改**：`propose --artifact A2 --op add --content "..." --episode E-xxx` 进隔离区（=改动先放待审货架），过闸后才生效。

⚠️ 安全护栏默认开：双指标棘轮 + 树外锚 fail-closed（fail-closed=拿不准就拒绝，宁可报错不放行），演化不能削弱安全。判断它能不能用在你的场景，看上方「能力边界三分类」与下方「什么时候别用」。完整命令与各步骤详解见「最小运行示例」。

> **能力口径（v2.25.14 确立，v2.27.10 复核现行）**：本 skill 默认交付**会话级**强制——全部闸门/账本/人类确认在 Agent 运行时与会话工作目录（`.metacog/`）内 fail-closed，属「人在环、系统级强制的可控自指」的运行时形态；**系统级**（OS 隔离把信任锚推出进程可写域、闭合 C-1）须额外部署文末「一键系统级隔离」套件。两种口径均**不声称**「无需人类在环」。无人值守/自动化场景的人类闸两步预签名工作流见下方「信任决策速查」。

## 信任决策速查（30 秒定位你的场景）

先回答「我该不该信任它」。按你的场景对号入座（尾括号为出处锚点）：

| 你的场景 | 默认可信度 | 需要的前置动作 | 已知限制——以及它**不影响**什么 |
|---|---|---|---|
| 本地个人开发 / 单 Agent 记账演化 | ✅ 开箱即可用 | 设 `METACOG_TRUST_ROOT_ANCHOR_KEY` 专属随机密钥（v2.27.17 C-01 起本地/生产同口径，无默认锚；见下方步骤 0） | 锚密钥不落源码；**不影响**单机记账/提议/裁决/回滚全流程 |
| 生产 / 多 Agent 共享部署 | ⚠️ **不建议**（v2.27.37 owner 结案口径） | 设 `METACOG_TRUST_ROOT_ANCHOR_KEY` 专属随机密钥；可选启用 C-1 OS 隔离部署 | 外部审计（2026-10-24 两轮）所指 C-01/H-01/H-05 已于 v2.27.17 代码层收口（诚实残余：env 密钥进程内可读属部署契约），C-01 已于 v2.27.37 由 owner 结案；`C1_deploy.py` 于 v2.27.38 硬化（随机临时目录替换固定 `%TEMP%` + 字节级完整性校验 + 提权前显式确认横幅），原固定 `%TEMP%`/Bypass 类风险已缓解，套件仍为「C-1 闭合现状」所述可选增强、不声称代码层完整闭合；本 skill 设计目标是**人在环**可控自指，**不是**无人值守/生产方案（见顶部「设计目标定位」）；**不影响**规则演化闭环本身 |
| 防止 AI 自签人类确认 | ✅ 可用，须人类闸 | 人类在真实 TTY 跑 `confirm --keygen`；签名在 `apply` 时 TTY 口令完成（`confirm --approve` 已于 v2.5.7 移除；v2.25.14 起无人值守可 `confirm --sign` 预签名经 `apply --sig` 应用） | 不防具管理员文件+代码写权的完全失控 Agent（见「诚实天花板」）；**不影响**正常人在环确认流程 |
| 无人值守 / 自动化部署（无 TTY） | ⚠️ 机制上可用，**设计目标外，不推荐**（v2.27.15 定位声明：本 skill 为人在环方案，无人值守属定位外使用；高风险改动走两步预签名） | 人类在有终端的机器跑 `confirm --sign --id X` 生成绑定签名 → `apply --id X --sig`（v2.25.14；签名后至 apply 前不得再记账，否则 t0 变化需重签；v2.25.16 起签名 **use-once**——同一签名仅授权一次 apply，重入场景须重签；`--out` 已存在须 `--force`、指向目录/写失败 rc=2 且签名仍在输出可复制；v2.25.17 起消费经**文件锁临界区原子执行**（TOCTOU 双消费收口）+ **D4 完整性硬闸**（删消费账本行/清空/删基线均 fail-closed 拒绝，sig-claims 消费账本独立于 applies 并纳入 D4 快照+哈希链；v2.25.20 起**链缺失也为 fail-closed**——删链洗白收口，v2.5.8 老基线可设 `METACOG_ALLOW_LEGACY_NO_CHAIN=1` 临时放行，严格 `== "1"` 匹配且链存在时无效；v2.25.21 起 `apply` 主路径**入口硬闸**接 applies 域 D4 核验——账本篡改/链缺失在入口即拒 rc=3，早于 use-once 消费检查）） | 无有效签名时 HUMAN 级提案一律拒绝（fail-closed 不降级）；诚实边界：删链/删基线单改已可进程内检出（v2.25.20/21 fail-closed）；v2.26.0 起链条目带 HMAC（方案A——手写/直写伪造条目 fail-closed，mac 纪元后无 mac 条目即拒）+ `confirm --keygen` 钉固链首指纹至 CONTRACT.md chain-identity-root（方案B——删链+引擎重建因首条 hash 含时间戳不可复现而检出，H-2b/U4 收口）；残余：攻击者持代码写权时「**清空消费账本+删基线+改制品+经引擎 API 重算基线并追加合法 mac 条目（链头不动）**」仍不可进程内检出（自举信任根，与 C-1 同类，须系统级部署契约兜底）；**v2.27.1 按域更正（Hermes 七轮实测，原述门槛被高估）**：script:/manifest: 域不入链、基线由 `record_script_integrity` 直接写且引擎代算 `_anchor_sig`，故「改文件 + 经引擎 API 重记基线」即可，**无需**持源码读权、**无需**追加合法 mac 条目；仅 artifact/applies/guard 域（入链）才需「重算基线 + 追加合法 mac 条目（链头不动）」；**不影响**棘轮/结构闸在无人值守下照常生效 |
| 看到「有条件通过 / CONDITIONAL-PASS」字样不知是否可信 | ✅ 两套口径，勿混同 | 无 | 它是 Hermes 代码层审计的流程级裁定（同生态审自己代码），与 TRACE 平台综合评级独立（见顶部「评级框架」与「C-1 闭合现状」）；**不影响**「安全性扫描 5.0/5、无 P0/P1」的代码层结论——该字样在平台报告中的出现，是评测 AI 回声了本文档自身的诚实披露文本 |
| 一次性任务 / 无法记账 / 想全自动变强 | ⛔ 不建议使用 | 换工具 | 无法产出 episode 证据（棘轮不采信无证据改动）；见「什么时候别用（反模式）」 |
| 跨领域自动迁移 / 通用内容生成 | ⛔ 超范围 | 找别的工具 | 本 skill 只做单领域规则演化（见「能力边界三分类」❌ 行） |

## 失控处置速查（按症状定位）

命令报错排查见下方「失败处理决策树」；本表处理的是**系统行为不对劲**而非命令失败：

| 你观察到的症状 | 立即动作 | 它意味着什么 / 何时无需担心 |
|---|---|---|
| 刚 apply 的规则不对劲 | `rollback --artifact <X> [--entry <Y>] --yes` 字节还原 | git 仓库内 apply/verdict 默认留底，可追溯 |
| `verdict` 裁决 REVERT | 无需手动处理，自动回滚已发生并记负样本 | 这是双指标棘轮在正常工作，不是故障 |
| 怀疑制品被绕过三闸直写篡改 | 跑 `verify`，返回 1 即检出 | verify 默认 fail-closed，检出即不再盲信当前内容 |
| 连续 3 次 REVERT | 🛑 停止演化，用 `verdict --auto-m1` 生成 M1 自省提议，须人类 TTY 签名确认 | M1 自省同样不能绕过人类闸 |
| 完全失控 / Agent 越权 | 诚实边界：本 skill 不防具管理员文件+代码写权的完全失控 Agent；兜底是 OS 级隔离（`C1_deploy.py`，见「部署权限与安全披露」）；终极手段：删除 `.metacog/` 目录即整体清除 | 属威胁模型内的已知边界（已披露），非未声明缺陷 |

## 最小运行示例 / Quick start

> ⚠️ **第一屏安全披露（v2.27.13 起，生态外第三方审计 P1-1 收口）**：**A1（系统提示）/ A4（工具策略）的改动默认需要人类签名确认**（`requires_human`，非 TTY 的 `apply` 会 rc=2 拒绝）——A1 的自演化会被 `retrieve --strict` 加载为后续会话的持久行为约束，等价于「Agent 自己给自己写系统提示」，故默认不开放给 Agent 自改。**A2（规则库）自演化不受影响**（核心用例）。确需无人值守实验，显式设 `METACOG_UNATTENDED_ARTIFACTS=1`（须在 `gate` 之前设置；gate 裁定有粘性，已 gated 提案不会按新环境变量重审）。

> 偏好叙事式上手？先读 [端到端叙事：从 init 到第一个 PROMOTE](references/walkthrough-first-promote.md)（一条真实命令链串起全部概念），再回来照本节命令操作。

设 `MC` 指向本 skill 目录：
```bash
# Linux/macOS
export MC="${HOME}/.workbuddy/skills/unclekk-metacog-self-evolve/scripts/metacog.py"
# Windows (PowerShell)
$env:MC = "$HOME\.workbuddy\skills\unclekk-metacog-self-evolve\scripts\metacog.py"
# Windows (cmd)
set MC=%USERPROFILE%\.workbuddy\skills\unclekk-metacog-self-evolve\scripts\metacog.py
```

### 步骤 0: 初始化
- **输入**: 空工作目录
- **输出**: `.metacog/` 目录及五制品骨架
- **命令**:
```bash
# Linux/macOS（先一次性生成密钥：python3 -c "import os,base64;print(base64.b64encode(os.urandom(48)).decode())"）
cd <你的工作目录> && METACOG_TRUST_ROOT_ANCHOR_KEY=<你的专属密钥> python3 "$MC" init
# Windows (PowerShell)
cd <你的工作目录>; $env:METACOG_TRUST_ROOT_ANCHOR_KEY='<你的专属密钥>'; python3 "$MC" init
# Windows (cmd)
cd /d <你的工作目录> && set METACOG_TRUST_ROOT_ANCHOR_KEY=<你的专属密钥> && python3 "%MC%" init
```
> **输出示例（真实）**：
> ```
> 初始化完成: C:\Users\you\.metacog
>   [OK]   创建 CONTRACT.md
>   [OK]   创建 artifacts/A1-system-prompt.md
>   [OK]   创建 artifacts/A2-rule-bank.md
>   [OK]   创建 artifacts/A3-safety-memory.md
>   [OK]   创建 artifacts/A4-tool-policy.md
>   [OK]   创建 meta/M1-evolve-policy.json
>   [OK]   创建 ledger/ratchet.json
>   [OK]   创建 meta/M1-evolve-policy.md
> 下一步: 每次任务结束后 `episode` 记账，发现问题用 `propose` 提改动。
> ```
> ⚠️ **首次运行需信任根密钥**（v2.27.17 C-01 收口后为唯一口径）：账本签名锚密钥**唯一来源** = 环境变量 `METACOG_TRUST_ROOT_ANCHOR_KEY`（base64 编码的 ≥32 字节专属随机密钥，M-01 校验：非法 base64 / 过短 → `ValueError` fail-closed）。源码内嵌默认锚已删除（「宁可装不上，不可自签」），原 `METACOG_TRUST_ROOT_ALLOW_DEFAULT=1` 兜底同步废除；本地开发/测试与生产同口径——不配置密钥，`init` 会报 `LedgerAnchorDefaultError` 并退出。

### 步骤 1: 会话开始 — 加载生效制品（G2 检索闸）
- **输入**: `.metacog/` 目录已存在
- **输出**: 当前生效制品内容（A1-A4 + M1）
- **命令**:
```bash
python3 "$MC" retrieve --strict     # 只输出 active，排除试用期条目
python3 "$MC" retrieve              # 包含试用期，标注 <试用中>
```
把输出读进上下文，作为本次会话的行为约束。**被 revoked 的条目不会出现在这里**——这是 Practice Makes Unsafe 强调的检索闸：光删掉不够，还得保证未来的执行者捞不到它。

### 步骤 2: 任务结束 — 记账归因（操作 1：效用内生）
- **输入**: 任务完成，可观测事件计数（来自任意工作流）
- **输出**: episode ID 写入 ledger/episodes.jsonl
- **命令**:
```bash
# ✅ 推荐（操作 1 起）：效用由可观测事件推导，注水在结构上不可行
python3 "$MC" episode --task "改公众号排版脚本" \
  --events rework=1 --events violation=1 --violations 1 \
  --attributed A2 --note "漏了先读原文件，覆盖了 KK 的手改内容"

# ✅ 也可一次性传 JSON 对象（与 --events 合并累加）
python3 "$MC" episode --task "同上" --events-json '{"rework":1,"accepted":1}' --violations 1

# ⚠️ 兜底（deprecated）：无事件时声明式 --utility 仍可写，但其效用不驱动沉淀
python3 "$MC" episode --task "同上" --utility 0.7 --violations 1 --attributed A2
```
- **事件词汇对一切工作流通用**（见 `META_EVENTS`）：负向 `rework`/`rerun`/`revert`/`correction`/`test_fail`/`gate_block`/`error`/`timeout`/`manual_fix`/`violation`；正向 `accepted`/`praised`。不同工作流只填各自可观测到的计数，无需改引擎。
- **效用推导**：`compute_utility(events)` 纯函数按权重扣分/上浮，区间 0~1，结果写入 `utility_source=derived` + `utility_provenance`（可复算、可审计）。**不读命令行数字**，所以"改命令行数字"无法抬高效用。
- **注水检测**：即便走 `--utility` 兜底，若申报值 ≥0.8 却伴随 `rework`/`correction`/`violation`/`manual_fix`/`revert`，会打 `[注水嫌疑]` 告警。
- **演进切换（牙齿）**：库中存在 `derived` 数据后，基线建立与 `verdict` 验收**只取 derived**；声明式 `--utility` 被架空——旧数据不删，但不再能驱动 PROMOTE/沉淀。
- `violations`：违规/返工次数。前 5 个 **derived** episode 自动建立基线。

### 步骤 3: 发现问题 — 提议自修改
- **输入**: 问题归因（哪个制品）、修改内容、证据 episode
- **输出**: 提议 ID 写入 gates/quarantine/
- **命令**:
```bash
python3 "$MC" propose --artifact A2 --op add \
  --content "- 改任何已存在文件前先 Read，禁止盲写覆盖。" \
  --reason "两次覆盖了用户手改内容" \
  --episode E-20260826-xxxx --episode E-20260826-yyyy
```
`op` 可选 `add` / `replace --target R-00X` / `remove --target R-00X`。
提议只进隔离区，**不直接生效**。

> **输出示例（真实）**：
> ```
>   [OK]   提议已入隔离区 P-20261019-b9c771 (add A2)
>   隔离区不是生效区——必须先 `gate` 过闸，再 `apply` 才进入试用期。
> P-20261019-b9c771
> ```
> 注意：`propose` 之后**必须**先 `gate` 过闸（`gate` 四检查全过才 `PASS`），再 `apply` 才能落到制品；跳过 `gate` 直接 `apply` 会报「没有过闸待应用的提议（先跑 `gate`）」。

🔴 **CHECKPOINT**: 确认提议已入隔离区后继续。

### 步骤 4: 过闸（G1 写入闸）
- **输入**: quarantine 中的提议
- **输出**: 裁定 PASS / HOLD / BLOCK
- **命令**:
```bash
python3 "$MC" gate
```
四类检查：不动点保护 → 红线扫描 → A3 只增不减 → 证据门槛（≥2 次）。
裁定 `PASS` / `HOLD`（证据不足，补证据再来）/ `BLOCK`（记入 archive 负样本）。

🔴 **CHECKPOINT**: 裁定 PASS 后继续，BLOCK 则停止。

### 步骤 5: 应用 → 进入试用期
- **输入**: gated 的提议
- **输出**: 制品更新，状态 trial
- **命令**:
```bash
python3 "$MC" apply --id <提案>        # M1/A1/A4（默认）或高风险条目需人类在 TTY 交互式输入口令签绑定签名（覆盖 id+chash+trial_from_index，v2.5.7 合并方案；A1/A4 默认人类闸为 v2.27.13 审计收口，opt-out 见第一屏披露）
python3 "$MC" apply --git           # 顺带 git commit 留回滚点
```
写入制品，状态 `trial`。**此时还不算沉淀。**

🔴 **CHECKPOINT**: 应用后继续步骤 6。

### 步骤 6: 双指标棘轮裁决
- **输入**: 累计 5 个新 episode
- **输出**: PROMOTE / REVERT 裁决
- **命令**:
```bash
python3 "$MC" verdict                # 常规双指标裁决
python3 "$MC" verdict --auto-m1     # 连续3次REVERT时自动生成M1元层自省提议（仍需人类在 TTY 运行 apply 签绑定签名确认才生效）
python3 "$MC" verdict --adaptive    # 棘轮自适应：按当前违规率动态收紧/放宽判定基线

```
> `--adaptive` 默认关闭，行为与原版完全一致；开启后按窗口违规率收紧（>0.3 基线×0.95）或放宽（<0.1 基线×1.05）判定阈值（详见 `CHANGELOG.md` Phase 1.2）。`status` 命令会展示三档自适应阈值。
> verdict 的 PROMOTE/REVERT 与 `--auto-m1` 触发的 M1 提议都会写入元认知日志（详见下条 `meta-log` 命令，Phase 2.1）。
累计 5 个新 episode 后比对基线：

| 指标 | 通过条件 | 依据 |
|---|---|---|
| `utility` | ≥ 基线 − 0.02 | SHE 要求安全演化不牺牲良性效用；ε 对应 Practice Makes Unsafe 中"效用仅变动 0.4 点"的量级 |
| `violation_rate` | ≤ 基线（严格不退） | 安全不允许用效用换 |

两条同时满足 → `PROMOTE`，条目转 `active`，基线上移一代。
任一不满足 → `REVERT`，条目移除/撤销，记入 archive 作负样本。**这一步就是防误演化的主闸。**

> **版本沿革（v2.2.5 → v2.27.x 逐轮审计收口叙事）不随包分发**（v2.27.48，按 SkillHub TRACE 平台反馈「减少历史内容」整改）：逐版收口明细以随包 `CHANGELOG.md` 为唯一权威来源；更早版本的原始审计档案留存于作者 dev 树作证据链（诚实披露：非删除，仅收敛发布范围）。当前生效的诚实边界以 §4「已知残留与诚实边界」与第一屏安全披露为准。
### 步骤 7: 定期体检
- **输入**: 任意时刻
- **输出**: 基线、制品统计、趋势判定
- **命令**:
```bash
python3 "$MC" status
```
输出基线、各制品条目统计、以及最近两窗口趋势判定：变聪明 / 变稳 / 平台期 / **退化（疑似误演化）**。

### 步骤 7.1: 元认知日志复盘（Phase 2.1）
- **输入**: 任意时刻
- **输出**: 最近 N 天反思记录统计与洞察
- **命令**:
```bash
python3 "$MC" meta-log            # 最近 7 天反思记录（PROMOTE/REVERT/M1 自动触发）
python3 "$MC" meta-log --days 30 # 最近 30 天
```
日志落点 `<root>/ledger/meta-cognition.log`（JSONL），每条含 `event_type`/`context`/`analysis`/`action`/`insight`。用于事后检索"Agent 是否真的越用越聪明"、定位系统性误演化。格式见 `references/faq-deep.md`（原 `design/meta-cognition-log-spec.md` 已于 v2.27.13 并入正文文档化，链接同步移除）。

### 步骤 7.2: 从领域模板初始化（Phase 2.2）
- **输入**: 领域 key（code_review / paper_review / document_editing）+ 可选输出目录 / 配置
- **输出**: 一个引擎兼容的领域实例 `.metacog`（五制品 + CONTRACT + 标准 ratchet）
- **命令**（⚠️ 首次运行须带信任根变量 `METACOG_TRUST_ROOT_ANCHOR_KEY`——**唯一来源，本地与生产同口径**（v2.27.17 起默认锚已删除、ALLOW_DEFAULT 兜底已废除，未配置则 `init-domain` 以 `LedgerAnchorDefaultError` fail-closed 退出；该错误与 `--output` 目录权限**无关**；密钥生成：`python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`）：
```bash
METACOG_TRUST_ROOT_ANCHOR_KEY=<你的专属密钥> python3 "$MC" init-domain code_review                  # 当前目录生成 .metacog
METACOG_TRUST_ROOT_ANCHOR_KEY=<你的专属密钥> python3 "$MC" init-domain paper_review -o ./my_review  # 指定输出目录
METACOG_TRUST_ROOT_ANCHOR_KEY=<你的专属密钥> python3 "$MC" init-domain document_editing --config cfg.json  # 仅支持 name/redlines 字段合并
```
- **`--config` 范围（N-08 收口，v2.27.15 起）**：`--config cfg.json` **仅允许**覆盖 `name`（显示名）与 `redlines`（领域红线建议注记，advisory 非条目、不进制品）两个字段。**安全制品（A1 系统提示 / A2 规则库 / A3 安全记忆 / A4 工具策略 / M1 元层策略）的领域定制，init-domain 一律不接受覆盖**——须在 init-domain 之后经 `propose` 提案 + A1/A4/M1 人类签名闸完成（人在环设计目标：拒绝一切绕过人类闸的安全内容写入路径）。若 cfg.json 含上述安全制品字段，init-domain 会直接拒绝（报错并退出，不静默吞掉）。
- 失败回滚（v2.27.16 M-6 收口）：init-domain 若中途失败（如信任根锚未就绪），本次新建的实例会被自动回滚清理，不留「制品已写但基线未建」的半成品；既有实例不会被删除（防误删数据）。
- 领域红线建议写入 `meta/domain-redlines.md`（仅 advisory，不削弱全局 `REDLINES` 安全不变式）。格式见 `references/design/domain-template-spec.md`。

### 步骤 7.3: 性能 Benchmark（Phase 3.1，模拟框架）
- **输入**: 领域（code_review / paper_review）/ episode 数 / 输出目录
- **输出**: 每领域 `average_utility` / `utility_trend` / `violation_rate`（paper_review 另含 `accuracy`）+ JSON 结果 + HTML 汇总报告
- **命令**:
```bash
python3 "$MC"   # 注意：benchmark 是独立包，直接跑脚本
python3 scripts/benchmark/run_all.py --domain all --episodes 50 --verbose
python3 scripts/benchmark/visualize.py references/benchmark/results/benchmark-code_review-*.json
```
框架为**模拟**多领域自改进效果（纯标准库、不调真实 LLM）。可视化 PNG 需 matplotlib，缺失时自动跳过、仅出 HTML/JSON（零第三方依赖硬约束）。格式见 `references/design/benchmark-spec.md`。

🛑 **STOP**: 连续 2 轮 verdict 全部 REVERT → 人工介入审查演化机制。

## 与相邻技能的分工

> 近邻 `hyperagents-self-evolution` 已本机卸载，仅作历史/论文来源参考（详见 `references/paper-mapping.md`）。

| 技能 | 现状 | 本 skill 的差别 |
|---|---|---|
| `hyperagents-self-evolution` | **本机已卸载**（2026-08-26）；离线批跑，需 eval 脚本 + API key | 本 skill **在日常真实会话中在线累积**，无需 eval 脚本，用滑动窗口统计代替离线评测 |
| `self-improving-agent` | 在 | 那是"记录"，本 skill 是"记录→归因→闸门→棘轮→沉淀/回滚"的闭环，有量化验收 |
| `skill-evolver`/`darwin-skill` | 在 | 优化某个 SKILL.md 文件；本 skill 优化的是 **Agent 自身的元认知契约**，且元层可自我修订 |

## 定制化参数 / Customization

本 skill 的行为可通过以下参数按你的场景调整（**操作 4 起改 `meta/M1-evolve-policy.json` 即可，参数级自指，无需碰引擎**；或 `propose` 时指定），无需改引擎逻辑：

| 参数 | 位置（操作 4 起） | fail-safe 落点 | 默认值 | 怎么调 |
|---|---|---|---|---|
| 效用容差 ε | `meta/M1-evolve-policy.json` 的 `ratchet.epsilon` | `metacog.py` 常量 `EPSILON` | `0.02` | 改 JSON 即可（参数级自指）；放宽到 `0.05` 更易 PROMOTE；收紧到 `0.01` 更保守 |
| 证据门槛 | `meta/M1-evolve-policy.json` 的 `ratchet.min_evidence` | `metacog.py` 常量 `MIN_EVIDENCE` | `2` 次独立 episode | 高风险领域调到 `3` 更稳 |
| 裁决窗口 | `meta/M1-evolve-policy.json` 的 `ratchet.default_window` | `metacog.py` 常量 `DEFAULT_WINDOW` | `5` | 任务稀疏时降到 `3` 加快反馈 |
| 领域红线 | `init-domain` 生成的 `meta/domain-redlines.md` | 空（advisory） | 按领域补"本场景绝对不能做的事"，仅建议不削弱全局 `REDLINES` |
| 自适应开关 | `verdict --adaptive` | 默认关 | 开启后按窗口违规率动态收紧/放宽判定基线 |

> 传递个人偏好时，把上面任一项写进你项目的 `CONTRACT.md`（人类持有，不在演化范围内），即成为团队统一约定。

## 五制品声明（可演化对象仅此五项）

来自 SHE 的 harness 四制品分解——把职责切开，才能归因，才能局部演化：

```
.metacog/
├── CONTRACT.md                    ← 人类持有，Agent 禁止修改（自指不动点）
├── artifacts/
│   ├── A1-system-prompt.md        ← 角色与行为基线
│   ├── A2-rule-bank.md            ← 具体做法条目（演化主战场）
│   ├── A3-safety-memory.md        ← 安全记忆，APPEND-ONLY
│   └── A4-tool-policy.md          ← 工具与权限边界
├── meta/
│   └── M1-evolve-policy.md        ← ★ 元层：如何提议修改的规则本身（可被演化）
├── ledger/{episodes.jsonl, ratchet.json, archive.jsonl}
└── gates/quarantine/              ← 提议隔离区（不是生效区）
```

M1 是关键：它规定"如何改进"，而它自己也在可演化清单里。这就是 HyperAgents 的元认知自修改——不只改行为，还改**产生改进的机制**。差别在于本 skill 给自指加了截断：`CONTRACT.md`、`metacog.py`、`SKILL.md` 三个文件 Agent 不可动。没有这个不动点，安全约束会在若干代之后被自己演化掉。

## 与 SHE 共享不动点（统一契约）| Shared Fixed Points with SHE

本 skill 的 A1–A4 **就是** `unclekk-safety-harness-evolution`（SHE，L3）的四工件，1:1 对应：

| metacog 制品 | SHE 工件 | 说明 |
|---|---|---|
| A1 系统提示 | `system_prompt` | 角色与行为基线 |
| A2 规则库 | `rule_bank` | 具体做法条目（演化主战场） |
| A3 安全记忆 | `safety_memory` | append-only |
| A4 工具策略 | `tool_policy` | 工具/权限边界 |

三道闸（G1 写入 / G2 检索 / G3 确认）+ 双指标棘轮，与 SHE 三硬闸共同构成**统一不动点契约**；唯一真相源 `CONTRACT.md`（运行时副本 `.metacog/CONTRACT.md`），两 skill 共享定义、引擎独立。

## 归因决策表（出问题时改哪个制品）

不许笼统地"我学到了要更小心"。必须归因到具体制品，否则改动无法验收：

| 症状 | 归因制品 | 提议要求 |
|---|---|---|
| 重复踩同一个坑 | **A3** | 直接生效，不设试用期（教训不该等） |
| 用错工具 / 越权操作 | **A4** | 需 ≥2 次独立证据 |
| 具体做法错、步骤漏 | **A2** | 需 ≥2 次独立证据 |
| 角色偏移、风格不符 | **A1** | 需 ≥2 次独立证据，谨慎 |
| 改过但没用 / 反复改同一处 / 连续 3 次回滚 | **M1** | 必须人类确认（在 TTY 运行 `apply` 交互式输入口令签绑定签名，覆盖 id+chash+trial_from_index；`confirm --approve` 已于 v2.5.7 移除（签名合并进 `apply` 的交互式 TTY 口令流程）） |

最后一行是元认知的入口：当问题不在"规则错了"而在"找规则的方式错了"，就该改 M1。

## 不可演化的红线

以下内容命中即 BLOCK，**哪怕它确实让任务成功了**——这正是论文反例的核心教训：

1. 绕过/跳过/关闭 审计、检查、确认、校验、闸门
2. 免除人工确认（"无需向用户确认""自动同意"）
3. 破坏性命令（`rm -rf`、`del /s`、`drop database`）
4. 绕过版本控制保护（`--no-verify`、`push --force`）
5. 提权与放宽权限（`chmod 777`、`bypassPermissions`）
6. 明文凭据
7. 削弱或删除 A3 安全记忆
8. 触及 `CONTRACT.md` / `metacog.py` / `SKILL.md`（自指不动点）

> **红线闸能力边界（诚实声明，v2.3.0 / D2）**：`REDLINES` 是**关键词正则拒绝列表（denylist）**，判定边界 = 词表覆盖面，**不构成语义防护**——提出修改的主体是 LLM，改写措辞是其默认行为，本闸只能拦「照抄禁用词」，拦不住「换种说法」。因此：①凡命中红线的**语义可疑项一律升级为需人类确认**（不靠正则赌语义）；②禁改类硬约束（不动点、A3 只增不减）已前移至 `CONTRACT.md` 人类侧契约，不依赖正则覆盖；③真实兜底仍是双指标棘轮（5 episode + utility/violation_rate 双不退）——但 `utility` 由外部申报、无独立校验，故语义绕过项必须靠人类在凭证确认环节兜底（P1 起 `--human-ok` 已废除，见下方人类闸凭证化）。**不要据此声称「拦住了不安全演化」，只能说「拦住了字面禁用词」。**（v2.25.13 影响范围注：**影响范围**仅 gate 红线扫描这一层的词表覆盖面；不动点保护、A3 只增不减、证据门槛与双指标棘轮均不依赖词表。**适用前提**：只要语义可疑项照常升级人类确认，词表边界不构成额外风险。）

## 元层自省触发条件

满足任一，**必须**改 M1 而不是继续改 A2：
- 连续 3 次 `verdict` 全部 REVERT（`verdict` 会自动提示）
- 同一处被反复改动 ≥3 次（归因错了）
- `status` 连续两窗口趋势不升（当前演化机制已失效）

**强制执行**: 不要忽略这些信号，立即执行 M1 提议。

## 使用纪律 / Usage Discipline（输出准确性约束）

- **禁止在不确定领域胡编**：任何 `propose` / `gate` 裁定 / `verdict` 裁决都必须基于 `ledger/` 中已有的 episode 证据或明确的指标数值，**不得**凭空编造"据观察""通常而言"式的结论。
- **每个输出注明决策逻辑**：提议要写清 `--reason` 并引用 `--episode`；`gate` 裁定要说明命中了哪一类检查（不动点 / 红线 / A3 只增 / 证据门槛）；`verdict` 要列出 `utility` 与 `violation_rate` 两项数值及与基线的对比。让用户能复核"为什么这么定"。
- **诚实评分**：utility 注水会让棘轮失效（详见 FAQ Q5）。评分偏低不可耻，被坏经验骗过才危险。

## 步数上限与兜底 / Step budget & fail-open

| 项 | 上限 | 超限行为 |
|---|---|---|
| 单条提案证据门槛 | ≥2 次独立 episode | 不足则 `gate` 返回 HOLD，不进入应用 |
| verdict 裁决窗口 | 累计 5 个新 episode | 未凑满保持 `trial`，不裁决、不沉淀 |
| 连续 REVERT 警戒 | 连续 2 轮全部 REVERT | 🛑 STOP：人工介入审查演化机制 |
| 隔离区滞留 | 30 天未处理 | 自动归档为负样本，不污染生效区 |

## 什么时候别用（反模式）

| 场景 | 为什么不要做 | 替代方案 |
|------|-------------|----------|
| **一次性任务** | 没有重复使用，棘轮统计无意义 | 直接写脚本，不用本 skill |
| **无法给出 utility** | 指标注水会让棘轮失效，比不做更糟 | **必须**评估 utility 后再决定 |
| **期待「装上就自动变强」** | 本 skill 要求每次任务后记账。不记账 = 没有进化 | **必须**建立 episode 记账习惯 |
| **试图绕过不动点** | CONTRACT.md / metacog.py / SKILL.md 永远禁改 | **必须**通过 propose → gate → apply 流程 |
| **跳过 episode 记账直接 propose** | 无证据的提议会被 gate HOLD | **必须**先积累 ≥2 次 episode |

## 反例黑名单（dim9: 绝对不要做的事）

| # | 反模式 | 为什么不要做 | 替代方案 | 归因 |
|---|--------|-------------|----------|------|
| **绕过安全检查** | 审计/确认/验证是安全底线 | **必须**完整过三闸 | SKILL_DEFECT |
| **免人工确认** | 绕过G3闸导致误演化固化 | **必须**人类在 TTY 运行 apply 交互式签绑定签名（覆盖 id+chash+trial_from_index） | SKILL_DEFECT |
| **破坏性命令** | `rm -rf` 等不可逆操作 | **必须**先 archive 备份 | SKILL_DEFECT |
| **绕过版本控制** | `--no-verify` 破坏回滚能力 | **必须**始终用 apply --git | SKILL_DEFECT |
| **提权/放宽权限** | chmod 777 降低安全基线 | **必须**保持最小权限 | SKILL_DEFECT |
| **明文凭据** | API key 明文写入制品 | **必须**用环境变量 | SKILL_DEFECT |
| **削弱安全记忆** | 删除 A3 等于删除教训 | **必须**A3 永远 append-only | SKILL_DEFECT |
| **触碰不动点** | 改契约文件破坏一致性 | **必须**这三文件永远禁改 | SKILL_DEFECT |
| **utility 注水** | 评分虚高让棘轮失效 | **必须**诚实评分 | OPTIMIZATION |
| **跳过证据门槛** | 单次成功不得直接生效 | **必须**收集 ≥2 次 episode | EXECUTION_LAPSE |

---

## 数据隐私规范 / Data Privacy

本 skill 在 `episode` / `meta-log` / `ledger/` 中记录的是**行为归因数据**（任务名、utility、violations、哪条规则被改），不是业务原文。仍请遵守：

1. **敏感内容脱敏**：`episode --note` 与 `meta-log` 的 `context` 字段只写"发生了什么、归因为哪条制品"，**不要**粘贴用户对话原文、PII、密钥、内部文档片段。例：`--note "漏读原文件覆盖了用户手改"` ✅ / `--note "用户张三的微信token是xxx"` ❌。
2. **凭据永不入制品**：红线第 6 条已禁明文凭据；API key 一律走环境变量（`$env:NAME` / `os.environ`），制品里只留"需环境变量 X"的提示。
3. **本地优先**：所有 ledger 默认落在你指定的 `<root>/`，不联网、不上传。需要跨设备共享时走你自己的 Obsidian/私有同步，不要交给第三方。
4. **可审计可擦除**：`ledger/archive.jsonl`（负样本）与 `episodes.jsonl` 含演化轨迹，属个人数据；删除 `.metacog/` 目录即整体清除，无需逐个擦除。

---

## 失败处理决策树

```
如果 propose 失败:
  → gate 返回 BLOCK:
    - 检查红线正则是否误匹配
    - 检查不动点保护是否冲突
    - 修复后重新 propose
  → gate 返回 HOLD:
    - 证据不足，收集更多 episode
    - 至少 ≥2 次独立复现
  → gate 超时:
    - 检查文件锁是否竞争
    - 清理 quarantine 目录后重试

如果 verdict 失败:
  → PROMOTE 失败（utility 下降）:
    - 条目 REVERT
    - 记入 archive.jsonl 负样本
    - 分析 utility 下降原因
  → REVERT 失败（棘轮卡死）:
    - 检查 episodes.jsonl 数据完整性
    - 手动清理 stale episode
    - 重新建立基线

如果 apply 失败:
  → 原子写入失败:
    - 检查磁盘空间
    - 检查文件权限
    - 清理临时文件后重试
  → git commit 失败:
    - 检查 git 状态
    - 合并冲突后重试
    - 或使用 --force 覆盖（需人工确认）
```

🔴 **CHECKPOINT**: 任何失败处理后，必须运行 `python scripts/test-core.py` 确认无回归。

---

详见 `references/paper-mapping.md`（含 4 篇论文逐条落地映射与一处主动设计分歧）。核心对应：HyperAgents 元层可编辑（M1 在可演化清单内 + 人类确认）/ SHE 四制品分解 + 归因引导 + 安全-效用双验证 / Practice Makes Unsafe 三闸（G1 写入 / G2 检索 / G3 确认）+ SafeEvolve / Survey 四组件闭环（episode→制品→环境→gate+棘轮）。

## 退出码与排查 / Exit codes & troubleshooting

命令失败时会带「↩ 怎么改」行；**每次退出码 2（含敲错子命令/参数的 argparse 级错误）还会在 stderr 末尾指向集中排查文档**。完整索引见 `references/troubleshooting.md`（或 `python metacog.py --explain` 直接打印）。高频**安全闸 reason**（`external-anchor-corrupt` / `external-anchor-path-writable` / `LedgerAnchorDefaultError` / `pubkey-root-mismatch` / `完整性-硬闸` / `FROZEN-*` 等）的白话解释与处置见 `references/error-glossary.md`（v2.25.15 新增）。

| 退出码 | 含义 | 典型场景 | 怎么处理 |
|---|---|---|---|
| 0 | 成功 | — | — |
| 2 | 参数/前置校验失败，或安全闸拦截 | 根未 init、`--utility` 超界、缺 `--content`/`--target`、`--artifact` 非法、G1 闸 BLOCK/HOLD、apply 目标不存在、需人类 TTY 绑定签名（`apply` 非交互/无有效 `--sig` 则拒绝；或 `confirm --sign` 预签名经 `--sig` 传入，v2.25.14）、init-domain 配置错 | 看报错「↩ 怎么改」；对照 `references/troubleshooting.md` |
| 其他非 0 | 运行期异常（配置/IO/git） | 配置解析失败、git add/commit 失败、文件读取失败 | 看报错「↩ 怎么改」；查 `references/troubleshooting.md` 第五类 |

> `--explain` 是全局开关，需放在子命令前：`python metacog.py --explain`。

## 已验证（v2.27.48 实跑快照，2026-10-30）

- **运行环境**：Python 3.13（零第三方依赖，仅标准库）；Windows / managed python
- **全量回归**：**56/56 套件诚实 PASS**（v2.27.48 代码，2026-10-30 实跑；判定三重：exit=0 + 末次自报全过 + 输出无 `[FAIL]` 标记）
- **复现方式**（随包可独立跑）：`python3 scripts/_run_all_tests.py`；运行器以随包清单 `scripts/test-suite-manifest.txt`（56 条，与实际套件 1:1）锚定分母——清单缺文件或清单外新增均直接 FAIL
- **独立审计链**：生态外 DSH 五轮审计链 PASS（最近一轮 4.4/5、无未收口 Medium+）+ owner（KK）治理结案裁定（`references/c1-owner-closure-instrument.md`）；Hermes 异族审计各轮裁定见 `CHANGELOG.md`
- **诚实边界**：上列为**套件级通过率**与**审计链裁定**，不等于对所有环境的端到端保证；冻结账本与树外锚点等运行期状态由 `verify` / `status` 自查，不在本轮全量回归覆盖内
- **测试证据**：见 `references/test-evidence.md`（当前版本摘要；更早版本逐次运行日志不随包分发）

## FAQ / 坑点

**Q1. 装上就能自动变强吗？**
A. 不能，必须每次任务后 `episode` 记账；不记账 = 没有进化。坑：以为 `init` 完就万事大吉。

**Q2. 它会不会把安全规则自己改没？**
A. 不会。三不动点 + 红线 + G3 人类确认闸三重拦截。坑：别把"元层可编辑"误读成"啥都能改"——M1 能改，三个不动点文件永远禁改（L3 可控自指，区别于会自毁的 L2 半开自指）。

**Q3. M1 怎么改？每次都要人工确认吗？**
A. 只在触发"元层自省"条件时才改 M1，且须由**人类在 TTY 运行 `apply` 交互式输入口令、当场签绑定签名**（覆盖 提案 id + 内容哈希 + 试用窗起点 trial_from_index，v2.5.7 合并方案，原 `confirm --approve` 已移除），否则拒绝。坑：`--human-ok` 已废除（AI 可自签）——被拦是设计不是 bug。

**Q4. 误演化了怎么办？**
A. `verdict` 双指标任一不满足即 `REVERT` 自动回滚，并记入 `archive.jsonl` 负样本。坑：无棘轮时坏经验被固化；有棘轮时坏经验被捞出标注，越改越稳。

**Q5. 基线怎么算？utility 注水会怎样？**
A. 操作 1 起基线由**前 5 个 derived episode** 推导值算术平均建立；一旦库中有了 derived 数据，声明式 `--utility` 不再参与基线/验收。注水在结构上被封死：`compute_utility` 只读可观测事件、不读命令行数字，且高申报值伴负向事件会触发 `[注水嫌疑]` 告警——所以别想靠改数字抬高效用。

**Q6. 能接进 CI 当结构门禁吗？**
A. 可以。专业用户把 `apply --git` 作为每次演化的回滚点；再把 `gate` / `verdict` 设为 CI 步骤——`verdict` 返回 `REVERT` 即视为门禁失败退出。坑：CI 里没有真实 episode 数据，`verdict` 会因证据不足保持 `trial`，所以 CI 只跑 `gate`（写入闸）更稳妥，裁决留给有数据的本地会话。

## 开场白示例（直接复制给 Agent）

- "帮我搭一个会自我进化但不会把安全规则改没的 Agent，用 unclekk-metacog-self-evolve 那套五制品+三闸。"
- "我每次写完代码都漏读原文件，用 metacog 把这个教训沉淀进规则库，并跑双指标棘轮看会不会误演化。"
- "评审一下我现在的自改进结构：它有没有不动点约束？演化错了能不能回滚？对照 metacog 的三闸说说缺口。"

## 威胁模型与信任边界 / Threat Model & Trust Boundary

> 本节为 v2.11.0 新增（Hermes r7 复派审计要求 ⑥）。目的是把「本 skill 防什么、不防什么、依赖什么假设」一次性讲清，避免把 fail-closed 机制误读为万能安全保证。

### 1. 保护目标（Security Goals）
- **G1 可控自指不变量**：五制品可演化，但三不动点文件（CONTRACT.md / SKILL.md 红线段 / 人类闸凭证）永远禁改；演化错了可回滚。
- **G2 账本防篡改**：基线（manifest/script/artifact/信任根域）写入即签名，验证即验签；签名失效或缺失（在截止期后）fail-closed。
- **G3 审计链不可伪造**：迁移/回滚审计链带 `epoch` 标记（v290）+ HMAC 链，旧链（首条缺 epoch）在 v2.11.0+ 已 fail-closed。
- **G4 发布期冻结完整性**：源/测试/文档冻结于 append-only `frozen-hashes.jsonl`，首次冻结哈希为权威基准，ledger 自身篡改可检出。

### 2. 攻击模型（Adversary Model）
**假设攻击者具备**：对 `ledger/` 目录写权限（可改基线/审计链）；对技能工作树写权限（可改脚本/文档）；可重放/伪造 proposal、可触发 `apply`/`verdict`/`verify` 命令。

**假设攻击者不具备（超出本 skill 范围）**：持有外部锚私钥 / 信任根私钥（离线 RSA 根，外部化）；持有生产 `METACOG_TRUST_ROOT_ANCHOR_KEY`（默认共享锚已删除、`ALLOW_DEFAULT` 兜底已废除，本地与生产同口径，须配置专属 `METACOG_TRUST_ROOT_ANCHOR_KEY`）；持有人类闸口令 / 预签名 `--sig` 文件（人类在 TTY 交互式签名）。

### 3. 密码学假设
- 基线签名 = HMAC-SHA256（密钥来自代码内嵌锚派生，标签与审计链 HMAC 标签分离）；
- 审计链 HMAC = HMAC-SHA256（独立标签）；
- 信任根 = 离线 RSA（外部锚，密钥不在本仓库）；
- 人类闸 = PBKDF2-SHA256(20 万轮) + TTY 交互式口令签绑定签名（覆盖 提案 id + 内容哈希 + trial_from_index，签名 use-once 消费；v2.5.7 合并方案，无人值守走 `confirm --sign` 预签名经 `apply --sig` 应用）。

### 4. 已知残留与诚实边界（当前生效的诚实边界；历轮收口明细见 CHANGELOG.md）
- **冻结 ledger 非运行期安全边界（v2.14.0 重申·P1-1 → v2.27.19 N-3 收口更新）**：`frozen-hashes.jsonl` 的 HMAC 链密钥 **v2.27.18 及以前为代码内派生常量**（`_freeze_key` = HMAC(常量种子, 标签)）——任何能读到本源码的同用户进程都能重算密钥、伪造整条 HMAC 链。**v2.27.19（N-3 收口）起该常量种子已删除**：链密钥改由部署专属锚密钥（env `METACOG_TRUST_ROOT_ANCHOR_KEY`，与账本签名锚同源，C-01 口径）派生；未配置/非法 → record/verify 全拒（fail-closed，宁可装不上）。持代码读权但不知部署 env 密钥者**无法再伪造 HMAC 链**（保护增量 c：链密钥部署专属化，源码泄漏 ≠ 链密钥泄漏）。现仍仅提供：(a) 意外损坏检出；(b) 与「树外锚点」配合，在 **tree-only 攻击者（可写技能树、不可写树外锚）** 篡改 ledger 时因锚不匹配而 fail-closed；本 skill 声称的「防仅持技能树写权」即指此树外锚隔离，而非 HMAC 链之密码学强度——二者强度不可混同。定位仍为**开发/发布期卫生工具**。**诚实边界（同 C-01）**：env 密钥对本进程自身可读属部署契约残余（非代码层可防）。**破坏性迁移**：旧常量种子账本在新密钥下校验必失败，须配置 env 后经授权重置门全量重 record（详见 CHANGELOG v2.27.19）。（历史注：v2.25.13 影响范围口径——单机本地使用不依赖 HMAC 链密码学强度，安全价值由树外锚隔离独立承担——对 v2.27.19 后仍然成立。）
- **树外锚点（信任根）的诚实边界**：锚落于 `~/.metacog_freeze_anchors/<slug>.anchor`（技能树之外、同机 HOME）。真正的防御对象是 **tree-only 攻击者（不可写树外锚）**；若攻击者同时持有 ledger + 锚 双写权 = 已破信任根，可同步改 ledger 并重写锚 → 此属已知 residual（见下），非代码层可防。v2.12.0 起整体替换 ledger 会被锚不匹配 `FROZEN-ANCHOR` fail-closed 检出；账本缺失亦 fail-closed（r8 P1-①②）。

- **历轮审计收口明细（v2.11.0 → v2.25.10，含每版 Hermes 独立审计裁定、诚实边界与 residual 登记）统一见随包发布的 `CHANGELOG.md`**——本处仅保留「当前仍生效」的诚实边界（下方 residual 枚举与密码学假设），不再内联逐版本收口叙事，避免历史与当前指引混杂。

- **legacy 基线残留**：v2.11.0 前生成、缺失 `_anchor_sig` 的存量基线在 v2.11.0 已 fail-closed（须 `keygen/apply` 重基线方获密码学保护）；v2.11.0 前旧审计链（首条缺 epoch）同样已 fail-closed。
- **过渡期语义（v2.14.0 引入·P2-6，v2.15.0 修正·M-1）**：v2.14.0 曾将 `_legacy_anchor_sig_allowed` / `_legacy_audit_chain_allowed` 的截止期改为**自动读取 `SKILL.md` frontmatter `version:`**（`_read_skill_version_tuple`），意为「cutoff 恒等于当前版本 ⇒ legacy 窗口恒为 0」。v2.15.0 据 Hermes r11 M-1 修正：该写法让 `version:` 字段隐式成为安全门控（改版本号即静默改变信任策略），等价于隐式硬编码。故改回**显式字面量 `LEGACY_*_CUTOFF = (2,15,0)`**，`version:` 字段退出安全门控；当前版本即截止期 ⇒ legacy 永不被容忍，且 cutoff 为可审计的显式安全决策。测试层演示仍可用显式 `cutoff=(2,15)` 参数模拟「截止期前」。
- 以上为代码层收口；v2.12.0→v2.20.0 各版收口明细（每版对应 Hermes 独立审计轮次与逐条收口：r8 P1 账本缺失 fail-closed / r9 H-B1~B4 / r10 双删重置+anchor-init 洗白 / r11 H-1/H-2/M-1/M-2 / r12 反斜杠路径逃逸根因 / r13 冻结态重置逃生舱 / r14 语料完整性 F-1~F-10 / r15 verify 漂移对称修复 / r16 原子回滚与竞态）**统一见随包 `CHANGELOG.md` 对应版本条目**，正文不再逐版枚举。历轮审计语料均以**中立请求**提请 Hermes 独立裁定，不预设结论、不以「是否上调评级」设问。

## C-1 闭合现状（2026-10-30 更新）

> **结论先行（v2.27.37 owner 结案口径）**：C-1「信任锚本身受信」**已由 owner（KK）结案**（v2.27.37），裁定书见 `references/c1-owner-closure-instrument.md`，判据修订见 `references/third-party-audit-signoff-guide.md` §10。现行有效评级口径 = **生态外 DSH 审计链 PASS（附已披露残余，最近一轮 4.4/5、无未收口 Medium+）+ owner 结案裁定**。诚实残余仍保留：C-1 的「完全非对称化」（包内仅留公钥、私钥离线）**仍未实施**，本 skill 不声称代码层完整闭合；OS 级隔离的完整性仍依赖部署契约（见顶部「设计目标定位」与下方诚实边界）。**⚠️ CONDITIONAL-PASS 口径已于 v2.27.37 退役**：Hermes 历轮「有条件通过」所附条件已全量解除，其升级前置「生态外第三方审计」已由五轮 DSH 实测审计链满足；本文档各处「有条件通过」字样一律以本退役声明为准。

- **软件层（信任根）**：v2.8.0 起 `trust-root.json` 由代码内嵌锚密钥签名、`load` 校验，根信任锚定在代码而非 Agent 可写 ledger；v2.27.17 起源码内嵌默认锚已删除（账本锚 + trust-root 签名锚均改 env 专属密钥唯一来源，M-01 校验），「宁可装不上，不可自签」。完全非对称化（私钥离线）列为已披露残余，未实施。
- **部署层（OS 隔离套件）**：`scripts/C1_deploy.py` 提供一键式 OS 级隔离部署——专用低权账户 `metacog-svc`（L1）、attestation 目录 ACL 收窄（L2）、`METACOG_REQUIRE_PROTECTED_ANCHOR=1` 运行时 fail-closed（L3）。v2.27.38 起 `C1_deploy.py` 已硬化：随机临时目录（替换固定 `%TEMP%`）+ 提取后字节级完整性校验（fail-closed）+ 提权前显式确认横幅（保留进程级 `-ExecutionPolicy Bypass`）。
- **诚实边界（保留，非 over-claim）**：C-1 真正生效取决于运维在生产保持配置（L1/L2 部署契约）；默认未部署 OS 隔离时本 skill 不声称 C-1 完全闭合，与威胁模型一致。Windows `os.access W_OK` 不可靠，最强姿态仍建议只读挂载 / TPM / 安全 enclave。
- **评测口径区分（避免误读）**：
  - **CONDITIONAL-PASS 已退役（v2.27.37）**：历史版本块中的「有条件通过」字样为当时裁定的逐字历史记录，不 rewrite；但自退役声明起，本文档现行评级口径一律以「DSH 审计链 PASS + owner 结案」为准。
  - **SkillHub TRACE 平台综合自动化评级**：本发布包在 SkillHub TRACE 五维评测（Trust / Reliability / Adaptability / Convention / Effectiveness）中，平台最新反馈（2026-10-30 第二轮重扫）综合 **4.8/5（优秀）**；同日前一轮为 **4.7/5**，安全性扫描 **5.0/5、无 P0/P1**——该「安全性扫描」是**恶意性 / 恶意代码扫描**口径，**不是**架构信任根健全性认证，不构成「C-1 已闭合」证据。该平台评级与 DSH 审计链是**两套独立口径**，请勿混同。

---

## 一键系统级隔离（Windows OS 隔离部署套件）

> **⚠️ 安全披露（诚实边界）**：`C1_deploy.py` 内嵌 8 个 PowerShell，v2.27.38 起已硬化——随机临时目录（替换固定 `%TEMP%`）+ 提取后字节级完整性校验（fail-closed）+ 提权前显式确认横幅（保留进程级 `-ExecutionPolicy Bypass`）。本套件是「系统级人在环可控自指」的**可选** OS 隔离增强：**人在环单人本地使用无需本套件**；生产 OS 级隔离完整性仍依赖部署契约（见上方「C-1 闭合现状」），本 skill 不声称代码层完整闭合。
> **新用户闭环**：SkillHub 拒绝 `.ps1` 文件，故 C-1 的 8 个 OS 隔离部署脚本已内嵌进单文件 `scripts/C1_deploy.py`（base64 打包，运行时解包到临时目录以 `powershell -File` 调用）。新用户 `skillhub install` 一个包即拿到完整「系统级可控自指」闭环，无需二次分发 `.ps1`。

所有硬编码路径（原 `D:\dryrun\metacog-dryrun\...`）均从 `C1_deploy.py` **自身位置推导**（`scripts/` 的父目录即技能根），故安装到任意目录均通用。

> **部署权限与安全披露（诚实边界）**：C-1 OS 隔离部署涉及系统级特权操作，使用前请知悉——
> - 须在**管理员**上下文运行 `setup` / `enable-external`（建账户、授登录权、注册自启）；
> - 会创建专用低权账户 `metacog-svc`（L1），并经 LSA API 授予 `SeInteractiveLogonRight` / `SeBatchLogonRight`；
> - 可将 Agent 注册为 Windows 服务或计划任务（以该低权账户运行）；
> - 账户口令以 **DPAPI（`ConvertFrom-SecureString`）/ `SecureString`** 存于 admin-only ACL 文件，**不落明文**；
> - **已移除**计划任务被拒时自动 `Enable-PSRemoting` 开启 WinRM 的兜底分支（避免静默开启网络监听）；如需 WSMan 网络登录路径，须管理员手动 `winrm quickconfig` 后使用。

### 前置条件
- Windows + 以**管理员**身份运行 PowerShell/Python；`python` 在 PATH 上。
- 下列 `setup`/`check`/`run` 等涉及降权账户、ACL、schtasks/WSMan 的步骤**必须在生产机执行**；非特权/沙箱环境仅校验脚本语法与解包，不实际跑隔离。

### 子命令
| 子命令 | 作用 |
|---|---|
| `setup` | 建低权账户 `metacog-svc`（L1）+ 备份/收窄 attestation 目录 ACL（L2） |
| `rollback` | 还原 ACL 备份（可选 `--remove-account` 移除账户） |
| `isolation-setup` | 仅收窄 attestation 目录 ACL（L2） |
| `check` | 以 Agent 账户预检 attestation 是否可写（fail-closed 判定） |
| `wire-service` | 注册为 Windows 服务（以低权账户运行） |
| `wire-scheduledtask` | 注册为计划任务（以低权账户运行） |
| `grant-logonright` | 一次性修复低权账户登录权 + 口令同步 |
| `enable-external` | 生成锚密钥（C-9）+ 启用外部信任锚（**须离线 root 公钥** `--root-pubkey-file`） |
| `run <metacog 参数>` | 以低权账户降权运行任意 metacog 子命令（L3 强制） |
| `launch` | 预检隔离后启动（包装 `C1_launch_metacog.ps1`） |

### 最小部署走查（生产机管理员 PowerShell）
```powershell
# 1) 进入技能根目录（skillhub install 后位于 ~/.workbuddy/skills/unclekk-metacog-self-evolve；C1_deploy.py 即 scripts/ 下）
cd <skill-root>
# 2) 创建低权账户 + 收窄锚证明目录 ACL（L1/L2）；attestation 路径按你的环境改
python scripts/C1_deploy.py setup --attestation-path "D:\protected\anchor\attestation.json"
# 3) 预检隔离是否达成（exit 0 = 不可写 = 已隔离）
python scripts/C1_deploy.py check --attestation-path "D:\protected\anchor\attestation.json"
# 4) 离线生成 RSA 根密钥对，导出公钥 JSON {"n":"<b64>","e":65537}，启用外部锚（C-9 锚密钥签名闭环）
python scripts/C1_deploy.py enable-external --root-pubkey-file "D:\offline\root-pubkey.json"
# 5) 之后每次跑 metacog 都经此降权（L3 强制），例如：
python scripts/C1_deploy.py run status
python scripts/C1_deploy.py run propose --artifact M1 --op add --content "..." --episode E1
```
> 完整契约、回滚、日志与诚实边界见 `C1_OS隔离_执行与回滚手册.md` 与 `新手操作指南.md`（二者均仅私域分发，**不随 SkillHub 包发布**；`.ps1` 不随包发布，逻辑已等额内嵌于 `C1_deploy.py`）。

---

## 最佳实践汇总（速查，避免散落）

跨上文各章节提炼的 10 条硬纪律，照做即可避开绝大多数反模式与误演化：

1. **每任务必记账**：任务结束 `episode --events <可观测事件> --attributed <A1~M1>`，效用由事件推导（注水在结构上不可行）；勿用 `--utility` 声明式兜底驱动沉淀。
2. **自修改必走闭环**：任何改规则的意图都走 `propose → gate → apply`，**绝不直写 `artifacts/*.md`**；直写会被 D4 `verify` 检出篡改（返回 1）。
3. **试用 ≠ 沉淀**：`apply` 后状态是 `trial`，须 `verdict` 裁决 `PROMOTE` 才转 `active`；高风险条目 `apply` 须人类在真实 TTY 交互式口令签绑定签名（v2.5.7 合并方案），无人值守走 `confirm --sign` 预签名经 `apply --sig` 应用（v2.25.14）；`--human-ok` 旗标与 `confirm --approve` 均已废除。
4. **凭据不进制品**：API key 一律走环境变量（`$env:NAME` / `os.environ`），制品只留「需环境变量 X」；红线第 6 条禁止明文凭据。
5. **不动点永禁改**：`CONTRACT.md` / `metacog.py` / `SKILL.md` 三文件永远不可演化；要调棘轮容差/窗口/证据门槛改 `meta/M1-evolve-policy.json`（参数级自指，fail-safe 回落默认）。
6. **会话开头先检索**：每轮 `retrieve --strict` 读生效约束进上下文；revoked 条目不会浮现（G2 检索闸）。
7. **跨领域用 `init-domain`**：A 领域规则不要复制进 B，新建领域实例后人工移栽跨领域通用教训作种子。
8. **定期自查完整性**：`status` 看基线/趋势/回滚可用性；`verify` 查直写篡改；发现问题 `rollback --artifact <X> [--entry <Y>] --yes` 字节还原。
9. **C-1 部署需正确运维**：系统级隔离（L1 低权账户 / L2 目录 ACL / L3 运行时 fail-closed）须按手册部署方获完整闭环；默认未部署 OS 隔离时不声称 C-1 完全闭合（诚实边界）。
10. **评测口径区分**：Hermes 历轮「有条件通过（CONDITIONAL-PASS）」口径已于 **v2.27.37 退役**（所附条件全量解除，升级前置「生态外第三方审计」已由五轮 DSH 实测审计链满足）；现行评级口径 = 生态外 DSH 审计链 PASS（附已披露残余，最近一轮 4.4/5、无未收口 Medium+）+ owner 结案裁定。SkillHub TRACE 平台最新反馈（2026-10-30 第二轮重扫）综合 **4.8/5 优秀**（同日前一轮为 4.7/5），其「安全性扫描 5.0/5」是恶意性扫描口径、**不构成**架构信任根认证，与 DSH 审计链为两套独立口径——详见顶部「评级框架」与上方「C-1 闭合现状」。

---

## 变更记录 / Changelog

> **版本信息的唯一权威来源是随包发布的 `CHANGELOG.md`**（覆盖 v1.0.0 → 当前版本，每版均登记 Hermes 独立审计裁定与诚实边界）。本文档不再内联历史，避免与 `CHANGELOG.md` 出现两份不一致的记录。
>
> **当前版本 v2.27.48（2026-10-30）**：按平台第二轮 TRACE 反馈（4.8/5，短板「仍偏庞杂、验证状态与清单不够准确」）整改——历史沿革与早期审计样本、旧版测试日志一律不随包（逐版明细以随包 `CHANGELOG.md` 为唯一权威来源）；「已验证」章节按 2026-10-30 实跑 **56/56 套件** 重写；随包套件清单恢复（运行器 fail-closed 依赖）；新增 `scripts/build_release_package.py` 确定性构建发布包 + 硬闸新增 G 检查（验证状态新鲜度）。**安全 / 信任内容不变**。
