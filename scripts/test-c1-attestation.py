# test-c1-attestation.py — C-1 非对称信任根 · v2.27.35 双密钥根信任回归
#
# 模块说明（v2.27.33，回应 DSH 审计 §2.6「测试诚实性」；v2.27.34 增 R3-1）：
# 本文件验证 v2.27.32/33/34 对生态外独立审计发现（v2.27.30-C1-R1 §10、v2.27.32-C1-R2、v2.27.33 R3-1）的承重项：
#   - 双密钥根信任（R-1）：根锚密封由 **RK 私钥**签名、经 RK_pub 验签；无 RK 私钥无法产出合法密封。
#   - v2.27.33 §2.3 收口「曾武装 fail-closed」：删 RK 钉固行 / 删树外 RK_pub 文件后，
#     **不仅 verify 报 rc=1，且受控闸门（propose/apply）必须实际被拒（rc≠0）、retrieve 拒绝吐规则
#     （rc=3）**——v2.27.32 版只断言 verify 的报告 rc、未断言闸门（被审计证伪的缺口，本版补上）。
#   - v2.27.33 §2.5 N-2 收口：RK 重装幂等（同一把 rc=0）、换 RK 无授权硬拒且不 clobber RK_pub 文件、
#     --rotate-auth（当前 RK 私钥签名）授权轮换、--armed-recovery 显式恢复路径。
#   - v2.27.33 §2.1 收口：ledger-drift——冻结账本与实际文件失配 → verify/gate fail-closed
#     （修复「commitment 只覆盖 ledger 文件、账本 stale 即代码层认证断裂」且审计人无锚密钥可复算）。
#   - v2.27.33 §2.5 N-1/N-3：MAX_AGE_DAYS 只许调短（>90 钳回 90）；未来时间戳（密封/attestation）拒收。
#   - v2.27.34 R3-1 收口（DSH §3）：_root_ever_armed 纳入 AK 层（.attest-pub.txt/.attest.json）。
#     攻击向量 = 删 RK 侧三处痕迹（钉固行+RK_pub+attest-root）但 AK 层保留 → v2.27.33 判 ever-armed=False
#     → 闸门 off → 可重建链；v2.27.34 因 AK 仍在 → ever-armed=True → 仍 fail-closed（见
#     test_attack_delete_rk_traces_keep_ak_fail_closed）。诚实残余：四删全清（含 AK）退化为 fresh install，
#     由带外指纹核对兜底，已在 CHANGELOG v2.27.34 登记。
#   - 诚实残余（结构性，非本文件可消除）：同用户全写权攻击者在显式 --armed-recovery 下仍可重建
#     自洽信任链（测试 test_attack_rebuild_chain 如实演示）——真正护栏 = RK 私钥离线 +
#     消费者侧带外指纹核对（见 references/asymmetric-trust-root-design.md）。
#
# 断言规模：16 组测试（含 R3-1 三删保留 AK fail-closed）/ 每组 2~8 条 r.add 断言
# （v2.27.33 实跑 15 组/63 断言；v2.27.32 为 10 组/29 断言；v2.27.30 前身 88 断言中
# 与 C-1 闸门无关的部分已迁回 test-trust-root.py 等套件，删减理由见 CHANGELOG v2.27.32/33/34）。
#
# 运行：python test-c1-attestation.py  （须先 cd scripts/）
import io
import contextlib
import json
import os as _os
import shutil
import sys
import tempfile
from pathlib import Path

import metacog
import sigcrypto

# 重定向树外 attestation 目录（必须在任何 CLI 调用前）
metacog.ATTEST_ANCHOR_DIR = Path(tempfile.mkdtemp(prefix="c1_attest_tree_"))

TEST_PASSPHRASE = "test-passphrase-32-bytes-minimum!!!"
TOKEN = "ceremony-token-2026"  # 单用户同权下自设（测试仅验证门逻辑，非模拟攻击者）


class T:
    def __init__(self, name):
        self.name = name
        self.passed = 0
        self.failed = 0

    def add(self, name, ok, detail=""):
        self.passed += ok
        self.failed += (not ok)
        print("  [{}] {}{}".format("PASS" if ok else "FAIL", name,
                                   (" - " + detail) if detail else ""))

    def summary(self):
        print("\n  -- {}: {}/{} PASS".format(self.name, self.passed, self.passed + self.failed))
        return self.failed == 0


def _run(argv):
    """跑 metacog.main，捕获 stdout，返回 (rc, output)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = metacog.main(argv)
    return rc, buf.getvalue()


def _mk_store():
    """沙盒 Store：唯一名 root + 空 ledger 三文件（integrity.json 有内容，其余空文件）。"""
    tmp = Path(tempfile.mkdtemp(prefix="c1_store_"))
    root = tmp / "c1-attest-store"
    (root / "ledger").mkdir(parents=True)
    (root / "ledger" / "integrity.json").write_text('{"scripts": {}, "manifest": {}}', encoding="utf-8")
    (root / "ledger" / "applies.jsonl").write_text("", encoding="utf-8")
    (root / "ledger" / "sig-claims.jsonl").write_text("", encoding="utf-8")
    return tmp, root


def _attest_paths(root):
    # v2.27.35（R2-N-5）：锚文件名走模块 slug（目录名--路径哈希），不再硬编码纯目录名
    _slug = metacog._attest_slug(metacog.Store(root))
    return (metacog.ATTEST_ANCHOR_DIR / (_slug + ".attest-pub.txt"),
            metacog.ATTEST_ANCHOR_DIR / (_slug + ".attest.json"))


def _seal_path(root):
    return metacog.ATTEST_ANCHOR_DIR / (metacog._attest_slug(metacog.Store(root)) + ".attest-root.txt")


def _root_pub_path(root):
    return metacog.ATTEST_ANCHOR_DIR / (metacog._attest_slug(metacog.Store(root)) + ".root-pub.txt")


def _reset_anchor_dir():
    """强制清空树外 attestation 目录（含 Windows 只读文件）。"""
    import stat as _stat
    d = metacog.ATTEST_ANCHOR_DIR
    if d.exists():
        for _child in d.iterdir():
            try:
                _child.chmod(_stat.S_IWRITE)
            except Exception:
                pass
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)


def _force_write(path, content):
    """解除只读后写入（树外文件经 _write_readonly 落只读属性）。"""
    import stat as _stat
    p = Path(path)
    try:
        p.chmod(_stat.S_IWRITE)
    except Exception:
        pass
    p.write_text(content, encoding="utf-8")


def _force_unlink(path):
    import stat as _stat
    p = Path(path)
    try:
        p.chmod(_stat.S_IWRITE)
    except Exception:
        pass
    p.unlink(missing_ok=True)


def _overwrite_seal(root, content):
    _force_write(_seal_path(root), content)


def _set_token():
    _os.environ["METACOG_ATTEST_PUBKEY_TOKEN"] = TOKEN
    _os.environ["METACOG_ATTEST_PUBKEY_TOKEN_EXPECTED"] = TOKEN


def _load_priv(enc_path, passphrase=TEST_PASSPHRASE):
    return sigcrypto.deserialize_priv(
        sigcrypto.decrypt_priv_str(json.loads(Path(enc_path).read_text()), passphrase))


def _full_ceremony(tmp, root):
    """v2.27.32/33 双密钥完整布建仪式：RK 生成+安装钉固 → AK 生成+安装钉固 → attest 签发 → RK 密封。
    幂等：密钥文件已存在则复用（不重复 keygen——否则新钥与既有钉固失配），仅重跑安装+签发。
    返回 (rk_dir, ak_dir)。"""
    _os.environ["RK_PASS"] = TEST_PASSPHRASE
    _os.environ["AK_PASS"] = TEST_PASSPHRASE
    _set_token()
    rk_dir = tmp / "rk"
    ak_dir = tmp / "ak"
    if not (rk_dir / "root-pub.pem").exists():
        _run(["--root", str(root), "anchor-root-keygen", "--out", str(rk_dir),
              "--passphrase-env", "RK_PASS"])
    rc, _ = _run(["--root", str(root), "anchor-root-pub-install",
                  "--pub", str(rk_dir / "root-pub.pem")])
    assert rc == 0, "RK pub install 应成功 rc=0，实际 rc={}".format(rc)

    if not (ak_dir / "anchor-attest-pub.txt").exists():
        _run(["--root", str(root), "anchor-attest-keygen", "--out", str(ak_dir),
              "--passphrase-env", "AK_PASS"])
    rc, _ = _run(["--root", str(root), "anchor-attest-pubkey-install",
                  "--pub", str(ak_dir / "anchor-attest-pub.txt")])
    assert rc == 0, "AK pub install 应成功 rc=0，实际 rc={}".format(rc)
    rc, _ = _run(["--root", str(root), "anchor-attest",
                  "--priv", str(ak_dir / "anchor-attest-priv.enc"),
                  "--passphrase-env", "AK_PASS"])
    assert rc == 0, "attest 签发应成功 rc=0，实际 rc={}".format(rc)
    rc, _ = _run(["--root", str(root), "anchor-attest-root-seal",
                  "--priv", str(rk_dir / "root-priv.enc"),
                  "--passphrase-env", "RK_PASS"])
    assert rc == 0, "RK 密封应成功 rc=0，实际 rc={}".format(rc)
    return rk_dir, ak_dir


def _assert_gates_blocked(r, root, label):
    """v2.27.33 核心：缺失态/降级态下，**闸门必须实际被拒**（不只是 verify 报告 rc=1）。
    这是 DSH §2.3 实测穿过的缺口——v2.27.32 测试只断言 verify，未断言 propose/apply/retrieve。"""
    rc_v, _ = _run(["--root", str(root), "anchor-attest-verify"])
    r.add("{} → verify FAIL(rc==1)".format(label), rc_v == 1, "rc={}".format(rc_v))
    rc_p, _ = _run(["--root", str(root), "propose", "--artifact", "A1",
                    "--op", "add", "--content", "gate-probe", "--reason", "probe"])
    r.add("{} → propose 被闸门拒绝(rc!=0)".format(label), rc_p != 0, "rc={}".format(rc_p))
    rc_a, _ = _run(["--root", str(root), "apply"])
    r.add("{} → apply 被闸门拒绝(rc!=0)".format(label), rc_a != 0, "rc={}".format(rc_a))
    rc_r, out = _run(["--root", str(root), "retrieve"])
    r.add("{} → retrieve 拒绝吐规则(rc==3)".format(label), rc_r == 3, "rc={}".format(rc_r))
    r.add("{} → retrieve 报 根信任-硬闸".format(label), "根信任" in out)


def test_rk_keygen_and_install():
    r = T("RK 根信任密钥生成 + 安装钉固（最高权威）+ 幂等重装（N-2）")
    tmp, root = _mk_store()
    rk_dir = tmp / "rk"
    try:
        # 无口令 env → rc=1
        _os.environ.pop("RK_PASS", None)
        rc1, _ = _run(["--root", str(root), "anchor-root-keygen", "--out", str(rk_dir),
                       "--passphrase-env", "RK_PASS"])
        r.add("无口令 env → RK keygen REFUSED(rc==1)", rc1 == 1, "rc={}".format(rc1))
        # 有口令 → rc=0，产出两文件
        _os.environ["RK_PASS"] = TEST_PASSPHRASE
        rc2, _ = _run(["--root", str(root), "anchor-root-keygen", "--out", str(rk_dir),
                       "--passphrase-env", "RK_PASS"])
        r.add("有口令 → RK keygen 成功(rc==0)", rc2 == 0, "rc={}".format(rc2))
        r.add("产出 RK 私钥（加密）+ 公钥两文件",
              (rk_dir / "root-priv.enc").exists() and (rk_dir / "root-pub.pem").exists())
        # 安装钉固：缺令牌 → rc=2
        _os.environ.pop("METACOG_ATTEST_PUBKEY_TOKEN", None)
        _os.environ.pop("METACOG_ATTEST_PUBKEY_TOKEN_EXPECTED", None)
        rc3, _ = _run(["--root", str(root), "anchor-root-pub-install",
                       "--pub", str(rk_dir / "root-pub.pem")])
        r.add("缺令牌 → RK pub install REFUSED(rc==2)", rc3 == 2, "rc={}".format(rc3))
        # 有令牌 → rc=0，且 RK 指纹钉固为最高权威
        _set_token()
        rc4, _ = _run(["--root", str(root), "anchor-root-pub-install",
                       "--pub", str(rk_dir / "root-pub.pem")])
        r.add("有令牌 → RK pub install 成功(rc==0)", rc4 == 0, "rc={}".format(rc4))
        try:
            pinned = metacog.Store(root).pinned_root_attest_pubkey_sha256()
        except ValueError:
            pinned = None
        r.add("RK 公钥指纹已钉固 CONTRACT.md（root_attest_pubkey_sha256）", pinned is not None,
              "pinned={}".format(pinned))
        # v2.27.33 N-2：同一把 RK 重装 → 幂等 rc=0（原实现对节标题行子串误中 → 必报「空指纹不符」）
        rc5, out5 = _run(["--root", str(root), "anchor-root-pub-install",
                          "--pub", str(rk_dir / "root-pub.pem")])
        r.add("同一把 RK 重装 → 幂等成功(rc==0)（N-2 修复）", rc5 == 0, "rc={}".format(rc5))
    finally:
        _reset_anchor_dir()
    return r.summary()


def _write_matching_ledger_and_resign(tmp, root, ak_dir):
    """写一份与实物一致的冻结账本并重签 attestation（frozen-hashes.jsonl ∈ ATTEST_FILES，
    其出现本身改变 commitment，故须重签；与生产仪式 record → attest 的顺序同构）。"""
    import hashlib
    contract_sha = hashlib.sha256((root / "CONTRACT.md").read_bytes()).hexdigest()
    (root / "frozen-hashes.jsonl").write_text(
        json.dumps({"path": "CONTRACT.md", "sha256": contract_sha}) + "\n", encoding="utf-8")
    _run(["--root", str(root), "anchor-attest",
          "--priv", str(ak_dir / "anchor-attest-priv.enc"), "--passphrase-env", "AK_PASS"])


def test_full_ceremony_verify_ok():
    r = T("完整仪式 → verify OK（第二权威背书）+ 账本对账通过")
    tmp, root = _mk_store()
    try:
        rk_dir, ak_dir = _full_ceremony(tmp, root)
        rc, out = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("完整仪式后 verify 通过(rc==0)", rc == 0, "rc={}".format(rc))
        r.add("verify 输出含 [OK]", "[OK]" in out)
        # 写入一份与实物完全一致的冻结账本 + 重签 → verify 仍通过（ledger-drift 正路径）
        _write_matching_ledger_and_resign(tmp, root, ak_dir)
        rc2, _ = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("账本与实物一致 → verify 仍通过(rc==0)", rc2 == 0, "rc={}".format(rc2))
    finally:
        _reset_anchor_dir()
    return r.summary()


def test_attack_delete_rk_pin_fail_closed():
    r = T("§2.3 收口：删 RK 钉固行 → verify + 闸门（propose/apply/retrieve）全 fail-closed")
    tmp, root = _mk_store()
    try:
        _full_ceremony(tmp, root)
        # 基线：闸门放行
        rc_p0, _ = _run(["--root", str(root), "propose", "--artifact", "A1",
                         "--op", "add", "--content", "baseline", "--reason", "probe"])
        r.add("基线 armed → propose 放行(rc==0)", rc_p0 == 0, "rc={}".format(rc_p0))
        # 删除 CONTRACT.md 中的 root_attest_pubkey_sha256 钉固行
        cpath = root / "CONTRACT.md"
        lines = [ln for ln in cpath.read_text(encoding="utf-8").splitlines()
                 if "root_attest_pubkey_sha256" not in ln]
        cpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _assert_gates_blocked(r, root, "删钉固行（RK_pub 文件仍在 → 曾武装）")
    finally:
        _reset_anchor_dir()
    return r.summary()


def test_attack_delete_rk_pub_fail_closed():
    r = T("§2.3 收口：删树外 RK_pub 文件 → verify + 闸门全 fail-closed（钉固在而公钥失）")
    tmp, root = _mk_store()
    try:
        _full_ceremony(tmp, root)
        _force_unlink(_root_pub_path(root))
        _assert_gates_blocked(r, root, "删 RK_pub 文件（钉固行仍在 → 曾武装）")
    finally:
        _reset_anchor_dir()
    return r.summary()


def test_attack_rebuild_chain_requires_armed_recovery():
    r = T("§2.3 收口：删钉固行后自铸 RK 重装——默认拒绝；--armed-recovery 显式放行（诚实残余演示）")
    tmp, root = _mk_store()
    try:
        _full_ceremony(tmp, root)
        # 攻击者删钉固行
        cpath = root / "CONTRACT.md"
        lines = [ln for ln in cpath.read_text(encoding="utf-8").splitlines()
                 if "root_attest_pubkey_sha256" not in ln]
        cpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # 自铸 RK2 并尝试重装——无 --armed-recovery → 拒绝
        _os.environ["RK_PASS"] = TEST_PASSPHRASE
        rk2 = tmp / "rk2"
        _run(["--root", str(root), "anchor-root-keygen", "--out", str(rk2),
              "--passphrase-env", "RK_PASS"])
        rc_no, out_no = _run(["--root", str(root), "anchor-root-pub-install",
                              "--pub", str(rk2 / "root-pub.pem")])
        r.add("曾武装态无 --armed-recovery 重装 → REFUSED(rc!=0)", rc_no != 0, "rc={}".format(rc_no))
        r.add("拒绝信息含 --armed-recovery 指引", "--armed-recovery" in out_no)
        # 显式 --armed-recovery → 放行（LOUD）
        rc_yes, out_yes = _run(["--root", str(root), "anchor-root-pub-install",
                                "--pub", str(rk2 / "root-pub.pem"), "--armed-recovery"])
        r.add("显式 --armed-recovery → 重装放行(rc==0)", rc_yes == 0, "rc={}".format(rc_yes))
        r.add("放行时输出 LOUD 告警（信任根变更）", "LOUD" in out_yes or "人工复核" in out_yes)
        # 诚实残余：攻击者持全写权 + 显式旗标可重建自洽链（AK2 重钉 ← RK2 签名授权 → RK2 密封 → verify OK）
        ak2 = tmp / "ak2"
        _run(["--root", str(root), "anchor-attest-keygen", "--out", str(ak2),
              "--passphrase-env", "AK_PASS"])
        ak2_fp = sigcrypto.anchor_pubkey_sha256(
            (ak2 / "anchor-attest-pub.txt").read_text(encoding="utf-8").strip())
        rk2_priv = _load_priv(rk2 / "root-priv.enc")
        repin_sig = tmp / "repin2.sig"
        repin_sig.write_text(sigcrypto.root_repin_sign(rk2_priv, ak2_fp), encoding="utf-8")
        _run(["--root", str(root), "anchor-attest-pubkey-install",
              "--pub", str(ak2 / "anchor-attest-pub.txt"), "--repin-auth", str(repin_sig)])
        _run(["--root", str(root), "anchor-attest",
              "--priv", str(ak2 / "anchor-attest-priv.enc"), "--passphrase-env", "AK_PASS"])
        rc_s, _ = _run(["--root", str(root), "anchor-attest-root-seal",
                        "--priv", str(rk2 / "root-priv.enc"), "--passphrase-env", "RK_PASS"])
        rc_v, _ = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("诚实残余如实演示：全写权 + 显式旗标 → 攻击链可重建（verify rc==0）", rc_s == 0 and rc_v == 0,
              "seal={} verify={}".format(rc_s, rc_v))
    finally:
        _reset_anchor_dir()
    return r.summary()


def test_attack_self_signed_seal_without_rk():
    r = T("入口 A 阻断：攻击者自铸 AK2 并用 AK2 私钥自签密封（无 RK 私钥）→ seal-bad-sig")
    tmp, root = _mk_store()
    try:
        _full_ceremony(tmp, root)  # RK 已正确建立为最高权威（RK_pub 钉固、密封由 RK 私钥签）
        ak2 = tmp / "ak2"
        _run(["--root", str(root), "anchor-attest-keygen", "--out", str(ak2),
              "--passphrase-env", "AK_PASS"])
        ak2_pem = (ak2 / "anchor-attest-pub.txt").read_text(encoding="utf-8").strip()
        ak2_fp = sigcrypto.anchor_pubkey_sha256(ak2_pem)
        ak2_priv = _load_priv(ak2 / "anchor-attest-priv.enc")
        _force_write(_attest_paths(root)[0], ak2_pem + "\n")
        cpath = root / "CONTRACT.md"
        lines = [ln for ln in cpath.read_text(encoding="utf-8").splitlines()
                 if "anchor_attest_pubkey_sha256" not in ln]
        lines.append("- **anchor_attest_pubkey_sha256**: `{}`".format(ak2_fp))
        cpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rec = sigcrypto.anchor_root_seal_sign(ak2_priv, ak2_fp, at=_dt_now())
        _overwrite_seal(root, rec + "\n")
        rc_v, out = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("自签密封（无 RK 私钥）→ verify FAIL(rc==1)", rc_v == 1, "rc={}".format(rc_v))
        r.add("verify 报 seal-bad-sig（根锚被改写/伪造）",
              "seal-bad-sig" in out or "root_anchor_seal_invalid" in out)
    finally:
        _reset_anchor_dir()
    return r.summary()


def test_repin_env_bypass_removed():
    r = T("重钉授权去 env 化：METACOG_ATTEST_REPIN_ALLOW 自设 env 不再可绕过")
    tmp, root = _mk_store()
    try:
        _full_ceremony(tmp, root)
        _os.environ["METACOG_ATTEST_REPIN_ALLOW"] = "1"
        ak2 = tmp / "ak2"
        _run(["--root", str(root), "anchor-attest-keygen", "--out", str(ak2),
              "--passphrase-env", "AK_PASS"])
        rc, out = _run(["--root", str(root), "anchor-attest-pubkey-install",
                        "--pub", str(ak2 / "anchor-attest-pub.txt")])
        r.add("设 REPIN_ALLOW=1 但无 RK 签名授权 → 重钉仍 REFUSED(rc==1)",
              rc == 1, "rc={}".format(rc))
        r.add("重钉失败提示含「RK 私钥签名授权」字样", "RK 私钥签名授权" in out)
    finally:
        _os.environ.pop("METACOG_ATTEST_REPIN_ALLOW", None)
        _reset_anchor_dir()
    return r.summary()


def test_repin_with_rk_auth_ok():
    r = T("重钉须 RK 私钥签名授权（--repin-auth），授权后成功")
    tmp, root = _mk_store()
    try:
        rk_dir, ak_dir = _full_ceremony(tmp, root)
        ak2 = tmp / "ak2"
        _run(["--root", str(root), "anchor-attest-keygen", "--out", str(ak2),
              "--passphrase-env", "AK_PASS"])
        ak2_pem = (ak2 / "anchor-attest-pub.txt").read_text(encoding="utf-8").strip()
        ak2_fp = sigcrypto.anchor_pubkey_sha256(ak2_pem)
        rc_no, _ = _run(["--root", str(root), "anchor-attest-pubkey-install",
                         "--pub", str(ak2 / "anchor-attest-pub.txt")])
        r.add("无 RK 授权重钉 → REFUSED(rc==1)", rc_no == 1, "rc={}".format(rc_no))
        rk_priv = _load_priv(rk_dir / "root-priv.enc")
        repin_path = tmp / "repin.sig"
        repin_path.write_text(sigcrypto.root_repin_sign(rk_priv, ak2_fp), encoding="utf-8")
        rc_yes, _ = _run(["--root", str(root), "anchor-attest-pubkey-install",
                          "--pub", str(ak2 / "anchor-attest-pub.txt"),
                          "--repin-auth", str(repin_path)])
        r.add("持 RK 签名授权 → 重钉成功(rc==0)", rc_yes == 0, "rc={}".format(rc_yes))
        try:
            pinned = metacog.Store(root).pinned_anchor_attest_pubkey_sha256()
        except ValueError:
            pinned = None
        r.add("重钉后 AK 钉固值更新为 AK2 指纹", pinned == ak2_fp, "pinned={}".format(pinned))
    finally:
        _reset_anchor_dir()
    return r.summary()


def test_rk_rotation():
    r = T("N-2 收口：RK 重装/轮换——换 RK 无授权硬拒不 clobber；--rotate-auth 授权轮换")
    tmp, root = _mk_store()
    try:
        rk_dir, ak_dir = _full_ceremony(tmp, root)
        old_pem = (_root_pub_path(root)).read_text(encoding="utf-8")
        # 换新 RK（无授权）→ rc=1，且 RK_pub 文件**不被覆盖**（校验先行，修复自我 DoS）
        _os.environ["RK_PASS"] = TEST_PASSPHRASE
        rk2 = tmp / "rk2"
        _run(["--root", str(root), "anchor-root-keygen", "--out", str(rk2),
              "--passphrase-env", "RK_PASS"])
        rc_no, _ = _run(["--root", str(root), "anchor-root-pub-install",
                         "--pub", str(rk2 / "root-pub.pem")])
        r.add("换 RK 无 --rotate-auth → REFUSED(rc==1)", rc_no == 1, "rc={}".format(rc_no))
        r.add("被拒后 RK_pub 文件未被覆盖（校验先行）",
              _root_pub_path(root).read_text(encoding="utf-8") == old_pem)
        rc_v, _ = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("被拒后 verify 仍通过（无 clobber DoS）", rc_v == 0, "rc={}".format(rc_v))
        # --rotate-auth（当前 RK 私钥签 root-rotate:<新指纹>）→ 轮换放行
        new_fp = sigcrypto.anchor_pubkey_sha256(
            (rk2 / "root-pub.pem").read_text(encoding="utf-8").strip())
        rk_priv = _load_priv(rk_dir / "root-priv.enc")
        rot = tmp / "rotate.sig"
        rot.write_text(sigcrypto.root_rotate_sign(rk_priv, new_fp), encoding="utf-8")
        rc_yes, out_yes = _run(["--root", str(root), "anchor-root-pub-install",
                                "--pub", str(rk2 / "root-pub.pem"),
                                "--rotate-auth", str(rot)])
        r.add("持当前 RK 签名授权 → 轮换成功(rc==0)", rc_yes == 0, "rc={}".format(rc_yes))
        try:
            pinned = metacog.Store(root).pinned_root_attest_pubkey_sha256()
        except ValueError:
            pinned = None
        r.add("轮换后钉固值更新为新 RK 指纹", pinned == new_fp, "pinned={}".format(pinned))
        # 轮换后旧密封由旧 RK 私钥签 → seal-bad-sig（fail-closed，须重密封——正确行为）
        rc_v2, _ = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("轮换后旧密封失效 → verify FAIL（fail-closed，须重密封）", rc_v2 == 1,
              "rc={}".format(rc_v2))
    finally:
        _reset_anchor_dir()
    return r.summary()


def test_seal_expiry_enforced():
    r = T("密封时效：≤0 钳 90（不可关）；>90 上行钳 90（N-1 不可放宽）")
    tmp, root = _mk_store()
    try:
        rk_dir, ak_dir = _full_ceremony(tmp, root)
        ak_pem = (ak_dir / "anchor-attest-pub.txt").read_text(encoding="utf-8").strip()
        ak_fp = sigcrypto.anchor_pubkey_sha256(ak_pem)
        rk_priv = _load_priv(rk_dir / "root-priv.enc")
        old_at = _dt_now_minus_days(200)
        old_rec = sigcrypto.anchor_root_seal_sign(rk_priv, ak_fp, at=old_at)
        _overwrite_seal(root, old_rec + "\n")
        # 尝试关过期（≤0）→ 钳为 90 → 旧密封仍判过期
        _os.environ["METACOG_ATTEST_MAX_AGE_DAYS"] = "0"
        rc1, out1 = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("MAX_AGE_DAYS=0 仍强制过期 → verify FAIL(rc==1)", rc1 == 1, "rc={}".format(rc1))
        r.add("verify 报 seal-expired（时效不可关）", "seal-expired" in out1)
        # v2.27.33 N-1：尝试放宽（=1000）→ 钳回 90 → 旧密封仍判过期
        _os.environ["METACOG_ATTEST_MAX_AGE_DAYS"] = "1000"
        rc2, out2 = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("MAX_AGE_DAYS=1000 被钳回 90 → 旧密封仍过期（N-1 修复）", rc2 == 1, "rc={}".format(rc2))
        r.add("verify 仍报 seal-expired（上行放宽被拒）", "seal-expired" in out2)
    finally:
        _os.environ.pop("METACOG_ATTEST_MAX_AGE_DAYS", None)
        _reset_anchor_dir()
    return r.summary()


def test_future_timestamp_rejected():
    r = T("N-3 收口：未来时间戳拒收（密封 seal-future；attestation malformed）")
    tmp, root = _mk_store()
    try:
        rk_dir, ak_dir = _full_ceremony(tmp, root)
        ak_pem = (ak_dir / "anchor-attest-pub.txt").read_text(encoding="utf-8").strip()
        ak_fp = sigcrypto.anchor_pubkey_sha256(ak_pem)
        rk_priv = _load_priv(rk_dir / "root-priv.enc")
        # RK 真签的未来密封（2099）→ seal-future 拒收
        fut_rec = sigcrypto.anchor_root_seal_sign(rk_priv, ak_fp, at="20990101T0000")
        _overwrite_seal(root, fut_rec + "\n")
        rc1, out1 = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("未来密封（RK 真签）→ verify FAIL(rc==1)", rc1 == 1, "rc={}".format(rc1))
        r.add("verify 报 seal-future（永不过期漏洞已堵）", "seal-future" in out1)
        # 未来 at 的 attestation → malformed
        _full_ceremony(tmp, root)  # 重建正常密封
        ak_priv = _load_priv(ak_dir / "anchor-attest-priv.enc")
        commits = metacog._attest_commits(metacog.Store(root))
        fut_att = sigcrypto.anchor_attest(ak_priv, commits, at="20990101T0000")
        _force_write(_attest_paths(root)[1], fut_att + "\n")
        rc2, out2 = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("未来 at 的 attestation → verify FAIL(rc==1)", rc2 == 1, "rc={}".format(rc2))
        r.add("verify 报 malformed（at-future）", "malformed" in out2 or "at-future" in out2)
    finally:
        _reset_anchor_dir()
    return r.summary()


def test_invalid_fingerprint_rejected():
    r = T("指纹/at 格式校验：非 hex 指纹与非法 at 被拒")
    tmp, root = _mk_store()
    try:
        rk_dir, ak_dir = _full_ceremony(tmp, root)
        rk_priv = _load_priv(rk_dir / "root-priv.enc")
        try:
            sigcrypto.anchor_root_seal_sign(rk_priv, "Z" * 64, at=_dt_now())
            r.add("非 hex 指纹 → 被拒（抛 ValueError）", False, "竟然接受")
        except ValueError:
            r.add("非 hex 指纹 → 被拒（抛 ValueError）", True)
        try:
            sigcrypto.anchor_root_seal_sign(rk_priv, "a" * 64, at="2026:10:27")
            r.add("非法 at（含冒号）→ 被拒", False, "竟然接受")
        except ValueError:
            r.add("非法 at（含冒号）→ 被拒", True)
    finally:
        _reset_anchor_dir()
    return r.summary()


def test_retrieve_read_gate():
    r = T("读闸全覆盖（§2.4 收口）：密封无效 **与层缺失** 均拒绝吐规则")
    tmp, root = _mk_store()
    try:
        _full_ceremony(tmp, root)
        rc_ok, _ = _run(["--root", str(root), "retrieve"])
        r.add("有效信任根 + 空 store → retrieve 通过(rc==0)", rc_ok == 0, "rc={}".format(rc_ok))
        # ① 密封被破坏 → rc=3
        _overwrite_seal(root, "garbage-not-a-valid-seal")
        rc_bad, out = _run(["--root", str(root), "retrieve"])
        r.add("密封被破坏 → retrieve 拒绝(rc==3)", rc_bad == 3, "rc={}".format(rc_bad))
        r.add("retrieve 报 根信任-硬闸", "根信任" in out)
        _full_ceremony(tmp, root)  # 重建
        # ② v2.27.33 §2.4：删除树外 AK 公钥（层缺失）→ 密封虽有效，retrieve 仍须拒
        _force_unlink(_attest_paths(root)[0])
        rc_miss, out2 = _run(["--root", str(root), "retrieve"])
        r.add("AK 公钥缺失（层缺失）→ retrieve 拒绝(rc==3)（§2.4 修复）",
              rc_miss == 3, "rc={}".format(rc_miss))
        r.add("retrieve 报 根信任-硬闸（层缺失路径）", "根信任" in out2)
    finally:
        _reset_anchor_dir()
    return r.summary()


def test_freeze_record_gate():
    r = T("freeze.record 门禁：信任根完好性 + 曾武装拒绝（防删钉固行后重基线洗白）")
    tmp, root = _mk_store()
    try:
        _full_ceremony(tmp, root)
        st = metacog.Store(root)
        ok1, viol1 = metacog._attest_root_integrity(st)
        r.add("有效仪式 → _attest_root_integrity 通过(True,[])", ok1 and viol1 == [],
              "viol={}".format(viol1))
        _overwrite_seal(root, "garbage-invalid-seal")
        ok2, viol2 = metacog._attest_root_integrity(st)
        r.add("密封被破坏 → _attest_root_integrity 阻塞(False)", (not ok2) and bool(viol2),
              "viol={}".format(viol2))
        # v2.27.33：删钉固行（RK_pub/密封仍在 = 曾武装）→ record 门禁拒绝
        _full_ceremony(tmp, root)
        cpath = root / "CONTRACT.md"
        lines = [ln for ln in cpath.read_text(encoding="utf-8").splitlines()
                 if "root_attest_pubkey_sha256" not in ln]
        cpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok3, viol3 = metacog._attest_root_integrity(metacog.Store(root))
        r.add("曾武装态（钉固缺失）→ record 门禁拒绝（ROOT-EVER-ARMED）",
              (not ok3) and any("EVER-ARMED" in v for v in viol3), "viol={}".format(viol3))
    finally:
        _reset_anchor_dir()
    return r.summary()


def test_ledger_drift_fail_closed():
    r = T("§2.1 收口：冻结账本与实物失配 → verify/gate fail-closed（无锚密钥可复算）")
    tmp, root = _mk_store()
    try:
        rk_dir, ak_dir = _full_ceremony(tmp, root)
        # 正确账本（+重签）→ 通过
        _write_matching_ledger_and_resign(tmp, root, ak_dir)
        rc0, _ = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("账本与实物一致 → verify 通过(rc==0)", rc0 == 0, "rc={}".format(rc0))
        # 篡改 CONTRACT.md（账本未更新）→ ledger_drift
        cpath = root / "CONTRACT.md"
        cpath.write_text(cpath.read_text(encoding="utf-8") + "\n<!-- drift -->\n", encoding="utf-8")
        # 注意：CONTRACT.md 被改后钉固行仍在 → verify 先过密封/attestation，再报 ledger_drift
        rc1, out1 = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("账实失配 → verify FAIL(rc==1)", rc1 == 1, "rc={}".format(rc1))
        r.add("verify 报 ledger_drift / 冻结账本失配", "ledger_drift" in out1 or "冻结账本" in out1)
        # 闸门同样拒绝
        rc_g, _ = _run(["--root", str(root), "propose", "--artifact", "A1",
                        "--op", "add", "--content", "x", "--reason", "probe"])
        r.add("账实失配 → propose 被拒(rc!=0)", rc_g != 0, "rc={}".format(rc_g))
        rc_r, _ = _run(["--root", str(root), "retrieve"])
        r.add("账实失配 → retrieve 拒绝(rc==3)", rc_r == 3, "rc={}".format(rc_r))
        # 恢复一致 → 重新通过
        cpath.write_text(cpath.read_text(encoding="utf-8").replace("\n<!-- drift -->\n", ""),
                         encoding="utf-8")
        rc2, _ = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("恢复一致 → verify 重新通过(rc==0)", rc2 == 0, "rc={}".format(rc2))
    finally:
        _reset_anchor_dir()
    return r.summary()


def _dt_now():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M")


def _dt_now_minus_days(n):
    import datetime as _dt
    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=n)).strftime("%Y%m%dT%H%M")


def test_attack_delete_rk_traces_keep_ak_fail_closed():
    r = T("R3-1 收口（v2.27.34）：删 RK 侧三处痕迹（钉固行+RK_pub+attest-root）但 AK 层保留 → 仍 fail-closed")
    tmp, root = _mk_store()
    try:
        _full_ceremony(tmp, root)
        # 基线：armed 态闸门放行
        rc_p0, _ = _run(["--root", str(root), "propose", "--artifact", "A1",
                         "--op", "add", "--content", "baseline", "--reason", "probe"])
        r.add("基线 armed → propose 放行(rc==0)", rc_p0 == 0, "rc={}".format(rc_p0))
        # ① 删 CONTRACT.md 的 root_attest_pubkey_sha256 钉固行
        cpath = root / "CONTRACT.md"
        lines = [ln for ln in cpath.read_text(encoding="utf-8").splitlines()
                 if "root_attest_pubkey_sha256" not in ln]
        cpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # ② 删树外 RK_pub 文件
        _force_unlink(_root_pub_path(root))
        # ③ 删树外 attest-root 密封文件
        _force_unlink(_seal_path(root))
        # 关键：AK 层（.attest-pub.txt / .attest.json）**保留**——这正是 DSH R3-1 的攻击向量：
        #   v2.27.33 的 _root_ever_armed 只查 RK_pub + v1 密封，三删后两样皆无 → 判 never-armed
        #   → 闸门 off → 攻击者自铸 RK/AK 重签 → verify 回 [OK]（R3-1 漏洞）；
        #   v2.27.34 把 AK 层纳入 ever-armed → 三删后 AK 仍在 → ever-armed=True → fail-closed。
        #   诚实残余（DSH §3 标注）：若连 AK 层一并删（四删全清），则退化为 genuine fresh install，
        #   由消费者带外核对 RK 指纹兜底；此非文件存在性判据能闭，属本轮修复边界，已在 CHANGELOG 登记。
        _assert_gates_blocked(r, root, "删 RK 侧三处痕迹、AK 层保留（R3-1 修复）")
        # 额外真断言：verify 须 rc=1（而非 rc=0 [OK]——回退 fresh 静默放行的特征）
        rc_v, _ = _run(["--root", str(root), "anchor-attest-verify"])
        r.add("三删保留 AK → verify FAIL(rc==1)（R3-1 修复：不再回退 fresh 静默放行）",
              rc_v == 1, "rc={}".format(rc_v))
    finally:
        _reset_anchor_dir()
    return r.summary()


def main():
    print("=== C-1 非对称信任根 · v2.27.34 双密钥回归 ===")
    results = []
    results.append(test_rk_keygen_and_install())
    results.append(test_full_ceremony_verify_ok())
    results.append(test_attack_delete_rk_pin_fail_closed())
    results.append(test_attack_delete_rk_pub_fail_closed())
    results.append(test_attack_rebuild_chain_requires_armed_recovery())
    results.append(test_attack_self_signed_seal_without_rk())
    results.append(test_repin_env_bypass_removed())
    results.append(test_repin_with_rk_auth_ok())
    results.append(test_rk_rotation())
    results.append(test_seal_expiry_enforced())
    results.append(test_future_timestamp_rejected())
    results.append(test_invalid_fingerprint_rejected())
    results.append(test_retrieve_read_gate())
    results.append(test_freeze_record_gate())
    results.append(test_ledger_drift_fail_closed())
    results.append(test_attack_delete_rk_traces_keep_ak_fail_closed())
    total_pass = sum(1 for x in results if x)
    print("\n=== C-1 v2.27.35 测试汇总: {}/{} 组 PASS ===".format(total_pass, len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    _os.chdir(Path(__file__).resolve().parent)
    sys.exit(main())
