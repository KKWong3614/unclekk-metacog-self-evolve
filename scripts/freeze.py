#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.16.0（Hermes r10/r11/r12 复派 P1/P2 收口）：测试/源冻结清单 —— append-only + HMAC 链 + 树外锚点 + 写前校验 + 安装标记 + 特权恢复门禁 + 只读保护

背景：v2.12.0 的「冻结清单」用**不可变**机制替代 CHANGELOG 内联散文 sha256（Hermes r7 H-A）：
  - frozen-hashes.jsonl（技能根目录）：每行一条冻结记录
        {"path": <相对技能根>, "sha256": <当前哈希>, "at": <ISO>, "prev_hmac": <链上一跳>, "hmac": <本跳>}
  - append-only：冻结哈希只追加、旧哈希永不被覆写；重基线必须追加新条目，旧条目原样保留。
  - HMAC 链（审计链同源模式）：任一条目被改/删/重排 → 链断裂 → 校验器 fail-closed 检出。
  - 树外锚点：ledger 提交值（sha256(ledger 字节)）写入技能树之外的锚文件；整体替换 ledger → FROZEN-ANCHOR 不匹配 fail-closed。

v2.13.0 收口 Hermes r9 高绕过（H-B1/H-B2/H-B3/H-B4，见 v2.13.0 注释）。

v2.14.0 收口 Hermes r10 P1/P2（诚实威胁模型：防「仅持技能树写权」的篡改；持 ledger+锚 双写权=已破信任根，属已知 residual）：
  - [P1-3 HIGH] anchor-init 加授权门禁：必须携带 METACOG_ANCHOR_INIT_TOKEN，否则 fail-closed 拒绝（返回 2）。
              封堵「同用户跑一次 anchor-init 洗白任意 ledger 篡改」——r10 新增最高危发现。
              anchor-init 同时写入审计日志（时间戳 + uid）。
              v2.27.17（M-03 收口）：令牌不再存于代码字面量，改双 env 比对（提供值 vs 期望值，均不落源码）。
  - [P1-2 HIGH] 新增安装状态标记 FROZEN_STATE marker（落在树外，与锚同目录）：
              record() bootstrap 分支：账本+锚 双删 但 marker 仍在 → FROZEN-RESET-BLOCKED fail-closed
              （除非 METACOG_FREEZE_ALLOW_RESET=1 且 METACOG_FREEZE_RESET_TOKEN 正确），封堵「删账本+删锚 后静默 re-init」孪生绕过。marker 缺失才允许首次全新初始化。
              v2.17.0（Hermes r13 H-3 收口）：重置门须令牌授权，METACOG_FREEZE_ALLOW_MISSING 不再能绕过 RESET-BLOCKED。
  - [P1-1 诚实披露（v2.14.0 原文）] 明确 HMAC 链密钥为代码内派生常量（旧常量种子 + _FREEZE_HMAC_LABEL）⇒ 对同用户/持代码读权攻击者
              零密码学保护（可读源码重算密钥伪造整条链）；唯一真正防御 tree-only 篡改的是**树外锚点**（攻击者不可写，
              声称「防仅持技能树写权」即指此）。威胁模型已在 SKILL.md §威胁模型 完整登记，不再混同 HMAC 链与锚点保护强度。
              （v2.27.19 N-3 收口：旧常量种子已删除，披露转为历史记录，见下方 v2.14.0 P1-1 → v2.27.19 更新块。）
              v2.27.19（N-3 收口）：常量链密钥已删除，改由部署专属 env 锚密钥派生（与账本签名锚同源，C-01 口径）——
              上述「可读源码重算密钥」残余闭合（新口径：须知部署 env 密钥方可伪造链）；env 对本进程可读属部署契约残余（同 C-01）。
  - [P1-4] 树外锚点写后落只读属性（Windows FILE_ATTRIBUTE_READONLY / POSIX 0444）；写前先解除（_unprotect/_protect）。
              ledger 位于技能树内（tree-only 攻击者本就可写），按设计不落只读，仅锚点（信任根）落只读。
  - [P2-5] _parse_chain 增加 ledger schema 白名单校验（字段集合/类型/HMAC·sha256 长度 64 hex/prev_hmac 格式/path 相对路径无 .. 逃逸）。
  - [P2-7] _reject_in_tree_anchor 依赖 resolve() 解引用符号链接——锚为指向树内的 symlink 也会被拒（已注释说明）。

v2.15.0 收口 Hermes r11 新发现（H-1/H-2/M-1/M-2/L-1/L-2 + §2 完整性）：
  - [H-1/M-3] _valid_entry 新增 _path_in_tree：纯字符串规范化拒绝绝对路径/Windows 盘符/逃逸出树的 '..' 路径（注：树内 '..' 如 foo/../bar 解析后仍落在树内，按设计放行，不视为逃逸），
              确保 ledger 内 path 恒落技能树内（verify 时按 SKILL_ROOT/p 哈希，杜绝树外文件哈希泄露）。
  - [H-2] 显式登记 residual ⑤：删 ledger 保锚截断需同步改写树外锚（tree-only 攻击者无锚写权 ⇒ 已被
              FROZEN-ANCHOR 不匹配 fail-closed）；持锚写权=已破信任根（同 residual ①），非代码层可防。
  - [M-1] metacog.py LEGACY_*_CUTOFF 改为显式字面量 (2,15,0)，不再从 SKILL.md version: 动态派生，
              version: 字段退出安全门控（改版本号不再静默改变信任策略）。
  - [L-1] _valid_entry 新增 at 字段 ISO-8601 UTC（YYYY-MM-DDThh:mm:ssZ）格式校验。
  - [L-2] _write_anchor 改用同目录临时文件 + os.replace 原子替换，缩窄 _unprotect→write→_protect 的 TOCTOU 窗口。
  - [M-2] SKILL.md §4 显式声明「anchor-init 令牌非密码学根，持本机代码执行权的同用户可读源码获得令牌并调用」。
  - [§2 完整性] 审计语料补出 _anchor_path/_read_anchor/_read_marker/_write_marker/_protect/_unprotect/
              _file_drift_violations/_hash_file/_load_lines/_audit_log/_HEX64/_ISO_AT 等全部引用函数，逐字公开。
  - [§4 证据] 测试输出附可复现命令 + 文件路径 + 文件 sha256；新增 P1-3 正向用例（持令牌 anchor-init 成功，
              诚实呈现「令牌非密码学根」这一预期行为）。

v2.16.0 收口 Hermes r12 独立复现实测发现（HIGH-1 / HIGH-2 / MED-2 / LOW-1）：
  - [HIGH-1·Hermes r12 实测] `_path_in_tree` 改用与真实拼接一致的语义：`(SKILL_ROOT / rel).resolve()` 必须 == root
              或严格在 root 之内（relative_to 不抛）。**根因修复**：v2.15.0 用 PurePosixPath 规范化，但 Windows 上
              `SKILL_ROOT / rel` 是 WindowsPath 语义（反斜杠是分隔符），PurePosixPath 把 `..\\outside` 当单字串不识别
              `..` 逃逸 → 实测 `record('..\\outside\\x')` 竟通过并把树外文件哈希写入 ledger。v2.16.0 显式拒绝含反斜杠路径 +
              用平台一致的 resolve/relative_to 做包含性判定，彻底封堵。
  - [HIGH-2·Hermes r12 实测] `metacog.py _read_skill_version_tuple` 读取失败不再回退到可令 legacy 容忍的低版本
              `(2,14,0)`（fail-open），改为 fail-closed 哨兵 `(99,99,99)`（读不到版本号 ⇒ 不容忍任何 legacy），
              杜绝删 SKILL.md / 缺 version 行触发的安全门静默打开。
  - [MED-2·Hermes r12 实测] `record()` 循环对每个 rel 先经 `_path_in_tree` 校验（拒绝 '' / '.' / 树外 / 绝对路径），
              并用 try/except 包裹 `_hash_file`（目录/无权限等不可哈希路径不再崩溃，跳过并告警）。
  - [LOW-1·Hermes r12 实测] `_valid_entry` 的 `at` 校验由正则 `_ISO_AT` 升级为 `datetime.strptime`（含日期有效性，
              拒绝 `2026-99-99` / `2026-02-30` 等非法日期）。

零第三方依赖。用法：
    python freeze.py record <rel-path> [<rel-path> ...]   # 追加冻结条目（写前门禁校验 + 自动维护锚/标记）
    python freeze.py verify                              # 校验全部冻结项 + ledger 完整性 + 树外锚点
    python freeze.py anchor-init                         # 特权恢复操作：显式重建树外锚点（需 METACOG_ANCHOR_INIT_TOKEN 与 _EXPECTED 成对一致）
"""
import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

SKILL_ROOT = Path(__file__).resolve().parent.parent
FREEZE_FILE = SKILL_ROOT / "frozen-hashes.jsonl"

# v2.11.0（H-A）：冻结 ledger 的 HMAC 派生标签（与基线签名/审计链 HMAC 标签分离，单钥双用防护）。
# 【诚实披露 v2.14.0 P1-1 → v2.27.19（N-3 收口）更新】：冻结 ledger 是**开发/发布期卫生工具**，
# 非运行期安全边界。v2.14.0-v2.27.18 期间其 HMAC 密钥为代码内派生常量（旧常量种子，名从历史），
# 对「同用户 / 持代码读权」攻击者零密码学保护——该残余**已于 v2.27.19 删除**：链密钥改由
# 部署专属锚密钥（env METACOG_TRUST_ROOT_ANCHOR_KEY，与账本签名锚同源，C-01 口径）派生，
# 未配置 / 非法 → record/verify 全拒（宁可装不上）。仍提供的保护：
#   (a) 意外损坏的检出；
#   (b) 与「树外锚点」配合，在 tree-only 攻击者（可写技能树、不可写树外锚）篡改 ledger 时，
#       因锚不匹配而 fail-closed（真正有效的隔离是树外锚点，而非 HMAC 链）。
#   (c) v2.27.19 起追加：链密钥部署专属化——持代码读权但不知部署 env 密钥者无法伪造 HMAC 链。
# 诚实边界（同 C-01）：env 密钥对本进程自身可读属部署契约；真正防篡改由「首次冻结哈希为权威
# + 旧哈希永覆写」语义 + 树外锚点共同保证。
_FREEZE_HMAC_LABEL = b"metacog-freeze-v211"
# v2.27.19（N-3 收口）：原代码常量种子已删除（源码卫生断言守卫：本文件全文不得再出现该常量名，
# 见 test-c01-no-default-anchor.py）。

# v2.14.0（P1-3）：anchor-init 授权令牌（防御纵深——非密码学根，仅用于强制「特权恢复」必须显式
# opt-in，阻止无令牌的自动化/误调用洗白篡改）。
# v2.27.17（C-01 专项 M-03 收口）：特权令牌**不再存于代码字面量**——原 `_ANCHOR_INIT_TOKEN` 与
# `_RESET_TOKEN` 两处明文常量对任何能读到源码（含 SKILL.md 引用）的进程等同公开，门禁形同虚设。改为**双 env 比对**：
# 调用方须同时提供 `METACOG_ANCHOR_INIT_TOKEN`（提供值）与 `METACOG_ANCHOR_INIT_TOKEN_EXPECTED`
# （期望值，部署方私下保管），两者恒定时间比对一致才放行；**无 EXPECTED → REFUSED（fail-closed）**。
# 提供值与期望值均不落源码，读源码不再等于持令牌（威胁模型收口至「读部署环境」）。
# 重置门同理：`METACOG_FREEZE_RESET_TOKEN` vs `METACOG_FREEZE_RESET_TOKEN_EXPECTED`。


def _token_pair_ok(provided_env: str, expected_env: str) -> bool:
    """v2.27.17（M-03）：特权令牌双 env 恒定时间比对。无期望值或无提供值 → False（fail-closed）。"""
    provided = os.environ.get(provided_env)
    expected = os.environ.get(expected_env)
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def _freeze_key():
    """v2.14.0：密钥 = HMAC(种子, 标签) → v2.27.19（N-3 收口）：链密钥改由**部署专属锚密钥**派生
    （env METACOG_TRUST_ROOT_ANCHOR_KEY，与账本签名锚同源——C-01 口径：信任根不由被约束方持有）。

    - env 未配置 → RuntimeError（fail-closed，record/verify 全拒，宁可装不上）。
    - env 非法 base64 / <32 字节 → ValueError 透传（M-01，trust_root.get_anchor_key）。
    - 诚实边界：env 对本进程可读属部署契约（同 C-01，非代码层可防）。
    - 迁移：旧常量种子签署的存量账本在新口径下链校验必失败（fail-closed）→
      须配置专属密钥后经授权重置门重新 record 建立基线（一次性破坏性迁移）。"""
    try:
        import trust_root
    except (ImportError, ModuleNotFoundError):
        raise RuntimeError(
            "trust_root 模块缺失，冻结链密钥无法派生（v2.27.19 N-3 收口：代码常量链密钥已删除，"
            "无任何兜底）——请恢复 trust_root.py（与 freeze.py 同目录）。")
    _anchor = trust_root.get_anchor_key()
    if _anchor is None:
        raise RuntimeError(
            "冻结链密钥未配置（v2.27.19 N-3 收口：代码常量链密钥已删除，与账本签名锚同源）。\n"
            "请设置环境变量 METACOG_TRUST_ROOT_ANCHOR_KEY 为 base64 编码的 ≥32 字节专属随机密钥；"
            "既有冻结账本须在配置后经授权重置门重新 record 建立基线。")
    return hmac.new(_anchor, _FREEZE_HMAC_LABEL, hashlib.sha256).digest()


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ───────────────────────── 树外锚点 + 安装标记 + 只读保护 ─────────────────────────

def _freeze_slug():
    """v2.27.35（R2-N-5 收口）：树外锚命名 slug = 「目录名--规范路径哈希前12位」。
    与 metacog._attest_slug 有意镜像（跨模块一致性由 test-v22735-n5-anchor-slug.py 断言）。
    v2.27.34 及以前为纯目录名——同机同名根目录实例互相覆盖树外锚（R2-N-5，Low）。"""
    import hashlib as _h
    canon = os.path.normcase(str(SKILL_ROOT.resolve()))
    return "{}--{}".format(SKILL_ROOT.name, _h.sha256(canon.encode("utf-8")).hexdigest()[:12])


def _anchor_write_path() -> Path:
    """v2.27.35（R2-N-5）：树外锚**写**路径——永远新命名，绝不写 legacy（否则迁移永不前进）。
    METACOG_FREEZE_ANCHOR env 显式覆盖时仍按 env（用户自命名，无碰撞问题）。"""
    env = os.environ.get("METACOG_FREEZE_ANCHOR")
    if env:
        p = Path(env).resolve()
        _reject_in_tree_anchor(p)
        return p
    return Path.home() / ".metacog_freeze_anchors" / (_freeze_slug() + ".anchor")


def _anchor_path() -> Path:
    """树外锚点**读**路径（v2.27.35 R2-N-5 迁移）：新命名优先；缺失且 legacy（纯目录名）
    锚绑定本实例时回退。绑定判据 = legacy 锚内容 == 当前账本 commitment
    （锚内容即 commitment，见 _write_anchor_with 调用处）——账本已变则不回退（fail-closed，
    须授权重 record 完成迁移）。**写路径请用 _anchor_write_path，勿用本函数。**"""
    env = os.environ.get("METACOG_FREEZE_ANCHOR")
    if env:
        p = Path(env).resolve()  # resolve() 解引用符号链接——symlink 指向树内也会被下方 _reject_in_tree_anchor 拒绝（v2.14.0 P2-7）
        _reject_in_tree_anchor(p)
        return p
    newp = _anchor_write_path()
    try:
        if newp.exists():
            return newp
    except OSError:
        return newp
    legacy = newp.parent / (SKILL_ROOT.name + ".anchor")
    if legacy.exists():
        try:
            if legacy.read_text(encoding="utf-8").strip() == _ledger_commitment():
                return legacy
        except Exception:
            pass
    return newp


def _marker_path() -> Path:
    """v2.14.0（P1-2）→ v2.27.35（R2-N-5）：安装状态标记（树外，锚同目录）。
    **写**路径用新命名 slug；读经 _read_marker 做 legacy 存在性回退（保守）。"""
    return _anchor_write_path().parent / (_freeze_slug() + ".installed")


def _reject_in_tree_anchor(p: Path):
    """v2.13.0 (H-B4) + v2.14.0 P2-7：锚必须落在技能树之外，否则「树外锚」机制失效。
    p 已 resolve()（解引用 symlink），故 symlink 指向树内同样被拒。"""
    try:
        p.relative_to(SKILL_ROOT.resolve())
    except ValueError:
        return  # p 不在技能树内，合法
    raise ValueError(
        "METACOG_FREEZE_ANCHOR 指向技能树内（{}），违反「树外锚」约束——锚必须落在技能树之外".format(p)
    )


def _read_marker() -> bool:
    # v2.27.35（R2-N-5）：新命名 OR legacy 命名任一存在即视为已安装（存在性保守判定，
    # 与 metacog._anchor_trace_exists 同口径——宁误报不漏报）。
    try:
        if _marker_path().exists():
            return True
        return (_anchor_write_path().parent / (SKILL_ROOT.name + ".installed")).exists()
    except OSError:
        return False


def _ledger_commitment() -> str:
    """v2.14.0 诚实披露：ledger 提交值 = sha256(ledger 全部字节)。
    截断/重排/整体替换 ledger → _ledger_commitment 变化 → 与树外锚不匹配 → FROZEN-ANCHOR fail-closed。
    这是 H-B1/H-B2 收口的真正支点（非 HMAC 链）。"""
    return hashlib.sha256(FREEZE_FILE.read_bytes()).hexdigest()


def _unprotect(p: Path):
    """解除只读（写前调用）。失败静默忽略。"""
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(p), 0x80)  # FILE_ATTRIBUTE_NORMAL
        else:
            os.chmod(p, 0o644)
    except Exception:
        pass


def _protect(p: Path):
    """v2.14.0（P1-4）：落只读属性（Windows FILE_ATTRIBUTE_READONLY=0x1 / POSIX 0444）。失败静默忽略。"""
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(p), 0x1)
        else:
            os.chmod(p, 0o444)
    except Exception:
        pass


def _audit_log(action: str, outcome: str, detail: str = ""):
    """v2.14.0（P1-3）：特权操作审计日志（时间戳 + uid），落树外锚同目录。失败静默忽略。"""
    try:
        p = _anchor_write_path().parent / (_freeze_slug() + ".audit.log")
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            uid = getpass.getuser()
        except Exception:
            uid = "?"
        line = "{} {} {} uid={} {}\n".format(_now_iso(), action, outcome, uid, detail)
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception as ex:  # v2.20.0（r16 L-3 收口）：审计日志尽力而为，但静默丢弃会让安全事件不可见；
        # 失败时向 stderr 输出 WARN（不阻断主流程），并在威胁模型登记此尽力而为性质。
        try:
            sys.stderr.write("[WARN] _audit_log 写入失败，审计事件已静默丢弃: %s\n" % ex)
        except Exception:
            pass


def _write_anchor_with(content: str):
    """v2.21.0（r17 M-新-1 收口·重构）：以指定内容写树外锚（原子替换 + 落只读）。
    供 _write_anchor() 正常写入，以及 record() 回滚时还原覆盖前锚内容复用。
    v2.27.35（R2-N-5）：**写走 _anchor_write_path（新命名）**，绝不写 legacy。"""
    p = _anchor_write_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # v2.20.0（r16 I-1 收口）：改用 tempfile 生成随机临时文件名，消除可预测 `.tmp` 名带来的并发竞态窗口。
    with tempfile.NamedTemporaryFile(dir=str(p.parent), delete=False, suffix=".tmp") as tf:
        tmp = Path(tf.name)
        tf.write(content.encode("utf-8"))
    _unprotect(p)  # 写前解除只读
    try:
        # v2.15.0（L-2）：同目录临时文件 + 原子替换，缩窄 _unprotect→write→_protect 的 TOCTOU 窗口
        os.replace(tmp, p)
        # v2.24.0（L-新-2 收口）：os.replace 已原子移走 tmp→p，故下方 unlink 在成功路径上 tmp 已不存在，
        # 仅为防御性清理 no-op；missing_ok=True 兜底极端并发残留的临时文件。该注释闭合文档↔源码证据链。
    finally:
        _protect(p)  # 写后落只读保护（v2.14.0 P1-4）
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _write_anchor():
    _write_anchor_with(_ledger_commitment())


def _read_anchor():
    p = _anchor_path()
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _remove_anchor():
    """v2.14.0：解除只读后删除锚（供测试/显式重置使用）。
    v2.27.35（R2-N-5）：新旧命名都清（legacy 残留会令读回退复活旧锚）。"""
    for p in (_anchor_write_path(),
              _anchor_write_path().parent / (SKILL_ROOT.name + ".anchor")):
        try:
            _unprotect(p)
            p.unlink(missing_ok=True)
        except OSError:
            pass


def _write_marker():
    """v2.14.0（P1-2）：写入安装状态标记（树外，与锚同目录）。
    v2.21.0（r17 M-新-1 收口）：返回 bool（True=成功 / False=失败），失败时向 stderr 输出 WARN
    （不再静默吞掉）。标记写入是 fail-closed 不变量「标记存在 ⟺ (ledger+锚点 存在)」的半边，
    静默失败会导致「ledger+锚在、标记缺」的不一致态，使后续 record() 被误判为首次安装、绕过 RESET-BLOCKED。
    record() 据此 fail-closed 回滚（见 record() 末段）。"""
    p = _marker_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("installed@" + _now_iso(), encoding="utf-8")
        return True
    except Exception as ex:
        sys.stderr.write("[WARN] _write_marker 写入失败，安装标记未建立：%s\n" % ex)
        return False


def _remove_marker():
    # v2.27.35（R2-N-5）：新旧命名都清（legacy 残留会令 _read_marker 误报已安装）
    _marker_path().unlink(missing_ok=True)
    try:
        (_anchor_write_path().parent / (SKILL_ROOT.name + ".installed")).unlink(missing_ok=True)
    except OSError:
        pass


# ───────────────────────── ledger 解析 / schema 校验 / HMAC 链 ─────────────────────────

def _load_lines():
    if not FREEZE_FILE.exists():
        return []
    return [l for l in FREEZE_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _path_in_tree(rel: str) -> bool:
    """v2.16.0（H-1 收口·Hermes r12 实测）：判定 rel 是否安全地落在技能树内。
    关键修正：v2.15.0 用 PurePosixPath 规范化，但 Windows 上 `SKILL_ROOT / rel` 是 WindowsPath 语义（反斜杠是分隔符），
    PurePosixPath 把 `..\\outside` 当单字串不识别 `..` 逃逸 → 实测 record('..\\outside\\x') 竟通过并把树外文件哈希写入 ledger。
    本版改用与真实拼接一致的语义：(SKILL_ROOT / rel).resolve() 必须 == root 或严格在 root 之内（relative_to 不抛）。
    注意：树内 '..'（如 foo/../bar 解析回树内）按设计放行——仅当解析结果逃逸出 root 才拒绝，行为安全，注释已据实收敛。
    同时显式拒绝：空串 / '.' / '~' 家目录 / Windows 盘符（C: 等）/ 含反斜杠（ledger 路径恒为 POSIX 正斜杠相对路径）。"""
    if not rel or rel.strip() == "":
        return False
    if rel.startswith("~"):
        return False
    if re.match(r"^[A-Za-z]:", rel):  # Windows 盘符（如 C:、D:）
        return False
    if "\\" in rel:  # ledger 路径一律 POSIX 正斜杠；反斜杠在 Windows 上是分隔符 → 一律拒绝
        return False
    try:
        root = SKILL_ROOT.resolve()
        target = (SKILL_ROOT / rel).resolve()
    except Exception:
        return False
    if target == root:
        return False  # rel 解析到根自身（'' / '.' / 仅 '..' 折叠回根）→ 非子路径文件
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _valid_entry(e) -> "tuple[bool, str]":
    """v2.14.0（P2-5）+ v2.15.0（H-1/L-1）收口：ledger schema 白名单 + 路径树内约束 + at 格式校验。返回 (ok, 原因)。"""
    if not isinstance(e, dict):
        return False, "非 dict 行"
    req = {"path": str, "sha256": str, "at": str, "prev_hmac": str, "hmac": str}
    for k, t in req.items():
        if k not in e or not isinstance(e[k], t):
            return False, "字段缺失/类型错误: {}".format(k)
    if not _HEX64.match(e["sha256"]):
        return False, "sha256 非 64 位 hex"
    if not _HEX64.match(e["hmac"]):
        return False, "hmac 非 64 位 hex"
    if e["prev_hmac"] and not _HEX64.match(e["prev_hmac"]):
        return False, "prev_hmac 非 64 位 hex（空串仅允许于首条记录）"
    # v2.16.0（L-1）：at 须为合法 ISO-8601 UTC（YYYY-MM-DDThh:mm:ssZ），含日期有效性（拒绝 2026-99-99 等非法日期）
    try:
        datetime.strptime(e["at"], "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return False, "at 非合法 ISO-8601 UTC（期望 YYYY-MM-DDThh:mm:ssZ）"
    # v2.15.0（H-1/M-3）：ledger 内 path 必须落在技能树内，杜绝绝对路径/盘符/'..' 逃逸
    if not _path_in_tree(e["path"]):
        return False, "path 逃逸技能树（绝对路径/盘符/'..' 逃逸）"
    return True, ""


def _parse_chain(lines):
    """解析并校验 HMAC 链（ledger 已被判存在且非空）。返回 (ok, violations, entries)。"""
    try:
        key = _freeze_key()
    except RuntimeError as _e:
        # v2.27.19（N-3 收口）：链密钥未配置/模块缺失 → 显式 violation（fail-closed，不裸 traceback）
        return False, ["FROZEN-KEY: {}".format(_e)], []
    prev = ""
    entries = []
    for ln in lines:
        try:
            e = json.loads(ln)
        except Exception:
            return False, ["FROZEN-LEDGER: 非法 JSON 行（ledger 被篡改）"], []
        ok, why = _valid_entry(e)
        if not ok:
            return False, ["FROZEN-LEDGER: schema 非法（{}）".format(why)], []
        if e.get("prev_hmac") != prev:
            return False, ["FROZEN-LEDGER: 链断裂（ledger 被改/删/重排）"], []
        payload = json.dumps({k: v for k, v in e.items() if k != "hmac"},
                             separators=(",", ":"), sort_keys=True)
        exp = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(exp, e.get("hmac", "")):
            return False, ["FROZEN-LEDGER: HMAC 失配（ledger 被篡改）"], []
        prev = e.get("hmac", "")
        entries.append(e)
    return True, [], entries


def _verify_anchor():
    """v2.13.0 (H-B2)：树外锚点检查。缺失=未初始化 fail-closed；不匹配=整体替换 fail-closed。"""
    anchor = _read_anchor()
    if anchor is None:
        if os.environ.get("METACOG_FREEZE_ALLOW_MISSING") == "1":
            return True, []
        return False, ["FROZEN-ANCHOR: 锚未初始化（技能声明冻结态但树外锚点不存在）。"
                       "请先运行 `python freeze.py anchor-init`（需 METACOG_ANCHOR_INIT_TOKEN）建立信任根。"]
    if anchor != _ledger_commitment():
        return False, ["FROZEN-ANCHOR: 树外锚点不匹配（ledger 已被整体替换/重算，证据链断裂）"]
    return True, []


def _file_drift_violations(entries):
    """基于首次冻结哈希权威 + 文件当前哈希，产出文件漂移/重冻结 violations。"""
    canon = {}      # path -> 首次 sha256
    seen = {}       # path -> 记录数
    order = []
    for e in entries:
        p = e.get("path")
        if p not in canon:
            canon[p] = e.get("sha256")
            order.append(p)
        seen[p] = seen.get(p, 0) + 1
    viol = []
    for p in order:
        fp = SKILL_ROOT / p
        if not fp.exists():
            viol.append("FROZEN-MISSING: {}（冻结文件已删除）".format(p))
            continue
        try:
            cur = _hash_file(fp)
        except Exception as ex:  # v2.20.0（r16 M-1 收口）：冻结文件变为目录/不可读时不再让 verify() 崩溃，
            # 而是登记一条违规并跳过（与 record() 路径的 MED-2 修复对齐，杜绝「修 A 忘 B」复发）。
            viol.append("FROZEN-READ-ERROR: {}（无法读取冻结文件：{}）".format(p, ex))
            continue
        # v2.27.15（L-07）：哈希比较改 hmac.compare_digest
        if not hmac.compare_digest(cur, canon[p]):
            viol.append("FROZEN-MODIFIED: {}（首次冻结={} 当前={}）".format(p, canon[p], cur))
        if seen[p] > 1:
            viol.append("RE-FROZEN: {} 在初次冻结后被再次冻结 {} 次（纪律告警：冻结后被改并重冻）"
                        .format(p, seen[p] - 1))
    return viol


def _verify_core(check_files=True):
    """完整/结构校验入口。check_files=True 含文件漂移检测；False 仅供 record/anchor-init 门禁使用。
    顺序：账本缺失(H-B 账本缺失) → 空账本(H-B3) → 树外锚(H-B2，先于链解析) → HMAC 链 → 文件漂移。"""
    if not FREEZE_FILE.exists():
        if os.environ.get("METACOG_FREEZE_ALLOW_MISSING") == "1":
            return True, []
        return False, ["FROZEN-LEDGER: 账本缺失（技能声明冻结态但 frozen-hashes.jsonl 不存在）"]
    lines = _load_lines()
    if not lines:
        return False, ["FROZEN-LEDGER: 账本为空（0 条冻结记录，无约束，视为证据链断裂）"]
    aok, aviol = _verify_anchor()
    if not aok:
        return False, aviol
    ok, viol, entries = _parse_chain(lines)
    if not ok:
        return False, viol
    if not check_files:
        return True, []
    fd = _file_drift_violations(entries)
    return (len(fd) == 0, fd)


def verify():
    """完整校验：ledger 完整性 + 树外锚点 + 各冻结文件当前哈希 vs 首次冻结哈希。返回 (ok, violations)。"""
    return _verify_core(check_files=True)


def _record_gate_ok():
    """v2.13.0 (H-B1)：record 写前门禁——ledger 结构 + 树外锚必须有效，但不查文件漂移（合法重冻不受影响）。
    v2.20.0（r16 L-4 收口）：移除不可达的 `if not FREEZE_FILE.exists(): return True, []` 死分支——
    record() 仅在 FREEZE_FILE 存在的 else 分支调用本门禁，该分支永不可达。"""
    lines = _load_lines()
    if not lines:
        return False, ["FROZEN-LEDGER: 账本为空（0 条冻结记录，无约束，视为证据链断裂）"]
    aok, aviol = _verify_anchor()
    if not aok:
        return False, aviol
    ok, viol, _ = _parse_chain(lines)
    if not ok:
        return False, viol
    return True, []


def record(rel_paths):
    """追加冻结条目（append-only）。
    - 现有账本：写前必须过 _record_gate_ok() 门禁（ledger 结构 + 树外锚匹配），否则 fail-closed 拒绝（v2.13.0 H-B1）。
    - 全新初始化（账本缺失）：区分「首次安装」与「冻结态被清空重置」——
      若账本+锚 双删 但 安装标记仍在 → FROZEN-RESET-BLOCKED fail-closed（v2.14.0 P1-2）；仅标记缺失才允许首次初始化。
    写成功后自动维护树外锚（落只读）与安装标记。返回追加条数；被拒时返回 -1。"""
    if not FREEZE_FILE.exists():
        anchor = _read_anchor()
        # v2.17.0（Hermes r13 H-3 收口）：ALLOW_MISSING 仅容忍「树外锚残留」这一读路径异常，
        # 不得用于绕过「冻结态被清空重置」的安全门（RESET-BLOCKED）。重置门仅可由 ALLOW_RESET + 正确令牌打开。
        if anchor is not None and os.environ.get("METACOG_FREEZE_ALLOW_MISSING") != "1":
            print("[REFUSED] record 被拒绝：账本缺失但树外锚点残留，疑似账本被重置。请先显式 anchor-init 或恢复账本。")
            return -1
        # 账本缺失 + 锚缺失：进一步区分首次安装 vs 清空重置
        if _read_marker():
            # v2.17.0（H-3 收口）：重置门禁须 METACOG_FREEZE_ALLOW_RESET=1 且重置令牌校验通过，
            # 不再是裸环境变量字符串比较（杜绝 `export METACOG_FREEZE_ALLOW_RESET=1` 单行绕过全部冻结保护）。
            # v2.27.17（M-03）：令牌改双 env 比对（METACOG_FREEZE_RESET_TOKEN vs
            # METACOG_FREEZE_RESET_TOKEN_EXPECTED，恒定时间；无 EXPECTED → REFUSED）。
            allow_reset = os.environ.get("METACOG_FREEZE_ALLOW_RESET") == "1"
            if not (allow_reset and _token_pair_ok("METACOG_FREEZE_RESET_TOKEN",
                                                   "METACOG_FREEZE_RESET_TOKEN_EXPECTED")):
                print("[REFUSED] record 被拒绝：安装标记存在但账本+锚均缺失，疑似冻结态被清空重置"
                      "（FROZEN-RESET-BLOCKED）。请恢复冻结态，或带 METACOG_FREEZE_ALLOW_RESET=1 "
                      "且 METACOG_FREEZE_RESET_TOKEN / METACOG_FREEZE_RESET_TOKEN_EXPECTED "
                      "成对一致的令牌显式授权重置。")
                _audit_log("record", "REFUSED", "reset-blocked(marker-present)")
                return -1
        # 首次全新初始化（marker 缺失）或显式令牌授权重置
    else:
        ok, viol = _record_gate_ok()
        if not ok:
            print("[REFUSED] record 被拒绝：现有账本校验未通过（FROZEN-RECORD-BLOCKED）。请先修复或重新 anchor-init。")
            for v in viol:
                print("  - " + v)
            return -1

    # v2.27.31（R-4）：C-1 信任根完整性门禁——attestation 层已钉固时，record 须先确认信任根完好
    # （树外公钥/attestation 存在、外部根锚**签名密封**有效且与钉固一致、attestation 未过期）。
    # 刻意不要求 commitment 匹配（record 的用途就是重写被跟踪文件，必然使旧 commitment 失配）；
    # 安全闭环 = record 后 attestation 仍失配 → 受控命令 fail-closed → 须离线重签。
    try:
        import metacog as _mc
        _ok_root, _viol = _mc._attest_root_integrity(_mc.Store(SKILL_ROOT))
        if not _ok_root:
            print("[REFUSED] record 被拒绝：C-1 信任根完整性校验未通过（FROZEN-C1-ROOT-BLOCKED）：")
            for _v in _viol:
                print("  - " + str(_v))
            print("  须先修复信任根（重装 attestation 层 / 由持离线私钥的一方重新密封）再重基线。")
            _audit_log("record", "REFUSED", "c1-root-integrity")
            return -1
    except ImportError:
        pass
    try:
        key = _freeze_key()
    except RuntimeError as _e:
        # v2.27.19（N-3 收口）：链密钥未配置/模块缺失 → REFUSED（fail-closed，不裸 traceback）
        print("[REFUSED] record 被拒绝：{}".format(_e))
        _audit_log("record", "REFUSED", "freeze-key-unconfigured")
        return -1
    lines = _load_lines()
    prev = ""
    if lines:
        try:
            prev = json.loads(lines[-1]).get("hmac", "")
        except Exception:
            prev = "<broken>"
    count = 0
    pre_size = FREEZE_FILE.stat().st_size if FREEZE_FILE.exists() else 0  # v2.20.0（r16 M-2 收口）：记录追加前尺寸，用于锚失败时回滚
    for rel in rel_paths:
        if not _path_in_tree(rel):  # v2.16.0（H-1/MED-2）：拒绝树外/非法/空/绝对路径，杜绝树外文件哈希混入 ledger
            print("[WARN] 跳过树外/非法路径：{}".format(rel))
            continue
        p = SKILL_ROOT / rel
        if not p.exists():
            print("[WARN] 跳过不存在的路径：{}".format(rel))
            continue
        try:
            sha = _hash_file(p)
        except Exception as ex:  # v2.16.0（MED-2）：目录/无权限等不可哈希路径不崩溃，跳过
            print("[WARN] 跳过无法哈希的路径 {}：{}".format(rel, ex))
            continue
        entry = {
            "path": rel,
            "sha256": sha,
            "at": _now_iso(),
            "prev_hmac": prev,
        }
        payload = json.dumps(entry, separators=(",", ":"), sort_keys=True)
        entry["hmac"] = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        with FREEZE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
        prev = entry["hmac"]
        count += 1
        print("[FREEZE] {} -> {}".format(rel, sha))
    print("已追加 {} 条冻结记录 → {}".format(count, FREEZE_FILE))
    if count == 0:
        # v2.19.0（Hermes r15 F-6 收口）：全部路径被跳过（树外/非法/不存在/不可哈希）时，
        # 不应静默返回成功并写锚点——冻结态实际未改变，用户仅靠 [WARN] 才知道。
        # 显式 REFUSED 并 fail-closed 返回 -1（main 据此 rc=1）。
        print("[REFUSED] record 未追加任何记录（全部路径无效/被跳过），冻结态未改变，不写锚点。")
        _audit_log("record", "REFUSED", "zero-appended")
        return -1
    # 写/更新树外锚点（落只读）；若锚不可写（如树外锚无写权，典型 tree-only 攻击者）→ 冻结无意义，fail-closed
    pre_anchor = _read_anchor()  # v2.21.0（r17 M-新-1 收口）：记录覆盖前锚内容，供标记写入失败时还原
    try:
        _write_anchor()
    except Exception as ex:
        # v2.20.0（r16 M-2 收口）：锚写入失败时，回滚本次已追加的 ledger 条目（截断到追加前尺寸，
        # 首初始化则删除空 ledger）；锚尚未写入故无需回滚锚。
        try:
            if pre_size == 0:
                if FREEZE_FILE.exists():
                    FREEZE_FILE.unlink(missing_ok=True)
            elif FREEZE_FILE.exists():
                os.truncate(str(FREEZE_FILE), pre_size)
        except Exception:
            pass
        print("[REFUSED] record 锚点写入失败（{}）：已回滚本次 ledger 追加，冻结态未改变，不写锚点。".format(ex))
        _audit_log("record", "REFUSED", "anchor-write-failed/rolled-back")
        return -1
    # 维护安装标记（树外）；写入失败 → fail-closed 回滚 ledger + 还原锚点，杜绝「ledger+锚在、标记缺」不一致态
    if not _write_marker():
        # v2.21.0（r17 M-新-1 收口）：标记写入失败（文件系统异常）属 fail-closed 漏洞——若静默留
        # 「ledger+锚在、标记缺」，后续删 ledger+锚 后 record() 会被误判为首次安装、绕过 RESET-BLOCKED。
        # 故回滚 ledger 到追加前尺寸，并把锚还原到覆盖前内容，保持「标记存在 ⟺ (ledger 存在 & 锚匹配)」不变量。
        try:
            if pre_size == 0:
                if FREEZE_FILE.exists():
                    FREEZE_FILE.unlink(missing_ok=True)
            elif FREEZE_FILE.exists():
                os.truncate(str(FREEZE_FILE), pre_size)
        except Exception:
            pass
        try:
            if pre_anchor is None:
                _remove_anchor()  # 首初始化：删掉刚写的新锚，回到「无任何冻结态」
            else:
                _write_anchor_with(pre_anchor)  # 追加场景：还原旧锚，与回滚后的 ledger 一致
        except Exception:
            pass
        print("[REFUSED] record 安装标记写入失败：已回滚本次 ledger 追加并还原锚点，冻结态未改变，不写标记。")
        _audit_log("record", "REFUSED", "marker-write-failed/rolled-back")
        return -1
    _audit_log("record", "OK", "appended={}".format(count))
    return count


def anchor_init():
    """v2.14.0（P1-3）：特权恢复操作——显式建立/重建信任根（树外锚点）。
    v2.27.17（M-03）：令牌改双 env 比对——须同时提供 METACOG_ANCHOR_INIT_TOKEN（提供值）与
    METACOG_ANCHOR_INIT_TOKEN_EXPECTED（期望值，部署方私下保管，不落源码），恒定时间一致才放行；
    缺一或错配 → fail-closed 拒绝（返回 2）。
    封堵「同用户跑一次 anchor-init 洗白任意 ledger 篡改」。要求 ledger 存在且结构校验通过（不含锚检查，因锚正被建立）。"""
    if not _token_pair_ok("METACOG_ANCHOR_INIT_TOKEN", "METACOG_ANCHOR_INIT_TOKEN_EXPECTED"):
        _audit_log("anchor-init", "REFUSED", "token missing/mismatch")
        print("[REFUSED] anchor-init 被拒绝：缺少/错误的授权令牌"
              "（METACOG_ANCHOR_INIT_TOKEN 与 METACOG_ANCHOR_INIT_TOKEN_EXPECTED 须成对提供且一致）。"
              "anchor-init 为特权恢复操作，非日常路径；日常 record() 已自动维护树外锚点。")
        return 2
    if not FREEZE_FILE.exists():
        print("[FAIL] anchor-init 失败：账本不存在，请先 record。")
        _audit_log("anchor-init", "FAIL", "ledger-missing")
        return 1
    lines = _load_lines()
    if not lines:
        print("[FAIL] anchor-init 失败：账本为空（0 条冻结记录），无约束可锚定。")
        _audit_log("anchor-init", "FAIL", "ledger-empty")
        return 1
    ok, viol, _ = _parse_chain(lines)
    if not ok:
        print("[FAIL] anchor-init 失败：账本校验未通过，拒绝为损坏账本建立锚点。")
        for v in viol:
            print("  - " + v)
        _audit_log("anchor-init", "FAIL", "ledger-invalid")
        return 1
    try:
        _write_anchor()
    except Exception as ex:
        print("[FAIL] anchor-init 失败：无法写入树外锚点（{}）。".format(ex))
        _audit_log("anchor-init", "FAIL", "anchor-write-failed:{}".format(ex))
        return 1
    # 同步刷新安装标记
    _write_marker()
    print("[OK] 已写入树外锚点：{}".format(_anchor_write_path()))
    _audit_log("anchor-init", "OK", "rebuilt")
    return 0


def main():
    ap = argparse.ArgumentParser(description="v2.15.0 冻结清单（append-only + HMAC 链 + 树外锚点 + 写前校验 + 特权恢复门禁）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("record", help="追加冻结条目（写前门禁校验）")
    rp.add_argument("paths", nargs="+", help="相对技能根的路径")
    vp = sub.add_parser("verify", help="校验冻结完整性 + 树外锚点")
    ap2 = sub.add_parser("anchor-init", help="特权恢复：重建树外锚点（需 METACOG_ANCHOR_INIT_TOKEN）")
    args = ap.parse_args()
    if args.cmd == "record":
        rc = record(args.paths)
        return 0 if rc >= 0 else 1
    if args.cmd == "verify":
        ok, viol = verify()
        if ok:
            # v2.27.15（M-03/§四.2 收口）：ALLOW_MISSING 跳过校验时不得谎报「树外锚点匹配」——
            # 该绿灯曾被写成官方复验口径而未披露「锚点校验被跳过」，对读者而言假绿灯比不写更危险。
            _allow_missing = os.environ.get("METACOG_FREEZE_ALLOW_MISSING") == "1"
            _ledger_missing = not FREEZE_FILE.exists()
            _anchor_missing = _read_anchor() is None
            if _allow_missing and (_ledger_missing or _anchor_missing):
                _skipped = []
                if _ledger_missing:
                    _skipped.append("冻结账本(ledger)缺失、未校验")
                if _anchor_missing:
                    _skipped.append("树外锚点缺失、未校验")
                _ledger_part = "ledger 完整" if not _ledger_missing else "账本缺失（未校验，不声称完整）"
                print("[OK*] 冻结文件未漂移（{}）；但{}，已按 METACOG_FREEZE_ALLOW_MISSING=1 跳过对应校验——"
                      "本输出不构成完整锚/账本完整性证据。".format(_ledger_part, "、".join(_skipped)))
            else:
                print("[OK] 冻结校验通过：所有冻结文件未漂移，ledger 完整，树外锚点匹配。")
            return 0
        print("[FAIL] 冻结校验失败：")
        for v in viol:
            print("  - " + v)
        return 1
    if args.cmd == "anchor-init":
        return anchor_init()
    return 2


if __name__ == "__main__":
    sys.exit(main())
