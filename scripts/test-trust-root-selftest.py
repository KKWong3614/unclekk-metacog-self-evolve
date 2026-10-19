#!/usr/bin/env python3
"""v2.25.0 CI gate: 确保 trust_root.py 模块自带自检通过。

异族独立审计（2026-10-17）发现：trust_root.py 自带 `_selftest()` 第 779 行陈旧断言
（v2.8.2 改默认 fail-closed 后未同步）导致模块自检挂掉，但生产回归 292/292 全绿
未覆盖该自测。本测试将 `python trust_root.py` 纳入回归门禁，防止模块自测再次静默失效。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRUST_ROOT = os.path.join(ROOT, "scripts", "trust_root.py")
PY = sys.executable


def main():
    p = subprocess.run(
        [PY, TRUST_ROOT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    out = p.stdout + p.stderr
    ok = (p.returncode == 0) and ("全部通过" in out)
    if not ok:
        print(out[-2000:] if out else "(无输出)")
        print("0/1 PASS  trust_root.py 模块自检失败 rc={}".format(p.returncode))
        sys.exit(1)
    print("1/1 PASS  trust_root.py 模块自检通过（含 v2.8.2 默认 fail-closed 断言 + 显式 opt-out 回落 None）")


if __name__ == "__main__":
    main()
