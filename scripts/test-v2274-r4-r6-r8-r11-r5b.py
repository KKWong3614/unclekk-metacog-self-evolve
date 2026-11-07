#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.27.4 回归测试套件（R-4/R-6/R-8/R-11/R-5b 收口，独立验证，非自验自收）

覆盖九轮 owner 授权收口的 5 项对抗回归用例，对应 v2.27.4 收口项：

  R-4 [M] 自指闸门解耦：_keygen_established() 不再依赖被保护物自身（chain-identity-root
    文本 / GUARD 基线键），改用独立证据（human-guard.json 文件存在 OR CONTRACT.md 含
    human-identity-root 钉固节）。连删 chain+GUARD+manifest 键仍判已 keygen（True）；
    仅当独立证据也消失（keypair 删 + 钉固节删）才返 False（彻底破坏态由 cmd_verify GUARD 块兜底）。

  R-6 [C] 重基线诚实标注：默认共享锚（未设 METACOG_TRUST_ROOT_ANCHOR_KEY）下，record_script_integrity
    重基线告警须附带诚实残余标注（无法区分授权/攻击重基线）；设专属锚密钥时该标注消失。

  R-8 [m] 硬闸 @body 豁免验签：manifest:SKILL.md@body 硬闸豁免路径须先验 _anchor_sig；
    伪造/缺失签名的 @body 基线不再令版本差异豁免失据（正文篡改仍被检出 drift）。

  R-11 [M] no-op apply 不落盘：cmd_apply 在无待应用提议（no-op）时不调用 record_script_integrity /
    ensure_pubkey_root_pinned，integrity.json 不被改写（含 manifest:SKILL.md@body 派生子键）。

  R-5b [m] @body 删键盲区闭合：verify 层 + 硬闸层双处检测 manifest:SKILL.md@body 派生键删除
    （SKILL.md 基线存在时须存在，缺失即 drift / not-ok）。

测试在专属 METACOG_TRUST_ROOT_ANCHOR_KEY（测试密钥）下进行；R-5b/R-8 硬闸用例
内部自设 METACOG_TRUST_ROOT_STRICT=1 验证硬闸确实强制，运行后还原。零第三方依赖。
"""
import hashlib
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

# 本地测试环境：默认锚显式承担 + legacy 逃生舱 + 隔离冻结锚
_os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"
_os.environ["METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"] = "1"
_os.environ["METACOG_FREEZE_ANCHOR"] = str(
    Path(tempfile.gettempdir()) / "metacog_v2274_test_anchor.anchor")

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
        print("\n{}".format("=" * 64))
        print("{}: {}/{} PASS".format(title, self.passed, total))
        print("=" * 64)
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
    nonce.write_text("offline-auth-nonce-v2274-9d3c1e7a", encoding="utf-8")
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


def _new_store_keygenned(pw="test-passphrase-v2274-1234"):
    """建临时 store + init + keygen（模拟 TTY）。补写 manifest 桩文件使其参与基线化。"""
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2274_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    for _name in metacog.Store.MANIFEST_NAMES:
        if _name == "CONTRACT.md":
            continue  # init 已创建
        _mp = st.root / _name
        if not _mp.exists():
            _mp.write_text("# 桩文件 {}\n内容占位 v2274。\n".format(_name), encoding="utf-8")
    restore = _with_tty_and_passphrase(pw)
    try:
        rc, _ = _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
    finally:
        restore()
    # 显式基线化，确保 manifest:SKILL.md@body 存在
    st.record_script_integrity()
    return st, tmp, rc


def _new_store_initonly():
    """仅 init（不 keygen）的对照 store——人类密钥对文件不存在，human-identity-root 钉固节由 init 模板写入。"""
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2274_init_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    for _name in metacog.Store.MANIFEST_NAMES:
        if _name == "CONTRACT.md":
            continue
        _mp = st.root / _name
        if not _mp.exists():
            _mp.write_text("# 桩文件 {}\n内容占位 v2274-init。\n".format(_name), encoding="utf-8")
    return st, tmp, 0


def _delete_pin_value_line(st):
    cpath = st.root / "CONTRACT.md"
    lines = cpath.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines
            if not (("human_pubkey_fingerprint" in ln) and (":" in ln))]
    cpath.write_text("\n".join(kept) + "\n", encoding="utf-8")


def _remove_human_identity_root_section(st):
    """从 CONTRACT.md 删除 human-identity-root 钉固节（含标题行）。"""
    cpath = st.root / "CONTRACT.md"
    text = cpath.read_text(encoding="utf-8")
    # 删除含 human-identity-root 的标题行及其后续非标题行（锚定标题本身，避免跨节误删）
    import re
    _new = re.sub(r"^##\s+.*human-identity-root.*$(?:\n(?!##).*)*", "", text, flags=re.M)
    cpath.write_text(_new, encoding="utf-8")


def _remove_chain_identity_root(st):
    """从 CONTRACT.md 删除 chain-identity-root 节（R-4 自指闸门旧依赖）。
    锚定在「含该词的标题行」+ 其后续非标题行，避免误删相邻 human-identity-root 节。"""
    cpath = st.root / "CONTRACT.md"
    text = cpath.read_text(encoding="utf-8")
    import re
    _new = re.sub(r"^##\s+.*chain-identity-root.*$(?:\n(?!##).*)*", "", text, flags=re.M)
    cpath.write_text(_new, encoding="utf-8")


# --------------------------------------------------------- R-4：自指闸门解耦
def test_r4_independent_evidence():
    """v2.27.4（R-4）：_keygen_established() 须依赖两路独立证据（human-guard.json 文件 / chain-identity-root
    文本），任一成立即判已 keygen；连删 chain+GUARD+manifest 键（保留 keypair 文件）仍 True（R-4 收口），
    删 keypair 文件但保留 chain 文本仍 True（R-1 删文件后 GUARD 缺失仍检出），仅两者皆删才 False。"""
    r = T()
    # 控制：基线态
    st, tmp, rc = _new_store_keygenned()
    try:
        r.add("keygen 成功", rc == 0, "rc={}".format(rc))
        r.add("基线态 _keygen_established()=True（控制）", st._keygen_established() is True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # 场景 A（R-4 双删逃逸）：删 chain 文本 + GUARD 基线键 + 全部 manifest/script 基线键，保留 keypair 文件
    stA, tmpA, _ = _new_store_keygenned()
    try:
        _remove_chain_identity_root(stA)
        _data = metacog.read_json(stA.integrity, {})
        _pruned = {k: v for k, v in _data.items()
                   if not (k.startswith("manifest:") or k.startswith("script:")
                           or k == stA.GUARD_INTEGRITY_KEY)}
        metacog.write_json(stA.integrity, _pruned)
        r.add("R-4 双删逃逸（删 chain+GUARD+manifest，保留 keypair 文件）→ 仍 True（文件证据）",
              stA._keygen_established() is True)
    finally:
        shutil.rmtree(tmpA, ignore_errors=True)
    # 场景 B（R-1 删文件）：删 keypair 文件（保留 chain 文本 + GUARD 基线键），chain 证据成立 → 仍 True
    stB, tmpB, _ = _new_store_keygenned()
    try:
        if stB.human_guard.exists():
            stB.human_guard.unlink()
        r.add("R-1 删 keypair 文件（保留 chain 文本）→ 仍 True（chain 证据，GUARD 缺失仍检出）",
              stB._keygen_established() is True)
    finally:
        shutil.rmtree(tmpB, ignore_errors=True)
    # 场景 C（彻底破坏）：删 keypair 文件 + 删 chain 文本 → 两路证据皆无 → False，交 GUARD 块兜底
    stC, tmpC, _ = _new_store_keygenned()
    try:
        if stC.human_guard.exists():
            stC.human_guard.unlink()
        _remove_chain_identity_root(stC)
        r.add("删 keypair 文件 + 删 chain 文本（彻底破坏）→ False（交 GUARD 块兜底）",
              stC._keygen_established() is False)
    finally:
        shutil.rmtree(tmpC, ignore_errors=True)
    # 对照：init/legacy 安装（无 keypair 文件、无 chain 文本）须返 False，不误触发硬闸
    st2, tmp2, _ = _new_store_initonly()
    try:
        r.add("init-only 安装（无 keypair / 无 chain）→ _keygen_established()=False（不误报）",
              st2._keygen_established() is False)
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)
    return r


# --------------------------------------------------------- R-6：锚密钥未配置 fail-closed + 专属锚重基线
def test_r6_rebaseline_honest_annotation():
    """v2.27.4（R-6）→ v2.27.17（C-01 收口更新语义）：
    ① 未设 METACOG_TRUST_ROOT_ANCHOR_KEY（C-01 后无默认锚）→ record_script_integrity 在
       锚签名步抛 LedgerAnchorDefaultError（fail-closed，宁可装不上不可自签），告警含诚实指引；
    ② 设合法专属锚密钥 → 重基线成功，无「锚密钥未配置」标注。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        _old_anchor = _os.environ.get("METACOG_TRUST_ROOT_ANCHOR_KEY")
        _os.environ.pop("METACOG_TRUST_ROOT_ANCHOR_KEY", None)  # 模拟未配置锚密钥
        # 篡改 SKILL.md 触发重基线
        _sp = st.root / "SKILL.md"
        _sp.write_text(_sp.read_text(encoding="utf-8") + "\n<!-- v2274 r6 tamper -->\n", encoding="utf-8")
        _raised, _out = None, ""
        try:
            _rc, _out = _run(st.record_script_integrity)
        except metacog.LedgerAnchorDefaultError as _e:
            _raised = _e
            _out = str(_e)
        r.add("未配置锚密钥 → 重基线 fail-closed（LedgerAnchorDefaultError）", _raised is not None)
        r.add("fail-closed 报错含诚实指引（METACOG_TRUST_ROOT_ANCHOR_KEY）",
              _raised is not None and "METACOG_TRUST_ROOT_ANCHOR_KEY" in _out,
              "含指引={}".format("METACOG_TRUST_ROOT_ANCHOR_KEY" in _out))
        # 设合法专属锚密钥（base64 ≥32 字节）→ 重基线成功，无「锚密钥未配置」标注
        _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"
        _sp.write_text(_sp.read_text(encoding="utf-8") + "\n<!-- v2274 r6 tamper2 -->\n", encoding="utf-8")
        _, _out2 = _run(st.record_script_integrity)
        r.add("设专属锚后重基线成功且无未配置标注（生产姿态）",
              "锚密钥未配置" not in _out2 and "共享默认锚" not in _out2)
        if _old_anchor is not None:
            _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = _old_anchor
        else:
            _os.environ.pop("METACOG_TRUST_ROOT_ANCHOR_KEY", None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


# --------------------------------------------------------- R-8：硬闸 @body 豁免验签
def _tamper_skill_body(st):
    _sp = st.root / "SKILL.md"
    _sp.write_text(_sp.read_text(encoding="utf-8") + "\n<!-- v2274 r8 body tamper -->\n",
                   encoding="utf-8")


def _change_skill_version_only(st, new_ver="2.27.5"):
    _sp = st.root / "SKILL.md"
    _txt = _sp.read_text(encoding="utf-8")
    import re
    _txt2 = re.sub(r"^version:\s*\S+", "version: {}".format(new_ver), _txt, flags=re.M)
    _sp.write_text(_txt2, encoding="utf-8")


def test_r8_hardgate_body_sig_required():
    """v2.27.4（R-8）：硬闸 SKILL.md @body 豁免须验 _anchor_sig；伪造/缺失签名不再令豁免失据。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        # 控制：仅改版本号（正文不变）→ 合法 @body 签名豁免 → 无 drift
        _change_skill_version_only(st)
        with _strict_on():
            _enf, _drift = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("STRICT 下硬闸生效 (enforced=True)", _enf is True, "enf={}".format(_enf))
        r.add("仅版本号变更 + 合法 @body 签名 → 无 drift（合法豁免，控制）",
              _drift == [], "drift={}".format(_drift))

        # 对抗：改正文（版本不变）+ 伪造 @body 基线（坏签名 + 哈希匹配篡改后正文）
        _tamper_skill_body(st)
        _data = metacog.read_json(st.integrity, {})
        # 用当前篡改后正文算 body hash
        _cur_body_text = (st.root / "SKILL.md").read_text(encoding="utf-8")
        _cur_body_text = (st.root / "SKILL.md").read_text(encoding="utf-8")
        _body_hash = st._skill_body_hash(_cur_body_text)
        _data["manifest:SKILL.md@body"] = {
            "hash": _body_hash,
            "size": (st.root / "SKILL.md").stat().st_size,
            "at": metacog.now_iso(),
            "_anchor_sig": "0" * 64,  # 伪造签名
        }
        metacog.write_json(st.integrity, _data)
        with _strict_on():
            _enf2, _drift2 = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("伪造 @body 签名（坏 sig）+ 正文篡改 → 仍计 drift（R-8 豁免被拒）",
              "manifest:SKILL.md" in _drift2, "drift={}".format(_drift2))

        # 还原合法 @body 签名 → 对照：若仅有版本差异则豁免；此处正文已篡改，即使合法 sig 也因正文不符而不豁免
        st.record_script_integrity()  # 重记合法基线（含合法 @body sig）
        _tamper_skill_body(st)  # 再次篡改正文
        with _strict_on():
            _enf3, _drift3 = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("合法 @body 签名但正文仍被篡改 → 仍计 drift（不误豁免，对照）",
              "manifest:SKILL.md" in _drift3, "drift={}".format(_drift3))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


# --------------------------------------------------------- R-11：no-op apply 不落盘
def _sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_r11_noop_apply_no_rebaseline():
    """v2.27.4（R-11）：无待应用提议（no-op）的 apply 不调用 record_script_integrity，
    integrity.json（含 manifest:SKILL.md@body）不被改写。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        r.add("keygen 成功", rc == 0, "rc={}".format(rc))
        st.record_script_integrity()  # 建立基线
        _before = _sha256_file(st.integrity)
        _props = st.proposals()
        _gated = [p for p in _props if p.get("status") == "gated"]
        r.add("前置：无 gated 提议（no-op 场景）", len(_gated) == 0, "gated={}".format(len(_gated)))
        _rc_a, _ = _run(metacog.cmd_apply, st, SimpleNamespace(id=None, sig=None, human_ok=False))
        r.add("no-op apply 返回 rc=0", _rc_a == 0, "rc={}".format(_rc_a))
        _after = _sha256_file(st.integrity)
        r.add("no-op apply 后 integrity.json 未被改写（R-11 收口）", _before == _after)
        # 防御性：@body 子键仍存在于基线（未被 no-op 抹除，亦未被 no-op 重记）
        _data = metacog.read_json(st.integrity, {})
        r.add("基线条目 manifest:SKILL.md@body 仍存在且未变",
              _data.get("manifest:SKILL.md@body") is not None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


# --------------------------------------------------------- R-5b：@body 删键盲区闭合
def test_r5b_body_deletion_detected():
    """v2.27.4（R-5b）：删 manifest:SKILL.md@body 派生键，verify 层与硬闸层双处须检出（drift / not-ok）。"""
    r = T()
    st, tmp, rc = _new_store_keygenned()
    try:
        # 控制：完整基线 → verify 层无异常、硬闸无 drift
        _out_ctrl = st.verify_integrity()
        _ctrl_bad = [a for a, ok, *_ in _out_ctrl if a == "manifest:SKILL.md@body" and not ok]
        r.add("控制：完整基线 verify 层不误报 @body 缺失", _ctrl_bad == [])
        # 删 @body 派生键
        _data = metacog.read_json(st.integrity, {})
        _data.pop("manifest:SKILL.md@body", None)
        metacog.write_json(st.integrity, _data)
        # verify 层：R-5b 修复后须显式报告 @body not-ok
        _out = st.verify_integrity()
        _bad = [a for a, ok, *_ in _out if a == "manifest:SKILL.md@body" and not ok]
        r.add("删 @body → verify 层报告 not-ok（R-5b 收口·verify 层）", _bad != [])
        # 硬闸层：STRICT 下须计 drift
        with _strict_on():
            _enf, _drift = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("删 @body → 硬闸层计 drift（R-5b 收口·硬闸层）",
              "manifest:SKILL.md@body" in _drift, "drift={}".format(_drift))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def main():
    results = []
    results.append(test_r4_independent_evidence())
    results.append(test_r6_rebaseline_honest_annotation())
    results.append(test_r8_hardgate_body_sig_required())
    results.append(test_r11_noop_apply_no_rebaseline())
    results.append(test_r5b_body_deletion_detected())
    all_ok = all(res.failed == 0 for res in results)
    print("\n" + "#" * 64)
    print("v2.27.4 套件总判定: {}".format("ALL PASS" if all_ok else "HAS FAIL"))
    print("#" * 64)
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
