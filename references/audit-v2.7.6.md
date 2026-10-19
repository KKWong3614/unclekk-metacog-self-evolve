# 统一 Hermes 复验 · v2.7.6 裁定（铁律5 · 只评不改）

- 日期：2026-10-07
- 被审：unclekk-metacog-self-evolve v2.7.6（信任根外部锚子系统）
- 审计通道：`mcp__hermes__hermes_audit`（异族独立审计员）；本轮 Hermes 走本地读盘 + 实跑独立核验，未采信 dossier 自述数字。
- 主 agent 只读复跑兜底：确认 L-1/M-3/L-2/L-3 事实主张属实；M-1 调用方 L2808-2811 误映射复核确认。

## 总体评级
⚠️ **有条件通过（与 v2.7.4 / v2.7.5 同档）**。C-1 根因仍 OPEN（连续 8 个次版本），无新 HIGH（M-1 攻击面与 C-1 同构，不构成新 HIGH）。评级 CONDITIONAL 维持正确，不建议上调。

## 逐项核对（授权 7 项）
| 核查项 | 裁定 | 说明 |
|---|---|---|
| 1. NEW-H1 purge 补清 ledger | ✅ 闭合（附 M-1 下游） | L632-644 逻辑正确；`test_purge_external_anchor_clears_ledger_then_legacy` 4 断言全过；sentinel在+baseline缺失仍 fail-closed 有回归测试锁住 |
| 2. NEW-V1 冻结 sha256 | ⚠️ 文本级闭合 | 5/5 哈希实测一致；但漏 `trust_root.py`（M-3），清单无签名、无独立存证 |
| 3. D1 第二静默分支 | ⚠️ 代码到位、测试缺失 | WARN 实测能发；测试文件零覆盖（M-2）；测试 harness 总先写 anchor+sentinel，生产链几不可达 |
| 4. NEW-M-2 对抗测试 | ✅ 闭合 | `test_external_anchor_valid_privkey_resign_baseline_passes_undetected` 实跑 PASS，显式文档化 C-1 残余 |
| 5. NEW-G2 披露精度 | ✅ 部分 | C-1 表述已改精确；TTY 门槛已点明；但"删措辞"未执行（L-1） |
| 6. CHANGELOG 严格降序 | ✅ 版本序号降序（54 头 0 逆序对）；⚠️ 日期逆序残留（L-2） |
| 7. SKILL.md 删措辞 | ❌ 未执行 | 15 处仍在（L-1） |

## 新暴露发现

### MEDIUM
- **M-1｜purge 半败被误报"无需回收"（v2.7.6 自身引入，实跑复现）**
  `purge_external_anchor`（L611-645）顺序"先清 ledger → 再 rmtree 外部证明目录"，任一步失败 `return False`。调用方 L2808-2811 把 `False` 一律当"目录本就不存在"→ `info("外部锚证明存储不存在，无需回收。")`。
  注入 `shutil.rmtree → PermissionError` 实测：ledger 已删、proof dir 残留、返 False → 报"无需回收"。更严重：purge 半败后钉固 `root-pubkey.pem` 仍在原目录、ledger 基线已清；此时 re-enable 无告警地用新传入 root_pubkey 覆盖钉固公钥 → 随后覆盖 baseline 同 hash 重签，`_external_anchor_deleted` 返 False，完整 C-1 绕过。披露称"人类 TTY 手动补清"，但人类收不到"需补清"信号，只会见"无需回收"。
- **M-2｜D1 第二静默分支零测试**：代码在、告警能发（`grep` 仅 metacog.py 命中），测试文件零覆盖；与 except 坏私钥分支（有 `test_external_anchor_bad_root_privkey_warns_and_unsigned`）不对称。
- **M-3｜NEW-V1 冻结清单漏 `trust_root.py`**：`trust_root.py` 被 metacog.py L45 import，承载 attestation_ok/sign_oob_token/RsaRootVerifierProvider，38.6KB，是外部锚信任路径核心；既不在冻结清单，也不在 `SCRIPT_NAMES = ("metacog.py","sigcrypto.py")`（L499）内部基线 → 双重漏检。

### LOW
- **L-1｜『主 agent 沙箱禁跑本地 .py』措辞未删（授权项未执行）**：SKILL.md 实测 14+ 处（含 v2.7.5 段保留原文），v2.7.6 块声称"已删"但未真正执行；HANDOFF §3 铁律1 已改写"v2.7.6 起不再声称"，文档自相矛盾。v2.7.6 自评 over-claim，已诚实订正（SKILL.md L359）。
- **L-2｜CHANGELOG 日期非降序**：v2.1.3（2026-09-08, L947）在 v2.1.2（2026-09-09, L979）之前。
- **L-3｜argparse help 版本漂移**：`--purge-external-anchor` help（L3074-3075）仍标 `v2.7.5`，但 purge 行为 v2.7.6 有实质变更（补清 ledger）。

## 改进建议（待 KK 授权 v2.7.7）
1. purge 返回三态 `"cleared"/"none"/"partial"` 取代 bool；半败时 stderr WARN + 退出码 2 明说"ledger 已清、证明目录残留于 `<path>`，请手动删除"，绝不用 `info("无需回收")` 承接 False。
2. 补 `test_external_anchor_d1_second_branch_warns_and_unsigned`：直调 `record_external_anchor_integrity`、锚缺失，断言 stderr 含"签名跳过"且 baseline 无 `signed`。
3. 冻结清单加入 `trust_root.py`（必补）+ `meta_optimizer.py`/`domain_detector.py`/`verify-redline.py`；并把 `trust_root.py` 加入 `SCRIPT_NAMES` 让 M-5 内部检测覆盖；清单另附到未被冻结的外部路径。
4. 删 SKILL.md 全部 14+ 处『主 agent 沙箱禁跑本地 .py』，或改为可验证客观陈述。
5. CHANGELOG 修 v2.1.2/v2.1.3 日期序；`--purge-external-anchor` help 版本标改 v2.7.6。
6. C-1 建议停止次版本收口循环（v2.7.0→v2.7.6 连续 8 版，每版新引入 1-4 MEDIUM 从未根除根因）；真闭合只两条路：外部不可变存储（TPM/只读介质/独立机），或承认该子系统在当前部署下不成立、降级为 advisory 并在 SKILL.md 首屏标注。

## 诚实纪律声明
- Hermes 只评不改，未改任何文件。
- 主 agent 仅更新 HANDOFF/CHANGELOG/SKILL 文档层以记录本裁定（含诚实订正 L-1）；受保护代码 `metacog.py`/`test-trust-root.py`/`sigcrypto.py` 未被改动，其 v2.7.6 冻结 sha256 仍有效。文档三层 sha256 因记录裁定被取代。
- v2.7.6 自评在 L-1（"已删沙箱禁跑措辞"）上 over-claim，已诚实订正，不作为收口完成项。
