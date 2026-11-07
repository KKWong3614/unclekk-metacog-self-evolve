#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.27.3 回归测试套件（R-7 收口，独立验证，非自验自收）

覆盖 R-7 裁定（八轮登记 C·初始安装自举零检测 · OPEN → 本版收口）的对抗回归用例，对应 v2.27.3 收口项：
  - 初始可信基线（keygen 建立的人类身份 + 全量代码/清单基线）在「外部锚已构建为真实离线根（hsm /
    hsm+oob）」时必须由离线根设备证明为人类身份背书，否则 fail-closed 拒绝建立可信基线
    （杜绝「预篡改树 + 正常 keygen」自举为干净基线，与合法安装不可区分）。
  - legacy（无外部锚）/ 默认 deny（无配置 → DenyTrustRoot）/ corrupt / 纯 oob → 一律放行（不误伤常规安装）。

  关键非破坏性断言：默认 deny（无配置）态下 _bootstrap_external_attested 仍返回 (True, None)，
  证明常规未配置外部锚的安装 init/keygen 不受影响（默认 deny 在 verify 验签时才 fail-closed，不阻断本地基线）。

  零第三方依赖，import metacog / trust_root / sigcrypto 直接单测。
"""
import hashlib
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

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
import sigcrypto
import trust_root


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
        print("\n{}".format("=" * 64))
        print("v2.27.3 R-7 自举外部背书回归测试结果: {}/{} PASS".format(self.passed, total))
        print("=" * 64)
        return self.failed == 0


def _new_store():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2273_r7_"))
    root = tmp / ".metacog"
    st = metacog.Store(root)
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


def _gen_human_guard(st, pub_h):
    metacog.write_json(st.human_guard, {
        "pubkey": sigcrypto.serialize_pub(pub_h),
        "privkey_enc": "dummy-enc-blob",
        "algo": "rsa-2048-pkcs1v15+aesctr-equiv",
        "created_at": "2026-10-20T00:00:00Z",
    })


def _write_contract_pinned(st, pinned):
    st.root.joinpath("CONTRACT.md").write_text(
        "# CONTRACT\n\n## human-identity-root\n\nhuman_pubkey_fingerprint: {}\n".format(pinned),
        encoding="utf-8")


def _setup_hsm(st, tmp, pub_off, priv_off, attested_matches=True, attestation_present=True):
    """在 store 配置 hsm 外部锚（attestation_path 置于 root 之外，通过 anchor_storage_outside_root 闸门）；
    返回 attestation 目录路径。attested_matches=False → 设备证明提交公钥与 live 公钥不符（模拟伪造/错绑）。"""
    pub_h, _ = sigcrypto.gen_keypair(2048)
    _gen_human_guard(st, pub_h)
    _pinned = hashlib.sha256(sigcrypto.serialize_pub(pub_h).encode("utf-8")).hexdigest()[:32]
    _write_contract_pinned(st, _pinned)
    _att_dir = tmp / "att_outside_root"   # root 之外（sibling），满足结构性 fail-closed 闸门
    _att_dir.mkdir(parents=True, exist_ok=True)
    _att_path = str(_att_dir / "attest.json")
    if attestation_present:
        _committed = sigcrypto.serialize_pub(pub_h) if attested_matches else sigcrypto.serialize_pub(
            sigcrypto.gen_keypair(2048)[0])
        trust_root.write_root_attestation(_att_path, _committed, _pinned, priv_off)
    # 写入签名版 trust-root.json（hsm + root_pubkey）；ALLOW_DEFAULT=1 已在调用方设置
    trust_root.write_trust_root_config(st.root, "hsm", attestation_path=_att_path, root_pubkey=pub_off)
    return _pinned


def _teardown_env(orig):
    for _k in ("METACOG_TRUST_ROOT_ALLOW_DEFAULT", "METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR",
               "METACOG_TRUST_ROOT_STRICT"):
        _os.environ.pop(_k, None)
    for _k, _v in orig.items():
        if _v is not None:
            _os.environ[_k] = _v


# --------------------------------------------------------- R-7a：legacy None → 放行（不误伤）
def test_r7_legacy_none(r):
    """v2.27.3（R-7）：无外部锚（opt-out 回落 None）→ _bootstrap_external_attested 返回 (True, None)。"""
    st, tmp = _new_store()
    orig = {k: _os.environ.get(k) for k in
            ("METACOG_TRUST_ROOT_ALLOW_DEFAULT", "METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR", "METACOG_TRUST_ROOT_STRICT")}
    _os.environ["METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"] = "1"  # v2.27.17 H-01 已删：此 env 已无效（no-op）；无配置走 DenyTrustRoot 放行路径
    try:
        _ok, _reason = metacog._bootstrap_external_attested(st)
        r.add("legacy（无外部锚）→ (True, None)", _ok is True and _reason is None,
              "ok={} reason={}".format(_ok, _reason))
    finally:
        _teardown_env(orig)
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------- R-7b：默认 deny（无配置）DenyTrustRoot → 放行（非破坏性）
def test_r7_default_deny_nonblocking(r):
    """v2.27.3（R-7）：无配置 → external_trust_root() 返 DenyTrustRoot（默认 deny）；
    _bootstrap_external_attested 仍 (True, None)，证明常规未配置安装不被阻断（不误伤）。"""
    st, tmp = _new_store()
    orig = {k: _os.environ.get(k) for k in
            ("METACOG_TRUST_ROOT_ALLOW_DEFAULT", "METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR", "METACOG_TRUST_ROOT_STRICT")}
    try:
        _ext = st.external_trust_root()
        r.add("无配置 → external_trust_root 为 DenyTrustRoot（默认 deny）",
              isinstance(_ext, trust_root.DenyTrustRoot), "ext={}".format(type(_ext).__name__))
        _ok, _reason = metacog._bootstrap_external_attested(st)
        r.add("默认 deny（无配置）→ 仍 (True, None)（非破坏性）",
              _ok is True and _reason is None, "ok={} reason={}".format(_ok, _reason))
    finally:
        _teardown_env(orig)
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------- R-7c：hsm 有效设备证明 → 放行（绑定成功）
def test_r7_hsm_valid_attestation(r):
    """v2.27.3（R-7）：hsm + 合法离线根设备证明（committed=live 公钥、cf=钉固指纹、签名有效）
    → _bootstrap_external_attested 返回 (True, None)。"""
    st, tmp = _new_store()
    orig = {k: _os.environ.get(k) for k in
            ("METACOG_TRUST_ROOT_ALLOW_DEFAULT", "METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR", "METACOG_TRUST_ROOT_STRICT")}
    _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"  # 测试锚密钥（C-01 后无默认锚；trust-root.json 写入所需）
    try:
        _pub_off, _priv_off = trust_root.gen_offline_root_keypair()
        _setup_hsm(st, tmp, _pub_off, _priv_off, attested_matches=True, attestation_present=True)
        _ext = st.external_trust_root()
        r.add("hsm 配置 → external_trust_root 为 HsmTrustRoot",
              isinstance(_ext, trust_root.HsmTrustRoot), "ext={}".format(type(_ext).__name__))
        _ok, _reason = metacog._bootstrap_external_attested(st)
        r.add("hsm 有效设备证明 → (True, None)（绑定成功，可建立可信基线）",
              _ok is True and _reason is None, "ok={} reason={}".format(_ok, _reason))
    finally:
        _teardown_env(orig)
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------- R-7d：hsm 缺设备证明 → fail-closed
def test_r7_hsm_missing_attestation(r):
    """v2.27.3（R-7）：hsm 配置但设备证明文件缺失 → attestation_ok 返 (False, no-device-attestation)
    → _bootstrap_external_attested 返 (False, bootstrap-external-anchor-no-device-attestation)。"""
    st, tmp = _new_store()
    orig = {k: _os.environ.get(k) for k in
            ("METACOG_TRUST_ROOT_ALLOW_DEFAULT", "METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR", "METACOG_TRUST_ROOT_STRICT")}
    _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"
    try:
        _pub_off, _priv_off = trust_root.gen_offline_root_keypair()
        _setup_hsm(st, tmp, _pub_off, _priv_off, attestation_present=False)
        _ok, _reason = metacog._bootstrap_external_attested(st)
        r.add("hsm 缺设备证明 → (False, bootstrap-external-anchor-no-device-attestation)（fail-closed）",
              _ok is False and _reason == "bootstrap-external-anchor-no-device-attestation",
              "ok={} reason={}".format(_ok, _reason))
    finally:
        _teardown_env(orig)
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------- R-7e：hsm 设备证明公钥不符 → fail-closed
def test_r7_hsm_attestation_mismatch(r):
    """v2.27.3（R-7）：hsm + 设备证明提交公钥与 live 公钥不符（错绑/伪造）→ attestation_ok 返
    (False, attestation-pubkey-mismatch) → _bootstrap_external_attested 返对应 fail-closed。"""
    st, tmp = _new_store()
    orig = {k: _os.environ.get(k) for k in
            ("METACOG_TRUST_ROOT_ALLOW_DEFAULT", "METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR", "METACOG_TRUST_ROOT_STRICT")}
    _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"
    try:
        _pub_off, _priv_off = trust_root.gen_offline_root_keypair()
        _setup_hsm(st, tmp, _pub_off, _priv_off, attested_matches=False, attestation_present=True)
        _ok, _reason = metacog._bootstrap_external_attested(st)
        r.add("hsm 设备证明公钥不符 → (False, bootstrap-external-anchor-attestation-pubkey-mismatch)",
              _ok is False and _reason == "bootstrap-external-anchor-attestation-pubkey-mismatch",
              "ok={} reason={}".format(_ok, _reason))
    finally:
        _teardown_env(orig)
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------- R-7f：cmd_init 在默认 deny（无配置）下不被阻断（回归保护）
def test_r7_init_default_deny_not_blocked(r):
    """v2.27.3（R-7）：无配置（默认 deny）下 cmd_init 仍返回 0（R-7 收口不阻断常规安装自举）。"""
    st, tmp = _new_store()
    orig = {k: _os.environ.get(k) for k in
            ("METACOG_TRUST_ROOT_ALLOW_DEFAULT", "METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR", "METACOG_TRUST_ROOT_STRICT")}
    _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"  # 测试锚密钥（record_integrity 写 _anchor_sig 所需；与默认 deny 外部锚姿态无关）
    try:
        _rc = metacog.cmd_init(st, None)
        r.add("cmd_init 在默认 deny（无配置）下返回 0（不阻断）", _rc == 0, "rc={}".format(_rc))
        r.add("cmd_init 仍建立 integrity.json（D4 快照）", metacog.read_json(st.integrity, {}) != {},
              "integrity_empty={}".format(metacog.read_json(st.integrity, {}) == {}))
    finally:
        _teardown_env(orig)
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    r = T()
    test_r7_legacy_none(r)
    test_r7_default_deny_nonblocking(r)
    test_r7_hsm_valid_attestation(r)
    test_r7_hsm_missing_attestation(r)
    test_r7_hsm_attestation_mismatch(r)
    test_r7_init_default_deny_not_blocked(r)
    ok = r.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
