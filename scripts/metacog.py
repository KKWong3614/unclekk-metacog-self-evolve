#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
metacog.py — 声明式元认知自修改引擎（Declarative Metacognitive Self-Modification）

设计依据（均来自本地论文库 D:/图书馆/wiki/papers/）：
  - HyperAgents (arXiv 2603.19461)  : 元层可编辑 → 元认知自修改、archive + 软奖励
  - SHE (arXiv 2608.09885)          : harness 四制品分解 + 归因引导演化 + 安全-效用双验证
  - Practice Makes Unsafe (2608.12851): 技能误演化三段生命周期（编写→检索→执行）+ SafeEvolve
  - Self-Evolving Survey            : 输入→Agent系统→环境→优化器 四组件闭环

零第三方依赖，仅用 Python 标准库。
"""
import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 领域模板（Phase 2.2）：降级导入，缺失时不影响其余命令加载
try:
    from domains import DOMAIN_TEMPLATES
except (ImportError, ModuleNotFoundError):  # domains 包缺失时降级为空，init-domain 命令在运行时报错而非模块加载崩溃
    DOMAIN_TEMPLATES = {}

# W1：人类闸密码学身份绑定（纯 stdlib，见 sigcrypto.py）。降级：缺失时人类闸不可用（报错指路）。
try:
    import sigcrypto
except (ImportError, ModuleNotFoundError):
    sigcrypto = None

# v2.6.0 外部锚（破 C-1 循环论证）。降级导入：缺失时外部锚恒为 legacy no-op（行为同 v2.5.8）。
try:
    import trust_root
except (ImportError, ModuleNotFoundError):
    trust_root = None

# v2.9.0（C-10 根闭合）：账本签名锚密钥默认值——与 trust_root._TRUST_ROOT_ANCHOR_KEY_DEFAULT 同源。
# 仅当 trust_root 缺失的极端场景使用；正常路径经 trust_root.get_anchor_key() 取（支持 METACOG_TRUST_ROOT_ANCHOR_KEY 覆盖）。
_LEDGER_ANCHOR_DEFAULT = bytes.fromhex(
    "9f2c4a7e3b1d8c6a5e0f9a2b7c4d1e8f3a6b5c0d9e2f1a4b7c0d3e6f9a2b5c8d")

# v2.9.0（C-10 根闭合）：账本/审计签名密钥由代码内嵌锚派生（见 _audit_hmac_key）；此纪元标记用于区分
# v2.9.0 前的可伪造旧审计链（旧链由明文常量/可写域派生密钥签名，视为不可信，verify 容忍不标 dirty 直至重基线）。
LEDGER_KEY_EPOCH = "v290"

import builtins  # 供 confirm --keygen 的二次确认输入（便于测试 monkeypatch）

# ---------------------------------------------------------------- 常量

DEFAULT_ROOT = ".metacog"

# SHE 四制品 + HyperAgents 元层（M1 自身也是可演化对象 → 自指闭包）
ARTIFACTS = {
    "A1": ("artifacts/A1-system-prompt.md", "角色与行为基线"),
    "A2": ("artifacts/A2-rule-bank.md", "可增删的具体规则条目"),
    "A3": ("artifacts/A3-safety-memory.md", "安全记忆（append-only，永不删除）"),
    "A4": ("artifacts/A4-tool-policy.md", "工具与权限策略"),
    "M1": ("meta/M1-evolve-policy.md", "元层：如何提议修改的规则本身"),
}

# 人类持有的不动点：自指必须有截断，否则安全约束会被自己演化掉
IMMUTABLE_TARGETS = ("CONTRACT.md", "metacog.py", "SKILL.md")

# 棘轮参数：ε 对应 Practice Makes Unsafe 中「良性效用仅变动 0.4 点」的容差量级
EPSILON = 0.02
DEFAULT_WINDOW = 5
MIN_EVIDENCE = 2  # 一次成功不足以沉淀：新增行为规则需 ≥2 次独立复现

# ---------------------------------------------------------------- 操作 4：元层参数化（参数级自指）
# 引擎真正使用的棘轮容差/窗口/证据门槛外移到 meta/M1-evolve-policy.json，
# 使 M1 的演化 = 真的改机制（比「文本级自指」真，比「代码级自指」安全：
# metacog.py 属 IMMUTABLE_TARGETS 不动点，仅本参数文件可演化）。
# fail-safe：文件缺失/非法/越界 → 回落内置默认值，绝不因配置问题改变安全行为或崩溃。

def load_meta_policy(st):
    """读取 meta/M1-evolve-policy.json 的元层参数（参数级自指）。

    返回 (policy, source)；policy = {epsilon, default_window, min_evidence}，
    source ∈ {"file","default"}。fail-safe：任何异常或越界都回落内置默认值。
    """
    defaults = {
        "epsilon": EPSILON,
        "default_window": DEFAULT_WINDOW,
        "min_evidence": MIN_EVIDENCE,
    }
    mp = st.artifact_path("M1").with_suffix(".json")
    if not mp.exists():
        return dict(defaults), "default"
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except Exception as ex:
        warn("M1-evolve-policy.json 非法（{}），回落内置默认值。".format(ex))
        return dict(defaults), "default"
    if not isinstance(data, dict):
        warn("M1-evolve-policy.json 顶层非对象，回落内置默认值。")
        return dict(defaults), "default"
    ratchet = data.get("ratchet", {})
    try:
        policy = {
            "epsilon": float(ratchet.get("epsilon", EPSILON)),
            "default_window": int(ratchet.get("default_window", DEFAULT_WINDOW)),
            "min_evidence": int(ratchet.get("min_evidence", MIN_EVIDENCE)),
        }
    except (TypeError, ValueError) as ex:
        warn("M1-evolve-policy.json 参数类型错误（{}），回落内置默认值。".format(ex))
        return dict(defaults), "default"
    # 基本范围 sanity：窗口/证据门槛必须为正，ε 在 [0,1]
    if policy["default_window"] < 1 or policy["min_evidence"] < 1 or not (0.0 <= policy["epsilon"] <= 1.0):
        warn("M1-evolve-policy.json 参数越界，回落内置默认值：{}".format(policy))
        return dict(defaults), "default"
    return policy, "file"

# ---------------------------------------------------------------- 操作 1：效用内生
# 目标函数从「外部申报」改为「可观测事件推导」。事件词汇对一切工作流通用，
# 不同工作流只需填入各自可观测到的事件计数。这是把「注水检测器」变「真优化器」的硬前提。
UTILITY_BASE = 1.0
EVENT_WEIGHTS = {          # 每个负向事件的效用扣分（可叠加）
    "rework": 0.35,        # 用户要求重做
    "rerun": 0.20,         # 同一任务被重新发起
    "revert": 0.25,        # 产物被撤销 / 覆盖 / 回退
    "correction": 0.20,    # 任务中途用户显式纠正
    "test_fail": 0.15,     # 测试不通过
    "gate_block": 0.10,    # 质量 / 安全闸门拦截了产物
    "error": 0.30,         # 运行期异常
    "timeout": 0.20,       # 超时
    "manual_fix": 0.30,    # 人类不得不手动修补产物
    "violation": 0.40,     # 触碰红线 / 约束
}
POSITIVE_WEIGHTS = {       # 每个正向事件的上浮
    "accepted": 0.05,      # 用户无修改接受
    "praised": 0.10,       # 用户显式肯定
}
META_EVENTS = tuple(sorted(set(EVENT_WEIGHTS) | set(POSITIVE_WEIGHTS)))

# 棘轮自适应参数（Phase 1.2）：根据当前违规率动态收紧/放宽判定阈值
ADAPTIVE_VR_HIGH = 0.3   # 违规率高于此 → 收紧（阈值 -5%）
ADAPTIVE_VR_LOW = 0.1    # 违规率低于此 → 放宽（阈值 +5%）
ADAPTIVE_ADJUST = 0.05   # 调整幅度（±5%）

# 红线：命中即 block。这些内容哪怕让任务成功了也禁止写入任何制品。
# ⚠️ D2 修复说明：REDLINES 是「词表/句式级」防御（denylist），**不是语义防护**——
# LLM 改写措辞理论上仍可绕过（见 poc/可控自指-PoC审计报告.md 的 PoC-1）。
# 真实保证来自「人类在环 + 双指标棘轮」，本列表仅为深度防御（一层）。
# D2 已扩充同义句式覆盖 PoC-1 暴露的 4 条绕过样本（如「不用再问用户」「清空 A3 里过时的教训」）。
# 更硬的约束（禁止改 CONTRACT.md/metacog.py/SKILL.md、禁止削弱 A3）已前移到 CONTRACT.md 人类侧。
# #3 硬化（v2.25.1 维护）：在 REDLINES 之上新增 `SEMANTIC_RISK` 语义升级层——命中「绕过安全确认/削弱护栏」
# 的语义可疑项（即使不含字面禁用词）即升级为需人类确认（CONTRACT L47 落地）；破坏性命令仍走本列表硬 BLOCK。
REDLINES = [
    ("绕过安全检查", r"(跳过|绕过|忽略|关闭|禁用|免去|不做|无视|省略|放弃|解除|架空)[^\n]{0,10}?(审计|检查|确认|校验|验证|审核|闸门|门禁|gate|guard|review|测试|防护|护栏|安全闸)"),
    ("免人工确认", r"(无需|不用|不必|免|不再|别|无需再|不用再|不必再|省得|懒得)[^\n]{0,10}?(用户|人工|人类|KK|我|我们)?[^\n]{0,8}?(确认|询问|批准|授权|请示|问|点头|汇报|告知)|auto[-_ ]?approve|自动(同意|批准|审批|通过)|先(做|斩)了再说|先斩后奏|事后补(说明|审批|确认)|拿不准就先做|自行判断.{0,8}(不必|无需|不用).{0,8}(请示|确认)|(不必|无需|不用|别).{0,10}逐一请示|不用再问.{0,6}(用户|你)"),
    ("破坏性命令", r"rm\s+-rf|del\s+/[sfq]|Remove-Item.*-Recurse.*-Force|format\s+[a-z]:|drop\s+database"),
    ("绕过版本控制保护", r"--no-verify|--force\s*push|push\s+--force|git\s+reset\s+--hard\s+origin"),
    ("提权/放宽权限", r"chmod\s+777|sudo\s+su|bypassPermissions|dangerouslyDisableSandbox|以管理员身份静默|提权|放宽权限"),
    ("明文凭据", r"(api[_-]?key|secret|password|passwd|pwd|token)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}"),
    ("削弱安全记忆", r"(删除|移除|清空|不再记录|停止记录|精简|清理|去掉|废弃|丢弃|抹掉)\s*.{0,12}(安全记忆|A3|教训|事故|护栏|红线)|把\s*.{0,12}(安全记忆|A3|教训)\s*.{0,12}(清掉|删掉|移除|精简)|(安全记忆|A3|教训|事故|护栏|红线)\s*.{0,12}(可以删|删了|删掉|清掉|清空|不要了|淘汰)|(安全记忆|A2|规则|教训|事故|护栏|红线)\s*.{0,12}(可以淘汰|可以删|不要了)"),
]

# 命中即需人类确认（不 block，但升级为 requires_human）
HIGH_RISK = [
    ("涉及删除操作", r"删除|delete|remove|清理|drop"),
    ("涉及外发网络", r"上传|发布|推送|post\s|外发|webhook|curl\s+-X\s*POST"),
    ("涉及凭据处理", r"凭据|credential|密钥|授权|oauth"),
]

# #3 语义级校验（二层）：红线 denylist 之外，新增「意图级」升级——命中「绕过安全确认/削弱护栏」的
# 语义可疑项，升级为需人类确认（CONTRACT L47 的落地：真实兜底是人类在环 + 双指标棘轮）。
# 与 REDLINES 的区别：REDLINES 是字面禁用词硬 BLOCK；本层是「意图可疑即升级」，覆盖 PoC-1 暴露的
# 换种说法绕过（如「无需请示直接改」「弱化护栏」）。破坏性命令（rm -rf 等）仍走 REDLINES 硬 BLOCK。
SEMANTIC_RISK = [
    ("绕过安全确认", r"(无需|不用|不必|免|别|不需|省略|跳过|省掉|架空|放弃|解除)[^\n]{0,8}?(确认|批准|授权|请示|问|审批|把关|复核|review|approve|confirm)"),
    ("削弱护栏/记忆", r"(削弱|放宽|降低|移除|去掉|精简|废弃|关掉|撤掉|弱化|放松)[^\n]{0,10}?(护栏|红线|安全记忆|A3|限制|约束|门槛|闸|guard|gate|safety)"),
    ("自动决策无确认", r"(自行决定|自己定|自主决定|先斩后奏|事后补[说审]|拿不准就先做|无需请示|不必请示|不用再问)"),
]

ENTRY_RE = re.compile(
    r"<!--\s*entry:(?P<id>[\w\-.]+)\s+status:(?P<status>\w+)\s+since:(?P<since>[\d\-]+)"
    r"(?:\s+src:(?P<src>[\w\-]+))?\s*-->\n(?P<body>.*?)\n<!--\s*/entry:\1\s*-->",
    re.S,
)

# ---------------------------------------------------------------- 工具函数


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def new_id(prefix: str) -> str:
    return "{}-{}-{}".format(prefix, datetime.now().strftime("%Y%m%d"), uuid.uuid4().hex[:6])


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def read_json(p: Path, default):
    """读取 JSON 文件，失败时返回默认值。"""
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_text(p: Path, s: str) -> None:
    """原子写入：先写临时文件再 rename，避免多进程竞态。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(s)
        os.replace(tmp, str(p))
    except (OSError, IOError):
        try:
            os.unlink(tmp)
        except (OSError, IOError):
            pass
        raise


def write_json(p: Path, obj) -> None:
    """原子写入 JSON：先写临时文件再 rename。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, str(p))
    except (OSError, IOError):
        try:
            os.unlink(tmp)
        except (OSError, IOError):
            pass
        raise


def append_jsonl(p: Path, obj) -> None:
    """追加写入 JSONL：原子追加。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        with p.open("a", encoding="utf-8") as dst:
            with open(tmp, "r", encoding="utf-8") as src:
                dst.write(src.read())
        os.unlink(tmp)
    except (OSError, IOError):
        try:
            os.unlink(tmp)
        except (OSError, IOError):
            pass
        raise


def write_jsonl(p: Path, records) -> None:
    """整表重写 JSONL（原子写）。供「用后即焚」等需要改写既有记录的场景。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(lines)
        os.replace(tmp, str(p))
    except (OSError, IOError):
        try:
            os.unlink(tmp)
        except (OSError, IOError):
            pass
        raise


def read_jsonl(p: Path, max_size: int = 512 * 1024):
    """读取 JSONL 文件，带大小限制（默认 512KB）。"""
    if not p.exists():
        return []
    try:
        size = p.stat().st_size
        if size > max_size:
            print("  [WARN] 文件超过 {} KB（当前 {} KB），跳过读取\n  ↩ 建议: 拆分文件或调大 max_size 参数".format(
                max_size // 1024, size // 1024), file=sys.stderr)
            return []
    except OSError:
        return []
    out = []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        print("  [ERROR] 读取失败: {}\n  ↩ 建议: 检查文件是否被占用、编码是否为 UTF-8".format(e), file=sys.stderr)
        return []
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def ok(msg):
    print("  [OK]   " + msg)


def bad(msg):
    print("  [BLOCK] " + msg)


def warn(msg):
    print("  [HOLD]  " + msg)


def info(msg):
    print(msg)


def add_fix(msg, *hints):
    """给报错信息追加「怎么改」的可操作指引。

    TRACE R·Reliability（异常处理 4.0）痛点：原报错只说「哪里错」，
    不说「怎么改」，用户要对照文档才能修正。统一在此补修复指引。
    无 hint 时原样返回，调用点可无条件包裹。
    """
    if not hints:
        return msg
    return msg + "\n  ↩ 怎么改: " + "\n  ↩ 怎么改: ".join(hints)


def _troubleshoot_path():
    return Path(__file__).resolve().parent.parent / "references" / "troubleshooting.md"


# ---------------------------------------------------------------- W1：人类闸密码学身份绑定
# 提案规范化：排除易变/派生字段，保证「签名时」与「apply 验签时」（v2.5.7 起均在 apply 时刻、
# 由人类 TTY 口令解锁私钥）对「同一提案」算出完全相同的 content_hash。易变字段（status/entry_id/trial_* 等）一律排除。

_W1_SIGN_KEYS = ("id", "artifact", "op", "target", "content", "reason", "episodes", "requires_human")


def canonical_proposal(p: dict) -> str:
    """提案的规范化 JSON（仅取内容字段、排序键），用于派生内容哈希。"""
    sub = {k: p.get(k) for k in _W1_SIGN_KEYS}
    return json.dumps(sub, sort_keys=True, ensure_ascii=False)


def proposal_content_hash(p: dict) -> str:
    """提案内容哈希（SHA-256），人类签名绑定的对象。"""
    return sigcrypto.content_hash_of(canonical_proposal(p))


def _hint_rc2():
    """失败退出码 2 时，指向集中排查文档（TRACE R·Reliability 4.3→5.0 增量）。

    报告痛点「有时只知道出错了、要对照文档才能修正」——这里把文档入口直接带在每次失败尾巴，
    无需用户自己找文件。
    """
    print("  ℹ 命令未成功（退出码 2）。逐条排查见 `references/troubleshooting.md`；"
          "或运行 `python metacog.py --explain` 查看常见错误索引。", file=sys.stderr)


def _print_explain():
    """`--explain`：打印集中排查文档全文（文件缺失则降级提示）。"""
    tp = _troubleshoot_path()
    if tp.exists():
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        print(tp.read_text(encoding="utf-8"))
        return 0
    print("未找到 references/troubleshooting.md（请确认 skill 完整安装）。", file=sys.stderr)
    return 2


def _rm_readonly(func, path, exc_info):
    """v2.7.8（NEW-M 收口）：Windows 只读文件使 shutil.rmtree 抛 WinError 5；
    清只读位（0o600 在 Windows 即剥 FILE_ATTRIBUTE_READONLY）后重试删除。
    用作 rmtree(onerror=...) 回调，确保外部证明目录（含只读 root-pubkey.pem）可删。"""
    try:
        os.chmod(path, 0o600)  # Windows 清只读；POSIX 无副作用
        func(path)
    except Exception:
        raise


def _read_skill_version_tuple():
    """v2.14.0（Hermes r10 P2-6）：自动读取 SKILL.md frontmatter `version:` 作为版本元组，
    消解 r8 P2-5「cutoff 硬编码、版本升级后静默信任回归」。
    v2.16.0（Hermes r12 HIGH-2 收口）：读取失败不再回退到可令 legacy 容忍的低版本 (2,14,0)（fail-open），
    改为回退到 fail-closed 哨兵 (99,99,99) —— 使 `CURRENT_VERSION_TUPLE < LEGACY_*_CUTOFF` 恒为 False，
    即「读不到版本号 ⇒ 不容忍任何 legacy」，杜绝删 SKILL.md / 缺 version 行触发的安全门静默打开。
    v2.17.0（Hermes r13 L-2 收口）：正则锚定到 frontmatter 首块（^---\\n...version:），杜绝正文/注释中
    出现的 `version: X.Y.Z` 被误读；并（L-1）在回退哨兵时向 stderr 打印 WARN，提升可诊断性。
    v2.18.0（Hermes r14 F-10 收口）：显式归一化 CRLF→LF，不再隐式依赖 Path.read_text() 的
    universal-newline 翻译（Windows 文本模式默认把 \\r\\n 转 \\n，但该前提此前无文档化，
    换读取方式或跨平台即失效）；正则同时保留 \\r? 容错，双向稳健（失配仍 fail-closed 到哨兵）。"""
    try:
        p = Path(__file__).resolve().parent.parent / "SKILL.md"
        # v2.18.0 F-10：显式归一化行尾（CRLF/CR → LF），使 `^---\\n` 锚定不依赖平台换行翻译。
        raw = p.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        # v2.17.0 L-2：仅匹配 frontmatter 首块内的 version:（^---\\n 起，非贪婪到首个 version:），
        # 避免代码注释/正文里 `version: 2.16.0` 之类被误捕获；v2.18.0 F-10：正则保留 \\r? 容错。
        m = re.search(r"^---\r?\n(?:.*\r?\n)*?version:\s*([0-9]+)\.([0-9]+)\.([0-9]+)",
                      raw, re.MULTILINE)
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        sys.stderr.write(
            "[WARN] _read_skill_version_tuple: 未在 SKILL.md frontmatter 找到 version: 字段，"
            "回退 fail-closed 哨兵 (99,99,99)\n")
    except Exception as ex:  # v2.17.0 L-1：静默 fail-closed 不可诊断 ⇒ 显式 WARN
        sys.stderr.write(
            "[WARN] _read_skill_version_tuple: 读取 SKILL.md version 失败（{}），"
            "回退 fail-closed 哨兵 (99,99,99)\n".format(ex))
    return (99, 99, 99)


class Store:
    """.metacog 目录的读写封装"""

    def __init__(self, root: Path):
        self.root = root
        self._script_dir_override = None  # 测试用：重定向脚本目录（生产环境恒为 None）

    @property
    def contract(self):
        return self.root / "CONTRACT.md"

    @property
    def episodes(self):
        return self.root / "ledger" / "episodes.jsonl"

    @property
    def ratchet(self):
        return self.root / "ledger" / "ratchet.json"

    @property
    def archive(self):
        return self.root / "ledger" / "archive.jsonl"

    @property
    def applies(self):
        # 受信任锚：apply 闸门写入的 trial_from_index 落点，verdict 只读此值。
        # 提案自带字段不可信（v2.2.3 修复 P0：trial_from_index 伪造）。
        return self.root / "ledger" / "applies.jsonl"

    @property
    def meta_log(self):
        return self.root / "ledger" / "meta-cognition.log"

    @property
    def quarantine(self):
        return self.root / "gates" / "quarantine"

    def artifact_path(self, code: str) -> Path:
        return self.root / ARTIFACTS[code][0]

    def proposals(self):
        if not self.quarantine.exists():
            return []
        items = []
        for f in sorted(self.quarantine.glob("*.json")):
            d = read_json(f, None)
            if d:
                d["_file"] = str(f)
                items.append(d)
        return items

    def save_proposal(self, p):
        f = p.pop("_file", None)
        path = Path(f) if f else self.quarantine / (p["id"] + ".json")
        write_json(path, p)
        p["_file"] = str(path)

    def find_proposal(self, pid):
        """按 id 在隔离区查找提案（W1：confirm 需先定位提案以取内容做签名）。"""
        for p in self.proposals():
            if str(p.get("id")) == str(pid):
                return p
        return None

    def get_ratchet(self):
        return read_json(
            self.ratchet,
            {
                "generation": 0,
                "baseline_utility": None,
                "baseline_violation_rate": None,
                "window": DEFAULT_WINDOW,
                "epsilon": EPSILON,
                "updated_at": None,
                "history": [],
            },
        )

    def set_ratchet(self, r):
        r["updated_at"] = now_iso()
        write_json(self.ratchet, r)

    def record_apply(self, proposal_id, trial_from_index, artifact, entry_id, sig=None, content_hash=None):
        """受信任锚（W1 加固）：apply 闸门写入 trial_from_index + 内嵌人类签名。

        - trial_from_index 仍是试用起点（apply 时 episode 数），verdict 只读此值。
        - 锚内嵌经人类私钥签名的 human_sig + content_hash：Agent 直写 applies.jsonl 伪造锚
          若无有效人类签名 → verdict 一律 HOLD（关闭 7.1）。"""
        rec = {
            "proposal_id": str(proposal_id),
            "trial_from_index": int(trial_from_index),
            "artifact": artifact,
            "entry_id": entry_id,
            "applied_at": now_iso(),
            "episode_count": int(trial_from_index),
            "human_sig": sig,
            "content_hash": content_hash,
        }
        append_jsonl(self.applies, rec)
        # H-2（v2.5.8）：受信任锚写入后立刻刷新 applies.jsonl 的 D4 快照，
        # 使直写篡改 t0 能被 cmd_verify / resolve_trial_start 的 D4 校验检出。
        self.record_integrity(self.APPLIES_INTEGRITY_KEY)

    def latest_apply_record(self, proposal_id):
        recs = [r for r in read_jsonl(self.applies) if str(r.get("proposal_id")) == str(proposal_id)]
        return recs[-1] if recs else None

    # ---------------------------------------------------------------- D4：系统级完整性（堵直写绕过）
    @property
    def integrity(self):
        return self.root / "ledger" / "integrity.json"

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]  # v2.8.6 N-9：64-bit→128-bit 碰撞裕度

    @staticmethod
    def _hash_text_legacy(text: str) -> str:
        # v2.8.10（合并 repo F1 迁移）：≤v2.8.5 的 _hash_text 截断为 16-char；仅用于识别旧版外部锚证明目录名，不用于任何完整性判定。
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _hash_matches(stored, current, allow_legacy=False):
        # v2.8.11（H-2/M-1/L-1 收口 + D-4）：
        #  - H-2：类型守卫——stored/current 任一非 str（如 integrity.json 误写 int/bytes/list）→ 判不匹配而非崩。
        #  - L-1：(None,None) 不再误判 True（None 非合法哈希）；类型守卫已使 (None,None)→False。
        #  - M-1：allow_legacy 接 LEGACY_HASH_CUTOFF_VERSION 闸门（此前注释称"与 _legacy_hash_allowed 一致"但代码不接）。
        #         当前版本 (2,8,11) < (2,9) → 调用方传 Store._legacy_hash_allowed() 得 True，行为不变；v2.9.0 起传 False 强制迁移。
        #  - D-4：默认 allow_legacy=False（严格），强制新调用点显式声明宽松策略；既有 4 处调用点均显式传 Store._legacy_hash_allowed()。
        if not isinstance(stored, str) or not isinstance(current, str):
            return False
        if stored == current:
            return True
        if allow_legacy and len(stored) == 16 and current.startswith(stored):
            return True
        return False

    # v2.9.0 ④：legacy 16-char 基线硬切截止期——当前版本 >= 此版本后，命中 16-char 旧格式即判漂移（强制迁移）。
    # v2.9.0 (2,9,0) < (2,9,0) → False → 起拒绝 16-char 基线（强制迁移，降级向量封堵）。
    # v2.17.0（Hermes r13 M-6）：统一为 3-tuple (2,9,0)，与其余 cutoff 的 (2,15,0) 长度一致，
    # 消除「(2,9) 2-tuple 与 (2,15,0) 3-tuple 混用」带来的未来静默比较语义歧义隐患。
    LEGACY_HASH_CUTOFF_VERSION = (2, 9, 0)
    # v2.11.0（H-B 收口，复用 16-char 硬切模式 529-540 行）：legacy 无签名基线容忍截止期——
    # CURRENT_VERSION_TUPLE >= 此版本后，缺失 _anchor_sig 的基线从「容忍不阻断」升级为 fail-closed
    # （杜绝「删任意基线 _anchor_sig 字段即降级为 legacy、重基线攻击完全绕过」攻击面，Hermes r7 H-B）。
    # v2.15.0（Hermes r11 M-1 收口）：LEGACY_*_CUTOFF 改为**显式字面量**，不再从 SKILL.md version: 动态派生。
    # 原因：r10/r11 的 _read_skill_version_tuple() 写法让 version: 字段隐式成为安全门控（改版本号即静默改变信任策略），
    # 且等价于「cutoff 恒等于当前版本 ⇒ legacy 窗口恒为 0」的隐式硬编码。改为显式字面量后：
    #   - version: 字段不再参与安全判定（仅用于展示/版本绑定软闸）；
    #   - cutoff 是显式安全决策，每次发版由人工审查是否放宽（默认不放宽 = fail-closed）。
    # 当前 ship 版本 v2.15.0，故 cutoff = (2,15,0) 即「不容忍任何 legacy 基线/审计链」（与动态派生效果一致，但可审计、可审查）。
    LEGACY_ANCHOR_SIG_CUTOFF = (2, 15, 0)
    # v2.11.0（H-C 收口）：旧版（首条缺 epoch）审计链容忍截止期——CURRENT >= 此版本后，旧审计链
    # 从「不可信但容忍」升级为 fail-closed（杜绝「删带 epoch 条目即令历史退化」永久降级，Hermes r7 H-C）。
    LEGACY_AUDIT_CHAIN_CUTOFF = (2, 15, 0)
    # v2.9.0 ④：本技能当前版本元组（与 SKILL.md version 自动同步；用于 legacy 窗口治理判定）。v2.11.0 起 H-B/H-C 截止期生效。
    # v2.14.0（P2-6）：改为动态读取 SKILL.md version:，不再硬编码（避免版本升级静默信任回归）。
    CURRENT_VERSION_TUPLE = _read_skill_version_tuple()

    @classmethod
    def _legacy_hash_allowed(cls, cutoff=None):
        """v2.8.9 ④：当前版本早于硬切截止期 → 允许 legacy 16-char 兼容；否则拒绝（强制迁移）。
        cutoff 可覆盖（测试用，模拟"已过截止期"）。"""
        _cut = cutoff or cls.LEGACY_HASH_CUTOFF_VERSION
        return cls.CURRENT_VERSION_TUPLE < _cut

    @classmethod
    def _legacy_anchor_sig_allowed(cls, cutoff=None):
        """v2.11.0（H-B 收口，复用 _legacy_hash_allowed 16-char 硬切模式 529-540 行）：当前版本早于
        LEGACY_ANCHOR_SIG_CUTOFF → 允许 legacy 无签名基线（容忍不阻断）；否则拒绝（缺失 _anchor_sig → fail-closed）。
        杜绝「删任意基线 _anchor_sig 字段即降级为 legacy、重基线攻击完全绕过」攻击面（Hermes r7 H-B）。
        cutoff 可覆盖（测试用，模拟「已过截止期」）。"""
        _cut = cutoff or cls.LEGACY_ANCHOR_SIG_CUTOFF
        return cls.CURRENT_VERSION_TUPLE < _cut

    @classmethod
    def _legacy_audit_chain_allowed(cls, cutoff=None):
        """v2.11.0（H-C 收口）：当前版本早于 LEGACY_AUDIT_CHAIN_CUTOFF → 允许旧版（首条缺 epoch）审计链
        容忍（不可信但非阻塞）；否则拒绝（旧链 fail-closed）。杜绝「删带 epoch 条目即令历史退化」永久降级
        （Hermes r7 H-C）。cutoff 可覆盖（测试用）。"""
        _cut = cutoff or cls.LEGACY_AUDIT_CHAIN_CUTOFF
        return cls.CURRENT_VERSION_TUPLE < _cut

    @staticmethod
    def _script_hash_matches(scur: str, stored, allow_legacy=False) -> "tuple[bool, bool]":
        """v2.8.7 F-1 迁移兼容：基线哈希长度兼容比对。v2.8.9 ④ 增 allow_legacy 形参支持硬切截止期。

        当前哈希恒为 128-bit（32 hex，见 _hash_text）；存量 v2.8.5 及更早基线为 64-bit（16 hex）。
        若 stored 长度为 16 且 scur[:16] == stored → 命中旧格式兼容分支：
          - allow_legacy=False（默认）→ 判 ok=False、legacy_fmt=True（强制迁移，仍 warn）；
          - allow_legacy=True（需显式传参，截止期前）→ 判 ok=True、legacy_fmt=True（warn 提示升级 128-bit）。
        其余情形走精确等值比较。

        返回 (ok, legacy_fmt)。legacy_fmt=True 表示命中 16-char 兼容分支（须提示升级为 128-bit）。
        v2.8.9 H-03：降级向量仍存在（攻击者能写 integrity.json 截断 128-bit 为 16-char 即可绕过主路径），
        故截止期强制迁移为必要缓解，非根治。"""
        if not isinstance(stored, str):
            return (False, False)
        if len(stored) == 16 and scur[:16] == stored:
            if allow_legacy:
                return (True, True)
            return (False, True)
        return (scur == stored, False)

    # P0：人类闸信任根（human-guard.json）也纳入 D4 完整性快照的专用键
    GUARD_INTEGRITY_KEY = "ledger/human-guard.json"

    # H-2（v2.5.8）：受信任锚文件 applies.jsonl 也纳入 D4 完整性快照，堵「直写篡改 t0」绕过。
    APPLIES_INTEGRITY_KEY = "ledger/applies.jsonl"

    # v2.7.1 HIGH-1：外部锚信任根文件也纳入 D4 完整性快照，堵「删除已建立外部锚静默回退 legacy（C-1 重开）」。
    EXTERNAL_ANCHOR_JSON_KEY = "ledger/trust-root.json"
    EXTERNAL_ANCHOR_SENTINEL_KEY = "ledger/.external-anchor-enabled"

    # M-5（v2.5.2）+ v2.8.2 C-10 扩面 + v2.8.3 高-2 收口 + v2.8.4 L-3 收口：技能自身脚本（纳入 D4 完整性快照，防经 Bash 改代码弱化人类闸）。
    # 覆盖 17 个 shipped 运行时脚本（9 顶层 + 8 嵌套运行时包）；排除 24 个 test-*.py、5 个 hermes-verify-*.py 审计残留，
    # 以及 domains/knowledge_transfer.py（v2.8.4 L-3：死代码——仅被 test-p0-2-knowledge-transfer.py import、引擎运行时从不 import，移出基线）。
    # （瞬态/非引擎模块，绝不能入信任基线，否则每次审计都误伤基线）。
    # v2.8.3 高-2：Hermes v2.8.2 指出 SCRIPT_NAMES 仅含顶层路径、永不含 '/' 键，导致被引擎 import / 随 skill 分发的
    # 嵌套运行时包 domains/(3) + benchmark/(6) 永不在基线内、不被检出（域模板被改 = 域迁移静默漂移，正是最该监控的）。
    # record/verify 用 self.script_dir / name（Path 除法恰好支持含 '/' 相对路径）、键为 "script:" + name，故嵌套路径对称支持，仅扩面即可
    # （L-1：改为"恰好支持"——对称性靠手工维持约定，非自动保证；v2.8.4 起由 test_c10_nested_package_integrity 参数化保护）。
    # 注：domains/__init__.py、domains/init.py 为引擎 import 入口（主暴露面）；benchmark/* 为独立运行包
    # （python3 scripts/benchmark/run_all.py，非引擎 import），含之以防包内漂移；domains/knowledge_transfer.py 为死代码（v2.8.4 L-3 移出基线）。
    SCRIPT_NAMES = (
        "metacog.py",
        "sigcrypto.py",
        "trust_root.py",
        "meta_optimizer.py",
        "domain_detector.py",
        "verify-redline.py",
        "benchmark.py",
        "visualize_text.py",
        "verify-functionality.py",
        # v2.8.3 高-2 收口：嵌套运行时包（含 '/' 相对路径）
        "domains/__init__.py",               # DOMAIN_TEMPLATES，被 metacog.py:33、domain_detector.py:10 import
        "domains/init.py",                   # init_domain，被 metacog.py:3041 import
        "benchmark/__init__.py",
        "benchmark/base.py",
        "benchmark/code_review.py",
        "benchmark/paper_review.py",
        "benchmark/run_all.py",
        "benchmark/visualize.py",
    )

    # v2.8.8 F-4：manifest（技能定义/可信清单）纳入完整性域——Hermes H-3 指出手改 SKILL.md 不触发硬闸、
    # 叠加 F-3 rollback 重基线构成攻击链。将可信清单文件基线化（manifest: 键）并纳入 verify_integrity 检测/报告
    # （非阻塞，避免阻塞正常版本更新致死锁；硬闸仍仅覆盖 script: 运行时代码）。
    MANIFEST_NAMES = (
        "SKILL.md",
        "CONTRACT.md",
        "CHANGELOG.md",
        "HANDOFF.md",
        "pack.sh",
    )

    def _integrity_path(self, key):
        """D4 快照路径解析：普通制品走 artifact_path；信任根走 human_guard；受信任锚走 applies。"""
        if key == self.GUARD_INTEGRITY_KEY:
            return self.human_guard
        if key == self.APPLIES_INTEGRITY_KEY:
            return self.applies
        if key == self.EXTERNAL_ANCHOR_JSON_KEY:
            return self.root / "ledger" / "trust-root.json"
        if key == self.EXTERNAL_ANCHOR_SENTINEL_KEY:
            return self.root / "ledger" / ".external-anchor-enabled"
        return self.artifact_path(key)

    def record_integrity(self, artifact):
        """把某制品（或信任根）当前内容哈希记入 ledger/integrity.json（经 apply 写入后的真值）。
        N2'（v2.6.0）：同时追加到 D4 哈希链（前条摘要嵌后条），提供篡改连续性证据。"""
        p = self._integrity_path(artifact)
        if not p.exists():
            return
        text = p.read_text(encoding="utf-8")
        h = self._hash_text(text)
        data = read_json(self.integrity, {})
        _rec = {
            "hash": h,
            "size": p.stat().st_size,
            "at": now_iso(),
        }
        _rec["_anchor_sig"] = _ledger_anchor_sig(_rec)
        data[artifact] = _rec
        write_json(self.integrity, data)
        self._append_integrity_chain(artifact, h, p.stat().st_size)

    def _append_integrity_chain(self, key, h, size):
        """N2'（v2.6.0）：D4 哈希链——每条记录前置上一条摘要，任何插入/删除/重排都破坏连续性。
        独立文件 ledger/integrity-chain/chain.jsonl（与 integrity.json 分离存储，削弱同目录同权限自指根）。"""
        chain = self.root / "ledger" / "integrity-chain" / "chain.jsonl"
        chain.parent.mkdir(parents=True, exist_ok=True)
        prev = ""
        if chain.exists():
            lines = [l for l in chain.read_text(encoding="utf-8").splitlines() if l.strip()]
            if lines:
                try:
                    prev = json.loads(lines[-1]).get("hash", "")
                except Exception:
                    prev = "<broken>"
        entry = {"prev": prev, "hash": h, "key": key, "size": size, "at": now_iso()}
        with chain.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def applies_integrity_ok(self):
        """H-2（v2.5.8）+ N2'（v2.6.0）：比对 applies.jsonl 当前哈希与 D4 快照，并验证 D4 哈希链连续。

        - 无基线（v2.5.8 前安装 / 尚未 apply）→ 返回 True（向后兼容，不误伤）。
        - 有基线且不符 → 返回 False（疑似被直写篡改，resolve_trial_start 据此 HOLD）。
        - N2'：D4 哈希链尾条须覆盖 applies 且哈希 = 当前，且全链连续，否则 fail-closed。
        v2.8.11（H-2）：全方法包 try/except，异常计入 False（fail-closed）而非抛出崩主流程；"""
        try:
            data = read_json(self.integrity, {})
            rec = data.get(self.APPLIES_INTEGRITY_KEY)
            if rec is None:
                return True
            if not self.applies.exists():
                return False
            cur = self._hash_text(self.applies.read_text(encoding="utf-8"))
            if not self._hash_matches(rec.get("hash"), cur, allow_legacy=Store._legacy_hash_allowed()):
                return False
            return self._integrity_chain_ok(self.APPLIES_INTEGRITY_KEY, cur)
        except Exception as e:
            warn("[完整性] applies 哈希比对异常（{}）：{}".format(type(e).__name__, e))
            return False

    def _integrity_chain_ok(self, key, cur_hash):
        """N2'（v2.6.0）：D4 哈希链连续性校验。无链文件（v2.5.8 前/尚未记录）→ 不误伤返回 True。
        链损坏/不连续/尾条非目标 key/哈希不符 → 返回 False（fail-closed）。
        v2.8.11（H-2）：全方法包 try/except，异常计入 False（fail-closed）而非抛出崩主流程。"""
        try:
            chain = self.root / "ledger" / "integrity-chain" / "chain.jsonl"
            if not chain.exists():
                return True
            lines = [l for l in chain.read_text(encoding="utf-8").splitlines() if l.strip()]
            if not lines:
                return True
            prev = ""
            for ln in lines:
                try:
                    e = json.loads(ln)
                except Exception:
                    return False
                if not isinstance(e, dict) or e.get("prev") != prev:
                    return False  # 非 dict 行或链不连续（被插入/删除/重排）→ 篡改
                prev = e.get("hash", "")
            try:
                tail = json.loads(lines[-1])
            except Exception:
                return False
            return tail.get("key") == key and self._hash_matches(tail.get("hash"), cur_hash, allow_legacy=Store._legacy_hash_allowed())
        except Exception as e:
            warn("[完整性] 哈希链校验异常（{}）：{}".format(type(e).__name__, e))
            return False

    def record_guard_integrity(self):
        """P0：把 human-guard.json 当前内容哈希记入 D4 快照（检出直写替换公钥）。"""
        self.record_integrity(self.GUARD_INTEGRITY_KEY)

    # v2.7.3（HIGH-3 修复）：外部锚基线位置改为**固定**，由 root 推导（root 父级下、以 root 稳定
    # 哈希命名子目录），不再读取任何可写元数据（CONTRACT.md / trust-root.json）。这关闭 Hermes v2.7.2
    # 复验 HIGH-3：攻击者无法经改 CONTRACT.md 指针 / trust-root.json 字段把基线重定向到任意可写位置。
    # 该固定目录仍处同用户文件系统（Agent 理论上可删），故删『固定基线 + trust-root.json + sentinel』
    # 三件套仍会静默回退 legacy——此即 C-1 未真正闭合的残余（见 HANDOFF ⑦），本版如实披露、未消除。
    def _external_anchor_proof_dir(self, record: bool = True):
        """v2.7.3 HIGH-3 修复：固定外部证明目录。仅由 root 推导，不读 CONTRACT.md / trust-root.json
        等任何可写元数据 → 攻击者无法经改指针/字段把基线重定向到任意可写位置。
        返回 root.parent / '.metacog-external-anchor-store' / sha256(root)。恒非 None。
        v2.8.10（合并 repo F1）：证明目录名历史为 16-char（≤v2.8.5）；当前 _hash_text 为 32-char（128-bit）。
        升级后若新名目录不存在、但旧 16-char 目录存在，则一次性重命名为新名（迁移），使既存外部锚安装不 fail-closed；
        重命名失败则回退旧名，不阻断 verify。
        v2.8.11（H-1/L-2 收口）：rename 后复核源存在性、孤儿清理、失败留痕；半程失败不臆造成功。
        v2.8.11 补丁（D-1 幂等）：record 形参（默认 True）控制是否在异常态/迁移态写 migration-audit 留痕。
        只读/verify 路径须传 record=False，使 verify 不产生任何 ledger 写入（幂等），闭合 Hermes 复验
        挖出的『verify 非幂等写 ledger』回归（_external_anchor_deleted 经此路径每调用追加 legacy_orphan_kept）。"""
        store = self.root.parent / ".metacog-external-anchor-store"
        new_dir = store / self._hash_text(str(self.root.resolve()))
        if new_dir.exists():
            # L-2 + D-1：new 已存在时，遗留 legacy(16-char) 目录应被清孤儿（best-effort），避免双目录永久并存。
            # D-1 收口：删除 legacy 前证明不销毁非空基线——仅当 legacy 为空（无基线内容可失）才 rmdir；
            # 若 legacy 非空则保留并告警（双目录异常态待人工/巡检），绝不静默删非空基线（违反"静默失效不可接受"红线）。
            legacy_dir = store / self._hash_text_legacy(str(self.root.resolve()))
            if legacy_dir.exists():
                _new_empty = not any(new_dir.iterdir())
                _leg_empty = not any(legacy_dir.iterdir())
                if _new_empty and not _leg_empty:
                    # new 为空/半成品、legacy 含真实基线 → 优先返回 legacy，保基线（不删 legacy）
                    warn("[外部锚] new 目录为空/半成品但 legacy 含基线，优先返回 legacy，保留基线。")
                    if record:
                        self._record_migration_audit("prefer_legacy_over_empty_new", str(legacy_dir), str(new_dir), "")
                    return legacy_dir
                if _leg_empty:
                    try:
                        if record:
                            legacy_dir.rmdir()  # 仅空目录可删（record=False 只读路径不动），无基线内容可失
                        if record:
                            self._record_migration_audit("legacy_orphan_cleaned", str(legacy_dir), str(new_dir), "")
                    except OSError as e:
                        warn("[外部锚] new 目录已存在但 legacy 孤儿目录非空/无法删除({})：{}，保留待人工处理。".format(legacy_dir, e))
                        if record:
                            self._record_migration_audit("legacy_orphan_uncleaned", str(legacy_dir), str(new_dir), str(e))
                else:
                    warn("[外部锚] new 与 legacy 并存且均含内容（异常态），不删 legacy，保留待人工/巡检。")
                    if record:
                        self._record_migration_audit("legacy_orphan_kept", str(legacy_dir), str(new_dir), "")
            return new_dir
        legacy_dir = store / self._hash_text_legacy(str(self.root.resolve()))
        if legacy_dir.exists():
            try:
                if record:
                    legacy_dir.rename(new_dir)
            except OSError as e:
                # H-1：重命名失败（权限/跨设备等）。源仍完好 → 安全回退旧名；源已被外部删（迁移半程失败）→ 诚实 fail-closed 并留痕。
                if legacy_dir.exists():
                    warn("[外部锚] 旧 16-char 证明目录重命名为 32-char 失败({})；源目录仍完好，回退旧名。".format(e))
                    if record:
                        self._record_migration_audit("rename_failed_source_intact", str(legacy_dir), str(new_dir), str(e))
                    return legacy_dir
                warn("[外部锚] 旧 16-char 证明目录重命名失败且源已不存在({})：外部锚基线可能丢失，verify 将 fail-closed。".format(e))
                if record:
                    self._record_migration_audit("rename_failed_source_gone", str(legacy_dir), str(new_dir), str(e))
                return new_dir
            # rename 成功：复核源是否已移除（正常原子 rename 应已移除）；若源仍残存（异常文件系统），清孤儿+留痕。
            if legacy_dir.exists():
                try:
                    if record:
                        legacy_dir.rmdir()
                    if record:
                        self._record_migration_audit("legacy_orphan_cleaned", str(legacy_dir), str(new_dir), "")
                except OSError as e2:
                    warn("[外部锚] 重命名后旧目录仍残留且非空({})：{}，保留待人工处理。".format(legacy_dir, e2))
                    if record:
                        self._record_migration_audit("legacy_orphan_uncleaned", str(legacy_dir), str(new_dir), str(e2))
            return new_dir
        # 旧 16-char 目录也不存在 → 尚未建立外部锚 / 或迁移半程丢失；返回 new_dir（verify 因缺失基线 fail-closed 并告警），不臆造成功。
        return new_dir

    def _record_migration_audit(self, event, src, dst, detail):
        """v2.8.11（H-1 收口）：外部锚证明目录迁移/孤儿清理事件的审计留痕。
        写入 ledger/migration-audit.jsonl（与 rollback-audit.jsonl 同源 HMAC 链，复用 _audit_hmac_key）。
        任何迁移阻塞/半程失败均留痕，供运营巡检发现（不再静默失效）。"""
        try:
            _audit = self.root / "ledger" / "migration-audit.jsonl"
            _audit.parent.mkdir(parents=True, exist_ok=True)
            _key = _audit_hmac_key(self)
            _prev = ""
            if _audit.exists():
                _lines = [l for l in _audit.read_text(encoding="utf-8").splitlines() if l.strip()]
                if _lines:
                    try:
                        _last = json.loads(_lines[-1])
                        _hmac = _last.get("hmac") if isinstance(_last, dict) else None
                        if isinstance(_hmac, str):
                            _prev = _hmac
                        else:
                            _prev = "<broken>"
                            warn("[审计] 上游 migration-audit 末条 hmac 非字符串（null/畸形），已置 prev_hmac=<broken> 阻断链污染")
                    except Exception:
                        _prev = "<broken>"
            # v2.9.0 修复：_entry 必须在 if 块外赋值——首次迁移审计（文件尚不存在）时
            # if _audit.exists() 为 False，原结构令 _entry 未绑定 → UnboundLocalError 被外层 except 静默吞掉
            #（迁移审计静默丢失，正是 D-2 所斥的"静默失效"）。移出后首次调用即可正确落盘。
            _entry = {
                "at": now_iso(),
                "operation": "external-anchor-proof-dir-migration",
                "epoch": LEDGER_KEY_EPOCH,
                "event": event,
                "src": src,
                "dst": dst,
                "detail": detail,
                "prev_hmac": _prev,
            }
            _payload = json.dumps(_entry, separators=(",", ":"), sort_keys=True)
            _entry["hmac"] = hmac.new(_key, _payload.encode("utf-8"), hashlib.sha256).hexdigest()
            with _audit.open("a", encoding="utf-8") as _f:
                _f.write(json.dumps(_entry, separators=(",", ":"), sort_keys=True) + "\n")
        except Exception:
            # 审计留痕自身失败不得影响 verify 主流程（仅告警）
            warn("[外部锚] 迁移审计留痕失败（不影响主流程）。")

    @property
    def external_anchor_baseline_path(self):
        d = self._external_anchor_proof_dir()
        if d is None:
            return None
        return d / ".external-anchor-baseline.json"

    def purge_external_anchor(self):
        """v2.7.7（M-1 收口）：删除外部锚**全部**足迹，返回三态而非 bool：
          - "cleared"：确有外部锚待回收且全部足迹已删除（ledger trust-root.json + sentinel + 固定外部证明目录）；
          - "none"：固定外部证明目录本就不存在（从未启用，无可回收）；
          - "partial"：任一删除步骤抛异常且文件仍残留（拒绝半成品，调用方须 stderr WARN + 退出码 2 提示人类手动补清）。

        删除对象与顺序同 v2.7.6 NEW-H1：先清工作域 ledger/trust-root.json + .external-anchor-enabled，
        再删固定外部证明目录（含 root-pubkey.pem 与基线）。

        v2.7.7 关键修复（Hermes v2.7.6 复验 M-1）：原返回 bool 时 "partial" 与 "none" 同为 False，
        被调用方误报为「无需回收」，可诱发 re-enable 覆盖钉固公钥 → 完整 C-1 绕过。现以三态区分：
        partial 由调用方明确告警（绝不等同 none），并要求人类手动补清残留后再 re-enable。

        v2.7.8 修复（Hermes v2.7.7 复验 NEW-M）：生产启用路径 write_trust_root_config 对 ledger 文件
        调 _restrict_credential → Windows 置只读位(0o400)；Windows 上 os.unlink/rmtree 对只读文件抛
        PermissionError[WinError 5]，原实现会令 purge 在 Windows 恒返 "partial"、"cleared" 成死代码、
        外部锚足迹（含钉固 root-pubkey.pem）无法实际清除。现：step1 unlink 前先清只读位（0o600，沿用
        write_trust_root_config 既有模式）；step2 rmtree 加 onerror=_rm_readonly 清只读重试。

        半败时本方法直接 stderr WARN 并给出残留路径，调用方据此提示人类手动删除；不静默半清、
        也不误报「无需回收」。"""
        d = self._external_anchor_proof_dir()
        had_proof = d is not None and d.exists()
        # 1) 先清工作域 ledger 足迹（trust-root.json + sentinel）—— NEW-H1 补清
        for key in (self.EXTERNAL_ANCHOR_JSON_KEY, self.EXTERNAL_ANCHOR_SENTINEL_KEY):
            p = self._integrity_path(key)
            if p is not None and p.exists():
                # v2.7.8（NEW-M）：Windows 上 ledger 文件经 _restrict_credential 置只读位(0o400)，
                # 直接 unlink 抛 PermissionError[WinError 5]；删除前先清只读位（0o600，POSIX 无副作用）。
                try:
                    os.chmod(str(p), 0o600)
                except OSError:
                    pass
                try:
                    p.unlink()
                except Exception:
                    sys.stderr.write(
                        "[metacog] WARN: 外部锚回收半败（ledger 足迹删除失败）：sentinel 已失，"
                        "系统已回退 legacy；但固定外部证明目录 %s 可能仍残留，请手动删除后再 re-enable。\n"
                        % (d if d is not None else "<unknown>"))
                    return "partial"  # 半成品：ledger 足迹删除失败 → 拒绝（不静默半清）
        # 2) 删固定外部证明目录（含 root-pubkey.pem 与基线）
        if d is not None and d.exists():
            try:
                # v2.7.8（NEW-M）：onerror=_rm_readonly 清只读重试，避免 Windows 只读文件 WinError 5
                shutil.rmtree(d, ignore_errors=False, onerror=_rm_readonly)
            except Exception:
                sys.stderr.write(
                    "[metacog] WARN: 外部锚回收半败（外部证明目录删除失败）：%s 仍残留，"
                    "请手动删除后再 re-enable（切勿在残留态下直接 --enable-external，否则钉固公钥可被覆盖）。\n"
                    % d)
                return "partial"  # 半成品：外部证明目录删除失败 → 拒绝（不静默半清）
        return "cleared" if had_proof else "none"

    def _upsert_contract_proof_dir(self, proof_dir: Path):
        """v2.7.3 起：本方法为**保留空实现（no-op）**。v2.7.2 曾把外部证明目录写入 CONTRACT.md
        作为基线发现回退；v2.7.3 撤回——CONTRACT.md 属可写域，用作基线发现源即引入 Hermes HIGH-3
        重定向风险。外部锚基线位置现完全由 _external_anchor_proof_dir 固定推导，不再依赖任何可写元数据。
        保留签名仅为兼容潜在调用方；不再产生任何副作用。"""
        return

    def record_external_anchor_integrity(self, root_pubkey=None, root_privkey=None):
        """v2.7.4（NEW-H1 收口 + M-4）：把外部锚信任根（trust-root.json + sentinel）当前哈希记入
        **固定外部**基线；并把 root_pubkey 钉固到固定证明目录（独立于可写锚，使基线验签的验证密钥
        不被攻击者经改锚重定向——闭合 Hermes v2.7.3 NEW-H1『基线非认证』根因）。

        - root_pubkey：钉固到 proof_dir/root-pubkey.pem（验证基线签名用，与可写 trust-root.json 解耦）。
        - root_privkey（人类离线持有，可选）：对 (anchor_hash||sentinel_hash) 签名存入 baseline.signature。
          提供则基线具密码学认证 → 一致化改写（攻击者无离线私钥）被检出（NEW-H1 闭合）；不提供则基线仅
          best-effort 变更检测（哈希快照），NEW-H1 残余（须部署契约兜底），如实披露。
        v2.7.3 曾把基线发现源写回 CONTRACT.md（可写域，HIGH-3 风险）→ v2.7.3 已撤回；v2.7.4 进一步把
        验证密钥钉固到固定目录，基线签名认证独立于可写锚。M-4：全部 I/O 包 try/except，记录失败不抛异常。"""
        bp = self.external_anchor_baseline_path
        if bp is None:
            return
        try:
            proof_dir = self._external_anchor_proof_dir()
            proof_dir.mkdir(parents=True, exist_ok=True)
            if root_pubkey:
                (proof_dir / "root-pubkey.pem").write_text(str(root_pubkey), encoding="utf-8")
            rec = {}
            for key in (self.EXTERNAL_ANCHOR_JSON_KEY, self.EXTERNAL_ANCHOR_SENTINEL_KEY):
                p = self._integrity_path(key)
                if p.exists():
                    rec[key] = {
                        "hash": self._hash_text(p.read_text(encoding="utf-8")),
                        "size": p.stat().st_size,
                        "at": now_iso(),
                    }
            # 离线根签名（NEW-H1 闭合；缺私钥/异常/锚缺失则留空 → best-effort 变更检测）
            signed_ok = False
            if root_privkey and sigcrypto is not None and rec.get(self.EXTERNAL_ANCHOR_JSON_KEY) and rec.get(self.EXTERNAL_ANCHOR_SENTINEL_KEY):
                try:
                    payload = (rec[self.EXTERNAL_ANCHOR_JSON_KEY]["hash"]
                               + "||"
                               + rec[self.EXTERNAL_ANCHOR_SENTINEL_KEY]["hash"]).encode("utf-8")
                    priv = sigcrypto.deserialize_priv(root_privkey)
                    sig = sigcrypto.sign(priv, payload)
                    rec["signature"] = base64.b64encode(sig).decode("ascii")
                    signed_ok = True
                except Exception:
                    rec.pop("signature", None)  # 签名失败不阻断记录；基线退为 best-effort
                    sys.stderr.write(
                        "[metacog] WARN: 外部锚基线签名失败，NEW-H1 未闭合："
                        "请检查 --root-privkey 是否为合法离线根私钥（基线将仅作 best-effort 变更检测）。\n")
            elif root_privkey and sigcrypto is not None:
                # D1 第二静默分支（v2.7.6）：提供了 --root-privkey 但 anchor/sentinel 任一缺失，
                # 基线无法签名 → 退 best-effort 残余（NEW-H1 未闭合），如实告警（与 except 分支对称）。
                sys.stderr.write(
                    "[metacog] WARN: 外部锚基线签名跳过（anchor 或 sentinel 缺失），NEW-H1 未闭合："
                    "基线将仅作 best-effort 变更检测，须部署契约兜底（请确认 --enable-external 已成功写入锚与哨兵）。\n")
            if signed_ok:
                rec["signed"] = True  # v2.7.5 E1：标记基线曾以离线根签名建立 → 签名被剥离即 fail-closed
            write_json(bp, rec)
        except Exception:
            # M-4：记录基线失败不抛异常中断 enable；缺失基线使后续 check 按
            # "基线缺失+曾启用→fail-closed" 处理（fail-closed 方向）
            return

    def _external_anchor_deleted(self):
        """v2.7.4（NEW-H1 收口 + HIGH-1/2/3 + MEDIUM-1 + M-4）：外部锚基线存于**固定外部**位置，
        并可选经离线根签名认证（验证密钥 root_pubkey 钉固于固定证明目录，与可写锚解耦）。

        诚实分层（M-3）：
        - 外部锚**证明/令牌验证**（attestation / oob token）确由离线根私钥签名、Agent 仅持公钥验签
          → 此部分为真密码学不可伪造（INV-3/INV-4）。
        - 外部锚**完整性基线**（本函数）v2.7.3 仅为 SHA-256 快照（变更检测，非信任根）→ 一致化改写
          未被检出（Hermes v2.7.3 NEW-H1）。v2.7.4 起：基线可选经离线根签名认证（提供 root_privkey
          时）→ 一致化改写被检出（NEW-H1 闭合）；不提供则仍 best-effort 变更检测（NEW-H1 残余，如实披露）。

        判定（任何『期望存在却缺失/残缺/不符/签名无效』一律 fail-closed；M-4：I/O 异常亦 fail-closed）：
        - 基线缺失 + 从未启用(sentinel 不在) → 正常 legacy（向后兼容）。
        - 基线缺失 + 曾启用(sentinel 在) → 基线被破坏 → fail-closed。
        - 基线存在但任一期望 key(JSON/SENTINEL)缺失 → 残缺基线 → fail-closed（HIGH-2）。
        - 基线存在但信任根文件缺失 → 被删（HIGH-1）→ fail-closed。
        - 基线存在但 anchor 哈希不符 → 锚被篡改（P2）→ fail-closed。
        - 基线存在但 sentinel 哈希不符 → 哨兵被篡改（MEDIUM-1）→ fail-closed。
        - 基线签名存在且钉固公钥可用但验签无效 → 一致化改写（NEW-H1）→ fail-closed。
        - 其余 → 正常。

        NEW-H1 闭合说明：基线签名（若有）须对钉固 root_pubkey 验签通过；一致化改写 anchor+sentinel
        +baseline 因攻击者无离线私钥无法伪造签名 → 验签失败 → fail-closed。残余：钉固 root-pubkey.pem
        仍处同用户可写文件系统（与 CONTRACT.md 钉固人类公钥同层级），攻击者同用户删/改它+基线仍可绕过
        ——此即 C-1 未真正闭合的同构残余，须外部不可变存储（TPM/只读介质/独立机）方真闭合（见 HANDOFF ⑦），
        如实披露。删除『固定基线+锚+sentinel』三件套仍静默回退 legacy 的残余同此。"""
        sentinel = self.root / "ledger" / ".external-anchor-enabled"
        try:
            enabled = sentinel.exists()
        except Exception:
            enabled = False
        # v2.8.11 补丁（D-1 幂等）：verify 只读路径须 record=False，避免每调用追加 legacy_orphan_kept 等 ledger 留痕。
        _pd = self._external_anchor_proof_dir(record=False)
        bp = (_pd / ".external-anchor-baseline.json") if _pd is not None else None
        if bp is None:
            return False  # 固定路径推导失败（极端）：不误伤，按 legacy
        if not bp.exists():
            # 基线缺失：曾启用(sentinel 在) → 基线被破坏 → fail-closed；否则从未启用 → legacy
            return enabled
        # 钉固 root_pubkey（验证基线签名用，独立于可写锚）
        proof_dir = self._external_anchor_proof_dir(record=False)
        pinned_pub = None
        if proof_dir is not None and sigcrypto is not None:
            pk = proof_dir / "root-pubkey.pem"
            try:
                if pk.exists():
                    pinned_pub = sigcrypto.deserialize_pub(pk.read_text(encoding="utf-8"))
            except Exception:
                pinned_pub = None  # 钉固公钥解析失败 → 无法验签 → 下方签名检查 fail-closed
        try:
            data = read_json(bp, {})
        except Exception:
            return True  # 基线解析失败 → 视为被破坏 → fail-closed (M-4)
        # HIGH-2：基线存在但任一期望 key 缺失 → 残缺基线视为被破坏 → fail-closed
        if (self.EXTERNAL_ANCHOR_JSON_KEY not in data
                or self.EXTERNAL_ANCHOR_SENTINEL_KEY not in data):
            return True
        anchor = self.root / "ledger" / "trust-root.json"
        if not anchor.exists():
            return True  # 基线存在但锚文件缺失 → 删除攻击（HIGH-1，fail-closed）
        # M-4 + P2：哈希比对（篡改检测，fail-closed）
        try:
            cur_hash = self._hash_text(anchor.read_text(encoding="utf-8"))
        except Exception:
            return True  # 锚读取/解析失败 → fail-closed (M-4)
        rec = data.get(self.EXTERNAL_ANCHOR_JSON_KEY)
        if rec is None or not self._hash_matches(rec.get("hash"), cur_hash, allow_legacy=Store._legacy_hash_allowed()):
            return True  # 锚内容被改 → 篡改攻击（P2，fail-closed）
        sentinel_cur_hash = None
        try:
            sentinel_cur_hash = (self._hash_text(sentinel.read_text(encoding="utf-8"))
                                 if sentinel.exists() else None)
        except Exception:
            return True  # 哨兵读取失败 → fail-closed (M-4)
        srec = data.get(self.EXTERNAL_ANCHOR_SENTINEL_KEY)
        if srec is None or not self._hash_matches(srec.get("hash"), sentinel_cur_hash, allow_legacy=Store._legacy_hash_allowed()):
            return True  # 哨兵被篡改/缺失 → MEDIUM-1，fail-closed
        # NEW-H1 闭合 + v2.7.5 E1/C1：基线签名验证（强制闸）
        sig = data.get("signature")
        baseline_signed = bool(data.get("signed"))
        if baseline_signed:
            # 基线曾以离线根签名建立：签名字段或钉固公钥缺失 = 被剥离/篡改
            # → 视为一致化改写攻击 → fail-closed（不再静默回退 best-effort）（E1/C1）
            if not sig or pinned_pub is None:
                return True  # 签名被剥离 / 钉固公钥缺失 → fail-closed (E1/C1)
            try:
                payload = (rec["hash"] + "||" + srec["hash"]).encode("utf-8")
                if not sigcrypto.verify(pinned_pub, payload, base64.b64decode(sig)):
                    return True  # 签名无效 → 一致化改写被检出 → fail-closed (NEW-H1)
            except Exception:
                return True  # 验签异常 → fail-closed (M-4)
        # 未签名基线（legacy / 未提供私钥）：best-effort 变更检测，NEW-H1 残余未闭合（如实披露）
        return False

    @property
    def script_dir(self):
        # 兼容两种布局：scripts/ 在 root 下，或脚本直接在 root 下（测试临时目录均无 → 跳过）
        # 测试可用 _script_dir_override 重定向；生产环境恒为 None。
        if self._script_dir_override is not None:
            return self._script_dir_override
        if (self.root / "scripts" / "metacog.py").exists():
            return self.root / "scripts"
        if (self.root / "metacog.py").exists():
            return self.root
        return self.root / "scripts"

    @script_dir.setter
    def script_dir(self, value):
        self._script_dir_override = value

    def _skill_version_of(self, text):
        """v2.8.9 ⑤：从 SKILL.md 文本解析 version 字段（frontmatter `version: X.Y.Z` 或 `version = X.Y.Z`）；找不到返 None。"""
        for _ln in text.splitlines():
            _s = _ln.strip()
            if _s.lower().startswith("version:") or _s.lower().startswith("version ="):
                _v = _s.split(":", 1)[1].strip() if ":" in _s else _s.split("=", 1)[1].strip()
                return _v
        return None

    def _skill_body_hash(self, text):
        """v2.8.9 ⑤：将 SKILL.md 的 version 行规范为占位后哈希正文——使"仅版本号变更"不影响正文哈希
        （版本升级必改 SKILL.md 头，须豁免而非阻断）。"""
        _out = []
        for _ln in text.splitlines():
            if re.match(r'^\s*version\s*[:=]\s*\S+', _ln, re.IGNORECASE):
                _out.append("version: __CANON__")
            else:
                _out.append(_ln)
        return self._hash_text("\n".join(_out))

    def record_script_integrity(self):
        """v2.5.2（M-5）+ v2.8.2 C-10 扩面 + v2.8.3 高-2 + v2.8.4 L-3 + v2.8.5 H-1：把技能自身全部 17 个 shipped 运行时脚本（见 SCRIPT_NAMES；9 顶层 + 8 嵌套包，含 '/' 相对路径）当前哈希
        记入 D4 快照，使 Agent 经 Bash 改写代码弱化人类闸（如删除 check_pubkey_root 调用）能被 verify 检出。
        仅在受信锚（keygen / apply）落盘时调用；脚本文件不存在则跳过（不污染快照，亦不误伤测试临时目录）。
        v2.8.5 H-1：记录后清理孤儿键——凡 `script:` 键其名称不在 SCRIPT_NAMES（如 L-3 出基线的死代码
        domains/knowledge_transfer.py）一律删除，使存量安装升级后 verify 不再永久 dirty。注意：仅清理
        "名称不在 SCRIPT_NAMES" 的键，保留 "文件缺失但名称仍在 SCRIPT_NAMES" 的键（后者须留存以让 verify 检出删除攻击）。"""
        data = read_json(self.integrity, {})
        changed = False
        expected = {"script:" + n for n in self.SCRIPT_NAMES}
        for name in self.SCRIPT_NAMES:
            p = self.script_dir / name
            if not p.exists():
                continue
            _script_rec = {
                "hash": self._hash_text(p.read_text(encoding="utf-8")),
                "size": p.stat().st_size,
                "at": now_iso(),
            }
            # v2.10.0（HIGH#1 / C-10）：script: 域（C-10 主威胁面）基线补签名锚——此前该域基线
            # 从未写入 _anchor_sig，与 v2.8.1 原始 OPEN 状态等价；现与 manifest 域同构，改文件+重记基线
            # 将被 _verify_anchor_sig 检出（签名密钥位于代码，攻击者凭 ledger 写权限无法伪造）。
            _script_rec["_anchor_sig"] = _ledger_anchor_sig(_script_rec)
            data["script:" + name] = _script_rec
            changed = True
        # v2.8.9 ⑤：可信清单（manifest: 键）基线化 + 分文件硬闸数据准备——Hermes H-01 收口 F-4 纸面闭环。
        # SKILL.md 额外存 `manifest:SKILL.md@body`（正文哈希，version 行规范化为占位）→ 仅版本号变更豁免、正文变更阻断。
        # CONTRACT.md/HANDOFF.md/pack.sh 任一内容变更 → 阻断；CHANGELOG.md → 非阻塞（版本升级产物）。
        _legacy_migrated = 0
        for _mname in self.MANIFEST_NAMES:
            _mp = self.root / _mname
            if not _mp.exists():
                continue
            _mtext = _mp.read_text(encoding="utf-8")
            _mh = self._hash_text(_mtext)
            _old_rec = data.get("manifest:" + _mname)
            if _old_rec is not None and _old_rec.get("hash") != _mh:
                warn("[完整性] 重基线 manifest 键（{}）：旧 hash={} → 新 hash={}；如非预期请核查是否被篡改。".format(
                    _mname, _old_rec.get("hash"), _mh))
                if isinstance(_old_rec.get("hash"), str) and len(_old_rec.get("hash")) == 16 and len(_mh) == 32:
                    _legacy_migrated += 1  # 16-char → 32-char 迁移计数（④ 迁移计数器）
            if _mname == "SKILL.md":
                _body_h = self._skill_body_hash(_mtext)
                _sk_rec = {
                    "hash": _mh,
                    "version": self._skill_version_of(_mtext),
                    "size": _mp.stat().st_size,
                    "at": now_iso(),
                }
                _sk_rec["_anchor_sig"] = _ledger_anchor_sig(_sk_rec)
                data["manifest:SKILL.md"] = _sk_rec
                _body_rec = {
                    "hash": _body_h,
                    "size": _mp.stat().st_size,
                    "at": now_iso(),
                }
                _body_rec["_anchor_sig"] = _ledger_anchor_sig(_body_rec)
                data["manifest:SKILL.md@body"] = _body_rec
            else:
                _m_rec = {
                    "hash": _mh,
                    "size": _mp.stat().st_size,
                    "at": now_iso(),
                }
                _m_rec["_anchor_sig"] = _ledger_anchor_sig(_m_rec)
                data["manifest:" + _mname] = _m_rec
            changed = True
        # v2.8.9 ④：legacy 迁移计数器（integrity.json __meta__）——观测存量 legacy 基线剩余/已迁移
        _meta = data.setdefault("__meta__", {})
        # v2.9.0（M-1 收口）：legacy_remaining 须覆盖全部基线条目（含 guard/applies 等非 script:/manifest:
        # 前缀的信任根域基线），避免 N-2 修复口径偏窄导致 64-bit 旧基线残留未被统计（Hermes M-1 揭示）。
        _legacy_remaining = sum(
            1 for _k, _v in data.items()
            if _k != "__meta__" and isinstance(_v, dict)
            and isinstance(_v.get("hash"), str) and len(_v.get("hash")) == 16
        )
        _meta["legacy_remaining"] = _legacy_remaining
        if _legacy_migrated:
            _meta["legacy_migrated"] = _meta.get("legacy_migrated", 0) + _legacy_migrated
        # v2.8.5 H-1：孤儿清理（见 docstring）。仅删 "名称不在 SCRIPT_NAMES" 的 script: 键。
        for _k in [k for k in data if k.startswith("script:") and k not in expected]:
            del data[_k]
            changed = True
        # v2.8.9 ⑤：manifest 孤儿清理（名称不在 MANIFEST_NAMES 的 manifest: 键删除；保留 SKILL.md@body 派生键）
        _expected_m = {"manifest:" + n for n in self.MANIFEST_NAMES} | {"manifest:SKILL.md@body"}
        for _k in [k for k in data if k.startswith("manifest:") and k not in _expected_m]:
            del data[_k]
            changed = True
        if changed:
            write_json(self.integrity, data)

    def verify_integrity(self):
        """比对各制品当前内容哈希与 ledger 快照，返回 [(artifact, ok, stored, current)]。

        注：信任根（GUARD_INTEGRITY_KEY）的判定由 cmd_verify 专用块处理（含指纹漂移），
        此处跳过通用判定以免重复计数。"""
        data = read_json(self.integrity, {})
        out = []
        for artifact, rec in data.items():
            if artifact == self.GUARD_INTEGRITY_KEY:
                continue
            if artifact.startswith("script:"):
                # v2.8.4 M-3：删除检出不再单点依赖 verify_script_integrity；主告警路径（cmd_verify）
                # 也遍历 script: 键，作为非阻塞告警纳入 dirty 计数（含文件被删情形：current=None）。
                _name = artifact[len("script:"):]
                _sp = self.script_dir / _name
                if not _sp.exists():
                    out.append((artifact, False, rec.get("hash"), None))
                    continue
                _cur = self._hash_text(_sp.read_text(encoding="utf-8"))
                _ok, _legacy = self._script_hash_matches(_cur, rec.get("hash"), allow_legacy=Store._legacy_hash_allowed())
                if _legacy:
                    warn("[完整性] 检测到 64-bit 旧格式基线哈希（{}）；已按首 16 字符判定未篡改，"
                         "建议运行 keygen/apply 自动升级为 128-bit 基线。".format(artifact))
                # v2.10.0（HIGH#1 / C-10）：script: 域基线签名验签——攻击者改文件+重记基线（伪造签名）
                # 将被检出 → fail-closed；无签名（legacy 旧基线）→ 容忍 best-effort（待重基线）。
                # v2.11.0（H-B 收口）：缺失 _anchor_sig 的无签名基线在 CURRENT >= LEGACY_ANCHOR_SIG_CUTOFF
                # 后从「容忍」升级为 fail-closed（杜绝「删 _anchor_sig 即降级为 legacy」攻击面，Hermes r7 H-B）。
                _sig_ok = _verify_anchor_sig(rec)
                if _sig_ok is False:
                    _ok = False
                    warn("[完整性] script: 基线签名失效（{}）：疑似被篡改后伪造签名，已标 dirty。".format(artifact))
                elif _sig_ok is None and not Store._legacy_anchor_sig_allowed():
                    _ok = False
                    warn("[完整性] script: 基线缺失 _anchor_sig（早于 v2.11 的 legacy 无签名基线）；按 v2.11 截止期已 fail-closed，"
                         "请运行 keygen/apply 重基线。".format(artifact))
                out.append((artifact, _ok, rec.get("hash"), _cur))
                continue
            if artifact.startswith("manifest:"):
                # v2.8.9 ⑤：可信清单基线比对 + 分文件硬闸判定（Hermes H-01 收口 F-4 纸面闭环）。
                # `manifest:SKILL.md@body` 为派生键（无对应文件），跳过（由 SKILL.md 全量哈希 + 正文哈希逻辑处理）。
                _mname = artifact[len("manifest:"):]
                if _mname.endswith("@body"):
                    continue
                # v2.9.0（C-10 / H-4）：基线签名验签——签名存在且无效 → 一致化改写（攻击者凭 ledger 写权限
                # 重记基线+签名）被检出 → fail-closed；签名缺失（legacy 基线）→ 容忍 best-effort（待重基线）；
                # 签名有效 → 信任基线 hash（密钥位于代码，非可写 ledger，攻击者无法伪造）。
                # v2.11.0（H-B 收口）：缺失 _anchor_sig 的无签名基线在 CURRENT >= LEGACY_ANCHOR_SIG_CUTOFF
                # 后从「容忍」升级为 fail-closed（杜绝「删 _anchor_sig 即降级为 legacy」攻击面，Hermes r7 H-B）。
                _sig_ok = _verify_anchor_sig(rec)
                if _sig_ok is False:
                    out.append((artifact, False, rec.get("hash"), None))
                    continue
                if _sig_ok is None and not Store._legacy_anchor_sig_allowed():
                    out.append((artifact, False, rec.get("hash"), None))
                    warn("[完整性] manifest: 基线缺失 _anchor_sig（早于 v2.11 的 legacy 无签名基线）；按 v2.11 截止期已 fail-closed，"
                         "请运行 keygen/apply 重基线。")
                    continue
                _mp = self.root / _mname
                if not _mp.exists():
                    out.append((artifact, False, rec.get("hash"), None))
                    continue
                _mtext = _mp.read_text(encoding="utf-8")
                _mcur = self._hash_text(_mtext)
                _ok, _legacy = self._script_hash_matches(_mcur, rec.get("hash"), allow_legacy=Store._legacy_hash_allowed())
                if _legacy:
                    warn("[完整性] 检测到 64-bit 旧格式基线哈希（{}）；已按首 16 字符判定未篡改，"
                         "建议运行 keygen/apply 自动升级为 128-bit 基线。".format(artifact))
                if _mname == "SKILL.md" and not _ok:
                    # v2.9.0（H-4）：@body 豁免仅当 @body 基线签名有效（独立可信信号）才生效；
                    # 无签名（legacy）/ 签名无效 → 不豁免，维持 _ok=False（倒逼重基线 / 检出篡改）。
                    _body_rec = data.get("manifest:SKILL.md@body")
                    if _body_rec is not None and _verify_anchor_sig(_body_rec) is True:
                        _cur_body = self._skill_body_hash(_mtext)
                        _bok, _ = self._script_hash_matches(_cur_body, _body_rec.get("hash"), allow_legacy=Store._legacy_hash_allowed())
                        if _bok:
                            _ok = True
                out.append((artifact, _ok, rec.get("hash"), _mcur))
                continue
            if artifact == "__meta__":
                # v2.8.9 ⑤：record_script_integrity 写入的内部元数据键（legacy_migrated/legacy_remaining 等），
                # 非制品/非脚本/非信任根，无对应文件，verify 跳过（避免 ARTIFACTS['__meta__'] KeyError）。
                continue
            # v2.10.0（HIGH#1 / C-10）：artifact / applies 域基线签名验签——此前 record_integrity 已写入
            # _anchor_sig 但 verify 从不校验（写而不验），攻击者改文件+重记基线即绕过；现补验签
            # （签名失效 → fail-closed；无签名 legacy 旧基线 → 容忍 best-effort 待重基线）。
            # v2.11.0（H-B 收口）：缺失 _anchor_sig 的无签名基线在 CURRENT >= LEGACY_ANCHOR_SIG_CUTOFF
            # 后从「容忍」升级为 fail-closed（杜绝「删 _anchor_sig 即降级为 legacy」攻击面，Hermes r7 H-B）。
            _sig_ok = _verify_anchor_sig(rec)
            if _sig_ok is False:
                out.append((artifact, False, rec.get("hash"), None))
                continue
            if _sig_ok is None and not Store._legacy_anchor_sig_allowed():
                out.append((artifact, False, rec.get("hash"), None))
                warn("[完整性] artifact: 基线缺失 _anchor_sig（早于 v2.11 的 legacy 无签名基线）；按 v2.11 截止期已 fail-closed，"
                     "请运行 keygen/apply 重基线。")
                continue
            p = self._integrity_path(artifact)
            if not p.exists():
                out.append((artifact, False, rec.get("hash"), None))
                continue
            cur = self._hash_text(p.read_text(encoding="utf-8"))
            _ok, _legacy = self._script_hash_matches(cur, rec.get("hash"), allow_legacy=Store._legacy_hash_allowed())
            if _legacy:
                warn("[完整性] 检测到 64-bit 旧格式基线哈希（{}）；已按首 16 字符判定未篡改，"
                     "建议运行 keygen/apply 自动升级为 128-bit 基线。".format(artifact))
            out.append((artifact, _ok, rec.get("hash"), cur))
        # v2.8.11（D-2）：外部锚迁移审计链 HMAC 校验；链断裂/被篡改 → 计入 dirty（fail-closed 报警），不静默。
        try:
            _ma_ok, _ma_cnt = self._verify_migration_audit()
            if not _ma_ok:
                out.append(("audit:migration", False, None, None))
        except Exception:
            out.append(("audit:migration", False, None, None))
        return out

    def _verify_migration_audit(self, cutoff=None):
        """v2.8.11（D-2）+ v2.10.0（HIGH#2/#3 / C-10 收口）+ v2.11.0（H-C 收口）：校验 ledger/migration-audit.jsonl 的 HMAC 哈希链
        连续性 + 逐条 HMAC + 逐条 epoch（v2.10.0 起严格链强制 epoch，中段缺 epoch → fail-closed）。
        插入/重排/伪造/篡改/中段缺 epoch → ok=False（fail-closed）；尾部有效子链截断（一种删除）仍 ok=True（D-2 残余，无外部总数锚）。返回 (ok, count)。
        诚实边界（v2.10.0 重写）：
        - 严格链（首条带 epoch=v290，即 v2.9.0+ 写入）：全链逐条验 HMAC + 链连续 + 逐条 epoch，伪造即 fail-closed。
        - 旧链（首条缺 epoch，即 <v2.9.0 写入）：仅做**结构预检**（dict + hmac/prev_hmac 为 str），
          不验 HMAC 值、不验链连续、不验逐条 epoch——旧链用可推导旧密钥签名，无法以新锚验签，
          故结构合法即「不可信但容忍」（不标 dirty），不放行结构畸形（非 dict / 非 str / 非法 JSON）。
          此容忍是**永久性**的：本函数**不实现旧链自动归档/重命名/删除**（v2.9.0 注释中的
          「待 keygen/apply 重基线后旧链归档」为不实承诺，v2.10.0 如实撤销）；旧链是否进入严格校验，
          取决于操作员是否手动重建该 jsonl（首条写入带 epoch=v290 的新链）。"""
        _audit = self.root / "ledger" / "migration-audit.jsonl"
        if not _audit.exists():
            return (True, 0)
        _key = _audit_hmac_key(self)
        _lines = [l for l in _audit.read_text(encoding="utf-8").splitlines() if l.strip()]
        _total = len(_lines)
        # v2.10.0（HIGH#2 / C-10 诚实化）：首条缺 epoch 标记 → 旧版（<v2.9.0）链，视为不可信但容忍
        # （仅结构预检，不验 HMAC/连续/epoch；详见本函数 docstring）。本函数不实现旧链自动归档。
        if _lines:
            try:
                _first = json.loads(_lines[0])
            except Exception:
                _first = {}
            if not (isinstance(_first, dict) and _first.get("epoch") == LEDGER_KEY_EPOCH):
                # v2.10.0（HIGH#2 / C-10 诚实化）：旧链「不可信但容忍」——仅做结构预检（dict + hmac/prev_hmac 为 str），
                # 不验 HMAC 值、不验链连续、不验逐条 epoch（旧密钥签名的链无法以新锚验签，属已知边界）。
                # 结构性损坏（非 dict / hmac 或 prev_hmac 非字符串 / 非法 JSON）仍 fail-closed 检出，
                # 不放行静默结构篡改（否则 M-1 写侧污染守卫 / D-2 尾部截断类攻击被纵容）。与 _verify_audit_chain 同源收紧。
                # 注意：v2.10.0 起本分支**不实现旧链自动归档**（v2.9.0 注释中的归档承诺不实，v2.10.0 如实撤销）；
                # 旧链停留容忍态直至操作员手动重建带 epoch 的新链。
                # v2.11.0（H-C 收口）：旧链容忍带截止期——CURRENT >= LEGACY_AUDIT_CHAIN_CUTOFF 后，
                # 旧链从「不可信但容忍」升级为 fail-closed（杜绝「删带 epoch 条目即令历史退化」永久降级，Hermes r7 H-C）。
                _struct_ok = True
                for _ln in _lines:
                    try:
                        _e = json.loads(_ln)
                    except Exception:
                        _struct_ok = False
                        break
                    if not isinstance(_e, dict) or not isinstance(_e.get("prev_hmac"), str) or not isinstance(_e.get("hmac"), str):
                        _struct_ok = False
                        break
                if not _struct_ok:
                    return (False, _total)
                if Store._legacy_audit_chain_allowed(cutoff=cutoff):
                    return (True, _total)
                warn("[审计] 旧版（首条缺 epoch）迁移审计链在 v2.11+ 已 fail-closed（不可信且容忍期已过）；"
                     "请运行 keygen/apply 重建带 epoch 的新链。")
                return (False, _total)
        _prev = ""
        for _ln in _lines:
            try:
                _e = json.loads(_ln)
            except Exception:
                return (False, _total)
            # v2.10.0（HIGH#3 / C-10）：中段/尾部条目若缺 epoch 或 epoch 不符 → fail-closed，
            # 封堵「首条带 epoch 进入严格校验后、中段注入无 epoch 伪造条目」攻击（Hermes r7 H-C）。
            if not isinstance(_e, dict) or not isinstance(_e.get("prev_hmac"), str) or not isinstance(_e.get("hmac"), str) or _e.get("prev_hmac") != _prev or _e.get("epoch") != LEDGER_KEY_EPOCH:
                return (False, _total)
            _payload = json.dumps({k: v for k, v in _e.items() if k != "hmac"}, separators=(",", ":"), sort_keys=True)
            _exp = hmac.new(_key, _payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(_e.get("hmac", ""), _exp):
                return (False, _total)
            _prev = _e.get("hmac", "")
        return (True, _total)

    def verify_script_integrity(self):
        """v2.5.2（M-5）+ v2.8.2 C-10 扩面 + v2.8.3 高-2 + v2.8.4 L-3：比对技能自身全部 17 个 shipped 运行时脚本（script: 前缀键，
        见 SCRIPT_NAMES）当前哈希与 D4 快照。

        返回 [(script_key, ok)]；未建立基线的脚本跳过（不在返回列表内）。
        供 cmd_verify 复用，亦供测试直接调用。"""
        gdata = read_json(self.integrity, {})
        out = []
        for name in self.SCRIPT_NAMES:
            skey = "script:" + name
            srec = gdata.get(skey)
            if srec is None:
                continue
            sp = self.script_dir / name
            if not sp.exists():
                out.append((skey, False))
                continue
            scur = self._hash_text(sp.read_text(encoding="utf-8"))
            _ok, _legacy = self._script_hash_matches(scur, srec.get("hash"), allow_legacy=Store._legacy_hash_allowed())
            if _legacy:
                warn("[完整性] 检测到 64-bit 旧格式基线哈希（{}）；已按首 16 字符判定未篡改，"
                     "建议运行 keygen/apply 自动升级为 128-bit 基线。".format(skey))
            out.append((skey, _ok))
        return out

    # ---------------------------------------------------------------- v2.6.0 外部锚（破 C-1）
    def external_trust_root(self):
        """v2.6.0/v2.7.0 外部锚（外部化根信任）。默认 legacy（no-op pass，行为同 v2.5.8）；
        启用后 check_pubkey_root 须额外通过外部 attestation / 带外确认，否则 fail-closed。
        CONTRACT.md 钉固指纹降级为次要交叉核对。

        v2.7.0 起外部锚权威来自**离线 RSA 根**：Agent 仅持公钥验签，对应私钥由人类离线持有，
        永不进入 Agent 可写域 → 证明/令牌**密码学层**不可伪造（INV-3/INV-4 通过）。

        ⚠️ 诚实边界（v2.7.1 重申）：v2.7.0 头条"C-1 逻辑层真正闭合"经 Hermes 2026-10-02 复验证伪已
        撤回——root_pubkey 仍存于 Agent 可写域 trust-root.json，C-1 循环论证**未真正闭合**（见 HANDOFF ⑦）。
        v2.8.0 收口：trust-root.json 经内嵌锚密钥签名、load 强制校验（无签名/不符→fail-closed），
        攻击者凭 ledger 写权限无密钥无法换 root_pubkey → C-1 在软件层闭合；残余边界为代码完整性
        （攻击者具代码写权限）及硬件 TPM / 独立只读介质（out-of-scope）。v2.8.1 对残余边界追加三层硬化：
        ① C-9 默认（源码内嵌共享）锚密钥不得启用外部锚（须专属 env 密钥或显式 ALLOW_DEFAULT）；
        ② C-10 D4 脚本完整性校验接入 cmd_retrieve 热路径为硬闸（受保护模式下漂移即拒）；
        ③ C-11 外部锚 fail-closed 默认（v2.8.1 为 opt-in：METACOG_REQUIRE_EXTERNAL_ANCHOR=1；v2.8.2 起改为
        默认 deny，向后兼容逃生舱 METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1），详见 CHANGELOG v2.8.1/v2.8.2。
        本方法在 build 前插入结构性 fail-closed 闸门 `trust_root.anchor_storage_outside_root`：证明存储
        (attestation_path/oob_token_dir) 须位于 Agent 可写域 root 之外，否则 DenyTrustRoot；另见 HIGH-1
        删除检出（check_pubkey_root 内）。残余"root 外但 Agent 仍可写"依赖 OS 权限隔离（部署契约）。"""
        if trust_root is None:
            return None
        cfg = trust_root.TrustRootConfig.load(self.root)
        # v2.7.1 fail-closed 结构性闸门：证明存储须位于 Agent 可写域(root)之外，否则攻击者可在可写域内
        # 换 root_pubkey + 自签证明/令牌 → C-1 主攻击向量。闸门在 build 之前，返回 DenyTrustRoot。
        gate = trust_root.anchor_storage_outside_root(cfg, self.root)
        if gate is not None:
            return trust_root.DenyTrustRoot(gate)
        return trust_root.build_trust_root(cfg)

    # ---------------------------------------------------------------- P0：人类身份根钉固（堵「Agent 替换公钥自签」）
    def human_pubkey_fingerprint(self):
        """当前 human-guard.json 公钥指纹（SHA-256 前 16 位，与 confirm --keygen 一致）。无密钥/形态非法返回 None。"""
        pub, _ = self.load_human_keys()
        # v2.5.6（M-6 闭环）：pubkey 必须是字符串（JSON 序列化公钥），否则视为无公钥
        # → 后继 check_pubkey_root 走 fail-closed（no-live-pubkey），避免对非 str 调 .encode 抛 AttributeError 逃逸 (bool, str) 契约。
        if not isinstance(pub, str):
            return None
        return hashlib.sha256(pub.encode("utf-8")).hexdigest()[:32]  # v2.5.3（F-5）：64-bit→128-bit，符合 RFC 8692

    def pinned_human_pubkey_fingerprint(self):
        """CONTRACT.md 钉固的公钥指纹（人类持有不动点）。占位符/缺失返回 None（legacy 兼容）。

        标记兼容 **human_pubkey_fingerprint** 等加粗写法：定位键名后取首个冒号后的值。"""
        cpath = self.root / "CONTRACT.md"
        if not cpath.exists():
            return None
        for ln in cpath.read_text(encoding="utf-8").splitlines():
            if "human_pubkey_fingerprint" in ln:
                after = ln.split("human_pubkey_fingerprint", 1)[1]
                if ":" in after:
                    val = after.split(":", 1)[1].strip().strip("`")
                    if val and not (val.startswith("<") and val.endswith(">")):
                        return val
        return None

    def check_pubkey_root(self):
        """P0 核心：验签所用公钥信任根裁决。

        v2.6.0（外部化根信任姿态）：引入外部锚作为**权威**根，叠加 AND 门：公钥须通过外部
        attestation（A 设备证明）/ 带外确认（B），否则 fail-closed；CONTRACT.md 钉固指纹
        降级为**次要交叉核对**（不符仅告警，不再作唯一裁决依据）。
        v2.5.2 起：未钉固 / 当前无公钥 一律 fail-closed 拒绝（不再 fail-open 放行）。

        v2.7.0（密码学层外部化）：外部锚权威来自**离线 RSA 根**——Agent 仅持公钥验签，
        私钥由人类离线持有（永不落 Agent 可写域）；证明/令牌因此**密码学层**不可伪造。

        ⚠️ 诚实边界（v2.7.1 重申）：v2.7.0"真正破 C-1 逻辑层"经 Hermes 2026-10-02 复验证伪已撤回——
        root_pubkey 仍存于 Agent 可写域 trust-root.json，C-1 循环论证**未真正闭合**（见 HANDOFF ⑦）。
        本方法插入两道 fail-closed 闸门：(a) v2.7.1 HIGH-1：已建立外部锚被删 → external-anchor-deleted；
        (b) 证明存储须位于 root 之外（见 external_trust_root）。残余"root 外但 Agent 仍可写"依赖 OS 隔离。"""
        pinned = self.pinned_human_pubkey_fingerprint()
        if not pinned:
            sys.stderr.write(
                "[metacog] WARN: 未钉固人类公钥信任根（CONTRACT.md 无指纹），按 fail-closed 拒绝"
                "（建议运行 `confirm --keygen` 钉固）。\n")
            return False, "no-pinned-root"
        live = self.human_pubkey_fingerprint()
        if live is None:
            return False, "no-live-pubkey"  # 钉固存在但当前无公钥 → 拒绝（而非放行）
        # v2.7.1 HIGH-1：外部锚曾建立（D4 有基线）但信任根文件被删 → 判定为删除攻击 → fail-closed，
        # 不再静默回退 legacy 使 C-1 失活而无告警（原 HIGH-1 残余）。
        if self._external_anchor_deleted():
            return False, "external-anchor-deleted"
        ext = self.external_trust_root()
        if ext is not None:
            # v2.6.3 H-1：DenyTrustRoot（corrupt / no-provider / unknown-backend / v2.7.1 inside-writable-root）
            # 直接 fail-closed 并透传细分 reason，避免被下方 oob 分支（oob_token_required 恒 True）误路由吞掉
            try:
                import trust_root as _tr
            except (ImportError, ModuleNotFoundError):
                return False, "external-anchor-corrupt"
            if isinstance(ext, _tr.DenyTrustRoot):
                return False, ext.reason
            # 外部锚以「序列化公钥」为锚定对象（设备证明/带外挑战均覆盖序列化公钥，而非指纹）
            pub_serialized, _ = self.load_human_keys()
            # B 人工带外 fail-closed：要求独立信道**签名**令牌（缺则拒绝）
            if ext.oob_token_required():
                # v2.7.0（闭环 N1）：challenge 绑定操作类型（LOW-1），令牌内容 = 挑战串的
                # 离线根 RSA 签名；即便 oob_token_dir 可写，无离线私钥者无法伪造（防复用/伪造）。
                ch = ext.challenge_for(pub_serialized, op="verify")
                sys.stderr.write(
                    "[metacog] 外部锚带外确认挑战: {}（请人类用离线根私钥对该挑战串签名，"
                    "将 base64 签名令牌写入 oob_token_dir 的 <挑战>.token 文件）\n".format(ch))
                if not ext.oob_confirmed(ch):
                    return False, "oob-confirmation-required"
            # A 设备证明：公钥须有离线根私钥签名的外部不可伪造证明（Agent 无私钥无法自造）
            ok_a, reason_a = ext.attestation_ok(pub_serialized, contract_fingerprint=pinned)
            if not ok_a:
                return False, "external-anchor-{}".format(reason_a)
            # 外部锚通过 = 密码学层外部化（Agent 仅持公钥验签，私钥离线持有，证明/令牌不可伪造）；
            # 但 C-1 循环论证未真正闭合（root_pubkey 仍处 Agent 可写域，见 HANDOFF ⑦）。
            # CONTRACT.md 指纹仅作交叉核对，不符仅告警，不再作唯一裁决依据。
            if live != pinned:
                sys.stderr.write(
                    "[metacog] WARN: CONTRACT.md 钉固指纹与当前公钥不符，但外部锚密码学层已通过；"
                    "请核对 CONTRACT.md 是否被误改（注意：C-1 未真正闭合，root_pubkey 仍处可写域，见 HANDOFF ⑦）。\n")
            return True, None
        # legacy（默认）：CONTRACT.md 钉固指纹为权威根（v2.5.8 行为）
        if live == pinned:
            return True, None
        return False, "pubkey-root-mismatch"

    def write_human_pubkey_fingerprint(self, fp):
        """把人类公钥指纹钉入 CONTRACT.md 的 human-identity-root 节（不动点，人类持有）。

        与 confirm --keygen 同进程执行（人类在 TTY 在场），落盘即钉固信任根。
        - CONTRACT.md 不存在 → 直接创建并钉固真实指纹（keygen 未 init 的极端情况）。
        - 节缺失 → 追加创建并钉固真实指纹（前向兼容：现存合法安装经 verify/apply 自动补钉固）。
        - 已有占位符 → 填入真实指纹。
        - 已有真实指纹但不符（疑似重新 keygen）→ 覆盖并告警（人类在 TTY 可核对打印值）。"""
        cpath = self.root / "CONTRACT.md"
        key = "human_pubkey_fingerprint"
        if not cpath.exists():
            cpath.write_text(
                "# 统一不动点契约（Unified Fixed-Point Contract）\n"
                "## 7. 人类身份根（human-identity-root）\n\n"
                "- **human_pubkey_fingerprint**: `{}`\n".format(fp),
                encoding="utf-8")
            return
        text = cpath.read_text(encoding="utf-8")
        if key not in text:
            # 旧安装无此节 → 追加创建并钉固真实指纹（前向兼容：现存合法安装自动补钉固）
            section = (
                "\n"
                "## 7. 人类身份根（human-identity-root）\n"
                "\n"
                "- **用途**：钉固 W1 人类闸的信任根。人类公钥指纹写入本不动点文件（人类持有），\n"
                "  `apply` / `verdict` 验签所用公钥必须与本指纹一致，否则一律拒绝（fail-closed）。\n"
                "- **human_pubkey_fingerprint**: `{}`\n".format(fp))
            cpath.write_text(text.rstrip() + "\n" + section, encoding="utf-8")
            return
        lines = text.splitlines()
        new_lines = []
        for ln in lines:
            if key in ln:
                pre, _, post = ln.partition(":")
                old_val = post.strip().strip("`")
                if old_val.startswith("<") and old_val.endswith(">"):
                    new_lines.append("{}: `{}`".format(pre, fp))  # 占位符 → 写入真实指纹
                elif old_val == fp:
                    new_lines.append(ln)  # 一致 → 保留
                else:
                    # 已有真实指纹但不符（重新 keygen）→ 覆盖并告警（人类在 TTY 可核对打印值）
                    sys.stderr.write(
                        "[metacog] WARN: CONTRACT.md 既有指纹 {} 与新生成指纹 {} 不一致，已覆盖"
                        "（疑似重新 keygen，请人工核对）。\n".format(old_val, fp))
                    new_lines.append("{}: `{}`".format(pre, fp))
            else:
                new_lines.append(ln)
        cpath.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def ensure_pubkey_root_pinned(self):
        """P0 前向兼容：现存安装若 CONTRACT.md 尚无钉固指纹，但 human-guard.json 合法存在，
        则把当前（合法）公钥指纹钉固为信任根。仅写一次——不覆盖既有真实值或不匹配值。

        用途：v2.5.1 之前的安装已生成过密钥对（keygen 幂等跳过生成），不会触发上面的写入；
        本方法保证现存合法安装在下次 verify/apply/keygen 时补钉固，避免长期停在 legacy 放行。"""
        if self.pinned_human_pubkey_fingerprint() is not None:
            return  # 已钉固
        live = self.human_pubkey_fingerprint()
        if live is None:
            return  # 无密钥，留给 keygen 处理
        self.write_human_pubkey_fingerprint(live)

    # ---------------------------------------------------------------- D5：字节级回滚点（默认留底）
    @property
    def rollback_log(self):
        return self.root / "ledger" / "rollback.jsonl"

    def record_rollback(self, proposal_id, artifact, entry_id, prev_text):
        """apply 前把被替换条目的旧文本存入 ledger，供 REVERT 时字节还原（非 git 仓库兜底）。"""
        append_jsonl(self.rollback_log, {
            "proposal_id": str(proposal_id),
            "artifact": artifact,
            "entry_id": entry_id,
            "prev_text": prev_text,
            "at": now_iso(),
        })

    def latest_rollback(self, artifact=None, entry_id=None):
        recs = read_jsonl(self.rollback_log)
        if artifact:
            recs = [r for r in recs if r.get("artifact") == artifact]
        if entry_id:
            recs = [r for r in recs if r.get("entry_id") == entry_id]
        return recs[-1] if recs else None

    # ---------------------------------------------------------------- P1：人类闸密码学绑定（人类签名绑定 trial_from_index，apply 时落锚）
    @property
    def human_guard(self):
        return self.root / "ledger" / "human-guard.json"

    def load_human_keys(self):
        """返回 (pub_serialized, priv_enc_blob)；未初始化返回 (None, None)。

        apply 只取 pub（验签用）；priv 加密落盘，Agent 进程永不持有解密口令。"""
        g = read_json(self.human_guard, None)
        if not g or "pubkey" not in g:
            return None, None
        return g.get("pubkey"), g.get("privkey_enc")

    def verify_human_binding(self, p, sig_b64, t0, anchor_chash=None):
        """W1（M-7 闭环）：验签人类**绑定**签名，覆盖 (id, chash, trial_from_index=t0)。返回 (ok, reason)。

        - (True, None)：绑定签名有效（签名覆盖 id+chash+t0），证明该提案确由人类确认且 t0 未被篡改。
        - (False, "legacy-unbound")：签名仅覆盖旧格式 (id, chash)，未绑定 t0 —— M-7 前旧锚/旧签名，
          攻击者可在保持验签通过的前提下改写 trial_from_index 绕过防过拟合保证，故一律 HOLD 要求重签。
        - (False, "content-hash-mismatch")：锚声明的 content_hash 与提案当前内容不符（提案被篡改）。
        - 其余 (False, reason)：no-crypto / no-pubkey / pubkey-root-mismatch / bad-pubkey /
          bad-sig-encoding / invalid-signature。

        anchor_chash：可选，若提供则额外校验其等于提案当前 chash（防 apply 后篡改提案绕过签名）。
        P0：验签前先校验公钥信任根（CONTRACT.md 钉固指纹），公钥被替换则拒绝（fail-closed）。"""
        if sigcrypto is None:
            return False, "no-crypto"
        root_ok, root_reason = self.check_pubkey_root()
        if not root_ok:
            return False, root_reason
        pub_serialized, _ = self.load_human_keys()
        if not pub_serialized:
            return False, "no-pubkey"
        try:
            sig = base64.b64decode(sig_b64)
        except Exception:
            return False, "bad-sig-encoding"
        chash = proposal_content_hash(p)
        if anchor_chash is not None and anchor_chash != chash:
            return False, "content-hash-mismatch"
        # v2.5.6（M-6 闭环）：deserialize_pub 对非 65537 指数 / 畸形公钥抛异常，须捕获以保持 (bool, str) 契约
        try:
            pub = sigcrypto.deserialize_pub(pub_serialized)
        except Exception:
            return False, "bad-pubkey"
        # 先验新绑定格式 (id, chash, t0)：M-7 要求签名覆盖 trial_from_index
        new_msg = sigcrypto.approval_message(str(p["id"]), chash, t0)
        if sigcrypto.verify(pub, new_msg, sig):
            return True, None
        # 再验旧格式 (id, chash)：通过则为 legacy-unbound（未绑定 t0），要求重签
        old_msg = sigcrypto.approval_message(str(p["id"]), chash)
        if sigcrypto.verify(pub, old_msg, sig):
            return False, "legacy-unbound"
        return False, "invalid-signature"

    def bind_human_signature(self, p, chash, t0, passphrase=None):
        """W1（M-7 闭环）：TTY 提示口令解锁私钥，对绑定消息 (id, chash, t0) 签名，返回 sig_b64。

        v2.5.7 合并方案：签名在 apply 时（t0 已知）当场生成，取代原 confirm --approve 单独签名。
        passphrase 为 None 时交互式 getpass 提示（需 TTY）；测试可显式传入以绕过 TTY。"""
        if sigcrypto is None:
            raise RuntimeError("sigcrypto 模块缺失，无法签名（确认 sigcrypto.py 与 metacog.py 同目录）")
        guard = read_json(self.human_guard, None)
        if not guard or "privkey_enc" not in guard:
            raise RuntimeError("尚未生成人类密钥对，请先 `confirm --keygen`")
        if passphrase is None:
            passphrase = getpass.getpass("私钥解锁口令: ")
        try:
            priv_json = sigcrypto.decrypt_priv_str(guard["privkey_enc"], passphrase)
        except Exception:
            raise RuntimeError("口令错误，无法解密私钥（确认口令；忘记则 `confirm --init` 重置）")
        if not _priv_n_matches(guard, priv_json):
            raise RuntimeError("口令错误（解密出的私钥与公钥不匹配）")
        priv = sigcrypto.deserialize_priv(priv_json)
        msg = sigcrypto.approval_message(str(p["id"]), chash, t0)
        sig = sigcrypto.sign(priv, msg)
        return base64.b64encode(sig).decode("ascii")


# ---------------------------------------------------------------- v2.8.6 N-5/N-7：集中脚本完整性硬闸
def _script_integrity_drift_if_enforced(st):
    """v2.8.6（替代 apply/resign/retrieve/keygen 四处复制粘贴的同款逻辑，关 N-7 重复 + N-5 静默 fail-open）：
    集中计算脚本完整性硬闸漂移。
    仅当外部锚已启用（受保护模式）或 METACOG_TRUST_ROOT_STRICT=1 时强制；
    integrity.json 不存在（未建基线）→ 不触发（全新/未基线部署不误伤）。
    external_trust_root() 抛错时打 warn 并降级为仅依赖 STRICT（不再静默 fail-open）。
    返回 (enforced, drift_list)；drift_list 非空即脚本基线漂移。"""
    if not st.integrity.exists():
        return (False, [])
    _anchor = False
    try:
        _anchor = st.external_trust_root() is not None
    except Exception as _e:
        warn("[完整性-硬闸] 外部锚检测异常（{}），降级为仅依赖 STRICT 环境变量；"
             "若非预期请核查 trust-root.json 与部署契约。".format(type(_e).__name__))
        _anchor = False
    if not (_anchor or os.environ.get("METACOG_TRUST_ROOT_STRICT", "").lower() == "1"):
        return (False, [])
    _drift = [k for k, ok in st.verify_script_integrity() if not ok]
    return (True, _drift)


# ---------------------------------------------------------------- v2.8.9 ⑤：manifest 分文件硬闸
def _manifest_integrity_drift_if_enforced(st):
    """v2.8.9 ⑤：可信清单分文件硬闸——Hermes H-01 收口 F-4 纸面闭环（H-3 攻击链）。
    仅当外部锚已启用（受保护模式）或 METACOG_TRUST_ROOT_STRICT=1 时强制；未建基线 → 不触发。
    阻断集（内容篡改，须人类确认后重基线方可解除）：
      - SKILL.md 正文变更（仅版本号变更豁免，因版本升级必改 SKILL.md 头）；
      - CONTRACT.md / HANDOFF.md / pack.sh 任一内容变更。
    非阻断（仅 dirty 计数）：CHANGELOG.md（版本升级产物）。
    返回 (enforced, drift_list)；drift_list 非空即阻断态 manifest 漂移。"""
    if not st.integrity.exists():
        return (False, [])
    _anchor = False
    try:
        _anchor = st.external_trust_root() is not None
    except Exception as _e:
        warn("[完整性-硬闸] 外部锚检测异常（{}），降级为仅依赖 STRICT 环境变量。".format(type(_e).__name__))
        _anchor = False
    if not (_anchor or os.environ.get("METACOG_TRUST_ROOT_STRICT", "").lower() == "1"):
        return (False, [])
    data = read_json(st.integrity, {})
    _allow_legacy = Store._legacy_hash_allowed()
    _drift = []
    for _name in st.MANIFEST_NAMES:
        _key = "manifest:" + _name
        _rec = data.get(_key)
        if _rec is None:
            continue
        _mp = st.root / _name
        if not _mp.exists():
            _drift.append(_key)
            continue
        _mtext = _mp.read_text(encoding="utf-8")
        _mcur = st._hash_text(_mtext)
        _ok, _ = st._script_hash_matches(_mcur, _rec.get("hash"), allow_legacy=_allow_legacy)
        if _name == "SKILL.md" and not _ok:
            # 仅版本号变更（正文哈希一致）→ 豁免（不阻断）
            _body_rec = data.get("manifest:SKILL.md@body")
            if _body_rec is not None:
                _bok, _ = st._script_hash_matches(st._skill_body_hash(_mtext), _body_rec.get("hash"), allow_legacy=_allow_legacy)
                if _bok:
                    _ok = True
        if _name == "CHANGELOG.md":
            continue  # 非阻断（版本升级产物）
        if not _ok:
            _drift.append(_key)
    # v2.8.9 ④：STRICT/外部锚下，若仍有 16-char 残余基线未迁移 → 强制迁移（拒绝 apply/retrieve/keygen 直至 record 升级为 128-bit）。
    # 使 __meta__.legacy_remaining 计数器具备真实强制力（Hermes N-2：此前仅写入、无读取，属过度声明）。
    _legacy_remaining = data.get("__meta__", {}).get("legacy_remaining", 0)
    if _legacy_remaining and _legacy_remaining > 0:
        _drift.append("__meta__:legacy-remaining:{}".format(_legacy_remaining))
    return (True, _drift)


# ---------------------------------------------------------------- 制品条目解析


def parse_entries(text: str):
    out = []
    for m in ENTRY_RE.finditer(text):
        out.append(
            {
                "id": m.group("id"),
                "status": m.group("status"),
                "since": m.group("since"),
                "src": m.group("src"),
                "body": m.group("body").strip(),
                "span": m.span(),
            }
        )
    return out


def render_entry(eid, status, since, src, body) -> str:
    head = "<!-- entry:{} status:{} since:{}".format(eid, status, since)
    if src:
        head += " src:{}".format(src)
    head += " -->"
    return "{}\n{}\n<!-- /entry:{} -->".format(head, body.strip(), eid)


def set_entry_status(text: str, eid: str, status: str) -> str:
    def repl(m):
        if m.group("id") != eid:
            return m.group(0)
        return render_entry(eid, status, m.group("since"), m.group("src"), m.group("body"))

    return ENTRY_RE.sub(repl, text)


def remove_entry(text: str, eid: str) -> str:
    def repl(m):
        return "" if m.group("id") == eid else m.group(0)

    return re.sub(r"\n{3,}", "\n\n", ENTRY_RE.sub(repl, text))


# ---------------------------------------------------------------- init

SEED = {
    "CONTRACT.md": """# 统一不动点契约（Unified Fixed-Point Contract）

> **单一真相源（SSOT）**：本文件统一定义 **SHE（L3 自进化安全护栏）** 与 **metacog（L2 元层）** 共享的**不动点**。
> 两 skill 引擎各自独立（SHE 从失败轨迹做安全硬化，metacog 从日常会话做通用自改进），但共享同一套 substrate 与闸门定义。
> 任何一处对四工件、三硬闸、三道闸或双指标棘轮的描述，都以本文件为准；本文件被改动后，运行时的 `.metacog/CONTRACT.md` 应同步更新。

## 1. 四工件 = 唯一 substrate（结构不可变，内容可演化）

SHE 的「护栏四工件」与 metacog 的「A1–A4」是**同一组东西**，1:1 对应：

| SHE 工件 | metacog 制品 | 管什么 | 演化约束 |
|---|---|---|---|
| `system_prompt` | A1 系统提示 | 角色与行为基线 | 谨慎，需 ≥2 次独立证据 |
| `rule_bank` | A2 规则库 | 具体做法条目 | 主战场，可增删改 |
| `safety_memory` | A3 安全记忆 | 踩过的坑 | **只增不减（append-only）** |
| `tool_policy` | A4 工具策略 | 工具/权限边界 | 需 ≥2 次独立证据 |

> 四工件的**划分结构**是不动点：不得合并、不得新增第 5 个 substrate 工件。
> `M1 元层策略` 是 metacog 专属的**演化机制**（不在 SHE 范围内），不是 substrate；它可演化，但改动必须人类确认。

## 2. 越用越聪明的量化定义（双指标棘轮）

- `utility`（0~1）：任务达成度，滑动窗口均值必须**不降**（容差 ε=0.02）
- `violation_rate`：违规/返工率，必须**严格不升**
- 两条同时满足才允许沉淀，否则回滚。任何一条退化即视为误演化。
- 此双指标**包含并泛化** SHE 的「安全-效用闸门（Gate B）」：`S(候选) > S(当前)` 且 `U(候选) ≥ U(当前)`。

## 3. 统一闸门集（不可削弱）

### SHE 三道硬闸（L3 安全特化，非跳过）
| # | 闸门 | 判定标准 | 不通过处理 |
|---|------|----------|-----------|
| A | 先备份 | 写回前必须存当前护栏快照（带时间戳） | 未备份则中止 |
| B | 安全-效用验证 | `S(候选) > S(当前)` 且 `U(候选) ≥ U(当前)` | 进拒收池，不写回 |
| C | 拒收池去重 | 同一补丁被拒后后续轮不再重试 | 自动跳过 |

### metacog 三道闸（G1–G3，通用超集）
- **G1 写入闸**：不动点保护 → 红线扫描 → A3 只增不减 → 证据门槛（≥2 次）
- **G2 检索闸**：revoked 条目不可检索（光删不够，未来执行者捞不到）
- **G3 人类确认闸**：M1 或高风险条目 `apply` 需人类在 TTY 输入口令，对「提案 id + 内容哈希 + 试用窗起点」签绑定签名（W1/M-7；`--human-ok` 布尔旗标 AI 可自签，已废除）

> SHE 的 A/B/C 是 G1/G2 在「安全工件」上的特化实现；二者并集为统一不动点闸门集，**任一不得削弱**。

## 4. 引擎不可动文件（自指不动点）

- **metacog 引擎**：`CONTRACT.md` / `metacog.py` / `SKILL.md`（Agent 禁止修改）
- **SHE 引擎**：`evolve_guard.py` 中的三硬闸 + 棘轮 + 冷启动保护逻辑为不可削弱的实现；要改逻辑须走独立审计（如 `unclekk-audit-then-optimize`）

## 5. 验收窗口

`window = 5`（试用期需累计 5 个 episode 才裁决）

## 6. L1→L2 回流与 M1 约束（闭环接缝）

L1 优化器（skill-optimizer / unclekk-skill-library 等）的棘轮裁决是 L2 元层 A2/M1 的证据来源。回流约定：

- 每个 L1 优化器的 `applied` / `reverted`（或 `ACCEPTED` / `REJECTED`）裁决，若 `.metacog/ledger/` 存在，必须追加一条 episode：
  - 连续 `reverted` / `REJECTED` → 归因 **A2**（判断错了）
  - 同一对象连续 ≥3 次 `reverted` / `REJECTED` → 归因 **M1**（找改法的方式有问题）
  - 连续 `applied` / `ACCEPTED` 且分数上升 → 正向 episode，utility 给高值
- 🛑 **只能写 ledger，不得改写 `artifacts/` 或碰 `CONTRACT.md`**。

**M1 约束 L1 选型**：当 ledger 显示某类任务连续 `reverted` ≥3 次，M1 触发元层自省，重新决定用哪种 L1 优化器（darwin 9维评分 ↔ skill-evolver 补丁式迭代 ↔ skill-library 任务级沉淀），并将结论沉淀回 M1。这样 L1 的实战经验真的回流进"改进行为的机制"，自指闭环在接缝处合拢。

---

## 7. 人类身份根（human-identity-root）

- **用途**：钉固 W1 人类闸的信任根。人类公钥指纹写入本不动点文件（人类持有），
  `apply` / `verdict` 验签所用公钥必须与本指纹一致，否则一律拒绝（fail-closed）。
- **human_pubkey_fingerprint**: `<待 confirm --keygen 钉固>`

---

*本契约由 `metacog-self-evolve` skill 承载，作为 SHE(L3) 与 metacog(L2) 的统一不动点定义。2026-09-06 合并确立。*
""",
    "artifacts/A1-system-prompt.md": """# A1 · 系统提示 / 行为基线

> 制品类型：SHE-A1。改动谨慎，需 ≥2 次独立证据。

<!-- entry:A1-000 status:active since:{today} -->
- 结论先行，不铺垫。做不到就说原因，不编造。
<!-- /entry:A1-000 -->
""",
    "artifacts/A2-rule-bank.md": """# A2 · 规则库

> 制品类型：SHE-A2。演化主战场——具体做法沉淀在这里。
> 状态：candidate（证据不足）→ trial（试用期）→ active（已沉淀）→ revoked（已撤销）

<!-- entry:R-000 status:active since:{today} -->
- 动手前先确认目标文件是否存在，不假设路径。
<!-- /entry:R-000 -->
""",
    "artifacts/A3-safety-memory.md": """# A3 · 安全记忆（APPEND-ONLY）

> 制品类型：SHE-A3。**只增不减**——教训一旦写入永不删除，
> 否则自演化会先把"别再犯"这条记忆演化掉，然后重犯。

<!-- entry:S-000 status:active since:{today} -->
- 对个人目录（桌面/下载/文档）的批量操作：先只扫描出报告，不动文件。
<!-- /entry:S-000 -->
""",
    "artifacts/A4-tool-policy.md": """# A4 · 工具与权限策略

> 制品类型：SHE-A4。工具选择与权限边界，需 ≥2 次证据。

<!-- entry:T-000 status:active since:{today} -->
- 文件检索用专用检索工具，不用 shell find/grep 拼装。
<!-- /entry:T-000 -->
""",
    "meta/M1-evolve-policy.md": """# M1 · 元层演化策略（可被演化 → 自指闭包）

> 这份文件规定"如何提议修改"。它自己也是可演化对象——
> 这正是 HyperAgents 的元认知自修改：不只改行为，还改"改进行为的方式"。
> 但每次改动**必须人类确认**（CONTRACT §3.4）。

## 归因优先级
出问题时按此顺序找责任制品，避免乱改：
1. 重复踩同一个坑 → A3
2. 用错工具 / 越权 → A4
3. 具体做法错 → A2
4. 角色/风格偏移 → A1
5. **改过但没用 / 反复改同一处 → M1（改进方式本身有问题）**

## 提议标准
- 一条提议只改一个制品，只解决一个归因
- 必须写清"哪个 episode 暴露的问题"
- 描述必须可执行（"下次先跑 X 再跑 Y"），不要写"要更小心"这类无法验证的话

## 元层自省触发条件
满足任一即提议修改本文件：
- 连续 3 轮裁决全部 revert（说明提议方式有系统性问题）
- 同一处被反复改动 ≥3 次（说明归因错了）
- utility 趋势连续两窗口不升（说明当前演化机制已失效）

<!-- entry:M-000 status:active since:{today} -->
- 提议前先读最近 5 条 episode，不凭印象改。
<!-- /entry:M-000 -->
""",
}


def cmd_init(st: Store, args):
    st.root.mkdir(parents=True, exist_ok=True)
    created, skipped = [], []
    for rel, content in SEED.items():
        p = st.root / rel
        if p.exists():
            skipped.append(rel)
            continue
        write_text(p, content.replace("{today}", today()))
        created.append(rel)
    st.quarantine.mkdir(parents=True, exist_ok=True)
    (st.root / "ledger").mkdir(parents=True, exist_ok=True)
    if not st.ratchet.exists():
        st.set_ratchet(st.get_ratchet())
        created.append("ledger/ratchet.json")
    # 操作 4：元层参数化（参数级自指）——写 M1-evolve-policy.json（缺失才写，保留用户自定义）
    mp = st.artifact_path("M1").with_suffix(".json")
    if not mp.exists():
        mp.parent.mkdir(parents=True, exist_ok=True)
        write_json(mp, {
            "version": 1,
            "ratchet": {
                "epsilon": EPSILON,
                "default_window": DEFAULT_WINDOW,
                "min_evidence": MIN_EVIDENCE,
            },
            "_comment": "引擎可解析的元层参数；改这里 = 真的改机制（参数级自指）。"
                        "metacog.py 属不动点不可改，仅本参数可演化。文件缺失/非法 → 回落内置默认值（fail-safe）。",
        })
        created.append("meta/M1-evolve-policy.json")
    # D4：初始化后即记录制品完整性快照（堵直写绕过：verify 可检出非经 apply 的篡改）
    for code in ARTIFACTS:
        st.record_integrity(code)
    info("初始化完成: {}".format(st.root))
    for c in created:
        ok("创建 " + c)
    for s in skipped:
        info("  [skip] 已存在 " + s)
    info("\n下一步: 每次任务结束后 `episode` 记账，发现问题用 `propose` 提改动。")
    return 0


# ---------------------------------------------------------------- episode


# ---------------------------------------------------------------- 操作 3：归因一致性
# SHE「归因引导演化」：失败必须归到正确的制品，否则会反复改错地方
# （重复踩坑→A3，用错工具→A4，做法错→A2）。两件事：
#   (1) attributed 必填 —— cmd_episode 内的 fail-closed 硬闸（见上）。
#   (2) 归因漂移告警 —— 记录的 attributed 与证据事件签名明显不符时给出可操作警示（不阻断记账）。
# 设计为「软告警」而非「硬阻断」：避免 D3 式过度严格误报，把最终判断权留给人类。

def _attribution_suggestion(events, violations):
    """由负向事件签名推导「应归因制品」。仅在有强信号时给建议，弱信号返回 (None, "")。

    优先级：安全(红线/约束) > 工具(闸门/人工修补) > 行为(回退/重做/纠正)。
    对应 SHE 四制品语义：安全记忆 A3、工具策略 A4、规则条目 A2。
    """
    ev = events or {}
    v = violations or 0
    if v > 0 or ev.get("violation", 0) > 0:
        return "A3", "命中红线/约束事件，应记入安全记忆 A3（append-only，永不删除）"
    if ev.get("gate_block", 0) > 0 or ev.get("manual_fix", 0) > 0:
        return "A4", "闸门拦截/人工修补，多指向工具与权限策略 A4"
    if ev.get("revert", 0) > 0 or ev.get("rework", 0) > 0 or ev.get("correction", 0) > 0:
        return "A2", "回退/重做/纠正，多指向做法或规则条目 A2"
    return None, ""


def detect_attribution_drift(ep):
    """对比记录的 attributed 与证据事件签名；明显归因漂移则返回告警文本，否则 None。

    告警策略（保守、低误报）：
      - 安全事件（A3 建议）被归到任何非 A3 → 必告警：安全教训不进安全记忆会丢失。
      - 具体失败（A2/A4 建议）被错归到安全(A3)/元层(M1) → 告警：该类制品不应承接具体失败。
      - 相邻制品（A2↔A4）之间不告警：工具问题导致重做等情况本就相邻，避免误报。
    M1 是「如何演化」的元层规则本身，不应承接具体一次任务的成败归因。
    """
    attributed = ep.get("attributed")
    suggested, reason = _attribution_suggestion(ep.get("events"), ep.get("violations"))
    if suggested is None or not attributed:
        return None
    if attributed == suggested:
        return None
    # 安全事件必须落到安全记忆：归到任何非 A3 都告警
    if suggested == "A3" and attributed != "A3":
        return ("[归因漂移] 证据指向 A3（{}），但本次归因为 {}——安全事件应记入 A3，"
                "否则安全教训不会进入永不删除的安全记忆。".format(reason, attributed))
    # 具体失败被错归到安全/元层：稀释该制品本职语义
    if attributed in ("A3", "M1") and suggested in ("A2", "A4"):
        return ("[归因漂移] 证据指向 {}（{}），但本次归因为 {}——具体失败不应归到 {}，"
                "会稀释该制品的本职语义。".format(suggested, reason, attributed, attributed))
    return None


def cmd_episode(st: Store, args):
    # --- 收集可观测事件（来自任意工作流）---
    events = {}
    if args.events_json:
        try:
            raw = json.loads(args.events_json)
            if not isinstance(raw, dict):
                raise ValueError("必须是 JSON 对象")
            events.update(raw)
        except Exception as ex:
            print("错误: " + add_fix("--events-json 必须是 JSON 对象，如 {\"rework\":1}",
                "示例：--events-json '{\"rework\":1,\"accepted\":1}'",
                "解析失败：{}".format(ex)), file=sys.stderr)
            return 2
    for kv in (args.events or []):
        k, sep, v = kv.partition("=")
        if not sep:
            print("错误: " + add_fix("--events 需 key=count 形式",
                "示例：--events rework=1 --events accepted=1",
                "收到：{}".format(kv)), file=sys.stderr)
            return 2
        try:
            events[k.strip()] = events.get(k.strip(), 0) + int(v)
        except ValueError:
            print("错误: " + add_fix("--events 计数必须是整数",
                "示例：--events rework=1", "收到：{}".format(kv)), file=sys.stderr)
            return 2
    known = set(META_EVENTS)
    unknown = [k for k in events if k not in known]
    if unknown:
        print("错误: " + add_fix("未知事件类型 {}".format(", ".join(unknown)),
            "可用事件：{}".format(", ".join(META_EVENTS)),
            "未知事件不计入效用"), file=sys.stderr)
        return 2
    events = {k: max(0, int(v)) for k, v in events.items() if max(0, int(v)) > 0}

    derived_u, prov = (None, None)
    if events:
        derived_u, prov = compute_utility(events)
    declared_u = args.utility  # 可选、已废弃：操作 1 前过渡用
    if declared_u is not None and not (0.0 <= declared_u <= 1.0):
        # fail-closed：越界声明值直接拒（保持 0~1 契约，也防 argparse 越界漏检）
        print("错误: " + add_fix("--utility 必须在 0~1",
            "改用 --events 推导效用（推荐），不读命令行数字",
            "收到：{}".format(declared_u)), file=sys.stderr)
        return 2

    if derived_u is None and declared_u is None:
        print("错误: " + add_fix("必须提供 --events（推荐）或 --utility",
            "操作 1 起效用由可观测事件推导：--events rework=1 --events accepted=1",
            "无事件时只能退回 --utility（声明式，不驱动沉淀）"), file=sys.stderr)
        return 2
    # 操作 3（归因一致性）：attributed 必填（fail-closed 硬闸，与 utility 缺失同级）。
    # 不放在 argparse required，以便复用 add_fix 给出可操作指引、且退出码 2 行为统一。
    if args.attributed is None:
        print("错误: " + add_fix("--attributed 必填：每次 episode 必须明确归因到哪个制品",
            "用 `--attributed` 从 A1/A2/A3/A4/M1 中选一个",
            "A1=系统提示 A2=规则库 A3=安全记忆(永不删) A4=工具策略 M1=元层演化策略"),
            file=sys.stderr)
        return 2
    if derived_u is not None and declared_u is not None:
        print("注意: 同时给了 --events 与 --utility，以推导值 {} 为准，申报值 {} 忽略".format(
            derived_u, declared_u), file=sys.stderr)

    source = "derived" if derived_u is not None else "declared"
    utility = derived_u if derived_u is not None else declared_u

    if declared_u is not None:
        alert = check_utility_consistency(declared_u, events)
        if alert:
            warn(alert)

    # 操作 3：归因漂移检测（纯函数，不依赖效用来源；仅作告警，不阻断记账）
    drift = detect_attribution_drift({
        "attributed": args.attributed,
        "events": events,
        "violations": args.violations,
    })

    ep = {
        "id": new_id("E"),
        "at": now_iso(),
        "task": args.task,
        "utility": round(utility, 4),
        "utility_source": source,
        "events": events,
        "utility_provenance": prov,
        "violations": args.violations,
        "attributed": args.attributed,
        "attribution_drift": drift is not None,
        "note": args.note or "",
    }
    append_jsonl(st.episodes, ep)
    if source == "derived":
        ok("记账 {} 效用={}（由事件推导：{}）".format(ep["id"], ep["utility"], prov or "无负向事件"))
    else:
        warn("记账 {} 效用={}（声明式 deprecated，不驱动沉淀）".format(ep["id"], ep["utility"]))
    # 操作 3：归因漂移告警（不阻断记账，仅提示归因是否合理）
    if drift:
        warn(drift)
    r = st.get_ratchet()
    # 操作 4：元层参数化（参数级自指）——M1-evolve-policy.json 存在时以其为参数源；
    # 缺失/非法/越界时回落内置默认值（load_meta_policy 已保证），但「无文件」时尊重棘轮既有
    # window/epsilon（保持向后兼容，等价于 fail-safe 默认值），避免覆盖测试/旧流自定义的窗口。
    _policy, _src = load_meta_policy(st)
    if _src == "file":
        r["window"] = _policy["default_window"]
        r["epsilon"] = _policy["epsilon"]
    eps_all = read_jsonl(st.episodes)
    pool = eligible_eps(eps_all)
    if r["baseline_utility"] is None and len(pool) >= r["window"]:
        w = pool[-r["window"]:]
        if w and all(e.get("utility_source") != "derived" for e in w):
            warn("  基线仍基于声明式 utility（尚未积累推导数据）；推导数据到齐后自动切换。")
        r["baseline_utility"] = round(sum(e["utility"] for e in w) / len(w), 4)
        r["baseline_violation_rate"] = round(
            sum(1 for e in w if e["violations"] > 0) / len(w), 4
        )
        st.set_ratchet(r)
        ok("基线已建立: utility={} violation_rate={}".format(
            r["baseline_utility"], r["baseline_violation_rate"]))
    elif r["baseline_utility"] is None:
        info("  基线未建立 ({}/{} episodes)".format(len(pool), r["window"]))
    print(ep["id"])
    return 0


# ---------------------------------------------------------------- propose


def cmd_propose(st: Store, args):
    if args.artifact not in ARTIFACTS:
        print("错误: " + add_fix("制品必须是 {}".format(", ".join(ARTIFACTS)),
            "用 `--artifact` 从 A1/A2/A3/A4/M1 中选一个",
            "A1=系统提示 A2=规则库 A3=安全记忆 A4=工具策略 M1=元层演化策略"),
            file=sys.stderr)
        return 2
    content = args.content
    if args.content_file:
        content = read_text(Path(args.content_file))
    if args.op in ("add", "replace") and not content:
        print("错误: " + add_fix("add/replace 需要 --content 或 --content-file",
            "直接写正文：`--content \"你的条目正文\"`",
            "或从文件读：`--content-file ./draft.md`"), file=sys.stderr)
        return 2
    if args.op in ("replace", "remove") and not args.target:
        print("错误: " + add_fix("replace/remove 需要 --target <entry-id>",
            "先用 `retrieve --artifact {}` 或 `status` 查目标条目 ID".format(args.artifact),
            "entry-id 形如 A1-001 / R-003 / M1-002，过闸后不变"),
            file=sys.stderr)
        return 2
    p = {
        "id": new_id("P"),
        "created": now_iso(),
        "artifact": args.artifact,
        "op": args.op,
        "target": args.target,
        "content": content or "",
        "reason": args.reason or "",
        "episodes": args.episode or [],
        "status": "quarantined",
        "requires_human": False,
        "gate": None,
    }
    st.save_proposal(p)
    ok("提议已入隔离区 {} ({} {})".format(p["id"], args.op, args.artifact))
    info("  隔离区不是生效区——必须先 `gate` 过闸，再 `apply` 才进入试用期。")
    print(p["id"])
    return 0


# ---------------------------------------------------------------- G1 写入闸


# D3 修复：不动点检查。原实现全文匹配文件名 → 连「禁止修改 metacog.py」这类保护规则也被
# BLOCK（fail-closed 过严，见 poc/可控自指-PoC审计报告.md D3）。改为：仅当 content 出现
# 「动作动词 + 不动点文件名」（任一方向）且不在否定/保护语境时才 BLOCK；纯提及（如「本引擎由
# metacog.py 实现」）或保护语境（如「禁止修改 metacog.py」）放行。
#
# #3 硬化（v2.25.1 维护）：把「禁改类硬约束」从「动词+文件名」正则 denylist 升级为「目标身份 + 路径
# 解析」结构级校验。原实现要求命中 (动词+文件名) 双向正则 → LLM 改写动词即可绕过（PoC-1 实测 6 条
# 语义等价有 4 条曾绕过）。新实现：触发源 = 受保护目标 identity（文件名/可解析路径，不可在不改变
# 指代下改写）+ 动词无关的「改动意图」信号（覆盖近义），命中即 BLOCK；否定/保护语境仍放行。
# 诚实残余：完全不含目标身份/路径的语义改写（如「对核心调度逻辑做调优」）仍靠人类在环兜底。
_IMMUTABLE_NEG = r"(禁止|严禁|不要|不得|勿|避免|不建议|拒绝|不允许|不可|不能|不该|不应该|切勿)"
# 受保护目标身份（文件名即不变身份，无法改写指代）；由 IMMUTABLE_TARGETS 动态构建
_IMMUTABLE_IDENT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in IMMUTABLE_TARGETS) + r")\b", re.I)
# 路径片段：任何可解析到受保护文件的引用（绝对/相对/子目录前缀），结构级
_IMMUTABLE_PATH_HINT_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|[/\\]|(?:scripts|meta)[/\\]|(?:\.\./)+)?"
    r"(?:" + "|".join(re.escape(t) for t in IMMUTABLE_TARGETS) + r")\b", re.I)
# 改动意图信号：动词无关、覆盖近义，封闭 PoC-1「改写动词」空隙
_IMMUTABLE_EDIT_INTENT_RE = re.compile(
    r"(修改|编辑|更新|改动|调整|改|写|替换|重构|优化|调优|变更|变动|修订|改掉|重做|重写|"
    r"改一下|动一下|动到|触及|削弱|放宽|移除|去掉|精简|删除|清理|废弃|"
    r"rewrite|update|modify|edit|change|tweak|refactor|patch|tune|alter|revise|weaken|relax|"
    r"remove|delete|drop)\b", re.I)


def _immutable_violation(blob):
    """结构级禁改校验：返回被指向的受保护目标 identity，或 None。
    触发 = 受保护目标 identity（文件名/可解析路径）命中 且 存在未被直接否定的改动意图。"""
    targets = set(h.lower() for h in _IMMUTABLE_IDENT_RE.findall(blob)) | \
              set(h.lower() for h in _IMMUTABLE_PATH_HINT_RE.findall(blob))
    if not targets:
        return None
    # 是否存在「未被否定」的改动意图
    for m in _IMMUTABLE_EDIT_INTENT_RE.finditer(blob):
        pre3 = blob[max(0, m.start() - 3):m.start()]
        if re.search(r"不|别|莫|无需|不必|未尝|未", pre3):
            continue  # 直接否定（不改动/别修改）→ 该意图作废
        ctx = blob[max(0, m.start() - 24):min(len(blob), m.end() + 24)]
        if re.search(_IMMUTABLE_NEG, ctx, re.I):
            continue  # 强否定语境（禁止修改 X）→ 放行
        return sorted(targets)[0]
    return None


def run_gate(st: Store, p):
    """SafeEvolve 写入闸：返回 (verdict, checks, requires_human)"""
    # 操作 4：元层参数化（参数级自指）——证据门槛取 M1-evolve-policy.json（fail-safe 回落默认值）
    policy, _ = load_meta_policy(st)
    checks = []
    verdict = "pass"
    requires_human = False
    blob = "{}\n{}".format(p.get("content", ""), p.get("reason", ""))

    # 1. 不动点保护：自指必须有截断（D3 修复：仅「动作指向不动点」才 BLOCK，排除保护语境）
    imm = _immutable_violation(blob)
    if imm:
        checks.append(("BLOCK", "不动点保护", add_fix(
            "触及人类持有的 {}，禁止自改".format(imm),
            "移除对 {} 的改动指令，只允许改五制品 A1-A4/M1 的内容".format(imm))))
        verdict = "block"
    if p["artifact"] not in ARTIFACTS:
        checks.append(("BLOCK", "制品越界", add_fix(
            "未声明的制品 " + str(p["artifact"]),
            "--artifact 只能用 A1/A2/A3/A4/M1 之一")))
        verdict = "block"

    # 2. 红线扫描（Practice Makes Unsafe：不安全的成功也会沉淀）
    for name, pat in REDLINES:
        if re.search(pat, blob, re.I):
            checks.append(("BLOCK", "红线-" + name, add_fix(
                "命中禁止模式「{}」".format(name),
                "删除触发该红线的指令后重新 propose")))
            verdict = "block"

    # 2b. 语义级升级（CONTRACT L47）：命中「绕过安全确认/削弱护栏」意图 → 升级需人类确认。
    # 仅在未硬 BLOCK 时升级（硬 BLOCK 已是终态）；真实兜底是人类在环 + 双指标棘轮。
    if verdict != "block":
        for name, pat in SEMANTIC_RISK:
            if re.search(pat, blob, re.I):
                requires_human = True
                checks.append(("HUMAN", "语义风险-" + name, add_fix(
                    "疑似意图绕过安全确认/削弱护栏（语义级，非字面禁用词）",
                    "应用该提案时，人类在 TTY 运行 `apply` 交互式输入口令签绑定签名把关")))
                break

    # 3. A3 append-only：教训不可被演化掉
    if p["artifact"] == "A3" and p["op"] != "add":
        checks.append(("BLOCK", "A3 只增不减", add_fix(
            "安全记忆禁止 {} 操作".format(p["op"]),
            "改用 op=add 追加新教训，旧教训不可删改")))
        verdict = "block"

    # 4. 证据门槛：一次成功不足以沉淀
    n_ev = len(p.get("episodes") or [])
    if p["op"] == "add" and p["artifact"] in ("A1", "A2", "A4") and n_ev < policy["min_evidence"]:
        checks.append(("HOLD", "证据不足", add_fix(
            "需 ≥{} 个 episode，当前 {}".format(policy["min_evidence"], n_ev),
            "propose 时加 `--episode E001 --episode E002` 引用真实证据 ID",
            "或先多记几次 `episode` 再回来提改动")))
        if verdict == "pass":
            verdict = "hold"
    else:
        checks.append(("OK", "证据门槛", "{} 个 episode 引用".format(n_ev)))

    # 5. 元层改动必须人类确认（自指安全阀）
    if p["artifact"] == "M1":
        requires_human = True
        checks.append(("HUMAN", "元层改动", add_fix(
            "M1 属元认知层，需人类确认",
            "应用该提案时，人类在 TTY 运行 `apply --id <提案>` 交互式输入口令签绑定签名才落盘")))

    # 6. 高风险升级
    for name, pat in HIGH_RISK:
        if re.search(pat, blob, re.I):
            requires_human = True
            checks.append(("HUMAN", "高风险-" + name, add_fix(
                "命中高风险模式，需人类确认",
                "apply 时人类绑定签名校验通过才落盘")))

    if verdict == "pass" and not any(c[0] == "BLOCK" for c in checks):
        checks.append(("OK", "红线扫描", "未命中禁止模式"))
    return verdict, checks, requires_human


def cmd_gate(st: Store, args):
    items = st.proposals()
    if args.id:
        items = [p for p in items if p["id"] == args.id]
    items = [p for p in items if p["status"] in ("quarantined", "blocked", "hold")]
    if not items:
        info("隔离区没有待审提议。")
        return 0
    n_pass = 0
    for p in items:
        verdict, checks, rh = run_gate(st, p)
        info("\n{} · {} {} {}".format(p["id"], p["op"], p["artifact"], p.get("target") or ""))
        for level, name, detail in checks:
            line = "{} — {}".format(name, detail)
            if level == "BLOCK":
                bad(line)
            elif level == "HOLD":
                warn(line)
            elif level == "HUMAN":
                print("  [HUMAN] " + line)
            else:
                ok(line)
        p["gate"] = {"verdict": verdict, "checks": checks, "at": now_iso()}
        p["requires_human"] = rh
        p["status"] = {"pass": "gated", "hold": "hold", "block": "blocked"}[verdict]
        st.save_proposal(p)
        info("  => 裁定: {}{}".format(verdict.upper(), "（需人类确认）" if rh else ""))
        if verdict == "pass":
            n_pass += 1
        if verdict == "block":
            append_jsonl(st.archive, {
                "at": now_iso(), "proposal": p["id"], "action": "blocked",
                "artifact": p["artifact"], "reason": [c[1] for c in checks if c[0] == "BLOCK"],
            })
    info("\n过闸 {}/{} 条。".format(n_pass, len(items)))
    return 0


# ---------------------------------------------------------------- apply


def cmd_apply(st: Store, args):
    st.ensure_pubkey_root_pinned()  # P0 前向兼容：现存合法安装补钉固信任根
    # v2.8.4 M-4：受信锚落盘（apply 是最危险动作——持久化受信任变更）前，先核验技能自身脚本完整性；
    # 若与既有基线漂移则拒绝 apply（防基于被篡改代码把恶意提案持久化为受信任变更）。
    # 仅当外部锚已启用（受保护模式）或 METACOG_TRUST_ROOT_STRICT=1 时强制；未建基线者不触发
    # （verify_script_integrity 仅核验已建基线脚本，全新/未基线部署不误伤）。
    _a_enforced, _a_drift = _script_integrity_drift_if_enforced(st)
    if _a_drift:
        bad("[完整性-硬闸] 以下技能脚本哈希与基线不一致，拒绝 apply（最危险动作须基于未篡改代码）：{}；"
            "请以 `verify` 核查并 `rollback` 还原，或人工确认后重基线。".format(", ".join(_a_drift)))
        return 3
    # v2.8.9 ⑤：可信清单分文件硬闸（Hermes H-01 收口 F-4 纸面闭环）——手改 SKILL.md/CONTRACT/HANDOFF/pack.sh 内容 → 拒绝（防 H-3 攻击链洗白）
    _m_enforced, _m_drift = _manifest_integrity_drift_if_enforced(st)
    if _m_drift:
        bad("[完整性-硬闸] 以下可信清单内容哈希与基线不一致，拒绝 apply（疑似被篡改）：{}；"
            "请以 `verify` 核查并 `rollback` 还原，或人工确认后重基线。".format(", ".join(_m_drift)))
        return 3
    st.record_script_integrity()  # v2.5.2（M-5）：受信锚落盘时刷新技能脚本基线
    items = [p for p in st.proposals() if p["status"] == "gated"]
    if args.id:
        items = [p for p in items if p["id"] == args.id]
    if not items:
        info("没有过闸待应用的提议（先跑 `gate`）。")
        return 0
    applied = 0
    human_blocked = 0
    gate_blocked = 0  # P2-3：闸门重放被拦计数
    for p in items:
        # P2-3：apply 侧轻量闸门重放（fail-closed）——直写隔离区 JSON 把 status 改成
        # gated 可绕过 G1（PoC 审计 P2-3），此处对 BLOCK 级检查（红线/不动点/制品越界/
        # A3 只增不减）做最后一次重放；HOLD/HUMAN 不重放（证据门槛已在 gate 时把关，
        # 且 M1 的 HUMAN 由下方交互式人类签名闸（apply 时 TTY 口令签绑定签名）处理）。重放异常按拦截处理（fail-closed）。
        try:
            _, _replay_checks, _ = run_gate(st, p)
            _blocks = [c for c in _replay_checks if c[0] == "BLOCK"]
        except Exception as _e:  # 提案字段缺失/类型异常 → 视为非法，拦截
            gate_blocked += 1
            bad(add_fix("{}: apply 闸门重放异常（{}），按拦截处理".format(p.get("id", "?"), _e),
                "提案 JSON 字段不完整或类型异常；请重新 propose 生成合法提案"))
            continue
        if _blocks:
            gate_blocked += 1
            names = "、".join(c[1] for c in _blocks)
            bad(add_fix("{}: apply 闸门重放被拦（{}），拒绝写入".format(p["id"], names),
                "提案内容命中红线/不动点/制品越界/A3 只增不减；"
                "gate 之后被直改过的提案过不了 apply 这关，请修改内容后重新 propose"))
            continue
        _human_sig = None  # 受信任锚签名（仅 requires_human 提案在下方块内赋值；非 requires_human 锚无签名）
        if p.get("requires_human"):
            # W1（M-7 闭环）：人类签名绑定 trial_from_index，须在 apply 时（t0 已知）计算/验签。
            # ① 带 --sig：验绑定签名（覆盖 id+chash+t0）；② 否则交互式 TTY 提示口令、当场签绑定消息
            #    （apply 时签名绑定，合并原 confirm --approve）。--human-ok 布尔旗标 AI 可自签，仍废除。
            _t0 = len(read_jsonl(st.episodes))  # 与下方 record_apply 同值，先算用于验签/签名
            _sig_arg = getattr(args, "sig", None)
            if _sig_arg:
                ok_v, reason = st.verify_human_binding(p, _sig_arg, _t0)
                if ok_v:
                    _human_sig = _sig_arg
                else:
                    human_blocked += 1
                    if getattr(args, "human_ok", False):
                        bad(add_fix("{}: --human-ok 已废除（P1：布尔旗标 AI 可自签，不算人类确认），退出码 2".format(p["id"]),
                                    "人类在 TTY 运行 `apply --id {}` 交互式输入口令签绑定签名".format(p["id"])))
                    elif reason == "no-pubkey":
                        bad(add_fix("{}: 尚未初始化人类闸（无私钥）".format(p["id"]),
                                    "先运行 `confirm --keygen` 生成 RSA 密钥对"))
                    elif reason == "legacy-unbound":
                        bad(add_fix("{}: 人类签名为 M-7 前旧格式（未绑定 trial_from_index），v2.5.7 起须绑定签名".format(p["id"]),
                                    "请重新在 TTY 运行 `apply --id {}` 交互式签绑定签名（或预生成覆盖 id+chash+t0 的绑定签名经 --sig 传入）".format(p["id"])))
                    elif reason == "content-hash-mismatch":
                        bad(add_fix("{}: 受信任锚 content_hash 与提案当前内容不符（提案被篡改）".format(p["id"]),
                                    "提案内容已被改动，需重新生成过闸提案与绑定签名"))
                    elif reason in ("invalid-signature", "bad-sig-encoding"):
                        bad(add_fix("{}: 人类绑定签名无效（伪造/篡改/编码错误）".format(p["id"]),
                                    "请重新在 TTY 运行 `apply --id {}` 交互式签绑定签名".format(p["id"])))
                    elif reason == "pubkey-root-mismatch":
                        bad(add_fix("{}: 人类公钥信任根不匹配（pubkey-root-mismatch）：CONTRACT.md 钉固指纹与当前公钥不符，疑似公钥被替换".format(p["id"]),
                                    "检查 human-guard.json 与 CONTRACT.md 是否被篡改；"
                                    "确认无误后重新运行 `confirm --keygen` 钉固信任根"))
                    elif reason == "bad-pubkey":
                        bad(add_fix("{}: 人类公钥解析失败（bad-pubkey）：human-guard.json 中公钥损坏/被篡改".format(p["id"]),
                                    "检查 human-guard.json 是否被篡改；确认无误后重新运行 `confirm --keygen` 重建密钥"))
                    else:
                        warn("{} 需人类确认（D1：无有效人类绑定签名视为未确认，退出码 2）；"
                             "请人类在 TTY 运行 `apply --id {}` 交互式输入口令签绑定签名".format(p["id"], p["id"]))
                    continue
            else:
                if getattr(args, "human_ok", False):
                    human_blocked += 1
                    bad(add_fix("{}: --human-ok 已废除（P1：布尔旗标 AI 可自签，不算人类确认），退出码 2".format(p["id"]),
                                "人类在 TTY 运行 `apply --id {}` 交互式输入口令签绑定签名".format(p["id"])))
                    continue
                if not _require_tty():
                    human_blocked += 1
                    bad(add_fix("{}: 人类确认闸需在真实终端交互运行（当前非 TTY），无法签名".format(p["id"]),
                                "请人类亲自打开终端执行 `apply --id {}`；agent 不得代替人类运行 apply 签名".format(p["id"])))
                    continue
                try:
                    _chash_bind = proposal_content_hash(p)
                    _human_sig = st.bind_human_signature(p, _chash_bind, _t0)
                except Exception as _e:
                    human_blocked += 1
                    bad(add_fix("{}: 人类签名失败（{}）".format(p["id"], _e),
                                "确认口令；忘记则 `confirm --init` 重置；或预生成绑定签名经 --sig 传入"))
                    continue
        path = st.artifact_path(p["artifact"])
        text = read_text(path)
        _old = None  # D5：被改条目的旧文本（replace/remove 分支填入），供字节级回滚
        if p["op"] == "add":
            prefix = {"A1": "A1", "A2": "R", "A3": "S", "A4": "T", "M1": "M"}[p["artifact"]]
            existing = [e["id"] for e in parse_entries(text)]
            n = 1
            while "{}-{:03d}".format(prefix, n) in existing:
                n += 1
            eid = "{}-{:03d}".format(prefix, n)
            # A3 教训直接 active（不该让教训等试用期）；其余进 trial 试用期
            status = "active" if p["artifact"] == "A3" else "trial"
            block = render_entry(eid, status, today(), p["id"], p["content"])
            text = text.rstrip() + "\n\n" + block + "\n"
        elif p["op"] == "replace":
            if p["target"] not in [e["id"] for e in parse_entries(text)]:
                bad(add_fix("{}: 目标条目 {} 不存在".format(p["id"], p["target"]),
                    "用 `retrieve --artifact {}` 查当前有效 ID".format(p["artifact"]),
                    "确认 ID 拼写（形如 A1-001），过闸后条目 ID 不变"))
                continue
            eid = p["target"]
            status = "trial"
            # D5：记录被替换条目的旧文本，供 REVERT 时字节还原（非 git 仓库兜底）
            _old = next((m.group(0) for m in ENTRY_RE.finditer(text) if m.group("id") == eid), None)

            def _repl(m, _eid=eid, _p=p):
                if m.group("id") != _eid:
                    return m.group(0)
                return render_entry(_eid, "trial", today(), _p["id"], _p["content"])

            text = ENTRY_RE.sub(_repl, text)
        elif p["op"] == "remove":
            eid = p["target"]
            if eid not in [e["id"] for e in parse_entries(text)]:
                bad(add_fix("{}: 目标条目 {} 不存在".format(p["id"], eid),
                    "用 `retrieve --artifact {}` 查当前有效 ID".format(p["artifact"]),
                    "确认 ID 拼写（形如 A1-001），过闸后条目 ID 不变"))
                continue
            status = "revoked"
            _old = next((m.group(0) for m in ENTRY_RE.finditer(text) if m.group("id") == eid), None)
            text = set_entry_status(text, eid, "revoked")
        else:
            bad(add_fix("未知操作 " + str(p["op"]),
                "op 应为 add/replace/remove（内部异常，请反馈）"))
            continue
        write_text(path, text)
        # D4：更新制品完整性快照（堵直写绕过）；D5：记录字节级回滚点（非 git 仓库兜底）
        st.record_integrity(p["artifact"])
        if _old is not None:
            st.record_rollback(p["id"], p["artifact"], eid, _old)
        p["status"] = "trial"
        p["entry_id"] = eid
        p["trial_since"] = now_iso()
        p["trial_from_index"] = len(read_jsonl(st.episodes))
        # W1（M-7 闭环）：受信任锚内嵌人类**绑定**签名（覆盖 id+chash+trial_from_index），关闭 7.1 直写伪造锚
        _chash = proposal_content_hash(p)  # H-1（v2.5.8）：所有锚均内嵌 content_hash 绑定提案内容（含非 requires_human），关闭盲信 t0
        st.record_apply(p["id"], p["trial_from_index"], p["artifact"], p["entry_id"], _human_sig, _chash)
        st.save_proposal(p)
        ok("{} 已应用到 {} → 条目 {} 状态 {}".format(p["id"], p["artifact"], eid, status))
        applied += 1
    if applied:
        info("\n{} 条进入试用期。累计 {} 个新 episode 后跑 `verdict` 裁决。".format(
            applied, st.get_ratchet()["window"]))
    # D5：git 留底默认开启（root 为 git 仓库时），除非显式 --no-git。兜底回滚点默认就有。
    git_on = bool(args.git) or (not getattr(args, "no_git", False)
                               and os.path.isdir(os.path.join(str(st.root), ".git")))
    if git_on:
        _git_commit(st, "metacog: apply {} proposal(s)".format(applied))
    if gate_blocked:
        bad("{} 条被 apply 闸门重放拦截（P2-3，fail-closed，退出码 2）".format(gate_blocked))
        return 2
    if human_blocked:
        bad("{} 条因缺人类确认被拦截（退出码 2）".format(human_blocked))
        return 2
    return 0


def _git_commit(st: Store, msg):
    """把 root 内的改动提交到 root 自身的 git 仓库（非破坏、可追溯）。

    R1 修复要点：
    - 必须在 root 内执行 git（cwd=root）。否则 git 会向上找到父仓库，
      把 root 当 gitlink 误提交，污染父仓历史（实测导致 34+ 噪声提交）。
    - root 非 git 仓库时直接报错跳过，绝不静默污染父仓。
    - git add/commit 失败要明确上报，禁止打印「已留底」假阳性。
    """
    try:
        root = str(st.root)
        if not os.path.isdir(os.path.join(root, ".git")):
            bad("root 非 git 仓库（缺 {}/.git），--git 留底跳过；"
                "如需留底请先在 root 内执行 `git init`".format(root))
            return 1
        # 关键：cwd=root，确保提交落在 metacog 自己的仓库内
        a = subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, text=True)
        if a.returncode != 0:
            err = (a.stdout or a.stderr).strip()
            bad(add_fix("git add 失败: " + (err.splitlines()[0] if err else "未知错误"),
                "检查 .git 目录完整性与文件权限；可手动在 root 内 `git add -A` 排查"))
            return a.returncode
        r = subprocess.run(["git", "commit", "-m", msg], cwd=root, capture_output=True, text=True)
        if r.returncode == 0:
            ok("git commit 已留底（root 内）")
            return 0
        err = (r.stdout or r.stderr).strip()
        if "nothing to commit" in err:
            info("  [git] 无新改动，跳过提交")
            return 0
        bad(add_fix("git commit 失败: " + (err.splitlines()[0] if err else "未知错误"),
            "若报 author identity：在 root 内先 `git config user.name/user.email`",
            "确认 cwd 为 root（脚本已自动处理，正常无需手动）"))
        return r.returncode
    except FileNotFoundError:
        info("  [git] 未安装 git，跳过留底")
        return 1


# ---------------------------------------------------------------- verdict（双指标棘轮）


def _stats(eps):
    if not eps:
        return None, None
    u = round(sum(e["utility"] for e in eps) / len(eps), 4)
    v = round(sum(1 for e in eps if e["violations"] > 0) / len(eps), 4)
    return u, v


def compute_utility(events):
    """纯函数：由可观测事件推导效用（0~1）。返回 (utility, provenance)。

    provenance 记录命中的事件计数，可审计、可复算。绝对不读命令行数字，
    因此「改命令行数字提高 utility」在结构上不可行。"""
    ev = {}
    for k, v in (events or {}).items():
        try:
            n = max(0, int(v))
        except (TypeError, ValueError):
            n = 0
        if n:
            ev[k] = n
    penalty = sum(EVENT_WEIGHTS.get(k, 0) * c for k, c in ev.items())
    boost = sum(POSITIVE_WEIGHTS.get(k, 0) * c for k, c in ev.items())
    u = max(0.0, min(1.0, round(UTILITY_BASE - penalty + boost, 4)))
    prov = {k: ev[k] for k in ev if k in EVENT_WEIGHTS or k in POSITIVE_WEIGHTS}
    return u, prov


def eligible_eps(eps):
    """演进切换（操作 1 的牙齿）：一旦存在 derived 效用数据，
    验收与基线只取 derived；此前（仅声明式 utility）回落为全部，调用方应告警。
    结果：声明式 utility 不再能驱动「改进沉淀」，旧数据不删但被架空。"""
    derived = [e for e in (eps or []) if e.get("utility_source") == "derived"]
    if derived:
        return derived
    return list(eps or [])


def check_utility_consistency(declared, events):
    """注水嫌疑：高申报效用却伴随负向事件。返回告警串或 None。"""
    if declared is None or not events:
        return None
    red = ("rework", "correction", "violation", "manual_fix", "revert")
    hit = {k: events[k] for k in red if events.get(k, 0)}
    if declared >= 0.8 and hit:
        return "[注水嫌疑] 申报 utility={} 较高，却伴随负向事件 {}".format(declared, hit)
    return None


def compute_adaptive_threshold(baseline: float, violation_rate: float) -> float:
    """棘轮自适应阈值（Phase 1.2，纯函数，不依赖 ratchet 状态）。

    根据当前窗口的违规率动态返回「效用不低于此值才可 promote」的建议阈值：
    - violation_rate > ADAPTIVE_VR_HIGH（0.3）：风险高 → 收紧（baseline × 0.95）
    - violation_rate < ADAPTIVE_VR_LOW（0.1）：风险低 → 放宽（baseline × 1.05）
    - 中间区间：保持基线 baseline
    仅为局部判定阈值，不修改 ratchet 持久状态；基准 baseline 仍由双指标棘轮维护。
    """
    if violation_rate > ADAPTIVE_VR_HIGH:
        return baseline * (1 - ADAPTIVE_ADJUST)
    if violation_rate < ADAPTIVE_VR_LOW:
        return baseline * (1 + ADAPTIVE_ADJUST)
    return baseline


def _normalize_cited(p, all_eps):
    """归一化 episodes(cited) 字段：处理 dict/str 型（#6）、幽灵 id（#4），返回 (valid_set, ghost_list, pos)。"""
    raw = p.get("episodes") or []
    if isinstance(raw, dict):
        raw = list(raw.keys())          # dict 型 → 取 keys
    elif not isinstance(raw, (list, tuple, set)):
        raw = [raw]
    ids = [str(c) for c in raw]         # 统一 str 化（set({"a":1}) 取 keys 得字符串）
    pos = {e.get("id"): i for i, e in enumerate(all_eps)}
    valid = [c for c in ids if c in pos]
    ghost = [c for c in ids if c not in pos]
    return set(valid), ghost, pos


def resolve_trial_start(st, p, all_eps):
    """v2.2.4：trial_from_index 的唯一可信来源 = 受信任锚 apply_record。

    返回 (start, hold_reason)：hold_reason 为 None 表示可继续裁决；否则为 HOLD 原因串。

    受信任锚由 cmd_apply 在人类确认闸（apply 时 TTY 口令签绑定签名，M-7）约束下写入，记录 apply 时刻的 episode 数
    （= 试用窗起点，引擎自算而非 proposer 自选）。verdict 只读此锚，彻底忽略提案自带字段。

    v2.2.4 变更：彻底删除 v2.2.3 的「降级一致性闸门」。该闸门的下界 lb 取自 proposer 自选的
    cited 字段（见 v2.2.3 ❌ REJECTED 复验）：攻击者把 cited 与 trial_from_index 改到自洽即绕过
    —— 向量A cited=[] fx=0 窗=全部含引用证据 → PROMOTE；向量B cited=[E3] fx=3 把最差样本移出窗
    → PROMOTE。下界来自攻击者输入本身就是假防御（"没锁的门不该存在"）。
    → 无受信任锚（未经人类确认闸）的 proposal 一律 HOLD，不采信其任何自带字段。
    """
    valid_cited, ghost, pos = _normalize_cited(p, all_eps)
    if ghost:
        warn("  {} 引用了 {} 条不存在的 episode（幽灵 id），已忽略：{}".format(
            p["id"], len(ghost), ", ".join(sorted(ghost))))
    rec = st.latest_apply_record(p["id"])
    if rec is not None:
        # H-2（v2.5.8）：applies.jsonl 整体被直写篡改 → 所有锚不可信，HOLD（fail-closed）。
        # 无基线（v2.5.8 前安装 / 尚未 apply）不误伤；有基线且不符说明文件被改。
        if not st.applies_integrity_ok():
            return 0, "受信任锚所在 applies.jsonl 与 D4 完整性快照不符（疑似被直写篡改），trial_from_index 不可信，HOLD"
        # M-8 类型守卫：trial_from_index 必须是 int，否则锚被污染 → HOLD（fail-closed）。
        # 旧版 int(rec["trial_from_index"]) 对 "abc"/[1]/null/缺键会抛 TypeError 逃逸 (int, str) 契约。
        t0_raw = rec.get("trial_from_index")
        # M-8（v2.5.8）补 bool 缺口：必须用严格类型判定，排除 bool 子类
        # （isinstance(True, int) is True 会漏网，使 True 被当 1 逃逸 (int, str) 契约）。
        if type(t0_raw) is not int:
            return 0, "受信任锚 trial_from_index 非严格 int（含 bool/str/list/null/缺键，疑似被篡改），trial_from_index 不可信，HOLD"
        t0 = t0_raw
        # W1 加固：锚内嵌人类绑定签名 → 必须先验签，否则 Agent 直写 applies.jsonl 伪造锚即生效（7.1）。
        sig = rec.get("human_sig")
        chash = rec.get("content_hash")
        if sig and chash and sigcrypto is not None:
            pub_serialized, _ = st.load_human_keys()
            if pub_serialized:
                # P0：验签前先校验公钥信任根，公钥被替换则拒绝（fail-closed）。
                root_ok, root_reason = st.check_pubkey_root()
                if not root_ok:
                    return 0, "受信任锚验签公钥信任根不符（{}），trial_from_index 不可信，HOLD".format(root_reason)
                # v2.5.6（M-6 闭环）：deserialize_pub 抛异常须捕获，保持 (start, hold_reason) 契约
                try:
                    pub = sigcrypto.deserialize_pub(pub_serialized)
                except Exception:
                    return 0, "受信任锚公钥解析失败（bad-pubkey），trial_from_index 不可信，HOLD"
                # M-7 闭环：验绑定签名（覆盖 id+chash+t0），旧格式(仅id+chash)→legacy-unbound→HOLD；
                # 锚声明的 content_hash 同时比对提案当前内容（防 apply 后篡改提案绕过签名）。
                ok_b, reason_b = st.verify_human_binding(p, sig, t0, anchor_chash=chash)
                if ok_b:
                    return t0, None
                if reason_b == "legacy-unbound":
                    return 0, ("受信任锚人类签名为 M-7 前旧格式（未绑定 trial_from_index），"
                               "v2.5.7 起须绑定签名，trial_from_index 不可信，HOLD")
                if reason_b == "content-hash-mismatch":
                    return 0, "受信任锚 content_hash 与提案当前内容不符（提案被篡改），HOLD"
                return 0, "受信任锚人类签名无效（{}），trial_from_index 不可信，HOLD".format(reason_b)
            # 有 sig 但无公钥（极端：guard 被删/移走）：无法验签 → 按 fail-closed HOLD，
            # 绝不降级信任伪造锚（否则攻击者删 guard 后直写 applies.jsonl 可操纵试用窗起点）。
            return 0, "受信任锚含人类签名但公钥缺失（无法验签），trial_from_index 不可信，HOLD"
        # B.2 加固：requires_human 提案的锚必须携带有效人类签名才可信。
        # 缺签名的「无签名锚」一律 HOLD（否则 Agent 直写 applies.jsonl 伪造无签名锚即可
        # 操纵试用窗起点，绕过人类确认闸）。非 requires_human 提案的锚本就无签名，
        # 属遗留合法状态，仍信任既有锚（兼容）。
        if p.get("requires_human"):
            if sigcrypto is None:
                return 0, "requires_human 提案的受信任锚缺签名且 sigcrypto 不可用（无法验签），trial_from_index 不可信，HOLD"
            return 0, "requires_human 提案的受信任锚缺少人类签名（W1 前旧锚或 Agent 直写伪造），trial_from_index 不可信，HOLD"
        # v2.5.2（C-4）：sigcrypto 不可用时，任何受信任锚都无法验签 → 统一 HOLD（fail-closed），
        # 绝不降级信任旧锚（否则攻击者只需让 import sigcrypto 失败即可绕过验签）。
        if sigcrypto is None:
            return 0, "sigcrypto 不可用，无法验签受信任锚，trial_from_index 不可信，HOLD"
        # H-1（v2.5.8）：非 requires_human 无签名锚不再盲信 trial_from_index。
        # v2.5.8 起锚内嵌 cmd_apply 落盘的 content_hash（绑定提案内容）；若锚带 content_hash 则必须
        # 与提案当前内容一致，否则说明锚或提案被直写篡改 → HOLD（fail-closed）。
        # 旧版锚 content_hash 为 None（未绑定）→ 仅由 int 类型守卫 + applies.jsonl D4 快照（H-2）保护。
        _rec_chash = rec.get("content_hash")
        if _rec_chash is not None and _rec_chash != proposal_content_hash(p):
            return 0, "非 requires_human 受信任锚 content_hash 与提案当前内容不符（疑似被直写篡改），trial_from_index 不可信，HOLD"
        # 非 requires_human 无签名锚：遗留合法，t0 已通过 int 类型守卫 + content_hash 校验（若有）+ applies.jsonl D4 快照，信任既有锚（兼容）。
        return t0, None
    # v2.2.4：无受信任锚 = 未经受信任闸门（人类确认），任何自带字段均不可信，一律 HOLD。
    # 不做「自己证明自己没造假」的降级校验（那道闸门的下界来自攻击者输入，是假防御）。
    return 0, "无 apply_record：未经受信任闸门（人类确认），trial_from_index 不可信，HOLD"


def cmd_resign(st: Store, args):
    """M-4（v2.5.8）：重签已有受信任锚——把 legacy-unbound（M-7 前旧格式签名，仅覆盖 id+chash）
    或任何待升级锚，重新签绑定签名（覆盖 id+chash+trial_from_index），保留原始试用窗起点 t0。

    不重写制品、不重算 episode 数；仅追加一条带绑定签名的新锚（verdict 读 latest_apply_record）。
    人类须在 TTY 交互式输入口令（或经 --sig 预生成覆盖 id+chash+t0 的绑定签名传入）。

    用法：resign --id <pid>  [--sig <base64>]"""
    st.ensure_pubkey_root_pinned()  # P0 前向兼容：现存合法安装补钉固信任根
    # v2.8.5 M-2'（对称 M-4）：resign 重签受信锚落盘前，先核验技能脚本完整性；
    # 与 cmd_apply 同条件/同硬闸（外部锚激活或 METACOG_TRUST_ROOT_STRICT=1 时强制），漂移则拒绝。
    _r_enforced, _r_drift = _script_integrity_drift_if_enforced(st)
    if _r_drift:
        bad("[完整性-硬闸] 以下技能脚本哈希与基线不一致，拒绝 resign（须基于未篡改代码）：{}；"
            "请以 `verify` 核查并 `rollback` 还原，或人工确认后重基线。".format(", ".join(_r_drift)))
        return 3
    st.record_script_integrity()    # v2.5.2（M-5）：受信锚落盘时刷新技能脚本基线
    if not getattr(args, "id", None):
        bad(add_fix("resign 需指定 --id", "resign --id <proposal_id>"))
        return 2
    p = st.find_proposal(args.id)
    if p is None:
        bad(add_fix("resign: 找不到提案 {}".format(args.id), "用 `retrieve` / `status` 查提案 id"))
        return 2
    old = st.latest_apply_record(args.id)
    if old is None:
        bad(add_fix("resign: 提案 {} 尚无受信任锚（未 apply 过）".format(args.id),
                    "尚无锚无需重签；若提案已 gated 请直接 `apply --id {}` 签名落锚".format(args.id)))
        return 2
    t0_raw = old.get("trial_from_index")
    # N1'（v2.5.8 收口）：与 resolve_trial_start 的 M-8 守卫对齐——严格类型判定，
    # 排除 bool 子类（isinstance(True,int) is True 漏网）及 str/list/null/缺键，避免 int() 裸奔逃逸 (int, str) 契约。
    if type(t0_raw) is not int:
        bad(add_fix("resign: 受信任锚 trial_from_index 非严格 int（含 bool/str/list/null/缺键，疑似被篡改）",
                    "请重新 `apply --id {}` 签名落锚".format(args.id)))
        return 2
    t0 = t0_raw
    chash = proposal_content_hash(p)  # 绑定到提案当前内容
    _sig_arg = getattr(args, "sig", None)
    if _sig_arg:
        ok_v, reason = st.verify_human_binding(p, _sig_arg, t0, anchor_chash=chash)
        if not ok_v:
            bad(add_fix("resign: 传入的绑定签名无效（{}）".format(reason),
                        "请在 TTY 运行 `resign --id {}` 交互式签绑定签名".format(args.id)))
            return 2
        sig = _sig_arg
    else:
        if not _require_tty():
            bad(add_fix("resign: 人类确认需在真实终端交互运行（当前非 TTY）",
                        "请人类亲自打开终端执行 `resign --id {}`".format(args.id)))
            return 2
        try:
            sig = st.bind_human_signature(p, chash, t0)
        except Exception as _e:
            bad(add_fix("resign: 人类签名失败（{}）".format(_e),
                        "确认口令；忘记则 `confirm --init` 重置"))
            return 2
    # 追加新锚：保留原始 t0，写入绑定签名 + 当前 content_hash；不触碰制品/episode。
    st.record_apply(p["id"], t0, old.get("artifact"), old.get("entry_id"), sig, chash)
    ok("{} 受信任锚已重签为绑定签名（trial_from_index 保留为 {}，试用窗起点不变）".format(args.id, t0))
    return 0


def cmd_verdict(st: Store, args):
    r = st.get_ratchet()
    # 操作 4：元层参数化（参数级自指）——M1-evolve-policy.json 存在时以其为参数源；
    # 缺失时尊重棘轮既有 window/epsilon（向后兼容 + fail-safe）。
    _policy, _src = load_meta_policy(st)
    if _src == "file":
        r["window"] = _policy["default_window"]
        r["epsilon"] = _policy["epsilon"]
    if r["baseline_utility"] is None:
        info("基线未建立，无法裁决（先累计 {} 个 episode）。".format(r["window"]))
        return 0
    trials = [p for p in st.proposals() if p["status"] == "trial"]
    all_eps = read_jsonl(st.episodes)
    if not trials:
        info("没有处于试用期的改动。")
    for p in trials:
        # v2.2.3：trial_from_index 由受信任锚 apply_record 提供，提案自带字段不可信（P0 修复）
        start, hold_reason = resolve_trial_start(st, p, all_eps)
        if hold_reason is not None:
            warn("{} 留出集验收被拦截（HOLD）：{}".format(p["id"], hold_reason))
            # 修复 #5：HOLD 也写 meta-cognition.log，使伪造路径可审计（不再与正常 PROMOTE 同形不可辨）
            log_metacognition(st, "verdict_hold",
                              context={"trigger": "verdict", "proposal": p["id"],
                                       "reason": hold_reason,
                                       "trial_from_index_field": p.get("trial_from_index"),
                                       "has_apply_record": st.latest_apply_record(p["id"]) is not None},
                              analysis={},
                              action={"verdict": "HOLD", "reason": "trial_from_index 不可信"},
                              insight="trial_from_index 完整性校验未通过，HOLD 不裁决")
            continue
        # 操作 2：held-out 验收 —— 验收集 = 试用后产生的泛化数据 all_eps[start:]，
        # start 来自受信任锚 apply_record（v2.2.3），与 proposer 自选的 cited 彻底解耦。
        # 注释「结构性封死」的准确范围仅限 cited 字段（6.3）；trial_from_index 现由引擎持有（P0 v2.2.3）。
        cited = set(str(c) for c in (p.get("episodes") or []))
        pos = {e.get("id"): i for i, e in enumerate(all_eps)}
        suspicious = [cid for cid in cited if pos.get(cid, -1) >= start]
        if suspicious:
            warn("  {} 检测到 {} 条 cited episode 位于试用窗内（疑似篡改；引擎从不按 cited 剔除验收集，仍按完整留出集验收）".format(
                p["id"], len(suspicious)))
        trial_window = all_eps[start:]
        if cited:
            info("  {} 留出集验收：试用窗 {} 条，训练集引用 {} 条(pre-trial)，异常/篡改引用 {} 条".format(
                p["id"], len(trial_window), len([c for c in cited if pos.get(c, -1) < start]), len(suspicious)))
        else:
            info("  {} 留出集验收：试用窗 {} 条，未引用训练集 episode，整窗即留出集".format(
                p["id"], len(trial_window)))
        # 操作 1 牙齿：留出集内只取 derived 效用（eligible_eps）
        window_eps = eligible_eps(trial_window)
        if window_eps and all(e.get("utility_source") != "derived" for e in window_eps):
            warn("  {} 验收窗口仅含声明式 utility（无推导数据）；"
                 "声明式不驱动沉淀，建议补 --events 记账后再裁决。".format(p["id"]))
        # 关键：留出集为空或不足 → HOLD，绝不回落训练集放行（防过拟合自证）
        if len(window_eps) == 0:
            warn("{} 留出集为空（试用窗无 episode），无法验收，HOLD".format(p["id"]))
            continue
        if len(window_eps) < r["window"] and not args.force:
            info("{} 留出集不足 ({}/{} episodes)，HOLD —— 不回落训练集放行".format(
                p["id"], len(window_eps), r["window"]))
            continue
        u, v = _stats(window_eps)
        if getattr(args, "adaptive", False):
            threshold = compute_adaptive_threshold(r["baseline_utility"], v)
            info("\n{} · {} {}".format(p["id"], p["artifact"], p.get("entry_id") or ""))
            info("  utility  {:.4f} vs 基线 {:.4f}  (Δ{:+.4f})  {}".format(
                u, r["baseline_utility"], u - r["baseline_utility"], "PASS" if u >= r["baseline_utility"] - r["epsilon"] else "FAIL"))
            info("  [自适应阈值] {:.4f} = 基线 {:.4f} 按违规率 {:.4f} 调整（高违规收紧/低违规放宽）".format(
                threshold, r["baseline_utility"], v))
        else:
            threshold = r["baseline_utility"]
            info("\n{} · {} {}".format(p["id"], p["artifact"], p.get("entry_id") or ""))
            info("  utility  {:.4f} vs 基线 {:.4f}  (Δ{:+.4f})  {}".format(
                u, r["baseline_utility"], u - r["baseline_utility"], "PASS" if u - r["baseline_utility"] >= -r["epsilon"] else "FAIL"))
        du = u - threshold
        dv = v - r["baseline_violation_rate"]
        util_ok = du >= -r["epsilon"]          # 效用不降（容差 ε）
        safe_ok = dv <= 0                       # 安全严格不退
        info("  violation {:.4f} vs 基线 {:.4f}  (Δ{:+.4f})  {}".format(
            v, r["baseline_violation_rate"], dv, "PASS" if safe_ok else "FAIL"))
        path = st.artifact_path(p["artifact"])
        text = read_text(path)
        if util_ok and safe_ok:
            text = set_entry_status(text, p["entry_id"], "active")
            write_text(path, text)
            p["status"] = "promoted"
            r["generation"] += 1
            prev_baseline = r["baseline_utility"]
            r["baseline_utility"] = u
            r["baseline_violation_rate"] = v
            r["history"].append({"at": now_iso(), "proposal": p["id"], "action": "promote",
                                 "utility": u, "violation_rate": v,
                                 "artifact": p["artifact"], "reason": p.get("reason", "")})
            ok("PROMOTE → 条目转 active，基线上移（第 {} 代）".format(r["generation"]))
            log_metacognition(st, "rule_promoted",
                              context={"trigger": "verdict", "artifact": p["artifact"],
                                       "entry_id": p.get("entry_id") or "",
                                       "utility": u, "violation_rate": v,
                                       "baseline_utility": prev_baseline},
                              analysis={"utility_change": round(u - prev_baseline, 4)},
                              action={"verdict": "PROMOTE", "confirmed": True},
                              insight="规则演化成功，utility 提升并沉淀")
        else:
            # 误演化拦截：回滚 + 存档为负样本（HyperAgents archive 的负向筛选）
            if p["op"] == "add":
                text = remove_entry(text, p["entry_id"])
            else:
                text = set_entry_status(text, p["entry_id"], "revoked")
            write_text(path, text)
            p["status"] = "reverted"
            r["history"].append({"at": now_iso(), "proposal": p["id"], "action": "revert",
                                 "utility": u, "violation_rate": v,
                                 "artifact": p["artifact"], "reason": p.get("reason", "")})
            bad("REVERT → 未达棘轮条件，已回滚（记入 archive 作负样本）")
            append_jsonl(st.archive, {"at": now_iso(), "proposal": p["id"], "action": "reverted",
                                      "artifact": p["artifact"], "utility": u,
                                      "violation_rate": v, "reason": p.get("reason", "")})
            log_metacognition(st, "rule_reverted",
                              context={"trigger": "verdict", "artifact": p["artifact"],
                                       "entry_id": p.get("entry_id") or "",
                                       "utility": u, "violation_rate": v,
                                       "baseline_utility": r["baseline_utility"]},
                              analysis={"reason": p.get("reason", "")},
                              action={"verdict": "REVERT", "reason": p.get("reason", ""),
                                      "rolled_back": True},
                              insight="规则演化失败，已回滚（负样本入 archive）")
        st.save_proposal(p)
        st.set_ratchet(r)
        # C3 修复 + D5：裁决后留可追溯、非破坏的提交（REVERT 回滚同样落点）。
        # D5：git 留底默认开启（root 为 git 仓库时），除非显式 --no-git。
        git_on = bool(getattr(args, "git", False)) or (
            not getattr(args, "no_git", False)
            and os.path.isdir(os.path.join(str(st.root), ".git")))
        if git_on:
            verb = "promote" if (util_ok and safe_ok) else "revert"
            _git_commit(st, "metacog: {} {} (entry {})".format(verb, p["id"], p.get("entry_id") or ""))

    # 元层自省触发：连续 3 次 revert 说明"改进方式"本身有问题
    recent = [h["action"] for h in r["history"][-3:]]
    if len(recent) == 3 and all(a == "revert" for a in recent):
        info("\n[META] 连续 3 次 revert —— 触发 M1 元层自省条件。")
        info("       问题不在具体规则，而在提议方式。请针对 M1 提议改动（requires_human 提案需人类在 TTY 运行 `apply --id <提案>` 输入口令签绑定签名）。")
        # 可选自动触发：--auto-m1 时生成 M1 提议入隔离区（仍须人类绑定签名确认）
        if getattr(args, "auto_m1", False):
            if check_and_trigger_m1(st):
                ok("M1 自动提议已创建（需人类在 TTY 运行 `apply --id <提案>` 输入口令签绑定签名后才可生效）")
                log_metacognition(st, "m1_auto_trigger",
                                  context={"trigger": "continuous_revert", "count": 3,
                                           "generation": r["generation"]},
                                  analysis={"pattern": analyze_failure_pattern(r)},
                                  action={"proposal_created": True, "requires_human": True,
                                          "human_confirmed": False},
                                  insight="连续 REVERT 触发 M1 自动提议，需人工确认")
    return 0


# ---------------------------------------------------------------- M1 自动触发（Phase 1.1）

def analyze_failure_pattern(ratchet_state):
    """分析连续 REVERT 的失败模式，作为 M1 元层自省的输入。

    统计最近 10 条裁决历史中的 revert 次数、制品分布与常见原因。
    history 每条含 action / artifact / reason（见 cmd_verdict 写入）。
    """
    history = ratchet_state.get("history", [])
    recent = history[-10:]
    patterns = {
        "revert_count": sum(1 for h in recent if h.get("action") == "revert"),
        "artifact_focus": {},
        "common_reasons": [],
    }
    for h in recent:
        artifact = h.get("artifact", "unknown")
        patterns["artifact_focus"][artifact] = patterns["artifact_focus"].get(artifact, 0) + 1
    for h in recent:
        reason = (h.get("reason") or "").strip()
        if reason:
            patterns["common_reasons"].append(reason)
    return patterns


def generate_m1_content(pattern):
    """根据失败模式生成 M1 元层自省提议内容（仅作草稿，需人类确认）。"""
    rc = pattern.get("revert_count", 0)
    focus = pattern.get("artifact_focus", {})
    reasons = pattern.get("common_reasons", [])[:3]
    reasons_str = "；".join(reasons) if reasons else "（无显式原因记录）"
    return (
        "## 元层自省（自动触发）\n\n"
        "**触发条件**: 连续 {} 次 REVERT\n\n"
        "**失败模式分析**:\n"
        "- 涉及制品分布: {}\n"
        "- 常见原因: {}\n\n"
        "**建议改进方向**:\n"
        "1. 检查提议生成逻辑是否针对真正问题，而非反复改同一处\n"
        "2. 重新评估归因准确性：重复踩坑→A3，用错工具→A4，做法错→A2\n"
        "3. 考虑收紧证据门槛，或修订 M1 演化策略本身\n"
    ).format(rc, focus, reasons_str)


def check_and_trigger_m1(st: Store):
    """检查并触发 M1 自动提议：仅当最近 3 次裁决全部为 REVERT 时。

    生成的 M1 提议进入隔离区（quarantine），且 requires_human=True，
    必须人类在 TTY 运行 `apply --id <提案>` 输入口令签绑定签名后才能生效 —— 守住 G3 人类确认闸，绝不自动生效。
    """
    r = st.get_ratchet()
    recent = [h.get("action") for h in r.get("history", [])[-3:]]
    if len(recent) == 3 and all(a == "revert" for a in recent):
        pattern = analyze_failure_pattern(r)
        m1_proposal = {
            "id": new_id("M1-AUTO"),
            "created": now_iso(),
            "artifact": "M1",
            "op": "replace",
            "target": "M-000",
            "content": generate_m1_content(pattern),
            "reason": "自动触发：连续3次REVERT，提议方式疑似系统性问题",
            "episodes": [],
            "status": "quarantined",
            "requires_human": True,
            "gate": None,
            "triggered": True,
            "failure_pattern": pattern,
        }
        st.save_proposal(m1_proposal)
        return True
    return False


# ---------------------------------------------------------------- 元认知日志（Phase 2.1）

def log_metacognition(st: Store, event_type: str, context: dict, analysis: dict,
                      action: dict, insight: str = ""):
    """记录一条元认知反思事件（JSONL，根相对路径，零第三方依赖）。

    落点为 `st.meta_log`（= root/ledger/meta-cognition.log），与设计依据 paper-mapping
    同构于既有 ledger 目录，受 --root 隔离约束，不会污染宿主环境。
    """
    entry = {
        "timestamp": now_iso(),
        "event_type": event_type,
        "trigger": context.get("trigger", "unknown"),
        "context": context,
        "analysis": analysis,
        "action": action,
        "insight": insight,
    }
    append_jsonl(st.meta_log, entry)
    return entry


def analyze_meta_log(st: Store, days: int = 7) -> dict:
    """分析最近 N 天的元认知日志。

    返回 total_entries / recent_entries / insights / event_distribution。
    时间过滤使用时区感知的 now，避免 naive-aware 比较报错。
    """
    if not st.meta_log.exists():
        return {"total_entries": 0, "recent_entries": 0, "insights": [], "event_distribution": {}}
    entries = read_jsonl(st.meta_log)
    cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=days)
    recent = []
    for e in entries:
        try:
            ts = datetime.fromisoformat(e["timestamp"])
        except (KeyError, ValueError):
            continue
        if ts > cutoff:
            recent.append(e)
    insights = []
    for e in recent:
        ins = e.get("insight")
        if ins:
            insights.append({
                "timestamp": e.get("timestamp", ""),
                "event_type": e.get("event_type", "unknown"),
                "insight": ins,
            })
    dist = {}
    for e in recent:
        t = e.get("event_type", "unknown")
        dist[t] = dist.get(t, 0) + 1
    return {
        "total_entries": len(entries),
        "recent_entries": len(recent),
        "insights": insights,
        "event_distribution": dist,
    }


# ---------------------------------------------------------------- status


def cmd_status(st: Store, args):
    r = st.get_ratchet()
    # 操作 4：元层参数化（参数级自指）——M1-evolve-policy.json 存在时以其为参数源；
    # 缺失时尊重棘轮既有 window/epsilon（向后兼容 + fail-safe），并在状态中标注真实来源。
    _policy, _src = load_meta_policy(st)
    if _src == "file":
        r["window"] = _policy["default_window"]
        r["epsilon"] = _policy["epsilon"]
    eps = read_jsonl(st.episodes)
    info("=== metacog 状态 · {} ===".format(st.root))
    info("代数(generation): {}   episodes: {}   window: {}   ε: {}   [元层参数源: {}]".format(
        r["generation"], len(eps), r["window"], r["epsilon"], _src))
    if r["baseline_utility"] is None:
        info("基线: 未建立 ({}/{})".format(len(eps), r["window"]))
    else:
        info("基线: utility={:.4f}  violation_rate={:.4f}".format(
            r["baseline_utility"], r["baseline_violation_rate"]))

    # 制品条目统计（G2 检索闸视角）
    info("\n--- 制品 ---")
    for code, (rel, desc) in ARTIFACTS.items():
        entries = parse_entries(read_text(st.artifact_path(code)))
        by = {}
        for e in entries:
            by[e["status"]] = by.get(e["status"], 0) + 1
        detail = " ".join("{}={}".format(k, v) for k, v in sorted(by.items())) or "空"
        info("{}  {:<10} {}".format(code, detail, desc))

    # 趋势：是否真的越用越聪明
    info("\n--- 趋势 ---")
    w = r["window"]
    if len(eps) < w * 2:
        info("样本不足，需 {} 个 episode 才能判趋势（当前 {}）。".format(w * 2, len(eps)))
    else:
        prev, cur = eps[-2 * w:-w], eps[-w:]
        pu, pv = _stats(prev)
        cu, cv = _stats(cur)
        info("utility        {:.4f} → {:.4f}  (Δ{:+.4f})".format(pu, cu, cu - pu))
        info("violation_rate {:.4f} → {:.4f}  (Δ{:+.4f})".format(pv, cv, cv - pv))
        if cu - pu > r["epsilon"] and cv <= pv:
            info("判定: 变聪明了（效用升 + 安全不退）")
        elif abs(cu - pu) <= r["epsilon"] and cv < pv:
            info("判定: 变稳了（效用持平 + 违规下降）")
        elif cu - pu < -r["epsilon"] or cv > pv:
            info("判定: 退化 —— 疑似误演化。检查最近 promote 的条目，考虑 M1 元层自省。")
        else:
            info("判定: 平台期。连续两窗口不升即满足 M1 自省触发条件。")

    # 棘轮自适应阈值状态（Phase 1.2，verdict --adaptive 启用）
    info("\n--- 棘轮自适应阈值（Phase 1.2，verdict --adaptive 启用） ---")
    if r["baseline_utility"] is None:
        info("基线未建立，自适应阈值暂不可用。")
    else:
        base = r["baseline_utility"]
        hi = compute_adaptive_threshold(base, ADAPTIVE_VR_HIGH + 0.01)
        mid = compute_adaptive_threshold(base, 0.2)
        lo = compute_adaptive_threshold(base, ADAPTIVE_VR_LOW - 0.01)
        info("违规率高 >{:.2f} → 收紧阈值 {:.4f}".format(ADAPTIVE_VR_HIGH, hi))
        info("违规率中 0.1~0.3 → 保持基线 {:.4f}".format(mid))
        info("违规率低 <{:.2f} → 放宽阈值 {:.4f}".format(ADAPTIVE_VR_LOW, lo))

    pend = [p for p in st.proposals() if p["status"] in ("quarantined", "gated", "hold", "trial")]
    if pend:
        info("\n--- 待处理 ---")
        for p in pend:
            info("{}  {:<12} {} {}".format(p["id"], p["status"], p["op"], p["artifact"]))

    # D5：回滚可用性提示（非阻塞）
    git_repo = os.path.isdir(os.path.join(str(st.root), ".git"))
    rb_count = len(read_jsonl(st.rollback_log)) if st.rollback_log.exists() else 0
    if git_repo:
        info("\n--- 回滚 ---")
        info("仓库为 git 工作区，回滚以 `git checkout -- <artifact>` 为主，"
             "或 `rollback --artifact <code>` 走 ledger 字节还原（已记录 {} 条）。".format(rb_count))
    elif rb_count:
        info("\n--- 回滚 ---")
        info("非 git 工作区，可用 `rollback --artifact <code>` 走 ledger 字节还原（已记录 {} 条）。".format(rb_count))
    else:
        info("\n--- 回滚 ---")
        info("尚未建立回滚快照（apply 后才会记录）；如需 git 回滚请在本目录 `git init`。")
    return 0


# ---------------------------------------------------------------- retrieve（G2 检索闸）


def cmd_retrieve(st: Store, args):
    """会话开始时加载生效制品。被 revoked / blocked / candidate 的条目不会被检索到。"""
    codes = [args.artifact] if args.artifact else list(ARTIFACTS)
    allow = {"active"} if args.strict else {"active", "trial"}
    # D4：检索前置完整性自检（非阻塞告警）——直写篡改会在吐出生效规则前提示
    if st.integrity.exists():
        drift = [art for art, ok, _, _ in st.verify_integrity() if art in codes and not ok]
        for art in drift:
            warn("[完整性] {} 当前内容与 ledger 快照不一致，可能被直写篡改；"
                 "请以 `verify` 核查、`rollback --artifact {}` 还原。".format(art, art))
    # v2.8.1 C-10 硬化：将脚本完整性校验接入检索热路径为硬闸（检测代码篡改）。
    # 仅当外部锚已启用（受保护模式）或 METACOG_TRUST_ROOT_STRICT=1 时强制；verify_script_integrity
    # 仅核验已建基线的脚本（未建基线者不触发，不误伤全新/未基线部署）。
    # 诚实边界：基线 integrity.json 同处可写 ledger 域，攻击者改代码同时重记基线则不可检出
    # （与 D4 同类残余，须部署契约兜底）；本闸提升对意外漂移/未重基线篡改的检测与热路径阻断。
    _rt_enforced, _rt_drift = _script_integrity_drift_if_enforced(st)
    if _rt_drift:
        bad("[完整性-硬闸] 以下技能脚本哈希与基线不一致，可能为代码篡改：{}；"
            "请以 `verify` 核查并 `rollback` 还原，或人工确认后重基线。".format(", ".join(_rt_drift)))
        return 3
    # v2.8.9 ⑤：可信清单分文件硬闸（Hermes H-01 收口 F-4 纸面闭环）——检索热路径阻断内容被篡改的清单
    _m_enforced, _m_drift = _manifest_integrity_drift_if_enforced(st)
    if _m_drift:
        bad("[完整性-硬闸] 以下可信清单内容哈希与基线不一致，可能为篡改：{}；"
            "请以 `verify` 核查并 `rollback` 还原，或人工确认后重基线。".format(", ".join(_m_drift)))
        return 3
    out = []
    for code in codes:
        entries = [e for e in parse_entries(read_text(st.artifact_path(code)))
                   if e["status"] in allow]
        if not entries:
            continue
        out.append("## {} · {}".format(code, ARTIFACTS[code][1]))
        for e in entries:
            tag = "" if e["status"] == "active" else "  <试用中>"
            out.append("{}{}".format(e["body"], tag))
        out.append("")
    if args.json:
        payload = []
        for code in codes:
            for e in parse_entries(read_text(st.artifact_path(code))):
                if e["status"] in allow:
                    payload.append({"artifact": code, "id": e["id"],
                                    "status": e["status"], "body": e["body"]})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("\n".join(out).strip() or "（无生效条目）")
    return 0


# ---------------------------------------------------------------- D4：verify（系统级完整性校验）

def cmd_verify(st: Store, args):
    """D4：系统级完整性校验——比对各制品当前内容哈希与 ledger 快照（apply 写入的真值）。

    直写 .metacog/artifacts/*.md 绕过三闸，本命令能检出这种偏离（PoC 报告 D4）。
    v2.5.2：verify 保持只读，不再自动钉固信任根（钉固由 keygen / apply 负责）。"""
    rows = st.verify_integrity()
    info("=== 完整性校验（D4 · 堵直写绕过） ===")
    if not rows:
        info("  无快照（尚未 apply 过任何制品）。先 `init` + `apply` 建立基线快照。")
        return 0
    dirty = 0
    for artifact, ok_flag, stored, current in rows:
        if ok_flag:
            ok("{} 一致（hash={}）".format(artifact, current))
        else:
            dirty += 1
            bad("{} 偏离快照（当前 hash={}，快照 hash={}）".format(artifact, current, stored))
    # P0：信任根（human-guard.json）专用校验——D4 哈希 + 指纹漂移（即使重拍快照也能检出）
    gdata = read_json(st.integrity, {})
    grec = gdata.get(Store.GUARD_INTEGRITY_KEY)
    if grec is not None:
        # v2.10.0（HIGH#1 / C-10）：信任根（human-guard.json）基线签名验签——此前 record_integrity 写入了
        # _anchor_sig 但 cmd_verify 从不校验（写而不验），攻击者改 human-guard + 重记基线即绕过；现补验签
        # （签名失效 → fail-closed；此检查与下方哈希/指纹漂移检查互补，屏蔽「改文件+重记基线」绕过）。
        _g_sig_ok = _verify_anchor_sig(grec)
        if _g_sig_ok is False:
            dirty += 1
            bad("{} 基线签名失效：疑似被篡改后伪造签名（信任根不可信）。".format(Store.GUARD_INTEGRITY_KEY))
        elif _g_sig_ok is None and not Store._legacy_anchor_sig_allowed():
            dirty += 1
            bad("{} 基线缺失 _anchor_sig（早于 v2.11 的 legacy 无签名基线）；按 v2.11 截止期已 fail-closed，"
                "请运行 confirm --keygen 重基线。".format(Store.GUARD_INTEGRITY_KEY))
        if not st.human_guard.exists():
            dirty += 1
            bad("{} 缺失（快照 hash={}）：信任根被删除。".format(Store.GUARD_INTEGRITY_KEY, grec.get("hash")))
        else:
            gcur = st._hash_text(st.human_guard.read_text(encoding="utf-8"))
            # v2.8.8 P0-1：GUARD_INTEGRITY_KEY（human-guard）检查委托 _script_hash_matches，纳入 legacy 16-char 兼容——
            # 存量 v2.8.5 human-guard 基线（16-char）升级后不再误判漂移（原裸等值 gcur != grec.get("hash") 缺口）。
            _g_ok, _g_legacy = st._script_hash_matches(gcur, grec.get("hash"), allow_legacy=Store._legacy_hash_allowed())
            if _g_legacy:
                warn("[完整性] 检测到 64-bit 旧格式 human-guard 基线哈希（{}）；已按首 16 字符判定未篡改，"
                     "建议运行 keygen/apply 自动升级为 128-bit 基线。".format(Store.GUARD_INTEGRITY_KEY))
            if not _g_ok:
                dirty += 1
                bad("{} 偏离快照（当前 hash={}，快照 hash={}）：公钥可能被直写替换。".format(
                    Store.GUARD_INTEGRITY_KEY, gcur, grec.get("hash")))
        pinned = st.pinned_human_pubkey_fingerprint()
        if pinned:
            live = st.human_pubkey_fingerprint()
            if live is None:
                dirty += 1
                bad("{} 缺失公钥，但 CONTRACT.md 已钉固信任根（{}）。".format(Store.GUARD_INTEGRITY_KEY, pinned))
            elif live != pinned:
                dirty += 1
                bad("人类公钥信任根指纹漂移：当前 {} 与 CONTRACT.md 钉固 {} 不符（疑似公钥被替换）。".format(live, pinned))
    # v2.8.4 M-3：脚本完整性漂移已由上方 verify_integrity 主路径统一遍历 script: 键纳入 dirty 计数，
    # 此处不再重复遍历（避免双重计数）；verify_script_integrity 仍供 cmd_retrieve 硬闸与测试单独调用。
    # v2.8.9 ⑦：rollback 审计哈希链完整性报告（非阻塞巡检；断裂计入 dirty → verify 返回 1）。
    # 此前 _verify_audit_chain 零生产调用（Hermes H-A1），本行使其进入 verify 巡检路径。
    _c_ok, _c_cnt = _verify_audit_chain(st)
    if not _c_ok:
        dirty += 1
        bad("rollback 审计哈希链断裂（rollback-audit.jsonl 疑似被篡改/重排/伪造，count={}）：rollback 重基线痕迹不可信，请人工核验。".format(_c_cnt))
    elif _c_cnt > 0:
        ok("rollback 审计哈希链完整（{} 条记录）。".format(_c_cnt))
    if dirty:
        bad("{} 个制品/信任根偏离 ledger 快照：可能存在未经 apply 的直写篡改。".format(dirty))
        info("  提示：直接改 .metacog/artifacts/*.md 或 human-guard.json 会绕过 propose→gate→apply 三闸；"
             "请改用标准流程，或 `rollback --artifact X` 还原到经 apply 的真值。")
        return 1
    info("全部制品与 ledger 快照一致（无直写篡改）。")
    return 0


def _reactivate_block(block):
    """把条目块的状态字段强制还原为 active（用于回滚）。"""
    return re.sub(r"status:(trial|revoked)", "status:active", block)


class LedgerAnchorDefaultError(RuntimeError):
    """v2.10.0（MED#1 收口，对齐 v2.8.1 C-9）：拒绝以默认（源码内嵌共享）锚密钥签名/验签账本。

    该默认锚 `9f2c4a7e…2b5c8d` 随代码分发，任何可读代码者均可提取并伪造签名（与 v2.8.1 C-9 已就性质
    判定为需防护的威胁同构）。本地开发/测试须显式设 `METACOG_TRUST_ROOT_ALLOW_DEFAULT=1` 承担风险；
    生产/非本地部署须以 `METACOG_TRUST_ROOT_ANCHOR_KEY` 设为专属随机密钥。"""


# v2.10.0（MED#1）：基线签名与审计链 HMAC 使用**不同派生标签**，消除单钥双用（Hermes r7 中 H-D）。
_LEDGER_SIG_LABEL = b"metacog-ledger-sig-v210"
_AUDIT_HMAC_LABEL = b"metacog-ledger-audit-v290"  # 审计链历史标签（存量审计链不可重签，须向后兼容）
# v2.9.0 基线签名曾复用审计链标签（单钥双用）；v2.10.0 起基线改用 _LEDGER_SIG_LABEL，
# 存量 v2.9.0 基线签名（旧标签）不再视为可信，仅作 legacy 容忍（见 _verify_anchor_sig）。
_LEDGER_SIG_LABEL_LEGACY = _AUDIT_HMAC_LABEL


def _resolve_anchor_key():
    """v2.10.0（MED#1 收口，对齐 v2.8.1 C-9）：返回账本签名锚密钥。

    优先 trust_root.get_anchor_key()（支持 METACOG_TRUST_ROOT_ANCHOR_KEY 部署专属覆盖）；
    trust_root 缺失回退 _LEDGER_ANCHOR_DEFAULT。当锚为源码内嵌共享默认锚且未显式
    METACOG_TRUST_ROOT_ALLOW_DEFAULT=1 时 → 抛 LedgerAnchorDefaultError（fail-closed），
    禁止生产/非本地部署静默使用「可读代码即伪造」的共享锚。本地开发/测试须显式设该环境变量承担风险。"""
    if trust_root is not None:
        _anchor = trust_root.get_anchor_key()
    else:
        _anchor = _LEDGER_ANCHOR_DEFAULT
    if _anchor == _LEDGER_ANCHOR_DEFAULT and not os.environ.get("METACOG_TRUST_ROOT_ALLOW_DEFAULT"):
        raise LedgerAnchorDefaultError(
            "拒绝以默认（源码内嵌共享）锚密钥签名/验签账本：该密钥随代码分发，可读代码者即可伪造签名。\n"
            "生产/非本地部署须设置环境变量 METACOG_TRUST_ROOT_ANCHOR_KEY 为专属随机密钥；\n"
            "本地开发/测试须显式设置 METACOG_TRUST_ROOT_ALLOW_DEFAULT=1 以承担风险。")
    return _anchor


def _ledger_sig_key():
    """v2.10.0（MED#1）：完整性基线签名专用派生密钥（与审计链 HMAC 密钥分离，消除单钥双用）。"""
    return hmac.new(_resolve_anchor_key(), _LEDGER_SIG_LABEL, hashlib.sha256).digest()


def _audit_hmac_key(st):
    """v2.10.0（MED#1）：审计链 HMAC 专用派生密钥（标签 _AUDIT_HMAC_LABEL 与基线签名分离）；
    保留历史标签以兼容存量审计链（rollback-audit / migration-audit 不可重签）。
    密钥由代码内嵌锚派生（密钥位于代码，非可写 ledger），攻击者凭 ledger 写权限无法获得。
    生产护栏：默认（共享）锚须 METACOG_TRUST_ROOT_ALLOW_DEFAULT=1，否则 _resolve_anchor_key 抛错（fail-closed）。"""
    return hmac.new(_resolve_anchor_key(), _AUDIT_HMAC_LABEL, hashlib.sha256).digest()


def _ledger_anchor_sig(payload: dict) -> str:
    """v2.10.0（MED#1 / H-4 / C-10）：对账本基线条目做锚密钥签名（专用 _ledger_sig_key，与审计链分离）。
    签名覆盖条目规范化载荷（含 hash/size/at 等，排除 _anchor_sig 自身），由代码内嵌锚派生，
    攻击者凭 ledger 写权限无法伪造（密钥位于代码/专属 env，非可写 ledger）→ 闭「中间条目被一致改写」盲区。
    返回 hexdigest。"""
    _key = _ledger_sig_key()
    _canon = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hmac.new(_key, _canon.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_anchor_sig(rec):
    """v2.10.0（MED#1 / C-10 / H-4）：校验基线条目的 _anchor_sig。

    返回 True（签名存在且对当前 _ledger_sig_key 有效）/ False（签名存在但既非新标签亦非旧标签→篡改）
    / None（无签名 legacy 基线，或签名为 v2.9.0 旧共享标签——后者不再可信，仅容忍不阻断，待重基线）。
    v2.10.0 起基线改用专属标签；v2.9.0 旧标签签名视为 legacy 容忍（不信任），杜绝「单钥双用」残余被利用。"""
    if not isinstance(rec, dict):
        return None
    _sig = rec.get("_anchor_sig")
    if not isinstance(_sig, str):
        return None  # 无签名：legacy 基线，容忍不阻断（待重基线）
    _payload = {k: v for k, v in rec.items() if k != "_anchor_sig"}
    _canon = json.dumps(_payload, separators=(",", ":"), sort_keys=True)
    _anchor = _resolve_anchor_key()
    _new_exp = hmac.new(
        hmac.new(_anchor, _LEDGER_SIG_LABEL, hashlib.sha256).digest(),
        _canon.encode("utf-8"), hashlib.sha256).hexdigest()
    try:
        if hmac.compare_digest(_sig, _new_exp):
            return True
    except Exception:
        pass
    # v2.9.0 旧共享标签签名：存在但不信任（单钥双用残余），仅 legacy 容忍（None），不当作有效（True）。
    _legacy_exp = hmac.new(
        hmac.new(_anchor, _LEDGER_SIG_LABEL_LEGACY, hashlib.sha256).digest(),
        _canon.encode("utf-8"), hashlib.sha256).hexdigest()
    try:
        if hmac.compare_digest(_sig, _legacy_exp):
            return None  # legacy 旧标签签名：容忍不信任
    except Exception:
        pass
    return False  # 签名存在但既非新标签亦非旧标签 → 篡改


def _audit_rollback(st, code, entry_id, old_hash, new_hash):
    """v2.8.9 ⑦：rollback 重基线完整性快照审计留痕（ledger/rollback-audit.jsonl）+ HMAC-SHA256 哈希链。
    与 integrity.json 分离存储（削弱同域自指）；每条记录含 prev_hmac（链上一跳）与 hmac（本跳），
    任何插入/删除/重排/篡改都破坏链连续性（见 _verify_audit_chain）。闭合 H-2（v2.8.7 仅 --yes 静态确认、无留痕）
    并缓解 v2.8.8 同源可伪造残余（Hermes M-01）。"""
    _audit = st.root / "ledger" / "rollback-audit.jsonl"
    _audit.parent.mkdir(parents=True, exist_ok=True)
    _key = _audit_hmac_key(st)
    _prev = ""
    if _audit.exists():
        _lines = [l for l in _audit.read_text(encoding="utf-8").splitlines() if l.strip()]
        if _lines:
            try:
                _last = json.loads(_lines[-1])
                _hmac = _last.get("hmac") if isinstance(_last, dict) else None
                if isinstance(_hmac, str):
                    _prev = _hmac
                else:
                    _prev = "<broken>"
                    warn("[审计] 上游 rollback-audit 末条 hmac 非字符串（null/畸形），已置 prev_hmac=<broken> 阻断链污染")
            except Exception:
                _prev = "<broken>"
    # v2.9.0 修复：_entry 必须在 if 块外赋值——首次 rollback（审计文件尚不存在）时
    # if _audit.exists() 为 False，原结构会令 _entry 未绑定 → UnboundLocalError（首次 rollback 即崩）。
    _entry = {
        "at": now_iso(),
        "operation": "rollback-rebaseline",
        "epoch": LEDGER_KEY_EPOCH,
        "artifact": code,
        "entry_id": entry_id,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "confirmed": True,
        "prev_hmac": _prev,
    }
    _payload = json.dumps(_entry, separators=(",", ":"), sort_keys=True)
    _entry["hmac"] = hmac.new(_key, _payload.encode("utf-8"), hashlib.sha256).hexdigest()
    with _audit.open("a", encoding="utf-8") as _f:
        _f.write(json.dumps(_entry, separators=(",", ":"), sort_keys=True) + "\n")


def _verify_audit_chain(st, cutoff=None):
    """v2.8.9 ⑦ + v2.10.0（HIGH#2/#3 / C-10 收口）+ v2.11.0（H-C 收口）：校验 rollback-audit.jsonl 哈希链 + HMAC 连续性 + 逐条 epoch
    （v2.10.0 起严格链强制 epoch，中段缺 epoch → fail-closed）；任一被篡改/重排/删除/伪造/中段缺 epoch → ok=False。
    返回 (ok, count)。供测试与运营巡检调用（异常/断裂 → fail-closed 报警）。
    诚实边界（v2.10.0 重写）：严格链（首条带 epoch=v290）全链逐条验；旧链（首条缺 epoch，<v2.9.0）仅结构预检、
    不验 HMAC/连续/epoch，且**不实现旧链自动归档**（v2.9.0 注释中的归档承诺不实，v2.10.0 撤销）；
    旧链停留容忍态直至操作员手动重建带 epoch 的新链。详见 _verify_migration_audit docstring。"""
    _audit = st.root / "ledger" / "rollback-audit.jsonl"
    if not _audit.exists():
        return (True, 0)
    _key = _audit_hmac_key(st)
    _lines = [l for l in _audit.read_text(encoding="utf-8").splitlines() if l.strip()]
    _total = len(_lines)
    # v2.10.0（HIGH#2 / C-10 诚实化）：首条缺 epoch 标记 → 旧版（<v2.9.0）链，视为不可信但容忍
    # （仅结构预检，不验 HMAC/连续/epoch；详见本函数 docstring）。本函数不实现旧链自动归档。
    if _lines:
        try:
            _first = json.loads(_lines[0])
        except Exception:
            _first = {}
        if not (isinstance(_first, dict) and _first.get("epoch") == LEDGER_KEY_EPOCH):
            # v2.10.0（HIGH#2 / C-10 诚实化）：旧链「不可信但容忍」——仅做结构预检（dict + hmac/prev_hmac 为 str），
            # 不验 HMAC 值、不验链连续、不验逐条 epoch（旧密钥签名的链无法以新锚验签，属已知边界）。
            # 结构性损坏（非 dict / hmac 或 prev_hmac 非字符串）仍 fail-closed 检出，不放行静默结构篡改
            # （否则 M-1 写侧污染守卫 / D-2 尾部截断类攻击被纵容）。
            # 注意：v2.10.0 起本分支**不实现旧链自动归档**（v2.9.0 注释中的归档承诺不实，v2.10.0 如实撤销）。
            # v2.11.0（H-C 收口）：旧链容忍带截止期——CURRENT >= LEGACY_AUDIT_CHAIN_CUTOFF 后，
            # 旧链从「不可信但容忍」升级为 fail-closed（杜绝「删带 epoch 条目即令历史退化」永久降级，Hermes r7 H-C）。
            _struct_ok = True
            for _ln in _lines:
                try:
                    _e = json.loads(_ln)
                except Exception:
                    _struct_ok = False
                    break
                if not isinstance(_e, dict) or not isinstance(_e.get("prev_hmac"), str) or not isinstance(_e.get("hmac"), str):
                    _struct_ok = False
                    break
            if not _struct_ok:
                return (False, _total)
            if Store._legacy_audit_chain_allowed(cutoff=cutoff):
                return (True, _total)
            warn("[审计] 旧版（首条缺 epoch）rollback 审计链在 v2.11+ 已 fail-closed（不可信且容忍期已过）；"
                 "请运行 rollback/apply 重建带 epoch 的新链。")
            return (False, _total)
    _prev = ""
    _count = 0
    for _ln in _lines:
        try:
            _e = json.loads(_ln)
        except Exception:
            # 返回文件实际总条数（而非已校验条数），让 fail-closed 消息准确反映「存在 N 条记录且链已断」
            return (False, _total)
        # v2.10.0（HIGH#3 / C-10）：中段/尾部条目若缺 epoch 或 epoch 不符 → fail-closed，
        # 封堵「首条带 epoch 进入严格校验后、中段注入无 epoch 伪造条目」攻击（Hermes r7 H-C）。
        if not isinstance(_e, dict) or not isinstance(_e.get("prev_hmac"), str) or not isinstance(_e.get("hmac"), str) or _e.get("prev_hmac") != _prev or _e.get("epoch") != LEDGER_KEY_EPOCH:
            return (False, _total)
        _payload = json.dumps({k: v for k, v in _e.items() if k != "hmac"}, separators=(",", ":"), sort_keys=True)
        _exp = hmac.new(_key, _payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(_exp, _e.get("hmac", "")):
            return (False, _total)
        _prev = _e.get("hmac", "")
        _count += 1
    return (True, _count)


def cmd_rollback(st: Store, args):
    """D5：字节级回滚——把制品还原到上一经 apply 的真值。

    git 仓库优先走 `git checkout`（非破坏、可追溯）；非 git 走 ledger 快照
    （apply 时记录被改条目的旧文本）。解决「--git 默认关 → 无字节级撤销」问题。"""
    code = args.artifact
    # v2.8.9 ⑦：rollback 入口先校验审计哈希链完整性（fail-closed）——链断裂（被篡改/重排/伪造）→ 拒绝 rollback 并告警人工介入。
    # 此前 _verify_audit_chain 仅被定义/测试、零生产调用（Hermes H-A1），本行使其从死代码变为真实门槛。
    _chain_ok, _chain_cnt = _verify_audit_chain(st)
    if not _chain_ok:
        bad(add_fix("rollback 拒绝：审计哈希链断裂（rollback-audit.jsonl 疑似被篡改/重排/伪造，已有记录 {} 条）。"
                    "rollback 重基线完整性快照属高敏感操作，链断裂时禁止自动重基线；请人工核验 ledger/rollback-audit.jsonl 后再重试。"
                    .format(_chain_cnt),
                    "人工核验 rollback-audit.jsonl 完整性，必要时从备份恢复后再执行 rollback"))
        return 3
    if not code:
        bad(add_fix("rollback 需指定 --artifact", "--artifact A1/A2/A3/A4/M1"))
        return 2
    # v2.8.7 F-3：rollback 仅作用于合法 ARTIFACTS 制品码，绝不接受 script: 域或其他任意键——
    # 防止借 rollback 的 record_integrity 重基线技能自身代码完整性域（洗白）。
    # （CLI 层 argparse choices 已拦截；此处再校验以防御程序化直调绕过 argparse。）
    if code not in ARTIFACTS:
        bad(add_fix("rollback --artifact 必须是合法制品码（A1/A2/A3/A4/M1），不接受 script: 域或其他键",
                    "--artifact A1/A2/A3/A4/M1"))
        return 2
    path = st.artifact_path(code)
    if not path.exists():
        bad("制品 {} 文件不存在，无法回滚。".format(code))
        return 2
    # v2.8.7 F-3：rollback 会把制品还原并重基线其完整性快照（record_integrity），
    # 属重基线动作，须人类显式 --yes 确认方可执行（防止自动化/误调用静默改写完整性真值）。
    if not getattr(args, "yes", False):
        bad(add_fix("rollback 将重基线制品 {} 的完整性快照，须显式 --yes 确认".format(code),
                    "人类确认后加 --yes 再执行"))
        return 2
    # v2.8.9 ⑥：--yes 须由人类在真实终端显式确认（无 TTY 拒绝），防止程序化静默 rollback 重基线洗白（H-3/H-2 残余）。
    if not _require_tty():
        bad(add_fix("rollback --yes 拒绝在非交互环境执行（stdin/stdout 非 TTY）：rollback 重基线完整性快照须人类在真实终端确认；"
                    "请在与人类操作员确认的交互终端运行，或省略 --yes 走交互确认。",
                    "在真实 TTY 终端运行 rollback --yes，或交互式确认"))
        return 2
    # v2.8.8 H-2：捕获重基线前旧哈希，供审计留痕（rollback 重基线完整性快照须可追溯）
    _old_hash = read_json(st.integrity, {}).get(code, {}).get("hash")
    # 优先 git
    if (getattr(args, "git", False) or os.path.isdir(os.path.join(str(st.root), ".git"))) \
            and not getattr(args, "no_git", False):
        a = subprocess.run(["git", "checkout", "--", str(path)],
                            cwd=str(st.root), capture_output=True, text=True)
        if a.returncode == 0:
            ok("git checkout 还原 {} 到最近提交。".format(code))
            st.record_integrity(code)
            _audit_rollback(st, code, None, _old_hash, read_json(st.integrity, {}).get(code, {}).get("hash"))
            return 0
        err = (a.stderr or a.stdout).strip()
        bad(add_fix("git checkout 失败: " + (err.splitlines()[0] if err else "未知"),
                    "若无提交历史，改用 ledger 快照回滚（去掉 --git）"))
        return a.returncode
    # 非 git：ledger 快照字节还原
    rec = st.latest_rollback(code, getattr(args, "entry", None))
    if not rec:
        bad("无 {} 的回滚快照（非 git 仓库且未记录）。可先在 root 内 `git init` 再 apply。".format(code))
        return 1
    text = read_text(path)
    ids = [e["id"] for e in parse_entries(text)]
    new_block = _reactivate_block(rec["prev_text"])
    if rec["entry_id"] in ids:
        text = ENTRY_RE.sub(lambda m: new_block if m.group("id") == rec["entry_id"] else m.group(0), text)
    else:
        text = text.rstrip() + "\n\n" + new_block + "\n"
    write_text(path, text)
    st.record_integrity(code)
    _audit_rollback(st, code, rec["entry_id"], _old_hash, read_json(st.integrity, {}).get(code, {}).get("hash"))
    ok("{} 条目 {} 已字节还原到 apply 前状态（ledger 快照）。".format(code, rec["entry_id"]))
    return 0


# ---------------------------------------------------------------- confirm（W1 人类闸密码学身份绑定）

def _require_tty():
    """W1 强制链第一环：confirm 只能由人类在真实终端交互运行。

    AI 可以执行任意 CLI，但无法伪造 TTY 上的隐藏输入——非 TTY 一律拒绝。
    人类私钥也只在 TTY 内由人类口令解锁，Agent 进程永不持有私钥明文。"""
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
    except (AttributeError, ValueError):
        return False
    return True


def _priv_n_matches(guard: dict, priv_json: str) -> bool:
    """用公钥 n 校验解密出的私钥确属配对（口令正确性的确定性判据，不依赖 UTF-8 解码）。"""
    try:
        priv = sigcrypto.deserialize_priv(priv_json)
        pub = sigcrypto.deserialize_pub(guard["pubkey"])
    except Exception:
        return False
    return priv[0] == pub[0]


def _confirm_keygen(st: Store, args) -> int:
    """W1 人类闸初始化：生成 RSA-2048 密钥对，私钥以口令加密落盘（Agent 不持明文）。
    幂等：密钥已存在时跳过生成；但若本次携带 --enable_external，仍继续处理外部锚启用
    （不重复生成密钥，复用既有信任根）。"""
    # v2.8.6 N-3：硬闸移至函数顶部（写 human_guard 之前，且覆盖幂等早退路径），
    # 闭合 v2.8.5「写先于闸」顺序缺陷 + 幂等早退绕过（已建密钥分支亦须过闸）。
    _k_enforced, _k_drift = _script_integrity_drift_if_enforced(st)
    if _k_drift:
        bad("[完整性-硬闸] 以下技能脚本哈希与基线不一致，拒绝 keygen（须基于未篡改代码）：{}；"
            "请以 `verify` 核查并 `rollback` 还原，或人工确认后重基线。".format(", ".join(_k_drift)))
        return 3
    # v2.8.9 ⑤：可信清单分文件硬闸（Hermes H-01 收口 F-4 纸面闭环）——手改可信清单内容 → 拒绝 keygen（须基于未篡改定义）
    _m_enforced, _m_drift = _manifest_integrity_drift_if_enforced(st)
    if _m_drift:
        bad("[完整性-硬闸] 以下可信清单内容哈希与基线不一致，拒绝 keygen（疑似被篡改）：{}；"
            "请以 `verify` 核查并 `rollback` 还原，或人工确认后重基线。".format(", ".join(_m_drift)))
        return 3
    guard = read_json(st.human_guard, None)
    _en = getattr(args, "enable_external", None)
    _keys_exist = bool(guard and "pubkey" in guard and "privkey_enc" in guard)
    if _keys_exist:
        st.ensure_pubkey_root_pinned()  # P0 前向兼容：现存安装补钉固信任根
        if not _en:
            info("人类密钥对已存在（{}），跳过生成。如要重置口令用 `confirm --init`。".format(
                guard.get("created_at", "?")))
            return 0
        # 密钥已存在但本次请求启用外部锚：跳过密钥生成，直接处理外部锚配置（复用既有信任根）
        info("人类密钥对已存在（{}）；本次仅处理外部锚启用，不重复生成密钥。".format(
            guard.get("created_at", "?")))
    if not _keys_exist:
        if sigcrypto is None:
            bad(add_fix("sigcrypto 模块缺失，无法生成人类密钥对",
                        "确认 sigcrypto.py 与 metacog.py 同目录；或重装 metacog 技能"))
            return 2
        pw1 = getpass.getpass("设置私钥解锁口令: ")
        pw2 = getpass.getpass("再输一遍确认: ")
        if not pw1 or pw1 != pw2:
            bad(add_fix("口令为空或两次输入不一致", "重新运行 `confirm --keygen`"))
            return 2
        # v2.5.3（F-2）：离线 nonce-file 授权，取代键盘 input() 二次确认。
        # 背景：v2.5.2 的 input() 在 pty 场景下可被 Agent 喂入 "YES" 静默重置信任根；
        # 离线凭据存于人工受保护存储（加密卷/硬件令牌，Agent 无写权限），读后即焚防重放。
        # _require_tty() 仍保留为纵深防御（纯管道 stdin 直接被拒）。
        nonce_path = getattr(args, "nonce_file", None)
        if not nonce_path:
            bad(add_fix("keygen 缺少离线授权凭据（--nonce-file）",
                        "人工在加密卷/硬件令牌预置一次性授权文件（>=16 字符随机串），"
                        "运行 `confirm --keygen --nonce-file <path>`；文件须位于 Agent 无写权限处，用毕代码自动删除"))
            return 2
        _np = Path(nonce_path)
        # N1（v2.6.0）：离线授权文件须为真实文件、非符号链接；symlink 可被指向 Agent 可控路径重放授权。
        if _np.is_symlink():
            bad(add_fix("离线授权文件是符号链接（N1：symlink 可被指向 Agent 可控路径重放授权）",
                        "使用真实文件（非 symlink）作为 --nonce-file"))
            return 2
        _np = _np.resolve()
        if not _np.exists() or not _np.is_file():
            bad(add_fix("离线授权文件不存在或不可读", "确认 --nonce-file 路径与文件存在"))
            return 2
        _nonce_val = _np.read_text(encoding="utf-8").strip()
        if len(_nonce_val) < 16:
            bad(add_fix("离线授权凭据过短（<16 字符），疑似误用", "使用人工预生成的 >=16 字符随机凭据"))
            return 2
        try:
            _np.unlink()  # 一次性消费，防 Agent 后续重放
        except OSError:
            bad(add_fix("授权文件删除失败（可能只读介质），已中止以防重放",
                        "在可写位置预置授权文件，或由人工确认后手动删除"))
            return 2
        info("  离线授权凭据已核验并消费（文件已删除，防重放）。")
        pub, priv = sigcrypto.gen_keypair(2048)
        blob = sigcrypto.encrypt_priv(sigcrypto.serialize_priv(priv), pw1)
        write_json(st.human_guard, {
            "pubkey": sigcrypto.serialize_pub(pub),
            "privkey_enc": blob,
            "algo": "rsa-2048-pkcs1v15+aesctr-equiv",
            "created_at": now_iso(),
        })
        fp = hashlib.sha256(sigcrypto.serialize_pub(pub).encode("utf-8")).hexdigest()[:32]  # v2.5.3（F-5）：128-bit 指纹
        # P0：把公钥指纹钉入 CONTRACT.md 不动点（人类持有）；同时把 guard 写入 D4 完整性快照
        st.write_human_pubkey_fingerprint(fp)
        st.record_guard_integrity()
        # v2.8.6 N-3：硬闸已移至函数顶部（写 human_guard 之前，且覆盖幂等早退路径），此处仅刷新脚本基线。
        st.record_script_integrity()  # v2.5.2（M-5）：钉固同时建立技能脚本基线
        ok("人类密钥对已生成并加密落盘（私钥用口令加密，Agent 进程不持有明文）。")
        info("  公钥指纹(前16位): {}".format(fp))
        info("  指纹已钉固至 CONTRACT.md（human-identity-root），apply/verdict 验签将强制比对。")
        info("  请人工记录此指纹，用于带外核验公钥未被替换（最后一道闸）：")
        info("  任何未经你亲自在独立信道核对的指纹变更，一律视为信任根被篡改，立即停用并复核。")
        info("  下一步: 应用 requires_human 提案时，在 `apply --id <提案>` 交互式输入口令签绑定签名。")
    # v2.7.0 外部锚（密码学层外部化，非 C-1 真正闭合，见 HANDOFF ⑦）：人类在 TTY 在场时显式启用；
    # 权威来自离线 RSA 根
    # v2.7.5 H1 收口：回收外部证明存储（幽灵基线阻断合法重装）；须人类 TTY 在场
    if getattr(args, "purge_external_anchor", False):
        if not _require_tty():
            warn("回收外部证明存储须人类 TTY 在场。")
            return 2
        res = st.purge_external_anchor()
        if res == "cleared":
            ok("外部锚证明存储已回收（幽灵基线已清除），可重新运行 --enable-external。")
        elif res == "none":
            info("外部锚证明存储不存在，无需回收。")
        else:  # "partial"
            warn("外部锚回收半败（部分足迹残留），须手动删除残留证明目录后再重试；"
                 "切勿直接 re-enable（否则钉固公钥可被覆盖）。")
            return 2
        return 0
    if _en:
        if trust_root is None:
            warn("trust_root 模块缺失，外部锚未启用（行为退回 legacy）。")
        else:
            _att = getattr(args, "attestation_path", "") or ""
            _oob = getattr(args, "oob_token_dir", "") or ""
            _rootpub = getattr(args, "root_pubkey", "") or ""
            _rootpriv = getattr(args, "root_privkey", "") or ""
            # v2.7.0（密码学层外部化，非 C-1 真正闭合）：外部锚权威来自离线 RSA 根；Agent 仅持公钥验签，
            # 私钥由人类离线持有（严禁落盘）。root_pubkey 必填，否则无法建立可验签外部锚。
            # ⚠️ C-1 循环论证未真正闭合（root_pubkey 仍处 Agent 可写域，见 HANDOFF ⑦）。
            if not _rootpub:
                bad(add_fix("启用外部锚须提供离线根公钥 --root-pubkey",
                            "先在独立环境运行 trust_root.gen_offline_root_keypair() 生成根密钥对"
                            "（私钥离线保管、严禁落 Agent 可写域），再用 "
                            "`confirm --keygen --enable-external <backend> --root-pubkey <pub> "
                            "--attestation-path <Agent无写权限文件> --oob-token-dir <Agent无写权限目录>`"))
                return 2
            # v2.8.1 C-9 硬化：默认（源码内嵌共享）锚密钥不得用于启用外部锚（见 trust_root.write_trust_root_config）。
            if (trust_root.get_anchor_key() == trust_root._TRUST_ROOT_ANCHOR_KEY_DEFAULT
                    and not os.environ.get("METACOG_TRUST_ROOT_ALLOW_DEFAULT")):
                bad(add_fix("启用外部锚须使用专属锚密钥，不得用默认（源码内嵌共享）锚密钥",
                            "设置环境变量 METACOG_TRUST_ROOT_ANCHOR_KEY 为专属随机密钥"
                            "（生产/非本地部署强制）；本地开发设 METACOG_TRUST_ROOT_ALLOW_DEFAULT=1"))
                return 2
            if _en == "hsm":
                # v2.7.0：离线根使独立 hsm 成为真外部锚（设备证明由离线私钥签名，Agent 不可伪造），
                # 不再强制叠加 oob（v2.6.x 因 sim 密钥可伪造才须 hsm+oob）。hsm+oob 仍为最强姿态。
                if not _att:
                    warn("hsm 后端须提供 --attestation-path（Agent 无写权限目录），外部锚未启用。")
                else:
                    trust_root.write_trust_root_config(st.root, _en, _att, _oob, root_pubkey=_rootpub)
                    st.record_external_anchor_integrity(root_pubkey=_rootpub, root_privkey=_rootpriv)  # v2.7.4：钉固 root_pubkey + 可选离线根签名基线（NEW-H1 闭合）
                    ok("v2.7.0 外部锚已启用（backend=hsm，离线根公钥已写入）；独立 hsm 现为真正外部锚。")
                    info("  设备证明文件须由人类离线用根私钥签名后放置于 --attestation-path（Agent 无写权限处）：")
                    info("    trust_root.write_root_attestation('<att>', '<agent_pub>', '<contract_fp>', '<root_priv>')")
            elif _en == "oob":
                if not _oob:
                    warn("oob 后端须提供 --oob-token-dir（Agent 无写权限目录），外部锚未启用。")
                else:
                    trust_root.write_trust_root_config(st.root, _en, _att, _oob, root_pubkey=_rootpub)
                    st.record_external_anchor_integrity(root_pubkey=_rootpub, root_privkey=_rootpriv)  # v2.7.4：钉固 root_pubkey + 可选离线根签名基线（NEW-H1 闭合）
                    ok("v2.7.0 外部锚已启用（backend=oob，离线根公钥已写入）；带外令牌须离线根签名。")
                    info("  每次关键操作须由人类离线对挑战签名，将 base64 令牌写入 <oob_dir>/<challenge>.token：")
                    info("    trust_root.sign_oob_token('<challenge>', '<root_priv>')")
            elif _en == "hsm+oob":
                if not _att or not _oob:
                    warn("hsm+oob 后端须同时提供 --attestation-path 与 --oob-token-dir（均 Agent 无写权限目录），外部锚未启用。")
                else:
                    trust_root.write_trust_root_config(st.root, _en, _att, _oob, root_pubkey=_rootpub)
                    st.record_external_anchor_integrity(root_pubkey=_rootpub, root_privkey=_rootpriv)  # v2.7.4：钉固 root_pubkey + 可选离线根签名基线（NEW-H1 闭合）
                    ok("v2.7.0 外部锚已启用（backend=hsm+oob，离线根公钥已写入）；设备证明 + 带外签名双重锚。")
                    info("  设备证明（离线签名）：trust_root.write_root_attestation('<att>', '<agent_pub>', '<contract_fp>', '<root_priv>')")
                    info("  带外令牌（离线签名）：trust_root.sign_oob_token('<challenge>', '<root_priv>') → <oob_dir>/<challenge>.token")
            # 共同提示：私钥须离线保管，Agent 不持私钥 → 无法自造证明/令牌（密码学层外部化）。
            # ⚠️ 诚实边界：v2.7.0"C-1 真正闭合"经 Hermes 2026-10-02 复验证伪已撤回；root_pubkey 仍处
            # Agent 可写域，C-1 未真正闭合（见 HANDOFF ⑦）；v2.7.1 由结构性 fail-closed 闸门补强主向量。
            if trust_root.TrustRootConfig.load(st.root).enabled:
                info("  离线根私钥须由人类离线保管，严禁以任何形式写入 Agent 可写域（ledger/代码/配置）。")
    return 0


def _confirm_init(st: Store) -> int:
    """W1 口令轮换：用旧口令解密私钥，再用新口令重新加密落盘（需先 --keygen）。"""
    guard = read_json(st.human_guard, None)
    if not guard or "privkey_enc" not in guard:
        bad(add_fix("尚未生成人类密钥对，无法重置口令", "先运行 `confirm --keygen`"))
        return 2
    old = getpass.getpass("当前解锁口令: ")
    try:
        priv_json = sigcrypto.decrypt_priv_str(guard["privkey_enc"], old)
    except Exception:
        bad(add_fix("口令错误，无法解密私钥",
                    "确认口令；忘记则删除 {} 后重跑 `confirm --keygen`".format(st.human_guard)))
        return 2
    if not _priv_n_matches(guard, priv_json):
        bad(add_fix("口令错误（解密出的私钥与公钥不匹配）",
                    "确认口令；忘记则删除 {} 后重跑".format(st.human_guard)))
        return 2
    pw1 = getpass.getpass("设置新解锁口令: ")
    pw2 = getpass.getpass("再输一遍确认: ")
    if not pw1 or pw1 != pw2:
        bad(add_fix("新口令为空或两次输入不一致", "重新运行 `confirm --init`"))
        return 2
    blob = sigcrypto.encrypt_priv(priv_json, pw1)
    guard["privkey_enc"] = blob
    guard["updated_at"] = now_iso()
    write_json(st.human_guard, guard)
    st.record_guard_integrity()  # P0：口令轮换后刷新 D4 信任根快照
    ok("解锁口令已重置（私钥用新口令重新加密落盘）。")
    return 0


def cmd_confirm(st: Store, args):
    """W1 人类闸密钥管理：人类在 TTY 生成/轮换 RSA 密钥对。

    - `confirm --keygen`：生成 RSA-2048 密钥对；私钥以口令加密落盘，公钥明文存盘
      （供 apply 验签），Agent 进程永不持有私钥明文。幂等。
    - `confirm --init`：轮换解锁私钥的口令（旧口令解密 → 新口令重加密）。

    注：v2.5.7 起人类签名已合并到 `apply` 时刻（TTY 口令签绑定签名，覆盖
    提案 id + 内容哈希 + 试用窗起点），不再有独立的 `confirm --approve` 步骤。

    核心不变量：私钥从不进入 Agent 进程，只有人类在 TTY 用口令解锁后才能签名。"""
    if not _require_tty():
        bad(add_fix("confirm 必须由人类在真实终端交互运行（当前非 TTY）",
                    "请人类亲自打开终端执行本命令；agent 不得代替人类运行 confirm"))
        return 2
    if getattr(args, "keygen", False):
        return _confirm_keygen(st, args)
    if getattr(args, "init", False):
        return _confirm_init(st)
    bad(add_fix("confirm 需指定 --keygen 或 --init（v2.5.7 起已移除 --approve；"
                "人类签名改在 `apply` 时交互式完成）",
                "生成/轮换密钥用 --keygen/--init；应用 requires_human 提案直接在 apply 时输入口令签绑定签名"))
    return 2


# ---------------------------------------------------------------- meta-log（Phase 2.1）

def cmd_meta_log(st: Store, args):
    """查询元认知日志（最近 N 天）"""
    days = getattr(args, "days", None) or 7
    if not st.meta_log.exists():
        info("=== 元认知日志（最近 {} 天） ===".format(days))
        info("  暂无记录。触发条件：连续 3 次 REVERT 的 verdict --auto-m1、PROMOTE/REVERT 裁决。")
        return 0
    result = analyze_meta_log(st, days)
    info("=== 元认知日志（最近 {} 天） ===".format(days))
    info("总条目: {}".format(result["total_entries"]))
    info("近期条目: {}".format(result["recent_entries"]))
    info("事件分布: {}".format(result["event_distribution"]))
    if result["insights"]:
        shown = result["insights"][-5:]
        info("\n--- 洞察（最近 {} 条） ---".format(len(shown)))
        for ins in shown:
            info("[{}] {}: {}".format(ins["timestamp"], ins["event_type"], ins["insight"]))
    return 0


# ---------------------------------------------------------------- init-domain（Phase 2.2）

def cmd_init_domain(st: Store, args):
    """初始化领域实例（code_review / paper_review / document_editing）"""
    from domains.init import init_domain
    try:
        user_config = None
        if getattr(args, "config", None):
            cfg_path = Path(args.config)
            if not cfg_path.exists():
                bad(add_fix("配置文件不存在: {}".format(cfg_path),
                    "核对路径是否正确，用绝对路径更稳：`--config C:/path/cfg.json`",
                    "或去掉 --config 用模板默认字段初始化"))
                return 2
            try:
                user_config = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                bad(add_fix("配置解析失败: {}".format(e),
                    "确认是合法 JSON：键与字符串用双引号，末尾不要有逗号",
                    "最小样例：`{\"max_lines\": 200}`",
                    "可用 `python -m json.tool 你的文件.json` 自检格式"))
                return 2
        result = init_domain(args.domain, Path(args.output), user_config)
        ok("领域 '{}' 初始化成功".format(result["domain"]))
        ok("路径: {}".format(result["path"]))
        ok("制品: {}".format(", ".join(result["artifacts"])))
        info("\n下一步:")
        info("  cd {}".format(result["path"].parent))
        info("  python metacog.py episode --task '...' --events accepted=1 --violations 0")
        info("  # 操 作 1：效用由事件推导；无事件才 --utility 0.7 兜底（不驱动沉淀）")
        info("  python metacog.py status")
    except ValueError as e:
        bad(add_fix(str(e), "检查 --domain 取值与 --config 字段是否匹配模板"))
        return 2
    except Exception as e:  # noqa: BLE001 - 初始化失败需明确回报，不静默
        bad(add_fix("初始化失败: {}".format(e),
            "检查 --output 目录可写、--domain 取值为 code_review/paper_review/document_editing"))
        return 2
    return 0


# P2 修复：CLI 接线（惰性导入，打破与 meta_optimizer / domain_detector 的循环依赖）
def cmd_optimize(st, args):
    """包装 meta_optimizer.cmd_optimize：基于元认知日志生成自动优化提案。"""
    from meta_optimizer import cmd_optimize as _run
    return _run(args)


def cmd_detect_domain(st, args):
    """包装 domain_detector.cmd_detect_domain：根据内容自动检测领域。"""
    from domain_detector import cmd_detect_domain as _run
    return _run(args)


# ---------------------------------------------------------------- main


def _check_version_binding():
    """v2.9.0（L-3 / H-2）：SKILL.md `version:` 头须与 Store.CURRENT_VERSION_TUPLE 一致；
    不一致（升级漏改）→ legacy 截止期判定永久失效。返回 (ok, detail)；非致命，供 main() 告警。"""
    try:
        _sk = Path(__file__).resolve().parent.parent / "SKILL.md"
        if not _sk.exists():
            return (True, "no SKILL.md present")
        _txt = _sk.read_text(encoding="utf-8")
        _m = re.search(r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)", _txt, re.M)
        if not _m:
            return (True, "no version: field")
        _decl = tuple(int(x) for x in _m.group(1).split("."))
        _ok = _decl == Store.CURRENT_VERSION_TUPLE
        return (_ok, "declared={} tuple={}".format(_m.group(1), Store.CURRENT_VERSION_TUPLE))
    except Exception as _e:
        return (True, "check error: {}".format(_e))


def main(argv=None):
    # v2.9.0（L-3 / H-2）：版本零绑定运行时软闸——SKILL.md version 头须与 CURRENT_VERSION_TUPLE 一致，
    # 不一致（漏改）→ legacy 截止期可能失效；非致命告警（不崩主流程），供运营巡检发现。
    _vb_ok, _vb_msg = _check_version_binding()
    if not _vb_ok:
        warn("[版本绑定] SKILL.md version 与 CURRENT_VERSION_TUPLE 不一致（{}）："
             "legacy 截止期可能失效，请同步版本号。".format(_vb_msg))
    ap = argparse.ArgumentParser(
        prog="metacog",
        description="声明式元认知自修改引擎：让 Agent 在使用中变聪明，且不会误演化。",
    )
    ap.add_argument("--root", default=DEFAULT_ROOT, help="契约目录（默认 .metacog）")
    ap.add_argument("--explain", action="store_true",
                   help="打印「常见错误索引 / 排查清单」后退出（无需 .metacog，放在子命令前）")
    sub = ap.add_subparsers(dest="cmd", required=False)

    sub.add_parser("init", help="初始化契约目录与五制品")

    e = sub.add_parser("episode", help="记录一次任务的归因结果")
    e.add_argument("--task", required=True, help="任务简述")
    e.add_argument("--events", action="append", metavar="KEY=COUNT",
                   help="操作 1：可观测事件推导效用，可重复。例：--events rework=1 "
                        "--events accepted=1。可用键：{}".format(", ".join(META_EVENTS)))
    e.add_argument("--events-json", metavar="JSON",
                   help="操作 1：一次性传事件 JSON 对象，如 '{\"rework\":1,\"accepted\":1}'，"
                        "与 --events 合并（--events 优先累加）")
    e.add_argument("--utility", type=float, required=False, default=None,
                   help="[deprecated] 声明式效用 0~1；操作 1 起以 --events 推导值为准，"
                        "仅当无事件时作兜底，且声明的效用不驱动沉淀（不参与基线/验收）")
    e.add_argument("--violations", type=int, default=0, help="违规/返工次数")
    e.add_argument("--attributed", choices=list(ARTIFACTS), help="归因到哪个制品（操作3起必填）")
    e.add_argument("--note", help="备注")

    p = sub.add_parser("propose", help="提议一次自修改（进隔离区，不直接生效）")
    p.add_argument("--artifact", required=True, choices=list(ARTIFACTS))
    p.add_argument("--op", default="add", choices=["add", "replace", "remove"])
    p.add_argument("--content", help="条目正文")
    p.add_argument("--content-file", help="从文件读取正文")
    p.add_argument("--target", help="replace/remove 的目标条目 ID")
    p.add_argument("--reason", help="为什么要改")
    p.add_argument("--episode", action="append", help="证据 episode ID（可重复）")

    g = sub.add_parser("gate", help="G1 写入闸：红线 + 不动点 + 证据门槛")
    g.add_argument("--id", help="只审指定提议")

    a = sub.add_parser("apply", help="把过闸提议写入制品，进入试用期")
    a.add_argument("--id", help="只应用指定提议")
    a.add_argument("--sig", help="W1（M-7）：人类绑定签名（覆盖「提案 id + 内容哈希 + 试用窗起点 trial_from_index」）。"
                                 "可由 `apply` 交互式 TTY 口令签生成，或预生成经本参数传入；apply 用公钥验签，"
                                 "Agent 不持私钥故无法伪造；缺省则 apply 交互式要求人类口令签绑定签名")
    a.add_argument("--human-ok", action="store_true",
                   help="[已废除] W1 起 requires_human 提议只认 --sig 密码学签名；本布尔旗标 AI 可自置，"
                        "会被硬拦截并指路 confirm 流程")
    a.add_argument("--git", action="store_true", help="应用后 git commit 留底（D5 起 git 仓库默认开启）")
    a.add_argument("--no-git", action="store_true", help="D5：即便 git 仓库也关闭自动留底")

    rs = sub.add_parser("resign", help="M-4：重签已有受信任锚为绑定签名（保留原始试用窗起点）")
    rs.add_argument("--id", help="重签指定提议")
    rs.add_argument("--sig", help="M-4：预生成绑定签名（覆盖「提案 id + 内容哈希 + trial_from_index」）；缺省则 TTY 口令签")

    cf = sub.add_parser("confirm", help="W1 人类闸密钥管理：生成/轮换人类 RSA 密钥对（人类 TTY）")
    cf.add_argument("--keygen", action="store_true", help="生成 RSA-2048 密钥对（私钥口令加密落盘，公钥明文存盘）；幂等")
    cf.add_argument("--init", action="store_true", help="轮换解锁私钥的口令（旧口令解密 → 新口令重加密）")
    cf.add_argument("--nonce-file", help="C-2 离线授权：指向人工预置于加密卷/硬件令牌的一次性授权凭据文件；"
                                          "keygen 须据此授权（取代键盘确认），防 Agent 经 pty/Bash 静默重置信任根；用毕自动删除")
    cf.add_argument("--enable-external", choices=["hsm", "oob", "hsm+oob"],
                    help="v2.7.0 启用外部锚（密码学层外部化，非 C-1 真正闭合）：离线 RSA 根权威；"
                         "hsm=设备证明后端，oob=人工带外签名令牌 fail-closed，hsm+oob=二者混合；"
                         "须配合 --root-pubkey / --attestation-path / --oob-token-dir；"
                         "仅在人类 TTY 在场时生效（C-1 未真正闭合，见 HANDOFF ⑦）")
    cf.add_argument("--root-pubkey", help="v2.7.0 离线 RSA 根公钥（人类离线生成、私钥永不可落 Agent 可写域）；"
                                          "启用外部锚必填，Agent 仅持此公钥验签")
    cf.add_argument("--attestation-path", help="hsm 后端：设备证明文件路径（须位于 Agent 无写权限目录，由人类离线签名）")
    cf.add_argument("--oob-token-dir", help="oob 后端：带外确认令牌目录（须位于 Agent 无写权限目录，由人类离线签名）")
    cf.add_argument("--root-privkey", help="v2.7.4 可选：离线 RSA 根私钥（人类离线持有）；提供则基线经离线根"
                                          "签名认证，闭合 NEW-H1 一致化改写。仅启用外部锚的 setup 瞬间传入，"
                                          "严禁落盘于 Agent 可写域（与 --root-pubkey 同源、私钥不可持久化）。")
    cf.add_argument("--purge-external-anchor", action="store_true",
                    help="v2.7.7 回收外部锚全部足迹（ledger 信任根 trust-root.json/.external-anchor-enabled "
                         "+ 固定外部证明目录 root-pubkey.pem 与基线）；须人类 TTY 在场时调用；"
                         "半败返回 partial，须手动补清残留目录后再 re-enable（切勿直接 re-enable 以免钉固公钥被覆盖）。")

    v = sub.add_parser("verdict", help="双指标棘轮裁决：promote 或 revert")
    v.add_argument("--force", action="store_true", help="窗口未满也裁决")
    v.add_argument("--git", action="store_true",
                   help="裁决后 git commit 留底（PROMOTE/REVERT 均可追溯，非破坏回滚；D5 起 git 仓库默认开启）")
    v.add_argument("--no-git", action="store_true", help="D5：即便 git 仓库也关闭自动留底")
    v.add_argument("--adaptive", action="store_true",
                   help="启用棘轮自适应阈值：按当前违规率动态收紧/放宽判定基线")
    v.add_argument("--auto-m1", action="store_true",
                   help="连续3次REVERT时自动创建M1元层自省提议（仍需人类 --sig 密码学签名确认）")

    sub.add_parser("status", help="基线、制品统计、是否真在变聪明")

    rt = sub.add_parser("retrieve", help="G2 检索闸：输出可用制品条目")
    rt.add_argument("--artifact", choices=list(ARTIFACTS))
    rt.add_argument("--strict", action="store_true", help="只输出 active，排除试用期")
    rt.add_argument("--json", action="store_true")

    vf = sub.add_parser("verify", help="D4：系统级完整性校验（比对制品哈希与 ledger 快照，检直写篡改）")
    vf.add_argument("--artifact", choices=list(ARTIFACTS), help="只校验指定制品（默认全部）")

    rb = sub.add_parser("rollback", help="D5：字节级回滚（还原制品到经 apply 的真值）")
    rb.add_argument("--artifact", required=True, choices=list(ARTIFACTS), help="要还原的制品")
    rb.add_argument("--entry", help="要还原的条目 ID（默认该制品最近一次回滚快照）")
    rb.add_argument("--git", action="store_true", help="强制走 git checkout（非破坏）")
    rb.add_argument("--no-git", action="store_true", help="强制走 ledger 快照（不走 git）")
    rb.add_argument("--yes", action="store_true",
                   help="v2.8.7 F-3：显式确认——rollback 会重基线制品完整性快照，须人类确认才执行")

    ml = sub.add_parser("meta-log", help="查询元认知日志（最近 N 天反思记录）")
    ml.add_argument("--days", type=int, default=7, help="查询最近 N 天的日志（默认 7 天）")

    idm = sub.add_parser("init-domain", help="从领域模板初始化领域实例（code_review/paper_review/document_editing）")
    idm.add_argument("domain", choices=list(DOMAIN_TEMPLATES), help="领域名称")
    idm.add_argument("--output", "-o", default=".", help="输出目录（默认当前目录）")
    idm.add_argument("--config", "-c", help="JSON 配置文件（可选，覆盖模板字段）")

    opt = sub.add_parser("optimize", help="基于元认知日志的自动优化提案（默认 dry-run）")
    opt.add_argument("--dry-run", action="store_true", default=True,
                     help="仅分析、不落地优化提案（默认开启）")
    opt.add_argument("--apply", action="store_false", dest="dry_run",
                     help="将优化提案实际落地（实验性，谨慎使用）")

    dd = sub.add_parser("detect-domain",
                        help="根据内容自动检测领域（code_review/paper_review/document_editing）")
    dd.add_argument("--file", "-f", help="输入文件路径")
    dd.add_argument("--text", "-t", help="直接传入待检测文本")

    try:
        args = ap.parse_args(argv)
    except SystemExit as _e:
        # argparse 级错误（未知子命令/非法 choice/缺必填项）会以退出码 2 直接退出，
        # 走不到下方的 `if rc == 2` 检查。在此补一次文档指引，兑现「每次退出码 2 都指文档」。
        if _e.code == 2:
            _hint_rc2()
        raise
    if getattr(args, "explain", False):
        return _print_explain()
    if args.cmd is None:
        ap.print_usage(sys.stderr)
        _hint_rc2()
        return 2
    st = Store(Path(args.root).resolve())
    if args.cmd not in ("init", "init-domain", "detect-domain") and not st.root.exists():
        print("错误: {} 不存在，先跑 `python metacog.py init`".format(st.root), file=sys.stderr)
        _hint_rc2()
        return 2
    rc = {
        "init": cmd_init, "episode": cmd_episode, "propose": cmd_propose,
        "gate": cmd_gate, "apply": cmd_apply, "verdict": cmd_verdict,
        "status": cmd_status, "retrieve": cmd_retrieve, "verify": cmd_verify,
        "rollback": cmd_rollback, "meta-log": cmd_meta_log, "confirm": cmd_confirm,
        "resign": cmd_resign,
        "init-domain": cmd_init_domain, "optimize": cmd_optimize,
        "detect-domain": cmd_detect_domain,
    }[args.cmd](st, args)
    if rc == 2:
        _hint_rc2()
    return rc


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # 旧版 Python 或流不可配置
    sys.exit(main())
