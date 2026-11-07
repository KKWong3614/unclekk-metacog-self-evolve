# test-v22735-n5-anchor-slug.py — R2-N-5 收口回归：树外锚命名空间隔离
#
# 模块说明（v2.27.35，回应 DSH R2-N-5「树外落点按目录名共享（同机多实例互相覆盖）」，Low）：
#   - 新 slug = 「目录名--规范路径哈希前12」：同名异路径实例命名空间隔离，互不覆盖；
#   - legacy（纯目录名）锚读回退：仅当 legacy RK_pub 指纹 == CONTRACT 根钉固（密码学绑定）；
#     同名异钥 legacy 文件**不**回退（fail-closed）；
#   - ever-armed 对 legacy 仅**存在性**判定（与合同内容解耦——R3-1 删钉固行后 pin=None
#     仍能检出曾武装，不回归 R3-1）；同名异实例 legacy 残留会误判曾武装 → fail-closed
#     须显式 --armed-recovery（宁误报不漏报，诚实代价）；
#   - freeze 侧 slug 与 metacog 侧**有意镜像**（跨模块一致性断言）；
#     freeze legacy 回退绑定判据 = legacy 锚内容 == 当前账本 commitment。
#
# 运行：python test-v22735-n5-anchor-slug.py  （须先 cd scripts/）
import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

import metacog
import freeze
import sigcrypto

# 重定向树外 attestation 目录（必须在任何 CLI 调用前）
metacog.ATTEST_ANCHOR_DIR = Path(tempfile.mkdtemp(prefix="n5_attest_tree_"))


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


def _pub_pem():
    pub, _priv = sigcrypto.gen_keypair()
    return sigcrypto.serialize_pub(pub)


def _contract_with_pin(fp):
    return "# CONTRACT (N-5 test minimal)\n\n- **root_attest_pubkey_sha256**: `{}`\n".format(fp)


def _mkroot(base, name):
    root = base / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _clean_anchor(*paths):
    for p in paths:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


# ───────────────────────── G1 slug 命名空间隔离 ─────────────────────────

def test_slug_isolation():
    t = T("G1 slug 隔离：同名异路径实例锚文件互不覆盖")
    base = Path(tempfile.mkdtemp(prefix="n5_iso_"))
    name = "n5skill"
    rootA = _mkroot(base / "locA", name)
    rootB = _mkroot(base / "locB", name)
    stA, stB = metacog.Store(rootA), metacog.Store(rootB)
    try:
        slugA = metacog._attest_slug(stA)
        slugB = metacog._attest_slug(stB)
        t.add("同名异路径 → slug 不同", slugA != slugB,
              "A={} B={}".format(slugA[:24], slugB[:24]))
        t.add("slug 前缀 = 目录名", slugA.startswith(name + "--") and slugB.startswith(name + "--"))
        t.add("同实例 slug 稳定（幂等）", metacog._attest_slug(stA) == slugA)
        pemA, pemB = _pub_pem(), _pub_pem()
        fA = metacog.ATTEST_ANCHOR_DIR / (slugA + ".root-pub.txt")
        fB = metacog.ATTEST_ANCHOR_DIR / (slugB + ".root-pub.txt")
        fA.write_text(pemA, encoding="utf-8")
        fB.write_text(pemB, encoding="utf-8")
        t.add("A 读到 A 的 RK_pub（不被 B 覆盖）",
              metacog._root_pub_path(stA).read_text(encoding="utf-8") == pemA)
        t.add("B 读到 B 的 RK_pub（不被 A 覆盖）",
              metacog._root_pub_path(stB).read_text(encoding="utf-8") == pemB)
        t.add("两实例锚文件物理独立", fA != fB and fA.exists() and fB.exists())
    finally:
        _clean_anchor(metacog.ATTEST_ANCHOR_DIR / (metacog._attest_slug(stA) + ".root-pub.txt"),
                      metacog.ATTEST_ANCHOR_DIR / (metacog._attest_slug(stB) + ".root-pub.txt"))
        shutil.rmtree(base, ignore_errors=True)
    return t.summary()


# ───────────────────────── G2 legacy 绑定回退 ─────────────────────────

def test_legacy_binding_fallback():
    t = T("G2 legacy 回退：指纹==钉固才采纳，异钥不采纳（fail-closed）")
    base = Path(tempfile.mkdtemp(prefix="n5_leg_"))
    name = "n5legskill"
    rootA = _mkroot(base / "a", name)
    rootB = _mkroot(base / "b", name)
    stA, stB = metacog.Store(rootA), metacog.Store(rootB)
    legacy = metacog.ATTEST_ANCHOR_DIR / (name + ".root-pub.txt")
    try:
        pemA, pemB = _pub_pem(), _pub_pem()
        fpA = sigcrypto.anchor_pubkey_sha256(pemA)
        fpB = sigcrypto.anchor_pubkey_sha256(pemB)
        (rootA / "CONTRACT.md").write_text(_contract_with_pin(fpA), encoding="utf-8")
        (rootB / "CONTRACT.md").write_text(_contract_with_pin(fpB), encoding="utf-8")
        legacy.write_text(pemA, encoding="utf-8")  # 共享 legacy 名（同 basename 碰撞场景）
        t.add("A：legacy RK_pub 指纹==钉固 → 绑定成立", metacog._legacy_anchor_bound(stA))
        rpA = metacog._anchor_read_path(stA, metacog._root_pub_path(stA), ".root-pub.txt")
        t.add("A：读解析回退到 legacy 文件", rpA == legacy and rpA.exists())
        t.add("B：同名异钥 legacy → 绑定拒绝", not metacog._legacy_anchor_bound(stB))
        rpB = metacog._anchor_read_path(stB, metacog._root_pub_path(stB), ".root-pub.txt")
        t.add("B：不回退（返回新命名缺失路径，fail-closed）", rpB == metacog._root_pub_path(stB) and not rpB.exists())
        # 钉固缺失（R3-1 删行）→ 绑定不可判 → 不回退
        (rootA / "CONTRACT.md").unlink()
        t.add("A：钉固删除后绑定不可判 → 不回退", not metacog._legacy_anchor_bound(stA))
        # 清掉 legacy 后新名缺失 → 读路径不存在（missing 语义保持）
        legacy.unlink()
        rpA2 = metacog._anchor_read_path(stA, metacog._root_pub_path(stA), ".root-pub.txt")
        t.add("legacy 清除后无回退对象 → 返回新命名路径", rpA2 == metacog._root_pub_path(stA))
    finally:
        _clean_anchor(legacy)
        shutil.rmtree(base, ignore_errors=True)
    return t.summary()


# ───────────────────────── G3 ever-armed legacy 存在性（R3-1 不回归） ─────────────────────────

def test_ever_armed_legacy_existence():
    t = T("G3 ever-armed：legacy 痕迹存在性判定（不依赖钉固，R3-1 不回归）")
    base = Path(tempfile.mkdtemp(prefix="n5_arm_"))
    name = "n5armskill"
    rootC = _mkroot(base / "c", name)
    stC = metacog.Store(rootC)
    leg_rp = metacog.ATTEST_ANCHOR_DIR / (name + ".root-pub.txt")
    leg_seal = metacog.ATTEST_ANCHOR_DIR / (name + ".attest-root.txt")
    leg_ak = metacog.ATTEST_ANCHOR_DIR / (name + ".attest-pub.txt")
    try:
        t.add("无任何痕迹 → ever-armed False", not metacog._root_ever_armed(stC))
        leg_rp.write_text(_pub_pem(), encoding="utf-8")
        t.add("仅 legacy RK_pub 存在（无钉固）→ True", metacog._root_ever_armed(stC))
        _clean_anchor(leg_rp)
        leg_seal.write_text("v1:abcd:2026-10-28T00:00:00Z:c2ln", encoding="utf-8")
        t.add("仅 legacy v1 密封存在 → True", metacog._root_ever_armed(stC))
        _clean_anchor(leg_seal)
        leg_ak.write_text(_pub_pem(), encoding="utf-8")
        t.add("仅 legacy AK 公钥存在（R3-1 层）→ True", metacog._root_ever_armed(stC))
        _clean_anchor(leg_ak)
        leg_seal.write_text("deadbeef01", encoding="utf-8")  # 裸指纹 = legacy 单密钥态，不计武装
        t.add("legacy 裸指纹密封（非 v1）→ 不计武装", not metacog._root_ever_armed(stC))
        _clean_anchor(leg_seal)
        t.add("全部清除 → False", not metacog._root_ever_armed(stC))
    finally:
        _clean_anchor(leg_rp, leg_seal, leg_ak)
        shutil.rmtree(base, ignore_errors=True)
    return t.summary()


# ───────────────────────── G4 freeze 侧同构 ─────────────────────────

def test_freeze_slug_mirror():
    t = T("G4 freeze 侧：slug 镜像一致 + 同名隔离 + legacy 锚绑定采纳")
    orig_root, orig_frz = freeze.SKILL_ROOT, freeze.FREEZE_FILE
    base = Path(tempfile.mkdtemp(prefix="n5_frz_"))
    name = "n5frzskill"
    rA, rB = _mkroot(base / "a", name), _mkroot(base / "b", name)
    leg_anchor = Path.home() / ".metacog_freeze_anchors" / (name + ".anchor")
    try:
        t.add("跨模块镜像一致（freeze vs metacog 同根）",
              freeze._freeze_slug() == metacog._attest_slug(metacog.Store(orig_root)))
        freeze.SKILL_ROOT, freeze.FREEZE_FILE = rA, rA / "frozen-hashes.jsonl"
        slugA = freeze._freeze_slug()
        freeze.SKILL_ROOT = rB
        slugB = freeze._freeze_slug()
        t.add("freeze：同名异路径 → slug 不同", slugA != slugB)
        freeze.SKILL_ROOT, freeze.FREEZE_FILE = rA, rA / "frozen-hashes.jsonl"
        (rA / "frozen-hashes.jsonl").write_text('{"n5": true}\n', encoding="utf-8")
        commit = hashlib.sha256((rA / "frozen-hashes.jsonl").read_bytes()).hexdigest()
        t.add("无锚 → 读解析返回新命名（缺失）",
              freeze._anchor_path() == freeze._anchor_write_path()
              and not freeze._anchor_path().exists())
        leg_anchor.write_text(commit, encoding="utf-8")
        t.add("legacy 锚内容==账本 commitment → 采纳（读回退生效）",
              freeze._anchor_path() == leg_anchor)
        leg_anchor.write_text("0" * 64, encoding="utf-8")
        t.add("legacy 锚内容失配 → 不采纳（fail-closed）",
              freeze._anchor_path() == freeze._anchor_write_path())
        freeze.SKILL_ROOT = rB
        t.add("同名异实例读不到他人 legacy 锚（B 无账本 → commitment 不同）",
              freeze._anchor_path() == freeze._anchor_write_path())
    finally:
        freeze.SKILL_ROOT, freeze.FREEZE_FILE = orig_root, orig_frz
        _clean_anchor(leg_anchor)
        shutil.rmtree(base, ignore_errors=True)
    return t.summary()


def main():
    print("=" * 70)
    print("R2-N-5 收口回归（v2.27.35）：树外锚命名空间隔离")
    print("=" * 70)
    results = [
        test_slug_isolation(),
        test_legacy_binding_fallback(),
        test_ever_armed_legacy_existence(),
        test_freeze_slug_mirror(),
    ]
    ok = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 70)
    print("=== R2-N-5 v2.27.35 测试汇总: {}/{} 组 PASS ===".format(ok, total))
    print("=" * 70)
    sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    main()
