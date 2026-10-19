#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# P2-1: 元认知自动优化机制
# 实现基于日志的模式识别和自动规则优化
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

from metacog import Store, append_jsonl, read_jsonl, write_json, read_json

class MetaCognitiveOptimizer:
    """元认知自动优化器"""
    
    def __init__(self, store: Store):
        self.store = store
        self.log_path = store.meta_log if store.meta_log else Path(".metacog/ledger/meta-cognition.log")
        self.optimization_rules = self._load_optimization_rules()
    
    def _load_optimization_rules(self) -> Dict[str, Any]:
        """加载优化规则"""
        rules_path = Path(__file__).parent.parent / "references" / "optimization-rules.json"
        if rules_path.exists():
            try:
                return read_json(rules_path, {})
            except Exception:
                pass
        return self._default_rules()
    
    def _default_rules(self) -> Dict[str, Any]:
        """默认优化规则"""
        return {
            "patterns": {
                "frequent_revert": {
                    "description": "频繁回滚模式",
                    "condition": "recent_reverts > 3",
                    "action": "suggest_rule_removal",
                    "weight": 0.8
                },
                "low_utility_trend": {
                    "description": "效用下降趋势",
                    "condition": "utility_trend == 'degrading'",
                    "action": "suggest_rule_review",
                    "weight": 0.7
                },
                "high_violation_rate": {
                    "description": "高违规率",
                    "condition": "violation_rate > 0.3",
                    "action": "suggest_stricter_rules",
                    "weight": 0.9
                },
                "stable_high_utility": {
                    "description": "稳定高效用",
                    "condition": "utility_trend == 'improving' and utility > 0.8",
                    "action": "suggest_rule_promotion",
                    "weight": 0.6
                }
            },
            "actions": {
                "suggest_rule_removal": {
                    "description": "建议移除低效规则",
                    "threshold": 0.5
                },
                "suggest_rule_review": {
                    "description": "建议审查规则",
                    "priority": "high"
                },
                "suggest_stricter_rules": {
                    "description": "建议添加更严格规则",
                    "category": "safety"
                },
                "suggest_rule_promotion": {
                    "description": "建议推广高效规则",
                    "priority": "low"
                }
            }
        }
    
    def analyze_patterns(self, days: int = 7) -> Dict[str, Any]:
        """分析日志中的模式"""
        entries = read_jsonl(self.log_path)
        if not entries:
            return {"patterns": [], "insights": [], "summary": {"total_entries": 0, "promotes": 0, "reverts": 0, "m1_triggers": 0}}
        
        # 过滤时间范围
        cutoff = datetime.now().replace(tzinfo=None) - timedelta(days=days)
        recent_entries = []
        for e in entries:
            ts_str = e.get("timestamp", "")
            if "Z" in ts_str:
                ts_str = ts_str.replace("Z", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
                if ts > cutoff:
                    recent_entries.append(e)
            except (ValueError, TypeError):
                continue
        
        patterns = []
        insights = []
        
        # 分析回滚模式
        reverts = [e for e in recent_entries if e.get("event_type") == "rule_reverted"]
        if len(reverts) > 3:
            patterns.append({
                "type": "frequent_revert",
                "count": len(reverts),
                "severity": "high"
            })
            insights.append(f"检测到频繁回滚模式：最近{days}天内回滚{len(reverts)}次")
        
        # 分析效用趋势
        promotes = [e for e in recent_entries if e.get("event_type") == "rule_promoted"]
        if len(promotes) > len(reverts) * 2:
            patterns.append({
                "type": "stable_high_utility",
                "promotes": len(promotes),
                "reverts": len(reverts),
                "ratio": len(promotes) / max(len(reverts), 1)
            })
            insights.append("检测到稳定高效用模式：PROMOTE/REVERT比例良好")
        
        return {
            "patterns": patterns,
            "insights": insights,
            "summary": {
                "total_entries": len(recent_entries),
                "promotes": len([e for e in recent_entries if e.get("event_type") == "rule_promoted"]),
                "reverts": len([e for e in recent_entries if e.get("event_type") == "rule_reverted"]),
                "m1_triggers": len([e for e in recent_entries if e.get("event_type") == "m1_auto_trigger"])
            }
        }
    
    def generate_optimization_proposals(self) -> List[Dict[str, Any]]:
        """生成优化提案"""
        analysis = self.analyze_patterns()
        proposals = []
        
        for pattern in analysis.get("patterns", []):
            pattern_type = pattern.get("type")
            if pattern_type in self.optimization_rules.get("patterns", {}):
                rule = self.optimization_rules["patterns"][pattern_type]
                action = rule.get("action")
                if action in self.optimization_rules.get("actions", {}):
                    action_config = self.optimization_rules["actions"][action]
                    proposals.append({
                        "pattern": pattern_type,
                        "action": action,
                        "description": action_config.get("description", ""),
                        "priority": action_config.get("priority", "medium"),
                        "evidence": pattern
                    })
        
        return proposals
    
    def auto_optimize(self, dry_run: bool = True) -> Dict[str, Any]:
        """自动优化（dry_run模式默认）"""
        proposals = self.generate_optimization_proposals()
        
        if not proposals:
            return {
                "status": "no_changes",
                "message": "未发现需要优化的模式",
                "proposals": []
            }
        
        # 按优先级排序
        priority_order = {"high": 0, "medium": 1, "low": 2}
        proposals.sort(key=lambda x: priority_order.get(x.get("priority", "medium"), 1))
        
        return {
            "status": "proposals_generated",
            "message": f"发现{len(proposals)}个优化提案",
            "proposals": proposals,
            "dry_run": dry_run
        }
    
    def apply_proposal(self, proposal_id: str) -> bool:
        """应用单个优化提案"""
        # 实际应用中会修改规则或配置
        # 这里先返回成功（模拟）
        return True


def cmd_optimize(args):
    """优化命令"""
    st = Store(Path(args.root))
    optimizer = MetaCognitiveOptimizer(st)
    
    if args.dry_run:
        result = optimizer.auto_optimize(dry_run=True)
        print(f"\n[OPTIMIZE] 分析结果（dry-run模式）:")
        print(f"  状态: {result['status']}")
        print(f"  消息: {result['message']}")
        if result.get('proposals'):
            print(f"  发现{len(result['proposals'])}个优化提案:")
            for i, prop in enumerate(result['proposals'], 1):
                print(f"    {i}. [{prop.get('priority', 'medium').upper()}] {prop.get('description', '')}")
    else:
        result = optimizer.auto_optimize(dry_run=False)
        print(f"\n[OPTIMIZE] 分析结果:")
        print(f"  状态: {result['status']}")
        print(f"  消息: {result['message']}")
        if result.get('proposals'):
            print(f"  发现{len(result['proposals'])}个优化提案:")
            for i, prop in enumerate(result['proposals'], 1):
                print(f"    {i}. [{prop.get('priority', 'medium').upper()}] {prop.get('description', '')}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".metacog")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true", dest="apply")
    args = parser.parse_args()
    cmd_optimize(args)
