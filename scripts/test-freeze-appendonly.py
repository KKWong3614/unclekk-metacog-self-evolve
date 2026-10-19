#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.12.0（H-A 收口 + Hermes r8 P1 加固）回归测试：冻结清单 append-only + HMAC 链 + 树外锚点。

验证 Hermes r7 H-A 的收口，以及 Hermes r8 P1 加固：
  - 正常冻结 + 校验通过；
  - 改冻结文件 → FROZEN-MODIFIED 检出；
  - 篡改 ledger 条目 → 树外锚点不匹配 FROZEN-ANCHOR fail-closed（r8 P1-②）；
  - 账本缺失 → FROZEN-LEDGER: 账本缺失 fail-closed（r8 P1-①，原误判为「无约束」）；
  - 整体替换 ledger（锚未动）→ FROZEN-ANCHOR 不匹配 fail-closed（r8 P1-②）；
  - HMAC 链断裂（锚同步后）→ FROZEN-LEDGER 链断裂 fail-closed；
  - 重冻结（append 新条目）→ RE-FROZEN 纪律告警，且仍以首次冻结哈希为权威；
  - append-only：旧条目永不被覆写。
"""
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# 重定向 SKILL_ROOT 到临时目录以隔离测试（不污染真实冻结清单）
_TMP = Path(tempfile.mkdtemp(prefix="metacog_freeze_"))
sys.path.insert(0, str(Path(__file__).parent))
import freeze as freeze_mod
freeze_mod.SKILL_ROOT = _TMP
freeze_mod.FREEZE_FILE = _TMP / "frozen-hashes.jsonl"


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
        print("v2.11.0 冻结清单测试: {}/{} PASS".format(self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _write(p: Path, text: str):
    p.write_text(text, encoding="utf-8")


def _clean():
    """清理账本 + 树外锚 + 安装标记残留，保证用例隔离。
    v2.14.0：record 在「账本缺失但锚残留」或「账本+锚缺失但安装标记仍在」时拒绝重置；
    锚点写后落只读属性，故需先 _remove_anchor() 解除只读再删除。"""
    freeze_mod.FREEZE_FILE.unlink(missing_ok=True)
    try:
        freeze_mod._remove_anchor()
    except Exception:
        pass
    try:
        freeze_mod._remove_marker()
    except Exception:
        pass


def test_freeze_basic():
    r = T()
    _clean()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    freeze_mod.record(["frozen_sample.py"])
    ok, viol = freeze_mod.verify()
    r.add("冻结后校验通过", ok and not viol, "viol={}".format(viol))
    r.add("冻结文件存在且 1 条记录", freeze_mod.FREEZE_FILE.exists()
          and len([l for l in freeze_mod.FREEZE_FILE.read_text().splitlines() if l.strip()]) == 1)
    return r


def test_modified_file_detected():
    r = T()
    _clean()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    freeze_mod.record(["frozen_sample.py"])
    # 攻击者/疏忽：改文件但未重新冻结
    _write(f, "TAMPERED content\n")
    ok, viol = freeze_mod.verify()
    r.add("改冻结文件 → 校验失败", ok is False)
    r.add("检出 FROZEN-MODIFIED", any("FROZEN-MODIFIED" in v for v in viol), "viol={}".format(viol))
    return r


def test_ledger_tamper_detected():
    r = T()
    _clean()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    freeze_mod.record(["frozen_sample.py"])
    # 攻击者：直接改 ledger 里的 sha256（模拟「重记冻结哈希」绕过）
    lines = freeze_mod.FREEZE_FILE.read_text().splitlines()
    e = json.loads(lines[0])
    e["sha256"] = hashlib.sha256(b"forged").hexdigest()
    payload = json.dumps({k: v for k, v in e.items() if k != "hmac"},
                         separators=(",", ":"), sort_keys=True)
    e["hmac"] = "0" * 64  # 不重算 HMAC → 链断裂
    lines[0] = json.dumps(e, separators=(",", ":"), sort_keys=True)
    freeze_mod.FREEZE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, viol = freeze_mod.verify()
    r.add("篡改 ledger 条目 → 校验失败", ok is False)
    r.add("检出 FROZEN-ANCHOR 锚点不匹配（整体替换被树外锚捕获）", any("FROZEN-ANCHOR" in v for v in viol),
          "viol={}".format(viol))
    return r


def test_refreeze_appendonly():
    r = T()
    _clean()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    freeze_mod.record(["frozen_sample.py"])
    first_lines = [l for l in freeze_mod.FREEZE_FILE.read_text().splitlines() if l.strip()]
    first_sha = json.loads(first_lines[0])["sha256"]
    # 改文件后「重新冻结」（append 新条目，不覆写旧条目）
    _write(f, "second version\n")
    freeze_mod.record(["frozen_sample.py"])
    new_lines = [l for l in freeze_mod.FREEZE_FILE.read_text().splitlines() if l.strip()]
    r.add("重冻结为 append（记录数 1→2，旧条目保留）",
          len(new_lines) == 2 and json.loads(new_lines[0])["sha256"] == first_sha)
    ok, viol = freeze_mod.verify()
    # 当前文件 != 首次冻结哈希 → 仍 FROZEN-MODIFIED；且 RE-FROZEN 告警
    r.add("重冻结后仍以首次哈希为权威 → FROZEN-MODIFIED 检出", any("FROZEN-MODIFIED" in v for v in viol),
          "viol={}".format(viol))
    r.add("重冻结触发 RE-FROZEN 纪律告警", any("RE-FROZEN" in v for v in viol), "viol={}".format(viol))
    r.add("重冻结未静默通过校验", ok is False)
    return r


def test_missing_ledger_failclosed():
    r = T()
    _clean()
    ok, viol = freeze_mod.verify()
    r.add("账本缺失 → verify fail-closed（r8 P1-①）", ok is False)
    r.add("检出 FROZEN-LEDGER: 账本缺失", any("FROZEN-LEDGER" in v for v in viol), "viol={}".format(viol))
    return r


def test_anchor_mismatch_detected():
    r = T()
    _clean()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    freeze_mod.record(["frozen_sample.py"])
    # 攻击者整体替换 ledger（不同内容），但不触碰树外锚 → 锚不匹配
    freeze_mod.FREEZE_FILE.write_text(
        json.dumps({"path": "frozen_sample.py", "sha256": "0" * 64, "at": "t",
                    "prev_hmac": "", "hmac": "0" * 64}) + "\n", encoding="utf-8")
    ok, viol = freeze_mod.verify()
    r.add("整体替换 ledger（锚未动）→ verify fail-closed", ok is False)
    r.add("检出 FROZEN-ANCHOR 锚点不匹配（r8 P1-②）", any("FROZEN-ANCHOR" in v for v in viol),
          "viol={}".format(viol))
    return r


def test_ledger_chain_break():
    r = T()
    _clean()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    freeze_mod.record(["frozen_sample.py"])
    # 篡改 ledger 内 sha256 并伪造 hmac，再同步锚点 → 应触发 FROZEN-LEDGER 链断裂
    lines = freeze_mod.FREEZE_FILE.read_text().splitlines()
    e = json.loads(lines[0])
    e["sha256"] = hashlib.sha256(b"forged").hexdigest()
    e["hmac"] = "0" * 64
    lines[0] = json.dumps(e, separators=(",", ":"), sort_keys=True)
    freeze_mod.FREEZE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    freeze_mod._write_anchor()  # 同步锚点，使锚不触发，专门验证链断裂检测
    ok, viol = freeze_mod.verify()
    r.add("篡改 ledger 链（锚同步）→ 校验失败", ok is False)
    r.add("检出 FROZEN-LEDGER 链断裂", any("FROZEN-LEDGER" in v for v in viol), "viol={}".format(viol))
    return r


def _cleanup_anchor():
    """v2.18.0（Hermes r14 F-8 收口）：本套件把 SKILL_ROOT 重定向到临时目录，锚点因此落在
    `~/.metacog_freeze_anchors/<tmpname>.*`——即**生产信任根目录内**。用例结束（含异常/中断）
    必须无条件清理，否则历轮测试会在真实信任根目录里堆积孤儿锚 + marker + 审计日志，
    污染本机制所要守护的对象。try/finally 保证中断路径也执行。"""
    for suffix in (".anchor", ".installed", ".audit.log"):
        try:
            (_anchor_dir() / (freeze_mod.SKILL_ROOT.name + suffix)).unlink(missing_ok=True)
        except Exception:
            pass
    for fn in (freeze_mod._remove_anchor, freeze_mod._remove_marker):
        try:
            fn()
        except Exception:
            pass


def _anchor_dir():
    return freeze_mod._anchor_path().parent


def main():
    try:
        results = []
        results.append(test_freeze_basic())
        results.append(test_modified_file_detected())
        results.append(test_ledger_tamper_detected())
        results.append(test_refreeze_appendonly())
        results.append(test_missing_ledger_failclosed())
        results.append(test_anchor_mismatch_detected())
        results.append(test_ledger_chain_break())
        all_ok = all(t.summary() for t in results)
        print("\n########## 冻结清单套件汇总 ##########")
        print("SUITE: {}".format("ALL PASS" if all_ok else "HAS FAILURE"))
        return 0 if all_ok else 1
    finally:
        # 清理临时目录 + 生产信任根目录内的孤儿锚/marker/审计日志（v2.18.0 F-8 收口）
        shutil.rmtree(_TMP, ignore_errors=True)
        _cleanup_anchor()


if __name__ == "__main__":
    sys.exit(main())
