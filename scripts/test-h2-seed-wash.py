#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# H-2 回归（v2.27.16）：删 seed-ids.json + 重跑 init 洗白收口。
#   原 domains/init.py 在覆盖后「unlink seed-ids.json + 重采」，且 cmd_init 重跑时若 seed 缺失会重采
#   （攻击者注入条目后删 seed + 重跑 init 即可把注入纳入种子集洗白）。
#   现：_write_seed_ids 在「制品已存在」时拒绝静默重采（guard）；seed 入 D4 基线（删种子即被 verify 检出）；
#       init-domain 仅在可信模板覆盖后 force 重采。
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


def _cli(root, *args):
    env = dict(_os.environ)
    # F2''（v2.27.37）：统一子进程 IO 编码，防 cp936 下「子进程 GBK 写 vs 父进程 utf-8 解码」失配
    env["PYTHONIOENCODING"] = "utf-8"

    return subprocess.run(
        [sys.executable, str(Path(__file__).parent / "metacog.py"), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)


def main():
    print("=" * 60)
    print("H-2 回归：删 seed-ids + 重跑 init 洗白收口（v2.27.16）")
    print("=" * 60 + "\n")
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_h2_"))
    try:
        mc = tmp / "dom"
        res = init_domain("code_review", mc)  # 写入种子集 + D4 基线
        mcd = mc / ".metacog"
        seed = mcd / "meta" / "seed-ids.json"
        integrity = mcd / "ledger" / "integrity.json"
        t.add("init_domain 成功", res["engine_compatible"] is True)
        t.add("seed-ids.json 已创建", seed.exists())
        t.add("seed 入 D4 基线(meta:seed-ids.json 键)",
              '"meta:seed-ids.json"' in integrity.read_text(encoding="utf-8"))

        # 模拟洗白前奏：删 seed-ids.json，再重跑 init（live 实例重跑）→ 应拒绝重采
        seed.unlink()
        r = _cli(mcd, "init")
        t.add("重跑 init 不重建 seed（H-2 守卫）", not seed.exists(), "seed 仍缺失")
        # verify 应 fail-closed（基线有 meta:seed-ids.json 键但文件缺失）
        r2 = _cli(mcd, "verify")
        t.add("删 seed + 重init: verify rc=1（H-2 fail-closed）", r2.returncode == 1,
              "rc={}".format(r2.returncode))
        _out2 = r2.stdout + r2.stderr
        t.add("fail-closed 信号含 seed/基线缺失",
              ("H-2" in _out2) or ("seed" in _out2.lower()) or ("基线缺失" in _out2) or ("meta:seed" in _out2),
              "rc={}".format(r2.returncode))

        # 单元：_write_seed_ids 在「制品存在 + seed 缺失」时拒绝静默重采（force=False）
        st = metacog.Store(mcd)
        a1 = st.artifact_path("A1")
        if not a1.exists():
            metacog.write_text(a1, "# A1\n<!-- entry:A1-000 status:active since:2026 -->\nbody\n<!-- /entry:A1-000 -->\n")
        refuse = metacog._write_seed_ids(st, force=False)
        t.add("_write_seed_ids(force=False) 拒绝重采", refuse is False, "返回 False")
        # 单元：force=True 可重采（仅可信覆盖后/显式 --reseed 语义）
        forced = metacog._write_seed_ids(st, force=True)
        t.add("_write_seed_ids(force=True) 可重采", forced is True, "返回 True")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed, failed, total = t.passed, t.failed, t.passed + t.failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
