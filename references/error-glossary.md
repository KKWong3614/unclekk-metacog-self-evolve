# 安全闸 reason 白话词典（Error Glossary）

> **用途**：命令报错里出现看不懂的英文 reason 字符串或安全术语时，到这里查「发生了什么（白话）→ 危险吗 → 怎么办」。
> **定位**：与 `troubleshooting.md`（按命令/退出码组织的 18 类常见错误）**互补不重复**——本表只收**安全闸与信任机制**的内部 reason。
> **权威口径**：本表是白话转译，不替代报错原文；若与实际报错「↩ 怎么改」有出入，以报错原文和 `CONTRACT.md` 为准。（v2.25.15 新增，响应 TRACE「专业术语较多的报错需查文档」反馈）

---

## 一、信任根 / 外部锚类（trust_root 层）

| reason / 术语 | 发生了什么（白话） | 危险吗 | 怎么办 |
|---|---|---|---|
| `LedgerAnchorDefaultError` | 未配置账本签名锚密钥即运行（v2.27.17 起源码内嵌默认锚已删除，fail-closed 防自签） | 不危险，是安全设计不是 bug | 设 `METACOG_TRUST_ROOT_ANCHOR_KEY` 为专属随机密钥（base64 ≥32 字节，`python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"` 生成）；本地与生产同口径，原 `METACOG_TRUST_ROOT_ALLOW_DEFAULT=1` 兜底已废除、设置无效 |
| `external-anchor-path-writable` | 开了严格模式（`METACOG_REQUIRE_PROTECTED_ANCHOR=1`）后，检出**锚证明文件所在目录对当前进程可写**——Agent 理论上能改写自己的信任证明，拒绝启动（fail-closed） | ⚠️ 需要行动 | 按「一键系统级隔离」套件收窄目录 ACL（管理员跑 `C1_deploy_full.ps1 -Action setup`），或换到 Agent 进程身份不可写的路径；确认无误前不要关闭严格模式 |
| `external-anchor-corrupt` | 外部锚证明**验签失败或与快照不符**（被删/改/换，或启动时没注入与 setup 同一把锚密钥） | ⚠️ 优先排查（可能是篡改，也可能是配置遗漏） | 先确认是否漏设 `METACOG_TRUST_ROOT_ANCHOR_KEY`（与 `C1_enable_external_anchor.ps1` 生成的 `metacog-anchor-key.txt` 同一把）；排除配置问题后仍报错 → 按疑似篡改处置：`verify` + 人工核查 + `rollback` |
| `anchor_storage_outside_root` | 锚证明文件被放在了 Agent 可写域 root **之内**（结构性主闸，v2.7.1 起） | 配置错误 | 把 `attestation_path` / `oob_token_dir` 挪到 Agent 可写域之外的专用目录（如 `D:\protected\anchor`） |
| 无外部锚直接报 Deny（默认拒绝） | v2.8.2 起**根信任出厂即 fail-closed**：没启用外部锚就拒绝，须显式逃生变量才回落 legacy | 不危险，出厂即拒是设计 | 本地：设 `METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1`（逃生舱）；生产：走「一键系统级隔离」完整部署 |

## 二、完整性 / 篡改检出类（integrity / freeze 层）

| reason / 术语 | 发生了什么（白话） | 危险吗 | 怎么办 |
|---|---|---|---|
| `[完整性-硬闸] 技能源码哈希与基线不一致，拒绝 apply` | apply（最危险动作）前检出**引擎脚本本身被改过**（与受信基线漂移），拒绝执行（防基于被篡改代码落盘恶意变更） | ⚠️ 优先排查 | `verify` 看漂移清单；是自己升级/改过 → 按发布流程重基线；没改过 → 按疑似篡改处置，`rollback` + 人工核查 |
| `可信清单内容哈希与基线不一致` | SKILL.md / CONTRACT.md / HANDOFF.md 等**可信清单文件被手改**（H-3 攻击链防御），拒绝 apply/keygen | ⚠️ 优先排查 | 同上：确认改动来源；正常版本升级走发布流程重基线，不明改动先 `rollback` |
| `verify` 返回 1 | 完整性校验**检出篡改/漂移**（直写绕闸、账本异常等） | ⚠️ 是告警不是故障 | 看 verify 输出的具体条目；按「失控处置速查」处理；不知情的变化一律当篡改查 |
| `FROZEN-MODIFIED`（freeze verify） | 冻结清单里的文件**当前哈希 ≠ 首次冻结哈希**（文件在冻结后被改过） | ⚠️ 需要解释 | 开发者正常升级 → 走授权重置重基线（见下）；不明改动 → 按疑似篡改处置 |
| `RE-FROZEN`（纪律告警） | 同一文件在首次冻结后**又被改又重冻**过（append-only 账本留了痕迹） | 视情况 | 有对应版本升级记录 → 正常；没有 → 追查谁改的 |
| `FROZEN-RESET-BLOCKED` | 有人**删了冻结账本和树外锚**想清空重置，但安装标记还在 → fail-closed 拒绝（防「清掉账本重造白名单」） | ⚠️ 若不是你在做版本升级，属高危信号 | 升级场景：带 `METACOG_FREEZE_ALLOW_RESET=1` + 令牌 `METACOG-FREEZE-RESET-REQUIRED` 显式授权；非升级场景：立即人工核查，勿盲目重置 |
| `FROZEN-ANCHOR` / 树外锚不匹配 | 冻结账本与用户主目录下的**树外锚点**对不上（账本被截断/重排/整体替换） | ⚠️ 高危信号（账本疑被篡改） | 停止 apply 类操作，人工核对 `~/.metacog_freeze_anchors/<slug>.anchor` 与账本；无法解释则视为被攻陷，按事件响应处理 |

## 三、人类闸类（G3 / confirm / apply 签名）

| reason / 术语 | 发生了什么（白话） | 危险吗 | 怎么办 |
|---|---|---|---|
| `confirm 必须由人类在真实终端交互运行（当前非 TTY）` | confirm/签名类命令检测到**不在真实终端**（AI 或脚本在跑）→ 拒绝。TTY 隐藏输入是 AI 伪造不了的东西 | 不危险，这是人类闸的第一环 | 人类亲自开终端跑；无人值守场景走两步预签名：人类 `confirm --sign --id X` → `apply --id X --sig`（v2.25.14） |
| `no-pubkey` / 尚未初始化人类闸 | 还没生成人类密钥对，无法验签 | 配置缺失 | 人类在 TTY 跑 `confirm --keygen`（需 `--nonce-file` 离线授权凭据） |
| `legacy-unbound` | 签名是旧格式（只覆盖 id+内容，没绑定 t0）——M-7 前的旧签名，防过拟合保证不成立 | 配置/历史遗留 | 在 TTY 重新签名（apply 交互式或 `confirm --sign`），旧签名不可复用 |
| `content-hash-mismatch` | 签名对应的**提案内容已被改动**（签名管不住改内容的手） | ⚠️ 提案可能被篡改 | 丢弃该提案，重新 propose + gate + 人类重新签名 |
| `invalid-signature` | 签名验不过：伪造、篡改、编码错误，**或签名后又有新记账导致 t0 变化** | 视来源 | 排除 t0 漂移（签名后跑过 `episode`？→ 重新 `confirm --sign`）；无解释的验签失败按伪造处置 |
| `pubkey-root-mismatch` | CONTRACT.md 里**钉固的公钥指纹与当前公钥不符**——公钥疑似被替换 | 🚨 高危，按攻击处置 | 立即停用；人工带外核对公钥指纹；确认被替换则重建信任根并排查入侵路径 |
| `bad-pubkey` | human-guard.json 里的公钥**损坏/解析失败** | 可能是损坏也可能是篡改 | 人工核查文件后重新 `confirm --keygen` 重建 |
| `--human-ok 已废除` | 布尔旗标 AI 可自签，v2.4.0 起废除，命中即硬拦 | 不危险（闸在起作用） | 改走 TTY 签名或预签名工作流 |
| t0 漂移 | `confirm --sign` 之后又跑过 `episode` 记账 → trial_from_index 变了 → 预签名失效 | 不危险（fail-closed 设计） | 重新 `confirm --sign` 生成新签名再 apply；签名到 apply 之间不要记账 |
| `该人类绑定签名已被消费过（use-once）`（v2.25.16） | 这个签名**已经成功应用过一次**了——同一签名只授权一次 apply（防「提案 apply 后被 rollback/状态直改重回 gated，旧签名再刷一次」的重放） | 不危险（use-once enforce 在起作用，v2.25.16 起由引擎强制而非碰巧不成立） | 让人类重新 `confirm --sign --id X` 生成新签名后再 apply；签名文件用完即可删 |
| `签名消费账本完整性校验失败（sig-claims D4 硬闸）`（v2.25.17） | 签名消费账本 `ledger/sig-claims.jsonl`（use-once 的权威账本）或其完整性基线**疑似被改动**——删行/清空账本/删基线以绕过 use-once 的行为都会命中此闸（账本被清空但基线还在、或链中有历史记录而基线被抹，均判篡改） | 🚨 高危：正常流程**永远不会**命中（claim 落账与建基线在文件锁内原子完成），命中即按篡改处置 | 人工核查 `ledger/`（sig-claims.jsonl / integrity.json / integrity-chain/chain.jsonl）；确认篡改则排查入侵路径；合法场景（重装/迁移）走全新 init，勿手工重放签名 |
| `--out 目标已存在`（v2.25.16） | 签名输出文件路径已有同名文件，拒绝静默覆盖 | 不危险 | 换文件名，或加 `--force` 显式覆盖 |
| `--out 指向目录而非文件`（v2.25.16） | `--out` 给的是目录路径，签名无法落盘（--force 也无效） | 不危险 | 换成具体文件路径（如 sig.txt） |
| `签名文件写入失败`（v2.25.16） | `--out` 写盘失败（权限/路径不存在等）——**签名本身已生成**，仍在 stdout 输出可直接复制，退出码 2 让调用方能感知失败 | 不危险 | 从输出复制签名使用，或修正路径后重试 |
| `提案内容含 N 处不可见/转义字符`（v2.25.16） | 提案全文里有 ANSI 转义/零宽字符等**看不见的字节**，已用 `[ESC]`/`[ZWSP]` 等标记可见化展示——签名绑定的是原始字节口径全文 | ⚠️ 谨慎：不可见字符是常见的「显示良性+实际恶意」载体 | 把标记也视为内容的一部分再决定是否签名；解释不了的不可见字符按可疑处置 |
| `chain.jsonl 缺失或为空（D4 链校验 fail-closed）`（v2.25.20） | D4 完整性哈希链文件 `ledger/integrity-chain/chain.jsonl` 不存在或为空——**删链以关闭链校验的洗白路径已收口**：`verify`/`apply` 入口对链缺失默认 fail-closed（rc=1/rc=3），不再静默放行 | 🚨 高危：正常流程**永远不会**命中（链在 init/record 时自动建立），命中即按删链篡改处置 | v2.5.8 老基线安装可设 `METACOG_ALLOW_LEGACY_NO_CHAIN=1` **临时**放行（严格 `== "1"` 匹配；链存在时该变量无效）并**尽快重基线**重建链；否则人工核查 `ledger/` 并排查入侵路径，合法场景（重装/迁移）走全新 init |
| `applies.jsonl 与 D4 完整性快照/哈希链不符（apply 入口硬闸）`（v2.25.21） | `apply` 主路径入口直接核验 applies 域 D4 快照与链——账本被直写篡改或链被删时**入口即拒**（rc=3），早于 use-once 消费检查 | 🚨 高危：正常流程**永远不会**命中（record_apply 双写基线+链原子完成） | 见上一条「chain.jsonl 缺失或为空」的处置；账本篡改则人工核查 `ledger/applies.jsonl` 与 `integrity.json`，确认篡改即排查入侵路径 |
| `链条目 HMAC 校验不符 / mac 纪元后出现无 mac 条目`（v2.26.0 方案A） | D4 链条目自 v2.26.0 起带 HMAC（独立派生密钥）：条目字段被改（HMAC 不符）或手写/直写伪造条目（无 mac 或错 mac）→ fail-closed。mac 纪元后无 mac 条目=伪造冒充 legacy（record 必然写 mac） | 🚨 高危：正常流程**永远不会**命中（引擎追加的条目 mac 必然合法），命中即按链条目伪造处置 | 纯 legacy 链（v2.26.0 前安装全无 mac）放行属正常（建议重基线）；mac 纪元后出现无 mac/错 mac 条目 → 人工核查 `chain.jsonl` 排查入侵路径；升级过渡场景可临时设 `METACOG_ALLOW_LEGACY_NO_CHAIN=1` 放行并尽快重基线 |
| `链首指纹与 CONTRACT.md 钉固不符（chain-identity-root）`（v2.26.0 方案B） | `confirm --keygen` 时把链**首条目** hash 钉入 CONTRACT.md（人类持有不动点）；删链或删链+引擎重建的链首 hash 因时间戳等字段不可复现与钉固不符 → verify 计 dirty / apply 入口拒（rc=3）——H-2b「删链重建无痕洗白」的密码学检出 | 🚨 高危：正常流程**永远不会**命中（append-only 链头永不变化）；命中即按删链重建处置 | 确认属合法重基线/重装 → 重新 `confirm --keygen` 钉固即恢复；否则排查入侵路径；过渡场景可临时设 `METACOG_ALLOW_LEGACY_NO_CHAIN=1` 放行；未 keygen 的 legacy 安装无钉固（放行+warn，建议 keygen 启用检出） |
| `基线记录缺失（R-1/R-2 删键逃逸收口，v2.27.0）` | keygen 完成后，**GUARD 基线**无条件必存在；磁盘上存在的受跟踪文件（SKILL.md/CONTRACT.md/HANDOFF.md/CHANGELOG.md/pack.sh/manifest 与 script 与核心制品 A1-M1）其基线键也必须存在。删基线键（如删 `ledger/human-guard.json` 记录、删 `manifest:CONTRACT.md` 记录）即从检测集消失的盲区已被收口 → verify 计 dirty。⚠️ 该兜底仅在「keygen 完成态」生效（CONTRACT.md 含 chain-identity-root 或 GUARD 基线存在判定）；未 keygen 的老安装不误伤 | 🚨 高危：命中即「基线被删」——要么被篡改抹痕、要么误删，都应查 | 人工核查 `integrity.json` 与对应文件；确认是合法重基线（重跑 `confirm --keygen` 全量重拍）则恢复；无法解释即按篡改处置；legacy（v2.26.0 前）安装无 chain-identity-root 钉固、其 GUARD 基线若被删退化为未覆盖，须升级重 keygen |
| `人类公钥信任根指纹漂移（v2.27.0 R-3 无条件化）` | `verify` 的钉固公钥漂移检查（CONTRACT.md 钉固指纹 vs 当前 human-guard.json 公钥指纹）**自 v2.27.0 起无条件执行**（不再嵌套于「链指纹校验失败」块内，与 H-2b' 同构缺陷全域清扫）：即便链指纹校验通过（钉固节/链首未动），只要 live 公钥指纹与钉固不符即 fail-closed 报告——堵「删 GUARD 基线 + 写攻击者公钥 + `record_guard_integrity` 重记基线」的静默替换 | 🚨 高危：正常流程**永远不会**命中（钉固与 live 公钥一致）；命中即公钥疑似被替换 | 立即停用；人工带外核对公钥指纹（`pubkey-root-mismatch` 同口径）；确认被替换则重建信任根 + 排查入侵路径；此检查与方案B 独立，二者任一命中即告警 |
| `CONTRACT.md 缺 human_pubkey_fingerprint 钉固值行，但 human-identity-root 钉固节仍在`（v2.27.1，N-3 收口） | 钉固公钥指纹的**值行被删除**（节标题还在）——v2.27.0 的漂移检查因 `if pinned:` 短路而在此场景整体不可达（删一行即令 verify rc=0）。v2.27.1 改三分支显式判定：此情形判为**删行逃逸** → fail-closed 报告 | 🚨 高危：正常流程**永远不会**命中（keygen 必写真实指纹）；命中即钉固值被抹 | 人工带外核对公钥指纹；确认被删则重建信任根（`confirm --keygen` 重新钉固）+ 排查入侵路径；另注：init 未 keygen 的**占位符**态（CONTRACT.md 自带 `<待 confirm --keygen 钉固>` 占位值）不属本条，verify 放行不误报 |
| ⚠️ **未修的 OPEN 残余（v2.27.1，如实登记，勿当已收口）** | **N-1（P1 HIGH）** `ensure_pubkey_root_pinned()` 在完整性硬闸**之前**执行（`cmd_apply`/`cmd_resign` 首行）——一次**被拒**的恶意 apply 即完成信任根永久替换，而 verify 静默、`check_pubkey_root` 仍返回 True。**N-2（P1 HIGH）** `_manifest_integrity_drift_if_enforced` 删键盲区——删全部 manifest 基线键 + 篡改 CONTRACT.md → apply/keygen/retrieve 层硬闸放行（verify 报告层已由 R-2 收口） | 🚨 高危：两项均**未修**，待 owner 指令 | 现阶段按「信任根可能已被替换」处置：人工带外核对 `confirm --keygen` 打印指纹与自有记录；apply 前先跑 `verify` 并人工确认清单漂移；勿把 apply 的 rc=3 拒绝当作「无副作用」（N-1 下被拒也可能已换钉固） |

## 四、G1 写入闸类（gate）

| reason / 术语 | 发生了什么（白话） | 危险吗 | 怎么办 |
|---|---|---|---|
| `[BLOCK] 不动点保护` | 提案想改 **CONTRACT.md / metacog.py / SKILL.md** 这三个引擎不可动文件（自指不动点：引擎不许改自己） | 不危险（闸在起作用） | 别改引擎本体；改动需求走独立审计 + 人类发版流程 |
| `[BLOCK] 红线-xxx` | 提案内容命中**禁用词正则**（危险命令、关鉴权等字面红线） | 内容有问题 | 修改提案内容；若是误匹配（正常内容撞词）调整措辞重新 propose |
| `SEMANTIC_RISK` 升级为人类确认 | 内容不含字面禁用词，但**语义上像在绕过安全确认/削弱护栏**（#3 语义硬化层） | 谨慎对待 | 人类看一眼再决定：确属正常改动就在 TTY 签名放行；拿不准就拒绝 |
| `[BLOCK] A3 只增不减` | 想删改 A3 安全记忆条目（A3 是 append-only 的「踩坑账」，只许新增） | 不危险（设计如此） | 教训条目不删；要修正用追加新条目说明 |
| `[HOLD] 证据不足` | 改动还没有 ≥2 次独立复现的 episode 证据，进试用期等待 | 不危险 | 先正常干活记账，证据够了再 verdict |

---

*出处：`metacog.py`（cmd_apply 人类闸分支 L2506-2570 含 use-once（v2.25.16）`Store.human_sig_consumed` L578 / `_confirm_sign` 含 `--out` 三态与不可见字符可见化 / `LedgerAnchorDefaultError` L3426-3457 / `proposal_content_hash` L364-366）、`trust_root.py`（DenyTrustRoot reason）、`freeze.py`（verify violations，实测输出）、`CONTRACT.md` §3 红线闸能力边界、`C1_OS隔离_执行与回滚手册.md` §五-§六。*
