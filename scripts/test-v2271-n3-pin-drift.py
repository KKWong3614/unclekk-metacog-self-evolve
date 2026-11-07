#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.27.1（Hermes 七轮复验 N-3 收口）接线缺陷回归测试套件（独立验证，非自验自收）

N-3 [P2 MEDIUM，Hermes 七轮实测 Confirmed]：v2.27.0 的 R-3「钉固公钥漂移检查无条件执行」
实为 `if pinned:` 整体短路——删 CONTRACT.md 的 `human_pubkey_fingerprint` 钉固值行
（pinned=None）即令整段漂移检查不可达，verify rc=0（人类签名信任根漂移不可见）。
v2.27.1 改为三分支显式判定：
  ① pinned 有值        → 与 live 公钥指纹比对（live 缺 / 不符均 fail-closed 报告）
  ② pinned 为 None     且钉固痕迹存在（CONTRACT.md 仍含 human-identity-root 节标题、
                         而 human_pubkey_fingerprint 键行已不在）→ 钉固值行被删 → fail-closed
  ③ pinned 为 None     且无痕迹（init 未 keygen 的占位符态 / 从未钉固）→ 放行（不误伤正常流）

诚实边界：③ 分支刻意放行「占位符态」——init 生成的 CONTRACT.md 自带占位符钉固值
（`<待 confirm --keygen 钉固>`），无法据其判定攻击；而「把已钉固值改回占位符」这一变体
由 manifest 域漂移（R-2 保持 manifest:CONTRACT.md 基线在场）检出，不依赖本检查。

零第三方依赖。锚点定向临时文件，不污染真实树外锚。
"""
import io
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

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
    Path(tempfile.gettempdir()) / "metacog_v2271_test_anchor.anchor")

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
    nonce.write_text("offline-auth-nonce-v2271-9f3c2a7b", encoding="utf-8")
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


def _new_store_keygenned(pw="test-passphrase-v2271-1234"):
    """建临时 store + init + keygen（模拟 TTY）。返回 (store, tmp, rc)。"""
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2271_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    restore = _with_tty_and_passphrase(pw)
    try:
        rc, _ = _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
    finally:
        restore()
    return st, tmp, rc


def _delete_pin_value_line(st):
    """删掉 CONTRACT.md 的 human_pubkey_fingerprint 钉固值行（保留节标题）→ pinned 变 None。"""
    cpath = st.root / "CONTRACT.md"
    lines = cpath.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines
            if not (("human_pubkey_fingerprint" in ln) and (":" in ln))]
    cpath.write_text("\n".join(kept) + "\n", encoding="utf-8")


def test_n3_pin_value_line_deleted():
    """N-3 核心：删钉固值行（节标题保留）→ v2.27.1 应 fail-closed 检出（v2.27.0 为 rc=0）。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        r.add("keygen 成功", rc == 0, "rc={}".format(rc))
        pinned_before = st.pinned_human_pubkey_fingerprint()
        r.add("keygen 后钉固公钥指纹存在", bool(pinned_before), "pinned={}".format(pinned_before))
        ctext = (st.root / "CONTRACT.md").read_text(encoding="utf-8")
        r.add("keygen 后 CONTRACT.md 含 human-identity-root 节标题",
              "human-identity-root" in ctext)
        r.add("keygen 后 _keygen_established 为真", st._keygen_established() is True)

        # —— 攻击：删钉固值行（保留节标题）——
        _delete_pin_value_line(st)
        r.add("删值行后 pinned 为 None", st.pinned_human_pubkey_fingerprint() is None)
        ctext2 = (st.root / "CONTRACT.md").read_text(encoding="utf-8")
        r.add("删值行后 human-identity-root 节标题仍在（钉固痕迹存在）",
              "human-identity-root" in ctext2)

        rc_n3, out_n3 = _run(metacog.cmd_verify, st, SimpleNamespace())
        r.add("N-3 删钉固值行 → verify rc=1（v2.27.0 为 rc=0）", rc_n3 == 1, "rc={}".format(rc_n3))
        r.add("N-3 verify 输出含钉固值缺失提示", "钉固值疑似被删" in out_n3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_n3_no_false_positive_init_placeholder():
    """对照：init 未 keygen（CONTRACT.md 自带占位符钉固值）→ 不得误报（③ 分支放行）。"""
    r = T()
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2271_ctrl_"))
    st = metacog.Store(tmp / ".metacog")
    try:
        metacog.cmd_init(st, SimpleNamespace())
        ctext = (st.root / "CONTRACT.md").read_text(encoding="utf-8")
        r.add("init 态 CONTRACT.md 含 human-identity-root 节标题",
              "human-identity-root" in ctext)
        r.add("init 态 pinned 为 None（占位符）",
              st.pinned_human_pubkey_fingerprint() is None)
        rc_i, out_i = _run(metacog.cmd_verify, st, SimpleNamespace())
        r.add("init 未 keygen → verify 不误报 rc=0", rc_i == 0, "rc={}".format(rc_i))
        r.add("init 未 keygen → 输出不含钉固值缺失告警", "钉固值疑似被删" not in out_i)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_n3_pinned_present_still_works():
    """回归：钉固值完好时，公钥漂移检测仍照常工作（不因三分支改造而失效）。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        pinned = st.pinned_human_pubkey_fingerprint()
        r.add("钉固值存在", bool(pinned))
        # 替换公钥 → 指纹漂移
        guard = metacog.read_json(st.human_guard, {})
        guard["pubkey"] = guard["pubkey"] + "-ATTACKER"
        metacog.write_json(st.human_guard, guard)
        st.record_guard_integrity()
        rc_d, out_d = _run(metacog.cmd_verify, st, SimpleNamespace())
        r.add("钉固值完好时公钥漂移仍检出 rc=1", rc_d == 1, "rc={}".format(rc_d))
        r.add("输出含公钥漂移提示", "公钥信任根指纹漂移" in out_d)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def main():
    results = []
    results.append(test_n3_pin_value_line_deleted())
    results.append(test_n3_no_false_positive_init_placeholder())
    results.append(test_n3_pinned_present_still_works())
    # R-9 整改（Hermes 八轮）：原 `all(res for res in results)` 因 T 无 __bool__ 恒为 True，FAIL 被静默掩盖；
    # 改为按 failed 计数判定，任一子测试失败即整体失败并 exit!=0。
    all_ok = all(res.failed == 0 for res in results)
    print("\n" + "#" * 60)
    print("v2.27.1 N-3 套件总判定: {}".format("ALL PASS" if all_ok else "HAS FAIL"))
    print("#" * 60)
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
