#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.10.0 回归测试套件（Hermes r7 收口，独立验证，非自验自收）

覆盖 r7 裁定（CONDITIONAL-PASS 维持）的 4 条对抗回归用例，对应 v2.10.0 收口项：
  - HIGH#1（C-10 域部分闭合）：script: 域（C-10 主威胁面）基线补签名锚后，攻击者「改文件 + 重记基线
    （伪造 _anchor_sig）」须被 verify_integrity 检出（fail-closed）；合法重基线（持真实锚）仍 PASS。
  - HIGH#2（旧链容忍诚实化 → v2.11.0 H-C 收口为 fail-closed）：首条缺 epoch 的旧审计链在 v2.11.0 起
    容忍期已过 → 结构合法但 HMAC 全伪也 fail-closed（杜绝永久降级信任底线，Hermes r7 H-C）；「结构畸形
    （hmac 非字符串）」始终 fail-closed。cutoff 覆盖为 (2,19) 时仍演示旧链容忍（过渡期语义保留）。
  - HIGH#3（epoch 逐条校验）：首条带 epoch=v290 进入严格校验后，中段注入缺 epoch 伪造条目 → fail-closed
    （migration / rollback 两条链同测）。
  - MED#1（账本锚生产护栏）：默认（共享）锚在无 METACOG_TRUST_ROOT_ALLOW_DEFAULT 时
    _resolve_anchor_key 抛 LedgerAnchorDefaultError（fail-closed）；设置专属锚或 ALLOW_DEFAULT 后不抛。

零第三方依赖，import metacog 直接单测。
"""
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

import hashlib
import hmac as _hmac
import json
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
                                    " - " + detail if detail else ""))

    def summary(self):
        total = self.passed + self.failed
        print("\n{}".format("=" * 60))
        print("v2.10.0 r7 收口回归测试结果: {}/{} PASS".format(self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _new_store():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2100_"))
    root = tmp / ".metacog"
    st = metacog.Store(root)
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


def _sign_audit(st, entry):
    """复刻 _record_migration_audit / _audit_rollback 的 HMAC 签名（payload 排除 hmac 字段）。"""
    key = metacog._audit_hmac_key(st)
    payload = json.dumps(entry, separators=(",", ":"), sort_keys=True)
    return _hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _write_audit_jsonl(st, name, entries):
    """name in {'migration-audit.jsonl','rollback-audit.jsonl'}；entries: 已带 hmac 的 dict 列表。"""
    p = st.root / "ledger" / name
    with p.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, separators=(",", ":"), sort_keys=True) + "\n")


# ----------------------------------------------------------------- HIGH#1：script: 域篡改 + 重记基线检出
def test_r7_script_tamper(r):
    """v2.10.0（HIGH#1 / C-10）：script: 基线签名锚补完后，攻击者改文件并重记基线（伪造 _anchor_sig）
    必须被 verify_integrity 检出（fail-closed）；合法基线（持真实锚签名）仍 PASS。"""
    st, tmp = _new_store()
    try:
        # 临时把 dummy 脚本纳入 SCRIPT_NAMES，验证 record_script_integrity 实际写入 _anchor_sig（HIGH#1 写侧）。
        _orig = metacog.Store.SCRIPT_NAMES
        metacog.Store.SCRIPT_NAMES = ("v2100_dummy.py",)
        _f = st.script_dir / "v2100_dummy.py"
        _f.parent.mkdir(parents=True, exist_ok=True)
        _f.write_text("print('hello')\n", encoding="utf-8")
        st.record_script_integrity()
        data = metacog.read_json(st.integrity, {})
        rec = data.get("script:v2100_dummy.py")
        r.add("record_script_integrity 为 script: 域写入 _anchor_sig",
              isinstance(rec, dict) and isinstance(rec.get("_anchor_sig"), str) and len(rec["_anchor_sig"]) == 64,
              "rec={}".format("missing" if rec is None else "ok"))

        # 合法：当前文件未被篡改 → verify 通过
        rows = st.verify_integrity()
        _hit = [x for x in rows if x[0] == "script:v2100_dummy.py"]
        r.add("合法 script: 基线 verify==True",
              len(_hit) == 1 and _hit[0][1] is True, "rows={}".format(_hit))

        # 攻击者：改文件内容 + 在 integrity.json 重写 hash 并伪造 _anchor_sig（随机 64-hex，无密钥）
        _f.write_text("print('pwned by attacker')\n", encoding="utf-8")
        _new_hash = st._hash_text(_f.read_text(encoding="utf-8"))
        _forged = {"hash": _new_hash, "size": _f.stat().st_size, "at": "2026-10-12T00:00:00Z",
                   "_anchor_sig": "0" * 64}
        data2 = metacog.read_json(st.integrity, {})
        data2["script:v2100_dummy.py"] = _forged
        metacog.write_json(st.integrity, data2)

        rows2 = st.verify_integrity()
        _hit2 = [x for x in rows2 if x[0] == "script:v2100_dummy.py"]
        r.add("攻击者改文件+伪造签名 → verify==False（fail-closed）",
              len(_hit2) == 1 and _hit2[0][1] is False, "rows={}".format(_hit2))
        metacog.Store.SCRIPT_NAMES = _orig
    finally:
        pass


# ----------------------------------------------------------------- HIGH#2：旧链容忍诚实边界（v2.11.0 收口为 fail-closed）
def test_r7_old_chain(r):
    """v2.11.0（HIGH#2 / H-C 收口）：首条缺 epoch 的旧审计链——
    (a) 结构合法但 HMAC 全伪 → 在 CURRENT >= LEGACY_AUDIT_CHAIN_CUTOFF 后 fail-closed（False，杜绝永久降级）；
        过渡演示：cutoff 覆盖为 (2,19) 时仍容忍（True），证明 tolerance 仅在该截止期前生效；
    (b) 结构畸形（hmac 非字符串）→ 始终 fail-closed（False）。"""
    st, tmp = _new_store()
    try:
        # (a) 结构合法 + HMAC 全伪的旧链 → v2.11.0 起 fail-closed
        _lines_a = [
            {"at": "t0", "operation": "op", "prev_hmac": "", "hmac": "0" * 64},
            {"at": "t1", "operation": "op", "prev_hmac": "0" * 64, "hmac": "0" * 64},
        ]
        _write_audit_jsonl(st, "migration-audit.jsonl", _lines_a)
        _ok_a, _cnt_a = st._verify_migration_audit()
        r.add("v2.11.0 旧链（首条无 epoch，HMAC 全伪）结构合法→fail-closed False [H-C 收口]",
              _ok_a is False and _cnt_a == 2, "ok={} cnt={}".format(_ok_a, _cnt_a))
        # 过渡演示：截止期前（cutoff=(2, 26)）仍容忍
        _ok_a_t, _cnt_a_t = st._verify_migration_audit(cutoff=(2, 26))
        r.add("截止期前(cutoff=2,23) 旧链结构合法→容忍 True（过渡演示）",
              _ok_a_t is True and _cnt_a_t == 2, "ok={} cnt={}".format(_ok_a_t, _cnt_a_t))

        # (b) 结构畸形（hmac 非字符串）→ fail-closed
        _lines_b = [
            {"at": "t0", "operation": "op", "prev_hmac": "", "hmac": 12345},
        ]
        _write_audit_jsonl(st, "migration-audit.jsonl", _lines_b)
        _ok_b, _cnt_b = st._verify_migration_audit()
        r.add("旧链结构畸形（hmac 非字符串）→ fail-closed False",
              _ok_b is False, "ok={}".format(_ok_b))
    finally:
        pass


# ----------------------------------------------------------------- HIGH#3：中段缺 epoch → fail-closed
def test_r7_midchain_epoch(r):
    """v2.10.0（HIGH#3）：首条带 epoch=v290 进入严格校验后，中段注入缺 epoch 伪造条目 → fail-closed。
    两条审计链（migration / rollback）同测。"""
    st, tmp = _new_store()
    try:
        # 构造 3 条有效链：第 0、2 条带 epoch=v290，第 1 条缺 epoch（模拟注入伪造）。
        def _build():
            _entries = []
            _prev = ""
            for i in range(3):
                _e = {"at": "t%d" % i, "operation": "op", "event": "e", "src": "s",
                      "dst": "d", "detail": "x", "prev_hmac": _prev}
                if i != 1:
                    _e["epoch"] = metacog.LEDGER_KEY_EPOCH
                # i==1 不写 epoch（缺 epoch 注入）
                _h = _sign_audit(st, _e)
                _e["hmac"] = _h
                _entries.append(_e)
                _prev = _h
            return _entries

        # migration 链
        _m = _build()
        _write_audit_jsonl(st, "migration-audit.jsonl", _m)
        _ok_m, _cnt_m = st._verify_migration_audit()
        r.add("migration 链中段缺 epoch → fail-closed False",
              _ok_m is False, "ok={} cnt={}".format(_ok_m, _cnt_m))

        # rollback 链（结构同构，含 epoch / confirmed 字段）
        _rb = []
        _prev = ""
        for i in range(3):
            _e = {"at": "t%d" % i, "operation": "rollback-rebaseline", "artifact": "A1",
                  "entry_id": "x", "old_hash": "o", "new_hash": "n", "confirmed": True,
                  "prev_hmac": _prev}
            if i != 1:
                _e["epoch"] = metacog.LEDGER_KEY_EPOCH
            _h = _sign_audit(st, _e)
            _e["hmac"] = _h
            _rb.append(_e)
            _prev = _h
        _write_audit_jsonl(st, "rollback-audit.jsonl", _rb)
        _ok_r, _cnt_r = metacog._verify_audit_chain(st)
        r.add("rollback 链中段缺 epoch → fail-closed False",
              _ok_r is False, "ok={} cnt={}".format(_ok_r, _cnt_r))

        # 对照：全链均带 epoch=v290 且 HMAC 有效 → True（证明严格链本身合法）
        _good = []
        _prev = ""
        for i in range(2):
            _e = {"at": "t%d" % i, "operation": "op", "event": "e", "src": "s",
                  "dst": "d", "detail": "x", "epoch": metacog.LEDGER_KEY_EPOCH,
                  "prev_hmac": _prev}
            _h = _sign_audit(st, _e)
            _e["hmac"] = _h
            _good.append(_e)
            _prev = _h
        _write_audit_jsonl(st, "migration-audit.jsonl", _good)
        _ok_g, _cnt_g = st._verify_migration_audit()
        r.add("migration 链全带 epoch 且 HMAC 有效 → True（对照）",
              _ok_g is True and _cnt_g == 2, "ok={} cnt={}".format(_ok_g, _cnt_g))
    finally:
        pass


# ----------------------------------------------------------------- MED#1：默认锚无 ALLOW_DEFAULT → fail-closed
def test_r7_default_anchor_guard(r):
    """v2.10.0（MED#1）：默认（共享）锚在无 METACOG_TRUST_ROOT_ALLOW_DEFAULT 时 _resolve_anchor_key
    抛 LedgerAnchorDefaultError（fail-closed）；设专属锚或 ALLOW_DEFAULT 后不抛。"""
    _orig_allow = _os.environ.get("METACOG_TRUST_ROOT_ALLOW_DEFAULT")
    _orig_key = _os.environ.get("METACOG_TRUST_ROOT_ANCHOR_KEY")
    try:
        # 模拟生产：默认锚 + 无 ALLOW_DEFAULT → 抛错
        _os.environ.pop("METACOG_TRUST_ROOT_ALLOW_DEFAULT", None)
        _os.environ.pop("METACOG_TRUST_ROOT_ANCHOR_KEY", None)
        _raised = False
        try:
            metacog._resolve_anchor_key()
        except metacog.LedgerAnchorDefaultError:
            _raised = True
        r.add("默认锚无 ALLOW_DEFAULT → 抛 LedgerAnchorDefaultError（fail-closed）", _raised)

        # 设 ALLOW_DEFAULT=1 → 不抛（本地开发/测试承担风险）
        _os.environ["METACOG_TRUST_ROOT_ALLOW_DEFAULT"] = "1"
        _raised2 = False
        try:
            metacog._resolve_anchor_key()
        except metacog.LedgerAnchorDefaultError:
            _raised2 = True
        r.add("设 ALLOW_DEFAULT=1 → 不抛（本地开发模式）", not _raised2)

        # 设专属锚（覆盖默认）→ 不抛（生产正确配置）
        _os.environ.pop("METACOG_TRUST_ROOT_ALLOW_DEFAULT", None)
        _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = _hmac.new(b"prod-secret", b"x", hashlib.sha256).digest().hex()
        _raised3 = False
        try:
            metacog._resolve_anchor_key()
        except metacog.LedgerAnchorDefaultError:
            _raised3 = True
        r.add("设专属 METACOG_TRUST_ROOT_ANCHOR_KEY → 不抛（生产配置）", not _raised3)
    finally:
        # 还原环境变量（不影响其它测试 / 运行器注入的 ALLOW_DEFAULT）
        for _k in ("METACOG_TRUST_ROOT_ALLOW_DEFAULT", "METACOG_TRUST_ROOT_ANCHOR_KEY"):
            _os.environ.pop(_k, None)
        if _orig_allow is not None:
            _os.environ["METACOG_TRUST_ROOT_ALLOW_DEFAULT"] = _orig_allow
        if _orig_key is not None:
            _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = _orig_key


def main():
    r = T()
    test_r7_script_tamper(r)
    test_r7_old_chain(r)
    test_r7_midchain_epoch(r)
    test_r7_default_anchor_guard(r)
    ok = r.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
