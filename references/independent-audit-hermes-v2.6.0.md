# 异族独立审计 · unclekk-metacog-self-evolve v2.6.0

- 审计角色：异族独立审计员（代码级、敌意批判、立场中立）
- 审计对象：`skill:unclekk-metacog-self-evolve` v2.6.0（外部锚破 C-1）
- 审计日期：2026-09-30
- 审计方法：读盘交叉核对（`trust_root.py` 全文 261 行、`metacog.py` 关键段 L510-660 / L655-734 / L2464-2550、`test-trust-root.py` 全文 336 行、`CHANGELOG.md` v2.6.0 节、`SKILL.md` L246-252）
- 纪律声明：本审计**未执行**任何被测 `.py`；结论全部基于静态读盘 + 逻辑推演。所有行号均已逐字符核对磁盘源码。

---

## 总体评级：有条件通过（Conditional Pass）· **不上调，且新增 3 项 HIGH 待办**

v2.6.0 的**工程实现是扎实的**：外部锚抽象清晰、fail-closed 分支齐备、N1/N2' 落地、225/225 回归无回归、诚实边界三条披露到位。**但代码级读盘发现 3 项 HIGH 缺陷未被 CHANGELOG / SKILL.md 披露**，其中两项使「破 C-1」的核心主张在 hsm 单独模式下**根本不成立**，第三项使外部锚**可被攻击者静默关闭**。

关键判断：**v2.6.0 没有破 C-1，它把信任假设从「系统自举」平移到了「两个未实测的目录写权限隔离」。** 这是一个位置的转移，不是信任根的外部化。评级维持 CONDITIONAL 是正确的；**但现有「三条诚实边界」不足以覆盖本版真实缺陷，必须扩充为六条**。

---

## 关键发现清单

### HIGH-1 · hsm 证明密钥硬编码泄漏 → hsm 单独模式下 C-1 完全 OPEN

**证据（`trust_root.py` L43, L46-53）：**

```python
_SIM_DEVICE_ATTEST_KEY = b"__SIM_DEVICE_ATTEST_ROOT__DO_NOT_USE_IN_PROD__"

def _sim_attest_sign(pub_serialized: str) -> bytes:
    return hmac.new(_SIM_DEVICE_ATTEST_KEY, pub_serialized.encode("utf-8"), "sha256").digest()

def _sim_attest_verify(pub_serialized: str, sig: bytes) -> bool:
    expected = _sim_attest_sign(pub_serialized)
    return hmac.compare_digest(expected, sig)
```

`HsmTrustRoot.attestation_ok`（L126-134）唯一接受签名形态是 `HMAC(_SIM_DEVICE_ATTEST_KEY, pub_serialized)`。**该密钥是明文硬编码常量，位于 Agent 可读（且 M-5 快照内的）源码文件里。** 攻击者只需**读**（不需写）即可获得证明签名能力。

**攻击路径（hsm 单独模式，无任何 oob）：**
1. 读 `trust_root.py` → 获得 `_SIM_DEVICE_ATTEST_KEY`
2. 篡改 `human-guard.json` → 得到任意 `pub_serialized`
3. 自算 `hmac(key, pub_serialized)` 写入 `attestation_path`（前提：该目录可写）
4. `attestation_ok` → `(True, None)` → `check_pubkey_root` 放行

**结论：hsm 单独模式下的「外部不可伪造」不成立。** CHANGELOG L24「设备证明，A 类」「本代码以软件 HSM 模拟器仿真（仅测试用）」的表述掩盖了一个致命事实：**代码中不存在切换到真机密钥的任何路径**——没有插件点、没有密钥注入接口、没有后端注册表。`_sim_attest_verify` 是唯一验证函数，永远用常量。

**根因定性：这不是「未实测」，这是已静态证明的设计缺陷。**

### HIGH-2 · 真机令牌在当前代码下必然 fail-closed → 可验证性声明不可达

`CHANGELOG.md` L24 声明「hsm 证明文件由硬件令牌对公钥签名生成」；`SKILL.md` L248 声明「hsm 设备证明文件由硬件令牌对公钥签名生成（本代码以软件 HSM 模拟器仿真，仅测试用；真机验证为人工步骤）」。

**静态证明该声明不可达：** 真机令牌用其自身非对称私钥签名 → 产物不可能等于 `HMAC(_SIM_DEVICE_ATTEST_KEY, pub_serialized)`（对称构造，不同算法族、不同密钥）→ `_sim_attest_verify` 必然返回 False → `attestation_ok` 返回 `("attestation-forged")` → `check_pubkey_root` **fail-closed 拒绝**。

**唯一能生成合法证明的函数是 `write_device_attestation`（`trust_root.py` L201-209），它就在 Agent 可执行代码里，用同一常量签名。** 也就是说：

- 真机令牌生成的证明 → **必然被拒**（不可用）
- Agent 自签的证明 → **必然通过**（不安全）

**二者必居其一，无论哪种 C-1 都没闭合。** 这是 HIGH-1 与 HIGH-2 的同一根因两个面：**hsm 后端没有真机实现路径**。

「真机验证为人工步骤」这一表述构成**过度承诺 / 不可验证声明**——它把一个已可静态证伪的不可用问题，包装成「待办事项」。

### HIGH-3 · 配置损坏 / 未知 backend 静默降级到 legacy → 外部锚可被攻击者静默关闭

**证据一（`trust_root.py` L73-76）：**
```python
try:
    d = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    return cls()  # 解析失败 → 保守回退 legacy（fail-safe）
```

**证据二（`trust_root.py` L172, L180-181）：**
```python
if not cfg.enabled or cfg.backend == "legacy":
    return None
...
# 未知 backend → 保守返回 None（fail-safe，不静默放行未知模式）
return None
```

`build_trust_root` 返回 `None` 的语义是「走 legacy 分支」（`metacog.py` L712 `if ext is not None:`）。注释自称「fail-safe」，**实际效果是把姿态降级到 C-1 未闭合的弱模式**。

**攻击路径（ENABLE 模式）：**
1. 攻击者写坏 `ledger/trust-root.json`（非法 JSON，或 `backend: "weird"`）
2. `TrustRootConfig.load` 返回 legacy 默认 / `build_trust_root` 返回 `None`
3. `check_pubkey_root` 走 legacy 分支 → 回到 v2.5.8 系统自举
4. 攻击者随即自由篡改 `human-guard.json` + `CONTRACT.md` + `integrity.json`，无任何外部锚拦截

**攻击成本：一次文件写入。** 而攻击者对 ledger/ 目录的写能力是 C-1 威胁模型的既定前提（他能改 human-guard.json / CONTRACT.md / integrity.json）。

**这是 fail-safe 与 fail-closed 的根本性混淆。** 在已显式启用外部锚的安全姿态下，配置损坏必须 **fail-closed（拒绝一切）**，而非静默回退到弱姿态。当前实现等于给攻击者留了一条「降级开关」。

---

### MEDIUM-1 · N1 符号链接防护不完整（新攻击面未覆盖）

`metacog.py` L2491-2496 只对 `nonce_file` 做了 `is_symlink()` 检查：

```python
_np = Path(nonce_path)
if _np.is_symlink():
    bad(...)
    return 2
```

v2.6.0 **新引入的两个外部锚路径均未做 symlink 检查**：
- `HsmTrustRoot.attestation_ok`（`trust_root.py` L121-126）：`os.path.isfile(ap)` + `Path(ap).read_text()` —— 若 `attestation_path` 是 symlink 指向 Agent 可控路径，结合 HIGH-1 的已知密钥，攻击者可写伪造证明到可控路径再挂 symlink。
- `OobTrustRoot.oob_confirmed`（`trust_root.py` L152-154）：`os.path.join(...)` + `os.path.isfile(tok)` —— 无 symlink 检查，且 `oob_token_dir` 本身也未做 `is_symlink()` 检查（目录级 symlink 可指向 Agent 可控目录）。

N1 的防护哲学（防 symlink 重放）**没有随 v2.6.0 新增面扩展**，这是 v2.6.0 引入的净新缺口。

### MEDIUM-2 · oob 令牌无内容校验 / 无时效 / 无一次性消费

`trust_root.py` L149-154：
```python
def oob_confirmed(self, challenge: str) -> bool:
    if not self.oob_token_dir:
        return False
    tok = os.path.join(self.oob_token_dir, challenge + ".token")
    return os.path.isfile(tok)
```

**文件存在即通过。** 无内容校验、无过期时间、无 nonce 消费。对比 nonce_file 的「读即焚」（`metacog.py` L2506 `_np.unlink()`），oob 令牌是**持久有效的**。

后果：一旦某挑战的 token 文件落盘，对**同一公钥**的该挑战**永久放行**。虽然 challenge 绑定 `pub_serialized`（换公钥→新 challenge→需新 token，此路径防得住），但对**不改变公钥的攻击**（如复用合法旧签名）无防护。安全强度从「文件存在性」判定，远低于系统其他部分的姿态。

### MEDIUM-3 · hsm 单独模式（无 oob）安全姿态远弱于文档暗示

`--enable-external hsm`（无 oob）被 `check_pubkey_root` L716 允许跳过 oob 检查（`oob_token_required()` 返回 False），仅靠 `attestation_ok`。结合 HIGH-1（密钥可自签），**hsm 单独模式等价于无外部锚**。

文档 L21「hsm+oob: 二者叠加（令牌为主根 + 带外为恢复闸/二级锚）」暗示 hsm+oob 才是完整姿态，但**代码不阻止单独 hsm**。应在 keygen 时强制：hsm 必须配 oob，或禁止单独 hsm。

---

### LOW-1 · oob challenge 仅绑定公钥，不绑操作类型 / 时间 / nonce

`trust_root.py` L108：
```python
return hashlib.sha256(("oob|" + pub_serialized).encode("utf-8")).hexdigest()[:16]
```

challenge 与操作无关。同一公钥下所有关键操作共享同一 challenge → 同一 token 文件长期有效。与 MEDIUM-2 叠加。

### LOW-2 · 外部锚模式下 CONTRACT.md 钉固降为仅告警，破坏 v2.5.2 C-3 纪律

`metacog.py` L725-728：
```python
if live != pinned:
    sys.stderr.write("...CONTRACT.md 钉固指纹与当前公钥不符，但外部锚已通过...")
```

v2.5.2 的 C-3 修复把「未钉固/不匹配」从 fail-open 改为 fail-closed（`CHANGELOG` L117 明确「不再 fail-open 放行」）。v2.6.0 在外部锚模式下把「不匹配」改为**仅 stderr 告警**——stderr 可被吞、可被重定向，等同 fail-open。**这是一次向后退步的纵深削减**，虽文档已披露「降级」，但未承认其降低防御等级。

### LOW-3 · 代码卫生：模块内 `__import__("datetime")`

`trust_root.py` L196：
```python
"updated_at": __import__("datetime").datetime.now().isoformat(),
```
模块顶部已 `import json / os / base64 / hashlib / hmac`，唯独 datetime 用内联 `__import__`。无功能影响，坏味道。

---

## Q1-Q5 裁决

### Q1 · v2.6.0 是否真正「破」了 C-1 的循环论证？

**否。它把信任假设从「系统自举」平移到了「外部锚文件/令牌的存在」，但外部锚的不可伪造性本身未闭合。**

三层拆解：
1. **legacy 默认模式**：C-1 原封未动（文档已披露 ✓）。
2. **hsm 单独模式**：C-1 完全 OPEN（HIGH-1：密钥硬编码可自签）。
3. **oob 单独模式**：C-1 形式上闭合，但**完全依赖「Agent 无写权限目录」这一未实测的部署假设**——一旦该假设不成立，攻击者自写 token 即过。
4. **hsm+oob 模式**：需同时满足两个前提。hsm 因 HIGH-1 可自签（不构成外部锚），实际**退化为 oob 单独模式**的安全姿态。

「彻底失控者还能在 Agent 无写权限目录外造不出锚」——**在 hsm 模式下不成立**（密钥在源码，无需目录写权限即可自签内容，只缺目录写权限落盘；而 hsm+oob 下两个目录都需无写权限）。**真正的外部不可伪造需要：证明密钥不在任何 Agent 可读处 + 令牌由独立于本机的主体签发。当前实现两条都不满足。**

### Q2 · fail-closed 对完全失控管理员是否真成立？

**逻辑分支成立，但前提依赖未实测的部署假设，且 HIGH-3 提供了绕过 fail-closed 的降级通道。**

- fail-closed 分支代码正确（缺文件/伪造/不匹配均 False）。
- 但前提「外部锚存储目录 Agent 确实无写权限」**未实测**，且**代码中无任何机制验证或强制该前提**——没有权限校验、没有 ACL 断言、没有启动期检查。这是一个纯粹的部署契约，无运行时保护。
- HIGH-3 更进一步：即使前提成立，攻击者也能通过**破坏配置**强制降级到 legacy，绕过整个外部锚。
- **应继续维持 CONDITIONAL**，且理由不止「未实测」——还包括 HIGH-1/2/3 三项已静态证明的缺陷。

### Q3 · 评级是否应维持 CONDITIONAL？

**是，维持 CONDITIONAL，不上调。** 理由：

1. 三项 HIGH 均未被现有「三条诚实边界」披露。现有边界披露的是「模拟器/默认关闭/CONDITIONAL」，**漏掉了密钥泄漏、真机不可用、配置降级三条真实缺陷**。
2. 「hsm 为软件模拟器、oob 依赖人工目录」这一披露方向正确，但**严重低估了 hsm 模拟器的破坏性**——它不是「待替换的占位」，而是「代码中唯一的验证路径」，替换它需要新增后端，不是填参数。
3. 225/225 same-author 自证已如实披露 ✓，这一点诚实。

**不上调的硬理由：HIGH-2 证明文档声明的功能（真机令牌）在当前代码下不可用，这是可验证性声明错误，不是待实测项。**

### Q4 · 回归风险是否覆盖？N1/N2'/C-2/legacy 兼容是否可靠？

- **N1**：**不可靠（MEDIUM-1）**。只覆盖 nonce_file，未覆盖 attestation_path / oob_token_dir（含目录级 symlink）。v2.6.0 引入的净新缺口。
- **N2'**：逻辑可靠。`_integrity_chain_ok`（L555-577）prev 链连续 + 尾条 key/hash 匹配，断链检测正确。但与 C-1 同构（chain.jsonl 与 integrity.json 同 ledger 同权限），静止态整目录被控时自指链断裂——CHANGELOG L21 已披露 ✓。
- **C-2**（带外核验）：oob 后端是 C-2 的实质实现，但仍有 MEDIUM-2（无内容/时效校验）与未实测目录权限两个缺口。
- **legacy 兼容**：`build_trust_root` 返回 `None` 的语义正确、测试覆盖 ✓；**但 HIGH-3 说明 legacy 回退可被攻击者诱导触发**，「兼容」与「降级攻击面」共用同一条路径，这是设计上的危险耦合。

### Q5 · 总体评级 + 必须写入的诚实边界

**评级：维持 ⚠️ CONDITIONAL（不上调）。** 新增 3 项 HIGH 待办 + 3 项 MEDIUM 待办。

**必须写入 SKILL.md / CHANGELOG 的诚实边界（现有 3 条 → 扩充为 6 条）：**

1. （保留）hsm 后端以软件 HSM 模拟器仿真，真机设备证明须由硬件令牌生成。
2. （保留）外部锚默认关闭，C-1 在默认模式仍 OPEN，须显式启用才闭合。
3. （保留）评级维持 CONDITIONAL。
4. **（新增·HIGH-1）** hsm 证明密钥 `_SIM_DEVICE_ATTEST_KEY` 硬编码于 `trust_root.py` 源码，Agent 可读 → hsm 单独模式下 C-1 仍 OPEN；hsm 必须与 oob 叠加使用，单独 hsm 无安全意义。
5. **（新增·HIGH-2）** 当前代码**无法接受真机令牌签名**（验证固定为 HMAC-SHA256 常量密钥），真机部署必然 fail-closed；真机支持需新增后端与密钥注入接口，非「人工步骤」可完成。
6. **（新增·HIGH-3）** 外部锚配置（`ledger/trust-root.json`）损坏或 backend 未知时**静默回退 legacy**（C-1 未闭合模式）；该回退可被攻击者利用。启用外部锚后配置损坏应 fail-closed，当前实现未满足。

---

## 针对性改进建议

### P1（阻塞性，须随 v2.6.1 落地）

1. **关闭 hsm 密钥泄漏（HIGH-1 + HIGH-2 同源）**
   - 删除 `_SIM_DEVICE_ATTEST_KEY` 常量，改为**后端注入式密钥源**：`HsmTrustRoot(attestation_path, key_provider)`，`key_provider` 为可插拔接口（测试用常量实现、生产用真机令牌实现）。
   - `attestation_ok` 不接受硬编码密钥签名，签名算法随后端走（真机 → RSA/Ed25519 非对称验签；模拟 → HMAC）。
   - 明确标注：在 `key_provider` 未替换为真机前，hsm 模式**不得启用**。

2. **配置损坏 fail-closed（HIGH-3）**
   - `TrustRootConfig.load` 解析失败时：若检测到「曾启用」痕迹（如目录存在 / 其他标志），返回 `enabled=True, backend="__corrupt__"` 使 `build_trust_root` 返回一个**恒拒实例**，而非 legacy 默认。
   - `build_trust_root` 对未知 backend 返回**恒拒实例**（`attestation_ok` 恒 `(False, "unknown-backend")`），而非 `None`。
   - 区分两种 None：「从未启用」（legacy）与「启用但损坏」（恒拒），不得共用。

3. **N1 扩展覆盖（MEDIUM-1）**
   - `HsmTrustRoot.attestation_ok`：`ap` 及其父目录 `is_symlink()` 检查。
   - `OobTrustRoot.oob_confirmed`：`oob_token_dir` 及 `tok` 均 `is_symlink()` 检查。
   - 统一收口到一个 `_assert_real_path(p)` 辅助函数，避免同类模式漏网（与 v2.5.8 记录的「recurring pattern」教训一致）。

### P2（安全性提升）

4. **oob 令牌增加内容校验 + 一次性消费（MEDIUM-2 + LOW-1）**
   - token 文件内容须为 `hmac(session_key, challenge)` 或 `challenge + nonce` 格式，校验通过才放行。
   - 校验通过后**原子消费**（`os.replace` 到 `.used` 后缀或删除），防重放。
   - challenge 绑定操作类型与时间窗（`sha256("oob|" + op + "|" + window + "|" + pub_serialized)`）。

5. **禁止单独 hsm（MEDIUM-3）**
   - `_confirm_keygen` 中 `--enable-external hsm`（无 oob）→ 直接拒绝并指路 hsm+oob。
   - 或强制 hsm 恒叠加 oob。

6. **外部锚模式下 CONTRACT.md 不符升级为 WARN + 计数（LOW-2）**
   - 不符时不仅 stderr，还写入 D4 完整性记录，使篡改可审计追踪。
   - 或明确承认「外部锚模式下 CONTRACT.md 降级为审计线索而非闸门」，并在文档中标注纵深削减。

### P3（代码卫生）

7. `trust_root.py` 顶部补 `import datetime`，删除 L196 内联 `__import__`。

---

## 审计自纠记录

本审计过程中我修正了两处自身推断偏差，如实记录：

- **N3-a**：初判「oob 令牌目录路径遍历风险」（`os.path.join(oob_token_dir, challenge + ".token")` 可能被 `..` 穿越）。复算后撤回：challenge 是 `sha256(...)[:16]` 十六进制串，字符集仅 `[0-9a-f]`，不含 `/`、`..`、空字节 → **无遍历**。撤回该项。
- **N3-b**：初判「`HsmOobTrustRoot` 多重继承 MRO 可能导致方法解析错误」。复算后确认：`attestation_ok` 来自 `HsmTrustRoot`、`oob_token_required`/`oob_confirmed` 来自 `OobTrustRoot`、`challenge_for` 来自 `TrustRoot`，三路无冲突 → **继承正确**。撤回该项。

以上两处撤回说明：**审计结论必须以算术/代码复算为凭，不得凭直觉定性**。本审计保留的 HIGH-1/2/3 三项均经源码逐行复算（密钥常量位置、验证函数签名形态、配置回退分支返回值语义），非推断。

---

## 审计纪律声明

- 本审计**未执行**任何被测 `.py`（含 `test-trust-root.py`），结论全部基于静态读盘 + 逻辑推演。
- 本审计执行方为 Hermes 自身，**非真·异族独立审计**（与被审对象同栈、同生态），与 CHANGELOG 既有披露一致。
- HIGH-2 的「真机令牌必然 fail-closed」为**静态证明**（算法族不匹配 + 密钥源固定），不依赖运行实测，可被任何读者以同样方式复算验证。

---

[Hermes · 异族独立审计员] Audit Completed at 2026-09-30T00:00:00+08:00
