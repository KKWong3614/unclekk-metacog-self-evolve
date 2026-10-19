#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# P2-1 测试：验证元认知自动优化
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from metacog import Store, cmd_init, cmd_episode, cmd_propose, cmd_gate, cmd_apply, cmd_verdict

def test_meta_optimizer_basic():
    """测试元认知优化器基础功能"""
    tmp = Path(tempfile.mkdtemp(prefix="metacog_p2_1_"))
    metacog_dir = tmp / ".metacog"
    
    try:
        # 初始化
        st = Store(metacog_dir)
        class FakeArgs:
            pass
        cmd_init(st, FakeArgs())
        
        # 导入优化器
        from meta_optimizer import MetaCognitiveOptimizer
        optimizer = MetaCognitiveOptimizer(st)
        
        # 测试模式分析
        analysis = optimizer.analyze_patterns(days=7)
        assert "patterns" in analysis
        assert "insights" in analysis
        assert "summary" in analysis
        
        # 测试提案生成
        proposals = optimizer.generate_optimization_proposals()
        assert isinstance(proposals, list)
        
        # 测试自动优化（dry-run）
        result = optimizer.auto_optimize(dry_run=True)
        assert "status" in result
        assert "message" in result
        
        print("✅ test_meta_optimizer_basic PASS")
        return True
    except Exception as e:
        print(f"❌ test_meta_optimizer_basic FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_meta_optimizer_with_log():
    """测试带日志的优化器"""
    tmp = Path(tempfile.mkdtemp(prefix="metacog_p2_1b_"))
    metacog_dir = tmp / ".metacog"
    
    try:
        # 初始化
        st = Store(metacog_dir)
        class FakeArgs:
            pass
        cmd_init(st, FakeArgs())
        
        # 导入优化器
        from meta_optimizer import MetaCognitiveOptimizer
        optimizer = MetaCognitiveOptimizer(st)
        
        # 写入一些模拟日志
        log_path = st.meta_log
        if log_path:
            from metacog import append_jsonl
            append_jsonl(log_path, {
                "timestamp": (datetime.now() - timedelta(hours=4)).isoformat(),
                "event_type": "rule_reverted",
                "context": {"rule_id": "R-001"},
                "analysis": "rule violated safety",
                "action": "revert",
                "insight": "need stricter rules"
            })
            append_jsonl(log_path, {
                "timestamp": (datetime.now() - timedelta(hours=3)).isoformat(),
                "event_type": "rule_reverted",
                "context": {"rule_id": "R-002"},
                "analysis": "rule caused error",
                "action": "revert",
                "insight": "rule is buggy"
            })
            append_jsonl(log_path, {
                "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(),
                "event_type": "rule_reverted",
                "context": {"rule_id": "R-003"},
                "analysis": "rule failed test",
                "action": "revert",
                "insight": "rule needs fix"
            })
            append_jsonl(log_path, {
                "timestamp": (datetime.now() - timedelta(hours=1)).isoformat(),
                "event_type": "rule_reverted",
                "context": {"rule_id": "R-004"},
                "analysis": "rule broken",
                "action": "revert",
                "insight": "systematic issue"
            })
        
        # 测试模式分析（应检测到频繁回滚）
        analysis = optimizer.analyze_patterns(days=7)
        patterns = analysis.get("patterns", [])
        
        # 应该检测到频繁回滚模式
        frequent_revert = [p for p in patterns if p.get("type") == "frequent_revert"]
        assert len(frequent_revert) > 0, "应检测到频繁回滚模式"
        assert frequent_revert[0]["count"] >= 3
        
        # 测试提案生成
        proposals = optimizer.generate_optimization_proposals()
        assert len(proposals) > 0, "应生成优化提案"
        
        # 测试自动优化
        result = optimizer.auto_optimize(dry_run=False)
        assert result["status"] == "proposals_generated"
        assert len(result["proposals"]) > 0
        
        print("✅ test_meta_optimizer_with_log PASS")
        return True
    except Exception as e:
        print(f"❌ test_meta_optimizer_with_log FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_optimize_command():
    """测试optimize命令"""
    tmp = Path(tempfile.mkdtemp(prefix="metacog_p2_1c_"))
    metacog_dir = tmp / ".metacog"
    
    try:
        # 初始化
        st = Store(metacog_dir)
        class FakeArgs:
            pass
        cmd_init(st, FakeArgs())
        
        # 测试命令
        import io
        from contextlib import redirect_stdout
        
        f = io.StringIO()
        with redirect_stdout(f):
            class OptimizeArgs:
                root = str(metacog_dir)
                dry_run = True
                apply = False
            from meta_optimizer import cmd_optimize
            cmd_optimize(OptimizeArgs())
        
        output = f.getvalue()
        assert "OPTIMIZE" in output or "分析" in output
        
        print("✅ test_optimize_command PASS")
        return True
    except Exception as e:
        print(f"❌ test_optimize_command FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    results = []
    results.append(test_meta_optimizer_basic())
    results.append(test_meta_optimizer_with_log())
    results.append(test_optimize_command())
    
    passed = sum(results)
    total = len(results)
    
    print(f"\n{'='*70}")
    print(f"P2-1 测试结果: {passed}/{total} PASS")
    print(f"{'='*70}\n")
    
    sys.exit(0 if passed == total else 1)
