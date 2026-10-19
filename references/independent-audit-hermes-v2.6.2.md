# 独立审计 · Hermes 代码级复验 · unclekk-metacog-self-evolve v2.6.2

> 审计方式：本机 Hermes（文本专家）以「异族独立审计员」身份审查。Hermes 在本环境**无磁盘读权限**（HANDOFF §7 已预警），故主 agent 按 §7 纪律将 **真实代码文本** 组装成 dossier（`/tmp/hermes_dossier.txt`，39KB，含 trust_root.py 全文 + metacog.py 两处改动片段 + test-trust-root.py 新增 6 测试 + 8 条诚实边界原文 + v2.6.2 收口说明）作为 `hermes_audit` 的 `content` 喂入。Hermes 自陈"未做独立代码复现或测试复跑，仅基于贴出片段"，故其裁定与 v2.6.1 同属**文本级**复验，非真异族（执行方与被审同栈）。
> 总体评级：**⚠️ CONDITIONAL 维持（不上调）**。
> 时间：2026-09-30（v2.6.2 实现 + 隔离 subagent 258/258 验证后统一派发）。

---

## 范围声明（Hermes 自述）
本机未找到 trust_root.py 实体，审计仅基于 dossier 贴出片段；未独立复现/复跑。对"258/258" subagent 自陈只能判可信度，不能独立验证。

## 总体评级：维持 CONDITIONAL
不建议上调至 PASS。理由：
- Q1 六个 MEDIUM 中真正代码层闭合的仅 MEDIUM-1（部分）、MEDIUM-2/6（部分）；MEDIUM-3/4/5 未闭合。
- 出现两个此前 v2.6.1 未指出的 MEDIUM 级残留（H-1 DenyTrustRoot reason 被吞；H-2 hsm 单独在 build 层可绕过）。
- 审计自陈"self-attested 非独立审计"，258/258 无独立复核证据。
- 威胁模型假设（attestation_path / oob_token_dir 需 Agent 无写权限）与代码实际行为（_is_protected 仅 WARN-only）不一致，文档 ⑦ 含 over-claim。

## 关键发现清单

### H-1 / MEDIUM — DenyTrustRoot 细分 reason 被 check_pubkey_root 吞掉
- `DenyTrustRoot.oob_token_required()` 恒 True → `check_pubkey_root` 先走 oob 分支 → `oob_confirmed` 恒 False → 返回 `"oob-confirmation-required"`。
- 结果：v2.6.2 声称的 corrupt / unknown-backend / no-provider 三类细分 reason 在任何启用路径上都到不了最终错误消息。LOW 收口项实际未生效，诊断能力被削弱。
- 修复：`oob_token_required()` 依据 `self.reason` 判断（corrupt/no-provider/unknown-backend 时返回 False），或 `check_pubkey_root` 进入 oob 分支前优先检查 reason。

### H-2 / MEDIUM — MEDIUM-3 "禁止单独 hsm" 仅在 CLI 层
- `_confirm_keygen` 拦截 `--enable-external hsm`；但 `build_trust_root` 对 `backend=="hsm"` 直接返回 `HsmTrustRoot`，无防御。
- 在 ledger 可写威胁模型下（文档 ⑦ 承认），攻击者可写 trust-root.json 为 `backend="hsm"+sim_key`，绕过 oob，MEDIUM-3 的 CLI 防线不成立。
- 修复：`build_trust_root` 内对 `backend=="hsm"` 直接 `return DenyTrustRoot("external-anchor-standalone-hsm-forbidden")`；`TrustRootConfig.load` 里校验。防线下沉到 build 层。

### M-1 / MEDIUM — MEDIUM-5 删除 trust-root.json 绕过：文档承认，代码未闭合
- `TrustRootConfig.load`：`if not p.exists(): return cls()` → legacy → build 返回 None → `check_pubkey_root` 的 `if ext is not None` fall through 放行。
- `test_delete_config_fallback_legacy` 把 fail-open 断言为 PASS，等于固化行为契约。ledger 可写模型下等价于"删除文件即关闭外部锚"。
- 修复：(a) 若有启用历史，config 缺失时 `return DenyTrustRoot("external-anchor-config-missing")` 不 fail-open；(b) 或显式声明信任根启用状态须外部持久化（非 ledger）。

### M-2 / MEDIUM — _is_protected 覆盖不全且测量对象错配
- 只检 `pp` 与 `pp.parent`，祖先目录可写时仍可 rename/delete。
- `os.access(t, W_OK)` 测当前进程权限，非 Agent 任意子进程/终端命令写能力；Windows NTFS ACL 下不可靠。
- oob_token_dir 被删时返回 None，被 `_deploy_warn` 误报"不存在"而非"未受保护"。
- `oob_confirmed` 对"不存在/symlink/无 token"统一返回 False → 最终统一报 `oob-confirmation-required`，失诊断意义。
- 修复：扩展祖先遍历 2–3 级；`oob_confirmed` 改签名 `(bool, str)` 回传 reason。

### M-3 / MEDIUM — 跨午夜 challenge 窗口不一致
- `challenge_for` 在 `oob_confirmed` 调用前算 `window=today`；午夜边界跨过则令牌文件按昨天 hash 命名，challenge 按今天算 → content 匹配但文件名不匹配 → fail-closed。
- 修复：`challenge_for` 同时返回 window 值并作为参数传入 `oob_confirmed`。

### M-4 / MEDIUM — oob 防重放实质强度低于表面
- challenge 完全由 (op, window=date, pub) 决定，无 nonce/签名/时间戳/高熵/每日轮转。
- 能写 oob_token_dir 者即可离线预生成今日 challenge+同 content 令牌。
- 防重放实际靠"oob_token_dir 写保护"部署契约，而非 content 校验或原子消费；而该契约仅 WARN-only 且 M-2 覆盖不全。
- 建议：文档明确"写保护是主防线，content 校验是二次冗余"，避免下游误判多重独立防线。

### L-1 / LOW — TOCTOU 竞态
- `_assert_real_path` 与后续 `os.path.isfile`/`read_text`/`os.replace` 间有时序窗口；有写权限者可精确替换为 symlink。
- 修复：`os.open(O_NOFOLLOW)` 或 fstat 校验 `st_nlink`。

### L-2 / LOW — sim_key 明文落 ledger，边界⑦承认但无代码护栏
- `write_trust_root_config` 无"禁止生产使用"校验；`backend==hsm` 且 sim_key 非空仍正常写盘。
- 修复：sim_key 落盘强制附 `"production_forbidden": true` 并拒绝加载生产模式；或改 env/keyring 注入。

### L-3 / LOW — test_delete_config_fallback_legacy 语义与文档相反
- 把 fail-open 回退当 PASS 断言，读起来是"闭合验证通过"，实际固化 M-1 缺陷。
- 修复：改为期望 DenyTrustRoot（fail-closed），或重命名并注明"已接受边界"非"验证通过"。

### L-4 / LOW — 版本号跳号
- v2.6.1→v2.6.2 新增安全机制+8 边界+新测试，按语义版本宜为 v2.7.0。

### L-5 / LOW — "258/258 subagent self-attested" 不可复核
- 未提供验证脚本源码、subagent 输出日志、失败用例原始输出。数字算术自洽但证据不足。

### L-6 / LOW — DenyTrustRoot 违背 LSP
- 实现 TrustRoot 接口但方法硬返回 False/"denied"；`oob_token_required` 恒 True 语义不对（外部锚禁用时不应要求 OOB）。H-1 根因在此。

## Q1 / Q2 / Q3 逐项

### Q1（MEDIUM-1/2/3/4/5/6 是否闭合）
- MEDIUM-1 symlink 防御扩展：**部分闭合**。三处都做 `_assert_real_path`，但只检自身+父，未查祖先 symlink，且 TOCTOU（L-1）。
- MEDIUM-2 oob 内容+原子消费+challenge 绑 op+window：**部分闭合**。设计正确，但跨午夜失效（M-3），实际强度取决于 oob_token_dir 写保护（M-4）。
- MEDIUM-3 禁止单独 hsm：**未闭合**。仅 CLI 层（H-2），build_trust_root 无防御。
- MEDIUM-4 sim_key 位置披露：仅文档，非代码闭合。写盘无生产禁用护栏（L-2）。
- MEDIUM-5 删除配置绕过：**未闭合**。文档承认（边界⑧）但代码未改，测试反向固化（L-3）。
- MEDIUM-6 C-1 表述限定：**部分闭合**。边界⑦"仅 oob 实质闭合"准确；但"依赖 attestation_path/oob_token_dir 确为 Agent 无写权限"代码未强制（M-2），over-claim。

### Q2（能否上调）
维持 CONDITIONAL。硬理由：
1. H-1+H-2 是新暴露 MEDIUM 残留，v2.6.1 未指出 → "全量 P1+P2 收口"实际不完整。
2. 审计证据链断：258/258 自陈，无可复核产物。
3. 威胁模型 vs 代码执行不一致：文档假设目录写保护是部署前提，代码只 WARN 不强制且覆盖不全。

### Q3（8 条诚实边界一致性）
- ① hsm 用 SimKeyProvider / TokenKeyProvider 桩 fail-closed：**准确**。
- ② 单独 hsm 无安全意义：意图准确，但 **over-claim**——"必须叠加 oob"代码上非强制（H-2）。
- ③ 默认关闭 C-1 默认 OPEN：基本准确。**under-claim**——未提"删除 trust-root.json 也会关闭"，实际两条关闭路径。
- ④ 可插拔 KeyProvider，sim 仅测试：**准确**。
- ⑤ 无法接受真机令牌签名：**准确**。
- ⑥ 评级维持 CONDITIONAL 待 Hermes 复验：**准确但应更新**——本次已构成复验条件，⑥ 应改为"已复验，维持 CONDITIONAL"。
- ⑦ 仅 oob 实质闭合 C-1，依赖 attestation_path/oob_token_dir Agent 无写权限：前半准确，后半 **over-claim**——代码仅 WARN-only 且覆盖不全（M-2）。
- ⑧ 删除 trust-root.json 属结构性限制无法闭合回 legacy：准确，但"无法闭合"措辞过重——代码可 fail-closed（return DenyTrustRoot），是可修未修。

## 改进建议（Hermes）
- P0：① DenyTrustRoot.oob_token_required 依 reason 判断 或 check_pubkey_root 优先 reason 白名单（H-1）；② build_trust_root 拒绝 backend=="hsm"（H-2）；③ 明确 config 缺失语义 fail-closed 或外部持久化（M-1）；④ oob_confirmed 签名改 (bool, str)。
- P1：⑤ _is_protected 扩展祖先 2–3 级 + oob_confirmed 区分四类原因；⑥ challenge_for 显式传 window；⑦ 文档写清 oob 主从防线。
- P2：⑧ _assert_real_path 加 fstat/O_NOFOLLOW；⑨ write_trust_root_config 拒 production sim_key 落盘；⑩ 测试更名注明"已接受边界"；⑪ 版本升 v2.7.0 同步文档；⑫ 提供验证脚本源码+原始输出使 258/258 可复核。

## 五个审计维度小结（Hermes）
1. 逻辑漏洞：C-1 在 ledger 可写模型下只能被 oob 部分闭合，hsm 不构成外部锚——文档承认方向对；但 MEDIUM-3/5 实际未闭合，全量收口表述不成立。
2. 安全隐患：新增 H-1、H-2、M-1、M-3、M-4、L-1；sim_key 明文（L-2）文档承认但代码无护栏。
3. 偏见与 AI 味：审计文本相对诚实（承认 self-attested）；但主材料对 MEDIUM-5 "结构性无法闭合"措辞过重，对 oob 多重防线表面强度轻微夸大；"破 C-1 循环论证"限定应前置到主叙事而非只放边界⑦。
4. 规范性：版本号跳号；SKILL.md/CHANGELOG.md 同步性未见；DenyTrustRoot 违背 LSP；expected_content 隐式约束未文档化。
5. 可用性与完整性：无独立复核证据（L-5）；错误粒度丢失致排障难（H-1、M-2）；test_delete_config_fallback_legacy 命名与文档相反误导后续审计（L-3）。

## 审计员独立性声明（Hermes 自陈）
本报告"异族独立审计员"角色与本机 Hermes 主体存在归属重叠，独立性弱于真正异族审计。建议由完全异质 agent（不同 provider、不同工作目录、无本机 skills 访问权）复跑一次。
