#!/usr/bin/env python3
"""
trust_root.py — v2.6.0 / v2.6.1 外部锚（破 C-1 循环论证）。

背景（C-1）：v2.5.8 的根信任由本系统自举——`check_pubkey_root()` 比对 human-guard.json
当前公钥指纹与 CONTRACT.md 钉固指纹。但二者同处可改写域；完全失控的管理员可同时重写
二者 + integrity.json 绕过全部机制。绝对层未闭合。

v2.6.0 破 C-1：引入外部不可伪造锚点，叠加 AND 门：① 保留 legacy RSA 验签；② 启用后额外
强制外部 attestation（A 设备证明）/ 带外确认（B）通过，否则 fail-closed。CONTRACT.md 指纹
降级为次要交叉核对。

v2.6.1 修复 Hermes 审计 3 项 HIGH：
- HIGH-1 / HIGH-2：删除模块级硬编码设备证明密钥；改为可插拔 KeyProvider（签名算法随后端走，
  测试用 SimKeyProvider、真机用 TokenKeyProvider 桩）。模块不再含任何可用密钥 → 读源码即签名的
  静态缺陷闭合。真机令牌支持仍需新增后端（TokenKeyProvider 当前为 NotImplemented 桩，启用即
  fail-closed，诚实地不可达，而非以「人工步骤」包装）。
- HIGH-3：配置损坏 / 未知 backend 不再静默降级 legacy，改返回恒拒实例（DenyTrustRoot），
  触发 fail-closed。区分「从未启用（legacy，返 None）」与「启用但损坏（恒拒）」。

v2.6.2 收口 Hermes 遗留 MEDIUM/LOW：symlink 防御扩至 attestation_path/oob_token_dir/tok
（_assert_real_path）；oob 令牌内容须等于 challenge + 确认后原子消费（防重放，challenge 绑
op+window）；DenyTrustRoot 按触发路径细分 reason；部署契约运行时检测+告警（跨平台权限语义
差异，默认 WARN-only 不 fail-closed）。

两种后端（KK 决 A+B 混合）：
- legacy : 默认/回退，无外部锚（行为 = v2.5.8）。
- hsm    : 设备证明后端（A）。根信任 = 离线根签名的设备证明文件，存于 Agent 无写权限目录。
- oob    : 人工带外 fail-closed（B）。每次关键签名须有独立信道**签名**确认令牌，缺则 fail-closed。
- hsm+oob: 二者叠加（离线根证明为主根 + 带外签名为恢复闸/二级锚）。

v2.7.0 外部锚权威**密码学层外部化**：引入**离线 RSA 根**——人类离线持 RSA 私钥，Agent 仅持
**公钥**验签。根证明文件与带外令牌均由离线私钥签名；Agent 不持有私钥 → 无法自造有效证明/令牌
（密码学层外部化，INV-3/INV-4 通过）。

**⚠️ 诚实边界（v2.7.1 重申）**：信任根配置（trust-root.json，含 root_pubkey）仍位于 Agent 可写域；
C-1 循环论证**未真正闭合**（v2.7.0 头条"逻辑层真正闭合"经 Hermes 2026-10-02 复验证伪已撤回，
见 HANDOFF ⑦）。v2.7.0 仅把"伪造证明/令牌"从密码学上排除（Agent 无私钥），但**信任锚本身**
（哪把 root_pubkey 受信）仍由同可写域的配置决定——攻击者凭 ledger 写权限即可换 root_pubkey +
自签证明。v2.7.1 补结构性 fail-closed 闸门（`anchor_storage_outside_root`：证明存储须位于 Agent
可写域 root 之外；metacog 侧已建外部锚的删除由 D4 快照检出 HIGH-1），残余"证明存储位于 root 之外
但 Agent 仍可写"仍需 OS 权限隔离（部署契约），诚实不声称默认部署下 C-1 已闭合。闭环 Hermes N1
（oob 令牌 RSA 签名不可伪造）保留。

**v2.8.0 C-1 软件层闭合**：v2.8.0 起 trust-root.json 经内嵌锚密钥 HMAC-SHA256 签名（见模块下方
get_anchor_key / sign_trust_root_config / verify_trust_root_config_sig），TrustRootConfig.load 强制
校验：无签名 / 签名不符 → fail-closed。锚密钥位于代码（非可写 ledger），攻击者凭 ledger 写权限无
密钥无法伪造签名 → "哪把 root_pubkey 受信"不再由可写配置单方面决定，C-1 在软件层闭合。残余边界：
攻击者同时具备代码写权限（代码完整性）→ 彻底隔离仍须 TPM / 独立只读介质（out-of-scope，部署契约兜底）。

纪律（HANDOFF §3/§5）：主 agent 不跑本地 .py；验证全交隔离 subagent。
真实部署注意：离线根私钥须由人类离线保管，**严禁**以任何形式写入 Agent 可写域（ledger/代码/
配置）；Agent 运行时仅持 root_pubkey 验签。硬件令牌（TokenKeyProvider，PKCS#11/TPM/WebAuthn）
作为代码完整的备用后端保留，真机未接入前 verify 恒 False → fail-closed（诚实不可达）。
"""

import base64
import datetime
import hashlib
import hmac
import json
import os
import secrets
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import sigcrypto  # 纯 stdlib 密码学原语（RSA 生成/签名/验签），用于 v2.7.0 离线根


# ---------------------------------------------------------------------------
# 可插拔密钥提供方（v2.6.1 HIGH-1/2：密钥不再硬编码于模块）
# ---------------------------------------------------------------------------

class KeyProvider(ABC):
    """设备证明签名/验签提供方。模块不持有任何硬编码密钥；密钥来源由子类注入。"""

    name = "abstract"

    @abstractmethod
    def sign(self, pub_serialized: str) -> bytes:
        """对公钥序列化签名，返回签名字节。"""

    @abstractmethod
    def verify(self, pub_serialized: str, sig: bytes) -> bool:
        """验签：签名是否由本提供方对 pub_serialized 签发。"""


class SimKeyProvider(KeyProvider):
    """【v2.7.0 弃用】测试用软件 HSM 模拟提供方：用注入的 secret 做 HMAC-SHA256。

    注意：secret 必须由调用方在构造时注入（来自配置/环境变量/测试），**绝不**硬编码于
    本模块源码。v2.7.0 起外部锚权威由**离线 RSA 根（RsaRootVerifierProvider）**承载，本类
    仅保留作向后引用与历史审计 artifact（hermes-verify-audit-*.py）兼容，不再被生产/新测试调用。"""

    name = "sim"

    def __init__(self, secret: bytes):
        if not isinstance(secret, (bytes, bytearray)):
            raise TypeError("SimKeyProvider secret 必须是 bytes")
        self._secret = bytes(secret)

    def sign(self, pub_serialized: str) -> bytes:
        return hmac.new(self._secret, pub_serialized.encode("utf-8"), "sha256").digest()

    def verify(self, pub_serialized: str, sig: bytes) -> bool:
        if not isinstance(sig, (bytes, bytearray)):
            return False
        expected = self.sign(pub_serialized)
        return hmac.compare_digest(expected, bytes(sig))


class TokenKeyProvider(KeyProvider):
    """真机硬件令牌提供方（桩）。v2.6.1 当前未实现真实后端。

    HIGH-2 诚实声明：本桩的 verify 恒返回 False（不可达），意味着在 TokenKeyProvider 真正
    实现前，hsm 后端在真机场景下**必然 fail-closed**。这不是「人工步骤」可补，而是需要新增
    后端（PKCS#11/TPM/WebAuthn 接入），属代码工作，非部署步骤。"""

    name = "token"

    def __init__(self, backend: str = "", token_pubkey: str = ""):
        self.backend = backend
        self.token_pubkey = token_pubkey

    def sign(self, pub_serialized: str) -> bytes:
        raise NotImplementedError(
            "TokenKeyProvider 未实现真实硬件令牌签名后端；请接入 PKCS#11/TPM/WebAuthn")

    def verify(self, pub_serialized: str, sig: bytes) -> bool:
        # 真机后端未实现前，任何签名均不可达 → fail-closed（诚实不可达，不静默放行）
        return False


# ---------------------------------------------------------------------------
# 离线 RSA 根（v2.7.0 破 C-1）：Agent 仅持公钥验签，私钥由人类离线持有
# ---------------------------------------------------------------------------

def _root_attestation_binding(committed_pubkey: str, contract_fingerprint: str, issued_at: str) -> bytes:
    """根证明规范绑定串：ROOT-ATTEST|<pubkey>|<contract_fp>|<issued_at>。
    签名覆盖「提交公钥 + 契约指纹 + 签发时间」，防 Agent 用合法证明套不同公钥/契约。"""
    return ("ROOT-ATTEST|" + committed_pubkey + "|" + contract_fingerprint + "|" + issued_at).encode("utf-8")


class RsaRootVerifierProvider(KeyProvider):
    """外部根验证方（密码学层外部化）。Agent 仅持 RSA **公钥** 验签；对应私钥由人类**离线持有**，
    永不进入 Agent 可写域（ledger/代码/配置）。Agent 无私钥 → 无法自造有效根证明/带外令牌
    （密码学层外部化，INV-3/INV-4 通过）。

    ⚠️ 诚实边界：root_pubkey 仍存于 Agent 可写域 trust-root.json，C-1 循环论证**未真正闭合**
    （v2.7.0"逻辑层真正闭合"经 Hermes 2026-10-02 复验证伪已撤回，见 HANDOFF ⑦）。v2.7.1 由
    `anchor_storage_outside_root` 结构性 fail-closed 闸门（证明存储须位于 Agent 可写域 root 之外）
    补强主攻击向量；残余"root 外但 Agent 仍可写"依赖 OS 权限隔离（部署契约）。

    sign() 显式 NotImplementedError：Agent 进程不具备签名能力，从机制上杜绝自造证明。
    verify() 验签规范绑定串（HsmTrustRoot 构造）或挑战串（OobTrustRoot 构造）。"""

    name = "rsa-root-verify"

    def __init__(self, pub_serialized: str):
        if not isinstance(pub_serialized, str) or not pub_serialized:
            raise ValueError("RsaRootVerifierProvider 需要非空 root_pubkey")
        # 非法公钥 → 抛；build_trust_root 捕获后返 DenyTrustRoot（fail-closed，不静默放行）
        self._pub = sigcrypto.deserialize_pub(pub_serialized)

    def sign(self, message: bytes) -> bytes:
        raise NotImplementedError("Agent 不持有离线根私钥，无法签名（防自造证明）")

    def verify(self, message: bytes, sig: bytes) -> bool:
        if not isinstance(message, (bytes, bytearray)) or not isinstance(sig, (bytes, bytearray)):
            return False
        try:
            return sigcrypto.verify(self._pub, bytes(message), bytes(sig))
        except Exception:
            return False


def gen_offline_root_keypair():
    """人类**离线**一次性生成根密钥对。返回 (pub_serialized, priv_serialized)。
    私钥须由人类离线保管，绝不以任何形式写入 Agent 可写域。本函数仅由人类 setup 调用，
    Agent 运行时绝不调用（Agent 仅持 pub_serialized 验签）。"""
    pub, priv = sigcrypto.gen_keypair(2048)
    return sigcrypto.serialize_pub(pub), sigcrypto.serialize_priv(priv)


def write_root_attestation(attestation_path: str, pub_serialized: str, contract_fingerprint: str,
                           priv_serialized: str, issued_by: str = "human-offline-root") -> None:
    """人类**离线**签名根证明文件（一次性 setup）。Agent 仅验签，不调用本函数。
    证明文件须置于 Agent 无写权限目录（部署契约）；内容 = 提交公钥 + 契约指纹 + 签发时间 + 签名。"""
    priv = sigcrypto.deserialize_priv(priv_serialized)
    issued_at = datetime.datetime.now().isoformat()
    binding = _root_attestation_binding(pub_serialized, contract_fingerprint, issued_at)
    sig = sigcrypto.sign(priv, binding)
    rec = {
        "committed_pubkey": pub_serialized,
        "contract_fingerprint": contract_fingerprint,
        "issued_at": issued_at,
        "issued_by": issued_by,
        "signature": base64.b64encode(sig).decode("ascii"),
    }
    Path(attestation_path).write_text(json.dumps(rec, indent=2), encoding="utf-8")


def sign_oob_token(challenge: str, priv_serialized: str) -> bytes:
    """人类**离线**对带外挑战签名（setup / 每次关键操作）。Agent 仅验签。
    令牌内容 = 挑战串的 RSA 签名 → 即使 oob_token_dir 可写，无离线私钥者无法伪造（闭环 N1）。"""
    priv = sigcrypto.deserialize_priv(priv_serialized)
    return sigcrypto.sign(priv, challenge.encode("utf-8"))


def _load_verifier(cfg) -> "RsaRootVerifierProvider | TokenKeyProvider | None":
    """按配置解析外部根验证方。优先 root_pubkey（离线 RSA 根，可测、逻辑破 C-1，Agent 仅验签）；
    否则若 token_backend 指定，用 TokenKeyProvider（真机，当前桩 verify 恒 False → fail-closed，
    诚实不可达）；否则 None（无法建立外部锚 → 下方按无 verifier fail-closed）。"""
    if getattr(cfg, "root_pubkey", ""):
        try:
            return RsaRootVerifierProvider(cfg.root_pubkey)
        except Exception as e:
            # 非法 root_pubkey（如非 JSON 形式）→ 无法验签 → 视为无 verifier（fail-closed）。
            # 但须显式暴露根因到 stderr，避免静默退化成 external-anchor-no-verifier 而无从排查
            # （H-3 真实副本实测：缺引号非 JSON 被存盘 → 静默 None → S7 在 enabled=True 表象下仍 BLOCK）。
            sys.stderr.write(
                "[trust_root] WARN: root_pubkey 非法（非合法 JSON 公钥），外部锚将 fail-closed"
                "（reason=external-anchor-no-verifier）。根因: {}\n".format(e))
            return None
    if getattr(cfg, "token_backend", ""):
        return TokenKeyProvider(cfg.token_backend, getattr(cfg, "token_pubkey", ""))
    return None


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# v2.8.0 C-1 闭合：信任根配置签名锚（软件层）
# ---------------------------------------------------------------------------
# C-1 根因：trust-root.json（含 root_pubkey）位于 Agent 可写域；"哪把 root_pubkey 受信"
# 由同可写域配置决定 → 循环论证。v2.8.0 起对该配置以内嵌锚密钥 HMAC-SHA256 签名，
# 加载时强制校验：无 _sig / _sig 不符 → load 返 corrupt → fail-closed（external-anchor-corrupt）。
# 锚密钥位于代码（非可写 ledger），攻击者凭 ledger 写权限无密钥无法伪造签名 → C-1 在软件层闭合。
# 残余边界：攻击者同时具备代码写权限（代码完整性）→ 彻底隔离须 TPM / 独立只读介质（out-of-scope）。
# 部署：默认内嵌锚；可用环境变量 METACOG_TRUST_ROOT_ANCHOR_KEY（base64，≥32 字节）覆盖为部署专属锚。
# 升级迁移：v2.8.0 前无签名旧配置加载即 fail-closed，须重新执行 --enable-external 落盘签名配置。

_TRUST_ROOT_ANCHOR_KEY_DEFAULT = bytes.fromhex(
    "9f2c4a7e3b1d8c6a5e0f9a2b7c4d1e8f3a6b5c0d9e2f1a4b7c0d3e6f9a2b5c8d")

def get_anchor_key() -> bytes:
    """v2.8.0：返回信任根签名锚密钥。优先环境变量（部署专属），否则内嵌默认锚。"""
    env = os.environ.get("METACOG_TRUST_ROOT_ANCHOR_KEY")
    if env:
        try:
            return base64.b64decode(env)
        except Exception:
            pass
    return _TRUST_ROOT_ANCHOR_KEY_DEFAULT

def _canonical_trust_root(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def sign_trust_root_config(payload: dict, key: bytes) -> str:
    """v2.8.0：对信任根配置载荷（不含 _sig）做 HMAC-SHA256 签名，返回 base64 串。"""
    canon = _canonical_trust_root(payload)
    return base64.b64encode(
        hmac.new(key, canon.encode("utf-8"), hashlib.sha256).digest()).decode("ascii")

def verify_trust_root_config_sig(d: dict, key: bytes) -> bool:
    """v2.8.0：校验 trust-root.json 的 _sig。无 _sig / 类型错 / 不符 → False（即 fail-closed）。"""
    sig = d.get("_sig")
    if not isinstance(sig, str):
        return False
    payload = {k: v for k, v in d.items() if k != "_sig"}
    expected = sign_trust_root_config(payload, key)
    try:
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


@dataclass
class TrustRootConfig:
    """外部锚配置（自 ledger/trust-root.json 读取；缺失 = legacy 模式）。"""
    backend: str = "legacy"           # legacy | hsm | oob | hsm+oob
    attestation_path: str = ""        # hsm：设备证明文件路径（Agent 无写权限目录）
    oob_token_dir: str = ""           # oob：带外确认令牌目录（Agent 无写权限目录）
    enabled: bool = False             # 外部锚总开关；False = 纯 legacy（行为不变）
    corrupt: bool = False             # v2.6.1 HIGH-3：配置文件存在但解析失败 → 启用态损坏
    sim_key: str = ""                 # 已弃用（v2.7.0）：sim 可伪造，离线根/真机取代之；保留字段兼容旧配置
    token_backend: str = ""           # 真机令牌后端标识（预留；v2.7.0 起作为备用后端，未接入前 verify 恒 False）
    root_pubkey: str = ""             # v2.7.0 离线 RSA 根：Agent 仅持公钥验签（私钥人类离线持有，严禁落盘）
    token_pubkey: str = ""            # 真机令牌公钥（预留，真机后端实现后填）

    @classmethod
    def load(cls, root: Path) -> "TrustRootConfig":
        p = root / "ledger" / "trust-root.json"
        sentinel = root / "ledger" / ".external-anchor-enabled"
        if not p.exists():
            # v2.6.3 M-1：配置缺失但启用标记仍在 → 视为启用态被篡改/删除，fail-closed
            # （防攻击者删 trust-root.json 静默关掉外部锚回退 legacy）；两者皆缺=从未启用
            if sentinel.exists():
                return cls(corrupt=True, enabled=True)
            return cls()  # 从未启用 → legacy，行为同 v2.5.8
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError, RecursionError):  # v2.6.4 ④ 收窄 + v2.6.5 补 RecursionError（病态超深嵌套 JSON 亦 fail-closed）
            # v2.6.1 HIGH-3：解析失败不再静默回落 legacy（可被攻击者写坏绕过），
            # 而是标记 corrupt → build_trust_root 返回恒拒实例（fail-closed）。
            return cls(corrupt=True, enabled=True)
        if not isinstance(d, dict):  # v2.6.4 ①：JSON 标量(null/[]/0/true)穿透会令 d.get 抛未捕获 AttributeError
            return cls(corrupt=True, enabled=True)
        # v2.8.0 C-1 闭合：信任根配置须带内嵌锚密钥签名；无签名/签名不符 → fail-closed
        # （防攻击者凭 ledger 写权限换 root_pubkey + 自签证明，闭合 C-1 循环论证）
        if not verify_trust_root_config_sig(d, get_anchor_key()):
            return cls(corrupt=True, enabled=True)
        return cls(
            backend=d.get("backend", "legacy"),
            attestation_path=d.get("attestation_path", ""),
            oob_token_dir=d.get("oob_token_dir", ""),
            enabled=(d.get("enabled") is True),  # v2.6.4 ②：杜绝字符串 "false" 被 bool() 强转 True
            corrupt=False,
            sim_key=d.get("sim_key", ""),
            token_backend=d.get("token_backend", ""),
            root_pubkey=d.get("root_pubkey", ""),
            token_pubkey=d.get("token_pubkey", ""),
        )


# ---------------------------------------------------------------------------
# 外部锚抽象
# ---------------------------------------------------------------------------

def _assert_real_path(p: str) -> bool:
    """N1 扩展（MEDIUM-1）+ N2（v2.7.0→v2.7.1）：路径须为真实文件/目录、非符号链接，否则返回 False。
    覆盖 v2.6.0 新引入的 attestation_path / oob_token_dir / tok，防 symlink 重放指向
    Agent 可控路径（与 _confirm_keygen 的 nonce_file 防护同哲学）。

    v2.7.1 N2：先判 is_symlink()（符号链接本身/父目录）→ 再 resolve() 归一到真实路径后判存在性，
    与 metacog._confirm_keygen 的 nonce_file 防护对齐（L2521/L2525）。resolve() 可兜住「中间目录为
    符号链接、仅查立即父漏判」的绕过（如 /a 为 symlink 但 /a/b 不是，parent.is_symlink() 漏判）。"""
    pp = Path(p)
    if pp.is_symlink():
        return False
    if pp.parent.is_symlink():
        return False
    try:
        rp = pp.resolve()
    except Exception:
        return False
    # 解析后若规范路径与原路径不一致（仅大小写/分隔符归一化除外），说明路径含符号链接重定向 → 不可信
    try:
        if os.path.normcase(str(rp)) != os.path.normcase(str(pp)):
            # Windows 大小写/分隔符归一化可能造成差异，用 realpath 二次确认确有重定向
            if os.path.realpath(str(pp)) != os.path.realpath(str(rp)):
                return False
    except Exception:
        pass
    return rp.exists()


class TrustRoot:
    """外部锚：根信任的「外部不可伪造」判定。legacy 模式为 no-op pass（行为不变）。"""

    name = "legacy"

    def attestation_ok(self, pub_serialized: str, contract_fingerprint: str = None) -> tuple:
        """根信任外部证明是否通过。返回 (ok, reason)。legacy 恒 (True, None)。
        contract_fingerprint 为 v2.7.0 可选交叉核对参数（hsm 设备证明绑定契约指纹）；
        legacy/oob 无需证明，忽略该参数，使 check_pubkey_root 可统一传递。"""
        return True, None

    def oob_token_required(self) -> bool:
        return False

    def oob_confirmed(self, challenge: str) -> bool:
        return True

    def challenge_for(self, pub_serialized: str, op: str = "verify",
                      window: str = None) -> str:
        # LOW-1：challenge 绑定操作类型 + 时间窗，避免同一公钥下所有操作共享同挑战长期有效
        if window is None:
            window = datetime.date.today().isoformat()
        return hashlib.sha256(
            ("oob|" + op + "|" + window + "|" + pub_serialized).encode("utf-8")
        ).hexdigest()[:16]


class DenyTrustRoot(TrustRoot):
    """v2.6.1 HIGH-3：恒拒实例。配置损坏/未知 backend / 无可用 key_provider 时返回，强制
    fail-closed。与 legacy（no-op pass）语义相反：此处任何证明/令牌都拒绝，使「启用但损坏」
    的外部锚绝不静默回落到 C-1 未闭合的弱姿态。

    v2.6.2（LOW 细分）：构造接收 reason，区分触发路径便于运维与审计追踪。"""

    name = "deny"

    def __init__(self, reason: str = "external-anchor-disabled"):
        self.reason = reason

    def attestation_ok(self, pub_serialized: str, contract_fingerprint: str = None) -> tuple:
        return False, self.reason

    def oob_token_required(self) -> bool:
        # v2.6.3 H-1：外部锚禁用时本就不应要求 OOB（LSP 修正）；配合 check_pubkey_root
        # 的 DenyTrustRoot 透传守卫，细分 reason 不再被 oob 分支吞掉
        return False

    def oob_confirmed(self, challenge: str, expected_content: str = None) -> bool:
        return False

    def challenge_for(self, pub_serialized: str, op: str = "verify",
                      window: str = None) -> str:
        return "denied"


class HsmTrustRoot(TrustRoot):
    """A 类：设备证明后端。根信任 = **离线根签名**的设备证明文件（Agent 无写权限目录）。
    v2.7.0：证明文件由离线根私钥签名、Agent 仅持公钥验签 → 无法自造（真正破 C-1）。
    文件须绑定「提交公钥 + 契约指纹」；提交公钥须等于当前 live 公钥（防 Agent 换公钥套证明）。"""

    name = "hsm"

    def __init__(self, attestation_path: str, verifier: "RsaRootVerifierProvider"):
        self.attestation_path = attestation_path
        self.verifier = verifier

    def attestation_ok(self, pub_serialized: str, contract_fingerprint: str = None) -> tuple:
        ap = self.attestation_path
        if not ap or not os.path.isfile(ap):
            # 无证明文件 = 根信任无法外部锚定 → fail-closed（管理员可重写 human-guard
            # + CONTRACT.md，但造不出离线根私钥签名的设备证明）。
            return False, "no-device-attestation"
        # v2.6.2（MEDIUM-1）：attestation_path 须为真实文件、非 symlink（防指向 Agent 可控路径）
        if not _assert_real_path(ap):
            return False, "attestation-symlink"
        # v2.6.6 + v2.7.0：整个解析/解码/验签体统一纳入 try——损坏输入一律 fail-closed
        try:
            rec = json.loads(Path(ap).read_text(encoding="utf-8"))
            if not isinstance(rec, dict):
                return False, "attestation-malformed"
            committed = rec.get("committed_pubkey")
            if committed != pub_serialized:
                # 提交公钥 ≠ 当前 live 公钥 → 拒绝（防 Agent 换公钥套用他人/旧证明）
                return False, "attestation-pubkey-mismatch"
            cf = rec.get("contract_fingerprint")
            if contract_fingerprint is not None and cf != contract_fingerprint:
                return False, "attestation-contract-mismatch"
            sig = base64.b64decode(rec.get("signature", "")) if rec.get("signature") else b""
            if not self.verifier.verify(
                    _root_attestation_binding(committed, str(cf), str(rec.get("issued_at", ""))), sig):
                return False, "attestation-forged"
            return True, None
        except Exception:
            return False, "attestation-malformed"


class OobTrustRoot(TrustRoot):
    """B 类：人工带外 fail-closed。每次关键签名须有独立信道的**签名**确认令牌。
    v2.7.0（闭环 N1）：令牌内容 = 挑战串的 RSA 签名（离线根私钥）；Agent 仅验签 → 即使
    oob_token_dir 可写，无离线私钥者无法伪造令牌。保留 symlink 防御 + 一次性消费防重放。"""

    name = "oob"

    def __init__(self, oob_token_dir: str, verifier: "RsaRootVerifierProvider"):
        self.oob_token_dir = oob_token_dir
        self.verifier = verifier

    def oob_token_required(self) -> bool:
        return True

    def oob_confirmed(self, challenge: str) -> bool:
        # MEDIUM-1：目录级 + 文件级 symlink 防御
        if not self.oob_token_dir or not _assert_real_path(self.oob_token_dir):
            return False  # 未配置/ symlink / 不存在 → fail-closed
        tok = os.path.join(self.oob_token_dir, challenge + ".token")
        if not _assert_real_path(tok):
            return False
        try:
            content = Path(tok).read_text(encoding="utf-8").strip()
            sig = base64.b64decode(content)
        except Exception:
            return False  # 内容非合法 base64 / 读取失败 → fail-closed（N1 闭环：无密钥无法造合法签名）
        # 令牌须为挑战串的合法 RSA 签名（离线根私钥签发）→ 无密钥者即便可写目录也无法伪造
        if not self.verifier.verify(challenge.encode("utf-8"), sig):
            return False
        # 一次性消费：确认后原子 rename 为 .used，防重放（同一挑战不可二次使用）
        try:
            os.replace(tok, tok + ".used")
        except OSError:
            return False
        return True


class HsmOobTrustRoot(HsmTrustRoot, OobTrustRoot):
    """A+B 混合：离线根设备证明为主根 + 带外签名为恢复闸/二级锚。"""

    name = "hsm+oob"

    def __init__(self, attestation_path: str, oob_token_dir: str, verifier: "RsaRootVerifierProvider"):
        HsmTrustRoot.__init__(self, attestation_path, verifier)
        OobTrustRoot.__init__(self, oob_token_dir, verifier)


def _is_protected(p: str) -> "bool | None":
    """P2 部署契约运行时检查（检测用，best-effort **WARN-only**，非 fail-closed 主闸）。

    返回 True=路径受保护（真实、非 symlink、当前进程无写权限）；False=可写（契约违反）；
    None=路径不存在（由 attestation_ok 另行 fail-closed）。

    v2.7.1 设计说明（诚实）：本 OS 权限检查**保留 WARN-only**，不升级为硬 fail-closed——
    原因：(1) 跨平台权限语义差异大（尤其 Windows 目录 readonly 属性不阻止写入、os.access W_OK
    对目录不可靠），升级为 fail-closed 会误杀合法部署且无法在 Windows 稳定生效；(2) 真正可靠的
    fail-closed 主闸是结构性闸门 `anchor_storage_outside_root`（证明存储须位于 Agent 可写域 root
    之外，跨平台确定）+ metacog 侧 D4 快照对「已建立外部锚被删」的检出（HIGH-1）。二者叠加即
    阻断 C-1 主攻击向量；残余「root 外但 Agent 仍可写」仍依赖 OS 权限隔离（部署契约）。"""
    pp = Path(p)
    if pp.is_symlink():
        # symlink 不论目标是否存在都判"不受保护"（False）；放在 exists() 之前，
        # 否则断链 symlink 会先被 exists() 短路成 None 而漏判。
        return False
    if not pp.exists():
        return None
    for t in (pp, pp.parent):
        try:
            if os.access(str(t), os.W_OK):
                return False
        except Exception:
            pass
    return True


def _deploy_warn(p: str) -> bool:
    """P2 部署契约检查（v2.25.1 #1 L3 升级为可 fail-closed 的 opt-in 严格模式）。

    返回 True=违反契约（路径对当前进程可写，外部锚不可伪造性不闭环）；False=通过/未判定（不阻断）。
    - 默认（未设 METACOG_REQUIRE_PROTECTED_ANCHOR）：仅 WARN（WARN-only，不 fail-closed），返回 False。
    - 严格模式（METACOG_REQUIRE_PROTECTED_ANCHOR=1）：违反即返回 True，由 build_trust_root 转
      DenyTrustRoot("external-anchor-path-writable")（fail-closed 拒启外锚）。
    理由见 _is_protected：跨平台权限语义差异大（尤其 Windows 目录 os.access W_OK 不可靠），故默认 WARN、
    严格模式 opt-in，避免误杀合法部署；已完成 OS 隔离（L1 身份分离 + L2 ACL 收窄）的部署可开启严格模式闭环 C-1。"""
    prot = _is_protected(p)
    if prot is False:
        if os.environ.get("METACOG_REQUIRE_PROTECTED_ANCHOR", "").lower() == "1":
            return True
        sys.stderr.write(
            "[trust_root] WARN: 外部锚路径 {} 当前进程可写（部署契约违反：该路径须 Agent 无"
            "写权限）。外部锚不可伪造性依赖此契约；请改为受保护路径，否则外部锚失效。\n".format(p))
    return False


def build_trust_root(cfg: TrustRootConfig):
    """按配置构建外部锚（v2.7.0：外部锚权威来自离线 RSA 根 / 真机令牌，Agent 仅验签）。

    - corrupt=True（配置损坏）→ 恒拒实例（fail-closed，reason=external-anchor-corrupt），**不再**回落 legacy。
    - enabled=False / backend=legacy → 返回 None（legacy 分支，行为同 v2.5.8）。
    - 未知 backend（且 enabled）→ 恒拒实例（fail-closed，reason=external-anchor-unknown-backend）。
    - oob：须有 verifier（root_pubkey 或真机）；无 verifier → 令牌无密码学绑定（N1 可伪造）→ 拒。
    - hsm / hsm+oob：须有 verifier；无 verifier（既无 root_pubkey 也无真机）→ 拒。
      v2.7.0：离线根使独立 hsm 成为真外部锚（离线私钥签名的设备证明，Agent 不可伪造），
      故独立 hsm + root_pubkey 合法放行（v2.6.x 因 sim 密钥可伪造才须 hsm+oob）。hsm+oob 仍为最强姿态。
    - v2.6.2（LOW）：DenyTrustRoot 按触发路径细分 reason，便于运维区分。
    """
    if cfg.corrupt:
        return DenyTrustRoot("external-anchor-corrupt")
    if not cfg.enabled or cfg.backend == "legacy":
        # v2.8.2 C-11 硬化（默认 fail-closed）：未启用外部锚（legacy）视为安全配置缺失 →
        # 默认 DenyTrustRoot（拒绝启动，强制外部锚成为部署必需项）。向后兼容逃生舱：
        # 仅当显式 METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1（严格等于字符串 "1"）才回落 legacy（返回 None）。
        # 设计演进：v2.8.1 为 opt-in（METACOG_REQUIRE_EXTERNAL_ANCHOR=1 才 deny）；v2.8.2 翻转为默认 deny。
        # 严格 == "1" 判定（Hermes v2.8.2 高-1 修复）：避免 truthy 误判——`=0`/`false`/`no`/`off` 等
        # 非空字符串在 truthy 语义下会错误解除强制力；仅 "1" 才回落 legacy，其余（含未设置）一律 deny。
        if os.environ.get("METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR", "").lower() == "1":
            return None
        return DenyTrustRoot("external-anchor-required")
    if cfg.backend == "oob":
        verifier = _load_verifier(cfg)
        if verifier is None:
            # oob 无 verifier → 令牌无密码学绑定（N1）→ 可伪造 → 拒（fail-closed）
            return DenyTrustRoot("external-anchor-oob-no-verifier")
        if _deploy_warn(cfg.oob_token_dir):
            return DenyTrustRoot("external-anchor-path-writable")
        return OobTrustRoot(cfg.oob_token_dir, verifier)
    if cfg.backend in ("hsm", "hsm+oob"):
        verifier = _load_verifier(cfg)
        if verifier is None:
            # 无 root_pubkey 且无真机后端 → 无法建立外部锚 → fail-closed
            return DenyTrustRoot("external-anchor-no-verifier")
        # v2.7.0：离线根使独立 hsm 成为真外部锚（设备证明由离线私钥签名，Agent 不可伪造），
        # 不再拒绝独立 hsm（v2.6.x 因 sim 密钥可伪造才须 hsm+oob）。hsm+oob 仍为最强姿态。
        if _deploy_warn(cfg.attestation_path):
            return DenyTrustRoot("external-anchor-path-writable")
        if cfg.backend == "hsm":
            return HsmTrustRoot(cfg.attestation_path, verifier)
        if _deploy_warn(cfg.oob_token_dir):
            return DenyTrustRoot("external-anchor-path-writable")
        return HsmOobTrustRoot(cfg.attestation_path, cfg.oob_token_dir, verifier)
    # 未知 backend → 恒拒（fail-closed，不静默放行未知模式）
    return DenyTrustRoot("external-anchor-unknown-backend")


def _anchor_paths(cfg) -> "list[str]":
    """v2.7.1：返回外部锚证明存储路径清单（须 fail-closed 闸门覆盖）。"""
    paths = []
    backend = getattr(cfg, "backend", "legacy")
    if backend in ("hsm", "hsm+oob") and getattr(cfg, "attestation_path", ""):
        paths.append(cfg.attestation_path)
    if backend in ("oob", "hsm+oob") and getattr(cfg, "oob_token_dir", ""):
        paths.append(cfg.oob_token_dir)
    return paths


def anchor_storage_outside_root(cfg, root: Path) -> "str | None":
    """v2.7.1 fail-closed 结构性闸门（跨平台可靠，不依赖 OS 权限语义）。

    返回 None=通过；否则返回失败 reason（供 DenyTrustRoot）。

    C-1 根因：信任根配置(trust-root.json 含 root_pubkey)位于 Agent 可写域；若证明存储
    (attestation_path/oob_token_dir)也可写，攻击者可在可写域内「换 root_pubkey + 自签证明/令牌」
    → 外部锚失效（Hermes 2026-10-02 复验证伪 v2.7.0"逻辑层闭合"）。

    本闸门要求证明存储必须位于 Agent 可写工作域(root)之外。攻击者只能把证明存储指向可写域内路径
    → 此处 fail-closed 拒绝，阻断主攻击向量。残余「证明存储位于 root 外但 Agent 仍可写」须由 OS
    权限隔离（部署契约：attestation_path/oob_token_dir 置于 Agent 无写权限目录）兜底；本软件层
    不声称默认部署下 C-1 已闭合（诚实边界，见 HANDOFF ⑦）。"""
    if not getattr(cfg, "enabled", False) or getattr(cfg, "backend", "legacy") == "legacy":
        return None
    try:
        root_resolved = Path(root).resolve()
    except Exception:
        return None
    for p in _anchor_paths(cfg):
        if not p:
            continue
        try:
            rp = Path(p).resolve()
        except Exception:
            # 无法解析（路径不存在等）→ 交由 attestation_ok / oob_confirmed 的 exists 检查 fail-closed
            continue
        try:
            if rp.is_relative_to(root_resolved):
                return "external-anchor-inside-writable-root"
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# 配置写入辅助（供 confirm --keygen 在 TTY 人类在场时落盘）
# ---------------------------------------------------------------------------

def _restrict_credential(path: Path) -> None:
    """尽最大努力把凭据文件收窄到属主（防御纵深，非主控制）。
    POSIX：chmod 0o600（真生效）。
    Windows：os.chmod 不按 Unix 八进制改 ACL，0o600 是空操作；改剥掉属主写位（0o400）
    → 置 FILE_ATTRIBUTE_READONLY（Windows 实际生效），文件抗 naive 覆盖/删除。
    注意：这仅是防御纵深——对"能写 ledger 目录"的攻击者为 moot（其可改回 ACL），
    且坚定的同用户攻击者也能清除只读位；主控制仍是部署契约（attestation_path /
    oob_token_dir 非 Agent 可写）。"""
    if os.name == "posix":
        try:
            os.chmod(str(path), 0o600)
        except OSError:
            pass
    else:
        try:
            os.chmod(str(path), 0o400)  # 剥属主写位 → 只读（Windows 生效）
        except OSError:
            pass


class TrustRootWriteError(Exception):
    """v2.8.1 C-9：以默认（源码内嵌共享）锚密钥启用外部锚被拒。"""


def write_trust_root_config(root: Path, backend: str, attestation_path: str = "",
                            oob_token_dir: str = "", root_pubkey: str = "") -> None:
    """启用外部锚（人类在 TTY 在场时执行）。写入 ledger/trust-root.json。
    v2.7.0：root_pubkey 为离线 RSA 根公钥（私钥人类离线持有，严禁落盘）；sim_key 已弃用。"""
    # v2.8.1 C-9 硬化：默认（源码内嵌、随代码分发的共享）锚密钥不得用于启用外部锚。
    # 该密钥任何可读代码者均可提取并伪造签名（C-9：源码明文 → 读即伪造）；生产/非本地部署
    # 须以 METACOG_TRUST_ROOT_ANCHOR_KEY 设为专属随机密钥。本地开发可显式
    # METACOG_TRUST_ROOT_ALLOW_DEFAULT=1 承担风险。
    if (get_anchor_key() == _TRUST_ROOT_ANCHOR_KEY_DEFAULT
            and not os.environ.get("METACOG_TRUST_ROOT_ALLOW_DEFAULT")):
        raise TrustRootWriteError(
            "拒绝以默认（源码内嵌共享）锚密钥启用外部锚：该密钥随代码分发，可读代码者即可伪造签名。\n"
            "生产/非本地部署须设置环境变量 METACOG_TRUST_ROOT_ANCHOR_KEY 为专属随机密钥；\n"
            "本地开发须显式设置 METACOG_TRUST_ROOT_ALLOW_DEFAULT=1 以承担风险。")
    # v2.25.1 #2 硬化（root_pubkey JSON 容错）：落盘前校验 root_pubkey 为合法可反序列化公钥；
    # 非法（如非 JSON 形式 {n:...,e:65537}）→ 直接 fail-closed 拒写，杜绝损坏值被持久化后
    # 静默退化为 external-anchor-no-verifier（见 H-3 真实副本 no-verifier 实测）。
    if root_pubkey:
        try:
            sigcrypto.deserialize_pub(root_pubkey)
        except Exception as e:
            raise TrustRootWriteError(
                "拒绝写入：root_pubkey 不是合法公钥（须为 JSON 形式的 RSA 公钥，"
                '如 {"n":"...","e":65537}）。根因：' + str(e) + "。\n"
                "外部锚未启用，trust-root.json 未改动。")
    ledger = root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)  # v2.6.4 ③：确保目录存在，避免写失败
    json_path = ledger / "trust-root.json"
    sentinel_path = ledger / ".external-anchor-enabled"
    # v2.6.5：若先前运行留下了 Windows 只读位，先清除以便覆盖（否则 os.replace 失败）
    for _f in (json_path, sentinel_path):
        if _f.exists():
            try:
                os.chmod(str(_f), 0o600)  # 恢复写位（Windows 清只读；POSIX 无副作用）
            except OSError:
                pass
    d = {
        "enabled": True,
        "backend": backend,
        "attestation_path": attestation_path,
        "oob_token_dir": oob_token_dir,
        "root_pubkey": root_pubkey,
        "token_backend": "",
        "token_pubkey": "",
        "updated_at": datetime.datetime.now().isoformat(),
    }
    # v2.6.4 ③：先写启用标记 sentinel，再原子写 json（temp + 同盘 rename）。
    # 顺序保证「启用 ⇔ sentinel」：若 json 写入中断，sentinel 在+json 缺→load fail-closed（安全方向）；
    # 若 json 原子落盘，sentinel 早已存在，删 json(留 sentinel) 仍触发 fail-closed（M-1）。
    sentinel_path.write_text(
        json.dumps({"backend": backend, "updated_at": datetime.datetime.now().isoformat()}),
        encoding="utf-8")
    tmp = ledger / ".trust-root.json.tmp"
    # v2.8.0 C-1 闭合：对配置载荷签名（锚密钥位于代码，非可写 ledger），加载时校验防换 root_pubkey
    signed_cfg = dict(d)
    signed_cfg["_sig"] = sign_trust_root_config(d, get_anchor_key())
    tmp.write_text(json.dumps(signed_cfg, indent=2), encoding="utf-8")
    os.replace(tmp, json_path)  # 同盘原子 rename，杜绝半截 json 被当合法配置
    # v2.6.5：收窄凭据文件权限（POSIX 0o600 / Windows 剥写位置只读，防御纵深）
    _restrict_credential(json_path)
    _restrict_credential(sentinel_path)


def write_device_attestation(attestation_path: str, pub_serialized: str,
                             key_provider: KeyProvider) -> None:
    """【已弃用 v2.7.0】保留仅作向后引用占位；设备证明改由人类离线 `write_root_attestation`
    （离线根私钥签名）生成。本函数不再被生产/测试路径调用。"""
    raise NotImplementedError(
        "write_device_attestation 已弃用；请改用 write_root_attestation（离线根私钥签名）")


# ---------------------------------------------------------------------------
# 自检（python3 trust_root.py）
# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("=== trust_root 自检 (v2.6.1) ===")
    pub = '{"n":"SIM_PUB","e":65537}'
    # legacy：恒 pass
    assert TrustRoot().attestation_ok(pub) == (True, None)
    assert TrustRoot().oob_confirmed("x") is True
    print("  legacy no-op OK")

    import tempfile
    import shutil
    # 离线 RSA 根：人类离线持私钥，Agent 仅持公钥验签（破 C-1）
    pub_off, priv_off = gen_offline_root_keypair()
    verifier = RsaRootVerifierProvider(pub_off)
    td = tempfile.mkdtemp()
    try:
        # hsm：无证明文件 → fail-closed
        att = os.path.join(td, "attest.json")
        hsm = HsmTrustRoot(att, verifier)
        assert hsm.attestation_ok(pub) == (False, "no-device-attestation")
        # 伪造（提交公钥不符）→ 拒绝
        write_root_attestation(att, "WRONG", "cf", priv_off)
        assert hsm.attestation_ok(pub) == (False, "attestation-pubkey-mismatch")
        # 合法证明（离线私钥签名）→ 通过
        write_root_attestation(att, pub, "cf", priv_off)
        assert hsm.attestation_ok(pub, contract_fingerprint="cf") == (True, None)
        # 用不同私钥伪造签名 → 拒绝（Agent 无私钥无法自造有效证明）
        _, priv_other = gen_offline_root_keypair()
        write_root_attestation(att, pub, "cf", priv_other)
        assert hsm.attestation_ok(pub, contract_fingerprint="cf") == (False, "attestation-forged")
        print("  hsm offline-root attestation OK")

        # oob：缺令牌 → fail-closed；放签名令牌 → 通过；无密钥伪造令牌 → 仍 fail-closed（N1 闭环）
        oobd = os.path.join(td, "oob")
        os.makedirs(oobd, exist_ok=True)
        oob = OobTrustRoot(oobd, verifier)
        ch = oob.challenge_for(pub)
        assert oob.oob_token_required() is True
        assert oob.oob_confirmed(ch) is False
        sig = sign_oob_token(ch, priv_off)
        Path(os.path.join(oobd, ch + ".token")).write_text(base64.b64encode(sig).decode("ascii"), encoding="utf-8")
        assert oob.oob_confirmed(ch) is True
        # N1 闭环：攻击者无私钥，放无签名/错签名令牌 → fail-closed
        ch2 = oob.challenge_for(pub)
        Path(os.path.join(oobd, ch2 + ".token")).write_text(ch2, encoding="utf-8")  # 无签名
        assert oob.oob_confirmed(ch2) is False
        print("  oob signed-token fail-closed OK")

        # TokenKeyProvider 桩：verify 恒 False → 真机不可用（HIGH-2 诚实）
        tk = TokenKeyProvider()
        assert tk.verify(pub, b"anything") is False
        try:
            tk.sign(pub)
            assert False, "TokenKeyProvider.sign 应 NotImplementedError"
        except NotImplementedError:
            pass
        print("  token stub fail-closed OK")

        # 工厂：v2.8.2 起默认 fail-closed（legacy 不再返回 None，须显式 opt-out 才回落 None）；corrupt → Deny；未知 backend → Deny
        assert build_trust_root(TrustRootConfig()).name == "deny"
        # 显式 opt-out（METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR=1）才回落 legacy None（向后兼容逃生舱）
        os.environ["METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"] = "1"
        assert build_trust_root(TrustRootConfig()) is None
        del os.environ["METACOG_ALLOW_LEGACY_NO_EXTERNAL_ANCHOR"]
        # hsm + root_pubkey → 合法离线根姿态（genuine break）；重置 att 为合法证明（上一步残留 forged）
        write_root_attestation(att, pub, "cf", priv_off)
        cfg_root = TrustRootConfig(enabled=True, backend="hsm", attestation_path=att, root_pubkey=pub_off)
        assert build_trust_root(cfg_root).attestation_ok(pub, contract_fingerprint="cf") == (True, None)
        # hsm 启用但无 verifier（无 root_pubkey 无真机）→ deny（fail-closed）
        dn = TrustRootConfig(enabled=True, backend="hsm", attestation_path=att)
        assert build_trust_root(dn).name == "deny"
        # oob 无 verifier → deny（N1：无密钥令牌可伪造）
        do = TrustRootConfig(enabled=True, backend="oob", oob_token_dir=oobd)
        assert build_trust_root(do).name == "deny"
        # corrupt
        dc = TrustRootConfig(corrupt=True, enabled=True, backend="hsm")
        assert build_trust_root(dc).name == "deny"
        # 未知 backend
        du = TrustRootConfig(enabled=True, backend="weird")
        assert build_trust_root(du).name == "deny"
        print("  工厂 + DenyTrustRoot OK")
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print("=== 全部通过 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
