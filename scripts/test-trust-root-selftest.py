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
    env = dict(os.environ)
    # F2'' 类加固（v2.27.37）：统一子进程 IO 编码，防 cp936 控制台下
    # 「子进程 GBK 写管道 vs 父进程按 encoding 解码」失配（与 test-n10-n11 同类）。
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(
        [PY, TRUST_ROOT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=env,
    )
    # 哨兵诊断（v2.27.37）：capture_output=True 下 stdout/stderr 理论上不应为 None；
    # 若出现该态（聚合器长序列中偶发），把 p 的完整内部状态落盘供根因分析，而非裸 TypeError。
    if p.stdout is None or p.stderr is None:
        import traceback
        diag = (
            "SENTINEL: capture_output=True 下出现 None 流\n"
            "returncode={!r} stdout is None={} stderr is None={}\n"
            "args={!r}\n".format(p.returncode, p.stdout is None, p.stderr is None, p.args)
        )
        sys.stderr.write(diag)
        sys.stderr.write("trust_root.py 模块自检哨兵失败（见上）\n")
        sys.exit(3)
    out = p.stdout + p.stderr
    ok = (p.returncode == 0) and ("全部通过" in out)
    if not ok:
        print(out[-2000:] if out else "(无输出)")
        print("0/1 PASS  trust_root.py 模块自检失败 rc={}".format(p.returncode))
        sys.exit(1)
    print("1/1 PASS  trust_root.py 模块自检通过（含 v2.8.2 默认 fail-closed 断言 + 显式 opt-out 回落 None）")


if __name__ == "__main__":
    main()
