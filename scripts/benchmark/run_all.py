#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Phase 3.1 统一 Benchmark 运行器
# 用法: python scripts/benchmark/run_all.py --domain code_review --episodes 50 --verbose
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.code_review import CodeReviewBenchmark
from benchmark.paper_review import PaperReviewBenchmark

SKILL_ROOT = Path(__file__).resolve().parents[2]


def generate_summary(reports: dict) -> dict:
    summary = {"timestamp": datetime.now().isoformat(), "domains": {}}
    total_episodes = 0
    total_duration = 0
    for domain, report in reports.items():
        summary["domains"][domain] = {
            "average_utility": report.get("average_utility"),
            "average_accuracy": report.get("average_accuracy"),
            "utility_trend": report.get("utility_trend"),
            "episode_count": report.get("episode_count"),
            "duration_seconds": report.get("duration_seconds"),
        }
        total_episodes += report.get("episode_count", 0)
        total_duration += report.get("duration_seconds", 0)
    summary["total_episodes"] = total_episodes
    summary["total_duration_seconds"] = total_duration
    summary["average_duration_per_episode"] = total_duration / max(total_episodes, 1)
    return summary


def main():
    ap = argparse.ArgumentParser(description="运行 metacog 跨领域 Benchmark（模拟）")
    ap.add_argument("--domain", "-d", choices=["code_review", "paper_review", "all"],
                    default="all", help="选择领域")
    ap.add_argument("--episodes", "-e", type=int, default=100, help="episode 数量")
    ap.add_argument("--output", "-o", type=Path,
                    default=SKILL_ROOT / "references" / "benchmark",
                    help="输出目录（结果落在 <output>/results/ 下）")
    ap.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = ap.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    benchmarks = []
    if args.domain in ("code_review", "all"):
        benchmarks.append(CodeReviewBenchmark(args.output))
    if args.domain in ("paper_review", "all"):
        benchmarks.append(PaperReviewBenchmark(args.output))

    all_reports = {}
    for bm in benchmarks:
        if args.verbose:
            print("\n运行 {} benchmark...".format(bm.domain))
        report = bm.run(episode_count=args.episodes)
        all_reports[bm.domain] = report
        result_file = bm.save_results()
        if args.verbose:
            print("结果已保存到: {}".format(result_file))
            print("平均 utility: {:.4f}".format(report.get("average_utility", 0)))
            print("趋势: {}".format(report.get("utility_trend", "N/A")))

    summary = generate_summary(all_reports)
    summary_file = args.output / "summary.json"
    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n汇总报告已保存到: {}".format(summary_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
