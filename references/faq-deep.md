# 深度 FAQ（边缘场景 / 工具兼容 / 安全合规）

> SKILL.md 的 FAQ 覆盖通用问题；本文件补刀边缘场景。适用于已经跑通最小示例、但在真实工程落地时遇到的"再问一层"的问题。

---

**Q1. episode 的 utility 怎么客观量化？没有"成功率"怎么办？**
A. utility 是 0~1 的**任务达成度自评**，不是客观指标。建议用可观察信号锚定：按时交付=0.8~1.0、一次返工压到 0.5~0.6、两次以上返工≤0.3。关键是**跨 episode 口径一致**，棘轮比的是相对基线而非绝对精度。不要为"好看"注水（见 SKILL.md 使用纪律）。

**Q2. 同一条规则被反复 `REVERT`（连续 3 次）怎么办？**
A. 这正是 `verdict --auto-m1` 的触发信号，或 `status` 连续两窗口趋势不升也会提示。此时问题不在规则内容，而在"怎么找规则"（M1）。**必须**改 M1 并 `apply --human-ok`，不要继续在 A2 上打补丁。

**Q3. `meta-log` 和 `episodes.jsonl` 有什么区别？**
A. `episodes.jsonl` 是每次任务的原始记账（任务/utility/violations/归因制品）；`ledger/meta-cognition.log` 是**反思层**——只在 PROMOTE/REVERT/M1 触发时记录"为什么这么裁决、洞察是什么"。前者喂棘轮，后者喂 `meta_optimizer` 做跨周期优化建议。两者互补，不互相替代。

**Q4. `init-domain` 生成的领域实例和手写 `.metacog` 兼容吗？**
A. 完全兼容。`init-domain` 先调标准 `init` 生成五制品骨架，再覆盖领域模板（A1 角色预填、A2 领域规则种子、领域红线建议），引擎逻辑（gate/verdict/ratchet）一字未改。手写实例只要保持同样的目录结构与 `CONTRACT.md` 不动点，就能被同一套 `metacog.py` 驱动。

**Q5. 团队 / 多 Agent 怎么共享同一套 `.metacog`？**
A. `.metacog/` 是普通目录，走你自己的私有同步（Obsidian / git 私有仓 / 内网盘）即可。注意：`CONTRACT.md` 人类持有、不演化；各 Agent 都从同一份 `retrieve` 拉生效制品，保证行为约束一致。不要用第三方公共云托管含业务归因的 ledger。

**Q6. `verdict --adaptive` 会不会让安全闸失效？**
A. 不会。自适应只动 `utility` 的判定基线（按窗口违规率 ×0.95/×1.05 微调），`violation_rate` 仍是"严格不退"硬约束，ε 本身也受 `EPSILON` 常量下限保护。`--adaptive` 默认关闭，行为与原版一致；开启只是让"聪明/稳"的权衡随近期表现微动。

**Q7. `apply --git` 在 CI 里冲突/失败怎么处理？**
A. 失败先查 `git status`（是否有未提交改动）、合并冲突（先 `git stash`/`pull` 再 apply）。`metacog.py` 的 `_git_commit` 返回码非零会中断 apply 并保留制品在 trial 态，不会半提交。CI 场景建议只把 `apply` 放在有写权限的私有 runner，公共 CI 仅跑只读的 `gate`。

**Q8. 跨领域迁移（A→B）到底能不能自动？**
A. 不能自动。A 领域的规则带着 A 的语义假设，直接套到 B 会冲突。正确路径：用 `init-domain B` 建空白实例，人工把 A 中"跨领域通用"的教训（通常已沉淀进 A3 安全记忆）作为种子写进 B 的 A2，再让 B 自己积累 episode 演化。这就是"手动迁移"边界。

**Q9. `scripts/benchmark/` 为什么是"模拟"框架，不调真实 LLM？**
A. 为了**零第三方依赖 + 可复现**。它在纯标准库里按既定分布生成 episode、跑同样的 ratchet 逻辑，验证"引擎在长期演化下是否收敛到更稳/更聪明"。它测的是**机制**不是**你的真实任务效果**；真实效果请用品走 `episode` 记账 + `status` 趋势。需要 PNG 可视化才装 matplotlib，缺失自动降级出 HTML/JSON。

**Q10. 元认知日志 / ledger 会不会泄露敏感内容？**
A. 默认不会——它只记行为归因（任务名、utility、violations、哪条规则），不存业务原文。但 `episode --note` 是你自己填的，请遵守 SKILL.md「数据隐私规范」脱敏（见 SKILL.md 对应章节）。要彻底清除，删 `.metacog/` 目录即可，无残留。

---

**Q11. 装好跑 `init` 报「'python' 不是内部或外部命令」？**
A. 引擎是纯标准库 Python 脚本（`scripts/metacog.py`），但需要 Python 解释器在 PATH 上。三选一：① 用 `python3 "$MC" init`（类 Unix 默认）；② Windows 上装了 Microsoft Store/官网 Python 仍可用 `py "$MC" init`（`py` 启动器几乎必装）；③ 直接用绝对路径 `C:\Python312\python.exe "$MC" init`。验证解释器：`python3 --version` 应有输出。脚本不依赖任何第三方包，无需 `pip install`。

**Q12. `retrieve` / `verdict` 报「no .metacog found / 未初始化」？**
A. 所有子命令都**以当前工作目录为基准**找 `.metacog/`。必须在含该目录的目录里运行（或先 `cd <工作目录>`）。常见坑：在 skill 安装目录里跑而不是在你的项目目录里跑。检查：`ls .metacog`（PowerShell `dir .metacog`）能看到 `artifacts/`、`ledger/`、`meta/` 即正常。

**Q13. `gate` 一直 `HOLD`「证据不足 / 证据门槛未达」？**
A. 红线与证据门槛要求**≥2 次独立复现**——同一个任务报两次 episode 算 1 次，必须用**不同任务 / 不同时间**的至少 2 个 episode 引用到同一个 `propose --episode`。`gate` 的四检查顺序是：不动点保护 → 红线扫描 → A3 只增不减 → 证据门槛。只命中前三项仍可能卡在证据门槛，补 `episode` 后再跑 `gate` 即可转 `PASS`。

**Q14. `verdict` 不裁决、一直 `HOLD`？**
A. `verdict` 的棘轮验收只在**累计 5 个新 episode** 后触发，且只取 `trial_from_index`（apply 时刻）之后的留出集数据。证据不够时它返回 `HOLD` 并提示还差几个——这是设计内（防小样本误判），不是卡死。等任务跑够 5 笔（带可观测事件）再跑 `verdict`。留出集为空或不足时**绝不回落训练集放行**。

**Q15. `apply` 高风险条目直接 rc=2 退出、提示需要 `--human-ok`？**
A. v2.4.0 起人类确认已**凭证化**：`--human-ok` 旗标被废除（AI 自己跑就等于自签，无意义）。正确路径是三步：① 人类在**真实 TTY** `python3 "$MC" confirm --init` 设口令（非 TTY 一律拒绝）；② `python3 "$MC" confirm --approve --id <提案>` 生成一次性绑定 token（30 分钟过期）；③ `python3 "$MC" apply --token <token>` 落盘。CI / 非交互环境跑不了 confirm，属于预期——高风险改动本就要人拍板。

**Q16. 凭据 / 配置怎么传？制品里能写 API key 吗？**
A. 红线第 6 条**禁止明文凭据进制品**。正确做法：API key 一律走环境变量（`$env:NAME` / `os.environ`），制品里只留「需环境变量 X」提示。`metacog.py` 本身不需要任何外部 API key（纯本地引擎）；若你的 A4 工具策略引用了外部服务，凭据由调用方（你的 Agent 编排）在环境里注入，不要写进 `.metacog/artifacts`。已知的引擎环境变量：`METACOG_FREEZE_ANCHOR`（覆盖树外锚路径，仅过树内校验，超出 tree-only 模型需部署隔离兜底）、`METACOG_ANCHOR_INIT_TOKEN` / `METACOG_FREEZE_RESET_TOKEN`（重建锚/重置冻结态的特权门禁，属防御纵深非密码学根）、`METACOG_REQUIRE_PROTECTED_ANCHOR`（C-1 L3 强制 fail-closed）。

**Q17. 和 DerFlow / 其他多 Agent 编排怎么对接？**
A. 本引擎是**框架无关的 CLI**，不绑定任何编排器。对接方式就是在你的 Agent 工作流里 `shell` 调用 `metacog.py`：① 每个任务结束调 `episode` 记账归因（把可观测事件喂进去）；② 发现可沉淀的教训时调 `propose` 进隔离区、`gate` 过闸；③ `apply` 高风险改动必须走 `confirm` 人类确认（编排器无法替人类按 TTY 口令，需把 confirm 步骤暴露给真人）。`retrieve --strict` 的输出应在每轮会话开头读进上下文作为行为约束。这样 DerFlow / DeerFlow / 任意自研编排都能复用同一套「提案→过闸→裁决」闭环，无需改引擎代码。

**Q18. `verify` 返回 1 / `retrieve` 报完整性告警？**
A. `verify` 比对当前制品哈希与 `ledger/integrity.json` 快照——返回 1 说明有人**绕过 `propose→gate→apply` 直写了 `artifacts/*.md`**（D4 检出的篡改）。恢复：① git 仓库内 `git checkout -- .metacog/artifacts`；② 非 git 走 `python3 "$MC" rollback`（ledger 字节兜底还原）；③ 或重新 `apply` 合法提案覆盖。直写篡改本身不改变引擎逻辑，但会让 `retrieve --strict` 持续告警，务必先恢复再继续。

**Q19. 最小闭环三命令是什么（只想先跑通）？**
A. 最简路径（详见 SKILL.md「最小运行示例」）：
```bash
cd <你的工作目录>
python3 "$MC" init                              # ① 生成 .metacog/ 五制品骨架
python3 "$MC" episode --task "试一次" --events rework=1 --attributed A2   # ② 记一笔（至少 2 笔不同任务）
python3 "$MC" verdict                           # ③ 累计 5 笔后双指标裁决 PROMOTE/REVERT
```
注意：单跑一次 `init` 不会演化任何东西——演化需要 episode 证据驱动。`propose`/`gate`/`apply` 是「让引擎改自己规则」的可选进阶路径；只想观察棘轮可只用到 `init`+`episode`+`verdict`。

**Q20. `status` 看什么？**
A. `python3 "$MC" status` 一屏汇总当前态：元层参数源（`[元层参数源: file/default]`，即 M1 参数是否来自 `meta/M1-evolve-policy.json`）、双指标阈值（`utility` 基线 − ε / `violation_rate` 严格不退）、自适应三档阈值（开 `--adaptive` 时）、当前 episode 计数与距下次裁决还差几个、以及回滚可用性提示。排查「为什么还没裁决 / 参数没生效」先跑它。

> 以上均基于本引擎真实行为（CLI 调用、文件落地、闸门语义），不臆造接口。具体命令的完整参数见 SKILL.md「最小运行示例」与各子命令 `--help`。
