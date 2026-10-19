# 独立验收审计报告 · unclekk-metacog-self-evolve v2.4.0

- **审计对象**：v2.4.0「人类闸凭证化」（`confirm --init` / `confirm --approve` / `apply --token`，废除 `--human-ok`；PoC 报告 P1 修复）
- **引擎**：`scripts/metacog.py`（SHA256 见附录）
- **审计长**：独立 Agent 审计长（隔离上下文，不信任实现者自评，探针自写）
- **日期**：2026-09-24
- **基线**：v2.3.2 已 APPROVED（`references/independent-audit-v2.3.2.md`），本次验增量 + 全量回归
- **判定**：**✅ APPROVED**

---

## 0. 审计方法

1. **源码接线核查**（不信任声明，逐处 grep + 逐行阅读）；
2. **功能探针**：自写 `audit-probe-v240.py`（进程内 monkeypatch 模拟 TTY/getpass，覆盖声称 1–4 正反两面）——**63/63 PASS**；
3. **对抗探针**：自写 `audit-adv-v240.py`（**全部走 subprocess 真实 CLI，stdin/stdout 均管道的非 TTY 环境，零 monkeypatch**，攻击者视角 a–g）——**22/22 PASS**；
4. **全量回归**：scripts 目录全部 23 个 `test-*.py` 逐文件运行；
5. **不动点与文档一致性核查**。

未修改 `metacog.py` 与任何测试文件；探针全部落在审计工作目录与系统临时目录。

## 1. 接线核查（声称 → 代码）

| 声称 | 代码位置 | 结论 |
|---|---|---|
| `_require_tty` 检查 stdin+stdout | metacog.py:1905-1914 | ✅ 非 TTY（含 AttributeError/ValueError）一律 False |
| `cmd_confirm` 顶部 TTY 闸 | metacog.py:1923-1926 | ✅ init/approve 共用，先于一切口令逻辑（rc=2） |
| PBKDF2-SHA256 10 万轮加盐 | metacog.py:1897-1902, 1938-1945 | ✅ `iters=100_000`、salt 16 字节 hex、`hmac.compare_digest` 恒时比较（:1957） |
| 只存哈希不存明文 | metacog.py:1939-1945 | ✅ guard JSON 仅 salt/hash/algo/iters/created_at |
| 重复 init 幂等 | metacog.py:1928-1932 | ✅ 已设置即提示返回，guard 不重写 |
| `secrets.token_hex(16)` + 落 confirmations.jsonl | metacog.py:1961-1964, 499-511 | ✅ 绑定 proposal_id、TTL 30min、used=False、channel=tty-passphrase |
| `check_confirmation` 校验顺序 | metacog.py:513-534 | ✅ missing → binding → used → expired，reason 区分 |
| `mark_confirmation_used` 用后即焚 | metacog.py:536-543, 1164-1166 | ✅ 校验通过即整表重写标记 used+used_at |
| `--human-ok` 废除 | metacog.py:1160-1182, 2090-2091 | ✅ 无效凭证下命中旗标 → 硬拦截 rc=2 并指路 confirm |
| argparse 接线 | metacog.py:2089-2098, 2164-2171 | ✅ `confirm --init/--approve/--id`、`apply --token/--human-ok`、dispatch 全接 |

## 2. 功能探针结果（audit-probe-v240.py，63/63 PASS）

### 声称 1：`confirm --init`（14 项全过）
- 空口令 rc=2 不落 guard；两次不一致 rc=2 不落 guard；
- 正常 init rc=0；guard 含 salt/hash/algo/iters/created_at，**iters=100000、algo=pbkdf2-sha256**；
- **探针独立复算 PBKDF2 哈希与 guard.hash 逐位一致**（1.8）；明文不出现在 guard JSON（1.7）；salt 16 字节（1.9）；
- 重复 init 幂等 rc=0、提示「已设置」、guard 的 salt/hash 未被重写。

### 声称 2：`confirm --approve`（13 项全过）
- 未设口令先 approve → rc=2 不落凭证；口令错 → rc=2 不落凭证；缺 `--id` → rc=2 不落凭证；
- 口令对 → rc=0，stdout 打印 `TOKEN: <32hex>`（与 `secrets.token_hex(16)` 格式一致）；
- 恰落一条凭证：绑定正确提案 ID、used=False、channel=tty-passphrase、**TTL 实测 1800.0s**。

### 声称 3：`apply --token`（18 项全过）
- 无 token（D1）rc=2 且制品字节未变；伪造 token（32 个 0）rc=2；空 token rc=2（missing）；
- **挪用**：B 的 token 用于 A → rc=2，提示「token 绑定的是其他提案」；
- 正确 token → rc=0，M1 制品真实写入（条目 M-001 trial），凭证 used=True + used_at；
- **复用**：焚后强制提案回 gated 再 apply → rc=2（used），制品**字节级零变化**；
- **过期**：改 expires_at 为过去 → rc=2（expired），制品未写。

### 声称 4：`--human-ok` 废除 / 普通提案不受影响（6 项全过）
- requires_human 提议 + `--human-ok` → rc=2、提示「已废除」、制品未写；
- 普通提议（requires_human=False，A1+2 episodes）无 token 照常 apply rc=0。

### F 系列：还原真实 `_require_tty` 后（7 项全过）
- 非 TTY init/approve 全拒 rc=2，guard 与 confirmations 均不落盘；
- 直写假 guard 假哈希 + 任意口令 → 恒 rc=2（`compare_digest` 不可能通过）。

## 3. 对抗探针结果（audit-adv-v240.py，22/22 PASS，subprocess 真实非 TTY）

| # | 攻击向量 | 结果 |
|---|---|---|
| a/e.1-2 | 非 TTY `confirm --init`（管道喂 stdin） | ✅ rc=2，guard 不落盘 |
| a/e.3-4 | 非 TTY `confirm --approve` | ✅ rc=2，confirmations 不落盘 |
| a/e.5-6 | `--init --approve` 组合旗标一次打穿 | ✅ rc=2，无任何凭证文件 |
| f.1-2 | **直写假 guard 假哈希 + 非交互铸造** | ✅ rc=2，TTY 闸先拦，「未落任何凭证」——**硬承诺「非 TTY 进程无法铸造」成立** |
| f.3 | 拒绝信息可操作性 | ✅ 「[BLOCK] confirm 必须由人类在真实终端交互运行（当前非 TTY）」 |
| a.1-3 | 伪造（32hex 随机）/空/缺 token | ✅ 全部 rc=2 |
| b.1-2 | B 提案 token 用于 A 提案 | ✅ rc=2 binding，提示「绑定的是其他提案」 |
| c.1-2 | 已焚 token 复用 | ✅ rc=2 used，提示「已被使用」 |
| d.1-2 | 过期 token | ✅ rc=2 expired，提示「已过期」 |
| g.1-2 | requires_human=False 提议无 token apply | ✅ rc=0，不受新闸影响 |
| f.4 | **[声明内] 直写合法结构伪凭证 + apply** | 如实记录：rc=0 会被接受——与威胁模型声明完全一致（「不防直写 confirmations.jsonl」，属 `.metacog` 直写更强对抗模型），**声明诚实** |
| X.1 | **[声明内] 直改隔离区 JSON 把 requires_human 翻 False** | 如实记录：apply rc=0——同一更强对抗模型类，与 P2-3 重放的设计边界一致（重放只查 BLOCK 级检查，requires_human 本就非重放对象），声明边界诚实 |

**攻击者结论**：在「AI 可执行任意 CLI 但非 TTY」的现实约束下，铸造（TTY+口令）、挪用（绑定）、复用（一次性）、过期（限时）四条路全部堵死；仅剩的直写 `.metacog` 通道属实现者已声明的更强对抗模型，与 v2.2.x 以来的「诚实天花板」口径一致，无隐瞒。

## 4. 全量回归（23 文件，逐文件实跑）

| 测试文件 | 本次 | 基线 | 结论 |
|---|---|---|---|
| test-core.py | **14/14** rc=0 | 14 | ✅ 无回归（token 流改写含用后即焚断言） |
| test-boundary-cases.py | **40/40** rc=0 | 40 | ✅ |
| test-held-out.py | **31/31** rc=0 | 31 | ✅ |
| test-attribution.py | **16/16** rc=0 | 16 | ✅ |
| test-meta-policy.py | **16/16** rc=0 | 16 | ✅ |
| test-utility-derivation.py | **32/32** rc=0 | 32 | ✅ |
| test-adaptive-ratchet.py | **11/11** rc=0 | 11 | ✅ |
| test-meta-log-integration.py | **8/8** rc=0 | 8 | ✅ |
| test-cli-wiring.py | **4/4** rc=0 | 4 | ✅ |
| test-d2-d5.py | **47/47** rc=0（D2:9 D3:6 D4:4 D5:5 P2:13 P3:10） | 47 | ✅ |
| **test-human-gate.py（新）** | **22/22** rc=0 | 22（新基线） | ✅ |
| test-p2-1-meta-optimizer.py | 2/3 rc=1（失败项=`test_meta_optimizer_with_log`） | 2/3 已知时间炸弹 | ✅ 未恶化（同一用例） |
| test-benchmark.py | 13/13 | — | ✅ |
| test-domain-init.py | 12/12 | — | ✅ |
| test-domain-migration.py | 6/6 | — | ✅ |
| test-init-domain.py | 8/8 | — | ✅ |
| test-m1-auto-trigger.py | 19/19 | — | ✅ |
| test-meta-log-command.py | 8/8 | — | ✅ |
| test-meta-log.py | 13/13 | — | ✅ |
| test-p0-1-real-data.py | 15/15 | — | ✅ |
| test-p0-2-knowledge-transfer.py | 19/19 | — | ✅ |
| test-p2-2-domain-detector.py | 5/5 | — | ✅ |
| test-p2-3-visualize.py | 6/6 | — | ✅ |

**唯一 rc≠0 为 test-p2-1 已知时间炸弹，与任务书基线一致，未恶化。**

## 5. 不动点与文档一致性

- `IMMUTABLE_TARGETS = ("CONTRACT.md", "metacog.py", "SKILL.md")`（metacog.py:49）✅ 完整；
- SKILL.md frontmatter `version: 2.4.0` ✅；
- CONTRACT.md:40 **G3 描述已改为 token 流**（「人类 TTY `confirm --approve` 铸造的一次性 `--token`……`--human-ok` 已废除」）✅；
- SKILL.md:185/314/454/473 人类闸凭证化与威胁模型声明完整，与 CHANGELOG v2.4.0 一致 ✅。

## 6. 问题清单

- **P0**：无。
- **P1**：无。
- **P2**：无。
- **P3 / 备注**（不阻塞 APPROVED）：
  1. **P3-1（文档陈旧引用）**：`CONTRACT.md:47` 仍写「凡命中红线的语义可疑项一律升级为需人类确认（`--human-ok`）」——旗标已废除，应改为「人类 TTY `confirm --approve` 一次性 token 凭证」。纯文档级，建议下版顺手修。
  2. **P3-2（继承观察）**：`metacog.py` 模块内仍无版本常量（VERSION/__version__ 缺失），与 v2.3.2 审计备注相同，探针只能依赖 frontmatter 取版本。可观测性建议。
  3. **P3-3（声明内边界实测，仅记录）**：①直写 `ledger/confirmations.jsonl` 合法结构伪凭证 + `apply --token` → rc=0 被接受；②直改隔离区 JSON `requires_human=False` → 无凭证 apply rc=0。两者均属实现者已诚实声明的 `.metacog` 直写更强对抗模型（不防，由 D4 verify 同等力度兜底、凭证账本不在哈希快照内）。本审计验证的是「声明与行为一致」——一致，无隐瞒。可选未来增强：token 落账本时存哈希（显示明文一次）、apply 锚与 token 绑定签名。
  4. **备注**：`confirm --approve` 的 TTL/绑定字段明文可读属设计内（人类已确认该提案，AI 执行落盘是流程本意），与声明一致。

## 7. 最终判定

### ✅ APPROVED

- 四项声称全部经独立探针正反双向验证：功能面 63/63、对抗面 22/22，合计 **85/85 PASS**；
- 硬承诺「非 TTY 进程无法铸造凭证」在真实非交互 subprocess 环境下成立（含直写假哈希、组合旗标、管道喂口令等绕行尝试）；
- 铸造/挪用/复用/过期四条攻击路全堵，错误信息区分四类原因且可操作；
- `--human-ok` 废除落地，D1 退出码语义保留，普通提案零影响；
- 全量回归 23 文件与基线完全一致，唯一 rc=1 为已知时间炸弹且未恶化；
- 不动点完整、frontmatter 2.4.0、CONTRACT.md G3 已改 token 流；
- 威胁模型声明与实测行为一致，无夸大、无隐瞒。

---
*审计探针存档（不改引擎、不改测试）*：
- 功能探针：`C:/Users/Administrator/WorkBuddy/2026-09-22-16-54-27/audit-probe-v240.py`（63/63 PASS，Exit 0）
- 对抗探针：`C:/Users/Administrator/WorkBuddy/2026-09-22-16-54-27/audit-adv-v240.py`（22/22 PASS，Exit 0）

*审计对象指纹*：`scripts/metacog.py` SHA256 = `755e7d514d70eb0e2566048ba35cc1a6c7a83a4bddba951703a12eb87cbae01f`
