#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# P0-1 测试：验证真实性能数据
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from benchmark.code_review import CodeReviewBenchmark
from benchmark.paper_review import PaperReviewBenchmark


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def add(self, name, ok, detail=""):
        self.passed += ok
        self.failed += (not ok)
        print("  [{}] {}{}".format("PASS" if ok else "FAIL", name,
                                    (" - " + detail) if detail else ""))


def test_code_review_real_data():
    """测试代码评审使用真实数据"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_bm_real_cr_"))
    try:
        bm = CodeReviewBenchmark(tmp)
        report = bm.run(episode_count=10)
        
        # 验证报告结构
        t.add("报告含 domain", report.get("domain") == "code_review")
        t.add("报告含 average_utility", "average_utility" in report)
        t.add("报告含 utility_trend", "utility_trend" in report)
        t.add("报告含 baseline_comparison", "baseline_comparison" in report)
        
        # 验证真实性（非随机）
        t.add("utility在合理范围", 0.5 <= report.get("average_utility", 0) <= 0.95)
        t.add("trend不为insufficient", report.get("utility_trend") != "insufficient_data")
        
        # 验证测试结果
        t.add("有基线对比", report.get("baseline_comparison", {}).get("improvement", 0) > 0)
        
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_paper_review_real_data():
    """测试论文评审使用真实数据"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_bm_real_pr_"))
    try:
        bm = PaperReviewBenchmark(tmp)
        report = bm.run(episode_count=10)
        
        # 验证报告结构
        t.add("报告含 domain", report.get("domain") == "paper_review")
        t.add("报告含 average_accuracy", "average_accuracy" in report)
        t.add("报告含 utility_trend", "utility_trend" in report)
        t.add("报告含 baseline_comparison", "baseline_comparison" in report)
        
        # 验证真实性
        t.add("accuracy在合理范围", 0.5 <= report.get("average_accuracy", 0) <= 0.95)
        t.add("趋势可计算", report.get("utility_trend") in ["improving", "stable"])
        
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_deterministic_output():
    """验证输出确定性（非随机）"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_bm_determ_"))
    
    try:
        bm1 = CodeReviewBenchmark(tmp / "run1")
        report1 = bm1.run(episode_count=5)
        
        bm2 = CodeReviewBenchmark(tmp / "run2")
        report2 = bm2.run(episode_count=5)
        
        # 相同输入应产生相同输出
        t.add("utility一致", report1["average_utility"] == report2["average_utility"])
        t.add("trend一致", report1["utility_trend"] == report2["utility_trend"])
        
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    
    return t


if __name__ == "__main__":
    print("=" * 70)
    print("P0-1 测试：真实性能数据验证")
    print("=" * 70)
    
    total_passed = 0
    total_failed = 0
    
    tests = [
        ("代码评审真实数据", test_code_review_real_data),
        ("论文评审真实数据", test_paper_review_real_data),
        ("输出确定性验证", test_deterministic_output),
    ]
    
    for name, test_func in tests:
        print(f"\n【{name}】")
        result = test_func()
        print(f"  结果: {result.passed}/{result.passed + result.failed} PASS")
        total_passed += result.passed
        total_failed += result.failed
    
    print("\n" + "=" * 70)
    print(f"总计: {total_passed}/{total_passed + total_failed} PASS")
    if total_failed == 0:
        print("✅ P0-1 测试通过")
    else:
        print(f"❌ {total_failed}项未通过")
    print("=" * 70)
    
    sys.exit(0 if total_failed == 0 else 1)
