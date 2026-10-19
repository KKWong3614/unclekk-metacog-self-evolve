# 异族独立审计 · unclekk-metacog-self-evolve v2.6.1

- 审计角色：异族独立审计员（代码级、敌意批判、立场中立）
- 审计对象：`skill:unclekk-metacog-self-evolve` v2.6.1（3 项 HIGH 修复复核）
- 审计日期：2026-09-30
- 审计方法：读盘交叉核对（`trust_root.py` 全文 396 行、`metacog.py` 关键段 L659-733 / L2531-2564、`test-trust-root.py` 全文 419 行、`SKILL.md` L246-254、`CHANGELOG.md` L32-55、`references/independent-audit-hermes-v2.6.0.md` 全文）
- 纪律声明：本审计**未执行**任何被测 `.py`；结论全部基于静态读盘 + 逻辑复算。所有行号均已逐字符核对磁盘源码。

---

## 总体评级：维持 ⚠️ CONDITIONAL · **不上调，不降级**

v2.6.1 的 **3 项 HIGH 均在静态证据上闭合**，未发现新增 HIGH。

- **HIGH-1 已静态闭合**：`grep -n "_SIM_DEVICE_ATTEST_KEY" trust_root.py` 结果为空；模块内所有验签走可插拔 `self.key_provider.verify`（`trust_root.py` L223），无硬编码常量、无旁路分支。
- **HIGH-2 已诚实处理**：`TokenKeyProvider.verify` 恒 `False`（L105）、`sign` 抛 `NotImplementedError`（L100-101），无任何绕过；文档明示"需新增后端，属代码工作，非人工步骤"，不再包装为部署步骤。
- **HIGH-3 已 fail-closed**：`load` 解析失败返回 `corrupt=True, enabled=True`（L143）；`build_trust_root` 对 corrupt（L265-266）/ 未知 backend（L279-280）/ hsm 无 provider（L273-275）均返回 `DenyTrustRoot`，`check_pubkey_root` L721-723 据此拒绝。区分「从未启用返 None」与「启用但损坏恒拒」两条路径，不再共用。

**不上调的硬理由（4 项）：**
1. **C-1 在默认模式（legacy，无 `ledger/trust-root.json`）仍 OPEN**——SKILL.md L254 诚实边界 ③ 已明确披露，评级不能因 HIGH 闭合而忽略这一默认姿态。
2. **外部锚的不可伪造性仍依赖「attestation_path / oob_token_dir 确为 Agent 无写权限目录」这一部署契约，代码无任何运行时强制**——无权限校验、无 ACL 断言、无启动期检查。这是 v2.6.0 审计已明确定性、v2.6.1 未改变、也不应改变的结构性限制。
3. **v2.6.0 审计裁定的 MEDIUM-1 / MEDIUM-2 / MEDIUM-3 三项均未落地**——`trust_root.py` 中 `is_symlink` 计数为 0，`OobTrustRoot.oob_confirmed`（L239-244）仍仅 `os.path.isfile`，`_confirm_keygen`（metacog.py L2539-2542）未强制单独 hsm 被拒。
4. **验证全部 self-attested**（同作者测试 + 隔离 subagent 跑），非独立审计；subagent 声称的 `test-trust-root.py` "36/36 PASS" 与静态清点约 37 项断言基本吻合（Hermes 自估 48-52 为粗略高估，见自纠 N3-c），套件全绿无回归。

**不降级理由**：3 HIGH 静态闭合、无新增 HIGH、诚实边界方向正确且已扩充。评级维持 CONDITIONAL 是 v2.6.0 → v2.6.1 的正确落点。

---

## 关键发现清单

### HIGH-1 · 已闭合（静态证据）

- `trust_root.py` 全文 grep `_SIM_DEVICE_ATTEST_KEY` = **0 匹配**（唯一残留出现在 `CHANGELOG.md` L38 与 `references/independent-audit-hermes-v2.6.0.md` 历史记录中，不在代码）。
- `KeyProvider` 抽象（L49-60）+ `SimKeyProvider`（L63-83，`__init__(self, secret)` 强制调用方注入，含类型守卫）+ `TokenKeyProvider` 桩（L86-105）。
- `HsmTrustRoot.attestation_ok` L222-224：**唯一**验签路径为 `self.key_provider.verify(pub_serialized, sig)`；无 fallback、无 `if key_provider is None: use_default` 旁路。
- `write_device_attestation`（L303-311）签名改由注入的 `key_provider` 完成，不再持有常量。
- `build_trust_root` L271-275：hsm / hsm+oob 走 `_load_key_provider(cfg)`；`None` 时**恒拒**（`DenyTrustRoot`），不回落 legacy。
- `test_key_provider_isolation`（L186-198）含静态审计点：`not hasattr(trust_root, "_SIM_DEVICE_ATTEST_KEY")`。

**残留定性**：v2.6.1 把密钥从"源码"迁移到"配置文件"（`ledger/trust-root.json.sim_key`）。见 MEDIUM-4——在威胁模型「ledger 可写」的前提下，此迁移不新增实质攻击面（ledger 内的密钥本就属可伪造），但 SKILL.md 现表述（"C-1 视为闭合"）**未完整披露该迁移的语义后果**，需补第 7 条诚实边界（见 P1.1）。

### HIGH-2 · 已闭合（诚实方式，非包装）

- `TokenKeyProvider.verify` L103-105：`return False`，注释明确「真机后端未实现前，任何签名均不可达 → fail-closed（诚实不可达，不静默放行）」。
- `TokenKeyProvider.sign` L99-101：`raise NotImplementedError("...请接入 PKCS#11/TPM/WebAuthn")`。
- `_load_key_provider`（L108-115）：**优先 token_backend → SimKeyProvider → None**；只要 `token_backend` 非空即返回 `TokenKeyProvider`，导致 `attestation_ok` 恒 False（`external-anchor-attestation-forged`），即 fail-closed。
- `metacog.py` L2553-2558：keygen 用 `SimKeyProvider` 签名；若用户改走 `TokenKeyProvider`，捕获 `NotImplementedError` 后 `warn("真机令牌后端未实现，未能生成设备证明")`——失败被显式告警，不静默。
- 文档表述（SKILL.md L250/L254 ⑤、CHANGELOG L49）**已明确承认「需新增后端，属代码工作，非人工步骤」**，不再是 v2.6.0 的"真机验证为人工步骤"表述。

**无残留。** HIGH-2 是本轮最诚实的修复：从"以人工步骤包装不可用功能"改为"明示 fail-closed + 承认代码工作"。

### HIGH-3 · 已闭合（fail-closed 语义已建立）

- `TrustRootConfig.load` L138-143：`json.loads` 失败 → `return cls(corrupt=True, enabled=True)`（不是 `cls()` legacy 默认）。
- `build_trust_root` L265-266：`if cfg.corrupt: return DenyTrustRoot()`——**先于** L267-268 的 `not cfg.enabled` 检查，避免 corrupt 被 enabled=False 短路。
- `build_trust_root` L271-280：hsm / hsm+oob 无 provider → `DenyTrustRoot`（L273-275）；未知 backend → `DenyTrustRoot`（L279-280）。
- `DenyTrustRoot` L178-196：`attestation_ok` 恒 `(False, "external-anchor-disabled")`、`oob_confirmed` 恒 `False`、`oob_token_required` 恒 `True`、`challenge_for` 恒 `"denied"`——语义与 `legacy`（no-op pass）**完全相反**，不会静默放行任何证明路径。
- `check_pubkey_root`（metacog.py L711-723）：`ext is not None` 时必走外部锚；`DenyTrustRoot` 的 `attestation_ok` 恒 False → 拒。
- `test_check_pubkey_root_corrupt_config_failclosed`（L312-339）覆盖 3 情形：非法 JSON / 未知 backend / corrupt 下篡改 human-guard——全部 fail-closed。

**低优残留**：`DenyTrustRoot.attestation_ok` L187 返回 reason `"external-anchor-disabled"`——字面上把"配置损坏"和"从未启用"混为一谈。建议改为 `"external-anchor-corrupt"` / `"external-anchor-unknown-backend"`，便于运维与审计区分（LOW 级，不影响安全）。

### MEDIUM-1 · v2.6.0 遗留未落地

`trust_root.py` 全文 `is_symlink` 匹配数 = **0**。
- `HsmTrustRoot.attestation_ok` L209-210：仅 `os.path.isfile(ap)` + `Path(ap).read_text()`——若 `ap` 是 symlink 指向 Agent 可控路径，可挂伪造证明。
- `OobTrustRoot.oob_confirmed` L242-244：仅 `os.path.join` + `os.path.isfile`——`oob_token_dir`（目录级 symlink）与 `tok`（文件级 symlink）均未检查。

N1 防护哲学（防 symlink 重放）未随 v2.6.0 新增面扩展，v2.6.1 亦未落地。

### MEDIUM-2 · v2.6.0 遗留未落地

`OobTrustRoot.oob_confirmed` L239-244：`return os.path.isfile(tok)`——**文件存在即通过**，无内容校验、无过期时间、无一次性消费。与 `nonce_file` 的"读即焚"（metacog.py L2506 `_np.unlink()`）姿态差距明显。持久有效 + 无内容校验 = 长期重放面。

### MEDIUM-3 · v2.6.0 遗留未落地

- `_confirm_keygen`（metacog.py L2539-2542）：`if _en in ("hsm", "hsm+oob") and not _att:` 仅检查路径缺失，**未拒绝单独 `--enable-external hsm`**。
- SKILL.md L254 ② 明说"单独 hsm 无安全意义"，代码未强制。属"文档-代码不对称"——文档说得对但代码不拦。
- 注意：MEDIUM-3 的危害性在 v2.6.1 下降（单独 hsm 已无实质安全增益），但**代码-文档对称性**仍需修复。

### MEDIUM-4 · 新发现（诚实边界不完整）

`write_trust_root_config`（trust_root.py L287-300）把 `sim_key` 明文写入 `ledger/trust-root.json`（L296）。威胁模型（v2.6.0 审计明确）：**ledger 目录对完全失控管理员可写**。

- 在威胁模型（ledger 可写）下，`sim_key` 位置不构成**额外**攻击面——ledger 内的任何密钥本就属"可被攻击者控制"。
- 但**在 SKILL.md 现表述下**（"C-1 视为闭合"、"根信任外部化成立"、诚实边界 ④"已改为可插拔 KeyProvider"），读者会误认为 hsm+oob 已足够。**实际 hsm+oob 中真正对外部锚有实质的仅是 oob 部分**——hsm 部分因 `sim_key` 位于可写区域内，从外部不可伪造性角度退化为"部署契约"。

这是**文档披露完整性问题，非代码漏洞**。须补第 7 条诚实边界，否则 SKILL.md 对 hsm 独立价值的暗示仍属**低估**。

### MEDIUM-5 · 结构性限制（v2.6.0 起未修）

攻击者可**删除** `ledger/trust-root.json`（`p.exists()` 为 False → `load` 返回 `cls()` legacy 默认）→ `build_trust_root` 返回 `None` → `check_pubkey_root` 走 legacy 分支。

这**不是 v2.6.1 新增漏洞**，是 v2.6.0 起即存的结构性限制：任何依赖配置文件的机制都无法防御"配置文件可删"——威胁模型下攻击者本来就能写 ledger，删除文件与写文件能力等价。v2.6.1 的 HIGH-3 修复只覆盖"文件存在但内容损坏"情形，未覆盖"文件被删除"情形。属部署契约必须明示，非 bug。

### MEDIUM-6 · 表述限定性

`check_pubkey_root` 文档（metacog.py L698-699）与 SKILL.md L254 ③ 明说「C-1 视为闭合」。**在威胁模型（ledger 可写）下**，hsm 部分不构成真正外部锚（因 `sim_key` 位于可写区域）。真正使 C-1 闭合的仅是 **oob 部分**——`oob_token_dir` 必须不可写，且 `oob_token_required` 恒 True。

建议 SKILL.md 表述由「启用外部锚后根信任外部化成立、C-1 视为闭合」改为「启用外部锚后 **oob 部分**为真正外部锚；hsm 部分在威胁模型下退化为部署契约，须叠加 oob 才构成完整姿态」。

### LOW-1 · v2.6.0 遗留

`TrustRoot.challenge_for`（L174-175）：`sha256("oob|" + pub_serialized)[:16]`——仅绑公钥，不绑操作类型 / 时间窗 / nonce。同一公钥下所有操作共享同一 challenge → 同一 token 长期有效。与 MEDIUM-2 叠加。

### LOW-2 · v2.6.0 遗留

`metacog.py` L725-728：外部锚模式下 CONTRACT.md 指纹不符仅 `stderr.write` 告警，不写 D4 完整性记录、不计入 D5。这是 v2.5.2 C-3 修复的**方向性回退**。虽有文档披露，但未承认纵深削减。

### LOW-3 · 已闭合

`trust_root.py` L34 已 `import datetime`；L298 使用 `datetime.datetime.now()`——v2.6.0 的内联 `__import__("datetime")` 已移除。

---

## Q1-Q5 裁决

### Q1 · HIGH-1 是否在 v2.6.1 静态闭合？
**是。** grep `_SIM_DEVICE_ATTEST_KEY` = 0；验签只走 `self.key_provider.verify`（L223），无旁路。签名算法随后端走（`SimKeyProvider` HMAC / `TokenKeyProvider` NotImplemented 桩）。见 MEDIUM-4：迁移到配置文件后攻击面在威胁模型下等价，但需在 SKILL.md 补齐披露。

### Q2 · HIGH-2 是否以诚实方式处理？
**是。** `TokenKeyProvider.verify` 恒 `False`、`sign` 抛 `NotImplementedError`——任何 `token_backend` 配置在 v2.6.1 下**必然 fail-closed**。文档明示「需新增后端，属代码工作，非人工步骤」。keygen 在 `TokenKeyProvider.sign` 抛错时**显式 warn**，不静默。本轮最诚实的修复。

### Q3 · HIGH-3 是否已 fail-closed？
**是。** 三种情形（corrupt / 未知 backend / hsm 无 provider）均返回 `DenyTrustRoot`，`DenyTrustRoot` 语义与 legacy 完全相反。**不再静默回落 legacy**。`corrupt` 检查先于 `not cfg.enabled`，避免被短路。测试覆盖 3 情形。

**残留**：删除 `trust-root.json` 会绕过 corrupt 检测回到 legacy（MEDIUM-5，结构性限制，须部署契约明示）。

### Q4 · 评级是否可从 CONDITIONAL 上调？
**否，维持 CONDITIONAL。**
- **闭合**：HIGH-1 / HIGH-2 / HIGH-3（静态证据充分）。
- **仍 OPEN**：C-1 默认 legacy 模式仍 OPEN；外部锚不可伪造性依赖未运行时强制的部署契约；MEDIUM-1/2/3 未落地；MEDIUM-4 新增（诚实边界不完整）；MEDIUM-5 结构性限制未披露；MEDIUM-6 表述需限定；LOW-1/2 未落地。
- **验证**：全部 self-attested，非独立审计。
- **核心理由**：C-1 默认模式仍 OPEN、外部锚不可伪造性依赖未运行时强制的部署契约——这两点是 v2.6.0 → v2.6.1 之间的**未变项**，不因 HIGH 修复而消失。

### Q5 · SKILL.md 6 条诚实边界是否与 v2.6.1 代码一致？
**与代码一致，但不完整（缺 1-2 条，见 MEDIUM-4 / MEDIUM-5）。**

| 边界 | 描述 | 代码一致性 | 评 |
|---|---|---|---|
| ① | hsm 以 SimKeyProvider 仿真，真机后端未实现（TokenKeyProvider 桩必 fail-closed） | 一致 | ✓ |
| ② | hsm 单独模式无安全意义，须叠加 oob | 一致（但代码不强制，MEDIUM-3） | ⚠ 一致但代码不对称 |
| ③ | 外部锚默认关闭，C-1 在默认模式仍 OPEN | 一致 | ✓ |
| ④ | hsm 证明密钥原硬编码，v2.6.1 已改 KeyProvider，sim 密钥仅测试 | 一致（但**未披露 sim_key 现位于 ledger 明文，威胁模型下退化为部署契约**） | ⚠ 不完整 |
| ⑤ | 当前代码无法接受真机令牌签名，真机部署需新增后端 | 一致 | ✓ |
| ⑥ | 评级维持 CONDITIONAL | 一致 | ✓ |

**必须补充的第 7 条**：「sim_key 存储在 `ledger/trust-root.json` 明文，在威胁模型（ledger 可写）下 hsm 部分不构成真正外部锚；实际闭合 C-1 的仅是 oob 部分（依赖 attestation_path / oob_token_dir 无写权限）；仅 oob 模式对 ledger 可写威胁模型具实质外部锚价值」。

**可选补充的第 8 条**：「删除 `ledger/trust-root.json` 会绕过 corrupt 检测回退 legacy——属部署契约必须明示的结构性限制，非代码可防御」。

---

## 针对性改进建议

### P1（阻塞性，须随 v2.6.2 落地）

1. **补齐诚实边界（MEDIUM-4 / MEDIUM-5 / MEDIUM-6）**：SKILL.md L254 与 CHANGELOG.md 的 6 条 → 扩充为 7-8 条。至少新增：
   - 「sim_key 存储在 `ledger/trust-root.json` 明文；威胁模型（ledger 可写）下 hsm 部分不构成真正外部锚；仅 oob 部分（依赖 attestation_path / oob_token_dir 无写权限）对威胁模型具实质外部锚价值」。
   - 「删除 `ledger/trust-root.json` 会绕过 corrupt 检测回到 legacy——部署契约必须明示，非代码可防御」。
   - 表述「启用外部锚后 C-1 视为闭合」须限定为「**oob 部分**闭合」，或明说「hsm 部分在威胁模型下退化为部署契约」。

2. **禁止单独 hsm（MEDIUM-3）**：`_confirm_keygen`（metacog.py L2539-2542）中，`_en == "hsm"`（无 oob）时**直接拒绝并指路 hsm+oob**，而非仅 warn。当前文档说不安全、代码不拦，属"文档-代码不对称"。

3. **N1 扩展覆盖（MEDIUM-1）**：`HsmTrustRoot.attestation_ok` 对 `ap` 及其父目录做 `is_symlink` 检查；`OobTrustRoot.oob_confirmed` 对 `oob_token_dir`（目录级）与 `tok`（文件级）均做 `is_symlink` 检查。建议抽出 `_assert_real_path(p)` 辅助函数。

### P2（安全性提升）

4. **oob token 内容校验 + 一次性消费（MEDIUM-2 + LOW-1）**：token 内容须为 `hmac(session_key, challenge)` 或 `challenge + nonce` 格式；校验通过后**原子消费**（`os.replace` 到 `.used` 或删除）；challenge 绑定操作类型与时间窗。

5. **部署契约运行时检查（新增）**：`build_trust_root` 在返回非 `None` 前，对 `attestation_path` / `oob_token_dir` 做可写性/属主检查，失败则降级为 `DenyTrustRoot` 并 `warn`。

### P3（代码卫生 / 审计追踪）

6. **外部锚模式下 CONTRACT.md 不符计入 D4（LOW-2）**：`check_pubkey_root` L725-728 除 stderr 告警外，同时 `record_integrity` 追加一条 D4 记录。

7. **DenyTrustRoot reason 细分（LOW）**：L187 的 `"external-anchor-disabled"` 按触发路径细分（corrupt / unknown-backend / no-provider）。

8. **测试套件计数复核**：`test-trust-root.py` 实际断言约 37 项（含 conditional），与 subagent 声称的 "36/36 PASS" 基本吻合；建议把**实际**断言数与 pass 数更新到 CHANGELOG.md，避免下次复验再发现同一差异。

---

## 审计自纠记录

- **N3-a（撤回原判：sim_key 位置非新增漏洞）**：初判「sim_key 迁移到 ledger 明文是新增 HIGH」——v2.6.0 在源码明文、v2.6.1 在 ledger 配置明文，威胁模型下攻击面等价。撤回原判，改判 MEDIUM-4 文档披露问题。
- **N3-b（撤回原判：删除配置文件绕过 corrupt 检测非新增漏洞）**：威胁模型「ledger 可写」下，删除文件与写文件能力等价，属结构性限制，非 v2.6.1 新增。撤回原判，改判 MEDIUM-5。
- **N3-c（测试断言数复核）**：subagent 声称 "36/36 PASS"；静态清点 `r.add` 约 37 项，与声称基本吻合（Hermes 初估 48-52 为粗略高估）。差异不影响 HIGH 级结论（均基于静态证据），但强化 self-attested 数据粒度须如实披露。

---

## 审计纪律声明

- 本审计**未执行**任何被测 `.py`，结论全部基于静态读盘 + 逻辑复算。
- 本审计执行方为 Hermes 自身，**非真·异族独立审计**（与被审对象同栈、同生态）。
- HIGH-1/2/3 的闭合判定均基于**可被任何读者以同样方式复算的静态证据**（grep 结果、行号、方法签名形态、返回值语义），不依赖运行实测。

---

## 附录：闭合度总表

| 项 | v2.6.0 裁定 | v2.6.1 静态复核 |
|---|---|---|
| HIGH-1（密钥硬编码） | OPEN | **已闭合**（静态证据充分） |
| HIGH-2（真机令牌不可用） | OPEN | **已闭合**（诚实方式，非包装） |
| HIGH-3（配置损坏静默降级） | OPEN | **已闭合**（fail-closed 已建立） |
| MEDIUM-1（symlink 未覆盖新面） | OPEN | **未落地** |
| MEDIUM-2（oob 令牌无校验/消费） | OPEN | **未落地** |
| MEDIUM-3（禁止单独 hsm） | OPEN | **未落地**（代码-文档不对称） |
| MEDIUM-4（诚实边界不完整） | — | **新增（本轮）** |
| MEDIUM-5（删除配置绕过 corrupt） | 未识别 | **新增披露（结构性限制）** |
| MEDIUM-6（"C-1 闭合"表述需限定） | 部分 | **需进一步限定** |
| LOW-1（challenge 仅绑公钥） | OPEN | **未落地** |
| LOW-2（CONTRACT.md 降级） | OPEN | **未落地** |
| LOW-3（内联 __import__） | OPEN | **已闭合** |
| C-1 默认模式 | OPEN | **仍 OPEN**（诚实边界 ③ 已披露） |
| 外部锚不可伪造性依赖部署契约 | 未实测 | **仍未运行时强制** |

**总体评级：⚠️ CONDITIONAL（不上调、不降级）— v2.6.1 是 v2.6.0 后的正确收敛点。**

---

[Hermes · 异族独立审计员] Audit Completed at 2026-09-30T10:00:00+08:00
