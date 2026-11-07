#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# H-4 回归（v2.27.16）：read_jsonl 移除 512KB 硬截断——大 applies.jsonl（>512KB）不再被误判为
# 无记录，导致条目审计对所有已 apply 非种子条目全量误报；且大库下注入条目仍能被检出（不假绿）。
# 零第三方依赖。
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)
_os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"

import json
import shutil
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


def main():
    print("=" * 60)
    print("H-4 回归：大 applies 不误报（v2.27.16）")
    print("=" * 60 + "\n")
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_h4_"))
    try:
        mc = tmp / "root"
        st = metacog.Store(mc)
        st.root.mkdir(parents=True, exist_ok=True)
        (st.root / "ledger").mkdir(parents=True, exist_ok=True)

        # 构造 >512KB 的 applies.jsonl（2000 条合法记录，每条约 300 字节 → 约 600KB）。
        n = 2000
        lines = []
        for i in range(n):
            lines.append(json.dumps({
                "proposal_id": "P{:04d}".format(i),
                "entry_id": "LG-{:04d}".format(i),
                "artifact": "A1",
                "body_hash": "deadbeefdeadbeefdeadbeefdeadbeef",
                "human_sig": "x", "content_hash": "y",
                "pad": "z" * 220,
            }))
        applies_text = "\n".join(lines) + "\n"
        (st.root / "ledger" / "applies.jsonl").write_text(applies_text, encoding="utf-8")
        size_kb = (st.root / "ledger" / "applies.jsonl").stat().st_size // 1024
        t.add("构造 >512KB applies（{}KB）".format(size_kb), size_kb > 512, "{}KB".format(size_kb))

        recs = metacog.read_jsonl(st.applies)
        t.add("read_jsonl 不截断：返回全部 {} 条".format(n), len(recs) == n,
              "got={}".format(len(recs)))

        # 大库 + 干净制品（仅种子条目）：扫描不得因体量而全量误报（warns 应空）。
        # 写一个最小合法 A1（仅含种子 A1-000）。
        a1 = st.artifact_path("A1")
        a1.parent.mkdir(parents=True, exist_ok=True)
        a1.write_text(metacog.render_entry("A1-000", "active", metacog.today(), "", "seed body")
                      + "\n", encoding="utf-8")
        notes, warns = metacog._audit_entries_scan(st)
        t.add("大库干净：无全量误报（warns 空）", not warns, "warns={}".format(warns))

        # 大库 + 注入非种子 active 条目：仍须被检出（不假绿）。
        a1.write_text(
            metacog.render_entry("A1-000", "active", metacog.today(), "", "seed body") + "\n"
            + metacog.render_entry("ZZ-999", "active", metacog.today(), "", "injected") + "\n",
            encoding="utf-8")
        notes2, warns2 = metacog._audit_entries_scan(st)
        t.add("大库注入仍被检出（不假绿）", any("ZZ-999" in w for w in warns2),
              "warns2={}".format(warns2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed, failed, total = t.passed, t.failed, t.passed + t.failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
