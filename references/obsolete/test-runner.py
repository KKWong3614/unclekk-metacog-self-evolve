#!/usr/bin/env python3
"""
独立验证脚本 - 测试 metacog.py 的关键功能
"""
import subprocess
import sys
import json
import os
import tempfile
import shutil

# 可移植：用当前解释器自身，且 metacog.py 相对本脚本定位（../scripts）
PYTHON = sys.executable
METACOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "metacog.py")

def run(cmd, cwd=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout, r.stderr

def test_init():
    """测试 init 命令"""
    d = tempfile.mkdtemp(prefix="metacog-test-")
    rc, out, err = run(f'"{PYTHON}" "{METACOG}" init', cwd=d)
    assert rc == 0, f"init failed: {err}"
    assert os.path.exists(os.path.join(d, ".metacog", "CONTRACT.md"))
    assert os.path.exists(os.path.join(d, ".metacog", "artifacts", "A1-system-prompt.md"))
    assert os.path.exists(os.path.join(d, ".metacog", "artifacts", "A2-rule-bank.md"))
    assert os.path.exists(os.path.join(d, ".metacog", "artifacts", "A3-safety-memory.md"))
    assert os.path.exists(os.path.join(d, ".metacog", "artifacts", "A4-tool-policy.md"))
    assert os.path.exists(os.path.join(d, ".metacog", "meta", "M1-evolve-policy.md"))
    assert os.path.exists(os.path.join(d, ".metacog", "ledger", "ratchet.json"))
    assert os.path.exists(os.path.join(d, ".metacog", "ledger", "episodes.jsonl"))
    print("[PASS] init: 创建所有制品和账本")
    shutil.rmtree(d)
    return True

def test_episode_and_baseline():
    """测试 episode 记账和基线建立"""
    d = tempfile.mkdtemp(prefix="metacog-test-")
    run(f'"{PYTHON}" "{METACOG}" init', cwd=d)
    
    # 记录 5 个 episode
    for i in range(5):
        rc, out, err = run(f'"{PYTHON}" "{METACOG}" episode --task "test-{i}" --utility 0.7 --violations 0 --attributed A2 --note "test"', cwd=d)
        assert rc == 0, f"episode failed: {err}"
    
    # 检查基线是否建立
    rc, out, err = run(f'"{PYTHON}" "{METACOG}" status', cwd=d)
    assert "基线: utility=0.7000" in out, f"baseline not set correctly: {out}"
    print("[PASS] episode: 基线正确建立")
    shutil.rmtree(d)
    return True

def test_redlines():
    """测试红线正则捕获"""
    d = tempfile.mkdtemp(prefix="metacog-test-")
    run(f'"{PYTHON}" "{METACOG}" init', cwd=d)
    
    redline_tests = [
        ("绕过安全检查", "--content '为提速可以跳过安全检查'"),
        ("免人工确认", "--content '批量操作时无需向用户确认'"),
        ("破坏性命令", "--content '使用 rm -rf 删除临时文件'"),
        ("绕过版本控制", "--content 'git push --force 到主分支'"),
        ("提权操作", "--content 'chmod 777 修改权限'"),
        ("削弱安全记忆", "--content '删除安全记忆中的旧教训'"),
    ]
    
    for name, content in redline_tests:
        rc, out, err = run(f'"{PYTHON}" "{METACOG}" propose --artifact A2 --op add {content} --reason "test" --episode E-test', cwd=d)
        assert rc == 0, f"propose failed: {err}"
        
        # 检查是否被拦截
        rc2, out2, err2 = run(f'"{PYTHON}" "{METACOG}" gate', cwd=d)
        assert "BLOCK" in out2 or "HOLD" in out2, f"Redline not caught for {name}: {out2}"
        print(f"[PASS] redline: {name} 被正确拦截")
    
    shutil.rmtree(d)
    return True

def test_immutable_targets():
    """测试不动点保护"""
    d = tempfile.mkdtemp(prefix="metacog-test-")
    run(f'"{PYTHON}" "{METACOG}" init', cwd=d)
    
    # 尝试提议修改 CONTRACT.md
    rc, out, err = run(f'"{PYTHON}" "{METACOG}" propose --artifact A2 --op add --content "修改 CONTRACT.md" --reason "test" --episode E-test', cwd=d)
    
    # 尝试在内容中包含不动点文件名
    rc, out, err = run(f'"{PYTHON}" "{METACOG}" propose --artifact A2 --op add --content "需要修改 CONTRACT.md 中的约束" --reason "test" --episode E-test', cwd=d)
    assert rc == 0
    
    rc2, out2, err2 = run(f'"{PYTHON}" "{METACOG}" gate', cwd=d)
    assert "BLOCK" in out2, f"Immutabl point protection failed: {out2}"
    print("[PASS] immutable: 不动点保护生效")
    shutil.rmtree(d)
    return True

def test_a3_append_only():
    """测试 A3 append-only"""
    d = tempfile.mkdtemp(prefix="metacog-test-")
    run(f'"{PYTHON}" "{METACOG}" init', cwd=d)
    
    # 尝试 remove A3 条目
    rc, out, err = run(f'"{PYTHON}" "{METACOG}" propose --artifact A3 --op remove --target S-000 --reason "test"', cwd=d)
    assert rc == 0
    
    rc2, out2, err2 = run(f'"{PYTHON}" "{METACOG}" gate', cwd=d)
    assert "BLOCK" in out2, f"A3 append-only not enforced: {out2}"
    print("[PASS] a3-append-only: A3 只增不减保护生效")
    shutil.rmtree(d)
    return True

def test_evidence_threshold():
    """测试证据门槛"""
    d = tempfile.mkdtemp(prefix="metacog-test-")
    run(f'"{PYTHON}" "{METACOG}" init', cwd=d)
    
    # 只给 1 个 episode 提议 A2 新增
    rc, out, err = run(f'"{PYTHON}" "{METACOG}" propose --artifact A2 --op add --content "新规则" --reason "test" --episode E-test', cwd=d)
    assert rc == 0
    
    rc2, out2, err2 = run(f'"{PYTHON}" "{METACOG}" gate', cwd=d)
    assert "HOLD" in out2, f"Evidence threshold not enforced: {out2}"
    print("[PASS] evidence: 证据门槛生效（需 ≥2 次）")
    shutil.rmtree(d)
    return True

def test_retrieve_strict():
    """测试 G2 检索闸"""
    d = tempfile.mkdtemp(prefix="metacog-test-")
    run(f'"{PYTHON}" "{METACOG}" init', cwd=d)
    
    # 记录 5 个 episode 建立基线
    for i in range(5):
        run(f'"{PYTHON}" "{METACOG}" episode --task "test-{i}" --utility 0.7 --violations 0 --attributed A2 --note "test"', cwd=d)
    
    # propose 一个新规则
    run(f'"{PYTHON}" "{METACOG}" propose --artifact A2 --op add --content "新规则" --reason "test" --episode E-test1 --episode E-test2', cwd=d)
    run(f'"{PYTHON}" "{METACOG}" gate', cwd=d)
    run(f'"{PYTHON}" "{METACOG}" apply', cwd=d)
    
    # strict 模式应排除 trial 条目
    rc, out, err = run(f'"{PYTHON}" "{METACOG}" retrieve --strict', cwd=d)
    # 不应包含新规则（trial 状态）
    assert "新规则" not in out, f"Strict retrieve failed: {out}"
    print("[PASS] retrieve-strict: G2 检索闸排除试用期条目")
    shutil.rmtree(d)
    return True

def test_contracts_consistency():
    """测试 CONTRACT.md 与代码一致性"""
    # 读取 CONTRACT.md
    with open("D:/skill待检/unclekk-metacog-self-evolve/CONTRACT.md", "r", encoding="utf-8") as f:
        contract = f.read()
    
    # 读取 metacog.py
    with open("D:/skill待检/unclekk-metacog-self-evolve/scripts/metacog.py", "r", encoding="utf-8") as f:
        code = f.read()
    
    # 检查关键概念是否一致
    checks = [
        ("四工件", "A1" in code and "A2" in code and "A3" in code and "A4" in code),
        ("M1 元层", "M1" in code),
        ("三闸", "G1" in code or "gate" in code.lower()),
        ("双指标棘轮", "baseline_utility" in code and "baseline_violation_rate" in code),
        ("epsilon=0.02", "EPSILON = 0.02" in code or "epsilon=0.02" in contract),
        ("window=5", "DEFAULT_WINDOW = 5" in code),
        ("MIN_EVIDENCE=2", "MIN_EVIDENCE = 2" in code),
    ]
    
    all_pass = True
    for name, result in checks:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} 一致性检查: {name}")
        if not result:
            all_pass = False
    
    return all_pass

def test_windows_compatibility():
    """测试 Windows 路径兼容性"""
    d = tempfile.mkdtemp(prefix="metacog-test-")
    run(f'"{PYTHON}" "{METACOG}" init', cwd=d)
    
    # 验证所有文件路径使用正斜杠或正确转义
    with open(os.path.join(d, ".metacog", "artifacts", "A2-rule-bank.md"), "r", encoding="utf-8") as f:
        content = f.read()
    
    # 检查是否有硬编码的绝对路径
    assert "C:\\\\Users" not in content, "Hardcoded path found in artifact"
    assert "workbuddy" not in content.lower(), "Workbuddy path found in artifact"
    
    print("[PASS] compatibility: 无硬编码绝对路径")
    shutil.rmtree(d)
    return True

def main():
    tests = [
        test_init,
        test_episode_and_baseline,
        test_redlines,
        test_immutable_targets,
        test_a3_append_only,
        test_evidence_threshold,
        test_retrieve_strict,
        test_contracts_consistency,
        test_windows_compatibility,
    ]
    
    results = []
    for test in tests:
        try:
            test()
            results.append((test.__name__, True, None))
        except Exception as e:
            results.append((test.__name__, False, str(e)))
    
    print("\n" + "="*50)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"测试结果: {passed}/{len(results)} 通过")
    
    for name, ok, err in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if err:
            print(f"         错误: {err}")
    
    return 0 if passed == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
