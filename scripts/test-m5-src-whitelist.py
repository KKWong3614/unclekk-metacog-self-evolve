#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# M-5 回归（v2.27.16）：render_entry 的 src 白名单与 ENTRY_RE 解析器一致（[\w\-]+），杜绝
# src:P-1.2 这类含非法字符的「幽灵条目」——render 后必须能被 parse_entries 正常解析（不消失）。
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
    print("M-5 回归：src 白名单统一（v2.27.16）")
    print("=" * 60 + "\n")
    t = T()

    # 场景 1：src 含非法字符（点号）→ 被安全丢弃，条目仍可被解析、正文不丢。
    blk = metacog.render_entry("X-1", "active", "2026-01-01", "P-1.2", "hello body")
    t.add("含非法字符 src 被丢弃（不抛错）", "src:P-1.2" not in blk, "")
    entries = metacog.parse_entries(blk)
    ok1 = any((e.get("id") == "X-1" and (e.get("body") or "").strip() == "hello body") for e in entries)
    t.add("条目可被 parse_entries 正常解析（正文不丢）", ok1, "entries={}".format(entries))

    # 场景 2：合法 src（仅 [\w\-]+）→ 保留。
    blk2 = metacog.render_entry("X-2", "active", "2026-01-01", "manual", "second body")
    t.add("合法 src 保留", "src:manual" in blk2, "")
    entries2 = metacog.parse_entries(blk2)
    ok2 = any((e.get("id") == "X-2" and (e.get("src") or "") == "manual") for e in entries2)
    t.add("合法 src 解析后保持", ok2, "entries={}".format(entries2))

    # 场景 3：无 src → 正常。
    blk3 = metacog.render_entry("X-3", "active", "2026-01-01", "", "third body")
    t.add("无 src 正常渲染", "X-3" in blk3 and "third body" in blk3, "")

    passed, failed, total = t.passed, t.failed, t.passed + t.failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
