# 铁律5 统一复验卷宗 · unclekk-metacog-self-evolve v2.8.5

> 目标：复验 v2.8.5 是否真正闭环 v2.8.4 统一 Hermes 复验（2026-10-09）裁定的 3 条 HIGH 阻断 H-1/H-2/H-3。
> 审计对象：真实工作树已同步至 `D:/skill待检/`（104 文件 faithful mirror，version=2.8.5）。
> 纪律：铁律5 = 修改一次性冻结后最后派发；本卷宗为 evidence dossier，不替代独立审计员判断。

## 一、v2.8.4 裁定（待复议的 3 条 HIGH）

- **H-1**：`record_script_integrity` 只 add 不 delete；L-3 把 `domains/knowledge_transfer.py` 移出 `SCRIPT_NAMES` 后，v2.8.3 存量基线含该孤儿键 → `verify_integrity` 遍历全键报 dirty、`verify_script_integrity` 只遍历 SCRIPT_NAMES 不报 → 告警可信度自毁 + 存量安装 `verify` 永久 rc=1。
- **H-2**：M-6 `__pycache__` 未真删 + `.gitignore`≠发布隔离（`.gitignore` 只影响 git 索引、目录拷贝分发无效）+ 仓内 junk 游离。
- **H-3**：M-3/M-4 零回归测试（孤儿清理 / script 删键 current=None / STRICT 真值表 / apply 硬闸拒 rc=3 / verify dirty 含 script 键）。

## 二、v2.8.5 处置（CHANGELOG 块节选）

- H-1：`record_script_integrity` 加孤儿清理循环（删 `script:` 前缀且基名不在 SCRIPT_NAMES 的键；保留"名在但文件缺失"键检删除攻击）。
- H-2：实删 3×`__pycache__` + `CHANGELOG.md.bak` + `audit-brief-v2.5.5-sigcrypto.md` + 5×`hermes-verify-*.py`；新增 `.packignore`+`pack.sh` 确定性发布打包（替代 `.gitignore` 局限）。
- H-3：`test-trust-root.py` 新增 6 用例（见第五节）。
- M-2'：`cmd_resign`/`cmd_confirm --keygen` 落盘前插同款 `verify_script_integrity` 硬闸（漂移 return 3）。
- 附加：`METACOG_TRUST_ROOT_STRICT` 四处由 truthy 改严格 `== "1"`。

## 三、代码证据（scripts/metacog.py）

### 3.1 record_script_integrity（L877-902，H-1 孤儿清理）
```python
    def record_script_integrity(self):
        data = read_json(self.integrity, {})
        changed = False
        expected = {"script:" + n for n in self.SCRIPT_NAMES}
        for name in self.SCRIPT_NAMES:
            p = self.script_dir / name
            if not p.exists():
                continue
            data["script:" + name] = {
                "hash": self._hash_text(p.read_text(encoding="utf-8")),
                "size": p.stat().st_size, "at": now_iso(),
            }
            changed = True
        # v2.8.5 H-1：孤儿清理。仅删 "名称不在 SCRIPT_NAMES" 的 script: 键。
        for _k in [k for k in data if k.startswith("script:") and k not in expected]:
            del data[_k]
            changed = True
        if changed:
            write_json(self.integrity, data)
```

### 3.2 cmd_apply 硬闸（L1841-1852，M-4 + STRICT 严格化）
```python
    if st.integrity.exists():
        _a_anchor = False
        try:
            _a_anchor = st.external_trust_root() is not None
        except Exception:
            _a_anchor = False
        if _a_anchor or os.environ.get("METACOG_TRUST_ROOT_STRICT", "").lower() == "1":
            _a_drift = [k for k, ok in st.verify_script_integrity() if not ok]
            if _a_drift:
                bad("[完整性-硬闸] ... 拒绝 apply ...：{}；...".format(", ".join(_a_drift)))
                return 3
```

### 3.3 cmd_resign 硬闸（L2237-2248，M-2' 对称）
```python
    if st.integrity.exists():
        _r_anchor = False
        try:
            _r_anchor = st.external_trust_root() is not None
        except Exception:
            _r_anchor = False
        if _r_anchor or os.environ.get("METACOG_TRUST_ROOT_STRICT", "").lower() == "1":
            _r_drift = [k for k, ok in st.verify_script_integrity() if not ok]
            if _r_drift:
                bad("[完整性-硬闸] ... 拒绝 resign ...：{}；...".format(", ".join(_r_drift)))
                return 3
```

### 3.4 cmd_retrieve 硬闸（L2689-2699）
```python
    if st.integrity.exists() and (_anchor_active or os.environ.get("METACOG_TRUST_ROOT_STRICT", "").lower() == "1"):
        script_drift = [k for k, ok in st.verify_script_integrity() if not ok]
        if script_drift:
            bad("[完整性-硬闸] ... 可能为代码篡改：{}；...".format(", ".join(script_drift)))
            return 3
```

### 3.5 cmd_confirm --keygen 硬闸（L2921-2932，M-2' 对称）
```python
        if st.integrity.exists():
            _k_anchor = False
            try:
                _k_anchor = st.external_trust_root() is not None
            except Exception:
                _k_anchor = False
            if _k_anchor or os.environ.get("METACOG_TRUST_ROOT_STRICT", "").lower() == "1":
                _k_drift = [k for k, ok in st.verify_script_integrity() if not ok]
                if _k_drift:
                    bad("[完整性-硬闸] ... 拒绝 keygen ...：{}；...".format(", ".join(_k_drift)))
                    return 3
```

### 3.6 verify_integrity / verify_script_integrity（L904-952，M-3 遍历 script: 键）
- `verify_integrity`（cmd_verify 主告警路径）遍历 `script:` 键，文件被删 → `(artifact, False, rec.hash, None)` 纳入 dirty（含 current=None）。
- `verify_script_integrity` 遍历 SCRIPT_NAMES，文件缺失 → `(skey, False)`（保留删除检出）。

## 四、发布隔离（H-2 子集）

`.packignore`（负向排除：nul / results-full-*.txt / scripts/_run_all_tests.py / __pycache__ / *.bak / sync_v*.py / clean_v*.py）+ `pack.sh`（基于 .packignore 确定性目录拷贝）。实测 `bash pack.sh` → `dist/unclekk-metacog-self-evolve-2.8.5/` 101 文件，nul/results-full/_run_all_tests 正确排除。

## 五、回归测试（scripts/test-trust-root.py，注册于 main()，插在 test_c10_nested_package_integrity 后）

1. `test_c10_orphan_key_cleanup`（H-1）：注入孤儿键→重记后消失；删 SCRIPT_NAMES 文件→键保留且 verify 报 False。
2. `test_c10_script_file_deletion_current_none`（M-3）：verify_integrity 含被删脚本行、ok=False、current=None。
3. `test_c10_trust_root_strict_truthtable`（附加）：STRICT 未设/`0`/`false` → cmd_apply rc!=3；`=1` → rc==3。
4. `test_c10_apply_hardgate_rejects`（M-4）：外部锚+漂移→apply rc==3；修正基线后 rc!=3。
5. `test_c10_verify_dirty_includes_script_key`（H-3⑤）：漂移→cmd_verify rc==1。
6. `test_c10_keygen_hardgate_rejects`（M-2'）：外部锚+漂移→keygen rc==3。

## 六、验证结果（self-attested + 隔离 subagent，受管 python，2026-10-09）

全量 24 套件 **24/24 exit 0、0 FAIL、零回归**：`test-trust-root.py` **211/211**（v2.8.4 192 + 19 新增断言）、`test-human-gate.py` 69/69、`test-core.py` 14/14、`test-cli-wiring.py` rc=0。

## 七、诚实边界（v2.8.5）

- H-1/H-2/H-3 为本方 self-attested 修复 + 验证，**最终评级以铁律5 Hermes 复议为准**（不自称 PASS）。
- 仍 OPEN：① `scripts/nul`（Windows 保留设备名，标准 API 不可删，须 KK 提权 shell 手动清，已入 .packignore 排除）；② `.git` 建仓（改由 .packignore+pack.sh 发布隔离，不依赖 git）；③ M-5 `integrity.json` 签名（复用 v2.8.0 HMAC，留 KK 决策）。
- C-10 残余不变：基线 `integrity.json` 同处可写 ledger 域 + 无签名，攻击者改代码+重记基线仍不可检出（D4 同类，须部署契约兜底）。

## 八、请独立审计员裁定

1. H-1 孤儿键清理逻辑是否真正闭合存量 dirty + 告警/硬闸分裂？孤儿清理是否误删"删除攻击"键（保留性）？
2. H-2 仓库清洁是否充分？`.packignore`+`pack.sh` 是否构成有效发布隔离（对比 `.gitignore` 局限）？nul 残留是否接受为已知 OPEN？
3. H-3 六测试是否真正覆盖 M-3/M-4 回归面？是否存在未测分支？
4. M-2' 硬闸对称是否完整（apply/retrieve/resign/keygen 四处一致）？
5. STRICT 严格化是否一致且语义正确？
6. 综合：v2.8.5 评级（PASS / CONDITIONAL-PASS / FAIL）？
