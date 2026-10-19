# Hermes 同栈审计 · unclekk-metacog-self-evolve v2.7.1
## C-1 主攻击向量 fail-closed + HIGH-1 删除检出 复验裁决

**审计时间**：2026-10-02（Hermes 同栈执行）
**被审对象**：`C:\Users\Administrator\.workbuddy\skills\unclekk-metacog-self-evolve`（SKILL.md `version: 2.7.1`）
**审计任务**：统一复验请求（只评不改）— 5 项裁决问题 + 5 个通用维度
**审计方式**：读盘 + 实跑端到端对抗探针 4 卷（`D:\hermes\temp\metacog-v271-audit\`）

---

## 0. 独立性标注（必读）

**本报告不是独立第三方审计。** Hermes 与被审技能同栈、同盘、同作者工作流；审计依据是文本级 + 代码实跑，非隔离环境黑盒。结论仅供参考，不能替代 KK 的外部裁定。

**本轮未做的事**（纪律遵守声明）：
- 未修改被审目录任何文件（只读）。
- 未跑作者的 `hermes-verify-audit-v2661*.py`（改跑自己的探针）。
- 未跑全量 24 文件 509/509（只跑 `test-trust-root.py`）。
- **未能实测 Windows symlink 创建**：`os.symlink` 抛 `WinError 1314 客户端没有所需的特权`，`cmd /c mklink` 同样失败（本机未启用开发者模式 / 无符号链接特权）。symlink 相关结论只能由静态推理 + POSIX 语义推断，**标注为未实测**。

---

## 1. 总体评级

> ## ⚠️ **有条件通过**（CONDITIONAL）— 主攻击向量 fail-closed 成立；HIGH-1 删除检出**可被威胁模型内直接绕过**（新 N1，HIGH）

**逐条结论**：

| # | 裁决问题 | 结论 |
|---|---|---|
| 1 | 主攻击向量（证明存储→可写域内）是否 fail-closed | **成立** ✅。实测 `(False, 'external-anchor-inside-writable-root')`，经真实 CLI 入口 |
| 2 | HIGH-1 删除检出是否完整 | **不完整** ❌。`_external_anchor_deleted` 只覆盖「两锚文件缺失 + D4 快照未动」这一个半区。三个半区实测中两个**未拦截** |
| 3 | 诚实边界是否准确 / CONDITIONAL 是否合理 | **评级合理，但披露不完整** ⚠️。诚实边界遗漏两条新边界（HIGH-1 基线自指、静默降级改写），且 `hsm+oob`「最强姿态」在契约违反下反而最弱 |
| 4 | 残留 v2.7.0 过度主张 | **存在** ❌。3 处残留，其中 2 处位于 `check_pubkey_root` 执行路径内（L789 注释 + L794 **运行时告警字符串**） |
| 5 | 综合评级 | **⚠️ 有条件通过**（见下） |

**为何是「有条件通过」而非「不通过」**：`anchor_storage_outside_root` 结构性闸门确实按设计工作（14 项路径枚举 0 误判、0 漏放），主攻击向量被真实阻断，v2.7.0→v2.7.1 是一次有效的安全推进。C-1 根因（`root_pubkey` 位于可写 `ledger/trust-root.json`）v2.7.1 本就声明不修，CONDITIONAL 维持与威胁模型一致。

**为何不能是「通过」**：N1 是一个**新的、威胁模型内的 HIGH-1 绕过**——它不是残余假设，而是「攻击者只需 4 次 unlink」即可让外部锚静默回到 C-1 未闭合状态。作者测试套件 110/110 全绿与该绕过共存，是「全绿 ≠ 无洞」的直接例证。

---

## 2. 审计阻塞项（材料自足性）

按 `independent-audit/references/material-self-sufficiency.md` 规则，以下未定义引用无法从材料自行判定，故**不对其依赖的闭合结论给「可采信」判断**。但本轮已读到实际磁盘代码，故逐项给出实测结论而非阻塞：

| 未定义符号 | 材料内给出？ | 磁盘定位 | 影响 |
|---|---|---|---|
| `TrustRootConfig.load` | 摘要提及 | `trust_root.py` L238-265 | 决定 `enabled`/`backend` 解析语义，已实读 |
| `_anchor_paths` | 未展示 | L519-527 | 决定闸门覆盖哪些路径，已实读 |
| `_assert_real_path` | 摘要（截断在 L291 `...`） | L272-297 | **N2 关键**。摘要被截断，实读后确认 `resolve()` 存在 |
| `_load_verifier` | 未展示 | L206-217 | 决定无 verifier 时行为，已实读 |
| `attestation_ok` 完整体 | 未展示 | L366-393 | 兜底检查，已实读 |
| `record_integrity` / `self.integrity` | 未展示 | `metacog.py` L480-527 | **N1 关键**。`self.integrity = root/ledger/integrity.json` — 在可写域内 |
| `_external_anchor_deleted` | 摘要 | L598-608 | **N1 关键**。只 `exists()`，不哈希比对 |
| `_offline_root` / `_enable_external` / `_with_tty_and_passphrase` | 未展示 | `test-trust-root.py` L104-113 / L245-257 / L80-90 | 探针复用其真实入口，已实读 |
| `read_json` / `_append_integrity_chain` | 未展示 | L190 / L529-544 | D4 链在 `ledger/integrity-chain/chain.jsonl`，同处可写域 |
| brief 中 `_assert_real_path`「摘要」末尾 `...` | 截断 | — | **材料不自足**：N2 结论依赖被截断行，必须读盘才能裁定 |

**材料自足性判定**：**不足**。brief 给出的是节选代码 + 逐字声称，其中 N2（`_assert_real_path` 是否真的 `resolve()`）与 HIGH-1 完整性（`_external_anchor_deleted` 判定条件）**都必须读盘才能裁定**。本轮已读盘，故给出裁定；但需记录：若仅凭 brief 文本，HIGH-1 的完整性**不可采信**——因为 `_external_anchor_deleted` 的完整实现未展示，而它的全部语义就在一个未展示的 `read_json(self.integrity)` 里。

---

## 3. 关键发现（按严重度）

### 🔴 N1 [HIGH] HIGH-1 删除检出可被威胁模型内直接绕过 — 基线自指（Self-Referential Baseline）

**这是本轮最重要发现，brief 的 5 项裁决问题中未预见到。**

`_external_anchor_deleted`（`metacog.py` L598-608）的判定源是 `self.integrity` = `self.root / "ledger" / "integrity.json"`（L480-481），D4 哈希链在 `self.root / "ledger" / "integrity-chain" / "chain.jsonl"`（L532）。**两者与它所保护的 `ledger/trust-root.json` / `ledger/.external-anchor-enabled` 同处一个可写目录。**

因此攻击者持 `ledger` 写权限时，HIGH-1 的「基线」和「被保护对象」是同一权限域——**基线不提供任何独立保证**。这是「闸门参数自破自」模式（`independent-audit/references/security-fix-reverification.md` 第七种自证模式）的直接实例。

**实测**（`hermes-verify-audit-v271.py` A4，经真实 CLI `cmd_confirm --keygen` + `_enable_external` + `record_external_anchor_integrity` 全链入口）：

```
C2 基线：合规外部锚 + D4 基线已记录     → ok=True  reason=None
   D4 快照中外部锚键 → {"ledger/trust-root.json":"68860c4a9185530a",
                        "ledger/.external-anchor-enabled":"8445907852202cf4"}
攻击：unlink integrity.json → unlink trust-root.json → unlink .external-anchor-enabled
   _external_anchor_deleted → False          ← 基线已随快照一起消失
   external_trust_root() → None → legacy 分支
   check_pubkey_root → (True, None)          ← C-1 完全重开，且 stderr 无任何 WARN
```

**作者测试为何全绿**：`test_external_anchor_deletion_failclosed`（L683-715）只 `unlink` 两个锚文件，**保留 `integrity.json`**。它覆盖的是 4 个半区里唯一 1 个被拦截的半区。

**半区枚举（实测）**：

| 半区 | D4 快照 | 锚文件 | 实测结果 |
|---|---|---|---|
| ① 仅 json 基线，两锚皆删 | 在 | 删 | **(True, None) — 未拦截** |
| ② 仅 sentinel 基线，删 json 留 sentinel | 在 | 半删 | (False, 'external-anchor-deleted') ✓ |
| ③ **快照 + 锚全删（威胁模型内）** | **删** | **删** | **(True, None) — 未拦截** |
| ④ 从未启用（legacy） | 无 | 无 | (True, None) ✓ 不误拦 |

**为何这是 HIGH 而非 MEDIUM**：`ledger` 写权限**正是 C-1 威胁模型的全部前提**（`root_pubkey` 之所以危险就在它于 `ledger/`）。在这个模型内，HIGH-1 的「已建立锚被删」防护在 4 次 `unlink` 后完全失效，且**零告警**。

**修复方向**（供 KK 参考，本轮只评不改）：
- 基线需脱离可写域才能成立：`integrity.json` / `chain.jsonl` 移至 root 外只读介质，或改由离线根私钥签名后与根证明并置（与 `attestation_path` 同契约）。
- 或把判定从「文件是否存在」改为「哈希是否与基线一致」——当前 `_external_anchor_deleted` 只看 `exists()`（实测 `_hash_text` 未出现在该方法体内），攻击者**改写而非删除**时（见 N2）同样失守。
- `_append_integrity_chain` 的链哈希在 `ledger/integrity-chain/` 内，同域可清，无法作为独立证据；`check_pubkey_root` 也**完全不调用** `applies_integrity_ok` / 任何链校验（实测：仅 `resolve_trial_start` L1868 调用它）。

---

### 🟠 N2 [MEDIUM] 「改写而非删除」使外部锚静默降级，无任何闸门拦截

删除被 HIGH-1 部分覆盖，**改写完全无防护**。实测（`hermes-verify-audit-v271-c.py`）：

```
攻击者把 trust-root.json 改写为 {"enabled": false, "backend": "legacy"}（文件保留）
   _external_anchor_deleted → False          ← 文件存在，不算删除
   external_trust_root() → None → legacy 分支 ← 外部锚静默失活
   check_pubkey_root → (True, None)          ← C-1 重开，stderr 零 WARN
```

三条路径实测：

| 攻击变体 | 实测 |
|---|---|
| A：`enabled=false` + `backend=legacy` | **(True, None) — 静默重开** |
| B：清空 `root_pubkey`，保留 `enabled`+`backend` | (False, 'external-anchor-no-verifier') ✓ 拦截 |
| C：换 evil `root_pubkey` + root 外自签证明 | (False, 'oob-confirmation-required') — 拦截但**依赖攻击者没配齐**（见 N3） |

**为何 A 失守**：`TrustRootConfig.load` 中 `enabled` 与 `backend` 是合法字段（L256-259），`build_trust_root` 对 `enabled=False`/`backend=legacy` 的设计语义就是「返回 None → legacy 分支」——这是**设计契约**，不是 bug。但对安全语义而言，「攻击者把已建立的外部锚改写为关闭」与「删除」效果等价，当前无任何闸门区分二者。

---

### 🟠 N3 [MEDIUM] 「root 外但 Agent 仍可写」残余在 `backend=oob` 下 C-1 **完全**重开；作者测试未覆盖该后端

闸门是**纯路径几何**检查（实测 `anchor_storage_outside_root` 源码：不含 `_is_protected`、不含 `os.access`，仅 `Path.resolve()` + `is_relative_to`），对 root 外路径**恒放行**，完全无法感知可写性。可写性检查在 `build_trust_root` 内走 `_is_protected` → `_deploy_warn`，**WARN-only 不 fail-closed**（v2.7.1 文档 L449-454 已自述此设计取舍）。

因此诚实边界声称的「残余 `root` 外但 Agent 仍可写」在契约违反时**不是残余、而是完整重开**。实测：

| 后端 | 证明存储 root 外 + 攻击者可写 + 持 evil 离线根私钥 | 闸门 | `check_pubkey_root` |
|---|---|---|---|
| `hsm` | ✓ | `None`（放行） | **(True, None) — 完全重开** |
| **`oob`** | ✓ | `None`（放行） | **(True, None) — 完全重开** |
| `hsm+oob` | ✓ | `None` | (False, 'no-device-attestation') — 仅因该用例 attestation 文件未落盘 |

**`backend=oob` 是新的未覆盖分支**：作者 C-1 对抗测试 `test_attacker_swaps_root_pubkey` 只用 `backend="hsm"`（L670），`test_external_anchor_deletion_failclosed` 只用 `"hsm+oob"`（L697）。**没有任何测试在契约违反下攻击 `oob` 单独后端。**

`oob` 单独后端在契约违反下比 `hsm` 更脆弱：攻击者**只需要写 `oob_token_dir`** 就能自签通过——不需要 attestation 文件。这是「主根 + 二级锚叠加不构成冗余」原则的又一次实例（与 v2.6.6.1 N1 同构：两个锚依赖同一条未运行时强制的部署契约）。

**附带正结论**：v2.6.6.1 的 N1（OOB challenge 无秘密）已被 v2.7.0 的 RSA 签名令牌真正修好——实测 attack 用 `evil_priv` 签名才通过，无密钥者无法伪造。v2.7.0 那项修复是真实的。

---

### 🟡 N4 [LOW-MEDIUM] 代码内残留 3 处 v2.7.0 过度主张，其中 2 处位于执行路径

| 位置 | 内容 | 影响 |
|---|---|---|
| `metacog.py` L789 | 注释：`# 外部锚通过 = 根信任外部化成立（C-1 已真正破于逻辑层，权威来自离线根私钥）` | 文档 |
| `metacog.py` **L794** | **运行时 stderr 告警字符串**：`"信任根以外部锚为准（C-1 已真正破于逻辑层），请核对 CONTRACT.md 是否被误改。"` | **用户可见、每次运行输出** |
| `metacog.py` L2614 / L2855 | 注释 + CLI `help` 文本：`v2.7.0 启用外部锚（破 C-1 逻辑层）` | 用户可见 |

L789 尤其矛盾：它紧接在 v2.7.1 诚实边界（L746-749）**同一方法内**声明「C-1 未真正闭合」之后 40 行。L794 是**运行时代码**，不是注释——用户会真实看到「C-1 已真正破于逻辑层」。

**正面**：v2.7.1 声明的撤回范围（`trust_root.py` 模块 docstring、`RsaRootVerifierProvider` docstring、`external_trust_root`/`check_pubkey_root` docstring、`cmd_confirm` 提示、SKILL/CHANGELOG/HANDOFF）经 grep 逐项核实**均已正确撤回**。撤回不彻底仅限上面 4 处。

---

### 🟡 N5 [LOW] 闸门 3 个豁免分支均为 fail-safe，但依赖下游兜底；`enabled=False`/`legacy` 豁免与 N2 同构

实测枚举 14 项：

| 输入 | 闸门 | 方向 |
|---|---|---|
| root 内绝对路径 / root 本身 | REJECT | ✓ |
| root 前缀相似串（`root+"SIBLING"`，非子路径） | ALLOW | ✓ 正确不误判 |
| `hsm+oob` 仅 oob 在 root 内 | REJECT | ✓ 双路径都查 |
| root 外真实/不存在/`../` 逃逸路径 | **ALLOW（豁免）** | ⚠️ 依赖下游 |
| `enabled=False` / `backend=legacy` | **ALLOW（豁免）** | ⚠️ = N2 同构 |

豁免路径 fail-safe 实测：`resolve` 失败 → `continue`；`root_resolved` 失败 → `return None`。下游兜底：`attestation_ok` 的 `_assert_real_path` 返回 False → `attestation-symlink`/`no-device-attestation`。实测 dangling 情形 `attestation_ok` 返回 `(False, 'no-device-attestation')`，**方向正确**。

但闸门把「路径不存在」当作豁免（`except Exception: continue`），把「未启用」当作豁免——两者混在同一 `return None` 语义下，`None` 同时表示「通过」和「不适用」，调用方无法区分。这是文档可读性缺口，非绕过。

---

### 🟡 N6 [LOW] 评级连续 6 轮「CONDITIONAL 维持」，已失去区分力

`CHANGELOG.md` 记录 5 轮 + 本轮 = 6 轮 Hermes 复验，**全部**「CONDITIONAL 维持」，评级从未移动。本技能已有真实撤回记录（v2.6.4→v2.6.5 撤回 Windows `chmod` over-claim；v2.7.0→v2.7.1 撤回「闭合 C-1」；v2.6.6.1→v2.7.1 撤回「sim_key/oob」口径），故**自评批判确实有效**——这不是固化。

但 CONDITIONAL 已成为默认稳态：本轮 N1 是一个**新的 HIGH 绕过**，按严重度语义应考虑更严评级；而 N4 残留过度主张按披露语义应考虑更严。评级在两个方向上都未移动。

**处置**（不自行改动评级）：本轮显式声明该评级已失去区分力。若需要一个能真正移动评级的判定，同栈文本级审计方无法提供——因为 C-1 的根因（根公钥可写）不在软件层可解范围内。

---

### 🔵 N7 [INFO] `_assert_real_path` N2 修复正确，但 symlink 盲区未在 Windows 实测

实读 `trust_root.py` L272-297 确认 N2 已修：`is_symlink()` → `parent.is_symlink()` → `resolve()` → `normcase`/`realpath` 二次确认 → `rp.exists()`。v2.6.6.1 N2（缺 `resolve()`）确已修复。

**未实测**：本机 `os.symlink` 抛 `WinError 1314`（无符号链接特权），`mklink` 亦失败。故以下结论为**静态推理**：
- 祖先链中段 symlink：`resolve()` 已能兜住（静态确认）。
- TOCTOU（check-then-use 间隙无 `O_NOFOLLOW`/fd 保持）：**仍存在**，`_assert_real_path` 返回后调用方另行 `Path(ap).read_text()`。
- POSIX 下祖先链 symlink 若 `realpath` 二次确认通过，仍可能判「受保护」——静态推断，未实测。

`_assert_real_path` 归一化枚举实测 9 项：大小写变化、双斜杠、尾部分隔符、`\\..\` 冗余、UNC 形式。UNC `\\.\C:/...` 与 `..` 冗余两项返回 False（拒绝），其余 True（接受）——**方向正确**，无绕过。

---

## 4. 逐条回答 5 项裁决问题

### Q1：主攻击向量下是否确实 fail-closed？有无绕过？

**主向量：成立 ✅**

实测经真实 CLI 入口（`cmd_confirm --keygen` → `_enable_external` → `write_root_attestation` → `check_pubkey_root`）：

```
攻击者换 root_pubkey + attestation_path 指向 ledger/ 内 + evil 自签
   → (False, 'external-anchor-inside-writable-root')   ✓ fail-closed
```

闸门插入点核实：`metacog.py` L704-707，在 `build_trust_root` **之前**，返回 `DenyTrustRoot(gate)`；`check_pubkey_root` L767-772 有 `DenyTrustRoot` 透传守卫，细分 reason 不被 oob 分支吞掉。

**brief 点名的绕过路径逐条实测**：

| 绕过设想 | 结论 | 依据 |
|---|---|---|
| root 外 symlink 回指可写域 | 闸门 `resolve()` 后 REJECT（静态确认，Windows 未实测 symlink）；且 `_assert_real_path` 双保险 | L553 `Path(p).resolve()` + L558 `is_relative_to` |
| 相对路径 `../` 绕过 `is_relative_to` | **不成立** ✓。闸门对双方各自 `resolve()`（L546 + L553），相对路径以 cwd 为基准解析后仍正确判定 | 实测 5 项相对路径，含 `..\..\up.json`、`.`、冗余 `..` |
| 大小写绕过 | **不成立** ✓。`is_relative_to` 在 Windows 大小写不敏感，且 `_assert_real_path` 另做 `normcase` | 实测 9 项归一化，无绕过 |
| `root+"SIBLING"` 前缀相似串 | **不被误判** ✓。`is_relative_to` 非字符串前缀比较 | 实测 ALLOW（正确） |
| **（brief 未列）root 外可写** | **闸门 0 拦截**，见 N3 | 结构性局限 |
| **（brief 未列）改写而非删除** | **无闸门**，见 N2 | 设计契约缺口 |

**审计自纠记录（诚实）**：探针第一卷 A3 曾把 `../SIBLING_IN_ROOT/x.json` 打成 `resolve_in_root=False` + `gate=REJECT` 的矛盾组合。复核后确认是 **FACT 打印时比较基准差异**（FACT 里的 `is_relative_to` 与闸门内的计算在同一调用中）——闸门双方各自 `resolve()`，判定自洽。**闸门无 bug，是我的观测打印有瑕疵。** 已修正为 C1 卷单独复核（`hermes-verify-audit-v271-c.py`），确认 `cwd = D:\hermes\temp\metacog-v271-audit`，`../SIBLING_IN_ROOT/x.json` 解析到 `D:\hermes\temp\...`（root 外）→ `gate=None` → 判定正确。

### Q2：HIGH-1 删除检出逻辑是否完整？

**不完整 ❌。** 4 个半区实测 2 个未拦截（见 N1 表格）。

**legacy 不误拦：正确 ✓** —— 从未启用外部锚时 `(True, None)`，无误伤。

**完整性缺口**：
1. **基线自指**（N1）：`integrity.json` 与 `trust-root.json` 同处可写域，4 次 `unlink` 即绕过。
2. **半区不对称**：仅覆盖「两锚文件皆删」半区；「仅删 json 留 sentinel」（实测 → `external-anchor-corrupt`，靠 `load()` 兜底）与「快照被删」半区均失守。这是 `references/material-self-sufficiency.md` 明确要求的「崩溃半区对称性检查」未覆盖的镜像半区。
3. **只查 `exists()` 不比对哈希**：`_external_anchor_deleted` 方法体内无 `_hash_text` 调用（实测静态确认）。因此「改写」比「删除」更易失守（N2 变体 A）。
4. **D4 哈希链未接入根信任通路**：`check_pubkey_root` 不调用 `applies_integrity_ok`，链校验仅在 `resolve_trial_start`（L1868）用于 applies 锚。`chain.jsonl` 与 `integrity.json` 同域可清，无法作为独立证据。

**「HIGH-1 已闭合」表述需修正**：CHANGELOG L13/L34、HANDOFF L135、SKILL L304 均写「HIGH-1 已闭合」。准确表述应为：**「HIGH-1 已闭合『攻击者仅删锚文件』这一个半区；删锚 + 删 D4 快照、以及改写配置两个相邻半区仍失守」。**

### Q3：诚实边界是否准确？CONDITIONAL 是否合理？

**评级合理，但披露不完整 ⚠️**（under-claim）。

边界声明本身准确的部分（已核实）：
- ✅ `root_pubkey` 仍位于可写 `ledger/trust-root.json` → C-1 根因未根除。**准确**。
- ✅ 软件层不声称默认部署下 C-1 已闭合。**准确**。
- ✅ 残余依赖 OS 权限隔离（部署契约）兜底。**准确**（且 `_is_protected` 确为 WARN-only，`build_trust_root` 内确认）。

**遗漏的两条边界**：
1. **未披露 HIGH-1 自身可在威胁模型内被绕过**（N1）。诚实边界说了「C-1 根因依赖部署契约兜底」，但没说「HIGH-1 这条新增防护的基线本身就在可写域内、4 次 unlink 即失效」。这是**本轮新增的披露缺口**。
2. **未披露 `hsm+oob`「最强姿态」在契约违反下反而最弱**（N3）：`oob` 单独后端下攻击者只需写一个目录，`hsm` 需写文件 + 目录，`hsm+oob` 需两者但 MRO 使 `attestation_ok` 解析到 `HsmTrustRoot` 版、攻击者须同时配齐。**「叠加构成冗余」的隐含假设不成立**——两个锚依赖同一条未运行时强制的契约。

**CONDITIONAL 维持是否合理**：**合理**。C-1 根因不在软件层可解范围（需 TPM/OS 信任源/独立只读介质），CONDITIONAL 是正确归类。但应**升级为「CONDITIONAL + 2 条新边界」**，而非「CONDITIONAL 维持」。

**降级（更松）不成立**：N1 是新 HIGH，方向相反。

### Q4：是否存在残留 v2.7.0 过度主张？

**存在，4 处**（N4）。撤回覆盖率约 92%（声明撤回的 12 处全部已撤回），残留集中在 `metacog.py`：
- L789 注释（同一方法内与 L746 诚实边界**自相矛盾**）
- **L794 运行时 stderr 字符串（用户可见）**
- L2614 注释、L2855 CLI `--enable-external` help 文本

另：`scripts/trust_root.py` L3/L9/L357/L488/L508/L650 等处的「破 C-1」措辞是**历史版本标记**（`v2.6.0 破 C-1`、`v2.7.0：... → 无法自造（真正破 C-1）`），属于变更历史语境，不构成过度主张——**不列入发现**，但 L357（`HsmTrustRoot` 类 docstring，非历史标注而是当前行为描述）建议一并对齐。

### Q5：综合评级

**⚠️ 有条件通过（CONDITIONAL）**，附 2 条新边界：
1. HIGH-1 删除检出仅覆盖「删锚文件」半区；删 D4 快照（`ledger/integrity.json`）即可在威胁模型内绕过（N1，HIGH）。
2. `root` 外但可写的残余在 `backend=oob` 下 C-1 完全重开，非「残余」而是完整失守；作者测试未覆盖 `oob` 单独后端（N3，MEDIUM）。

---

## 5. 五个通用维度

### 5.1 逻辑漏洞
- **自相矛盾**（N4 L789）：同一方法内 L746 声明「C-1 未真正闭合」、L789 注释「C-1 已真正破于逻辑层」。
- **循环论证/基线自指**（N1）：HIGH-1 的信任依据（D4 快照）与被保护对象同权限域——**这是本轮唯一的结构性逻辑漏洞**，且是 brief 未预见的。
- **循环论证未被 v2.7.1 修好，且被正确承认**：C-1 根因（根公钥自举于可写域）明确留作未闭合，诚实边界准确。**这是本技能最突出的优点**——一个跨 6 轮迭代、3 次真实撤回、并主动承认自己 v2.7.0 头条主张错误的工程纪律。
- **未证前提**：闸门把「路径不在 root 内」等同于「路径受保护」。等价关系不成立（N3）——几何条件≠权限条件。文档 L449-454 已诚实说明此取舍，故非隐瞒，但诚实边界未把该等价的**后果**（C-1 完全重开 vs 残余）说清。

### 5.2 安全隐患
- **命令执行**：无。`_assert_real_path` 全 fail-safe；`sign()` 显式 `NotImplementedError`；`attestation_ok` 全量 try/except → fail-closed；`load()` 收窄异常 + `RecursionError` + `isinstance(d, dict)` + `is True` 严格布尔。这几点做得扎实。
- **凭据泄露**：`RsaRootVerifierProvider.sign()` 从机制上杜绝 Agent 自造证明；`_restrict_credential` 在 Windows 上诚实承认 `chmod 0o400` 只置只读位、对同用户攻击者 moot（L572-576 文档明确）。
- **越权/绕过**：N1（HIGH）+ N2（MEDIUM）+ N3（MEDIUM）。
- **注入**：`_append_integrity_chain` / `write_trust_root_config` 走 `json.dumps`，无字符串拼接注入面。
- **供应链**：纯 stdlib，`_deploy_warn` 无网络调用。
- **数据外泄**：无网络出口。
- **DoS**：`load()` 已补 `RecursionError`（病态超深嵌套 JSON → fail-closed，实测 4/4 PASS）。`_anchor_paths` 遍历数量固定（≤2），无遍历放大。
- **N3 降级导入对称性**（正面）：`import trust_root` 在函数体内 try/except → `(False, "external-anchor-corrupt")`，v2.6.6.1 N3 已修。但 `sigcrypto` 的降级保护在 `metacog.py` L1854-1860 有专门 fail-closed 分支，`trust_root` 侧只有 `external_trust_root` 一处 try/except——**纪律基本对称，非发现**。

### 5.3 偏见与 AI 味
- **过度承诺**：残留 4 处（N4），其中 L794 是运行时字符串。
- **回避不确定性**：无。诚实边界 8 条 + 3 次真实撤回，是本技能最强的特征。
- **套话堆砌**：文档有工程味（版本号、行号、理由、取舍说明齐全），非 AI 味。
- **立场偏见**：CHANGELOG L13 主动记录「KK 裁定先收尾、复验暂缓、本版以 self-attested 收尾」，并**明确标注「非独立审计、未经 Hermes 同栈复验」**——这本身就是反偏见行为，值得肯定。
- **幻觉**：未检出。`110/110` 声称经独立复跑**真实确认**（见 §6）。

### 5.4 规范性
- **MCP 协议**：不适用（纯 Python CLI）。
- **skill 规范**：`SKILL.md` frontmatter `version: 2.7.1` 与 CHANGELOG 一致（v2.6.6.1 曾出现 SKILL/CHANGELOG 版本不一致，本轮已对齐 ✓）。
- **编码规范**：`#!/usr/bin/env python3` + `PYTHONHOME/PYTHONPATH` 清理 + `sys.stdout.reconfigure(encoding="utf-8")` + Windows/POSIX 双分支 + 中文注释带版本溯源。**规范度高**。
- **文档规范**：CHANGELOG 按版本倒序、每条带验证证据、诚实边界编号化（⑦⑧）、HANDOFF 含下一步动作与依赖。**规范度高**。
- **可追溯性缺口（N9）**：`references/` 下 Hermes 复验报告**最新只到 `independent-audit-hermes-v2.6.2.md` + `audit-v2.6.6-hermes-indep.md`**。**v2.6.3–v2.6.5、v2.7.0、v2.7.1 的 Hermes 复验报告均未落盘**——6 轮复验中有 4 轮只有 SKILL/CHANGELOG/HANDOFF 的转述。与 v2.6.6.1 审计发现的「证据链断裂」问题**同一模式、未修复**（v2.6.6.1 只落了 1 份）。本报告落盘后可补齐 v2.7.1 这一轮。
- **Git**：该目录**非 git 仓库**（`git log` 失败），无本地版本历史。SKILL 主仓在 `D:\hermes\skills` 有 `.git`，但本技能实体在隐藏目录 `.workbuddy` 下，两者非同一仓库。冻结态无法用 git 追溯。

### 5.5 可用性与完整性
- **开箱即用**：`test-trust-root.py` 独立可跑、helper 自包含、无外部依赖、无硬编码密钥。✓
- **缺失步骤**：`backend=oob` 的 C-1 对抗测试缺失（N3）；HIGH-1 的快照被删/配置被改两个半区测试缺失（N1/N2）。
- **未定义引用**：见 §2 阻塞项，11 个符号，全部已读盘裁定。
- **不可验证声明**：`110/110` — **已独立复跑确认真实**（非 dry_run，退出码 0）。这是本次材料中**唯一**的量化声称，且它通过验伪。
- **Windows 平台**：`_restrict_credential` 诚实承认 Windows `os.chmod` 语义限制；`_is_protected` 诚实承认 Windows 目录 readonly 不阻止写入、`os.access` 对目录不可靠，故保持 WARN-only（L449-451）。**这是本轮审计中最成熟的一处平台自觉**。
- **未实测项**：Windows symlink（`WinError 1314` 无特权）。N7 结论标注为静态推理。

---

## 6. 独立验证：作者声称核验

| 作者声称 | 我的核验 | 结果 |
|---|---|---|
| `test-trust-root.py` 110/110 PASS | 实跑 `PYTHONHOME="" PYTHONPATH="" python test-trust-root.py` | ✅ **110/110 PASS，退出码 0** |
| 新增 2 项对抗测试 | L653 / L683 存在，L737-738 已注册进 main 运行器 | ✅ |
| 闸门插入点 L702-707 | 实读 L701-707 精确匹配 | ✅ 行号可信 |
| HIGH-1 闸门 L759-762 | 实读 L761-762 精确匹配 | ✅ |
| D4 记录与检出 L591-608 | 实读 L591-608 精确匹配 | ✅ |
| N2 `_assert_real_path` 已 `resolve()` | 实读 L285-297，`resolve()` 存在 | ✅ **v2.6.6.1 N2 已修** |
| N3 `import trust_root` try/except | 实读 L767-770 | ✅ **v2.6.6.1 N3 已修** |
| SKILL.md version = 2.7.1 | 实读 L5 `version: 2.7.1` | ✅ |
| 「110/110 无用例覆盖篡改 root_pubkey」（v2.7.0 缺口）已补齐 | `test_attacker_swaps_root_pubkey` 覆盖 | ✅ 主向量已覆盖 |
| **（作者未声称）HIGH-1 完整** | 半区枚举 4 项实测 | ❌ **2/4 半区失守** |
| **（作者未声称）`oob` 后端 C-1 安全** | 实测 | ❌ **完全重开** |

**「全绿 ≠ 无洞」实证**：110/110 PASS 同时存在 1 个 HIGH 绕过 + 2 个 MEDIUM 绕过。作者用例覆盖了闸门的**拒绝**分支（A1）和 HIGH-1 的**一个**半区（④），漏掉了 3 个半区与 1 个后端。这正是 `references/security-fix-reverification.md` 的教训。

---

## 7. 读盘清单与未读区间（可追溯性自曝）

**实际读盘（绝对路径）**：

| 文件 | 覆盖 | 行数 |
|---|---|---|
| `scripts/trust_root.py` | L136-196, L199-297, L355-430, L500-619 | 723（约 40%） |
| `scripts/metacog.py` | L476-527, L580-640, L690-819, L1858-1879 | 2946（约 15%） |
| `scripts/test-trust-root.py` | L1-113, L245-257, L618-754 | 985（约 30%） |
| `SKILL.md` | grep 全文（C-1/评级/验证相关） | 111695 B |
| `CHANGELOG.md` | grep 全文 + L1-40 | 143917 B |
| `HANDOFF.md` | grep 全文 | 36381 B |
| `CONTRACT.md` | grep（ledger 写权限） | 5787 B |

**未读区间**：`trust_root.py` L1-135（KeyProvider/sigcrypto 绑定）/ L431-499 / L620-723；`metacog.py` 约 2400 行（verdict/episode/apply/CLI 主体，L527-580、L819-2403、L2403-2946 除零星片段）；`test-trust-root.py` L113-245、L257-618、L754-985；`SKILL.md` 全文逐行未读（仅 grep）；`CONTRACT.md` 全文未逐行读（仅 grep「写权限」0 命中——**该文件可能未定义威胁模型的 ledger 写权限边界，值得补**）。

**用户提到但实际不存在**：无。brief 中所有引用符号均在磁盘上找到对应实现。

**验证方式区分**：
- **实跑确证**：A1 主向量、A3 路径枚举 14 项、A4/A5 半区枚举、A7 静态结构、B1 相对路径复核、C2/C3 静默降级、D1/D2/D3 后端枚举、D5 闸门结构、`test-trust-root.py` 110/110。
- **静态推理（未实跑）**：B2/B3 Windows symlink 路径（`WinError 1314` 无特权，无法创建）、TOCTOU 间隙、B4 UNC/冗余分隔符的语义后果。

---

## 8. 针对性改进建议（可落地）

**P1 — HIGH-1 基线外置（修 N1）**
```
方案 A（最小改动）：record_external_anchor_integrity() 把外部锚基线写入
  root 外路径（与 attestation_path 同契约的 Agent 无写权限目录），
  _external_anchor_deleted 从该外部基线读取，而非 self.integrity。
方案 B（更强）：把「外部锚已建立」的标记由离线根私钥签名，与 attestation
  并置于 attestation_path；D4 快照仅作冗余，不作判定源。
验证用例（必须新增）：
  - 删 trust-root.json + sentinel + integrity.json → 必须 fail-closed
  - 删 trust-root.json + sentinel + integrity-chain/chain.jsonl → 必须 fail-closed
```

**P2 — 配置改写防护（修 N2）**
```
把 _external_anchor_deleted 的判定从 exists() 改为哈希比对：
  基线哈希 != 当前 trust-root.json 哈希 → fail-closed("external-anchor-modified")
  需新增 reason 枚举：external-anchor-modified（当前 reason 契约不含此值）
注意：这会与 N1 联动——基线须在 root 外，否则改写基线同样可绕过。
```

**P3 — 移除 4 处残留过度主张（修 N4）**
```
metacog.py L789 注释 → 改为「外部锚通过 = 证明/令牌由离线根签名，C-1 未真正闭合（见 HANDOFF ⑦）」
metacog.py L794 运行时字符串 → 删除「C-1 已真正破于逻辑层」
metacog.py L2614 注释、L2855 help 文本 → 同口径对齐
trust_root.py L357 HsmTrustRoot docstring → 同上
```

**P4 — 补 `backend=oob` C-1 对抗测试（修 N3）**
```
test_attacker_swaps_root_pubkey 增加 backend="oob" 分支：
  root 外 oob_token_dir + evil_priv 自签令牌 → 当前实测 (True, None)
  → 该用例将直接 FAIL，暴露残余的真实强度（这是好事：测试应先红）
```

**P5 — 诚实边界补 2 条**
```
⑨ HIGH-1 删除检出的基线（ledger/integrity.json）与被保护对象同处可写域；
   攻击者持 ledger 写权限时，删 D4 快照即可绕过 HIGH-1（4 次 unlink）。
   HIGH-1 仅覆盖「攻击者仅删锚文件」半区。
⑩ backend=oob 单独部署时，攻击者仅需 oob_token_dir 写权限 + evil 离线根
   私钥即可完全重开 C-1；hsm+oob「叠加」不构成冗余，两个锚依赖同一条
   未运行时强制的部署契约。
```

**P6 — 证据链落盘（修 N9）**
```
v2.6.3–v2.6.5 / v2.7.0 / v2.7.1 的 Hermes 复验报告落 references/。
本轮报告即为 v2.7.1 的落盘版。建议 v2.7.2+ 起：每次 Hermes 复验
强制落 references/independent-audit-hermes-vX.Y.Z.md，否则评级
不具可追溯性（v2.6.6.1 已发现此问题，未修复）。
```

---

## 9. 审计完整性自声明（audit_integrity_note）

**本报告审计方（Hermes 同栈）的自纠记录**：

- **N3-1（观测瑕疵，已自纠）**：探针第一卷 A3 把 `../SIBLING_IN_ROOT/x.json` 打成 `resolve_in_root=False` 与 `gate=REJECT` 的矛盾组合。复核确认为 **FACT 打印基准差异**，非闸门错误——闸门对 root 与候选路径各自 `resolve()`（L546/L553），判定自洽。已用 C1 卷单独复核修正。**结论未变**：相对路径绕过不成立。
- **N3-2（探针 bug，已自纠）**：D 卷首跑 D1 返回 `(False, 'attestation-forged')`，与预期（闸门放行）矛盾。排查发现探针在 `finally` 中 `rmtree(tt)` 删掉了 attestation 文件，导致 `attack_*` 返回前文件已消失。修正后 D1 实测 `(True, None)`。**未修正前会误报闸门有效**——这条记录说明「探针自身也要审」。
- **N3-3（未能实测，已标注）**：Windows symlink 因 `WinError 1314` 无法创建，B2/B3 结论降级为静态推理，已在 N7 显式标注，未当作实测证据使用。
- **N3-4（未采信的作者自述）**：`110/110` 与「隔离 subagent 自验」均为作者声称。前者已独立复跑确认真实；后者（subagent 自验）**未采信**，本报告未引用其作为证据。

**评级失去区分力声明**：本技能已 6 轮连续「CONDITIONAL 维持」。本轮发现 1 个新 HIGH 绕过 + 2 个新 MEDIUM 绕过 + 4 处过度主张残留，评级在「更严」与「更松」两个方向上均有移动理由却未移动。**我不自行改动评级**（同栈、文本级、无隔离环境，无法提供能真正移动评级的判定），但显式声明：当前 CONDITIONAL 已退化为默认稳态，其信息量低于它在 v2.6.5 时。若 KK 需要一个能真正判定「C-1 是否闭合」的结论，答案是**软件层无法提供**——根公钥外部化（TPM/OS 信任源/独立只读介质）是唯一路径，已在 HANDOFF §157 正确记录为「超出 v2.7.1 范围」。

**本轮最可肯定的一点**：这个技能的诚实纪律是真实的——3 次主动撤回自己版本的头条主张（v2.6.4→v2.6.5 Windows chmod、v2.7.0→v2.7.1「闭合 C-1」、v2.6.6.1→v2.7.1「sim_key/oob」口径），并主动标注「self-attested 非独立审计、复验暂缓」。在自评循环普遍固化的场景下，**有真实撤回记录 = 自评批判有效**。本轮的 N1/N2/N3 不是这个技能的缺陷，而是**任何**依赖部署契约的安全机制在同一威胁模型下都会遇到的边界——它们应该被写进诚实边界，而不是被当作 v2.7.1 的失败。

---

## 10. ad-hoc 验证记录（报告可复现性）

**验证脚本**：`D:\hermes\temp\metacog-v271-audit\hermes-verify-consolidated-v271.py`
**复跑命令**：`PYTHONHOME="" PYTHONPATH="" python3.12 hermes-verify-consolidated-v271.py`
**解释器**：Python 3.12.0（`C:\Users\Administrator\.local\bin\python3.12.exe`）
**结果**：**36 PASS / 0 FAIL，退出码 0**，2026-10-02T16:19:41（复跑通过，与前次一致）

> **这是 ad-hoc 验证，不是测试套件通过**。它只断言本报告提出的结论，不等于
> 作者 24 文件 509/509 全量；作者测试套件单独复跑确认为 110/110 PASS（G0）。

### 断言分组

| 组 | 覆盖的报告结论 | 断言数 |
|---|---|---|
| G0 | 作者声称 110/110 PASS 真实成立 | 1 |
| G1 | N1 HIGH-1 基线自指绕过（含 4 次 unlink 全链 + 作者测试半区对照） | 6 |
| G2 | N2 改写而非删除静默降级（含清空 root_pubkey 对照） | 4 |
| G3 | N3 闸门无权限语义 + 3 后端全部可重开 C-1 | 6 |
| G4 | Q1 主向量 fail-closed + 7 项路径枚举 + legacy 不误拦 | 8 |
| G5 | N4 残留过度主张（按内容定位，非硬编码行号） | 5 |
| G6 | N7 `_assert_real_path` resolve 修复、N3 import 兜底、豁免路径 fail-safe | 4 |
| G7 | 测试覆盖缺口（对抗测试 backend 实测为 `hsm` / `hsm+oob`） | 2 |

### 关键实测值（可直接复跑比对）

```
G1-5  删 integrity.json+chain+两锚 → (ok=True, reason=None)   ← HIGH-1 被绕过
G2-3  改写 enabled=False/backend=legacy → (ok=True, reason=None)  ← 静默降级
G3-4  backend=hsm/hsm+oob/oob，root 外可写 + evil 自签 → 闸门 None，全部 (ok=True, None)
G4-1  主攻击向量 → (False, 'external-anchor-inside-writable-root')  ← fail-closed 成立
G4-8  未启用外部锚 → (ok=True, reason=None)  ← legacy 不误拦
G5-1  「已真正破于逻辑层」恰 2 处：L789（注释）+ L794（运行时字符串）
G7-1  两项新对抗测试 backend = {attacker_swaps:['hsm'], anchor_deletion:['hsm+oob']}
G7-2  standalone "oob" 仅见于 test_check_pubkey_root_oob_failclosed_and_pass
      与 test_delete_config_fallback_legacy（均非 C-1 对抗测试）
```

### 验证脚本自身的缺陷与自纠（3 处，全部已修）

诚实记录：本轮验证脚本第一版跑出了 **33 PASS / 2 FAIL**，两处 FAIL 都是**我自己探针的 bug**，不是被审技能的缺陷。

1. **G0 抛异常**：`obs()` 与 `check()` 的 detail 格式化用 `str + int` 拼接
   （`退出码` 是 `int`），`str + detail` 直接 `TypeError`。修正为 `str(detail)`。
   第一版因此**误报 g0 抛异常**，且中断了该组后续输出。
2. **G4-8 误判**：探针创建 legacy store 后未钉固根，`check_pubkey_root` 在更早处以
   `no-pinned-root` 拒绝，**掩盖了「legacy 分支是否被误拦」的真实语义**。
   修正为补跑 `cmd_confirm --keygen`。修正后实测 `(True, None)`，报告结论「legacy 不误拦」**成立**。
3. **G7-1 空转通过（最危险的一处）**：第一版用「是否出现 `backend="oob"`」的正则，
   但两项新对抗测试的 backend 是**位置参数**（`_enable_external(st, tmp, "hsm", ...)`），
   正则匹配为空集 → `'oob' not in []` 恒真 → **空转通过**。更糟的是即便匹配到了，
   `"oob" in ["hsm", "hsm+oob"]` 也是 `True`（子串命中），会**误判为覆盖**。
   修正为按函数边界切块 + 只认字面量精确值，并新增 G7-2 断言 standalone `"oob"`
   的真实归属。实测两项对抗测试 backend 分别为 `hsm` / `hsm+oob`，
   standalone `oob` 确实只出现在两个非对抗测试中——**报告结论成立，但第一版是靠巧合通过**。

**教训**：断言失败必须先怀疑探针自己。第一版 G7-1 那种「空集判定恒真」的空转通过
比断言失败更危险，因为它给出假绿灯。

### 遗留无法验证项（未当作已验证使用）

- **Windows symlink 无法实测**：`os.symlink` 抛 `WinError 1314`（无符号链接特权），
  `cmd /c mklink` 同样失败。N7 中 symlink 相关结论**全部为静态推理**，本验证脚本
  未对其作任何断言。
- **TOCTOU 间隙**：`_assert_real_path` 返回后调用方另行 `Path.read_text()`，
  check-then-use 间隙未做并发压测，**未验证**。
- **未跑全量**：只跑 `test-trust-root.py`（110 项）+ 本 ad-hoc 36 断言，
  未跑作者 24 文件 509/509。
- **非 git 仓库**：`references/` 与技能实体均无本地版本历史，无法用 git 校验冻结态。

---

## 11. 一句话总结

**v2.7.1 的主攻击向量 fail-closed 闸门真实有效（实测确认），但 HIGH-1 的基线与它保护的锚同处可写域——攻击者 4 次 unlink 即可让外部锚静默回到 C-1 未闭合状态且零告警。评级 CONDITIONAL 合理，但需附 2 条新边界；另有 4 处 v2.7.0 过度主张未撤回，其中 1 处是用户可见的运行时告警字符串。⚠️ 有条件通过。**
