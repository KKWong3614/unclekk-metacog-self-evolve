# 独立审计报告 · unclekk-metacog-self-evolve v2.7.4（铁律 5 统一复验）

- 审计时间：2026-10-07（Asia/Shanghai）
- 审计执行方：**同栈 Hermes**（非独立第三方；与本机 WorkBuddy 生态相关，与被审对象同 Python/同文件系统）
  → 结论仅供参考；文本级 + 探针级复核，未做硬件/网络/真实 TTY 部署验证。
- 材料自足性声明：dossier 节选了 L617-660、L662-747 关键段、CLI L2755/L2773/2782/2791、L3006。
  本轮**全部符号均从磁盘完整源文件交叉核对**，不存在未定义引用阻塞项（见 §3 读盘清单）。
- 纪律：dossier 明示「只评不改」，本轮**未修改被审 skill 任何文件**；报告仅存档于审计侧目录。

## 总体评级：⚠️ 有条件通过（CONDITIONAL 维持，但披露不完整）

NEW-H1 主路径经实跑确认闭合；M-2 对 Hermes 上轮 over-statement 的纠正是**正确的**（已实测复核）。
但「签名基线 ⇒ NEW-H1 闭合」成立的条件被低估：签名层是**凭「signature 字段存在 + 钉固公钥存在」
双条件启用**的可选闸，任一条被单点移除即静默降级为已披露的无签名残余路径——**该形态未披露**。
新增 3 项 MEDIUM（E1/D1/H1）+ 2 项 LOW（C1/G1），无新 HIGH。C-1 仍 OPEN 的自述成立。

---

## 1. 实跑证据（审计侧独立探针，非作者套件）

脚本：`D:\hermes\temp\audit-v274\probe_v274.py`（复用作者 harness 助手 + 独立 tmp store，
经真实入口 `cmd_confirm` / `check_pubkey_root` 端到端，非内部构造器绕过入口层）。

作者套件复核：`test-trust-root.py` 实跑 **132/132 PASS，exit 0**（与自述一致，已独立复现）。

| 探针 | 结果 | 含义 |
|---|---|---|
| A1 签名基线 + 一致化改写 anchor+sentinel+baseline | **检出 (True)** | NEW-H1 主路径**确实闭合** ✅ |
| B1 改写钉固 root-pubkey.pem + 一致化重写 + 自持私钥重签 | **未检出 (False)** | 已披露残余（doc 写「同用户删/改它+基线」）✅ 但可操作序列未展开 |
| **C1 删钉固 root-pubkey.pem + 一致化改写** | **未检出 (False)** | `pinned_pub is None` → 验签分支静默跳过。disclosed 仅写「删/改 pubkey+基线」，未点明「单删 pem 即整层失效」 |
| **E1 剥除 baseline.signature 字段 + 一致化改写** | **未检出 (False)** | **新发现**：signature 字段单点删除即令签名层失效；作者 132 用例零覆盖、诚实边界未列 |
| **D1 坏 `--root-privkey`（非法 JSON）** | **静默退为无签名基线，CLI 仍报「外部锚已启用」** | **新发现**：L654-655 `rec.pop("signature")` 吞异常，无 stderr 告警 |
| F1 删 baseline+sentinel → `_external_anchor_deleted` 返 False | 确认 | 删除检出闸被绕过（已披露）✅ |
| F2a 删 baseline+sentinel 后 `ext` 类型 | **OobTrustRoot（非 legacy）** | Hermes 上轮 NEW-HIGH 把 `return enabled==False` 误读为 legacy 放行 → **作者纠正是正确的** ✅ |
| F3 删 baseline+sentinel 后改写 anchor | 删除检出闸不触发 | 「防御纵深降级、非 fail-open」表述**准确** ✅ |
| G1 M-4「全部 I/O 包 try/except」逐行 | L690/696/705/718/731 为裸调用 | 表述不精确（**无 fail-open 后果**，仅精度问题）|
| **H1 基线+钉固公钥位于 root 之外** | 确认；wipe `.metacog` 不回收 | **新发现（可用性）**：幽灵基线阻断合法重装 |

审计侧探针自检记录（N3 留痕）：
- 首跑 3 个前置断言 FAIL，经诊断定位为**探针自身密钥配对错误**（`setup()` 生成密钥对而调用方另传一支，
  签名用错密钥 → `_external_anchor_deleted` 恒 True）。修正配对后 A0/B0/C0/E0/F0 前置全部 PASS。
  该假说已用独立脚本反证（`pinned==pub_off: True / verify: True / deleted: False`），结论已修正。
- H1 首跑 FAIL 为**路径归一化探针缺陷**（bash 视图 `.metacog_tr_` vs Python 视图 `C:\Users\...\` 不一致），
  用 `os.path.normcase + startswith(root + os.sep)` 复算后 PASS。

---

## 2. 关键发现清单

### 高（HIGH）
无新增。

### 中（MEDIUM）

**M-NEW-1 / E1：签名层是「凭存在启用」的可选闸，单删 `signature` 字段即静默失效（未披露）**
- 代码：`_external_anchor_deleted` L738-739 `sig = data.get("signature"); if sig and pinned_pub is not None:`
  → 签名校验只在**两条件同时成立**时执行；缺任一即**跳过**（非拒绝）。
- 实测：签名基线（前置 A0 PASS）+ 一致化改写 + `data.pop("signature")` → `_external_anchor_deleted()` 返
  **False**（未检出）。攻击者无需生成密钥、无需触碰 proof_dir，只改基线 JSON 一个字段。
- 影响：v2.7.4 的头条声称「签名认证基线 ⇒ NEW-H1 闭合」只在 `signature` 与钉固公钥**同时存活**时成立；
  删一个字段即静默回退到已披露的「无签名 best-effort」残余路径，且**无任何告警**。
- 严重度论证（诚实边界内的定性）：文档已认账「基线/钉固 pubkey 同用户可写」。在该已认账威胁模型下，
  签名相对纯哈希基线的增量保证≈0——两者都可被同用户单点破坏。因此 E1 不是新的攻击面，
  而是**头条声称的条件被省略**。建议按 MEDIUM 记录（非新 HIGH），并把条件写进声称本身。

**M-NEW-2 / D1：`--root-privkey` 无效时静默降级 + setup 报成功（未披露）**
- 代码：L654-655 `except Exception: rec.pop("signature", None)  # 签名失败不阻断记录`
  → 吞掉 `json.JSONDecodeError`（坏私钥）、`ValueError`（指数非法）、以及任何序列化异常。
- 实测：传 `--root-privkey "{not-a-private-key}"` → 基线 `signature` 字段不存在；
  CLI 仍打印 `ok("v2.7.0 外部锚已启用…")`。人类在 setup 瞬间的一次粘贴错误，
  会让 NEW-H1 永久处于未闭合态而无人知晓。
- 影响：安全性质与配置态不一致（配置声称签名、基线实际无签名），且**该态不可事后区分**——
  验证侧对「无签名基线」一律静默接受。建议：签名失败时 `warn()` 明示「基线未签名，NEW-H1 未闭合」，
  或将签名失败提升为 enable 失败。

**M-NEW-3 / H1：外部证明存储位于 root 之外 → 幽灵基线阻断合法重装（未披露、无回收指引）**
- 实测：enable 外部锚后 `rm -rf .metacog` → 重新 `init` + 合法 `keygen` →
  `check_pubkey_root()` 仍返回 **False / external-anchor-deleted**。
  根因：`_external_anchor_proof_dir()` = `root.parent / ".metacog-external-anchor-store" / sha256(root)`，
  wipe root 不回收；新 root 无 `ledger/trust-root.json`，命中 L718 `if not anchor.exists(): return True`（HIGH-1 生效，方向正确）。
- 影响：**可用性/运维缺口，非安全洞**（fail-closed 方向正确）。但合法重装需人工定位并删除
  `C:\Users\<user>\...\AppData\Local\Temp\<...>\.metacog-external-anchor-store\<32位hex>\`，
  SKILL.md 步骤与 HANDOFF 均无此回收指引。HIGH-3 修复把基线移出 root 是正确取舍，
  代价（残留态）未被文档化。

### 低（LOW）

**L-NEW-1 / C1：「单删钉固公钥即整层失效」未点明**
- `pinned_pub is None` → L739 条件不成立 → 验签跳过（实测 C1 未检出）。
- 与已披露残余「同用户删/改它+基线可绕过签名验签」在**实质上重合**，故不计新攻击面；
  但披露措辞暗示「删 pubkey **和** 基线」两步，实际**删 pem 一步**（+基线哈希一致化）即可。
  建议在诚实边界中把机制点明为「验签为可选闸：钉固公钥缺失 ⇒ 静默跳过，非拒绝」。

**L-NEW-2 / G1：M-4「全部 I/O 包 try/except」表述不精确**
- `_external_anchor_deleted` 中 L690（`sentinel.exists()`）、L696（`bp.exists()`）、L705（`pk.exists()`）、
  L718（`anchor.exists()`）、L731（`sentinel.exists()`）均为**未被函数内 try 直接包裹**的调用；
  L710 `read_json(bp,{})` 位于 `try` 块外但 `read_json` 内部自吞 `JSONDecodeError/OSError`。
- 实测/静态推演：这些路径的实际结局均为 fail-closed（`return enabled` / 外层调用 / 后续比对返 True），
  **未发现 fail-open 后果**。Windows 上 `Path.exists()` 捕获 OSError 返 False，不抛。
  → 属表述精度问题，建议改为「所有异常路径均导向 fail-closed（部分由函数内 try、部分由外层调用或后续
  哈希比对兜底）」，避免审计者按字面复核时误判为未覆盖。

---

## 3. 逐条回答请求裁定

**Q1：NEW-H1 是否真正闭合？钉固 pubkey 同用户可写须部署契约兜底，是否如实披露且评级合理？**
- 闭合：**条件性成立**。主路径（签名基线 + 一致化改写）实跑确认被检出（A1 PASS，作者用例与审计侧独立复现一致）。
- 但闭合前提是 `signature` 字段与 `root-pubkey.pem` **同时存活**（M-NEW-1/C1）。
  钉固 pubkey 可写**已如实披露**；`signature` 字段单点删除**未披露**。
  → 披露不完整，评级方向（CONDITIONAL）合理，但诚实边界须补 2 项。

**Q2：M-2/M-3/M-4 是否收口？**
- **M-3 ✅ 收口**。实读确认外部锚证明/令牌为离线根私钥签名、Agent 仅持公钥（`sigcrypto.verify`），
  而完整性基线为 SHA-256 快照 + 可选签名——分层表述与代码一致，over-claim 已移除。
- **M-4 ⚠️ 行为收口、措辞未收口**。fail-closed 方向全部成立（含 M-4 新增的异常路径），
  但「全部 I/O 包 try/except」为字面不准确（L-NEW-2，无安全后果）。
- **M-2 ⚠️ 部分收口**。3 个新增用例真实存在且断言正确；对 Hermes 上轮 NEW-HIGH
  「`return enabled==False` = legacy 静默放行」的**纠正是正确的**（实测 F2a：ext 仍为 OobTrustRoot，
  未退 legacy；F3 确认系防御纵深降级而非 fail-open）——此项作者诚实度得分。
  但覆盖仍缺 E1（剥 signature）、C1（删钉固 pubkey）、D1（坏 privkey 静默降级）三条分支。

**Q3：评级 ⚠️ CONDITIONAL 维持（C-1 OPEN）是否成立？**
- **成立，方向正确**。C-1 根因（`root_pubkey` 锚定于 Agent 可写 `ledger/trust-root.json`）确实未根除，
  本轮无任何代码变更触及该点；签名基线只缩窄一致化改写面，不换信任根。
- 补充诚实标注（同栈审计纪律）：该评级自 v2.7.1 起已连续维持多轮（v2.7.1→2.7.2→2.7.3→2.7.4）。
  复验裁定序列为「不通过→不通过→不通过→本轮有条件通过」，**本轮是首次非「不通过」**，
  故区分力尚未完全丧失。但同栈文本级审计方**无法提供能真正移动的评级**（C-1 需代码级不可写外部存储/TPM，
  超出文本审计能力）。若需真正闭合判定，须 KK 授权更大版本 + 外部独立审计方。
- 前置条件：M-NEW-1/D1/H1 补入诚实边界前，评级虽方向公允、**披露不完整**。

**Q4：是否有新 HIGH/MEDIUM？**
- 新 HIGH：**无**。
- 新 MEDIUM：**3 项**（E1 签名字段单点删除 / D1 坏 privkey 静默降级 / H1 幽灵基线阻断合法重装）。
- 新 LOW：**2 项**（C1 披露精度 / G1 M-4 措辞精度）。
- 关于「删『固定基线+锚+sentinel』三件套仍静默回退 legacy」：**作者已修正为上轮 Hermes 的误读**——
  实测确认删 baseline+sentinel 后外部锚验证闸仍在（OobTrustRoot），非 legacy 放行。此项不再成立为新发现，
  作者的自我纠正是本次审计中最有诚意的部分。
- 关于「无签名基线路径 NEW-H1 残余」：**已如实披露且有用例钉住**（`test_external_anchor_unsigned_baseline_coherent_rewrite_not_detected`，132/132 内）。
  本轮新发现是**签名路径可被降级为无签名路径**（E1），而非无签名路径本身。

---

## 4. 针对性改进建议（可落地）

1. **签名闸改为强制而非可选**（收 M-NEW-1/C1 根）：对「曾以签名基线建立」的部署，`signature` 字段或钉固公钥
   缺失时应 `return True`（fail-closed），而非跳过。判定信号可用基线内一个 `signed: true` 标记
   （由 setup 写入、纳入签名 payload），使「无签名基线」与「签名被剥离的基线」可区分。
2. **`--root-privkey` 签名失败提升为告警或失败**（收 M-NEW-2）：至少在 L655 加 `warn("基线未签名，
   NEW-H1 未闭合：请检查 --root-privkey 是否为合法离线根私钥")`；或将 `record_external_anchor_integrity`
   返回值纳入 `cmd_confirm` 判定。
3. **补 3 条诚实覆盖测试**：E1（剥 signature → fail-closed，采用建议 1 后）、C1（删钉固 pubkey）、
   D1（坏 privkey → 基线无 signature 且产生告警）。
4. **补外部证明存储生命周期步骤**（收 M-NEW-3）：SKILL.md 增「回收外部证明存储」步骤，
   或提供 `confirm --purge-external-anchor` 经 TTY+nonce 授权删除 `.metacog-external-anchor-store/<hash>/`，
   使合法重装不依赖人工定位 32 位哈希目录。
5. **措辞精度**（收 L-NEW-2）：M-4 表述改为「所有异常路径均导向 fail-closed」。
6. **诚实边界补录**：把 M-NEW-1/D1/H1 追加进 SKILL.md ⑦ 与 HANDOFF ⑦（C-1 相关边界列表）。

## 5. 未覆盖 / 未执行声明（可追溯性缺口自曝）

- 未执行：`test-human-gate.py`(69)、`test-core.py`(14)、`test-boundary-cases.py`(40)、`test-cli-wiring.py`(4)、
  `trust_root.py` 自检——dossier 自述全绿，本轮**仅实跑 test-trust-root.py**，其余套件未复跑。
- 未执行：真实 TTY 部署、离线私钥不出设备的硬件验证（YubiKey/TPM）、跨信任边界部署契约验证。
  本环境为单用户 Windows 进程，`_require_tty()` 被 harness 桩为 `lambda: True`——
  **所有探针均在绕过 TTY 闸的形态下运行**，未验证 C-2（Agent 伪造 TTY/pty 注入）在当前版本的状态。
- 未读区间：`metacog.py` 3093 行中未逐行通读；仅覆盖外部锚相关区段（L484-747、L860-940、L2645-2800、L2992-3008）。
  `trust_root.py` 覆盖 L117-205、L300-430、L530-559；`sigcrypto.py` 覆盖 L117-195。
- 未验证：`sigcrypto.deserialize_priv` 无输入校验（仅 `deserialize_pub` 校验 e==65537）。
  本轮未构造弱 `d` 攻击路径；该缺口在 v2.7.4 变更范围内**不构成新风险**（根私钥人类离线持有），
  但记为既存边界。

## 6. 审计员自身推断的验伪声明（N3）

本轮我犯过 2 次探针自错并已修正留痕：
1. **密钥配对错误假说**：首跑 5 个前置断言全 FAIL，我一度以为是代码缺陷；
   诊断脚本反证 `pinned==pub_off: True / verify: True / deleted: False` 后确认是探针传错密钥对。
   已修正并重跑，A0/B0/C0/E0/F0 全部 PASS。
2. **路径归一化假说**：H1 首跑 FAIL，实为 bash 视图与 Python 视图的路径表示不一致；
   改 `os.path.normcase + startswith` 后 PASS（结论翻转）。

未采信项：dossier 中「首轮 130/130 含 1 FAIL … 已修正为 …_residual 诚实断言」的叙述未逐轮复现，
仅采信修正后 132/132（已独立实跑确认）。

---
[Hermes] 独立审计完成 · 2026-10-07 · 同栈文本级+探针级复核 · 未修改被审 skill 任何文件

---

## 7. Ad-hoc 验证（探针自身可信度，非被审对象验收）

脚本：`C:\Users\ADMINI~1\AppData\Local\Temp\hermes-verify-probe-v274.py`
结果：**18 PASS / 0 FAIL**，exit 0。性质 = **ad-hoc 定向验证，非测试套件绿灯**。

| 项 | 内容 | 结果 |
|---|---|---|
| V1 | `probe_v274.py` 退出码 0、无 Traceback、产出计数行 | PASS ×3（12 PASS / 3 FAIL） |
| V2 | 三项报告的 FAIL（E1/C1/B1）在输出中原样复现 | PASS ×3 |
| V4 | 控制组 A1 PASS 复现（探针有判别力，其 FAIL 才具语义） | PASS |
| V4 | 五段前置断言 A0/B0/C0/E0/F0 全 PASS（排除密钥配对类探针缺陷） | PASS |
| V3 | 报告引用的代码锚点仍在磁盘源码原样存在 | PASS ×5<br>命中 L655 / L739 / L719 |
| V5 | 作者套件隔离进程复跑 132/132（确认探针未污染共享状态） | PASS ×2 |
| 附 | E1 独立复算（不经探针脚本，直连源码）：前置锚通过 → 保留 signature 时检出 → 剥除 signature 后未检出 | PASS ×3 |

未覆盖：本验证只确证「探针结论对磁盘源码的引用一致、且关键结论可用第二条独立路径复算」，
**不构成对 unclekk-metacog-self-evolve 的验收**。C-2（Agent 伪造 TTY）在所有探针中均被桩掉，未验证。
