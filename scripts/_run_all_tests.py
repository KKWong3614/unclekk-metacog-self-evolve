#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""unclekk-metacog-self-evolve 全量 test-*.py 回归运行器（随包分发，独立可复现）。

v2.27.14 M-08 收口：此前运行器未随包（HANDOFF.md 自认"非独立可复现"），本文件随
scripts/ 分发，路径相对化（不依赖任何本机绝对路径），审计方/第三方可在任意机直接跑：

    python3 scripts/_run_all_tests.py

v2.27.15（N-16 收口，外部审计 v2.27.14）：
- **判定不再只看退出码**（兑现 CHANGELOG v2.22/F4 声明却未实现的 no_self_report 能力）：
  ① 套件必须发出可解析自报（末次 `X/Y PASS`），X<Y 即 FAIL（exit 0 也 FAIL）；
  ② 套件输出含 `[FAIL]` 标记即 FAIL（防「打印失败却 exit 0」的掩错——HANDOFF.md:634
  自述过的失败模式）；
  ③ 完全无可解析自报 → FAIL（no-self-report）。
- **应有套件清单**（scripts/test-suite-manifest.txt）：清单声明但文件缺失 → 直接 FAIL，
  分母不得静默变小（删测试文件不再让通过率自动变好看）；清单外新增套件 → WARN 提醒更新清单。

口径（诚实）：
- 全局仅设专属 METACOG_TRUST_ROOT_ANCHOR_KEY=测试密钥（v2.27.17 C-01：源码内嵌默认锚已删除，
  测试统一用固定测试密钥；生产/非本地须以部署专属随机密钥覆盖）；
- METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR 已随 H-01 删除（v2.27.17）：该变量不再有任何效果，
  历史上「绝不全局强设」的踩坑②记录保留备查（现无该回落路径）；
- 逐项子进程运行，超时（180s）计 FAIL，失败打印 stdout/stderr 尾部。
"""
import os as _os
import re as _re
import subprocess
import sys
from pathlib import Path

# 相对化：本文件位于 <skill>/scripts/_run_all_tests.py
SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent
MANIFEST = SCRIPTS / "test-suite-manifest.txt"
_SELFREPORT_RE = _re.compile(r"(\d+)\s*/\s*(\d+)\s*(?:组\s*)?PASS")
# v2.27.15：部分套件以「总判定: ALL PASS / HAS FAIL」作自报（无 X/Y 计数行），同样可解析
_VERDICT_RE = _re.compile(r"总判定:\s*(ALL PASS|HAS FAIL)")
# v2.27.15（Hermes 三审 C-N3g）：[FAIL] 标记扫描正则化——大小写变体（[fail]/[Fail]）同样命中
_FAIL_MARKER_RE = _re.compile(r"\[\s*f[a][i][l]\s*\]", _re.IGNORECASE)


def _expected_suites():
    if not MANIFEST.exists():
        return None
    return [ln.strip() for ln in MANIFEST.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


def main():
    tests = sorted(SCRIPTS.glob("test-*.py"))
    names = [t.name for t in tests]

    # N-16：应有套件清单——分母不得静默变小
    # v2.27.15（Hermes 三审 C-N3f 收口）：manifest 文件缺失/被删 → fail-closed（原实现静默跳过
    # 全套清单校验，攻击者可删 manifest+塞假套件绕过）。
    expected = _expected_suites()
    if expected is None:
        print("[FAIL] test-suite-manifest.txt 缺失——应有套件清单是分母完整性的唯一依据，"
              "缺失即整体 FAIL（fail-closed，Hermes 三审 C-N3f）。请恢复清单文件。")
        sys.exit(1)
    missing = [e for e in expected if e not in names]
    if missing:
        print("[FAIL] 应有套件缺失（test-suite-manifest.txt 声明但 scripts/ 下不存在）：")
        for m in missing:
            print("  - " + m)
        print("分母不得静默变小：请恢复文件，或显式更新清单并在 CHANGELOG 说明删除理由。")
        sys.exit(1)
    # v2.27.15（Hermes 三审 C-N3h 收口）：清单外套件从 WARN 升级为 FAIL——恶意/遗忘的清单外
    # 套件不得被静默纳入分母；新增合法套件须同步更新清单（清单本身入冻结账本）。
    extra = [n for n in names if n not in expected]
    if extra:
        print("[FAIL] 清单外套件（test-suite-manifest.txt 未声明，Hermes 三审 C-N3h：不静默纳分）：")
        for e in extra:
            print("  - " + e)
        print("新增合法回归请同步更新 test-suite-manifest.txt 并入冻结账本后重跑。")
        sys.exit(1)

    total = len(tests)
    passed = 0
    failed = []
    env = dict(_os.environ)
    env["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"
    for t in tests:
        name = t.name
        reason = ""
        try:
            p = subprocess.run([sys.executable, str(t)], cwd=str(SCRIPTS),
                               env=env, capture_output=True, encoding="utf-8",
                               errors="replace", timeout=600)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = 124
            p = None
        ok = (rc == 0)
        # v2.27.15（N-16）：exit 0 不再是唯一判据
        out_all = ((p.stdout if p else "") + "\n" + (p.stderr if p else ""))
        last = None
        for last in _SELFREPORT_RE.finditer(p.stdout if p else ""):
            pass
        verdict = None
        for verdict in _VERDICT_RE.finditer(p.stdout if p else ""):
            pass
        if ok and last is not None:
            x, y = int(last.group(1)), int(last.group(2))
            if x == 0 and y == 0:
                ok = False
                reason = "自报 0/0（无用例执行，疑似套件未真正运行）"
            elif x < y:
                ok = False
                reason = "自报 {}/{}<全过".format(x, y)
        elif ok and verdict is not None:
            if verdict.group(1) != "ALL PASS":
                ok = False
                reason = "总判定 HAS FAIL"
        if ok and _FAIL_MARKER_RE.search(out_all):
            ok = False
            reason = "输出含 [FAIL] 类标记"
        if ok and last is None and verdict is None:
            ok = False
            reason = "无可解析自报(no-self-report)"
        if ok:
            passed += 1
        else:
            failed.append((name, rc, reason,
                           p.stdout[-600:] if p else "", p.stderr[-600:] if p else ""))
        label = "PASS" if ok else "FAIL(rc={}, {})".format(rc, reason or "exit!=0")
        print("[{:>4}/{:<4}] {:<28} {}".format(passed + len(failed), total, label, name), flush=True)
    print("\n" + "=" * 70)
    print("全量回归: {}/{} 诚实 PASS（exit=0 且自报全过且无 [FAIL] 标记）".format(passed, total))
    print("=" * 70)
    if failed:
        print("\n失败清单:")
        for name, rc, reason, out, err in failed:
            print("- {} rc={} ({})".format(name, rc, reason))
            if out.strip():
                print("   stdout tail:", out.strip()[-300:])
            if err.strip():
                print("   stderr tail:", err.strip()[-300:])
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
