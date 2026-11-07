#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.27.3 回归测试套件（R-5 收口，独立验证，非自验自收）

覆盖 R-5 裁定（八轮登记 C·硬闸零基线签名校验 · OPEN → 本版收口）的对抗回归用例，对应 v2.27.3 收口项：
  - 硬闸计算层（_script_integrity_drift_if_enforced / _manifest_integrity_drift_if_enforced）此前**从不**
    调用 _verify_anchor_sig，仅比哈希——攻击者凭 ledger 写权限直写（或经引擎 API 重记）基线哈希即穿透
    apply/keygen/retrieve 入口硬闸（仅 verify 事后报警）。
  - v2.27.3 起两函数均补 _verify_anchor_sig 校验，与 verify_integrity 报告层（L1643-1650 / L1667-1675）
    同口径 fail-closed：签名失效（False）/（非 legacy 容忍期）缺失签名（None）→ 计 drift。

  测试在 METACOG_TRUST_ROOT_STRICT=1（强制硬闸生效）+ 专属 METACOG_TRUST_ROOT_ANCHOR_KEY（测试密钥）
  （本地开发模式，_verify_anchor_sig 不抛 LedgerAnchorDefaultError）下进行；CURRENT_VERSION_TUPLE
  恒 >= LEGACY_ANCHOR_SIG_CUTOFF(2,15,0) → 缺失 _anchor_sig 的 None 态按 fail-closed 计 drift。

  诚实边界（不声称已闭合）：默认（源码内嵌共享）锚在 ALLOW_DEFAULT=1 下可读即自签——攻击者持
  源码读权可重算**合法**签名通过本闸（与 v2.10.0 诚实天花板同口径）；本测试验证的是「默认环境即
  使如此，伪造/删 sig 仍被检出」，生产须以专属 METACOG_TRUST_ROOT_ANCHOR_KEY 闭合该残余。

零第三方依赖，import metacog 直接单测。
"""
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

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
                                    " - " + detail if detail else ""))

    def summary(self):
        total = self.passed + self.failed
        print("\n{}".format("=" * 64))
        print("v2.27.3 R-5 硬闸签名校验回归测试结果: {}/{} PASS".format(self.passed, total))
        print("=" * 64)
        return self.failed == 0


def _new_store():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2273_r5_"))
    root = tmp / ".metacog"
    st = metacog.Store(root)
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


# --------------------------------------------------------- R-5a：script: 域硬闸签名校验
def test_r5_script_gate(r):
    """v2.27.3（R-5）：_script_integrity_drift_if_enforced 须对 script: 基线签名失效/缺失计 drift。
    控制：合法 sig → 无 drift；对抗：伪造 sig（"0"*64 → False）/ 删 sig（None → fail-closed）均须 drift。"""
    st, tmp = _new_store()
    try:
        _orig = metacog.Store.SCRIPT_NAMES
        _dummy = "v2273_r5_dummy.py"
        metacog.Store.SCRIPT_NAMES = (_dummy,)
        _f = st.script_dir / _dummy
        _f.parent.mkdir(parents=True, exist_ok=True)
        _f.write_text("print('baseline')\n", encoding="utf-8")
        st.record_script_integrity()

        _key = "script:" + _dummy
        _enf, _drift = metacog._script_integrity_drift_if_enforced(st)
        r.add("STRICT 下硬闸生效 (enforced=True)", _enf is True, "enf={}".format(_enf))
        r.add("合法 script: 基线签名 → 无 drift（控制）",
              _drift == [], "drift={}".format(_drift))

        # 对抗1：伪造 _anchor_sig（"0"*64，非合法 HMAC）→ _verify_anchor_sig 返 False → drift
        _data = metacog.read_json(st.integrity, {})
        _data[_key]["_anchor_sig"] = "0" * 64
        metacog.write_json(st.integrity, _data)
        _enf2, _drift2 = metacog._script_integrity_drift_if_enforced(st)
        r.add("伪造 script: 基线签名（False）→ 计 drift（fail-closed）",
              _key in _drift2, "drift={}".format(_drift2))

        # 对抗2：删除 _anchor_sig → _verify_anchor_sig 返 None → CURRENT>=cutoff 下 fail-closed 计 drift
        _data3 = metacog.read_json(st.integrity, {})
        _data3[_key].pop("_anchor_sig", None)
        metacog.write_json(st.integrity, _data3)
        _enf3, _drift3 = metacog._script_integrity_drift_if_enforced(st)
        r.add("缺失 script: 基线 _anchor_sig（None）→ 计 drift（fail-closed）",
              _key in _drift3, "drift={}".format(_drift3))

        # 还原合法 sig → 无 drift（证明非误报）
        st.record_script_integrity()  # 重记基线恢复合法 sig
        _enf4, _drift4 = metacog._script_integrity_drift_if_enforced(st)
        r.add("还原合法签名 → 无 drift（非误报）", _drift4 == [], "drift={}".format(_drift4))

        metacog.Store.SCRIPT_NAMES = _orig
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------- R-5b：manifest: 域硬闸签名校验
def test_r5_manifest_gate(r):
    """v2.27.3（R-5）：_manifest_integrity_drift_if_enforced 须对 manifest: 基线签名失效/缺失计 drift
    （CHANGELOG.md 为非阻塞域，跳过签名阻断，不引入假阳性）。"""
    st, tmp = _new_store()
    try:
        # 在 store 根创建一份 SKILL.md（manifest 域受跟踪文件），供 record_script_integrity 基线化
        _sk = st.root / "SKILL.md"
        _sk.write_text("# v2273 R-5 测试\n\n正文内容。\n", encoding="utf-8")
        st.record_script_integrity()

        _key = "manifest:SKILL.md"
        _enf, _drift = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("STRICT 下 manifest 硬闸生效 (enforced=True)", _enf is True, "enf={}".format(_enf))
        r.add("合法 manifest: 基线签名 → 无 drift（控制）",
              _drift == [], "drift={}".format(_drift))

        # 对抗1：伪造 _anchor_sig → False → drift
        _data = metacog.read_json(st.integrity, {})
        _data[_key]["_anchor_sig"] = "0" * 64
        metacog.write_json(st.integrity, _data)
        _enf2, _drift2 = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("伪造 manifest: 基线签名（False）→ 计 drift（fail-closed）",
              _key in _drift2, "drift={}".format(_drift2))

        # 对抗2：删除 _anchor_sig → None → fail-closed 计 drift
        _data3 = metacog.read_json(st.integrity, {})
        _data3[_key].pop("_anchor_sig", None)
        metacog.write_json(st.integrity, _data3)
        _enf3, _drift3 = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("缺失 manifest: 基线 _anchor_sig（None）→ 计 drift（fail-closed）",
              _key in _drift3, "drift={}".format(_drift3))

        # 还原合法 sig → 无 drift（非误报）
        st.record_script_integrity()
        _enf4, _drift4 = metacog._manifest_integrity_drift_if_enforced(st)
        r.add("还原合法签名 → 无 drift（非误报）", _drift4 == [], "drift={}".format(_drift4))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    _orig_strict = _os.environ.get("METACOG_TRUST_ROOT_STRICT")
    _orig_key = _os.environ.get("METACOG_TRUST_ROOT_ANCHOR_KEY")
    _os.environ["METACOG_TRUST_ROOT_STRICT"] = "1"
    _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"
    try:
        r = T()
        test_r5_script_gate(r)
        test_r5_manifest_gate(r)
        ok = r.summary()
    finally:
        # 还原环境变量（不影响其它测试 / 运行器注入的测试密钥）
        for _k in ("METACOG_TRUST_ROOT_STRICT",):
            _os.environ.pop(_k, None)
        _os.environ.pop("METACOG_TRUST_ROOT_ANCHOR_KEY", None)
        if _orig_strict is not None:
            _os.environ["METACOG_TRUST_ROOT_STRICT"] = _orig_strict
        if _orig_key is not None:
            _os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = _orig_key
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
