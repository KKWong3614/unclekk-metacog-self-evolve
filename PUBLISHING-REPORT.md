# SkillHub 发布验证报告 — unclekk-metacog-self-evolve v2.25.6

**打包日期**: 2026-10-18
**目标路径**: D:\skill发布\unclekk-metacog-self-evolve-v2.25.6.zip

## 版本绑定校验

- SKILL.md `version: 2.25.6` == package.json `version: 2.25.6` == _skillhub_meta.json `version: 2.25.6` ✅

## 发布清单统计

- 文件总数（SkillHub 白名单过滤后）: **114**
- 总大小: **2,394,933 bytes**
- 过滤剔除: `.packignore`（无扩展名，非白名单）、`references/benchmark/results/report.html`（.html 非白名单）；运行态目录（`__pycache__/`、`.metacog/`）不计入。

| 扩展名 | 文件数 |
|--------|--------|
| .md | 54 |
| .py | 53 |
| .json | 6 |
| .jsonl | 1 |

> C-1 部署套件以单文件 `scripts/C1_deploy.py`（.py，白名单内）形式随包分发，内嵌 8 个 `C1_*.ps1`（base64），运行时解包到临时目录以 `powershell -File` 调用。新用户 `skillhub install` 一个包即获得完整「系统级可控自指」闭环（引擎 + 人在环三闸 + OS 级 L1/L2/L3 隔离），无需二次分发 `.ps1`。

### 完整性抽查

- 版本绑定: SKILL.md `version: 2.25.6` == package.json / _skillhub_meta.json `version: 2.25.6` ✅
- 冻结清单: `scripts/frozen-hashes.jsonl` 重基线至 **16 路径**（新增 `scripts/C1_deploy.py`），`verify` rc=0（append-only + HMAC 链 + 树外锚点）✅
- C1 包装: `python scripts/C1_deploy.py --help` 通过；8 个内嵌 `.ps1` base64 往返字节一致 ✅
- 引擎源码（`metacog.py` / `trust_root.py` / `sigcrypto.py` / `freeze.py` / `CONTRACT.md`）与 v2.25.5 发布基线逐字节一致（新增 `C1_deploy.py` 外无引擎改动）✅
- 评级状态（截至打包）: 软件层 v2.8.0 起 Hermes 裁定 `RESOLVED·CONDITIONAL-PASS`；部署层 `C1_*.ps1` 已于加固主机 PC-20230325SHQZ 实机验证；本次仅补「可分发性」（入包），无新安全/健壮性缺陷；诚实边界（C-1 真正生效取决于生产机正确部署）保留。
- 发布为按版本创建（create-only），故以 **2.25.6** 承载本次入包。
