# 统一 Hermes 复验 · v2.7.7 裁定（铁律5 · 只评不改）

- 日期：2026-10-08
- 被审：unclekk-metacog-self-evolve v2.7.7（信任根外部锚子系统）
- 审计通道：`mcp__hermes__hermes_audit`（异族独立审计员，本轮 Hermes 自带探针 harness 实跑 + 主 agent 独立实证复核）；铁律3：Hermes 裁定仅以文本为凭，不依赖其声称的落盘探针文件（其 harness 自认 5 处 bug，结论须经独立核验）。
- 主 agent 独立实证：Windows 只读 `unlink`/`rmtree` 行为实跑复现（os.name=nt, py3.13.14）。

## 总体评级
⚠️ **有条件通过（与 v2.7.4 / v2.7.5 / v2.7.6 同档）**。v2.7.7 授权 6 项（M-1/M-2/M-3/L-1/L-2/L-3）代码层闭合 + 测试绿（155/155）；但**新暴露 1 项 MEDIUM（Windows 生产路径 purge 只读断裂 + 测试/生产分歧导致的验证 over-claim）**，C-1 根因仍 OPEN（连续 9 个次版本）。评级 CONDITIONAL 维持正确，不建议上调。

## 逐项核对（授权 6 项收口）
| 核查项 | 裁定 | 说明 |
|---|---|---|
| M-1（purge 三态） | ✅ 代码闭合 | `purge_external_anchor()` 返回 `"cleared"/"none"/"partial"`（metacog.py L611-650）；半败 stderr WARN + 调用方 L2804-2812 对 `partial` 退出码 2 + warn，不再误报"无需回收"。**但见下方 NEW-M：三态语义正确，Windows 生产路径却恒返 partial（"cleared" 成死代码）** |
| M-2（D1 第二分支测试） | ✅ 闭合 | `test_external_anchor_d1_second_branch_warns_and_unsigned` 实跑 PASS（2/2）；与坏私钥分支对称 |
| M-3（冻结清单 + SCRIPT_NAMES） | ✅ 闭合 | `SCRIPT_NAMES` 加 `trust_root.py`（L499）；冻结清单补 `trust_root.py`/`meta_optimizer.py`/`domain_detector.py`/`verify-redline.py`（CHANGELOG 冻结清单 9 文件 sha256 实测一致） |
| L-1（删沙箱禁跑措辞） | ✅ 闭合 | SKILL.md 14+ 处『主 agent 沙箱禁跑本地 .py』已删（逗号形+括号形），仅留引用式说明；与 §3 铁律1 一致 |
| L-2（CHANGELOG 日期降序） | ✅ 闭合 | v2.1.3(09-08→09-10) 与 v2.1.2(09-09) 降序修正 |
| L-3（help 版本标） | ✅ 闭合 | `--purge-external-anchor` help 标 v2.7.7 并精确描述三态/半败 |

## 新暴露发现

### MEDIUM — NEW-M（Windows 生产路径 purge 只读断裂 + 验证 over-claim）
**根因（主 agent 独立实证，非仅文本声称）**：
- 生产启用路径 `write_trust_root_config`（trust_root.py L589-625）在落盘后对 `ledger/trust-root.json` + `ledger/.external-anchor-enabled` 调 `_restrict_credential`（L624-625）。`_restrict_credential`（L569-586）在 Windows 分支执行 `os.chmod(path, 0o400)` → 置 `FILE_ATTRIBUTE_READONLY`（Windows 实际生效，POSIX 分支为 0o600）。
- `purge_external_anchor` step1（metacog.py L629-639）对这两文件执行 `p.unlink()`；**Windows 上 `os.unlink()` 对只读文件抛 `PermissionError [WinError 5]`**（主 agent 实测复现：os.name=nt, py3.13.14，chmod 0o400 后 st_file_attributes & 0x1=True，unlink RAISE）。→ step1 恒失败 → 恒 `return "partial"` + WARN，**ledger 永不清、step2 外部证明目录（含钉固 `root-pubkey.pem`）永不可达、永不删**。
- 同理 step2 `shutil.rmtree(d, ignore_errors=False)`（L643）若抵达，对含只读文件目录亦 RAISE（主 agent 实测：`rmtree` 含只读文件 RAISE WinError 5）。但本机生产 step1 先失败，step2 实际不可达。

**后果**：
1. **功能断裂（Windows）**：生产环境 purge 永远返回 `"partial"`、`"cleared"` 成为死代码；外部锚足迹（ledger + 证明目录 + 钉固公钥）在任何 Windows 部署下**无法被实际清除**。人类每次 purge 都收"半败需手动补清"告警，但根因是代码未清只读位，而非真实残留。
2. **安全邻接（C-1 疲劳）**：`partial` 本意是"异常→人工核查后再 re-enable"；但 Windows 上它**恒为 on**，告警沦为噪声，人类可能习惯"无视告警强制 re-enable"→ 经人工 override 重新引入 C-1 覆盖钉固公钥风险。返回码层面仍 fail-closed（partial 拒绝 re-enable），但清理从未完成。
3. **诚实披露缺口（验证 over-claim）**：155/155 的 "cleared" 断言依赖测试夹具——purge 测试辅助 `_enable_external`（test-trust-root.py L245-260）**直写 `write_text` 未经 `_restrict_credential`（无只读位）**，故 `unlink()` 在测试中成功、断言通过；**测试套件完全未覆盖真实 Windows 只读 purge 路径**。验证证据对 Windows 生产 purge 行为存在 over-claim，须诚实订正。

**与 M-1 的关系**：v2.7.7 的"三态"改造锁住了"partial 不等同 none、调用方须告警"的语义，方向正确；但它**未触及 `unlink`/`rmtree` 在只读文件上的 Windows 失败根**——在 Windows 上 partial 从"异常分支"变成了"唯一分支"，反而使 cleanup 彻底失效。属 M-1 实现层未闭合的残余，建议 v2.7.8 修复。

**建议修复（待 KK 授权 v2.7.8，仅文档层外）**：
- step1 删除前清只读位：`p.unlink()` 前 `os.chmod(str(p), 0o600)`（沿用 `write_trust_root_config` L598-603 既有模式）。
- step2 `shutil.rmtree(d, onerror=_rm_readonly)`（`onerror` 回调先 `os.chmod` 清只读再重试），防御证明目录含只读文件情形（当前证明目录文件未受限，但属未来-proof）。
- 测试 `_enable_external` 应改走 `write_trust_root_config`（或显式 `_restrict_credential`）以覆盖真实 Windows 只读；或新增 Windows 专属实跑用例 / 标注 `@skipUnless(os.name=="posix")` 诚实暴露未覆盖。

### C-1 仍 OPEN（同 v2.7.6，连续 9 版）
`root_pubkey` 锚定仍位于 Agent 可写 `ledger/trust-root.json`；v2.7.7 未触碰根因。Hermes 本轮"M-1 杜绝 C-1 绕过仍未兑现"的 stage2b 主张与已文档化 C-1 OPEN 同构，**非新发现**；其 0o600→WinError 5 指针真实，主 agent 已独立实证并升级为上述 NEW-M。

## 改进建议（待 KK 授权 v2.7.8）
1. 修 NEW-M（Windows purge 只读断裂）：step1/step2 删除前清只读位（见上）。
2. 修测试/生产分歧：`_enable_external` 走生产写入路径或显式受限；诚实标注未覆盖平台。
3. C-1 仍未根除：维持 advisories；真闭合只两条路——外部不可变存储（TPM/只读介质/独立机），或承认该子系统在当前部署不成立、降级为 advisory 并在 SKILL.md 首屏标注（Hermes v2.7.6 已提建议 6）。建议停止次版本收口循环（v2.7.0→v2.7.7 连续 9 版）。

## 诚实纪律声明
- Hermes 只评不改，未改任何文件；其探针落盘于 `D:\hermes\temp\audit-v277\` 与 `%TEMP%`，审计对象零修改（铁律3：不采信其探针，仅采纳文本裁定 + 主 agent 独立实证）。
- 主 agent 仅更新 HANDOFF/CHANGELOG/SKILL 文档层以记录本裁定（含 NEW-M 诚实订正）；受保护代码 `metacog.py`/`test-trust-root.py`/`sigcrypto.py`/`trust_root.py` 未被改动，其 v2.7.7 冻结 sha256 仍有效。文档三层 sha256 因记录裁定被取代。
- v2.7.7 自评在"Windows 生产 purge 可 cleared"上存在隐含 over-claim（测试夹具掩盖），已诚实订正为本 NEW-M，不作为收口完成项。

## 后续（v2.7.8 已修 · 2026-10-08）
KK 授权 v2.7.8 修复 NEW-M，已落地并冻结：
- **代码**：`Store.purge_external_anchor()` step1 `unlink` 前 `os.chmod(p, 0o600)` 清只读位；step2 `shutil.rmtree(d, onerror=_rm_readonly)` 新增模块级 `_rm_readonly` 回调清只读重试（metacog.py）。
- **测试**：新增 `test_purge_external_anchor_clears_readonly_ledger_and_proof`（模拟生产只读态，断言 `"cleared"` + 幂等 `"none"`，5 断言）；`test-trust-root.py` 总断言 155→160、全绿（exit 0）。
- **文档**：SKILL.md `version`→2.7.8 + v2.7.8 块；CHANGELOG.md v2.7.8 块（含 9 文件 sha256 冻结清单）；HANDOFF.md §2.18 + 标题；本裁定 NEW-M（待 v2.7.8）措辞对应更新。
- **评级**：v2.7.8 自评 CONDITIONAL 维持，C-1 仍 OPEN（连续 10 版），NEW-M 已闭合。统一 Hermes 复验（铁律5）待派发确认。
