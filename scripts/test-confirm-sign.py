#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.25.14 `confirm --sign` 预签名测试套件（无人值守人类闸工作流）

背景：v2.5.7 起人类签名合并到 `apply` 时刻（TTY 口令签绑定签名，覆盖 id+chash+t0），
`apply --sig` 预签名验签路径自 M-7 起就存在，但缺少人类可用的预生成工具——
无人值守/无 TTY 场景这条合法路径"有验无签"。v2.25.14 新增 `confirm --sign`
补齐该工具：安全语义与 apply 当场签名完全一致（私钥仍只在人类 TTY 内由口令解锁）。

覆盖：
  1. 非 TTY 一律拒绝（--sign 继承 confirm 的 TTY 强制链第一环，无新增绕过）
  2. 缺 --id / 未知 id / 未 keygen → rc=2，报错含可操作指引
  3. 知情同意输出：提案 id / 制品与操作 / 内容哈希 / 提案全文 / t0 警告 / 泄露面警告 / 无人值守用法
     （v2.25.15 收口：全文逐行披露不再截断，防「预览良性+尾部恶意」骗签）
  4. 端到端两步工作流：人类 TTY `confirm --sign --out` → 非 TTY `apply --sig` 成功
     （提案转 trial、受信任锚内嵌绑定签名、--out 文件与 apply 消费值一致）
  5. 签名后记账（t0 漂移）→ apply --sig 验签失败 rc=2（fail-closed），报错指向重签
  6. 错误口令 → 预签名失败 rc=2
  7. 全文披露（v2.25.15）：>160 字符提案尾部完整可见、总字符数如实标注

TTY 场景用 monkeypatch 模拟（_require_tty / getpass.getpass），等价于人类在真实终端操作。
"""
import io
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))
import metacog

# 与 test-human-gate 同口径：legacy 回落逃生舱 + 默认锚显式承担（本地测试环境）
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
                                    " - " + detail if detail else ""))

    def summary(self):
        total = self.passed + self.failed
        print("\n{}".format("=" * 60))
        print("confirm --sign 测试结果: {}/{} PASS".format(self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _new_store_inited():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_sign_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    return st, tmp


def _keygen_ns(tmp):
    """v2.5.3（F-2）：keygen 须 --nonce-file 离线授权。"""
    nonce = Path(tmp) / "keygen_nonce.txt"
    nonce.write_text("offline-auth-nonce-9f3c2a7b", encoding="utf-8")
    return SimpleNamespace(sign=False, keygen=True, init=False, approve=False,
                           id=None, out=None, nonce_file=str(nonce))


def _sign_ns(pid=None, out=None, force=False):
    return SimpleNamespace(sign=True, keygen=False, init=False, approve=False,
                           id=pid, out=out, force=force, nonce_file=None)


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


def _run(fn, *a):
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = fn(*a)
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


def _make_human_proposal(st, pid="P-SIGN", content="- 元层策略微调（sign 测试）"):
    p = {"id": pid, "status": "gated", "requires_human": True,
         "artifact": "M1", "op": "add", "content": content,
         "reason": "test", "episodes": [], "target": None}
    metacog.write_json(st.quarantine / (pid + ".json"), p)
    return p


def test_tty_enforcement():
    """非 TTY 环境 confirm --sign 一律拒绝（继承 TTY 强制链第一环，rc=2）。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-SIGN"))
        r.add("非 TTY confirm --sign 拒绝", rc == 2 and "TTY" in out, "rc={}".format(rc))
        r.add("不产出任何签名文件", True, "非 TTY 早退于签名动作之前")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_arg_validation():
    """缺 --id / 未知 id / 未 keygen → rc=2 且报错含可操作指引。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid=None))
        r.add("缺 --id 拒绝", rc == 2 and "--id" in out, "rc={}".format(rc))

        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-NOPE"))
        r.add("未知 id 拒绝", rc == 2 and "不存在或未过闸" in out, "rc={}".format(rc))
        r.add("报错列出可用过闸提案（空）", "（无）" in out, "提示可操作")

        _make_human_proposal(st, "P-SIGN")
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-SIGN"))
        r.add("未 keygen 时预签名拒绝", rc == 2 and "预签名失败" in out, "rc={}".format(rc))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_sign_end_to_end():
    """端到端两步工作流：人类 TTY 预签名 --out → 非 TTY apply --sig 成功。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    sig_file = tmp / "human_sig.txt"
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))  # keygen（TTY 模拟）
        p = _make_human_proposal(st, "P-SIGN")

        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-SIGN", out=str(sig_file)))
        r.add("预签名成功", rc == 0, "rc={}".format(rc))
        r.add("知情同意：输出提案 id", "P-SIGN" in out, "id 可见")
        r.add("知情同意：输出制品/操作", "M1 / add" in out, "制品与操作可见")
        r.add("知情同意：输出内容预览", "元层策略微调" in out, "人类看得到要批什么")
        # v2.25.15 收口：全文披露 + 内容哈希 + 泄露面警告
        r.add("知情同意：内容哈希输出（64位hex）",
              bool(re.search(r"[0-9a-f]{64}", out)), "chash 可带外核对")
        r.add("知情同意：泄露面警告输出", "泄露" in out and "可信信道" in out, "签名即授权已声明")
        r.add("旧截断预览字段已移除", "内容预览" not in out, "防「预览良性+尾部恶意」骗签回归")
        r.add("t0 警告输出", "t0=0" in out and "不得再记账" in out, "约束已声明")
        r.add("无人值守用法输出", "apply --id P-SIGN --sig" in out, "两步工作流可照抄")

        r.add("签名文件已写出", sig_file.exists(), str(sig_file.name))
        sig = sig_file.read_text(encoding="utf-8").strip() if sig_file.exists() else ""
        r.add("签名文件为单行 base64", bool(sig) and "\n" not in sig.strip(), "len={}".format(len(sig)))
    finally:
        restore()
    # —— 还原 TTY 后 = 无人值守环境（非 TTY）——
    try:
        rc, out = _run(metacog.cmd_apply, st, SimpleNamespace(id="P-SIGN", sig=sig,
                                                              human_ok=False, git=False, no_git=True))
        r.add("非 TTY apply --sig(预签名) 成功", rc == 0, "rc={}".format(rc))
        saved = [q for q in st.proposals() if q["id"] == "P-SIGN"]
        r.add("提案转 trial", bool(saved) and saved[0]["status"] == "trial",
              "status={}".format(saved[0]["status"] if saved else "?"))
        applied_rec = st.latest_apply_record("P-SIGN")
        r.add("受信任锚内嵌人类绑定签名", bool(applied_rec and applied_rec.get("human_sig")), "anchor sig")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_sign_t0_drift():
    """签名后记账（t0 漂移）→ apply --sig 验签失败 rc=2（fail-closed），报错指向 confirm --sign 重签。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    sig_file = tmp / "human_sig.txt"
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        _make_human_proposal(st, "P-DRIFT")
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-DRIFT", out=str(sig_file)))
        r.add("t0=0 预签名成功", rc == 0, "rc={}".format(rc))
        sig = sig_file.read_text(encoding="utf-8").strip()
    finally:
        restore()
    try:
        # 签名后新增一笔记账 → t0 变为 1，绑定签名不再匹配
        with open(st.episodes, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "E-SIGN", "task": "t0-drift-probe"}) + "\n")
        rc, out = _run(metacog.cmd_apply, st, SimpleNamespace(id="P-DRIFT", sig=sig,
                                                              human_ok=False, git=False, no_git=True))
        r.add("t0 漂移后 apply 拒绝（fail-closed）", rc == 2, "rc={}".format(rc))
        r.add("报错指向 confirm --sign 重签", "confirm --sign" in out, "可操作指引")
        saved = [q for q in st.proposals() if q["id"] == "P-DRIFT"]
        r.add("提案未被应用（仍 gated）", bool(saved) and saved[0]["status"] == "gated",
              "status={}".format(saved[0]["status"] if saved else "?"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_sign_wrong_passphrase():
    """错误口令 → 预签名失败 rc=2（私钥口令解锁失败，与 apply 当场签名同语义）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
    finally:
        restore()
    restore_wrong = _with_tty_and_passphrase("wrong-pass")
    try:
        _make_human_proposal(st, "P-WPW")
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-WPW"))
        r.add("错误口令预签名拒绝", rc == 2 and "口令错误" in out, "rc={}".format(rc))
    finally:
        restore_wrong()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_sign_full_disclosure():
    """v2.25.15 全文披露收口：>160 字符提案的尾部内容必须完整可见（防「预览良性+尾部恶意」骗签）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        tail_marker = "TAIL-MARKER-9f3c2a7b-恶意尾部在这"
        long_content = "- 长内容提案：开头看起来完全正常无害。" + "A" * 200 + "\n" + tail_marker
        _make_human_proposal(st, "P-FULL", content=long_content)
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-FULL"))
        r.add("长内容提案预签名成功", rc == 0, "rc={}".format(rc))
        r.add("尾部内容完整可见（无截断）", tail_marker in out, "知情同意覆盖全文")
        r.add("总字符数如实标注", "共 {} 字符".format(len(long_content.strip())) in out, "长度可见")
        r.add("全文逐行前缀输出", "| " + tail_marker in out, "行级展示")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_useonce_enforce():
    """v2.25.16 P1：use-once enforce——同一绑定签名只允许消费一次。

    场景：提案 apply 后重回 gated（模拟 rollback / 状态直改重入，Hermes 审计 P1 场景），
    旧签名再次 apply 必须被拒（此前仅靠提案状态副作用碰巧成立）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    sig_file = tmp / "s.txt"
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        _make_human_proposal(st, "P-USE")
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-USE", out=str(sig_file)))
        r.add("预签名成功", rc == 0, "rc={}".format(rc))
        sig = sig_file.read_text(encoding="utf-8").strip()
    finally:
        restore()
    try:
        rc, out = _run(metacog.cmd_apply, st, SimpleNamespace(id="P-USE", sig=sig,
                                                              human_ok=False, git=False, no_git=True))
        r.add("首次 apply 成功", rc == 0, "rc={}".format(rc))
        # 模拟 rollback / 状态直改使提案重回 gated（审计 P1 攻击场景）
        p = metacog.read_json(st.quarantine / "P-USE.json", {})
        p["status"] = "gated"
        metacog.write_json(st.quarantine / "P-USE.json", p)
        rc, out = _run(metacog.cmd_apply, st, SimpleNamespace(id="P-USE", sig=sig,
                                                              human_ok=False, git=False, no_git=True))
        r.add("同一签名二次 apply 被拒（use-once）", rc == 2 and "已被消费" in out and "use-once" in out, "rc={}".format(rc))
        saved = [q for q in st.proposals() if q["id"] == "P-USE"]
        r.add("提案未被再次应用", bool(saved) and saved[0]["status"] == "gated",
              "status={}".format(saved[0]["status"] if saved else "?"))
        # —— v2.25.17 对抗断言（Hermes v2.25.16 复验 C-1）：篡改消费账本的三条绕过路径均被拒 ——
        def _reset_gated():
            p2 = metacog.read_json(st.quarantine / "P-USE.json", {})
            p2["status"] = "gated"
            metacog.write_json(st.quarantine / "P-USE.json", p2)

        ledger = st.root / "ledger"
        # c1) 删 applies.jsonl 中签名行（claims 不动）→ use-once 仍拦（claims 是权威消费账本）
        apl = ledger / "applies.jsonl"
        kept = [l for l in apl.read_text(encoding="utf-8").splitlines() if sig not in l]
        apl.write_text("".join(l + "\n" for l in kept), encoding="utf-8")
        rc, out = _run(metacog.cmd_apply, st, SimpleNamespace(id="P-USE", sig=sig,
                                                              human_ok=False, git=False, no_git=True))
        # v2.25.21（m-4）：apply 主路径入口接 applies_integrity_ok——账本直写篡改在
        # 完整性硬闸（rc=3）即被拦，早于 use-once 消费检查（行为升级：入口即拒）。
        r.add("删 applies 签名行后二次 apply 仍被拒", rc == 3 and "完整性-硬闸" in out, "rc={}".format(rc))
        # c2) 删 claims 签名行（文件被清空但基线仍在）→ D4 硬闸拒绝（删行绕过收口）
        _reset_gated()
        clm = ledger / "sig-claims.jsonl"
        kept = [l for l in clm.read_text(encoding="utf-8").splitlines() if sig not in l]
        clm.write_text("".join(l + "\n" for l in kept), encoding="utf-8")
        rc, out = _run(metacog.cmd_apply, st, SimpleNamespace(id="P-USE", sig=sig,
                                                              human_ok=False, git=False, no_git=True))
        r.add("清空 claims 后二次 apply 被拒（有基线无账本=fail-closed）", rc == 3 and "完整性-硬闸" in out, "rc={}".format(rc))
        # c3) 删 integrity.json（有账本、无基线）→ fail-closed 拒绝（删基线绕过收口）
        _reset_gated()
        (ledger / "integrity.json").unlink()
        rc, out = _run(metacog.cmd_apply, st, SimpleNamespace(id="P-USE", sig=sig,
                                                              human_ok=False, git=False, no_git=True))
        r.add("删 integrity.json 后二次 apply 被拒（非空无基线=fail-closed）", rc == 2 and "完整性" in out, "rc={}".format(rc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_out_safety():
    """v2.25.16 P2：--out 已存在缺省拒绝覆盖（--force 才覆盖）；写失败 rc=2 且签名仍可复制。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        _make_human_proposal(st, "P-OUT")
        existing = tmp / "s.txt"
        existing.write_text("OLD-CONTENT", encoding="utf-8")
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-OUT", out=str(existing)))
        r.add("--out 已存在缺省拒绝覆盖", rc == 2 and "已存在" in out, "rc={}".format(rc))
        r.add("原文件未被覆盖", existing.read_text(encoding="utf-8") == "OLD-CONTENT", "内容保留")
        rc, out_f = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-OUT", out=str(existing), force=True))
        r.add("--force 显式覆盖成功", rc == 0 and "OLD-CONTENT" not in existing.read_text(encoding="utf-8"),
              "rc={}".format(rc))
        # 从 --force 成功输出提取真实签名（"绑定签名（base64）"行的下一行）
        sig = ""
        _lines = out_f.splitlines()
        for _i, _ln in enumerate(_lines):
            if "绑定签名（base64）" in _ln and _i + 1 < len(_lines):
                sig = _lines[_i + 1].strip()
                break
        # 写失败路径须用「父目录不存在」的路径触发（引擎对已存在目录会精确报 isdir 错）
        bad_out = str(tmp / "no_such_dir" / "s.txt")
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-OUT", out=bad_out))
        r.add("--out 写失败（父目录不存在）rc=2", rc == 2 and "写入失败" in out, "rc={}".format(rc))
        # v2.27.17（nonce 化）：每次 confirm --sign 生成一次性 nonce → 签名串逐次不同，
        # 不能再用「--force 输出的签名 == 失败输出中的签名」断言；改为直接从本次写失败输出
        # 解析签名行（v2:{nonce}:{b64}），验证签名未因写失败而丢失、仍可复制。
        _wf_sig = ""
        _wf_lines = out.splitlines()
        for _i, _ln in enumerate(_wf_lines):
            if "绑定签名（base64" in _ln and _i + 1 < len(_wf_lines):
                _wf_sig = _wf_lines[_i + 1].strip()
                break
        r.add("写失败时签名仍在输出可复制", _wf_sig.startswith("v2:") and len(_wf_sig) > 300,
              "sig前缀={}".format(_wf_sig[:16]))
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-OUT", out=str(tmp)))
        r.add("--out 指向目录精确报错 rc=2", rc == 2 and "指向目录" in out, "rc={}".format(rc))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_informed_consent_normalization():
    """v2.25.16 P2：ANSI/零宽字符可见化；chash 与显示字符数口径统一（不 strip）。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        content = "  良性开头\x1b[2J清屏\u200b隐藏尾部  "
        _make_human_proposal(st, "P-VIS", content=content)
        p = st.find_proposal("P-VIS")
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-VIS"))
        r.add("预签名成功", rc == 0, "rc={}".format(rc))
        r.add("ANSI 转义已可见化（[ESC]）", "[ESC]" in out, "终端渲染不可伪造")
        r.add("零宽字符已可见化（[ZWSP]）", "[ZWSP]" in out, "隐藏内容可见")
        r.add("原始 ESC 不再出现在输出", "\x1b" not in out, "防清屏/变色注入")
        r.add("不可见字符告警输出", "不可见/转义字符" in out, "N 处告警")
        r.add("字符数为未 strip 口径", "共 {} 字符".format(len(content)) in out, "与 chash 口径一致")
        r.add("输出 chash 与签名绑定对象一致", metacog.proposal_content_hash(p) in out, "带外核对可用")
        # —— v2.25.17（M-2 收口，Hermes 复验实测盲区）：BiDi 视觉翻转注入可见化 ——
        bidi = "https://pay.example.com\u202e\u20ac500"
        _make_human_proposal(st, "P-BIDI", content=bidi)
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-BIDI"))
        r.add("BiDi RTL-OVERRIDE 已可见化（[RTL]）", rc == 0 and "[RTL]" in out, "视觉翻转不可伪造")
        r.add("原始 U+202E 不再出现在输出", "\u202e" not in out, "渲染层翻转被消除")
        r.add("BiDi 字符计入不可见告警", "不可见/转义字符" in out, "告警计数覆盖 BiDi")
        # —— v2.25.18（M-2 二次扩面，Hermes 二次复验）：变体选择器范围兜底 ——
        vs = "text\uFE0Fhint"
        _make_human_proposal(st, "P-VS", content=vs)
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-VS"))
        # 只检查提案全文行（引擎自身 UI 文案的 ⚠️ emoji 自带 U+FE0F，不属提案内容，排除在断言外）
        _vs_line = [ln for ln in out.splitlines() if "hint" in ln]
        r.add("变体选择器 U+FE0F 已兜底标注", rc == 0 and _vs_line and
              "[U+FE0F]" in _vs_line[0] and "\uFE0F" not in _vs_line[0], "列举不完备类别有兜底")
        r.add("变体选择器计入不可见告警", "不可见/转义字符" in out, "告警与可见化同口径")
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_t0_over_limit():
    """v2.25.16 P2（接收复核 Confirmed）：episodes 超 512KB 后 t0 不再恒 0（行数口径），签名/验签闭环不复活旧签名。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    sig_file = tmp / "s.txt"
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        # 造 3000 行 episode（约 600KB > read_jsonl 512KB 上限）
        pad = "x" * 180
        with open(st.episodes, "w", encoding="utf-8") as f:
            for i in range(3000):
                f.write(json.dumps({"id": "E-{:04d}".format(i), "task": pad}) + "\n")
        _make_human_proposal(st, "P-T0BIG")
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-T0BIG", out=str(sig_file)))
        r.add("超限账本下预签名成功", rc == 0, "rc={}".format(rc))
        r.add("t0 为真实行数（3000）", "t0=3000" in out, "不再恒 0")
        sig = sig_file.read_text(encoding="utf-8").strip()
    finally:
        restore()
    try:
        rc, out = _run(metacog.cmd_apply, st, SimpleNamespace(id="P-T0BIG", sig=sig,
                                                              human_ok=False, git=False, no_git=True))
        r.add("超限账本下 apply --sig 成功（口径一致）", rc == 0, "rc={}".format(rc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_h2_chain_washout():
    """v2.25.20 H-2（Hermes 三轮实测确认）：删 chain.jsonl 的「改制品→重算基线→verify rc=0 无痕」洗白路径收口。

    verify_integrity 原仅比哈希+基线签名（不查链）；本组断言链校验已补进
    制品/script/manifest/guard 全域 verify 主路径 + applies 域 gate，且 legacy 逃生舱可放行。"""
    r = T()
    st, tmp = _new_store_inited()
    restore = _with_tty_and_passphrase("correct-horse")
    sig_file = tmp / "s.txt"
    try:
        metacog.cmd_confirm(st, _keygen_ns(tmp))
        _make_human_proposal(st, "P-H2")
        rc, out = _run(metacog.cmd_confirm, st, _sign_ns(pid="P-H2", out=str(sig_file)))
        sig = sig_file.read_text(encoding="utf-8").strip()
    finally:
        restore()
    try:
        rc, out = _run(metacog.cmd_apply, st, SimpleNamespace(id="P-H2", sig=sig,
                                                              human_ok=False, git=False, no_git=True))
        r.add("首次 apply 成功（建基线+链）", rc == 0, "rc={}".format(rc))
        rc, out = _run(metacog.cmd_verify, st, SimpleNamespace())
        r.add("正常状态（链在）verify rc=0", rc == 0, "rc={}".format(rc))
        chain = st.root / "ledger" / "integrity-chain" / "chain.jsonl"
        chain.unlink()
        rc, out = _run(metacog.cmd_verify, st, SimpleNamespace())
        r.add("删 chain.jsonl 后 verify rc=1（H-2 洗白路径收口）", rc == 1, "rc={}".format(rc))
        r.add("删链后 applies 域链校验 fail-closed",
              st._integrity_chain_ok(st.APPLIES_INTEGRITY_KEY, "x") is False, "gate 闸同步收口")
        r.add("删链后 record_integrity 双写域（artifact/applies/guard）全部 dirty",
              all(not ok for k, ok, _, _ in st.verify_integrity()
                  if ok is not None and not k.startswith(("script:", "manifest:", "audit:"))),
              "无静默洗白（script:/manifest: 域走 _anchor_sig 防线不入链，豁免合理）")
        _os.environ["METACOG_ALLOW_LEGACY_NO_CHAIN"] = "1"
        try:
            rc, out = _run(metacog.cmd_verify, st, SimpleNamespace())
            r.add("legacy 逃生舱 METACOG_ALLOW_LEGACY_NO_CHAIN=1 放行", rc == 0, "rc={}".format(rc))
            r.add("逃生舱下 _integrity_chain_ok 放行",
                  st._integrity_chain_ok(st.APPLIES_INTEGRITY_KEY, "x") is True, "legacy 兼容口径")
        finally:
            _os.environ.pop("METACOG_ALLOW_LEGACY_NO_CHAIN", None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def main():
    tests = [
        ("A. TTY 强制", test_tty_enforcement),
        ("B. 参数校验", test_arg_validation),
        ("C. 端到端两步工作流", test_sign_end_to_end),
        ("D. t0 漂移 fail-closed", test_sign_t0_drift),
        ("E. 错误口令", test_sign_wrong_passphrase),
        ("F. 全文披露（v2.25.15）", test_sign_full_disclosure),
        ("G1. use-once enforce（v2.25.16）", test_useonce_enforce),
        ("G2. --out 安全（v2.25.16）", test_out_safety),
        ("G3. 知情同意归一化（v2.25.16）", test_informed_consent_normalization),
        ("G4. t0 超限口径（v2.25.16）", test_t0_over_limit),
        ("H. H-2 删链洗白 fail-closed（v2.25.20）", test_h2_chain_washout),
    ]
    all_ok = True
    for title, fn in tests:
        print("\n--- {} ---".format(title))
        r = fn()
        all_ok = all_ok and r.summary()
    print("\n总体: {}".format("ALL PASS" if all_ok else "FAILURES PRESENT"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
