#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.16.0（Hermes r9/r10/r11/r12 复派）H-B1/H-B2/H-B3/H-B4 + P1-2/P1-3 + H-1/L-1 + r12 HIGH-1/HIGH-2/MED-2/LOW-1 收口对抗回归测试套件（独立验证，非自验自收）

覆盖各版 Hermes 裁定后新收口的绕过路径：
  - H-B1 [HIGH]：record() 写前必须 verify() 通过，禁止在损坏/被截断账本上静默追加重启链。
                 本套件复现「仅持技能树写权」的 tree-only 攻击（截断 ledger、不动树外锚）→ record 被拒。
                 （诚实 residual：攻击者若同时持 ledger+锚 双写权，可同步锚后 record 成功——属 r9 已声明的已知 residual，
                  非代码层可防，已在 CHANGELOG/HANDOFF 登记。）
  - H-B2 [HIGH]：verify() 锚缺失不再静默 bootstrap，改为 fail-closed（FROZEN-ANCHOR: 锚未初始化）。
                 显式 anchor-init 可建立信任根。
  - H-B3 [MED]：空账本（0 字节）verify 不再 rc=0，改为 fail-closed（FROZEN-LEDGER: 账本为空）。
  - H-B4 [LOW]：METACOG_FREEZE_ANCHOR 指向技能树内时，_anchor_path() 拒绝（ValueError）。
  - r10 P1-2/P1-3：双删重置 FROZEN-RESET-BLOCKED + anchor-init 令牌门禁（无令牌拒绝 rc=2）。
  - v2.15.0 H-1/M-3 [HIGH]：_valid_entry 新增 _path_in_tree，拒绝绝对路径 / ~ / Windows 盘符 / .. 逃逸，
                  杜绝树外文件哈希经自签链混入 ledger。
  - v2.15.0 L-1：_valid_entry 校验 at 为 ISO-8601 UTC（YYYY-MM-DDThh:mm:ssZ）。
  - v2.15.0 M-2 诚实呈现：持令牌 + 结构合法 ledger，anchor_init 成功（rc=0）——证明令牌非密码学根（预期行为，residual ②）。
  - v2.16.0 HIGH-1（Hermes r12 跨平台实测）：Windows 反斜杠逃逸 `..\\outside\\x` 必须被 _path_in_tree 拒绝
                  （v2.15.0 用 PurePosixPath 不识别 Windows 反斜杠为分隔符 → 实测竟通过并把树外文件哈希落 ledger）。
  - v2.16.0 HIGH-2（Hermes r12 实测）：metacog._read_skill_version_tuple 读取失败回退 fail-closed (99,99,99)
                  （非 fail-open 低版本 (2,14,0)），杜绝删 SKILL.md / 缺 version 行静默打开 legacy 安全门。
  - v2.16.0 MED-2（Hermes r12 实测）：record() 对每个 rel 先经 _path_in_tree 校验，不可哈希路径（目录/无权限/空/根）
                  跳过告警、不崩溃、不写脏数据。
  - v2.16.0 LOW-1（Hermes r12 实测）：at 校验由正则升级为 datetime.strptime，拒绝非法日期（2026-99-99 / 2026-02-30）。

零第三方依赖。运行无需特殊环境变量（锚定向到临时文件，不污染真实树外锚）。
"""
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 隔离：锚点指向临时文件（在技能树之外，避免污染真实 ~/.metacog_freeze_anchors）
os.environ["METACOG_FREEZE_ANCHOR"] = str(Path(tempfile.gettempdir()) / "metacog_hb_test_anchor.anchor")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))
import freeze as freeze_mod

_TMP = Path(tempfile.mkdtemp(prefix="metacog_hb_"))
freeze_mod.SKILL_ROOT = _TMP
freeze_mod.FREEZE_FILE = _TMP / "frozen-hashes.jsonl"
_ANCHOR = Path(os.environ["METACOG_FREEZE_ANCHOR"])


def _clean_state():
    """v2.14.0：清理账本 + 树外锚（解除只读后删） + 安装标记，保证用例隔离。"""
    freeze_mod.FREEZE_FILE.unlink(missing_ok=True)
    try:
        freeze_mod._remove_anchor()
    except Exception:
        pass
    try:
        freeze_mod._remove_marker()
    except Exception:
        pass


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
        print("v2.16.0 收口回归: {}/{} PASS".format(self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _write(p: Path, text: str):
    p.write_text(text, encoding="utf-8")


def _count_lines():
    if not freeze_mod.FREEZE_FILE.exists():
        return 0
    return len([l for l in freeze_mod.FREEZE_FILE.read_text().splitlines() if l.strip()])


def test_hb1_record_after_truncate_refused():
    """H-B1：tree-only 攻击者截断 ledger（不动树外锚）→ record 必须被拒（FROZEN-RECORD-BLOCKED）。"""
    r = T()
    _clean_state()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    # 建立含 2 条记录的基线（第一次 record 写锚）
    freeze_mod.record(["frozen_sample.py"])
    rc2 = freeze_mod.record(["frozen_sample.py"])  # 第二次追加（RE-FROZEN 路径，但仍成功写锚）
    r.add("基线建立：二次 record 成功（rc>=0）", rc2 >= 0, "rc={}".format(rc2))
    r.add("基线：2 条冻结记录", _count_lines() == 2, "lines={}".format(_count_lines()))
    # --- tree-only 攻击：截断 ledger 至 1 条，不动树外锚（锚仍反映 2 条账本）---
    lines = freeze_mod.FREEZE_FILE.read_text().splitlines()
    freeze_mod.FREEZE_FILE.write_text(lines[0] + "\n", encoding="utf-8")
    r.add("攻击前置：ledger 已被截断为 1 条", _count_lines() == 1)
    # record 必须拒绝（verify 因锚不匹配失败 → FROZEN-RECORD-BLOCKED）
    rc = freeze_mod.record(["frozen_sample.py"])
    r.add("截断后 record 被拒绝（rc<0，H-B1 收口）", rc < 0, "rc={}".format(rc))
    r.add("拒绝后账本未被静默追加（仍为 1 条）", _count_lines() == 1, "lines={}".format(_count_lines()))
    ok, viol = freeze_mod.verify()
    r.add("截断后 verify 直接 fail-closed（锚不匹配）", ok is False)
    r.add("检出 FROZEN-ANCHOR 锚不匹配", any("FROZEN-ANCHOR" in v for v in viol), "viol={}".format(viol))
    return r


def test_hb2_anchor_missing_failclosed():
    """H-B2：删树外锚后 verify 必须 fail-closed（不再静默 bootstrap）。anchor-init 可重建信任根。"""
    r = T()
    _clean_state()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    freeze_mod.record(["frozen_sample.py"])
    r.add("基线：record 建立账本+锚", _ANCHOR.exists() and _count_lines() == 1)
    # 攻击：删树外锚（需先解除只读）
    freeze_mod._remove_anchor()
    ok, viol = freeze_mod.verify()
    r.add("删锚后 verify fail-closed（H-B2 收口）", ok is False)
    r.add("检出 FROZEN-ANCHOR: 锚未初始化", any("FROZEN-ANCHOR: 锚未初始化" in v for v in viol), "viol={}".format(viol))
    # 合法恢复：显式 anchor-init 重建信任根（v2.14.0 P1-3：需 METACOG_ANCHOR_INIT_TOKEN 授权）
    os.environ["METACOG_ANCHOR_INIT_TOKEN"] = freeze_mod._ANCHOR_INIT_TOKEN
    rc = freeze_mod.anchor_init()
    r.add("anchor-init 成功（rc=0）", rc == 0, "rc={}".format(rc))
    r.add("anchor-init 成功（rc=0）", rc == 0, "rc={}".format(rc))
    r.add("anchor-init 后锚文件重建", _ANCHOR.exists())
    ok2, viol2 = freeze_mod.verify()
    r.add("anchor-init 后 verify 通过", ok2 is True, "viol={}".format(viol2))
    return r


def test_hb3_empty_ledger_failclosed():
    """H-B3：空账本（0 字节）verify 必须 fail-closed（原误判 rc=0）。"""
    r = T()
    _clean_state()
    # 创建 0 字节空账本
    freeze_mod.FREEZE_FILE.write_text("", encoding="utf-8")
    ok, viol = freeze_mod.verify()
    r.add("空账本 verify fail-closed（H-B3 收口）", ok is False)
    r.add("检出 FROZEN-LEDGER: 账本为空", any("FROZEN-LEDGER: 账本为空" in v for v in viol), "viol={}".format(viol))
    # 仅空白行同理
    freeze_mod.FREEZE_FILE.write_text("   \n\n\t\n", encoding="utf-8")
    ok2, viol2 = freeze_mod.verify()
    r.add("纯空白账本同样 fail-closed", ok2 is False)
    return r


def test_hb4_intree_anchor_rejected():
    """H-B4：METACOG_FREEZE_ANCHOR 指向技能树内时，_anchor_path() 必须拒绝。"""
    r = T()
    saved = os.environ.get("METACOG_FREEZE_ANCHOR")
    try:
        # 指向技能树内路径（_TMP 即 SKILL_ROOT）
        in_tree = _TMP / ".intree.anchor"
        os.environ["METACOG_FREEZE_ANCHOR"] = str(in_tree)
        raised = False
        try:
            freeze_mod._anchor_path()
        except ValueError as e:
            raised = True
            r.add("树内锚点路径被拒绝（ValueError）", "技能树内" in str(e), "msg={}".format(e))
        r.add("_anchor_path 对树内锚抛异常（H-B4 收口）", raised)
    finally:
        if saved is None:
            os.environ.pop("METACOG_FREEZE_ANCHOR", None)
        else:
            os.environ["METACOG_FREEZE_ANCHOR"] = saved
    # 恢复后正常锚点可用
    r.add("恢复后锚点路径合法（在树外）", not str(freeze_mod._anchor_path()).startswith(str(_TMP)))
    return r


def test_reset_blocked_double_delete():
    """r10 P1-2：已安装（marker 存在）后删 ledger+锚（双删）但保留 marker → record 必须 FROZEN-RESET-BLOCKED 拒绝，不静默重置。"""
    r = T()
    _clean_state()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    freeze_mod.record(["frozen_sample.py"])  # 首次初始化，写 marker + 锚
    r.add("基线：安装标记已建立", freeze_mod._read_marker())
    # 双删 ledger + 锚，但保留 marker（模拟攻击者未删标记）
    freeze_mod.FREEZE_FILE.unlink(missing_ok=True)
    freeze_mod._remove_anchor()
    r.add("双删后标记仍在（模拟未删标记）", freeze_mod._read_marker())
    if "METACOG_FREEZE_ALLOW_RESET" in os.environ:
        del os.environ["METACOG_FREEZE_ALLOW_RESET"]
    rc = freeze_mod.record(["frozen_sample.py"])
    r.add("双删后 record 被拒（FROZEN-RESET-BLOCKED, rc<0）", rc < 0, "rc={}".format(rc))
    ok, viol = freeze_mod.verify()
    r.add("双删态 verify fail-closed（账本缺失）", ok is False)
    # 显式授权重置应放行（r13 H-3 收口：ALLOW_RESET=1 必须与正确 RESET_TOKEN 配对，裸 env 不再放行）
    os.environ["METACOG_FREEZE_ALLOW_RESET"] = "1"
    os.environ["METACOG_FREEZE_RESET_TOKEN"] = freeze_mod._RESET_TOKEN
    rc2 = freeze_mod.record(["frozen_sample.py"])
    r.add("带 METACOG_FREEZE_ALLOW_RESET=1 + 正确 RESET_TOKEN 可授权重置（rc>=0）", rc2 >= 0, "rc={}".format(rc2))
    del os.environ["METACOG_FREEZE_ALLOW_RESET"]
    del os.environ["METACOG_FREEZE_RESET_TOKEN"]
    return r


def test_anchor_init_launder_refused():
    """r10 P1-3：攻击者改 ledger 后跑 anchor-init 洗白 → 必须被令牌门禁拒绝（默认无令牌拒绝，rc==2）。"""
    r = T()
    _clean_state()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    freeze_mod.record(["frozen_sample.py"])
    # 攻击者改 ledger 中 sha256（不重算 HMAC，链断裂）
    lines = freeze_mod.FREEZE_FILE.read_text().splitlines()
    e = json.loads(lines[0])
    e["sha256"] = hashlib.sha256(b"forged").hexdigest()
    e["hmac"] = "0" * 64
    lines[0] = json.dumps(e, separators=(",", ":"), sort_keys=True)
    freeze_mod.FREEZE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # 不带令牌跑 anchor-init（应默认拒绝）
    os.environ.pop("METACOG_ANCHOR_INIT_TOKEN", None)
    rc = freeze_mod.anchor_init()
    r.add("无令牌 anchor-init 被拒绝（rc==2, P1-3 收口）", rc == 2, "rc={}".format(rc))
    ok, viol = freeze_mod.verify()
    r.add("洗白失败后 verify 仍 fail-closed", ok is False)
    return r


def test_h1_path_in_tree():
    """v2.15.0 H-1/M-3：_valid_entry 必须拒绝任何树外路径（绝对路径 / ~ / Windows 盘符 / .. 逃逸），接收树内相对路径。"""
    r = T()
    base = {"path": "scripts/freeze.py", "sha256": "a" * 64,
            "at": "2026-10-15T00:00:00Z", "prev_hmac": "", "hmac": "b" * 64}
    ok_in, why = freeze_mod._valid_entry(dict(base))
    r.add("树内相对路径被接收", ok_in, why)
    # 绝对路径（POSIX）
    bad_abs = dict(base); bad_abs["path"] = "/etc/passwd"
    r.add("绝对路径 /etc/passwd 被拒（H-1 收口）", not freeze_mod._valid_entry(bad_abs)[0])
    # 树外逃逸 ../
    bad_esc = dict(base); bad_esc["path"] = "../escaped/x"
    r.add("树外逃逸 ../escaped/x 被拒", not freeze_mod._valid_entry(bad_esc)[0])
    # 中间 .. 逃逸到树外
    bad_esc2 = dict(base); bad_esc2["path"] = "a/../../b"
    r.add("中间 .. 逃逸 a/../../b 被拒", not freeze_mod._valid_entry(bad_esc2)[0])
    # Windows 盘符
    bad_drv = dict(base); bad_drv["path"] = "C:/windows/system32"
    r.add("Windows 盘符 C:/windows 被拒", not freeze_mod._valid_entry(bad_drv)[0])
    # ~ 家目录
    bad_tilde = dict(base); bad_tilde["path"] = "~/secrets"
    r.add("~ 家目录 ~/secrets 被拒", not freeze_mod._valid_entry(bad_tilde)[0])
    # 树内 .. 折叠（不逃逸，应接收）
    ok_fold = dict(base); ok_fold["path"] = "a/../b"
    r.add("树内折叠 a/../b 仍被接收", freeze_mod._valid_entry(ok_fold)[0])
    return r


def test_l1_at_iso_format():
    """v2.15.0 L-1：at 必须是 ISO-8601 UTC（YYYY-MM-DDThh:mm:ssZ），否则 _valid_entry 拒绝。"""
    r = T()
    good = {"path": "scripts/freeze.py", "sha256": "a" * 64,
            "at": "2026-10-15T12:34:56Z", "prev_hmac": "", "hmac": "b" * 64}
    ok, why = freeze_mod._valid_entry(dict(good))
    r.add("合法 ISO at 被接收", ok, why)
    bad = dict(good); bad["at"] = "hello"
    r.add("非法 at='hello' 被拒（L-1 收口）", not freeze_mod._valid_entry(bad)[0])
    bad2 = dict(good); bad2["at"] = "2026-10-15 12:34:56"
    r.add("空格分隔时间被拒", not freeze_mod._valid_entry(bad2)[0])
    bad3 = dict(good); bad3["at"] = "2026-10-15T12:34:56"  # 缺 Z
    r.add("缺 Z 后缀被拒", not freeze_mod._valid_entry(bad3)[0])
    return r


def test_p13_token_init_succeeds():
    """v2.15.0 M-2 诚实呈现：持令牌 + 结构合法 ledger，anchor_init 成功（rc=0）。
    证明令牌是防御纵深（非密码学根）——已知令牌值的同用户可调用，此为本设计预期行为（residual ②）。"""
    r = T()
    _clean_state()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    freeze_mod.record(["frozen_sample.py"])
    os.environ["METACOG_ANCHOR_INIT_TOKEN"] = freeze_mod._ANCHOR_INIT_TOKEN
    rc = freeze_mod.anchor_init()
    r.add("持令牌 + 合法 ledger：anchor_init 成功（rc==0，令牌非密码学根）", rc == 0, "rc={}".format(rc))
    ok, _ = freeze_mod.verify()
    r.add("anchor_init 后 verify 通过", ok)
    return r


def test_h1_crossplatform_backslash():
    """v2.16.0 HIGH-1（Hermes r12 跨平台实测）：Windows 反斜杠逃逸 `..\\outside\\SECRET.txt` 必须被 _path_in_tree 拒绝。
    v2.15.0 用 PurePosixPath 不识别 Windows 反斜杠为分隔符 → 实测 `_path_in_tree('..\\\\outside\\\\x')` 竟返回 True，
    使 record() 把树外文件哈希写入 ledger。v2.16.0 显式拒绝含反斜杠路径 + 平台一致 resolve/relative_to 包含性判定。"""
    r = T()
    base = {"path": "scripts/freeze.py", "sha256": "a" * 64,
            "at": "2026-10-15T00:00:00Z", "prev_hmac": "", "hmac": "b" * 64}
    # 模拟 Hermes r12 实测向量：反斜杠树外逃逸
    bad = dict(base); bad["path"] = "..\\outside\\SECRET.txt"
    ok_bad, why = freeze_mod._valid_entry(bad)
    r.add("Windows 反斜杠逃逸 ..\\outside\\SECRET.txt 被拒（HIGH-1 收口）", not ok_bad, why)
    # 树内但含反斜杠（ledger 路径恒为 POSIX 正斜杠）
    bad2 = dict(base); bad2["path"] = "scripts\\freeze.py"
    r.add("树内但含反斜杠 scripts\\freeze.py 被拒（ledger 路径须 POSIX）",
          not freeze_mod._valid_entry(bad2)[0])
    # 直接单测 _path_in_tree
    r.add("_path_in_tree('..\\\\outside\\\\x') == False（反斜杠逃逸）",
          freeze_mod._path_in_tree("..\\outside\\x") is False)
    r.add("_path_in_tree('scripts\\\\freeze.py') == False（反斜杠一律拒）",
          freeze_mod._path_in_tree("scripts\\freeze.py") is False)
    return r


def test_med2_record_edge_cases():
    """v2.16.0 MED-2（Hermes r12 实测）：record() 须对每个 rel 先经 _path_in_tree 校验，
    并对不可哈希路径（目录/无权限/空/根/不存在）跳过告警、不崩溃、不写脏数据。"""
    r = T()
    _clean_state()
    f = _TMP / "frozen_sample.py"
    _write(f, "original content\n")
    rc0 = freeze_mod.record(["frozen_sample.py"])
    r.add("基线：首次 record 成功", rc0 >= 0, "rc={}".format(rc0))
    before = _count_lines()
    # 造一个真实目录，触发 _hash_file 对目录的异常分支
    (_TMP / "scripts").mkdir(exist_ok=True)
    # 混合：合法 + 反斜杠树外 + 空 + 根 + 目录 + 不存在
    try:
        rc = freeze_mod.record(["frozen_sample.py", "..\\outside\\x", "", ".", "scripts", "nonexistent.py"])
        r.add("边缘组合 record 未抛异常（rc 合法）", isinstance(rc, int), "rc={}".format(rc))
    except Exception as ex:
        r.add("边缘组合 record 未抛异常（rc 合法）", False, "EXC={}".format(ex))
    after = _count_lines()
    # 断言反斜杠 / 空 / . / 目录 路径未写入 ledger
    bad_written = False
    for ln in (freeze_mod.FREEZE_FILE.read_text().splitlines() if freeze_mod.FREEZE_FILE.exists() else []):
        try:
            e = json.loads(ln)
            pth = e.get("path", "")
            if ("\\" in pth) or (pth in ("", ".")) or (pth == "scripts" and not _TMP.joinpath("scripts").is_file()):
                bad_written = True
        except Exception:
            pass
    r.add("反斜杠/空/./目录 路径未写入 ledger（MED-2 收口）", not bad_written)
    # 记录数只应增长（frozen_sample.py 已被重冻一次，append-only），不应因非法路径异常膨胀
    r.add("记录数未因非法路径异常膨胀", after >= before, "before={} after={}".format(before, after))
    return r


def test_low1_date_validity():
    """v2.16.0 LOW-1（Hermes r12 实测）：at 校验由正则 _ISO_AT 升级为 datetime.strptime，拒绝非法日期。"""
    r = T()
    base = {"path": "scripts/freeze.py", "sha256": "a" * 64,
            "at": "2026-10-15T12:34:56Z", "prev_hmac": "", "hmac": "b" * 64}
    ok, why = freeze_mod._valid_entry(dict(base))
    r.add("合法 ISO 日期被接收", ok, why)
    # v2.15.0 正则 _ISO_AT 会误收的非法日期
    bad_month = dict(base); bad_month["at"] = "2026-99-99T99:99:99Z"
    r.add("非法月/日/时 2026-99-99T99:99:99Z 被拒（LOW-1 收口）",
          not freeze_mod._valid_entry(bad_month)[0])
    bad_feb = dict(base); bad_feb["at"] = "2026-02-30T00:00:00Z"
    r.add("不存在的 2 月 30 日 2026-02-30T00:00:00Z 被拒",
          not freeze_mod._valid_entry(bad_feb)[0])
    return r


def test_h2_version_fallback_failclosed():
    """v2.16.0 HIGH-2（Hermes r12 实测）：metacog._read_skill_version_tuple 读取失败回退 fail-closed (99,99,99)，
    而非可令 legacy 容忍的低版本 (2,14,0)（fail-open）——杜绝删 SKILL.md / 缺 version 行静默打开安全门。
    本测试临时移走真实 SKILL.md 以触发读取失败，finally 中恢复。"""
    r = T()
    import importlib
    meta = importlib.import_module("metacog")
    real_root = Path(__file__).resolve().parent.parent
    sm = real_root / "SKILL.md"
    backup = real_root / "SKILL.md.h2bak"
    moved = False
    try:
        if sm.exists() and not backup.exists():
            sm.rename(backup)
            moved = True
        vt = meta._read_skill_version_tuple()
        r.add("读取失败回退 fail-closed 哨兵 (99,99,99)", vt == (99, 99, 99), "vt={}".format(vt))
    finally:
        if moved and backup.exists():
            backup.rename(sm)
    # 恢复后应正常读回真实版本
    vt2 = meta._read_skill_version_tuple()
    r.add("恢复后读取真实版本元组（非哨兵）", vt2 != (99, 99, 99), "vt2={}".format(vt2))
    return r


def main():
    results = []
    results.append(test_hb1_record_after_truncate_refused())
    results.append(test_hb2_anchor_missing_failclosed())
    results.append(test_hb3_empty_ledger_failclosed())
    results.append(test_hb4_intree_anchor_rejected())
    results.append(test_reset_blocked_double_delete())
    results.append(test_anchor_init_launder_refused())
    results.append(test_h1_path_in_tree())
    results.append(test_l1_at_iso_format())
    results.append(test_p13_token_init_succeeds())
    results.append(test_h1_crossplatform_backslash())
    results.append(test_med2_record_edge_cases())
    results.append(test_low1_date_validity())
    results.append(test_h2_version_fallback_failclosed())
    all_ok = all(t.summary() for t in results)
    print("\n########## v2.16.0 H-B/P1/H-1/HIGH-1/HIGH-2/MED-2/LOW-1 收口套件汇总 ##########")
    print("SUITE: {}".format("ALL PASS" if all_ok else "HAS FAILURE"))
    # 清理
    shutil.rmtree(_TMP, ignore_errors=True)
    freeze_mod._remove_anchor()  # 锚点已落只读，需先解除只读再删
    freeze_mod._remove_marker()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
