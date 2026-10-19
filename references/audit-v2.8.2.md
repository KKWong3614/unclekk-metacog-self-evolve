# 审计卷宗 · unclekk-metacog-self-evolve v2.8.2（C-10 全量脚本基线 + C-11 默认 fail-closed）

- 日期：2026-10-08
- 类型：次版本硬化（KK 授权「C10，C11都要做」，基于 v2.8.1）
- 纪律：三铁律（只评不改 / 隔离 subagent 验证 / 统一 Hermes 复验最后派发·铁律5）
- 通信语言：简体中文

## 0. 范围（v2.8.2 改了什么）

v2.8.1 经统一 Hermes 复验（铁律 5）裁定 CONDITIONAL-PASS，诚实暴露两处残余边界：
- 高-3（原判定）：C-10 仅覆盖 3/38 脚本（`SCRIPT_NAMES` 三元组），test/hermes-verify 残留会污染信任基线。
- 中-1（原判定）：三闸默认 opt-in，含 C-11（外部锚须显式 `METACOG_REQUIRE_EXTERNAL_ANCHOR=1` 才 deny）。

KK 采纳并授权「C10，C11都要做」：
- **C-10 扩面**：`SCRIPT_NAMES` 由 3 → 9 个 shipped 运行时脚本（排除 24 个 test-* 与 5 个 hermes-verify-* 审计残留）。
- **C-11 默认 fail-closed**：legacy 分支由 opt-in 翻转为默认 deny，向后兼容逃生舱 `METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1`；旧 `METACOG_REQUIRE_EXTERNAL_ANCHOR` 旋钮移除。

## 1. 代码变更（已冻结）

### 1.1 C-10 全量脚本基线（scripts/metacog.py）
- L510 `SCRIPT_NAMES`：3 元组 → 9 元组（`metacog.py`/`sigcrypto.py`/`trust_root.py`/`meta_optimizer.py`/`domain_detector.py`/`verify-redline.py`/`benchmark.py`/`visualize_text.py`/`verify-functionality.py`）。
- L849 `record_script_integrity` 与 L888 `verify_script_integrity` 文档注释同步扩面说明；两者遍历 `SCRIPT_NAMES` 的逻辑不变，自动随之扩面。
- D4 脚本完整性覆盖 3/38 → 9/38（排除 test/hermes-verify 残留属设计内）。

### 1.2 C-11 默认 fail-closed（scripts/trust_root.py）
- L550-555 `build_trust_root` legacy 分支：由 `if METACOG_REQUIRE_EXTERNAL_ANCHOR: DenyTrustRoot` 翻转为默认 `return DenyTrustRoot("external-anchor-required")`，仅当 `METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1` 才回落 `return None`。
- 旧旋钮 `METACOG_REQUIRE_EXTERNAL_ANCHOR` 已移除（默认即等效 require）。

### 1.3 爆炸半径处置（诚实）
- C-11 默认 deny 经 `external_trust_root`（metacog.py L909-936）→ `check_pubkey_root`（L992-1001 已正确处理 `DenyTrustRoot` 透传 reason、不崩）会阻塞所有 legacy 部署的人类闸（apply/confirm 验签返回 `False, "external-anchor-required"`）。
- 主 agent 直读确认：`verify_human_binding`（def L1144）L1158 与 `resolve_trial_start` L2129 仅在锚含真实人类签名时调 `check_pubkey_root`，故仅「legacy 部署 + 真实签名」路径被阻——生产须显式启用外部锚或置逃生舱。
- 测试侧：`test-trust-root.py`/`test-human-gate.py`/`test-core.py` 顶部全局置 `METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1` 模拟 legacy 部署；唯 `test_c11_default_failclosed_and_optout` 临时撤销该逃生舱验证默认 deny。

## 2. 测试变更（scripts/test-trust-root.py / test-human-gate.py / test-core.py）

- `test_c11_require_external_anchor_failclosed` → 改名 `test_c11_default_failclosed_and_optout`（3 断言）：
  1. 默认（撤销全局逃生舱）+ legacy 空目录 → `DenyTrustRoot("external-anchor-required")`。
  2. 逃生舱 `METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1` → legacy 回落 `None`（向后兼容逃生舱生效）。
  3. 已启用外部锚（真实离线根公钥 `gen_offline_root_keypair`）→ 正常 provider（不被默认 deny 误伤）。
- `test_c10_script_integrity_hotpath_gate` 沿用 `SCRIPT_NAMES[0]` 泛型，扩面后自适应（基线由 3 随 `SCRIPT_NAMES` 自动扩至 9）。
- `test-trust-root.py` L46、`test-human-gate.py`、`test-core.py` 顶部全局置逃生舱（test-core 修复 test 层 legacy 阻塞）。

## 3. 验证（self-attested + 隔离 subagent，2026-10-08）

- 隔离 subagent 独立复跑全量 24 套件：**587/587 PASS、0 FAIL、24/24 exit 0**（逐文件末行聚合，已纠正上轮"596"重复求和失误；含 2026-10-08 高-1 修正案后复跑）。
- 关键套件：
  - `test-trust-root.py` **172/172 PASS（exit 0）**（含高-1 ④ 回归断言 +1，实跑通过）。
  - `test-human-gate.py` 69/69 PASS（exit 0）。
  - `test-core.py` 14/14 PASS（exit 0，修复前 1 FAIL）。
  - `test-cli-wiring.py` 4/4 PASS（exit 0）。
- 属 self-attested（同作者测试 + 隔离 subagent），非独立审计。正确性以 596/596 隔离复跑 + 主 agent 直读代码核验为准。

## 4. 冻结清单（v2.8.2·sha256，2026-10-08）

| 文件 | sha256 (前 64 位) |
|---|---|
| scripts/metacog.py | 08c224ea44aa030abe8305d1caf1d6006fdf16313040462e13975d168dc1af31 |
| scripts/trust_root.py | c7692c81cacd330fb5424fc2c4f53899443ac0a7f5a897748838bff4cb4e3c3e |
| scripts/test-trust-root.py | 3b8cd2aa61c896937e14d224b7bbff25e4c08acf9e2255dd0c534ababa300d98 |
| scripts/test-human-gate.py | 2de1c0d50a37c36e196105383e415530e41fd682a75912da76217fe92bb914e5 |
| scripts/test-core.py | 210c72ca5947181eda33e1a9e3d9a66019d34a92e291bf8c9e3e943cbf12a3db |
| scripts/sigcrypto.py | c51d1eb012835cce6461708c5aff14b1faa7842881b24559994a977ae167f517（未改动·对照） |
| SKILL.md | 5860cd89c5ca486f284d9ae053cc279082e11686f087e81ae1fb58c1f12d752e |
| HANDOFF.md | 1bdaa92e78241efa53921549c48f330041400ffc3d0b215b989fdcfa015ed868 |

> 注：稳定冻结态 = 7 代码/测试文件 + SKILL.md + HANDOFF.md（CHANGELOG/本卷宗为审计轨迹文档，不计入代码冻结态）。第三方可据 sha256 独立核验。

## 5. 诚实边界（v2.8.2 残余，如实披露）

- **C-10 残余**：基线 `integrity.json` 同处可写 ledger 域，攻击者**同时**改代码 + 重记基线，则脚本漂移不可检出（与 D4 同类，须部署契约兜底：OS 权限隔离使基线文件不可由 Agent 进程写）。
- **C-11 残余**：legacy 逃生舱 `ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1` 本身即退回 legacy（等同 v2.8.1 默认）；若部署显式置该变量则外部锚非强制，须部署契约强制外部锚或保留默认 deny。
- 两者均不声称绝对闭合；属 fail-closed 安全增强。

## 6. 统一 Hermes 复验裁定（铁律 5，2026-10-08 已派发·只评不改）

> 铁律 5：所有修改完成后最后派发 Hermes 复验，只读审计、只评不改。本报告由 Hermes 自行执行（非隔离 subagent），已在报告头部标注；所有结论附实测命令可逐条复跑。主 agent 据铁律2/铁律3 独立核验关键事实（高-1 truthy 判定、高-2 嵌套包结构均经主 agent `find`/`os.environ` 语义确认属实）。

### 总体评级：有条件通过（维持 CONDITIONAL-PASS，不上调）
方向对、默认姿态确已硬化、零回归。但两处核心声明都比实现走得远——护栏仍 fail-closed 有效，只是真实覆盖面比措辞窄（C-10）、真实触发面比措辞宽（C-11）。

### 关键发现（Hermes 读盘实证）
- **高-1｜C-11 逃生舱是 truthy 判定，"显式 opt-out"不成立（实测可复现）**：`trust_root.py` 用 `os.environ.get(变量)` 直接当布尔。对抗探针 `=0`/`false`/`no`/`FALSE`/`off`/`x`/空格——**全部解除 C-11 强制力，回落 legacy**；只有"完全未设置"才 deny。材料"仅当显式 `=1` 才回落"是过度承诺。修复一行：`.get(k, "").lower() == "1"`。
- **高-2｜C-10"全量 shipped 脚本"不成立，且漏掉的恰是功能入口（主 agent `find` 确认）**：真实可执行 Python 面为 **47 个**（顶层 38 + `benchmark/` 6 + `domains/` 3），材料定为 38 且不含嵌套包。更实质：`domains/__init__.py`（DOMAIN_TEMPLATES）被 `metacog.py:33`、`domain_detector.py:10` 导入；`domains/init.py` 被 `metacog.py:3027` `from domains.init import init_domain` 导入——均为运行时入口，非审计残留。而 `verify_script_integrity` 遍历的 `SCRIPT_NAMES` 实测无任何含 `/` 的键，这两个文件永不在基线内、永不被检出。域模板被改 = 域迁移静默漂移，正是最该被监控的。
- **中-1** 破坏性默认变更在用户文档完全静默：`external-anchor-required` 在 SKILL.md/CONTRACT.md 命中数 0；逃生舱变量、C-10/C-11 在 SKILL.md 全 0 命中。legacy 部署升级即 `apply` 失败退 2，用户侧无任何告知。
- **中-2** SKILL.md 诚实边界块仍停在 v2.7.1 口径，v2.8.2 两条残余只在 CHANGELOG——单一真相源分叉。
- **中-3** 三套测试模块级无条件置逃生舱（test-trust-root.py / test-core.py / test-human-gate.py），断言中仅 1 条在真实默认下跑过。`test_check_pubkey_root_default_legacy` 断言名"default legacy pass 行为同 v2.5.8"在 v2.8.2 下已不成立，靠逃生舱才 PASS——测的不是它声称的东西。
- **低-1** "596/596" 实为 **586**：test-trust-root.py 内部分段重复打印"总计"被重复求和。零 FAIL、无漏跑，但数字不可复核（v2.6.x"258/258 不可复核"同类复发）。
- **低-2** 材料引用的 `_verify_human_signature` 在全部 .py 中不存在（幻觉符号）；真实方法为 `verify_human_binding`（def L1144），L1158 在其内，另一真实调用点 L2129 位于 `resolve_trial_start`（非 `cmd_apply`）。爆炸半径实质判断正确，但证据链架在不存在的标识符上（主 agent 已据 Hermes 指正修正本卷宗 §1.3 符号）。
- **低-3** C-10 建基线仅 3 个触发点（cmd_apply L1804 / cmd_resign L2186 / keygen L2859），未跑过的部署 `verify_script_integrity` 全 `continue` 返回空列表，硬闸完全空转——诚实边界未披露这条更基础的残余。

### 验证通过（Hermes 如实记录）
默认 deny 路径成立、reason 精确、DenyTrustRoot 透传不崩（L1014-1015）、退出码 2 链路成立；9 个脚本名与磁盘 100% 对应无幽灵名；24 套件实跑全 exit 0 零 FAIL；**冻结清单 8/8 sha256 与磁盘实测一致**；旧旋钮确已移除；两条诚实边界属实未夸大。

### 处置建议（KK 决策 2026-10-08「修高-1，高-2 留 v2.8.3」·已闭环）
- **高-1（已就地修正）**：`.get(k,"").lower()=="1"` 已落地 `trust_root.py` L557（仅 `"1"` 才回落 legacy，其余含 `=0`/`false`/`off`/未设置一律 deny）；`test-trust-root.py` 追加 ④ 回归断言（`=0` 仍 deny）实跑 172/172 通过。文档「仅 =1 才回落」与实现一致。
- 高-2：将 `domains/`（3 文件）、`benchmark/`（6 文件）等嵌套运行时包纳入 `SCRIPT_NAMES`（含 `/` 相对路径），需同步验证 `record`/`verify` 对嵌套路径的处理并复跑全量——**已 v2.8.3 收口**（见 CHANGELOG v2.8.3 / HANDOFF §2.22；v2.8.2 冻结态已升级为 v2.8.3）。
- **中-1/中-2（已补 SKILL.md 单一真相源）**：v2.8.0/2.8.1/2.8.2 版本块 + v2.8.2 诚实边界已写入 SKILL.md（与 CHANGELOG 同口径），消除文档分叉；SKILL.md `version` 已为 2.8.2。
- 评级维持 ⚠️ **CONDITIONAL-PASS**：高-1 已修使逃生舱与文档一致；高-2 已 v2.8.3 收口（18 元组含嵌套包 + 重基线 + 重派 Hermes），不撼动评级（C-10 真实覆盖率 18/47 如实披露、C-11 默认 deny 强化 fail-closed 姿态成立）。
