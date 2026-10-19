# 异族独立审计 · unclekk-metacog-self-evolve v2.8.11 第三轮「补丁级修 4 项」收口复核

审计角色：异族独立审计员（立场中立，敌意性批判）
审计日期：2026-10-11
被审对象：skill:unclekk-metacog-self-evolve，SKILL.md `version: 2.8.11`（第三轮补丁后未升版本号）
审计基准：`C:\Users\Administrator\.workbuddy\skills\unclekk-metacog-self-evolve\`（工作树实态，非 git 仓库，无 VCS diff 可比）

---

## 一、总体评级

### ⚠️ 有条件通过（CONDITIONAL-PASS）—— 维持，不予上调 PASS

**裁定理由一句话**：四项补丁**真实闭合了它们字面上声明的范围**，不存在伪造或"合规剧场"；但 r2 的升级门槛从未满足，第三轮**没有对任何外部攻击者产生净安全增益**，且审计中发现 2 项**未披露**的新缺陷（其中 1 项落在生产硬闸路径上）。

上调 PASS 所需的三件事，本轮一件都没做到：
1. D-4 根因（16-char 降级向量）未修，反而在当前版本号下**全体 10 处调用点均为活跃宽松态**（下文 F-1）；
2. D-1/D-2/D-3 的共同根因 C-10（无签名、HMAC 密钥可由同树文件推导）按自述"留 v2.9.0"，补丁级不可闭合；
3. 新引入的守卫不一致（下文 F-2）使 D-2 类修复只覆盖了两个同构审计链中的一个，且未披露。

---

## 二、独立验证证据（非转述，全部实跑）

运行环境：python 3.13.13，`PYTHONHOME="" PYTHONPATH=""`，工作树实态。

| 核验项 | 声称 | 实测 | 结论 |
|---|---|---|---|
| `test-trust-root.py` | 284/284 PASS | 284/284 PASS，EXIT 0 | ✅ 真 |
| `_external_anchor_proof_dir` `record` 形参 | 存在，默认 True | L713 确认 | ✅ 真 |
| 8 处 `_record_migration_audit` 全部包 `if record:` | 是 | L738/744/748/752/763/767/774/778 全部确认 | ✅ 真 |
| verify 只读路径 2 处传 `record=False` | L974/L982 | 确认，且**这是 `_external_anchor_proof_dir` 全部 6 个调用点中仅有的 2 处** | ✅ 真 |
| 写路径 3 处保持默认 | L818/L844/L899 | 确认 | ✅ 真 |
| 冻结哈希 metacog.py `71026ed4…5e1a` | — | 实算 `71026ed41fa335000aebeb01150d034185778c0ea10b3e9ec5e9563d7ccd5e1a` | ✅ 一致 |
| 冻结哈希 SKILL.md `cb0c7f23…` | — | 实算一致 | ✅ 一致 |
| 冻结哈希 HANDOFF.md `c048291f…` | — | 实算一致 | ✅ 一致 |
| 新增 4 个测试函数均注册 `main()` | 是 | L1447-1451 确认 | ✅ 真 |
| **断言计数** | **"D-1:7 / D-2:7 / D-3:7 共 21 条"** | **D-1=3（2+1）、D-2=7、D-3=7，共 17 条** | ❌ **数字不实**（HANDOFF §17 写的是 17，是正确的；审计请求材料自己写错了） |

审计员自写对抗探针共 **29 条**（附录 A 15 条 + 附录 B 8 条 + 附录 C 6 条），判定口径见附录 C 末。其中 5 条「PASS」的含义是**攻击成功、残余确实存在**（B2/B3/B4/C2/D2），1 条「FAIL」是**缺陷确认**（H 组 rollback-audit 缺守卫）。探针全部复现了材料自述的残余项，并挖出 2 项**未披露**的新缺陷。

---

## 三、关键发现清单

### 【高】F-1：D-1「verify 只读/幂等」的声明超出实际修复范围 —— verify 仍在改文件系统，且这些改动现在完全无留痕

材料称："`record=False` 使 verify **不产生任何 ledger 写入（幂等）**"。

实测（探针 A 组 + E 组）：

| 探针 | 结果 |
|---|---|
| A1 `_external_anchor_deleted` ×2 | ledger 零新增（c0=0, c1=0, c2=0）✅ |
| A4 verify 未新增任何 ledger 文件 | 目录列表前后完全一致 ✅ |
| E4 双目录均非空（`legacy_orphan_kept` 分支）verify ×3 | 零写入 ✅ |
| **E1** new 不存在 + legacy 存在 → verify(record=False) | **发生 legacy→new 目录 RENAME，且零审计留痕** ❌ |
| **E3** new 非空 + legacy 空孤儿 → verify(record=False) | **legacy 目录被 rmdir 删除，且零审计留痕** ❌ |

`record` 形参**只压制了 `_record_migration_audit` 的调用**，对方法体内的 `legacy_dir.rename(new_dir)`（L757）和 `legacy_dir.rmdir()`（L742/L772）毫无约束。

判读口径（诚实）：
- 若把 D-1 严格理解为 r2 记录的原文「verify 非幂等**写 ledger**」—— **该具体缺陷已闭合**，A/E4 组证实。
- 若按材料措辞「verify 只读路径」「verify 不产生任何写入（幂等）」理解 —— **不成立**。verify 仍是文件系统写操作（rename / rmdir），第二次调用看到的状态与第一次不同（E1c 确认）。
- 更严重的后果：`_record_migration_audit` 的设计初衷写在 L786「任何迁移阻塞/半程失败均留痕，供运营巡检发现（**不再静默失效**）」。补丁后，verify 路径上的 rename/delete 是**静默发生且零留痕**的——D-1 的修法把「静默失效」从异常态搬到了正常 verify 态，与该函数自己的设计目标直接冲突。

**这是"修症状而非修定义"的典型形态**：把断言改成"ledger 不变"，然后用测试证明"ledger 不变"，而 verify 的写副作用换了个名字继续存在。

### 【中】F-2：D-2 的 `isinstance` 守卫只同步到了 1/2 同构审计链 —— 生产硬闸路径可被单行畸形数据打穿（未披露）

D-2 修复在 `_verify_migration_audit`（L1243）加入了 `if not isinstance(_e, dict)`。同构的姊妹函数 `_verify_audit_chain`（L3246，校验 `rollback-audit.jsonl`）**没有这个守卫**。

实测（探针 H 组）：
```
baseline rollback-audit lines = 1
合法链 → ok=True cnt=1
FAIL rollback-audit 非 dict 行 → 抛 AttributeError（无 isinstance 守卫）
PASS migration-audit 非 dict+非法行 → ok=False cnt=2（有守卫）
```

关键放大因素：`_verify_audit_chain` **不是死代码**，它有 2 处生产调用——L3166（verify 巡检）与 L3265（**rollback 硬闸**，L3264 注释自称"此前零生产调用，本行使其从死代码变为真实门槛"）。因此在 rollback 入口，一行非 dict 数据即可让 `AttributeError` 未捕获地逸出硬闸，而非按设计 fail-closed。

同一类 bug（dict 守卫），D-2 只修了另一半。且 CHANGELOG/HANDOFF 通篇未提及。本缺陷**非本轮代码引入**（`_verify_audit_chain` 自 v2.8.9 ⑦ 起即无守卫），但属**本轮完全未披露**的清单外缺陷，且其修复成本仅一行——在已知 D-2 存在 dict 问题的前提下漏掉姊妹函数，属审计覆盖不完整。

**同源不一致的第二例（同批修复，同类不对称）**：`_hash_matches`（L505）默认 `allow_legacy=False`，而 `_script_hash_matches`（L535）默认 `allow_legacy=True`。同一文件内两个语义等价的哈希比对函数，默认值方向相反。L511 的注释声称「D-4：默认 allow_legacy=False（严格），强制新调用点显式声明宽松策略」，但只对 `_hash_matches` 生效——凡新增 `_script_hash_matches` 调用点若忘记显式传参，即自动落到宽松侧。当前 L1168 正是一处这样的裸用点（见 F-4）。

### 【中】F-3：D-2 残余的严重度被系统性低估 —— 降级密钥是源码内明文常量，不需要 ledger 写权限

材料披露的 D-2 残余措辞是："攻击者持 **ledger 写权限** + 同派生密钥重算合法 HMAC"。

实测（探针 I 组 + B4）：
- `_audit_hmac_key`（L3186）在 `human-guard.json` 不存在时降级返回 **`b"METACOG_FALLBACK_AUDIT_KEY_v289_C10"`** —— 该常量**明文硬编码在 L3194 的源码里**，任何读到技能包的人都能直接算出合法 HMAC。
- 实测探针 B4：持该密钥追加一条合法 HMAC 伪造条目 → `_verify_migration_audit` 返回 `ok=True, cnt=3`，**完全不可检出**。

即：残余的触发条件不是"持 ledger 写权限"（需要提权），而是"能读到技能包"（零提权）。披露把攻击前提说重了。**同一个降级常量还同时是 `rollback-audit.jsonl` 的密钥**（L3204 复用 `_audit_hmac_key`），影响面是两条链。

### 【中】F-4：D-4 残余是"当前版本号下全体 10 处调用点活跃宽松"，不是"1 处裸用默认"

材料的披露："`_script_hash_matches`(L535) 仍默认 `allow_legacy=True` 且 `verify_integrity` L1155 裸用默认未传参（16-char 前缀宽松面）"。

实测：
- **行号错了**：裸用默认的调用点是 **L1168**，不是 L1155。
- **严重度严重低估**：`LEGACY_HASH_CUTOFF_VERSION = (2, 9)`（L523），`CURRENT_VERSION_TUPLE = (2, 8, 11)`（L525），故 `Store._legacy_hash_allowed()` **当前返回 True**。因此全部 **10 处**显式传 `allow_legacy=Store._legacy_hash_allowed()` 的调用点（L668/699/1008/1017/1189/1198/1212/1270/1622/1627/3145）今天全部处于宽松态。
- 后果：L546-552 的降级向量——攻击者若能写 `integrity.json`，把 128-bit 基线哈希截断为前 16 字符即可通过校验——**在 v2.8.x 全体制品域上今天就开放**，不是"宽松面"而是"活跃降级面"，要等到版本越过 (2,9) 才关闭。

代码作者自己在 L547-548 的 docstring 里写得很诚实（"降级向量仍存在（攻击者能写 integrity.json 截断 128-bit 为 16-char 即可绕过主路径），故截止期强制迁移为必要缓解，**非根治**"）——但审计材料复述时把这个降级为"同源已知项、非本轮新增、留 v2.9.0"。**代码是诚实的，材料是过度简化的。**

### 【中】F-5：同一版本号内第 3 轮补丁，版本卫生已失效

- SKILL.md `version` 恒为 2.8.11，未变；metacog.py / CHANGELOG.md / HANDOFF.md 在同一版本号下已修改 3 轮。
- 任何以"2.8.11"为标识建立的外部完整性基线、分发包、审计结论现在**无法区分是哪一轮的 2.8.11**。dist 目录里仍是 `unclekk-metacog-self-evolve-2.8.5`（分发产物也早已落后 6 个小版本，从未重建）。
- r2 报告自己已经诊断了同一类问题："CONDITIONAL-PASS 已连持多轮、每轮新挖缺陷而评级不动，退化为默认稳态；同栈自评只能验证'已知清单是否闭合'不能验证'前提是否成立'"。第三轮的实证结果完全印证了这个诊断：补丁把 4 项已知清单项从 FAIL 改到 PASS，同时新增 2 项清单外缺陷，评级依旧不动。

### 【低】F-6：`scripts/nul` —— 14122 字节 Windows 保留设备名残留，落在 shipped 目录内

`scripts/nul`（14122 B，UTF-8，CRLF，内容是 `[trust_root] WARN:` 日志转储）是某次 `> nul` 重定向被字面量解释的产物。它**不在** `SCRIPT_NAMES`（17 项）、**不在** dist 分发产物中（`.packignore` 显式排除 `nul` 与 `scripts/nul`）。

`.packignore` 注释自述："Windows 保留设备名残留（**标准 API 不可删，须 KK 提权 shell 手动清**）"。即该文件在标准 Windows 用户态无法删除，只能靠提权 shell —— 这是一项**运维隐患**（同类残留可能在其它主机上以设备名形式遮蔽真实文件访问），虽对本技能安全模型无直接影响。属卫生问题，非安全问题。

### 【低】F-7：审计请求材料自身的数字不可信

材料称"D-1/D-2/D-3 相关断言共 **21** 条（D-1:7 / D-2:7 / D-3:7）"。实测 D-1 = 3 条（`test_v2811_proof_dir_record_flag` 2 条 + `test_v2811_external_anchor_verify_idempotent` 1 条）、D-2 = 7、D-3 = 7，**合计 17**。HANDOFF §17 自己写的 17 是对的。

一个未实算的数字出现在正式裁定材料里，恰好是本审计要求批判的"不可验证声明"模式——且是**高估方向**。这类偏差虽小，但说明该材料的数字类字段缺乏实测背书，需逐项复核才可采用。

---

## 四、逐维度审计

### 1. 逻辑漏洞

- **偷换判定口径（F-1）**：把"verify 不写 ledger"当作"verify 幂等/只读"的证据。前者是后者的子集，测试只覆盖了子集。测试全绿 ≠ 缺陷闭合。
- **未证前提**：D-1 的全部修复依赖"`new_dir` 与 `legacy_dir` 在语义上可互换"这一前提，但探针 A1c/E2 证实**代码从未证明等价性**——异常态下静默选边（实测 `selected=a566ba0f36ff96d0055b9aa4`），且 CHANGELOG L77 自述"实际判据是 `new` 是否为**空**（与'new 含基线'相反）"。也就是说 D-1 修的其实是"不要删掉可能非空的东西"，而不是"保证选到正确的那一个"。r2 已指出这一点，第三轮没有回应。
- **循环论证风险**：284/284 与"隔离 subagent 静态复核 PASS"均出自与代码同栈的生成方（r2 报告已自认"同栈自评只能验证已知清单是否闭合"）。本审计的 29 条对抗探针是本次唯一独立 oracle。
- **无自相矛盾**：CHANGELOG / HANDOFF / 代码 docstring 三处的技术描述互相一致，且与代码实测一致（除 F-4 的行号与 F-7 的计数）。这点是加分项。

### 2. 安全隐患

- **未修复的活跃降级向量（F-4）**：16-char 前缀校验在当前版本下于全体 10 处调用点活跃开放，写入 `integrity.json` 即可降级绕过。
- **明文常量密钥（F-3）**：`METACOG_FALLBACK_AUDIT_KEY_v289_C10` 使两条审计链（migration-audit / rollback-audit）在降级态下对任何能读源码者完全可伪造，且审计材料低估了这一点。
- **未捕获异常逸出生产硬闸（F-2）**：`rollback` 入口可被单行畸形 JSONL 打穿，fail-closed 退化为异常逃逸。
- **verify 静默改文件系统（F-1）**：安全护栏自身的"验证"操作会重命名/删除目录，且补丁后这些改动无任何留痕，与"不再静默失效"的设计目标相悖。
- **未发现的项**：本轮未引入命令执行、凭据外泄、注入、供应链新风险。测试与源码纯 stdlib，无网络调用、无 subprocess 拼接。

### 3. 偏见与 AI 味

- **过度承诺（F-1）**："verify 不产生任何 ledger 写入（幂等）"—— 实际只做到了不写 ledger 文件，filesystem 仍在变。措辞比代码强。
- **向下简化（F-3/F-4）**：把"源码内明文常量密钥，零提权可伪造"简化为"持 ledger 写权限可伪造"；把"当前版本全体 10 处活跃降级"简化为"1 处裸用默认的宽松面"。两处都是**朝乐观方向**简化，且都发生在代码已诚实披露的地方 —— 说明偏差不在代码层，而在**上报复述层**。这是最值得警惕的模式：底层工程师诚实，汇报链失真。
- **数字未实测（F-7）**："21 条"。
- **正面**：残余披露本身是真实存在的、具体的、带行号的（B2/B3/B4/C2 全部复现），没有把残余藏起来。这比大多数同类材料诚实。

### 4. 规范性

- 冻结清单机制（CHANGELOG 内嵌 sha256 + self-referential 规避注释）设计合理，3 项哈希**全部实测一致** ✅ —— 这是本材料中最扎实的一环。
- CHANGELOG 明确记录每次评级的"不予上调"理由，且引用了具体探针结果（"Hermes 实跑探针验伪 over-claim 而非撒谎"），审计留痕纪律好。
- 行号引用**实测有 1 处错误**（L1155 应为 L1168）。按既定规范，行号须 `grep -n` 复核，此处未做。
- `scripts/nul` 未被清理，`.packignore` 已声明它是标准 API 不可删的运维残留（F-6）。
- dist 未随任何版本重建（仍是 2.8.5），分发产物与源码脱节 6 个小版本，属流程债。

### 5. 可用性与完整性

- **可复现性良好**：284/284 本人独立复现成功；无第三方依赖，纯 stdlib；探针可脱离被测代码独立运行。
- **缺失项**：
  - 无 VCS。工作树不是 git 仓库（`git log` → not a repository），所谓"改动限于 4 类文件"只能靠变更者自述 + 冻结哈希间接核验，**无法独立 diff 验证**。这是审计链上最弱的环节。
  - `_verify_audit_chain` 缺 dict 守卫（F-2），D-2 修复不完整。
  - `scripts/nul` 残留（F-6）。
- **不可验证声明**：审计请求材料中的"21 条"（F-7）；"改动限于 4 类文件"（无 git，不可独立核验，只能采信）。

---

## 五、针对性改进建议（按落地成本排序）

**P1 —— 立刻做，成本极低**

1. **补 `_verify_audit_chain`（L3246）的 `isinstance(_e, dict)` 守卫**，与 `_verify_migration_audit`（L1243）对齐。一行改动。同时新增 1 条断言：rollback-audit 注入非 dict 行 → 不抛 AttributeError 且返回 `(False, n)`。当前该路径是 rollback 生产硬闸（L3265），可被单行数据打穿。
2. **统一 `_script_hash_matches`（L535）的默认为 `allow_legacy=False`**，与 `_hash_matches`（L505）一致；然后把 L1168 等调用点补上显式 `allow_legacy=Store._legacy_hash_allowed()`。这一条同时消除 F-4 的裸用点与 F-2 第二例的默认值不对称，且不需要把 10 处传参点全部改一遍。
3. **修正文档行号**：CHANGELOG L108 与 HANDOFF §17 中的 "L1155" → **L1168**。
4. **修正断言计数**：审计材料/汇报口径统一为 **17 条**（D-1=3 / D-2=7 / D-3=7），与 HANDOFF §17 一致。

**P2 —— 措辞回退到代码真实能力（防 over-claim 复发）**

5. 把 D-1 的全部表述从「verify 只读路径」「verify 不产生任何 ledger 写入（幂等）」收紧为：「verify 路径不再写 `migration-audit.jsonl`；**但 `_external_anchor_proof_dir` 内的 `rename`/`rmdir` 仍会执行，verify 非文件系统只读**」。同步修正 metacog.py L722-723 docstring 与测试 docstring。
6. 若要真正做到 verify 只读，需要把 `record` 形参语义升级为 `mutate: bool`（或 `read_only`），同时包住 L742/L757/L772 三处文件系统写操作，并在 verify 路径下对"检测到迁移需要但未执行"改为返回可判定的 dirty 状态而非静默跳过。**这是真修复，工作量约 15 行 + 4 条断言。**
7. 把 D-2 残余披露从"持 ledger 写权限 + 同派生密钥"改为"降级态密钥为源码内明文常量 `METACOG_FALLBACK_AUDIT_KEY_v289_C10`（L3194），**读到技能包即可伪造**；migration-audit 与 rollback-audit 两条链共用此密钥"。
8. 把 D-4 残余披露从"1 处裸用默认的宽松面"改为"截至 v2.8.11（`CURRENT_VERSION_TUPLE` < `LEGACY_HASH_CUTOFF_VERSION=(2,9)`），全体 10 处调用点 `allow_legacy` 均为 True，16-char 降级向量在全部制品域活跃开放，直至版本越过 (2,9) 才关闭"。

**P3 —— 停止在 2.8.11 上继续打补丁**

9. **建议 KK 采纳 r2 的建议 (2)**：直接授权 v2.9.0 签名化迁移。第三轮已实证 r2 的核心判断——D-1/D-2/D-3 共同根因是"同用户可写文件系统上的自指完整性"，补丁级只能逐个补洞，而本轮补洞的同时又漏了 2 个同类洞。继续在 2.8.11 上迭代第 4 轮的期望收益已趋近于零。
10. 若 KK 仍决定继续补丁：至少把版本号推进到 2.8.12，使"哪一轮的 2.8.11"可区分；同步重建 dist（当前 dist 仍为 2.8.5）。
11. 给工作树建立 git 仓库。无 VCS 时"改动限于 N 类文件"这类范围纪律**不可审计**，只能盲信。
12. 提权 shell 清除 `scripts/nul`（`del \\?\C:\...\scripts\nul`），并排查是哪条命令的 `> nul` 被字面量解释，避免同类残留在他处遮蔽真实文件。

---

## 六、裁定说明（回应请求问题）

> 「是否仍维持 CONDITIONAL-PASS，或上调 PASS？升级门槛是否已满足？」

**维持 CONDITIONAL-PASS，升级门槛未满足。**

已满足的部分（真实、可核验）：
- ✅ D-1「verify 不写 migration-audit.jsonl」—— 实测 A1/A2/A3/A4/E4 全过；
- ✅ D-2/D-3 断言存在且全绿（各 7 条），且断言内容与技术描述一致；
- ✅ 残余披露的**存在性**真实（B2/B3/B4/C2 全部复现），未藏匿；
- ✅ 冻结清单 3 项哈希全部实测一致；
- ✅ 284/284 独立复现成功；措辞对齐已落地（`_verify_migration_audit` docstring L1228 已改为"除尾部有效子链截断仍 ok=True 外"）。

未满足的部分：
- ❌ r2 门槛中的 **D-4 未在代码层关闭**，且实际严重度高于披露（F-4）；
- ❌ r2 门槛中的根因 C-10（无签名）按自述留 v2.9.0，补丁级不可闭合；
- ❌ **本轮新增 2 项未披露缺陷**：F-2（守卫不对称，位于生产硬闸路径，可抛异常）与 F-3（明文常量密钥，零提权可伪造）；另 `_hash_matches`/`_script_hash_matches` 默认值方向相反（F-2 第二例）；
- ❌ D-1 的实际修复范围小于其措辞声明（F-1），措辞对齐只覆盖了 `_verify_migration_audit` docstring，未覆盖 D-1 自身声明。

**结构性判断**：r2 报告自陈"CONDITIONAL-PASS 已连持多轮、退化为默认稳态"。第三轮数据印证了这一点——补丁把 4 项已知清单从 FAIL 改到 PASS，同时引入 2 项清单外缺陷，评级不变。**在同一版本号上再打第 4 轮补丁的期望收益已经低于风险**（版本卫生失效 + 每轮都漏同类洞）。升级门槛在补丁范式下**不可达**，不是"再修一轮就够"的问题。

---

## 附录 A：审计员对抗探针（D-1 幂等 + D-2/D-3 残余 + 硬闸），15 条

```python
# A 组：D-1 幂等 —— verify 全路径是否真的零 ledger 写入
A1  _external_anchor_deleted x2 → 零新增 ledger        PASS (c0=0 c1=0 c2=0)
A1b 两次返回值一致（判定幂等）                          PASS (r1=False r2=False)
A1c 异常态静默选边（未证等价即返回其一）                PASS (selected=a566ba0f36ff96d0055b9aa4)
A2  无基线异常态 verify x3 → 零新增                    PASS (c0=0 c3=0)
A3  写路径 record=True 异常态 → 追加 1 条              PASS (cnt=1)
A4  verify 未新增 ledger 文件                           PASS (目录列表前后一致)

# B 组：D-2 _verify_migration_audit —— 尾部截断 / authed-forgery
B1  合法 3 条链 → ok=True count=3                       PASS
B2  尾部截断 1 条 → 仍 ok=True                          PASS  [残余复现：不可检出]
B3  尾部截断 2 条 → 仍 ok=True                          PASS  [截断任意条数不可检出]
B4  authed-forgery（持密钥追加合法 HMAC）→ ok=True      PASS  [残余复现：不可检出]

# C 组：D-3 _integrity_chain_ok —— 中间条目一致化改写
C1  合法 3 条链 → True                                  PASS
C2  中间条目 key/size/at 被改写 → 仍 True               PASS  [残余复现：中间非 prev/hash 字段不可检出]
C3  中间 hash 被改（链断）→ False                       PASS

# D 组：D-2 声明与代码语义一致性 / 硬闸
D1  合法截断下 verify_integrity 无 audit:migration 告警 PASS
D2  断链 → 仅 audit:migration(dirty)，无硬闸阻断        PASS
```

## 附录 B：审计员对抗探针（verify 路径 filesystem 副作用），8 条

```python
# E 组：verify 路径 record=False 下的文件系统副作用
E1   verify(record=False) 发生 legacy→new RENAME        PASS (before=(T,F) after=(F,T))
E1b  该 rename 无任何审计留痕（record=False 压制）       PASS (audit_exists=False)
E1c  同一 verify 路径第二次调用看到的状态已不同（非幂等） PASS
E2   new 为空+legacy 含真实基线 → verify 静默选 legacy 且零留痕  PASS
E3   verify(record=False) 静默删除空 legacy 孤儿目录且零留痕    PASS
E4   双目录均非空 verify x3 → 零写入（补丁已闭合的分支）        PASS

# F 组：生产 verify 全链路
F1   生产 check_pubkey_root 不写 ledger                 PASS (lines=0)
F2   生产 check_pubkey_root 不改动 store 目录结构        PASS
```

（冻结哈希 / 守卫一致性 / 密钥降级三项另见附录 C。）

## 附录 C：冻结清单 / 守卫一致性 / 密钥降级核验，6 条

```python
G1   metacog.py  实际 sha256 = 71026ed41fa335000aebeb01150d034185778c0ea10b3e9ec5e9563d7ccd5e1a   与声称 71026ed4…5e1a 一致  PASS
G2   SKILL.md    实际 sha256 = cb0c7f23ffe11e3c41d9b17d965c3fb68958cfe124b218201e07a347fa5fa8d8   与冻结清单一致      PASS
G3   HANDOFF.md  实际 sha256 = c048291fd829961c965fb8ec361297dfd7c69ae2448b3e1b4f9e227df8cb55d0   与冻结清单一致      PASS
H    rollback-audit 注入非 dict 行 → 抛 AttributeError（_verify_audit_chain 无 isinstance 守卫）  FAIL  [缺陷确认]
H'   migration-audit 同一输入 → ok=False 不抛异常（有守卫）                                       PASS  [守卫仅半边]
I    无 human-guard 时降级密钥为源码内明文常量 b"METACOG_FALLBACK_AUDIT_KEY_v289_C10"（L3194）    确认  [零提权可伪造]
```

合计：**29 条**对抗探针。判定口径：B2/B3/B4/C2/D2 五条的「PASS」= 攻击成功、残余确实存在（非缺陷修复）；H 的「FAIL」= 缺陷确认。无一条探针证明任何攻击不可行。

---

审计员备注：本次审计仅基于工作树实态 + 独立探针，未采信任何自述结论。工作树非 git 仓库，"改动限于 4 类文件"的范围纪律无法独立验证，属本次审计的已知盲点。探针文件为临时产物，审计完成后已从 `scripts/` 清除，不污染 shipped 目录。
