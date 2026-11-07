#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# M-3 回归（v2.27.16）：_reactivate_block 加 expected_id 约束——只复活 id == expected_id 的条目；
# 匹配到非目标 id → 抛 ValueError（拒绝复活伪造成员后重基线洗白）；前缀残余告警不静默。
# 零第三方依赖。
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)
_os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"

import sys
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


def main():
    print("=" * 60)
    print("M-3 回归：_reactivate_block expected_id 约束（v2.27.16）")
    print("=" * 60 + "\n")
    t = T()

    forged = metacog.render_entry("R-777", "revoked", metacog.today(), "", "forged")
    target = metacog.render_entry("R-001", "revoked", metacog.today(), "", "target body")

    # 场景 1：expected_id 命中目标 → 正常复活为 active，不抛错。
    try:
        out1 = metacog._reactivate_block(target, "R-001")
        ok1 = ("status:active" in out1) and ("R-001" in out1)
        t.add("expected_id 命中：正常复活", ok1, "")
    except Exception as e:
        t.add("expected_id 命中：正常复活", False, "{}: {}".format(type(e).__name__, e))

    # 场景 2：expected_id 不匹配首条（伪造在前）→ 抛 ValueError 拒绝。
    block2 = forged + "\n" + target
    try:
        metacog._reactivate_block(block2, "R-001")
        t.add("expected_id 不匹配：抛 ValueError 拒绝", False, "未抛错（漏检）")
    except ValueError:
        t.add("expected_id 不匹配：抛 ValueError 拒绝", True, "")
    except Exception as e:
        t.add("expected_id 不匹配：抛 ValueError 拒绝", False, "非 ValueError: {}".format(e))

    # 场景 3：expected_id=None（旧式调用）不破坏——命中首条且复活。
    try:
        out3 = metacog._reactivate_block(forged, None)
        ok3 = ("status:active" in out3) and ("R-777" in out3)
        t.add("expected_id=None：向后兼容复活首条", ok3, "")
    except Exception as e:
        t.add("expected_id=None：向后兼容复活首条", False, "{}: {}".format(type(e).__name__, e))

    passed, failed, total = t.passed, t.failed, t.passed + t.failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
