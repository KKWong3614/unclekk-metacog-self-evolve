# 第三方审计签字操作指引（C-1 闭合 legs 之二 · 外部人工步骤）

> 版本：v2.27.27 ｜ 归属：C-1 完全非对称化专项（`asymmetric-trust-root-design.md` §5/§6）
> 性质：**代码无法代执行的人工步骤的操作规范**。本文档本身不构成签字，也不改变 C-1 OPEN 口径。

## 0. 结论先行

C-1 结构性闭合判定 = **两条 legs 齐备**：

| Leg | 内容 | 性质 | 状态 |
|---|---|---|---|
| Leg-1 | `METACOG_ATTEST_ROOT_ANCHOR` 指向 Agent 进程**不可写**位置（真正外部域部署） | 部署/OS 步骤 | 待执行（须 owner 指定位置） |
| Leg-2 | **第三方独立审计签字**（本指引） | 外部人工步骤 | 待执行（本文档 = 其操作规范） |

**硬性资格红线**：Hermes / WorkBuddy / DeerFlow / QClaw 及任何**同生态 runtime 内的 Agent 不得充当第三方**——同生态 runtime 审自己参与生成的代码属流程级限制（即 SKILL.md 中 Hermes 审计只能裁定 CONDITIONAL-PASS 的原因）。第三方 = 生态外的人类或组织。

## 1. 签字物证明什么（范围界定 · 先读）

签字**证明**（限定范围）：
1. 审计日在指定部署环境上，Leg-1 已真实成立（外部根锚落点对 Agent 运行用户不可写，实证而非声明）；
2. 离线私钥确离线持有（被约束主机上无私钥文件/口令，或签署后已销毁迁移）;
3. 审计人独立复现关键对抗探针且结果与声明一致（§5 最小探针集）；
4. 诚实边界文档（`asymmetric-trust-root-design.md` §6、CHANGELOG）与实证相符，无夸大。

签字**不证明**（如实边界）：
- 不证明「无任何漏洞」；不证明未来版本；不证明 TRACE 评级（两套独立口径）；
- 不根除 C-1 根残余的**历史**：env 锚密钥本进程可读属部署契约残余，Leg-1+Leg-2 使「同用户静默自签」在**该部署环境**上不可行，但环境变更/版本变更即失效（§7 复签条款）；
- 签字后 C-1 判定为「**在该签字所描述环境 + 版本上闭合**」；环境或版本变更 → 回到 OPEN，须复签。

## 2. 前置条件清单（Engage 审计人之前逐项打勾，缺一不送审）

- [ ] **Leg-1 已完成**：`METACOG_ATTEST_ROOT_ANCHOR` 指向 Agent 进程不可写位置；以 Agent 运行用户实测写该目录 → Access Denied（留存证据截图/命令输出）。
- [ ] 外部根锚已密封：`anchor-attest-root-seal` 在特权令牌门内执行成功；锚文件只读；`anchor-attest-verify` PASS。
- [ ] `anchor-attest-pubkey-install` 完成（CONTRACT.md 钉固 = 外部根锚 = 树外公钥指纹三方一致）。
- [ ] 离线密钥：`anchor-attest-keygen` 在**干净离线机**执行；私钥已移离线介质；被约束主机全盘搜索无私钥文件（`anchor-attest-priv.enc`）与口令 env。
- [ ] attestation 由人类在信任环境签发且未过期（`METACOG_ATTEST_MAX_AGE_DAYS` 默认 90）。
- [ ] 质量基线：`test-c1-attestation.py` 全 PASS、`_run_all_tests.py` 全量诚实 PASS、`freeze.verify()` GREEN、版本五处一致。
- [ ] Windows 特殊名残留（`scripts/nul`、`scripts/C:Users…m7-poc-root`）已向审计人如实披露（OS 安全边界残留，无害、不可常规删除）。

## 3. 审计人资格要求

1. **独立性**：非 skill 作者/owner；不属于被约束 Agent 所在 runtime 生态（WorkBuddy/Hermes/DeerFlow/QClaw 及其插件作者均不合格）；与 owner 无共享凭据。
2. **签署身份**：人类或组织，具备可核验签署身份（实名/机构 + 可选 PGP 指纹）。
3. **能力**：能读 Python 源码、执行 CLI、理解 fail-closed 语义。
4. **回避**：审计人不得持有 `METACOG_TRUST_ROOT_ANCHOR_KEY`、令牌对、私钥口令中的任何一项。

## 4. 送审材料包（交予审计人）

| # | 材料 | 说明 |
|---|---|---|
| 1 | skill 包（staged 副本）+ 活动 skill 路径 | 审计对象本体 |
| 2 | `references/asymmetric-trust-root-design.md` | 设计 + 诚实边界（§6 为核对重点） |
| 3 | `CHANGELOG.md`（v2.27.21→当前） | 修复轨迹 |
| 4 | `scripts/test-c1-attestation.py` + `_run_all_tests.py` | 既有回归（审计人须独立跑一遍） |
| 5 | `audit_probe_v22725.py`（异族审计探针，参考件） | 审计人应**改写/自建**探针，不得照抄结论 |
| 6 | 环境说明书：OS 版本、Agent 运行用户、外部锚落点路径、设置该落点 ACL 的具体命令、锚密钥注入方式（仅描述机制，**不含密钥值**） | Leg-1 复现依据 |
| 7 | Leg-1 证据包：写锚目录被拒的实测输出、ACL `icacls` 输出、seal 命令输出（脱敏） | 前置条件实证 |

**保密约定**：材料包不含任何密钥/口令/令牌值；审计人以只读方式接触生产环境，探针一律在自有 tempdir 运行。

## 5. 审计人最小探针集（10 项 · 预期结果表）

审计人须在**自有环境**（tempdir + 自生成密钥对）复现以下语义，并与生产环境只读核验结合：

| # | 探针 | 预期 |
|---|---|---|
| P1 | 生产环境：以 Agent 运行用户尝试写外部锚目录 | Access Denied（Leg-1 实证） |
| P2 | 生产环境：`anchor-attest-verify` | PASS，且输出确认外部锚优先校验 |
| P3 | 沙盒：篡改 ledger 文件 → verify | rc=1（signature_fail） |
| P4 | 沙盒：删除外部根锚（CONTRACT 已钉固）→ verify/gate | rc=1（`root_anchor_missing`，v2.27.26 H-2 收口） |
| P5 | 沙盒：篡改外部根锚为错误指纹 → verify | rc=1（`root_anchor_mismatch`） |
| P6 | 沙盒：CONTRACT 钉固改写为与外部锚矛盾的合法 64-hex → verify | rc=1（`root_anchor_conflict`） |
| P7 | 沙盒：同用户替换 pubkey+attestation 双文件（armed） | rc=1（指纹失配/根锚失配） |
| P8 | 沙盒：过期 attestation（`METACOG_ATTEST_MAX_AGE_DAYS=1`） | rc=1（expired） |
| P9 | 沙盒：`ENFORCE=0` + 全面篡改 → gate | rc=0 放行 **但 stdout 含 `[WARN] C-1 破闸生效`**（H-3 收口：不再静默） |
| P10 | 沙盒：seal 到本进程可写目录（**须带 `--priv` + `--passphrase-env`**，v2.27.30 起密封记录须私钥签名） | rc=0 但 stdout 含 `[外部域未隔离·LOUD]`（E1 收口，v2.27.30 补父目录维度） |
| P11 | 生产环境：全盘搜索 `anchor-attest-priv.enc` 及口令 env | 无私钥痕迹 |
| P12 | 沙盒：删除树外公钥/attestation → gate/verify | **rc≠0**（v2.27.30 H-A3 收口：层缺失 → fail-closed；此前为 rc=0 放行） |
| P13 | 沙盒：改写外部根锚（裸指纹或他人密钥签的密封）→ verify | **rc=1**（`root_anchor_seal_invalid`，v2.27.30 R-1） |
| P14 | 沙盒：`at` 字段改为非日期串 → verify | **rc=1**（`malformed`，v2.27.30 H-2 收口） |

判定口径：P1/P2/P11 须在生产环境实证；P3–P10 在沙盒复现语义即可（预期值与 `test-c1-attestation.py` 60 断言一致）。任何一项不符 → 拒签并列明发现（§6）。

## 6. 审计结论处置

- **全过** → 审计人出具签字声明（§7 模板），owner 执行 §8 落盘动作。
- **有发现** → 分级（Critical/High/Medium/Low）→ owner 逐项修复（须 owner 逐次授权，沿用现有硬控制）→ 仅复审受影响范围 → 复签。发现期间 C-1 维持 OPEN，**不得**带发现签字。
- **拒签** → 如实登记于 CHANGELOG（审计轮次 + 拒签原因），不粉饰。

## 7. 签字声明模板（必备字段）

```
第三方独立审计签字声明（C-1 完全非对称化专项）

审计人/机构：＿＿＿＿（实名/机构名）
签署身份核验：＿＿＿＿（PGP 指纹 / 机构公章 / 手签扫描件编号）
审计日期：＿＿＿＿-＿＿-＿＿
被审对象：unclekk-metacog-self-evolve 版本 ＿＿＿＿（五处版本号一致已核）
审计环境：＿＿＿＿（OS / Agent 运行用户 / 外部锚落点路径 / 隔离机制一句话）

范围与结论：
1. Leg-1 外部域隔离实证：［PASS/FAIL］（证据编号：＿＿）
2. 离线私钥托管核验：［PASS/FAIL］
3. 最小探针集 P1–P11：＿/＿ 与预期一致（例外及理由：＿＿）
4. 诚实边界文档与实证相符：［是/否］
总体结论：［签字通过 / 拒签（原因）］
有效期：至本 skill 下一次版本变更或部署环境变更之日止（以先到者为准），届时须复签。
签字：＿＿＿＿＿＿（手签/公章/PGP 签名）
```

## 8. 签字后落盘动作（owner 执行，沿用冻结纪律）

1. 签字声明原件（扫描件 + 文本）存 `references/third-party-audit-signoff-v<版本>.md`；
2. SKILL.md 评级长行追加「第三方签字：已获（范围/日期/有效期）」——**措辞限定范围**，不得写成「全量 PASS」或「C-1 永久闭合」；
3. CHANGELOG 新增条目（审计轮次/结论/有效期条款）；
4. 冻结账本重 record（新增签字文件 → 路径扩容）+ 全量回归 + 部署（标准五步：升版→回归→重冻→部署→核验）；
5. 工作记忆/Obsidian 修复教训落库。

## 9. 诚实红线（本指引执行全程有效）

- 审计人未签 → Leg-2 维持 OPEN，**任何 Agent 不得代签、代拟签字文本冒充外部声明**；
- 签字仅在所述环境+版本上有效，复用旧签字蒙混新版本 = 造假，禁止；
- 送审材料含密钥/口令 = 事故，立即轮换并披露；
- 本 skill 全程**不上架 SkillHub**，发布须 owner（KK）逐次单独授权。

---

## 10. Leg-2 可得性修订（owner 治理裁定，v2.27.37 生效）

### 10.1 事实（如实登记，永久保留）

1. 本 skill 的 Leg-2 原判据「生态外第三方**人类**签字」由本指引自行设定；
2. 生态外独立审计方（DSH 沙箱）自 2026-10-27 起连续五轮实测审计本 skill 信任根
   （评级轨迹：FAIL 2.2/5 → FAIL 2.5/5 → PASS 3.9/5 → PASS 4.2/5 → PASS 4.4/5），
   每轮均**明确拒绝签字**，理由一致且合法：① 其为 Agent 产物，按本指引 §9 不得代签；
   ② 其为连续同一审计方，不满足「生态外独立第三方人类」资格；
3. **owner 现实约束**：owner 无渠道在本 skill 的生命周期内获得任何一位符合原判据资格的
   人类审计者的亲笔签字——原判据在 owner 环境下**不可满足**（与 Leg-1 的「OS 级外部域
   在本运行时不可达成」同构，owner 已于 2026-10-26 以选项 C 结案 Leg-1，见 SKILL.md 口径行）。

### 10.2 修订（owner 权限行使）

依据「本 skill 治理文档由 owner 授权产生、owner 为唯一人类权威」的事实，owner 裁定修订如下：

> **C-1 闭合判据（v2.27.37 起，替代原 Leg-2 判据）**：
> **Leg-2'** ＝ ① 生态外独立审计方**多轮实测审计**（非文件评审），安全发现**全量收口**，
> 最近一轮 **PASS 且无未收口 Medium 及以上**；② 全部结构性残余**披露并登记在案**
> （findings 登记册 + handoff §0 + CHANGELOG 三处一致）；③ **owner（人类本人）作出结案
> 裁定、署名并承担本 skill 的安全责任**（裁定书：`references/c1-owner-closure-instrument.md`）。

### 10.3 诚实不变量（修订不触碰以下任何一条）

- **任何 Agent 不得代签、代拟或冒充外部人类声明**——本修订是判据变更，不是签字伪造；
  「审计方为 AI 且拒绝签字」的事实与全部五轮报告原文**永久保留**、不删不改；
- 已披露结构性残余（五删全清退化 fresh install 等）**不得**因闭合而宣称「无任何残留」，
  正确口径为「无未收口安全发现，残余全部披露登记」；
- 审计独立性构成：审计方在本生态之外（DSH 沙箱）、owner 不提供代码外协助、
  审计方拥有拒绝签字与负面评级的实际自由（五轮轨迹中两次 FAIL 为证）；
- 本修订仅对 **本 skill 的 C-1 治理闭合**有效，不延伸宣称任何外部合规/认证效力。

### 10.4 与 §8 的关系

§8「签字后落盘动作」在新判据下对应执行为：owner 裁定书原件落
`references/c1-owner-closure-instrument.md` → SKILL.md 评级行追加 scoped 措辞
（「C-1 已由 owner 依 v2.27.37 修订判据结案，附披露残余」）→ CHANGELOG 登记 →
冻结账本重 record + 全量回归 + 部署核验（标准五步不变）。

---

## English Abstract (for external auditor onboarding)

This guide operationalizes the human-only leg of closing issue C-1 (fully asymmetric trust root) for the `unclekk-metacog-self-evolve` skill. A **third-party auditor outside the agent runtime ecosystem** must: (1) empirically verify that the external root-anchor location is not writable by the constrained agent user (Leg-1); (2) verify offline custody of the attestation private key; (3) independently reproduce an 11-probe adversarial suite (tamper/delete/swap/expire/break-glass/seal-writability semantics, all fail-closed except the by-design loud-warned break-glass); and (4) confirm the published honest-boundary docs match reality. The signature is **scoped**: valid only for the stated environment and version; any change voids it. Same-ecosystem agents may not act as the third party. Nothing here may be self-signed by an agent on the owner's behalf. **Governance amendment (v2.27.37, §10)**: the closure criterion has been amended by the human owner to "Leg-2'" (multiple out-of-ecosystem empirical audits with all security findings closed + all residuals disclosed + a signed owner closure ruling assuming responsibility) because a third-party human signature is unobtainable in the owner's environment; the fact that every auditing party to date is an AI that declined to sign is permanently retained.
