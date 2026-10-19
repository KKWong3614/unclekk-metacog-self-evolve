#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Phase 2.2 跨领域知识迁移接口
# P0-2 修复：实现领域间知识共享机制
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from domains import DOMAIN_TEMPLATES


class KnowledgeTransfer:
    """领域间知识迁移管理器"""
    
    def __init__(self, skill_root: Path):
        self.skill_root = skill_root
        self.knowledge_base = skill_root / "references" / "knowledge-base.json"
        self._load_knowledge_base()
    
    def _load_knowledge_base(self):
        """加载知识 base"""
        if self.knowledge_base.exists():
            with open(self.knowledge_base, 'r', encoding='utf-8') as f:
                self.knowledge_base_data = json.load(f)
        else:
            self.knowledge_base_data = {
                "shared_rules": {},
                "cross_domain_patterns": {},
                "best_practices": {},
                "created_at": None,
                "updated_at": None
            }
    
    def _save_knowledge_base(self):
        """保存知识 base"""
        self.knowledge_base.parent.mkdir(parents=True, exist_ok=True)
        with open(self.knowledge_base, 'w', encoding='utf-8') as f:
            json.dump(self.knowledge_base_data, f, indent=2, ensure_ascii=False)
    
    def extract_rules(self, source_domain: str) -> List[Dict]:
        """从源领域提取可迁移规则"""
        template = DOMAIN_TEMPLATES.get(source_domain)
        if not template:
            return []
        
        # 提取A2规则中的通用模式
        transferable_rules = []
        for rule in template.get("A2_rules", []):
            content = rule.get("content", "")
            # 判断是否为通用规则（非领域特定）
            if self._is_transferable(content):
                transferable_rules.append({
                    "id": rule["id"],
                    "content": content,
                    "source_domain": source_domain,
                    "transferable": True
                })
        
        return transferable_rules
    
    def _is_transferable(self, content: str) -> bool:
        """判断规则是否可跨领域迁移"""
        # 领域特定关键词（不可迁移）
        domain_specific = [
            "SQL", "注入", "XSS", "CSRF",  # 代码安全
            "论文", "评审", "引用", "实验",  # 论文评审
            "格式", "排版", "图表"  # 文档编辑
        ]
        
        # 通用关键词（可迁移）
        universal = [
            "命名", "规范", "错误处理", "异常",
            "安全检查", "输入验证", "参数化",
            "可维护性", "可读性", "最佳实践"
        ]
        
        # 检查是否包含领域特定关键词
        for keyword in domain_specific:
            if keyword in content:
                return False
        
        # 检查是否包含通用关键词
        for keyword in universal:
            if keyword in content:
                return True
        
        return False
    
    def transfer_to_domain(self, source_domain: str, target_domain: str) -> Dict:
        """迁移知识到目标领域"""
        if target_domain not in DOMAIN_TEMPLATES:
            return {"error": f"未知领域: {target_domain}"}
        
        # 提取源领域规则
        source_rules = self.extract_rules(source_domain)
        
        # 获取目标领域现有规则
        target_template = DOMAIN_TEMPLATES[target_domain]
        existing_rules = {rule["id"]: rule["content"] for rule in target_template.get("A2_rules", [])}
        
        # 合并规则（去重）
        transferred = []
        for rule in source_rules:
            # 检查是否已存在
            rule_content = rule["content"]
            if rule_content not in existing_rules.values():
                transferred.append(rule)
                existing_rules[f"R-NEW-{len(transferred):03d}"] = rule_content
        
        # 更新知识 base
        if source_domain not in self.knowledge_base_data["shared_rules"]:
            self.knowledge_base_data["shared_rules"][source_domain] = []
        self.knowledge_base_data["shared_rules"][source_domain] = source_rules
        
        if target_domain not in self.knowledge_base_data["shared_rules"]:
            self.knowledge_base_data["shared_rules"][target_domain] = []
        self.knowledge_base_data["shared_rules"][target_domain].extend(transferred)
        
        # 记录迁移历史
        if "transfer_history" not in self.knowledge_base_data:
            self.knowledge_base_data["transfer_history"] = []
        self.knowledge_base_data["transfer_history"].append({
            "timestamp": str(__import__('datetime').datetime.now()),
            "from": source_domain,
            "to": target_domain,
            "rules_transferred": len(transferred)
        })
        
        self._save_knowledge_base()
        
        return {
            "source_domain": source_domain,
            "target_domain": target_domain,
            "rules_extracted": len(source_rules),
            "rules_transferred": len(transferred),
            "status": "success"
        }
    
    def get_cross_domain_patterns(self) -> Dict:
        """获取跨领域模式"""
        patterns = {}
        for domain, rules in self.knowledge_base_data.get("shared_rules", {}).items():
            for rule in rules:
                pattern = self._extract_pattern(rule["content"])
                if pattern:
                    if pattern not in patterns:
                        patterns[pattern] = []
                    patterns[pattern].append({
                        "domain": domain,
                        "rule_id": rule["id"],
                        "content": rule["content"]
                    })
        return patterns
    
    def _extract_pattern(self, content: str) -> Optional[str]:
        """提取通用模式"""
        if "命名" in content and "规范" in content:
            return "naming_convention"
        elif "错误" in content and "处理" in content:
            return "error_handling"
        elif "安全" in content and "检查" in content:
            return "security_check"
        elif "输入" in content and "验证" in content:
            return "input_validation"
        return None
    
    def export_knowledge(self, domain: str, output_path: Path) -> Dict:
        """导出领域知识"""
        knowledge = {
            "domain": domain,
            "extracted_at": str(__import__('datetime').datetime.now()),
            "shared_rules": self.knowledge_base_data.get("shared_rules", {}).get(domain, []),
            "patterns": self.get_cross_domain_patterns()
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(knowledge, f, indent=2, ensure_ascii=False)
        
        return knowledge


# 全局实例
_knowledge_transfer = None


def get_knowledge_transfer(skill_root: Path) -> KnowledgeTransfer:
    """获取知识迁移管理器单例"""
    global _knowledge_transfer
    if _knowledge_transfer is None:
        _knowledge_transfer = KnowledgeTransfer(skill_root)
    return _knowledge_transfer


def init_knowledge_transfer(skill_root: Path):
    """初始化知识迁移管理器"""
    global _knowledge_transfer
    _knowledge_transfer = KnowledgeTransfer(skill_root)
    return _knowledge_transfer
