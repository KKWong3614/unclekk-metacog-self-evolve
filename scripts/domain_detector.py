#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# P2-2: 领域自动检测机制
# 实现基于内容的领域自动分类
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

from domains import DOMAIN_TEMPLATES

class DomainDetector:
    """领域自动检测器"""
    
    # 领域关键词映射
    DOMAIN_KEYWORDS = {
        "code_review": [
            "function", "class", "method", "variable", "bug", "error",
            "syntax", "compile", "test", "lint", "refactor", "logic",
            "代码", "函数", "类", "方法", "变量", "bug", "错误",
            "语法", "编译", "测试", "重构", "逻辑"
        ],
        "paper_review": [
            "abstract", "introduction", "method", "result", "conclusion",
            "citation", "reference", "hypothesis", "experiment", "data",
            "论文", "摘要", "引言", "方法", "结果", "结论",
            "引用", "假设", "实验", "数据"
        ],
        "document_editing": [
            "grammar", "spelling", "style", "format", "paragraph",
            "sentence", "word", "edit", "revise", "proofread",
            "语法", "拼写", "风格", "格式", "段落",
            "句子", "编辑", "修订", "校对"
        ]
    }
    
    def __init__(self):
        self.keywords = self._build_keyword_index()
    
    def _build_keyword_index(self) -> Dict[str, Dict[str, int]]:
        """构建关键词索引"""
        index = {}
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            keyword_count = {}
            for kw in keywords:
                keyword_count[kw.lower()] = keyword_count.get(kw.lower(), 0) + 1
            index[domain] = keyword_count
        return index
    
    def detect_domain(self, content: str, top_n: int = 3) -> List[Dict[str, Any]]:
        """检测内容所属领域"""
        if not content:
            return []
        
        # 预处理
        content_lower = content.lower()
        words = re.findall(r'\w+', content_lower)
        
        # 计算每个领域的匹配分数
        scores = {}
        for domain, keyword_count in self.keywords.items():
            score = 0
            matched_keywords = []
            for word in words:
                if word in keyword_count:
                    score += keyword_count[word]
                    matched_keywords.append(word)
            if score > 0:
                scores[domain] = {
                    "score": score,
                    "matched_keywords": list(set(matched_keywords)),
                    "density": score / max(len(words), 1)
                }
        
        # 排序
        sorted_domains = sorted(
            scores.items(),
            key=lambda x: (x[1]["score"], x[1]["density"]),
            reverse=True
        )
        
        # 返回top_n
        return [
            {"domain": domain, **info}
            for domain, info in sorted_domains[:top_n]
        ]
    
    def suggest_domain(self, content: str) -> Optional[str]:
        """建议最合适的领域"""
        detections = self.detect_domain(content, top_n=1)
        if detections and detections[0]["score"] > 0:
            return detections[0]["domain"]
        return None
    
    def get_domain_templates(self) -> Dict[str, Any]:
        """获取领域模板"""
        return DOMAIN_TEMPLATES


def cmd_detect_domain(args):
    """检测领域命令"""
    detector = DomainDetector()
    
    # 读取内容
    content = ""
    if args.file:
        content_path = Path(args.file)
        if content_path.exists():
            content = content_path.read_text(encoding="utf-8")
        else:
            print(f"[ERROR] 文件不存在: {args.file}")
            return 2
    elif args.text:
        content = args.text
    else:
        # 从stdin读取
        import sys
        content = sys.stdin.read()
    
    if not content.strip():
        print("[WARN] 内容为空，无法检测领域")
        return 1
    
    # 检测
    detections = detector.detect_domain(content)
    
    if not detections:
        print("[INFO] 未检测到匹配的领域")
        print("[INFO] 建议手动选择领域模板")
        return 0
    
    # 输出结果
    print(f"\n[DETECT] 检测到{len(detections)}个可能领域:")
    for i, det in enumerate(detections, 1):
        print(f"  {i}. {det['domain']}:")
        print(f"     分数: {det['score']}")
        print(f"     密度: {det['density']:.2%}")
        print(f"     匹配词: {', '.join(det['matched_keywords'][:5])}")
    
    # 建议
    best = detections[0]
    if best["score"] > 0:
        print(f"\n[RECOMMEND] 建议使用领域: {best['domain']}")
    
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", "-f", help="输入文件")
    parser.add_argument("--text", "-t", help="输入文本")
    args = parser.parse_args()
    exit(cmd_detect_domain(args))
