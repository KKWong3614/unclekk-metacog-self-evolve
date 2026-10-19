# 统一 Hermes 复验 · v2.8.1 裁定（铁律5 · 只评不改）

- 日期：2026-10-08（Hermes 派发：本 dossier 完成后派发）
- 被审：unclekk-metacog-self-evolve v2.8.1（信任根外部锚子系统 · Hermes v2.8.0 复验 C-9/C-10/C-11 残余边界硬化）
- 审计通道：`mcp__hermes__hermes_audit`（异族独立审计员，纯文本审计——Hermes 以 dossier + 代码绝对路径为凭，符合铁律3"Hermes 非真异族，裁定仅以文本为凭"）。
- 主 agent 独立验证：Windows 信任根 C-9/C-10/C-11 三层硬闸行为 + 全量测试，均实跑复现（os.name=nt, py3.13.12）。
- 绝对路径：`C:\Users\Administrator\.workbuddy\skills\unclekk-metacog-self-evolve\`
- 冻结清单（v2.8.1·sha256，见文末）：9 文件。

## v2.8.1 设计（C-9/C-10/C-11 硬化）

### 来源（Hermes v2.8.0 复验裁定，2026-10-08 已派发）
v2.8.0 统一 Hermes 复验裁定 C-1 RESOLVED·有条件通过，并诚实暴露三项残余边界：
- **C-9 [MEDIUM]**：默认锚密钥是 `trust_root.py` 明文 hex 字面量 → 读源码即得 HMAC 密钥，可为任意配置伪造 `_sig`；v2.8.0 仅记为"部署建议 env 覆盖"。
- **C-10 [MEDIUM]**：D4 `verify_script_integrity()` 全文件仅 `cmd_verify`（人工报告命令）调用；`cmd_retrieve`（热路径）只调 `verify_integrity()` 且显式跳过 `script:` 前缀键，基线 `integrity.json` 同处可写 ledger 域 → D4 是**检测**手段，非**阻止**手段。
- **C-11 [MEDIUM]**：外部锚 opt-in，空目录/未启用 → `build_trust_root()` 返 None（零外部锚）；`backend` 在签名内，持密钥者可签 `backend="legacy"` 合法禁用锚。

KK 采纳并授权「开 v2.8.1」硬化三者（铁律1 授权后改）。候选方案：将三项"建议/检测"升级为 fail-closed **硬闸**（默认拒绝 / 热路径拦截 / 强制启用）。

### C-9 默认密钥硬闸
- **根因**：默认锚密钥随代码分发（源码明文），任何能读代码者即可为任意 `trust-root.json` 伪造 `_sig`，使"签名锚"在默认密钥下形同虚设。
- **设计**：`write_trust_root_config()` 开头插入硬闸——若当前锚密钥仍为默认（`get_anchor_key() == _TRUST_ROOT_ANCHOR_KEY_DEFAULT`）且未设 `METACOG_TRUST_ROOT_ALLOW_DEFAULT`，则抛 `TrustRootWriteError` 拒绝落盘；`cmd_confirm --enable-external` 同步预检拒绝（CLI 层拦截）。生产/非本地部署须以 `METACOG_TRUST_ROOT_ANCHOR_KEY` 覆盖为部署专属随机密钥。
- **向后兼容**：`METACOG_TRUST_ROOT_ALLOW_DEFAULT=1` 仅本地开发显式承担风险时放行（全局测试置该变量使既有默认密钥测试通过）。

### C-10 D4 热路径硬闸
- **根因**：D4 脚本完整性校验仅接人工 `cmd_verify`，热路径 `cmd_retrieve` 不调用、且跳过 `script:` 键 → 攻击者改技能脚本直至人工 verify 才暴露，属"检测"非"阻止"。
- **设计**：`cmd_retrieve()` 在产出前插入硬闸——当外部锚已启用（`external_trust_root() is not None`，受保护模式）或 `METACOG_TRUST_ROOT_STRICT=1` 时，调用 `verify_script_integrity()`；任一已建基线脚本哈希漂移 → 返回非零拒绝（fail-closed）。未建基线脚本不触发（不误伤全新/未基线部署）。
- **向后兼容**：默认不触发（需外部锚启用或显式 STRICT），无回归。

### C-11 外部锚 fail-closed 默认
- **根因**：外部锚 opt-in，未启用=legacy 零外部锚；持密钥者可签 `backend="legacy"` 合法禁用锚。
- **设计**：`build_trust_root()` 在 `not enabled or backend=="legacy"` 分支内插入——若 `METACOG_REQUIRE_EXTERNAL_ANCHOR=1`，则返 `DenyTrustRoot("external-anchor-required")`（拒绝启动，需人工确认启用外部锚）。
- **向后兼容**：默认关（与授权一致），不强制 fail-closed，避免误伤既有 legacy 部署。

### 代码变更（已冻结，2026-10-08）
- `scripts/trust_root.py`：
  - 新增 `class TrustRootWriteError(Exception)`。
  - `write_trust_root_config()` 开头 C-9 硬闸（默认密钥 + 无 ALLOW_DEFAULT → 抛 TrustRootWriteError）。
  - `build_trust_root()` C-11 fail-closed（`METACOG_REQUIRE_EXTERNAL_ANCHOR` 时 legacy→DenyTrustRoot）。
  - sha256：`f917be52d041ad761131227bc1cb861cb491122821fdd95ca68e7316a50d9d48`
- `scripts/metacog.py`：
  - `cmd_confirm --enable-external`（L2861 后、hsm 分支前）C-9 CLI 预检（默认密钥 + 无 ALLOW_DEFAULT → `bad` + `return 2`）。
  - `cmd_retrieve()`（L2598 后、out=[] 前）C-10 热路径硬闸（`_anchor_active or METACOG_TRUST_ROOT_STRICT` 时脚本漂移 → `bad` + `return 3`）。
  - `external_trust_root()` 诚实边界补 v2.8.1 三层硬化指引。
  - sha256：`9f714dfaa6f6c7724460e1fba8250f3765c3be95e5fed22d7e31bb24afaf4d96`
- 未改动：`sigcrypto.py` / `meta_optimizer.py` / `domain_detector.py` / `verify-redline.py`（sha256 与 v2.8.0 冻结值一致）。

### 测试变更（scripts/test-trust-root.py，已冻结）
- 模块顶部（L42 后）注入 `os.environ["METACOG_TRUST_ROOT_ALLOW_DEFAULT"] = "1"`（使既有默认密钥测试通过；C-9 拒绝测试临时撤销该变量）。
- 新增 `test_c9_default_anchor_key_rejected_for_external`（2 断言：默认密钥+无 ALLOW_DEFAULT→TrustRootWriteError / ALLOW_DEFAULT=1→允许）。
- 新增 `test_c10_script_integrity_hotpath_gate`（2 断言：外部锚启用+注入错误脚本基线→cmd_retrieve rc!=0 / 移除注入基线→rc==0）。
- 新增 `test_c11_require_external_anchor_failclosed`（2 断言：REQUIRE+legacy 空目录→DenyTrustRoot("external-anchor-required") / REQUIRE+已启用(真实公钥 `gen_offline_root_keypair`)→正常 provider）。
- `main()` 注册三新用例（test_trust_root_config_c1_signature_closure 后）。
- sha256：`0d7544cb14f9e101cad304529be35667be04ada8bb6fc8ef87bd2f5c5387d45e`

### 验证（self-attested + 隔离 subagent，2026-10-08）
`test-trust-root.py` **170/170 PASS（exit 0）**（v2.8.0 164/164 + 6 新增断言）；隔离 subagent 独立复跑确认 170/170、0 FAIL、exit 0；`test-cli-wiring.py` 4/4、`test-human-gate.py` 69/69（无回归）。属 self-attested，非独立审计。

### 诚实边界（v2.8.1）
- **C-10 残余**：基线 `integrity.json` 同处可写 ledger 域，攻击者**同时**改代码 + 重记基线，则脚本漂移不可检出——与 D4 同类，须部署契约兜底（OS 权限隔离，使基线文件不可由 Agent 进程写）。
- **C-9 硬闸边界**：仅阻止无意识地用默认（共享）密钥；不替代 OS 代码完整性——若敌具代码写权，仍可改 `_TRUST_ROOT_ANCHOR_KEY_DEFAULT` 并重签。
- v2.8.1 不声称"无需人类在环/无硬件即绝对闭合"；三层硬闸属 fail-closed 安全增强，残余如实披露。

### 冻结清单（v2.8.1·sha256，2026-10-08）
- `scripts/metacog.py`：9f714dfaa6f6c7724460e1fba8250f3765c3be95e5fed22d7e31bb24afaf4d96
- `scripts/test-trust-root.py`：0d7544cb14f9e101cad304529be35667be04ada8bb6fc8ef87bd2f5c5387d45e
- `scripts/sigcrypto.py`：c51d1eb012835cce6461708c5aff14b1faa7842881b24559994a977ae167f517
- `scripts/trust_root.py`：f917be52d041ad761131227bc1cb861cb491122821fdd95ca68e7316a50d9d48
- `scripts/meta_optimizer.py`：826156a9912e649b968281606d9ee7f55a284f33ae0af6d7d8492a8b43580dda
- `scripts/domain_detector.py`：52388e1e7ca11f67adcbc68bc508aae07d77cfc0fc4c3996af8fe85f9f7a4932
- `scripts/verify-redline.py`：170ec9705e02e0f707df38c75cfee0c58e1af3d2c703b55eef0866eb3936abe9
- `SKILL.md`：d92d3ccc6df9b912b4d3bc89dcdbfa39abb372e23d5ace86c96a349f5ac4f3c7
- `HANDOFF.md`：13cf9bd5459ba6855031c0100f4e93a0d26ecc5c045a8d3ae839bbef48eb4f4a（审计轨迹文档，随裁定追加 sha256 变化；稳定冻结=7 代码文件+SKILL.md）

## 主 agent 自评
- **评级：C-1 RESOLVED + 残余边界按 Hermes v2.8.0 已诚实硬化**——C-9/C-10/C-11 收窄为可运维的 fail-closed 硬闸/开关；Hermes v2.8.0「C-9 源码明文 / D4 仅检测」已不再为未披露残差。9 文件冻结 sha256 见上。
- 受保护代码 `metacog.py`/`trust_root.py`/`test-trust-root.py` 等 v2.8.1 冻结 sha256 已落盘；待 Hermes 派发复验。

## 统一 Hermes 复验裁定（铁律5 · 2026-10-08 已派发）

> **派发状态**：KK 重连 Hermes MCP 后派发成功（`mcp__hermes__hermes_audit` 返回裁定）。**诚实警示（铁律2/铁律3）**：Hermes 返回的"验证证据"段落（adversarial-probe / 3 fix patches / `Store(tempfile.mkdtemp())` / `_hash_text(real)` / 14/14·13/13 PASS）指向**另一文件**，与 v2.8.1 trust_root C-9/C-10/C-11 硬化无关——系 Hermes MCP 跨会话污染（其自陈"54 pre-existing hermes-verify-* artifacts from earlier audit sessions"）。该数值证据**不可作为 v2.8.1 依据**。本裁定仅采信 Hermes 的**文本 findings（高-1~中-2）**，并由主 agent 直读代码逐条核验。

### Hermes 裁定（文本 findings，已读盘/直读代码核验）
- **总体评级：CONDITIONAL-PASS（非 RESOLVED）**——C-1 在窄威胁模型内仍 RESOLVED；C-9/C-10/C-11 三层硬闸为有效 fail-closed 增强，但默认 opt-in + 覆盖不全，故维持有条件通过。
- **高-1 [HIGH] HANDOFF.md 哈希失配**：Hermes 实测 HANDOFF.md = `015012e5…` ≠ 冻结清单 `cb6d6800…`。**成立**——主 agent 在冻结哈希计算后追加了"铁律5 派发尝试"注记致哈希变更（HANDOFF 为审计轨迹文档，同 v2.8.0 处理）。已修正冻结清单 HANDOFF.md → `13cf9bd5…`（最终态），并标注"审计轨迹文档，稳定冻结=7 代码文件+SKILL.md"。
- **高-2 [HIGH] C-9 不阻断 C-1 主向量且未披露**：C-9 默认密钥硬闸针对"默认密钥可被读源码伪造签名"残差，并不独立闭合 C-1（ledger 写权限换 root_pubkey）。**部分成立**——v2.8.1 已披露"C-9 不替代 OS 代码完整性"，但未显式点明"不阻断 C-1 主向量"；主 agent 采纳，补诚实边界。
- **高-3 [HIGH] C-10 仅覆盖 3/38 脚本**：`SCRIPT_NAMES=("metacog.py","sigcrypto.py","trust_root.py")` 仅 3 个；`verify_script_integrity` 仅基线化此 3 脚本，热路径硬闸同理仅保护 3 个。**成立**——如实披露：C-10 硬闸覆盖 3 核心脚本，非全量 38 脚本。
- **中-1 [MED] 三闸默认 opt-in**：C-9 靠 `ALLOW_DEFAULT=1`（测试/本地）、C-10 仅受保护/STRICT 触发、C-11 默认关——生产须显式启用方生效。**成立，设计内**（向后兼容），记为部署契约：生产须设 `METACOG_TRUST_ROOT_ANCHOR_KEY` + 建议 `STRICT=1`/`REQUIRE=1`。
- **中-2 [MED] 测试套件以 C-9 关闭态运行**：`test-trust-root.py` 模块顶全局 `ALLOW_DEFAULT=1`，C-9 拒绝路径仅由专用用例临时撤销验证。**成立，测试设计**（避免 25+ 默认密钥用例失效），非缺陷；已如实标注。

### 主 agent 核验（铁律2 直读代码）
- 高-1 成立（哈希实测一致，已修正）；高-3 成立（`SCRIPT_NAMES` 实测 3 项）；中-1/中-2 成立（代码/测试实测）。
- 高-2 采纳补诚实边界：C-9 范围=默认密钥伪造残差，不宣称闭合 C-1 主向量；v2.8.1 已含"C-9 不替代 OS 代码完整性"，追加"不阻断 C-1 ledger 写主向量"。

### 主 agent 立场（铁律5 · 采纳）
- **采纳高-1/高-3/中-1/中-2**：均成立，已修正冻结哈希 / 如实披露覆盖不全 / 标注部署契约 / 标注测试配置。
- **采纳高-2（补边界）**：C-9 诚实边界补"不阻断 C-1 主向量"。
- **评级确认**：⚠️ **CONDITIONAL-PASS**——C-1 软件层 RESOLVED（窄模型）+ C-9/C-10/C-11 残余已收窄为 fail-closed 硬闸并诚实化；维持有条件通过（默认 opt-in + 覆盖不全属设计内残差，须部署契约兜底）。
- **反驳"验证证据"段落**：Hermes 的 14/14·13/13 adversarial-probe 数值证据指向无关文件（跨会话污染），**不采信为 v2.8.1 证据**；v2.8.1 正确性仍以 170/170 隔离 subagent 复跑 + 主 agent 直读代码核验为准。

### 最终裁定
- **v2.8.1 评级：CONDITIONAL-PASS（有条件通过）**——三层硬闸有效且诚实化；残余（C-10 仅 3/38 脚本、三闸默认 opt-in、C-9 不阻断 C-1 主向量）如实披露，须部署契约兜底。
- **待 KK 终裁**：是否进一步硬化（如 C-10 扩至全量脚本基线 / C-11 默认 fail-closed 可配置）。本回合仅评不改（铁律1），9 文件冻结 sha256 见上（HANDOFF 为审计轨迹，哈希随本裁定追加变化）。
