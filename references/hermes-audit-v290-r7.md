# Hermes 异族独立审计 r7 — unclekk-metacog-self-evolve v2.9.0

- 裁定时间：2026-10-12（Asia/Shanghai）
- 审计对象：`C:\Users\Administrator\.workbuddy\skills\unclekk-metacog-self-evolve\` v2.9.0
- 审计方式：不采信 self-attested；仅采信源码直读 + 实跑对抗探针 + 哈希重算
- 探针位置：`D:\skill待检\_r7_audit\r7_probe{,2,3,4,5}.py`（C: 权威树不残留审计产物）
- **总体评级：⚠️ CONDITIONAL-PASS（不上调 PASS）**

---

## 0. 证据基线（可复核）

| 核验项 | 结果 |
|---|---|
| 6 文件 sha256 与冻结清单 | 全 MATCH（metacog.py=6771f496…, test-trust-root.py=d44f57cb…, HANDOFF.md=52605ebe…, SKILL.md=b05d7399…, test-v290-c10-h4-legacy.py=d9484b75…） |
| 双树（C: 权威 / D:\skill待检 镜像） | 6/6 字节一致 |
| `_run_all_tests.py` 独立复跑 | suites OK=25 FAIL=0，746 PASS-line，exit 0 |
| `_legacy_hash_allowed()` | 实测 False，`(2,9,0) < (2,9)` 判定正确 |

证据链在「文件确实冻结、测试确实绿」层面**自洽**。但测试全绿 ≠ 缺陷闭合：25 个套件中**没有任何一个用例覆盖「脚本/制品/信任根域被篡改 + 同步重记基线」这一 C-10 的核心威胁**（`grep` 实测：全部基线改写测试命中 `manifest:*` 域）。这是 746 PASS-line 的真实解释力边界。

---

## 1. 关键发现

### 【高 H-A】C-10「根闭合」是域部分闭合；`script:` / artifact / 信任根域 的签名「写而不验」，且 `script:` 域连写都没有

实跑覆盖矩阵（`r7_probe3/4`）：

| integrity.json 域 | 写 `_anchor_sig` | `verify` 路径验签 | 改文件+重记基线能否检出 |
|---|---|---|---|
| `manifest:SKILL.md` / `@body` / `CONTRACT.md` | ✅ | ✅ | **检出** |
| artifact（A1~A4/M1） | ✅ | ❌ | **放行** |
| `ledger/applies.jsonl` | ✅ | ❌ | **放行** |
| `ledger/human-guard.json` | ✅ | ❌ | **放行**（`cmd_verify` exit=0） |
| `script:*`（17 个运行时脚本） | ❌ **从未写入** | ❌ | **放行** |

实跑证据（`r7_probe4`，真实 CLI 路径）：

```
A1                         -> [('A1', True, ...)]           # 篡改未检出
ledger/applies.jsonl       -> [('ledger/applies.jsonl', True, ...)]
_verify_anchor_sig(guard) = False  # 签名确实已失效，但无人调用
cmd_verify exit = 0       # “全部制品与 ledger 快照一致（无直写篡改）”
```

**直接矛盾点**：CHANGELOG.md v2.9.0 与 HANDOFF.md §18 均写明「对 integrity.json **各基线条目（manifest:SKILL.md / @body / script: / 信任根域）** 做锚密钥 HMAC 签名」。实测 `script:*` 键记录为 `{hash, size, at}`，**无 `_anchor_sig`**；artifact/信任根域签名被写入但 `verify_integrity` 与 `cmd_verify` 全路径从未对其调用 `_verify_anchor_sig`。文档声称的覆盖面与实现覆盖面不一致。

**结论**：C-10 闭合域 = `manifest:` 3 个键（SKILL.md / @body / CONTRACT.md）。`script:` 域——即 C-10 自 v2.8.1 起声明的**主威胁面**（弱化 `check_pubkey_root` / 删除硬闸调用的攻击链）——**零签名、零闸门，与 v2.8.1 的原始 OPEN 状态等价**。C-10 应标注为「manifest 域已闭合；script/artifact/信任根域仍 OPEN」。

### 【高 H-B】旧链容忍分支彻底解除 HMAC 校验；「待 keygen/apply 重基线后旧链归档」无实现

实跑（`r7_probe.py` P3）：写入一条**无任何有效 HMAC、无任何 epoch** 的伪造旧链：

```
ok=True cnt=2    # HMAC 全错、结构合法 → 全链通过
```

容忍分支仅校验 `isinstance(dict)` + `hmac`/`prev_hmac` 为 str，**不校验 HMAC 值、不校验链连续、不校验 epoch 逐条**。结构性预检只挡住「结构畸形」，挡不住「结构合法的伪造」——攻击者只需写出 2 行形如 `{"prev_hmac":"","hmac":"0"*64}` 的 JSON 即可获得一条「合法」审计链。D-2「尾部有效子链截断」残余在旧链上并未被签名根治。

更严重：代码注释（L1275 / L1283 / L3346）三处声称「待 keygen/apply 重基线后旧链归档，启用锚签名新链方进入严格校验」。实跑全源码 grep：**不存在任何对 `migration-audit.jsonl` / `rollback-audit.jsonl` 的 unlink / rename / replace / move 动作**，两条链仅以 `append` 写入。因此旧链一旦首条缺 epoch，将**永久停留在容忍态**，永远无法进入严格校验——收口前提是空承诺。

### 【高 H-C】epoch 结构预检只校验链首条目，中段/尾部混入伪造条目 fail-open

实跑（`r7_probe.py` P4）：链 = `[v290-epoch + 有效HMAC]`, `[无 epoch + 有效HMAC]`, `[v290-epoch + 有效HMAC]` → 返回 `(True, 3)`。判定逻辑仅 `if not (_first.get("epoch") == LEDGER_KEY_EPOCH)`，**首条通过后全链直接进入 HMAC 比对，中段条目是否带 epoch 无人检查**。可借此向已启用新链的实例插入任意无 epoch 伪造记录而通过校验。姊妹函数 `_verify_audit_chain` 存在完全相同缺陷。

### 【中 H-D】锚密钥随代码分发，默认锚无生产护栏；威胁模型与 v2.8.1 C-9 已闭合标准不一致

- `_TRUST_ROOT_ANCHOR_KEY_DEFAULT` 与 `_LEDGER_ANCHOR_DEFAULT` 字节完全相同：`9f2c4a7e…2b5c8d`，均为源码字面量（`r7_probe4` 实测由字面量独立重算 == `_audit_hmac_key(None)`）。
- `trust_root.write_trust_root_config()` 对「用默认内嵌锚启用外部锚」**有硬拒绝**（须显式 `METACOG_TRUST_ROOT_ALLOW_DEFAULT=1`），并明确记录理由「该密钥任何可读代码者均可提取并伪造签名（C-9：源码明文 → 读即伪造）」。
- 但 `_audit_hmac_key()` 承载的**账本/审计签名路径无同等护栏**：生产部署下静默使用共享硬编码锚，无任何告警。同一威胁模型在两处被不对称对待。
- 附加：`_audit_hmac_key` 同时被用于 `integrity` 基线签名与两条审计链 HMAC，锚密钥可由 env `METACOG_TRUST_ROOT_ANCHOR_KEY` 覆盖 → 攻击者可自设已知值重签全部历史链。

v2.9.0 文案把 C-10 标注为「软件层闭合」，但**软件层的秘密材料仍可由读代码者获取**，这与同仓库 v2.8.1 已经闭合并明确排除的 C-9 属同一性质。如实标注应为：「在部署契约假设『攻击者无代码读权限』下成立；默认锚随代码分发，无 HSM/TPM，无生产强制专属锚。」

### 【中 H-E】H-1 强制迁移存在逃逸窗口

实跑（`r7_probe5`）：

```
存量 7 个 16-char 基线 → 调用一次 record_script_integrity() 后：
  残留 ['A1', 'ledger/human-guard.json']，legacy_remaining = 2
```

`record_script_integrity` 是 `apply` 主流程内的**强制调用点**，每次 apply 都会静默完成 manifest/script 域 16-char → 32-char 重基线并**清零计数器**（仅告警、不阻断）。故 H-1「强制迁移」对 manifest/script 域实际是 best-effort，仅 artifact/guard 两域会被遗留并被 `__meta__.legacy_remaining` 计入（STRICT 下确实阻断，此点与 Hermes N-2 结论一致、已验证）。

### 【中 H-F】测试套件未覆盖真实威胁路径，746 PASS-line 的解释力被高估

`test-v290-c10-h4-legacy.py` 的 C-10 集成测试测的是「manifest:SKILL.md 基线被伪造签名 → 检出」——即**已闭合域的正向测试**。全库 grep：所有「重记基线 hash」型测试均落在 `manifest:*` 域，**无一用例触及 `script:*` / artifact / guard 域**。7 个 v2.8.8 blocking/medium 缺陷（H-1~H-4 + M-1~M-3）被 v2.9.0 收口，但**没有一条针对未闭合域的对抗用例**。测试数增长（16 FAIL → 0 FAIL）与威胁面收敛是两个不同量。

### 【低 H-G】代码自证性矛盾

`_verify_migration_audit` docstring（L1264-1266）仍写「**C-10 残余：密钥可由 ledger 写权限推导**」，同时同一 docstring 写「v2.9.0 签名化迁移根治」。而 `_audit_hmac_key` 已从「明文常量 + human-guard 内容派生」改为代码内嵌锚派生——**密钥已由 ledger 写权限不可推导**。两处注释互相矛盾，读者无法判断该函数的真实安全边界。

### 【低 H-H】工作树残留（M-3 声称已清理但未清完）

- `scripts/nul`（14,122 字节，10-08）仍存在。已被 `.packignore` 排除（打包层有效），但 M-3 声称「删除 `scripts/nul`」与磁盘实况不符——应为「打包排除」。
- 新增发现：`scripts/` 下存在嵌套目录 `C:UsersAdministratorWorkBuddy2026-09-26-10-31-47m7-poc-root\`（含 artifacts/ledger，自嵌套一层），为 Windows 路径分隔符误用导致的 POC 残留（9-29），`.packignore` 未覆盖，`_run_all_tests.py` 亦不触及。
- `sync_v285_to_d.py` / `sync_v286_to_d.py` 仍在工作树（HANDOFF 已声明「保留，KK 工作流依赖」，与 `.packignore` 一致，属设计内）。

---

## 2. 四个待裁定问题的回答

**Q1 四类改动是否真正闭合 H-1/H-4/M-1/M-2/M-3（C-10 同源）？**
不是全部。H-4 ✅ 实测闭合（@body 豁免须签名有效）。H-1 ⚠️ 部分（强制力仅覆盖遗留 artifact/guard 域，manifest/script 域经 apply 静默迁移）。M-1 ✅ 计数口径确实拓宽且实测累加（`legacy_migrated=4`）。M-2/M-3 ⚠️ 只读无副作用成立；工作树清理声明与磁盘实况不符。**C-10 本体：仅 manifest 域闭合，script/artifact/信任根域仍 OPEN。**

**Q2 `_verify_migration_audit` 是否与 `_verify_audit_chain` 同源收紧，有无 fail-open？**
同源收紧仅针对「结构畸形」，且**两个函数共享两个新的 fail-open**：(a) 旧链分支完全解除 HMAC 与连续性校验；(b) epoch 仅校验链首条目，中段/尾部不校验。

**Q3 H-1 全局拒绝 16-char 后，是否存在存量安装被「静默放行」的逃逸窗口？**
存在，但形态与设想不同：**不是放行，而是静默迁移**。`apply` 强制调用 `record_script_integrity()`，一次性把 manifest/script 域 16-char 基线升级为 32-char 并清零计数器，仅告警不阻断。STRICT 模式下 artifact/guard 域残留确实阻断（已验证）。

**Q4 C-10 无 HSM/TPM 前提下应如何如实标注？**
应标注为：**「在『攻击者无代码读权限 + 已配置专属 `METACOG_TRUST_ROOT_ANCHOR_KEY`』部署契约下成立；默认锚随代码分发，可读代码者即可派生全部签名密钥（v2.8.1 C-9 已就此性质判定为需防护）；且签名闸门仅覆盖 `manifest:` 3 个键，`script:`/artifact/信任根域无闸门。」** 不能笼统写「软件层闭合」。

---

## 3. HANDOFF.md r7 行建议措辞

```
- 铁律5 Hermes 复派（r7，2026-10-12，异族独立审计，不采信 self-attested）→ ⚠️ **CONDITIONAL-PASS 维持，不予上调 PASS**。
  证据基线自洽：6 文件 sha256 全 MATCH、双树 6/6 字节一致、25/25 套件 OK、746 PASS-line、`_legacy_hash_allowed()=False` 实测成立。
  但实跑对抗探针（`D:\skill待检\_r7_audit\r7_probe{,2,3,4,5}.py`，14+10+多项断言）挖出 3 高 + 3 中 + 2 低，核心结论：
  - 【高】C-10 为**域部分闭合**：签名闸门实际仅覆盖 `manifest:` 3 键（SKILL.md / @body / CONTRACT.md）；
    `script:*` 域（C-10 主威胁面）基线**从未写入 `_anchor_sig`**，artifact/`applies.jsonl`/`human-guard.json` 域签名**写而不验**。
    实跑：改脚本+重记基线 → `verify_integrity` 放行、`cmd_verify` exit=0「无直写篡改」。
    CHANGELOG/HANDOFF 声称「各基线条目（… script: / 信任根域）均签名」与实现不符 → 文档-实现不一致。
  - 【高】旧链（首条缺 epoch）容忍分支**完全解除 HMAC 与链连续校验**，结构合法的伪造链即通过（实跑 `ok=True cnt=2`）；
    且「待 keygen/apply 重基线后旧链归档」**无实现**（全源码无 audit 链归档/删除/重命名动作）→ 旧链永久停留容忍态。
  - 【高】epoch 结构预检仅校验链首条目，中段/尾部混入无-epoch 伪造条目 fail-open（实跑 `(True,3)`）；姊妹函数 `_verify_audit_chain` 同缺陷。
  - 【中】默认锚 `9f2c4a7e…2b5c8d` 随代码分发且账本签名路径无 `METACOG_TRUST_ROOT_ALLOW_DEFAULT` 同等待产护栏（v2.8.1 C-9 同性质已闭合，此处未同步）；锚密钥单钥双用（基线签名 + 两条审计链）。
  - 【中】H-1 逃逸窗口：`apply` 强制调 `record_script_integrity()` 静默完成 manifest/script 域 16-char→32-char 迁移并清零 `legacy_remaining`（7→2 实测）。
  - 【中】测试缺口：全库「重记基线 hash」型测试 100% 落在 `manifest:*` 域，未覆盖 script/artifact/guard 域被篡改+重基线攻击 → 746 PASS-line 不支撑 C-10 闭合论断。
  处置建议：v2.10.0 收口（`script:`/artifact/guard 域补验签或如实降级标注 + audit 链归档实现或改注释 + epoch 逐条校验 + 账本锚生产护栏 + 4 条对抗回归用例），
  在此之前 r5/r6/r7 CONDITIONAL-PASS 维持，r7 不采信 self-attested 为独立审计结论。
```

---

## 4. 残余风险汇总（冻结前须明示）

1. `script:*` 17 个运行时脚本基线无签名闸门 → C-10 主威胁面仍 OPEN（自 v2.8.1 起未实质收敛）。
2. artifact / `applies.jsonl` / `human-guard.json` 基线签名写而不验 → 信任根域可被「改文件+重记基线」静默改写且 `cmd_verify` 报告一致。
3. 旧审计链（无 epoch）容忍分支不校验 HMAC → 审计可被整体伪造；归档承诺无实现。
4. epoch 仅校验链首 → 新链可被中段注入伪造条目。
5. 默认锚随代码分发且账本路径无生产护栏 → 威胁模型弱于 v2.8.1 C-9 已确立的标准。
6. 测试套件覆盖与文档声称覆盖面不一致 → 后续版本的「回归零回归」结论同样只覆盖已闭合域。

---

## 5. 交付物自校验（ad-hoc，非套件绿）

校验脚本：`C:\Users\ADMINI~1\AppData\Local\Temp\hermes-verify-r7-adhoc.py`（可重跑）。
结果：**PASS=40 FAIL=0 / total=40**（2026-10-12）。

| 组 | 项 | 含义 |
|---|---|---|
| V1 | 2 | 探针唯一仓库在 `D:\skill待检\_r7_audit\`，5 个语法全有效 |
| V2 | 11 | 5 探针实跑无异常；10 条关键裁定证据逐一 grep 到实测输出（`ok=True cnt=2` / `(True,3)` / `keys=['at','hash','size']` / `cmd_verify exit = 0` / `_verify_anchor_sig(guard rec) = False` / `MEASURED script-tamper-rebaseline detected = False` / `legacy_remaining = 2` 等） |
| V3 | 11 | 报告存在于双树、含裁定 + 8 个发现项 + 覆盖矩阵 + r7 建议措辞 + 残余风险 |
| V4 | 6 | HANDOFF §18 r7 行已落地，「待派发」占位消除，分级计数与探针路径与哈希偏离声明在案 |
| V5 | 3 | 源码哈希未动（审计未改代码）；HANDOFF 偏离冻结值 `52605ebe→f06c6b9c`（已在报告与 HANDOFF 中披露） |
| V6 | 3 | HANDOFF / 报告 / metacog.py 双树字节一致 |

**口径说明（重要）**：上述为交付物级 ad-hoc 自校验，证明「探针可重跑、结论可复现、文档落地、未改源码、双树一致」；**它不是被测系统的回归测试**。`scripts/_run_all_tests.py` 的 25/25、746 PASS-line 是项目自述基线，本轮审计未修改其覆盖的任何源码，故该基线仍然有效，但它**不能**支撑 C-10 闭合论断（见 H-F）。

