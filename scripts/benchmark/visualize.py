#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Phase 3.1 可视化报告
# D1 修正：matplotlib 为可选依赖。缺失时跳过 PNG 绘图，仍生成 HTML/JSON 报告
# （skill 硬约束：零第三方依赖，仅标准库）。
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import matplotlib
    matplotlib.use("Agg")  # 非交互式后端
    import matplotlib.pyplot as plt
    _HAS_MPL = True
except Exception:  # matplotlib 未安装 -> 降级，不阻塞报告生成
    _HAS_MPL = False


def visualize_benchmark(result_file: Path, output_dir: Path):
    """生成效用/违规趋势图（PNG）。matplotlib 缺失时跳过并返回 None。"""
    data = json.loads(Path(result_file).read_text(encoding="utf-8"))
    results = data.get("results", [])
    if not results:
        print("无结果可可视化: {}".format(result_file))
        return None
    if not _HAS_MPL:
        print("[跳过] matplotlib 未安装，未生成 PNG（HTML/JSON 报告仍可用）: {}".format(result_file))
        return None

    episodes = [r["episode"] for r in results]
    utilities = [r["evaluation"]["utility"] for r in results]
    violations = [r["evaluation"]["violations"] for r in results]

    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    ax1 = axes[0]
    ax1.plot(episodes, utilities, "b-", linewidth=1.5, label="Utility")
    ax1.axhline(y=sum(utilities) / len(utilities), color="r", linestyle="--",
                label="Average: {:.4f}".format(sum(utilities) / len(utilities)))
    ax1.set_xlabel("Episode")
    ax1.set_ylabel("Utility")
    ax1.set_title("{} - Utility Trend".format(data.get("domain", "Unknown")))
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    ax2.plot(episodes, violations, "g-", linewidth=1.5, label="Violations")
    avg_v = sum(violations) / len(violations)
    ax2.axhline(y=avg_v, color="r", linestyle="--", label="Average: {:.2f}".format(avg_v))
    ax2.set_xlabel("Episode")
    ax2.set_ylabel("Violations")
    ax2.set_title("{} - Violations Trend".format(data.get("domain", "Unknown")))
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    chart_file = Path(output_dir) / "{}-trend.png".format(data.get("domain", "unknown"))
    plt.savefig(chart_file, dpi=150, bbox_inches="tight")
    plt.close()
    print("图表已保存到: {}".format(chart_file))
    return chart_file


def generate_html_report(results_dir: Path, output_file: Path):
    """生成 HTML 汇总报告（仅标准库，任意环境可用）。"""
    results_dir = Path(results_dir)
    result_files = sorted(results_dir.glob("benchmark-*.json"))

    parts = ['<!DOCTYPE html>', '<html>', '<head>', '<meta charset="utf-8">',
             '<title>Benchmark Report</title>',
             '<style>body{font-family:Arial,sans-serif;margin:40px}'
             '.domain{margin-bottom:40px;padding:20px;border:1px solid #ddd}'
             '.metric{display:inline-block;margin-right:30px}'
             '.trend-improving{color:green}.trend-degrading{color:red}'
             '.trend-stable{color:gray}</style>', '</head>', '<body>',
             '<h1>Benchmark Report</h1>',
             '<p>Generated: {}</p>'.format(datetime.now().isoformat())]

    for rf in result_files:
        data = json.loads(Path(rf).read_text(encoding="utf-8"))
        domain = data.get("domain", "unknown")
        evals = [r.get("evaluation", {}) for r in data.get("results", [])]
        avg_u = sum(e.get("utility", 0) for e in evals) / max(len(evals), 1) if evals else 0
        trend = data.get("utility_trend", "stable")
        trend_class = "trend-{}".format(trend) if trend in ("improving", "degrading", "stable") else "trend-stable"
        parts.append('<div class="domain">')
        parts.append("<h2>{}</h2>".format(domain))
        parts.append('<div class="metric">Episodes: {}</div>'.format(data.get("episode_count", 0)))
        parts.append('<div class="metric">Duration: {:.1f}s</div>'.format(data.get("duration_seconds", 0)))
        parts.append('<div class="metric">Avg Utility: {:.4f}</div>'.format(avg_u))
        parts.append('<div class="metric {}">Trend: {}</div>'.format(trend_class, trend))
        png = "{}-trend.png".format(domain)
        if Path(results_dir / png).exists():
            parts.append('<img src="{}" width="600">'.format(png))
        parts.append("</div>")

    parts.append("</body></html>")
    Path(output_file).write_text("\n".join(parts), encoding="utf-8")
    print("HTML 报告已保存到: {}".format(output_file))
    return output_file


if __name__ == "__main__":
    if len(sys.argv) > 1:
        rf = Path(sys.argv[1])
        visualize_benchmark(rf, rf.parent)
        generate_html_report(rf.parent, rf.parent / "report.html")
    else:
        print("用法: python visualize.py <result_file.json>")
