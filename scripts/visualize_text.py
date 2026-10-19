#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# P2-3 修复：纯Python可视化模块
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

class TextChart:
    """文本图表生成器"""
    
    @staticmethod
    def bar_chart(data: Dict[str, float], title: str = "", width: int = 40) -> str:
        """生成条形图"""
        if not data:
            return "无数据"
        
        max_val = max(data.values()) if data.values() else 1
        lines = []
        
        if title:
            lines.append(f"\n{title}")
            lines.append("-" * len(title))
        
        for key, val in sorted(data.items(), key=lambda x: x[1], reverse=True):
            bar_len = int((val / max_val) * width) if max_val > 0 else 0
            bar = "█" * bar_len
            percentage = f"({val:.2%})" if max_val > 0 else ""
            lines.append(f"{key[:20]:<20} {bar:>{width}} {percentage}")
        
        return "\n".join(lines)
    
    @staticmethod
    def trend_indicator(trend: str) -> str:
        """趋势指示器"""
        indicators = {
            "improving": "↑ 改善",
            "degrading": "↓ 退化",
            "stable": "→ 稳定",
            "unknown": "？ 未知"
        }
        return indicators.get(trend, indicators["unknown"])


class HtmlChart:
    """HTML图表生成器"""
    
    @staticmethod
    def render_bar_chart(data: Dict[str, float], title: str = "", color: str = "#4CAF50") -> str:
        """生成HTML条形图"""
        if not data:
            return '<div class="chart-empty">无数据</div>'
        
        max_val = max(data.values()) if data.values() else 1
        
        html = f'<div class="chart-container">\n'
        if title:
            html += f'  <h3>{title}</h3>\n'
        
        html += '  <div class="bar-chart">\n'
        for key, val in sorted(data.items(), key=lambda x: x[1], reverse=True):
            pct = (val / max_val * 100) if max_val > 0 else 0
            html += f'    <div class="bar-row">\n'
            html += f'      <span class="bar-label">{key}</span>\n'
            html += f'      <div class="bar-wrapper">\n'
            html += f'        <div class="bar" style="width: {pct}%; background-color: {color};" title="{val:.4f}"></div>\n'
            html += f'      </div>\n'
            html += f'      <span class="bar-value">{val:.4f}</span>\n'
            html += f'    </div>\n'
        html += '  </div>\n'
        html += '</div>'
        
        return html
    
    @staticmethod
    def render_line_chart(points: List[Dict[str, Any]], title: str = "", color: str = "#2196F3") -> str:
        """生成HTML折线图"""
        if not points:
            return '<div class="chart-empty">无数据</div>'
        
        width = 600
        height = 300
        padding = 40
        
        xs = [p.get("x", i) for i, p in enumerate(points)]
        ys = [p.get("y", 0) for p in points]
        
        if not ys:
            return '<div class="chart-empty">无数据</div>'
        
        min_y, max_y = min(ys), max(ys)
        range_y = max_y - min_y if max_y != min_y else 1
        
        step_x = (width - 2 * padding) / max(len(xs) - 1, 1)
        points_svg = []
        for i, (x, y) in enumerate(zip(xs, ys)):
            svg_x = padding + i * step_x
            svg_y = height - padding - ((y - min_y) / range_y * (height - 2 * padding))
            points_svg.append(f"{svg_x},{svg_y}")
        
        path_d = "M " + " L ".join(points_svg)
        grad_id = hash(title) % 10000
        
        html = f'<div class="chart-container">\n'
        if title:
            html += f'  <h3>{title}</h3>\n'
        
        html += f'''  <svg width="{width}" height="{height}" class="line-chart">
    <defs>
      <linearGradient id="grad-{grad_id}" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" style="stop-color:{color};stop-opacity:0.3" />
        <stop offset="100%" style="stop-color:{color};stop-opacity:0.05" />
      </linearGradient>
    </defs>
    <path d="{path_d}" fill="none" stroke="{color}" stroke-width="2" />
    <path d="{path_d} L {width-padding},{height-padding} L {padding},{height-padding} Z" 
          fill="url(#grad-{grad_id})" opacity="0.3" />
'''
        
        for i, (x, y) in enumerate(zip(xs, ys)):
            svg_x = padding + i * step_x
            svg_y = height - padding - ((y - min_y) / range_y * (height - 2 * padding))
            html += f'    <circle cx="{svg_x}" cy="{svg_y}" r="4" fill="{color}" />\n'
        
        html += '  </svg>\n'
        html += '</div>'
        
        return html


class BenchmarkVisualizer:
    """Benchmark可视化器（纯Python实现）"""
    
    def __init__(self, results: Dict[str, Any]):
        self.results = results
        self.text_chart = TextChart()
        self.html_chart = HtmlChart()
    
    def generate_text_report(self) -> str:
        """生成文本报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("Benchmark 可视化报告（纯文本模式）")
        lines.append("=" * 60)
        lines.append("")
        
        summary = self.results.get("summary", {})
        lines.append("【汇总】")
        lines.append(f"  总episodes: {summary.get('total_episodes', 0)}")
        lines.append(f"  平均utility: {summary.get('average_utility', 0):.4f}")
        acc = summary.get('average_accuracy')
        lines.append(f"  平均accuracy: {f'{acc:.4f}' if acc else 'N/A'}")
        lines.append(f"  趋势: {self.text_chart.trend_indicator(summary.get('utility_trend', 'unknown'))}")
        lines.append("")
        
        domains = self.results.get("domains", {})
        if domains:
            lines.append("【各域对比】")
            utility_data = {k: v.get("average_utility", 0) for k, v in domains.items()}
            lines.append(self.text_chart.bar_chart(utility_data, "平均Utility", width=30))
            lines.append("")
        
        return "\n".join(lines)
    
    def generate_html_report(self, output_path: Path) -> Path:
        """生成HTML报告"""
        html_content = self._build_html()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_content, encoding="utf-8")
        return output_path
    
    def _build_html(self) -> str:
        """构建HTML内容"""
        summary = self.results.get("summary", {})
        domains = self.results.get("domains", {})
        
        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Benchmark 报告 - {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        h3 {{ color: #555; margin-top: 30px; }}
        .summary-box {{ background: #f8f9fa; padding: 20px; border-radius: 6px; margin: 20px 0; }}
        .summary-item {{ display: inline-block; margin-right: 30px; }}
        .summary-value {{ font-size: 24px; font-weight: bold; color: #4CAF50; }}
        .summary-label {{ font-size: 14px; color: #666; }}
        .chart-container {{ margin: 20px 0; padding: 15px; background: #fafafa; border-radius: 6px; }}
        .bar-chart {{ display: flex; flex-direction: column; gap: 10px; }}
        .bar-row {{ display: flex; align-items: center; gap: 10px; }}
        .bar-label {{ width: 150px; text-align: right; font-weight: 500; }}
        .bar-wrapper {{ flex: 1; height: 30px; background: #e0e0e0; border-radius: 4px; overflow: hidden; }}
        .bar {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
        .bar-value {{ width: 80px; font-weight: 500; }}
        .badge {{ display: inline-block; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 500; }}
        .badge-improving {{ background: #e8f5e9; color: #2e7d32; }}
        .badge-degrading {{ background: #ffebee; color: #c62828; }}
        .badge-stable {{ background: #fff3e0; color: #ef6c00; }}
        .chart-empty {{ color: #999; font-style: italic; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e0e0e0; color: #999; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Benchmark 报告</h1>
        <p class="footer">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <div class="summary-box">
            <h3>汇总统计</h3>
            <div class="summary-item">
                <div class="summary-value">{summary.get('total_episodes', 0)}</div>
                <div class="summary-label">总Episodes</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{summary.get('average_utility', 0):.4f}</div>
                <div class="summary-label">平均Utility</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{f"{summary.get('average_accuracy', 0):.4f}" if summary.get('average_accuracy') else 'N/A'}</div>
                <div class="summary-label">平均Accuracy</div>
            </div>
            <div class="summary-item">
                <span class="badge badge-{summary.get('utility_trend', 'stable')}">{self._trend_text(summary.get('utility_trend', 'stable'))}</span>
                <div class="summary-label">趋势</div>
            </div>
        </div>
'''
        
        if domains:
            html += '        <h3>各域对比</h3>\n'
            for domain_name, domain_data in domains.items():
                html += f'        <div class="chart-container">\n'
                html += f'          <h4>{domain_name}</h4>\n'
                
                utility_data = {
                    "utility": domain_data.get("average_utility", 0),
                    "baseline": domain_data.get("baseline_utility", 0)
                }
                html += self.html_chart.render_bar_chart(
                    utility_data, 
                    f"{domain_name} - Utility对比",
                    color="#4CAF50"
                )
                html += '        </div>\n'
        
        html += '''
        <div class="footer">
            <p>本报告由 unclekk-metacog-self-evolve 生成 | 纯Python实现，无matplotlib依赖</p>
        </div>
    </div>
</body>
</html>
'''
        
        return html
    
    def _trend_text(self, trend: str) -> str:
        """趋势文本"""
        return {
            "improving": "↑ 改善",
            "degrading": "↓ 退化",
            "stable": "→ 稳定",
            "unknown": "？ 未知"
        }.get(trend, trend)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True, help="输入JSON文件")
    parser.add_argument("--output", "-o", required=True, help="输出目录")
    parser.add_argument("--text-only", action="store_true", help="仅生成文本报告")
    args = parser.parse_args()
    
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] 文件不存在: {args.input}")
        exit(1)
    
    with open(input_path, 'r', encoding='utf-8') as f:
        results = json.load(f)
    
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    text_report = BenchmarkVisualizer(results).generate_text_report()
    text_path = output_dir / "report.txt"
    text_path.write_text(text_report, encoding="utf-8")
    print(f"[OK] 文本报告: {text_path}")
    
    if not args.text_only:
        html_path = output_dir / "report.html"
        BenchmarkVisualizer(results).generate_html_report(html_path)
        print(f"[OK] HTML报告: {html_path}")
    
    print("\n[INFO] 可视化完成（纯Python实现，无matplotlib依赖）")
