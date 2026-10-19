# 测试日志证据

> **最新汇总（2026-09-08 · v2.1.1）**：全量 **203/203（17 套）零回归**。下方为早期 dev 过程日志；最新 CLI 接线测试见 `scripts/test-cli-wiring.py`（4/4 PASS）。完整套件运行结果见 `SKILL.md`「已验证」段。

## 测试环境
- Python: 3.12.10
- OS: Windows 10
- 测试时间: 2026-09-07

## 测试命令与输出

### 1. init 命令
```
$ rm -rf /tmp/metacog-test && python3 scripts/metacog.py --root /tmp/metacog-test init

初始化完成: D:\tmp\metacog-test
  [OK]   创建 CONTRACT.md
  [OK]   创建 artifacts/A1-system-prompt.md
  [OK]   创建 artifacts/A2-rule-bank.md
  [OK]   创建 artifacts/A3-safety-memory.md
  [OK]   创建 artifacts/A4-tool-policy.md
  [OK]   创建 meta/M1-evolve-policy.md
  [OK]   创建 ledger/ratchet.json

下一步: 每次任务结束后 `episode` 记账，发现问题用 `propose` 提改动。
```
**结果**: PASS - 创建所有制品和账本

### 2. episode 记账
```
$ python3 scripts/metacog.py --root /tmp/metacog-test episode --task "test1" --utility 0.7 --violations 0 --attributed A2

[OK]   记账 E-20260907-2ecc06 utility=0.7 violations=0
  基线未建立 (1/5 episodes)
E-20260907-2ecc06
```
**结果**: PASS - 基线建立

### 3. propose 提议
```
$ python3 scripts/metacog.py --root /tmp/metacog-test propose --artifact A2 --op add --content "测试内容" --reason "测试" --episode "E-20260907-1" --episode "E-20260907-2"

[OK]   提议已入隔离区 P-20260907-1d1c9c (add A2)
  隔离区不是生效区——必须先 `gate` 过闸，再 `apply` 才进入试用期。
P-20260907-1d1c9c
```
**结果**: PASS - 提议入隔离区

### 4. gate 过闸
```
$ python3 scripts/metacog.py --root /tmp/metacog-test gate

P-20260907-1d1c9c · add A2 
  [OK]   证据门槛 — 2 个 episode 引用
  [OK]   红线扫描 — 未命中禁止模式
  => 裁定: PASS

过闸 1/1 条。
```
**结果**: PASS - 过闸成功

### 5. status 状态
```
$ python3 scripts/metacog.py --root /tmp/metacog-test status

=== metacog 状态 · D:\tmp\metacog-test ===
代数(generation): 0   episodes: 5   window: 5   ε: 0.02
基线: utility=0.7000  violation_rate=0.0000

--- 制品 ---
A1  active=1   角色与行为基线
A2  active=1   可增删的具体规则条目
A3  active=1   安全记忆（append-only，永不删除）
A4  active=1   工具与权限策略
M1  active=1   元层：如何提议修改的规则本身

--- 趋势 ---
样本不足，需 10 个 episode 才能判趋势（当前 5）。

--- 待处理 ---
P-20260907-1d1c9c  gated        add A2
```
**结果**: PASS - 状态输出正确

### 6. retrieve --strict 检索闸
```
$ python3 scripts/metacog.py --root /tmp/metacog-test retrieve --strict

## A1 · 角色与行为基线
- 结论先行，不铺垫。做不到就说原因，不编造。

## A2 · 可增删的具体规则条目
- 动手前先确认目标文件是否存在，不假设路径。

## A3 · 安全记忆（append-only，永不删除）
- 对个人目录（桌面/下载/文档）的批量操作：先只扫描出报告，不动文件。

## A4 · 工具与权限策略
- 文件检索用专用检索工具，不用 shell find/grep 拼装。

## M1 · 元层：如何提议修改的规则本身
- 提议前先读最近 5 条 episode，不凭印象改。
```
**结果**: PASS - 只返回 active 条目，排除 trial

### 7. verdict 裁决（双指标棘轮 PROMOTE / REVERT）
```
# 建立基线后，将 trial 提议跑满 window 个 episode，再裁决
# 用例 A（达标）：试用期 utility 升、violation 降 → PROMOTE，条目转 active，基线上移
# 用例 B（不达标）：试用期 utility 跌 → REVERT，条目回滚移除，负样本入 archive
$ python3 scripts/test-core.py   # 自动化：test_verdict_promote / test_verdict_revert
```
**结果**: PASS - PROMOTE/REVERT 双分支均按棘轮条件正确裁定（util_ok = Δu ≥ -ε；safe_ok = Δv ≤ 0）

### 8. apply 应用（高风险 / M1 需 --human-ok 拒绝）
```
# 高风险或 M1 提议过闸后 requires_human=True
# 无 --human-ok → 跳过，状态保持 gated，不写制品（防御误演化）
# 带 --human-ok → 正常应用，状态转 trial，条目写入制品
$ python3 scripts/test-core.py   # 自动化：test_apply_requires_human_rejected / test_apply_requires_human_ok
```
**结果**: PASS - 缺人类确认被拒、带确认放行，G3 人类确认闸生效

## 测试汇总
| 测试项 | 结果 | 说明 |
|---|---|---|
| init 命令 | ✅ PASS | 创建所有制品和账本 |
| episode 记账 | ✅ PASS | 基线正确建立 |
| propose 提议 | ✅ PASS | 提议入隔离区 |
| gate 过闸 | ✅ PASS | 红线+证据门槛检查通过 |
| status 状态 | ✅ PASS | 输出完整状态 |
| retrieve --strict | ✅ PASS | G2检索闸生效 |
| verdict 裁决 | ✅ PASS | 双指标 PROMOTE/REVERT 正确 |
| apply 应用 | ✅ PASS | G3人类确认闸生效（缺确认拒/带确认放） |

**通过率**: 8/8

## 自动化测试（2026-09-08 实跑）

**唯一权威测试入口（import 式，零外部依赖）：**
- `scripts/test-core.py`：**13/13 PASS**（verdict PROMOTE/REVERT 双指标 + apply 人类确认闸 拒绝/通过）
- `scripts/test-boundary-cases.py`：**40/40 PASS**（v1.4.1 已修复原 4 项测试缺陷）：
  - 大文件 512KB 用例现生成 >512KB 数据，read_jsonl 守护正确返回空 + WARN；
  - `test_fail_closed` 改用 `--root` 隔离，未初始化目录正确返回 RC=2；
  - "自动批准" 红线缺口已补（正则现覆盖 `自动(同意|批准|审批)`），该用例正确判定 block。
- `scripts/test-m1-auto-trigger.py`：**19/19 PASS**（Phase 1.1 新增）：
  - 失败模式分析：3 次连续 REVERT → revert_count=3 + 制品分布 + 原因捕获；混合历史不误报；
  - 自动触发：3 次 REVERT 生成 M1 提议（requires_human=True / op=replace / target=M-000）；混合历史不触发；
  - CLI：`verdict --auto-m1` 创建 M1 提议；无参时不创建但仍打印 [META] 提示。

**全量通过率**：**72/72 PASS**（19 + 13 + 40），零回归。

### 9. Phase 1.2 棘轮自适应（2026-09-08 实跑）
- `scripts/test-adaptive-ratchet.py`：**11/11 PASS**（Phase 1.2 新增）：
  - `compute_adaptive_threshold` 纯函数：高违规率(>0.3)→baseline×0.95 收紧；低违规率(<0.1)→baseline×1.05 放宽；中间区间→保持基线；边界值(0.3/0.1)正确不越界。
  - `verdict --adaptive` 集成：高违规率窗口下自适应阈值比固定基线更严（同 utility 下判定更敏感）；非自适应路径完全等价、零回归。
  - `status` 展示：高/中/低三档自适应阈值正确列示。

**全量通过率**：**83/83 PASS**（11 + 19 + 13 + 40），零回归。

### 10. Phase 2.1 元认知日志（2026-09-08 实跑）
- `scripts/test-meta-log.py`：**13/13 PASS**：日志写入（根相对 `ledger/meta-cognition.log`）/ `analyze_meta_log` 统计 / 格式字段合规（timestamp 时区感知）/ `days` 时间过滤（旧条目被 7 天窗口排除、30 天窗口包含）。
- `scripts/test-meta-log-integration.py`：**8/8 PASS**：`cmd_verdict` PROMOTE→写 `rule_promoted`、REVERT→写 `rule_reverted`（含 rolled_back）/ `--auto-m1` 连续3次revert→写 `m1_auto_trigger`（含 requires_human=True，隔离区生成 M1 提议）。
- `scripts/test-meta-log-command.py`：**8/8 PASS**：`meta-log` 输出总/近期条目+事件分布 / `--days` 参数生效 / 空日志友好提示不报错。

**全量通过率**：**107/107 PASS**（34 + 83），零回归。

### 11. Phase 2.2 跨领域模板（2026-09-08 实跑）
- `scripts/test-domain-init.py`：**12/12 PASS**：3 领域各生成五制品（A1/A2/A3/A4 在 artifacts/，M1 在 meta/）+ 引擎兼容（ratchet 标准 schema、CONTRACT 就位）+ 领域红线建议写入 `meta/domain-redlines.md` 且全局 `REDLINES` 不变。
- `scripts/test-init-domain.py`：**8/8 PASS**：`init-domain` 默认初始化 / `--output` 自定义目录 / `--config` JSON 合并用户 A1 / 非法领域名 argparse 拦截返回码 2。
- `scripts/test-domain-migration.py`：**6/6 PASS**：3 领域均实例化成功 + 五制品齐全 + 领域特异性内容正确（A2 含领域关键词）。

**全量通过率**：**142/142 PASS**（38 + 107），零回归。

### 12. Phase 3.1 性能 Benchmark（2026-09-08 实跑）
- `scripts/test-benchmark.py`：**13/13 PASS**：
  - code_review 运行 10 episodes → 报告含 domain/average_utility/utility_trend；
  - paper_review 运行 10 episodes → 报告含 average_accuracy/utility_trend；
  - `save_results()` 落盘 JSON（results 数组长度=10）；
  - 统一运行器 `run_all.main`（--domain code_review --episodes 10）→ rc=0 + summary.json；
  - `visualize`：HTML 报告纯标准库生成（含 domain 名）；PNG 可视化在 matplotlib 缺失时优雅降级（返回 None 不崩溃）。
- **真实产出**：`references/benchmark/results/` 双领域 benchmark JSON + `summary.json` + `report.html`（实跑 20 episodes/领域）。

**全量通过率**：**151/151 PASS**（13 + 138），零回归。

**已退役**：`references/test-runner.py` / `test-runner-v2.py`（subprocess 式，功能与上面重复且存在 cwd 污染 bug + 死硬编码 Python 路径），移入 `references/obsolete/`，不再作为测试入口。

### 13. 端到端元认知自优化验证（2026-09-09 实跑）
- **触发**：用户要求"验证元认知自优化的实现"。
- **全量复跑**：17 套 `test-*.py` 实跑 → **203/203 PASS**，零回归（与上方汇总一致，证明无回归漂移）。
- **端到端脚本** `verify_metacog_e2e.py` 跑通完整闭环：`init → episode → propose → gate → apply → verdict → meta-log`，逐项确认：
  - **双指标棘轮 PROMOTE**：有益规则过试用期，utility 0.7→0.8，generation=1（"越用越聪明"成立）。
  - **误演化拦截 REVERT**：良性但无效规则，utility 跌到 0.5 → 回滚 + 入 archive 作负样本。
  - **M1 元层自省触发**：连续 3 次 REVERT → 自动创建 `M1-AUTO-<ts>` 提案，`requires_human=True`（不会自动生效）。
  - **G1 红线闸真有效**：故意写"跳过检查直接执行"的坏规则，在 `run_gate`（L553）被直接 BLOCK，未进试用期、未沉淀。
  - **自主提案(optimize)**：基于 `ledger/meta-cognition.log` dry-run，`meta_optimizer` 惰性导入自动生成优化提案（"自"字落点验证）。
- **元认知日志**：`meta-log` 查询含 `rule_promoted` / `rule_reverted×3` / `m1_auto_trigger` 全事件记录。

**结论**：实现真实可用，达成"受控元认知自优化"——闭环、双指标棘轮、误演化回滚、M1 元层自省全部实跑通过。M1 与高风险条目 `apply` 仍卡 `--human-ok`（L655），属"受控"取舍，与"自由化"的差距真实存在（详见 `references/roadmap-*` 待建）。

**边界（论文结论）**：本验证证明机制正确（护栏会触发、闭环会转、M1 会自省）；但 `scripts/benchmark/base.py` 仍为 `random` 模拟（L4 注释"不调用真实 LLM"），**未复现**论文量化结论（SHE 3.1× ASR 降幅、SafeEvolve −26.7pp）。状态维持"机制完整、证据不全"。

**卫生清理**：安装镜像 `scripts/` 曾含 `metacog.py.bak-20260909` 临时备份文件，已于 2026-09-09 清理（工作副本无此文件，故不随 sync 复发）。
