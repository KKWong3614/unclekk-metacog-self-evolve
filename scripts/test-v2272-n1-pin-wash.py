#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.27.2（Hermes 八轮复验 N-1 收口）信任根钉固顺序回归测试套件（独立验证，非自验自收）

N-1 [P1 HIGH，Hermes 七轮实测 Confirmed]：cmd_apply / cmd_resign 在入口最前调用
ensure_pubkey_root_pinned() 钉固人类公钥信任根——早于所有完整性硬闸。攻击者已替换
human-guard.json（公钥）且安装尚无钉固（legacy）时，一次「被硬闸拒绝」的 apply/resign
仍会先把攻击者公钥钉固为信任根，洗白攻击面。
v2.27.2 把钉固移至「所有完整性硬闸通过之后、record_script_integrity 落盘之前」：
  - 被拒 apply/resign（任一硬闸漂移）→ 永不触发钉固 → 信任根不被洗白（N-1 收口）
  - 干净 apply（闸全过）→ 钉固照常写入（对照：钉固功能未退化）

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

# 本地测试环境：默认锚显式承担 + legacy 逃生舱 + 隔离冻结锚（STRICT 仅在 apply/resign 前临时开启）
_os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"
_os.environ["METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"] = "1"
_os.environ["METACOG_FREEZE_ANCHOR"] = str(
    Path(tempfile.gettempdir()) / "metacog_v2272_n1_test_anchor.anchor")

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
    nonce.write_text("offline-auth-nonce-v2272-n1-7d2e1c4f", encoding="utf-8")
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


def _new_store_keygenned(pw="test-passphrase-v2272-n1-1234"):
    """建临时 store + init + keygen（模拟 TTY）。init 不创建 SKILL.md/HANDOFF.md/CHANGELOG.md/pack.sh，
    此处补写桩文件使其参与基线化。返回 (store, tmp, rc)。"""
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2272_n1_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    for _name in metacog.Store.MANIFEST_NAMES:
        if _name == "CONTRACT.md":
            continue  # init 已创建
        _mp = st.root / _name
        if not _mp.exists():
            _mp.write_text("# 桩文件 {}\n内容占位 v2272-n1。\n".format(_name), encoding="utf-8")
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


def _tamper_skill_body(st):
    """篡改 SKILL.md 正文（非版本行）→ 触发 manifest 硬闸拒绝（正文哈希豁免不适用）。"""
    spath = st.root / "SKILL.md"
    text = spath.read_text(encoding="utf-8")
    spath.write_text(text + "\n<!-- v2272-n1 tamper marker -->\n", encoding="utf-8")


def _apply_args():
    return SimpleNamespace(id=None, sig=None, human_ok=False)


def test_n1_rejected_apply_does_not_pin():
    """N-1 核心：被硬闸拒绝的 apply 不得钉固信任根（v2.27.1 为「先钉固后拒」→ 洗白）。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        r.add("keygen 成功", rc == 0, "rc={}".format(rc))
        # 模拟 legacy 安装：guard 已存在但无钉固
        _delete_pin_value_line(st)
        r.add("删钉固值行后 pinned 为 None", st.pinned_human_pubkey_fingerprint() is None)
        # 建基线（含删行后的 CONTRACT.md），使干净态不误报
        st.record_script_integrity()
        # 篡改 SKILL.md 正文 → 触发 manifest 硬闸拒绝
        _tamper_skill_body(st)
        with _strict_on():
            rc_a, _ = _run(metacog.cmd_apply, st, _apply_args())
        r.add("篡改后 apply 被硬闸拒绝 rc=3", rc_a == 3, "rc={}".format(rc_a))
        r.add("N-1 被拒 apply 后 pinned 仍为 None（未洗白）",
              st.pinned_human_pubkey_fingerprint() is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_n1_clean_apply_still_pins():
    """v2.27.4（R-11 收口回归）：无 gated 提案的 no-op apply 不得落盘（不钉固、不重基线）——
    钉固/基线刷新已移至 `if not items: return 0` 之后，遵循「拒绝/无操作态永不持久化」。
    （钉固功能本身由 test_n1_clean_resign_still_pins 的 resign 路径覆盖，未退化。）"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        _delete_pin_value_line(st)
        r.add("删钉固值行后 pinned 为 None（前置）", st.pinned_human_pubkey_fingerprint() is None)
        st.record_script_integrity()
        _before = metacog.read_json(st.integrity, {})
        with _strict_on():
            rc_a, _ = _run(metacog.cmd_apply, st, _apply_args())
        # 无 gated 提案 → rc=0；钉固/基线刷新应在 no-op 返回之后，不落盘
        r.add("no-op apply rc=0", rc_a == 0, "rc={}".format(rc_a))
        r.add("R-11 no-op apply 后 pinned 仍为 None（未落盘钉固）",
              st.pinned_human_pubkey_fingerprint() is None)
        _after = metacog.read_json(st.integrity, {})
        r.add("R-11 no-op apply 后 integrity.json 未变（未重基线）", _before == _after)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_n1_rejected_resign_does_not_pin():
    """N-1 对称：被脚本硬闸拒绝的 resign 不得钉固信任根（script_dir 重定向造漂移）。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        _delete_pin_value_line(st)
        r.add("删钉固值行后 pinned 为 None（前置）", st.pinned_human_pubkey_fingerprint() is None)
        # 造一个会漂移的脚本基线：重定向 script_dir 到含真实 SCRIPT_NAMES 文件的临时目录
        # （脚本硬闸仅基线/检查 SCRIPT_NAMES 中的文件名，故须用真实名 domain_detector.py）
        _scdir = Path(tempfile.mkdtemp(prefix="metacog_v2272_n1_scr_"))
        _fake = _scdir / "domain_detector.py"
        _fake.write_text("def f():\n    return 1\n", encoding="utf-8")
        st.script_dir = _scdir
        st.record_script_integrity()  # 基线化 domain_detector.py
        # 篡改脚本 → 脚本硬闸漂移
        _fake.write_text("def f():\n    return 999  # tampered\n", encoding="utf-8")
        with _strict_on():
            rc_r, _ = _run(metacog.cmd_resign, st, SimpleNamespace(id=None, sig=None))
        r.add("脚本漂移后 resign 被硬闸拒绝 rc=3", rc_r == 3, "rc={}".format(rc_r))
        r.add("N-1 被拒 resign 后 pinned 仍为 None（未洗白）",
              st.pinned_human_pubkey_fingerprint() is None)
        shutil.rmtree(_scdir, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_n1_clean_resign_still_pins():
    """对照：干净 resign（脚本无漂移）仍正常钉固信任根（功能未退化）。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        _delete_pin_value_line(st)
        r.add("删钉固值行后 pinned 为 None（前置）", st.pinned_human_pubkey_fingerprint() is None)
        _scdir = Path(tempfile.mkdtemp(prefix="metacog_v2272_n1_scr_clean_"))
        _fake = _scdir / "domain_detector.py"
        _fake.write_text("def f():\n    return 1\n", encoding="utf-8")
        st.script_dir = _scdir
        st.record_script_integrity()  # 基线化 domain_detector.py（未篡改）
        # 缺 --id → 钉固（闸后、id 校验前）执行后返回 2；断言 pin 已写入
        with _strict_on():
            rc_r, _ = _run(metacog.cmd_resign, st, SimpleNamespace(id=None, sig=None))
        r.add("干净 resign 返回 2（缺 id，钉固已在闸后执行）", rc_r == 2, "rc={}".format(rc_r))
        r.add("N-1 干净 resign 后 pinned 已写入（功能未退化）",
              st.pinned_human_pubkey_fingerprint() is not None)
        shutil.rmtree(_scdir, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def main():
    results = []
    results.append(test_n1_rejected_apply_does_not_pin())
    results.append(test_n1_clean_apply_still_pins())
    results.append(test_n1_rejected_resign_does_not_pin())
    results.append(test_n1_clean_resign_still_pins())
    # R-9 整改（Hermes 八轮）：原 `all(res for res in results)` 因 T 无 __bool__ 恒为 True，FAIL 被静默掩盖；
    # 改为按 failed 计数判定，任一子测试失败即整体失败并 exit!=0。
    all_ok = all(res.failed == 0 for res in results)
    print("\n" + "#" * 60)
    print("v2.27.2 N-1 套件总判定: {}".format("ALL PASS" if all_ok else "HAS FAIL"))
    print("#" * 60)
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
