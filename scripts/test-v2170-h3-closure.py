#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.17.0（Hermes r13 复派）H-3 / L-1 / L-2 / M-6 收口对抗回归测试套件（独立验证，非自验自收）

v2.17.0 针对 Hermes r13 指出的根因项做代码层收口：
  - H-3 [HIGH]：v2.16.0 及之前 `record()` 的冻结态重置门（RESET-BLOCKED）由裸环境变量
        `METACOG_FREEZE_ALLOW_RESET=1` 字符串比较打开（无令牌）；且 `METACOG_FREEZE_ALLOW_MISSING=1`
        能旁路重置门。等价于「export 一行即绕过全部冻结保护」。
        v2.17.0：① ALLOW_MISSING 不再能旁路 RESET-BLOCKED；② 重置门须同时满足
        `METACOG_FREEZE_ALLOW_RESET=1` 且 `METACOG_FREEZE_RESET_TOKEN == _RESET_TOKEN`（与 anchor-init 令牌门对齐）。
  - L-1 [LOW]：`_read_skill_version_tuple` 读取失败回退 fail-closed 哨兵 (99,99,99) 时，向 stderr 打印 WARN 提升可诊断性。
  - L-2 [LOW]：version 正则锚定到 frontmatter 首块（^---\\n...version:），杜绝正文/注释中 `version: X.Y.Z` 被误读。
  - M-6 [MED]：`LEGACY_HASH_CUTOFF_VERSION` 由 2-tuple (2,9) 统一为 3-tuple (2,9,0)，与其余 cutoff (2,15,0) 长度一致。

零第三方依赖。锚点定向临时文件，不污染真实树外锚。
"""
import importlib
import os
import sys
import tempfile
from pathlib import Path

# 隔离：锚点指向临时文件（技能树之外，避免污染真实 ~/.metacog_freeze_anchors）
os.environ["METACOG_FREEZE_ANCHOR"] = str(Path(tempfile.gettempdir()) / "metacog_v2170_test_anchor.anchor")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))
import freeze as freeze_mod

_TMP = Path(tempfile.mkdtemp(prefix="metacog_v2170_"))
freeze_mod.SKILL_ROOT = _TMP
freeze_mod.FREEZE_FILE = _TMP / "frozen-hashes.jsonl"
_ANCHOR = Path(os.environ["METACOG_FREEZE_ANCHOR"])


class _Env:
    """临时设置/恢复若干环境变量的上下文管理器。"""
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


def _clean_state():
    """清理账本 + 树外锚 + 安装标记，保证用例隔离。"""
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
        print("v2.17.0 H-3/L-1/L-2/M-6 收口回归: {}/{} PASS".format(self.passed, total))
        print("=" * 60)
        return self.failed == 0


def _simulate_reset_blocked_state():
    """构造「冻结态被清空重置」场景：账本缺失 + 锚缺失 + 安装标记仍在。"""
    _clean_state()
    # 仅写入安装标记（模拟曾经初始化），账本与锚均缺失
    freeze_mod._write_marker()


def test_h3_allow_missing_no_longer_bypasses_reset_block():
    """H-3a：METACOG_FREEZE_ALLOW_MISSING=1 单独存在，不得旁路 RESET-BLOCKED。"""
    r = T()
    _simulate_reset_blocked_state()
    with _Env(METACOG_FREEZE_ALLOW_MISSING="1", METACOG_FREEZE_ALLOW_RESET=None, METACOG_FREEZE_RESET_TOKEN=None):
        rc = freeze_mod.record(["frozen_sample.py"])
        r.add("ALLOW_MISSING=1 仍被 RESET-BLOCKED 拒绝（rc<0）", rc < 0, "rc={}".format(rc))
    r.add("拒绝后账本未被创建", not freeze_mod.FREEZE_FILE.exists())
    return r


def test_h3_allow_reset_without_token_refused():
    """H-3b：METACOG_FREEZE_ALLOW_RESET=1 无令牌，不得旁路 RESET-BLOCKED（裸环境变量逃生舱已封）。"""
    r = T()
    _simulate_reset_blocked_state()
    with _Env(METACOG_FREEZE_ALLOW_MISSING=None, METACOG_FREEZE_ALLOW_RESET="1", METACOG_FREEZE_RESET_TOKEN=None):
        rc = freeze_mod.record(["frozen_sample.py"])
        r.add("ALLOW_RESET=1 无令牌仍被 RESET-BLOCKED 拒绝（rc<0）", rc < 0, "rc={}".format(rc))
    r.add("拒绝后账本未被创建", not freeze_mod.FREEZE_FILE.exists())
    return r


def test_h3_allow_reset_with_token_succeeds():
    """H-3c：ALLOW_RESET=1 + 正确 METACOG_FREEZE_RESET_TOKEN，重置门正常授权（证明令牌门可用）。"""
    r = T()
    _simulate_reset_blocked_state()
    with _Env(METACOG_FREEZE_ALLOW_MISSING=None, METACOG_FREEZE_ALLOW_RESET="1",
              METACOG_FREEZE_RESET_TOKEN=freeze_mod._RESET_TOKEN):
        f = _TMP / "frozen_sample.py"
        f.write_text("reset content\n", encoding="utf-8")
        rc = freeze_mod.record(["frozen_sample.py"])
        r.add("ALLOW_RESET=1 + 正确令牌 → 重置授权成功（rc>=0）", rc >= 0, "rc={}".format(rc))
    r.add("重置成功后账本已创建", freeze_mod.FREEZE_FILE.exists())
    return r


def test_h3_first_init_without_any_env_allowed():
    """对照：首次全新初始化（标记缺失）不须任何令牌，record 成功。"""
    r = T()
    _clean_state()  # 标记/账本/锚全缺 = 首次安装
    with _Env(METACOG_FREEZE_ALLOW_MISSING=None, METACOG_FREEZE_ALLOW_RESET=None, METACOG_FREEZE_RESET_TOKEN=None):
        f = _TMP / "frozen_sample.py"
        f.write_text("first init\n", encoding="utf-8")
        rc = freeze_mod.record(["frozen_sample.py"])
        r.add("首次全新初始化（无令牌）record 成功（rc>=0）", rc >= 0, "rc={}".format(rc))
    return r


def test_l2_frontmatter_anchored_version_and_warn():
    """L-2：version 正则锚定 frontmatter 首块——注释/正文里的 version: 不被误读；失败回退哨兵时打印 WARN（L-1）。"""
    r = T()
    meta = importlib.import_module("metacog")
    real_root = Path(__file__).resolve().parent.parent
    sm = real_root / "SKILL.md"
    backup = real_root / "SKILL.md.v2170bak"
    moved = False
    try:
        if sm.exists() and not backup.exists():
            sm.rename(backup)
            moved = True
        # 仅注释/代码块内出现 version: 9.9.9，frontmatter 无 version: → 应回退哨兵 (99,99,99)
        sm.write_text(
            "---\nname: x\n# 注释里 version: 9.9.9 不该被误读\n---\n"
            "正文也可能写 `version: 9.9.9`\n", encoding="utf-8")
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            vt = meta._read_skill_version_tuple()
        r.add("L-2：注释/正文 version: 不被误读 → 回退哨兵 (99,99,99)", vt == (99, 99, 99), "vt={}".format(vt))
        r.add("L-1：回退哨兵时向 stderr 打印 WARN", "WARN" in buf.getvalue(), "stderr={}".format(buf.getvalue().strip()[:80]))
        # frontmatter 内含合法 version: 2.17.0 → 应正确读回
        sm.write_text(
            "---\nname: x\nversion: 2.17.0\ndesc: y\n---\nbody\n", encoding="utf-8")
        vt2 = meta._read_skill_version_tuple()
        r.add("L-2：frontmatter version: 正确读回 (2,17,0)", vt2 == (2, 17, 0), "vt2={}".format(vt2))
    finally:
        if moved and backup.exists():
            os.replace(backup, sm)  # 用备份覆盖还原真实 SKILL.md（os.replace 可安全覆盖已存在的目标）
    return r


def test_m6_legacy_cutoff_is_3tuple():
    """M-6：LEGACY_HASH_CUTOFF_VERSION（Store 类属性）已统一为 3-tuple (2,9,0)。"""
    r = T()
    meta = importlib.import_module("metacog")
    cut = meta.Store.LEGACY_HASH_CUTOFF_VERSION
    cur = meta.Store.CURRENT_VERSION_TUPLE
    r.add("M-6：Store.LEGACY_HASH_CUTOFF_VERSION == (2,9,0)（3-tuple 与其余 cutoff 一致）",
          cut == (2, 9, 0), "val={}".format(cut))
    # 语义不变：当前版本不早于 cutoff ⇒ legacy 不被允许（窗口关闭）
    r.add("M-6：CURRENT {} < cutoff {} 为 False（legacy 窗口已关闭）".format(cur, cut),
          not (cur < cut), "cur={} cut={}".format(cur, cut))
    return r


def main():
    results = []
    results.append(test_h3_allow_missing_no_longer_bypasses_reset_block())
    results.append(test_h3_allow_reset_without_token_refused())
    results.append(test_h3_allow_reset_with_token_succeeds())
    results.append(test_h3_first_init_without_any_env_allowed())
    results.append(test_l2_frontmatter_anchored_version_and_warn())
    results.append(test_m6_legacy_cutoff_is_3tuple())
    all_ok = all(t.summary() for t in results)
    print("\n########## v2.17.0 H-3/L-1/L-2/M-6 收口套件汇总 ##########")
    print("SUITE: {}".format("ALL PASS" if all_ok else "HAS FAILURE"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
