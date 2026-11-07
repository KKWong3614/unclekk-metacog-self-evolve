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
import contextlib
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

# v2.27.17（C-01 收口）：源码内嵌默认锚常量已**删除**（"宁可装不上，不可自签"）。
# 账本签名锚密钥唯一来源 = 环境变量 METACOG_TRUST_ROOT_ANCHOR_KEY（专属随机密钥，base64，≥32 字节）；
# 原兜底 METACOG_TRUST_ROOT_ALLOW_DEFAULT 同步废除。未配置 → _resolve_anchor_key() 抛
# LedgerAnchorDefaultError（fail-closed 拒绝启动），见该函数。

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
    """读取 JSON 文件，失败时返回默认值。

    v2.27.15（M-05 收口·部分）：解析失败（文件存在但非合法 JSON / 读取异常）不再静默——
    输出 stderr 告警后仍返回 default（保持 API 兼容）。安全路径不得依赖本函数对
    「缺失/损坏 → 空」的 fail-open 语义做green判定，缺失=空的口径由调用方显式声明。"""
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as _e:
        print("  [WARN] read_json 解析失败（{}: {}），返回 default——文件存在但损坏属异常态，请人工核验: {}".format(
            type(_e).__name__, _e, p), file=sys.stderr)
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
    """追加写入 JSONL。原子性实测口径（v2.25.17 修正，原注释「原子追加」夸大）：
    单条追加（tempfile + open("a")）在 OS 层近似原子，但**不含读-判断-写原子性**——
    跨进程的「检查→追加」序列必须配合 _applies_lock 等文件锁使用（见 consume_human_sig_atomic）。"""
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


@contextlib.contextmanager
def _applies_lock(st):
    """v2.25.17（C-2 收口）：applies/sig-claims 消费临界区锁——跨平台文件锁。

    Hermes v2.25.16 复验（C-2）：use-once 检查与落账原相隔 116 行、无锁，双消费实测成立
    （单进程顺序测试对此类缺陷结构性盲区）。本锁把「检查 → 落账 → 基线刷新」包进同一临界区。
    实现：Windows 用 msvcrt.locking（LK_LOCK 阻塞重试），POSIX 用 fcntl.flock；
    锁文件 ledger/.applies.lock（内容无关，仅锁字节区间）。"""
    lock_path = st.root / "ledger" / ".applies.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            if not f.read(1):
                f.write("0")
                f.flush()
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        f.close()


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


def read_jsonl(p: Path, max_size: int = None):
    """读取 JSONL 文件（逐行流式，无人为大小上限）。

    v2.27.16（H-4 收口）：移除原 512KB 硬截断——大文件（如长期运行的 applies.jsonl）不再被
    误判为「无记录」，避免条目审计对**健康大库**全量误报（原 512KB 超限返回 [] 会把所有已
    apply 非种子条目报成疑似注入，且文案诱导用户关掉 --no-audit-entries 控制）。调用方若确有
    上限需求可显式传 max_size 自行裁定；默认不做截断。读取失败（OSError）→ 返回 []（fail-open
    语义保留，但不再因「文件大」而截断）。"""
    if not p.exists():
        return []
    if max_size is not None:
        try:
            _size = p.stat().st_size
            if _size > max_size:
                print("  [WARN] 文件 {} KB 超过建议上限 {} KB：未截断，仍逐行解析；如需硬上限请调用方处理".format(
                    _size // 1024, max_size // 1024), file=sys.stderr)
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


def _episodes_len(st) -> int:
    """trial_from_index 口径（v2.25.16）：episodes 物理行数，**不经 read_jsonl 的 512KB 上限**。

    Hermes v2.25.14-15 审计接收复核 Confirmed：read_jsonl 超限返回空 → t0 恒 0，
    旧签名复活 + 「签名后记账防重放」静默失效。sign（_confirm_sign）与 apply（验签处、
    record_apply 落盘处）必须同用本函数，保证绑定口径一致且超限不静默降级。

    v2.25.17（M-3 边界声明，Hermes 复验）：本函数返回**物理行数**，不是 episode 记录数——
    空行/垃圾行也计入。签名绑定三元组 (id, chash, t0) 中 t0 只防「行数变化」，
    **不覆盖 episodes 记录内容的改写**（chash 只绑定提案内容）；行数不变的内容篡改
    须由 episodes 完整性机制（D4/integrity）另行防护，勿把本口径误读为内容绑定。"""
    p = st.episodes
    if not p.exists():
        return 0
    n = 0
    with open(p, "rb") as f:
        for _ in f:
            n += 1
    return n


# v2.25.16（P2 收口）起始、v2.25.17（M-2 收口）扩展：不可见/转义字符 → 可见标记
# （知情同意可视化，防终端渲染与签名对象不一致）。
# v2.25.17 依据 Hermes 复验实测盲区补齐：U+202A-202E（BiDi 嵌入/翻转——U+202E 是经典
# 视觉翻转注入）、U+2066-2069（BiDi isolate）、U+061C（ARABIC LETTER RESET）、
# U+00A0（NBSP）、U+00AD（软连字）、U+180E、U+2028/2029（行/段分隔符）等格式控制字符。
_INVISIBLE_MARKS = (
    ("\x1b", "[ESC]"),
    ("\u200b", "[ZWSP]"),
    ("\u200c", "[ZWNJ]"),
    ("\u200d", "[ZWJ]"),
    ("\u200e", "[LRM]"),
    ("\u200f", "[RLM]"),
    ("\u2060", "[WJ]"),
    ("\ufeff", "[BOM]"),
    # v2.25.17（M-2）：BiDi 与格式控制字符
    ("\u202a", "[LRE]"),
    ("\u202b", "[RLE]"),
    ("\u202c", "[PDF]"),
    ("\u202d", "[LRO]"),
    ("\u202e", "[RTL]"),
    ("\u2066", "[LRI]"),
    ("\u2067", "[RLI]"),
    ("\u2068", "[FSI]"),
    ("\u2069", "[PDI]"),
    ("\u061c", "[ALM]"),
    ("\u00a0", "[NBSP]"),
    ("\u00ad", "[SHY]"),
    ("\u180e", "[MVS]"),
    ("\u2028", "[LS]"),
    ("\u2029", "[PS]"),
    # v2.25.18（M-2 二次扩面，Hermes 二次复验）：空格类格式字符 + 兜底原则
    # （「22 项」是列举完备不是类别完备——补 uncommon 空格；变体选择器在 _visible_text 范围兜底）
    ("\u1680", "[OGHAM]"),
    ("\u2002", "[ENSP]"),
    ("\u2003", "[EMSP]"),
    ("\u2004", "[3/SP]"),
    ("\u2005", "[4SP]"),
    ("\u2007", "[FIGSP]"),
    ("\u2008", "[PUNCTSP]"),
    ("\u2009", "[THINSP]"),
    ("\u200a", "[HAIRSP]"),
    ("\u202f", "[NNBSP]"),
    ("\u205f", "[MMSP]"),
    ("\u3000", "[IDSP]"),
    # v2.25.19（Hermes 三轮实测复验 m-1）：U+2000-200A 空格块补齐
    ("\u2000", "[ENQUAD]"),
    ("\u2001", "[EMQUAD]"),
    ("\u2006", "[6SP]"),
)


def _visible_text(s: str) -> str:
    """ANSI 转义与零宽/BOM 等不可见字符以可见标记替代；其余控制字符（除换行）以 [U+XXXX] 标注。
    v2.25.18：变体选择器（U+FE00-FE0F，可改变前字符渲染形态，列举不完备的类别）范围兜底标注。"""
    for raw, mark in _INVISIBLE_MARKS:
        s = s.replace(raw, mark)
    out = []
    for ch in s:
        o = ord(ch)
        if o < 32 and ch != "\n":
            out.append("[U+{:04X}]".format(o))
        elif 0xFE00 <= o <= 0xFE0F:
            out.append("[U+{:04X}]".format(o))
        else:
            out.append(ch)
    return "".join(out)


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
    def sig_claims(self):
        # v2.25.17（C-2 收口）：人类签名消费标记（use-once 账本）——独立于 applies.jsonl，
        # 由 consume_human_sig_atomic 在文件锁临界区内原子追加 + 即刻建 D4 基线，
        # 使「use-once 检查 → 消费落账 → 基线刷新」窗口收敛为零（Hermes 复验证实的 TOCTOU 双消费）。
        return self.root / "ledger" / "sig-claims.jsonl"

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

    def record_apply(self, proposal_id, trial_from_index, artifact, entry_id, sig=None, content_hash=None, body_hash=None):
        """受信任锚（W1 加固）：apply 闸门写入 trial_from_index + 内嵌人类签名。

        - trial_from_index 仍是试用起点（apply 时 episode 数），verdict 只读此值。
        - 锚内嵌经人类私钥签名的 human_sig + content_hash：Agent 直写 applies.jsonl 伪造锚
          若无有效人类签名 → verdict 一律 HOLD（关闭 7.1）。
        - v2.27.16（H-3 收口）：新增 body_hash（条目正文 SHA 锚）——条目级审计据此比对「正文是否
          与 apply 时一致」，封堵「只保留 id、篡改正文不留痕」的绕过（原扫描仅比 id 不入正文）。"""
        rec = {
            "proposal_id": str(proposal_id),
            "trial_from_index": int(trial_from_index),
            "artifact": artifact,
            "entry_id": entry_id,
            "applied_at": now_iso(),
            "episode_count": int(trial_from_index),
            "human_sig": sig,
            "content_hash": content_hash,
            "body_hash": body_hash,
        }
        append_jsonl(self.applies, rec)
        # H-2（v2.5.8）：受信任锚写入后立刻刷新 applies.jsonl 的 D4 快照，
        # 使直写篡改 t0 能被 cmd_verify / resolve_trial_start 的 D4 校验检出。
        self.record_integrity(self.APPLIES_INTEGRITY_KEY)

    def latest_apply_record(self, proposal_id):
        recs = [r for r in read_jsonl(self.applies) if str(r.get("proposal_id")) == str(proposal_id)]
        return recs[-1] if recs else None

    def human_sig_consumed(self, sig_b64: str) -> bool:
        """v2.25.16（P1 收口）/ v2.25.17（C-1/C-2 收口修订）：use-once 判定。

        查两处消费账本的**原文**子串（base64 字符集无 JSON 转义字符，子串匹配可靠）：
        ① applies.jsonl（v2.25.16 起）——record_apply 落账含签名原文；
        ② sig-claims.jsonl（v2.25.17 起）——consume_human_sig_atomic 原子消费标记。
        两处均刻意不经 read_jsonl（512KB 上限返回空会使消费校验静默失效，同 t0 收口理由）；
        任一读取异常按已消费处理（fail-closed）。
        诚实边界（v2.25.18 口径统一、v2.25.19 按 Hermes 三轮实测复验 H-1 补全）：本判定的强度 =
        「消费账本完整（D4 基线在且匹配+链连续）+ 单进程串行 + 链条目可信」；注意 use-once 判定
        查 **applies 与 sig-claims 两处账本**，完整绕过须**两处齐改**（各自改写+重算基线+向
        chain.jsonl 追加 prev 正确的伪造条目——无需删除任何文件）方可进程内不可检出（自举信任根
        固有边界，见 applies_gate_ok 与 CONTRACT.md 诚实天花板）——进程内无法闭合，须系统级
        部署契约兜底。"""
        for _f in (self.applies, self.sig_claims):
            if not _f.exists():
                continue
            try:
                text = _f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return True
            if sig_b64 in text:
                return True
        return False

    def _integrity_chain_ok_latest(self, key, cur_hash):
        """v2.25.17（C-1 收口配套）：applies_gate_ok 专用链校验。

        与 _integrity_chain_ok 的差异：后者要求链**尾条**是目标 key——在 apply 消费路径上
        不成立（claim 建基线后，record_apply 等其他 record_integrity 会把链尾推走，误伤）。
        本变体：① 全链连续性校验（同原逻辑，任何插入/删除/重排即 False）；
        ② 从链中找**最近一条**目标 key 条目，其哈希须等于当前文件哈希；
        ③ 找不到目标 key 条目 → False（有基线必有链条，出现即篡改，fail-closed）。
        v2.25.18（N-1 收口，Hermes 二次复验）：链文件不存在或为空 → **False**（原 return True
        与 fail-closed 宣称矛盾——单删 chain.jsonl 即可永久关闭链校验且无告警；本方法仅在
        D4 基线已存在时被调用，而 record_integrity 写基线时必然同时写链，「有基线、无链」
        只可能是人为抹除）。"""
        try:
            chain = self.root / "ledger" / "integrity-chain" / "chain.jsonl"
            if not chain.exists():
                return False
            lines = [l for l in chain.read_text(encoding="utf-8").splitlines() if l.strip()]
            if not lines:
                return False
            entries, _ok = self._chain_entries_verified(lines)
            if not _ok:
                return False
            latest = None
            for e in entries:
                if e.get("key") == key:
                    latest = e
            if latest is None:
                return False
            return self._hash_matches(latest.get("hash"), cur_hash, allow_legacy=Store._legacy_hash_allowed())
        except Exception as e:
            warn("[完整性] sig-claims 链校验异常（{}）：{}".format(type(e).__name__, e))
            return False

    def _chain_has_key(self, key) -> bool:
        """v2.25.17：链条中是否存在目标 key 的历史条目（供 applies_gate_ok 判「基线被抹」。"""
        try:
            chain = self.root / "ledger" / "integrity-chain" / "chain.jsonl"
            if not chain.exists():
                return False
            for ln in chain.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                try:
                    if json.loads(ln).get("key") == key:
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return True  # 链读取异常按「有历史」处理（fail-closed）

    def applies_gate_ok(self) -> bool:
        """v2.25.17（C-1 收口）：apply 消费路径专用完整性硬闸。

        Hermes v2.25.16 复验（C-1）：applies_integrity_ok 的「无基线 → True」向后兼容分支
        被实测利用——删 integrity.json 使 use-once 无限消费；删 applies 行则 D4 基线不符
        但校验不在 apply 主流程上、且二次 apply 会把基线覆盖洗白（事后不可检出）。

        本闸对 sig-claims.jsonl（use-once 的权威消费账本）取更严口径：
        - 不存在 / 为空 → True（首次 apply 前的合法空态）；
        - **非空但无 D4 基线 → False（篡改信号，fail-closed）**——正常流程 claim 落账
          与建基线在锁内原子完成，「有账本、无基线」只可能是人为抹除；
        - 有基线 → 哈希 + 链连续性校验（applies_integrity_ok 同源逻辑）。
        applies.jsonl 自身的删行由 human_sig_consumed 查 claims 账本兜住（签名原文仍在 claims）。"""
        try:
            f = self.sig_claims
            cur_text = f.read_text(encoding="utf-8") if f.exists() else ""
            data = read_json(self.integrity, {})
            rec = data.get(self.SIG_CLAIMS_INTEGRITY_KEY)
            if rec is None:
                # 无 integrity.json 基线：查独立链条（chain.jsonl 与 integrity.json 分离存储，
                # 删基线不删链 = 篡改痕迹）——链中存在 sig-claims 历史条目 → 基线被抹，fail-closed
                if self._chain_has_key(self.SIG_CLAIMS_INTEGRITY_KEY):
                    return False
                # 链中从无记录：空文件 = 首次 apply 前合法空态；非空无任何记录 = 异常
                return not cur_text.strip()
            if not cur_text.strip():
                # 空文件但有基线 = 账本被清空 = 篡改（清空账本使 use-once「失忆」正是攻击目标）
                return False
            cur = self._hash_text(cur_text)
            if not self._hash_matches(rec.get("hash"), cur, allow_legacy=Store._legacy_hash_allowed()):
                return False
            return self._integrity_chain_ok_latest(self.SIG_CLAIMS_INTEGRITY_KEY, cur)
        except Exception as e:
            warn("[完整性] sig-claims 闸校验异常（{}）：{}".format(type(e).__name__, e))
            return False

    def consume_human_sig_atomic(self, sig_b64: str):
        """v2.25.17（C-1+C-2 根治）：apply 人类签名消费唯一入口——文件锁临界区内原子执行
        「D4 硬闸 → use-once 检查 → 消费标记落账 → 基线刷新」。

        返回 (ok, reason)；ok=False 时 reason ∈ {"applies-integrity", "consumed"}。
        C-2（TOCTOU）：检查与落账原相隔 116 行且无锁，双消费实测成立；本方法把两者收敛进
        同一临界区（_applies_lock：Windows msvcrt.locking / POSIX fcntl.flock），窗口为零。
        C-1：入口先过 applies_gate_ok（删行/删基线即拒绝）。
        语义注：检查通过即预写消费标记——若 apply 后续步骤失败（如目标条目缺失），签名已
        消费（fail-closed），这防止「检查通过但落账失败」被重放利用。**恢复路径诚实边界
        （v2.27.15 更正，外部审计 N-16：原「人类重新 `confirm --sign` 即可」不总成立）**：
        sigcrypto.sign 为确定性签名（同消息恒同字节）——apply 路径尚有偶然通道（新增一条
        episode 使 t0 变化 → 不同签名）；**resign 路径无通道**（t0 由旧锚固定、chash 由提案
        固定），签名烧毁后该提案永久不可再重签（先备份 .metacog）。nonce 化须与 attestation
        格式迁移一并实施，已并入 C-01 非对称化专项。剩余诚实边界（v2.25.18 口径统一）：攻击者同时改写消费账本、D4 基线与
        完整性链（含追加 prev 正确的伪造链条目）不可检出（自举信任根，须系统级部署契约兜底）。"""
        with _applies_lock(self):
            if not self.applies_gate_ok():
                return False, "applies-integrity"
            if self.human_sig_consumed(sig_b64):
                return False, "consumed"
            append_jsonl(self.sig_claims, {"type": "sig-claim", "sig": sig_b64, "ts": now_iso()})
            self.record_integrity(self.SIG_CLAIMS_INTEGRITY_KEY)
            return True, ""

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
        if not (isinstance(stored, str) and isinstance(current, str)
                and stored.isascii() and current.isascii()):
            return False
        # v2.27.15（L-07）：哈希比较改 hmac.compare_digest（非常量时间 == 属卫生隐患模式）
        if hmac.compare_digest(stored, current):
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

    # v2.25.17（C-1 收口）：签名消费标记账本纳入 D4 快照——Hermes 复验证实「删 applies 行 + 删基线」
    # 可绕过 use-once；sig-claims.jsonl 非空但无基线即视为篡改（fail-closed），消费闸专用。
    SIG_CLAIMS_INTEGRITY_KEY = "ledger/sig-claims.jsonl"

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
        "package.json",   # v2.27.16（M-4 收口）：纳入可信清单基线——防 package.json 被篡改降级重开 legacy 截止期
    )

    def _integrity_path(self, key):
        """D4 快照路径解析：普通制品走 artifact_path；信任根走 human_guard；受信任锚走 applies。"""
        if key == self.GUARD_INTEGRITY_KEY:
            return self.human_guard
        if key == self.APPLIES_INTEGRITY_KEY:
            return self.applies
        if key == self.SIG_CLAIMS_INTEGRITY_KEY:
            return self.sig_claims
        if key == self.EXTERNAL_ANCHOR_JSON_KEY:
            return self.root / "ledger" / "trust-root.json"
        if key == self.EXTERNAL_ANCHOR_SENTINEL_KEY:
            return self.root / "ledger" / ".external-anchor-enabled"
        if key.startswith("meta:"):
            # v2.27.16（H-2 收口）：meta/ 下辅助证据文件（如种子集 seed-ids.json）纳入 D4 基线域，
            # 删种子文件即可被 verify 检出（fail-closed）——封堵「删种子+重跑 init 洗白」面。
            return self.root / "meta" / key[len("meta:"):]
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
        # v2.26.0（方案A，H-2a 手写变体收口）：链条目附 HMAC（覆盖 prev/hash/key/size/at 全载荷），
        # 校验侧对含 mac 条目强制验签、无 mac 条目 fail-closed（见 _chain_entries_verified）。
        entry["mac"] = _chain_entry_hmac(entry)
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

    def _chain_ok_for_verify(self, key, cur_hash):
        """v2.25.20（H-2 收口）：verify 路径专用链校验入口——把链校验补进制品/script/manifest/guard 全域。

        Hermes 三轮实测（H-2）：verify_integrity 原仅比哈希+基线签名（不查链），
        「删 chain.jsonl → 改制品 → 重算基线 → verify rc=0 无痕」成立。
        链文件缺失/为空 → 默认 fail-closed；METACOG_ALLOW_LEGACY_NO_CHAIN=1 时放行
        （v2.5.8 老基线 legacy 兼容，warn 提示重基线）。链存在 → _integrity_chain_ok_latest
        （全链连续 + 最近一条目标 key 条目哈希须匹配当前）。"""
        try:
            chain = self.root / "ledger" / "integrity-chain" / "chain.jsonl"
            if not chain.exists() or not chain.read_text(encoding="utf-8").strip():
                if os.environ.get("METACOG_ALLOW_LEGACY_NO_CHAIN") == "1":
                    warn("[完整性] chain.jsonl 缺失，METACOG_ALLOW_LEGACY_NO_CHAIN=1 已放行"
                         "（legacy 兼容口径，建议尽快重基线建立链）。")
                    return True
                warn("[完整性] chain.jsonl 缺失或为空（key={}）：D4 链校验 fail-closed"
                     "（v2.25.20 H-2 收口——删链洗白不再静默通过；v2.5.8 老基线安装可设 "
                     "METACOG_ALLOW_LEGACY_NO_CHAIN=1 临时放行并尽快重基线）。".format(key))
                return False
            return self._integrity_chain_ok_latest(key, cur_hash)
        except Exception as e:
            warn("[完整性] verify 链校验异常（{}）：{}".format(type(e).__name__, e))
            return False

    def _chain_entries_verified(self, lines):
        """v2.26.0（方案A，H-2a 手写变体收口）：解析链并逐条校验连续性 + HMAC。

        返回 (entries, True) 或 (None, False)。
        规则（对齐 LEGACY_ANCHOR_SIG_CUTOFF 纪元语义）：
        - 含 mac 条目：HMAC 必验（不符 → fail-closed，env 不放行——mac 在但错=明确篡改）；
        - 无 mac 条目（v2.26.0 前安装的 legacy 条目）：
          · 出现在任何 mac 条目**之前**（纯 legacy 链或迁移期前缀）→ 放行 + warn 建议重基线；
          · 出现在 mac 条目**之后**（mac 纪元回潮）→ fail-closed（手写/直写伪造冒充 legacy，
            record_integrity 自 v2.26.0 起必然写 mac）——METACOG_ALLOW_LEGACY_NO_CHAIN=1
            可临时放行（与链缺失同一逃生舱口径），warn 建议重基线；
        - JSON 非法行 / 非 dict / prev 不连续 → fail-closed。"""
        entries = []
        legacy_n = 0
        mac_seen = False
        legacy_after_mac = 0
        prev = ""
        for ln in lines:
            try:
                e = json.loads(ln)
            except Exception:
                return None, False
            if not isinstance(e, dict) or e.get("prev") != prev:
                return None, False  # 非 dict 行或链不连续（被插入/删除/重排）→ 篡改
            if "mac" in e:
                _pl = {k: v for k, v in e.items() if k != "mac"}
                if not hmac.compare_digest(str(e.get("mac", "")), _chain_entry_hmac(_pl)):
                    warn("[完整性] 链条目 HMAC 校验不符（key={}，at={}）：疑似手写/伪造链条目"
                         "（v2.26.0 方案A——H-2a 加链型洗白收口）。".format(e.get("key", "?"), e.get("at", "?")))
                    return None, False
                mac_seen = True
            else:
                legacy_n += 1
                if mac_seen:
                    legacy_after_mac += 1
            prev = e.get("hash", "")
            entries.append(e)
        if legacy_after_mac:
            if os.environ.get("METACOG_ALLOW_LEGACY_NO_CHAIN") == "1":
                warn("[完整性] 链含 {} 条 mac 纪元后的 legacy 无签名条目，METACOG_ALLOW_LEGACY_NO_CHAIN=1 "
                     "已放行（建议尽快重基线建立全 HMAC 链）。".format(legacy_after_mac))
            else:
                warn("[完整性] 链含 {} 条 mac 纪元后的 legacy 无签名条目（v2.26.0 方案A fail-closed——"
                     "record_integrity 必然写 mac，此后出现的无 mac 条目疑似手写伪造；v2.26.0 前升级场景"
                     "可临时设 METACOG_ALLOW_LEGACY_NO_CHAIN=1 放行并尽快重基线）。".format(legacy_after_mac))
                return None, False
        elif legacy_n:
            warn("[完整性] 链含 {} 条 legacy 无签名条目（v2.26.0 前安装），已放行；建议重基线建立全 HMAC 链。".format(legacy_n))
        return entries, True

    def _integrity_chain_ok(self, key, cur_hash):
        """N2'（v2.6.0）：D4 哈希链连续性校验。
        v2.25.20（H-2 收口，Hermes 三轮实测）：链文件不存在或为空 → **fail-closed**（原 v2.6.0
        向后兼容口径 return True 被实测利用——删 chain.jsonl 即永久关闭链校验且无告警；
        record_integrity 写基线时必然同时写链，「有基线、无链」只可能是人为抹除或崩溃中间态）。
        legacy 兼容：v2.5.8 基线（先于 v2.6.0 链机制）的老安装可显式设
        METACOG_ALLOW_LEGACY_NO_CHAIN=1 临时放行（warn 提示尽快重基线）。
        链损坏/不连续/尾条非目标 key/哈希不符 → 返回 False（fail-closed）。
        v2.8.11（H-2）：全方法包 try/except，异常计入 False（fail-closed）而非抛出崩主流程。"""
        try:
            chain = self.root / "ledger" / "integrity-chain" / "chain.jsonl"
            if not chain.exists() or not chain.read_text(encoding="utf-8").strip():
                if os.environ.get("METACOG_ALLOW_LEGACY_NO_CHAIN") == "1":
                    warn("[完整性] chain.jsonl 缺失，METACOG_ALLOW_LEGACY_NO_CHAIN=1 已放行"
                         "（legacy 兼容口径，建议尽快重基线建立链）。")
                    return True
                warn("[完整性] chain.jsonl 缺失或为空（key={}）：D4 链校验 fail-closed"
                     "（v2.25.20 H-2 收口——删链洗白不再静默通过；v2.5.8 老基线安装可设 "
                     "METACOG_ALLOW_LEGACY_NO_CHAIN=1 临时放行并尽快重基线）。".format(key))
                return False
            lines = [l for l in chain.read_text(encoding="utf-8").splitlines() if l.strip()]
            entries, _ok = self._chain_entries_verified(lines)
            if not _ok:
                return False
            tail = entries[-1]
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
                # v2.27.4（R-6 诚实残余标注）→ v2.27.17（C-01 收口改写）：锚密钥未配置时
                # 重基线随后的 _anchor_sig 签名将 fail-closed 拒绝（C-01：源码内嵌默认锚已删除，
                # 「宁可装不上，不可自签」）——本告警提前留痕，指引配置专属随机锚密钥。
                if os.environ.get("METACOG_TRUST_ROOT_ANCHOR_KEY") is None:
                    warn("[完整性] 重基线残余（{}）：锚密钥未配置（未设 METACOG_TRUST_ROOT_ANCHOR_KEY），"
                         "C-01 收口后无默认锚，本次重基线将在锚签名步 fail-closed 拒绝；"
                         "请配置 base64 编码的 ≥32 字节专属随机锚密钥。".format(_mname))
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
                # 注（v2.25.20 H-2 架构口径）：script:/manifest: 域基线由 record_script_integrity 直接写
                # integrity.json（不入链），其防线是 _anchor_sig 基线签名（密钥在代码，重记基线无法伪造）——
                # 链校验不适用于这两域；链校验补在 record_integrity 双写的 artifact/applies/guard 域。
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
            # v2.25.20（H-2 收口）：artifact/applies 域链校验——删链洗白不再静默通过
            if _ok and not self._chain_ok_for_verify(artifact, cur):
                _ok = False
                warn("[完整性] D4 链校验失败（{}）：链缺失/不连续/最近条目与当前不符——疑似删链洗白，已标 dirty。".format(artifact))
            out.append((artifact, _ok, rec.get("hash"), cur))
        # v2.8.11（D-2）：外部锚迁移审计链 HMAC 校验；链断裂/被篡改 → 计入 dirty（fail-closed 报警），不静默。
        try:
            _ma_ok, _ma_cnt = self._verify_migration_audit()
            if not _ma_ok:
                out.append(("audit:migration", False, None, None))
        except Exception:
            out.append(("audit:migration", False, None, None))
        # v2.27.0（R-1/R-2 收口）：应有基线集——keygen 后凡磁盘存在的受跟踪文件其基线键必须存在，
        # 删基线键（R-2 删 manifest:CONTRACT.md / R-1 删 GUARD 域等）即从检测集消失的盲区收口。
        # 仅 keygen 已建立完整基线的安装生效（_keygen_established），未 keygen/老安装不误伤。
        if self._keygen_established():
            _data_keys = set(data.keys())
            # GUARD 基线无条件必存在（keygen 始终 baseline guard；删除即逃逸，与文件是否在场无关）
            if self.GUARD_INTEGRITY_KEY not in _data_keys:
                out.append((self.GUARD_INTEGRITY_KEY, False, None, None))
            for _ek, _ep in self._expected_baseline_items():
                if _ek not in _data_keys:
                    out.append((_ek, False, None, None))
            # v2.27.4（R-5b 收口）：manifest:SKILL.md@body 派生键（SKILL.md 基线存在时）亦须存在，
            # 删除即 drift——此前 _expected_baseline_items 仅产出 manifest:<name> 不含 @body 子键，
            # 删 @body 不计入应有集（盲区）。@body 由 record_script_integrity 随 SKILL.md 一并写入、孤儿清理保留，
            # 故 keygen 安装中其存在是契约；缺失即逃逸。
            if "manifest:SKILL.md" in _data_keys and "manifest:SKILL.md@body" not in _data_keys:
                out.append(("manifest:SKILL.md@body", False, None, None))
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
            # v2.27.3（R-5 收口）：脚本基线签名验签接入硬闸计算层——与 verify_integrity（L1643-1650）
            # 同口径 fail-closed。此前硬闸仅比哈希、从不调 _verify_anchor_sig，攻击者凭 ledger 写权限
            # 直写（或经引擎 API 重记）基线哈希即穿透硬闸（仅 verify 事后报警）。现签名失效（False）或
            # （非 legacy 容忍期）缺失签名（None）→ 计 drift，使硬闸层与报告层口径一致。
            _sig_ok = _verify_anchor_sig(srec)
            if _sig_ok is False:
                _ok = False
                warn("[完整性-硬闸] script: 基线签名失效（{}）：疑似被篡改后伪造签名，已标 drift。".format(skey))
            elif _sig_ok is None and not Store._legacy_anchor_sig_allowed():
                _ok = False
                warn("[完整性-硬闸] script: 基线缺失 _anchor_sig（早于 v2.11 的 legacy 无签名基线）；"
                     "按 v2.11 截止期已 fail-closed，请运行 keygen/apply 重基线。".format(skey))
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
                # v2.27.17（C-01 专项 H-01 删除的连带语义收口）：DenyTrustRoot 细分——
                # 纯未配置（reason=external-anchor-required，trust-root.json 不存在）→ 回落
                # legacy CONTRACT 钉固裁决分支（下方重复三分支，WARN 留痕）；其余 reason
                # （corrupt / no-provider / unknown-backend / inside-writable-root）维持 fail-closed。
                # 依据：H-01（METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR）删除后，未配置部署的
                # external_trust_root() 由 None 变 DenyTrustRoot；若一律 fail-closed，所有
                # 本地/legacy 部署验签全灭。纯未配置不是篡改信号（corrupt / inside-writable-root
                # 才是）；账本锚密钥不受影响——C-01 收口后仍 env-only，绝不回落默认锚。
                if getattr(ext, "reason", "") != "external-anchor-required":
                    return False, ext.reason
                sys.stderr.write(
                    "[metacog] WARN: 未配置外部锚（trust-root.json 缺失），按 legacy 部署回落 "
                    "CONTRACT.md 钉固指纹裁决（human-identity-root）；生产部署请配置外部锚。"
                    "账本签名锚密钥不受此回落影响（C-01：env 专属密钥，无默认兜底）。\n")
                if live == pinned:
                    return True, None
                return False, "pubkey-root-mismatch"
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
        本方法保证现存合法安装在下次 verify/apply/keygen 时补钉固，避免长期停在 legacy 放行。

        v2.27.17（C-01 专项 H-05 默认开的连带收口）：补钉固会变更 CONTRACT.md 内容
        （human-identity-root 节）——H-05 清单硬闸默认开后，若不刷新基线，下一次硬闸命令
        将按清单漂移拒绝（「钉一次固、处处被拒」footgun）。故实际写入钉固后随即
        record_script_integrity() 重基线（调用方已过硬闸，到达此处的 CONTRACT.md 必与基线一致，
        刷新只吸收本次钉固写入，不洗白任何漂移）。"""
        if self.pinned_human_pubkey_fingerprint() is not None:
            return  # 已钉固
        live = self.human_pubkey_fingerprint()
        if live is None:
            return  # 无密钥，留给 keygen 处理
        self.write_human_pubkey_fingerprint(live)
        self.record_script_integrity()

    # ---------------- v2.27.22（C-1 ①）：锚状态 attestation 公钥钉固（结构性可写域闸门）
    ATTEST_PIN_KEY = "anchor_attest_pubkey_sha256"

    def pinned_anchor_attest_pubkey_sha256(self):
        """CONTRACT.md 钉固的 attestation 公钥指纹（SHA-256，64-hex）。缺失/占位符返回 None（legacy 兼容）。

        钉固值由 H-05 硬闸 + L1 冻结保护（CONTRACT.md 属不可动文件）；`anchor_attest_verify`
        加载树外公钥后须与本指纹一致，否则 fail-closed——闭环审计主发现（同用户替换
        pubkey+attestation 双文件伪造）。标记兼容加粗写法：定位键名后取首个冒号后的值。"""
        cpath = self.root / "CONTRACT.md"
        if not cpath.exists():
            return None
        # v2.27.30（M-A2 收口）：解析锚定**行首的 markdown 列表项**（原实现为子串匹配 + 取首个命中，
        # 攻击者只要在权威行之前插入一行含该子串的文本即可改变解析结果）。
        import re as _re
        pat = _re.compile(r"^\s*[-*]\s*\**" + _re.escape(self.ATTEST_PIN_KEY) + r"\**\s*:\s*`?([0-9a-fA-F]{64})`?\s*$")
        hits = []
        for ln in cpath.read_text(encoding="utf-8").splitlines():
            m = pat.match(ln.strip())
            if m:
                hits.append(m.group(1).lower())
        if not hits:
            return None
        uniq = set(hits)
        if len(uniq) > 1:
            # 多处冲突指纹 → 无法确定权威 → fail-closed（抛错，调用方须硬拒）
            raise ValueError("CONTRACT.md 存在 {} 处冲突的钉固指纹：{}".format(len(uniq), sorted(uniq)))
        return hits[0]

    # ---------------- v2.27.32（R-1 双密钥根信任）：根信任公钥 RK 钉固（最高权威）
    # RK 是与 attestation 公钥 AK 不同的第二把密钥，由人类离线持有；其公钥指纹作为
    # 「信任根之根」钉固于此，根锚密封须由 RK 私钥签名、经 RK 公钥验签。此钉固缺失即
    # 无法建立信任根 → fail-closed（不再退化为「未钉固双轨放行」，坐实审计 §3.3 入口 B）。
    ROOT_ATTEST_PIN_KEY = "root_attest_pubkey_sha256"

    def pinned_root_attest_pubkey_sha256(self):
        """CONTRACT.md 钉固的**根信任公钥指纹**（RK_pub SHA-256，64-hex）。缺失返回 None。

        v2.27.32：此钉固是 C-1 信任链的**最高权威**。
        v2.27.33（N-4 口径对齐）：「缺失」的处理由调用方结合**曾武装标记**判定——
        `_attest_enforce_mode` / `_attest_root_integrity` 在 RK_pub 文件或 v1 密封存在时
        把「钉固缺失」判为 fail-closed（疑似删除降级），而非当作「未钉固」放行；
        两者皆缺（真·legacy fresh 态）才按未启用处理。本方法本身只负责忠实解析：
        行首锚定（M-A2）+ 多行冲突抛 ValueError。"""
        cpath = self.root / "CONTRACT.md"
        if not cpath.exists():
            return None
        import re as _re
        pat = _re.compile(r"^\s*[-*]\s*\**" + _re.escape(self.ROOT_ATTEST_PIN_KEY) + r"\**\s*:\s*`?([0-9a-fA-F]{64})`?\s*$")
        hits = []
        for ln in cpath.read_text(encoding="utf-8").splitlines():
            m = pat.match(ln.strip())
            if m:
                hits.append(m.group(1).lower())
        if not hits:
            return None
        uniq = set(hits)
        if len(uniq) > 1:
            raise ValueError("CONTRACT.md 存在 {} 处冲突的根信任指纹：{}".format(len(uniq), sorted(uniq)))
        return hits[0]

    def write_root_attest_pubkey_sha256(self, sha, force=False):
        """把根信任公钥指纹钉入 CONTRACT.md 的 root_attest_pubkey_sha256 节（最高权威，人类持有）。

        与写 AK 钉固同进程执行（特权令牌门已过）；落盘即武装结构性根信任闸门。
        - CONTRACT.md 不存在 / 节缺失 → 追加创建。
        - 占位符（<...>）→ 填入真实指纹。
        - 已有真实值且相符 → 幂等保留。
        - 已有真实值不符 → **硬拒**（RK 变更须授权），除非 force=True（仅可由
          cmd_anchor_root_pub_install 在验证 --rotate-auth（当前 RK 私钥签名授权）后传入，
          v2.27.33 N-2 收口）。
        v2.27.33（DSH §2.5 N-2）：值行匹配从 `key in ln` 子串改为**行首列表项正则**
        （原实现对节标题行（含键名）也命中，`partition(":")` 得到空 old 值 →
        同一把 RK 重装必报「空指纹不符」→ RK 重装/轮换在 CLI 层不可用且自我 DoS）。"""
        cpath = self.root / "CONTRACT.md"
        key = self.ROOT_ATTEST_PIN_KEY
        import re as _re
        val_pat = _re.compile(r"^\s*[-*]\s*\**" + _re.escape(key) + r"\**\s*:\s*`?([0-9a-fA-F]{64})`?\s*$")
        if not cpath.exists():
            cpath.write_text(
                "# 统一不动点契约（Unified Fixed-Point Contract）\n"
                "## 10. 根信任公钥（root_attest_pubkey_sha256 · 最高权威）\n\n"
                "- **用途**：钉固 C-1 双密钥根信任的**根信任公钥 RK** 指纹（v2.27.32）。\n"
                "  根锚密封须由 RK 私钥签名、经 RK 公钥验签；本指纹即 RK 公钥的 SHA-256，\n"
                "  为信任链最高权威——缺失或不符即 fail-closed，不得静默双轨放行。\n"
                "- **root_attest_pubkey_sha256**: `{}`\n".format(sha),
                encoding="utf-8")
            return
        text = cpath.read_text(encoding="utf-8")
        if key not in text:
            section = (
                "\n"
                "## 10. 根信任公钥（root_attest_pubkey_sha256 · 最高权威）\n"
                "\n"
                "- **用途**：钉固 C-1 双密钥根信任的**根信任公钥 RK** 指纹（v2.27.32，最高权威）。\n"
                "  根锚密封须由 RK 私钥签名、经 RK 公钥验签；本指纹为信任链最高权威，\n"
                "  缺失或不符即 fail-closed（攻击者替换 RK 公钥即被本不动点拒绝）。\n"
                "- **root_attest_pubkey_sha256**: `{}`\n".format(sha))
            cpath.write_text(text.rstrip() + "\n" + section, encoding="utf-8")
            return
        lines = text.splitlines()
        new_lines = []
        replaced = False
        for ln in lines:
            m = val_pat.match(ln.strip())
            if m:
                old_val = m.group(1).lower()
                if old_val == sha:
                    new_lines.append(ln)
                elif force:
                    pre = ln.partition(":")[0]
                    new_lines.append("{}: `{}`".format(pre, sha))
                    replaced = True
                else:
                    # v2.27.32：根信任指纹变更须 RK 私钥签名授权（--rotate-auth），此处直接硬拒。
                    raise ValueError("既有根信任指纹 {} 与新值 {} 不符——拒绝覆盖"
                                     "（根信任变更须当前 RK 私钥签名授权 --rotate-auth）".format(old_val[:16], sha[:16]))
            elif key in ln:
                pre, _, post = ln.partition(":")
                old_val = post.strip().strip("`")
                if old_val.startswith("<") and old_val.endswith(">"):
                    new_lines.append("{}: `{}`".format(pre, sha))
                    replaced = True
                else:
                    # 含键名但非 64-hex 值行（说明文字/标题等）→ 原样保留，不做子串改写
                    new_lines.append(ln)
            else:
                new_lines.append(ln)
        cpath.write_text(("\n".join(new_lines) + "\n") if replaced or lines != new_lines
                         else text, encoding="utf-8")

    def write_anchor_attest_pubkey_sha256(self, sha, force=False):
        """把 attestation 公钥指纹钉入 CONTRACT.md 的 anchor-attest-pubkey-root 节（不动点，人类持有）。

        与 anchor-attest-pubkey-install 同进程执行（特权令牌门已过的部署方），落盘即武装结构性闸门。
        - CONTRACT.md 不存在 → 直接创建并钉固。
        - 节缺失 → 追加创建并钉固。
        - 已有占位符 → 填入真实指纹。
        - 已有真实指纹但不符（疑似重装公钥）→ **硬拒**，除非 force=True（force 仅可由已通过
          RK 重钉签名授权的 cmd_anchor_attest_pubkey_install 显式传入，v2.27.32 §10 #3）。
        v2.27.32：移除原 METACOG_ATTEST_REPIN_ALLOW env 自授权；重钉授权改由 RK 私钥签名
        （见 root_repin_sign / root_repin_verify），调用方无法用 env 自行放行。"""
        cpath = self.root / "CONTRACT.md"
        key = self.ATTEST_PIN_KEY
        if not cpath.exists():
            cpath.write_text(
                "# 统一不动点契约（Unified Fixed-Point Contract）\n"
                "## 9. 锚状态 attestation 公钥根（anchor-attest-pubkey-root）\n\n"
                "- **用途**：钉固 C-1 双密钥根信任中的 **attestation 公钥 AK** 指纹（v2.27.32）。\n"
                "  密封背书指纹（由 RK 验签得出）须与本指纹一致，否则 fail-closed。\n"
                "- **anchor_attest_pubkey_sha256**: `{}`\n".format(sha),
                encoding="utf-8")
            return
        text = cpath.read_text(encoding="utf-8")
        if key not in text:
            section = (
                "\n"
                "## 9. 锚状态 attestation 公钥根（anchor-attest-pubkey-root）\n"
                "\n"
                "- **用途**：钉固 C-1 双密钥根信任中的 **attestation 公钥 AK** 指纹（v2.27.32）。\n"
                "  密封背书指纹须与本指纹一致，否则 fail-closed（攻击者替换 AK 公钥即被拒）。\n"
                "- **anchor_attest_pubkey_sha256**: `{}`\n".format(sha))
            cpath.write_text(text.rstrip() + "\n" + section, encoding="utf-8")
            return
        lines = text.splitlines()
        new_lines = []
        for ln in lines:
            if key in ln:
                pre, _, post = ln.partition(":")
                old_val = post.strip().strip("`")
                if old_val.startswith("<") and old_val.endswith(">"):
                    new_lines.append("{}: `{}`".format(pre, sha))  # 占位符 → 写入真实指纹
                elif old_val == sha:
                    new_lines.append(ln)  # 一致 → 保留
                elif force:
                    # v2.27.32：已由 RK 重钉签名显式授权（force=True 仅来自 install 的授权路径）
                    sys.stderr.write(
                        "[metacog][LOUD] CONTRACT.md 既有 AK 指纹 {} 与新值 {} 不符，"
                        "已按 RK 重钉签名授权覆盖——信任根变更，须人工复核。\n"
                        .format(old_val, sha))
                    new_lines.append("{}: `{}`".format(pre, sha))
                else:
                    # v2.27.32（§10 #3）：既有真实指纹不符 → 硬拒（无 env 自授权）。
                    raise ValueError("既有锚 attestation 公钥指纹 {} 与新值 {} 不一致——拒绝覆盖"
                                     "（重钉须 RK 私钥签名授权 --repin-auth）"
                                     .format(old_val[:16], sha[:16]))
            else:
                new_lines.append(ln)
        cpath.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # ---------------- v2.26.0（H-2a/H-2b 收口方案B）：链首指纹人类锚钉固（chain-identity-root）
    CHAIN_FP_KEY = "chain_head_fingerprint"
    CHAIN_FP_EMPTY = "empty-chain-at-keygen"

    def _chain_head_fingerprint(self):
        """v2.26.0（方案B）：当前 D4 链**首条目** hash（append-only 头部——record 追加只动尾部，
        头部永不变化，可持续校验）。链缺失 → None；链存在但为空 → CHAIN_FP_EMPTY 哨兵；
        解析异常 → None（fail-closed 交给校验侧）。"""
        try:
            chain = self.root / "ledger" / "integrity-chain" / "chain.jsonl"
            if not chain.exists():
                return None
            lines = [l for l in chain.read_text(encoding="utf-8").splitlines() if l.strip()]
            if not lines:
                return self.CHAIN_FP_EMPTY
            e = json.loads(lines[0])
            return e.get("hash") if isinstance(e, dict) else None
        except Exception:
            return None

    def write_chain_fingerprint(self):
        """v2.26.0（方案B，H-2b 删链重建收口）：把当前链首指纹钉入 CONTRACT.md chain-identity-root 节。

        与 write_human_pubkey_fingerprint 同构：由 `confirm --keygen` 在人类 TTY 在场时写入
        （人类持有 CONTRACT.md 不动点）。删链后重建的链首条目 hash 必然改变（时间戳等字段
        不可复现），verify/apply 据此检出「删链+删基线+引擎 API 重建」型无痕洗白（H-2b/U4）。
        - CONTRACT.md 不存在 / 节缺失 → 创建节并钉固。
        - 已有值不符（重基线/重装）→ 覆盖并告警（人类在 TTY 可核对）。"""
        fp = self._chain_head_fingerprint()
        if fp is None:
            warn("[链指纹] chain.jsonl 缺失/解析异常，本次未钉固链指纹（重基线后重新 keygen）。")
            return
        cpath = self.root / "CONTRACT.md"
        key = self.CHAIN_FP_KEY
        if not cpath.exists():
            cpath.write_text(
                "# 统一不动点契约（Unified Fixed-Point Contract）\n"
                "## 8. 链身份根（chain-identity-root）\n\n"
                "- **chain_head_fingerprint**: `{}`\n".format(fp),
                encoding="utf-8")
            return
        text = cpath.read_text(encoding="utf-8")
        if key not in text:
            section = (
                "\n"
                "## 8. 链身份根（chain-identity-root）\n"
                "\n"
                "- **用途**：钉固 D4 完整性哈希链的**首条目指纹**（append-only 头部，record 追加不变）。\n"
                "  删链后重建的链首条目 hash 必然改变（时间戳等字段不可复现），verify/apply 据此检出\n"
                "  「删链+重建基线」型洗白（v2.26.0 方案B——H-2b 收口）。由 `confirm --keygen` 在人类\n"
                "  TTY 在场时写入；重基线/重装后须重新 keygen 钉固。\n"
                "- **chain_head_fingerprint**: `{}`\n".format(fp))
            cpath.write_text(text.rstrip() + "\n" + section, encoding="utf-8")
            return
        new_lines = []
        for ln in text.splitlines():
            if key in ln and ":" in ln:
                pre, _, post = ln.partition(":")
                old_val = post.strip().strip("`")
                if old_val != fp:
                    sys.stderr.write(
                        "[metacog] WARN: CONTRACT.md 既有链指纹 {} 与当前 {} 不一致，已覆盖"
                        "（疑似重基线/重装，请人工核对；如非本人操作按篡改处置）。\n".format(old_val, fp))
                new_lines.append("{}: `{}`".format(pre, fp))
            else:
                new_lines.append(ln)
        cpath.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def chain_fingerprint_ok(self):
        """v2.26.0（方案B）：校验当前链首指纹与 CONTRACT.md 钉固值一致（H-2b 删链重建收口）。

        - CONTRACT.md 无钉固（legacy/未 keygen）→ 放行 + warn（建议 keygen 钉固启用检出）。
        - 钉固为 empty 哨兵（keygen 时链为空）：链已建 → 放行 + warn 建议重新 keygen 钉固。
        - 钉固为具体指纹：链缺失/首 hash 与钉固不符 → fail-closed（删链或重建链），
          METACOG_ALLOW_LEGACY_NO_CHAIN=1 可临时放行（与链缺失同一逃生舱口径，warn 提示重新钉固）。"""
        try:
            cpath = self.root / "CONTRACT.md"
            pinned = None
            if cpath.exists():
                for ln in cpath.read_text(encoding="utf-8").splitlines():
                    if self.CHAIN_FP_KEY in ln and ":" in ln:
                        pinned = ln.partition(":")[2].strip().strip("`")
                        break
            if pinned is None:
                # v2.26.1（H-2c 收口，Hermes 五轮 B6 实测）：钉固痕迹=CONTRACT.md 含
                # chain-identity-root 节标题（钉固节曾写入）而值行缺失 → 钉固行被删
                # （删单行文本逃逸路径）→ fail-closed。
                # v2.26.1 修正（test-core 回归暴露）：**不得**用 human-guard.json 存在性作判据——
                # v2.26.0 前 keygen 从不写链指纹，「有 guard 无钉固」是合法历史态（直写 guard 的
                # 既有测试/极老安装均误伤）。两者皆无（未 keygen 老安装/init 未钉固态）→ legacy
                # 放行 + warn。
                # 残余（诚实披露）：攻击者连节标题一并删除 → 判据消失，须 CONTRACT.md manifest
                # 域保护（受保护模式 enforced）或人类带外核对兜底。
                _cpath_txt = cpath.read_text(encoding="utf-8") if cpath.exists() else ""
                if "chain-identity-root" in _cpath_txt:
                    if os.environ.get("METACOG_ALLOW_LEGACY_NO_CHAIN") == "1":
                        warn("[链指纹] CONTRACT.md 钉固行缺失但钉固痕迹存在（疑似被删），"
                             "METACOG_ALLOW_LEGACY_NO_CHAIN=1 已放行；请重新 `confirm --keygen` 恢复钉固。")
                        return True
                    warn("[完整性] CONTRACT.md 缺 chain_head_fingerprint 钉固行，但钉固痕迹存在"
                         "（human-guard 存在或 chain-identity-root 节在）：钉固行疑似被删"
                         "（H-2c——删单行逃逸路径已收口，fail-closed）；"
                         "确认误删可设 METACOG_ALLOW_LEGACY_NO_CHAIN=1 临时放行并重新 keygen。")
                    return False
                warn("[链指纹] CONTRACT.md 尚无 chain_head_fingerprint 钉固（legacy/未 keygen），已放行；"
                     "运行 `confirm --keygen` 钉固链指纹以启用 H-2b 删链重建检出。")
                return True
            cur = self._chain_head_fingerprint()
            if cur == pinned:
                return True
            if pinned == self.CHAIN_FP_EMPTY:
                warn("[链指纹] keygen 时链为空（钉固={}），现已建链；放行并建议重新 keygen 钉固链首指纹。".format(pinned))
                return True
            if os.environ.get("METACOG_ALLOW_LEGACY_NO_CHAIN") == "1":
                warn("[链指纹] 链首指纹与钉固不符（钉固={}，当前={}），METACOG_ALLOW_LEGACY_NO_CHAIN=1 "
                     "已放行（重基线/重装场景请重新 keygen 钉固）。".format(pinned, cur))
                return True
            warn("[完整性] 链首指纹与 CONTRACT.md 钉固不符（钉固={}，当前={}）：疑似删链重建或重基线未重新钉固"
                 "（v2.26.0 方案B——H-2b 收口）；确认合法重装后重新 `confirm --keygen`，否则按篡改处置。".format(pinned, cur))
            return False
        except Exception as e:
            warn("[完整性] 链指纹校验异常（{}）：{}".format(type(e).__name__, e))
            return False

    # ---------------------------------------------------------------- v2.27.0（R-1/R-2 收口）：应有基线集
    def _keygen_established(self):
        """v2.27.4（R-4 收口）：判定技能是否已 keygen（建立完整基线集）的**可信**信号。

        旧实现（v2.27.0–v2.27.3）把判定建立在「被保护物自身」上——CONTRACT.md 的 chain-identity-root
        文本 或 integrity.json 的 GUARD 基线键——攻击者连删 chain-identity-root 节标题 + GUARD 基线键 +
        全部 manifest 基线键 即令 `_keygen_established()=False` → verify_integrity / 硬闸的「应有基线集」
        闸门整体失效、verify/apply 全绿（八轮 R-4 双删逃逸，自指闸门）。

        新实现改为依赖**两路独立证据、任一成立即视为已 keygen**（强制基线集）：
          - human-guard.json 密钥对文件存在（keygen 落盘、init/legacy 不创建、删基线键不删它）；
          - 或 CONTRACT.md 含 chain-identity-root 链身份根（keygen 写入、cmd_init 模板不含、
            删 GUARD 基线键不删它）。
        两路来自不同攻击面、互相兜底：
          - R-4 双删逃逸删 chain 文本 + GUARD 基线键 + 全部 manifest 键，但删不掉 keypair 文件
            → 文件证据成立 → 闸门仍 True（manifest 基线缺失仍检出）；
          - R-1 删 keypair 文件 + GUARD 基线键，但删不掉 chain 文本 → chain 证据成立 → 闸门仍 True
            （GUARD 基线缺失仍被 verify_integrity / 硬闸检出，不静默通过）；
          - 仅当 keypair 文件 + chain 文本**皆删**（彻底破坏态）→ 返 False，由 cmd_verify GUARD 块
            （grec 缺失 → bad）fail-closed 兜底，不再静默通过。
        注：CONTRACT.md 的 human-identity-root 钉固节由 cmd_init 模板写入（init 即存在），不可作为
        keygen 判据，故不纳入本函数（避免 init/legacy 安装误判为已 keygen 致硬闸误报，见 v2.27.4 回归）。"""
        if self.human_guard.exists():
            return True
        cpath = self.root / "CONTRACT.md"
        if cpath.exists() and "chain-identity-root" in cpath.read_text(encoding="utf-8"):
            return True
        return False

    def _expected_baseline_items(self):
        """v2.27.0（R-1/R-2）：返回「磁盘上存在的受跟踪文件」→ 其对应基线键 的迭代（key, path）。

        - manifest:/script:/核心制品（A1-M1）：仅纳入磁盘真实存在的文件，避免非 shipped 部署的
          脚本/清单缺文件却要求基线而误报；文件存在而基线键缺失 → 删键逃逸（R-2 删 manifest:CONTRACT.md 等）。
        - GUARD（human-guard.json）不在此处产出——其基线在 keygen 后**必须**存在（无论文件是否在场），
          由 verify_integrity 的「GUARD 基线无条件必存在」分支单独兜底（R-1 删 GUARD 基线+删文件亦检出）。"""
        for _name in self.MANIFEST_NAMES:
            _p = self.root / _name
            if _p.exists():
                yield ("manifest:" + _name, _p)
        for _name in self.SCRIPT_NAMES:
            _p = self.script_dir / _name
            if _p.exists():
                yield ("script:" + _name, _p)
        for _code in ARTIFACTS:
            _p = self.artifact_path(_code)
            if _p.exists():
                yield (_code, _p)

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

        v2.27.17（C-01 专项 L-06/nonce 化）：签名串支持两级格式——
        - ``v2:{nonce}:{b64sig}``（新）：b64sig 为 v2 长度前缀消息（含 nonce 字段）的签名，四级回退第 1 级；
        - 裸 b64（存量）：按四级回退依次尝试——
          ① v2 长度前缀消息（含 t0、无 nonce，确定性构造）；
          ② 旧格式含 t0（M-7 绑定）；
          ③ 旧格式无 t0 → (False, "legacy-unbound")（未绑定 t0，一律 HOLD 要求重签）。

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
            pub = sigcrypto.deserialize_pub(pub_serialized)
        except Exception:
            return False, "bad-pubkey"
        # v2.27.17：解析 v2:{nonce}:{b64sig} 前缀格式；否则按存量裸 b64 处理
        _nonce = None
        _b64 = sig_b64
        if isinstance(sig_b64, str) and sig_b64.startswith("v2:"):
            _parts = sig_b64.split(":", 2)
            if len(_parts) != 3 or not _parts[1] or not _parts[2]:
                return False, "bad-sig-encoding"
            _nonce, _b64 = _parts[1], _parts[2]
        try:
            sig = base64.b64decode(_b64, validate=True)
        except Exception:
            return False, "bad-sig-encoding"
        chash = proposal_content_hash(p)
        if anchor_chash is not None and anchor_chash != chash:
            return False, "content-hash-mismatch"
        _pid = str(p["id"])
        # 四级回退（见 docstring）：任一级验签通过且为绑定语义即 (True, None)
        if _nonce is not None:
            if sigcrypto.verify(pub, sigcrypto.approval_message(_pid, chash, t0, nonce=_nonce), sig):
                return True, None
            return False, "invalid-signature"
        # 存量裸 b64：① v2 无 nonce（覆盖 t0）
        if sigcrypto.verify(pub, sigcrypto.approval_message(_pid, chash, t0), sig):
            return True, None
        # ② 旧格式含 t0（M-7 绑定）
        if sigcrypto.verify(pub, sigcrypto.approval_message_legacy(_pid, chash, t0), sig):
            return True, None
        # ③ 旧格式无 t0 → legacy-unbound（未绑定 t0），要求重签
        if sigcrypto.verify(pub, sigcrypto.approval_message_legacy(_pid, chash), sig):
            return False, "legacy-unbound"
        return False, "invalid-signature"

    def bind_human_signature(self, p, chash, t0, passphrase=None):
        """W1（M-7 闭环）：TTY 提示口令解锁私钥，对绑定消息 (id, chash, t0) 签名，返回签名串。

        v2.27.17（C-01 专项 L-06/nonce 化）：每次绑定生成一次性 nonce（new_nonce()），
        对 v2 长度前缀消息（含 nonce 字段）签名，返回 ``v2:{nonce}:{b64sig}``——
        每次绑定的签名串互不相同，消除「确定性签名可预先离线制作后换时重放」的构造面。

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
        _nonce = sigcrypto.new_nonce()
        msg = sigcrypto.approval_message(str(p["id"]), chash, t0, nonce=_nonce)
        sig = sigcrypto.sign(priv, msg)
        return "v2:{}:{}".format(_nonce, base64.b64encode(sig).decode("ascii"))


# ---------------------------------------------------------------- v2.8.6 N-5/N-7：集中脚本完整性硬闸
def _script_integrity_drift_if_enforced(st):
    """v2.8.6（替代 apply/resign/retrieve/keygen 四处复制粘贴的同款逻辑，关 N-7 重复 + N-5 静默 fail-open）：
    集中计算脚本完整性硬闸漂移。
    v2.27.17（C-01 专项 H-05 收口）：硬闸**默认开**——原条件「外部锚已启用 或 METACOG_TRUST_ROOT_STRICT=1」
    实为 opt-in，且被 H-01 逃生舱（METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1 → external_trust_root()
    返 None）一句 env 整体旁路（审计实证的 H-01→H-05 削弱链；H-01 本版已删）。现默认强制，
    仅显式 METACOG_TRUST_ROOT_LENIENT=1（严格 =="1"）才退出并 warn 留痕。
    integrity.json 不存在（未建基线）→ 不触发（全新/未基线部署不误伤）。
    返回 (enforced, drift_list)；drift_list 非空即脚本基线漂移。"""
    if not st.integrity.exists():
        return (False, [])
    if os.environ.get("METACOG_TRUST_ROOT_LENIENT", "") == "1":
        warn("[完整性-硬闸] METACOG_TRUST_ROOT_LENIENT=1：本轮显式跳过脚本完整性硬闸"
             "（H-05 默认开的显式退出，留痕）——本输出不含脚本基线漂移阻断。")
        return (False, [])
    _drift = [k for k, ok in st.verify_script_integrity() if not ok]
    return (True, _drift)


# ---------------------------------------------------------------- v2.8.9 ⑤：manifest 分文件硬闸
def _manifest_integrity_drift_if_enforced(st):
    """v2.8.9 ⑤：可信清单分文件硬闸——Hermes H-01 收口 F-4 纸面闭环（H-3 攻击链）。
    v2.27.17（C-01 专项 H-05 收口）：硬闸**默认开**（原「外部锚已启用 或 STRICT=1」opt-in 已翻转，
    退出口径与 _script_integrity_drift_if_enforced 一致：仅显式 METACOG_TRUST_ROOT_LENIENT=1）；
    未建基线 → 不触发。
    阻断集（内容篡改，须人类确认后重基线方可解除）：
      - SKILL.md 正文变更（仅版本号变更豁免，因版本升级必改 SKILL.md 头）；
      - CONTRACT.md / HANDOFF.md / pack.sh 任一内容变更。
    非阻断（仅 dirty 计数）：CHANGELOG.md（版本升级产物）。
    返回 (enforced, drift_list)；drift_list 非空即阻断态 manifest 漂移。"""
    if not st.integrity.exists():
        return (False, [])
    if os.environ.get("METACOG_TRUST_ROOT_LENIENT", "") == "1":
        warn("[完整性-硬闸] METACOG_TRUST_ROOT_LENIENT=1：本轮显式跳过清单完整性硬闸"
             "（H-05 默认开的显式退出，留痕）——本输出不含清单漂移阻断。")
        return (False, [])
    data = read_json(st.integrity, {})
    _allow_legacy = Store._legacy_hash_allowed()
    _drift = []
    # v2.27.2（N-2 收口）：复用 _expected_baseline_items 获取「磁盘存在的受跟踪 manifest
    # → 其基线键」。凡该基线键缺失（_rec is None，删键逃逸）即计入 drift——与 verify_integrity
    # 的「应有基线集」（R-2）同口径，闭合 apply/resign 入口硬闸的删键盲区。
    # 闸门：仅当安装已 keygen（_keygen_established()，即「完整基线集应当存在」）才对缺失键计入 drift。
    #   - 已 keygen 安装被删 manifest 基线键（攻击者保留 chain-identity-root / GUARD 基线）→ 仍检出（N-2 闭合）；
    #   - 未 keygen / init 占位 / legacy 未钉固 store → 不产生误报（与正常兼容流及既有套件一致）。
    # 注意：不可用「integrity 中是否存在任一 manifest: 键」作闸门——那会让「删光全部 manifest 基线键」
    #   的攻击重新逃逸（删光后闸门为假）。_keygen_established() 不依赖 manifest 键本身，故不被该攻击误导。
    _expected = {k: p for k, p in st._expected_baseline_items() if k.startswith("manifest:")}
    _manifest_baseline_expected = st._keygen_established()
    for _key, _mp in _expected.items():
        _name = _key[len("manifest:"):]
        _rec = data.get(_key)
        if _rec is None:
            if _manifest_baseline_expected:
                _drift.append(_key)   # N-2：基线键被删（删键逃逸）→ fail-closed（仅已 keygen 安装）
            continue
        # v2.27.3（R-5 收口）：清单基线签名验签接入硬闸计算层——与 verify_integrity（L1667-1675）
        # 同口径 fail-closed。此前本函数自比哈希、从不校验 _anchor_sig，攻击者凭 ledger 写权限
        # 直写（或经引擎 API 重记）基线哈希即穿透 apply/keygen/retrieve 入口硬闸。现签名失效
        # （False）或（非 legacy 容忍期）缺失签名（None）→ 计 drift。CHANGELOG.md 为非阻塞
        # （版本升级产物），保持非阻断、跳过签名阻断（与既有 drift 语义一致，不引入假阳性）。
        if _name != "CHANGELOG.md":
            _sig_ok = _verify_anchor_sig(_rec)
            if _sig_ok is False:
                _drift.append(_key)
                warn("[完整性-硬闸] manifest: 基线签名失效（{}）：疑似被篡改后伪造签名，已标 drift 拒绝。".format(_key))
                continue
            if _sig_ok is None and not Store._legacy_anchor_sig_allowed():
                _drift.append(_key)
                warn("[完整性-硬闸] manifest: 基线缺失 _anchor_sig（早于 v2.11 的 legacy 无签名基线）；"
                     "按 v2.11 截止期已 fail-closed，请运行 keygen/apply 重基线。".format(_key))
                continue
        _mtext = _mp.read_text(encoding="utf-8")
        _mcur = st._hash_text(_mtext)
        _ok, _ = st._script_hash_matches(_mcur, _rec.get("hash"), allow_legacy=_allow_legacy)
        if _name == "SKILL.md" and not _ok:
            # v2.27.4（R-8 收口）：@body 豁免须先验签（与 verify_integrity L1690 同口径 fail-closed）。
            # 旧实现仅判 _body_rec is not None 即豁免——攻击者凭 ledger 写权限伪造
            # manifest:SKILL.md@body 基线（无效/缺失 _anchor_sig）即可令「版本号变更豁免」失据，
            # 绕过正文篡改检出。现要求 _anchor_sig 有效（_verify_anchor_sig is True）才豁免；
            # 签名失效/缺失 → 不豁免，维持 _ok=False（倒逼重基线 / 检出篡改）。
            _body_rec = data.get("manifest:SKILL.md@body")
            if _body_rec is not None and _verify_anchor_sig(_body_rec) is True:
                _bok, _ = st._script_hash_matches(st._skill_body_hash(_mtext), _body_rec.get("hash"), allow_legacy=_allow_legacy)
                if _bok:
                    _ok = True
        if _name == "CHANGELOG.md":
            continue  # 非阻断（版本升级产物）
        if not _ok:
            _drift.append(_key)
    # v2.27.4（R-5b 收口·硬闸侧）：manifest:SKILL.md@body 派生键删除盲区闭合——与 verify_integrity（L1751）
    # 同口径。_expected 仅产出 manifest:<name> 不含 @body 子键，攻击者删 @body（保留 manifest:SKILL.md
    # 父键）即令「版本差异豁免」失据且不计入应有集。仅已 keygen 安装（_manifest_baseline_expected）计入 drift。
    if _manifest_baseline_expected and data.get("manifest:SKILL.md") is not None:
        if data.get("manifest:SKILL.md@body") is None:
            _drift.append("manifest:SKILL.md@body")
    # 保留原「基线在但文件缺失」检查（shipped 部署文件被删须检出；非 shipped 缺文件由 _expected 已排除）
    for _name in st.MANIFEST_NAMES:
        _key = "manifest:" + _name
        _mp = st.root / _name
        if (not _mp.exists()) and (data.get(_key) is not None):
            _drift.append(_key)
    # v2.8.9 ④：STRICT/外部锚下，若仍有 16-char 残余基线未迁移 → 强制迁移（拒绝 apply/retrieve/keygen 直至 record 升级为 128-bit）。
    # 使 __meta__.legacy_remaining 计数器具备真实强制力（Hermes N-2：此前仅写入、无读取，属过度声明）。
    _legacy_remaining = data.get("__meta__", {}).get("legacy_remaining", 0)
    if _legacy_remaining and _legacy_remaining > 0:
        _drift.append("__meta__:legacy-remaining:{}".format(_legacy_remaining))
    return (True, _drift)


# ---------------------------------------------------------------- v2.27.3（R-7 收口）：初始可信基线自举外部背书
def _bootstrap_external_attested(st):
    """v2.27.3（R-7 收口）：初始可信基线（keygen 建立的人类身份 + 全量代码/清单基线）建立前，若外部锚
    已构建为真实离线根（hsm / hsm+oob），须由其设备证明为当前人类身份（序列化公钥 + CONTRACT.md 钉固
    指纹）背书，否则 fail-closed 拒绝建立可信基线（杜绝「预篡改树 + 正常 keygen」自举为干净基线，
    与合法安装不可区分）。

    返回 (ok, reason)：
      - legacy（无外部锚）/ 默认 deny（无配置 → DenyTrustRoot("external-anchor-required")）/ corrupt /
        inside-writable-root / 纯 oob（每操作带外令牌，不依赖引导期设备证明）→ (True, None)，不误伤
        正常兼容流与默认部署（这些态由 check_pubkey_root 在验签时另行 fail-closed，引导期不阻断）。
      - hsm / hsm+oob 构建根 → 要求 attestation_ok(序列化公钥, CONTRACT.md 钉固指纹) 通过
        （离线根私钥签名的设备证明，Agent 无私钥无法自造）→ (True, None)；否则 (False,
        "bootstrap-external-anchor-<reason>")。

    设计要点（非破坏性）：本函数仅对「真实离线根已配置」态强制引导期背书；默认 deny / oob / legacy /
    corrupt 一律放行，确保未配置外部锚的常规安装（init/keygen）不受影响——与 v2.8.2 起的默认 deny 姿态
    一致（默认 deny 在 verify 验签时才 fail-closed，不阻断本地完整性基线建立）。

    诚实边界：① 仅 hsm/hsm+oob 提供「引导期设备证明」绑定（oob 为每操作令牌，无引导证明概念）；
    ② 残余「攻击者同时具代码写权限」仍须 TPM / 独立只读介质（out-of-scope，部署契约兜底），
    与 C-1 同源自举信任根口径一致。"""
    _ext = st.external_trust_root()
    # 仅当外部锚构建为 hsm / hsm+oob（真实离线根、可作引导期背书）时才强制；其余态一律放行。
    if _ext is None or not hasattr(_ext, "name") or _ext.name not in ("hsm", "hsm+oob"):
        return True, None
    _pub_serialized, _ = st.load_human_keys()
    if not isinstance(_pub_serialized, str) or not _pub_serialized:
        return False, "bootstrap-no-live-pubkey"
    _pinned = st.pinned_human_pubkey_fingerprint()
    _ok, _reason = _ext.attestation_ok(_pub_serialized, contract_fingerprint=_pinned)
    if not _ok:
        return False, "bootstrap-external-anchor-{}".format(_reason)
    return True, None


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
    # v2.27.14 C-02 收口（审计 v2.27.13 附录 C 复现）：正文转义 HTML 注释定界符，结构性消除
    # 「body 内嵌条目分隔符伪造 active 条目绕过 G1/G2 闸与双指标棘轮」注入类。转义后 body 内的
    # `<!--`/`-->` 不再匹配 ENTRY_RE，解析层不会凭空造出未经 verdict 的条目。
    _raw = (body or "")
    _n_esc = _raw.count("<!--") + _raw.count("-->")
    safe_body = _raw.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    # v2.27.15（N-16）：转义发生时不再静默——合法正文里的 HTML 注释会被改写为惰性文本，
    # 用户应被告知（行为不变：安全优先；可见性补齐）。
    if safe_body != _raw:
        try:
            # v2.27.15（Hermes 三审 L-N3i）：计数为实际受影响的定界符字节数，非整个 body 长度
            warn("[render_entry] 正文含条目定界符，已转义为惰性文本（安全优先，内容不会被解析为条目）："
                 "entry {} 的 {} 处定界符受影响".format(eid, _n_esc))
        except Exception:
            pass
    # v2.27.15（Hermes 三审 C-N3a 纵深加固）：src 头字段白名单校验。ENTRY_RE 的 src 捕获组
    # 本身限 [\w\-]+（实证：注入序列无法经解析层进入 src），但 render_entry 也被直接调用
    # （domains/init、未来调用方），此处对 src 做同一白名单——非法字符（含空格/换行/尖括号）
    # 一律丢弃 src 并告警（fail-safe：宁可少一个来源标注，不让头部携带任何可拼接定界符的字节）。
    if src and not re.fullmatch(r"[\w\-]+", str(src)):
        try:
            warn("[render_entry] src 字段含非法字符（白名单 [\\w\\-]+），已丢弃 src：entry {}"
                 .format(eid))
        except Exception:
            pass
        src = ""
    head = "<!-- entry:{} status:{} since:{}".format(eid, status, since)
    if src:
        head += " src:{}".format(src)
    head += " -->"
    return "{}\n{}\n<!-- /entry:{} -->".format(head, safe_body.strip(), eid)


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
    # 注（v2.27.3 R-7 收口边界）：init 建立的是「初步运营基线」（提案/账本/M1 策略/ratchet 等，不含人类身份），
    # 权威可信基线（人类身份 + 全量代码/清单）由 keygen 经 record_script_integrity 建立，R-7 的引导期
    # 外部背书强制点设在 _confirm_keygen（见 _bootstrap_external_attested）；init 此处不阻断，避免与
    # 正常兼容流冲突（init 时尚无人类公钥、无法绑定设备证明）。
    # v2.27.15（Hermes 三审 C-N3b 收口）：种子 id 实证落盘（仅首次写入，防注入后重跑 init 洗白）。
    if _write_seed_ids(st):
        created.append("meta/seed-ids.json")
    # v2.27.16（H-2 收口）：种子集纳入 D4 基线——删种子文件即被 verify 检出（fail-closed）。
    if (st.root / "meta" / "seed-ids.json").exists():
        st.record_integrity("meta:seed-ids.json")
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
    # v2.27.14 C-02 防御性拒绝（审计 v2.27.13 附录 C）：正文含条目定界符 `<!-- entry:` / `<!-- /entry:`
    # 即视为注入企图，直接拒绝；render_entry 另有转义兜底，此处为显式 fail-closed。
    if content and ("<!-- entry:" in content or "<!-- /entry:" in content):
        print("错误: " + add_fix("提案正文不得包含条目定界符 `<!-- entry:` / `<!-- /entry:`（C-02 注入防护）",
            "请改写正文，移除 HTML 注释形式的条目标记"), file=sys.stderr)
        return 2
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

    # 5b. 系统提示/工具策略默认人类确认（v2.27.13，生态外第三方审计 P1-1 收口：
    #     A1 自演化=持久化提示注入通道——Agent 自写自晋升的 A1 条目会经 retrieve --strict
    #     成为后续会话的行为约束。A1/A4 默认纳入人类闸；无人值守实验态须显式 opt-in 自担。）
    if p["artifact"] in ("A1", "A4") and os.environ.get("METACOG_UNATTENDED_ARTIFACTS") != "1":
        requires_human = True
        checks.append(("HUMAN", "A1/A4 默认人类确认", add_fix(
            "A1（系统提示）/A4（工具策略）改动会持久影响后续会话行为，默认需人类把关",
            "人类在 TTY 运行 `apply --id <提案>` 签绑定签名后落盘；"
            "无人值守实验须显式设 METACOG_UNATTENDED_ARTIFACTS=1（严格匹配）自担风险")))

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
    # v2.25.21（H-2 收口 m-4，Hermes 四轮 MEDIUM）：apply 主路径接 applies 域 D4 检查——
    # 此前全库仅 resolve_trial_start 一处调用 applies_integrity_ok，删链+逃生舱放行后
    # verdict 锚在篡改状态仍可继续记账。此处 fail-closed：applies.jsonl 与 D4 快照/链
    # 不符（含链被删）时拒绝 apply；链缺失可用 METACOG_ALLOW_LEGACY_NO_CHAIN=1 临时
    # 放行（legacy 兼容口径，与 verify 同一闸门语义），但建议尽快重基线。
    if not st.applies_integrity_ok():
        bad("[完整性-硬闸] applies.jsonl 与 D4 完整性快照/哈希链不符（疑似被直写篡改或链被删），拒绝 apply；"
            "请以 `verify` 核查，v2.5.8 老基线可设 METACOG_ALLOW_LEGACY_NO_CHAIN=1 临时放行并尽快重基线。")
        return 3
    # v2.26.0（方案B，H-2b 收口）：apply 入口接链首指纹钉固校验——删链+引擎 API 重建的链
    # 与 keygen 钉固值不符即拒（重建链首条目 hash 因时间戳不可复现）。
    if not st.chain_fingerprint_ok():
        bad("[完整性-硬闸] 链首指纹与 CONTRACT.md 钉固不符或链缺失（chain-identity-root），拒绝 apply；"
            "确认合法重装/重基线后重新 `confirm --keygen` 钉固，否则按篡改处置。")
        return 3
    items = [p for p in st.proposals() if p["status"] == "gated"]
    if args.id:
        items = [p for p in items if p["id"] == args.id]
    if not items:
        info("没有过闸待应用的提议（先跑 `gate`）。")
        return 0
    # v2.27.4（R-11 收口）：钉固信任根 + 脚本基线刷新须置于「no-op 判定之后」。
    # 旧实现置于 if not items: return 0 之前——「无待应用提议」的 apply 仍会落盘基线
    # （含 manifest:SKILL.md@body 派生子键），违背「拒绝/无操作态永不持久化」原则
    # （v2.27.2 N-1 收口的同源自指残留）。现仅当确有 gated 提议要应用时才刷新基线，
    # no-op apply 不再改写 integrity.json。
    # v2.27.2（N-1 收口）：钉固信任根须在「所有完整性硬闸通过之后、落盘之前」执行。
    # 原实现置于入口最前，被硬闸拒绝的 apply 仍会把（可能已被篡改的）human-guard.json
    # 公钥指纹钉固为信任根，洗白攻击面；现移至闸后（且 no-op 后），拒绝/无操作态永不触发钉固。
    st.ensure_pubkey_root_pinned()  # P0 前向兼容：现存合法安装补钉固信任根（闸后执行）
    st.record_script_integrity()  # v2.5.2（M-5）：受信锚落盘时刷新技能脚本基线
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
            _t0 = _episodes_len(st)  # v2.25.16：行数口径（不经 512KB 上限），与 _confirm_sign / record_apply 同值
            _sig_arg = getattr(args, "sig", None)
            if _sig_arg:
                ok_v, reason = st.verify_human_binding(p, _sig_arg, _t0)
                if ok_v:
                    # v2.25.17（C-1+C-2 收口）：消费唯一入口——锁内原子「D4 硬闸 → use-once 检查 →
                    # 消费标记落账 → 基线刷新」（v2.25.16 的裸检查被 Hermes 复验证实可删行绕过 + TOCTOU 双消费）
                    _ok_c, _reason_c = st.consume_human_sig_atomic(_sig_arg)
                    if not _ok_c:
                        human_blocked += 1
                        if _reason_c == "applies-integrity":
                            bad(add_fix("{}: 签名消费账本完整性校验失败（sig-claims D4 硬闸），拒绝消费人类签名".format(p["id"]),
                                        "sig-claims.jsonl / 其完整性基线（integrity.json）/ 完整性链"
                                        "（ledger/integrity-chain/chain.jsonl）之一疑似被改动"
                                        "（删行/清空/删基线/删链/伪造链条目等绕过 use-once 的行为均会命中此闸）；"
                                        "人工核查 ledger/ 后恢复；若为「基线已写、链未写」的崩溃中间态，"
                                        "可对齐补写缺失的链条目或恢复 chain.jsonl 备份后重试，勿直接重放签名"))
                        else:
                            bad(add_fix("{}: 该人类绑定签名已被消费过（use-once：同一签名只授权一次 apply）".format(p["id"]),
                                        "请人类重新 `confirm --sign --id {}` 生成新签名后再 apply".format(p["id"])))
                        continue
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
                                    "请重新在 TTY 运行 `apply --id {}` 交互式签绑定签名；"
                                    "若为 `confirm --sign` 预签名，签名后记账会使 t0 变化 → "
                                    "请重新 `confirm --sign --id {}` 后以新签名重试（v2.25.14）".format(p["id"], p["id"])))
                    elif reason == "pubkey-root-mismatch":
                        bad(add_fix("{}: 人类公钥信任根不匹配（pubkey-root-mismatch）：CONTRACT.md 钉固指纹与当前公钥不符，疑似公钥被替换".format(p["id"]),
                                    "检查 human-guard.json 与 CONTRACT.md 是否被篡改；"
                                    "确认无误后重新运行 `confirm --keygen` 钉固信任根"))
                    elif reason == "bad-pubkey":
                        bad(add_fix("{}: 人类公钥解析失败（bad-pubkey）：human-guard.json 中公钥损坏/被篡改".format(p["id"]),
                                    "检查 human-guard.json 是否被篡改；确认无误后重新运行 `confirm --keygen` 重建密钥"))
                    else:
                        warn("{} 需人类确认（D1：无有效人类绑定签名视为未确认，退出码 2）；"
                             "请人类在 TTY 运行 `apply --id {}` 交互式输入口令签绑定签名；"
                             "或重新 `confirm --sign --id {}` 预签名后经 --sig 传入（v2.25.14；"
                             "签名后至 apply 前不得再记账，否则 t0 变化验签失败）".format(p["id"], p["id"], p["id"]))
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
                                "请人类亲自打开终端执行 `apply --id {0}`；agent 不得代替人类运行 apply 签名。"
                                "无人值守/自动化场景（v2.25.14）：人类在有终端的机器上运行 "
                                "`confirm --sign --id {0}` 预生成绑定签名，再以 `apply --id {0} --sig <签名>` 应用"
                                "（签名后至 apply 前不得再记账，否则 t0 变化需重签）".format(p["id"])))
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
        p["trial_from_index"] = _episodes_len(st)  # v2.25.16：与验签处同口径（行数，不经 512KB 上限）
        # W1（M-7 闭环）：受信任锚内嵌人类**绑定**签名（覆盖 id+chash+trial_from_index），关闭 7.1 直写伪造锚
        _chash = proposal_content_hash(p)  # H-1（v2.5.8）：所有锚均内嵌 content_hash 绑定提案内容（含非 requires_human），关闭盲信 t0
        # v2.27.16（H-3 收口）：正文哈希锚——与 render_entry 同口径（转义 + strip）哈希，
        # 供条目级审计比对「正文是否与 apply 一致」（封堵只保留 id、篡改正文不留痕的绕过）。
        _body_hash = st._hash_text(((p.get("content") or "")
                                   .replace("<!--", "&lt;!--").replace("-->", "--&gt;").strip()))
        st.record_apply(p["id"], p["trial_from_index"], p["artifact"], p["entry_id"], _human_sig, _chash, _body_hash)
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
    # v2.8.5 M-2'（对称 M-4）：resign 重签受信锚落盘前，先核验技能脚本完整性；
    # 与 cmd_apply 同条件/同硬闸（外部锚激活或 METACOG_TRUST_ROOT_STRICT=1 时强制），漂移则拒绝。
    _r_enforced, _r_drift = _script_integrity_drift_if_enforced(st)
    if _r_drift:
        bad("[完整性-硬闸] 以下技能脚本哈希与基线不一致，拒绝 resign（须基于未篡改代码）：{}；"
            "请以 `verify` 核查并 `rollback` 还原，或人工确认后重基线。".format(", ".join(_r_drift)))
        return 3
    # v2.27.2（N-1 收口）：钉固信任根须在脚本硬闸通过之后执行（与 cmd_apply 同口径）。
    st.ensure_pubkey_root_pinned()  # P0 前向兼容：现存合法安装补钉固信任根（闸后执行）
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
    # v2.27.14 H-06 收口（审计 v2.27.13）：resign 须与 apply 同构——在落盘前于文件锁临界区内原子消费
    # 该一次性人类签名，消除「同一签名被 resign 反复重锚」的重放。
    _ok_c, _reason_c = st.consume_human_sig_atomic(sig)
    if not _ok_c:
        bad(add_fix("resign: 人类绑定签名消费失败（{}），拒绝重签".format(_reason_c),
                    "该签名可能已被使用；若为首次 resign 却报消费失败，请核查 sig-claims.jsonl 完整性"))
        return 2
    # v2.27.16（H-3 收口）：resign 与 apply 同构落 body_hash 锚（同口径，正文哈希一致）。
    _body_hash = st._hash_text(((p.get("content") or "")
                               .replace("<!--", "&lt;!--").replace("-->", "--&gt;").strip()))
    st.record_apply(p["id"], t0, old.get("artifact"), old.get("entry_id"), sig, chash, _body_hash)
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
            # v2.27.13 P0-1（生态外第三方审计收口）：verdict 改写制品后必须同步刷新 D4 快照，
            # 否则正常 PROMOTE 后 verify/retrieve 立即误报「被直写篡改」（apply 路径本有此调用）。
            st.record_integrity(p["artifact"])
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
            # v2.27.13 P0-1：REVERT 回滚同样改写制品，同步刷新 D4 快照（与 PROMOTE/apply 对齐）。
            st.record_integrity(p["artifact"])
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
    # v2.27.32（R-1 双密钥根信任 · §10 #4）→ v2.27.33（DSH §2.4 收口）：读通道纳入
    # 根信任闸门的**全状态覆盖**。原实现只在「钉固在 + RK_pub 在」时校验密封——
    # 层缺失（AK 公钥/attestation 被删）时规则照吐。现改为：enforce mode ≠ off 即走
    # _attest_verify_core 全量核验，任何非 ok 状态（含 missing/root_pin_missing/
    # root_pub_missing/ledger_drift/...）均拒绝吐出生效规则（C-1：别把坏规则卖给下一会话）。
    if _attest_enforce_mode(st) != "off":
        _vst, _vdet = _attest_verify_core(st)
        if _vst != "ok":
            bad("[根信任-硬闸] 根信任/attestation 核验未通过（status={}），信任根无法确认，"
                "拒绝吐出生效规则（C-1：别把坏规则卖给下一会话）。"
                "请以 `anchor-attest-verify` 核查，并经持离线私钥一方修复重签。".format(_vst))
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

def _write_seed_ids(st: Store, force=False) -> bool:
    """v2.27.15（Hermes 三审 C-N3b 收口）：把 init/init-domain 当时的全部条目 id 实证落盘
    meta/seed-ids.json（**仅首次写入**，不覆盖——防止「注入后重跑 init 刷新种子集」洗白）。
    供 _audit_entries_scan 用精确种子集替代宽泛的 R-\\d{3}/S-\\d{3} 通配（该通配存在
    「R-777 形态注入 id 被当作种子放行」的假阴性）。返回是否新建/重写了文件。

    v2.27.16（H-2 收口）：新增 force 开关与「制品已存在则禁止重采」守卫——
      · 文件已存在且 force=False → 不触碰（返回 False），避免静默重采；
      · 文件缺失但制品已存在（疑似删种子后重跑 init）→ 默认拒绝重采（防注入条目被纳入种子集洗白），
        仅当 force=True（init-domain 可信覆盖后 / 显式 --reseed）才重采；
      · 文件缺失且制品尚不存在（全新实例）→ 采集并落盘；
      · 写入失败 → warn（令调用方感知）并返回 False，不静默吞。"""
    p = st.root / "meta" / "seed-ids.json"
    _artifacts_present = any(st.artifact_path(c).exists() for c in ARTIFACTS)
    if p.exists():
        if not force:
            return False
        # force=True：覆盖现有种子（仅 init-domain 可信覆盖后 / 显式 --reseed 使用）
    elif _artifacts_present and not force:
        warn("[H-2] meta/seed-ids.json 缺失但制品已存在：疑似删种子后重跑 init 洗白，"
             "拒绝重采（防注入条目被纳入种子集）。如确需重建种子，请用 init-domain 的可信覆盖后重采，"
             "或人工核验制品无注入后重建实例。")
        return False
    ids = {}
    for code in ARTIFACTS:
        path = st.artifact_path(code)
        if not path.exists():
            continue
        try:
            ids[code] = sorted({e.get("id", "") for e in parse_entries(read_text(path)) if e.get("id")})
        except Exception:
            ids[code] = []
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        write_json(p, {"_comment": "init/init-domain 时的种子条目 id（实证集，仅首次写入不覆盖）。"
                                   "N-11 条目扫描以本文件为精确种子白名单。", "seeds": ids})
        return True
    except Exception as e:
        warn("[H-2] meta/seed-ids.json 写入失败（{}）：种子基线不可用，条目审计将回落通配模式，"
             "请人工核验实例完整性。".format(e))
        return False


def _audit_entries_scan(st: Store):
    """v2.27.15（N-11 收口）：升级迁移的条目级审计扫描（verify 默认开启，--no-audit-entries 跳过）。

    背景：cmd_apply 先写制品后记基线，故 2.27.13（可注入时代）写下的被污染内容与 D4 基线
    **一致**——verify 说"干净"，伪造 active 条目继续被 retrieve 服务。本扫描按条目粒度找
    「无法由 propose→apply 产生」的条目：
      ① 同一制品内重复条目 id；
      ② active/非active 条目 id 不在 applies.jsonl 且不属于 init 种子集；
      ③ v2.27.16（H-3）：条目 id 命中 applies 但**正文哈希**与 apply 时不符（只保留 id、篡改正文不留痕）；
      ④ v2.27.16（M-1）：applies.jsonl 文件级 D4 基线/锚签名/链 被篡改（伪造 apply 记录）；
      ⑤ v2.27.16（M-2）：meta/seed-ids.json 结构被篡改（回落通配模式，fail-closed）；
      ⑥ v2.27.16（H-2）：meta/seed-ids.json 基线存在但文件缺失（删种子洗白，fail-closed）。
    种子集判定（Hermes 三审 C-N3b 收口）：优先读 meta/seed-ids.json（实证精确集）；
    2.27.15 之前的旧实例无该文件时回落通配模式（A1-000/T-000/M-000/R-\\d{3}/S-\\d{3}）
    并提示重建或跑迁移以获得精确扫描。
    返回 (notes, warns)——notes 为信息级提示，warns 为 fail-closed 告警（verify 据此 rc=1）。"""
    applied_ids = set()
    applies_body = {}  # entry_id -> body_hash（H-3 正文锚比对）
    for rec in read_jsonl(st.applies):
        if isinstance(rec, dict):
            for k in ("entry_id", "id"):
                if rec.get(k):
                    applied_ids.add(str(rec[k]))
            _eid = str(rec.get("entry_id") or rec.get("id") or "")
            _bh = rec.get("body_hash")
            if _eid and isinstance(_bh, str):
                applies_body[_eid] = _bh
    seed_file = st.root / "meta" / "seed-ids.json"
    fallback_re = re.compile(r"^(A1-000|T-000|M-000|R-\d{3}|S-\d{3})$")
    notes = []
    warns = []
    # M-1：applies.jsonl 文件级完整性（D4 基线哈希 + _anchor_sig + 链 latest 语义）复核——防直写篡改
    # applies 伪造锚。注：applies 行本身不携带逐行 _anchor_sig（仅 integrity.json 基线条目有），故复核
    # 文件级基线，与 verify_integrity 对 APPLIES_INTEGRITY_KEY 的校验同源、互补（条目扫描内联，防遗漏）。
    # v2.27.16 实测更正：**不用 applies_integrity_ok()**——其内部 _integrity_chain_ok 要求「链尾条须
    # 覆盖 applies」，任何其他域在 apply 之后合法重基线（如 GUARD/keygen）都会令链尾移走而误报 False
    # （v2110/v22713 套件回归暴露）。此处改用与 verify 主路径同语义的三步判定。
    _m1_rec = read_json(st.integrity, {}).get(Store.APPLIES_INTEGRITY_KEY)
    if _m1_rec is not None:
        if not st.applies.exists():
            warns.append("[M-1] applies.jsonl 基线存在但文件缺失：受信任锚账本被删——请人工核验。")
        else:
            _m1_cur = st._hash_text(st.applies.read_text(encoding="utf-8"))
            if not st._hash_matches(_m1_rec.get("hash"), _m1_cur, allow_legacy=Store._legacy_hash_allowed()):
                warns.append("[M-1] applies.jsonl 与 D4 基线哈希不符：受信任锚可能被直写篡改（伪造 apply 记录），"
                             "疑似绕过——请人工核验。")
            else:
                _m1_sig = _verify_anchor_sig(_m1_rec)
                if _m1_sig is False or (_m1_sig is None and not Store._legacy_anchor_sig_allowed()):
                    warns.append("[M-1] applies.jsonl 基线锚签名无效/缺失（非 legacy 窗口）：疑似伪造基线"
                                 "（伪造 apply 记录）——请人工核验。")
                elif not st._chain_ok_for_verify(Store.APPLIES_INTEGRITY_KEY, _m1_cur):
                    warns.append("[M-1] applies.jsonl D4 链校验失败（链缺失/不连续/最近条目不符）："
                                 "疑似删链洗白——请人工核验。")
    # 种子集：优先读 meta/seed-ids.json（实证精确集）；异常/缺失按 legacy 回落。
    exact_seeds = None
    _baseline_has_seed = "meta:seed-ids.json" in read_json(st.integrity, {})
    _has_applies = bool(applied_ids)
    if seed_file.exists():
        try:
            _d = json.loads(seed_file.read_text(encoding="utf-8"))
            # M-2：结构校验——非 dict / 缺 seeds / seeds 非 dict → 视为被篡改，fail-closed（不静默回落通配）。
            if not isinstance(_d, dict) or "seeds" not in _d or not isinstance(_d.get("seeds"), dict):
                raise ValueError("结构非法（非预期 schema）")
            exact_seeds = {str(x) for lst in (_d.get("seeds") or {}).values() for x in (lst or [])}
        except Exception as e:
            # M-2：种子集不可信 → 回落通配并 fail-closed（warn 入 warns，verify rc=1）。
            warns.append("[M-2] meta/seed-ids.json 结构校验失败（{}）：种子集不可信，条目审计回落通配模式并 fail-closed，"
                         "疑似篡改——请人工核验。".format(e))
            exact_seeds = None
    else:
        # H-2：种子缺失。仅当本实例基线期望种子（2.27.16+，含 meta:seed-ids.json 基线键）才 fail-closed；
        # 旧实例（无基线键）仅信息提示，不误伤。
        if _has_applies and _baseline_has_seed:
            warns.append("[H-2] meta/seed-ids.json 基线存在但文件缺失：种子被删，条目审计回落通配模式且 fail-closed，"
                         "疑似删种子洗白——请人工核验。")
        elif _has_applies and not _baseline_has_seed:
            notes.append("[H-2-scan-info] meta/seed-ids.json 缺失（旧实例未建基线）：种子判定回落通配模式，"
                         "R-NNN/S-NNN 形态 id 精确性受限；建议重建实例或人工迁移以启用精确种子集。")
        else:
            notes.append("[scan-info] 无 meta/seed-ids.json（全新实例）：种子判定回落通配模式，"
                         "R-NNN/S-NNN 形态 id 的精确性受限；建议 `init`/`init-domain` 重建或人工迁移以启用精确种子集。")
    for code in ARTIFACTS:
        path = st.artifact_path(code)
        if not path.exists():
            continue
        try:
            text = read_text(path)
        except Exception:
            continue
        entries = parse_entries(text)
        seen = {}
        for e in entries:
            eid = e.get("id", "")
            _body = (e.get("body") or "").strip()
            _cur_body_hash = st._hash_text(_body) if _body else ""
            seen.setdefault(eid, 0)
            seen[eid] += 1
            # H-3：正文替换检测——id 命中 applies 但正文哈希不符 → 疑似只保留 id、篡改正文不留痕。
            # 覆盖 active 与 非active（攻击者可用 trial/revoked 状态规避原 active-only 检查）。
            if eid in applies_body and _cur_body_hash and applies_body[eid] != _cur_body_hash:
                warns.append("{}: 条目 {} 正文与 apply 记录不符（H-3 正文替换，疑似只保留 id 篡改正文不留痕）——请人工核验".format(code, eid))
                continue
            if e.get("status") != "active":
                # v2.27.16（H-3 收口）：非 active 伪造也须判定（原静默 skip 给攻击者留了「用 trial 状态绕过」的面）。
                # 正常 trial/revoked 条目均在 applies 中（apply 写入），会经下方 applied_ids/seed 放行；
                # 不在 applies 且非种子的非 active 条目 = 可疑伪造/注入残留。
                if eid in applied_ids:
                    continue
                if exact_seeds is not None:
                    if eid in exact_seeds:
                        continue
                elif fallback_re.match(eid or ""):
                    continue
                warns.append("{}: 非 active 条目 {} 不在 applies.jsonl 且非 init 种子（疑似伪造/注入残留）——请人工核验".format(code, eid))
                continue
            if eid in applied_ids:
                continue
            if exact_seeds is not None:
                if eid in exact_seeds:
                    continue
            elif fallback_re.match(eid or ""):
                continue
            warns.append("{}: active 条目 {} 不在 applies.jsonl 且非 init 种子"
                         "（疑似 2.27.13 时代注入残留或直写伪造，请人工核验）".format(code, eid))
        for eid, n in seen.items():
            if n > 1:
                warns.append("{}: 条目 id {} 出现 {} 次（重复 id，疑似拼接/注入残留）".format(code, eid, n))
    return notes, warns


def cmd_verify(st: Store, args):
    """D4：系统级完整性校验——比对各制品当前内容哈希与 ledger 快照（apply 写入的真值）。

    直写 .metacog/artifacts/*.md 绕过三闸，本命令能检出这种偏离（PoC 报告 D4）。
    v2.5.2：verify 保持只读，不再自动钉固信任根（钉固由 keygen / apply 负责）。"""
    rows = st.verify_integrity()
    info("=== 完整性校验（D4 · 堵直写绕过） ===")
    # v2.27.16（H-1 收口）：原 `if not rows: return 0` 在 integrity.json 被删除时令 verify 恒绿——
    # 直写篡改唯一可见信号被静默关闭（删基线即「关检测」）。现区分：
    #  · applies 非空 + integrity 缺失 → 疑似删基线静默关检测 → fail-closed（rc=1）；
    #  · 全新实例（applies 空且 integrity 缺失/空）→ 明示「完整性未建立」，不误判绿；
    #  · 两类都不早退——继续下方条目级审计（空快照也须扫，防注入残留）。
    if not rows:
        _applies_recs = read_jsonl(st.applies)
        _has_applies = bool(_applies_recs)
        if _has_applies and not st.integrity.exists():
            bad("完整性基线 integrity.json 缺失，但 applies.jsonl 已有 {} 条 apply 记录："
                "疑似删基线以静默关闭直写检测（H-1 收口，fail-closed）。".format(len(_applies_recs)))
            return 1
        info("  无完整性快照（尚未 apply 过任何制品或基线为空）。先 `init` + `apply` 建立基线快照。")
        info("  [注意] 本实例完整性基线尚未建立（integrity.json 缺失/空），D4 直写检测暂不生效；"
             "请尽快 `apply` 建立基线后再 verify。")
        # 不提前 return——继续下方条目级审计（空快照也须扫，防注入残留）。
    dirty = 0
    for artifact, ok_flag, stored, current in rows:
        if ok_flag:
            ok("{} 一致（hash={}）".format(artifact, current))
        else:
            dirty += 1
            if stored is None and current is None:
                bad("{} 基线记录缺失（keygen 后该基线应存在却被删除，R-1/R-2 删键逃逸收口）。".format(artifact))
            else:
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
            # v2.25.20（H-2 收口）：guard 域链校验——删链洗白不再静默通过
            elif not st._chain_ok_for_verify(Store.GUARD_INTEGRITY_KEY, gcur):
                dirty += 1
                bad("{} D4 链校验失败：链缺失/不连续/最近条目与当前不符——疑似删链洗白。".format(Store.GUARD_INTEGRITY_KEY))
    # v2.26.0（方案B，H-2b 收口；v2.26.1 修接线 H-2b'；v2.27.0 R-3 全域清扫：钉固公钥漂移检查
    # 从「链指纹失败」嵌套块移出、无条件执行——与 H-2b' 同构的接线缺陷，条件成立时检测失效）
    # 链首指纹钉固校验**无条件执行**（不依赖 guard 基线存在）——删链+引擎 API 重建的
    # 链首 hash 与 keygen 钉固值不符（重建链时间戳等字段不可复现），fail-closed 检出。
    if not st.chain_fingerprint_ok():
        dirty += 1
        bad("链首指纹与 CONTRACT.md 钉固不符或链缺失（chain-identity-root）：疑似删链重建/重基线未重新钉固。")
    # v2.27.1（N-3 收口，Hermes 七轮实测）：钉固公钥漂移检查**三分支显式判定**。
    # v2.27.0 原写法为 `if pinned:` 整体短路——删 CONTRACT.md 的 human_pubkey_fingerprint 值行
    # （pinned=None）即令整段漂移检查不可达，七轮实测 verify rc=0（N-3，P2）。
    # 现改为：
    # ① pinned 有值 → 与 live 公钥指纹比对（live 缺 / 不符均 fail-closed 报告）；
    # ② pinned 为 None 但**钉固痕迹存在**（CONTRACT.md 仍含 human-identity-root 节标题，
    #    而 human_pubkey_fingerprint 键行已不在）→ 钉固值行被删 → fail-closed 报告；
    # ③ pinned 为 None 且无痕迹（init 未 keygen 的占位符态 / 从未钉固）→ 放行（不误伤正常流）。
    pinned = st.pinned_human_pubkey_fingerprint()
    live = st.human_pubkey_fingerprint()
    if pinned:
        if live is None:
            dirty += 1
            bad("{} 缺失公钥，但 CONTRACT.md 已钉固信任根（{}）。".format(Store.GUARD_INTEGRITY_KEY, pinned))
        elif live != pinned:
            dirty += 1
            bad("人类公钥信任根指纹漂移：当前 {} 与 CONTRACT.md 钉固 {} 不符（疑似公钥被替换）。".format(live, pinned))
    else:
        _cpath = st.root / "CONTRACT.md"
        _ctxt = _cpath.read_text(encoding="utf-8") if _cpath.exists() else ""
        _pin_line_exists = any(("human_pubkey_fingerprint" in ln) and (":" in ln)
                               for ln in _ctxt.splitlines())
        if ("human-identity-root" in _ctxt) and (not _pin_line_exists):
            dirty += 1
            bad("CONTRACT.md 缺 human_pubkey_fingerprint 钉固值行，但 human-identity-root 钉固节仍在："
                "钉固值疑似被删（N-3——删行逃逸收口，fail-closed）。")
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
    # v2.27.15（N-11 收口，Hermes 三审 C-N3e 收口）：条目级扫描**默认开启**——
    # 迁移防线不能 opt-in（owner/Agent 都可能忘记加参数，注入条目在日常 verify 里静默通过）。
    # `--no-audit-entries` 显式跳过（跳过时 warn 留痕）。发现可疑条目即 fail（rc=1）。
    if not getattr(args, "no_audit_entries", False):
        _notes, _ew = _audit_entries_scan(st)
        for _n in _notes:
            info(_n)
        if _ew:
            for _w in _ew:
                bad("[条目审计] " + _w)
            bad("条目级审计发现 {} 处可疑条目（N-11 迁移扫描）：请人工核验上述条目，"
                "确认为注入残留时用 `propose --op replace` 修复或重建实例；"
                "确属误报可用 `verify --no-audit-entries` 临时跳过（留痕）。".format(len(_ew)))
            return 1
        ok("条目级审计（N-11 迁移扫描）：无可疑条目。")
    else:
        # v2.27.16（L-4 协同）：跳过提示走 stderr（不污染 stdout 自报解析，运行器据此判 no-self-report）
        print("[verify] 已按 --no-audit-entries 跳过条目级审计（N-11）——本输出不含条目级注入检查。",
              file=sys.stderr)
    info("全部制品与 ledger 快照一致（无直写篡改）。")
    return 0


def _reactivate_block(block, expected_id=None):
    """把条目块的状态字段强制还原为 active（用于回滚）。

    v2.27.15（N-10 收口）：还原状态后经 render_entry **重新渲染**——历史快照（2.27.13 可注入
    时代写入的 rollback.jsonl 产物）或被污染的 git 提交中内嵌的伪造条目定界符，复活时被转义为
    惰性文本，不再原样拼回制品成为可解析的 status:active 注入条目。对干净快照（render_entry
    时代的块）这是恒等往返，字节不变。
    v2.27.16（M-3 收口）：新增 `expected_id` 约束 + 前缀残余告警——
    ① 若 `expected_id` 给定且解析出的条目 id 与之不符 → 抛 ValueError（拒绝复活非目标条目，
       防止回滚「安装」任意伪造成员后重基线洗白）；② 目标条目之前的前缀残余（如伪造条目尾巴）
       原被静默丢弃，现一并告警（fail-safe：回滚只复活目标条目本身）。"""
    blk = re.sub(r"status:(trial|revoked)", "status:active", block)
    m = ENTRY_RE.search(blk)
    if not m:
        return blk
    _found_id = m.group("id")
    if expected_id is not None and _found_id != expected_id:
        raise ValueError(
            "rollback 复活块条目 id={} 与期望 expected_id={} 不符（M-3 收口：拒绝复活非目标条目"
            "——防止回滚安装任意伪造成员后重基线洗白）".format(_found_id, expected_id))
    _prefix = blk[:m.start()].strip()
    if _prefix:
        warn("[rollback] 快照块在目标条目之前含残余内容（{} 字节），已丢弃不复活"
             "（M-3 收口：前缀残余如伪造条目尾巴须告警而非静默）".format(len(_prefix)))
    _suffix = blk[m.end():].strip()
    if _suffix:
        warn("[rollback] 快照块含目标条目之外的残余内容（{} 字节），已丢弃不复活"
             "（N-10 收口：历史快照可能携带注入片段，只复活目标条目）".format(len(_suffix)))
    return render_entry(_found_id, "active", m.group("since"), m.group("src"), m.group("body"))


class LedgerAnchorDefaultError(RuntimeError):
    """v2.27.17（C-01 收口）：账本签名锚密钥未配置/不合规时拒绝启动（fail-closed）。

    源码内嵌默认对称锚已删除（第三轮审计建议 #11："宁可装不上，不可自签"）——该默认锚随代码分发，
    任何可读代码者均可提取并伪造签名（C-01 的核心）。原兜底 METACOG_TRUST_ROOT_ALLOW_DEFAULT
    同步废除（允许默认锚 = 允许自签）。唯一合法来源：环境变量 METACOG_TRUST_ROOT_ANCHOR_KEY
    （base64 编码的 ≥32 字节专属随机密钥，M-01 校验）。诚实边界：env 对进程自身可读，属部署契约
    兜底范畴（结构性根除须非对称化/硬件 TPM，独立专项）。"""


# v2.10.0（MED#1）：基线签名与审计链 HMAC 使用**不同派生标签**，消除单钥双用（Hermes r7 中 H-D）。
_LEDGER_SIG_LABEL = b"metacog-ledger-sig-v210"
_AUDIT_HMAC_LABEL = b"metacog-ledger-audit-v290"  # 审计链历史标签（存量审计链不可重签，须向后兼容）
# v2.9.0 基线签名曾复用审计链标签（单钥双用）；v2.10.0 起基线改用 _LEDGER_SIG_LABEL，
# 存量 v2.9.0 基线签名（旧标签）不再视为可信，仅作 legacy 容忍（见 _verify_anchor_sig）。
_LEDGER_SIG_LABEL_LEGACY = _AUDIT_HMAC_LABEL


def _resolve_anchor_key():
    """v2.27.17（C-01 收口 + M-01）：返回账本签名锚密钥——**仅**来自部署专属环境变量。

    源码内嵌默认锚已删除；trust_root.get_anchor_key() 返回 None（env 未配置）→ 抛
    LedgerAnchorDefaultError（fail-closed 拒绝启动）；env 非法 base64 / <32 字节 → 由
    get_anchor_key 抛 ValueError（M-01 fail-closed，不回落）。"""
    if trust_root is None:
        raise LedgerAnchorDefaultError(
            "trust_root 模块缺失，且源码内嵌默认锚已删除（C-01 收口）：无法解析账本签名锚密钥。\n"
            "请恢复 trust_root.py 或设置环境变量 METACOG_TRUST_ROOT_ANCHOR_KEY 为专属随机密钥。")
    _anchor = trust_root.get_anchor_key()
    if _anchor is None:
        raise LedgerAnchorDefaultError(
            "账本签名锚密钥未配置（C-01 收口：源码内嵌默认锚已删除——「宁可装不上，不可自签」；"
            "原兜底 METACOG_TRUST_ROOT_ALLOW_DEFAULT 已废除）。\n"
            "请设置环境变量 METACOG_TRUST_ROOT_ANCHOR_KEY 为 base64 编码的 ≥32 字节专属随机密钥，"
            "例：python -c \"import os,base64;print(base64.b64encode(os.urandom(48)).decode())\"。\n"
            "既有实例以旧默认锚签署的基线须在配置专属锚后重新 init/keygen 建立基线。")
    return _anchor


def _ledger_sig_key():
    """v2.10.0（MED#1）：完整性基线签名专用派生密钥（与审计链 HMAC 密钥分离，消除单钥双用）。"""
    return hmac.new(_resolve_anchor_key(), _LEDGER_SIG_LABEL, hashlib.sha256).digest()


def _audit_hmac_key(st):
    """v2.10.0（MED#1）：审计链 HMAC 专用派生密钥（标签 _AUDIT_HMAC_LABEL 与基线签名分离）；
    保留历史标签以兼容存量审计链（rollback-audit / migration-audit 不可重签）。
    密钥由部署专属锚派生（v2.27.17 C-01 收口：源码内嵌默认锚已删除，唯一来源 env 专属密钥，非可写 ledger），
    攻击者凭 ledger 写权限无法获得。锚未配置 → _resolve_anchor_key 抛错（fail-closed）。"""
    return hmac.new(_resolve_anchor_key(), _AUDIT_HMAC_LABEL, hashlib.sha256).digest()


# v2.26.0（H-2a/H-2b 收口方案A，Hermes 四轮建议）：D4 链条目 HMAC——第三个独立派生标签，
# 与基线签名（_LEDGER_SIG_LABEL）/审计链（_AUDIT_HMAC_LABEL）分离，消除单钥双用。
_CHAIN_HMAC_LABEL = b"metacog-chain-entry-hmac-v2260"


def _chain_entry_hmac_key():
    """v2.26.0（方案A）：D4 链条目 HMAC 专用派生密钥。
    密钥由代码内嵌锚派生（密钥位于代码/专属 env，非可写 ledger）——与 script: 域 _anchor_sig
    同强度：防御纵深（闭「不经引擎 API 手写/直写链条目」的伪造路径，H-2a 手写变体），
    对持源码读权者可重算（诚实边界与 _anchor_sig 一致，见 SKILL.md「诚实天花板」）。"""
    return hmac.new(_ledger_sig_key(), _CHAIN_HMAC_LABEL, hashlib.sha256).digest()


def _chain_entry_hmac(payload: dict) -> str:
    """v2.26.0（方案A）：对链条目规范化载荷（排序键 + 紧凑分隔符，调用方须排除 mac 自身）计算 HMAC。"""
    _canon = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hmac.new(_chain_entry_hmac_key(), _canon.encode("utf-8"), hashlib.sha256).hexdigest()


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
    try:
        new_block = _reactivate_block(rec["prev_text"], expected_id=rec["entry_id"])
    except ValueError as _ve:
        bad(add_fix("rollback 拒绝：{}".format(_ve),
                    "回滚快照块条目与待回滚条目不符，疑似快照被污染；请人工核验 rollback-audit.jsonl 后再试"))
        return 1
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
        # v2.26.0（方案B）：人类 TTY 在场，顺带钉固 D4 链首指纹（H-2b 删链重建检出）。
        # 须在 record_script_integrity 之前（本方法会改 CONTRACT.md，manifest 基线须随后刷新）。
        st.write_chain_fingerprint()
        st.record_guard_integrity()
        # v2.27.3（R-7 收口）：受保护模式（外部锚 hsm/hsm+oob 已配置）下，建立可信基线（人类身份 + 全量
        # 代码/清单基线）前须由离线根设备证明为人类身份背书，否则 fail-closed 拒绝（杜绝预篡改树自举为
        # 干净基线）。legacy / 纯 oob → 不误伤（oob 为每操作带外令牌，不依赖引导期设备证明）。
        _b_ok, _b_reason = _bootstrap_external_attested(st)
        if not _b_ok:
            bad("[完整性-自举] 受保护模式外部锚设备证明未通过（{}），拒绝建立可信基线；"
                "请先由人类离线根私钥对当前人类公钥签写设备证明文件（committed_pubkey=当前公钥、"
                "contract_fingerprint=CONTRACT.md 钉固指纹）后重试 `confirm --keygen`。".format(_b_reason))
            return 3
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
            # v2.27.17（C-01 收口）：源码默认锚已删除、ALLOW_DEFAULT 废除——启用外部锚须已配置
            # 专属 env 锚密钥（get_anchor_key() 非 None；非法/过短由 M-01 校验抛 ValueError）。
            try:
                _anchor_cfg_ok = trust_root.get_anchor_key() is not None
            except ValueError as _vk:
                bad(add_fix("启用外部锚被拒：{}".format(_vk),
                            "设置环境变量 METACOG_TRUST_ROOT_ANCHOR_KEY 为 base64 编码的"
                            " ≥32 字节专属随机密钥"))
                return 2
            if not _anchor_cfg_ok:
                bad(add_fix("启用外部锚被拒：锚密钥未配置（C-01 收口：源码内嵌默认锚已删除，"
                            "「宁可装不上，不可自签」）",
                            "设置环境变量 METACOG_TRUST_ROOT_ANCHOR_KEY 为 base64 编码的"
                            " ≥32 字节专属随机密钥"))
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


def _confirm_sign(st: Store, args) -> int:
    """W1（v2.25.14）：人类 TTY 预生成绑定签名，供无人值守/无 TTY 场景 `apply --sig` 消费。

    安全语义与 apply 时当场签名**一致**：签名覆盖 (提案 id + 内容哈希 + trial_from_index=t0)，
    Agent 进程不持有私钥明文（口令须由人类在 TTY 交互提供），故无法自签，也无法把签名挪用于
    其他提案 / 篡改后的内容 / t0 变化之后。签名后至 apply 前不得再记账（episode）——
    否则 t0 变化 → apply 验签失败（fail-closed），需重新 `confirm --sign`。
    本命令不新增绕过**密码学验证**的路径；但引入两项非密码学新面并已在工具侧约束（v2.25.16）：
    ① 签名文件磁盘窗口期——泄露面警告 + use-once enforce（同一签名仅消费一次）+ 用后可删指引；
    ② --out 写入面——已存在须 --force、写失败 rc=2。"""
    pid = getattr(args, "id", None)
    if not pid:
        bad(add_fix("confirm --sign 需 --id 指定要预签名的过闸提案",
                    "先 `gate` 查看待应用提案 id，再 `confirm --sign --id <提案id>`"))
        return 2
    p = st.find_proposal(pid)
    if not p or p.get("status") != "gated":
        _gated = [q.get("id", "?") for q in st.proposals() if q.get("status") == "gated"]
        bad(add_fix("提案 {} 不存在或未过闸（status={}）".format(pid, (p or {}).get("status")),
                    "当前过闸待应用提案：{}；若无，先 propose/gate 让提案过闸".format("、".join(_gated) or "（无）")))
        return 2
    # 知情同意（v2.25.15 收口 + v2.25.16 P2 收口）：签名绑定的是提案**全文**（chash 对 canonical 提案全文
    # SHA-256），人类必须看到全文再签——只显示截断预览会让「前 160 字良性 + 尾部恶意」的提案获得知情
    # 同意外观（v2.25.14 自审 Confirmed 缺口）。v2.25.16 起：全文打印**不再 strip**（显示与签名对象同一原文，
    # chash 口径统一），ANSI 转义与零宽/BOM 等不可见字符以可见标记替代（防终端渲染与签名对象不一致）。
    _content = p.get("content") or ""
    _chash_full = proposal_content_hash(p)
    _n_invis = sum(_content.count(raw) for raw, _ in _INVISIBLE_MARKS)
    # v2.25.18：变体选择器（U+FE00-FE0F）不在列举集内但同样计入告警（与 _visible_text 兜底同口径）
    _n_invis += sum(1 for _ch in _content if 0xFE00 <= ord(_ch) <= 0xFE0F)
    info("即将为以下提案预生成人类绑定签名（签名覆盖下方提案全文；确认无误后再输口令）：")
    info("  提案 id   : {}".format(p.get("id")))
    info("  制品/操作 : {} / {}{}".format(p.get("artifact"), p.get("op"),
          (" → " + str(p.get("target"))) if p.get("target") else ""))
    info("  内容哈希  : {}（对提案全文的 SHA-256，供带外核对提案内容未被调包）".format(_chash_full))
    info("  提案全文（共 {} 字符）：".format(len(_content)))
    if _n_invis:
        warn("提案内容含 {} 处不可见/转义字符（ANSI/零宽/BOM 等），已在下方以 [ESC]/[ZWSP] 等标记展示——"
             "请把标记也视为内容的一部分再确认（签名绑定的是原始字节口径的全文）。".format(_n_invis))
    for _line in (_visible_text(_content).splitlines() or ["（空内容）"]):
        info("    | {}".format(_line))
    info("  ⚠️ 泄露面：本签名仅授权上述全文的这一提案一次 apply（绑定 t0，v2.25.16 起由引擎 use-once 强制）；"
         "签名输出或 --out 文件经任何渠道泄露，等同把该提案的 apply 授权交给持有者——"
         "请仅经可信信道传递，用后即可删除。")
    chash = proposal_content_hash(p)
    _t0 = _episodes_len(st)  # v2.25.16：行数口径（不经 512KB 上限），与 apply 验签/落盘同值
    warn("t0={}（试用窗起点）。签名后至 apply 前不得再记账（episode），"
         "否则 t0 变化 → apply 验签失败（fail-closed），需重新 `confirm --sign`。".format(_t0))
    try:
        sig = st.bind_human_signature(p, chash, _t0)
    except Exception as _e:
        bad(add_fix("预签名失败（{}）".format(_e),
                    "确认口令；忘记则 `confirm --init` 重置后重试"))
        return 2
    # 自验回环（v2.25.16 定位校准）：**漂移检测，非独立验证**——与 apply 共用同一 verify 与同一公钥，
    # 能抓 sign→verify 之间的公钥漂移/信任根切换（rc=3 唯一触发路径），无增量密码学保证。
    ok_v, reason = st.verify_human_binding(p, sig, _t0)
    if not ok_v:
        bad(add_fix("预签名自验失败（{}），已放弃输出".format(reason),
                    "内部异常（sigcrypto/公钥信任根状态），请反馈"))
        return 3
    out_path = getattr(args, "out", None)
    if out_path:
        if os.path.isdir(out_path):
            bad(add_fix("--out 指向目录而非文件：{}（v2.25.16 起精确判别）".format(out_path),
                        "换成具体文件路径（如 sig.txt）；目录不能作为签名落盘目标，--force 也无效"))
            return 2
        if os.path.exists(out_path) and not getattr(args, "force", False):
            bad(add_fix("--out 目标已存在：{}（v2.25.16 起拒绝静默覆盖）".format(out_path),
                        "换一个文件名，或加 --force 显式覆盖"))
            return 2
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(sig + "\n")
            ok("绑定签名已写入 {}（单行 base64，可直接经 --sig 传入）。".format(out_path))
        except Exception as _e:
            bad(add_fix("签名文件写入失败（{}）".format(_e),
                        "检查 --out 路径权限；签名已在下方输出，可直接复制使用"))
            info("t0={}  绑定签名（base64，供直接复制）：".format(_t0))
            info(sig)
            return 2  # v2.25.16：写失败不再返回 rc=0（调用方可感知失败）
    info("t0={}  绑定签名（base64）：".format(_t0))
    info(sig)
    info("无人值守应用：python metacog.py apply --id {} --sig <上方签名或 $(cat 签名文件)>".format(pid))
    return 0


def cmd_confirm(st: Store, args):
    """W1 人类闸密钥管理：人类在 TTY 生成/轮换 RSA 密钥对、预生成绑定签名。

    - `confirm --keygen`：生成 RSA-2048 密钥对；私钥以口令加密落盘，公钥明文存盘
      （供 apply 验签），Agent 进程永不持有私钥明文。幂等。
    - `confirm --init`：轮换解锁私钥的口令（旧口令解密 → 新口令重加密）。
    - `confirm --sign --id <提案id> [--out <文件>]`（v2.25.14，v2.25.15 收口知情同意，v2.25.16 收口 use-once/--out）：为指定过闸提案预生成
      人类绑定签名（覆盖 id+内容哈希+t0），供无人值守 `apply --sig` 使用；
      仍须人类 TTY 口令解锁私钥，安全语义与 apply 当场签名一致；
      v2.25.15 起签名前打印提案**全文**（不再截断预览，防「预览良性+尾部恶意」骗签）+ 内容哈希带外核对 + 泄露面警告；
      v2.25.16 起泄露面警告由引擎 use-once enforce（同一签名仅消费一次），--out 已存在须 --force、写失败 rc=2。

    注：v2.5.7 起人类签名已合并到 `apply` 时刻（TTY 口令签绑定签名，覆盖
    提案 id + 内容哈希 + 试用窗起点），不再有独立的 `confirm --approve` 步骤。

    核心不变量：私钥从不进入 Agent 进程，只有人类在 TTY 用口令解锁后才能签名。"""
    if not _require_tty():
        bad(add_fix("confirm 必须由人类在真实终端交互运行（当前非 TTY）",
                    "请人类亲自打开终端执行本命令；agent 不得代替人类运行 confirm"))
        return 2
    if getattr(args, "sign", False):
        return _confirm_sign(st, args)
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
    except LedgerAnchorDefaultError as e:
        # v2.27.16（M-6 收口）：信任根锚未就绪是 init-domain 最常见的失败真实原因——
        # 不再误导"检查 --output 目录可写"（与该错误无关）。给出准确修复路径。
        bad(add_fix("初始化失败（信任根锚未就绪）：{}".format(e),
                    "为 METACOG_TRUST_ROOT_ANCHOR_KEY 配置 base64 编码的 ≥32 字节专属随机密钥"
                    "（本地开发/测试同理，C-01 收口后不再有默认兜底锚）。"
                    "此错误与 --output 目录权限无关。"))
        return 2
    except Exception as e:  # noqa: BLE001 - 初始化失败需明确回报，不静默
        _msg = str(e)
        if "ANCHOR_KEY" in _msg or "METACOG_TRUST_ROOT" in _msg:
            bad(add_fix("初始化失败（信任根锚未就绪）：{}".format(e),
                        "配置 METACOG_TRUST_ROOT_ANCHOR_KEY 专属随机密钥"
                        "（C-01 收口后不再有默认兜底锚）。"
                        "此错误与 --output 目录权限无关。"))
        else:
            bad(add_fix("初始化失败: {}".format(e),
                "检查 --domain 取值与 --config 字段是否匹配模板；"
                "若提示信任根/锚相关错误，请见上方 ANCHOR_KEY 说明"))
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


# v2.27.16（M-4 收口）：版本硬下限——低于此（如攻击者把 SKILL.md 与 package.json 两处 version
# 同时降到 2.8.0 以重开 legacy 截止期并恢复降级通道）一律 fail-closed。本版本起设定，随每次发布抬升。
MIN_SUPPORTED_VERSION = (2, 27, 35)


def _ver_tuple(s: str):
    try:
        return tuple(int(x) for x in str(s).split("."))
    except (ValueError, AttributeError):
        return None


def _check_version_binding():
    """v2.9.0（L-3 / H-2）：SKILL.md `version:` 头须与包版本一致；不一致（升级漏改）→ legacy 截止期判定永久失效。
    v2.27.15（N-14 收口）：参照物从 Store.CURRENT_VERSION_TUPLE（同源自 SKILL.md，自比恒真、
    「漏改告警」结构上不可达）改为 **package.json 的 version 字段**（独立落盘源）。
    v2.27.15（Hermes 三审 M-N3c 收口）：异常路径 fail-closed 化——SKILL.md 存在但 package.json
    缺失/损坏/解析失败 → 判不一致（False）并告警，不再静默放行（防「删 package.json → 绑定检查
    静默 skip → 假绿灯」）。仅「无 SKILL.md」（脚本独立运行场景）维持放行。"""
    try:
        _root = Path(__file__).resolve().parent.parent
        _sk = _root / "SKILL.md"
        if not _sk.exists():
            return (True, "no SKILL.md present")
        _txt = _sk.read_text(encoding="utf-8")
        _m = re.search(r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)", _txt, re.M)
        if not _m:
            return (True, "no version: field")
        _decl = _m.group(1)
        _pj = _root / "package.json"
        if not _pj.exists():
            # M-N3c：SKILL.md 在而 package.json 缺 → 异常态，fail-closed
            return (False, "package.json missing（版本绑定的独立参照物缺失，疑似删除/损坏——请恢复）")
        try:
            _pkg_ver = str(json.loads(_pj.read_text(encoding="utf-8")).get("version", ""))
        except Exception as _je:
            return (False, "package.json 解析失败（{}）——版本绑定无法核验，fail-closed".format(_je))
        _ok = _decl == _pkg_ver
        if _ok:
            _dt = _ver_tuple(_decl)
            _pt = _ver_tuple(_pkg_ver)
            if _dt is not None and _dt < MIN_SUPPORTED_VERSION:
                return (False, "SKILL.md version {} 低于最低支持版本 {}.{}.{}（疑似被降级以重开 legacy 截止期），fail-closed".format(
                    _decl, *MIN_SUPPORTED_VERSION))
            if _pt is not None and _pt < MIN_SUPPORTED_VERSION:
                return (False, "package.json version {} 低于最低支持版本 {}.{}.{}，fail-closed".format(
                    _pkg_ver, *MIN_SUPPORTED_VERSION))
        return (_ok, "skill.md={} package.json={}".format(_decl, _pkg_ver))
    except Exception as _e:
        warn("[版本绑定] 检查异常（{}）——fail-closed 判不一致，请人工核验包完整性。".format(_e))
        return (False, "check error: {}".format(_e))


# ----------------------------------------------------------------------------
# C-1 完全非对称化（v2.27.21 阶段1）：锚状态 attestation 命令组
# ----------------------------------------------------------------------------
# 信任根分层：运行期 HMAC 锚（env 对称密钥，本进程可读 = 部署契约残余）保留为
# 「意外损坏检出层」；真正防篡改承诺挪到**离线私钥**——人类离线对本 Store 的
# ledger 状态 commitment 签 RSA attestation，进程内只有公钥（钉固树外只读）。
# 被约束方事后篡改 ledger → commitment 变 → attestation 失配 → fail-closed，
# 且无私钥无法伪造新 attestation。双轨过渡（阶段1）：公钥/attestation 未配置
# → WARN 不阻断（现网行为不变）；阶段2 起可经 env 强制。

# 测试可重定向：attestation 公钥/认证文件所在目录（默认与 freeze 树外锚同目录约定）
# v2.27.33（内聚性修复）：本目录亦响应 METACOG_ATTEST_ROOT_ANCHOR env——此前 RK_pub/AK_pub/
# attestation 落点固定 home 常量、仅密封路径读 env，两处落点分裂（包内核验须改模块属性才能对齐）。
# env 存在时统一指向之（与 _attest_root_anchor_dir 同源）；测试仍可直接赋值模块属性覆盖。
ATTEST_ANCHOR_DIR = (Path(os.environ["METACOG_ATTEST_ROOT_ANCHOR"]).resolve()
                     if os.environ.get("METACOG_ATTEST_ROOT_ANCHOR")
                     else Path.home() / ".metacog_freeze_anchors")
# attestation 默认覆盖的 ledger 状态文件（相对 st.root；缺失 → commit 记 "missing"，
# 事后补建/删除均改变 commit → 与既有 attestation 失配，同样 fail-closed）。
# v2.27.23（C-1 ③）：新增 frozen-hashes.jsonl（H-05 冻结完整性账本）纳入 commitment——
# 使 attestation 也覆盖「冻结基线」本身，攻击者替换 frozen-hashes.jsonl（即便 H-05 未强制）
# 亦被 attestation 验签失配捕获（fail-closed，防御纵深）。commit 键自动推导为 frozen_hashes。
ATTEST_FILES = ("ledger/integrity.json", "ledger/applies.jsonl", "ledger/sig-claims.jsonl", "frozen-hashes.jsonl")

# v2.27.24（C-1 阶段2/3）：受管控命令集合——派发前须经 C-1 强制闸门（非对称 attestation 层）。
# 仅覆盖改变 ledger/制品的自修改生命周期命令；只读命令与 attestation 布建命令不在此列。
ATTEST_GATED_CMDS = ("propose", "gate", "apply", "resign", "rollback", "verdict")


def _attest_slug(st):
    """v2.27.35（R2-N-5 收口）：树外锚文件命名 slug = 「目录名--规范路径哈希前12位」。
    v2.27.34 及以前为纯目录名——同机两个同名根目录实例会互相覆盖对方树外锚
    （同用户可写域内交叉污染，R2-N-5，Low）。取规范路径哈希后：同名异路径实例
    命名空间隔离；同实例（路径不变）slug 稳定。
    刻意**不依赖 CONTRACT.md 内容**（含钉固值）：R3-1 攻击删钉固行后 ever-armed
    检测仍须能定位锚文件（legacy 存在性回退见 _anchor_trace_exists）。"""
    import hashlib as _h
    canon = os.path.normcase(str(Path(st.root).resolve()))
    return "{}--{}".format(st.root.name, _h.sha256(canon.encode("utf-8")).hexdigest()[:12])


def _legacy_anchor_bound(st):
    """v2.27.35（R2-N-5 迁移）：legacy（纯目录名）锚集是否密码学绑定本实例。
    判据 = legacy RK_pub 存在且其指纹 == CONTRACT.md 根钉固值——攻击者在共享锚目录
    放同名异钥文件即绑定失败 → 不回退 → fail-closed。钉固缺失（含 R3-1 删行）→ False。"""
    legacy = ATTEST_ANCHOR_DIR / (st.root.name + ".root-pub.txt")
    if not legacy.exists():
        return False
    try:
        pin = st.pinned_root_attest_pubkey_sha256()
    except ValueError:
        return False
    if not pin:
        return False
    try:
        import sigcrypto as _sc
        return _sc.anchor_pubkey_sha256(legacy.read_text(encoding="utf-8")) == pin
    except (OSError, ValueError):
        return False


def _anchor_read_path(st, new_path, suffix):
    """v2.27.35（R2-N-5 迁移）：锚文件**读**解析——新命名优先；缺失且 legacy 锚集绑定
    本实例（_legacy_anchor_bound）时回退 legacy 命名。
    **写路径永远用新命名**（各 _write_readonly 调用点直接用 getter 新名不改），
    legacy 只读不写——迁移随下次布建/仪式自然完成，无需单独迁移命令。
    注意：本函数不可用于写路径，否则迁移永不前进。"""
    try:
        if new_path.exists():
            return new_path
    except OSError:
        return new_path
    if _legacy_anchor_bound(st):
        legacy = new_path.parent / (st.root.name + suffix)
        try:
            if legacy.exists():
                return legacy
        except OSError:
            pass
    return new_path


def _anchor_trace_exists(st, suffix, require_v1=False):
    """v2.27.35（R2-N-5）：曾武装痕迹存在性判定——新命名 OR legacy 命名任一存在即真。
    **刻意不做绑定校验**（存在性判据与合同内容解耦）：R3-1 攻击删钉固行后 pin=None、
    绑定不可判，但 legacy 锚文件仍在 → 仍判曾武装 → fail-closed（不回归 R3-1）。
    代价（诚实披露）：同名异实例的 legacy 残留会令本实例误判曾武装 → 闸门拒绝、
    须显式 --armed-recovery 人工复核——宁误报不漏报，方向安全。"""
    try:
        p_new = ATTEST_ANCHOR_DIR / (_attest_slug(st) + suffix)
        if p_new.exists():
            if not require_v1:
                return True
            return p_new.read_text(encoding="utf-8").strip().startswith("v1:")
    except OSError:
        pass
    try:
        p_leg = ATTEST_ANCHOR_DIR / (st.root.name + suffix)
        if p_leg.exists():
            if not require_v1:
                return True
            return p_leg.read_text(encoding="utf-8").strip().startswith("v1:")
    except OSError:
        pass
    return False


def _attest_pubkey_path(st):
    return ATTEST_ANCHOR_DIR / (_attest_slug(st) + ".attest-pub.txt")


def _attest_file_path(st):
    return ATTEST_ANCHOR_DIR / (_attest_slug(st) + ".attest.json")


# v2.27.25（C-1 外部域存储闸门 · 代码可落地部分）：权威信任根（公钥指纹）存至 Agent 可写域之外。
# 默认落点 = ATTEST_ANCHOR_DIR（树外 home 目录，同用户进程可写——仅防御纵深：防 tree-only 篡改 +
# 与 CONTRACT.md 钉固形成「树内 + 树外」双权威交叉核对）；真正闸门须经 METACOG_ATTEST_ROOT_ANCHOR
# 重定向到 Agent 进程不可写的位置（不同用户 / 管理员保护 / HSM / 只读介质），方为真正外部域闸门。
def _attest_root_anchor_dir():
    env = os.environ.get("METACOG_ATTEST_ROOT_ANCHOR")
    if env:
        return Path(env).resolve()
    return ATTEST_ANCHOR_DIR


def _attest_root_anchor_path(st):
    return _attest_root_anchor_dir() / (_attest_slug(st) + ".attest-root.txt")


def _break_glass_path(st):
    """破闸计数文件（v2.27.31 R-5）——树外锚目录，纳入 attestation commitment。"""
    return ATTEST_ANCHOR_DIR / (_attest_slug(st) + ".breakglass.json")


def _break_glass_log_path(st):
    """破闸留痕日志（v2.27.31 R-5）——树外锚目录，append-only（HMAC 链，若锚密钥可用）。"""
    return ATTEST_ANCHOR_DIR / (_attest_slug(st) + ".breakglass.log")


def _break_glass_state(st):
    """读取破闸计数状态：{'count': int, 'last': str}（文件缺失 → count 0）。"""
    p = _anchor_read_path(st, _break_glass_path(st), ".breakglass.json")
    try:
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            return {"count": int(d.get("count", 0)), "last": str(d.get("last", ""))}
    except Exception:
        pass
    return {"count": 0, "last": ""}


def _ensure_break_glass_file(st):
    """确保破闸计数文件存在（count=0）——v2.27.31 R-5：签名时 commitment 需稳定。"""
    p = _break_glass_path(st)
    if p.exists():
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"count": 0, "last": ""}, ensure_ascii=False, sort_keys=True),
                     encoding="utf-8")
    except OSError:
        pass


def _break_glass_increment(st, reason):
    """破闸计数 +1 并追加留痕日志（v2.27.31 R-5）。

    计数文件纳入 attestation commitment → 破闸后 commitment 与已签 attestation 失配
    → 后续受控命令 fail-closed（须离线重签）。即：破闸不再「无痕」。"""
    p = _break_glass_path(st)
    stt = _break_glass_state(st)
    stt["count"] += 1
    stt["last"] = reason
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(stt, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    lp = _break_glass_log_path(st)
    line = "{} count={} reason={}".format(
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        stt["count"], reason)
    try:
        with lp.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    return stt


def _root_pub_path(st):
    """v2.27.32（R-1 双密钥根信任）：根信任公钥 RK_pub 落点（树外锚目录，独立文件）。"""
    return ATTEST_ANCHOR_DIR / (_attest_slug(st) + ".root-pub.txt")


def _root_ever_armed(st):
    """v2.27.33（DSH §2.3 收口）→ v2.27.34（DSH R3-1 收口）：「曾武装」标记——与 CONTRACT.md
    钉固行**无关**的信任根存在性证据。任一为真即说明本机曾建立（或试图建立）双密钥根信任：
      ① 树外 RK_pub 文件存在（v2.27.32 起由 anchor-root-pub-install 放置）；
      ② 树外密封文件存在且为 v1 签名密封格式（v2.27.32 起由 RK 私钥签发；
         legacy 单密钥时代的裸指纹格式**不**计为武装——保持旧部署双轨兼容）；
      ③ v2.27.34（DSH R3-1）新增：树外 AK 层任一存在——`.attest-pub.txt`（AK 公钥）或
         `.attest.json`（AK 自签 attestation）。**这是 R3-1 修复的核心**：v2.27.33 仅判据
         ①+②，攻击者可「删净三处（钉固行+RK_pub+attest-root）但保留 AK 层」把系统回退到 fresh 态
         静默放行并重建信任链；纳入 AK 层后，**删三处（AK 仍在）→ 仍判 ever-armed → fail-closed**。
         **诚实边界**：若攻击者连 AK 层一并删（四删全清），则所有曾武装痕迹归零 → ever-armed=False
         → 退化为 genuine fresh install，仍可重建链——此残余由带外 RK 指纹核对兜底（文件存在性判据
         的固有边界，DSH §3 建议的 CONTRACT 哨兵节可进一步抬高成本，本轮未实现）。
         fresh install 在 anchor-attest-keygen 之前不产生 AK 层文件，不会误伤 legacy 双轨。
      ④ v2.27.35（R2-N-5）：三层痕迹判定改为 _anchor_trace_exists——新命名 OR legacy
         （纯目录名）命名任一存在即真。legacy 回退**刻意不做绑定校验**（存在性与合同
         内容解耦，R3-1 删钉固行场景下绑定不可判仍能检出）。诚实代价：同名异实例的
         legacy 残留会误判曾武装 → fail-closed 须显式 --armed-recovery（宁误报不漏报）。"""
    # v2.27.35（R2-N-5）：三层痕迹均改为「新命名 OR legacy 命名」存在性判定
    if _anchor_trace_exists(st, ".root-pub.txt"):
        return True
    if _anchor_trace_exists(st, ".attest-root.txt", require_v1=True):
        return True
    # v2.27.34（DSH R3-1）：AK 层纳入曾武装判据——堵「删三处保留 AK 仍回退 fresh 静默放行」
    if _anchor_trace_exists(st, ".attest-pub.txt") or _anchor_trace_exists(st, ".attest.json"):
        return True
    return False


def _ledger_file_drift(st):
    """v2.27.33（DSH §2.1 收口）：逐条复算 frozen-hashes.jsonl 对实际文件，返回失配路径列表。

    背景：随包 attestation 的 commitment 只覆盖 5 个 ledger 文件、不直接覆盖代码——
    「交付字节 = 被认证字节」的唯一桥梁是冻结账本；账本一旦 stale（如 v2.27.32 包内
    10/36 失配），代码层认证即断裂。本检查使 anchor-attest-verify 在账本与实物不符时
    fail-closed，任何人都可无锚密钥复算（原 freeze.py verify 需锚密钥，审计人不可运行）。"""
    import hashlib as _hashlib
    lp = st.root / "frozen-hashes.jsonl"
    if not lp.exists():
        return []  # 从未 freeze record 过（无基线）→ 无对账对象，不构成 drift
    drifted = []
    for ln in lp.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            e = json.loads(ln)
            rel, want = e["path"], e["sha256"]
        except Exception:
            drifted.append("<unparseable-ledger-line>")
            continue
        p = st.root / rel
        try:
            got = _hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        except OSError:
            got = None
        if got != want:
            drifted.append(rel)
    return drifted


def _read_root_seal(st, max_age_days=0):
    """v2.27.32（R-1 双密钥根信任）：加载 RK_pub 并校验根锚签名密封，返回 (ak_fp, status)。

    status ∈ ok / root_pub_missing / root_pub_parse_fail / root_pin_ambiguous /
             root_pin_missing / root_pin_mismatch / seal_missing / unsigned /
             malformed / seal-bad-sig / seal-malformed / seal-expired
    密封由 **RK 私钥**签名、经 **RK_pub** 验签（第二权威，与 attestation 公钥 AK 解耦）；
    只有 ok 的指纹才可作为权威 AK_fp。root_pin_missing / root_pin_mismatch = 最高权威
    未建立/被篡改 → fail-closed（坐实审计 §3.3 入口 B：删钉固行不再静默放行）。"""
    import sigcrypto as _sc
    rp = _anchor_read_path(st, _root_pub_path(st), ".root-pub.txt")
    if not rp.exists():
        return (None, "root_pub_missing")
    try:
        rk_pem = rp.read_text(encoding="utf-8").strip()
        rk_pub = _sc.deserialize_pub(rk_pem)
    except Exception:
        return (None, "root_pub_parse_fail")
    try:
        root_pin = st.pinned_root_attest_pubkey_sha256()
    except ValueError:
        return (None, "root_pin_ambiguous")
    if root_pin is None:
        return (None, "root_pin_missing")
    if _sc.anchor_pubkey_sha256(rk_pem) != root_pin:
        return (None, "root_pin_mismatch")
    p = _anchor_read_path(st, _attest_root_anchor_path(st), ".attest-root.txt")
    if not p.exists():
        return (None, "seal_missing")
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except OSError:
        return (None, "unreadable")
    if not raw:
        return (None, "malformed")
    if not raw.startswith("v1:"):
        # 裸 64-hex 指纹（v2.27.31 前格式）——**不再被接受为权威**（攻击者可手写）
        return (None, "unsigned")
    ok, reason, ak_fp = _sc.anchor_root_seal_verify(rk_pub, raw, max_age_days=max_age_days)
    if not ok:
        return (None, {"seal-bad-sig": "seal-bad-sig", "seal-malformed": "seal-malformed",
                       "seal-expired": "seal-expired", "seal-unsigned": "unsigned"}.get(reason, reason))
    return (ak_fp, "ok")


def _read_attest_root_anchor(st):
    """兼容读取：返回 RK 验签后的 AK_fp 或 None。"""
    fp, _status = _read_root_seal(st)
    return fp


def _read_attest_root_anchor_sealed(st, pub=None):
    """v2.27.32：密封由 RK 私钥签名，验签密钥为 RK_pub（与 AK 解耦）；pub 参数已弃用。"""
    fp, status = _read_root_seal(st)
    return (fp, status)


def _seal_attest_root_anchor(st, sha, priv=None):
    """v2.27.32（R-1 双密钥根信任）：写入**签名密封记录**到外部根锚。

    priv 为离线 **RK 私钥**（根信任密钥，独立于 attestation 公钥 AK）——密封记录由 RK 私钥
    签名、经 RK_pub 验签（第二权威，与 AK 解耦）。Agent 进程内**永不持有 RK 私钥**。
    这实现的是 C-1 的**授权分离维度**：能改写外部根锚的主体，必须同时持有 RK 私钥；
    同用户攻击者即使拿到令牌对、能写任意落点、自铸 AK 并自签 attestation，
    也无法产出由 RK 私钥签名的合法密封记录 → 根锚被改写即 seal-bad-sig → fail-closed。
    **故「写入者 ≠ 信任根持有者」在语义上成立（v2.27.31 单密钥自签方案被审计证伪后重写）。**
    priv 为 None 时仅写裸指纹（**仅兼容旧格式，禁止在信任路径使用**）。"""
    import sigcrypto as _sc
    d = _attest_root_anchor_dir()
    d.mkdir(parents=True, exist_ok=True)
    content = (sha + "\n") if priv is None else (
        _sc.anchor_root_seal_sign(priv, sha) + "\n")
    _write_readonly(_attest_root_anchor_path(st), content)


def _attest_commits(st):
    """重算当前 ledger 状态 commitment（{name: sha256hex|"missing"}）。

    v2.27.31（R-5）：追加 break_glass —— 破闸计数文件的 sha256。
    破闸使该计数变化 → commitment 与已签 attestation 失配 → 后续受控命令 fail-closed
    → 破闸必然留下「须离线重签」的可检痕迹（不再只是 stdout 一句话）。"""
    import hashlib as _hashlib
    commits = {}
    for rel in ATTEST_FILES:
        p = st.root / rel
        if not p.exists():
            commits[rel.split("/")[-1].split(".")[0].replace("-", "_")] = "missing"
        else:
            commits[rel.split("/")[-1].split(".")[0].replace("-", "_")] = (
                _hashlib.sha256(p.read_bytes()).hexdigest())
    _bg = _anchor_read_path(st, _break_glass_path(st), ".breakglass.json")
    try:
        commits["break_glass"] = (_hashlib.sha256(_bg.read_bytes()).hexdigest()
                                  if _bg.exists() else "missing")
    except OSError:
        commits["break_glass"] = "missing"
    return commits


def _attest_root_integrity(st):
    """v2.27.32（R-1 双密钥根信任 · R-4，供 freeze.record 门禁用）。

    返回 (ok, violations)：确认「信任根本体」完好——
    ① 根信任钉固 root_attest_pubkey_sha256 存在且 RK_pub 匹配（最高权威）；
    ② 根锚密封由 RK 私钥签名、经 RK_pub 验签有效（第二权威背书）；
    ③ 树外 AK 公钥指纹与密封背书指纹一致；④ attestation 文件存在。
    AK 钉固（CONTRACT.md）为冗余交叉核对；缺失亦可（密封已锚定 AK_fp）。
    **刻意不校验 commitment 匹配**：record 的用途正是重写被跟踪文件（必然使旧 commitment 失配），
    若要求匹配则「变更→重基线」流程自锁。安全性由「破闸计数 + 离线重签」保证。"""
    import sigcrypto as _sc
    viol = []
    try:
        root_pin = st.pinned_root_attest_pubkey_sha256()
    except ValueError as ex:
        return (False, ["ROOT-PIN-AMBIGUOUS: {}".format(ex)])
    if root_pin is None:
        # v2.27.33（DSH §2.3 收口）：曾武装（RK_pub / v1 密封存在）而钉固缺失 →
        # 疑似删除降级，record 不得放行（否则攻击者删一行即可重基线洗白篡改后的账本）
        if _root_ever_armed(st):
            return (False, ["ROOT-EVER-ARMED: 钉固行缺失但存在曾武装痕迹（RK_pub 文件 / v1 密封）——"
                            "疑似删除降级，拒绝重基线；请人工核对并经 --armed-recovery 显式恢复"])
        return (True, [])  # 未建立根信任（非 C-1 双密钥布建态）→ 不施加本门禁（legacy 行为）
    # ① RK_pub 存在且匹配根信任钉固
    rp = _anchor_read_path(st, _root_pub_path(st), ".root-pub.txt")
    if not rp.exists():
        viol.append("RK_pub 缺失（根信任未放置）")
        return (False, viol)
    try:
        rk_pem = rp.read_text(encoding="utf-8").strip()
        rk_pub = _sc.deserialize_pub(rk_pem)
    except Exception as ex:
        return (False, ["RK_pub 解析失败：{}".format(ex)])
    if _sc.anchor_pubkey_sha256(rk_pem) != root_pin:
        return (False, ["RK_pub 指纹与根信任钉固值不符（最高权威被篡改）"])
    # ② 根锚密封有效（RK 验签）
    ak_fp, seal_status = _read_root_seal(st, max_age_days=_attest_max_age_days())
    if seal_status != "ok":
        return (False, ["外部根锚密封无效（status={}）".format(seal_status)])
    # ③ AK 公钥指纹与密封背书指纹一致
    pub_path = _anchor_read_path(st, _attest_pubkey_path(st), ".attest-pub.txt")
    if not pub_path.exists():
        return (False, ["树外 AK 公钥缺失"])
    try:
        pub_pem = pub_path.read_text(encoding="utf-8").strip()
        live_sha = _sc.anchor_pubkey_sha256(pub_pem)
    except Exception as ex:
        return (False, ["树外 AK 公钥解析失败：{}".format(ex)])
    if live_sha != ak_fp:
        return (False, ["AK 公钥指纹与密封背书指纹不符（AK 公钥被替换）"])
    # AK 钉固交叉核对（冗余）：存在且不符 → 失败
    try:
        ak_pin = st.pinned_anchor_attest_pubkey_sha256()
    except ValueError as ex:
        return (False, ["AK-PIN-AMBIGUOUS: {}".format(ex)])
    if ak_pin is not None and ak_pin != ak_fp:
        return (False, ["AK 钉固值与密封背书指纹矛盾（树内/树外之一被篡改）"])
    if not _anchor_read_path(st, _attest_file_path(st), ".attest.json").exists():
        viol.append("attestation 文件缺失")
    if viol:
        return (False, viol)
    return (True, [])


def _write_readonly(p: Path, data: str):
    """写树外文件并落只读（Win FILE_ATTRIBUTE_READONLY / POSIX 0444，与 freeze 锚同款）。
    既有只读文件先解除（重装公钥/重签 attestation 场景），写后重新落只读。"""
    import os as _os
    import stat as _stat
    ATTEST_ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            _os.chmod(str(p), _stat.S_IWRITE)  # 解除只读（Windows 必需；POSIX 无害）
        except Exception:
            pass
    p.write_text(data, encoding="utf-8")
    try:
        _os.chmod(str(p), _stat.S_IREAD)
    except Exception:
        pass


def _attest_token_pair_ok(name_provided, name_expected):
    """v2.27.21（C-1 阶段1，M-03 同款）：特权令牌双 env 恒定时间比对。
    缺一或错配 → False（fail-closed）。读源码不等于持令牌。"""
    provided = os.environ.get(name_provided)
    expected = os.environ.get(name_expected)
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


def cmd_anchor_attest_keygen(st, args):
    """生成离线 attestation 密钥对：私钥口令加密落盘（提醒移离线介质），公钥明文导出。
    本命令在部署方信任环境运行；私钥文件不应留在被约束主机的可读位置。"""
    import sigcrypto as _sc
    outdir = Path(args.out).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    passphrase = os.environ.get(args.passphrase_env or "", "")
    if not passphrase:
        print("[REFUSED] 口令未配置：请设环境变量 {}（--passphrase-env 指定名）。"
              "口令不进命令行（C1_deploy 教训：进程列表泄露面）。".format(args.passphrase_env))
        return 1
    pub, priv = _sc.gen_keypair(2048)
    priv_file = outdir / "anchor-attest-priv.enc"
    pub_file = outdir / "anchor-attest-pub.txt"
    blob = _sc.encrypt_priv(_sc.serialize_priv(priv), passphrase)
    priv_file.write_text(json.dumps(blob), encoding="utf-8")
    pub_file.write_text(_sc.serialize_pub(pub), encoding="utf-8")
    print("[OK] 离线 attestation 密钥对已生成：")
    print("  私钥（口令加密）: {}".format(priv_file))
    print("  公钥（明文）    : {}".format(pub_file))
    print("[提醒] 请将私钥文件移至离线介质（C-1 目标：被约束主机只留公钥）；"
          "公钥随后经 anchor-attest-pubkey-install 钉固树外（须特权令牌）。")
    return 0


def cmd_anchor_attest_pubkey_install(st, args):
    """特权操作：把离线公钥钉固到树外只读目录（M-03 同款双 env 令牌门）。"""
    if not _attest_token_pair_ok("METACOG_ATTEST_PUBKEY_TOKEN", "METACOG_ATTEST_PUBKEY_TOKEN_EXPECTED"):
        warn("[REFUSED] anchor-attest-pubkey-install 被拒绝：缺少/错误的授权令牌"
             "（METACOG_ATTEST_PUBKEY_TOKEN 与 ..._EXPECTED 须成对提供且一致）。"
             "公钥钉固为特权信任根操作。")
        return 2
    pub_file = Path(args.pub).resolve()
    if not pub_file.exists():
        print("错误: 公钥文件不存在：{}".format(pub_file))
        return 1
    import sigcrypto as _sc
    try:
        _sc.deserialize_pub(pub_file.read_text(encoding="utf-8").strip())
    except Exception as ex:
        print("[REFUSED] 公钥解析失败（{}）——拒绝钉固非法公钥。".format(ex))
        return 1
    sha = _sc.anchor_pubkey_sha256(pub_file.read_text(encoding="utf-8"))
    # v2.27.30（M-A2 收口）：**先**校验与既有钉固值是否一致，不符即硬拒——
    # 避免先把新公钥写到树外（造成 verify 指纹失配的 fail-closed DoS）再谈钉固。
    try:
        cur_pin = st.pinned_anchor_attest_pubkey_sha256()
    except ValueError as ex:
        print("[REFUSED] CONTRACT.md 钉固解析歧义（{}）——拒绝改写信任根，请人工核对。".format(ex))
        return 1
    if cur_pin is not None and cur_pin != sha:
        # v2.27.32（§10 #3）：重钉授权**不得**来自调用方 env；须 RK 私钥签名（--repin-auth，文件）。
        auth = getattr(args, "repin_auth", None)
        _rk_pub = None
        _rp = _anchor_read_path(st, _root_pub_path(st), ".root-pub.txt")
        if _rp.exists():
            try:
                _rk_pub = _sc.deserialize_pub(_rp.read_text(encoding="utf-8").strip())
            except Exception:
                _rk_pub = None
        _auth_sig = None
        if auth:
            _ap = Path(auth)
            if not _ap.exists():
                print("[REFUSED] 重钉授权文件不存在：{}".format(_ap))
                return 1
            _auth_sig = _ap.read_text(encoding="utf-8").strip()
        if not _auth_sig or not _rk_pub or not _sc.root_repin_verify(_rk_pub, sha, _auth_sig):
            print("[REFUSED] 新公钥指纹 {} 与 CONTRACT.md 既有钉固值 {} 不符——重钉须 **RK 私钥签名授权**"
                  "（--repin-auth），不得由调用方 env 授权（v2.27.32 §10 #3）。"
                  "持 RK 私钥一方签署 repin:<新指纹> 后方可重钉。".format(sha[:16] + "...", cur_pin[:16] + "..."))
            return 1
    _write_readonly(_attest_pubkey_path(st), pub_file.read_text(encoding="utf-8").strip() + "\n")
    print("[OK] 公钥已钉固树外只读：{}".format(_attest_pubkey_path(st)))
    # v2.27.22（C-1 ①）：把公钥指纹钉入 CONTRACT.md（受 H-05 硬闸 + L1 冻结保护），
    # 作为结构性可写域闸门——攻击者替换树外公钥 + attestation 双文件时，因公钥指纹
    # 不匹配钉固值，verify 必拒（闭环审计主发现：pubkey+attestation 双文件替换伪造）。
    try:
        _force = bool(cur_pin is not None and cur_pin != sha)  # 已授权重钉 → 允许覆盖
        st.write_anchor_attest_pubkey_sha256(sha, force=_force)
        print("[OK] 公钥指纹已钉固 CONTRACT.md（anchor_attest_pubkey_sha256）：{}".format(sha[:16] + "..."))
        warn("[提示] CONTRACT.md 内容已变更，须重新基线冻结账本（record）以吸收本次钉固写入，"
             "否则 H-05 硬闸会因哈希漂移拒绝后续受保护命令。")
    except ValueError as ex:
        print("[REFUSED] 钉固 CONTRACT.md 指纹被拒（{}）——信任根未变更，install 失败。".format(ex))
        return 1
    except Exception as ex:  # noqa: BLE001
        print("[WARN] 钉固 CONTRACT.md 指纹失败（{}）——公钥已钉固树外但结构性闸门未生效，"
             "verify 仍按未钉固双轨。".format(ex))
    return 0


def cmd_anchor_attest_root_seal(st, args):
    """v2.27.25（C-1 外部域存储闸门）：把权威公钥指纹密封到外部根锚（Agent 可写域之外）。

    特权令牌门（M-03 同款）。须先 anchor-attest-pubkey-install 完成树外公钥钉固，或经 --pub 直接提供公钥文件。
    默认落点 = 树外 home 目录（同用户可写——仅防御纵深）；
    生产部署须将 METACOG_ATTEST_ROOT_ANCHOR 指向 Agent 进程不可写位置（不同用户/管理员/HSM/只读介质），
    方为真正外部域闸门——攻击者即便持 Agent 全写权也无法改写该权威，C-1 闭合才有实质意义。"""
    if not _attest_token_pair_ok("METACOG_ATTEST_PUBKEY_TOKEN", "METACOG_ATTEST_PUBKEY_TOKEN_EXPECTED"):
        warn("[REFUSED] anchor-attest-root-seal 被拒绝：缺少/错误的授权令牌"
             "（METACOG_ATTEST_PUBKEY_TOKEN 与 ..._EXPECTED 须成对提供且一致）。"
             "外部根锚为特权信任根操作。")
        return 2
    import sigcrypto as _sc
    pub_file = (Path(args.pub).resolve() if args.pub
                else _anchor_read_path(st, _attest_pubkey_path(st), ".attest-pub.txt"))
    if not pub_file.exists():
        print("错误: 公钥文件不存在：{}".format(pub_file))
        return 1
    try:
        pem = pub_file.read_text(encoding="utf-8").strip()
        _sc.deserialize_pub(pem)
    except Exception as ex:
        print("[REFUSED] 公钥解析失败（{}）——拒绝密封非法公钥。".format(ex))
        return 1
    sha = _sc.anchor_pubkey_sha256(pem)
    # v2.27.32（R-1 双密钥）：密封记录须由 **RK 私钥**签名（第二权威，与 AK 解耦）。
    # 未提供 RK 私钥 → 拒绝密封（否则同用户攻击者可自铸 AK 并自签密封冒充权威）。
    priv = None
    if args.priv:
        priv_file = Path(args.priv).resolve()
        if not priv_file.exists():
            print("[REFUSED] 私钥文件不存在：{}".format(priv_file))
            return 1
        passphrase = os.environ.get(args.passphrase_env or "", "")
        if not passphrase:
            print("[REFUSED] 口令未配置：请设环境变量 {}（--passphrase-env 指定名）。".format(args.passphrase_env))
            return 1
        try:
            _blob = json.loads(priv_file.read_bytes())
            priv = _sc.deserialize_priv(_sc.decrypt_priv_str(_blob, passphrase))
        except Exception as ex:
            print("[REFUSED] 私钥解密失败（{}）——fail-closed。".format(type(ex).__name__))
            return 1
    else:
        print("[REFUSED] anchor-attest-root-seal 须提供离线私钥（--priv + --passphrase-env）以签发"
              "签名密封记录（v2.27.31 R-1）。未签名的根锚可被同用户任意改写，不得进入信任路径。")
        return 1
    # v2.27.32（R-1 双密钥根信任）：根锚密封须由 **RK 私钥**签名、经 **RK_pub** 验签；
    # 密封前须确认 RK 已建立（RK_pub 已放置且匹配 CONTRACT.md 根信任钉固），否则密封无意义。
    try:
        _root_pin = st.pinned_root_attest_pubkey_sha256()
    except ValueError as ex:
        print("[REFUSED] CONTRACT.md 根信任钉固解析歧义（{}）——拒绝密封，请人工核对。".format(ex))
        return 1
    if _root_pin is None:
        print("[REFUSED] 根信任未建立（CONTRACT.md 无 root_attest_pubkey_sha256）——"
              "须先 anchor-root-keygen → anchor-root-pub-install 建立根信任后再密封。")
        return 1
    _rp = _anchor_read_path(st, _root_pub_path(st), ".root-pub.txt")
    if not _rp.exists():
        print("[REFUSED] RK_pub 文件缺失（{}）——须先 anchor-root-pub-install 放置 RK_pub。".format(_rp))
        return 1
    try:
        _rk_pub_pem = _rp.read_text(encoding="utf-8").strip()
        _rk_pub = _sc.deserialize_pub(_rk_pub_pem)
    except Exception as ex:
        print("[REFUSED] RK_pub 解析失败（{}）——拒绝密封。".format(ex))
        return 1
    if _sc.anchor_pubkey_sha256(_rk_pub_pem) != _root_pin:
        print("[REFUSED] RK_pub 指纹与 CONTRACT.md 根信任钉固值不符——最高权威被篡改，拒绝密封。")
        return 1
    # v2.27.30（R-9 收口）：密封前须与 CONTRACT.md 既有 AK 钉固值比对——不符即硬拒。
    # 此前 root-seal 接受任意 --pub 并直接密封其指纹（未与已钉固权威核对），构成设计性后门：
    # 攻击者可令根锚与任意公钥自洽（配合改写钉固值即闭环）。
    try:
        cur_pin = st.pinned_anchor_attest_pubkey_sha256()
    except ValueError as ex:
        print("[REFUSED] CONTRACT.md 钉固解析歧义（{}）——拒绝密封，请人工核对。".format(ex))
        return 1
    if cur_pin is not None and cur_pin != sha:
        print("[REFUSED] 待密封 AK 指纹 {} 与 CONTRACT.md 钉固值 {} 不符——拒绝密封"
              "（v2.27.30 R-9 收口）。请先经 anchor-attest-pubkey-install 完成钉固变更，"
              "再行密封。".format(sha[:16] + "...", cur_pin[:16] + "..."))
        return 1
    _seal_attest_root_anchor(st, sha, priv)
    # v2.27.32：回验刚签出的密封——确认 priv 确为 RK 私钥（与 RK_pub 匹配），避免误用错钥。
    _fp, _st = _read_root_seal(st, max_age_days=_attest_max_age_days())
    if _st != "ok":
        print("[REFUSED] 密封回验失败（{}）——priv 与 RK_pub 不匹配，拒绝进入信任路径。".format(_st))
        try:
            _attest_root_anchor_path(st).unlink()
        except Exception:
            pass
        return 1
    print("[OK] 权威 AK 指纹已**由 RK 私钥签名密封**外部根锚（写入者须持信任根私钥，v2.27.32 R-1 双密钥）：{}".format(
        _attest_root_anchor_path(st)))
    # v2.27.26（E1 收口）+ v2.27.30（L-A2 补强）：落点隔离判定不只看「本进程可写」，
    # 还要看**父目录**可写性——NTFS 上文件本身 0444 而父目录可写时，攻击者可直接 rename
    # 覆盖整个文件（Leg-1 攻防中已实证 rename 路径可行）。
    _anchor_dir = _attest_root_anchor_dir()
    _reasons = []
    if os.access(str(_anchor_dir), os.W_OK):
        _reasons.append("落点目录对本进程可写")
    _parent = _anchor_dir.parent
    try:
        if os.access(str(_parent), os.W_OK):
            _reasons.append("父目录 {} 可写（NTFS 可 rename 覆盖整文件）".format(_parent))
    except Exception:
        pass
    if _reasons:
        warn("[外部域未隔离·LOUD] 外部根锚落点未隔离：{}（落点 {}）——非真正外部域"
             "（同用户攻击者仍可改写该权威，双权威交叉核对对其同权失效）。"
             "生产须设 METACOG_ATTEST_ROOT_ANCHOR 指向 Agent 进程不可写位置"
             "（不同用户/管理员/HSM/只读介质，且其父目录亦不可写）；离线私钥亦须确离线持有。"
             .format("；".join(_reasons), _anchor_dir))
    else:
        print("[OK] 外部根锚落点目录及其父目录对本进程均不可写，符合真正外部域闸门要求。")
    return 0


def cmd_anchor_root_keygen(st, args):
    """v2.27.32（R-1 双密钥根信任）：生成根信任密钥对 RK。

    RK 是独立于 attestation 密钥（AK）的**第二权威**，由人类离线持有。其私钥仅用于：
    ① 签署根锚密封（anchor-attest-root-seal）；② 授权 AK 公钥重钉（repin-auth）。
    私钥口令加密落盘（提醒移离线介质），公钥明文导出。"""
    import sigcrypto as _sc
    outdir = Path(args.out).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    passphrase = os.environ.get(args.passphrase_env or "", "")
    if not passphrase:
        print("[REFUSED] 口令未配置：请设环境变量 {}（--passphrase-env 指定名）。".format(args.passphrase_env))
        return 1
    pub, priv = _sc.gen_keypair(2048)
    priv_file = outdir / "root-priv.enc"
    pub_file = outdir / "root-pub.pem"
    blob = _sc.encrypt_priv(_sc.serialize_priv(priv), passphrase)
    priv_file.write_text(json.dumps(blob), encoding="utf-8")
    pub_file.write_text(_sc.serialize_pub(pub), encoding="utf-8")
    print("[OK] 根信任密钥对 RK 已生成：")
    print("  私钥（口令加密）: {}".format(priv_file))
    print("  公钥（明文）    : {}".format(pub_file))
    print("[提醒] 请将 RK 私钥移至离线介质（RK 为第二权威，仅用于密封 AK 指纹与授权重钉）；"
          "其公钥指纹 {} 须带外分发给消费者，并在 CONTRACT.md 钉固为最高权威"
          "（root_attest_pubkey_sha256）。".format(_sc.anchor_pubkey_sha256(
              pub_file.read_text(encoding="utf-8"))[:16] + "..."))
    return 0


def cmd_anchor_root_pub_install(st, args):
    """v2.27.32（R-1 双密钥根信任）：放置 RK 公钥到树外只读目录，并钉固其指纹为最高权威。

    特权令牌门。RK 公钥指纹（root_attest_pubkey_sha256）是 C-1 信任链的**最高权威**；缺失即 fail-closed。
    v2.27.33（DSH §2.5 N-2 收口）：
      - **校验先行**：与既有钉固/RK_pub 的全部冲突判定在**写盘之前**完成——原实现先
        _write_readonly 覆盖 RK_pub 再做钉固校验，被拒时公钥文件已被覆盖（自我 DoS）。
      - **--rotate-auth**（文件）：RK 轮换授权——由**当前** RK 私钥对 root-rotate:<新RK_fp>
        签名（root_rotate_sign），经当前 RK_pub + 钉固核对后验签放行。补齐此前缺失的
        RK 轮换授权路径（原实现换 RK 直接硬拒，轮换只能手编 CONTRACT.md）。
      - **--armed-recovery**：曾武装恢复开关——钉固行缺失但 RK_pub 文件 / v1 密封仍在
        （疑似删除降级）时，重装须显式声明并 LOUD 告警（防「删一行即静默重建信任链」，
        与 _attest_enforce_mode 的曾武装 fail-closed 配套）。"""
    if not _attest_token_pair_ok("METACOG_ATTEST_PUBKEY_TOKEN", "METACOG_ATTEST_PUBKEY_TOKEN_EXPECTED"):
        warn("[REFUSED] anchor-root-pub-install 被拒绝：缺少/错误的授权令牌。")
        return 2
    pub_file = Path(args.pub).resolve()
    if not pub_file.exists():
        print("错误: RK 公钥文件不存在：{}".format(pub_file))
        return 1
    import sigcrypto as _sc
    try:
        _sc.deserialize_pub(pub_file.read_text(encoding="utf-8").strip())
    except Exception as ex:
        print("[REFUSED] RK 公钥解析失败（{}）——拒绝放置非法公钥。".format(ex))
        return 1
    sha = _sc.anchor_pubkey_sha256(pub_file.read_text(encoding="utf-8"))
    # --- v2.27.33：校验先行（写盘前完成全部冲突判定）---
    try:
        cur_pin = st.pinned_root_attest_pubkey_sha256()
    except ValueError as ex:
        print("[REFUSED] CONTRACT.md 根信任钉固解析歧义（{}）——拒绝改写信任根，请人工核对。".format(ex))
        return 1
    _rp = _root_pub_path(st)  # 写路径（新命名，v2.27.35 R2-N-5）
    _rp_read = _anchor_read_path(st, _rp, ".root-pub.txt")
    _cur_pem = None
    if _rp_read.exists():
        try:
            _cur_pem = _rp_read.read_text(encoding="utf-8").strip()
            _cur_pub = _sc.deserialize_pub(_cur_pem)
        except Exception as ex:
            print("[REFUSED] 既有 RK_pub 文件解析失败（{}）——疑似篡改，拒绝在未裁决前覆盖"
                  "（v2.27.33 校验先行）。请人工核对后处理。".format(ex))
            return 1
    _force_rotate = False
    if cur_pin is not None and cur_pin != sha:
        # RK 轮换：须当前 RK 私钥签名授权（--rotate-auth），经当前 RK_pub 验签。
        auth = getattr(args, "rotate_auth", None)
        _sig = None
        if auth:
            _ap = Path(auth)
            if not _ap.exists():
                print("[REFUSED] RK 轮换授权文件不存在：{}".format(_ap))
                return 1
            _sig = _ap.read_text(encoding="utf-8").strip()
        if not _cur_pem or not _sig or not _sc.root_rotate_verify(_cur_pub, sha, _sig):
            print("[REFUSED] 新 RK 指纹 {} 与既有钉固值 {} 不符——RK 轮换须 **当前 RK 私钥签名授权**"
                  "（--rotate-auth，root-rotate:<新指纹>），不得静默覆盖（v2.27.33 N-2）。"
                  "若既有 RK_pub 损坏无法验签，须人工裁决后手工恢复钉固。".format(sha[:16] + "...", cur_pin[:16] + "..."))
            return 1
        _force_rotate = True
    if cur_pin is None and _root_ever_armed(st):
        # v2.27.33：曾武装（RK_pub / v1 密封存在）而钉固缺失 → 重装须显式声明（LOUD）
        if not getattr(args, "armed_recovery", False):
            print("[REFUSED] 检测到曾武装痕迹（RK_pub 文件 / v1 密封存在）而钉固行缺失——"
                  "疑似删除降级，拒绝静默重装（v2.27.33 §2.3 收口）。"
                  "若为合法恢复，请显式加 --armed-recovery 并人工复核信任根状态。")
            return 1
        warn("[LOUD] --armed-recovery 显式恢复：钉固行缺失但曾武装痕迹存在，"
             "本次重装将重建根信任钉固——请人工复核 CONTRACT.md 与树外锚状态（信任根变更）。")
    # --- 校验全部通过，方才写盘（顺序即 N-2 修复本体）---
    _write_readonly(_rp, pub_file.read_text(encoding="utf-8").strip() + "\n")
    print("[OK] RK 公钥已放置树外只读：{}".format(_rp))
    try:
        st.write_root_attest_pubkey_sha256(sha, force=_force_rotate)
        print("[OK] RK 公钥指纹已钉固 CONTRACT.md（root_attest_pubkey_sha256，最高权威）：{}".format(
            sha[:16] + "..."))
        if _force_rotate:
            warn("[LOUD] RK 根信任已轮换（旧 RK 授权）——RK 公钥指纹已变更，"
                 "消费者侧带外分发的 root-fp 须重新分发核对。")
    except ValueError as ex:
        print("[REFUSED] 钉固 RK 指纹被拒（{}）——根信任未变更，install 失败。".format(ex))
        return 1
    return 0


def cmd_anchor_attest(st, args):
    """对本 Store 当前 ledger 状态签发 attestation（需离线私钥文件 + 口令 env）。
    产出 attest 串写入树外（默认）或 --out 指定路径。"""
    import sigcrypto as _sc
    priv_file = Path(args.priv).resolve()
    if not priv_file.exists():
        print("错误: 私钥文件不存在：{}".format(priv_file))
        return 1
    passphrase = os.environ.get(args.passphrase_env or "", "")
    if not passphrase:
        print("[REFUSED] 口令未配置：请设环境变量 {}。".format(args.passphrase_env))
        return 1
    try:
        _blob = json.loads(priv_file.read_bytes())
        priv = _sc.deserialize_priv(_sc.decrypt_priv_str(_blob, passphrase))
    except Exception as ex:
        print("[REFUSED] 私钥解密失败（{}）——口令错误或文件损坏（fail-closed）。".format(type(ex).__name__))
        return 1
    # v2.27.31（R-5）：破闸计数文件须在签发前落定（否则签发后计数文件出现 → commitment 失配）
    _ensure_break_glass_file(st)
    commits = _attest_commits(st)
    att = _sc.anchor_attest(priv, commits)
    out = Path(args.out).resolve() if args.out else _attest_file_path(st)
    if args.out is None:
        _write_readonly(out, att + "\n")
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(att + "\n", encoding="utf-8")
    print("[OK] attestation 已签发 → {}".format(out))
    for k, v in commits.items():
        print("  {}: {}".format(k, v[:16] + ("..." if len(v) > 16 else "")))
    return 0


def _attest_max_age_days():
    """v2.27.32（R-1 收口 §10 #5）：attestation / 根锚密封过期阈值（天）。

    默认 90；**≤0 或非法值一律回落为强制默认值 90**（v2.27.32 起严禁关闭过期——
    此前 METACOG_ATTEST_MAX_AGE_DAYS<=0 可令过期检查失效，使 200 天前签发的
    attestation 仍为 [OK]，属审计 §4.2 指出的可关过期开关）。
    v2.27.33（DSH §2.5 N-1）：**向上放宽同步禁止**——env 设 >90 一律钳回 90
    （阈值只允许调短以收紧，不允许调长以放宽过期窗；此前 env=1000 可令 240 天前
    的 attestation 复活为 [OK]）。过期 = 距签发时间戳（at）超过阈值 → 硬闸 fail-closed。"""
    try:
        v = int(os.environ.get("METACOG_ATTEST_MAX_AGE_DAYS", "90"))
    except ValueError:
        v = 90
    if v <= 0 or v > 90:
        return 90  # 强制默认：既不允许关闭过期，也不允许向上放宽过期窗
    return v


def _attest_enforce_mode(st):
    """v2.27.32（R-1 双密钥根信任）：返回强制模式，决定 verify / 闸门是否硬拒。

    - METACOG_ATTEST_ENFORCE == "0" → "off"（破闸：LOUD + 留痕，仅紧急逃生）。
    - == "1" → "on"（显式强制；缺失层 → 硬拒 rc=2）。
    - 未设（默认）：以**根信任 RK** 是否建立为权威触发——
        · RK 已建立（root_attest_pubkey_sha256 钉固存在 且 RK_pub 文件存在且匹配）
          且 AK 层完整（pub+att 均在）→ "armed"（默认强制）；
        · RK 已建立但 AK 层不完整 → "on"（fail-closed，不再静默双轨放行）；
        · RK 未建立 → v2.27.33（DSH §2.3 收口）**曾武装判定**：
            - 树外 RK_pub 文件或 v1 密封任一存在（= 曾建立根信任而钉固行/公钥文件
              现已缺失，疑似被删除降级）→ "on"（fail-closed，不再静默关闸——
              此前删钉固行或删 RK_pub 文件均可把 armed 静默降为 off，闸门全开零告警，
              且可重建攻击者自洽信任链）；
            - 两者皆缺 → "off"（真·legacy：本机从未启用双密钥根信任）。
    删除原 METACOG_ATTEST_ALLOW_PARTIAL_LAYER 静默 off 分支（审计 §4.2：该开关零告警放行，
    坐实入口 B）。该逃生需求改由 METACOG_ATTEST_ENFORCE=0 的 LOUD+留痕通道承载。"""
    env = os.environ.get("METACOG_ATTEST_ENFORCE", "")
    if env == "0":
        return "off"
    if env == "1":
        return "on"
    # v2.27.32：以 RK（第二权威）是否建立为触发，而非 AK 钉固行。
    try:
        root_pin = st.pinned_root_attest_pubkey_sha256()
    except ValueError:
        # 根信任钉固解析歧义（多行冲突）→ fail-closed
        return "on"
    if root_pin is None:
        # v2.27.33：曾武装（RK_pub 文件 / v1 密封存在）而钉固缺失 → 疑似删除降级 → fail-closed
        if _root_ever_armed(st):
            return "on"
        return "off"  # 真·legacy：从未启用双密钥根信任（无任何武装痕迹）
    if not _anchor_read_path(st, _root_pub_path(st), ".root-pub.txt").exists():
        # v2.27.33：钉固在而 RK_pub 文件缺失 → 曾武装降级 → fail-closed（原判 off 属缺陷）
        return "on"
    # RK 已建立：AK 层完整 → armed；不完整 → on（fail-closed，不再静默双轨）
    if (_anchor_read_path(st, _attest_pubkey_path(st), ".attest-pub.txt").exists()
            and _anchor_read_path(st, _attest_file_path(st), ".attest.json").exists()):
        return "armed"
    return "on"


def _attest_verify_core(st):
    """v2.27.32（R-1 双密钥根信任）：核验核心，供 verify 命令与强制闸门共用。

    返回 (status, detail)。status ∈
      ok                     — RK 验签密封有效 + AK 公钥/钉固匹配 + AK attestation 签名有效 + 未过期
      missing                — 树外 AK 公钥或 attestation 文件缺失（层未布建）
      parse_fail             — 树外 AK 公钥解析失败（疑似篡改）
      root_pub_parse_fail    — RK_pub 解析失败（疑似篡改）
      root_pin_mismatch      — RK_pub 指纹与 CONTRACT.md 根信任钉固值不符（最高权威被篡改）
      root_anchor_seal_invalid — 根锚密封无效/缺失/过期/手写（status 细节见 detail）
      root_anchor_mismatch   — 树外 AK 公钥指纹与密封背书指纹不符（AK 公钥被替换）
      root_anchor_conflict   — 密封背书指纹与 CONTRACT.md AK 钉固值矛盾（树内/树外之一被篡改）
      pin_ambiguous          — CONTRACT.md AK 钉固解析歧义（多行冲突）
      expired                — AK attestation 时间戳超出阈值
      malformed              — attestation 串格式畸形 / at 非法 / **at 为未来时间**（v2.27.33）
      ledger_drift           — 冻结账本与实际文件失配（v2.27.33：代码层认证桥断裂 → fail-closed）
      signature_fail         — ledger commitment 与 attestation 验签失配（已篡改或须重签）

    设计要点：根锚密封由 **RK 私钥**签名、经 **RK_pub** 验签（第二权威，与 AK 解耦）。
    攻击者无 RK 私钥即无法产出合法密封 → 入口 A/B（自铸密钥 + 重钉）被打破。"""
    import datetime as _dt
    import sigcrypto as _sc
    pub_path = _anchor_read_path(st, _attest_pubkey_path(st), ".attest-pub.txt")   # AK pub
    att_path = _anchor_read_path(st, _attest_file_path(st), ".attest.json")
    if not pub_path.exists() or not att_path.exists():
        return ("missing", None)
    try:
        pub_pem = pub_path.read_text(encoding="utf-8").strip()
        pub = _sc.deserialize_pub(pub_pem)
    except Exception as ex:
        return ("parse_fail", str(ex))
    live_sha = _sc.anchor_pubkey_sha256(pub_pem)

    # --- v2.27.32：RK 根信任密封（第二权威）---
    root_fp, seal_status = _read_root_seal(st, max_age_days=_attest_max_age_days())
    if seal_status == "root_pub_parse_fail":
        return ("root_pub_parse_fail", None)
    if seal_status == "root_pin_mismatch":
        return ("root_pin_mismatch", (root_fp, seal_status))
    if seal_status != "ok":
        # root_pub_missing / root_pin_missing / root_pin_ambiguous / seal_missing /
        # unsigned / malformed / seal-bad-sig / seal-malformed / seal-expired
        return ("root_anchor_seal_invalid", (seal_status, None))

    ak_fp = root_fp  # 密封背书指纹 = RK 验签得出的 AK 指纹（第二权威背书）
    if live_sha != ak_fp:
        return ("root_anchor_mismatch", (live_sha, ak_fp))   # 树外 AK 公钥被替换
    # AK 钉固（CONTRACT.md）交叉核对：冗余，非主键；缺失亦可（密封已锚定 AK_fp）
    try:
        ak_pin = st.pinned_anchor_attest_pubkey_sha256()
    except ValueError as ex:
        return ("pin_ambiguous", str(ex))
    if ak_pin is not None and ak_pin != ak_fp:
        return ("root_anchor_conflict", (ak_pin, ak_fp))

    # --- AK 自签 attestation 核验 + 过期 ---
    att = att_path.read_text(encoding="utf-8").strip()
    seg = att.split(":", 2)
    if len(seg) == 3 and seg[0] == "v1":
        at = seg[1]
        try:
            at_dt = _dt.datetime.strptime(at, "%Y%m%dT%H%M").replace(tzinfo=_dt.timezone.utc)
            max_age = _attest_max_age_days()
            if max_age > 0:
                age = (_dt.datetime.now(_dt.timezone.utc) - at_dt).days
                if age > max_age:
                    return ("expired", (at, age, max_age))
                # v2.27.33（DSH §2.5 N-3）：未来时间戳永不过期 → 拒收（age<0 即畸形语义）
                if age < 0:
                    return ("malformed", ("at-future", at))
        except ValueError:
            # v2.27.30（H-A2 收口）：非标准时间戳 → fail-closed。
            return ("malformed", ("at", at))
    commits = _attest_commits(st)
    ok, reason = _sc.anchor_attest_verify(pub, commits, att)
    if not ok:
        return ("malformed" if reason == "attest-malformed" else "signature_fail", reason)
    # v2.27.33（DSH §2.1 收口）：账本-实物逐条对账——commitment 只覆盖 ledger 文件本身，
    # 「交付字节 = 被认证字节」须由冻结账本桥接；账本 stale（如 v2.27.32 包内 10/36 失配）
    # 即代码层认证断裂 → fail-closed（任何人可无锚密钥复算，修复审计人不可运行 verify 的残余）。
    _drift = _ledger_file_drift(st)
    if _drift:
        return ("ledger_drift", _drift)
    return ("ok", commits)


def _attest_gate(st):
    """v2.27.24（C-1 阶段2/3）：强制闸门——在受管控命令派发前调用。
    返回 rc：0=放行；非0=硬拒（命令不执行）。未强制（双轨/off）→ 0（现网行为不变）。
    强制：层未布建/公钥解析失败/指纹失配/过期/验签失败/畸形 → 非0 硬拒。"""
    mode = _attest_enforce_mode(st)
    if mode == "off":
        # v2.27.26（H-3 收口）：显式破闸 METACOG_ATTEST_ENFORCE=0 不可静默 fail-open，
        # 须发 LOUD 告警（每次受管控命令派发前均可见），仅限紧急逃生/离线布建期。
        if os.environ.get("METACOG_ATTEST_ENFORCE") == "0":
            # v2.27.31（R-5）：破闸**留痕**——计数 +1 并写入 append-only 日志；
            # 计数纳入 attestation commitment → 破闸后 commitment 失配 →
            # 后续受控命令 fail-closed（须离线重签）→ 破闸不再是「无痕」。
            _bg = _break_glass_increment(st, "enforce=0")
            print("[WARN] C-1 破闸生效（METACOG_ATTEST_ENFORCE=0）：非对称 attestation 层已关闭，"
                  "受管控命令将在无任何信任根校验下放行（含 ledger 篡改/公钥替换风险）——"
                  "仅限紧急逃生/离线布建期，事后须立即恢复强制并人工复核。")
            print("[WARN] 破闸留痕：累计 {} 次；日志 {}。"
                  "本次破闸已使 attestation commitment 失配 → 后续受控命令将 fail-closed，"
                  "须持离线私钥重新签发后恢复。".format(_bg["count"], _break_glass_log_path(st)))
        return 0
    status, detail = _attest_verify_core(st)
    if status == "ok":
        return 0
    if status == "missing":
        print("[REFUSED] C-1 强制闸门：非对称层未布建（公钥/attestation 缺失）——命令被拒绝（rc=2）。"
              "须先 anchor-attest-keygen → anchor-attest-pubkey-install → anchor-attest 布建并离线签发。")
        return 2
    if status == "parse_fail":
        print("[REFUSED] C-1 强制闸门：树外公钥解析失败（疑似篡改），命令被拒绝（rc=1）。")
        return 1
    if status == "pin_mismatch":
        print("[REFUSED] C-1 强制闸门：公钥指纹与 CONTRACT.md 钉固值不符（疑似替换攻击），命令被拒绝（rc=1）。")
        return 1
    if status == "root_anchor_mismatch":
        print("[REFUSED] C-1 强制闸门：公钥指纹与外部根锚（Agent 可写域之外权威）不符（疑似替换攻击），命令被拒绝（rc=1）。")
        return 1
    if status == "root_anchor_conflict":
        print("[REFUSED] C-1 强制闸门：外部根锚与 CONTRACT.md 钉固值相互矛盾（树内/树外双权威之一被篡改），命令被拒绝（rc=1）。")
        return 1
    if status == "root_anchor_missing":
        print("[REFUSED] C-1 强制闸门：CONTRACT.md 已钉固（双权威意图）但外部根锚缺失或不可读（疑似被删除/权限收紧/未布建）——"
              "删除外部锚以静默降级到单权威属绕过双权威交叉核对，命令被拒绝（rc=1）。"
              "请经 anchor-attest-root-seal 补密封外部根锚。")
        return 1
    if status == "pin_ambiguous":
        print("[REFUSED] C-1 强制闸门：CONTRACT.md 钉固解析歧义（多处冲突指纹）——无法确定权威指纹，"
              "fail-closed，命令被拒绝（rc=1）。请人工核对 CONTRACT.md 锚状态 attestation 公钥根节。")
        return 1
    if status == "root_anchor_seal_invalid":
        print("[REFUSED] C-1 强制闸门：外部根锚**签名密封无效**（{}）——根锚缺失/被改写/手写/过期/格式损坏，"
              "信任根无法确认，fail-closed，命令被拒绝（rc=1）。"
              "须由持离线 RK 私钥的一方经 anchor-attest-root-seal 重新密封。".format(detail[0]))
        return 1
    if status == "root_pin_mismatch":
        print("[REFUSED] C-1 强制闸门：根信任公钥指纹与 CONTRACT.md 根信任钉固值不符（最高权威被篡改），"
              "命令被拒绝（rc=1）。请人工核对 root_attest_pubkey_sha256 钉固与 RK_pub 文件。")
        return 1
    if status == "root_pub_parse_fail":
        print("[REFUSED] C-1 强制闸门：根信任公钥 RK_pub 解析失败（疑似篡改），命令被拒绝（rc=1）。")
        return 1
    if status == "expired":
        print("[REFUSED] C-1 强制闸门：attestation 过期（{}，距今 {} 天 > 阈值 {} 天）——"
              "须人类离线重签，命令被拒绝（rc=1）。".format(detail[0], detail[1], detail[2]))
        return 1
    if status == "malformed":
        print("[REFUSED] C-1 强制闸门：attestation 畸形，命令被拒绝（rc=1）。")
        return 1
    if status == "signature_fail":
        print("[REFUSED] C-1 强制闸门：attestation 验签失败（ledger 状态已被篡改或须重签），命令被拒绝（rc=1）。")
        return 1
    if status == "ledger_drift":
        print("[REFUSED] C-1 强制闸门：冻结账本与实际文件失配（{} 条，如 {}）——"
              "「交付字节 = 被认证字节」的代码层认证桥已断裂，命令被拒绝（rc=1）。"
              "请以 freeze record 重基线并经离线私钥重签 attestation。".format(
                  len(detail), ", ".join(detail[:3])))
        return 1
    return 0


def cmd_anchor_attest_verify(st, args):
    """验锚状态 attestation（C-1 非对称层）。
    双轨（阶段1/3 未强制）：缺失 → WARN rc=0（运行期仍靠 env HMAC 检出层）；已配置 → 失配/过期
    /公钥指纹与 CONTRACT.md 钉固值不符 → rc=1。v2.27.22（①）：指纹须匹配 CONTRACT.md 钉固值
    （H-05 硬闸 + L1 冻结保护），否则 fail-closed——闭环审计主发现（同用户替换
    pubkey+attestation 双文件伪造）。v2.27.24（阶段2/3）：过期策略 + 默认强制（armed→mandatory）。
    v2.27.25（外部域存储闸门）：若外部根锚（Agent 可写域之外权威）已密封，其优先级高于 CONTRACT.md
    钉固——公钥指纹须匹配外部根锚，且外部根锚与 CONTRACT.md 钉固须一致（双权威交叉核对），否则 rc=1。"""
    status, detail = _attest_verify_core(st)
    # v2.27.32：RK 是否建立决定「未配置」是 legacy 双轨还是 fail-closed。
    try:
        root_pin = st.pinned_root_attest_pubkey_sha256()
    except ValueError:
        root_pin = None
    rk_established = bool(root_pin) and _anchor_read_path(
        st, _root_pub_path(st), ".root-pub.txt").exists()
    if status == "ok":
        commits = detail
        print("[OK] 锚状态 attestation 验证通过：ledger 状态与离线私钥认证一致"
              "（RK 验签密封 + AK 自签 attestation）。")
        for k, v in commits.items():
            print("  {}: {}".format(k, v[:16] + ("..." if len(v) > 16 else "")))
        if not rk_established:
            warn("[根信任未建立] CONTRACT.md 无 root_attest_pubkey_sha256 钉固或 RK_pub 缺失——"
                 "本机未启用双密钥根信任（legacy），C-1 承重结构未武装；"
                 "请经 anchor-root-keygen → anchor-root-pub-install 建立根信任。")
        return 0
    if status == "missing":
        if rk_established or _root_ever_armed(st):
            # v2.27.33：曾武装（RK_pub/密封存在）而 AK 层缺失同样 fail-closed，不再走 legacy WARN
            print("[FAIL] 根信任已建立（或存在曾武装痕迹）但树外 AK 公钥/attestation 缺失或不可读——"
                  "层被删除即视为绕过强制闸门的尝试，fail-closed（rc=1）。"
                  "请经 anchor-attest-pubkey-install + anchor-attest 重建层并离线重签。")
            return 1
        warn("[非对称层未配置] 树外 AK 公钥或 attestation 缺失——C-1 完全非对称化未启用，"
             "运行期仅靠 env HMAC 检出层（部署契约残余仍在）。")
        return 0
    if status == "parse_fail":
        print("[FAIL] 树外 AK 公钥解析失败（{}）——疑似被篡改，fail-closed。".format(detail))
        return 1
    if status == "root_pub_parse_fail":
        print("[FAIL] 根信任公钥 RK_pub 解析失败——疑似被篡改，fail-closed。")
        return 1
    if status == "root_pin_mismatch":
        print("[FAIL] 根信任公钥指纹与 CONTRACT.md 根信任钉固值不符（最高权威被篡改）——fail-closed（rc=1）。")
        return 1
    if status == "pin_mismatch":
        print("[FAIL] 树外 AK 公钥指纹与 CONTRACT.md AK 钉固值不符（{} vs {}）——"
              "疑似同用户替换公钥+attestation 双文件伪造，fail-closed。".format(
                  detail[0][:16], detail[1][:16]))
        return 1
    if status == "root_anchor_mismatch":
        print("[FAIL] AK 公钥指纹与 RK 验签密封背书指纹不符（{} vs {}）——"
              "疑似 AK 公钥替换攻击，fail-closed。".format(detail[0][:16], detail[1][:16]))
        return 1
    if status == "root_anchor_conflict":
        print("[FAIL] RK 验签密封背书指纹与 CONTRACT.md AK 钉固值矛盾（{} vs {}）——"
              "树内/树外之一被篡改，fail-closed。".format(detail[0][:16], detail[1][:16]))
        return 1
    if status == "root_anchor_missing":
        print("[FAIL] 根信任已建立但外部根锚缺失/不可读——fail-closed。请经 anchor-attest-root-seal 补密封。")
        return 1
    if status == "pin_ambiguous":
        print("[FAIL] CONTRACT.md 钉固解析歧义（多处冲突指纹，{}）——无法确定权威指纹，fail-closed。".format(detail))
        return 1
    if status == "root_anchor_seal_invalid":
        print("[FAIL] 外部根锚签名密封无效（{}）——根锚缺失/被改写/手写/过期/格式损坏，信任根无法确认，"
              "fail-closed（v2.27.32 R-1）。须由持离线 RK 私钥的一方重新密封。".format(detail[0]))
        return 1
    if status == "expired":
        print("[FAIL] attestation 过期（{}，距今 {} 天 > 阈值 {} 天）——须人类离线重签。"
              "fail-closed。".format(detail[0], detail[1], detail[2]))
        return 1
    if status == "malformed":
        print("[FAIL] 畸形 attestation（{}）——fail-closed。".format(detail))
        return 1
    if status == "ledger_drift":
        print("[FAIL] 冻结账本与实际文件失配（{} 条：{}…）——代码层认证桥断裂，"
              "fail-closed。请 freeze record 重基线 + 离线重签。".format(
                  len(detail), ", ".join(detail[:3])))
        return 1
    # signature_fail
    print("[FAIL] 锚状态 attestation 验证失败（ledger 状态已被篡改或 attestation 须重签）——fail-closed。")
    commits = _attest_commits(st)
    for k, v in commits.items():
        print("  当前 {}: {}".format(k, v[:16] + ("..." if len(v) > 16 else "")))
    return 1


def main(argv=None):
    # v2.9.0（L-3 / H-2）：版本零绑定运行时软闸——SKILL.md version 头须与 package.json 一致，
    # 不一致（漏改）→ legacy 截止期可能失效；非致命告警（不崩主流程），供运营巡检发现。
    # v2.27.15（N-14）：参照物改为 package.json（原与 CURRENT_VERSION_TUPLE 同源自比恒真）。
    _vb_ok, _vb_msg = _check_version_binding()
    if not _vb_ok:
        bad("[版本绑定] SKILL.md / package.json 版本不一致或低于最低支持版本（{}）："
            "legacy 截止期可能失效或被故意降级重开，已阻断命令（fail-closed）。请同步版本号后重试。".format(_vb_msg))
        return 1
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

    cf = sub.add_parser("confirm", help="W1 人类闸密钥管理：生成/轮换人类 RSA 密钥对、预生成绑定签名（人类 TTY）")
    cf.add_argument("--keygen", action="store_true", help="生成 RSA-2048 密钥对（私钥口令加密落盘，公钥明文存盘）；幂等")
    cf.add_argument("--init", action="store_true", help="轮换解锁私钥的口令（旧口令解密 → 新口令重加密）")
    cf.add_argument("--sign", action="store_true",
                    help="v2.25.14：为指定过闸提案预生成人类绑定签名（覆盖「提案 id + 内容哈希 + trial_from_index」），"
                         "供无人值守 `apply --sig` 使用；仍须人类 TTY 口令解锁私钥，安全语义与 apply 当场签名一致；"
                         "签名后至 apply 前不得再记账（episode），否则 t0 变化 → apply 验签失败需重签")
    cf.add_argument("--id", help="--sign 指定要预签名的过闸提案 id")
    cf.add_argument("--out", help="--sign 可选：把签名写入该文件（单行 base64），便于自动化读取")
    cf.add_argument("--force", action="store_true",
                    help="--out 目标已存在时显式覆盖（v2.25.16 起缺省拒绝静默覆盖）")
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
    vf.add_argument("--no-audit-entries", action="store_true",
                    help="N-11（v2.27.15，Hermes 三审 C-N3e 收口）：跳过条目级迁移扫描（默认开启）。"
                         "跳过时输出 warn 留痕——本输出不含条目级注入检查。")

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

    # v2.27.21（C-1 阶段1）：锚状态 attestation 命令组（离线私钥签 / 进程内仅公钥验）
    akg = sub.add_parser("anchor-attest-keygen",
                         help="C-1：生成离线 attestation 密钥对（私钥口令加密落盘，提醒移离线介质）")
    akg.add_argument("--out", required=True, help="密钥对输出目录")
    akg.add_argument("--passphrase-env", default="METACOG_ATTEST_PASSPHRASE",
                     help="口令所在环境变量名（口令不进命令行）")
    api_ = sub.add_parser("anchor-attest-pubkey-install",
                          help="C-1：钉固离线 AK 公钥到树外只读目录（特权令牌门）")
    api_.add_argument("--pub", required=True, help="AK 公钥文件（anchor-attest-keygen 产出）")
    api_.add_argument("--repin-auth", help="重钉授权签名（RK 私钥对 repin:<新AK_fp> 的签名，base64）；"
                                        "仅当与既有钉固值不符时必需（v2.27.32 §10 #3，取代原 env 自授权）")
    aa = sub.add_parser("anchor-attest",
                        help="C-1：对本 Store 当前 ledger 状态签发 attestation（需离线私钥文件 + 口令 env）")
    aa.add_argument("--priv", required=True, help="离线私钥文件（口令加密）")
    aa.add_argument("--passphrase-env", default="METACOG_ATTEST_PASSPHRASE",
                    help="口令所在环境变量名")
    aa.add_argument("--out", help="attestation 输出路径（默认树外只读目录）")
    aav = sub.add_parser("anchor-attest-verify",
                         help="C-1：验锚状态 attestation（未配置 → WARN 双轨；强制模式(armed/ENFORCE=1)下缺失→rc=2、失配/过期→rc=1）")
    aars = sub.add_parser("anchor-attest-root-seal",
                          help="C-1：密封权威公钥指纹到外部根锚（Agent 可写域之外，特权令牌门；须先 pubkey-install）")
    aars.add_argument("--pub", help="AK 公钥文件（默认取树外已钉固 AK 公钥；须先 anchor-attest-pubkey-install）")
    aars.add_argument("--priv", help="离线 RK 私钥文件（口令加密）——v2.27.32 R-1 双密钥：密封记录须由 RK 私钥签名")
    aars.add_argument("--passphrase-env", help="私钥口令所在环境变量名（口令不进命令行）")
    ark = sub.add_parser("anchor-root-keygen",
                         help="C-1 双密钥根信任：生成根信任密钥对 RK（私钥口令加密落盘，须离线保管）")
    ark.add_argument("--out", required=True, help="RK 密钥对输出目录")
    ark.add_argument("--passphrase-env", default="METACOG_ROOT_PASSPHRASE",
                     help="RK 私钥口令所在环境变量名（口令不进命令行）")
    arp = sub.add_parser("anchor-root-pub-install",
                         help="C-1 双密钥根信任：放置 RK 公钥到树外并钉固其指纹为最高权威（特权令牌门）")
    arp.add_argument("--pub", required=True, help="RK 公钥文件（anchor-root-keygen 产出）")
    arp.add_argument("--rotate-auth", metavar="FILE",
                     help="v2.27.33：RK 轮换授权文件（当前 RK 私钥对 root-rotate:<新指纹> 的签名，root_rotate_sign 产出）")
    arp.add_argument("--armed-recovery", action="store_true",
                     help="v2.27.33：显式声明曾武装恢复（钉固行缺失但 RK_pub/密封仍在时重装必需，LOUD）")

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
    if args.cmd not in ("init", "init-domain", "detect-domain", "anchor-attest-keygen") and not st.root.exists():
        print("错误: {} 不存在，先跑 `python metacog.py init`".format(st.root), file=sys.stderr)
        _hint_rc2()
        return 2
    # v2.27.24（C-1 阶段2/3）：受管控命令强制闸门——派发前先过非对称 attestation 层硬闸。
    # 未强制（双轨/off）→ 0 放行，现网行为不变；强制且层异常 → 非0 硬拒（命令不执行）。
    _gated = args.cmd in ATTEST_GATED_CMDS or (args.cmd == "confirm" and getattr(args, "sign", False))
    if _gated:
        _grc = _attest_gate(st)
        if _grc:
            if _grc == 2:
                _hint_rc2()
            return _grc
    rc = {
        "init": cmd_init, "episode": cmd_episode, "propose": cmd_propose,
        "gate": cmd_gate, "apply": cmd_apply, "verdict": cmd_verdict,
        "status": cmd_status, "retrieve": cmd_retrieve, "verify": cmd_verify,
        "rollback": cmd_rollback, "meta-log": cmd_meta_log, "confirm": cmd_confirm,
        "resign": cmd_resign,
        "init-domain": cmd_init_domain, "optimize": cmd_optimize,
        "detect-domain": cmd_detect_domain,
        "anchor-attest-keygen": cmd_anchor_attest_keygen,
        "anchor-attest-pubkey-install": cmd_anchor_attest_pubkey_install,
        "anchor-attest": cmd_anchor_attest,
        "anchor-attest-verify": cmd_anchor_attest_verify,
        "anchor-attest-root-seal": cmd_anchor_attest_root_seal,
        "anchor-root-keygen": cmd_anchor_root_keygen,
        "anchor-root-pub-install": cmd_anchor_root_pub_install,
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
