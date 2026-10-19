# 论文依据与落地映射

所有依据均取自本地知识库 `D:/图书馆/wiki/`，非凭印象。核验时间 2026-08-26。

## 1. HyperAgents — 自指自改进（主干思路）

- arXiv: 2603.19461 ｜ GitHub: facebookresearch/HyperAgents（2695⭐）｜ 协议 CC BY-NC-SA 4.0（非商用）
- 知识库页：`wiki/papers/paper-hyperagents.md`、`wiki/concepts/concept-self-referential-agent.md`

关键论点：
- 既有自改进方法依赖**固定、手工设计的元层机制**，这本身是速度上限。
- HyperAgents 把 task agent 与 meta agent 塞进**同一个可编辑程序**，且元层的修改流程本身也可被编辑 → **元认知自修改**：不只改解题行为，还改"生成未来改进"的机制。
- 扩展 DGM 得 DGM-H，去掉"任务性能↔自修改能力同域对齐"假设，支持任意可计算任务。
- 元层改进能**跨域迁移、跨运行累积**。
- ⚠️ 论文自身警示：执行模型生成的不可信代码有破坏性风险。

落地：
- M1 制品（`meta/M1-evolve-policy.md`）进入可演化清单 → 自指闭包成立。
- 但 M1 改动强制 `requires_human`，且 `CONTRACT.md`/`metacog.py`/`SKILL.md` 列为不动点。
  **这是对论文的主动收窄**——论文追求开放式自加速，个人 Agent 场景更需要可控性。

## 2. SHE — 安全 Harness 演化（结构与验收）

- arXiv: 2608.09885 ｜ GitHub: RainbowQTT/SHE（4⭐）
- 知识库页：`wiki/papers/paper-she.md`

关键论点：
- Agent 安全不只取决于模型权重，还取决于管理上下文/记忆/工具/权限的 **harness**。
- harness 各组件耦合会**模糊安全责任归属**，使局部演化困难 → 拆成四制品：System Prompt / Rule Bank / Safety Memory / Tool Policy。
- **归因引导的演化循环**：轨迹失败 → 结构化诊断 → 制品专属边界细化 → 安全-效用验证择优。
- 结果：Agent-SafetyBench 上 ASR 相对静态 harness **降低 3.1×**，且良性效用不降反升；泛化到 AgentHarm 未见风险、跨模型迁移无需重训。

落地：
- A1/A2/A3/A4 直接对应四制品。
- 归因决策表 = 归因引导演化的操作化；`episode --attributed` 强制归因。
- `verdict` 的双指标 = 安全-效用双验证（这是"良性效用不降反升"能成立的机制原因）。

## 3. Practice Makes Unsafe — 技能误演化（本 skill 的主要防御对象）

- arXiv: 2608.12851 ｜ GitHub: henrymao2004/misevolve（0⭐，建仓 2026-07-27）
- 知识库页：`wiki/papers/paper-practice-makes-unsafe.md`

关键论点（也是最硬的数字）：
- 自改进 Agent 把成功轨迹转成**跨任务持久状态**。一旦触发该成功的输入消失，**一次不安全的成功也会变成可复用策略**。
- 演化优化的是任务结果**而非流程安全** → 受污染的经验导致**技能误演化**。
- 实测 25 个 agent-method 配置（各 25 轮，共 525 任务）：**全部 21 个演化配置都写出了不安全产物**，其中 **15 个导致新会话伤害**；3 个恶意任务把遗留 ASR 从 **16.0% 抬到 35.3%**。
- 生命周期三段：**编写（authoring）→ 检索（retrieval）→ 后续执行（later execution）**。只测单点行为无法归因。
- SafeEvolve（写前修复 + 复用管控）：不安全检索 **−26.7pp**、新会话伤害 **−17.3pp**，良性效用仅变动 **0.4 点**。
- 结论原文要点：持久自适应安全必须管控"哪些更新被写入"以及"未来执行器复用什么"。

落地：
| 论文要素 | 实现 |
|---|---|
| 编写段风险 | G1 写入闸：红线扫描 + 不动点保护 + A3 只增不减 |
| 检索段风险 | G2 检索闸：`retrieve` 只返回 active/trial，revoked 永不返回 |
| 后续执行段风险 | G3：M1 与高风险条目需 `--human-ok` |
| "一次不安全的成功会沉淀" | 证据门槛 MIN_EVIDENCE=2，单次成功不得直接生效 |
| "良性效用仅变动 0.4 点" | 棘轮容差 ε=0.02（同量级） |
| SafeEvolve 复用管控 | revoked 条目留在文件里但状态标记，检索时过滤 |

## 4. Self-Evolving Agents Survey — 闭环骨架

- 知识库页：`wiki/papers/paper-self-evolving-survey.md`、`wiki/concepts/concept-self-evolving-agent.md`
- GitHub: EvoAgentX/Awesome-Self-Evolving-Agents（2343⭐）

关键论点：多数 Agent 系统部署后**保持静态**；自进化的统一框架是四组件反馈闭环：
**系统输入 → Agent 系统 → 环境 → 优化器**。综述另设专章讨论评测、安全与伦理。

落地：`episode`（系统输入/反馈）→ 五制品（Agent 系统）→ 真实任务（环境）→ `gate`+`verdict`（优化器）。

## 5. 一处主动的设计分歧

论文之间存在张力，本 skill 选了一边，明确记录：

> HyperAgents 主张元层完全可编辑以获得开放式自加速；
> Practice Makes Unsafe 证明 21/21 的演化配置都会产出不安全产物。

**取舍**：保留元层可编辑（否则不成立元认知自修改），但给元层加人类确认闸，并设三个 Agent 不可动的不动点文件。代价是牺牲一部分自加速速度，换取"不会把安全约束自己演化掉"。

这属于工程取舍而非论文结论，使用者若在隔离沙箱中追求最大自演化速度，可自行放宽——但请先读一遍 Practice Makes Unsafe 的 21/21。
