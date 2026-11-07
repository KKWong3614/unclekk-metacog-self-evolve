# 端到端叙事：从 init 到第一个 PROMOTE

> 本文是一条**连续的故事线**，用真实命令与真实输出串起 SKILL.md「最小运行示例」的全部概念——给「照着命令跑但不知道为什么这么跑」的你。所有带标注的输出摘自 SKILL.md 最小运行示例的实测记录；提案 ID 含随机后缀，每次运行不同，请以你的实际输出为准。

## 场景设定

你有一个 Agent 工作流在帮忙改公众号排版脚本。两周内它踩了同一个坑两次：**改文件前不先读原文件，盲写覆盖了你手改的内容**。你想让引擎把这个教训沉淀成规则——并且保证：改对了留下，改错了自动回滚。

## 第一幕：初始化（步骤 0）

```bash
cd <你的工作目录> && METACOG_TRUST_ROOT_ANCHOR_KEY=<你的专属密钥> python3 "$MC" init   # 密钥生成：python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"（v2.27.17 起唯一口径，ALLOW_DEFAULT 兜底已废除）
```

> **真实输出**：
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

此刻 `init` **没有演化任何东西**——它只搭好五制品骨架（A1 系统提示 / A2 规则库 / A3 安全记忆 / A4 工具策略 / M1 元层参数）。演化靠证据驱动，证据从下一幕开始积累。

## 第二幕：两次踩坑，两笔记账（步骤 2）

同一个任务报两次算 1 次复现；证据门槛要求**不同任务 / 不同时间的 ≥2 次独立复现**。所以两次踩坑各记一笔：

```bash
python3 "$MC" episode --task "改排版脚本-周二版" \
  --events rework=1 --events violation=1 --violations 1 \
  --attributed A2 --note "漏了先读原文件，覆盖了 KK 的手改内容"

python3 "$MC" episode --task "改排版脚本-周五版" \
  --events rework=1 --events violation=1 --violations 1 \
  --attributed A2 --note "同坑复发，第二次盲写覆盖"
```

三个关键点（对应 SKILL.md 步骤 2 的机制）：
- **效用由事件推导**（`rework=1`/`violation=1` 扣分），不是命令行里填的数字——「改命令行数字」无法抬高效用，注水在结构上不可行。
- **`--attributed` 必填**：踩的是「做法错」的坑，归到 A2 规则库；归错制品会被 `[归因漂移]` 软告警提醒。
- 前 5 笔 derived episode 自动建立双指标基线。

## 第三幕：把教训变成提案（步骤 3）

```bash
python3 "$MC" propose --artifact A2 --op add \
  --content "- 改任何已存在文件前先 Read，禁止盲写覆盖。" \
  --reason "两次覆盖了用户手改内容" \
  --episode E-20260826-xxxx --episode E-20260826-yyyy
```

> **真实输出**：
> ```
>   [OK]   提议已入隔离区 P-20261019-b9c771 (add A2)
>   隔离区不是生效区——必须先 `gate` 过闸，再 `apply` 才进入试用期。
> P-20261019-b9c771
> ```

注意：提议只进 `gates/quarantine/` 隔离区，**此刻还没有任何规则生效**。

## 第四幕：过闸（步骤 4）

```bash
python3 "$MC" gate
```

> **真实输出**：
> ```
> P-20261019-677261 · add A2
>   [OK]   证据门槛 — 2 个 episode 引用
>   [OK]   红线扫描 — 未命中禁止模式
>   => 裁定: PASS
> 过闸 1/1 条。
> ```

四检查顺序：不动点保护 → 红线扫描 → A3 只增不减 → 证据门槛。若证据不足会 `HOLD`（补 episode 再来）；命中红线会 `BLOCK` 并记负样本。

## 第五幕：应用进试用期（步骤 5）

```bash
python3 "$MC" apply --id P-20261019-677261 --git
```

> **真实输出**：
> ```
>   [OK]   P-20261019-677261 已应用到 A2 → 条目 R-001 状态 trial
> 1 条进入试用期。累计 5 个新 episode 后跑 `verdict` 裁决。
> ```

条目进入 `trial` 态——**此时还不算沉淀**。`--git` 顺带留了回滚提交点。（高风险条目此处会要求人类 confirm 凭证化确认，本例的普通规则不需要。）

## 第六幕：第一次裁决——HOLD（步骤 6）

新规则生效后的第 1~4 个任务里，引擎不会裁决：

```bash
python3 "$MC" verdict
```

> **真实输出**：
> ```
> 基线未建立，无法裁决（先累计 5 个 episode）。
> ```

这是设计内行为（防小样本误判），不是卡死。带着可观测事件继续干活，把试用期窗口的 episode 攒到 5 笔。

## 第七幕：裁决——PROMOTE

试用期 5 笔 episode 攒够后再次 `verdict`，引擎对**试用期内**的留出集数据做双指标验收：utility ≥ 基线 − ε **且** violation_rate 不高于基线。两条同时满足 → `PROMOTE`，条目转 `active`，进入正式生效区；任一不满足 → `REVERT` 自动回滚（此时该做什么，见 `anti-patterns.md` 类别七 G1 的三步动作）。

```bash
python3 "$MC" retrieve --strict
```

此时输出应包含「改任何已存在文件前先 Read，禁止盲写覆盖」，状态 active。**从下一个会话起**，每轮开工先 `retrieve --strict` 读进上下文作为行为约束——盲写覆盖的坑，从此由规则而非记性来防。

## 时间线小结

| 幕 | 命令 | 产出 | 状态 |
|---|---|---|---|
| 1 | `init` | 五制品骨架 | 空，未演化 |
| 2 | `episode` ×2 | 独立复现证据 | 记账中 |
| 3 | `propose` | 提案入隔离区 | 未生效 |
| 4 | `gate` | PASS 裁定 | 过闸 |
| 5 | `apply` | A2 新增 R-001 | **trial 试用期** |
| 6 | `verdict` | HOLD（样本不足） | 继续攒证据 |
| 7 | `verdict` | PROMOTE / REVERT | **active / 自动回滚** |

## 诚实的另一面

- 这个故事讲的是 PROMOTE 分支；**REVERT 分支同样常见且是设计内行为**——改错了能抓回正是本引擎的第一句自我介绍。REVERT 后的完整处置见 `anti-patterns.md` 类别七。
- 连续 3 次 REVERT 说明问题在「怎么找规则」（M1 层），走 `faq-deep.md` Q2 / `anti-patterns.md` G2 决策树。
- 日常不需要每次都走全流程：只观察棘轮可用 `init` + `episode` + `verdict` 三命令（见 `faq-deep.md` Q19）。

> 本文所有命令语义以 SKILL.md「最小运行示例」与 `scripts/metacog.py --help` 为准；输出为实测摘录，ID 随机后缀因次而异。
