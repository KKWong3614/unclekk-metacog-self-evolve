#!/usr/bin/env python3
# Phase 3.1 测试：跨领域 Benchmark 框架（模拟）
# 覆盖：code_review / paper_review 运行 + 报告 + 结果落盘 + 统一运行器 + 可视化降级
# 零第三方依赖，import benchmark 包直接单测。matplotlib 缺失时可视化优雅降级。
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

import json
import shutil
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))
from benchmark.code_review import CodeReviewBenchmark
from benchmark.paper_review import PaperReviewBenchmark
from benchmark import visualize


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def add(self, name, ok, detail=""):
        self.passed += ok
        self.failed += (not ok)
        print("  [{}] {}{}".format("PASS" if ok else "FAIL", name,
                                    (" - " + detail) if detail else ""))


def test_code_review_run():
    """code_review benchmark 运行生成报告（含 average_utility / utility_trend）"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_bm_cr_"))
    try:
        bm = CodeReviewBenchmark(tmp)
        report = bm.run(episode_count=10)
        t.add("报告含 domain", report.get("domain") == "code_review", str(report.get("domain")))
        t.add("报告含 average_utility", "average_utility" in report and report["average_utility"] > 0,
              "avg_u={:.4f}".format(report.get("average_utility", 0)))
        t.add("报告含 utility_trend", "utility_trend" in report, str(report.get("utility_trend")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_paper_review_run():
    """paper_review benchmark 运行生成报告（含 average_accuracy）"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_bm_pr_"))
    try:
        bm = PaperReviewBenchmark(tmp)
        report = bm.run(episode_count=10)
        t.add("报告含 domain", report.get("domain") == "paper_review", str(report.get("domain")))
        t.add("报告含 average_accuracy", "average_accuracy" in report, "accuracy 字段存在")
        t.add("报告含 utility_trend", "utility_trend" in report, str(report.get("utility_trend")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_save_results():
    """save_results 落盘 JSON 结果文件"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_bm_save_"))
    try:
        bm = CodeReviewBenchmark(tmp)
        bm.run(episode_count=10)
        fp = bm.save_results()
        t.add("结果 JSON 已写入", fp.exists(), str(fp))
        data = json.loads(fp.read_text(encoding="utf-8"))
        t.add("JSON 含 results 数组", isinstance(data.get("results"), list) and len(data["results"]) == 10,
              "results 长度={}".format(len(data.get("results", []))))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_run_all():
    """统一运行器 run_all.main 跑通（--domain code_review 小样本）→ 0 + summary.json"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_bm_all_"))
    try:
        old_argv = sys.argv
        sys.argv = ["run_all", "--domain", "code_review", "--episodes", "10", "--output", str(tmp)]
        try:
            rc = __import__("benchmark.run_all", fromlist=["main"]).main()
        finally:
            sys.argv = old_argv
        t.add("返回码 0", rc == 0, "rc={}".format(rc))
        t.add("summary.json 生成", (tmp / "summary.json").exists(), "汇总报告就位")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_visualize_html_only():
    """可视化：HTML 报告纯标准库生成；matplotlib 缺失时 PNG 优雅降级不崩"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_bm_viz_"))
    try:
        # 构造一个最小结果 JSON
        payload = {
            "domain": "code_review",
            "episode_count": 10,
            "duration_seconds": 1.0,
            "results": [{"episode": i, "evaluation": {"utility": 0.7, "violations": 1}}
                        for i in range(1, 11)],
        }
        rf = tmp / "benchmark-code_review-test.json"
        rf.write_text(json.dumps(payload), encoding="utf-8")

        # HTML 报告（纯标准库，必成功）
        html = visualize.generate_html_report(tmp, tmp / "report.html")
        t.add("HTML 报告生成", Path(html).exists(), str(html))
        t.add("HTML 含 domain 名", "code_review" in Path(html).read_text(encoding="utf-8"), "内容正确")

        # PNG 可视化：无论 matplotlib 是否可用都不应抛异常
        res = visualize.visualize_benchmark(rf, tmp)
        ok_degrade = res is None or isinstance(res, Path)
        t.add("PNG 可视化不崩溃（缺 matplotlib 则降级）", ok_degrade,
              "返回 {}".format("None(降级)" if res is None else res.name))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def main():
    print("=" * 60)
    print("跨领域 Benchmark 测试 (Phase 3.1)")
    print("=" * 60 + "\n")
    groups = [test_code_review_run(), test_paper_review_run(), test_save_results(),
              test_run_all(), test_visualize_html_only()]
    passed = sum(g.passed for g in groups)
    failed = sum(g.failed for g in groups)
    total = passed + failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
