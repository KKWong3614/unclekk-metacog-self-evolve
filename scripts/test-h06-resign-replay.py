#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H-06 回归（审计 v2.27.13）：cmd_resign 必须消费一次性人类绑定签名，阻断同一签名被 resign 重放。

机理：旧版 cmd_resign 仅 verify_human_binding（验签）但不消费该一次性签名；而 apply 消费签名。
于是同一个人类签名 S 可同时授权一次 apply 与一次 resign（或 reverse），破坏「一签名=一授权」。

修复（metacog.py:3627）：resign 在落盘前于文件锁临界区内调用 consume_human_sig_atomic(sig)，
与 apply 同构。注 sigcrypto.sign 为确定性签名（同 (id,chash,t0) 消息得同签名），故：
  - 已被 apply 消费的绑定签名 S 再次用于 resign → 必须被拒（rc=2，消费失败）；
  - 合法重签（legacy-unbound 锚 → 绑定签名，走 TTY 重签生成新绑定 sig）仍成功（rc=0）；
  - 该合法重签生成的新绑定 sig 被消费后，再次 resign 复用 → 必须被拒（rc=2）。

零第三方依赖；import metacog 直接单测。复用 test-human-gate 的人类签名辅助。
"""
import io
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

import shutil
import sys
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

# 允许 legacy 回落；本地测试允许默认共享锚（与 run_all_tests 全局一致）。
_os.environ["METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"] = "1"
_os.environ["METACOG_TRUST_ROOT_ANCHOR_KEY"] = "bWV0YWNvZy10ZXN0LWFuY2hvci1rZXktMDEyMzQ1Njc4OWFiY2RlZi0wMTIzNDU2Nzg5"


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def add(self, name, ok, detail=""):
        self.passed += ok
        self.failed += (not ok)
        print("  [{}] {}{}".format("PASS" if ok else "FAIL", name,
                                    (" - " + detail) if detail else ""))

    def summary(self):
        total = self.passed + self.failed
        print("\n" + "=" * 60)
        print("H-06 resign 一次性签名回归: {}/{} PASS".format(self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _run(fn, *a):
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = fn(*a)
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


def _new_store_inited():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_h06_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    return st, tmp


def _keygen_ns(tmp):
    nonce = Path(tmp) / "keygen_nonce.txt"
    nonce.write_text("offline-auth-nonce-9f3c2a7b", encoding="utf-8")
    return SimpleNamespace(keygen=True, init=False, approve=False, id=None, nonce_file=str(nonce))


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


def _binding_sig(st, p, t0, passphrase):
    guard = metacog.read_json(st.human_guard, {})
    priv_json = metacog.sigcrypto.decrypt_priv_str(guard["privkey_enc"], passphrase)
    priv = metacog.sigcrypto.deserialize_priv(priv_json)
    chash = metacog.proposal_content_hash(p)
    msg = metacog.sigcrypto.approval_message(str(p["id"]), chash, t0)
    return base64.b64encode(metacog.sigcrypto.sign(priv, msg)).decode("ascii")


def _apply_args(pid=None, sig=None, human_ok=False):
    return SimpleNamespace(id=pid, sig=sig, human_ok=human_ok, git=False, no_git=True)


def _make_human_proposal(st, pid="P-H06", content="- 元层策略微调", requires_human=True):
    p = {"id": pid, "status": "gated", "requires_human": requires_human,
         "artifact": "M1", "op": "add", "content": content,
         "reason": "test", "episodes": [], "target": None}
    metacog.write_json(st.quarantine / (pid + ".json"), p)
    return p


def test_resign_consumes_used_signature():
    """核心修复证明：已被 apply 消费的绑定签名 S 再用于 resign → 必须被拒（rc=2）。

    无此修复时 resign 不消费签名，S 可同时授权 apply 与 resign（重放）。"""
    t = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        p = _make_human_proposal(st, "P-H06A")
        sig = _binding_sig(st, p, 0, "correct-horse")

        # apply --sig S：消费 S，建立受信任锚
        rc_a, _ = _run(metacog.cmd_apply, st, _apply_args(pid="P-H06A", sig=sig))
        t.add("apply --sig 成功(消费S)", rc_a == 0, "rc={}".format(rc_a))
        t.add("apply 后存在受信任锚", st.latest_apply_record("P-H06A") is not None, "anchor 存在")

        # resign --sig S（同一绑定签名）→ 修复后必须因消费失败被拒
        rc_r, out_r = _run(metacog.cmd_resign, st, SimpleNamespace(id="P-H06A", sig=sig))
        t.add("resign 复用已消费签名被拒", rc_r == 2 and "消费失败" in out_r,
              "rc={}".format(rc_r))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_legacy_anchor_resign_still_works_and_consumes():
    """合法重签路径仍可用，且重签后二次复用被拒（修复在 TTY 分支同样消费）。"""
    t = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        # 制造 legacy-unbound 锚（旧格式签名，仅 id+chash，未绑定 t0；binding sig 未进入消费账本）
        p = _make_human_proposal(st, "P-H06B", content="- 元层策略微调")
        chash = metacog.proposal_content_hash(p)
        old_msg = metacog.sigcrypto.approval_message("P-H06B", chash)  # 无 t0
        old_sig = base64.b64encode(metacog.sigcrypto.sign(
            metacog.sigcrypto.deserialize_priv(
                metacog.sigcrypto.decrypt_priv_str(
                    metacog.read_json(st.human_guard, {})["privkey_enc"], "correct-horse")),
            old_msg)).decode("ascii")
        t0_legacy = 2
        metacog.append_jsonl(st.applies, {"proposal_id": "P-H06B", "trial_from_index": t0_legacy,
                                          "artifact": "M1", "entry_id": "M-001",
                                          "human_sig": old_sig, "content_hash": None})
        p["status"] = "trial"

        # 合法重签：resign --sig None（TTY）生成全新绑定 sig → 成功（rc=0）
        rc_r1, _ = _run(metacog.cmd_resign, st, SimpleNamespace(id="P-H06B", sig=None))
        t.add("合法重签(legacy→binding)成功", rc_r1 == 0, "rc={}".format(rc_r1))
        rec = st.latest_apply_record("P-H06B")
        t.add("重签后锚含绑定签名+chash", bool(rec and rec.get("human_sig"))
              and rec.get("content_hash") == chash, "binding ok")
        t.add("重签保留原始 t0", bool(rec) and rec.get("trial_from_index") == t0_legacy,
              "t0={}".format(rec.get("trial_from_index") if rec else None))

        # 二次 resign 重放已消费的同一签名串（H-06 真实攻击面）→ 消费失败必须被拒（rc=2）。
        # v2.27.17（nonce 化）：bind_human_signature 每次生成一次性 nonce，TTY 重签会产出
        # 全新合法签名（人类 TTY 授权的合法重签，非重放）——「确定性签名 = 天然一次性」的
        # 旧检测面随之失效；use-once 消费账本的防重放对象改为「同一签名串」，故重放攻击
        # 以「传入已消费签名」方式复现（与 apply --sig 重放同构）。
        _consumed_sig = rec.get("human_sig") if rec else None
        rc_r2, out_r2 = _run(metacog.cmd_resign, st,
                             SimpleNamespace(id="P-H06B", sig=_consumed_sig))
        t.add("重放已消费签名被拒", rc_r2 == 2 and "消费失败" in out_r2,
              "rc={}".format(rc_r2))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def main():
    r1 = test_resign_consumes_used_signature()
    r2 = test_legacy_anchor_resign_still_works_and_consumes()
    ok = r1.summary() and r2.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
