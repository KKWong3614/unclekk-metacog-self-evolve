#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# L-3 回归（v2.27.16）：_hash_matches 对非 ASCII 哈希不得抛 TypeError（原 hmac.compare_digest
# 遇非 ASCII str 直接抛 TypeError → verify 崩而非报 dirty）。现加 isascii() 守卫，非 ASCII → False。
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
    print("L-3 回归：非 ASCII 哈希不崩（v2.27.16）")
    print("=" * 60 + "\n")
    t = T()
    # 非 ASCII 哈希：守卫返回 False，绝不抛 TypeError。
    try:
        r1 = metacog.Store._hash_matches("éabc", "éabc")
        t.add("非ASCII哈希不抛异常且返回False", (r1 is False), "r1={}".format(r1))
    except TypeError as e:
        t.add("非ASCII哈希不抛异常且返回False", False, "TypeError: {}".format(e))
    # 正常 ASCII 匹配仍 True。
    r2 = metacog.Store._hash_matches("deadbeef", "deadbeef")
    t.add("正常ASCII匹配返回True", r2 is True, "r2={}".format(r2))
    # 正常 ASCII 不匹配仍 False（且不崩）。
    r3 = metacog.Store._hash_matches("deadbeef", "feedface")
    t.add("正常ASCII不匹配返回False", r3 is False, "r3={}".format(r3))
    # None 不再误判 True（类型守卫）。
    r4 = metacog.Store._hash_matches(None, None)
    t.add("None/None 返回False（类型守卫）", r4 is False, "r4={}".format(r4))
    # bytes 等非 str 也返回 False 不崩。
    try:
        r5 = metacog.Store._hash_matches(b"deadbeef", b"deadbeef")
        t.add("bytes哈希返回False不崩", r5 is False, "r5={}".format(r5))
    except Exception as e:
        t.add("bytes哈希返回False不崩", False, "{}: {}".format(type(e).__name__, e))

    passed, failed, total = t.passed, t.failed, t.passed + t.failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
