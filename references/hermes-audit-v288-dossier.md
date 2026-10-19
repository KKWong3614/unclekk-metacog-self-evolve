# 铁律5 统一复验卷宗 · unclekk-metacog-self-evolve v2.8.8

> 目标：复验 v2.8.8 是否真正闭环 Hermes v2.8.7 复派（铁律5，2026-10-10）⚠️ CONDITIONAL-PASS 裁定维持的发布阻断 P0-1（GUARD 路径 legacy 兼容缺口）及诚实披露 OPEN 项 F-4（manifest 不在完整性域，H-3 攻击链）/ H-2（rollback 重基线无留痕）。
> 审计对象：真实工作树 `C:\Users\Administrator\.workbuddy\skills\unclekk-metacog-self-evolve\`（version=2.8.8，sha256 校验 metacog.py/test-trust-root.py/test-d2-d5.py 与冻结清单一致）。
> 纪律：铁律5 = 修改一次性冻结后最后派发；本卷宗为 evidence dossier，不替代独立审计员判断。

## 一、v2.8.7 裁定（待收口的 P0-1 / F-4 / H-2）

Hermes v2.8.7 复派（铁律5，2026-10-10）裁定 ⚠️ CONDITIONAL-PASS，维持：

- **P0-1（GUARD 路径 legacy 兼容缺口 · 发布阻断）**：v2.8.7 的 `_script_hash_matches` 委托覆盖了 `verify_integrity` 的 script: 与非 script: 制品分支、`verify_script_integrity`，但 `GUARD_INTEGRITY_KEY`（human-guard 信任根）在 `verify_integrity` 被 `continue` 跳过，其实际比对在 `cmd_verify` 仍裸等值 `gcur != grec.get("hash")`，未纳入 legacy 兼容——存量 v2.8.5 human-guard 基线（16-char）升级后误判漂移。Hermes 据此维持 CONDITIONAL-PASS。
- **F-4（manifest 不在完整性域 · H-3 攻击链）**：SKILL.md/CONTRACT.md/CHANGELOG.md/HANDOFF.md/pack.sh 未被纳入 D4 完整性快照，手改不触发硬闸，叠加 F-3 rollback 重基线构成连贯攻击链。v2.8.7 如实标注为 OPEN。
- **H-2（rollback 重基线无留痕）**：v2.8.7 的 `--yes` 人类确认无持久审计轨迹，残余在 C-10 威胁模型内。v2.8.7 如实标注为 OPEN。

## 二、v2.8.8 处置（CHANGELOG 块节选）

- **P0-1**：`cmd_verify` 的 `GUARD_INTEGRITY_KEY` 比对由裸等值改为委托 `_script_hash_matches(gcur, grec.get("hash"))`——16-char 旧基线命中兼容分支（ok=True + warn 提示升级 128-bit），真实篡改仍判漂移。新增 `test_c11_legacy_16char_guard_baseline_compatible`（2 断言：旧 16-char GUARD 基线 → rc==0 / 真实篡改 → rc==1）。
- **F-4**：新增 `MANIFEST_NAMES`（5 个清单文件），`record_script_integrity` 写入 `manifest:` 键，`verify_integrity` 新增 `manifest:` 分支做**非阻塞**检测（纳入 dirty 计数 + legacy 兼容 warn）。**设计原则：manifest 排除出硬闸**（硬闸 `_script_integrity_drift_if_enforced` 仍仅 `script:` 运行时代码）→ 正常版本升级改 SKILL.md/CHANGELOG.md 不会死锁 apply/keygen。新增 `test_f4_manifest_integrity_domain`（5 断言：record 写入 manifest: 键 / 全 MANIFEST_NAMES / 手改 SKILL.md 判漂移 / 硬闸 drift 为空不锁死 / 重基线自愈）。
- **H-2**：`cmd_rollback` 重基线前后捕获旧→新哈希，落盘 `ledger/rollback-audit.jsonl`（与 integrity.json 分离存储，削弱同域自指），记录 operation=rollback-rebaseline / artifact / entry_id / old_hash / new_hash / confirmed=True。新增 `test_d5_rollback_audit_trail`（8 断言全过）。诚实注记：`--yes` 无 TTY 校验仍 OPEN，留 v2.8.9。

## 三、代码证据（scripts/metacog.py，v2.8.8）

### 3.1 P0-1（cmd_verify GUARD 块委托 helper）
```python
gcur = st._hash_text(st.human_guard.read_text(encoding="utf-8"))
# v2.8.8 P0-1：GUARD_INTEGRITY_KEY（human-guard）检查委托 _script_hash_matches，纳入 legacy 16-char 兼容
_g_ok, _g_legacy = st._script_hash_matches(gcur, grec.get("hash"))
if _g_legacy:
    warn("[完整性] 检测到 64-bit 旧格式 human-guard 基线哈希（{}）；已按首 16 字符判定未篡改，"
         "建议运行 keygen/apply 自动升级为 128-bit 基线。".format(Store.GUARD_INTEGRITY_KEY))
if not _g_ok:
    dirty += 1
    bad("{} 偏离快照（当前 hash={}，快照 hash={}）：公钥可能被直写替换。".format(
        Store.GUARD_INTEGRITY_KEY, gcur, grec.get("hash")))
```

### 3.1.1 `_script_hash_matches` 真实实现（消除 M-02 歧义）

```python
# metacog.py L500-514（Store 静态方法）
def _script_hash_matches(scur: str, stored) -> "tuple[bool, bool]":
    """v2.8.7 F-1 迁移兼容：基线哈希长度兼容比对。
    当前哈希恒为 128-bit（32 hex，见 _hash_text）；存量 v2.8.5 及更早基线为 64-bit（16 hex）。
    若 stored 长度为 16 且 scur[:16] == stored → 命中旧格式兼容分支，判 ok=True、legacy_fmt=True
    （调用方应 warn 提示重基线；下一次 keygen/apply 的 record_script_integrity 会将其自动升级为 128-bit）。
    其余情形走精确等值比较。返回 (ok, legacy_fmt)。"""
    if stored is None:
        return (False, False)
    if len(stored) == 16 and scur[:16] == stored:
        return (True, True)
    return (scur == stored, False)
```

**语义澄清（回应 Hermes M-02）**：`scur` 恒为 128-bit（32 hex）；`stored` 基线可为 16-char（legacy 64-bit，v2.8.5 及更早）或 32-char（现行）。命中 16-char 分支 = 取当前 128-bit 哈希**前 16 字符**与 16-char 旧基线比较——**非** "截断 128-bit 基线为 16-char"。真实篡改（哈希全变）→ 前 16 字符必然不同 → 返回 `(False, ...)` 仍判漂移，故 P0-1 真实篡改防护成立。Hermes H-03 指认的**主动降级向量**另见 §五 P0-1 补注。

### 3.2 F-4（MANIFEST_NAMES + record/verify 分支）
```python
MANIFEST_NAMES = ("SKILL.md", "CONTRACT.md", "CHANGELOG.md", "HANDOFF.md", "pack.sh")
# record_script_integrity 内：对 MANIFEST_NAMES 逐个写 manifest: 键（warn 重基线）
# verify_integrity 内：if artifact.startswith("manifest:"): 非阻塞比对（_script_hash_matches + dirty 计数）
```

### 3.3 H-2（_audit_rollback 模块级 + cmd_rollback 接线）
```python
def _audit_rollback(st, code, entry_id, old_hash, new_hash):
    """v2.8.8 H-2：rollback 重基线完整性快照审计留痕，落盘 ledger/rollback-audit.jsonl。"""
    _audit = st.root / "ledger" / "rollback-audit.jsonl"
    _audit.parent.mkdir(parents=True, exist_ok=True)
    _entry = {"at": now_iso(), "operation": "rollback-rebaseline", "artifact": code,
              "entry_id": entry_id, "old_hash": old_hash, "new_hash": new_hash, "confirmed": True}
    with _audit.open("a", encoding="utf-8") as _f:
        _f.write(json.dumps(_entry, separators=(",", ":")) + "\n")
# cmd_rollback：st.record_integrity(code) 后调用 _audit_rollback(st, code, ..., _old_hash, new_hash)
```
注：`_audit_rollback` 原误置于 `Store` 类内（4 空格缩进），导致 `cmd_rollback` 模块级调用 `NameError`；v2.8.8 搬移至模块级（位于 `cmd_rollback` 之前），回归由 NameError 转为 57/57 PASS。

## 四、测试证据（self-attested，受管 python 逐文件聚合 · 2026-10-10 复跑确认）

- 新增断言：P0-1 ×2、F-4 ×5、H-2 ×8，合计 +15。
- **受影响两件套（实跑复验）**：`test-trust-root.py` **238/238**（v2.8.7 231 + 7 = P0-1 ×2 + F-4 ×5，全部落在 trust-root）、`test-d2-d5.py` **57/57**（v2.8.7 49 + 8 = H-2 ×8，全部落在 d2-d5）；两件套 2026-10-10 复跑均 `exit 0`（日志 `/tmp/trust-root-v288.txt`、`/tmp/d2-d5-v288.txt` 末行 "全文件总计: 238/238 PASS" / "57/57 PASS"）。
- **全量 24 套件 24/24 exit 0、0 FAIL、合计 645 PASS-line**（v2.8.7 630 + 15），零回归。仅 trust-root / d2-d5 两件套获得 +15 断言，其余 22 件套与 v2.8.7 基线一致、未改。
- **24 套件清单**（回应 Hermes L-02，均位于 `scripts/`，受管 python 逐文件跑）：
  1. test-benchmark.py
  2. test-cli-wiring.py
  3. test-domain-init.py
  4. test-domain-migration.py
  5. test-init-domain.py
  6. test-m1-auto-trigger.py
  7. test-meta-log-command.py
  8. test-meta-log.py
  9. test-p0-1-real-data.py
  10. test-p0-2-knowledge-transfer.py
  11. test-p2-2-domain-detector.py
  12. test-p2-3-visualize.py
  13. test-boundary-cases.py
  14. test-adaptive-ratchet.py
  15. test-meta-log-integration.py
  16. test-held-out.py
  17. test-utility-derivation.py
  18. test-attribution.py
  19. test-meta-policy.py
  20. test-p2-1-meta-optimizer.py
  21. test-human-gate.py
  22. test-core.py
  23. test-trust-root.py（v2.8.8 +7 断言）
  24. test-d2-d5.py（v2.8.8 +8 断言）
- 属 self-attested（同作者测试 + 本 Agent 实跑），非独立审计；Hermes 同栈非第三方（见 HANDOFF §2.8 / §3 铁律）。

## 五、诚实边界（v2.8.8）

- **P0-1**：GUARD 路径含 legacy 16-char 兼容，与 F-1/H-1 一致；保留 128-bit 增强；迁移由下次 record 自动完成。**P0-1 补注（Hermes H-03）**：legacy 16-char 分支命中即返回 `ok=True`，属**主动降级向量**——若攻击者能写 integrity.json（C-10 域可写），将 128-bit GUARD 记录截断为 16-char 即可令主路径放行。本版无迁移截止期 / 无迁移计数器，留 v2.8.9 治理（建议 ④）。
- **F-4（非阻塞设计）**：manifest 漂移检测纳入 verify_integrity dirty 计数（报告级），但**不进硬闸**——有意权衡（版本升级必然改 SKILL.md/CHANGELOG.md），属检测+报告而非 fail-closed 阻断。
- **H-2（`--yes` 无 TTY 校验）**：rollback 留痕已闭环，但 `--yes` 仍可由调用方程序化静态满足、无 TTY 校验；残余在 C-10 威胁模型内，留 v2.8.9 加 TTY 校验。
- **C-10 同源残余**：manifest:` 键与 rollback-audit.jsonl 分离存储仅削弱同域自指，未消除 integrity.json 同处可写 ledger 域、无签名的根问题。

## 六、复派裁定（铁律5 · Hermes v2.8.8 复派 · 2026-10-10）

- **复派工具**：`mcp__hermes__hermes_audit`，target = `skill:unclekk-metacog-self-evolve@2.8.8`，content = 本卷宗全文。
- **verdict**：⚠️ **CONDITIONAL-PASS（有条件通过）**——v2.8.8 三项修复在**代码层真实闭环**（代码证据 / 测试增补 +15 断言 / 诚实边界披露完整），但**目标裁定 PASS 自证不成立**：H-01 攻击链未断、H-03 降级向量未治、C-10 未解。Hermes 明确驳回 §六原"PASS / 或维持 CONDITIONAL-PASS"的自利措辞。

### 6.1 关键发现（Hermes v2.8.8 复派）

- **H-01 [HIGH] F-4 是纸面闭环**：manifest 漂移仅**非阻塞** dirty 计数，硬闸仍仅 `script:`——手改 SKILL.md 的 H-3 攻击链**完全保留**；CHANGELOG 原写 "F-4 … 闭环" 属语义偷换（"未检测"→"检测不阻断"是工程进步，非攻击链阻断）。→ **F-4 维持 OPEN**（诚实披露项）。
- **H-02 [HIGH] "目标裁定 PASS" 自证矛盾**：§六原文本先写 CLOSED 又承认 CONDITIONAL-PASS；异族视角维持 CONDITIONAL-PASS。
- **H-03 [HIGH] P0-1 legacy 16-char 分支 = 主动降级向量**：`_script_hash_matches` 命中 16-char 即返回 `ok=True`；若攻击者能改写 integrity.json（C-10 确认该域可写），将 128-bit 记录**主动截断为 16-char** 即可绕过主路径。无迁移截止期 / 无迁移计数器。→ 诚实边界须补此降级向量（见 §五 P0-1 补注）。
- **M-01**：H-2 留痕 `rollback-audit.jsonl` 与 integrity.json **同 ledger 域**、追加无锁、无 HMAC、无原子写——**同源伪造物**，信任根与被监控对象同源，等于零留痕。
- **M-02**：legacy 16-char 语义文本混用 64-bit / 128-bit（本卷宗 §3.1 warn 串 "64-bit"、§二处置段 "128-bit"）。已在 §3.1.1 贴真实 helper 源码澄清：**16 hex = 64-bit**；"前 16 字符比对" ≠ "截断基线"。
- **M-03**：self-attested 测试证据可信度下限（"未失败"≠"未遗漏"）。
- **M-04**：v2.8.7 的 `_audit_rollback` NameError 致 rollback 功能实际损坏，直至 v2.8.8 自审才发现——发布前缺 pre-release smoke test 强制跑 rollback 主路径。
- **M-05**：卷宗 AI 味 / 过度承诺（"evidence dossier"、"H-3 攻击链"、"目标裁定 PASS" 自利裁定）。
- **L-01**：F-4 非阻塞设计动机成立，但 SKILL.md 与 CONTRACT.md/HANDOFF.md 同权处理，粒度不足。
- **L-02**："24 套件"原未展开——本卷宗 §四 已补全 24 套件清单。

### 6.2 Hermes 建议（部分已内化本卷宗，部分排 v2.8.9）

- **复派前必改（已内化）**：① §六 裁定改 CONDITIONAL-PASS（已做）；② 异族实跑 sha256 + 测试（self-attested 已记，Hermes 同栈非第三方，见 HANDOFF §2.8）；③ 贴 helper 源码消 M-02（§3.1.1 已做）。
- **v2.8.9 修复项**：④ P0-1 补 legacy 窗口治理（迁移计数器 `legacy_guard_count` 写入 integrity.json + 硬切截止期）；⑤ F-4 补分文件硬闸（SKILL.md 版本头变更豁免、内容变更 + CONTRACT/HANDOFF/pack.sh 变更进硬闸、CHANGELOG 保留非阻塞）；⑥ H-2 `--yes` 补 `sys.stdin.isatty()` 校验；⑦ H-2 补审计保护（append-only + HMAC 派生自 GUARD_INTEGRITY_KEY，或双写系统事件日志）。
- **卷宗格式**：⑧ 展开 24 套件（§四 已做）；⑨ 修正测试增量自洽（§四 已做）；⑩ §二 改用语 "新增 X" → "新增 X 代码路径（未含独立验证）"（诚实降调，待 KK 授权措辞修正）。

### 6.3 诚实结论

- **P0-1**：代码层 CLOSED（真实篡改防护成立），但 **H-03 主动降级向量 OPEN**（C-10 前置）。
- **F-4**：**OPEN 维持**（H-01 攻击链未断；非阻塞检测 ≠ fail-closed 阻断）。
- **H-2**：**PARTIAL CLOSED**（留痕落地，但 `--yes` 无 TTY 校验 + 同源可伪造 两项 OPEN，留 v2.8.9）。
- **总裁定**：⚠️ **CONDITIONAL-PASS**，条件 = 建议 ④⑤⑥⑦ 排入 v2.8.9 里程碑；不声称独立审计通过。

---

## 七、v2.8.9 补充协议（KK 授权收口 ④⑤⑥⑦ · 铁律5 复派首派 NOT PASS → 二次修复 → 二次复派 NOT PASS · 2026-10-11）

### 7.1 v2.8.9 处置（CHANGELOG 块节选）
- **④ P0-1 legacy 窗口治理（H-03 降级向量收口）**：`Store` 新增 `LEGACY_HASH_CUTOFF_VERSION = (2, 9)` + `CURRENT_VERSION_TUPLE = (2, 8, 9)` + 类方法 `_legacy_hash_allowed(cutoff=None)`（当前版本 < cutoff → True；v2.8.9 仍 < (2,9) → True，legacy 仍放行、零效果仅推迟失效；`v2.9.0` < (2,9) → False → 起拒绝 16-char 基线）。`_script_hash_matches` 增 `allow_legacy=True` 形参——命中 16-char 且 `allow_legacy=False` 时返 `(False, True)`（强制迁移，不再放行主路径）。各 verify 调用点统一传 `allow_legacy=Store._legacy_hash_allowed()`（过截止期自动拒 16-char 基线）。`record_script_integrity` 写入 `__meta__`（`legacy_migrated` 迁移计数 / `legacy_remaining` 16-char 残余键统计）。`_manifest_integrity_drift_if_enforced` 末尾追加 `__meta__:legacy-remaining` 阻断（N-2 修正：任一制品尚有 16-char 残余即 fail-closed 拒绝，赋予强制迁移真实力，非仅计数）。⚠️ 首版误写 `(2, 10)`（N-1：实际 v2.10.x 才阻断非 v2.9.x），二次修复据 Hermes 首派 NOT PASS 裁定订正为 `(2, 9)`。
- **⑤ F-4 分文件硬闸（H-01 纸面闭环收口）**：SKILL.md 写 `manifest:SKILL.md`（含 version 字段）+ `manifest:SKILL.md@body`（正文哈希，version 行规为 `version: __CANON__` 后哈希）；其余 4 清单写 `manifest:<name>`。新增 `_manifest_integrity_drift_if_enforced(st)`（仅 STRICT/外部锚下强制）：阻断集 = SKILL.md 正文变更 + CONTRACT/HANDOFF/pack.sh 内容变更；CHANGELOG 跳过（`continue`，保留非阻塞检测）。接线 `cmd_apply` / `cmd_retrieve` / `_confirm_keygen`（rc=3 先闸后 `record_script_integrity` 避免升级死锁）。
- **⑥ H-2 `--yes` TTY 校验（建议 ⑥）**：`cmd_rollback` 复用既有 W1 `_require_tty()`（L3143）加非交互拒绝（stdin/stdout 非 TTY → return 2），防程序化 `SimpleNamespace(yes=True)` 静默 rollback 重基线洗白。
- **⑦ H-2 审计 HMAC/链（建议 ⑦ · 同源可伪造缓解）**：`_audit_rollback` 重写为 HMAC-SHA256 + `prev_hmac` 哈希链（每条含链上一跳 + 本跳 hmac），写入 `ledger/rollback-audit.jsonl`（与 integrity.json 分离）。`_audit_hmac_key` 优先派生自 human-guard 信任根内容（无则降级常量 `METACOG_FALLBACK_AUDIT_KEY_v289_C10`）；新增 `_verify_audit_chain(st)` fail-closed 校验（HMAC 篡改 / prev_hmac 重排 / 删除 / 伪造 → False）。**H-A1 收口（二次修复）**：首版 `_verify_audit_chain` 仅定义/被测试、零生产调用（死代码）。二次修复接入生产路径——`cmd_rollback` 入口先 `_verify_audit_chain`（链断裂 → rc=3 拒绝重基线 + 告警）；`cmd_verify` 巡检加链完整性（断裂计入 dirty → 返回 1）。`_verify_audit_chain` 失败返回口径由「已校验条数」改为「文件实际总条数」（count 语义修正）。新增 `test_d5_rollback_chain_broken_rejects`（5 断言：apply rc=0 / 篡改后链断 → False / 链断裂 rollback 拒绝 rc==3 / 拒绝后制品字节不变 fail-closed / R-CB 仍 active 未被二次重基线）。

### 7.2 诚实边界（v2.8.9）
- **④**：硬切截止期 (2,9) 约束「降级向量」（`v2.9.0` 起拒 16-char），但 C-10 根未根除——legacy 拒绝仅约束「降级向量」而非「可写域换根」防护。
- **⑤**：分文件硬闸仍仅 STRICT/外部锚强制（legacy 默认不锁死，与 F-2 一致）；CHANGELOG 维持非阻塞（版本升级权衡）→ H-3 攻击链在 legacy 默认下**仍未 fail-closed 阻断**（诚实：STRICT 启用才生效）。
- **⑥**：TTY 校验仅纵深防御（纯管道 stdin 直接拒），真实终端+人类确认的攻击者仍可通过（C-10 域可写本即高危）。
- **⑦**：HMAC 密钥派生自同处可写 ledger 域的 human-guard 信任根（C-10），无签名锚固 → 同源可伪造风险**仍 OPEN**（双写系统事件日志为根治，未做）。三项修复均属「缩小攻击面/提高门槛」，非 C-10 根闭合。

### 7.3 测试证据（self-attested · 受管 python 逐文件聚合 · 2026-10-11 二次修复后复跑）
- 全量 24 套件 → **24/24 OK、0 FAIL、合计 672 PASS-line**（v2.8.8 645 + 27：trust-root +14 / d2-d5 +13（⑥×4 / ⑦×4 / H-A1×5））。
- `test-trust-root.py` **252/252**（v2.8.8 238 + 14）：`test_f4_manifest_integrity_domain` 重写 +5 / `test_legacy_window_governance` 新增 +5 / 其他 +4。
- `test-d2-d5.py` **70/70**（v2.8.8 57 + 13）：`test_d5_rollback_yes_requires_tty` ⑥ ×4 / `test_d5_rollback_audit_chain` ⑦ ×4 / `test_d5_rollback_chain_broken_rejects` H-A1 ×5；既有 byte_restore/audit_trail 补 `_require_tty = lambda: True` 桩闭环校验。
- **回归修复**：`verify_integrity` 主循环补 `__meta__` 键跳过，修复 `record_script_integrity` 写入 `__meta__` 触发的 `ARTIFACTS['__meta__']` KeyError（影响 `test_c10_script_file_deletion_current_none` 等用例，已修复零回归）。
- 属 self-attested，非独立审计。

### 7.4 铁律5 Hermes 复派 v2.8.9（首派 NOT PASS · 2026-10-10）
- 派发 `mcp__hermes__hermes_audit`（target=`skill:unclekk-metacog-self-evolve@2.8.9`）→ 裁定 **❌ NOT PASS**（比预期 ⚠️ CONDITIONAL-PASS 更严）。核心可落地发现：H-A1（`_verify_audit_chain` 零生产调用=死代码）/ H-A2（C-10 同域换根绕过 ⑤）/ H-A3（④ 确定性降级攻击）/ N-1（截止期语义 `(2,10)` 实际 v2.10.x 才阻断非 v2.9.x）/ N-2（`__meta__` 过度声明、强制迁移无真实力）/ N-4（工作树畸形目录）。

### 7.5 二次修复 + 二次复派（待派发·最后派发 · 2026-10-11）
- **二次修复（KK 授权 v2.8.9 范围内 ④⑤⑥⑦ 缺陷收口，非 scope creep）**：H-A1（⑦ 接入 `cmd_rollback`/`cmd_verify` 生产路径）/ N-1（④ 截止期 `(2,10)`→`(2,9)`）/ N-2（④ `__meta__:legacy-remaining` 强制迁移真实力 fail-closed）/ N-4（畸形目录链 `shutil.rmtree` 删除，0 剩余）/ `_verify_audit_chain` 计数口径修正（失败返回文件实际总条数）/ `test_d5_rollback_chain_broken_rejects` 断言订正（验证 fail-closed 制品字节不变 + R-CB 仍 active）。全量 **24/24 OK、0 FAIL、672 PASS-line** 零回归。
- 修改已冻结（metacog.py / test-trust-root.py / test-d2-d5.py / SKILL.md / HANDOFF.md / 本卷宗 均落盘 + sha256 校验，见 CHANGELOG v2.8.9 冻结清单）。
- **二次复派（铁律5 最后派发）已执行·裁定 ❌ NOT PASS（2026-10-11，Hermes 重连后派发）**：Hermes 独立复跑 trust-root 252/252 + d2-d5 70/70 确认零回归（非仅采信 self-attested）；实跑对抗探针 8/8 攻击达成，挖出 4 项文档未披露的 blocking 缺陷：**H-1**（`verify_integrity` L1039 硬编码 `allow_legacy=True`，16-char 降级穿透全部硬闸+阻断路径后 `verify` 仍报绿色、运维零告警）/ **H-2**（`CURRENT_VERSION_TUPLE` 硬编码且与 SKILL.md version 零绑定断言，升级漏改即 ④ 截止期永久失效）/ **H-3**（⑦ 无 human-guard 时 HMAC 回退密钥硬编码于源码明文常量，且 ⑦ 默认部署不启用）/ **H-4**（⑤ `@body` 派生键期望值同源于被改文件重算，SKILL.md 正文可完整洗白，`@body` 不构成独立第二信号，N-2「强制迁移真实力」over-claim）。MEDIUM：M-1（`legacy_remaining` 仅覆盖 script:/manifest: 前缀、human-guard.json 等信任根域不计入，N-2 修复口径偏窄）/ M-2（④ v2.8.9 当版本净效果为零、攻击窗口仍全开）/ M-3（工作树残留 sync_v*.py/scripts/nul/dist/ 旧产物）。**诚实结论**：H-A1 死代码已闭合（✅）；H-A2/H-A3/⑦ 维持 OPEN（Hermes 实测复现）；N-2 修复方向对但覆盖错（M-1/H-4 揭示 `@body` 自指失独）——属 over-claim，已记入。H-1~H-4 + M-1 均超出原「授权 v2.8.9」范围，按「严格按指令修复·不擅自扩大」纪律未擅自修复，待 KK 授权 v2.9.0 收口。完整审计报告见 Hermes 返回全文（对抗探针 `hermes-audit-metacog-v289.py`）。
