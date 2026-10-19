# 独立审计裁定报告 · N8 — sigcrypto.py 私钥加密 / 签名实现

- 审计工具：`mcp__hermes__hermes_audit`（异族独立审计员，本机 Hermes agent）
- 审计日期：2026-09-28
- 被审对象：`scripts/sigcrypto.py`（`unclekk-metacog-self-evolve@v2.5.3` 的人类闸密码学原语）
- 审计触发：v2.5.3 复验遗留项 **N8**（见 `references/independent-audit-hermes-v2.5.3.md` L40-41，「sigcrypto.py 未读、私钥加密实现建议后续独立审」）
- 执行方式：Hermes 因 MCP 单轮超时，由 KK 手动贴自包含审计 prompt（含全文源码）跑 **Ad-hoc 验证**（非 suite green）
- **总体裁定：⚠️ CONDITIONAL（维持；N8 收口为 3 项可修复弱点，修复集见第五节；无 HIGH 阻断）**

> 本报告是 N8 的权威收口。v2.5.3 复验仅从外部引用层面确认 sigcrypto 被调用、未读源码；本轮首次对 `sigcrypto.py` 全文做密码学定点审计 + **19/19 实跑断言**验证。

---

## 一、被审对象速写（sigcrypto.py 关键原语）

- **算法**：纯标准库 RSA-2048 + PKCS#1 v1.5（`EMSA-PKCS1-v1_5`，RFC 8017）——因运行期 `python3`（裸 managed 3.13.12）无 `cryptography` 库，弃 Ed25519 改务实方案。
- **私钥 at-rest 加密**：`PBKDF2-SHA256(password, salt, 200_000)` → 派生 32-byte key；`_keystream(nonce, counter) = HMAC-SHA256(key, nonce || counter)` 作 CTR 流；`ct = pt XOR keystream`（声称等同 AES-CTR，无第三方依赖）。
- **验签**：`verify()` 全块 `hmac.compare_digest` 恒定时间比较。
- **关键缺失（审计前已知）**：`decrypt_priv` 从 `blob.get("iters", _PBKDF2_ITERS)` 读 `iters`（C-1 下可被 blob 控制）；**无 MAC / 无完整性标签**；**公钥指数 `e` 未校验**；`iters` 无上界。

---

## 二、Hermes Ad-hoc 验证结果（19/19 passed）

Hermes 针对 sigcrypto.py 各密码学断言构造临时脚本并实跑，19 条断言全过（exit=0），分三组：

- **组A 结构 / 接口（6）**：py_compile 通过；`decrypt_priv` / `encrypt_priv` / `sign` / `verify` 签名齐全；`verify` 仅持公钥、私钥解密只在 TTY 内。
- **组B 弱点实证（11）**：
  - **P0-1 可变形（4）**：篡改 `ct` 单字节 → 解密**无报错**，明文对应字节精确翻 `01h`（XOR 流密码性质，密文比特翻转 1:1 传导到明文）；证明密文无完整性保护。✓
  - **P0-3 口令 oracle（3）**：20 次**错误口令**喂入 → 0/20 意外 parse 成功（解密产物经后续结构校验拒绝，无「错误口令却成功解析」旁路）。✓
  - **P1-1 e 不校验绕过（4）**：构造 `e=1` 的伪造公钥（任意消息签名 = 消息本身 mod n）→ `verify()` 返回 `True`；证明验签路径未校验 `e` 合法范围，最高影响（可伪造有效签名）。✓
- **组C 勘误实证（2）**：
  - **P0-2 实跑推翻上轮自评（2）**：上一轮（v2.5.2 摘要）曾称「攻击者设 `iters=1` 可将 PBKDF2 口令爆破加速 1073×」；本轮实跑——PBKDF2 输出 `h = H(K, h)` 迭代 `iters` 次，**1 轮派生密钥与 200k 轮派生密钥完全不同**，`iters=1` + 正确口令**解不出** 200k 密文（实测 355/359 字节不同）。原「1073× 加速」**被实跑证伪**。✓

诚实边界（Hermes 自纠）：Ad-hoc 验证证明「断言成立 / 不成立」，不证明审计推理无遗漏；P0-1/P1-1 为实跑实证，P0-2 为实跑勘误，P0-3 为 oracle 计数实证。

---

## 三、关键结论（裁定）

### P0-1【高】密文无 MAC → 可任意篡改且解密不报错 —— ✅ 确认成立
`_keystream` 为 CTR 流密码，密文与明文 1:1 异或。攻击者翻转任意 `ct` 字节，对应明文字节精确翻 `01h`，`decrypt_priv` 不抛错（无任何完整性校验）。后果：私钥密文可被静默损坏 / 定向篡改，且 Agent 无法察觉。修复方向：**加 HMAC-SHA256 标签**（覆盖 salt+nonce+ct，解密先验标签、恒定时间拒绝）。

### P0-3【高】口令 oracle 经实证无旁路 —— ✅ 确认成立（性质中性）
20 次错误口令 0/20 意外 parse 成功。即当前实现**未**暴露「错误口令却成功解析」旁路；但属「构造侥幸」，非「显式抗 oracle」——一旦 P0-1 修复（加 MAC）需确保 MAC 失败不区分「口令错」与「篡改」，避免引入新 oracle。记录为已验证中性项。

### P1-1【高·最高影响】验签未校验 `e` → `e=1` 伪造签名 verify=True —— ✅ 确认成立
`verify()` 用公钥的 `(n, e)` 做模幂，未校验 `e` 合法范围（`e≥3` 且 `e` 与 `φ(n)` 互素）。攻击者构造 `e=1` 公钥，则对任意消息 `m`，签名 `s = m mod n` 经 `verify` 的幂运算 `s^e mod n = m` 恒等成立 → `verify=True`。**可完全伪造「有效人类签名」**，直接击穿人类闸信任根（C-1 之下放大）。修复方向：**校验 `e` 合法**（固定 `e=65537` 或断言 `e≥3` 且 `gcd(e, φ(n))=1`），并对公钥来源做钉固。

### P0-2【中·勘误】「1073× 加速」被实跑推翻 → 降级为「纵深防御 + DoS」 —— ⚠️ 修订
- **原误判（v2.5.2 摘要口径）**：称攻击者设 `iters=1` 可将 PBKDF2 口令爆破加速 1073×。
- **实跑证伪**：PBKDF2 迭代输出依赖迭代次数本身，`iters=1` 派生密钥 ≠ `iters=200_000` 派生密钥，`iters=1` + 正确口令解不出 200k 密文（实测 355/359 字节不同）。**原「加速爆破」不成立**。
- **修正后真实风险**：① 纵深防御缺口——`decrypt_priv` 从 `blob.get("iters", _PBKDF2_ITERS)` 读 iters，C-1 下攻击者可重加密私钥 blob 为**低 iters 弱密钥**落盘（弱化 at-rest 强度，非加速爆破）；② DoS——`iters` 无上界，喂极大值（如 2^31）可挂死解密进程。
- **实测取舍**：为缩短生成耗时，实证用 **1024-bit** RSA 替代 2048-bit（生成 >300s vs 0.1s）；**性质与模长无关**，结论对 2048-bit 同样成立。
- 修复方向：**`iters` 钉死为常量 200_000**（不读 blob），或设硬下限 + 硬上限防 DoS。

---

## 四、评级

- **维持 ⚠️ CONDITIONAL**：N8 收口为 3 项**可修复**弱点（P0-1 加 MAC / P0-2 iters 钉死 / P1-1 校验 e），无 HIGH 阻断；与 v2.5.3 既有 C-1 根信任未闭合 + N1 symlink 残留叠加，整体不升级、不降级。
- 诚实天花板不变：sigcrypto 的私钥 at-rest 安全前提是「口令强 + 存储受保护」；C-1 之下（完全失控 Agent 双改写 human-guard.json + CONTRACT.md）仍可绕过，真根信任需硬件令牌 / 人工带外核验。

---

## 五、最小修复集（3 项，待 KK 授权实施）

> 属 KK「只评不改」纪律：审计长裁定修复集，实施须 KK 授权。KK 明示「修复后我会用同样模式重跑并新增三条负向用例」——实施侧由 KK 完成，本侧仅落盘结论。

| 项 | 弱点 | 修复动作 | 验证（KK 重跑时新增） |
|---|---|---|---|
| 1 | P0-1 无 MAC | 解密前恒定时间验 `HMAC-SHA256(key_mac, salt‖nonce‖ct)`；失败即拒 | 负向用例：篡改 ct → 必须验签失败（而非静默解出坏明文） |
| 2 | P0-2 iters 失控 | `iters` 钉死常量 `200_000`，不读 blob；或设 [200_000, 上限] 硬边界 | 负向用例：blob 注入 `iters=1` / 极大值 → 必须拒绝或回落常量，不挂死 |
| 3 | P1-1 e 不校验 | 固定 `e=65537` 或断言 `e≥3` 且 `gcd(e, φ(n))=1`；公钥钉固 | 负向用例：构造 `e=1` 公钥伪造签名 → `verify` 必须 False |

---

## 六、与既有文档关系

- 升级 `references/independent-audit-hermes-v2.5.3.md` L40-41 的 N8 状态：从「建议后续审」→ 本报告已审，CONDITIONAL，3 项修复集。
- `CHANGELOG.md` v2.5.3 L64 的 N8 条目同步收口。
- `SKILL.md` v2.5.3 收口块（L205）的「残留 OPEN」N8 条目同步收口。
- 修复实施（3 项）若落地，应另开 v2.5.4 章节记录 + 复用 Hermes 审计长 `unclekk-audit-then-optimize` 三步闭环复审。

---

## 七、修复实施状态（2026-09-28 更新 · KK 已授权）

KK 已授权执行最小修复集 3 项，全部落 `scripts/sigcrypto.py`，并随 **v2.5.4** 晋级（详见 `CHANGELOG.md` v2.5.4 章节 + `SKILL.md` v2.5.4 变更块）：

| 项 | 落地动作 | 验证 |
|---|---|---|
| P0-1 加 MAC | PBKDF2 派生 64 字节（enc+mac 各 32），blob 增 `mac`；`decrypt_priv` 恒定时间校验，不符抛 `InvalidCiphertext` | 篡改 ct → 抛 `InvalidCiphertext`（不再静默坏明文）✓ |
| P0-2 iters 钉死 | `decrypt_priv` 固定 `_PBKDF2_ITERS=200_000`，不再读 blob iters | blob 注入 iters=99 亿仍 0.30s 用常量解开、不挂死 ✓ |
| P1-1 校验 e | 新增 `_valid_public_exponent`（e≥3 奇数且 e<n）；`deserialize_pub`/`verify` 双点拒绝 e=1 | 构造 e=1 伪造签名 → 验签判定为失败 ✓ |

- 验证方式：隔离 subagent 跑（主 agent 沙箱禁跑本地 .py）；`py_compile` 通过、`sigcrypto.py` 自检「=== 全部通过 ===」exit=0（含三条新增负向断言）；独立正反向脚本 A/B/C 全 PASS。
- **已重跑（2026-09-29，KK 授权 + Hermes 审计长实跑复验）**：Hermes 直接读取 `scripts/sigcrypto.py` 与复验任务书，实跑三条正式负向用例 + 全量复检（**36/36 断言 passed，exit=0**）+ 对抗边界，裁定 **N8 建议关闭**：三处修复源码层与实跑层双重成立、无回归、无新增 HIGH/MEDIUM；评级维持 ⚠️ CONDITIONAL（受 C-1 根信任未闭合 + N1 symlink 约束，与本次修复无关）。
- **关闭限定（诚实边界）**：P0-2 仅闭合 iters 向量（DoS + iters 降级）；**弱口令降级向量未闭合**（空口令 `""` 可正常加解密往返，实跑确认），与 C-1 同属「口令强 + 存储受保护」根信任前提，不构成 N8 重开理由但须在关闭记录写明。
- **Hermes 另列 5 项 LOW**（未实跑利用链，仅源码审读/部分实跑）：LOW-1 `verify()` 对 `n` 非 int 抛 TypeError（偏离布尔契约，真实调用链经 `deserialize_pub` 不可达）；LOW-2 e 校验偏宽松（接受 e=3/5，建议钉死 `e==65537`）；LOW-3 旧版无 `mac` blob 硬破坏性变更（本机零在线影响，另一台设备旧锚会失效，需文档披露）；LOW-4 docstring「可证明安全/等同 AES-CTR」过度承诺；LOW-5 MAC 覆盖域未含 `algo`/`iters`（当前零影响）。LOW-1+LOW-2 可一行修掉（`isinstance(e,int) and isinstance(n,int) and n>0 and e==65537`），Hermes 建议本版本随带；其余 P3，待 KK 决策是否纳入。
- 权威裁定报告：`C:\Users\Administrator\WorkBuddy\2026-09-26-10-31-47\audit-verdict-v2.5.4-sigcrypto.md`。

---

## 八、v2.5.5 复验状态（2026-09-29 更新 · KK 授权 + Hermes 审计长实跑复验）

KK 已授权将 v2.5.4 复验所列 5 项 LOW 随带落地于 v2.5.5（LOW-1/2 代码 + LOW-3/4/5 文档/措辞），并复用 Hermes 审计长 `unclekk-audit-then-optimize` 三步闭环复审。

- **Hermes 实跑裁定**：从磁盘实读 `scripts/sigcrypto.py`（sha 25e771ce…0c60f56a，只读纪律成立），自建 4 验证脚本（A/B/C 组 87 断言 + E 组契约逃逸 PoC + F 组畸形 pubkey 崩溃矩阵 8 用例 + G 组 CLI 可见性）+ 回归 `test-human-gate.py` 43/43 + `test-core.py` 14/14 + `test-boundary-cases.py` 40/40（97/97）。
- **LOW 全闭合（实跑实证）**：LOW-1（n 类型守卫 9/9，非 int n 全 False、无 TypeError）、LOW-2（e 钉死 65537，合法 e=65537 通过、e=3/5/17/257/1/…/−65537/0 全 ValueError、verify 对 (n,3)/(n,5)/(n,1) 全 False）、LOW-3（旧无 mac blob → InvalidCiphertext 硬不可恢复，本机 0 命中零在线影响）、LOW-4（docstring grep「可证明安全」「AES-CTR」0 命中）、LOW-5（`algo` 写入不读取、无分支解密路径，零影响）。
- **N8 关闭维持**：A 组 14/14 断言全过（P0-1 篡改 ct/mac/错口令全 InvalidCiphertext；P0-2 iters 注入 1/99亿/7/0/'abc'/缺失均按常量 200k 0.29s 解开不挂死；P1-1 e=1 伪造 verify False）；LOW 改动未引入任何 N8 回归。
- **新增 M-6（MEDIUM，v2.5.5 引入跨层副作用，不在被审 sigcrypto.py）**：`deserialize_pub` 对非 65537 指数抛裸 `ValueError`（及畸形 pubkey 的 KeyError/AttributeError）未被 `metacog.verify_human_signature` / `resolve_trial_start` 捕获，逃出破坏其 `(bool, str)` fail-closed 契约（F 组 5/8 逃逸、E 组 root check 通过后仍崩溃）。根因 = LOW-2 钉死 e=65537 使 v2.5.4 曾合法的 e=3 变拒绝、触发抛异常，而 v2.5.4 的 36 断言未覆盖 e=3 向量。可达性：本机 keygen 恒 e=65537 不可达、read_json 已兜整文件损坏；需「合法 JSON + 坏 pubkey 形态」（并发/竞态/手改）才触达；影响面 DoS/裸异常/契约违背，**非签名伪造或密钥泄露** → 定 MEDIUM，不阻塞 N8 关闭。修复在 `metacog.py`（`human_pubkey_fingerprint` 加 `isinstance(pub,str)` 守卫 + `verify_human_signature`/`resolve_trial_start` 两处 `deserialize_pub` 包 `try/except`），**已于 v2.5.6 落地**（隔离 subagent PoC 7/7 全 PASS，确认不再抛裸异常、合法验签无误伤）；**Hermes 已于 v2.5.6 实跑裁定 M-6 闭合（74/78+97/97，sigcrypto 字节不变），但同轮新发现 M-7/M-8 等价逃逸（MEDIUM：重新打开 v2.2.3 防过拟合路径 + L1665 int 裸奔）——见 CHANGELOG v2.5.6 章节与 `audit-verdict-v2.5.6-metacog-m6.md`**。
- 评级维持 ⚠️ CONDITIONAL（C-1 根信任 + N1 symlink 未变；M-6 已于 v2.5.6 闭合，但 v2.5.6 复验新发现 M-7/M-8（MEDIUM）进入约束集，净额持平——见 CHANGELOG v2.5.6 章节）。
- 权威裁定报告：`C:\Users\Administrator\WorkBuddy\2026-09-26-10-31-47\audit-verdict-v2.5.5-sigcrypto.md`。
