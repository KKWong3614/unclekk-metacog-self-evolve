# 统一 Hermes 复验报告 · unclekk-metacog-self-evolve v2.7.5

> 派发：铁律 5（2026-10-07，KK「重启并信任」Hermes MCP 后最后派发）。Hermes 读盘 + 实跑对抗探针复验。
> 总体评级：**⚠️ 有条件通过（CONDITIONAL 维持，与 v2.7.4 同档）**。

## 审计证据链
- 读盘：`metacog.py` L600-774、L2773-2837、L2674-2684；`sigcrypto.py` L140-200；`trust_root.py` L505-562、L589-615
- 实跑（git-bash python3.12）：
  - `test-trust-root.py` **137/137 PASS**（E1/C1/D1 三用例均在 main 且全绿）
  - `trust_root.py` 自检 `=== 全部通过 ===`；test-cli-wiring 4/4；test-human-gate 69/69；test-core 14/14；test-boundary-cases 40/40
- 材料片段与磁盘代码逐字对齐（1.1 / 1.3 全部字段一致，1.2 系 1.1 子集，1.4 文档改动）
- 断言数核对：E1=2 断言 + C1=1 + D1=2 = **5 断言**；132+5=137，数字对得上

## 总体评级
⚠️ 有条件通过（CONDITIONAL 维持，与 v2.7.4 同档）。E1/C1/D1/H1/G1 五项声明均已真实收口；C-1 根因未根除；并新暴露 H1 收口引入的 1 项 MEDIUM 缺口 + 1 项披露精度瑕疵。

## 裁定逐项

| 项 | 裁定 | 依据 |
|---|---|---|
| 1. E1 | ✅ 闭合 | L761-766：`baseline_signed` 为真时 `sig` 缺失即 `return True`；单删 `signature` 字段被检出 |
| 2. D1 | ✅ 闭合 | L673-675 写入 stderr 告警；L676-677 只在 `signed_ok` 时写 `signed=True`，不再谎报 |
| 3. H1 | ⚠️ 半闭合 | purge 仅删 `proof_dir`（baseline+钉固 pubkey），**未清 ledger/trust-root.json + sentinel**；且 purge 无测试覆盖 |
| 4. C1 | ✅ 闭合 | L728-730 + L765-766：`pinned_pub is None` → fail-closed |
| 4. G1 | ✅ 收口 | 措辞改为"全部异常路径均导向 fail-closed"，与行为一致（外层 except 吞异常但方向 fail-closed） |
| 5. 评级 | ⚠️ CONDITIONAL 维持 | C-1 根因（`root_pubkey` 在可写 `ledger/trust-root.json`）经 7 个次版本仍未根除；新暴露见下 |
| 6. 文档 | ⚠️ 与代码一致，但见 NEW-G2 | |

## 关键发现清单

### [MEDIUM] NEW-H1：`purge_external_anchor` 引入未披露的检测缺口
L616-622 purge 只 `shutil.rmtree(proof_dir)`；ledger/trust-root.json 与 `.external-anchor-enabled` 原样留存。因此：
1. 若之后 anchor/sentinel 被删（正常 wipe 或攻击）→ L718-720 走 `not bp.exists()` 分支 + `enabled=False` → 返回 False → **legacy 静默**，`_external_anchor_deleted()` 完全无感。
2. purge 后系统处于"baseline 被删但 sentinel 仍在"的幽灵态，检测闸零覆盖。
3. **测试零覆盖**：`grep purge test-*.py` 命中 0 处。
这直接推翻 v2.7.4 材料中"删 baseline+sentinel 两件套仅是删除检出闸被绕过、非 legacy 放行"的诚实纠正——**purge 是第三条能触发同类 legacy 回退的路径，未纳入披露**。

### [MEDIUM] NEW-V1：「代码/测试/文档已冻结」不可独立验证
材料首行声称冻结，但：无 git commit hash、无文件 SHA256 清单、无 mtime 快照、无签名。审计方只能对"读盘时点"负责，无法对"冻结时点"负责。审计结论存在时间窗不确定性。

### [MEDIUM] D1 存在第二个静默降级点，v2.7.5 未补告警
L662：`if root_privkey and sigcrypto is not None and rec.get(EXTERNAL_ANCHOR_JSON_KEY) and rec.get(EXTERNAL_ANCHOR_SENTINEL_KEY)` —— 若 anchor 或 sentinel 任一文件不存在，`rec.get(...)` 为 None → 整段跳过 → **无告警、无 `signed` 字段**。与 D1 except 分支的处理不对称。v2.7.4 遗留，v2.7.5 收口 D1 时未覆盖此分支。

### [MEDIUM] NEW-M-2：测试矩阵对"持合法根私钥"路径仍零断言
v2.7.5 新增 3 测试均为单点原子操作（strip signature / unlink pubkey / bad privkey）。材料第 4 节把"攻击者同时持有有效离线根私钥可重建合法签名基线"仅作文字披露，**无对应测试**。M-2 从 v2.7.3 提出至今（v2.7.4 / v2.7.5）持续未闭合。

### [LOW] NEW-G2：C-1 披露的绕过门槛表述不精确
材料第 4 节："若攻击者同时持有有效离线根私钥则可重建合法签名基线"。实测最小充分条件为 **{workspace 可写 + 离线根私钥 + TTY}**，且路径为"**直接覆盖** `baseline.json` 用同 hash 重签"，非"重建"。省略了"覆盖既有 baseline"这一更短路径，且未点明 TTY 是 purge 路径的额外门槛（直接覆盖无需 TTY）。C-1 状态未变，但披露精度仍可再提。

### [LOW] CHANGELOG 版本顺序非严格降序
实测顺序：2.7.3 → 2.7.4 → 2.7.5 → 2.7.2 → 2.7.1 → 2.7.0 → 2.6.6.1 → 2.6.6 → 2.6.5 → 2.6.4 → 2.6.3 → 2.6.0 → 2.6.2 → 2.6.1 → 2.5.8 → 2.5.7 → 2.5.2 → 2.5.6 → 2.5.5 → 2.5.4 → 2.5.3 → 2.5.0 → 2.5.1 → 2.4.0 → …（v2.6.x 与 v2.5.x 段多处逆序，历史重排遗留）。违反 semver changelog 追溯审计约定。

### [LOW] 措辞精度
- SKILL.md L345："主 agent 沙箱禁跑本地 .py"—— 与事实不符（本次审计即由 Hermes 主环境实跑验证成功），属误导性不可验证声明，影响后续审计方的复跑预期。
- 第 3 节："v2.7.4 修正后 132/132 + 3 新增用例，断言 132→137"—— 3 新增用例 = 5 新增断言；数字正确但并列易被误读。

## 无 HIGH 声明
未新增 HIGH。C-1 根因本身仍属"高"级残余，但为已知未变更项，不计本轮新增。

## 针对性改进建议（可落地）
1. **purge 补齐**：`purge_external_anchor()` 同时清除 `ledger/trust-root.json` 与 `ledger/.external-anchor-enabled`；或在 purge 后若两者仍存在则 `bad(...) return 2` 拒绝"仅清 proof_dir"的半成品状态。
2. **补 3 测试**：purge 幂等（无目录时）、purge 后 `_external_anchor_deleted` 行为、purge 未清 ledger 时删 sentinel 的 legacy 路径。
3. **D1 第二个分支补告警**：`rec.get(...)` 为空时同样写 stderr WARN（区分"缺文件"与"坏私钥"两种原因）。
4. **补"持合法根私钥"对抗测试**：证明 C-1 同构残余为 KNOWN OPEN，与"未检出"区分（对齐 M-2 诚实矩阵口径）。
5. **CHANGELOG 重排**：按版本号严格降序；v2.6.0/2.6.2/2.6.1 与 v2.5.2/2.5.6/2.5.5 段乱序修正。
6. **冻结留证**：materials 附 `sha256sum metacog.py trust_root.py sigcrypto.py test-trust-root.py SKILL.md CHANGELOG.md HANDOFF.md` 清单，或给出 git commit。
7. **措辞修正**：SKILL.md L345 删除"主 agent 沙箱禁跑"；C-1 披露补"直接覆盖 baseline 用同 hash 重签"路径 + 标注 TTY 是 purge 路径额外门槛。
8. **长期**：C-1 唯一真闭合仍需"根公钥 + 钉固 pubkey + baseline 三件套外部化到代码级不可写存储（TPM / OS 信任源 / 独立只读介质 / 独立机）"，本轮无进展，待 KK 授权更大版本。

---

**审计结论一句话**：v2.7.5 把 v2.7.4 暴露的 3 MEDIUM + 2 LOW 都真实收口了（代码、测试、文档三方一致，实跑全绿），但 **C-1 根因连续 7 个次版本仍未根除，且 H1 收口动作本身留下了 purge 未清 ledger 的新 MEDIUM 缺口**——评级维持"有条件通过"，不建议升为"通过"，也无需降为"不通过"。
