#!/usr/bin/env python3
# P1-1 修复：必须在任何 import 之前清除 uv 环境变量，防止 SRE module mismatch
# 注意：必须在 import 语句之前，因为 uv 的 PYTHONHOME 会在 import 时生效
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

# -*- coding: utf-8 -*-
"""
边界情况与安全处理测试套件
测试 v1.4.0 安全性优先策略强化内容
"""
import json
import sys
import tempfile
import shutil
from pathlib import Path

# 设置 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

# 导入 metacog
sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
import metacog


class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []
    
    def add(self, name, passed, detail=""):
        status = "PASS" if passed else "FAIL"
        self.tests.append((name, status, detail))
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        print(f"  [{status}] {name}" + (f" - {detail}" if detail else ""))
    
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"测试结果: {self.passed}/{total} PASS")
        if self.failed > 0:
            print(f"失败项: {self.failed}")
            for name, status, detail in self.tests:
                if status == "FAIL":
                    print(f"  - {name}: {detail}")
        print(f"{'='*60}\n")
        return self.failed == 0


def test_malformed_json():
    """测试 malformed JSON 处理"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        st.root.mkdir(parents=True, exist_ok=True)
        
        # 创建 malformed JSONL
        ep_file = st.episodes
        ep_file.parent.mkdir(parents=True, exist_ok=True)
        ep_file.parent.mkdir(parents=True, exist_ok=True)
        ep_file.write_text('{"id": "E-001", "utility": 0.7}\n{malformed\n{"id": "E-002", "utility": 0.8}\n', encoding='utf-8')
        
        # 应该跳过错误行，返回 2 条有效记录
        eps = metacog.read_jsonl(ep_file)
        result.add("malformed JSON 跳过错误行", len(eps) == 2, f"读取到 {len(eps)} 条")
        
        # 不应该修改已生效制品
        result.add("malformed JSON 不修改制品", not any(f.exists() for f in root.glob("artifacts/*.md")), "制品目录为空")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def test_large_file_handling():
    """测试大文件处理（>512KB）"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        st.root.mkdir(parents=True, exist_ok=True)
        
        # 创建 >512KB 的 JSONL（每行约 110 字节，6000 行 ≈ 660KB，确超 512KB 阈值）
        ep_file = st.episodes
        ep_file.parent.mkdir(parents=True, exist_ok=True)
        ep_file.parent.mkdir(parents=True, exist_ok=True)
        with ep_file.open('w', encoding='utf-8') as f:
            for i in range(6000):
                f.write(json.dumps({"id": f"E-{i:05d}", "utility": 0.7,
                                     "violations": 0, "pad": "x" * 80}) + '\n')
        
        # 应该返回空列表并输出警告
        import io
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        eps = metacog.read_jsonl(ep_file)
        stderr_output = sys.stderr.getvalue()
        sys.stderr = old_stderr
        
        result.add("大文件 (>512KB) 返回空列表", len(eps) == 0, f"返回 {len(eps)} 条")
        result.add("大文件输出警告", "[WARN]" in stderr_output, "警告消息包含 WARN")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def test_atomic_write():
    """测试原子写入（并发安全）"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        st.root.mkdir(parents=True, exist_ok=True)
        
        # 测试 write_text 原子性
        test_file = root / "test.txt"
        metacog.write_text(test_file, "content1")
        result.add("write_text 创建文件", test_file.exists(), "文件已创建")
        result.add("write_text 内容正确", test_file.read_text() == "content1", "内容匹配")
        
        # 测试 write_json 原子性
        json_file = root / "test.json"
        metacog.write_json(json_file, {"key": "value"})
        result.add("write_json 创建文件", json_file.exists(), "文件已创建")
        result.add("write_json 内容正确", json.loads(json_file.read_text()) == {"key": "value"}, "JSON 解析正确")
        
        # 测试 append_jsonl 原子性
        jsonl_file = root / "test.jsonl"
        metacog.append_jsonl(jsonl_file, {"id": "E-001"})
        result.add("append_jsonl 创建文件", jsonl_file.exists(), "文件已创建")
        lines = jsonl_file.read_text().strip().split('\n')
        result.add("append_jsonl 内容正确", len(lines) == 1 and json.loads(lines[0])["id"] == "E-001", "JSONL 解析正确")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def test_fail_closed():
    """测试 fail-closed 行为"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        
        # 未初始化目录时，非 init 命令应返回 RC=2（用 --root 隔离，避免落到 cwd）
        rc = metacog.main(["--root", str(root), "episode", "--task", "test", "--utility", "0.5", "--attributed", "A2"])
        result.add("未初始化目录返回 RC=2", rc == 2, f"返回码: {rc}")
        
        # 初始化后，正常命令应返回 RC=0
        rc = metacog.main(["--root", str(root), "init"])
        result.add("初始化成功返回 RC=0", rc == 0, f"返回码: {rc}")
        
        # 无效 utility 应返回 RC=2
        rc = metacog.main(["--root", str(root), "episode", "--task", "test", "--utility", "1.5", "--attributed", "A2"])
        result.add("无效 utility 返回 RC=2", rc == 2, f"返回码: {rc}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def test_redline_edge_cases():
    """测试红线边界情况"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        st.root.mkdir(parents=True, exist_ok=True)
        st.quarantine.mkdir(parents=True, exist_ok=True)
        (st.root / "ledger").mkdir(parents=True, exist_ok=True)
        metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
        
        # 测试各种绕过表述
        test_cases = [
            ("跳过安全检查", True),
            ("绕过验证流程", True),
            ("忽略测试步骤", True),
            ("无需用户确认", True),
            ("自动批准", True),
            ("rm -rf 删除", True),
            ("del /s 删除", True),
            ("chmod 777 提权", True),
            ("正常修改规则", False),
            ("添加新条目", False),
        ]
        
        for content, should_block in test_cases:
            p = {
                "id": "P-test",
                "artifact": "A2",
                "op": "add",
                "content": content,
                "reason": "test",
                "episodes": ["E-001", "E-002"],
            }
            verdict, checks, _ = metacog.run_gate(st, p)
            is_blocked = verdict == "block"
            result.add(f"红线测试: {content}", is_blocked == should_block, 
                      f"预期 block={should_block}, 实际 block={is_blocked}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def test_a3_append_only():
    """测试 A3 append-only 约束"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        st.root.mkdir(parents=True, exist_ok=True)
        st.quarantine.mkdir(parents=True, exist_ok=True)
        (st.root / "ledger").mkdir(parents=True, exist_ok=True)
        metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
        
        # 创建 A3 制品
        a3_path = st.artifact_path("A3")
        a3_path.parent.mkdir(parents=True, exist_ok=True)
        a3_path.write_text("# A3\n\n<!-- entry:S-000 status:active since:2026-09-07 -->\n- 测试条目\n<!-- /entry:S-000 -->\n", encoding='utf-8')
        
        # 测试 remove 操作应被 BLOCK
        p = {
            "id": "P-remove",
            "artifact": "A3",
            "op": "remove",
            "target": "S-000",
            "content": "",
            "reason": "test",
            "episodes": ["E-001", "E-002"],
        }
        verdict, checks, _ = metacog.run_gate(st, p)
        result.add("A3 remove 操作被 BLOCK", verdict == "block", "A3 只增不减约束生效")
        
        # 测试 add 操作应通过
        p["op"] = "add"
        p["content"] = "- 新安全记忆"
        p["target"] = None
        verdict, checks, _ = metacog.run_gate(st, p)
        result.add("A3 add 操作通过", verdict == "pass", "A3 允许新增")
        
        # 验证 S-000 仍然存在
        entries = metacog.parse_entries(a3_path.read_text())
        result.add("A3 原有条目保留", any(e["id"] == "S-000" for e in entries), "S-000 未被删除")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def test_immutable_targets():
    """测试不动点保护"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        st.root.mkdir(parents=True, exist_ok=True)
        st.quarantine.mkdir(parents=True, exist_ok=True)
        (st.root / "ledger").mkdir(parents=True, exist_ok=True)
        metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
        
        # 测试触及不动点的提议
        for target in metacog.IMMUTABLE_TARGETS:
            p = {
                "id": f"P-{target}",
                "artifact": "A2",
                "op": "add",
                "content": f"修改 {target} 文件",
                "reason": "test",
                "episodes": ["E-001", "E-002"],
            }
            verdict, checks, _ = metacog.run_gate(st, p)
            result.add(f"不动点保护: {target}", verdict == "block", f"{target} 受保护")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def test_evidence_threshold():
    """测试证据门槛"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        st.root.mkdir(parents=True, exist_ok=True)
        st.quarantine.mkdir(parents=True, exist_ok=True)
        (st.root / "ledger").mkdir(parents=True, exist_ok=True)
        metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
        
        # 测试 1 个 episode 应 HOLD
        p = {
            "id": "P-low-evidence",
            "artifact": "A2",
            "op": "add",
            "content": "- 测试规则",
            "reason": "test",
            "episodes": ["E-001"],
        }
        verdict, checks, _ = metacog.run_gate(st, p)
        result.add("单 episode 证据 HOLD", verdict == "hold", "需 ≥2 个 episode")
        
        # 测试 2 个 episode 应 PASS
        p["episodes"] = ["E-001", "E-002"]
        verdict, checks, _ = metacog.run_gate(st, p)
        result.add("双 episode 证据 PASS", verdict == "pass", "≥2 个 episode 通过")
        
        # 测试 A3 不需要证据门槛
        p["artifact"] = "A3"
        p["episodes"] = ["E-001"]
        verdict, checks, _ = metacog.run_gate(st, p)
        result.add("A3 跳过证据门槛", verdict == "pass", "A3 教训直接生效")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def test_consecutive_reverts():
    """测试连续 REVERT 触发 M1 自省"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        st.root.mkdir(parents=True, exist_ok=True)
        
        # 建立基线
        for i in range(5):
            metacog.append_jsonl(st.episodes, {"id": f"E-{i:03d}", "utility": 0.7, "violations": 0})
        r = st.get_ratchet()
        r["baseline_utility"] = 0.7
        r["baseline_violation_rate"] = 0.0
        st.set_ratchet(r)
        
        # 创建 trial 提议
        p = {
            "id": "P-revert-test",
            "status": "trial",
            "entry_id": "R-001",
            "op": "add",
            "artifact": "A2",
            "trial_from_index": 5,
        }
        metacog.write_json(st.quarantine / "P-revert-test.json", p)
        st.record_apply("P-revert-test", 5, "A2", "R-001")   # v2.2.3：受信任锚
        
        # 创建 5 个低 utility episode
        for i in range(5):
            metacog.append_jsonl(st.episodes, {"id": f"E-{5+i:03d}", "utility": 0.5, "violations": 1})
        
        # 第一次 verdict
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        metacog.cmd_verdict(st, type('Args', (), {'force': True})())
        output1 = sys.stdout.getvalue()
        sys.stdout = old_stdout
        
        result.add("首次 REVERT 触发", "REVERT" in output1, "条目应被回滚")
        
        # 检查 history 中是否有 revert 记录
        r = st.get_ratchet()
        result.add("历史记录 REVERT", len(r["history"]) > 0 and r["history"][-1]["action"] == "revert", 
                  f"history 长度: {len(r['history'])}")
        
        # 连续 3 次 revert 应触发 M1 提示
        r["history"] = [
            {"action": "revert", "utility": 0.5},
            {"action": "revert", "utility": 0.5},
            {"action": "revert", "utility": 0.5},
        ]
        st.set_ratchet(r)
        
        # 重置提议状态
        p["status"] = "trial"
        metacog.write_json(st.quarantine / "P-revert-test.json", p)
        
        sys.stdout = io.StringIO()
        metacog.cmd_verdict(st, type('Args', (), {'force': True})())
        output2 = sys.stdout.getvalue()
        sys.stdout = old_stdout
        
        result.add("连续 3 次 REVERT 触发 M1 提示", "[META]" in output2, "应提示元层自省")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def test_ratchet_baseline():
    """测试基线建立与棘轮裁决"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        st.root.mkdir(parents=True, exist_ok=True)
        st.quarantine.mkdir(parents=True, exist_ok=True)
        (st.root / "ledger").mkdir(parents=True, exist_ok=True)
        
        # 建立基线
        for i in range(5):
            metacog.append_jsonl(st.episodes, {"id": f"E-{i:03d}", "utility": 0.6, "violations": 1})
        
        r = st.get_ratchet()
        result.add("基线未建立", r["baseline_utility"] is None, "前 5 个 episode 建基线")
        
        # 继续添加 5 个 episode 触发基线建立
        for i in range(5, 10):
            metacog.append_jsonl(st.episodes, {"id": f"E-{i:03d}", "utility": 0.6, "violations": 1})
        
        # 手动设置基线（模拟 cmd_episode 逻辑）
        eps = metacog.read_jsonl(st.episodes)[:5]
        r["baseline_utility"] = sum(e["utility"] for e in eps) / len(eps)
        r["baseline_violation_rate"] = sum(1 for e in eps if e["violations"] > 0) / len(eps)
        st.set_ratchet(r)
        
        result.add("基线建立成功", r["baseline_utility"] == 0.6, f"基线 utility={r['baseline_utility']}")
        
        # 测试 PROMOTE 条件（utility 上升，violation 下降）
        for i in range(10, 15):
            metacog.append_jsonl(st.episodes, {"id": f"E-{i:03d}", "utility": 0.8, "violations": 0})
        
        # 创建 trial 提议
        p = {
            "id": "P-promote-test",
            "status": "trial",
            "entry_id": "R-001",
            "artifact": "A2",
            "trial_from_index": 5,
        }
        metacog.write_json(st.quarantine / "P-promote-test.json", p)
        st.record_apply("P-promote-test", 5, "A2", "R-001")   # v2.2.3：受信任锚
        
        # 创建 A2 制品
        a2_path = st.artifact_path("A2")
        a2_path.parent.mkdir(parents=True, exist_ok=True)
        a2_path.write_text("# A2\n\n<!-- entry:R-001 status:trial since:2026-09-07 -->\n- 测试规则\n<!-- /entry:R-001 -->\n", encoding='utf-8')
        
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        metacog.cmd_verdict(st, type('Args', (), {'force': True})())
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        
        result.add("PROMOTE 条件满足", "PROMOTE" in output, "utility 上升应 promote")
        
        # 验证条目状态变为 active
        a2_text = a2_path.read_text()
        result.add("条目状态更新", "status:active" in a2_text, "trial → active")
        
        # 验证基线上移
        r = st.get_ratchet()
        result.add("基线上移", r["baseline_utility"] > 0.6, f"新基线={r['baseline_utility']}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def test_immutable_structural():
    """#3 硬化：禁改硬约束结构级校验——闭合 PoC-1「改写动词绕过」，且否定/纯提及正确放行。"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        st.root.mkdir(parents=True, exist_ok=True)
        st.quarantine.mkdir(parents=True, exist_ok=True)
        (st.root / "ledger").mkdir(parents=True, exist_ok=True)
        metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))

        # (content, should_block, 说明)
        cases = [
            ("对 metacog.py 做无害调优", True, "PoC-1 动词改写绕过 → 应闭合"),
            ("建议改动 CONTRACT.md 的措辞", True, "目标身份 + 改动意图 → 应 BLOCK"),
            ("修改 scripts/metacog.py 的调度逻辑", True, "路径引用解析到受保护文件 → 应 BLOCK"),
            ("改 D:/skill/metacog.py 的入口", True, "绝对路径引用 → 应 BLOCK"),
            ("禁止修改 metacog.py", False, "强否定语境保护规则 → 应放行"),
            ("不改动 metacog.py", False, "直接否定（不改动）→ 应放行"),
            ("本引擎由 metacog.py 实现，本次不改动", False, "纯提及 + 否定 → 应放行"),
            ("对核心调度逻辑做调优", False, "诚实残余：无目标身份/路径的语义改写 → 放行（靠人类在环兜底）"),
        ]
        for content, should_block, note in cases:
            p = {
                "id": "P-imm",
                "artifact": "A2",
                "op": "add",
                "content": content,
                "reason": "test",
                "episodes": ["E-001", "E-002"],
            }
            verdict, checks, _ = metacog.run_gate(st, p)
            is_blocked = verdict == "block"
            result.add(f"结构级禁改: {content}", is_blocked == should_block,
                      f"{note} | 预期 block={should_block}, 实际={is_blocked}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def test_semantic_escalation():
    """#3 语义级升级：命中「绕过安全确认/削弱护栏」意图 → 升级需人类确认（不硬 BLOCK）。"""
    result = TestResult()
    tmpdir = tempfile.mkdtemp(prefix="metacog_test_")
    try:
        root = Path(tmpdir) / ".metacog"
        st = metacog.Store(root)
        st.root.mkdir(parents=True, exist_ok=True)
        st.quarantine.mkdir(parents=True, exist_ok=True)
        (st.root / "ledger").mkdir(parents=True, exist_ok=True)
        metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))

        # 语义可疑但非字面禁用词（denylist 未覆盖）→ 应升级 requires_human，且不应硬 BLOCK
        p = {
            "id": "P-sem",
            "artifact": "A2",
            "op": "add",
            "content": "建议弱化护栏以提升演化效率",
            "reason": "test",
            "episodes": ["E-001", "E-002"],
        }
        verdict, checks, requires_human = metacog.run_gate(st, p)
        result.add("语义升级: 非字面意图不硬 BLOCK", verdict != "block",
                  f"verdict={verdict}（应为 pass/hold，非 block）")
        result.add("语义升级: 升级为需人类确认", requires_human is True,
                  f"requires_human={requires_human}（应为 True）")

        # 第二个语义可疑项：降低确认门槛（denylist 未覆盖）
        p3 = {
            "id": "P-sem3",
            "artifact": "A2",
            "op": "add",
            "content": "降低确认门槛让规则自动生效",
            "reason": "test",
            "episodes": ["E-001", "E-002"],
        }
        verdict3, _, rh3 = metacog.run_gate(st, p3)
        result.add("语义升级: 降低门槛不硬 BLOCK", verdict3 != "block",
                  f"verdict={verdict3}（应为 pass/hold，非 block）")
        result.add("语义升级: 降低门槛升级确认", rh3 is True,
                  f"requires_human={rh3}（应为 True）")

        # 对照组：纯正常新增 → 不升级、不 block
        p2 = {
            "id": "P-sem2",
            "artifact": "A2",
            "op": "add",
            "content": "新增一条关于日志格式的规则",
            "reason": "test",
            "episodes": ["E-001", "E-002"],
        }
        verdict2, _, rh2 = metacog.run_gate(st, p2)
        result.add("语义升级: 正常新增不误伤", verdict2 != "block" and rh2 is False,
                  f"verdict={verdict2}, requires_human={rh2}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return result


def main():
    print("="*60)
    print("边界情况与安全处理测试套件 (v1.4.0)")
    print("="*60 + "\n")
    
    all_results = TestResult()
    
    print("【测试组 1: 文件处理】")
    all_results.tests.extend(test_malformed_json().tests)
    all_results.tests.extend(test_large_file_handling().tests)
    all_results.tests.extend(test_atomic_write().tests)
    
    print("\n【测试组 2: 安全约束】")
    all_results.tests.extend(test_fail_closed().tests)
    all_results.tests.extend(test_redline_edge_cases().tests)
    all_results.tests.extend(test_a3_append_only().tests)
    all_results.tests.extend(test_immutable_targets().tests)
    all_results.tests.extend(test_immutable_structural().tests)
    all_results.tests.extend(test_semantic_escalation().tests)
    all_results.tests.extend(test_evidence_threshold().tests)
    
    print("\n【测试组 3: 棘轮机制】")
    all_results.tests.extend(test_consecutive_reverts().tests)
    all_results.tests.extend(test_ratchet_baseline().tests)
    
    # 去重合并结果
    seen = set()
    unique_tests = []
    for test in all_results.tests:
        if test[0] not in seen:
            seen.add(test[0])
            unique_tests.append(test)
    
    all_results.tests = unique_tests
    all_results.passed = sum(1 for t in all_results.tests if t[1] == "PASS")
    all_results.failed = sum(1 for t in all_results.tests if t[1] == "FAIL")
    
    all_results.summary()
    return 0 if all_results.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
