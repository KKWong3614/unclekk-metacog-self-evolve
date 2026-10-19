# 异族独立审计报告 — unclekk-metacog-self-evolve v2.6.6

审计员：Hermes（异族独立审计员，与 WorkBuddy 生态无关）
审计对象：`C:\Users\Administrator\.workbuddy\skills\unclekk-metacog-self-evolve\` v2.6.6
审计方式：直读磁盘真实文件 + 实跑验证（不采信自评）
日期：2026-09-30

---

## 一、总体评级

**⚠️ 有条件通过（CONDITIONAL）— 维持**

v2.6.6 声称的改动**全部为真**，285/285 我独立复现成功。但本轮审计在 `attestation_ok`
同一函数体内发现 **6 条新的「损坏输入逃逸」路径**，其中 5 条可经
`check_pubkey_root` 端到端无捕获升级、把 Python traceback 打到 CLI。它们与 v2.6.6 自称修复的
「损坏输入逃逸」属**同一缺陷类别**，修复只覆盖了类别中的一个实例。

---

## 二、关键发现清单

### 【高】M1 — 6 条新逃逸向量，attestation_ok 的 fail-closed 契约仍不成立

文件：`scripts/trust_root.py` L246-271 `HsmTrustRoot.attestation_ok`

我写了独立对抗探针（**不使用技能自带测试**），对 attestation 文件喂 19 种病态输入。
结果：**19 中 6 条逸出异常**，其中 4 条完全在 v2.6.6 新增的 `try/except (ValueError, OSError)`
覆盖范围之外：

| 输入 | 逃逸异常 | 逃逸位置 | 与 v2.6.6 新增 try 的关系 |
|---|---|---|---|
| `{"pubkey":"P","attest":12345}`（int） | `TypeError: argument should be a bytes-like object or ASCII string, not 'int'` | L265 b64decode | **在 try 内，但 TypeError∉(ValueError,OSError) → 漏网** |
| `{"pubkey":"P","attest":true}`（bool） | `TypeError: ... not 'bool'` | L265 | 同上，**漏网** |
| attestation 顶层 = `[...]` 数组 | `AttributeError: 'list' object has no attribute 'get'` | **L260** `rec.get("pubkey")` | **在 try 外，完全未保护** |
| attestation 顶层 = `null` | `AttributeError: 'NoneType' object has no attribute 'get'` | L260 | 同上 |
| attestation 顶层 = `"hello"` | `AttributeError: 'str' object has no attribute 'get'` | L260 | 同上 |
| attestation 顶层 = `12345` | `AttributeError: 'int' object has no attribute 'get'` | L260 | 同上 |

**关键对比 — 同类缺陷在别处已修，此处漏修：**

- `TrustRootConfig.load()` L155 显式做 `if not isinstance(d, dict): return cls(corrupt=True, ...)`
  防御"JSON 标量穿透令 d.get 抛 AttributeError"（注释写"v2.6.4 ①"）。
  → **完全相同的病态输入模式，在 `attestation_ok` 里 L260 没有任何 isinstance 守卫。**
- `metacog.py` L856-873 对 `verify_human_binding` 路径做了 `try: b64decode except Exception: "bad-sig-encoding"`
  和 `try: deserialize_pub except Exception: "bad-pubkey"` 的契约保持。
  → **同样的 (bool,str) 契约保持纪律，`attestation_ok` 的调用点 L729 没有。**

**端到端升级已实证。** 我复用技能的 fixture 构造真实场景（初始化 Store → keygen → 启用
hsm+oob → 写合法证明 → 消费 OOB 令牌 → 把证明通过 → 然后污染证明文件再验），
5 条全部**无捕获逸出**，`check_pubkey_root` 不返回 (bool,str) 而是直接抛异常：

```
[X] JSON top-level = array   -> UNCAUGHT ESCAPE: AttributeError: 'list' object has no attribute 'get'
[X] JSON top-level = null    -> UNCAUGHT ESCAPE: AttributeError: 'NoneType' object has no attribute 'get'
[X] JSON top-level = string  -> UNCAUGHT ESCAPE: AttributeError: 'str' object has no attribute 'get'
[X] attest = int 12345       -> UNCAUGHT ESCAPE: TypeError: ... not 'int'
[X] attest = bool true       -> UNCAUGHT ESCAPE: TypeError: ... not 'bool'
end-to-end through check_pubkey_root:  escapes=5  failclosed=0
VERDICT: ESCALATES UNCAUGHT
```

**影响边界（诚实，不夸大）：** 无捕获异常 ≠ 认证绕过。异常发生在 `if not ok_a` **之前**，
所以攻击者**无法借此放行**，最坏是崩溃而非越权 —— 不构成安全绕过，**评级不上调**。
但这是运维级健壮性缺陷：attestation 文件被意外截断/被写入非 JSON 内容/磁盘损坏时，
运维拿到的是 traceback 而非可诊断的 reason 码，排障成本上升。且它明确违反 v2.6.6
自己声称的「打断 fail-closed 路径」判据 —— 该判据是本轮修复的唯一理由，现在仍不成立。

**严重度定级说明：** 定为【高】而非【中】，因为 (a) 与 v2.6.6 自称修复的是同一缺陷类别，
(b) `load()` 的同类守卫就在同一文件里，属"同类已修、此处漏修"的审计红线，
(c) 5/5 端到端无捕获已实证，非推测。但**不上调安全评级**，因为无认证绕过路径。

---

### 【中】M2 — v2.6.6 的修复是"单实例补丁"，未收口缺陷类别

v2.6.6 注释（L262-263）把该问题定性为"与 P1-④ 同类「损坏输入逃逸」"。但实际改动
`except (ValueError, OSError)` 只挡住了 `binascii.Error`（ValueError 子类）**这一条**：

- 同一表达式 `base64.b64decode(rec.get("attest",""))` 遇非 str 抛 **TypeError**，未被捕获；
- L260 `rec.get(...)` 遇非 dict 抛 **AttributeError**，在 try 外根本无保护；
- `OSError` 对 `b64decode` **完全不可达**（纯内存函数），属无意义的死捕获，且暗示作者
  并未逐条枚举该表达式真实的异常谱。

结论：本轮是"按症状打补丁"而非"按类别收口"。建议见第三节。

---

### 【低】L1 — `attest=None` 与 `attest=[]` 静默降级为 "attestation-forged"

实测：`attest=None`（key 存在）、`attest=[]`、`attest={}` 三者都**不逸出**，但返回
`(False, "attestation-forged")`。原因：`if rec.get("attest") else b""` 判定它们为 falsy →
`sig=b""` → 走到 `key_provider.verify` → HMAC 不匹配 → "forged"。

fail-closed 方向正确，**不逸出**，所以不是漏洞。但语义标签错误：这些是**格式损坏**，
不是**伪造**，运维会被 reason 码误导。属低危观测性问题。

---

### 【确认安全】L2 — L257/292/332 三处 `except Exception` 复核为真安全

按要求复核，三处均为 fail-closed 方向：

- L257（`attestation_ok` 读 attestation JSON）：`except Exception → return False, "attestation-malformed"` ✓
- L292（`OobTrustRoot.oob_confirmed` 读令牌）：`except Exception → return False` ✓
- L332（`_is_protected` 的 `os.access`）：`except Exception: pass` → 落入 `return True`
  ✓ —— 注意此处置为"受保护"是**宽松方向**，但 `_is_protected` 被文档明确标注为
  "检测用、非 fail-closed、默认 WARN-only"（L321-325），主控制是 OS 级权限隔离，
  故此处宽松不构成绕过。**维持上一轮"非缺陷"裁定，但我补充此条为已知宽松点备案。**

### 【确认安全】L3 — L332 断链 symlink 判据复核

L327-330 先判 `is_symlink()` 再判 `exists()`，注释理由（断链 symlink 会被 exists()
短路成 None 而漏判）成立。实测无问题。

---

## 三、针对性改进建议（可落地）

**S1（必修，收口 M1）** — 把 `attestation_ok` 的 JSON 结构校验前置，与 `load()` 对齐：

```python
        try:
            rec = json.loads(Path(ap).read_text(encoding="utf-8"))
        except Exception:
            return False, "attestation-malformed"
        # 与 TrustRootConfig.load() L155 的 v2.6.4 ① 守卫对齐：非 dict 一律 malformed
        if not isinstance(rec, dict):
            return False, "attestation-malformed"
        # 证明须覆盖当前公钥
        if rec.get("pubkey") != pub_serialized:
            return False, "attestation-pubkey-mismatch"
        raw = rec.get("attest", "")
        # 类型守卫：非 str 不喂给 b64decode（堵 TypeError）
        if not isinstance(raw, str):
            return False, "attestation-malformed"
        try:
            sig = base64.b64decode(raw) if raw else b""
        except (ValueError, OSError):
            return False, "attestation-malformed"
```

这样 6 条逃逸全部闭合，且 reason 语义正确（损坏→malformed，不再错标 forged）。

**S2（建议，堵 TypeError 的另一路径）** — 或直接把 L266 的捕获收窄为
`except (ValueError, TypeError)`，并删掉不可达的 `OSError`。但需同时做 S1 的 isinstance
守卫，否则 L260 的 AttributeError 仍在 try 外。

**S3（建议，纵深）** — `metacog.py` L729 调用点加一层契约保持兜底
（对齐 L864/L872 的既有模式），使 `attestation_ok` 即使未来再引入新逃逸，
`check_pubkey_root` 仍返回 (bool,str) 而非抛异常：

```python
            try:
                ok_a, reason_a = ext.attestation_ok(pub_serialized)
            except Exception:
                return False, "external-anchor-attestation-error"
```

**S4（补测试，对齐本轮实证）** — 新增用例应覆盖：attestation 顶层为非 dict（4 形态）、
attest 为非 str（int/bool）。当前 `test_attestation_ok_malformed_base64_failclosed`
只测了**字符串型**非法 base64 一个形态，广度与递归测试的 4 形态参数化不对等。

---

## 四、四问裁定

**Q1：MEDIUM-LOW（attestation_ok b64decode 逃逸）是否代码级闭合？**
→ **该单一实例闭合。** L264-267 的 `try/except (ValueError, OSError)` 真实存在，
非法**字符串型** base64（`"not!!valid==base64"`、`"abc"`、`"AAAAA"`、`"\ud800"`）
实测全部返回 `(False, "attestation-malformed")`，不逸出 `binascii.Error`。我独立实跑
`test_attestation_ok_malformed_base64_failclosed` PASS。**但缺陷类别未闭合**（见 M1/M2）。

**Q2：Q3 测试广度缺口是否补齐？**
→ **表面补齐，实质有缺口。** 三项均已落盘且实测生效：递归 4 形状
（list-50k/dict-50k/mixed-25k/list-200k 全 PASS）、Windows `st_file_attributes` 直查
（json+sentinel 两项全 PASS）、新 b64decode 测试 PASS。
**但新增测试只覆盖了 1 个形态（字符串型非法 base64），未覆盖非 str attest 与非 dict 顶层 ——
恰好是 M1 的 5 条逃逸。** 即：广度补在了"已修的那一维"，未补在"未修的那一维"。
新增逃逸向量：**有，5 条**（见 M1 表）。

**Q3：v2.6.6 是否引入新 HIGH/MEDIUM？**
→ **285/285 我独立复现成功，非不可复现**：test-trust-root 84/84、test-human-gate 69/69、
test-core 14/14、test-boundary-cases 40/40、test-d2-d5 47/47、test-held-out 31/31，
合计 285，零 FAIL。该项**不成立**。
→ `except (ValueError, OSError)` 过宽吞掉无关异常？**否** —— 过窄而非过宽：
TypeError/AttributeError 漏网，OSError 不可达。属"宽度校准错误"（M2）。
→ L257/292/332 是否真安全？**是**，三处均 fail-closed（见 L2），但我备案 L332
为已知宽松点。
→ **新增的 HIGH 是 M1（6 条逃逸，5 条端到端无捕获）**，属 v2.6.6 未消除的既存同类缺陷，
非 v2.6.6 引入。

**Q4：评级是否可上调？**
→ **维持 ⚠️ CONDITIONAL。不上调、不降级。**
理由：
1. 不上调：C-1 在默认模式仍 OPEN（backend=legacy 恒 pass，`TrustRoot.attestation_ok`
   返回 `(True, None)`，无外部锚），外部锚不可伪造性仍依赖未运行时强制的部署契约
   （`_deploy_warn` 仅 WARN-only，不 fail-closed）。v2.6.6 未触碰此项，维持 CONDITIONAL 正确。
2. 不降级：M1 的 6 条逃逸**均无认证绕过路径**（异常发生在放行判据之前，最坏崩溃而非越权），
   不构成安全降级事由。
3. 附条件：评级维持 CONDITIONAL **附带前提** —— M1 的 5 条端到端逃逸须在下一版本
   （建议 v2.6.7）按 S1+S3 收口；否则建议将评级标注为
   "CONDITIONAL（外部锚路径含未捕获崩溃面）"，不得声称"损坏输入逃逸已收口"。

---

## 五、诚实边界

- 我**实跑**了 285/285 全量 6 套件 + 独立对抗探针 19 例 + 端到端 fixture 场景 5 例；
  本报告中所有 PASS/ESCAPE 数字均为我本机真实执行结果，非采信自评。
- 运行环境注意：须 `env -u PYTHONHOME -u PYTHONPATH`，否则 uv 托管的 cpython-3.11 与
  Python312 混用触发 `AssertionError: SRE module mismatch`（非技能缺陷，纯环境污染）。
- M1 的严重度定级含判断成分：我判为【高】基于"同类缺陷已修但漏修 + 端到端无捕获"两条，
  但它**不**构成安全绕过，故未上调总评级。若审计人认为"无认证绕过即不属高"，
  可下调为【中】，但 M1 的存在本身与证据链不因此改变。
- 审计脚本（保留不删）：
  `scripts/hermes-verify-adv-probe.py`（19 例 attestation_ok 对抗探针）
  `scripts/hermes-verify-adv-e2e.py`（5 例 check_pubkey_root 端到端升级验证）
