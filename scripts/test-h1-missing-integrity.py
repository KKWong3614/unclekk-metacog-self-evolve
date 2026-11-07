#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# H-1 回归（v2.27.16）：删 integrity.json 静默关检测收口。
#   原 cmd_verify 在 integrity.json 缺失（rows 空）时直接 `return 0`，使「删基线即关检测」——
#   直写篡改唯一可见信号被静默关闭。
#   现：applies 非空 + integrity 缺失 → fail-closed(rc=1)；全新实例（applies 空）→ rc=0 但明示「完整性未建立」。
# 零第三方依赖。
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)
_os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))
import metacog


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def add(self, name, ok, detail=""):
        self.passed += ok
        self.failed += (not ok)
        print("  [{}] {}{}".format("PASS" if ok else "FAIL", name,
                                    (" - " + detail) if detail else ""))


def _cli(root, *args):
    env = dict(_os.environ)
    # F2''（v2.27.37）：统一子进程 IO 编码，防 cp936 下「子进程 GBK 写 vs 父进程 utf-8 解码」失配
    env["PYTHONIOENCODING"] = "utf-8"

    return subprocess.run(
        [sys.executable, str(Path(__file__).parent / "metacog.py"), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)


def main():
    print("=" * 60)
    print("H-1 回归：删 integrity.json 静默关检测收口（v2.27.16）")
    print("=" * 60 + "\n")
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_h1_"))
    try:
        mc = tmp / "root"
        r = _cli(mc, "init")
        t.add("init rc=0", r.returncode == 0, r.stderr[-200:])
        integrity = mc / "ledger" / "integrity.json"
        applies = mc / "ledger" / "applies.jsonl"
        t.add("integrity.json 已创建", integrity.exists())

        # 场景 A：全新实例（删基线 + 无 apply）→ 不误判绿，rc=0 且明示「完整性未建立」
        if integrity.exists():
            integrity.unlink()
        r0 = _cli(mc, "verify")
        t.add("删基线+无apply: verify rc=0（不误判绿）", r0.returncode == 0, "rc={}".format(r0.returncode))
        t.add("提示『完整性基线尚未建立』", "尚未建立" in (r0.stdout + r0.stderr), "")

        # 场景 B：模拟 apply（写一条 applies 记录）后再删基线 → 应 fail-closed rc=1
        applies.write_text(
            json.dumps({"proposal_id": "P1", "entry_id": "A1-000", "artifact": "A1",
                       "body_hash": "deadbeefdeadbeefdeadbeefdeadbeef"}) + "\n",
            encoding="utf-8")
        r1 = _cli(mc, "verify")
        t.add("删基线+有apply: verify rc=1（H-1 fail-closed）", r1.returncode == 1, "rc={}".format(r1.returncode))
        t.add("输出含 H-1 标识", "H-1" in (r1.stdout + r1.stderr), "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed, failed, total = t.passed, t.failed, t.passed + t.failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
