# 独立审计复验报告 · unclekk-metacog-self-evolve @ v2.5.3（F-2 / F-5 后续修复）

- 审计工具：`mcp__hermes__hermes_audit`（异族独立审计员，本机 Hermes agent，复用上一轮会话）
- 审计日期：2026-09-28
- 被审对象：`skill:unclekk-metacog-self-evolve@v2.5.3`（F-2 keygen 离线 nonce-file 授权 + F-5 128-bit 指纹）
- **总体裁定：⚠️ CONDITIONAL（维持；F-2/F-5 经实跑验证闭合，但新增 N1 symlink 残留 + C-1 根信任未闭合）**

> 本轮是 v2.5.2 审计（`references/independent-audit-hermes-v2.5.2.md`，⚠️ CONDITIONAL）的**后续修复复验**：v2.5.3 收口了其中两项可立即落地者（F-2、F-5）。Hermes 不仅评审交办材料，还**实跑验伪脚本**核对磁盘源码与断言。

---

## 一、Hermes 实跑验伪结果（24/24 passed，exit=0）

Hermes 生成临时验伪脚本（`C:\Users\ADMINI~1\AppData\Local\Temp\hermes-verify-audit-v253-20260928.py`）并运行，24 条断言分五组：
- 组1 语法（2）：py_compile 通过
- 组2 行为（5）：unwrap 输出无损换行（字符数一致）、代码围栏成对
- 组3 上轮脚本自证（2）：16/16 全绿（自证链闭合）
- 组4 F-5 源码依据（5）：**L588 `human_pubkey_fingerprint`→`[:32]`** ✓、**L2270 keygen 写入→`[:32]`** ✓、**L476 `_hash_text`→`[:16]`（非信任根，保持 64-bit）** ✓、**全文 hexdigest 截断恰好 3 处，无第四处信任根指纹计算** ✓、无内联指纹消费 ✓
- 组5 F-2 节选真实性 + N1 证据（8）：7 段 nonce 代码字面量在磁盘源码**逐字命中** → 交办材料引用的原文与真实源码一致；**`lstat`/`is_symlink`/`O_NOFOLLOW`/`lchmod`/`GetFileInformationByHandle` 全文均不存在** → N1 发现的代码侧证据成立

诚实边界（Hermes 自纠）：仅证明"引用代码与磁盘一致、换行无损 + F-5 无遗漏"；不证明审计报告推理正确；N1 symlink 为静态推理未构造 PoC；N4（43/43 vs 41/41 数字矛盾）Hermes 只能证明两边原文都存在，不能判定真值（实际 runner 输出为 **43/43**）。

---

## 二、关键结论

### F-5（C-5 128-bit 指纹）—— ✅ 闭合，无遗漏
两处指纹计算（live `human_pubkey_fingerprint` L588 + keygen 写入 CONTRACT.md L2270）均改 `[:32]`；D4 漂移哈希 `_hash_text` L476 保持 `[:16]`（与信任根无关）；全文仅 3 处 hexdigest 截断，无第 4 处信任根指纹。钉固值（128-bit）与 live 值（128-bit）一致性判定不变。

### F-2（C-2 离线 nonce-file 授权）—— ✅ 闭合（代码与材料一致）
`_confirm_keygen(st, args)` 新增 args 透传；缺 `--nonce-file` → rc=2；凭据 <16 字符 → rc=2；读即焚（`unlink`）防重放；`cmd_confirm` 顶部 `_require_tty()`（isatty）保留纵深防御。相对 v2.5.2 的 `input("YES")`，攻击从「喂管道/pty stdin」升级为「须写受保护路径」，难度显著提高。
- **诚实限定**：nonce-file 的安全前提是「文件位于 Agent 无写权限的受保护存储」。若 Agent 能写该位置则可伪造——与 C-1 诚实天花板同源。nonce-file 改进的是攻击门槛，不是根信任本身。

### 新增 N1【中】nonce-file 路径无 symlink 防御（新残留，待 PoC）
Hermes 指出：nonce 路径读取/删除未用 `lstat`/`O_NOFOLLOW`/`GetFileInformationByHandle` 等防符号链接手段。Agent 可在受保护存储位置放置指向其可控文件的符号链接（或链接 human-guard.json / nonce 路径），绕过"受保护存储"假设。属静态推理，需 KK 授权构造 PoC 实证。修复方向：读取/删除前用 `os.lstat` 校验非 symlink（Unix），Windows 用 `GetFileInformationByHandle` 检测 reparse point，或要求 nonce 路径为普通文件且非重解析点。

### N2 / N3【低，语义判断】pty 攻击面未完全闭合 / `_require_tty` 与 nonce 冗余
Hermes 认为：真正能喂 pty 的 Agent 仍可能在 TTY 内交互；`_require_tty`（isatty）与 nonce 在"纯管道"场景功能重叠。实现方观点：二者互补——`_require_tty` 挡纯管道 stdin，nonce 挡 pty-forgery（须写受保护路径），非空冗余。属语义判断，无断言可验伪。

### N4 / N8【低】测试计数口径矛盾 / `bad`/`add_fix`/`info` 异常行为未验 + sigcrypto.py 未读
N4：43/43 为真实 runner 输出（新增 `test_f2_nonce_gate` 3 断言 + 原 40 = 43）；"41" 为实现方预估偏差，不影响结论。N8：Hermes 未验证异常打印行为，且未读 sigcrypto.py 全文（建议后续审 sigcrypto 的私钥加密实现）——**已于 2026-09-28 由 Hermes 独立审计收口，裁定 ⚠️ CONDITIONAL，最小修复集 3 项，详见 `references/independent-audit-hermes-N8-sigcrypto.md`**。

---

## 三、评级与下一步

- **评级维持 ⚠️ CONDITIONAL**：F-2/F-5 已实跑验证闭合，但 C-1 根信任（循环论证）原封未动 + 新增 N1 symlink 残留。
- **待 KK 决策**：N1（symlink 防御）是否纳入下一轮；sigcrypto.py 私钥加密实现是否需独立审计（N8）。
- **诚实天花板（不变）**：完全失控 + 具文件/代码双写能力的 Agent 仍可双改写 human-guard.json + CONTRACT.md 钉固；真根信任需硬件令牌或人工带外核验。
