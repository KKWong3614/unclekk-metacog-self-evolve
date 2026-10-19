# 性能 Benchmark 框架规范（Phase 3.1）

> 来源：implementation-checklist-v2.0.md Phase 3.1
> 落地日期：2026-09-08
> 实现位置：`scripts/benchmark/`（base / code_review / paper_review / run_all / visualize）

## 1. 目标

提供跨领域「模拟」性能框架，量化多领域自改进效果（utility / violation_rate / accuracy / trend），
不调用真实 LLM（符合 skill 零第三方依赖约束）。当前预置 code_review / paper_review 两个领域。

## 2. 框架结构

- `base.py`：`BaseBenchmark` 抽象基类（setup → run_episode → evaluate → generate_report → save_results + calculate_trend）。
- `code_review.py` / `paper_review.py`：领域实现（模拟评审，纯 random 数据）。
- `run_all.py`：统一运行器（`--domain code_review|paper_review|all --episodes N --output DIR`）。
- `visualize.py`：趋势图（PNG，可选）+ HTML 汇总报告（纯标准库）。

## 3. 关键设计决策（相对清单的修正）

- **D1（matplotlib 可选）**：原 `visualize.py` 顶部 `import matplotlib.pyplot` 会在无该包环境直接崩溃，
  违反「零第三方依赖」。改为 `try/except` 降级：`_HAS_MPL=False` 时跳过 PNG 绘图并提示，
  HTML/JSON 报告仍正常生成。已实跑验证（环境无 matplotlib → 优雅跳过）。
- **D2（去硬编码路径）**：原 `code_review.py`/`paper_review.py` 写死 `D:\skill待检\unclekk-metacog-self-evolve`，
  破坏 P0-2 跨机器约束。改为 `SKILL_ROOT = Path(__file__).resolve().parents[2]` 推导技能根，`run_all` 默认输出也由技能根推导。
- **结果落盘**：`save_results()` 写入 `<output>/results/benchmark-<domain>-<ts>.json`；汇总 `summary.json` 写在 `<output>/`。

## 4. 运行

```bash
python3 scripts/benchmark/run_all.py --domain all --episodes 50 --verbose
python3 scripts/benchmark/visualize.py references/benchmark/results/benchmark-code_review-*.json
```

## 5. 验收

- 单领域 / 全领域均可运行；报告含 average_utility / utility_trend（及 paper_review 的 accuracy）。
- 结果 JSON 落盘；HTML 报告纯标准库生成（任意环境可用）。
- matplotlib 缺失环境不崩溃（降级跳过 PNG）。
