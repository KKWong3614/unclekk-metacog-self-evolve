# 测试证据（当前版本摘要）

> **实跑时间**：2026-10-30 ｜ **版本**：v2.27.48 ｜ **环境**：Python 3.13（零第三方依赖，仅标准库），Windows / managed python

## 1. 全量回归结果

**56/56 套件诚实 PASS**（判定三重，缺一即判 FAIL）：

1. 进程退出码 `exit=0`
2. 末次自报 `X/Y PASS` 且 `X == Y`（不接受「exit 0 但自报不全」）
3. 输出中无 `[FAIL]` 标记（防「打印失败却 exit 0」的掩错模式）

## 2. 复现方式（随包可独立运行）

```bash
python3 scripts/_run_all_tests.py
```

- **应有套件清单** `scripts/test-suite-manifest.txt`（56 条，随包分发）：清单声明但文件缺失 → 直接 FAIL；清单外新增套件 → FAIL（不静默纳分）。分母完整性由清单唯一锚定，删测试文件无法让通过率自动变好看。
- 运行器全局仅设专属 `METACOG_TRUST_ROOT_ANCHOR_KEY` 测试密钥（v2.27.17 C-01：源码内嵌默认锚已删除）；生产环境须以部署专属随机密钥覆盖。
- 单套件超时 180s 计 FAIL 并打印 stdout/stderr 尾部。

## 3. 套件清单（56）

  - `test-adaptive-ratchet.py` · `test-attribution.py` · `test-benchmark.py` · `test-boundary-cases.py` · `test-c01-no-default-anchor.py` · `test-c02-entry-injection.py`
  - `test-c1-attestation.py` · `test-cli-wiring.py` · `test-confirm-sign.py` · `test-core.py` · `test-d2-d5.py` · `test-domain-init.py`
  - `test-domain-migration.py` · `test-freeze-appendonly.py` · `test-h06-resign-replay.py` · `test-h1-missing-integrity.py` · `test-h2-seed-wash.py` · `test-h3-body-substitution.py`
  - `test-h4-large-applies.py` · `test-held-out.py` · `test-human-gate.py` · `test-init-domain.py` · `test-l3-compare-digest-nonascii.py` · `test-m1-auto-trigger.py`
  - `test-m3-reactivate-expected-id.py` · `test-m5-src-whitelist.py` · `test-marker-write-fail.py` · `test-meta-policy.py` · `test-n08-init-domain-injection.py` · `test-n09-init-baseline.py`
  - `test-n10-n11-rollback-migration.py` · `test-p0-1-real-data.py` · `test-p0-2-knowledge-transfer.py` · `test-p2-1-meta-optimizer.py` · `test-p2-2-domain-detector.py` · `test-p2-3-visualize.py`
  - `test-sigcrypto.py` · `test-trust-root-selftest.py` · `test-trust-root.py` · `test-utility-derivation.py` · `test-v2100-r7-closure.py` · `test-v2110-habc-closure.py`
  - `test-v2120-p1-closure.py` · `test-v2130-hb-closure.py` · `test-v2170-h3-closure.py` · `test-v2260-chain-hardening.py` · `test-v2270-r1r2r3.py` · `test-v2271-n3-pin-drift.py`
  - `test-v22713-audit-closeout.py` · `test-v2272-n1-pin-wash.py` · `test-v2272-n2-manifest-key-deletion.py` · `test-v2273-r5-anchor-sig-gate.py` · `test-v2273-r7-bootstrap.py` · `test-v2274-r4-r6-r8-r11-r5b.py`
  - `test-v290-c10-h4-legacy.py` · `test-v22735-n5-anchor-slug.py`

## 4. 与信任根 / 攻击面的对应关系

| 攻击面 | 对应套件（节选） |
|---|---|
| 默认锚自签（信任根洗白） | `test-c01-no-default-anchor.py`、`test-c1-attestation.py` |
| 密钥/签名密码学 | `test-sigcrypto.py`、`test-trust-root.py`、`test-trust-root-selftest.py` |
| 签重放 / 重签 | `test-h06-resign-replay.py` |
| 人类闸自签 | `test-human-gate.py`、`test-confirm-sign.py` |
| 删键逃逸 / 基线漂移 | `test-v2272-n2-manifest-key-deletion.py`、`test-v2273-r5-anchor-sig-gate.py` |
| 版本收口回归 | `test-v227*-closure.py`、`test-v2260-chain-hardening.py`、`test-v2270-r1r2r3.py` |

逐版收口与审计裁定明细见 `CHANGELOG.md`；更早版本（v2.1.1 时代，2026-09-08/09）的逐次运行日志**不随包分发**，留存于作者 dev 树作审计追溯。

## 5. 诚实边界

- 上列为**套件级通过率**与**审计链裁定**，不等于对所有环境的端到端保证。
- 冻结账本（`ledger/`）、树外锚点等**运行期状态**不在本轮全量回归的覆盖范围（运行期由 `verify` / `status` 自查）。
