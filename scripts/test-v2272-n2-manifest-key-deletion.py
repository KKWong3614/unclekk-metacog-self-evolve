#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.27.2（Hermes 八轮复验 N-2 收口）manifest 硬闸删键盲区回归测试套件（独立验证，非自验自收）

N-2 [P1 HIGH]：_manifest_integrity_drift_if_enforced 原实现对 `manifest:<name>` 基线键缺失
（`_rec is None`）直接 `continue`——攻击者删掉 integrity.json 里的 manifest 基线键（删键逃逸）
即可让 apply/resign 入口硬闸对该 manifest 失盲。
v2.27.2 复用 verify_integrity 同款 `_expected_baseline_items`：凡磁盘存在的受跟踪 manifest
其基线键缺失即计入 drift（与 R-2「应有基线集」同口径）；并以 `Store._keygen_established()` 为闸门——
仅已 keygen 安装（chain-identity-root / legacy GUARD 基线）才对缺失键计入 drift。

【八轮审计整改 R-10】：原套件用 `cmd_init`（无 keygen）建 store → `_keygen_established()` 恒为
False → 修复代码路径零覆盖（且 "删基线键→drift" 断言因闸门为假被掩的 FAIL 被 harness 吞掉）。
本版改为「真实 keygen 安装」建 store，使 N-2 删键闭路由测试真实触发；并保留「未 keygen/init 态
删光键不误报」对照，验证 `_keygen_established()` 闸门的正确性（零误伤）。

测试覆盖（真实 keygen 安装为主）：
  - A：删 manifest:CONTRACT.md 基线键（文件仍在）→ 必须计入 drift（N-2 收口·关键路径）
  - B：完整态 → 不误报（无 false positive）
  - C：manifest 键在 + 正文篡改 → 仍计入 drift（既有内容漂移检查未退化）
  - D：基线在但文件缺失 → 仍计入 drift（原「文件缺失」检查保留，未回归）
  - E（对照）：未 keygen 的 init 态删光全部 manifest 基线键 → 不误报（闸门生效，零误伤）

零第三方依赖。隔离冻结锚。
"""
import io
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

import contextlib
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# 本地测试环境：默认锚显式承担 + legacy 逃生舱 + 隔离冻结锚 + STRICT 强制硬闸
_os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"
_os.environ["METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"] = "1"
_os.environ["METACOG_TRUST_ROOT_STRICT"] = "1"
_os.environ["METACOG_FREEZE_ANCHOR"] = str(
    Path(tempfile.gettempdir()) / "metacog_v2272_n2_test_anchor.anchor")

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


@contextlib.contextmanager
def _strict_on():
    _old = _os.environ.get("METACOG_TRUST_ROOT_STRICT")
    _os.environ["METACOG_TRUST_ROOT_STRICT"] = "1"
    try:
        yield
    finally:
        if _old is None:
            _os.environ.pop("METACOG_TRUST_ROOT_STRICT", None)
        else:
            _os.environ["METACOG_TRUST_ROOT_STRICT"] = _old


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
    nonce.write_text("offline-auth-nonce-v2272-n2-3f8a9c1b", encoding="utf-8")
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


def _new_store_keygenned(pw="test-passphrase-v2272-n2-5678"):
    """建临时 store + init + keygen（模拟 TTY）→ 真实 keygen 安装（_keygen_established()=True）。
    init 不创建 SKILL.md/HANDOFF.md/CHANGELOG.md/pack.sh，此处补写桩文件使其参与基线化。"""
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2272_n2_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    for _name in metacog.Store.MANIFEST_NAMES:
        if _name == "CONTRACT.md":
            continue  # init 已创建
        _mp = st.root / _name
        if not _mp.exists():
            _mp.write_text("# 桩文件 {}\n内容占位 v2272-n2。\n".format(_name), encoding="utf-8")
    restore = _with_tty_and_passphrase(pw)
    try:
        rc, _ = _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
    finally:
        restore()
    # keygen 已基线化 manifest（record_script_integrity 纳入 MANIFEST_NAMES）；再保险一次
    st.record_script_integrity()
    return st, tmp, rc


def _new_store_init_only():
    """对照：仅 cmd_init（无 keygen）→ _keygen_established()=False。补写 manifest 桩文件并基线化。"""
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2272_n2_init_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    for _name in metacog.Store.MANIFEST_NAMES:
        _mp = st.root / _name
        if not _mp.exists():
            _mp.write_text("# 桩文件 {}\n内容占位 v2272-n2-init。\n".format(_name), encoding="utf-8")
    st.record_script_integrity()
    return st, tmp


def _delete_baseline_key(st, key):
    data = metacog.read_json(st.integrity, {})
    data.pop(key, None)
    metacog.write_json(st.integrity, data)


def test_n2_manifest_baseline_key_deleted():
    """N-2 核心（真实 keygen 安装）：删 manifest:CONTRACT.md 基线键（文件仍在）→ drift 命中。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        r.add("keygen 成功", rc == 0, "rc={}".format(rc))
        r.add("keygen 安装 _keygen_established()=True", st._keygen_established() is True)
        _enforced, _drift = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("STRICT 下硬闸强制", _enforced is True)
        r.add("完整态 manifest:CONTRACT.md 不在 drift（前置）",
              "manifest:CONTRACT.md" not in _drift)
        # —— 攻击：删基线键（文件保留）——
        _delete_baseline_key(st, "manifest:CONTRACT.md")
        _enforced2, _drift2 = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("N-2 删基线键 → manifest:CONTRACT.md 计入 drift（收口关键路径）",
              "manifest:CONTRACT.md" in _drift2)
        # 删光全部 5 个 manifest 基线键 → 仍须全部检出（闸门不依赖 manifest 键自身）
        for _n in metacog.Store.MANIFEST_NAMES:
            _delete_baseline_key(st, "manifest:" + _n)
        _enforced3, _drift3 = metacog._manifest_integrity_drift_if_enforced(st)
        _miss = [k for k in ("manifest:" + _n for _n in metacog.Store.MANIFEST_NAMES)
                 if k in _drift3]
        r.add("删光全部 manifest 基线键 → 仍全部检出（不重新逃逸）",
              len(_miss) == len(metacog.Store.MANIFEST_NAMES), "命中={}".format(len(_miss)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_n2_no_false_positive_intact():
    """对照（真实 keygen 安装）：完整态（基线键全在、内容匹配）→ 不误报。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        _enforced, _drift = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("STRICT 下硬闸强制", _enforced is True)
        _manifest_keys = ["manifest:" + _n for _n in metacog.Store.MANIFEST_NAMES]
        _fp = [k for k in _manifest_keys if k in _drift]
        r.add("完整态无任何 manifest 基线键误报", _fp == [], "误报={}".format(_fp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_n2_content_tamper_still_drift():
    """回归（真实 keygen 安装）：manifest 键在但正文篡改 → 仍计入 drift（既有内容漂移检查未退化）。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        _sp = st.root / "SKILL.md"
        _sp.write_text(_sp.read_text(encoding="utf-8") + "\n<!-- tamper -->\n", encoding="utf-8")
        _enforced, _drift = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("正文篡改 → manifest:SKILL.md 计入 drift", "manifest:SKILL.md" in _drift)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_n2_file_missing_still_drift():
    """回归（真实 keygen 安装）：基线在但 manifest 文件缺失 → 仍计入 drift（原「文件缺失」检查保留）。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        (st.root / "CONTRACT.md").unlink()
        _enforced, _drift = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("基线在但文件缺失 → manifest:CONTRACT.md 计入 drift",
              "manifest:CONTRACT.md" in _drift)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_n2_init_no_false_positive():
    """对照（未 keygen/init 态）：删光全部 manifest 基线键 → 不误报（_keygen_established() 闸门生效）。"""
    r = T()
    st, tmp = _new_store_init_only()
    try:
        r.add("init 安装 _keygen_established()=False（前置）", st._keygen_established() is False)
        # 删光全部 5 个 manifest 基线键
        for _n in metacog.Store.MANIFEST_NAMES:
            _delete_baseline_key(st, "manifest:" + _n)
        _enforced, _drift = metacog._manifest_integrity_drift_if_enforced(st)
        _manifest_keys = ["manifest:" + _n for _n in metacog.Store.MANIFEST_NAMES]
        _fp = [k for k in _manifest_keys if k in _drift]
        r.add("未 keygen 删光键 → 不误报（闸门生效，零误伤）", _fp == [], "误报={}".format(_fp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def main():
    results = []
    results.append(test_n2_manifest_baseline_key_deleted())
    results.append(test_n2_no_false_positive_intact())
    results.append(test_n2_content_tamper_still_drift())
    results.append(test_n2_file_missing_still_drift())
    results.append(test_n2_init_no_false_positive())
    # R-9 整改：原 `all(res for res in results)` 恒为 True（T 无 __bool__）→ FAIL 被静默掩盖；
    # 改为按 failed 计数判定，任一子测试失败即整体失败并 exit!=0。
    all_ok = all(res.failed == 0 for res in results)
    total_passed = sum(res.passed for res in results)
    total_failed = sum(res.failed for res in results)
    print("\n" + "#" * 60)
    print("v2.27.2 N-2 套件总判定: {}（{}/{} PASS）".format(
        "ALL PASS" if all_ok else "HAS FAIL", total_passed, total_passed + total_failed))
    print("#" * 60)
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
