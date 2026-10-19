# 铁律5 统一复验卷宗 · unclekk-metacog-self-evolve v2.8.7

> 目标：复验 v2.8.7 是否真正闭环 Hermes v2.8.6 统一复验（2026-10-10）⚠️ CONDITIONAL-PASS 裁定暴露的发布阻断 F-1 及诚实性缺陷 F-2/F-3/F-5/F-6。
> 审计对象：真实工作树已同步至 `D:/skill待检/`（103 文件 faithful mirror，version=2.8.7，sha256 校验 metacog.py/test-trust-root.py/test-d2-d5.py 与 C: 一致）。
> 纪律：铁律5 = 修改一次性冻结后最后派发；本卷宗为 evidence dossier，不替代独立审计员判断。

## 一、v2.8.6 裁定（待复议的 F-1~F-7）

Hermes v2.8.6 复议对 N-1~N-9 的逐项裁定：N-1✓ / N-2✓ / N-3✓(条件) / N-4 PARTIAL / N-5✓ / N-7✓ / N-9✗(新增阻断 F-1)。并挖出 7 条诚实性/残留发现：

- **F-1（N-9 迁移兼容 · 发布阻断）**：v2.8.6 将 `_hash_text` 由 `:16`(64-bit) 改为 `:32`(128-bit)，但 `verify_script_integrity` / `verify_integrity` 对基线哈希做裸等值比较 `scur == srec.get("hash")`。存量 v2.8.5 及更早基线（16 字符）升级到 v2.8.6+(32 字符) 即被全量判漂移；强制模式（外部锚启用或 `METACOG_TRUST_ROOT_STRICT=1`）四路径（apply/resign/retrieve/keygen）全 `return 3` 锁死，且 v2.8.6 CHANGELOG 零披露。
- **F-2（legacy 默认闸失能未披露）**：N-3/N-5 集中硬闸 `_script_integrity_drift_if_enforced` 仅在「外部锚启用 **或** `METACOG_TRUST_ROOT_STRICT=1`」时才拒绝漂移；**legacy 默认（无外部锚、无 STRICT）下硬闸是 no-op（返回 `(False, [])`），不拦任何篡改**。v2.8.6 诚实边界未披露此限制。
- **F-3（rollback 洗白）**：`cmd_rollback` 原无完整性相关约束，其 `record_integrity` 重基线动作缺乏人类确认，且 `--artifact` 校验仅依赖 argparse（程序化直调可绕过），存在借 rollback 重基线代码完整性域的残余风险。
- **F-4（manifest 不在完整性域）**：manifest（SKILL.md 等清单文件）未被纳入 D4 脚本完整性快照，攻击者改 manifest 不触发硬闸。
- **F-5（动机错乱）**：v2.8.6 将 N-9 动机写为「降低基线哈希碰撞导致的误拒/误放」，表述误导（哈希加宽本质是降低碰撞概率，非解决「误拒」）。
- **F-6（CHANGELOG「其余未改」不实）**：v2.8.6 冻结清单称「其余文件（SKILL.md/CHANGELOG.md/HANDOFF.md/.packignore/pack.sh 等）同 v2.8.5 冻结哈希，本版未改」——不实：v2.8.6 实际改了 `SKILL.md`(version)、`CHANGELOG.md`(新块)、`.packignore`(N-2)。
- **F-7（报告缺评级）**：v2.8.6 卷宗未给最终评级，仅列裁定请求，未下结论。

## 二、v2.8.7 处置（CHANGELOG 块节选）

- **F-1**：抽静态 helper `_script_hash_matches(scur, stored)`——当 `stored` 长度 16 且 `scur[:16] == stored` 命中旧格式兼容分支，判 `ok=True` 并 `warn` 提示重基线；其余走精确等值。`verify_script_integrity` 与 `verify_integrity` 两处裸等值均委托此 helper。**保留 `_hash_text` 的 `:32`（128-bit）不回退**；下一次 `record_script_integrity`（keygen/apply 落盘时）自动将 16-char 基线改写为 128-bit，迁移一次性完成。新增 `test_c11_legacy_16char_baseline_compatible`（5 断言）。
- **F-2**：诚实边界显式披露 N-3/N-5 硬闸 legacy 默认 no-op、不拦篡改；须显式启用外部锚或 `STRICT=1` 才获保护。
- **F-3**：`cmd_rollback` 顶部加两道闸——① `--artifact` 必须 ∈ `ARTIFACTS`（函数内再校验，防御程序化直调绕过 argparse）；② 新增 `--yes` 显式人类确认（重基线完整性快照须人类确认）。rollback 设计仅作用于 `ARTIFACTS` 制品码，不触碰 `script:` 域。更新 `test_d5_rollback_byte_restore`(加 yes) + 新增 `test_d5_rollback_f3_guards`。
- **F-4**：**仍 OPEN**——超出 KK v2.8.7 授权范围，留后续版本（已如实标注）。
- **F-5**：N-9 动机改为「降低基线哈希碰撞概率（128-bit 较 64-bit 碰撞空间指数级增大）」。
- **F-6**：纠正 v2.8.6 冻结清单不实声明；v2.8.7 冻结清单按**真实按文件 sha256** 列出变动文件（CHANGELOG.md 因自引用不列哈希，已注明）。
- **F-7**：本卷宗补明确评级（见第八节）。

## 三、代码证据（scripts/metacog.py，v2.8.7）

### 3.1 长度兼容 helper（F-1）
```python
@staticmethod
def _script_hash_matches(scur: str, stored) -> "tuple[bool, bool]":
    """v2.8.7 F-1 迁移兼容：基线哈希长度兼容比对。
    当前哈希恒为 128-bit（32 hex）；存量 v2.8.5 及更早基线为 64-bit（16 hex）。
    若 stored 长度为 16 且 scur[:16] == stored → 命中旧格式兼容分支，判 ok=True、legacy_fmt=True
    （调用方应 warn 提示重基线；下一次 keygen/apply 的 record_script_integrity 会将其自动升级为 128-bit）。
    返回 (ok, legacy_fmt)。"""
    if stored is None:
        return (False, False)
    if len(stored) == 16 and scur[:16] == stored:
        return (True, True)
    return (scur == stored, False)
```

### 3.2 verify_script_integrity（硬闸路径，F-1）
```python
            scur = self._hash_text(sp.read_text(encoding="utf-8"))
            _ok, _legacy = self._script_hash_matches(scur, srec.get("hash"))
            if _legacy:
                warn("[完整性] 检测到 64-bit 旧格式基线哈希（{}）；已按首 16 字符判定未篡改，"
                     "建议运行 keygen/apply 自动升级为 128-bit 基线。".format(skey))
            out.append((skey, _ok))
```

### 3.3 verify_integrity（cmd_verify 非阻塞告警路径，F-1）
```python
                _cur = self._hash_text(_sp.read_text(encoding="utf-8"))
                _ok, _legacy = self._script_hash_matches(_cur, rec.get("hash"))
                if _legacy:
                    warn("[完整性] 检测到 64-bit 旧格式基线哈希（{}）；...".format(artifact))
                out.append((artifact, _ok, rec.get("hash"), _cur))
```

### 3.4 cmd_rollback 两道闸（F-3）
```python
    code = args.artifact
    if not code:
        bad(add_fix("rollback 需指定 --artifact", "--artifact A1/A2/A3/A4/M1"))
        return 2
    # v2.8.7 F-3：rollback 仅作用于合法 ARTIFACTS 制品码，绝不接受 script: 域或其他任意键
    if code not in ARTIFACTS:
        bad(add_fix("rollback --artifact 必须是合法制品码（A1/A2/A3/A4/M1），不接受 script: 域或其他键",
                    "--artifact A1/A2/A3/A4/M1"))
        return 2
    ...
    # v2.8.7 F-3：rollback 会重基线制品完整性快照，须人类显式 --yes 确认
    if not getattr(args, "yes", False):
        bad(add_fix("rollback 将重基线制品 {} 的完整性快照，须显式 --yes 确认".format(code),
                    "人类确认后加 --yes 再执行"))
        return 2
```
（argparse 层 `rb.add_argument("--yes", action="store_true", ...)` 亦已加。）

## 四、迁移路径（F-1 消除升级锁死）

存量 v2.8.5 安装（16-char 基线）升级到 v2.8.7 后：
1. `verify_script_integrity` / `verify_integrity` 命中 16-char 兼容分支 → 判未篡改（`warn` 提示），**不锁死**；
2. 强制模式（外部锚/STRICT=1）硬闸 `drift` 为空 → 四路径不 `return 3`；
3. 下一次 keygen/apply 的 `record_script_integrity` 将基线改写为 128-bit → 迁移完成。

## 五、回归测试（scripts/test-trust-root.py + test-d2-d5.py）

- `test_c11_legacy_16char_baseline_compatible`（F-1）：① verify ok=True；② verify_integrity 兼容；③ STRICT=1 不锁死(drift 空)；④ 真实篡改仍判漂移(ok=False)；⑤ record 自动升级 128-bit。5/5。
- `test_d5_rollback_f3_guards`（F-3）：无 --yes 拒绝(rc==2)；非法 artifact(script:) 拒绝(rc==2)。2/2。
- `test_d5_rollback_byte_restore` 加 `yes=True` 仍 5/5（既有行为不变）。

## 六、验证结果（self-attested + 受管 python，2026-10-10 · 含 H-1 补全后重跑）

全量 24 套件 **24/24 exit 0、0 FAIL、零回归、合计 630 PASS-line**（断言级口径；v2.8.6 620 + 10：test-trust-root +8 / test-d2-d5 +2）：`test-trust-root.py` **231/231**（v2.8.6 223 + 8 新增 c11：script: 键 5 + 非 script: 制品键 3）、`test-d2-d5.py` **49/49**（含 7 个测试函数；v2.8.6 47 + 2 新增 F-3）、`test-human-gate.py` 69/69、`test-core.py` 14/14、`test-cli-wiring.py` rc=0。属 self-attested，非独立审计。

## 七、诚实边界（v2.8.7）

- **F-1 迁移兼容**：16-char 旧基线按首 16 字符判定未篡改并 `warn`，不锁死；保留 128-bit 增强；迁移由下次 record 自动完成。
- **F-2 legacy 失能**：N-3/N-5 硬闸默认 legacy（无外部锚/无 STRICT）为 no-op，不拦篡改；须显式启用外部锚或 STRICT=1。
- **F-4（manifest 不在完整性域）仍 OPEN**：超出 KK v2.8.7 授权范围，留后续版本。
- **F-7（报告缺评级）**：本卷宗第八节补明确评级。
- M-5 `integrity.json` 签名、`.git` 建仓、nul 残留（Windows 保留设备名，须 KK 提权 shell 手动清）三项仍 OPEN。
- C-10 残余不变：基线 `integrity.json` 同处可写 ledger 域 + 无签名，攻击者改代码 + 重记基线仍不可检出（D4 同类，须部署契约兜底）。

## 八、最终评级（F-7 补全）

**裁定：⚠️ CONDITIONAL-PASS（H-1 补全后可复议为 PASS）**

- F-1（发布阻断）已闭环（含 H-1 非 script: 分支补全）：存量升级不再锁死，保留 128-bit 增强 + 自动迁移；script: 与非 script: 两分支均有回归覆盖（共 8 断言）。
- F-2/F-5/F-6 诚实性已修正：legacy no-op 披露、N-9 动机去误导、冻结清单按真实哈希列示（CHANGELOG.md 自引用不列哈希已注明）。
- F-3 已硬化（部分闭环）：制品码校验 + --yes 人类确认；H-2 残余（--yes 静态可满足、无留痕）在 C-10 威胁模型内，留后续版本。
- 残留 OPEN 项（F-4 manifest 不在完整性域 / H-3 攻击链 / M-5 签名 / C-10 ledger 同可写域 / nul / .git）均为 v2.8.x 已知、已披露、非本版回归引入。

**条件（若审计员坚持）**：F-4（manifest 纳入完整性域）建议在 v2.8.8 处理；其余 OPEN 项为长期已知边界，不视为本版缺陷。

## 十、首轮 Hermes 复议结果（2026-10-10 · 铁律5）与 H-1 补全

**Hermes 首轮裁定：❌ NOT-PASS。** 卷宗自评「建议升级为 PASS」不成立，阻断项 H-1 实测反例：

- **H-1（阻断）**：`_script_hash_matches` 只在 script: 分支被调用；`verify_integrity` 非 script: 分支（L951）仍是裸等值 `cur == rec.get("hash")`，从未委托 helper。探针实测 A1 制品基线截为 16-char 后 `verify_integrity` 返回 `('A1', False, ...)`——存量升级仍被误判漂移。影响 A1~A4/M1 五制品 + human-guard + applies + trust-root + external-anchor-sentinel 共 9 类非 script: 键。`test_c11` 原 5 断言只测 script:metacog.py，盲区致漏修。**已补全**：非 script: 分支同样委托 helper + 加 legacy warn；新增 `test_c11_legacy_16char_artifact_baseline_compatible`（3 断言）覆盖盲区。
- **H-2**：F-3 `--yes` 静态可满足（`SimpleNamespace(yes=True)` 过闸）、无 TTY 校验、无留痕；攻击面从代码域移到制品域。→ F-3 标记为 PARTIAL，H-2 残余在 C-10 模型内。
- **H-3**：F-4「不影响安全」推定有反例——手改 SKILL.md 不触发硬闸，叠加 F-3 rollback 重基线构成攻击链。→ F-4 留 v2.8.8，已标注攻击链风险。
- **M-1**：测试计数口径混用（CHANGELOG 写 test-d2-d5 7/7 函数数，实测 49/49 断言数）。→ 已统一为断言级口径：test-trust-root 231/231、test-d2-d5 49/49、合计 630 PASS-line。
- **M-2**：冻结清单仅覆盖 5/103 文件、无签名。→ 已注明属 self-attested、v2.8.6 哈希仍可于上方 v2.8.6 节回溯。
- **同步纪律**：派发树漏卷宗本体（references/hermes-audit-v287-dossier.md）——因首轮 sync 早于卷宗创建；重派前已重跑 sync 使 D: 含卷宗。

**复派请求**：H-1 已补全、M-1 口径已修正，请 Hermes 就 v2.8.7（含 H-1 补全）复议，目标评级 PASS（F-1~F-7 处置：F-1 CLOSED / F-2 CLOSED / F-3 PARTIAL(H-2) / F-4 OPEN(H-3) / F-5 CLOSED / F-6 PARTIAL / F-7 CLOSED）。

## 九、请独立审计员裁定

1. F-1 长度兼容 helper 是否真正消除存量升级锁死，且不削弱真实篡改检测（16-char 基线 + 真实内容变更仍判漂移）？
2. F-1 迁移路径（warn → 下次 record 自动升级 128-bit）是否可接受为「非锁死迁移」？是否要求显式迁移命令而非依赖下次 record？
3. F-2 legacy no-op 披露是否充分？是否接受「legacy 默认不拦篡改」为已知边界？
4. F-3 制品码校验 + --yes 是否实质消除「借 rollback 洗白」残余风险？rollback 不触碰 script: 域的事实是否足以闭合 Hermes 字面所指？
5. F-6 冻结清单修正（真实按文件哈希、CHANGELOG.md 自引用不列哈希）是否诚实充分？
6. F-4（manifest 不在完整性域）留 v2.8.8 是否可接受，还是必须本版处理？
7. 综合：v2.8.7 评级（PASS / CONDITIONAL-PASS / FAIL），及对 F-1~F-7 逐条是否 CLOSED？

## 十一、复派结果（2026-10-10 · 铁律5 最后派发）

Hermes 复派裁定：**⚠️ CONDITIONAL-PASS（与首轮一致，未晋级 PASS）**。

- **审计对象确认**：Hermes 报告其审计的 `metacog.py` md5 = `7696dcfdc7c310bd375fd4fc8b7d78bf`，与本工作树 v2.8.7 `scripts/metacog.py` 完全一致 → 复派针对正确文件（非 `dist/unclekk-metacog-self-evolve-2.8.5/` 旧构建；该 `dist/` 仍为 2.8.5 构建产物，与本审计无关）。
- **H-1 非 script: 分支补全 = 已确认闭环**：V5 行为探针证实 artifact 域（非 script: 制品键）legacy 16-char 基线经 `_script_hash_matches` 判定未篡改（helper 接受 / 裸 `==` 拒绝，同输入差分证明补丁生效）；本工作树 `grep` 确认 L940/L951/L976 三处均委托 helper，且 `test-trust-root.py` 231/231（含 `test_c11_legacy_16char_artifact_baseline_compatible` 3 断言）实测通过。Hermes V2 静态扫描「_script_hash_matches 不在 cmd_verify 区间」为误报（其扫描区间未覆盖 L951 非 script: 分支）。
- **P0-1（新阻断·真实残余）**：Hermes 指出 `cmd_verify` 中 `GUARD_INTEGRITY_KEY`（human-guard 信任根）检查 **L2784 仍为裸等值 `gcur != grec.get("hash")`**，且 `verify_integrity` 于 L929 `continue` 跳过该键 → legacy 16-char 兼容 helper **未覆盖 human-guard 路径**。存量 v2.8.5 human-guard 基线（16-char）升级后该检查仍误判漂移。此为本版 F-1 迁移兼容的盲区，致评级维持 CONDITIONAL-PASS。本工作树已实读 L2784 确认裸等值、L929 确认 `continue` 跳过，P0-1 成立。
- **P0-2（H-2 同源·PARTIAL 残余）**：`cmd_rollback` 的 `--yes` 闸为静态 bool（`getattr(args, "yes", False)`），无 `_require_tty` 调用、无 TTY 校验、无留痕；确认 PARTIAL 残余在 C-10 威胁模型内。
- **F-4**：SKILL.md/CONTRACT.md 不在完整性域（引擎受保护、二者未受保护），留 v2.8.8。

**结论**：v2.8.7 的 H-1（verify_integrity 非 script: 分支）确已修复并验证，但 GUARD 路径（L2784）遗留同类裸等值缺口（P0-1），F-1 迁移兼容不完整 → 复派仍为 ⚠️ CONDITIONAL-PASS。P0-1 超出 KK 原授权「修 H-1（verify_integrity 非 script: 分支）」范围，按「严格按指令修复·不擅自扩大」纪律，本 turn 只评不改、不补 GUARD 路径；待 KK 授权后并入 v2.8.8（L2784 改委托 `_script_hash_matches` + 新增 GUARD legacy 回归断言 + 重测 + 复派）。
