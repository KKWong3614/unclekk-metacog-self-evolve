#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# H-3 回归（v2.27.16）：只比 id 改正文不留痕收口。
#   原条目级扫描仅比对条目 id 是否出现在 applies/种子集，攻击者「保留 id、篡改正文」即可绕过。
#   现：每个命中 applies 的条目比对正文哈希（body_hash）；非 active 伪造也须判定（不再静默 skip）。
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


def main():
    print("=" * 60)
    print("H-3 回归：只比 id 改正文不留痕收口（v2.27.16）")
    print("=" * 60 + "\n")
    t = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_h3_"))
    try:
        mc = tmp / "root"
        env = dict(_os.environ)
        # F2''（v2.27.37）：统一子进程 IO 编码
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "metacog.py"), "--root", str(mc), "init"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=120)
        t.add("init rc=0", r.returncode == 0, r.stderr[-150:])
        st = metacog.Store(mc)

        a1 = st.artifact_path("A1")
        txt = a1.read_text(encoding="utf-8")
        entries = metacog.parse_entries(txt)
        e0 = [e for e in entries if e["id"] == "A1-000"][0]
        orig_body = e0["body"]
        body_hash = st._hash_text((orig_body or "").strip())

        # 写入 applies 记录（含 body_hash，模拟 apply 落锚）——注意真实路径在 ledger/ 下
        rec = {"proposal_id": "P1", "entry_id": "A1-000", "artifact": "A1",
               "body_hash": body_hash, "human_sig": "x", "content_hash": "y", "applied_at": "2026"}
        (mc / "ledger" / "applies.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")

        # 场景 1：正文未改 → 无 H-3 告警
        notes1, warns1 = metacog._audit_entries_scan(st)
        t.add("正文未改：无 H-3 告警", not any("H-3" in w for w in warns1), "warns1={}".format(warns1))

        # 场景 2：正文被改（只留 id）→ 应报 H-3
        # 用 ENTRY_RE 精确匹配跨度重写 A1-000 正文，避免原始正文子串在渲染文本中不精确匹配的问题。
        m = next(mm for mm in metacog.ENTRY_RE.finditer(txt) if mm.group("id") == "A1-000")
        txt2 = txt[:m.start("body")] + (m.group("body") + " TAMPERED_BODY") + txt[m.end("body"):]
        a1.write_text(txt2, encoding="utf-8")
        notes2, warns2 = metacog._audit_entries_scan(st)
        t.add("正文被改：报 H-3 告警", any("H-3" in w for w in warns2), "warns2={}".format(warns2))

        # 场景 3：非 active 伪造（id 不在 applies/种子集）→ 应报「非 active」告警
        forged = metacog.render_entry("ZZ-999", "trial", metacog.today(), "", "forged") + "\n"
        a1.write_text(txt2 + forged, encoding="utf-8")
        notes3, warns3 = metacog._audit_entries_scan(st)
        t.add("非active伪造：报非 active 告警", any("非 active" in w for w in warns3),
              "warns3={}".format(warns3))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed, failed, total = t.passed, t.failed, t.passed + t.failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
