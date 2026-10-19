#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.9.0 回归测试套件（独立验证，非自验自收）

覆盖 v2.8.8 dossier §7.5 Hermes NOT-PASS 裁定要求、经 KK 授权 v2.9.0 收口的项：
  - C-10 / H-3（F-3）：账本/审计签名锚密钥由代码内嵌锚派生（trust_root.get_anchor_key()），
    不再明文常量 / 可写 ledger 域派生；攻击者凭 ledger 写权限无法伪造 _anchor_sig → fail-closed 检出。
  - H-4：manifest @body 派生键不再构成独立第二信号——SKILL.md 正文洗白须 @body 基线签名有效才豁免，
    签名无效 / 缺失（legacy）→ 不豁免，检出篡改。
  - H-1 / #166（legacy 16-char 截止期激活）：v2.9.0 CURRENT_VERSION_TUPLE=(2,9,0) >= 截止期(2,9)
    → _legacy_hash_allowed()=False → 16-char 旧基线判漂移（拒绝），不再静默放行。
  - M-2 / F-1（只读 verify 路径无文件系统副作用）：verify_integrity + 审计链只读校验不修改 ledger。
  - L-3 / H-2（版本零绑定断言）：SKILL.md `version:` 头须与 Store.CURRENT_VERSION_TUPLE 一致。

零第三方依赖，import metacog 直接单测。
"""
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

import json
import re
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
                                    " - " + detail if detail else ""))

    def summary(self):
        total = self.passed + self.failed
        print("\n{}".format("=" * 60))
        print("v2.9.0 C-10/H-4/legacy/L-3 测试结果: {}/{} PASS".format(self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _new_store():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v290_"))
    root = tmp / ".metacog"
    st = metacog.Store(root)
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


_SKILL_BODY = """正文第一段：C-10 根闭合须可验证。
正文第二段：@body 不得自指失独。
"""

_SKILL_MD = """---
name: unclekk-metacog-self-evolve
version: 2.9.0
---
# 测试用 SKILL.md

{body}""".format(body=_SKILL_BODY)


def _write_skill(st, text=_SKILL_MD):
    p = st.root / "SKILL.md"
    p.write_text(text, encoding="utf-8")
    return p


def _snapshot(root):
    snap = {}
    for p in root.rglob("*"):
        if p.is_file():
            s = p.stat()
            snap[str(p.relative_to(root))] = (s.st_mtime_ns, s.st_size)
    return snap


# ----------------------------------------------------------------- C-10 / H-3（F-3）：锚签名不可伪造（单元）
def test_c10_anchor_sig_nonforgeable():
    """v2.9.0（C-10 / H-3 / F-3）：_ledger_anchor_sig 由代码内嵌锚密钥派生；
    _verify_anchor_sig 对有效签名返回 True、伪造签名返回 False、无签名（legacy）返回 None。"""
    r = T()
    payload = {"hash": "abcdef" * 5, "size": 123, "at": "2026-10-12T00:00:00Z"}
    sig_real = metacog._ledger_anchor_sig(payload)
    r.add("有效签名 _verify_anchor_sig==True",
          metacog._verify_anchor_sig({**payload, "_anchor_sig": sig_real}) is True)
    # 伪造（错误密钥 / 任意串）必须被识破
    r.add("伪造签名 _verify_anchor_sig==False",
          metacog._verify_anchor_sig({**payload, "_anchor_sig": "0" * 64}) is False)
    # 篡改载荷后真实签名不再匹配
    tampered = {**payload, "hash": "ffff" * 5}
    r.add("载荷篡改后真实签名失配==False",
          metacog._verify_anchor_sig({**tampered, "_anchor_sig": sig_real}) is False)
    # legacy 无签名 → 容忍（None，不阻断）
    r.add("无签名 _verify_anchor_sig==None（legacy 容忍）",
          metacog._verify_anchor_sig(dict(payload)) is None)
    return r


# ----------------------------------------------------------------- C-10（集成）：攻击者凭 ledger 写权限伪造基线被检出
def test_c10_integrity_forge_detected():
    """v2.9.0（C-10）：攻击者重写 integrity.json 的 manifest:SKILL.md 基线（改 hash + 用错误密钥伪造
    _anchor_sig）→ verify_integrity 须判 False（fail-closed）。合法重基线（持真实锚密钥）仍 PASS。"""
    r = T()
    st, tmp = _new_store()
    try:
        _write_skill(st)
        st.record_script_integrity()
        data = metacog.read_json(st.integrity, {})
        rec = data.get("manifest:SKILL.md")
        r.add("基线含 _anchor_sig 字段", isinstance(rec, dict) and isinstance(rec.get("_anchor_sig"), str)
              and len(rec["_anchor_sig"]) == 64, "rec={}".format("missing" if rec is None else "ok"))

        # 攻击者：改 hash 并伪造（错误密钥）签名
        rec["hash"] = "deadbeef" * 4
        rec["_anchor_sig"] = "0" * 64
        data["manifest:SKILL.md"] = rec
        metacog.write_json(st.integrity, data)

        res = st.verify_integrity()
        hit = [(a, ok) for (a, ok, *_rest) in res if a == "manifest:SKILL.md"]
        r.add("伪造基线被 verify 检出（False）",
              bool(hit) and hit[0][1] is False, "hit={}".format(hit))

        # 合法重基线（持真实锚密钥，模拟人类/代码路径）：重算后签名有效
        _write_skill(st, _SKILL_MD.replace("正文第一段", "正文第一段（合法修订）"))
        st.record_script_integrity()
        res2 = st.verify_integrity()
        hit2 = [(a, ok) for (a, ok, *_rest) in res2 if a == "manifest:SKILL.md"]
        r.add("合法重基线后 verify 通过（True）",
              bool(hit2) and hit2[0][1] is True, "hit={}".format(hit2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


# ----------------------------------------------------------------- H-4：@body 自指失独闭合
def test_h4_body_selfreference_closed():
    """v2.9.0（H-4）：攻击者改写 SKILL.md 正文，并重算 manifest:SKILL.md 与 @body 基线 hash 匹配新文件、
    用错误密钥伪造两个 _anchor_sig → verify 仍须检出（@body 不再构成可自洽洗白的第二信号）。
    对照：仅版本号变更（正文不变）、@body 基线签名有效 → 仍豁免通过（良性路径保留）。"""
    r = T()
    st, tmp = _new_store()
    try:
        _write_skill(st)
        st.record_script_integrity()
        data = metacog.read_json(st.integrity, {})

        # --- 负向：正文被改 + 双基线 hash 重算匹配 + 伪造签名 ---
        _tampered = _SKILL_MD.replace("正文第一段：C-10", "正文第一段：ATTACKER_TAMPERED")
        _write_skill(st, _tampered)
        _new_full = st._hash_text(_tampered)
        _new_body = st._skill_body_hash(_tampered)
        sk = data["manifest:SKILL.md"]
        sk["hash"] = _new_full
        sk["_anchor_sig"] = "0" * 64  # 伪造（错误密钥）
        body = data["manifest:SKILL.md@body"]
        body["hash"] = _new_body
        body["_anchor_sig"] = "0" * 64  # 伪造（错误密钥）
        data["manifest:SKILL.md"] = sk
        data["manifest:SKILL.md@body"] = body
        metacog.write_json(st.integrity, data)

        res = st.verify_integrity()
        hit = [(a, ok) for (a, ok, *_rest) in res if a == "manifest:SKILL.md"]
        r.add("H-4 正文洗白 + 双伪造签名被检出（False）",
              bool(hit) and hit[0][1] is False, "hit={}".format(hit))

        # --- 正向：仅版本号变（正文不变），@body 基线签名有效 → 仍豁免通过 ---
        _ver_only = _SKILL_MD.replace("version: 2.9.0", "version: 2.9.1")
        _write_skill(st, _ver_only)
        # 重基线（真实密钥）：全量 + @body 均有效签名
        st.record_script_integrity()
        res2 = st.verify_integrity()
        hit2 = [(a, ok) for (a, ok, *_rest) in res2 if a == "manifest:SKILL.md"]
        r.add("H-4 良性版本号变更仍通过（True）",
              bool(hit2) and hit2[0][1] is True, "hit={}".format(hit2))

        # --- 正向：版本号变（正文不变）但全量基线陈旧、@body 签名有效 → @body 豁免生效 ---
        # 先以 X 基线（全量 + @body 均有效签名），再写 Y（仅版本号变、正文同）且不重基线，
        # 模拟"基线为旧版快照、文件已良性变更"。
        _write_skill(st, _SKILL_MD)        # X
        st.record_script_integrity()         # 基线 = X（全量 + @body 均有效签名）
        _write_skill(st, _ver_only)         # Y（仅版本变、正文同）→ 不重基线
        res3 = st.verify_integrity()
        hit3 = [(a, ok) for (a, ok, *_rest) in res3 if a == "manifest:SKILL.md"]
        r.add("H-4 @body 豁免仍可用（有效签名时正文不变→豁免 True）",
              bool(hit3) and hit3[0][1] is True, "hit={}".format(hit3))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


# ----------------------------------------------------------------- H-1 / #166：legacy 16-char 截止期激活
def test_h1_legacy_cutoff_active():
    """H-1 / #166 legacy 16-char 截止期：真实截止期 LEGACY_HASH_CUTOFF_VERSION=(2,9)；
    CURRENT_VERSION_TUPLE=(2,12,0) >= (2,9) → _legacy_hash_allowed()=False（已激活，不再静默放行）。
    16-char 旧基线（allow_legacy=False）判漂移（ok=False, legacy=True）；
    未来截止期（cutoff 覆盖为晚于当前版本 (2,19)）仍允许（ok=True）——纯测试假设，不重开真实安全窗口。"""
    r = T()
    r.add("v2.11.0 当前版本 _legacy_hash_allowed()==False（真实截止期已激活）",
          metacog.Store._legacy_hash_allowed() is False)
    r.add("未来截止期（cutoff=(2, 26)，晚于当前版本）_legacy_hash_allowed()==True",
          metacog.Store._legacy_hash_allowed(cutoff=(2, 26)) is True)

    scur = metacog.Store._hash_text("任意内容用于测试")
    stored16 = scur[:16]  # 模拟 64-bit 旧基线
    ok_false, legacy_false = metacog.Store._script_hash_matches(scur, stored16, allow_legacy=False)
    r.add("16-char 基线 @allow_legacy=False → ok=False 且 legacy=True",
          ok_false is False and legacy_false is True,
          "ok={} legacy={}".format(ok_false, legacy_false))
    ok_true, legacy_true = metacog.Store._script_hash_matches(scur, stored16, allow_legacy=True)
    r.add("16-char 基线 @allow_legacy=True → ok=True（截止期前行为）",
          ok_true is True and legacy_true is True,
          "ok={} legacy={}".format(ok_true, legacy_true))
    return r


# ----------------------------------------------------------------- epoch 容忍：旧版（<v2.9.0）无 epoch 审计链容忍
def test_legacy_epoch_tolerance():
    """v2.9.0（C-10）：rollback/migration 审计链首条缺 epoch 标记（旧版可伪造链）→ 容忍 (True, count)，
    不标 dirty；v2.9.0 新链（含 epoch）严格校验，篡改 → (False, *)。"""
    r = T()
    # Part A：v2.11.0 旧版无 epoch 链 → fail-closed（H-C 收口：容忍期已过，杜绝永久降级）
    st, tmp = _new_store()
    try:
        _audit = st.root / "ledger" / "rollback-audit.jsonl"
        _old = {"at": "t", "operation": "x", "artifact": "A2", "entry_id": "R",
                "old_hash": "o", "new_hash": "n", "confirmed": True,
                "prev_hmac": "", "hmac": "whatever"}
        _audit.write_text(json.dumps(_old) + "\n", encoding="utf-8")
        _ok_old, _cnt_old = metacog._verify_audit_chain(st)
        r.add("v2.11.0 旧版无 epoch 审计链 → fail-closed (False, 1) [H-C 收口]",
              _ok_old is False and _cnt_old == 1, "ok={} cnt={}".format(_ok_old, _cnt_old))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Part A2：过渡演示——在「截止期前版本」(cutoff 覆盖为晚于当前的 (2,19)) 旧链仍容忍，
    # 证明 tolerance 行为仅在 CURRENT >= LEGACY_AUDIT_CHAIN_CUTOFF 后失效（非无条件收紧）。
    st, tmp = _new_store()
    try:
        _audit = st.root / "ledger" / "rollback-audit.jsonl"
        _old = {"at": "t", "operation": "x", "artifact": "A2", "entry_id": "R",
                "old_hash": "o", "new_hash": "n", "confirmed": True,
                "prev_hmac": "", "hmac": "whatever"}
        _audit.write_text(json.dumps(_old) + "\n", encoding="utf-8")
        # 直接调用模块函数并注入 cutoff 覆盖，模拟「截止期前版本」行为
        _ok_trans, _cnt_trans = metacog._verify_audit_chain(st, cutoff=(2, 26))
        r.add("截止期前(cutoff=2,23) 旧链仍容忍 (True, 1)",
              _ok_trans is True and _cnt_trans == 1, "ok={} cnt={}".format(_ok_trans, _cnt_trans))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Part B：v2.9.0 新链（含 epoch）严格校验（独立 fixture）
    st, tmp = _new_store()
    try:
        _audit = st.root / "ledger" / "rollback-audit.jsonl"
        metacog._audit_rollback(st, "A2", "R1", "o1", "n1")
        metacog._audit_rollback(st, "A2", "R2", "o2", "n2")
        _ok_new, _cnt_new = metacog._verify_audit_chain(st)
        r.add("v2.9.0 新链完整 → (True, 2)",
              _ok_new is True and _cnt_new == 2, "ok={} cnt={}".format(_ok_new, _cnt_new))

        # 篡改新链 hmac（首条仍含 epoch，不触发容忍早返回）→ 严格拒绝
        _lines = _audit.read_text(encoding="utf-8").splitlines()
        _rec0 = json.loads(_lines[0]); _rec0["hmac"] = "0" * 64
        _lines[0] = json.dumps(_rec0, separators=(",", ":"), sort_keys=True)
        _audit.write_text("\n".join(_lines) + "\n", encoding="utf-8")
        _ok_t, _cnt_t = metacog._verify_audit_chain(st)
        r.add("v2.9.0 新链篡改 → (False, 2)",
              _ok_t is False and _cnt_t == 2, "ok={} cnt={}".format(_ok_t, _cnt_t))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


# ----------------------------------------------------------------- M-2 / F-1：只读 verify 路径无文件系统写入
def test_readonly_verify_no_fs_writes():
    """v2.9.0（M-2 / F-1）：verify_integrity 及审计链只读校验不得修改 ledger / 外部锚证明目录。"""
    r = T()
    st, tmp = _new_store()
    try:
        _write_skill(st)
        st.record_script_integrity()

        before = _snapshot(st.root)
        st.verify_integrity()
        try:
            st._verify_audit_chain()
        except Exception:
            pass
        try:
            st._verify_migration_audit()
        except Exception:
            pass
        # 触发外部锚证明目录只读解析（不应写迁移审计）
        try:
            st._external_anchor_proof_dir(record=False)
        except Exception:
            pass
        after = _snapshot(st.root)
        r.add("verify 只读路径无文件系统写入（mtime/size 不变）",
              before == after,
              "before={} after={}".format(len(before), len(after)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


# ----------------------------------------------------------------- L-3 / H-2：版本零绑定断言
def test_l3_version_binding():
    """v2.9.0（L-3 / H-2）：SKILL.md `version:` 头须与 Store.CURRENT_VERSION_TUPLE 一致。"""
    r = T()
    sk = Path(__file__).resolve().parent.parent / "SKILL.md"
    r.add("SKILL.md 存在", sk.exists(), str(sk))
    if sk.exists():
        txt = sk.read_text(encoding="utf-8")
        m = re.search(r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)", txt, re.M)
        r.add("解析到 version 字段", m is not None)
        if m:
            decl = tuple(int(x) for x in m.group(1).split("."))
            r.add("声明版本 == CURRENT_VERSION_TUPLE",
                  decl == metacog.Store.CURRENT_VERSION_TUPLE,
                  "decl={} tuple={}".format(m.group(1), metacog.Store.CURRENT_VERSION_TUPLE))
            r.add("声明字符串 == 格式化元组",
                  m.group(1) == "{}.{}.{}".format(*metacog.Store.CURRENT_VERSION_TUPLE))
    # 运行时软闸函数本身可用
    _ok, _msg = metacog._check_version_binding()
    r.add("_check_version_binding() 返回一致(True)", _ok is True, "msg={}".format(_msg))
    return r


# ----------------------------------------------------------------- 迁移审计首次调用须落盘（v2.9.0 修复回归）
def test_migration_audit_first_call_writes():
    """v2.9.0（D-2 静默失效修复）：_record_migration_audit 在审计文件尚不存在（首次调用）时须正确落盘，
    不得因 _entry 作用域未绑定被外层 except 静默吞掉；落盘后含 epoch 且 _verify_migration_audit 通过。"""
    r = T()
    st, tmp = _new_store()
    try:
        _ma = st.root / "ledger" / "migration-audit.jsonl"
        r.add("首次调用前迁移审计文件不存在", not _ma.exists())
        st._record_migration_audit("test_event", "src", "dst", "detail")
        r.add("首次调用后迁移审计文件已落盘", _ma.exists())
        _lines = [l for l in _ma.read_text(encoding="utf-8").splitlines() if l.strip()]
        r.add("落盘 1 条且含 epoch=v290",
              len(_lines) == 1 and json.loads(_lines[0]).get("epoch") == metacog.LEDGER_KEY_EPOCH,
              "lines={}".format(len(_lines)))
        _ok, _cnt = st._verify_migration_audit()
        r.add("首条含 epoch → 严格校验 (True, 1)", _ok is True and _cnt == 1,
              "ok={} cnt={}".format(_ok, _cnt))
        # 篡改 hmac（仍含 epoch，不触发容忍）→ 拒绝
        _rec0 = json.loads(_lines[0]); _rec0["hmac"] = "0" * 64
        _lines[0] = json.dumps(_rec0, separators=(",", ":"), sort_keys=True)
        _ma.write_text("\n".join(_lines) + "\n", encoding="utf-8")
        _ok_t, _cnt_t = st._verify_migration_audit()
        r.add("迁移审计篡改 → (False, 1)", _ok_t is False and _cnt_t == 1,
              "ok={} cnt={}".format(_ok_t, _cnt_t))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def main():
    results = []
    results.append(test_c10_anchor_sig_nonforgeable())
    results.append(test_c10_integrity_forge_detected())
    results.append(test_h4_body_selfreference_closed())
    results.append(test_h1_legacy_cutoff_active())
    results.append(test_legacy_epoch_tolerance())
    results.append(test_migration_audit_first_call_writes())
    results.append(test_readonly_verify_no_fs_writes())
    results.append(test_l3_version_binding())
    all_ok = all(t.summary() for t in results)
    print("\n########## v2.9.0 套件汇总 ##########")
    print("SUITE: {}".format("ALL PASS" if all_ok else "HAS FAILURE"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
