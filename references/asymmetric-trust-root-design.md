# C-1 完全非对称化设计 · 锚状态 attestation（v2.27.21 阶段1 落地）

> 状态：**阶段1 已落地（双轨过渡）**；阶段2/3 未实施，见 §5。归 C-1 专项（KK 逐次授权）。
> 关联：C-01 收口（v2.27.17）、N-3（v2.27.19）、N-4（v2.27.20）；`remediation-roadmap-v2.27.15.md` §2.1 非对称化设计承接。

## 1. 问题定义（C-1 残余）

v2.27.17 C-01 收口后，信任根锚密钥唯一来源 = env `METACOG_TRUST_ROOT_ANCHOR_KEY`（对称，≥32B）。
**诚实边界**：env 对本进程自身可读属部署契约残余——被约束进程（Agent）能读到锚密钥，
理论上可对任意 ledger 状态重签 HMAC，即「装上了但可自签」。对称密钥无法在
「进程可用」与「进程不可伪造」之间两全——这是 C-1 的本质。

## 2. 解法：分层信任 + 离线 attestation（模式 A）

**核心取舍**：私钥离线 ⇒ 进程内不可能实时逐条签名（否则每次写入都要人类介入，
工作流不可行）。故采用 **attestation 认证模式**：

| 层 | 密钥 | 持有方 | 职责 | 强度 |
|---|---|---|---|---|
| L1 检出层（运行期） | env 对称锚（HMAC 链） | 进程可读 | 意外损坏检出 + tree-only 篡改检出 | 部署契约残余（可自签） |
| L2 认证层（离线） | RSA-2048 离线私钥 | **仅人类离线环境** | 对 ledger 状态 commitment 签 attestation | 进程无私钥 ⇒ 不可伪造 |

L2 语义：人类在离线环境对「当前 ledger 状态 commitment」签名 attestation；
进程内仅持**公钥**（钉固树外只读，与 freeze 树外锚同目录约定）。
验证：重算当前 commitment → 公钥验签。**事后篡改 ledger ⇒ commitment 变 ⇒ 失配 fail-closed，
且进程无法伪造新 attestation（无私钥）**。这把「写后篡改」的信任根从对称 env 挪到离线私钥，
即 C-1 目标「包内仅公钥、私钥离线」。

## 3. commitment 定义（v2.27.21 阶段1）

`_attest_commits(st)` 对四个状态文件逐个 sha256（字节级，缺失文件 → `"missing"`，
事后删除/补建均改变 commit ⇒ 与既有 attestation 失配，同样检出）：

- `ledger/integrity.json`（script/manifest 完整性基线）
- `ledger/applies.jsonl`（受信任锚落账）
- `ledger/sig-claims.jsonl`（人类签名消费账本）
- `frozen-hashes.jsonl`（H-05 冻结完整性账本；v2.27.23 ③ 追加，防御纵深覆盖冻结基线本身）

字节级口径（非结构级）是刻意选择：任何一行增删改都改变 commit，无需理解文件 schema；
粒度粗但目标本就是「状态被改即失配」。

## 4. 命令与密钥生命周期（v2.27.21）

```
① anchor-attest-keygen --out <dir> --passphrase-env NAME
   生成 RSA-2048 密钥对；私钥口令加密（AES-CTR+HMAC，sigcrypto encrypt_priv）落盘
   并提示移离线介质；公钥明文导出。
② （部署方）将私钥移至离线介质；公钥带到目标主机。
③ anchor-attest-pubkey-install --pub <pub-file>
   特权令牌门（METACOG_ATTEST_PUBKEY_TOKEN / ..._EXPECTED 双 env 恒定时间比对，
   M-03 同款）→ 公钥钉固树外只读（<slug>.attest-pub.txt）。
④ anchor-attest --priv <priv-file> --passphrase-env NAME [--out PATH]
   在信任环境对当前 ledger 状态签发 attestation（"v1:{at}:{b64sig}"，at 为紧凑无冒号
   UTC 时间戳——段内无冒号定界约束，见 sigcrypto.anchor_attestation_message docstring）
   → 默认写树外只读（<slug>.attest.json）。
⑤ anchor-attest-verify
   重算 commitment → 树外公钥验签。双轨（阶段1）：公钥或 attestation 缺失 → WARN
   「非对称层未配置」rc=0（现网行为不变）；失配/验签失败/畸形 → rc=1 fail-closed。
```

格式与安全细节：
- 消息复用 v2 长度前缀格式（N-4 口径：UTF-8 字节数），purpose 前缀 `METACOG-ANCHOR-ATTEST-v1` 防跨协议复用。
- 字段名白名单（integrity/applies/sig_claims），防任意字段注入。
- attestation 为低频人工操作、无 use-once 消费语义 → 确定性签名（PKCS#1 v1.5，L-06/N-16 既有披露）不引入 nonce。

## 5. 阶段路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| 阶段1（v2.27.21）+ ①（v2.27.22）+ ③（v2.27.23） | 原语 + 4 命令 + 双轨 verify + 19→24→27 断言回归 + **公钥 sha256 钉入 CONTRACT.md 结构性闸门** + **frozen-hashes.jsonl 纳入 commitment**（防御纵深覆盖冻结基线） | **已落地（C-1 仍 OPEN）** |
| 阶段2（v2.27.24） | 硬闸整合：`METACOG_ATTEST_ENFORCE=1` 时受管控命令派发前经 `_attest_gate` 硬闸——层缺失→rc=2 拒 / 失配·过期·指纹失配·畸形→rc=1 拒；attestation 过期策略（`METACOG_ATTEST_MAX_AGE_DAYS` 默认 90） | **已落地（C-1 仍 OPEN）** |
| 阶段3（v2.27.24） | 默认强制（armed→mandatory：`METACOG_ATTEST_ENFORCE` 未设且 CONTRACT.md 已钉固指纹+层完整布建→强制）+ 定期重签纪律（过期即硬闸 rc≠0）+ 运行期 HMAC 显式降格为「检出层」文档口径 | **已落地（C-1 仍 OPEN）** |
| 阶段4（v2.27.25） | **外部域存储闸门（代码可落地部分）**：权威公钥指纹除钉入 CONTRACT.md 外，另存一份至 Agent 可写域之外（`ATTEST_ANCHOR_DIR`，默认 home 同级树外；经 `METACOG_ATTEST_ROOT_ANCHOR` 重定向到 Agent 进程不可写位置方为真正外部域闸门，类比 v2.7.1 `anchor_storage_outside_root`）；verify 双权威交叉核对（外部根锚存在→优先校验公钥指纹与其一致，且须与 CONTRACT.md 钉固一致；缺失→回退 CONTRACT.md 钉固双轨）；新增 `root_anchor_mismatch`/`root_anchor_conflict` 两态硬拒（rc=1）；特权命令 `anchor-attest-root-seal`（令牌门）密封权威指纹到外部根锚（落只读）+ test-c1 新增 4 函数 15 断言（38→53）；五处版本号 2.27.25 | **已落地（C-1 仍 OPEN）** |
| 阶段4 收口（v2.27.26） | **异族审计（评级 C）三项操作性缺口收口**：H-2 删外部锚静默降级→钉固存在即要求外部锚必在（`root_anchor_missing` 硬拒 rc=1，删锚不再绕过双权威）；H-3 破闸静默 fail-open→`METACOG_ATTEST_ENFORCE=0` 派发前发 LOUD 告警（破闸语义不变）；E1 seal 落点对本进程可写→发 `[外部域未隔离·LOUD]` 告警。test-c1 53→60 断言。**审计 H-1 如实登记：默认落点下双权威对同用户攻击者仍为同权虚设** | **已落地（C-1 仍 OPEN）** |
| Leg-1 部署尝试（v2.27.28）→ 结案（2026-10-26） | **真正外部域部署尝试 → 本运行时环境阻碍实证 → 诚实回退 → KK 裁定接受 C 结案**：三处树外落点（`C:\ProgramData\MetacogExtAnchor` / `D:\MetacogExtAnchor` / `D:\MetacogExtRoot`）多轮攻防均失败——① 沙箱过滤器对 skill 写出的树外文件施加不可逆锁（DACL 剥空 0 ACE，读/写/删/授权全拒，仅元数据放行）；② `icacls /inheritance:r` 本机非标准连带剥空子文件 DACL（最小复现 4 ACEs→0，/reset 无法修复）；③ 运行时为 UAC 受限令牌（无 SeTakeOwnership/SeRestore）。**结论：本运行时内 OS 级「Agent 不可写且可读」外部域不可达成（锁与读互斥）**；KK 于 2026-10-26 重启宿主验证无效后裁定**接受选项 C**：以防御纵深级（home 树外默认 seal，H-1 口径如实适用）为 Leg-1 终态，不再追求 OS 级外部域。完整布建仪式已落地（keygen→install 钉固 CONTRACT.md→root-seal 落 home→重冻 33→attest 签发→verify PASS）→ 密钥销毁（口令未持久化+私钥 blob 销毁=等价销毁）；三处 junk 目录不可删已挂账 | **CLOSED（防御纵深级终端态，KK 裁定接受 C）** |

## 6. 兼容矩阵与诚实边界

- 双轨过渡：未配置非对称层 → 现网行为完全不变（WARN 留痕），既有 53 套件零破坏。
- **阶段1/2/3 诚实口径（v2.27.24）**：阶段2（ENFORCE 硬闸）+ 阶段3（armed→mandatory 默认强制 + 过期策略 + HMAC 显式降格「检出层」）代码已落地；但强制生效前提是「armed 已布建 + 部署方实际启用（`METACOG_ATTEST_ENFORCE=1` 或 armed 默认）+ 离线私钥确离线持有」。**阶段2/3 不声称 C-1 完全闭合**：env 锚密钥对本进程可读（部署契约残余，C-1 本质）未根除，同用户持 env 密钥仍可重基线 CONTRACT.md 钉固值（与 ① 同门槛）；C-1 结构性闭合判定 = 外部域存储闸门（信任根/锚存至 Agent 可写域之外，类比 v2.7.1 `anchor_storage_outside_root`）+ 独立审计复核。
- **阶段1 防护边界（如实，v2.27.21 审计实证 + v2.27.22 ① 收敛）**：attestation 公钥/认证文件落于
  `~/.metacog_freeze_anchors/`（home 目录，同用户进程可写，只读属性可被属主 `chmod u+w`
  还原）。v2.27.21 阶段1 的 verify 对传入公钥**无钉固指纹二次校验**——同用户全写权攻击者
  （能改 ledger + 公钥 + attestation 三文件）可自签新 attestation 并通过 verify，故阶段1 **仅防
  tree-only 攻击者**。**v2.27.22 ① 已收口该审计主发现**：`anchor-attest-pubkey-install` 经特权令牌门
  把公钥 SHA-256 钉入 CONTRACT.md（受 H-05 硬闸 + L1 冻结保护，CONTRACT.md 属不可动文件），
  `anchor-attest-verify` 加载树外公钥后须与本指纹一致，否则 fail-closed。**armed 后**，同用户替换
  pubkey+attestation 双文件 → 公钥指纹不匹配钉固值 → 验签必拒（test-c1 第21/22条已证）。
- **① 仍属部分加固，C-1 仍 OPEN（诚实口径，v2.27.22）**：① 把公钥信任锚从「树外裸文件」提升到
  「L1 冻结保护的 CONTRACT.md 不动点」，使 pubkey 替换攻击的门槛从"改两个树外文件"升到"改 L1 受保护
  的 CONTRACT.md（须 env 锚密钥重基线或触发 H-05 fail-closed"）——是实质增量，但**未根除** C-1 根残余：
  ① 的钉固权威仍依赖 H-05 + L1，而 L1 的 env 锚密钥对本进程可读（部署契约残余），同用户持 env 密钥仍可
  重基线 CONTRACT.md 钉固值（与任意 L1 受保护篡改同门槛）。此外 ① **双轨未强制**：CONTRACT.md 无钉固
  （legacy/未钉固）时 verify 仍 WARN（闸门未武装），同用户替换双文件仍可能绕过（test-c1 第23/24条已证残余）。
  故 ① = "结构性闸门 armed 后闭环审计主发现，但 C-1 仍 OPEN"——真正闭合须阶段2/3 强制 + 部署启用 +
  第三方审计签字。类比 v2.7.1 `anchor_storage_outside_root`，① 是较弱的"钉入可写树内 CONTRACT.md"变体
  （非"存储位于 Agent 可写域之外"），严谨性相对 v2.7.1 仍有差距。
- **③ 防御纵深（v2.27.23）**：`frozen-hashes.jsonl` 纳入 commitment 后，attestation 也覆盖「冻结基线」本身，
  攻击者替换/删除冻结账本（即便 H-05 未强制）亦被验签失配捕获。但 H-05 自 v2.27.17 已默认强制
  （frozen-hashes 本就被锚密钥 HMAC 链保护），③ 对该文件的边际保护价值有限，仅属 defense-in-depth，
  **不改变 C-1 OPEN 口径**。
- **阶段4 外部域闸门诚实口径（v2.27.25，v2.27.26 异族审计后补全）**：代码可落地部分已落地——权威指纹双权威交叉核对（`root_anchor_mismatch`/`root_anchor_conflict` 双态硬拒 rc=1）+ `anchor-attest-root-seal` 密封命令（令牌门）。**异族独立审计（针对 v2.27.25 实现，评级 C，20 探针 19 复现）实证四项发现，v2.27.26 如实登记并收口**：
  - **H-1（默认配置双权威虚设，v2.27.26 未改、如实维持）**：默认落点 `ATTEST_ANCHOR_DIR` = home 同级树外目录，外部根锚与树外公钥/attestation **同目录同权限（0444）**，同用户 `chmod u+w` 可改写外部根锚（审计实测成功）——即默认配置下「双权威交叉核对」对同用户攻击者是**同权虚设**，v2.27.25 相对阶段1/① 的增量防御 = 0。须经 `METACOG_ATTEST_ROOT_ANCHOR` 重定向到**不同用户/管理员/HSM/只读介质**等 Agent 进程不可写位置，方为真正外部域存储闸门（类比 v2.7.1 `anchor_storage_outside_root`）。
  - **H-2（删锚静默降级，v2.27.26 已收口）**：v2.27.25 中删除外部根锚 → 静默退回 CONTRACT 单权威 → 同用户写入攻击者公钥 + 重签 + 覆写钉固值 → verify ok（无需令牌、不刷冻结账本）。v2.27.26 改为：CONTRACT 钉固存在即要求外部根锚必在且匹配，缺失 → `root_anchor_missing` 硬拒（rc=1），删锚绕过被封闭。
  - **H-3（破闸静默 fail-open，v2.27.26 已收口）**：v2.27.25 中 `METACOG_ATTEST_ENFORCE=0`（同用户可自设 env）→ 三重篡改仍 rc=0 且零告警零留痕。v2.27.26 改为：显式破闸派发前发 LOUD 告警（破闸放行语义不变——这是部署方紧急逃生权，但不再静默）。
  - **E1（seal 落点无隔离校验，v2.27.26 已收口）**：v2.27.25 中 seal 落点对 Agent 完全可写时仍 rc=0 无告警。v2.27.26 改为：密封后实证校验落点目录对本进程可写性，可写 → `[外部域未隔离·LOUD]` 告警。
  - **C-1 结构性闭合判定（v2.27.28 更新，2026-10-26 结案）**：Leg-1（真正外部域部署）**已结案为防御纵深级终端态**——本运行时环境阻碍三重实证（沙箱过滤器不可逆锁树外文件 DACL / `icacls /inheritance:r` 非标准剥空子文件 DACL / UAC 受限令牌），OS 级「Agent 不可写且可读」外部域在本运行时**不可达成（锁与读互斥）**；KK 于 2026-10-26 重启宿主验证无效后裁定**接受选项 C**，以防御纵深级（home 树外默认 seal，可读可验、树外存储，但 H-1 口径「同用户可改写」如实适用，未消除）为 Leg-1 终态，详见 CHANGELOG v2.27.28；三处 junk 目录如实挂账。Leg-2（生态外第三方签字）规范已备（v2.27.27）待实际执行。**C-1 整体维持 OPEN**，待 Leg-2 签字后方可在所述环境+版本上判定闭合。降级披露：布建密钥在本机生成（非干净离线机 keygen，「私钥从未抵达被约束主机」未达成，口令未持久化 + 私钥 blob 签发后销毁=等价销毁）；Leg-2 审计须裁定是否接受或要求干净机重新布签。
- 私钥口令经 env 传递（不进命令行，C1_deploy 教训）；私钥文件须离线保管，留在被约束主机
  即退化为「口令保护」级（如实警示于 keygen 输出）。
- **v2.27.30 收口（授权维度·已被审计证伪）**：外部根锚改为**离线私钥签名密封**（`v1:<指纹>:<at>:<sig>`），意图实现「写入者 ≠ 信任根持有者」。但该版密封由**被钉固那把 attestation 公钥（AK）自签**其自身指纹——语义上等价于自签，**未引入第二独立权威**；重钉授权来自调用方自设 env（`METACOG_ATTEST_REPIN_ALLOW`）；删钉固行可静默关闸。生态外独立审计（deepseek-harness / DSH 沙箱，2026-10-27）对 v2.27.30 送审包裁定 **FAIL（2.2/5）**，核心承重 R-1 在生产态实测失效，两条无需私钥的接管路径（A：自设 REPIN_ALLOW 重钉自签；B：删钉固行静默放行）均可复现。owner 经授权按审计 §10 路线重做。
- **v2.27.32 双密钥根信任（R-1 真·授权分离）**：引入**独立于 AK 的根信任密钥 RK**（人类离线持有）。根锚密封 `v1:<AK_fp>:<at>:<sig_by_RK>` 改由 **RK 私钥签名、RK 公钥验签**——密封不再由 AK 自签，直接打破入口 A/B（攻击者无 RK 私钥无法产出合法密封）。RK 公钥指纹钉固为**最高权威** `root_attest_pubkey_sha256`（CONTRACT.md）；消费者信任链锚定在**包完整性哈希**（KK 带外发布），非机器内任意文件。重钉须 **RK 私钥签名授权**（`--repin-auth`，文件）替代旧 env 自授权；删 RK 钉固行 → `root_pin_missing` → verify 硬拒；读通道（retrieve）在 RK 已建立且密封无效时拒吐规则（rc=3）；`MAX_AGE_DAYS≤0` 钳为 90（时效不可关）；指纹强制 64 位 hex、at 强制 `YYYYMMDDTHHMM`。同版另修复产品 bug：`--repin-auth` 文件路径误当签名内容。验收：重写 `test-c1-attestation.py`（10 组 / 27 断言全 PASS，覆盖 §10 全部承重）+ `test-sigcrypto.py` 40/40 + 全量聚合 **55/55 诚实 PASS**。
- **v2.27.33 缺失态收口（R-2 · DSH 复审 §2.3/§2.1/§2.4）**：v2.27.32 双密钥模型经同一生态外审计方
  复审确认「设计路径做对了」，但实证两个 High——①删 RK 钉固行/RK_pub 文件可把 enforce 静默降为
  `off` 并重建攻击者自洽信任链（信任仍挂在一行可删的 Markdown 上）；②冻结账本 stale 使代码层认证断裂。
  v2.27.33 以**曾武装标记**（`_root_ever_armed`：RK_pub 文件或 v1 密封任一存在即 fail-closed）、
  **ledger-drift 对账**（verify 内置账本-实物逐条复算，无锚密钥可核验）、**读闸全状态覆盖**、
  RK 轮换授权（`--rotate-auth`）、时效双向钳制与未来时间戳拒收逐条收口；N-5（锚目录按实例名共享）
  如实 OPEN。结构性残余不变：同用户全写权 + 显式 `--armed-recovery` 仍可重建链——真正护栏 =
  RK 私钥离线持有 + 消费者侧带外指纹核对。
- **审计发现登记（v2.27.29，2026-10-26）**：同生态异族审计（Hermes）评级 **FAIL**（2 高 2 中 3 低），owner 独立复核确认并**新增最高危 H-A3**（删树外公钥 → 强制闸门整体降级放行，零告警、无需私钥/令牌，且绕开 H-2 收口）——**8 项发现全部 OPEN，本版零代码修复**（修复须 owner 逐次授权）。**口径修正**：H-2 / H-3 / E1 由「已收口」改口径为「部分收口 / 残余」，与 H-1 同口径；Leg-1 防御纵深级终态的残余面由「仅 H-1」修正为 **H-A3 + H-A1 + H-A2 + M-A1 四条并存**。详见 `references/audit-findings-2026-10-26.md`；送审包说明见 `references/audit-handoff-package.md`。**上述 8 项（含 H-A3）已于 v2.27.32 按 §10 路线全量收口（owner 授权），送审包重建见 `references/audit-handoff-package.md`**。
