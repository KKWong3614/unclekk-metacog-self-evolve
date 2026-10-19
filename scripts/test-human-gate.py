#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W1 人类闸密码学身份绑定测试套件（系统级强制可控自指）

v2.5.7（M-7 闭环）变更：人类签名合并到 apply 时刻（TTY 口令签绑定签名，覆盖
「提案 id + 内容哈希 + 试用窗起点 trial_from_index」）。不再有独立的 `confirm --approve`。
本套件相应适配：
  - TTY 强制：非交互环境一律拒绝 confirm（AI 无法伪造 TTY 隐藏输入）；apply 人类签名亦需 TTY
  - 密钥生命周期：keygen 生成 RSA-2048 密钥对；私钥口令加密落盘、公钥明文存盘；
    明文私钥不落盘、口令不落盘；错误口令拒绝；重复 keygen 幂等
  - 绑定签名：v2.5.7 起签名覆盖 (id + chash + t0)；改内容 / 换提案 id / 改写 trial_from_index → 验签失败
  - M-7：攻击者改写受信任锚的 trial_from_index（保持有效/旧签名）→ 验签失败 HOLD（防过拟合保证不破）
  - 自签废除：--human-ok 对 requires_human 提议一律 rc=2；无凭证 rc=2（D1 语义保留）；伪造 sig rc=2
  - 无凭证需求提案不受影响（正常 apply）

TTY 场景用 monkeypatch 模拟（_require_tty / getpass.getpass）；等价于人类在真实终端操作后的落账结果。
绑定签名直接以已知口令解密私钥构造（等价于人类 TTY 签名的落账结果）。
"""
import io
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

import shutil
import sys
import json
import tempfile
import base64
from pathlib import Path
from types import SimpleNamespace

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))
import metacog

# v2.8.2 C-11：全局允许 legacy（无外部锚）回落（部署契约逃生舱），使本套件既有 check_pubkey_root
# legacy 断言不误伤（C-11 默认 deny 会令 legacy 部署 check_pubkey_root 失败；此处开启逃生舱模拟 legacy 部署）。
_os.environ["METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"] = "1"


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
        print("W1 人类闸测试结果: {}/{} PASS".format(self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _new_store_inited():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_w1_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    return st, tmp


def _keygen_ns(tmp):
    """v2.5.3（F-2）：keygen 须 --nonce-file 离线授权。返回带临时授权凭据的 keygen 参数。"""
    nonce = Path(tmp) / "keygen_nonce.txt"
    nonce.write_text("offline-auth-nonce-9f3c2a7b", encoding="utf-8")  # >=16 字符随机串
    return SimpleNamespace(keygen=True, init=False, approve=False, id=None, nonce_file=str(nonce))


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


def _binding_sig(st, p, t0, passphrase):
    """v2.5.7：直接在测试内用已知口令解密私钥，对绑定消息 (id, chash, t0) 签名。

    等价于人类在 TTY 运行 `apply` 交互式输入口令签绑定签名后的落账结果。"""
    guard = metacog.read_json(st.human_guard, {})
    priv_json = metacog.sigcrypto.decrypt_priv_str(guard["privkey_enc"], passphrase)
    priv = metacog.sigcrypto.deserialize_priv(priv_json)
    chash = metacog.proposal_content_hash(p)
    msg = metacog.sigcrypto.approval_message(str(p["id"]), chash, t0)
    return base64.b64encode(metacog.sigcrypto.sign(priv, msg)).decode("ascii")


def _run(fn, *a):
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = fn(*a)
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


def _apply_args(pid=None, sig=None, human_ok=False):
    return SimpleNamespace(id=pid, sig=sig, human_ok=human_ok,
                           git=False, no_git=True)


def _make_human_proposal(st, pid="P-M1X", content="- 元层策略微调", requires_human=True):
    p = {"id": pid, "status": "gated", "requires_human": requires_human,
         "artifact": "M1", "op": "add", "content": content,
         "reason": "test", "episodes": [], "target": None}
    metacog.write_json(st.quarantine / (pid + ".json"), p)
    return p


def test_tty_enforcement():
    """非 TTY 环境 confirm 一律拒绝（强制链第一环）；apply 人类签名亦需 TTY。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        rc, out = _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        r.add("非 TTY confirm --keygen 拒绝", rc == 2 and "TTY" in out, "rc={}".format(rc))
        # v2.5.7：不再有 confirm --approve；apply 需 TTY 人类签名（无 --sig 时）
        _make_human_proposal(st, "P-TTY")
        rc2, out2 = _run(metacog.cmd_apply, st, _apply_args(pid="P-TTY"))
        r.add("非 TTY apply 人类签名拒绝", rc2 == 2 and "TTY" in out2, "rc={}".format(rc2))
        r.add("口令文件未创建", not st.human_guard.exists(), "guard 不存在")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_keygen_and_passphrase():
    """keygen 生成密钥对；明文私钥/口令不落盘；错误口令拒绝；重复 keygen 幂等。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        rc, out = _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        r.add("keygen 成功", rc == 0, "rc={}".format(rc))
        guard = metacog.read_json(st.human_guard, {})
        r.add("存公钥+密文私钥", bool(guard.get("pubkey")) and bool(guard.get("privkey_enc")), "keys 存在")
        r.add("明文私钥不落盘", "correct-horse" not in metacog.read_text(st.human_guard)
              and "d\"" not in metacog.read_text(st.human_guard).split("privkey_enc", 1)[-1][:40],
              "无明文私钥")
        r.add("加密算法标记", guard.get("algo", "").startswith("rsa-2048"), "algo={}".format(guard.get("algo")))

        rc, out = _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        r.add("重复 keygen 幂等", rc == 0 and "已存在" in out, "rc={}".format(rc))

        # 错误口令 → bind_human_signature 拒绝（等价于 apply 交互式签名被拒；v2.5.7 取代 approve）
        _make_human_proposal(st, "P-X2")
        px = st.find_proposal("P-X2")
        try:
            st.bind_human_signature(px, metacog.proposal_content_hash(px), 0, passphrase="wrong-pass")
            r.add("错误口令拒绝", False, "应抛异常")
        except Exception as e:
            r.add("错误口令拒绝", "口令错误" in str(e), "err={}".format(e))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_sign_and_apply():
    """正确口令签绑定签名 → apply --sig 成功；内容篡改/换提案 → 验签失败。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        p = _make_human_proposal(st, "P-M1X")
        # v2.5.7：apply 时 episode 数为 0 → t0=0；直接以已知口令签绑定消息
        sig = _binding_sig(st, p, 0, "correct-horse")
        r.add("绑定签名已生成", bool(sig), "sig={}".format((sig or "")[:12] + "..."))

        # 正确提案 + 正确绑定签名 → 成功
        rc, out = _run(metacog.cmd_apply, st, _apply_args(pid="P-M1X", sig=sig))
        r.add("apply --sig 成功", rc == 0, "rc={}".format(rc))
        saved = [p for p in st.proposals() if p["id"] == "P-M1X"][0]
        r.add("提案转 trial", saved["status"] == "trial", "status={}".format(saved["status"]))
        # 受信任锚内嵌绑定签名（关闭 7.1）
        applied_rec = st.latest_apply_record("P-M1X")
        r.add("受信任锚含人类绑定签名", bool(applied_rec and applied_rec.get("human_sig")), "anchor sig")

        # 换提案 id → 内容哈希不同 → 验签失败（绑定校验）
        p_other = _make_human_proposal(st, "P-OTHER", content="- 元层策略微调")
        sig_other = _binding_sig(st, p_other, 0, "correct-horse")
        # 用 P-M1X 的 sig 去 apply P-OTHER → 验签失败
        rc, out = _run(metacog.cmd_apply, st, _apply_args(pid="P-OTHER", sig=sig))
        r.add("换提案 id 验签失败", rc == 2 and "无效" in out, "rc={}".format(rc))

        # 篡改内容后重签路径：原提案已 trial；重建 gated 并篡改，用原 sig → 失败
        _make_human_proposal(st, "P-M1X", content="- 被篡改的元层策略")
        rc, out = _run(metacog.cmd_apply, st, _apply_args(pid="P-M1X", sig=sig))
        r.add("内容篡改验签失败", rc == 2 and "无效" in out, "rc={}".format(rc))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_self_sign_abolished():
    """--human-ok 废除：requires_human 提议带 --human-ok 也 rc=2；无凭证 rc=2（D1 保留）；伪造 sig rc=2。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        _make_human_proposal(st, "P-SELF")
        before = st.artifact_path("M1").read_text(encoding="utf-8")

        rc, out = _run(metacog.cmd_apply, st, _apply_args(pid="P-SELF", human_ok=True))
        r.add("--human-ok 自签被拒", rc == 2 and "已废除" in out, "rc={}".format(rc))
        rc2, out2 = _run(metacog.cmd_apply, st, _apply_args(pid="P-SELF", human_ok=False))
        r.add("无凭证 D1 拒绝保留", rc2 == 2 and ("人类确认闸" in out2 or "需人类确认" in out2), "rc={}".format(rc2))
        rc3, out3 = _run(metacog.cmd_apply, st, _apply_args(pid="P-SELF", sig="deadbeef" * 8))
        r.add("伪造 sig 拒绝", rc3 == 2, "rc={}".format(rc3))

        after = st.artifact_path("M1").read_text(encoding="utf-8")
        r.add("制品未被写入", before == after, "M1 未变")
        saved = [p for p in st.proposals() if p["id"] == "P-SELF"][0]
        r.add("提案保持 gated", saved["status"] == "gated", "status={}".format(saved["status"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_no_human_needed():
    """非 requires_human 提议无需凭证照常应用。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        _make_human_proposal(st, "P-NORMAL", requires_human=False)
        rc, out = _run(metacog.cmd_apply, st, _apply_args(pid="P-NORMAL"))
        r.add("普通提案无需凭证", rc == 0, "rc={}".format(rc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_p0_pubkey_root_pinning():
    """P0：公钥信任根钉固。替换 human-guard.json 公钥（攻击者自签）必须被 apply 拒绝（fail-closed）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        # 信任根已钉固至 CONTRACT.md，且与当前公钥一致
        pinned = st.pinned_human_pubkey_fingerprint()
        r.add("信任根已钉固至 CONTRACT.md", bool(pinned), "pinned={}".format(pinned))
        live = st.human_pubkey_fingerprint()
        r.add("当前指纹与钉固一致", live == pinned, "live={}".format(live))
        # human-guard.json 已纳入 D4 快照
        gdata = metacog.read_json(st.integrity, {})
        r.add("信任根纳入 D4 快照", metacog.Store.GUARD_INTEGRITY_KEY in gdata, "snapshot 存在")

        if metacog.sigcrypto is not None:
            # 攻击者生成自己的密钥对并替换 human-guard.json 的公钥
            apub, apriv = metacog.sigcrypto.gen_keypair(2048)
            guard = metacog.read_json(st.human_guard, {})
            guard["pubkey"] = metacog.sigcrypto.serialize_pub(apub)
            metacog.write_json(st.human_guard, guard)
            root_ok, root_reason = st.check_pubkey_root()
            r.add("替换公钥后信任根校验失败", (not root_ok) and root_reason == "pubkey-root-mismatch",
                  "reason={}".format(root_reason))

            # 攻击者用自己私钥伪造签名（内容哈希绑定），apply 应被信任根校验拒绝
            _make_human_proposal(st, "P-ATTACK")
            chash = metacog.proposal_content_hash(st.find_proposal("P-ATTACK"))
            msg = metacog.sigcrypto.approval_message("P-ATTACK", chash)  # 旧格式（无 t0）
            forged_sig = metacog.base64.b64encode(metacog.sigcrypto.sign(apriv, msg)).decode("ascii")
            rc, out = _run(metacog.cmd_apply, st, _apply_args(pid="P-ATTACK", sig=forged_sig))
            r.add("替换公钥+伪造签名被信任根拒绝", rc == 2 and "pubkey-root-mismatch" in out, "rc={}".format(rc))
        else:
            r.add("sigcrypto 可用（跳过攻击模拟）", False, "sigcrypto 为 None")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_b2_anchor_missing_sig_holds():
    """B.2：requires_human 提案的锚缺有效签名 → resolve_trial_start 一律 HOLD；非 requires_human 不误伤。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        # 正常人类绑定签名 apply → 建立合法锚（t0=0，空 episode）
        p = _make_human_proposal(st, "P-B2")
        sig = _binding_sig(st, p, 0, "correct-horse")
        rc, out = _run(metacog.cmd_apply, st, _apply_args(pid="P-B2", sig=sig))
        r.add("正常人类签名 apply 成功", rc == 0, "rc={}".format(rc))
        pp = st.find_proposal("P-B2")
        pp["status"] = "trial"
        start, hold = metacog.resolve_trial_start(st, pp, [])
        r.add("合法绑定签名锚 resolve 不 HOLD", hold is None, "hold={}".format(hold))

        # 攻击者伪造「无签名锚」：直接覆写 applies.jsonl，移除 human_sig / content_hash
        applied = st.latest_apply_record("P-B2")
        forged = dict(applied)
        forged.pop("human_sig", None)
        forged.pop("content_hash", None)
        metacog.write_text(st.applies, json.dumps(forged, ensure_ascii=False) + "\n")
        p2 = st.find_proposal("P-B2")
        p2["status"] = "trial"
        start2, hold2 = metacog.resolve_trial_start(st, p2, [])
        r.add("无签名锚(requires_human)一律 HOLD", hold2 is not None, "hold={}".format(hold2))

        # 回归：非 requires_human 提案经正常 apply（无签名）落入合法锚，仍应信任（不误伤正常流程）
        # 注（v2.5.8）：不再手动覆写 applies.jsonl 制造「已篡改」基线——H-2 的 D4 校验会据此 HOLD，
        # 与「正常合法锚应信任」的回归意图冲突；改走正常 apply 路径建立正确 D4 基线。
        _make_human_proposal(st, "P-NB2", requires_human=False)
        rc_nb, out_nb = _run(metacog.cmd_apply, st, _apply_args(pid="P-NB2"))
        r.add("非 requires_human 正常 apply 成功", rc_nb == 0, "rc={}".format(rc_nb))
        pnb = st.find_proposal("P-NB2")
        pnb["status"] = "trial"
        start3, hold3 = metacog.resolve_trial_start(st, pnb, [])
        r.add("非 requires_human 无签名锚仍信任", hold3 is None and start3 == 0,
              "hold={}, start={}".format(hold3, start3))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_p0_legacy_install_autopin():
    """P0 前向兼容（v2.5.2 更新）：现存安装（有 guard、CONTRACT.md 无钉固）→ verify 保持只读（不钉固）；
    经 keygen（幂等）/ apply 补钉固后，替换公钥被拒。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        # 模拟升级前状态：去掉 CONTRACT.md 的钉固节（## 7）
        cpath = st.root / "CONTRACT.md"
        text = cpath.read_text(encoding="utf-8")
        idx = text.find("## 7.")
        if idx != -1:
            cpath.write_text(text[:idx].rstrip() + "\n", encoding="utf-8")
        r.add("升级前 CONTRACT.md 无钉固", st.pinned_human_pubkey_fingerprint() is None, "pinned=None")
        # v2.5.2：verify 必须保持只读——运行 verify 后钉固仍应为 None（不得自动钉固）
        metacog.cmd_verify(st, SimpleNamespace())
        r.add("verify 只读不钉固（v2.5.2）", st.pinned_human_pubkey_fingerprint() is None, "pinned 仍 None")
        # 现存安装经 keygen（幂等跳过）补钉固信任根
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        pinned = st.pinned_human_pubkey_fingerprint()
        live = st.human_pubkey_fingerprint()
        r.add("keygen 幂等补钉固信任根", pinned == live, "pinned={}, live={}".format(pinned, live))
        # 钉固已生效后，替换公钥 + 伪造签名应被拒绝
        if metacog.sigcrypto is not None:
            apub, apriv = metacog.sigcrypto.gen_keypair(2048)
            guard = metacog.read_json(st.human_guard, {})
            guard["pubkey"] = metacog.sigcrypto.serialize_pub(apub)
            metacog.write_json(st.human_guard, guard)
            p = _make_human_proposal(st, "P-LEGACY")
            chash = metacog.proposal_content_hash(p)
            msg = metacog.sigcrypto.approval_message("P-LEGACY", chash)
            forged = metacog.base64.b64encode(metacog.sigcrypto.sign(apriv, msg)).decode("ascii")
            rc, out = _run(metacog.cmd_apply, st, _apply_args(pid="P-LEGACY", sig=forged))
            r.add("补钉固后替换公钥被拒绝", rc == 2 and "pubkey-root-mismatch" in out, "rc={}".format(rc))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_v252_hardening():
    """v2.5.2：P0 信任根 fail-closed；sigcrypto 不可用统一 HOLD；脚本完整性检出篡改。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        # P0 fail-closed：移除 CONTRACT.md 钉固指纹行（使 pinned 失效）→ check_pubkey_root 必须拒绝
        ct = st.contract.read_text(encoding="utf-8")
        ct2 = "\n".join(ln for ln in ct.splitlines() if "human_pubkey_fingerprint" not in ln)
        st.contract.write_text(ct2 + "\n", encoding="utf-8")
        ok_root, reason = st.check_pubkey_root()
        r.add("未钉固→fail-closed(no-pinned-root)", (not ok_root) and reason == "no-pinned-root", "reason={}".format(reason))
        st.contract.write_text(ct, encoding="utf-8")  # 还原

        # C-4：sigcrypto 不可用时，非 requires_human 旧锚也必须 HOLD（不再降级信任）
        old_sc = metacog.sigcrypto
        metacog.sigcrypto = None
        try:
            _make_human_proposal(st, "P-HOLD", requires_human=False)
            metacog.append_jsonl(st.applies, {"proposal_id": "P-HOLD", "trial_from_index": 3})
            p = [x for x in st.proposals() if x["id"] == "P-HOLD"][0]
            start, hold = metacog.resolve_trial_start(st, p, [])
            r.add("sigcrypto 不可用→旧锚 HOLD", start == 0 and hold is not None and "sigcrypto 不可用" in hold, "hold={}".format(hold))
        finally:
            metacog.sigcrypto = old_sc

        # M-5：写入假脚本 → 记录基线 → 篡改 → verify_script_integrity 检出
        fake_dir = Path(tempfile.mkdtemp(prefix="metacog_scr_"))
        fake_py = fake_dir / "metacog.py"
        fake_py.write_text("original", encoding="utf-8")
        st.script_dir = fake_dir
        st.record_script_integrity()
        g = metacog.read_json(st.integrity, {})
        r.add("脚本基线已记录", "script:metacog.py" in g, "key 存在")
        fake_py.write_text("tampered", encoding="utf-8")
        res = st.verify_script_integrity()
        tampered = [k for k, ok in res if ok is False]
        r.add("脚本篡改被检出", "script:metacog.py" in tampered, "res={}".format(res))
        shutil.rmtree(fake_dir, ignore_errors=True)
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_m7_binding_sig_blocks_t0_rewrite():
    """M-7 闭环：受信任锚的人类绑定签名覆盖 trial_from_index。

    - 合法绑定签名锚（签名覆盖 id+chash+t0，t0 与锚一致）→ resolve 通过；
    - 攻击者改写锚的 trial_from_index（保持同一有效签名）→ 验签失败 → HOLD（防过拟合保证不被绕过）；
    - M-7 前旧格式签名（仅 id+chash，未绑定 t0）→ 即便有效也判 legacy-unbound → HOLD（强制重签）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        # 建立合法锚：绑定签名覆盖 (id, chash, t0=5)
        p = _make_human_proposal(st, "P-M7", content="- 元层策略微调")
        chash = metacog.proposal_content_hash(p)
        t0_real = 5
        sig = _binding_sig(st, p, t0_real, "correct-horse")
        for i in range(t0_real):
            metacog.append_jsonl(st.episodes, {"id": "E{:03d}".format(i), "utility": 0.7, "violations": 0})
        metacog.append_jsonl(st.applies, {"proposal_id": "P-M7", "trial_from_index": t0_real,
                                          "artifact": "M1", "entry_id": "M-001",
                                          "human_sig": sig, "content_hash": chash})
        pp = st.find_proposal("P-M7")
        pp["status"] = "trial"
        start, hold = metacog.resolve_trial_start(st, pp, [])
        r.add("合法绑定签名锚 resolve 通过", hold is None and start == t0_real, "start={},hold={}".format(start, hold))

        # 攻击者改写 trial_from_index=0（全历史=留出集），保持同一 sig → 验签必须失败 → HOLD
        forged = {"proposal_id": "P-M7", "trial_from_index": 0, "artifact": "M1",
                  "entry_id": "M-001", "human_sig": sig, "content_hash": chash}
        metacog.write_text(st.applies, json.dumps(forged, ensure_ascii=False) + "\n")
        pp2 = st.find_proposal("P-M7")
        pp2["status"] = "trial"
        start2, hold2 = metacog.resolve_trial_start(st, pp2, [])
        r.add("改写 trial_from_index=0 验签失败 HOLD", hold2 is not None, "hold={}".format(hold2))

        # M-7 前旧格式签名（仅 id+chash，未绑定 t0）：真实但缺 t0 绑定 → legacy-unbound → HOLD
        old_msg = metacog.sigcrypto.approval_message("P-M7", chash)  # 无 t0
        old_sig = metacog.base64.b64encode(metacog.sigcrypto.sign(
            metacog.sigcrypto.deserialize_priv(
                metacog.sigcrypto.decrypt_priv_str(
                    metacog.read_json(st.human_guard, {})["privkey_enc"], "correct-horse")),
            old_msg)).decode("ascii")
        legacy = {"proposal_id": "P-M7", "trial_from_index": 5, "artifact": "M1",
                   "entry_id": "M-001", "human_sig": old_sig, "content_hash": chash}
        metacog.write_text(st.applies, json.dumps(legacy, ensure_ascii=False) + "\n")
        pp3 = st.find_proposal("P-M7")
        pp3["status"] = "trial"
        start3, hold3 = metacog.resolve_trial_start(st, pp3, [])
        r.add("旧格式签名(未绑定t0)→legacy-unbound HOLD", hold3 is not None, "hold={}".format(hold3))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_f2_nonce_gate():
    """v2.5.3（F-2）：keygen 缺 --nonce-file 一律拒绝（防 Agent 经 pty/Bash 静默重置信任根）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        rc, out = _run(metacog.cmd_confirm, st, SimpleNamespace(keygen=True, init=False, approve=False, id=None, nonce_file=None))
        r.add("缺 nonce-file 拒绝", rc == 2 and "离线授权" in out, "rc={}".format(rc))
        r.add("缺 nonce-file 未生成 guard", not st.human_guard.exists(), "guard 不存在")
        rc2, out2 = _run(metacog.cmd_confirm, st, _keygen_ns(tmp))
        r.add("合法 nonce 授权成功", rc2 == 0 and st.human_guard.exists(), "rc={}".format(rc2))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_low6b_bad_pubkey_branch():
    """LOW-6b（v2.5.8）：verify_human_binding 返回 bad-pubkey 时，apply 分派表须 fail-closed
    （human_blocked + rc=2 + 指路 confirm --keygen），不得落入 else 静默 warn。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        p = _make_human_proposal(st, "P-BPK")
        # 隔离验证分派逻辑：强制 verify_human_binding 返回 bad-pubkey（无需构造畸形公钥）
        orig = st.verify_human_binding
        st.verify_human_binding = lambda *a, **k: (False, "bad-pubkey")
        try:
            rc, out = _run(metacog.cmd_apply, st, _apply_args(pid="P-BPK", sig="x"))
        finally:
            st.verify_human_binding = orig
        r.add("bad-pubkey → rc=2", rc == 2, "rc={}".format(rc))
        r.add("bad-pubkey 提示重建密钥", "bad-pubkey" in out and "confirm --keygen" in out,
              "out={}".format(out[:160]))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_m8_bool_guard():
    """M-8（v2.5.8）：trial_from_index 为 bool 也须 HOLD（isinstance(True,int) is True 漏洞）。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        p = _make_human_proposal(st, "P-BOOL", requires_human=False)
        # bool 伪装成 int：True 会被 isinstance(int) 误判通过，type() is int 必须拦下
        metacog.append_jsonl(st.applies, {"proposal_id": "P-BOOL", "trial_from_index": True,
                                          "artifact": "M1", "entry_id": "M-001",
                                          "human_sig": None, "content_hash": None})
        p["status"] = "trial"
        start, hold = metacog.resolve_trial_start(st, p, [])
        r.add("bool 型 trial_from_index HOLD", hold is not None, "hold={}".format(hold))
        # 对照：正常 int 不被误伤
        metacog.write_text(st.applies, json.dumps(
            {"proposal_id": "P-BOOL", "trial_from_index": 0, "artifact": "M1",
             "entry_id": "M-001", "human_sig": None, "content_hash": None},
            ensure_ascii=False) + "\n")
        start2, hold2 = metacog.resolve_trial_start(st, p, [])
        r.add("正常 int 不误伤", hold2 is None and start2 == 0, "hold={},start={}".format(hold2, start2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_h1_nonreq_content_hash_binding():
    """H-1（v2.5.8）：非 requires_human 锚内嵌 content_hash，若与提案当前内容不符 → HOLD（直写篡改检出）；
    正常锚（content_hash 匹配）仍信任。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        p = _make_human_proposal(st, "P-H1", requires_human=False, content="- 正常内容")
        chash = metacog.proposal_content_hash(p)
        metacog.append_jsonl(st.applies, {"proposal_id": "P-H1", "trial_from_index": 0,
                                          "artifact": "M1", "entry_id": "M-001",
                                          "human_sig": None, "content_hash": chash})
        p["status"] = "trial"
        s1, h1 = metacog.resolve_trial_start(st, p, [])
        r.add("content_hash 匹配→信任", h1 is None and s1 == 0, "h1={},s1={}".format(h1, s1))
        # 篡改提案内容（绕过签名，因非 requires_human 无签名）：锚 content_hash 仍旧 → 不符 → HOLD
        p2 = _make_human_proposal(st, "P-H1", requires_human=False, content="- 被篡改内容")
        p2["status"] = "trial"
        s2, h2 = metacog.resolve_trial_start(st, p2, [])
        r.add("提案被篡改→content_hash 不符 HOLD", h2 is not None, "h2={}".format(h2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_h2_applies_jsonl_tamper_detected():
    """H-2（v2.5.8）：applies.jsonl 被直写篡改 t0 后，resolve_trial_start 经 D4 快照检出 → HOLD。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        # 经正常 apply 落合法非 requires_human 锚（同时建立 applies.jsonl D4 快照）
        p = _make_human_proposal(st, "P-H2", requires_human=False, content="- 内容")
        rc, out = _run(metacog.cmd_apply, st, _apply_args(pid="P-H2"))
        r.add("正常 apply 成功", rc == 0, "rc={}".format(rc))
        p["status"] = "trial"
        s0, h0 = metacog.resolve_trial_start(st, p, [])
        r.add("合法锚信任", h0 is None and s0 == 0, "h0={},s0={}".format(h0, s0))
        # 直写篡改 applies.jsonl 的 trial_from_index（绕过 apply 重拍基线）
        recs = [json.loads(x) for x in st.applies.read_text(encoding="utf-8").splitlines() if x.strip()]
        for rec in recs:
            if rec.get("proposal_id") == "P-H2":
                rec["trial_from_index"] = 999
        st.applies.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in recs) + "\n", encoding="utf-8")
        s1, h1 = metacog.resolve_trial_start(st, p, [])
        r.add("直写篡改 applies.jsonl → D4 检出 HOLD", h1 is not None and "D4" in h1, "h1={}".format(h1))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_m4_resign_legacy_anchor():
    """M-4（v2.5.8）：legacy-unbound 锚（M-7 前旧格式签名，仅 id+chash）可经 resign 重签为绑定签名。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        # 制造一个 legacy 锚（旧格式签名，仅覆盖 id+chash，未绑定 t0；content_hash=None）
        p = _make_human_proposal(st, "P-LEG", content="- 元层策略微调")
        chash = metacog.proposal_content_hash(p)
        old_msg = metacog.sigcrypto.approval_message("P-LEG", chash)  # 无 t0
        old_sig = metacog.base64.b64encode(metacog.sigcrypto.sign(
            metacog.sigcrypto.deserialize_priv(
                metacog.sigcrypto.decrypt_priv_str(
                    metacog.read_json(st.human_guard, {})["privkey_enc"], "correct-horse")),
            old_msg)).decode("ascii")
        t0_legacy = 2
        metacog.append_jsonl(st.applies, {"proposal_id": "P-LEG", "trial_from_index": t0_legacy,
                                          "artifact": "M1", "entry_id": "M-001",
                                          "human_sig": old_sig, "content_hash": None})
        p["status"] = "trial"
        start0, hold0 = metacog.resolve_trial_start(st, p, [])
        r.add("重签前 legacy-unbound HOLD", hold0 is not None, "hold0={}".format(hold0))
        # resign：保留原始 t0，重签绑定签名（TTY 口令）
        rc, out = _run(metacog.cmd_resign, st, SimpleNamespace(id="P-LEG", sig=None))
        r.add("resign 命令成功", rc == 0, "rc={}".format(rc))
        # resign 后：latest 锚为绑定签名，resolve 通过且 t0 保留
        rec = st.latest_apply_record("P-LEG")
        r.add("重签后锚含绑定签名", rec.get("human_sig") is not None and rec.get("content_hash") == chash,
              "rec sig={}, chash 匹配={}".format(rec.get("human_sig") is not None, rec.get("content_hash") == chash))
        r.add("重签后保留原始 t0", rec.get("trial_from_index") == t0_legacy,
              "t0={}".format(rec.get("trial_from_index")))
        start1, hold1 = metacog.resolve_trial_start(st, p, [])
        r.add("重签后 resolve 不 HOLD", hold1 is None and start1 == t0_legacy,
              "hold1={},start1={}".format(hold1, start1))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_n1p_resign_int_guard():
    """N1'（v2.5.8 收口）：cmd_resign 对 latest_apply_record 中畸形 trial_from_index
    （bool/str/list/null/缺键）须 fail-closed 返回 2，不崩溃、不写入新锚。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        p = _make_human_proposal(st, "P-N1", content="- 元层策略微调")
        for bad_t0, label in ((True, "bool True"), ("abc", "str"), ([1], "list"),
                              (None, "null"), ("MISSING", "缺键")):
            rec = {"proposal_id": "P-N1", "artifact": "M1", "entry_id": "M-001",
                   "human_sig": None, "content_hash": None}
            if bad_t0 != "MISSING":
                rec["trial_from_index"] = bad_t0
            metacog.write_jsonl(st.applies, [rec])
            before = len(metacog.read_jsonl(st.applies))
            rc, out = _run(metacog.cmd_resign, st, SimpleNamespace(id="P-N1", sig=None))
            after = len(metacog.read_jsonl(st.applies))
            r.add("N1' {} 返回 2".format(label), rc == 2, "rc={}".format(rc))
            r.add("N1' {} 未写入新锚".format(label), after == before,
                  "before={},after={}".format(before, after))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def main():
    all_ok = True
    grand_p = grand_f = 0
    for fn in (test_tty_enforcement, test_keygen_and_passphrase,
               test_sign_and_apply, test_self_sign_abolished,
               test_no_human_needed, test_p0_pubkey_root_pinning,
               test_b2_anchor_missing_sig_holds, test_p0_legacy_install_autopin,
               test_v252_hardening, test_m7_binding_sig_blocks_t0_rewrite,
               test_f2_nonce_gate,
               test_low6b_bad_pubkey_branch, test_m8_bool_guard,
               test_h1_nonreq_content_hash_binding, test_h2_applies_jsonl_tamper_detected,
               test_m4_resign_legacy_anchor, test_n1p_resign_int_guard):
        print("\n--- {} ---".format(fn.__name__))
        res = fn()
        grand_p += res.passed
        grand_f += res.failed
        all_ok = res.summary() and all_ok
    print("\n" + "=" * 60)
    print("全文件总计: {}/{} PASS（口径=断言行）".format(grand_p, grand_p + grand_f))
    print("=" * 60)
    return 0 if (all_ok and grand_f == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
