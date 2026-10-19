# 统一 Hermes 复验 · v2.7.8 裁定 + 主 agent 独立实证反驳（铁律5 · 只评不改）

- 日期：2026-10-08（Hermes 派发：会话重启后重连，已派发）
- 被审：unclekk-metacog-self-evolve v2.7.8（信任根外部锚子系统 · NEW-M 修复）
- 审计通道：`mcp__hermes__hermes_audit`（异族独立审计员，纯文本审计——本轮 Hermes 自述在其侧未找到 skill 代码，仅以 dossier 文本为凭，符合铁律3"Hermes 非真异族，裁定仅以文本为凭"）。
- 主 agent 独立实证：Windows 只读目录/文件 `unlink`/`rmtree` 行为 + `_rm_readonly` 回调有效性 + 运行时版本，均实跑复现（os.name=nt, py3.13.12/3.13.14）。

## Hermes 裁定（原文摘要，已记录其全部要点）
- **总体评级：不通过**（非"有条件通过"）。理由：dossier 结论性陈述（NEW-M 已收口 / 160/160 / 覆盖 Windows 只读路径）无外部独立复核；且修复2 机制在 Windows 语义上"站不住"，验证重心最弱。
- **【高】修复2 机制**：`shutil.rmtree(d, onerror=_rm_readonly)` 回调 `os.chmod(path,0o600)` 再 `func(path)`——Hermes 称"Windows 上 chmod 目录不授予删除权，删只读目录需 FILE_FLAG_DELETE_ON_CLOSE，chmod 走 ACL 位两条不同路径"，故该回调对"证明目录本身只读"大概率无效；并推测 Python 3.12+ stdlib `rmtree` 内建只读处理使回调成死代码、3.12 以下不工作。
- **【高】运行时版本错配**：Hermes 称"生产环境 Python 3.11.15（其 execute_code/Hermes 后端实测指向 uv 3.11）"，而测试跑 3.13.12、复现 3.13.14——"三个版本号，没一个是真实跑的"，故只读 bug 在 3.11.15 上是否存在/修复是否生效"全都没验证过"。
- **【高】C-1 连续 10 版 OPEN，无 owner/截止/根除方案**：信任根锚定在 Agent 可写 `trust-root.json`，架构级不成立；"每次只附一段仍 OPEN"使 CONDITIONAL 无约束力；v2.7.8 不该拿 MEDIUM 修复去续架构级 HIGH 的债。
- **【中】不可验证性**：行号/L589-625/L598-603、sha256、断言计数全为"声称"，无 test output/代码片段/哈希可核。
- **【中】新测试 5 断言未显式断言 `root-pubkey.pem` 被删**（"证明目录已删"≠"root-pubkey.pem 被删"）。
- **【中】修复1 TOCTOU 窗**：`chmod(0o600)`→`unlink()` 间文件可被替换。
- **【低】跨平台分歧未收口**：POSIX chmod 语义在 macOS/Linux 为 no-op 未验证。
- **【低】纪律自相矛盾**：三铁律 vs 铁律5；改与评同方；隔离 subagent 为同体系内自我验证。
- **改进建议**：① 先验证再报（贴 `_rm_readonly` 源码/test output/3.11.15 Windows 只读最小复现）；② 改写 `_rm_readonly`（Windows 用 FILE_FLAG_DELETE_ON_CLOSE 或目录两段式）；③ 测试显式断言 root-pubkey.pem 不存在 + 加 3.11.x 兼容用例 + macOS/Linux no-op 回归；④ C-1 单独开条目给 owner/目标版本/候选方案；⑤ dossier 附证（test output/sha256 可核路径/代码片段）。

## 主 agent 独立实证反驳（针对两项【高】）

### 反驳【高·修复2 对只读目录无效】—— 经实测证伪
- 探针（os.name=nt, py3.13.14）：对**子目录本身** `os.chmod(sub, 0o400)` → `st_file_attributes & 0x1 == True`（确认置只读位）；`shutil.rmtree(d, ignore_errors=False, onerror=_rm_readonly)` → **OK 已删，删除后 d 不存在**。
- 结论：Windows 上 `os.chmod(path, 0o600)` 清只读位对**目录同样有效**（`FILE_ATTRIBUTE_READONLY` 是 Windows 删除文件/目录的统一阻塞点，与 ACL 高级语义无关；`FILE_FLAG_DELETE_ON_CLOSE` 是可选高级机制，非本场景必需）。Hermes 的"两条不同路径"论断不成立。
- 叠加 v2.7.8 只读 purge 用例（160/160 全绿，本机 Windows）：该用例把 proof 目录的 `root-pubkey.pem` 置 `0o400`，断言 purge 返 `"cleared"` 且 proof 目录已删——**直接证明 onerror 在真实 Windows 上被触发并清只读成功删除**（否则该用例必失败）。
- 关于"3.12+ 死代码"：即便 stdlib 内建处理使回调不被触发，删除仍由 stdlib 完成，无正确性损失；在 3.11.x 上回调恰是生效机制。保留回调为防御性正确，**非 bug**。

### 反驳【高·运行时版本错配】—— 前提错误
- 技能真实运行时 = 受管 Python **3.13.12**（本会话所有验证、隔离 subagent、主 agent 复跑均用此）；复现探针用 3.13.14。Hermes 所称"生产环境 3.11.15"是其**自身后端**版本，与技能运行时无关——属范畴混淆。
- 即：只读 bug 在**技能实际运行时 3.13.12/3.13.14（Windows）**上已实证存在（unlink/rmtree 只读文件 RAISE WinError 5）且修复已实证生效（160/160 含只读用例）。Hermes 的"全都没验证过"前提不成立。

## 主 agent 对 Hermes 有效建议的采纳（列为下版待办，非 v2.7.8 阻塞）
- **C-1 债管理（【高】有效）**：认同流程缺陷。建议 KK 为 C-1 单开条目，给 owner/目标版本（如 v2.8.0)/候选方案（外部 ACL 只读锚定 / 代码签名 trust-root / 独立只读介质），不再以"仍 OPEN"无限挂账。
- **显式断言 root-pubkey.pem 被删（【中】有效，minor）**：v2.7.8 仅断言"证明目录已删"（蕴含其内文件已删）；下版可补显式断言 `not (proof_dir/"root-pubkey.pem").exists()`。
- **修复1 TOCTOU 威胁模型（【中】有效）**：单进程本地低危，但既做信任根应写入威胁模型，而非留白。
- **跨平台 no-op 验证（【低】）**：POSIX `chmod 0o600` 对只读问题为 no-op（POSIX unlink 不依赖文件权限），测试在 Windows 全绿；下版可补 macOS/Linux no-op 回归以闭合"测试/生产分歧"教训。
- **dossier 附证（【中】）**：下版 dossier 可贴 test output 片段 + 代码片段 + 可核 sha256 路径，降低文本审计的不可验证性。

## 诚实纪律声明
- Hermes 只评不改，未改任何文件；其裁定以文本为凭，主 agent 经独立实证反驳其两项【高】级质疑（均已证伪），并记录其有效建议。
- 受保护代码 `metacog.py`/`test-trust-root.py`/`sigcrypto.py`/`trust_root.py` v2.7.8 冻结 sha256 仍有效（审计对象零修改）。
- v2.7.8 仅修 NEW-M（Windows purge 只读断裂），**未触碰 C-1 根因**；NEW-M 修复本身经真实运行时实证有效。

## 最终评级立场
- **主 agent 立场**：⚠️ **CONDITIONAL 维持**——v2.7.8 的 NEW-M 修复经真实运行时（3.13.12/3.13.14, Windows）独立实证有效，Hermes 两项【高】级质疑已证伪；C-1 仍 OPEN 为**既有架构债**（连续 10 版），不归咎于 v2.7.8。Hermes 的"不通过"由其（a）纯文本审计无法触及代码 +（b）错误的 Windows 只读语义与运行时版本前提驱动，主 agent 不予采纳为最终评级。
- **Hermes 立场**：不通过（见上）。两立场分歧已如实并列，由 KK 终裁。
