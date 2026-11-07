#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.27.0（Hermes 六轮复验 R-1/R-2/R-3 收口）对抗回归测试套件（独立验证，非自验自收）

R-1 [MEDIUM]：真实 keygen 后删 human-guard.json + 删 integrity.json GUARD 域记录 → verify 静默通过
  （人类签名信任根可被静默替换）。
  v2.27.0 收口：引入「应有基线集」——keygen 后 GUARD 基线**无条件必存在**（与文件是否在场无关），
  删基线键即 dirty；且钉固公钥漂移检查（R-3）无条件化，删基线+写入攻击者公钥+重记基线仍检出。

R-2 [MEDIUM]：verify_integrity 无「应有基线集」概念——删 manifest:CONTRACT.md 基线键 + 篡改正文
  → dirty=[]（删键即从检测集消失，盲区可扩展全域）。
  v2.27.0 收口：keygen 后凡磁盘存在的受跟踪文件（manifest:/script:/核心制品）其基线键必须存在，
  删键即 dirty。

R-3 [MEDIUM]：钉固公钥漂移检查嵌套在「链指纹失败」条件块内（与 H-2b' 同构）——方案B 通过时
  该检测不可达，删 GUARD 基线+写入攻击者公钥+重记基线 → verify rc=0。
  v2.27.0 收口：钉固公钥漂移检查移出嵌套块、无条件执行。

逃逸前提口径（诚实边界，与 v2.26.0 自举残余一致）：持代码+文件写权的完全失控 Agent 仍可能
「删两者（human-guard.json + 基线）+ 改制品 + 经引擎 API 重算基线 + 追加合法 mac 条目（链头不动）」
——本套件测的是「删键逃逸」与「公钥漂移」两类独立可检出面，自举残余须系统级部署契约兜底。

零第三方依赖。锚点定向临时文件，不污染真实树外锚。
"""
import io
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# 本地测试环境：默认锚显式承担 + legacy 逃生舱 + 隔离冻结锚
_os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"
_os.environ["METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"] = "1"
_os.environ["METACOG_FREEZE_ANCHOR"] = str(
    Path(tempfile.gettempdir()) / "metacog_v2270_test_anchor.anchor")

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

    def summary(self, title):
        total = self.passed + self.failed
        print("\n{}".format("=" * 60))
        print("{}: {}/{} PASS".format(title, self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _with_tty_and_passphrase(pw):
    """模拟人类在 TTY 交互：替换 _require_tty、getpass 与 builtins.input。返回还原函数。"""
    old_tty, old_gp = metacog._require_tty, metacog.getpass.getpass
    old_in = metacog.builtins.input
    metacog._require_tty = lambda: True
    metacog.getpass.getpass = lambda prompt="": pw
    metacog.builtins.input = lambda prompt="": "YES"

    def restore():
        metacog._require_tty = old_tty
        metacog.getpass.getpass = old_gp
        metacog.builtins.input = old_in
    return restore


def _keygen_ns(tmp):
    nonce = Path(tmp) / "keygen_nonce.txt"
    nonce.write_text("offline-auth-nonce-v2270-9f3c2a7b", encoding="utf-8")
    return SimpleNamespace(keygen=True, init=False, approve=False, id=None,
                           nonce_file=str(nonce), enable_external=None,
                           attestation_path="", oob_token_dir="",
                           root_pubkey="", root_privkey="",
                           purge_external_anchor=False)


def _run(fn, *a):
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = fn(*a)
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


def _new_store_keygenned(pw="test-passphrase-v2270-1234"):
    """建临时 store + init + 创建 5 个 manifest 桩文件 + keygen（模拟 TTY）。

    注意：Store 根目录为 tmp/.metacog（self.root），manifest 桩文件须写在 self.root 下，
    record_script_integrity 才基线化它们（贴近真实安装）。"""
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2270_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    # 创建 MANIFEST_NAMES 桩文件（写在 self.root 下），使 keygen 基线化它们
    for _name in st.MANIFEST_NAMES:
        (_p := st.root / _name)
        if _name == "SKILL.md":
            _p.write_text("---\nname: stub\nslug: stub\nversion: 9.99.9\n---\nbody\n", encoding="utf-8")
        else:
            _p.write_text("# stub {}\n".format(_name), encoding="utf-8")
    restore = _with_tty_and_passphrase(pw)
    try:
        rc, _ = _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
    finally:
        restore()
    return st, tmp, rc


def _integrity_keys(st):
    return set(metacog.read_json(st.integrity, {}).keys())


def test_r1_guard_baseline_deletion():
    """R-1：删 human-guard.json + 删 GUARD 基线键 → verify_integrity 应报 GUARD 基线缺失 dirty。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        r.add("keygen 成功", rc == 0, "rc={}".format(rc))
        r.add("keygen 后已建立完整基线（_keygen_established）",
              st._keygen_established() is True)
        r.add("keygen 后 GUARD 基线存在", metacog.Store.GUARD_INTEGRITY_KEY in _integrity_keys(st))
        r.add("keygen 后 manifest:CONTRACT.md 基线存在",
              "manifest:CONTRACT.md" in _integrity_keys(st))
        # 干净态 verify rc=0
        rc0, _ = _run(metacog.cmd_verify, st, SimpleNamespace())
        r.add("干净态 verify rc=0", rc0 == 0, "rc={}".format(rc0))

        # —— R-1 攻击：删 human-guard.json + 删 GUARD 基线键 ——
        st.human_guard.unlink(missing_ok=True)
        data = metacog.read_json(st.integrity, {})
        data.pop(metacog.Store.GUARD_INTEGRITY_KEY, None)
        metacog.write_json(st.integrity, data)

        rows = st.verify_integrity()
        guard_missing = any(a == metacog.Store.GUARD_INTEGRITY_KEY and (not ok)
                            for a, ok, _, _ in rows)
        r.add("R-1 删 GUARD 基线键 → verify_integrity 报 GUARD 缺失 dirty", guard_missing)

        rc1, out1 = _run(metacog.cmd_verify, st, SimpleNamespace())
        r.add("R-1 删 GUARD 基线键 → verify rc=1（不再静默通过）", rc1 == 1, "rc={}".format(rc1))
        r.add("R-1 verify 输出含基线缺失提示", "基线记录缺失" in out1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_r1_continuation_key_swap():
    """R-1 续 + R-3：删 GUARD 基线 + 写入攻击者公钥 + record_guard_integrity 重记基线
    → 方案B 通过（链/钉固节未动），但钉固公钥漂移检查（R-3 无条件化）应检出 rc=1。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        # 记录钉固公钥指纹（CONTRACT.md human-identity-root）
        pinned = st.pinned_human_pubkey_fingerprint()
        r.add("钉固公钥指纹存在", bool(pinned), "pinned={}".format(pinned))

        # 删 GUARD 基线键
        data = metacog.read_json(st.integrity, {})
        data.pop(metacog.Store.GUARD_INTEGRITY_KEY, None)
        metacog.write_json(st.integrity, data)

        # 写入攻击者公钥（改 pubkey 字符串 → 指纹漂移）+ 重记基线
        guard = metacog.read_json(st.human_guard, {})
        guard["pubkey"] = guard["pubkey"] + "-ATTACKER-SWAPPED"
        metacog.write_json(st.human_guard, guard)
        st.record_guard_integrity()  # 重算基线（与攻击者文件一致）

        r.add("重记基线后 GUARD 基线存在（方案B 不拦）",
              metacog.Store.GUARD_INTEGRITY_KEY in _integrity_keys(st))
        r.add("链指纹校验仍通过（钉固节/链首未动）", st.chain_fingerprint_ok() is True)

        live = st.human_pubkey_fingerprint()
        r.add("live 公钥指纹≠钉固（已漂）", live != pinned, "live={}".format(live))

        # 修复前：该场景 verify rc=0（R-3 嵌套不可达）；修复后：R-3 无条件化 → rc=1
        rc_swap, out_swap = _run(metacog.cmd_verify, st, SimpleNamespace())
        r.add("R-3 公钥漂移无条件检出 → verify rc=1", rc_swap == 1, "rc={}".format(rc_swap))
        r.add("R-3 verify 输出含公钥漂移提示", "公钥信任根指纹漂移" in out_swap)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_r2_manifest_baseline_deletion():
    """R-2：删 manifest:CONTRACT.md 基线键 + 篡改 CONTRACT.md 正文 → verify_integrity 应报缺失 dirty。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        # —— R-2 攻击：删 manifest:CONTRACT.md 基线键 + 篡改正文 ——
        data = metacog.read_json(st.integrity, {})
        data.pop("manifest:CONTRACT.md", None)
        metacog.write_json(st.integrity, data)
        (st.root / "CONTRACT.md").write_text("# tampered contract\n", encoding="utf-8")

        rows = st.verify_integrity()
        m_missing = any(a == "manifest:CONTRACT.md" and (not ok)
                        for a, ok, _, _ in rows)
        r.add("R-2 删 manifest:CONTRACT.md 基线键 → verify_integrity 报缺失 dirty", m_missing)

        rc2, out2 = _run(metacog.cmd_verify, st, SimpleNamespace())
        r.add("R-2 删 manifest 基线键 → verify rc=1（不再 dirty=[]）", rc2 == 1, "rc={}".format(rc2))
        r.add("R-2 verify 输出含基线缺失提示", "基线记录缺失" in out2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_r2_other_manifest_keys():
    """R-2 泛化：删任一 manifest 基线键（SKILL.md/CHANGELOG.md/HANDOFF.md/pack.sh）→ 均检出 dirty。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        for _name in ("SKILL.md", "CHANGELOG.md", "HANDOFF.md", "pack.sh"):
            data = metacog.read_json(st.integrity, {})
            data.pop("manifest:" + _name, None)
            metacog.write_json(st.integrity, data)
            rows = st.verify_integrity()
            miss = any(a == "manifest:" + _name and (not ok) for a, ok, _, _ in rows)
            r.add("R-2 删 manifest:{} 基线键 → 检出 dirty".format(_name), miss)
            # 复原
            st.record_script_integrity()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_control_no_false_positive():
    """对照：未 keygen 的 init 态不误伤（无完整基线集 → 不应触发应有基线集）；keygen 后全净 rc=0。"""
    r = T()
    # 未 keygen：仅 init，无 chain-identity-root、无 GUARD 基线 → _keygen_established False
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2270_ctrl_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    r.add("未 keygen → _keygen_established False", st._keygen_established() is False)
    rows = st.verify_integrity()
    guard_dirty = any(a == metacog.Store.GUARD_INTEGRITY_KEY and (not ok) for a, ok, _, _ in rows)
    r.add("未 keygen → 不误报 GUARD 基线缺失", not guard_dirty)
    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass
    # keygen 后全净
    st2, tmp2, rc = _new_store_keygenned()
    try:
        rc_clean, _ = _run(metacog.cmd_verify, st2, SimpleNamespace())
        r.add("keygen 后全净 → verify rc=0", rc_clean == 0, "rc={}".format(rc_clean))
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)
    return r


def main():
    results = []
    results.append(test_r1_guard_baseline_deletion())
    results.append(test_r1_continuation_key_swap())
    results.append(test_r2_manifest_baseline_deletion())
    results.append(test_r2_other_manifest_keys())
    results.append(test_control_no_false_positive())
    # R-9 整改（Hermes 八轮）：原 `all(res for res in results)` 因 T 无 __bool__ 恒为 True，FAIL 被静默掩盖；
    # 改为按 failed 计数判定，任一子测试失败即整体失败并 exit!=0。
    all_ok = all(res.failed == 0 for res in results)
    print("\n" + "#" * 60)
    print("v2.27.0 R-1/R-2/R-3 套件总判定: {}".format("ALL PASS" if all_ok else "HAS FAIL"))
    print("#" * 60)
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
