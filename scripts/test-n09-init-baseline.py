#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# N-09 回归（v2.27.15，外部审计 v2.27.14 Medium 收口）：
#   init_domain 覆盖五制品后重记 D4 完整性基线——领域实例出生即可 verify rc=0，
#   不再"5 制品偏离快照"恒红（恒红噪声曾掩掉直写篡改的唯一可见信号）。
# 零第三方依赖。
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)
_os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"

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
from domains.init import init_domain


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def add(self, name, ok, detail=""):
        self.passed += ok
        self.failed += (not ok)
        print("  [{}] {}{}".format("PASS" if ok else "FAIL", name,
                                    (" - " + detail) if detail else ""))


def main():
    print("=" * 60)
    print("N-09 回归：init-domain 出生 verify 干净（v2.27.15）")
    print("=" * 60 + "\n")
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_n09_"))
    try:
        res = init_domain("code_review", tmp)  # 不带 --config，完全合法路径
        mc = tmp / ".metacog"
        t.add("init_domain 成功", res["engine_compatible"] is True, str(res["path"]))

        # CLI 端到端：verify 必须 rc=0（修复前为 rc=1，5 制品全偏离快照）
        env = dict(_os.environ)
        # F2''（v2.27.37）：统一子进程 IO 编码，防 cp936 下「子进程 GBK 写 vs 父进程 utf-8 解码」失配
        env["PYTHONIOENCODING"] = "utf-8"

        r = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "metacog.py"),
             "--root", str(mc), "verify"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=120)
        t.add("领域实例 verify rc=0", r.returncode == 0,
              "rc={} tail={}".format(r.returncode, (r.stdout + r.stderr)[-200:]))
        t.add("无『偏离快照』阻断", "偏离" not in (r.stdout + r.stderr), "恒红噪声已消")

        # 直写篡改仍应被检出（正向对照：完整性信号在干净基线上才有意义）
        a1 = mc / "artifacts" / "A1-system-prompt.md"
        a1.write_text(a1.read_text(encoding="utf-8").replace("审查", "审查TAMPERED"), encoding="utf-8")
        r2 = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "metacog.py"),
             "--root", str(mc), "verify"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=120)
        t.add("直写篡改仍被 verify 检出(rc!=0)", r2.returncode != 0,
              "rc={}（信号未被噪声稀释）".format(r2.returncode))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed, failed, total = t.passed, t.failed, t.passed + t.failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
