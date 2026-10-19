# M1 自动触发机制 · 设计规格（Phase 1.1）

> 制定：2026-09-08 | 落地于 `scripts/metacog.py` | 目标版本 v2.0.0

## 1. 触发条件定义

- **连续 3 次 REVERT**（ratchet `history` 末尾 3 条均为 `action == "revert"`）→ 触发 M1 自动提议生成
- **混合历史**（REVERT + PROMOTE 混合，或不足 3 条）→ 不触发
- 触发后生成的 M1 提议进入隔离区（quarantine），**必须 `--human-ok` 确认才能 apply** —— 守住 G3 人类确认闸
- 开关：**默认关闭**，需显式 `verdict --auto-m1` 才启用（向后兼容：无 `--auto-m1` 时行为不变）

## 2. 数据流

```
cmd_verdict(st, args)
  └─ 现有双指标棘轮裁决（PROMOTE/REVERT）照常执行，且每次裁决向
     ratchet.history 追加 {at, proposal, action, utility, violation_rate, artifact, reason}
  └─ 连续3次REVERT检测（history[-3:] 全为 revert）
       ├─ 始终打印 [META] 提示（原有行为保留）
       └─ 若 args.auto_m1：
            └─ check_and_trigger_m1(st)
                 ├─ analyze_failure_pattern(ratchet) → {revert_count, artifact_focus, common_reasons}
                 ├─ generate_m1_content(pattern)    → M1 草稿 markdown
                 └─ 生成 M1 提议 {artifact:M1, op:replace, target:M-000,
                                      requires_human:True, triggered:True} 存入隔离区
```

## 3. 关键不变式（安全约束）

| 约束 | 保证方式 |
|---|---|
| 自动提议绝不自动生效 | 提议 `requires_human=True` + `op:replace` 命中 G1 的 M1 分支 → `cmd_apply` 须 `--human-ok` |
| 不动点不被触碰 | 提议只进 quarantine，不写 `metacog.py`/`SKILL.md`/`CONTRACT.md` |
| 失败闭环可追溯 | `failure_pattern` 随提议一并保存，人类确认前可审阅 |
| 向后兼容 | 无 `--auto-m1` 时 `getattr(args, "auto_m1", False)` 为 False，零副作用 |

## 4. history 记录增强

为支持 `artifact_focus` 与 `common_reasons`，`cmd_verdict` 在 PROMOTE/REVERT 两条分支向 `history` 追加时
额外写入 `artifact` 与 `reason` 字段（既有字段保留，向后兼容旧历史条目用 `.get` 读取）。

## 5. 验收用例（见 scripts/test-m1-auto-trigger.py）

- 失败模式分析：3 次连续 REVERT → `revert_count==3`、制品分布正确、原因捕获
- 混合历史：REVERT+PROMOTE → 不触发自动提议
- 自动触发：3 次 REVERT + `--auto-m1` → 隔离区新增 M1 提议，`requires_human` 为真
- CLI 参数：`verdict --auto-m1` 生效；无参时不触发；help 正确
