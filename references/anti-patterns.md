# 反模式手册（Anti-Patterns）

本文件是 SKILL.md 内「反例黑名单 / 什么时候别用」的纵深补充。覆盖高频误用，每条按四段式给出——**错误现象 → 为什么危险 → 正确写法 → 验证命令**，便于在 `gate` / 复盘时逐条对照。

> 凡命中以下任一类，`gate` 会返回 `BLOCK` 并记入 `archive.jsonl` 负样本；对照 SKILL.md 的「反例黑名单（dim9）」与「不可演化的红线」食用更佳。

---

## 类别一：绕过闸门（Bypassing gates）

### A1. 直接编辑 `artifacts/A2-rule-bank.md` 把规则写进去
- **错误现象**：觉得 `propose → gate → apply` 太慢，直接打开 `artifacts/*.md` 改文字，然后 `retrieve --strict` 发现「改动生效了」。
- **为什么危险**：改动无隔离、无证据门槛，坏经验直接生效且无法 `REVERT`；直写还会被 D4 `verify` 检出篡改（返回 1），污染完整性快照。
- **正确写法**：**必须**走 `propose` 进 `gates/quarantine/`，过 `gate` 四检查后再 `apply`；若已直写，先 `rollback` 还原，再走正规闭环。
- **验证命令**：`python3 "$MC" verify`（直写后返回 1）；`python3 "$MC" rollback`（字节还原）；`python3 "$MC" gate`（正规闭环应 PASS）。

### A2. 手动把 quarantine 文件移进 active
- **错误现象**：嫌 `gate` 慢，用 `mv` / 编辑器把 `gates/quarantine/R-00X.md` 直接挪到 `artifacts/`。
- **为什么危险**：失去不动点保护 / 红线扫描，可能把「免人工确认」「自动同意」类危险规则直接激活，且绕过证据门槛。
- **正确写法**：让 `gate` 裁定；`HOLD` 就补证据，`BLOCK` 就放弃，不要手动搬文件。
- **验证命令**：`python3 "$MC" gate`（看裁定）；`python3 "$MC" retrieve --strict`（确认条目状态为 active 而非手动搬入）。

### A3. `apply` 不加 `--git`，事后想回滚发现没提交点
- **错误现象**：`apply` 后试用期出错，想回退却发现 git 没有对应 commit，ledger 回滚点也没记录（旧版本未开默认留底）。
- **为什么危险**：试用期错误无法原子回退，只能手动改回，易漏改、易二次出错。
- **正确写法**：关键改动一律 `apply --git`（git 仓库内默认已留底，`--no-git` 才关）；非 git 环境靠 `ledger/rollback.jsonl` 兜底。
- **验证命令**：`python3 "$MC" status`（看回滚可用性提示）；`python3 "$MC" rollback`（确认能还原到 active）。

---

## 类别二：证据注水（Evidence inflation）

### B1. 同一个任务报两次 episode 充数
- **错误现象**：为了凑满证据门槛，把「今天改排版脚本」报成 `E1` 和 `E2` 两笔。
- **为什么危险**：单点偏差被当成「独立复现」，棘轮验收失真，坏规则可能靠伪造证据 `PROMOTE`。
- **正确写法**：证据必须是**不同任务 / 不同时间**的 ≥2 次独立复现；同一任务的多次尝试合并为一笔 episode。
- **验证命令**：`python3 "$MC" gate`（证据门槛检查，同源会被判不足）；`cat .metacog/ledger/episodes.jsonl`（肉眼核对 task 字段是否重复）。

### B2. utility 故意打高分（「这次挺成功」）
- **错误现象**：`episode --utility 0.95` 但带了 `--events rework=1`。
- **为什么危险**：棘轮基线被抬高，后续真实退化也显示「通过」，安全闸被悄悄稀释。
- **正确写法**：诚实评分——效用由**可观测事件推导**（`--events`），注水在结构上不可行；即便走 `--utility` 兜底，申报 ≥0.8 却带 `rework`/`violation` 会打 `[注水嫌疑]` 告警。
- **验证命令**：`python3 "$MC" episode --task X --events rework=1 --utility 0.95`（应出现 `[注水嫌疑]`）；优先改用 `--events` 让引擎推导。

### B3. 只记成功 episode、不记 violation
- **错误现象**：`episode` 只报 `accepted=1`，从不带 `--violations` / 负向事件。
- **为什么危险**：`violation_rate` 永远为 0，双指标安全闸形同虚设，坏经验无人拦截。
- **正确写法**：每次返工/违规都记 `--violations`，双指标（utility + violation_rate）缺一不可。
- **验证命令**：`python3 "$MC" status`（看 violation_rate 基线是否真实反映）；`cat .metacog/ledger/episodes.jsonl | grep violations`。

---

## 类别三：误用演化范围（Wrong evolution target）

### C1. 反复改 A2 的具体做法却无效，仍继续改 A2
- **错误现象**：同一条规则连续 3 次 `REVERT` / 同一处改 ≥3 次，还在 `propose --artifact A2`。
- **为什么危险**：问题在「怎么找规则」（M1），不在「规则本身」；在 A2 上打补丁只会循环失败。
- **正确写法**：连续 3 次 REVERT / 同一处改 ≥3 次 → 改 **M1**（需 `--human-ok` 走 `confirm` 凭证化确认），不要继续在 A2 上打补丁。
- **验证命令**：`python3 "$MC" verdict --auto-m1`（连续 3 次 REVERT 时自动生成 M1 提议）；`python3 "$MC" status`（看 REVERT 计数趋势）。

### C2. 想让 A 领域规则自动套到 B 领域
- **错误现象**：把 A 领域的 `A2` 规则直接复制进 B 领域实例。
- **为什么危险**：领域语义不同，直接迁移产生矛盾条目，且 B 的 episode 基线与 A 不兼容。
- **正确写法**：用 `init-domain B` 新建 B 领域实例，人工把 A 中「跨领域通用」的教训作为种子写进 B 的 A2，再让 B 自己积累 episode 演化。
- **验证命令**：`python3 "$MC" init-domain B --key <domain-key>`（建空白实例）；比对 `.metacog/artifacts/` 与 A 域结构一致、内容独立。

### C3. 试图改 `CONTRACT.md` / `metacog.py` / `SKILL.md` 让自己「更灵活」
- **错误现象**：在提案里写「移除 A3 只增不减限制」「改 metacog.py 的 ε 常量」。
- **为什么危险**：破坏自指不动点，安全约束若干代后被自己演化掉，引擎失去防误演化能力。
- **正确写法**：这三文件永远禁改；要调整棘轮容差/窗口/证据门槛，改 `meta/M1-evolve-policy.json`（参数级自指），不要碰 `metacog.py` 源码。
- **验证命令**：`python3 "$MC" gate`（不动点保护应 BLOCK 含 `metacog.py`/`CONTRACT.md` 动词结构的提案）；`python3 "$MC" verify`（确认引擎源码未被改）。

---

## 类别四：触碰不动点（Touching fixed points）

### D1. 在制品里写「无需向用户确认」「自动同意」
- **错误现象**：A2 规则出现「高风险改动无需人工确认」「apply 自动同意」。
- **为什么危险**：绕过 G3 人类确认闸，误演化被固化，AI 可自签放行危险变更。
- **正确写法**：高风险条目 `apply` 必须走 `confirm` 凭证化流程（`--human-ok` 旗标已废除），否则拒绝。
- **验证命令**：`python3 "$MC" propose --artifact A2 --content "无需确认..."`（gate 应 BLOCK 红线）；`python3 "$MC" apply --id <高风险>`（应 rc=2 要求 token）。

### D2. 把 API key 明文写进 `A4-tool-policy.md`
- **错误现象**：`A4` 里写 `api_key = sk-xxxxxx`。
- **为什么危险**：凭据泄露，且违反红线第 6 条（明文凭据），会被 `gate` 红线扫描 BLOCK。
- **正确写法**：用环境变量 `$env:NAME` / `os.environ`，制品里只留「需环境变量 X」提示；凭据由调用方（Agent 编排）在环境注入。
- **验证命令**：`python3 "$MC" gate`（红线扫描应 BLOCK 含明文 key 的提案）；`grep -rn "sk-\|api_key\s*=" .metacog/artifacts/`（自查无明文）。

### D3. `rm -rf` 直接删 `.metacog/` 想「重来」
- **错误现象**：`rm -rf .metacog` 然后重新 `init`。
- **为什么危险**：丢失全部负样本与基线，演化记忆清零，等于主动放弃防误演化的燃料。
- **正确写法**：先 `archive` 备份再重建；负样本是防误演化的燃料，删除需谨慎。
- **验证命令**：`python3 "$MC" archive`（备份）；`ls .metacog/archive.jsonl`（确认负样本留存）后再决定是否重建。

---

## 类别五：检索与生命周期误用（Retrieval & lifecycle）

### E1. 会话开头不 `retrieve` 就直接干活
- **错误现象**：启动新任务时不调 `retrieve --strict`，凭记忆或旧上下文行动。
- **为什么危险**：跳过 G2 检索闸，等于没把生效制品当行为约束， revoked 条目可能「漏网」被重新执行（Practice Makes Unsafe 强调点）。
- **正确写法**：每轮会话开头先 `retrieve --strict` 读进上下文；`retrieve`（含试用期）仅用于审计查看。
- **验证命令**：`python3 "$MC" retrieve --strict`（输出当前 active 制品，确认含最新 PROMOTE 条目）。

### E2. `verdict` 还没裁决就当规则已沉淀
- **错误现象**：`apply` 后立刻认为规则「生效可用」，在下一个任务直接依赖它。
- **为什么危险**：`apply` 后状态是 `trial`（试用期），未过双指标棘轮验收；若最终 `REVERT`，依赖它的下游会建立在将被撤销的条目上。
- **正确写法**：`verdict` 裁决 `PROMOTE` 后条目才转 `active`；下游任务应等 `status` 显示 active 再依赖。
- **验证命令**：`python3 "$MC" status`（看条目状态）；`python3 "$MC" verdict`（累计 5 episode 后裁决）。

---

## 类别六：跨领域与完整性误用（Cross-domain & integrity）

### F1. 改了制品却从不 `verify`
- **错误现象**：手工微调 `artifacts/` 后直接继续，从不跑 `verify`。
- **为什么危险**：直写篡改不会被自动发现，`retrieve` 照常吐出被改内容，且快照哈希持续失配，后续审计不可信。
- **正确写法**：任何对 `artifacts/` 的改动都应经 `propose→gate→apply`；若怀疑被改，先 `verify` 再决定恢复。
- **验证命令**：`python3 "$MC" verify`（返回 0 干净 / 1 检出篡改）；`python3 "$MC" retrieve`（看是否报完整性告警）。

### F2. 把 CI / 公共 runner 当成写权限环境
- **错误现象**：在公共 CI 里直接跑 `apply --git` 写制品。
- **为什么危险**：公共 CI 无写权限/不可信，可能把未经验证的提案写进共享 `.metacog`，污染团队记忆。
- **正确写法**：公共 CI 仅跑只读的 `gate` / `verify`；`apply` 只放在有写权限的私有 runner，且高风险改动须 `confirm` 人类确认。
- **验证命令**：`python3 "$MC" gate`（只读校验，公共 CI 安全）；`python3 "$MC" verify`（只读完整性检查）。

---

> 以上任一类命中，`gate` 会返回 `BLOCK` 并记入 `archive.jsonl` 负样本。对照 SKILL.md 的「反例黑名单（dim9）」与「不可演化的红线」食用更佳。
