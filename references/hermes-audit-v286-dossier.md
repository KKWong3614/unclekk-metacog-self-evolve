# 铁律5 统一复验卷宗 · unclekk-metacog-self-evolve v2.8.6

> 目标：复验 v2.8.6 是否真正闭环 Hermes v2.8.5 统一复验（2026-10-09）CONDITIONAL-PASS 裁定的 9 条升级阻点 N-1~N-9。
> 审计对象：真实工作树已同步至 `D:/skill待检/`（102 文件 faithful mirror，version=2.8.6，sha256 校验 metacog.py/test-trust-root.py 与 C: 一致）。
> 纪律：铁律5 = 修改一次性冻结后最后派发；本卷宗为 evidence dossier，不替代独立审计员判断。

## 一、v2.8.5 裁定（待复议的 9 条阻点 N-1~N-9）

- **N-1（H-2 子项）**：Hermes 指 H-2「实删 `__pycache__` 未真删」与磁盘事实不符——真实工作树（C:）`find -name __pycache__` 为空（H-2 主项已完成）；D: 残留 `__pycache__` 系 Hermes 自身在该路径跑测试由 Python 导入生成，`sync_v285_to_d.py` 当时未排除自身被拷入 D: 致下游产物残留。
- **N-2（.packignore 补全）**：`.packignore` 缺 `.gitignore` 已有而它缺的 `out.txt`/`err.txt`/`*.log`/`.DS_Store`，发布白名单与 git 忽略不一致。
- **N-3（keygen 硬闸顺序 + 幂等绕过）**：`cmd_confirm --keygen` 的脚本完整性硬闸位于"写 human_guard 之后"，且幂等早退分支（`_keys_exist and not _en → return 0`）完全绕过 → 篡改代码可借已建密钥静默跳过硬闸。
- **N-4（resign 硬闸零测试 + rollback 无闸）**：resign 硬闸无专门测试；`cmd_rollback` 无脚本完整性硬闸；STRICT 真值表只在 apply 站点验。
- **N-5 / N-7（四处硬闸复制粘贴 + 静默 fail-open）**：apply/resign/retrieve/keygen 四处各复制一份 `external_trust_root() is not None` + `except Exception: anchor=False` 静默 fail-open（异常被吞、无告警）。
- **N-9（哈希碰撞裕度）**：`_hash_text` 截断 `:16`（64 bit）碰撞裕度低。

## 二、v2.8.6 处置（CHANGELOG 块节选）

- **N-1**：经核实 H-2 主项（清工作树 `__pycache__`/junk）v2.8.5 已完成；v2.8.5 复议所见 D: 残留系下游测试产物 + sync 脚本未自排除，非本 skill 工作树脏数据。v2.8.6 已在 `.packignore` 排除 `scripts/__pycache__` 并修正 sync 脚本排除逻辑（写入 `sync_v286_to_d.py`，复用 .packignore，排除 sync 脚本自身/`__pycache__`/nul/`dist/`），如实标注，不谎称"未真删"亦不夸大未做之事。
- **N-2**：`.packignore` 补 `out.txt`/`err.txt`/`*.log`/`.DS_Store`（与 `.gitignore` 对齐）。
- **N-3**：`metacog.py` 将 keygen 硬闸移至 `_confirm_keygen` **函数顶部**（写 human_guard 之前，且覆盖幂等早退路径）；删除底部重复内联块。新增 `test_c10_keygen_idempotent_still_gates`（已建密钥+漂移+受保护模式→rc==3 拒；修正基线→rc==0 放行）。
- **N-4**：补 `test_c10_resign_hardgate_rejects`（resign 漂移→rc==3）；`cmd_rollback` 无硬闸仍 OPEN（留 KK 决策，见诚实边界）。
- **N-5 / N-7**：抽出模块级 helper `_script_integrity_drift_if_enforced(st)`（集中漂移计算；异常时 `warn()` 降级为仅依赖 STRICT、不再静默 fail-open），四处调用点统一委托；真值表测试 `test_c10_gate_helper_truthtable` 覆盖 8 分支。
- **N-9**：`_hash_text` 截断 `:16`→`:32`（128 bit）。

## 三、代码证据（scripts/metacog.py，v2.8.6）

### 3.1 集中硬闸 helper（模块级，置于 Store 类闭合之后，N-5/N-7）
```python
def _script_integrity_drift_if_enforced(st):
    if not st.integrity.exists():
        return (False, [])
    _anchor = False
    try:
        _anchor = st.external_trust_root() is not None
    except Exception as _e:
        warn("[完整性-硬闸] 外部锚检测异常（{}），降级为仅依赖 STRICT 环境变量；...".format(type(_e).__name__))
        _anchor = False
    if not (_anchor or os.environ.get("METACOG_TRUST_ROOT_STRICT", "").lower() == "1"):
        return (False, [])
    _drift = [k for k, ok in st.verify_script_integrity() if not ok]
    return (True, _drift)
```

### 3.2 调用点（apply/resign/retrieve/keygen 四处统一委托）
```python
    _a_enforced, _a_drift = _script_integrity_drift_if_enforced(st)
    if _a_drift:
        bad("[完整性-硬闸] ... 拒绝 apply ...：{}；...".format(", ".join(_a_drift)))
        return 3
```
（resign/retrieve/keygen 同构，仅 bad() 文案与命令名不同；原四处复制的 `external_trust_root() is not None` + `except Exception: anchor=False` 已归零，仅 helper 内保留 1 处并改为 warn 降级。）

### 3.3 keygen 顶部硬闸（N-3，覆盖幂等早退路径）
```python
    # v2.8.6 N-3：硬闸移至函数顶部（写 human_guard 之前，且覆盖幂等早退路径）
    _k_enforced, _k_drift = _script_integrity_drift_if_enforced(st)
    if _k_drift:
        bad("[完整性-硬闸] ... 拒绝 keygen ...：{}；...".format(", ".join(_k_drift)))
        return 3
    guard = read_json(st.human_guard, None)
    _en = getattr(args, "enable_external", None)
    _keys_exist = bool(guard and "pubkey" in guard and "privkey_enc" in guard)
    if _keys_exist:
        ...
        if not _en:
            ...
            return 0   # 幂等早退：现已在顶部闸之后，漂移必被拦截
```

### 3.4 _hash_text（N-9）
```python
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]  # v2.8.6 N-9：64-bit→128-bit 碰撞裕度
```

## 四、发布隔离（N-2 子集）

`.packignore`（负向排除：nul / results-full-*.txt / scripts/_run_all_tests.py / __pycache__ / *.pyc / sync_v*.py / clean_v*.py / out.txt / err.txt / *.log / .DS_Store / *.bak / *.tmp）+ `pack.sh`（基于 .packignore 确定性目录拷贝）。v2.8.6 经 `sync_v286_to_d.py` 镜像到 `D:/skill待检/`：102 文件 faithful mirror，无 `__pycache__`/nul/sync/_run_all_tests 等被排除产物。

## 五、回归测试（scripts/test-trust-root.py）

- `test_c10_keygen_idempotent_still_gates`（N-3）：已建密钥+漂移+受保护模式→cmd_confirm --keygen 幂等分支 rc==3 拒；修正基线→rc==0 放行（修复该测试缺失 TTY mock 夹具，使端到端可达）。
- `test_c10_gate_helper_truthtable`（N-5/N-7）：helper 8 分支（无基线/有基线无漂移/漂移未强制/STRICT=0/false/1/外部锚启用/异常降级）。
- `test_c10_resign_hardgate_rejects`（N-4）：resign 漂移→rc==3。
- 其余 c10 套件（orphan_key_cleanup / nested_package_integrity / script_integrity_hotpath_gate / script_file_deletion_current_none / trust_root_strict_truthtable / apply_hardgate_rejects / verify_dirty_includes_script_key / keygen_hardgate_rejects）继承 v2.8.5。

## 六、验证结果（self-attested + 受管 python，2026-10-10）

全量 24 套件 **24/24 exit 0、0 FAIL、零回归、合计 620 PASS-line**：`test-trust-root.py` **223/223**（v2.8.5 211 + 12 新增 c10 断言）、`test-human-gate.py` 69/69、`test-core.py` 14/14、`test-cli-wiring.py` rc=0。`metacog.py` 经 `ast` 校验 `Store.human_guard` 在类内、`Store.end_lineno=1240` 类体完整（v2.8.6 初版曾误将 helper 以 col-0 插入类体内致类提前闭合、`human_guard` 属性丢失，已回退 v2.8.5 干净基线 sha256 `9baa1bb5…e18ba0be` 校验匹配后正确重放）。

## 七、诚实边界（v2.8.6）

- **N-1/H-2 主项（清工作树 `__pycache__`/junk）v2.8.5 已完**；v2.8.5 复议所见 D: 残留为下游测试产物 + sync 脚本未自排除，非本 skill 工作树脏数据，已如实标注。
- `cmd_rollback` 仍无脚本完整性硬闸（N-4 部分 OPEN）：rollback 为回退动作，强制硬闸可能阻断合法回退；是否加闸（建议至少非阻塞告警）留 KK 决策。
- M-5 `integrity.json` 签名、`.git` 建仓、nul 残留（Windows 保留设备名，须 KK 提权 shell 手动清）三项仍 OPEN，同 v2.8.5。
- C-10 残余不变：基线 `integrity.json` 同处可写 ledger 域 + 无签名，攻击者改代码 + 重记基线仍不可检出（D4 同类，须部署契约兜底）。

## 八、请独立审计员裁定

1. N-3 keygen 硬闸移至函数顶部是否真正闭合「写先于闸」顺序缺陷 + 幂等早退绕过？幂等分支（已建密钥）在漂移场景下是否必被拦截？
2. N-5/N-7 集中 helper 是否彻底消除四处复制 + 静默 fail-open？异常降级（warn 而非崩溃/静默）是否恰当？是否存在 helper 自身未覆盖分支？
3. N-9 哈希 64→128 bit 是否足够且不破坏既有基线兼容（存量 integrity.json 仍存 :16 哈希的存量安装是否仍能 verify）？
4. N-1/H-2 诚实边界修正是否如实（v2.8.5 主项已完成、D: 残留系下游产物）？是否接受此标注？
5. N-2 `.packignore` 补全是有效发布隔离补全？nul 残留是否接受为已知 OPEN？
6. N-4 resign 硬闸测试是否足够？`cmd_rollback` 无闸的 OPEN 是否可接受，还是必须补（至少告警）？
7. 综合：v2.8.6 评级（PASS / CONDITIONAL-PASS / FAIL），及对 N-1~N-9 逐条是否 CLOSED？
