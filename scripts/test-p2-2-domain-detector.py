#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# P2-2 测试：验证领域自动检测
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from metacog import Store, cmd_init

def test_domain_detector_basic():
    """测试领域检测器基础功能"""
    try:
        from domain_detector import DomainDetector
        
        detector = DomainDetector()
        
        # 测试代码评审检测
        code_content = """
def calculate_total(prices):
    total = 0
    for price in prices:
        total += price
    return total

# Bug: 没有处理空列表
def test_calculate():
    assert calculate_total([]) == 0
"""
        detections = detector.detect_domain(code_content)
        assert len(detections) > 0
        assert detections[0]["domain"] == "code_review"
        assert detections[0]["score"] > 0
        
        # 测试论文评审检测
        paper_content = """
Abstract: This paper presents a novel approach to...
Introduction: The problem of machine learning has been...
Method: We propose a new algorithm called...
Result: Our experiments show that...
Conclusion: In conclusion, we demonstrate...
"""
        detections = detector.detect_domain(paper_content)
        assert len(detections) > 0
        assert detections[0]["domain"] == "paper_review"
        assert detections[0]["score"] > 0
        
        # 测试文档编辑检测
        doc_content = """
The quick brown fox jumps over the lazy dog.
Grammar and spelling are important for clear communication.
Please review the paragraph structure and style.
"""
        detections = detector.detect_domain(doc_content)
        assert len(detections) > 0
        assert detections[0]["domain"] == "document_editing"
        assert detections[0]["score"] > 0
        
        print("✅ test_domain_detector_basic PASS")
        return True
    except Exception as e:
        print(f"❌ test_domain_detector_basic FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_domain_detector_mixed():
    """测试混合内容检测"""
    try:
        from domain_detector import DomainDetector
        
        detector = DomainDetector()
        
        # 混合内容（代码+论文）
        mixed_content = """
def train_model(data):
    # 这是代码部分
    model = NeuralNetwork()
    model.fit(data)
    return model

Abstract: This paper presents a novel neural network architecture...
Method: We propose a new training algorithm...
"""
        detections = detector.detect_domain(mixed_content, top_n=2)
        assert len(detections) >= 2
        
        # 第一个应该是code_review或paper_review
        top_domains = [d["domain"] for d in detections[:2]]
        assert "code_review" in top_domains or "paper_review" in top_domains
        
        print("✅ test_domain_detector_mixed PASS")
        return True
    except Exception as e:
        print(f"❌ test_domain_detector_mixed FAIL: {e}")
        return False


def test_domain_detector_empty():
    """测试空内容检测"""
    try:
        from domain_detector import DomainDetector
        
        detector = DomainDetector()
        
        # 空内容
        detections = detector.detect_domain("")
        assert detections == []
        
        # 纯空白
        detections = detector.detect_domain("   \n\t  ")
        assert detections == []
        
        # 无匹配词
        detections = detector.detect_domain("This is just random text without any domain keywords.")
        # 可能匹配也可能不匹配，但不应崩溃
        assert isinstance(detections, list)
        
        print("✅ test_domain_detector_empty PASS")
        return True
    except Exception as e:
        print(f"❌ test_domain_detector_empty FAIL: {e}")
        return False


def test_suggest_domain():
    """测试领域建议"""
    try:
        from domain_detector import DomainDetector
        
        detector = DomainDetector()
        
        # 明确的代码内容
        code = "def foo(): pass  # This is code"
        suggested = detector.suggest_domain(code)
        # 可能返回code_review或None（取决于匹配阈值）
        assert suggested is None or suggested == "code_review"
        
        # 明确的论文内容
        paper = "Abstract: This paper presents..."
        suggested = detector.suggest_domain(paper)
        assert suggested is None or suggested == "paper_review"
        
        # 不确定的内容
        unclear = "This is just some text."
        suggested = detector.suggest_domain(unclear)
        # 可能返回None
        assert suggested is None
        
        print("✅ test_suggest_domain PASS")
        return True
    except Exception as e:
        print(f"❌ test_suggest_domain FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_domain_templates():
    """测试领域模板获取"""
    try:
        from domain_detector import DomainDetector
        
        detector = DomainDetector()
        templates = detector.get_domain_templates()
        
        assert isinstance(templates, dict)
        assert "code_review" in templates
        assert "paper_review" in templates
        assert "document_editing" in templates
        
        for domain_name, template in templates.items():
            assert "name" in template
            assert "A1" in template
            assert "A2_rules" in template
        
        print("✅ test_domain_templates PASS")
        return True
    except Exception as e:
        print(f"❌ test_domain_templates FAIL: {e}")
        return False


if __name__ == "__main__":
    results = []
    results.append(test_domain_detector_basic())
    results.append(test_domain_detector_mixed())
    results.append(test_domain_detector_empty())
    results.append(test_suggest_domain())
    results.append(test_domain_templates())
    
    passed = sum(results)
    total = len(results)
    
    print(f"\n{'='*70}")
    print(f"P2-2 测试结果: {passed}/{total} PASS")
    print(f"{'='*70}\n")
    
    sys.exit(0 if passed == total else 1)
