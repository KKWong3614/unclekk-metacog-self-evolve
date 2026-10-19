# 独立审计 · unclekk-metacog-self-evolve v2.5.8

- **审计对象**：`unclekk-metacog-self-evolve` @ v2.5.8（SKILL.md / CHANGELOG.md / scripts/metacog.py / scripts/test-human-gate.py）
- **审计方**：Hermes 审计长（`mcp__hermes__hermes_audit`，自称「异族独立审计员」；但历次（v2.5.6/v2.5.7）自陈执行方为本机 Hermes 自身，与被审同栈，**非真异族**——本结论沿用此诚实边界）
- **审计时间**：2026-09-29（KK 重启并重新信任 Hermes MCP 后派发）
- **前置**：v2.5.7 实跑复验裁定 ⚠️ CONDITIONAL，退回 5 项待 v2.5.8 落地；KK 授权「全部 5 项一并修」，本版一次收口

---

## 1. 审计过程（诚实记录两次派发）

**第一派发（自述版）**：提交 v2.5.8 五项修复的**自述摘要**作为 content。Hermes 返回 **「不通过」（2 HIGH 阻断 + 多项中/低）**，但同时自陈：**未能在磁盘上定位 skill 源码**（搜索 `D:/hermes/skills`、`C:/Users/Administrator` 均无 `metacog` 命中），故裁定基于自述文本而非真实代码。

**第二派发（代码级）**：显式给出绝对路径，要求 Hermes 直接 `Read` SKILL.md / CHANGELOG.md / metacog.py / test-human-gate.py，并对照代码验证实现。Hermes 实际读盘并跑了一个**只读校验脚本**（落 `C:\Users\ADMINI~1\AppData\Local\Temp\hermes-verify-metacog-v258.py`），结果：

```
G1: 11/11 PASS   （审计引用的行号在真实文件上仍正确）
G2:  5/5 PASS    （3 个攻击向量可复现）
TOTAL: 16/16 PASS, exit 0
```

Hermes **将裁定由「不通过」升级为「有条件通过（Conditional Pass）」**。即：第一派发的「不通过」主要是流程失误（未让 Hermes 读盘），非代码必然有问题。本记录如实保留两次结果。

---

## 2. 五项修复核验（代码级，实锤落地）

| 项 | 代码位置 | 核验结论 |
|---|---|---|
| LOW-6b bad-pubkey 分支 | `cmd_apply` requires_human 分派表（新增 `elif reason == "bad-pubkey":`，human_blocked+=1 + bad() 指路 confirm --keygen + 退出码 2） | ✅ 落地 |
| M-8 bool 子类 | `resolve_trial_start` 守卫 `if type(t0_raw) is not int:`（排除 bool 子类） | ✅ 落地 |
| H-2 applies.jsonl 纳入 D4 | `record_apply` 末尾 `record_integrity(APPLIES_INTEGRITY_KEY)`；`_integrity_path` 新增 applies 分支；`applies_integrity_ok()` 无基线返回 True（向后兼容） | ✅ 落地 |
| H-1 非 req 锚 content_hash | `cmd_apply` 所有锚内嵌 content_hash；`resolve_trial_start` 顶部先校验 applies.jsonl D4（L1716-1717），非 req 锚校验 content_hash（L1771-1773） | ✅ 落地 |
| M-4 resign 重签 | `cmd_resign` 保留 t0 重签绑定签名；`--sig` 路径在 L1807 仍经 `verify_human_binding` 验签 | ✅ 落地 |

---

## 3. 第一派发两条 HIGH 在真实代码下的复核

- **H-1（「无基线返回 True = 首次部署绕过」）**：代码确为 `applies_integrity_ok()` 无基线返回 True（L518-519），是**向后兼容权衡**（不误伤 v2.5.8 前安装、尚未 apply 的安装）。**关键**：即便 D4 无基线，非 requires_human 锚的 **per-anchor `content_hash` 校验（L1772）仍运行**——攻击者须预写一条 `content_hash` 与提案当前内容一致的 applies.jsonl 才能漏。真实残留 =「攻击者在首次 `record_apply` 前预写被污染 applies.jsonl」的窄窗口，属防御纵深缺口，非干净 bug。**评级修正**：由 HIGH 降为 **MEDIUM（含向后兼容权衡）**。
- **H-2（「resign --sig 绕过 TTY human gate」）**：**裁定不准确**。代码 L1806-1812：`--sig` 传入后立即 `verify_human_binding(p, _sig_arg, t0, anchor_chash=chash)` 验签，无效则拒绝返回 2。**跳过的是 TTY/口令交互仪式，未跳过密码学验签**（仍须有效私钥签名）。该残留已在诚实天花板 M-1 披露（绑定签名仅证「私钥确认」，非「人类在场」）。**评级修正**：由 HIGH 降为 **LOW（操作披露项，非门绕过）**。

---

## 4. 新发现（均 MEDIUM/LOW，非阻断）

- **N1'（resign int() 裸奔）**：`cmd_resign` L1803 原 `t0 = int(old.get("trial_from_index"))` 沿用 M-8 已在 `resolve_trial_start` 修过的同模式裸奔——畸形 t0（bool/str/list/null/缺键）经 `int()` 抛错或逃逸 `(int,str)` 契约。**处置**：已在收口补丁中补 `type(t0_raw) is not int` 严格守卫（fail-closed）+ 新增回归 `test_n1p_resign_int_guard`（10/10）；隔离验证 201/201 全绿。
- **N2'（D4 自指根，结构性）**：D4 完整性快照 `integrity.json` 与 `applies.jsonl` 同 ledger 目录、同权限；整目录被控于静止态时自指链断裂。**性质**：结构性限制（类比 C-1），非代码 bug；须靠底层存储/权限隔离弥补。**处置**：归入诚实天花板披露，不修。
- **recurring pattern（「修了实例未修类」）**：`verify_human_binding` 分派表每次新增理由码须手动同步（LOW-6b 曾漏）。属可维护性观察，建议后续改为数据驱动分派或加测试断言覆盖全理由码。

---

## 5. 验证口径（诚实边界）

- 隔离 subagent 实跑 5 套件 **201/201 PASS**（test-human-gate 69/69 含 6 个 v2.5.8 相关新增回归、test-core 14/14、test-boundary-cases 40/40、test-d2-d5 47/47、test-held-out 31/31），零 FAIL / 零断言异常 / 退出码 0。**属 self-attested**（同一作者写的测试、同代码库运行），**非独立审计**。
- Hermes 只读校验 16/16（G1 11/11 + G2 5/5）证明审计引用的代码位置与攻击向量在真实文件上成立。
- Hermes 自承「非真异族」——与 v2.5.7 一致；独立性的根本局限未消除。

---

## 6. 裁定

**有条件通过（Conditional Pass）**——五项修复实锤落地、N1' 收口补丁已加、无新增 HIGH。维持 **CONDITIONAL 档**（未推过，但确认未降级）。

**仍 OPEN（诚实天花板）**：
- C-1 循环论证（根信任层绝不宣称安全）
- C-2 部分（仍依赖人工带外核验指纹）
- N1（symlink，待 PoC）
- N2'（D4 自指根，结构性）

**声称口径（铁律）不变**：本系统是「人在环、系统级强制的可控自指」／「受控元认知自修改」，永不声称"无需人类在环""系统自主可控""闭环可控自指（无人类）"。

---

## 7. 附：审计长遗留问题（已答复）

审计长末问「是否写审计报告到 references/independent-audit-v2.5.8.md」——已写本文件。收口动作（N1' 落地 + 评级更新为 Conditional Pass + N2'/recurring 披露）经 KK 授权「落 N1' + 全收口」执行完毕。
