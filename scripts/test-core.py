#!/usr/bin/env python3
# P1-1 修复：必须在任何 import 之前清除 uv 环境变量，防止 SRE module mismatch
# 注意：必须在 import 语句之前，因为 uv 的 PYTHONHOME 会在 import 时生效
import os as _os
_os.environ.pop('PYTHONHOME', None)
_os.environ.pop('PYTHONPATH', None)

# -*- coding: utf-8 -*-
"""
核心流程测试套件（P0-1 补充）
覆盖第三方审计指出"未测试"的两个核心路径：
  - cmd_verdict 双指标棘轮（PROMOTE / REVERT）
  - cmd_apply 高风险/M1 需人类密码学签名（--sig）确认，无签名拒绝

零第三方依赖，import metacog 直接单测。与 test-boundary-cases.py 互补。
"""
import base64
import io
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

# v2.8.2 C-11：全局允许 legacy（无外部锚）回落（部署契约逃生舱），使本套件既有 apply/confirm
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
                                    (" - " + detail) if detail else ""))


def fresh_store():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_core_"))
    st = metacog.Store(tmp / ".metacog")
    st.root.mkdir(parents=True, exist_ok=True)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    metacog.write_json(st.ratchet, metacog.Store.get_ratchet(st))
    return st, tmp


def write_a2(st, entry_id, status, body):
    p = st.artifact_path("A2")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# A2\n\n<!-- entry:{} status:{} since:2026-09-07 src:P-test -->\n{}\n<!-- /entry:{} -->\n".format(
            entry_id, status, body, entry_id),
        encoding="utf-8")


def test_verdict_promote():
    """utility 上升 + violation 下降 → PROMOTE，条目转 active，基线上移"""
    t = T()
    st, tmp = fresh_store()
    try:
        # 基线：utility=0.6, violation=1.0
        for i in range(5):
            metacog.append_jsonl(st.episodes, {"id": f"E{i:03d}", "utility": 0.6, "violations": 1})
        r = st.get_ratchet()
        r["baseline_utility"] = 0.6
        r["baseline_violation_rate"] = 1.0
        st.set_ratchet(r)

        write_a2(st, "R-001", "trial", "- 候选规则")
        p = {"id": "P-promote", "status": "trial", "entry_id": "R-001", "op": "add",
             "artifact": "A2", "trial_from_index": 5}
        metacog.write_json(st.quarantine / "P-promote.json", p)
        st.record_apply("P-promote", 5, "A2", "R-001")   # v2.2.3：受信任锚

        # 试用期窗口：utility 升、violation 降
        for i in range(5, 10):
            metacog.append_jsonl(st.episodes, {"id": f"E{i:03d}", "utility": 0.8, "violations": 0})

        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        metacog.cmd_verdict(st, type("Args", (), {"force": True})())
        sys.stdout = old
        out = buf.getvalue()

        t.add("verdict PROMOTE 输出", "PROMOTE" in out, "out 含 PROMOTE")
        t.add("条目转 active", "status:active" in st.artifact_path("A2").read_text(), "R-001 转 active")
        t.add("基线上移", st.get_ratchet()["baseline_utility"] > 0.6,
              "新基线={:.4f}".format(st.get_ratchet()["baseline_utility"]))
        t.add("提案状态 promoted", st.proposals()[0]["status"] == "promoted", "status=promoted")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_verdict_revert():
    """utility 下降 → REVERT，条目回滚移除"""
    t = T()
    st, tmp = fresh_store()
    try:
        # 基线：utility=0.8, violation=0.0
        for i in range(5):
            metacog.append_jsonl(st.episodes, {"id": f"E{i:03d}", "utility": 0.8, "violations": 0})
        r = st.get_ratchet()
        r["baseline_utility"] = 0.8
        r["baseline_violation_rate"] = 0.0
        st.set_ratchet(r)

        write_a2(st, "R-002", "trial", "- 候选规则")
        p = {"id": "P-revert", "status": "trial", "entry_id": "R-002", "op": "add",
             "artifact": "A2", "trial_from_index": 5}
        metacog.write_json(st.quarantine / "P-revert.json", p)
        st.record_apply("P-revert", 5, "A2", "R-002")   # v2.2.3：受信任锚

        # 试用期窗口：utility 跌、violation 升 → 不达标
        for i in range(5, 10):
            metacog.append_jsonl(st.episodes, {"id": f"E{i:03d}", "utility": 0.5, "violations": 1})

        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        metacog.cmd_verdict(st, type("Args", (), {"force": True})())
        sys.stdout = old
        out = buf.getvalue()

        t.add("verdict REVERT 输出", "REVERT" in out, "out 含 REVERT")
        t.add("条目被回滚移除", "R-002" not in st.artifact_path("A2").read_text(), "R-002 已移除")
        t.add("提案状态 reverted", st.proposals()[0]["status"] == "reverted", "status=reverted")
        t.add("负样本入 archive", len(metacog.read_jsonl(st.archive)) >= 1,
              "archive 记录 {}".format(len(metacog.read_jsonl(st.archive))))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_apply_requires_human_rejected():
    """高风险/M1 提议无 --human-ok → 拒绝应用（状态保持 gated，不写文件）"""
    t = T()
    st, tmp = fresh_store()
    try:
        p = {"id": "P-needhuman", "status": "gated", "requires_human": True,
             "artifact": "A2", "op": "add", "content": "- 高风险规则", "reason": "删除测试",
             "entry_id": None}
        metacog.write_json(st.quarantine / "P-needhuman.json", p)
        before = st.artifact_path("A2").read_text() if st.artifact_path("A2").exists() else ""

        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        metacog.cmd_apply(st, type("Args", (), {"id": None, "human_ok": False, "git": False})())
        sys.stdout = old
        out = buf.getvalue()

        t.add("apply 拒绝无确认（非TTY）", "人类确认闸" in out, "输出提示需 TTY 签名")
        t.add("提案保持 gated", st.proposals()[0]["status"] == "gated", "状态未推进")
        after = st.artifact_path("A2").read_text() if st.artifact_path("A2").exists() else ""
        t.add("未写入制品", before == after, "A2 内容未变")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def test_apply_requires_human_ok():
    """W1（v2.5.7）：带有效「绑定签名」（覆盖 id+chash+t0） → 正常应用（状态转 trial，条目写入）。

    W1 人类闸密码学身份绑定：--human-ok 已废除；测试用 sigcrypto 直接构造
    人类密钥对 + 对「提案 id + 内容哈希 + 试用窗起点 t0=0」签绑定签名
    （等价于人类 TTY `apply` 交互式输入口令签名的落账结果）。"""
    t = T()
    st, tmp = fresh_store()
    try:
        p = {"id": "P-human-ok", "status": "gated", "requires_human": True,
             "artifact": "A2", "op": "add", "content": "- 高风险规则已确认", "reason": "删除测试",
             "entry_id": None, "target": None, "episodes": []}
        metacog.write_json(st.quarantine / "P-human-ok.json", p)
        # 构造人类密钥对并写入 human-guard.json（私钥口令加密落盘）
        pub, priv = sigcrypto.gen_keypair(2048)
        blob = sigcrypto.encrypt_priv(sigcrypto.serialize_priv(priv), "test-pass")
        metacog.write_json(st.human_guard, {
            "pubkey": sigcrypto.serialize_pub(pub),
            "privkey_enc": blob,
            "algo": "rsa-2048-pkcs1v15+aesctr-equiv",
            "created_at": "2026-01-01T00:00:00",
        })
        # 对「提案 id + 内容哈希 + 试用窗起点 t0=0」签绑定签名（apply 时 episode 数为 0）
        chash = metacog.proposal_content_hash(p)
        _t0 = 0
        msg = sigcrypto.approval_message(str(p["id"]), chash, _t0)
        sig = base64.b64encode(sigcrypto.sign(priv, msg)).decode("ascii")

        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        metacog.cmd_apply(st, type("Args", (), {"id": None, "human_ok": False,
                                                "sig": sig, "git": False})())
        sys.stdout = old

        t.add("apply 带有效签名成功", st.proposals()[0]["status"] == "trial", "状态转 trial")
        t.add("条目写入 A2", "高风险规则已确认" in st.artifact_path("A2").read_text(), "内容已落盘")
        # W1 受信任锚内嵌人类签名（关闭 7.1 直写伪造）
        applied_rec = st.latest_apply_record("P-human-ok")
        t.add("受信任锚含人类签名", bool(applied_rec and applied_rec.get("human_sig")), "anchor sig")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return t


def main():
    print("=" * 60)
    print("核心流程测试套件 (P0-1: verdict + apply)")
    print("=" * 60 + "\n")
    groups = [test_verdict_promote(), test_verdict_revert(),
              test_apply_requires_human_rejected(), test_apply_requires_human_ok()]
    passed = sum(g.passed for g in groups)
    failed = sum(g.failed for g in groups)
    total = passed + failed
    print("\n" + "=" * 60)
    print("测试结果: {}/{} PASS".format(passed, total))
    print("=" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
