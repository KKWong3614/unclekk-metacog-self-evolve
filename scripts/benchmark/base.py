#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Phase 3.1 Benchmark 基类（仅标准库）
# 框架用于「模拟」多领域自改进效果，不调用真实 LLM（符合 skill 零第三方依赖约束）。
import json
import random
import sys
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

# 自举：确保 scripts/ 在 sys.path，使 `from benchmark.xxx` 在直接运行脚本时也能解析
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class BaseBenchmark(ABC):
    """Benchmark 基类：setup → run_episode → evaluate → generate_report"""

    def __init__(self, domain: str, output_dir: Path):
        self.domain = domain
        self.output_dir = Path(output_dir)
        self.results = []
        self.start_time = None
        self.end_time = None

    @abstractmethod
    def setup(self):
        pass

    @abstractmethod
    def run_episode(self, episode_num: int) -> dict:
        pass

    @abstractmethod
    def evaluate(self, episode_result: dict) -> dict:
        pass

    @abstractmethod
    def generate_report(self) -> dict:
        pass

    def run(self, episode_count: int = 100):
        self.start_time = datetime.now()
        self.setup()
        for i in range(1, episode_count + 1):
            episode_result = self.run_episode(i)
            evaluation = self.evaluate(episode_result)
            self.results.append({
                "episode": i,
                "timestamp": datetime.now().isoformat(),
                "episode_result": episode_result,
                "evaluation": evaluation,
            })
            if i % 10 == 0:
                print("  进度: {}/{}".format(i, episode_count))
        self.end_time = datetime.now()
        return self.generate_report()

    def save_results(self):
        results_dir = self.output_dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        filename = "benchmark-{}-{}.json".format(
            self.domain, datetime.now().strftime("%Y%m%d-%H%M%S"))
        filepath = results_dir / filename
        payload = {
            "domain": self.domain,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": (self.end_time - self.start_time).total_seconds()
            if self.start_time and self.end_time else 0,
            "episode_count": len(self.results),
            "results": self.results,
        }
        filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return filepath

    @staticmethod
    def calculate_trend(data: list) -> str:
        if len(data) < 2:
            return "insufficient_data"
        half = len(data) // 2
        first_half = sum(data[:half]) / max(half, 1)
        second_half = sum(data[half:]) / max(len(data) - half, 1)
        if second_half > first_half * 1.05:
            return "improving"
        elif second_half < first_half * 0.95:
            return "degrading"
        return "stable"
