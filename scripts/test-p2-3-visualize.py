#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# P2-3 测试：验证纯Python可视化
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def test_text_chart_bar():
    """测试文本条形图"""
    try:
        from visualize_text import TextChart
        
        chart = TextChart()
        
        # 测试基本条形图
        data = {"Python": 0.8, "Java": 0.6, "C++": 0.4}
        result = chart.bar_chart(data, "语言对比")
        assert "Python" in result
        assert "Java" in result
        assert "C++" in result
        assert "█" in result  # 条形字符
        
        # 测试空数据
        result = chart.bar_chart({}, "空数据")
        assert "无数据" in result
        
        print("✅ test_text_chart_bar PASS")
        return True
    except Exception as e:
        print(f"❌ test_text_chart_bar FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_text_chart_trend():
    """测试趋势指示器"""
    try:
        from visualize_text import TextChart
        
        chart = TextChart()
        
        assert "改善" in chart.trend_indicator("improving")
        assert "退化" in chart.trend_indicator("degrading")
        assert "稳定" in chart.trend_indicator("stable")
        assert "未知" in chart.trend_indicator("unknown")
        
        print("✅ test_text_chart_trend PASS")
        return True
    except Exception as e:
        print(f"❌ test_text_chart_trend FAIL: {e}")
        return False


def test_html_chart_bar():
    """测试HTML条形图"""
    try:
        from visualize_text import HtmlChart
        
        chart = HtmlChart()
        
        # 测试基本条形图
        data = {"Python": 0.8, "Java": 0.6}
        result = chart.render_bar_chart(data, "语言对比")
        assert "<div class=\"chart-container\">" in result
        assert "Python" in result
        assert "Java" in result
        assert "style=" in result  # 内联样式
        
        # 测试空数据
        result = chart.render_bar_chart({}, "空数据")
        assert "无数据" in result
        
        print("✅ test_html_chart_bar PASS")
        return True
    except Exception as e:
        print(f"❌ test_html_chart_bar FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_html_chart_line():
    """测试HTML折线图"""
    try:
        from visualize_text import HtmlChart
        
        chart = HtmlChart()
        
        # 测试折线图
        points = [{"x": 1, "y": 0.5}, {"x": 2, "y": 0.7}, {"x": 3, "y": 0.6}]
        result = chart.render_line_chart(points, "效用趋势")
        assert "<svg" in result
        assert "<path" in result
        assert "<circle" in result
        
        # 测试空数据
        result = chart.render_line_chart([], "空数据")
        assert "无数据" in result
        
        print("✅ test_html_chart_line PASS")
        return True
    except Exception as e:
        print(f"❌ test_html_chart_line FAIL: {e}")
        return False


def test_benchmark_visualizer():
    """测试Benchmark可视化器"""
    try:
        from visualize_text import BenchmarkVisualizer
        
        # 创建模拟数据
        results = {
            "summary": {
                "total_episodes": 100,
                "average_utility": 0.75,
                "average_accuracy": 0.82,
                "utility_trend": "improving"
            },
            "domains": {
                "code_review": {
                    "average_utility": 0.78,
                    "baseline_utility": 0.70,
                    "violation_rate": 0.05
                },
                "paper_review": {
                    "average_utility": 0.72,
                    "baseline_utility": 0.68,
                    "violation_rate": 0.08
                }
            }
        }
        
        visualizer = BenchmarkVisualizer(results)
        
        # 测试文本报告
        text_report = visualizer.generate_text_report()
        assert "Benchmark" in text_report
        assert "100" in text_report  # total_episodes
        assert "0.75" in text_report  # average_utility
        
        # 测试HTML报告生成
        tmp = Path(tempfile.mkdtemp(prefix="metacog_p2_3_"))
        try:
            html_path = tmp / "report.html"
            visualizer.generate_html_report(html_path)
            assert html_path.exists()
            
            html_content = html_path.read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in html_content
            assert "Benchmark" in html_content
            assert "code_review" in html_content
            assert "paper_review" in html_content
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        
        print("✅ test_benchmark_visualizer PASS")
        return True
    except Exception as e:
        print(f"❌ test_benchmark_visualizer FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_visualize_command():
    """测试可视化命令"""
    try:
        import subprocess
        
        # 创建临时数据文件
        tmp = Path(tempfile.mkdtemp(prefix="metacog_p2_3b_"))
        try:
            data_path = tmp / "data.json"
            data = {
                "summary": {
                    "total_episodes": 50,
                    "average_utility": 0.7,
                    "utility_trend": "stable"
                },
                "domains": {}
            }
            data_path.write_text(json.dumps(data, indent=2))
            
            output_dir = tmp / "output"
            
            # 运行可视化命令
            result = subprocess.run(
                [sys.executable, "-m", "visualize_text", "--input", str(data_path), "--output", str(output_dir)],
                capture_output=True, text=True,
                cwd=str(Path(__file__).parent)
            )
            
            # 检查输出
            text_report = output_dir / "report.txt"
            html_report = output_dir / "report.html"
            
            assert text_report.exists(), "文本报告应生成"
            assert html_report.exists(), "HTML报告应生成"
            
            print("✅ test_visualize_command PASS")
            return True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        print(f"❌ test_visualize_command FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    results = []
    results.append(test_text_chart_bar())
    results.append(test_text_chart_trend())
    results.append(test_html_chart_bar())
    results.append(test_html_chart_line())
    results.append(test_benchmark_visualizer())
    results.append(test_visualize_command())
    
    passed = sum(results)
    total = len(results)
    
    print(f"\n{'='*70}")
    print(f"P2-3 测试结果: {passed}/{total} PASS")
    print(f"{'='*70}\n")
    
    sys.exit(0 if passed == total else 1)
