#!/usr/bin/env python3
# 性能基准测试框架
# 用于验证 metacog 引擎在不同场景下的实际效用

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone

# 清除 uv 环境变量
os.environ.pop('PYTHONHOME', None)
os.environ.pop('PYTHONPATH', None)

MC_PATH = Path(__file__).resolve().parent / "metacog.py"

def run_cmd(cmd, cwd=None):
    """运行命令并返回结果"""
    import subprocess
    env = {**os.environ, 'PYTHONHOME': '', 'PYTHONPATH': ''}
    result = subprocess.run([sys.executable, str(MC_PATH)] + cmd, 
                           cwd=cwd, capture_output=True, text=True, env=env)
    return result.returncode, result.stdout, result.stderr

def test_basic_evolution(tmpdir):
    """测试基础演化能力"""
    print("\n【测试1: 基础演化能力】")
    
    # 初始化
    rc, out, err = run_cmd(["init"], cwd=tmpdir)
    assert rc == 0, f"init失败: {err}"
    
    # 记录5个episode建立基线
    utilities = [0.5, 0.6, 0.55, 0.65, 0.7]
    for i, u in enumerate(utilities, 1):
        rc, out, err = run_cmd(["episode", "--task", f"任务{i}", 
                               "--utility", str(u), "--violations", "0"], 
                              cwd=tmpdir)
        assert rc == 0, f"episode {i} 失败"
    
    # 查询状态
    rc, out, err = run_cmd(["status"], cwd=tmpdir)
    assert rc == 0, "status失败"
    assert "基线" in out, "基线未建立"
    
    print(f"  ✅ 基线建立成功")
    return True

def test_rule_evolution(tmpdir):
    """测试规则演化能力"""
    print("\n【测试2: 规则演化能力】")
    
    # 记录2个episode作为证据
    for i in range(2):
        rc, out, err = run_cmd(["episode", "--task", f"任务{i+1}",
                               "--utility", "0.6", "--violations", "0"],
                              cwd=tmpdir)
    
    # 提议新规则
    rc, out, err = run_cmd(["propose", "--artifact", "A2", "--op", "add",
                           "--content", "- 新增规则：测试规则演化",
                           "--reason", "测试证据",
                           "--episode", "E-001", "--episode", "E-002"],
                          cwd=tmpdir)
    assert rc == 0, "propose失败"
    
    # 过闸
    rc, out, err = run_cmd(["gate"], cwd=tmpdir)
    assert rc == 0, "gate失败"
    
    # 应用
    rc, out, err = run_cmd(["apply", "--human-ok"], cwd=tmpdir)
    assert rc == 0, "apply失败"
    
    print(f"  ✅ 规则演化成功")
    return True

def test_safety_guards(tmpdir):
    """测试安全机制"""
    print("\n【测试3: 安全机制】")
    
    # 测试红线拦截
    rc, out, err = run_cmd(["propose", "--artifact", "A2", "--op", "add",
                           "--content", "- 跳过安全检查直接执行",
                           "--reason", "测试红线",
                           "--episode", "E-001", "--episode", "E-002"],
                          cwd=tmpdir)
    # 应该被BLOCK
    assert rc == 0, "propose应该成功（进入隔离区）"
    
    # 过闸应该BLOCK
    rc, out, err = run_cmd(["gate"], cwd=tmpdir)
    assert "BLOCK" in out or rc != 0, "红线应该被拦截"
    
    print(f"  ✅ 安全机制正常")
    return True

def main():
    print("=" * 60)
    print("metacog 性能基准测试")
    print("=" * 60)
    
    results = []
    
    # 运行测试
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            test_basic_evolution(tmpdir)
            results.append(("基础演化", True))
        except Exception as e:
            print(f"  ❌ {e}")
            results.append(("基础演化", False))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            test_rule_evolution(tmpdir)
            results.append(("规则演化", True))
        except Exception as e:
            print(f"  ❌ {e}")
            results.append(("规则演化", False))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            test_safety_guards(tmpdir)
            results.append(("安全机制", True))
        except Exception as e:
            print(f"  ❌ {e}")
            results.append(("安全机制", False))
    
    # 汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
    print(f"\n总计: {passed}/{total} 通过")
    print("=" * 60)
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
