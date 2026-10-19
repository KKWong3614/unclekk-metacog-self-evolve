# 常见错误索引 / 排查清单（Troubleshooting）

本文件是 `metacog.py` 所有报错的**集中索引**。命令行遇到任何「错误:」/「[BLOCK]」/「[HOLD]」且退出码 2 时，
先在本文件按场景找原因与修法；每条报错本身也会带「↩ 怎么改」行。

> 触发本文件的方式：
> - 失败时在 stderr 末尾会自动打印「ℹ 命令未成功（退出码 2）…`references/troubleshooting.md`」。
> - 主动查看：`python metacog.py --explain`（无需 `.metacog`，放在子命令前）。

## 退出码速查
| 退出码 | 含义 | 下一步 |
|---|---|---|
| 0 | 成功 | — |
| 2 | 参数/前置校验失败，或安全闸拦截 | 看报错「↩ 怎么改」+ 下表 |
| 其他非 0 | 运行期异常（配置/IO/git） | 看报错「↩ 怎么改」+ 下表「运行异常」 |

## 一、前置 / 参数校验（RC=2）

### 1. 根目录不存在
- 现象：`错误: <root> 不存在，先跑 python metacog.py init`
- 原因：未在目标目录初始化契约。
- 修法：`python metacog.py init`（默认 `.metacog`，或用 `--root <dir>` 指定）。

### 2. --utility 超界
- 现象：`错误: --utility 必须在 0~1 之间`
- 修法：传 0~1 浮点，如 `--utility 0.7`；达成度高给 0.8~1.0，返工多给 0.2~0.4，完全失败给 0。

### 3. --artifact 非法
- 现象：argparse 报错 `invalid choice: 'ZZZ'`
- 修法：只能用 `A1/A2/A3/A4/M1`（A1=系统提示 A2=规则库 A3=安全记忆 A4=工具策略 M1=元层演化策略）。

### 4. add/replace 缺正文
- 现象：`错误: add/replace 需要 --content 或 --content-file`
- 修法：`--content "正文"` 或 `--content-file ./draft.md`。

### 5. replace/remove 缺 --target
- 现象：`错误: replace/remove 需要 --target <entry-id>`
- 修法：`retrieve --artifact <A>` 或 `status` 查 ID；形如 A1-001 / R-003 / M1-002（过闸后 ID 不变）。

## 二、G1 写入闸（gate，RC=2 或 HOLD）

### 6. [BLOCK] 不动点保护
- 原因：提议触及 CONTRACT.md / metacog.py / SKILL.md（人类持有的不动点）。
- 修法：移除对这三者的改动，只改五制品 A1-A4/M1 内容。

### 7. [BLOCK] 制品越界
- 修法：`--artifact` 只能用 A1/A2/A3/A4/M1。

### 8. [BLOCK] 红线-xxx
- 原因：内容命中禁止模式（如"跳过安全检查""删除 / rm -rf""自动批准"等）。
- 修法：删除触发该红线的指令后重新 `propose`。

### 9. [BLOCK] A3 只增不减
- 原因：对安全记忆(A3)执行了 replace/remove。
- 修法：改用 op=add 追加新教训，旧教训不可删改。

### 10. [HOLD] 证据不足
- 现象：需 ≥2 个 episode，当前 0。
- 修法：`propose` 时加 `--episode E001 --episode E002` 引用真实证据；或先多记几次 `episode`。

### 11. [HUMAN] 元层改动 / 高风险
- 修法：`apply` 时加 `--human-ok` 显式确认。

## 三、apply（RC=2）

### 12. 目标条目不存在
- 现象：`[BLOCK] P-xxx: 目标条目 R-999 不存在`
- 修法：`retrieve --artifact <A>` 查有效 ID，确认拼写（过闸后 ID 不变）。

### 13. 需人类确认
- 现象：`[HOLD] P-xxx 需人类确认，加 --human-ok 才能应用`
- 修法：确认无误后 `apply --id <P> --human-ok`。

## 四、init-domain（RC=2）

### 14. 配置文件不存在
- 修法：核对路径（用绝对路径更稳），或去掉 `--config` 用模板默认字段。

### 15. 配置解析失败
- 修法：确认合法 JSON（键与字符串用双引号、末尾无逗号）；最小样例 `{"max_lines": 200}`；`python -m json.tool 文件.json` 自检格式。

### 16. 非法 domain / 初始化失败
- 修法：`--domain` 取 code_review / paper_review / document_editing；`--output` 目录可写。

## 五、运行异常（非 RC=2，多属 IO / git）

### 17. git add/commit 失败
- 修法：root 非 git 仓会自动跳过（需留底先 `git init`）；commit 报 author identity 则 `git config user.name/user.email`；其余查文件权限。

### 18. 读取失败 / 超大文件
- 现象：`[ERROR] 读取失败` / `[WARN] 文件超过 512KB，跳过读取`
- 修法：检查文件是否被占用、编码是否 UTF-8；超大文件拆分或调大 max_size 参数。

---

仍无法解决？查看 `references/` 下设计文档（`anti-patterns.md` / `faq-deep.md`），或回 SkillHub 提 issue。
