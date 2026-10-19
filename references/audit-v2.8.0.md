# 统一 Hermes 复验 · v2.8.0 裁定（铁律5 · 只评不改）

- 日期：2026-10-08（Hermes 派发：待 KK 重连 Hermes MCP 后派发）
- 被审：unclekk-metacog-self-evolve v2.8.0（信任根外部锚子系统 · C-1 架构债根治）
- 审计通道：`mcp__hermes__hermes_audit`（异族独立审计员，纯文本审计——Hermes 以 dossier + 代码绝对路径为凭，符合铁律3"Hermes 非真异族，裁定仅以文本为凭"）。
- 主 agent 独立验证：Windows 信任根配置签名/校验行为 + 全量测试，均实跑复现（os.name=nt, py3.13.12）。

## v2.8.0 设计（C-1 根治）

### C-1 根因（历史）
信任根配置 `trust-root.json`（含 `root_pubkey`）位于 Agent 可写域 `ledger/`；"哪把 root_pubkey 受信"由同可写域配置决定 → 循环论证。攻击者凭 ledger 写权限即可换 `root_pubkey` + 自签证明/令牌自证。该债连续 10+ 版 OPEN，Hermes v2.7.8 复验列为【高】有效建议："应单开条目给 owner/目标版本/候选方案（外部 ACL 只读锚定 / 代码签名 trust-root / 独立只读介质）"。KK 授权「开 v2.8.0」根治。

### 候选方案选定：代码签名 trust-root（内嵌锚密钥）
- 锚密钥位于**代码**（非可写 ledger），对 `trust-root.json` 做 HMAC-SHA256 签名、`load` 强制校验。直接闭合"受信根由可写配置决定"的循环论证。
- 优于"外部 ACL 只读锚定"：Windows 只读位可由同用户 chmod 清除（v2.7.8 NEW-M 已证）；优于"独立只读介质/TPM"：需硬件，out-of-scope。

### 代码变更（`scripts/trust_root.py`，已冻结）
- 新增模块级 `_TRUST_ROOT_ANCHOR_KEY_DEFAULT`（内嵌 32 字节锚密钥；环境变量 `METACOG_TRUST_ROOT_ANCHOR_KEY` 可覆盖为部署专属锚）+ `get_anchor_key()` / `sign_trust_root_config()` / `verify_trust_root_config_sig()`。
- `write_trust_root_config()`：落盘前对配置载荷（不含 `_sig`）签名，写入 `_sig`。
- `TrustRootConfig.load()`：加载时强制校验 `_sig`；缺失 / 类型错 / 不符 → `corrupt=True, enabled=True` → `build_trust_root` 返 `DenyTrustRoot("external-anchor-corrupt")` → fail-closed。
- 诚实边界更新：`trust_root.py` 模块文档 + `metacog.py` `external_trust_root()` 由"C-1 未真正闭合"更新为"v2.8.0 软件层闭合，残余=代码完整性/硬件 TPM（out-of-scope）"。

### 测试变更（`scripts/test-trust-root.py`，已冻结）
- 新增 `test_trust_root_config_c1_signature_closure`（4 断言）：合法签名加载 / 换 root_pubkey 保留旧签名 fail-closed / 无签名 fail-closed（升级迁移）/ 签名篡改 fail-closed。
- `_enable_external` 测试助手统一签名（覆盖 ~25 调用点）。
- `test_external_anchor_tampered_hash`、`test_load_enabled_string_false` 适配签名闸；`test_deny_reason_passthrough` 改写签名配置以触达 build 层 unknown-backend 判定。

### 验证（隔离 subagent，managed python 3.13.12 / Windows）
`test-trust-root.py` **164/164 PASS（exit 0）**（v2.7.8 160/160 + 4 新增断言）；隔离 subagent 独立复跑确认 164/164、0 FAIL、exit 0。含 C-1 核心用例：换 `root_pubkey` 保留旧签名 → 签名不符 → fail-closed（攻击被阻断）。

### 诚实边界（v2.8.0）
- **C-1 软件层已闭合**：信任根配置经代码层锚密钥签名认证，"哪把 root_pubkey 受信"不再由可写 ledger 单方面决定。
- **残余边界（如实披露，非缺陷）**：① 攻击者同时具**代码写权限**（可改 `_TRUST_ROOT_ANCHOR_KEY_DEFAULT`）→ 签名锚失效，属代码完整性边界，超出软件层；② 彻底隔离仍须 **TPM / 独立只读介质**（out-of-scope，部署契约兜底）。v2.8.0 不声称"无需人类在环/无硬件即绝对闭合"。

### 冻结清单（v2.8.0·sha256，2026-10-08）
- `scripts/metacog.py`：9137aa41d7ea669f1a880e8c5c94e93b382f41b0f3b9e3b5b5466ea8323ee88a
- `scripts/test-trust-root.py`：ea1794aa794e6073397690453fe09aac8ffa4d9541927ca73e7fbbef78cbbad1
- `scripts/sigcrypto.py`：c51d1eb012835cce6461708c5aff14b1faa7842881b24559994a977ae167f517
- `scripts/trust_root.py`：6775d0ef4e4069182c896781824cca952e330418d27290c441e175831ceef636
- `scripts/meta_optimizer.py`：826156a9912e649b968281606d9ee7f55a284f33ae0af6d7d8492a8b43580dda
- `scripts/domain_detector.py`：52388e1e7ca11f67adcbc68bc508aae07d77cfc0fc4c3996af8fe85f9f7a4932
- `scripts/verify-redline.py`：170ec9705e02e0f707df38c75cfee0c58e1af3d2c703b55eef0866eb3936abe9
- `SKILL.md`：cd91182c3fd6e32605e64f914c50ca2141f0d809afa6a0b9de8ef65900879b82
- `HANDOFF.md`：b1a07d79dee265071ea34a39da63a745e8b43d99d22c2c1c522476bc9c18b4e2（v2.8.0 发布冻结值；2026-10-08 统一 Hermes 复验裁定后本 dossier 铁律5 节 + HANDOFF §2.19/§4 同步追加，sha256 已变——属审计轨迹追加，**7 代码文件 + SKILL.md 冻结值不变**）

## 主 agent 自评
- **评级：C-1 软件层 OPEN 已解除**，评级由连续 11 轮 ⚠️ CONDITIONAL 上调。C-1 经签名锚在软件层闭合；残余边界（代码完整性/硬件 TPM）如实披露，不归咎 v2.8.0。
- 受保护代码 `metacog.py`/`trust_root.py`/`test-trust-root.py` 等 v2.8.0 冻结 sha256 仍有效（审计对象零修改，待 Hermes 派发）。

## 统一 Hermes 复验裁定（铁律5 · 2026-10-08 已派发）

### Hermes 裁定原文（要点，已读盘实证，未改任何产物）
- **总体结论**：C-1 在其自述威胁模型内**确实关闭**；但该模型把"代码不可写"当成边界，而本系统里 Agent 天然具代码读/写权 → 边界不实；且 D4 兜底**不在热路径**执行。
- **Hermes 自测 28/28 PASS**（脚本 `C:\Users\Administrator\WorkBuddy\2026-09-30-08-20-28\adv_c1_test.py`，直读真实磁盘产物）：SHA256 = `6775d0ef…f636` 与冻结值一致；篡改 root_pubkey+保留旧 _sig → corrupt → DenyTrustRoot；签名覆盖除 _sig 外全字段；畸形/null/截断/嵌套/哨兵删 → 全部 corrupt；改代码密钥+重签 → 配置干净加载（C-1 全开）。
- **C-9 [MEDIUM]**：默认锚密钥是 `trust_root.py` 明文 hex 字面量 → **读**源码即得 HMAC 密钥，可为任意配置伪造 _sig；威胁模型只圈 ledger 写权，从未圈代码读权。
- **C-10 [MEDIUM]**：D4 `verify_script_integrity()` 全文件仅 `cmd_verify`（人工报告命令）调用；`cmd_retrieve`（热路径）只调 `verify_integrity()` 且显式跳过 `script:` 前缀键、自陈"非阻塞告警"；基线 `integrity.json` 同在可写 ledger 域 → D4 是**检测**手段，非**阻止**手段；"改密钥+重记基线"直到人工 verify 才暴露。
- **C-11 [MEDIUM]**：外部锚 opt-in，空目录/未启用 → `build_trust_root()` 返 None（零外部锚）；`backend` 在签名内，持密钥者可签 `backend="legacy"` 合法禁用锚。
- **C-12 [LOW-MEDIUM]**：`METACOG_TRUST_ROOT_ANCHOR_KEY` 为进程级，能设该 env 的进程可为**所有**部署伪造签名（默认键下"各部署不共享密钥"才成立）。
- **未采信项**：Hermes 因 `test-trust-root.py` 导入含 126 处 RSA 纯 Python 运算 >90s、两次超时强杀（180s/20s）未能复现 164/164。Hermes 未用该数字支撑任何结论。

### 主 agent 核验（铁律2 诚实披露 · 直读代码确认）
- C-10 代码级断言**成立**：`metacog.py` `verify_integrity` L878-879 显式 `continue` 跳过 `script:` 键；`verify_script_integrity` 全文件仅 L2670（cmd_verify）一处调用；`cmd_retrieve` L2598-2600 只调 `verify_integrity` 且注释"非阻塞告警"；`integrity.json` L493 位于 `ledger/`（可写域）。
- C-11 成立：`build_trust_root` L550-551 `not enabled or backend=="legacy" → return None`；`backend` 经签名（L312 入 TrustRootConfig）；持密钥签 `legacy` 合法禁用（设计内）。
- C-9 成立：默认密钥为 `trust_root.py` 明文字面量（读源码即得）；缓解=部署以 env 覆盖为**专属随机密钥**（已在 v2.8.0 文档记为"部署建议"）。
- C-12 成立：env 进程级，跨部署共享即单点；缓解=每部署唯一密钥。

### 主 agent 立场（铁律5 · 采纳/反驳）
- **采纳 C-9（sharpen）**：dossier 残余①原述"代码**写**权限"偏弱；Hermes 正确指出"代码**读**"已足伪造（默认密钥在源码）。→ 修正：默认密钥部署仅当"代码对敌不可读"时安全，**对公开 skill 不成立** → env 覆盖为专属密钥由"推荐"升为"非本地部署强制"。
- **采纳 C-10（关键）**：D4 是检测（人工 cmd_verify）非阻止；基线同可写域、热路径不调用、跳过 script 键。→ **撤回**将"代码完整性"表述为"部署契约兜底/有效残差边界"的任何暗示；诚实改为"代码完整性属部署契约/out-of-band，产品内 D4 仅供检测、不得列为补偿控制面"。
- **采纳 C-11（定位 by-design）**：外部锚 opt-in 是既定设计，非 v2.8.0 回归；v2.8.0 范围=「启用后防 ledger 写篡改」，与"未启用=legacy"正交。→ 记为未来硬化候选（fail-closed 默认），不计入 v2.8.0 缺陷。
- **采纳 C-12（文档澄清）**：env 须每部署唯一；共享即单点。→ 文档澄清。
- **反驳"164/164 不可信"**：主 agent 与隔离 subagent 均已实证 `test-trust-root.py` **164/164 PASS（exit 0）**（本次复跑落盘 `/tmp/tr_test.log`）；Hermes 未复现系其 180s/20s 超时强杀 RSA 重型导入，**非套件失败**。承认"套件重型（RSA 纯 Python 导入）"是真实可维护性/CI 隐患（非正确性），建议未来拆分。

### 最终裁定与待 KK 终裁
- **C-1 状态**：由连续 11 轮「OPEN → CONDITIONAL」**上调为「RESOLVED（软件层·窄威胁模型：敌具 ledger 写权、无代码读/写权、无 env 密钥）」**。新专项测试（换 root_pubkey 保留旧签名 → fail-closed）实证攻击被阻断。
- **评级**：⚠️ **有条件通过（CONDITIONAL-PASS）**——C-1 软件层闭合成立；但须按 Hermes **收窄并诚实化残余**：① 默认密钥部署须 env 覆盖专属密钥（强制非本地部署）；② 产品内 D4 仅为检测、不得宣称控制面。两步诚实化落地后，v2.8.0 评级脱离"因 C-1 OPEN 而 CONDITIONAL"，转为"已闭合·残余已诚实化"档。
- **待 KK 决策**：是否授权 **v2.8.1** 硬化 C-9/C-10/C-11（默认密钥强制 env / D4 接入 cmd_retrieve 硬闸 / 外部锚 fail-closed 默认）。本回合仅评不改（铁律1），9 文件冻结 sha256 不变。
