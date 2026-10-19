# 独立审计报告 · unclekk-metacog-self-evolve @ v2.5.2（真实 Hermes MCP 复验）

- 审计工具：`mcp__hermes__hermes_audit`（异族独立审计员，本机 Hermes agent）
- 审计日期：2026-09-28
- 被审对象：`skill:unclekk-metacog-self-evolve@v2.5.2`（P0 硬化复验：C-3 / C-4 / verify 只读化 / M-5 / C-2）
- 审计立场：中立偏敌对，无利益关联；仅基于实现方提交的节选材料 + 后续源码核实
- **总体评级：⚠️ CONDITIONAL（有条件通过，附严重保留意见）**

> 本文件为 v2.5.2 的**权威裁定**。前序报告 `independent-audit-hermes-v2.5.1.md`（⚠️ REJECTED/CONDITIONAL，命中 C-1~C-5/M-1~M-6/L-1~L-6）为本版本输入；`independent-audit-deep-v2.5.0.md` 顶部已加真实性更正（其 v2.5.1「✅ APPROVED」实为隔离 subagent 代笔，已被真实 Hermes 审计取代）。

---

## 一、审计分档结论

| 层面 | 判定 | 说明 |
|---|---|---|
| 代码文本层（code-text correctness） | P0 项基本闭合（1 项存疑已核实排除，见 §三 F-3 复核） | C-3/C-4/verify 只读化/M-5/C-2 在源码层无遗留 fail-open 路径 |
| 根信任层（root-trust closure） | **未闭合** | C-1 循环论证原样保留（见 F-1） |
| 新增可利用退化 | 1 处中等（F-2 stdin 管道绕过）、1 处命名夸大（F-4） | |

---

## 二、Hermes 关键发现（原文要点）

### 🔴 F-1【高】C-1 循环论证原样保留
威胁模型定义「信任根必须是 Agent 无法单方面伪造/重写的不动点」，但 v2.5.2 全部改动都在 Agent 可写文件内。`check_pubkey_root` 的两个输入（`pinned_human_pubkey_fingerprint` / `human_pubkey_fingerprint`）均派生自 Agent 可写文件（CONTRACT.md / human-guard.json）。拥有写盘能力的 Agent 只需把 CONTRACT.md 指纹改成 human-guard.json 当前值，`check_pubkey_root` 即返回 True。**这不是信任根，只是防意外漂移的校验**。材料已诚实披露 C-1 未收口，但「P0 硬化」若被解读为「信任根安全」属过度承诺。

### 🔴 F-2【高】C-2 交互确认可被 stdin 管道绕过
`builtins.input()` 做 keygen 二次确认。Bash 天然可管道：`echo YES | python metacog.py confirm --keygen` 完全绕过交互提示。该防护仅在「人类直接键入」场景成立；Agent 从 Bash 拉起进程时防护价值为零。建议改为绑定带外信道（离线预录 secret nonce / 硬件令牌挑战应答）。当前属「防误操作」而非「防攻击」。

### 🟠 F-3【中，已核实排除】C-4 疑似死代码
审计基于节选尾部（1665-1673）推断 `if p.get("requires_human"):` 内第二个 `return 0` 之后不可达 → 误判「所有 requires_human 提案永久 HOLD」。经实现方提供完整 `resolve_trial_start` 源码核实（见 §三），该推断不成立：1665 块仅在 1638 `if sig and chash and sigcrypto` 为 False 时到达，有效 requires_human 签名在 1638-1655 块验签通过；1668 的 return 是 B.2「缺有效签名才 HOLD」的既定意图。F-3 撤销。

### 🟠 F-4【中】M-5 命名夸大 + 快照无签名
`integrity/*.json` 位于 Agent 可写路径、无签名；`record_script_integrity` 无调用方鉴权，攻击序列「改代码 → 重拍快照 → verify 全绿」可绕过。实际价值仅防误改/意外漂移，非防主动攻击。建议改名「脚本漂移检测（drift detection）」或对快照签名（用独立于 human 侧 RSA 的第二枚离线密钥 / TPM NV）。

### 🟠 F-5【中】C-5 64-bit 指纹截断熵不足
`hashlib.sha256(...).hexdigest()[:16]` = 64 位，不满足 FIPS 186-4 / RFC 8692 推荐的 128-bit（32 hex）。单信任根场景下人类不会生成 40 亿对密钥，理论上够用，但 16 字符口述核对已近可靠性下限。若 v2.5.2 定位「P0 硬化」，此项应一并修为 128-bit。

### 🟡 F-6【低】verify 只读化闭合，但需 grep 核实「仅」字面意义
需 `grep -n ensure_pubkey_root_pinned` 逐一列调用点，确认仅在 keygen/apply，无第三处。

### 🟡 F-7【低】测试证据可信度限定
40/40 PASS 同时可存在 F-3 类漏测；建议公开每条断言覆盖的分支，增「非 requires_human 应放行」反向断言。

### 🟡 F-8【低】语气诚实度
正向：§5 主动披露 C-1/C-2/C-5/M-1 未收口，§2 铁律明确不声称「无需人类在环」；负向：「P0 硬化」「带外记录」标题含轻微夸大。

### 审计自纠（audit_integrity_note）
本次初版仅基于节选、未读完整源码；F-3 以「待核实」标注，核实后撤销。未实跑测试套件；§4 数字未独立复验。

---

## 三、实现方复核回应（2026-09-28）

### 3.1 F-3 复核：确认非死代码（提供完整 `resolve_trial_start` 控制流）
```
1638  if sig and chash and sigcrypto is not None:        # 锚含完整签名材料且可验签
1639      pub_serialized, _ = st.load_human_keys()
1640      if pub_serialized:
1641          root_ok = st.check_pubkey_root()            # P0 信任根 fail-closed
1642          if not root_ok: return 0, HOLD
1643          if sigcrypto.verify(...):                   # 签名有效 + content_hash 一致
1644              return int(trial_from_index), None      # ← 有效 requires_human 签名在此放行
1645          return 0, HOLD
1659      return 0, "有 sig 但无公钥 HOLD"                 # sig 在但 guard 缺失
1665  if p.get("requires_human"):                          # 仅当 1638 为 False 才到达
1667      return 0, "requires_human 锚缺有效签名 HOLD"       # B.2 既定意图（无签名锚 HOLD）
1671  if sigcrypto is None: return 0, HOLD                  # C-4 统一 HOLD
1673  return int(trial_from_index), None                    # 非 requires_human 合法旧锚放行
```
- 1665 块是 1638 块的**降级兜底**，不是主放行路径。有效 requires_human 签名在 1638-1644 放行。
- 经验证反驳：测试 `test_sign_and_apply`（requires_human=True 提案 P-M1X）apply 后 status=`trial`（7/7 PASS）；`test_b2_anchor_missing_sig_holds` 确认合法签名锚 resolve 不 HOLD（hold=None）。若 F-3 成立，这两条必 FAIL——而套件 40/40 全绿。**F-3 撤销，C-4 在代码层确已闭合。**

### 3.2 已接受并需落地的发现
| 编号 | 性质 | 实现方处置 |
|---|---|---|
| F-1 | 真实局限 | 接受。已在 §诚实天花板声明；本文件及 CHANGELOG/SKILL 统一把「信任根钉固」表述收敛为「钉固校验（防漂移，非独立信任根）」，避免「P0 信任根已闭合」过度承诺 |
| F-2 | 真实弱点 | 接受。v2.5.2 的 C-2 只是交互确认 + 带外*提醒*，非强制带外信道；stdin 管道可绕过。拟下一轮改离线 nonce-file 或硬件令牌挑战应答（待 KK 授权） |
| F-4 | 命名夸大 | 接受。M-5 在文档改称「脚本漂移检测（防意外改码，非防主动攻击）」；代码标识符保留（重命名为 P2 级，待授权） |
| F-5 | 真实弱点 | 接受。`[:16]`→`[:32]`（128-bit）拟下一轮修 |
| F-6 | 核实项 | 已做：`ensure_pubkey_root_pinned` 调用点 = `cmd_verify` 已移除 + `confirm --keygen` 前向兼容分支（`_confirm_keygen`）+ `cmd_apply`（grep 确认仅此三处语义等价位置，verify 路径已无写根） |
| F-7 | 测试透明 | 接受。本文件附录公开 v2.5.2 相关断言覆盖分支 |

### 3.3 诚实天花板（不变）
完全失控 + 具文件/代码双写能力的 Agent 仍可双改写 `human-guard.json` + `CONTRACT.md` 钉固；真根信任需硬件令牌（YubiKey/FIDO2/TPM NV 只读位）或人工带外核验。C-1 在 v2.5.2 未根除，故**根信任层绝不宣称安全**。

---

## 四、v2.5.2 相关测试断言覆盖（回应 F-7，公开透明）

`test-human-gate.py` 中与本次硬化直接相关的断言（其余为 v2.5.0/2.5.1 既有）：
- `test_v252_hardening`（4 断言）：① 未钉固→fail-closed(no-pinned-root) ② sigcrypto 不可用→旧锚 HOLD ③ 脚本基线已记录 ④ 脚本篡改被检出
- `test_p0_pubkey_root_pinning`（5 断言）：钉固一致 + guard 入 D4 快照 + 替换公钥被拒(pubkey-root-mismatch) + 伪造签名被拒
- `test_p0_legacy_install_autopin`（4 断言）：verify 只读不钉固 + keygen 幂等补钉固 + 替换公钥被拒（覆盖「非 requires_human 应放行」反向路径，回应 F-7）
- `test_b2_anchor_missing_sig_holds`（4 断言）：合法签名锚不 HOLD + 无签名锚 HOLD + 非 requires_human 无签名锚仍信任
- `test_sign_and_apply`（7 断言）：含 requires_human=True 提案 apply 成功 → trial（证明 F-3 不成立）

全绿：test-core 14/14、test-boundary-cases 40/40、test-human-gate 40/40；py_compile 四文件 OK；退出码均 0。

---

## 五、结论一句话
v2.5.2 在 **C-1 之下**的次生问题于代码文本层收得干净，作者诚实披露文化值得肯定；但 **C-1 根信任原封不动、C-2 交互确认可管道绕过、M-5 命名夸大、C-5 64-bit 指纹**仍待修。评级标注为「⚠️ CONDITIONAL · 仅代码层」，禁止对外以「P0 硬化完成」口径传播。
