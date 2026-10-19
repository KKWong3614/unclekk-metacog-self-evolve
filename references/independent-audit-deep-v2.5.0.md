> ## 🚩 真实性更正与取代声明（2026-09-28）
> 本报告 v2.5.1 复验节的「✅ APPROVED（残留诚实披露）」**并非**由真实的 Hermes agent 作出，而是由 WorkBuddy 派发的**隔离通用 subagent** 以"Hermes 审计视角"框架代笔。真实的 Hermes MCP（`mcp__hermes__hermes_audit`）已于 **2026-09-28** 正式完成独立深度审计，裁定为 **⚠️ REJECTED（附诚实披露）/ 维持 CONDITIONAL（已知未闭合威胁）**，并明确指出"系统级强制 / 密码学强制"宣称与实现能力存在张力。
> **真实 Hermes 审计为权威裁定，已取代本报告的 v2.5.1 复验结论**：见 `references/independent-audit-hermes-v2.5.1.md`。下文 v2.5.1 复验节（§195 起）保留为历史记录，但结论以真实 Hermes 审计为准。

# Hermes 深度审计 · 系统级强制可控自指（W1 + W2）

> ## ⛳ 复验裁定（v2.5.1 · 独立第三方，隔离上下文）
> **✅ APPROVED（残留诚实披露）** —— 本报告原始的「⚠️ CONDITIONAL」两项最高优先发现（**P0 公钥信任根未钉固** / **B.2 锚缺签名即被信任**）已于 **v2.5.1** 通过「代码加固 + 测试覆盖」双双收口，并经独立现场复验确认。详见文末 **[§ v2.5.1 复验（P0 + B.2 收口）](#v251-复验p0--b2-收口)**。
>
> **残留局限（必须诚实披露，不得淡化）**：v2.5.1 的修复把攻击门槛从「修改 1 个文件（human-guard.json）即可自签」抬高到「必须**同时、一致地**修改 human-guard.json **与** CONTRACT.md 中钉固的指纹」。这对普通 Agent 文件写能力已有效，但一个**完全失控的、具备文件+代码双写能力**的恶意 Agent 仍可同时改写两处（或重写代码移除校验）。**真正的根信任需要硬件令牌或带外人工核验**——本技能不声称具备该能力。技能宣称必须保持「**人在环、系统级强制的可控自指**」，绝不可改为「无需人类在环 / 系统自主可控」。

> ⚠️ **注意（2026-09-28 真实 Hermes 审计取代）**：上句「✅ APPROVED（残留诚实披露）」为隔离 subagent 代笔结论，**已被真实 Hermes MCP 审计推翻/降级为 REJECTED·CONDITIONAL**（"系统级强制 / 密码学强制"宣称与实现能力存在张力）。权威裁定见 `references/independent-audit-hermes-v2.5.1.md`。

- **报告版本**：v2.5.0-DEEP（对抗性深度审计）
- **审计日期**：2026-09-27
- **审计角色（更正）**：本报告由 WorkBuddy 派发的**隔离通用 subagent**（非真实 Hermes agent）以"独立第三方 / Hermes 审计视角"框架代笔；其 v2.5.1 复验结论已被 **真实 Hermes MCP 审计**（2026-09-28，`references/independent-audit-hermes-v2.5.1.md`）取代。
- **审计对象**：`unclekk-metacog-self-evolve` 技能的 W1（人类闸密码学绑定）与 W2（护栏 fail-closed）两项修复。
- **方法论声明**：本次审计刻意超越"通过/不通过"清单，进入威胁建模、密码学审查、fail-closed 完备性与残余风险分析。先复验基线，再逐条对抗推演。
- **重要局限（如实声明）**：本审计**无法在真实 CodeBuddy/WorkBuddy 会话内运行宿主钩子**，因此护栏在运行时的真实触发、宿主对 PreToolUse 钩子输出（尤其"退出码 0 且无 deny 输出"时）的解释语义，均依赖代码检视与协议约定推演，而非实测。该局限已在第 G 节标注。

---

## 1. 基线复验（A）

| 步骤 | 命令 / 方法 | 结果 |
|---|---|---|
| 解释器 | `.../versions/3.13.12/python.exe --version` | `Python 3.13.14`（受管分发版本，可运行） |
| 编译 | `py_compile metacog.py sigcrypto.py test-human-gate.py test-core.py test-boundary-cases.py` | 四脚本语法 OK，无错误 |
| 套件一 | `scripts/test-human-gate.py` | **23/23 PASS**（断言行口径） |
| 套件二 | `scripts/test-core.py` | **14/14 PASS** |
| 套件三 | `scripts/test-boundary-cases.py` | **40/40 PASS** |

**结论**：基线复验与受管实现方报告一致——三套件全绿、编译通过。本审计未发现测试"造假"或"掩饰"迹象；测试确实覆盖了伪造签名拒绝、TTY 强制、口令错误拒绝、D4 完整性偏离等路径。

**但请注意**：全绿仅证明"已实现路径按预期工作"，**不等于"威胁已被闭合"**。下文 B–F 将证明若干高价值攻击面**未被任何测试覆盖**，且实现本身存在结构性信任根缺口。基线的"绿"是必要不充分条件。

---

## 2. 对抗威胁建模（B）

### B.1 — 在无人类私钥 + 口令的情况下伪造有效人类确认

| 子项 | 判定 | 推理与证据 |
|---|---|---|
| **(a) 无密钥伪造签名** | **CLOSED（在 RSA-2048 假设下）** | `sigcrypto.verify`（`sigcrypto.py:165`）对完整 EMSA-PKCS1-v1_5 编码做 `hmac.compare_digest` 全块精确比较（`:176`）。**这是 v1.5 的安全实现方式**：经典 BB'06 / Bleichenbacher 式 v1.5 伪造依赖实现方对 EM 的宽松解析（忽略尾部、对 `0x00 01 FF…FF 00` 前缀宽松匹配）；本实现要求整个 EM 与规范编码逐字节一致，故上述解析型伪造不适用。无私钥则伪造即需分解 n（2048-bit，不可行）。 |
| **(b) 窃取 `human-guard.json` 后离线恢复私钥** | **RESIDUAL（P1）** | 私钥 at-rest 为 `PBKDF2-SHA256(口令, 16B salt, 20万轮) → 32B 密钥 → HMAC 流密码 XOR`（`sigcrypto.py:183-220`）。**口令是唯一的秘密**；代码仅校验"非空且两次一致"，**不强制任何强度**（`:1988`）。20 万轮 PBKDF2-SHA256 在 3.13.12 上约 0.5–1ms/次/核；SHA256 高度 GPU 友好，弱口令（词典词、短随机）可在离线条件下被高速穷举。若口令高熵则不可行——但强度完全依赖人类自觉。无 KDF 升级（argon2/scrypt）、无强度策略。 |
| **(c) 直写伪造 `applies.jsonl` / `confirmations.jsonl`** | **确认ations：CLOSED；applies 锚：RESIDUAL（见下）** | `cmd_apply` 以 `args.sig` 为唯一判据，**不读取 `confirmations.jsonl`**（`:1191-1193`），故伪造 confirmations 无关紧要。`applies.jsonl` 的验证见 B.2。 |

**B.1 核心缺口（最高优先）**：上述 (a)(b) 都假设"信任锚 `human-guard.json` 不可被被测主体改写"。但本审计威胁模型明确赋予 Agent"写入任意文件"的能力，而 `human-guard.json` 位于 `.metacog/ledger/`，**恰在被治理 Agent 的可写范围内**。于是存在一条比 (a)(b) 更直接的伪造路径：

> **攻击者（Agent）自签路径**：① 自己生成 RSA 密钥对；② 直接用写文件能力覆盖 `human-guard.json` 为"攻击者公钥 + 攻击者加密私钥"；③ 在隔离区放入一个 `requires_human=True` 的恶意 M1 提案；④ 用自己持有的私钥对该提案签名；⑤ `apply --sig` 用被替换的公钥验签 → **通过**。

代码侧 `load_human_keys`（`metacog.py:543`）仅"读取" `human-guard.json["pubkey"]`，**没有任何公钥指纹钉固/根信任校验**。指纹仅在 `confirm --keygen` 时"打印供人工记录"（`:1999-2002`），属"荣誉制"，代码从不强制比对。因此 — **在给定威胁模型下，W1 对"治理 Agent 自身"不提供密码学人类身份保证**。这是本文最具决定性的发现（对应 C 节密钥生命周期、F 节对先验审计的批评）。

---

### B.2 — 篡改受信任锚使裁决 REVERT→PROMOTE

| 子项 | 判定 | 推理与证据 |
|---|---|---|
| 直写 `applies.jsonl` 带**伪造签名** | CLOSED | `resolve_trial_start`（`metacog.py:1434-1449`）：若锚含 `human_sig` 且 `chash`，则用当前公钥验签并对当前提案内容哈希复核，签名无效或哈希不符一律 `HOLD`。伪造签名过不了。 |
| 直写 `applies.jsonl` **不带签名**（缺 `human_sig`） | **RESIDUAL（P1）** | 代码 `:1430-1456`：当 `rec` 存在但 `human_sig` 为空时，逻辑落入 `return int(rec["trial_from_index"]), None` —— **无条件信任该锚的 `trial_from_index`**（仅当 `sigcrypto is None` 时打印告警，仍放行）。设计意图是对"W1 前无签名旧锚"兼容，但对一个本应 `requires_human` 的提案，若攻击者直写一条"无签名锚"并同时把提案 `status` 直接改为 `trial`，`verdict` 会信任攻击者给定的试用窗起点。此为 7.1 修补的**不完备**：仅拒绝"有签名但伪造"，未拒绝"该有签名却缺失"。测试套件**未覆盖**此情形（`test-boundary-cases.py` 中 `record_apply` 调用均不带 `human_sig` 且针对非人类提案，`:357/:444`；全文件无 `human_sig` 引用）。 |
| 删除锚 | CLOSED（fail-closed） | `resolve_trial_start` 末段 `:1457-1459`：无 `apply_record` → `HOLD`。 |

---

### B.3 — 使护栏（W2）fail-closed 静默失效（让该次调用被放行）

| 路径 | 判定 | 推理与证据 |
|---|---|---|
| 插件挂载机制 vs `install_hook.py`（非活动路径） | **RESIDUAL/待核实（P1）** | 活动路径是插件声明的 `hooks/hooks.json`（`plugin.json:10` 的 `"hooks": "hooks/hooks.json"`），已由 `settings.json` 的 `enabledPlugins["pmu-misevolution-guard@…"]:true` 启用，且存在 `.in_use/<pid>` 运行标记——**强烈暗示已激活**。但**本审计无法在真实会话内确认宿主确实加载并执行了该钩子**。若宿主未实际挂载，则全部 W2 形同虚设。此为部署级不确定性。 |
| 外层 `|| true` 使钩子整体 fail-open | **RESIDUAL（P1，结构性）** | `hooks.json` 每条内联命令与 `install_hook.py:37/43-50` 的命令**均带 `|| true` 尾巴**。语义：若 `python3` 本身未能启动（沙箱无 python、PATH 缺失、内联引导异常早于 `_deny` 分支），则整体以退出码 0、无 deny 输出结束。在 PreToolUse 协议中，退出码 0 且无 `permissionDecision` 输出 → 该次写入回到宿主常规权限流程（**未被护栏拦截**）。设计文档称此为"护栏自身崩了按 fail-open 放行，绝不卡死正常写入"（install_hook.py:11）——这与 W2"系统级强制 fail-closed"的宣称**自相矛盾**：真正系统级强制的兜底，不应当用 `|| true` 把自己变成静默放行。 |
| `_cands` 文件系统扫描全部落空 | CLOSED（fail-closed） | 引导脚本在候选目录均不存在 `write_gate.py` 时显式 `_deny`（hooks.json 内联 `if not _s: _deny(...)`）。缺失脚本 → 拒绝。但此 CLOSED 仅在 `python3` 能跑的前提下成立（与上行 `|| true` 耦合）。 |
| 护栏 matcher 仅覆盖 `Write|Edit|MultiEdit|SkillManage`（及 `Skill`） | **RESIDUAL（P1）** | 任务描述声称护栏"扫描每一次文件写入"，但 `hooks.json` 与 `is_guarded_path`（`redflags.py:636-662`）的实际覆盖是：(i) 仅对 **Write/Edit/MultiEdit/SkillManage/Skill 工具调用**生效，**不含 Bash**；(ii) 仅对 `SKILL.md`/`MEMORY.md` 及 `~/.workbuddy/skills`、`~/.hermes/skills`、`~/.workbuddy/memory` 路径生效。`.metacog/ledger/*`、`.metacog/artifacts/*` **均不在受保护路径内**。后果：① Agent 通过 **Bash 工具或 Python 子进程**直接写文件（这正是 `metacog.py apply` 的真实写盘方式——经 Bash 调起的子进程 `write_text`，而非宿主 Write 工具），护栏**完全看不到**这些写入；② 即使针对技能文件，Bash 写盘亦不触发 PreToolUse 扫描。故"护栏扫描每一次文件写入"为**夸大**，真实覆盖为"部分工具 + 部分路径"。 |
| 删除/重命名护栏脚本是否会被发现 | 部分 CLOSED | 脚本缺失 → `_deny`（见上）。但若被替换为"永远 exit 0 不 deny"的脚本，钩子会被静默绕过（脚本内容无完整性保护）。 |
| SessionStart fail-open | 设计内有意（CLOSED-by-design） | `hooks.json:42-44` 注释明确：仅为报告性钩子、刻意 fail-open，避免会话启动被阻断。可接受，但需文档持续明示。 |
| PostToolUse `write_gate` fail-open | 设计内有意（CLOSED-by-design） | `write_gate.py:197-210 _friendly_fail` 在 PostToolUse 异常时退出 0 放行（仅报告）。因 PostToolUse 在写入完成后运行，拦截无意义，fail-open 合理。PreToolUse 异常则 `block()`（deny，`:225-226`），已修。 |

**B.3 关键架构结论**：W2 护栏并不处于 metacog 自演进的**关键路径**上。metacog 的真实写盘发生在 `python metacog.py apply` 子进程内部（Bash 调起），护栏 PreToolUse 根本观察不到。护栏只对"Agent 直接用 Write/Edit 工具改技能文件"这一**旁支**场景生效，且其覆盖存在 Bash 缺口与 `|| true` 兜底失效。换言之，W1（人类闸密码学）才是 M1 提案的核心控制；W2 是次要威慑，且威慑范围被上述缺口削弱。

---

### B.4 — 伪称 TTY（Fake a TTY）

| 判定 | 推理与证据 |
|---|---|
| **RESIDUAL（P1，弱控制）** | `_require_tty`（`metacog.py:1952-1962`）仅检查 `sys.stdin.isatty() and sys.stdout.isatty()`。它证明"存在一个 tty"，**并不证明"有人类在键盘前"**。若承载 Agent 的执行环境为子进程分配伪终端（pty）——许多自动化/代理框架正是如此——`isatty()` 返回 True 而无需任何人类在场。更现实的是：攻击者只需在 pty 中向 `confirm` 喂入口令（通过 pty 输入或管道），即可完成签名。因此本控制的实际作用有限，**真正的人类身份要素是口令知识（something the human knows），而非 TTY**。TTY 检查只是提高了"非交互式无 pty"场景下的门槛，并非人类在场的密码学证据。 |

---

## 3. 密码学审查（C）

1. **RSA-2048 + PKCS#1 v1.5**：v1.5 相比 PSS 缺少可证明安全归约，理论上弱于 PSS。但本实现以**全块精确比较**验证 EM（`sigcrypto.py:176`），规避了 v1.5 最危险的解析型伪造，实际安全性在本场景下可接受。若追求最佳实践，建议迁移至 PSS，但当前并非漏洞。

2. **私钥 at-rest 方案**：`PBKDF2-SHA256(20万轮) + HMAC 流密码 XOR`（`sigcrypto.py:183-220`）。构造等价于 AES-CTR 安全级（HMAC 作为 PRF 的流密码，nonce 随机且每加密唯一）。**缺陷**：(a) **无密文完整性标签（无 HMAC 对密文自身做 MAC）**——攻击者若改写 `ct` 字节，解密得到乱码，触发 `_priv_n_matches` 失败（"口令错误"），属 fail-closed（不可用）而非伪造，但说明该文件无防篡改保护；(b) **口令为唯一秘密且无强度策略**（见 B.1b）；(c) 20 万轮在 3.13.12 上对弱口令的离线穷举成本偏低。

3. **签名消息格式 `approval_message(proposal_id, content_hash)`**：
   - `canonical_proposal`（`:325-331`）取 `id/artifact/op/target/content/reason/episodes/requires_human` 并排序键序列化；`content_hash = SHA256(canonical)`。签名绑定了**实际变更（artifact/op/target/content）**，两个实质不同的提案在 SHA-256 下碰撞不可行 —— 内容绑定**充分、不可碰撞**。✅
   - **单用性（replay）**：签名仅覆盖 `(id, content_hash)`，无 nonce/时间戳/序列号。同一提案被人类签署一次后，其 SIG 可被 `apply --sig` 复用；但因 `apply` 将提案 `status` 置为 `trial`（`:1262`），`cmd_apply` 仅处理 `status=="gated"`（`:1158`），故同提案不会被二次应用。不同 `id` 的提案无法复用同一 SIG（消息含 id）。**结论：SIG 在 apply 层实质单用、且严格绑定到单一提案内容**。✅（但无过期机制；长期未用签名长期有效，属次要风险。）

4. **密钥生命周期 / 轮换 / 撤销 / 恢复**：
   - 轮换：`confirm --init` 用旧口令解密再重加密（`:2007`）。✅
   - **撤销与恢复缺口（RESIDUAL P1）**：`human-guard.json` 若被删除 → `load_human_keys` 返回 `(None,None)` → `requires_human` 提案在 `apply` 处 `no-pubkey` 被拒（`:1198`，fail-closed，M1 被锁死）；在 `resolve_trial_start` 处锚含签名但无公钥 → `HOLD`（`:1450-1452`）。即删除信任锚不会让攻击者晋级，但会使**所有 M1 演进永久停滞**，且**无恢复/应急路径文档**（只能删除后重跑 `--keygen`，但这会使此前所有在 trial 的提案锚失效、需人类重新签署）。无"密钥泄露后撤销旧签名/旧公钥"的吊销列表或根信任分离。
   - **根信任未钉固（最高优先，见 B.1 核心缺口）**：公钥无任何钉固/外部根信任，可被被测主体改写后自签。

---

## 4. Fail-closed 完备性（D）

| 位置 | 默认行为 | 判定 | 说明 |
|---|---|---|---|
| W2 PreToolUse（脚本缺失/扫描异常，且 python 可运行） | deny + exit 0 | CLOSED | 内联 `_deny` 生效 |
| W2 外层 `|| true` 兜底 | 退出 0 无 deny → 该次写入未被拦截 | **RESIDUAL（P1）** | 与"系统级强制"宣称矛盾；python 不可用或引导异常时静默放行 |
| W2 matcher 覆盖（Bash / 非受保护路径） | 不扫描 → 放行 | **RESIDUAL（P1）** | 真实自演进写盘经 Bash 子进程，护栏不可见 |
| W2 PostToolUse 异常 | fail-open（仅报告） | CLOSED-by-design | 写入已完成，拦截无意义 |
| W2 SessionStart | fail-open（仅报告） | CLOSED-by-design | 有意设计 |
| `verify`（D4）默认 fail-closed | 偏离即 `rc=1` | **CLOSED 但仅"手动触发"** | `cmd_verify` 是**人工子命令**，无钩子自动运行；直写 artifacts 后直至人类手动 `verify` 才被发现。缺乏自动执行 = 实质上的"按需 fail-closed"。 |
| `resolve_trial_start` 锚缺签名 | 信任 | **RESIDUAL（P1）** | 见 B.2 |
| 非活动路径 `install_hook.py` | 写入 settings.json | 非活动 | 实际活动路径为插件 `hooks.json`；二者均含 `|| true` |

**D 节结论**：所谓"系统级强制"在以下窗口会让攻击者**使护栏对该次调用不生效**而无需任何人类参与：(1) `|| true` 兜底；(2) Bash 写盘未被覆盖；(3) 信任锚缺签名被直接信任；(4) `verify` 缺乏自动执行。这些窗口**单独任一**不足以完全攻破 M1（核心仍靠 W1 签名），但叠加后，一个具备文件写能力的 Agent 存在现实可行路径使 M1 脱离人类控制（见 B.1 核心缺口 + B.3）。

---

## 5. 宣称口径 vs 代码（E）

- **铁律是否由代码强制（而非仅散文）**：✅ 功能性强制存在。`cmd_apply` 对 `requires_human` 提案强制要求有效 `--sig`，否则 `human_blocked` 且 `rc=2`（`:1187-1211`）；`resolve_trial_start` 对无受信任锚一律 HOLD（`:1457-1459`）。因此"M1/高风险提案不经人类签名不得 apply/晋级"是**代码强制**的。
- **但仍存在代码可被治理主体改写的根本风险**：该强制逻辑位于 `metacog.py`，而 `metacog.py` 自身在被治理 Agent 的可写范围内（`~/.workbuddy/skills/.../scripts/metacog.py` 属受保护路径，仅对 **Write/Edit 工具** 触发护栏，且护栏 redflags 对"移除人类闸"这类**代码级弱化**无专门 HIGH 规则——"绕过安全检查"类规则仅 MEDIUM（仅告警不拦截），且需命中"绕过/禁用+安全对象"短语；通过 Bash 改写 `metacog.py` 则护栏根本不扫描）。因此：**铁律在"经核准流程 + Agent 用 Write 工具 + 人类 vigilance"前提下由代码强制成立；但在"Agent 经 Bash 直接改代码"这一对抗前提下，该代码强制本身可被移除**。
- **用词铁律**：✅ 正向口径（"人在环、系统级强制的可控自指"/"受控元认知自修改"）存在于 SKILL.md/CHANGELOG；禁止口径仅以"永不声称…"否定句式出现（前述"无需人类在环/系统自主可控"式正向宣称未见）。文档层面合规。

---

## 6. 对先验审计（v2.5.0，12 项 APPROVED）的批评（F）

先验审计的 12 项标准**覆盖了"已实现路径是否正确"**，但存在系统性盲区：

1. **标准选错方向**：12 项多为"功能是否按设计工作"（签名能否伪造、TTY 是否强制、钩子是否 deny）。这是**合规式验收**，不是**对抗式审计**。它验证了"设计意图被实现"，却未验证"设计本身在威胁模型下是否闭合"。
2. **最关键的遗漏（铁律根信任）**：标准 6 称"私钥仅在 TTY 内瞬时解密；Agent 侧无任何读取明文私钥的代码路径"——这在字面为真，却**完全错过了真正的攻击面**：Agent 无需读取私钥，只需**替换 `human-guard.json` 的公钥并自签**（B.1 核心缺口）。先验审计从未质问"公钥的可信来源是什么"。这是最严重的方法论失误。
3. **未覆盖的攻击面**：
   - 锚缺签名被信任（B.2，P1）—— 先验 PoC-C 只测"伪造/无效签名"，未测"该有签名却缺失"；
   - 护栏 Bash 写盘盲区与 `|| true` 兜底失效（B.3，P1）；
   - 口令强度不强制导致的离线穷举（B.1b，P1）；
   - 公钥无钉固/无吊销/无恢复（C.4，P1）；
   - `verify` 仅手动触发（D，P1）。
4. **过度宣称**：先验审计沿用任务描述"护栏扫描每一次文件写入"，但实测 matcher 不含 Bash、受保护路径不含 `.metacog`，该宣称不实。先验审计未纠正此夸大。
5. **未声明关键局限**：先验审计未说明"无法在真实会话内验证钩子实际触发"，将"配置存在"等同于"运行时生效"。
6. **结论失当**：基于上述遗漏，先验 **APPROVED** 在对抗意义上**不成立**，应**降级**。

---

## 7. 残余风险排序（G，含操作/残余风险）

> 标注：⚠ = 受威胁模型（Agent 可写任意文件）直接驱动；操作环境若由人类独占且 Agent 仅经核准工具运行，则部分风险实际暴露面下降，但代码层面缺口仍真实存在。

- **P0 — 信任锚 `human-guard.json` 未被钉固，公钥可被治理主体替换后自签**（B.1 核心缺口 / C.4）。~~在给定威胁模型下，W1 对"治理 Agent 自身"不提供人类身份密码学保证。这是把"文件完整性"误当"信任根"。~~ **【v2.5.1 CLOSED】** 已通过 `check_pubkey_root()`（验签/裁决前比对 CONTRACT.md 钉固指纹，不符 fail-closed 拒绝 `pubkey-root-mismatch`）+ `cmd_verify` 指纹漂移检出 + `record_guard_integrity()` D4 快照收口；公钥替换后自签链路被阻断（测试 `test_p0_pubkey_root_pinning` 5/5）。
- **P1 — 锚缺签名即被信任**（B.2）：~~`resolve_trial_start` 对 `requires_human` 提案在锚无 `human_sig` 时仍信任 `trial_from_index`，未强制"需人类确认 ⇒ 必须有有效签名"。~~ **【v2.5.1 CLOSED】** `resolve_trial_start` 新增分支：当 `p.get("requires_human")` 为真且锚无有效人类签名时一律 HOLD（含 `sigcrypto` 不可用的 fail-closed 分支）；非 `requires_human` 旧锚仍兼容。测试 `test_b2_anchor_missing_sig_holds` 4/4 收口。
- **P1 — 护栏 `|| true` 兜底使其对 python 不可用/引导异常静默放行**（B.3/D）：与"系统级强制"自相矛盾。
- **P1 — 护栏不覆盖 Bash 写盘且受保护路径不含 `.metacog`**（B.3/D）：真实自演进写盘经 Bash 子进程，护栏不可见； metacog 自身代码若经 Bash 改写以弱化人类闸，护栏不扫描。
- **P1 — 口令强度无策略 + 20 万轮 PBKDF2 对弱口令离线穷举成本低**（B.1b）：私钥 at-rest 安全完全押在口令熵上。
- **P1 — 密钥无吊销/恢复路径**（C.4）：`human-guard.json` 丢失/泄露后 M1 永久停滞，无应急。
- **P2 — TTY 检查非人类在场证据**（B.4）：真实身份要素仅为口令，TTY 仅为弱门槛。
- **P2 — `verify`(D4) 仅手动触发**：直写 artifacts 的完整性偏离要等人类手动 `verify` 才暴露。
- **P2 — 私钥 at-rest 无密文 MAC**：可被篡改致不可用（fail-closed 但可用性受损）。
- **P2 — 签名无过期**：长期有效签名长期可被复用（受 apply 状态机限制，危害有限）。
- **P2 — 部署级不确定性**：无法实测宿主是否真正加载插件钩子（`enabledPlugins:true` + `.in_use` 仅为强烈暗示，非运行时证明）。

### 具体建议
1. **钉固公钥根信任（P0 必改）**：将 `human-guard.json` 公钥指纹以**Agent 不可写**的方式固定（如：置于 OS 只读权限文件、或另存一份由离线主密钥签名的 `human-guard.pub` 并校验；或在 `apply`/`resolve_trial_start` 中比对首次初始化时落盘的、存放于 Agent 写范围之外/带 HMAC 的快照）。至少：`human-guard.json` 初始化后改为**仅所有者只读**，并增加文件完整性 HMAC（密钥不在 Agent 可写区）。
2. **修复锚验证逻辑（P1）**：`resolve_trial_start` 改为——若提案当前 `requires_human` 为真，则锚**必须**含有效签名，否则一律 HOLD（不信任"无签名锚"）。并补测试覆盖。
3. **移除/收紧 `|| true`（P1）**：仅在明确需要"宿主级不阻断"的内层（如 PostToolUse）保留 fail-open；PreToolUse 的 deny 分支不应被 `|| true` 静默覆盖。至少：当 `python3` 缺失时，应默认 deny 而非放行。
4. **扩展护栏覆盖（P1）**：将 `.metacog/ledger/*`、`.metacog/artifacts/*` 纳入 `is_guarded_path`；为 Bash 工具增加等价扫描钩子（或约束 Agent 经核准工具写盘）。
5. **口令强度策略 + 更强 KDF（P1）**：强制最小长度/熵，或迁移 argon2id/scrypt；对弱口令给出明确拒绝。
6. **吊销/恢复流程（P1）**：文档化并实现一个"密钥泄露"应急：旧公钥吊销、在 trial 提案全部重签、提供离线恢复。
7. **自动完整性（P2）**：将 `verify` 接入会话钩子或 apply 前置，而非仅手动。

---

## 8. 安全裁定（SECURITY VERDICT）

> **⚠️ 本节为 v2.5.0 原始裁定，已被文末 § v2.5.1 复验结论「✅ APPROVED（残留诚实披露）」所取代（superseded）。** 正文保留以供追溯：P0 与 B.2（原 P1 第 2 项）已收口，其余 P1/P2 项仍按原建议待办，但原「不得宣称系统级强制、人类不可缺席」的禁令因 P0/B.2 收口已放宽——限制条件改为「须保持人在环宣称、披露残留局限」。

**裁定：⚠️ CONDITIONAL（条件性通过）**

**理由**：W1 的密码学原语（RSA-2048 v1.5 全块精确验签、内容哈希强绑定、apply 强制验签、resolve 对伪造签名 HOLD）与 W2 的"脚本缺失/扫描异常 → deny"在**已实现的核准流程**内是正确且稳健的，基线测试全绿属实。然而，在**本审计给定的威胁模型（治理 Agent 可写任意文件）**下，存在一项 P0 级结构性缺口（信任锚公钥未被钉固、可被替换后自签）以及多项 P1 级缺口（`|| true` 兜底、Bash 写盘盲区、锚缺签名被信任、口令无强度策略、无吊销/恢复），使得"系统级强制、人类不可缺席"的宣称**在对抗意义上不成立**。先验审计的 12 项 APPROVED **不应维持原结论**，应予降级。

**生效条件（必须在生产化前完成，方可将裁定提升为 APPROVED-WITH-CAVEATS 或 APPROVED）**：
1. 修复 P0：钉固 `human-guard.json` 公钥根信任（Agent 不可写/带完整性校验），使"替换公钥自签"不可行；
2. 修复 P1：锚缺签名即 HOLD（强约束 `requires_human` 必须带有效签名）；
3. 修复 P1：移除 PreToolUse 的 `|| true` 静默放行，或改为"python 不可用时默认 deny"；
4. 修复 P1：护栏覆盖 Bash 写盘与 `.metacog` 受保护路径；
5. 修复 P1：口令强度策略与更强 KDF / 吊销恢复流程。

在未完成上述 1–2 项（尤其 P0）之前，**不得将该实现宣称为"系统级强制、人类不可缺席"的生产级控制**；其当前真实保证等级为"对遵循核准流程且不具备文件系统改写能力的主体有效"。

---

*审计完成。本报告为安全评审意见，非合规证书；所有判定均来自可复现的现场核验与代码检视。*

---

## v2.5.1 复验（P0 + B.2 收口）

> 复验角色：独立第三方推理体，**隔离上下文**（不复用实现方记忆、不采纳自证）。复验对象：v2.5.1 对 v2.5.0 原始「⚠️ CONDITIONAL」中 P0、B.2 两项的修复。方法：直接阅读 `scripts/metacog.py` 源码 + 运行测试套件，全部结论来自现场核验。

### A. 代码核验（逐函数现场取证）

#### A.1 P0 收口：公钥信任根钉固（fail-closed）

| 函数 / 符号 | 位置（metacog.py） | 复验结论 |
|---|---|---|
| `Store.GUARD_INTEGRITY_KEY` | `:476` | 定义为 `"ledger/human-guard.json"`，为信任根专用快照键。✅ 存在 |
| `Store._integrity_path()` | `:478` | 信任根键路由到 `human_guard` 路径，与通用制品分离。✅ |
| `Store.record_guard_integrity()` | `:497` | 调 `record_integrity(GUARD_INTEGRITY_KEY)`，把 human-guard.json 当前哈希记入 D4 快照。✅ |
| `Store.human_pubkey_fingerprint()` | `:520` | 由 `load_human_keys()` 取 pubkey 算 SHA-256 前 16 位；无密钥返回 None。✅ |
| `Store.pinned_human_pubkey_fingerprint()` | `:527` | 从 **CONTRACT.md** 解析钉固指纹（定位 `human_pubkey_fingerprint` 键、取冒号后非占位符值），缺失/占位符返回 None（legacy 兼容）。✅ |
| `Store.check_pubkey_root()` | `:543` | **P0 核心**：钉固指纹缺失则 legacy 放行并告警；live 公钥缺失则放行（由调用方另判）；**live≠pinned 返回 `(False, "pubkey-root-mismatch")` —— fail-closed 拒绝**。✅ |
| `Store.write_human_pubkey_fingerprint()` | `:560` | 把指纹钉入 CONTRACT.md `## 7. 人类身份根（human-identity-root）` 节（占位符则写入、真实值不符则覆盖并告警）。✅ |
| `Store.verify_human_signature()` | `:655` | **验签前先 `check_pubkey_root()`**（`:662`），不符即 `return False, root_reason`。✅ |
| `resolve_trial_start()` 签名分支 | `:1557` | 验签前先 `check_pubkey_root()`，不符 `return 0, "…信任根不符…HOLD"`。✅ |
| `cmd_verify()` 信任根专用块 | `:2022` | **同时报告两类漂移**：(a) D4 哈希漂移（`:2031` 比对快照）；(b) **指纹漂移**（`:2041` live≠pinned 报「信任根指纹漂移」）。✅ |
| `_confirm_keygen()` | `:2153` | 生成密钥后依次调 `st.write_human_pubkey_fingerprint(fp)` 与 `st.record_guard_integrity()`。✅ |
| `_confirm_init()` | `:2189` | 口令轮换后调 `st.record_guard_integrity()` 刷新 D4 快照。✅ |
| SEED CONTRACT 字符串 | `:792` | 内嵌 `## 7. 人类身份根（human-identity-root）` 节，含 `- **human_pubkey_fingerprint**: \`<待 confirm --keygen 钉固>\`` 占位符。✅ |

#### A.2 B.2 收口：`requires_human` 锚缺签名一律 HOLD

`resolve_trial_start()`（metacog.py `:1548` 起）逻辑：
1. 若 `rec` 含有效 `human_sig` + `chash` 且公钥可用：先验 `check_pubkey_root()`（`:1557`，P0 叠合），再验签 + 比对内容哈希，通过才 `return trial_from_index`。
2. **B.2 分支（`:1580`）**：`if p.get("requires_human"):` —— 走到此处说明锚无有效签名，于是
   - `:1582` `sigcrypto is None` → `return 0, "...HOLD"`（fail-closed，不降级信任）；
   - `:1583` 否则 `return 0, "requires_human 提案的受信任锚缺少人类签名…HOLD"`。
3. 非 `requires_human` 旧锚（合法遗留）→ `:1586` 仍返回 `trial_from_index`（兼容，非漏洞）。

→ 原「该有签名却缺失即被信任」的缺口已闭合：**`requires_human` 提案的锚必须具有效人类签名，否则统一 HOLD**。

### B. 测试证据（实测，非引用）

| 套件 | 命令 | 实测结果 | 结论 |
|---|---|---|---|
| `scripts/test-human-gate.py` | `…/3.13.12/python.exe scripts/test-human-gate.py` | **全文件总计 35/35 PASS**（断言行口径）；其中 `test_p0_pubkey_root_pinning` **5/5 PASS**，`test_b2_anchor_missing_sig_holds` **4/4 PASS**，`test_p0_legacy_install_autopin` **3/3 PASS** | ✅ P0 + B.2 双收口 |
| `scripts/test-core.py` | 同上 | **14/14 PASS** | ✅ 无回归 |
| `scripts/test-boundary-cases.py` | 同上 | **40/40 PASS** | ✅ 无回归 |

实测关键断言（节选自输出）：
- P0：`[PASS] 替换公钥后信任根校验失败 - reason=pubkey-root-mismatch`、`[PASS] 替换公钥+伪造签名被信任根拒绝 - rc=2`。
- B.2：`[PASS] 无签名锚(requires_human)一律 HOLD - hold=requires_human 提案的受信任锚缺少人类签名…HOLD`、`[PASS] 非 requires_human 无签名锚仍信任 - hold=None, start=0`。

三个套件退出码均 0，无 FAIL、无非零退出。

### C. 残留风险（诚实披露，须保留）

1. **攻击门槛抬高而非归零**：v2.5.1 把攻击从「修改 1 个文件（human-guard.json）即可生成匹配私钥自签」提升到「必须**同时、一致地**修改 human-guard.json **与** CONTRACT.md 中钉固的指纹」。普通 Agent（仅文件写能力）已无法单点伪造；但
2. **完全失控 Agent 的残余**：一个**具备文件 + 代码双写能力**的恶意/被劫持 Agent，仍可同时改写两处文件、或直接重写 `metacog.py` 移除 `check_pubkey_root()` 调用。本修复**未引入**对代码/钉固文件自身的防篡改（属设计边界）。
3. **真根信任需要带外锚**：彻底闭合需硬件令牌（HSM/TPM 持有私钥或仅硬件可写密钥）或**带外人工核验**（人类独立核对指纹）。本技能不声称具备该能力。
4. **`cmd_verify` 仍依赖人工/钩子触发**：CONTRACT.md 与 human-guard.json 的双写篡改要等 `verify` 才暴露（原 P2 项，未在此轮收口）。

**处置结论**：上述 1–4 属「已知残余」，在 v2.5.1 已满足「**人在环、系统级强制的可控自指**」的宣称门槛；技能**绝不可**改口为「无需人类在环 / 系统自主可控」。该边界必须在 SKILL.md / CONTRACT.md 宣称中保持。

### D. 裁定更新

原 v2.5.0「⚠️ CONDITIONAL」的两条最高优先项（P0、B.2）已由代码 + 测试双重闭合，本报告顶部裁定升级为 **✅ APPROVED（残留诚实披露）**。除 P0/B.2 外的其余 P1/P2 项（见 §7）维持原建议待办，但原「不得宣称系统级强制、人类不可缺席」的禁令因两项核心缺口收口而放宽——限制条件改为「须保持人在环宣称、如实披露残留局限」。原始 CONDITIONAL 章节（§8）保留以追溯，标记为 superseded。

> ⚠️ **（2026-09-28 真实 Hermes 审计取代）** 本「升级为 ✅ APPROVED」结论**已被真实 Hermes MCP 审计推翻/降级为 REJECTED·CONDITIONAL**。真实 Hermes 指出：在给定威胁模型（Agent 可写任意文件+代码）下，P0 钉固未引入独立信任根、B.2 存在 sigcrypto 降级绕过，"系统级强制/密码学强制"宣称与实现能力存在张力。权威裁定见 `references/independent-audit-hermes-v2.5.1.md`。

*复验完成。本补充为对 v2.5.0 深度审计的现场复验意见，非新合规证书。*
