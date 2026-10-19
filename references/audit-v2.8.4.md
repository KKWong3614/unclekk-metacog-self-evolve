# 统一 Hermes 复验 — unclekk-metacog-self-evolve v2.8.4（铁律 5）

- 日期：2026-10-09（重派；前次 FAIL 系审计路径错配：D:/skill待检/ 当时为旧 2.1.1 副本，本次已同步为真实 v2.8.4 工作树）
- 审计目标（磁盘）：`D:/skill待检/unclekk-metacog-self-evolve/`（已镜像真实 `C:\Users\Administrator\.workbuddy\skills\unclekk-metacog-self-evolve`，8 冻结哈希 8/8 实测一致）
- 总体评级：**不通过（FAIL）— 由 CONDITIONAL-PASS 下调**

---

## 裁定理由
Hermes 指认 3 条 HIGH 新发现（H-1 / H-2 / H-3），其中 H-1 为本次变更直接引入的回归。维持 CONDITIONAL-PASS 的依据不成立，评级应下调，不宜维持。

## 10 条处置实测复核（Hermes 以磁盘实测为据，非采信自述）
| 编号 | 主张 | 实测结论 |
|---|---|---|
| M-1 | 行号 3027→3041、L868/909→L875/914 | 部分成立；行号 3027→3041 正确，但 L875/L914 仍偏 2 行（实测 L877/L925）→ 精度问题复发（见 L-1'） |
| M-2 | 参数化遍历全部 8 个 `/` 条目 | 成立（test-trust-root.py，含键集合对称断言） |
| M-3 | verify_integrity 遍历 script: 键、含删除 current=None | 部分成立；删除检出有效，但引出 H-1 孤儿键永久 dirty |
| M-4 | cmd_apply 落盘前 verify 硬闸 | 部分成立（metacog.py L1833-1844 确在 record 前）；但硬闸走 verify_script_integrity，完全绕过孤儿键，且 METACOG_TRUST_ROOT_STRICT 在测试 0 处引用 |
| M-5 | 诚实标注 C-10 为「漂移检测器」 | 成立（CHANGELOG.md）；v2.8.4 唯一真正诚实的条目 |
| M-6 | 删 __pycache__、加 .gitignore | 不成立（见 H-2） |
| L-1 | 「天然支持」→「恰好支持」 | 成立（metacog.py）；但 HANDOFF 残留「18 元组」旧口径 |
| L-2 | 覆盖率分子拆分 | 成立；但同文档 398/399 行仍写「18 元组 / 18/47」→ 文档自相矛盾 |
| L-3 | SCRIPT_NAMES 18→17 | 代码成立（len=17 实测），文档未成立，且引入 H-1 |
| L-4 | 恢复 24 套件总 PASS | 607/607 由本方复跑确认；Hermes 独立复跑 test-trust-root 192/192 口径无水分 |

冻结清单 8/8 sha256 **全部实测一致**。

## 关键发现
### H-1【高·新引入回归】L-3 × M-3 交叉 bug：孤儿基线键永不清理，cmd_verify 永久失败
`record_script_integrity`（metacog.py L877-894）只 add 从不 delete；L-3 把 `domains/knowledge_transfer.py` 移出 SCRIPT_NAMES。M-3 让 `verify_integrity` 遍历已有键 → 存量基线（v2.8.3 含该键）升级后产生永久 dirty。
- 后果 1：存量安装每次 `verify` 返回 rc=1，除非先 `apply`/`keygen` 重记基线。
- 后果 2：告警（verify_integrity 含孤儿）与硬闸（verify_script_integrity 仅遍历 SCRIPT_NAMES 不含孤儿）不一致 → 告警可信度自毁。
- 材料从未处理存量 integrity.json 迁移。

### H-2【高】M-6「__pycache__ 已删」为假，且 .gitignore 不构成发布隔离
- 真实 C: 树 `scripts/benchmark/__pycache__`、`scripts/domains/__pycache__` 仍存在（M-6 仅删顶层 scripts/__pycache__）。
- .gitignore 只影响 git 索引；skill 经目录拷贝/打包分发，gitignore 对 zip/cp 无效 → 概念偷换。
- CHANGELOG.md.bak(182KB)、audit-brief-v2.5.5-sigcrypto.md、5× hermes-verify-*.py 仍游离于仓内 → 仓库卫生实质未改善。

### H-3【高】文档口径自相矛盾 + 核心修复零回归测试
- 同一文档内口径冲突：v2.8.3 块记「18 元组 / 18/47」、v2.8.4 块记「17 = 9+2+6」、HANDOFF 残留「18 元组」+「天然支持」。
- 607 条断言覆盖不了最危险改动：METACOG_TRUST_ROOT_STRICT **0 处引用**；M-4 apply 硬闸、M-3 script 删键(current=None)、M-3 孤儿键均无测试 → 测试套件与变更集脱节。

### M-1'【中】`.git 仓未建` 与磁盘矛盾（部分同步伪影，见下方本方核验）
材料 M-6 写「.git 仓未建」，但 D: 磁盘 `.git` 存在（HEAD 6f33d8a）。**注：此系本次同步保留 D: 旧 2.1.1 .git 所致；真实 C: 树 `git status` 实测 fatal: not a git repository（无 .git）**。但「仓内 40+ 游离文件」属实（junk 文件真实存在）。

### M-2'【中】record_script_integrity 调用点不对称
实测 apply(1845)/keygen(2227)/confirm(2897) 三处落盘；仅 apply 前置 M-4 硬闸；keygen/confirm 同样触发受信锚落盘却先 record 后无 verify。

### M-3'【中】C-10「漂移检测器」定位弱化 C-1 闭合结论
M-5 承认 integrity.json 无签名、C-10 非控制面；但第四节仍称「C-1 在窄威胁模型内软件层闭合（v2.8.0）」。两者不能同时成立，应反向传播到 C-1 评级。

### L-1'【低】引证精度系统性复发（第二次）
v2.8.3 审计 M-1 即指出行号漂移，v2.8.4 再现（文档写 L875/L914，实测 L877/L925）。无「发布前 grep -n 复核」机械流程。

### L-2'【低】材料自我辩护未获证实
M-6 称「前次 Hermes FAIL 系路径错配」为追溯性翻案，未附同步前后哈希对证 → 标注为未经核证（本方本次已实测 8/8 一致佐证）。

### L-3'【低】可用性：文档体积
SKILL.md 158KB + CHANGELOG.md 227KB + HANDOFF.md 93KB ≈ 478KB，v2.8.4 未处理反增长。

### 附加（未列入 10 条）
`METACOG_TRUST_ROOT_STRICT` 判据 truthy（`os.environ.get(...)` 非空即真，`=0`/`"false"` 均生效），与 `METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR` 严格 `=1` 不一致；v2.8.2 高-1 修的是后者，前者复现同类缺陷且无测试。

## 本方独立核验（真实缺陷 vs 同步伪影）
- 真实 C: 树已验证：version 2.8.4；8 冻结哈希一致；scripts/benchmark/__pycache__、scripts/domains/__pycache__ 仍存在；CHANGELOG.md.bak / audit-brief-v2.5.5-sigcrypto.md / 5× hermes-verify-*.py 驻留；`git status` → fatal: not a git repository（无 .git）。
- **H-1 经读码确认（metacog.py L877-944）**：record 只 add 不 delete；verify_integrity 遍历全键（含孤儿→dirty）；verify_script_integrity 仅遍历 SCRIPT_NAMES（不含孤儿→硬闸不拦）。存量安装升级后 verify 永久 rc=1、告警与硬闸分裂 → 真实回归。
- **L-1' 经 grep 确认**：record_script_integrity=L877、verify_script_integrity=L925，文档写 L875/L914 确为错误（本方精度修复自身不精，须 v2.8.5 更正）。
- **M-1'「.git 存在」为同步伪影**：D: 保留了旧 2.1.1 的 .git（HEAD 6f33d8a），真实 C: 树无 .git。但「仓内游离 junk 文件」为真实。
- **H-3「文档自相矛盾」主要为误读历史版本块**（v2.8.3 块记 18、v2.8.4 块记 17，乃各版本快照非矛盾）；真实缺陷在于 M-3/M-4 零回归测试。

## 诚实边界（v2.8.4 维持）
- M-5 integrity.json 无签名；C-10 仅漂移检测器非控制面；根因 C-1 OPEN。
- 禁称「无人类闭环 / 已安全」。

## v2.8.5 backlog（阻断项）
1. **[H-1]** record_script_integrity 加孤儿清理（删除不在 SCRIPT_NAMES 的 script: 键）；verify_integrity 记「孤儿已清理」事件而非永久 dirty；CHANGELOG 注记存量安装需 apply 一次重建基线。
2. **[H-2]** 实删 scripts/**/__pycache__；明确 .gitignore ≠ 发布隔离（提供打包白名单/MANIFEST.in）；移出 CHANGELOG.md.bak / audit-brief-* / 5× hermes-verify-*.py。
3. **[H-3]** 补 5 回归测试：孤儿键清理、script 文件删除(current=None)、METACOG_TRUST_ROOT_STRICT 真值表（=0/"false"/"1"/未设）、cmd_apply 硬闸拒绝(rc=3)、cmd_verify dirty 含 script 键。
4. **[L-1']** 修正文档行号 L875/L914 → L877/L925（SKILL/CHANGELOG）。
5. **[M-2']** keygen/confirm 落盘点补 M-4 同款前置 verify 硬闸。
6. **[附加]** METACOG_TRUST_ROOT_STRICT 改严格 =1，与 ALLOW_LEGACY_NO_EXTERNAL_ANCHOR 一致。

## 冻结清单 sha256（8 文件·2026-10-09，D: 实测 8/8 一致）
- scripts/metacog.py            777f407018bd4d080db6404155affc7268a9177ec28a95971db8c76882474fdf
- scripts/test-trust-root.py   cf2afe7a3f007ecef1323acda62bdc363180b6314dd1593e0d918d83aba12528
- SKILL.md                    7fffd8fc63cfd6947a70a2d196f1ba45089cc0d43ee0594a962db9a8002ab334
- HANDOFF.md                  e4b68afbdc879e0dbacc0e6ce016409788d94065b0b3da6de19576a6b8d10452
- scripts/trust_root.py       c7692c81cacd330fb5424fc2c4f53899443ac0a7f5a897748838bff4cb4e3c3e（未改动·对照）
- scripts/test-human-gate.py   2de1c0d50a37c36e196105383e415530e41fd682a75912da76217fe92bb914e5（未改动·对照）
- scripts/test-core.py        210c72ca5947181eda33e1a9e3d9a66019d34a92e291bf8c9e3e943cbf12a3db（未改动·对照）
- scripts/sigcrypto.py        c51d1eb012835cce6461708c5aff14b1faa7842881b24559994a977ae167f517（未改动·对照）
