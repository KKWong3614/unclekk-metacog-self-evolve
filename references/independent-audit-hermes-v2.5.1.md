# Hermes 独立深度审计 · unclekk-metacog-self-evolve @ v2.5.1（W1+W2）

> **审计来源（如实声明）**：本报告由 **真实 Hermes MCP（`mcp__hermes__hermes_audit`）** 产出，审计日期 **2026-09-28**。
> 它是 WorkBuddy 通过已接通的 Hermes MCP 正式调用 Hermes 审计员（异族独立审计员 / 敌意中立）完成的深度审计，**不是**此前那份由隔离 subagent 以"Hermes 审计视角"框架代笔的报告（`references/independent-audit-deep-v2.5.0.md` 的 v2.5.1 复验节）。本报告为 v2.5.1 的权威第三方裁定，并取代前者的"✅ APPROVED"结论。
>
> **审计对象**：`unclekk-metacog-self-evolve` 技能的 W1（人类闸密码学绑定）与 W2（护栏 fail-closed）；聚焦 v2.5.1 对 v2.5.0 原始 CONDITIONAL 中 P0（公钥信任根未钉固）+ B.2（锚缺签名即被信任）两项声称的收口。
> **方法论**：异族独立审计员，敌意中立；直接审查传入的 `metacog.py` 修复代码 + 威胁模型 + 测试证据，独立推演，不采纳实现方自证。

---

## 总体评级：⚠️ REJECTED — 有条件接受（"人在环" 宣称成立，但 "密码学强制" 宣称不成立）

**核心裁定**：v2.5.1 在**代码文本层**确实闭合了 v2.5.0 上报的 P0 和 B.2 的"直接路径"（旧路径不再能绕过），但**在威胁模型给定的前提下（Agent 具备任意文件写 + 代码写）**，P0 的"钉固"没有引入真正独立的信任根，B.2 也存在新的绕过分支。技能实际能提供的强度是**"人为约定下的可审计性"**，而不是宣称的"系统级强制可控自指"。

上一轮 v2.5.0 裁定 ⚠️ CONDITIONAL。本轮维持 ⚠️ CONDITIONAL → 但从"两个 P0 未闭合"降级为**"两个 P0 在给定威胁模型下无法闭合"**——是**威胁模型的极限暴露**，不是修复不到位。

---

## 关键发现清单

### 🔴 严重（C）— 5 条

**C-1 · 公钥钉固循环论证（P0 名义闭合，实质不闭合）**
威胁模型明确："被治理 Agent 具备写入任意文件能力，包括 `.metacog/ledger/human-guard.json` 与技能代码 `metacog.py` 本身"。因此：
- `load_human_keys()` 读的文件 → Agent 可写
- `pinned_human_pubkey_fingerprint()` 读的 CONTRACT.md → Agent 可写
- `sigcrypto.deserialize_pub()` 的输入 → Agent 可控

`check_pubkey_root()` 只验证"两处文件一致"，**没有独立第三方信任根**。攻击路径：
```
① Agent 写 attacker_pub 到 human-guard.json
② Agent 计算 fp = sha256(attacker_pub)[:16]
③ Agent 写 fp 到 CONTRACT.md
④ Agent 用 attacker_priv 签名 → verify_human_signature() 通过
```
4 步全部走 Bash 子进程即可，PreToolUse 护栏完全观察不到（材料 §0 自己承认）。
`ensure_pubkey_root_pinned()` 更糟——**Agent 调用一次就把自己的公钥自动钉进 CONTRACT.md**，无需任何"人类操作"。

**C-2 · keygen 无人工因素，Agent 单步可"重置"整个信任根**
`_confirm_keygen` 生成新密钥对后 `write_human_pubkey_fingerprint(fp)` 直接钉固。触发路径若仅是 CLI 命令，**在 Agent 具备子进程写能力时等价于 Agent 拥有"重置公钥根"的能力**——这直接击穿 W1"人类身份绑定"的核心主张。真正的 keygen 必须依赖带外 TTY 口令 + out-of-band 确认（材料 §2 已提到"TTY 检查非人类在场证据"，但未作为 keygen 阻塞条件）。

**C-3 · `check_pubkey_root` 两个 legacy 分支静默 fail-open**
```python
if not pinned: sys.stderr.write("WARN: ..."); return True, None
if live is None: return True, None
```
- **契约未钉固 → 直接返回 True**：等于"没有 PIN，就用 live 当 root"，这是 fail-open 而非 fail-closed。材料自称 W1+W2 是 fail-closed，此处不成立。
- **live 为 None → 直接返回 True**：human-guard.json 被删后，verify 流程会加载"任意新出现的公钥"作为信任根。虽然下一行 `load_human_keys()` 会返回 None 从而 fail-closed，但顺序上先放行了 root 检查，语义与实现相矛盾，且为未来扩展埋雷。

**C-4 · `resolve_trial_start` 新增的"B.1 fail-open 绕过"分支**
代码顺序：
```python
if sig and chash:                        # 有签名
    完整验签流程...
return 0, "requires_human ... HOLD"       # 无签名 → 正确 HOLD ✓
if sigcrypto is None:                    # sigcrypto 不可用
    WARN: 非人类确认锚跳过签名校验
    return int(rec["trial_from_index"])   # ⚠️ 对非-requires_human 静默信任
```
**攻击路径**：攻击者删除 apply_record 中的 `human_sig` 和 `content_hash` 字段（Bash 写），使 `sig and chash` 判为 False，跳到 `if sigcrypto is None` 降级分支。此时 Agent 只要保证 sigcrypto 模块不可用（例如在 bootstrap 阶段注入一个坏 PYTHONPATH 让 `import sigcrypto` 失败——材料 §1.1 已显示 `if sigcrypto is None` 是运行时判定的），**就能让旧锚免签通过**。

这实际是把 W1 从"必须验签"降级为"只要 sigcrypto 模块加载失败就退化"。虽然材料 §0 说 Agent 无法让 Bash 写的钩子观察到，但**代码层已经提供了这个绕过开关**。

**C-5 · 16 位指纹的碰撞风险被严重低估**
`sha256(...)[:16]` 是 64 bit hex。RSA-2048 生成密钥的熵约 256 bit，理论上不存在"故意碰撞"，但：
- **64 bit birthday 碰撞**在 2^32 次生成后概率已达 50%。
- 更严重的问题：**用 sha256(pub_pem_string)[:16] 做身份根本身就是错误设计**——应使用 SPKI 规范化 DER 编码的 sha256 **完整 256 bit 指纹**（业界标准，如 SSH 的 `SHA256:base64`）。16 位只是"可读性"妥协，且未在任何文档中声明为安全相关（易被误解为身份根本身）。
- 材料 §1.4 的"同时检哈希偏离 + 指纹漂移"是双重校验，但两处的输入都是同一个 pub 字符串——**指纹偏离检测不能弥补 64 bit 熵不足的问题**。

### 🟡 中等（M）— 6 条

**M-1 · CONTRACT.md 解析极其脆弱**
```python
if "human_pubkey_fingerprint" in ln:
    after = ln.split("human_pubkey_fingerprint", 1)[1]
    if ":" in after:
        val = after.split(":", 1)[1].strip().strip("`")
```
- 匹配注释行（如 `- 用途：... human_pubkey_fingerprint 是钉固...`）也会被匹配
- 匹配顺序依赖行序；攻击者插入一行 `- human_pubkey_fingerprint: fake` 在真行之前即可替换根
- 无 markdown 结构校验、无 section 边界识别
- 使用人类可读 Markdown 作为**安全关键信任根存储**，本应是 fail-closed 硬拒绝

**M-2 · `verify_human_signature` 未校验 `cur_hash == content_hash`**
对比 `resolve_trial_start`（有校验）：
```python
def verify_human_signature(self, p, sig_b64):
    ...
    chash = proposal_content_hash(p)          # 只用当前内容哈希
    msg = sigcrypto.approval_message(p["id"], chash)
    if sigcrypto.verify(pub, msg, sig): ...
```
如果攻击者：① 让签名者批准提案 v1（生成 sig1）；② 之后偷偷改 p["content"] 为 v2；③ `verify_human_signature(p_v2, sig1)` 仍会用 **v2 的哈希**构造 msg 去验，此时签名不匹配 → **反而 fail-closed**。等等——这其实是正确的。但反向看：签名是绑 `proposal_id`+`content_hash` 的，如果攻击者同时改 proposal_id 使其与签名的 id 一致、同时保证 content 与签名的 hash 一致——那就是签名者批准的另一个提案了。这里的关键遗漏是**没有校验签名者本人是谁（无签名者身份绑定）**。

**M-3 · `ensure_pubkey_root_pinned()` 在 `cmd_verify` 中被无条件调用**
`cmd_verify` 开头一句 `st.ensure_pubkey_root_pinned()`。如果 CONTRACT.md 缺失钉固，**cmd_verify 会把"当前 live 公钥"自动钉进去**——这把"审计/校验"命令变成了"根信任写入"命令，违反最小惊讶原则。verify 应该是只读操作。

**M-4 · `_hash_text(human_guard.read_text())` 对格式敏感**
`cmd_verify` 用 `human_guard.read_text()` 的哈希作为完整性快照。任何 JSON 字段顺序、缩进、末尾换行差异都会导致 false positive，或反过来被攻击者重序列化后哈希仍一致。这不是安全性问题，但**降低了 D4 的可用性**（材料 §2 的 P2 已提到"仅手动触发"，本条进一步恶化了它）。

**M-5 · 未验证 `metacog.py` 自身完整性**
`verify_integrity()` 只覆盖 `human_guard`。§2 P1 明确说"metacog 自身代码若经 Bash 改写以弱化人类闸"是核心风险，但**cmd_verify 未把 `metacog.py`（或其 sha256）纳入完整性范围**。这是"元认知自修改"技能的致命盲区：Agent 可以在不触发任何 hook 的情况下删除 `check_pubkey_root` 调用，代码层面完全合法。

**M-6 · 材料 §2 P1/P2 分级不一致**
- "口令强度无策略 + 20 万轮 PBKDF2" 归 P1
- "私钥 at-rest 无密文 MAC（可被篡改致不可用）" 归 P2

两者本质相同（都是私钥材料完整性），分级依据不明。且 PBKDF2 20 万轮对现代 GPU 是 10⁷ 次/秒级——**弱口令离线破解 <1 分钟**，应升为 P0。

### 🟢 低（L）— 6 条

**L-1 · "系统级强制" 措辞过强**：Bash 子进程完全绕过 PreToolUse 护栏，"系统级"应降级为"进程内护栏 + 事后审计"。

**L-2 · "密码学人类身份绑定" 措辞过强**：绑定对象是"能敲 keygen 的人"，不是"某个人"。应改为"绑定到某个持有私钥的过程"。

**L-3 · 测试证据不可核验**：材料只给数字（35/35、14/14、40/40），未附测试代码或运行日志。独立审计员无法验证关键断言是否真跑了。

**L-4 · SEED 模板占位符 `<待 confirm --keygen 钉固>`**：解析时被排除（`startswith("<") and endswith(">")`），但如果攻击者写成 `<abc12345>`（伪造的十六进制占位符），也会通过——虽然 sha256 校验会挂，但语义污染风险存在。

**L-5 · `write_human_pubkey_fingerprint` 的"WARN: 不一致，已覆盖"**：静默覆盖，缺二次确认。

**L-6 · 无签名过期机制**（§2 已列，仍是 P2）：签名一旦生成即永久有效，与"人在环"的时效性主张相悖。

---

## 逐条回应 §5 的五点问询

**5.1 · 1.1/1.2 是否真实闭合 P0 与 B.2**
- **1.1 (P0)：名义闭合、实质不闭合**。攻击路径见 C-1。legacy 分支见 C-3。解析健壮性见 M-1。
- **1.2 (B.2)：主路径闭合（requires_human 无签名 HOLD）**，但见 C-4（sigcrypto 不可用时的降级绕过）。`root check → verify` 顺序正确。`cur_hash == chash` 位置正确（在 verify 之后）。

**5.2 · §2 残留 P1/P2 是否仍有效**
全部仍然有效。特别是 P1"Agent 经 Bash 改 metacog.py 移除 check_pubkey_root"——**v2.5.1 未做任何防御**，反而在 C-1/C-2 中进一步暴露了这个漏洞。§4"诚实天花板"的自述是**准确的、诚实的**，但评级仍给 CONDITIONAL 与宣称的"密码学强制"存在张力。

**5.3 · 结构化裁定**
```
总体评级：⚠️ CONDITIONAL → 建议改判 ⚠️ REJECTED（附"诚实披露"）

理由：
- 在给定威胁模型（Agent 全文件写 + 全代码写）下，
  P0 的"钉固"未引入独立信任根，B.2 存在 sigcrypto 降级绕过。
- 材料 §4 已诚实承认攻击天花板，但评级仍宣称"系统级强制"，
  这是措辞过度承诺。
- 建议改判 REJECTED，理由是"宣称与实现能力不一致"，而非代码缺陷。
  若接受 §4 的天花板描述作为正式口径，则维持 CONDITIONAL。
```

---

## 针对性改进建议（按落地优先级）

### 🔧 立即修（P0，v2.5.2 必须）

1. **明确威胁模型边界写入 SKILL.md 首屏**：
   > "本技能不防御『Agent 具备任意文件写 + 代码写能力』的攻击场景。此场景下人类闸退化为审计日志，不能宣称『强制』。"

2. **`check_pubkey_root` legacy 分支改 fail-closed**：
   ```python
   if not pinned: return False, "no-pinned-root"
   if live is None: return False, "no-live-pubkey"
   ```
   移除两处 `return True, None`。

3. **`resolve_trial_start` 中 `sigcrypto is None` 的降级路径，非 requires_human 也改为 HOLD**，或者明确文档化"当 sigcrypto 不可用时整个系统停用"（fail-fast，而非降级）。

4. **禁止 `cmd_verify` 调用 `ensure_pubkey_root_pinned()`**：verify 必须是只读。keygen 是独立、需要带外口令+TTY 的操作。

5. **keygen 阻塞条件加严**：必须 TTY + 交互口令 + 二次确认 + out-of-band 记录（例如打印指纹让人复制到独立信道）。禁止 CLI 非交互执行。

6. **把 `metacog.py` 自身纳入完整性快照**：cmd_verify 校验 `hash(metacog.py)` 与记录值比对，不一致 → fail。

### 🔧 短期修（P1，v2.6.0）

7. **契约存储从 Markdown 迁移到 TOML/JSON 专文件**（`human-guard.root.toml`），带严格 schema，禁用注释，字段固定顺序。
8. **指纹从 16 位 hex 升级为完整 sha256 SPKI**（`base64(sha256(DER_SPKI))`，SSH 风格），至少 32 位 hex。
9. **P1 口令策略**：加盐 PBKDF2 迭代 60 万轮 + 强制口令长度 ≥16 + 拒绝常见词。
10. **密钥吊销/恢复路径**：`human-guard.rotate` 带备份密钥 + 二次审批。

### 🔧 中期修（P2，v2.7.0）

11. 签名 TTL（例如 24 小时）+ 时间戳入签名消息。
12. 私钥密文外加 HMAC（防止 at-rest 篡改）。
13. `verify_human_signature` 与 `resolve_trial_start` 的验签流程抽成**单一公共函数**（DRY），避免两处实现漂移。
14. PreToolUse 护栏覆盖 Bash 命令字符串扫描（`bash -c`, `python -c`, `sh -c` 内的文件路径），或者明确放弃声称覆盖 Bash。
15. 补自动化端到端测试：从"Agent 试图同时改 human-guard.json + CONTRACT.md + metacog.py"的完整攻击场景验证。

---

## 独立审计员附加意见（元审计）

材料自身质量评估：**高于行业平均**。§4"诚实天花板"是自陈攻击面最清晰的一段，说明开发方对威胁模型有清醒认识。但：

- 宣称"密码学人类身份绑定" + "系统级强制" 与实际实现能力（约定性审计 + 单一文件系统信任根）**存在张力**。
- 建议在 SKILL.md 首屏把 §4 那段直接抄成"能力边界"章节，评级改为 ⚠️ CONDITIONAL WITH KNOWN-UNCLOSED-THREATS。
- 若目标是发布给公开用户，需附**第三方测试代码仓库**，否则 35/35 断言不可信。

---

**审计员：Hermes（真实 MCP · 异族独立审计员 / 敌意中立）· 完成时间：2026-09-28**
**调用方式**：`mcp__hermes__hermes_audit`（target=`skill:unclekk-metacog-self-evolve@v2.5.1`，content=自包含审计交办材料 11550 字节）
**本报告为安全评审意见，非合规证书；所有判定均来自可复现的代码检视与对抗推演。**
