#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.26.0（Hermes 四轮复验 H-2a/H-2b 收口）方案 A+B 对抗回归测试套件（独立验证，非自验自收）

方案A（链条目 HMAC，_CHAIN_HMAC_LABEL 独立派生）：
  - record_integrity 追加的链条目必带 mac；校验侧（_chain_entries_verified）强制验签。
  - 篡改条目任一字段 → HMAC 不符 → fail-closed（env 不放行）。
  - mac 纪元后出现无 mac 条目（手写伪造冒充 legacy）→ fail-closed（METACOG_ALLOW_LEGACY_NO_CHAIN=1 放行）。
  - 纯 legacy 链（v2.26.0 前安装）→ 放行 + warn。

方案B（链首指纹人类锚钉固，CONTRACT.md chain-identity-root）：
  - keygen（人类 TTY 在场）钉固链首条目 hash（append-only 头部）。
  - 删链 → 链首指纹取 None → 与钉固不符 → fail-closed（H-2b 删链检出）。
  - 删链+引擎 API 重建 → 新链首条目 hash 因时间戳不可复现 → 与钉固不符 → fail-closed（U4 收口）。
  - 未钉固（legacy/未 keygen）→ 放行 + warn；empty 哨兵（keygen 时链空）→ 建链后放行 + warn。

诚实边界（H-2a 全引擎 API 变体为自举残余）：改制品 + record_integrity 重算基线 + 引擎追加合法 mac
条目（链头不动）→ A/B 均不可进程内检出——与 C-1 自举信任根同类，须系统级部署契约兜底，
SKILL.md「诚实天花板」已如实登记。本套件断言的是「非全引擎 API」变体的收口。

零第三方依赖。锚点定向临时文件，不污染真实树外锚。
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ["METACOG_FREEZE_ANCHOR"] = str(Path(tempfile.gettempdir()) / "metacog_v2260_test_anchor.anchor")
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

    def summary(self, title):
        total = self.passed + self.failed
        print("\n{}".format("=" * 60))
        print("{}: {}/{} PASS".format(title, self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _new_store_inited():
    tmp = Path(tempfile.mkdtemp(prefix="metacog_v2260_"))
    st = metacog.Store(tmp / ".metacog")
    metacog.cmd_init(st, SimpleNamespace())
    return st, tmp


def _seed_chain(st):
    """落两个 ledger 域文件并 record → 建 2 条目链（全带 mac）。返回链行列表。"""
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    (st.root / "ledger/applies.jsonl").write_text("{}\n", encoding="utf-8")
    (st.root / "ledger/sig-claims.jsonl").write_text("", encoding="utf-8")
    st.record_integrity(metacog.Store.APPLIES_INTEGRITY_KEY)
    st.record_integrity(metacog.Store.SIG_CLAIMS_INTEGRITY_KEY)
    chain = st.root / "ledger/integrity-chain/chain.jsonl"
    return [l for l in chain.read_text(encoding="utf-8").splitlines() if l.strip()]


class _Env:
    """临时设置/恢复环境变量的上下文管理器。"""
    def __init__(self, **kw):
        self.kw = kw
        self._saved = {}

    def __enter__(self):
        for k, v in self.kw.items():
            self._saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k in self.kw:
            if self._saved.get(k) is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = self._saved[k]


def test_a_chain_hmac():
    """方案A：链条目 HMAC——写入必带 mac、篡改/手写/冒充 legacy 全 fail-closed。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        lines = _seed_chain(st)
        e1 = json.loads(lines[0])
        tail = json.loads(lines[-1])
        r.add("A1 record 后链条目含 mac", "mac" in e1 and "mac" in tail)
        ents, ok = st._chain_entries_verified(lines)
        r.add("A2 全链 HMAC 校验通过（init 可能已建链，条目数>=2）", ok and len(ents) >= 2,
              "ok={} n={}".format(ok, len(ents) if ents else 0))
        # 篡改条目字段（hash）→ mac 不符 → False
        e1b = dict(e1)
        e1b["hash"] = "d" * 64
        _, ok2 = st._chain_entries_verified([json.dumps(e1b, separators=(",", ":"))] + lines[1:])
        r.add("A3 篡改条目字段 → HMAC 不符 → False", ok2 is False)
        # 手写伪造条目（合法 prev、无 mac，mac 纪元后）→ False
        forge = {"prev": tail["hash"], "hash": "f" * 64, "key": "ledger/evil",
                 "size": 1, "at": "2026-10-20T00:00:00"}
        _, ok3 = st._chain_entries_verified(lines + [json.dumps(forge, separators=(",", ":"))])
        r.add("A4 mac 纪元后手写无 mac 条目 → False", ok3 is False)
        # 手写伪造条目带错 mac → False
        forge2 = dict(forge)
        forge2["mac"] = "0" * 64
        _, ok4 = st._chain_entries_verified(lines + [json.dumps(forge2, separators=(",", ":"))])
        r.add("A5 手写条目带伪造 mac → False", ok4 is False)
        # env 逃生舱放行（与链缺失同一口径）
        with _Env(METACOG_ALLOW_LEGACY_NO_CHAIN="1"):
            _, ok5 = st._chain_entries_verified(lines + [json.dumps(forge, separators=(",", ":"))])
        r.add("A6 env 逃生舱放行 mac 纪元后 legacy 条目", ok5 is True)
        # 纯 legacy 链（v2.26.0 前安装）→ 放行
        legacy_lines = [
            json.dumps({"prev": "", "hash": "a" * 64, "key": "k1", "size": 1, "at": "t"}, separators=(",", ":")),
            json.dumps({"prev": "a" * 64, "hash": "b" * 64, "key": "k2", "size": 2, "at": "t"}, separators=(",", ":")),
        ]
        ents6, ok6 = st._chain_entries_verified(legacy_lines)
        r.add("A7 纯 legacy 链（全无 mac）放行", ok6 and len(ents6) == 2)
        # verify 集成：删链 → verify dirty（rc 语义：dirty>0）
        (st.root / "ledger/integrity-chain/chain.jsonl").unlink()
        rows = st.verify_integrity()
        dirty = [row for row in rows if not row[1]]
        r.add("A8 删链后 verify 检出 dirty（fail-closed）", len(dirty) > 0,
              "dirty={}".format(len(dirty)))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_b_chain_fingerprint():
    """方案B：链首指纹人类锚钉固——未钉固放行、钉固后删链/重建链检出。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        # 未钉固（无 CONTRACT.md 钉固节）→ legacy 放行 + warn
        ok0 = st.chain_fingerprint_ok()
        r.add("B1 未钉固（legacy）放行", ok0 is True)
        cpath = st.root / "CONTRACT.md"
        r.add("B2 CONTRACT.md 尚无 chain_head_fingerprint", st.CHAIN_FP_KEY not in cpath.read_text(encoding="utf-8"))
        lines = _seed_chain(st)
        head = json.loads(lines[0])["hash"]
        # 钉固（keygen 同路径）
        st.write_chain_fingerprint()
        r.add("B3 write_chain_fingerprint 钉入 CONTRACT.md",
              st.CHAIN_FP_KEY in cpath.read_text(encoding="utf-8"))
        r.add("B4 钉固后校验通过", st.chain_fingerprint_ok() is True)
        # 正常追加（record）不动链头 → 仍通过
        (st.root / "ledger/sig-claims.jsonl").write_text("x\n", encoding="utf-8")
        st.record_integrity(metacog.Store.SIG_CLAIMS_INTEGRITY_KEY)
        r.add("B5 record 追加（头部不变）仍通过", st.chain_fingerprint_ok() is True)
        # H-2b/U4 场景：删链 + 引擎 API 重建 → 新链首条 hash 与钉固不符 → False
        chain_path = st.root / "ledger/integrity-chain/chain.jsonl"
        chain_path.unlink()
        r.add("B6 删链 → 链首指纹校验 False（H-2b 检出）", st.chain_fingerprint_ok() is False)
        st.record_integrity(metacog.Store.APPLIES_INTEGRITY_KEY)  # 引擎重建链（首条 hash 因时间戳不同）
        r.add("B7 删链+引擎重建 → 仍 False（重建链首 hash 不可复现）", st.chain_fingerprint_ok() is False)
        # env 逃生舱放行
        with _Env(METACOG_ALLOW_LEGACY_NO_CHAIN="1"):
            ok8 = st.chain_fingerprint_ok()
        r.add("B8 env 逃生舱放行（重基线场景）", ok8 is True)
        # 重新 keygen 钉固（模拟重基线后）→ 覆盖为新指纹 → 通过
        st.write_chain_fingerprint()
        r.add("B9 重新钉固后通过", st.chain_fingerprint_ok() is True)
        # empty 哨兵场景：清空链 → 手动钉固 empty 哨兵 → 建链后放行 + warn
        chain_path.write_text("", encoding="utf-8")
        cpath.write_text(cpath.read_text(encoding="utf-8").replace(head, st.CHAIN_FP_EMPTY), encoding="utf-8")
        st.record_integrity(metacog.Store.APPLIES_INTEGRITY_KEY)
        r.add("B10 empty 哨兵（keygen 时链空）建链后放行", st.chain_fingerprint_ok() is True)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_b2_verify_and_pinning_escape():
    """v2.26.1（Hermes 五轮 B5/B6 实测收口）：verify 接线无条件化 + H-2c 删钉固行逃逸收口。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        _seed_chain(st)
        st.write_chain_fingerprint()
        # H-2b'（五轮 B5）：删 GUARD 基线（integrity.json guard 记录）→ verify 链指纹校验仍可达
        chain_path = st.root / "ledger/integrity-chain/chain.jsonl"
        chain_path.unlink()
        st.record_integrity(metacog.Store.APPLIES_INTEGRITY_KEY)  # 引擎重建链（首 hash 变）
        data = metacog.read_json(st.integrity, {})
        data.pop(metacog.Store.GUARD_INTEGRITY_KEY, None)
        metacog.write_json(st.integrity, data)  # 模拟删 GUARD 基线
        # 断言：chain_fingerprint_ok 本身 False（不依赖 guard 基线）
        r.add("B11 删 GUARD 基线后链指纹校验仍为 False（接线不依赖 guard 域）",
              st.chain_fingerprint_ok() is False)
        # verify 集成：用 SimpleNamespace 走 cmd_verify（dirty>0 → rc=1）
        st2 = st  # 同一 store；cmd_verify 输出 dirty
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = metacog.cmd_verify(st2, SimpleNamespace())
        r.add("B12 verify 删 GUARD 基线 + 重建链 → rc=1（链指纹校验无条件可达）", rc == 1, "rc={}".format(rc))
        # H-2c（五轮 B6）：keygen 已跑（guard 存在）但 CONTRACT.md 钉固行被删 → fail-closed
        st.write_chain_fingerprint()
        cpath = st.root / "CONTRACT.md"
        kept = [l for l in cpath.read_text(encoding="utf-8").splitlines()
                if st.CHAIN_FP_KEY not in l]
        cpath.write_text("\n".join(kept) + "\n", encoding="utf-8")
        r.add("B13 删 CONTRACT.md 钉固行（guard 存在）→ False（H-2c 收口）",
              st.chain_fingerprint_ok() is False)
        with _Env(METACOG_ALLOW_LEGACY_NO_CHAIN="1"):
            ok14 = st.chain_fingerprint_ok()
        r.add("B14 env 逃生舱放行（钉固行被删过渡场景）", ok14 is True)
        # 未 keygen 老安装（guard 不存在且钉固节被整节删除）→ legacy 放行
        gp = st.root / "ledger/human-guard.json"
        if gp.exists():
            gp.unlink()
        kept2 = [l for l in cpath.read_text(encoding="utf-8").splitlines()
                 if "chain-identity-root" not in l and st.CHAIN_FP_KEY not in l]
        cpath.write_text("\n".join(kept2) + "\n", encoding="utf-8")
        r.add("B15 未 keygen（guard 不存在且钉固痕迹全无）legacy 放行", st.chain_fingerprint_ok() is True)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def test_c_apply_entry_gate():
    """方案A+B 集成：apply 入口硬闸（applies D4 + 链首指纹）在删链/重建场景拒绝。"""
    r = T()
    st, tmp = _new_store_inited()
    try:
        lines = _seed_chain(st)
        st.write_chain_fingerprint()
        # H-2b U4 场景完整重放：删链 + 删 applies 基线 + 引擎重建 → apply 入口 apply 硬闸须拒
        # （构造：直接调 chain_fingerprint_ok 模拟 apply 入口判定——不跑完整 apply（需提案/签名），
        #   硬闸由 cmd_apply L2797 区域两道 if not ok: return 3 组成，判定函数即本两法。）
        (st.root / "ledger/integrity-chain/chain.jsonl").unlink()
        st.record_integrity(metacog.Store.APPLIES_INTEGRITY_KEY)  # 引擎重建链
        gate = (not st.applies_integrity_ok()) or (not st.chain_fingerprint_ok())
        r.add("C1 删链+重建后 apply 入口两道闸任一拒绝（H-2b U4 收口）", gate is True,
              "applies_ok={} fp_ok={}".format(st.applies_integrity_ok(), st.chain_fingerprint_ok()))
        # 重新钉固 → 两道闸均过（合法重基线恢复路径）
        st.write_chain_fingerprint()
        gate2 = (st.applies_integrity_ok() is True) and (st.chain_fingerprint_ok() is True)
        r.add("C2 重新钉固后入口恢复放行", gate2 is True)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def main():
    all_ok = True
    for fn, title in [(test_a_chain_hmac, "方案A 链条目 HMAC 测试"),
                      (test_b_chain_fingerprint, "方案B 链首指纹钉固测试"),
                      (test_b2_verify_and_pinning_escape, "v2.26.1 verify 接线+H-2c 收口测试"),
                      (test_c_apply_entry_gate, "A+B 集成 apply 入口硬闸测试")]:
        r = fn()
        if not r.summary(title):
            all_ok = False
    print("\n总体: {}".format("ALL PASS" if all_ok else "FAILURES PRESENT"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
