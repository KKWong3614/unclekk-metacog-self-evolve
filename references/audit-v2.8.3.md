# 统一 Hermes 复验报告 · v2.8.3（铁律5）

> 审计对象：skill:unclekk-metacog-self-evolve · v2.8.3（Hermes v2.8.2 高-2 收口：C-10 补嵌套运行时包）
> 审计方：本机 Hermes（文本级审计员，非真异族；结论以磁盘实跑为凭，不采信材料声称）
> 派发时间：2026-10-09（铁律5：所有修改一次性做完并冻结后最后派发）
> 材料来源：主 agent 组装的 v2.8.3 审计载荷（代码 excerpt + 验证摘要 + 诚实边界 + 冻结哈希）

---

## 一、总体评级

**有条件通过（CONDITIONAL-PASS 维持，不上调）**

高-2 确已收口，Hermes 独立复算通过；但初稿发布门禁工件（HANDOFF 冻结哈希）自指失真，且收口质量（测试宽度、硬闸覆盖）弱于材料叙述。无新增阻断发布的高危。

---

## 二、高-2 收口裁决：确认（实证，非采信）

1. `SCRIPT_NAMES` 实测为 18 元组，含 9 条带 `/` 的嵌套路径，全部落盘。
2. record/verify 含 `/` 键处理正确：隔离临时目录重建全部 18 脚本布局，实跑 `record_script_integrity` → 基线产出恰好 18 个 `script:` 键，NOT IN BASELINE 为空；篡改 `domains/__init__.py` 后 `verify_script_integrity` 精确报 `['script:domains/__init__.py']`。record 与 verify 键集合实际对称。
3. 覆盖率数字对得上：scripts/ 顶层 .py 实为 38（含 24 test-*、5 hermes-verify-*），38 + 9 嵌套 = 47，覆盖 18/47，剩 29 为测试/审计残留。
4. 嵌套包性质描述准确：`metacog.py:3041` from domains.init import init_domain（材料曾写 :3027，见 M-1）、`metacog.py:33` / `domain_detector.py:10` from domains import DOMAIN_TEMPLATES；benchmark/ 确为独立 CLI 包（run_all.py 自行 bootstrap sys.path，非引擎 import）。

---

## 三、关键发现清单

### 【高】H-1　HANDOFF.md 冻结哈希不可信，且自相矛盾（已修）
- 申报：HANDOFF.md = 758ea4da…18b4
- 实跑 sha256：a3ee9f60…f6ad（最终）/ 初稿 51c29ee9…（§2.22 写入后）
- 矛盾根因：HANDOFF.md 在写入 §2.22 冻结块时，块内记录了 HANDOFF.md 自身哈希；而该哈希是写入前的值，且文件含其自身哈希本身无解（自指）。其余 7 文件哈希全部对版。
- **处置（v2.8.3 已修）**：HANDOFF.md 不再自记自身哈希；其冻结哈希改由 CHANGELOG v2.8.3 冻结清单承载（容器 CHANGELOG 不列自身，无自指）；冻结清单 HANDOFF.md 条目已更新为最终实测 `a3ee9f607d713dc485285fe28204c5e19b37dae4ef41452a1f64a1a61aa2f6ad`。8 文件哈希现已全数对版。

### 【中】
- **M-1 行号引用漂移**：metacog.py:3027→实际 3041；record_script_integrity L881-889→实际 893；verify_script_integrity L914/922-932→实际 936。结论方向不受影响，但引证精度退化。
- **M-2 测试断言宽度不足**：test_c10_nested_package_integrity 仅覆盖 1/18 嵌套文件（domains/init.py）；benchmark/ 6 文件 0 覆盖；script_dir 三档布局分支 0 覆盖；record/verify 键集合对称无断言保护。
- **M-3 删除检测单点依赖**：verify_integrity（L896-897）主动 continue 掉所有 `script:` 键，删除检出完全依赖 verify_script_integrity 单独一条路；cmd_retrieve 的 D4 主告警走 verify_integrity（0 条 script:），删除类攻击只能等受保护模式才被发现。
- **M-4 硬闸覆盖不全**：verify_script_integrity 仅接入 cmd_retrieve（需外部锚激活或 STRICT=1）；cmd_apply（L1816-2140）对 integrity 调用 3 次、0 次 verify，只 record 不 verify——最危险动作不受脚本完整性硬闸保护。cmd_confirm/keygen/resign 同理。
- **M-5 integrity.json 无认证**：write_json 两处（L564、L892）无签名直写；trust-root.json 有 HMAC-SHA256 但 integrity.json 没有。C-10 在 Agent 具 ledger 写权限的部署下安全价值归零，须明确标注为"漂移检测器"。
- **M-6 仓库卫生与可审计性**：scripts/nul、out.txt、err.txt 随包发布；无 .git；SKILL.md 154KB / HANDOFF.md 88KB / CHANGELOG 过长；HANDOFF §4 单条 bullet 数千字跨 8 版本堆叠。审计成本本身压低复审执行概率。

### 【低】
- **L-1**「嵌套路径天然支持」宜改「恰好支持」：对称性是手工维持约定，当前无测试保护。
- **L-2**「覆盖 18/47」分子质量不均：benchmark 6 项 + domains/knowledge_transfer.py 非引擎 import，真实引擎主暴露面约 11 项，建议分列申报。
- **L-3** domains/knowledge_transfer.py 全仓仅命中 SCRIPT_NAMES 与注释，无任何 import 方（死代码），应归档或移出基线。
- **L-4** 验证聚合口径回退：v2.8.3 只报 24/24 exit 0，丢了总 PASS 数（应恢复 590 量级实测）。

---

## 四、改进建议（可落地，留 v2.8.4 backlog）

1. H-1：冻结块禁止记录自身哈希；改为 references/freeze-v2.8.x.txt（外部不可写域）承载，与本次审计结论一并落独立锚。
2. M-2：test 参数化遍历全部 `/` 条目逐一改写-检出-还原；新增断言 `set(record 键) == set(verify 键)`。
3. M-4：cmd_apply 制品落盘前插 verify_script_integrity 硬闸（同 cmd_retrieve 条件）；cmd_confirm --keygen 亦加（keygen 是刷新基线入口）。
4. M-5：给 integrity.json 加锚密钥签名（复用 v2.8.0 HMAC），或删除"C-10 是控制面"隐含表述。
5. M-3：verify_integrity 主告警路径也遍历 `script:` 键（非阻塞告警）。
6. L-3：归档/删除 domains/knowledge_transfer.py、benchmark/ 若非必需。
7. M-6：加 .gitignore 覆盖 nul/out.txt/err.txt 并删除；建 .git 获可回溯锚；HANDOFF §4 按版本分节。
8. M-1/L-4：下一版材料行号先 grep -n 复核；恢复 24 套件总 PASS 数。

---

## 五、结论

高-2 代码改动真实有效（实测通过），无新增阻断发布的高危。初稿"冻结清单"因自指哈希失真已修（H-1），现 8 文件哈希全数对版。评级维持 CONDITIONAL-PASS。M-/L- 共 10 条发现均非阻断，留 v2.8.4 强化 backlog。
