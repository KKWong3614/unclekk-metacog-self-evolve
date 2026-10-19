#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# P0-2 测试：验证领域间知识迁移
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from domains.knowledge_transfer import KnowledgeTransfer, get_knowledge_transfer, init_knowledge_transfer
from domains import DOMAIN_TEMPLATES


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def add(self, name, ok, detail=""):
        self.passed += ok
        self.failed += (not ok)
        print("  [{}] {}{}".format("PASS" if ok else "FAIL", name,
                                    (" - " + detail) if detail else ""))


def test_knowledge_extraction():
    """测试知识提取"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_kt_extract_"))
    
    try:
        kt = init_knowledge_transfer(tmp)
        
        # 提取代码评审规则
        rules = kt.extract_rules("code_review")
        
        t.add("提取到规则", len(rules) > 0)
        t.add("规则含source_domain", all(r.get("source_domain") == "code_review" for r in rules))
        t.add("规则含transferable标记", all(r.get("transferable") == True for r in rules))
        
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    
    return t


def test_cross_domain_transfer():
    """测试跨领域迁移"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_kt_transfer_"))
    
    try:
        kt = init_knowledge_transfer(tmp)
        
        # 从代码评审迁移到论文评审
        result = kt.transfer_to_domain("code_review", "paper_review")
        
        t.add("迁移成功", result.get("status") == "success")
        t.add("有规则迁移", result.get("rules_transferred", 0) > 0)
        t.add("源领域正确", result.get("source_domain") == "code_review")
        t.add("目标领域正确", result.get("target_domain") == "paper_review")
        
        # 验证知识base已保存
        kb_path = tmp / "references" / "knowledge-base.json"
        t.add("知识base已保存", kb_path.exists())
        
        if kb_path.exists():
            with open(kb_path, 'r', encoding='utf-8') as f:
                kb = json.load(f)
            t.add("迁移历史已记录", "transfer_history" in kb)
            t.add("共享规则已记录", len(kb.get("shared_rules", {})) > 0)
        
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    
    return t


def test_pattern_detection():
    """测试模式检测"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_kt_pattern_"))
    
    try:
        kt = init_knowledge_transfer(tmp)
        
        # 添加一些规则到知识base
        kt.knowledge_base_data["shared_rules"]["test_domain"] = [
            {"id": "R-001", "content": "命名规范：函数名使用蛇形命名", "source_domain": "test"},
            {"id": "R-002", "content": "错误处理：所有外部调用必须包含异常处理", "source_domain": "test"},
            {"id": "R-003", "content": "安全检查：用户输入必须经过验证", "source_domain": "test"},
        ]
        
        # 获取跨领域模式
        patterns = kt.get_cross_domain_patterns()
        
        t.add("检测到模式", len(patterns) > 0)
        t.add("命名模式存在", "naming_convention" in patterns)
        t.add("错误处理模式存在", "error_handling" in patterns)
        t.add("安全检查模式存在", "security_check" in patterns)
        
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    
    return t


def test_knowledge_export():
    """测试知识导出"""
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_kt_export_"))
    
    try:
        kt = init_knowledge_transfer(tmp)
        
        # 导出知识
        output_path = tmp / "exported_knowledge.json"
        knowledge = kt.export_knowledge("code_review", output_path)
        
        t.add("导出成功", output_path.exists())
        t.add("含domain字段", knowledge.get("domain") == "code_review")
        t.add("含extracted_at时间戳", "extracted_at" in knowledge)
        t.add("含shared_rules", "shared_rules" in knowledge)
        t.add("含patterns", "patterns" in knowledge)
        
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    
    return t


if __name__ == "__main__":
    print("=" * 70)
    print("P0-2 测试：领域间知识迁移验证")
    print("=" * 70)
    
    total_passed = 0
    total_failed = 0
    
    tests = [
        ("知识提取", test_knowledge_extraction),
        ("跨领域迁移", test_cross_domain_transfer),
        ("模式检测", test_pattern_detection),
        ("知识导出", test_knowledge_export),
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
        print("✅ P0-2 测试通过")
    else:
        print(f"❌ {total_failed}项未通过")
    print("=" * 70)
    
    sys.exit(0 if total_failed == 0 else 1)
