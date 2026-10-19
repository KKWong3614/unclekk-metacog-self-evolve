# unclekk-metacog-self-evolve v2.0 落地清单

**制定日期**: 2026-09-08  
**目标版本**: v2.0.0  
**目标评分**: 95/100（从当前59/100提升）  
**预计工期**: 30小时  
**执行标准**: 每阶段完成后必须通过验证脚本，否则回滚

---

## 执行摘要

| 阶段 | 内容 | 工时 | 评分提升 | 依赖 |
|------|------|------|----------|------|
| Phase 1.1 | M1自动触发 | 4h | 59→65 | 无 |
| Phase 1.2 | 棘轮自适应 | 4h | 65→72 | Phase 1.1 |
| Phase 2.1 | 元认知日志 | 6h | 72→78 | Phase 1.2 |
| Phase 2.2 | 跨领域模板 | 6h | 78→85 | Phase 2.1 |
| Phase 3.1 | 性能benchmark | 10h | 85→95 | Phase 2.2 |
| **总计** | | **30h** | **+36分** | |

---

## Phase 1.1: M1自动触发机制（4小时）

### 任务分解

#### 1.1.1 设计触发条件（30分钟）
- [ ] 定义连续REVERT检测逻辑
- [ ] 设计failure_pattern分析函数
- [ ] 确定M1提议生成模板

**输入文件**:
- `scripts/metacog.py:776-781`（现有连续REVERT检测）
- `references/remediation-plan-v1.5.0.md`（设计文档）

**输出文件**:
- `references/design/m1-auto-trigger-spec.md`

**验收标准**:
```markdown
## 触发条件定义
- 连续3次REVERT → 触发M1自动提议
- 混合历史（REVERT+PROMOTE）→ 不触发
- 触发后进入隔离区，需--human-ok确认
```

---

#### 1.1.2 实现失败模式分析（60分钟）
```python
# scripts/metacog.py 新增函数

def analyze_failure_pattern(ratchet_state):
    """分析连续REVERT的失败模式"""
    history = ratchet_state.get("history", [])
    recent = history[-10:]  # 分析最近10次
    
    patterns = {
        "revert_count": sum(1 for h in recent if h["action"] == "revert"),
        "artifact_focus": {},
        "common_reasons": []
    }
    
    # 统计涉及的制品
    for h in recent:
        artifact = h.get("artifact", "unknown")
        patterns["artifact_focus"][artifact] = patterns["artifact_focus"].get(artifact, 0) + 1
    
    # 提取失败原因
    for h in recent:
        reason = h.get("reason", "")
        if reason:
            patterns["common_reasons"].append(reason)
    
    return patterns
```

**验收标准**:
- [ ] 函数返回dict包含revert_count/artifact_focus/common_reasons
- [ ] 测试用例：3次连续REVERT返回正确模式
- [ ] 测试用例：混合历史返回空模式

**验证脚本**:
```bash
python scripts/test-m1-trigger.py
# 预期: 3/3 PASS
```

---

#### 1.1.3 实现自动触发逻辑（90分钟）
```python
# scripts/metacog.py 修改cmd_verdict函数

def cmd_verdict(st, args):
    # ... 现有逻辑 ...
    
    # 新增：M1自动触发检查
    if args.auto_m1:  # 新增--auto-m1参数
        if check_and_trigger_m1(st):
            ok("M1自动提议已创建（需--human-ok确认）")
    
    return 0

def check_and_trigger_m1(st):
    """检查并触发M1自动提议"""
    r = st.get_ratchet()
    recent = [h["action"] for h in r["history"][-3:]]
    
    # 连续3次REVERT检测
    if len(recent) == 3 and all(a == "revert" for a in recent):
        # 分析失败模式
        pattern = analyze_failure_pattern(r)
        
        # 生成M1提议
        m1_proposal = {
            "id": new_id("M1-AUTO"),
            "artifact": "M1",
            "op": "replace",
            "content": generate_m1_content(pattern),
            "reason": f"自动触发：连续3次REVERT，模式: {pattern['revert_count']}次",
            "triggered": True,
            "failure_pattern": pattern,
            "requires_human": True  # 关键：仍需人工确认
        }
        
        # 保存到隔离区
        st.save_proposal(m1_proposal)
        return True
    
    return False

def generate_m1_content(pattern):
    """根据失败模式生成M1内容"""
    return f"""## 元层自省（自动触发）

**触发条件**: 连续{pattern['revert_count']}次REVERT

**失败模式分析**:
- 涉及制品: {dict(pattern['artifact_focus'])}
- 常见原因: {pattern['common_reasons'][:3]}

**建议改进方向**:
1. 检查提议生成逻辑是否针对真正问题
2. 重新评估归因准确性
3. 考虑是否需要修改M1演化策略
"""
```

**验收标准**:
- [ ] 连续3次REVERT自动创建M1提议
- [ ] 提议进入隔离区（quarantine/）
- [ ] 提议标记`requires_human: True`
- [ ] 日志记录触发事件

**验证脚本**:
```bash
# 测试连续REVERT触发
python scripts/test-m1-auto-trigger.py
# 预期: 4/4 PASS
```

---

#### 1.1.4 添加命令行参数（30分钟）
```python
# scripts/metacog.py 修改argparse

parser.add_argument('--auto-m1', action='store_true',
                    help='自动触发M1提议（需配合连续3次REVERT）')
```

**验收标准**:
- [ ] `python metacog.py verdict --auto-m1` 参数生效
- [ ] 无--auto-m1时不触发（保持向后兼容）
- [ ] 帮助信息显示正确

---

### Phase 1.1 验收清单

- [ ] 失败模式分析函数测试通过（3/3）
- [ ] 自动触发逻辑测试通过（4/4）
- [ ] 命令行参数测试通过（2/2）
- [ ] 安全机制无退化（红线测试10/10）
- [ ] 单元测试新增15个用例
- [ ] 文档更新（SKILL.md添加--auto-m1说明）

**预计耗时**: 4小时  
**预期评分**: 59→65（+6分）

---

## Phase 1.2: 棘轮自适应机制（4小时）

### 任务分解

#### 1.2.1 实现自适应阈值（60分钟）
```python
# scripts/metacog.py 修改Ratchet类

class AdaptiveRatchet:
    def __init__(self, base_utility=0.5, epsilon=0.02):
        self.base_utility = base_utility
        self.epsilon = epsilon
        self.window = []
        self.violation_rate = 0.0
        self.threshold_history = []
    
    def update(self, utility, violation_rate):
        """自适应更新棘轮状态"""
        self.window.append(utility)
        if len(self.window) > 5:
            self.window.pop(0)
        
        self.violation_rate = violation_rate
        
        # 计算自适应阈值
        threshold = self.adaptive_threshold()
        self.threshold_history.append(threshold)
        
        # 滑动窗口均值更新基线
        new_base = self.sliding_window_mean()
        if new_base:
            self.base_utility = new_base
        
        return threshold
    
    def adaptive_threshold(self):
        """根据violation_rate动态调整阈值"""
        if self.violation_rate > 0.3:
            # 高违规率，更严格（降低阈值5%）
            return self.base_utility * 0.95
        elif self.violation_rate < 0.1:
            # 低违规率，更宽松（提高阈值5%）
            return self.base_utility * 1.05
        else:
            # 正常范围，保持基线
            return self.base_utility
    
    def sliding_window_mean(self):
        """滑动窗口均值，带epsilon容差"""
        if len(self.window) < 2:
            return None
        
        current = sum(self.window) / len(self.window)
        previous = sum(self.window[:-1]) / (len(self.window) - 1)
        
        # 变化在epsilon内不更新
        if abs(current - previous) < self.epsilon:
            return previous
        return current
    
    def get_status(self):
        """获取棘轮状态"""
        return {
            "base_utility": self.base_utility,
            "threshold": self.adaptive_threshold(),
            "violation_rate": self.violation_rate,
            "window_size": len(self.window),
            "threshold_trend": self.threshold_history[-5:] if self.threshold_history else []
        }
```

**验收标准**:
- [ ] violation_rate > 0.3时阈值降低5%
- [ ] violation_rate < 0.1时阈值提高5%
- [ ] epsilon容差生效（微小变化不更新）
- [ ] 窗口满5个后正确更新

**验证脚本**:
```bash
python scripts/test-adaptive-ratchet.py
# 预期: 5/5 PASS
```

---

#### 1.2.2 集成到verdict流程（60分钟）
```python
# scripts/metacog.py 修改cmd_verdict

def cmd_verdict(st, args):
    r = st.get_ratchet()
    eps = read_jsonl(st.episodes)
    
    # 使用自适应棘轮
    ratchet = AdaptiveRatchet(
        base_utility=r.get("baseline_utility", 0.5),
        epsilon=r.get("epsilon", 0.02)
    )
    
    if len(eps) < r["window"]:
        info(f"样本不足，需 {r['window']} 个episode（当前 {len(eps)}）。")
        return 0
    
    window = eps[-r["window"]:]
    prev_window = eps[-2*r["window"]:-r["window"]]
    
    # 计算当前violation_rate
    current_vr = sum(e.get("violations", 0) for e in window) / len(window)
    prev_vr = sum(e.get("violations", 0) for e in prev_window) / len(prev_window)
    
    # 更新自适应阈值
    threshold = ratchet.update(r["baseline_utility"], current_vr)
    
    # 使用自适应阈值进行裁决
    # ... 现有裁决逻辑，但使用threshold而非固定基线 ...
```

**验收标准**:
- [ ] verdict命令使用自适应阈值
- [ ] threshold_history正确记录
- [ ] 状态输出包含threshold信息

**验证脚本**:
```bash
python scripts/test-verdict-adaptive.py
# 预期: 4/4 PASS
```

---

#### 1.2.3 添加状态查询（30分钟）
```python
# scripts/metacog.py 新增status输出

def cmd_status(st, args):
    # ... 现有逻辑 ...
    
    # 新增：棘轮自适应状态
    info("\n--- 棘轮自适应状态 ---")
    info(f"当前基线: {ratchet.base_utility:.4f}")
    info(f"自适应阈值: {ratchet.adaptive_threshold():.4f}")
    info(f"违规率: {ratchet.violation_rate:.4f}")
    info(f"窗口大小: {len(ratchet.window)}/5")
    if ratchet.threshold_history:
        info(f"阈值趋势: {'→'.join(f'{t:.4f}' for t in ratchet.threshold_history[-5:])}")
```

**验收标准**:
- [ ] status命令显示自适应状态
- [ ] 阈值趋势正确显示
- [ ] 无格式错误

---

### Phase 1.2 验收清单

- [ ] 自适应阈值函数测试通过（5/5）
- [ ] verdict集成测试通过（4/4）
- [ ] status查询测试通过（2/2）
- [ ] 向后兼容性测试（无--adaptive参数时行为不变）
- [ ] 单元测试新增12个用例
- [ ] 文档更新（SKILL.md添加自适应说明）

**预计耗时**: 4小时  
**预期评分**: 65→72（+7分）

---

## Phase 2.1: 元认知日志系统（6小时）

### 任务分解

#### 2.1.1 设计日志格式（60分钟）
```markdown
# references/design/meta-cognition-log-spec.md

## 日志格式

```json
{
  "timestamp": "2026-09-08T17:00:00+08:00",
  "event_type": "metacognitive_reflection",
  "trigger": "continuous_revert",
  "context": {
    "episode_count": 15,
    "generation": 3,
    "baseline_utility": 0.65,
    "current_utility": 0.58,
    "violation_rate": 0.15
  },
  "analysis": {
    "failure_pattern": {
      "revert_count": 3,
      "artifact_focus": {"A2": 2, "A1": 1},
      "common_reasons": ["归因错误", "证据不足"]
    },
    "attribution_accuracy": 0.6,
    "proposed_m1": "检查归因逻辑"
  },
  "action": {
    "m1_proposal_created": true,
    "requires_human_confirmation": true,
    "human_confirmed": false
  },
  "insight": "连续REVERT表明归因环节存在问题，建议增强归因验证机制"
}
```
```

**验收标准**:
- [ ] 日志格式定义完整
- [ ] 包含所有必要字段
- [ ] 示例正确

---

#### 2.1.2 实现日志记录函数（120分钟）
```python
# scripts/metacog.py 新增模块

import json
from pathlib import Path
from datetime import datetime

META_LOG_PATH = ".metacog/logs/meta-cognition.log"

def log_metacognition(event_type: str, context: dict, analysis: dict, 
                      action: dict, insight: str = ""):
    """记录元认知反思事件"""
    log_entry = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "event_type": event_type,
        "trigger": context.get("trigger", "unknown"),
        "context": context,
        "analysis": analysis,
        "action": action,
        "insight": insight
    }
    
    # 追加到日志文件
    log_path = Path(META_LOG_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(log_entry, ensure_ascii=False, indent=2) + '\n')
    
    return log_entry

def analyze_meta_log(days: int = 7) -> dict:
    """分析最近N天的元认知日志"""
    log_path = Path(META_LOG_PATH)
    if not log_path.exists():
        return {"entries": 0, "insights": []}
    
    # 读取日志
    entries = []
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    
    # 过滤最近N天
    cutoff = datetime.now() - timedelta(days=days)
    recent = [e for e in entries 
              if datetime.fromisoformat(e['timestamp']).astimezone() > cutoff]
    
    # 统计分析
    insights = []
    for e in recent:
        if e.get('insight'):
            insights.append({
                "timestamp": e['timestamp'],
                "event_type": e['event_type'],
                "insight": e['insight']
            })
    
    return {
        "total_entries": len(entries),
        "recent_entries": len(recent),
        "insights": insights,
        "event_distribution": count_by_type(recent)
    }

def count_by_type(entries):
    """统计事件类型分布"""
    dist = {}
    for e in entries:
        t = e.get('event_type', 'unknown')
        dist[t] = dist.get(t, 0) + 1
    return dist
```

**验收标准**:
- [ ] log_metacognition函数正确写入日志
- [ ] analyze_meta_log函数正确分析日志
- [ ] 日志格式符合规范
- [ ] 时间过滤正确

**验证脚本**:
```bash
python scripts/test-meta-log.py
# 预期: 4/4 PASS
```

---

#### 2.1.3 集成到关键节点（120分钟）
```python
# 在以下位置添加日志记录

# 1. M1自动触发时
if check_and_trigger_m1(st):
    log_metacognition(
        event_type="m1_auto_trigger",
        context={"trigger": "continuous_revert", "count": 3},
        analysis={"pattern": analyze_failure_pattern(r)},
        action={"proposal_created": True, "requires_human": True},
        insight="连续REVERT触发M1自动提议，需人工确认"
    )

# 2. verdict裁决后
if verdict == "PROMOTE":
    log_metacognition(
        event_type="rule_promoted",
        context={"artifact": p["artifact"], "entry_id": p["entry_id"]},
        analysis={"utility_change": utility_delta},
        action={"verdict": "PROMOTE", "confirmed": True},
        insight="规则演化成功，utility提升"
    )

# 3. REVERT裁决后
if verdict == "REVERT":
    log_metacognition(
        event_type="rule_reverted",
        context={"artifact": p["artifact"], "entry_id": p["entry_id"]},
        analysis={"reason": p.get("reason", "")},
        action={"verdict": "REVERT", "reason": p.get("reason", "")},
        insight="规则演化失败，已回滚"
    )
```

**验收标准**:
- [ ] 关键节点都有日志记录
- [ ] 日志内容完整准确
- [ ] 不影响原有流程

**验证脚本**:
```bash
python scripts/test-meta-log-integration.py
# 预期: 3/3 PASS
```

---

#### 2.1.4 添加日志查询命令（60分钟）
```python
# scripts/metacog.py 新增cmd

def cmd_meta_log(args):
    """查询元认知日志"""
    days = args.days if hasattr(args, 'days') and args.days else 7
    
    result = analyze_meta_log(days)
    
    info(f"=== 元认知日志（最近{days}天） ===")
    info(f"总条目: {result['total_entries']}")
    info(f"近期条目: {result['recent_entries']}")
    info(f"事件分布: {result['event_distribution']}")
    
    if result['insights']:
        info(f"\n--- 洞察（最近{min(5, len(result['insights']))}条）---")
        for insight in result['insights'][-5:]:
            info(f"[{insight['timestamp']}] {insight['event_type']}: {insight['insight']}")
    
    return 0

# 添加命令行参数
parser_meta_log = subparsers.add_parser('meta-log', help='查询元认知日志')
parser_meta_log.add_argument('--days', type=int, default=7,
                             help='查询最近N天的日志（默认7天）')
parser_meta_log.set_defaults(func=cmd_meta_log)
```

**验收标准**:
- [ ] `python metacog.py meta-log` 命令可用
- [ ] 显示统计信息和洞察
- [ ] --days参数生效

**验证脚本**:
```bash
python scripts/test-meta-log-command.py
# 预期: 3/3 PASS
```

---

### Phase 2.1 验收清单

- [ ] 日志格式定义完整（1/1）
- [ ] 日志记录函数测试通过（4/4）
- [ ] 关键节点集成测试通过（3/3）
- [ ] 日志查询命令测试通过（3/3）
- [ ] 日志文件正确创建和写入
- [ ] 文档更新（SKILL.md添加meta-log说明）

**预计耗时**: 6小时  
**预期评分**: 72→78（+6分）

---

## Phase 2.2: 跨领域模板系统（6小时）

### 任务分解

#### 2.2.1 设计领域模板（60分钟）
```python
# scripts/domains/__init__.py

# 预置领域模板
DOMAIN_TEMPLATES = {
    "code_review": {
        "name": "代码评审",
        "A1": """# 代码评审助手

你是一个专业的代码评审助手，负责审查代码质量、安全性和最佳实践。

## 核心职责
1. 检查代码逻辑正确性
2. 识别安全漏洞
3. 评估代码可读性和可维护性
4. 建议性能优化

## 行为准则
- 保持客观、建设性的评审风格
- 优先关注安全性和逻辑错误
- 提供具体可执行的改进建议
""",
        "A2_rules": [
            {"id": "R-001", "content": "命名规范：函数名使用蛇形命名，类名使用帕斯卡命名", "since": "2026-09-08"},
            {"id": "R-002", "content": "错误处理：所有外部调用必须包含 try-catch", "since": "2026-09-08"},
            {"id": "R-003", "content": "安全检查：所有用户输入必须经过参数化查询", "since": "2026-09-08"}
        ],
        "A3_memories": [
            {"id": "S-000", "content": "事故：评审时遗漏了SQL注入漏洞，教训：必须检查所有用户输入的处理路径", "since": "2026-09-08"}
        ],
        "A4_policy": """# 代码评审工具策略

## 工具使用规范
- 使用静态分析工具扫描代码
- 运行单元测试验证逻辑
- 检查依赖版本安全性
- 不修改被评审的代码文件
""",
        "M1_policy": """# 代码评审元层策略

## 演化机制
- 每次评审后记录utility和violations
- 连续3次REVERT触发M1修改
- 证据门槛：≥2次独立复现
""",
        "redlines": [
            ("安全漏洞", r"(注入|XSS|CSRF|未授权)[^\n]{0,10}?(允许|忽略|跳过|绕过)"),
            ("权限提升", r"(chmod\s+777|sudo\s+su|bypass.*?security)"),
            ("数据泄露", r"(password|secret|token)[^\n]{0,5}=\s*[^\s]{8,}")
        ]
    },
    
    "paper_review": {
        "name": "论文评审",
        "A1": """# 论文评审助手

你是一个专业的学术论文评审助手，负责评估研究质量、创新性和方法论。

## 核心职责
1. 评估研究创新性
2. 检查方法论严谨性
3. 验证实验设计合理性
4. 评估结论可信度

## 行为准则
- 保持学术客观性
- 关注创新性和贡献
- 提供建设性批评
""",
        "A2_rules": [
            {"id": "R-001", "content": "创新性：必须有明确的研究贡献和创新点", "since": "2026-09-08"},
            {"id": "R-002", "content": "方法论：方法必须严谨且可复现", "since": "2026-09-08"},
            {"id": "R-003", "content": "实验：必须有充分的实验验证", "since": "2026-09-08"}
        ],
        "A3_memories": [
            {"id": "S-000", "content": "事故：遗漏了方法复现性问题，教训：必须检查实验细节完整性", "since": "2026-09-08"}
        ],
        "A4_policy": """# 论文评审工具策略

## 工具使用规范
- 使用引用分析工具检查创新性
- 检查实验代码可访问性
- 验证统计方法正确性
- 不修改被评审的论文
""",
        "M1_policy": """# 论文评审元层策略

## 演化机制
- 每次评审后记录utility和violations
- 连续3次REVERT触发M1修改
- 证据门槛：≥2次独立复现
""",
        "redlines": [
            ("学术不端", r"(抄袭|剽窃|数据造假)[^\n]{0,10}?(允许|忽略)"),
            ("伦理问题", r"(未通过.*?ethics|human.*?subjects.*?without.*?approval)"),
            ("利益冲突", r"(conflict.*?of.*?interest)[^\n]{0,5}?(隐瞒|未声明)")
        ]
    },
    
    "document_editing": {
        "name": "文档编辑",
        "A1": """# 文档编辑助手

你是一个专业的文档编辑助手，负责确保文档质量、一致性和准确性。

## 核心职责
1. 检查格式规范性
2. 验证术语一致性
3. 确保逻辑清晰性
4. 发现事实错误

## 行为准则
- 保持文档风格一致
- 关注读者体验
- 提供可执行的修改建议
""",
        "A2_rules": [
            {"id": "R-001", "content": "格式规范：遵循既定模板格式", "since": "2026-09-08"},
            {"id": "R-002", "content": "术语一致：同一概念使用统一术语", "since": "2026-09-08"},
            {"id": "R-003", "content": "逻辑清晰：段落间有明确逻辑关系", "since": "2026-09-08"}
        ],
        "A3_memories": [
            {"id": "S-000", "content": "事故：术语不一致导致理解混淆，教训：必须维护术语表", "since": "2026-09-08"}
        ],
        "A4_policy": """# 文档编辑工具策略

## 工具使用规范
- 使用格式检查工具验证规范
- 检查术语一致性
- 验证引用和链接
- 不删除原有内容
""",
        "M1_policy": """# 文档编辑元层策略

## 演化机制
- 每次编辑后记录utility和violations
- 连续3次REVERT触发M1修改
- 证据门槛：≥2次独立复现
""",
        "redlines": [
            ("事实错误", r"(错误数据|不准确信息|过时内容)[^\n]{0,10}?(保留|忽略)"),
            ("敏感信息", r"(密码|密钥|token)[^\n]{0,5}=\s*[^\s]{8,}"),
            ("版权侵权", r"(未经授权.*?复制|侵犯.*?版权)")
        ]
    }
}
```

**验收标准**:
- [ ] 3个预置领域模板定义完整
- [ ] 每个模板包含完整五制品
- [ ] 红线规则针对领域定制

---

#### 2.2.2 实现领域初始化函数（120分钟）
```python
# scripts/domains/init.py

from pathlib import Path
import json

def init_domain(domain_name: str, output_dir: Path, user_config: dict = None):
    """初始化领域实例"""
    
    # 获取模板
    template = DOMAIN_TEMPLATES.get(domain_name)
    if not template:
        raise ValueError(f"未知领域: {domain_name}")
    
    # 合并用户配置
    if user_config:
        template = merge_template(template, user_config)
    
    # 创建.metacog目录
    metacog_dir = output_dir / ".metacog"
    metacog_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建子目录
    (metacog_dir / "artifacts").mkdir()
    (metacog_dir / "gates" / "quarantine").mkdir(parents=True)
    (metacog_dir / "ledger").mkdir()
    (metacog_dir / "meta").mkdir()
    (metacog_dir / "logs").mkdir()
    
    # 写入五制品
    write_artifact(metacog_dir / "artifacts" / "A1-system-prompt.md", 
                   template["A1"])
    write_artifact(metacog_dir / "artifacts" / "A2-rule-bank.md",
                   format_rule_bank(template["A2_rules"]))
    write_artifact(metacog_dir / "artifacts" / "A3-safety-memory.md",
                   format_safety_memory(template["A3_memories"]))
    write_artifact(metacog_dir / "artifacts" / "A4-tool-policy.md",
                   template["A4_policy"])
    write_artifact(metacog_dir / "meta" / "M1-evolve-policy.md",
                   template["M1_policy"])
    
    # 创建棘轮状态
    ratchet = {
        "baseline": None,
        "window": [],
        "generation": 0,
        "epsilon": 0.02
    }
    write_json(metacog_dir / "ledger" / "ratchet.json", ratchet)
    
    # 创建空的episode和archive
    (metacog_dir / "ledger" / "episodes.jsonl").touch()
    (metacog_dir / "ledger" / "archive.jsonl").touch()
    
    return {
        "domain": domain_name,
        "path": metacog_dir,
        "artifacts": ["A1", "A2", "A3", "A4", "M1"]
    }

def merge_template(template, user_config):
    """合并用户配置到模板"""
    merged = template.copy()
    for key in ["A1", "A2_rules", "A3_memories", "A4_policy", "M1_policy", "redlines"]:
        if key in user_config:
            merged[key] = user_config[key]
    return merged

def write_artifact(path, content):
    """写入制品文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def format_rule_bank(rules):
    """格式化规则库"""
    lines = ["# 规则库\n", "## 规则条目\n"]
    for rule in rules:
        lines.append(f"\n<!-- entry:{rule['id']} status:active since:{rule['since']} -->")
        lines.append(f"- {rule['content']}")
        lines.append(f"<!-- /entry:{rule['id']} -->")
    return "".join(lines)

def format_safety_memory(memories):
    """格式化安全记忆"""
    lines = ["# 安全记忆\n", "## 事故记录\n"]
    for mem in memories:
        lines.append(f"\n<!-- entry:{mem['id']} status:active since:{mem['since']} -->")
        lines.append(f"- {mem['content']}")
        lines.append(f"<!-- /entry:{mem['id']} -->")
    return "".join(lines)

def write_json(path, data):
    """写入JSON文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
```

**验收标准**:
- [ ] init_domain函数正确创建五制品
- [ ] 用户配置正确合并
- [ ] 目录结构符合规范
- [ ] 文件编码正确（UTF-8）

**验证脚本**:
```bash
python scripts/test-domain-init.py
# 预期: 5/5 PASS
```

---

#### 2.2.3 添加命令行接口（60分钟）
```python
# scripts/metacog.py 新增命令

def cmd_init_domain(args):
    """初始化领域实例"""
    from domains.init import init_domain
    
    try:
        result = init_domain(
            domain_name=args.domain,
            output_dir=Path(args.output),
            user_config=args.config
        )
        
        ok(f"领域 '{result['domain']}' 初始化成功")
        ok(f"路径: {result['path']}")
        ok(f"制品: {', '.join(result['artifacts'])}")
        
        info("\n下一步:")
        info(f"  cd {result['path'].parent}")
        info("  python metacog.py episode --task '...' --utility 0.7 --violations 0")
        
    except ValueError as e:
        bad(str(e))
        return 2
    except Exception as e:
        bad(f"初始化失败: {e}")
        return 2
    
    return 0

# 添加命令行参数
parser_init = subparsers.add_parser('init-domain', help='初始化领域实例')
parser_init.add_argument('domain', choices=list(DOMAIN_TEMPLATES.keys()),
                         help='领域名称')
parser_init.add_argument('--output', '-o', default='.',
                         help='输出目录（默认当前目录）')
parser_init.add_argument('--config', '-c', type=str,
                         help='JSON配置文件（可选）')
parser_init.set_defaults(func=cmd_init_domain)
```

**验收标准**:
- [ ] `python metacog.py init-domain code_review` 命令可用
- [ ] `--output`参数生效
- [ ] `--config`参数正确合并配置
- [ ] 错误处理正确

**验证脚本**:
```bash
python scripts/test-init-domain.py
# 预期: 4/4 PASS
```

---

#### 2.2.4 实现跨领域迁移测试（60分钟）
```python
# scripts/test-domain-migration.py

import tempfile
import shutil
from pathlib import Path

def test_domain_migration():
    """测试跨领域迁移"""
    tests = [
        ("code_review", "代码评审领域"),
        ("paper_review", "论文评审领域"),
        ("document_editing", "文档编辑领域")
    ]
    
    results = []
    
    for domain, desc in tests:
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                # 初始化领域
                result = init_domain(domain, Path(tmpdir))
                
                # 验证五制品存在
                metacog_dir = Path(tmpdir) / ".metacog"
                artifacts = [
                    metacog_dir / "artifacts" / "A1-system-prompt.md",
                    metacog_dir / "artifacts" / "A2-rule-bank.md",
                    metacog_dir / "artifacts" / "A3-safety-memory.md",
                    metacog_dir / "artifacts" / "A4-tool-policy.md",
                    metacog_dir / "meta" / "M1-evolve-policy.md"
                ]
                
                all_exist = all(p.exists() for p in artifacts)
                
                # 验证内容不同（领域特异性）
                a2_content = (metacog_dir / "artifacts" / "A2-rule-bank.md").read_text()
                has_domain_specific = any(keyword in a2_content 
                                         for keyword in get_domain_keywords(domain))
                
                results.append({
                    "domain": domain,
                    "success": all_exist and has_domain_specific,
                    "artifacts_count": len([p for p in artifacts if p.exists()])
                })
                
            except Exception as e:
                results.append({
                    "domain": domain,
                    "success": False,
                    "error": str(e)
                })
    
    # 统计结果
    passed = sum(1 for r in results if r["success"])
    total = len(results)
    
    print(f"\n跨领域迁移测试: {passed}/{total} 通过")
    for r in results:
        status = "✅" if r["success"] else "❌"
        print(f"  {status} {r['domain']}: {r['artifacts_count']}/5 制品")
    
    return passed == total

def get_domain_keywords(domain):
    """获取领域关键词"""
    keywords = {
        "code_review": ["命名规范", "安全检查", "参数化查询"],
        "paper_review": ["创新性", "方法论", "实验"],
        "document_editing": ["格式规范", "术语", "逻辑"]
    }
    return keywords.get(domain, [])

if __name__ == "__main__":
    success = test_domain_migration()
    exit(0 if success else 1)
```

**验收标准**:
- [ ] 3个领域初始化成功
- [ ] 每个领域有5个制品
- [ ] 领域特异性内容正确

**验证脚本**:
```bash
python scripts/test-domain-migration.py
# 预期: 3/3 PASS
```

---

### Phase 2.2 验收清单

- [ ] 领域模板定义完整（3/3）
- [ ] 初始化函数测试通过（5/5）
- [ ] 命令行接口测试通过（4/4）
- [ ] 跨领域迁移测试通过（3/3）
- [ ] 文档更新（SKILL.md添加init-domain说明）
- [ ] 示例脚本提供（scripts/examples/init-paper-review.py）

**预计耗时**: 6小时  
**预期评分**: 78→85（+7分）

---

## Phase 3.1: 性能Benchmark（10小时）

### 任务分解

#### 3.1.1 设计Benchmark框架（120分钟）
```python
# scripts/benchmark/base.py

from abc import ABC, abstractmethod
from pathlib import Path
import json
from datetime import datetime

class BaseBenchmark(ABC):
    """Benchmark基类"""
    
    def __init__(self, domain: str, output_dir: Path):
        self.domain = domain
        self.output_dir = output_dir
        self.results = []
        self.start_time = None
        self.end_time = None
    
    @abstractmethod
    def setup(self):
        """准备测试环境"""
        pass
    
    @abstractmethod
    def run_episode(self, episode_num: int) -> dict:
        """运行单个episode"""
        pass
    
    @abstractmethod
    def evaluate(self, episode_result: dict) -> dict:
        """评估episode结果"""
        pass
    
    @abstractmethod
    def generate_report(self) -> dict:
        """生成报告"""
        pass
    
    def run(self, episode_count: int = 100):
        """运行完整benchmark"""
        self.start_time = datetime.now()
        
        self.setup()
        
        for i in range(1, episode_count + 1):
            episode_result = self.run_episode(i)
            evaluation = self.evaluate(episode_result)
            
            self.results.append({
                "episode": i,
                "timestamp": datetime.now().isoformat(),
                "episode_result": episode_result,
                "evaluation": evaluation
            })
            
            # 每10个episode输出进度
            if i % 10 == 0:
                print(f"  进度: {i}/{episode_count}")
        
        self.end_time = datetime.now()
        
        return self.generate_report()
    
    def save_results(self):
        """保存结果"""
        results_dir = self.output_dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"benchmark-{self.domain}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        filepath = results_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({
                "domain": self.domain,
                "start_time": self.start_time.isoformat(),
                "end_time": self.end_time.isoformat(),
                "duration_seconds": (self.end_time - self.start_time).total_seconds(),
                "episode_count": len(self.results),
                "results": self.results
            }, f, ensure_ascii=False, indent=2)
        
        return filepath
```

**验收标准**:
- [ ] BaseBenchmark类定义完整
- [ ] 抽象方法正确定义
- [ ] run方法流程正确

---

#### 3.1.2 实现代码评审Benchmark（180分钟）
```python
# scripts/benchmark/code_review.py

from .base import BaseBenchmark
from pathlib import Path
import subprocess
import sys

class CodeReviewBenchmark(BaseBenchmark):
    """代码评审领域Benchmark"""
    
    def __init__(self, output_dir: Path):
        super().__init__("code_review", output_dir)
        self.skill_root = Path(__file__).resolve().parents[1]  # 实际部署用 __file__ 推导，不硬编码机器路径
        self.metacog_script = self.skill_root / "scripts" / "metacog.py"
    
    def setup(self):
        """初始化代码评审环境"""
        # 创建测试工作目录
        self.test_dir = self.output_dir / "test-env" / "code-review"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化metacog
        subprocess.run(
            [sys.executable, str(self.metacog_script), "init"],
            cwd=self.test_dir,
            capture_output=True
        )
        
        # 创建测试PR
        self.test_prs = self.generate_test_prs(50)
    
    def generate_test_prs(self, count: int) -> list:
        """生成测试PR"""
        prs = []
        for i in range(1, count + 1):
            prs.append({
                "id": f"PR-{i:03d}",
                "file": f"test_file_{i}.py",
                "issue_type": self.get_random_issue_type(),
                "description": self.get_issue_description(i)
            })
        return prs
    
    def get_random_issue_type(self) -> str:
        """随机选择问题类型"""
        import random
        return random.choice([
            "naming_convention",
            "error_handling",
            "security_vulnerability",
            "performance_issue",
            "code_style"
        ])
    
    def get_issue_description(self, pr_id: int) -> str:
        """生成问题描述"""
        descriptions = {
            "naming_convention": f"函数名mixingCase不符合规范",
            "error_handling": f"缺少try-catch处理外部调用",
            "security_vulnerability": f"存在SQL注入风险",
            "performance_issue": f"循环内查询数据库",
            "code_style": f"注释缺失，逻辑复杂"
        }
        issue_type = self.get_random_issue_type()
        return descriptions.get(issue_type, "未知问题")
    
    def run_episode(self, episode_num: int) -> dict:
        """运行单个评审episode"""
        pr = self.test_prs[(episode_num - 1) % len(self.test_prs)]
        
        # 模拟评审过程
        review_result = self.simulate_review(pr)
        
        return {
            "episode": episode_num,
            "pr_id": pr["id"],
            "issue_type": pr["issue_type"],
            "review_result": review_result
        }
    
    def simulate_review(self, pr: dict) -> dict:
        """模拟代码评审"""
        # 实际实现中会调用LLM进行评审
        # 这里使用简化模拟
        import random
        
        return {
            "found_issues": random.randint(1, 5),
            "critical_issues": random.randint(0, 2),
            "suggestions": random.randint(2, 8),
            "review_quality": random.uniform(0.5, 0.9)
        }
    
    def evaluate(self, episode_result: dict) -> dict:
        """评估评审质量"""
        review = episode_result["review_result"]
        
        # 计算utility
        utility = (
            review["review_quality"] * 0.4 +
            (1 - review["critical_issues"] / max(review["found_issues"], 1)) * 0.3 +
            (review["suggestions"] / 10) * 0.3
        )
        
        # 计算violations（关键问题未检出）
        violations = review["critical_issues"]
        
        return {
            "utility": round(utility, 4),
            "violations": violations,
            "found_issues": review["found_issues"],
            "critical_issues": review["critical_issues"]
        }
    
    def generate_report(self) -> dict:
        """生成报告"""
        if not self.results:
            return {"error": "无结果"}
        
        utilities = [r["evaluation"]["utility"] for r in self.results]
        violations = [r["evaluation"]["violations"] for r in self.results]
        
        return {
            "domain": self.domain,
            "episode_count": len(self.results),
            "duration_seconds": (self.end_time - self.start_time).total_seconds(),
            "average_utility": sum(utilities) / len(utilities),
            "utility_trend": self.calculate_trend(utilities),
            "average_violations": sum(violations) / len(violations),
            "violation_rate": sum(violations) / len(violations) / 5.0  # 假设最多5个issue
        }
    
    def calculate_trend(self, data: list) -> str:
        """计算趋势"""
        if len(data) < 2:
            return "insufficient_data"
        
        first_half = sum(data[:len(data)//2]) / (len(data)//2)
        second_half = sum(data[len(data)//2:]) / (len(data) - len(data)//2)
        
        if second_half > first_half * 1.05:
            return "improving"
        elif second_half < first_half * 0.95:
            return "degrading"
        else:
            return "stable"
```

**验收标准**:
- [ ] CodeReviewBenchmark类实现完整
- [ ] 生成50个测试PR
- [ ] 评估逻辑正确
- [ ] 报告格式正确

**验证脚本**:
```bash
python scripts/benchmark/run-code-review.py
# 预期: 生成报告，utility趋势可分析
```

---

#### 3.1.3 实现论文评审Benchmark（180分钟）
```python
# scripts/benchmark/paper_review.py

from .base import BaseBenchmark
from pathlib import Path
import subprocess
import sys

class PaperReviewBenchmark(BaseBenchmark):
    """论文评审领域Benchmark"""
    
    def __init__(self, output_dir: Path):
        super().__init__("paper_review", output_dir)
        self.skill_root = Path(__file__).resolve().parents[1]  # 实际部署用 __file__ 推导，不硬编码机器路径
        self.metacog_script = self.skill_root / "scripts" / "metacog.py"
    
    def setup(self):
        """初始化论文评审环境"""
        self.test_dir = self.output_dir / "test-env" / "paper-review"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        subprocess.run(
            [sys.executable, str(self.metacog_script), "init"],
            cwd=self.test_dir,
            capture_output=True
        )
        
        self.test_papers = self.generate_test_papers(30)
    
    def generate_test_papers(self, count: int) -> list:
        """生成测试论文"""
        papers = []
        for i in range(1, count + 1):
            papers.append({
                "id": f"PAPER-{i:03d}",
                "quality": self.get_random_quality(),
                "issues": self.get_paper_issues(),
                "innovativeness": self.get_random_innovativeness()
            })
        return papers
    
    def get_random_quality(self) -> str:
        """随机选择论文质量"""
        import random
        return random.choice(["excellent", "good", "average", "poor"])
    
    def get_paper_issues(self) -> list:
        """生成论文问题"""
        import random
        issues = []
        if random.random() > 0.5:
            issues.append("methodology_weak")
        if random.random() > 0.6:
            issues.append("experiment_insufficient")
        if random.random() > 0.7:
            issues.append("innovation_lack")
        return issues
    
    def get_random_innovativeness(self) -> float:
        """随机创新度"""
        import random
        return random.uniform(0.3, 0.9)
    
    def run_episode(self, episode_num: int) -> dict:
        """运行单个评审episode"""
        paper = self.test_papers[(episode_num - 1) % len(self.test_papers)]
        
        review_result = self.simulate_review(paper)
        
        return {
            "episode": episode_num,
            "paper_id": paper["id"],
            "quality": paper["quality"],
            "review_result": review_result
        }
    
    def simulate_review(self, paper: dict) -> dict:
        """模拟论文评审"""
        import random
        
        base_score = {"excellent": 0.9, "good": 0.7, "average": 0.5, "poor": 0.3}
        quality_score = base_score.get(paper["quality"], 0.5)
        
        # 根据问题调整分数
        issue_penalty = len(paper["issues"]) * 0.1
        final_score = max(0.1, quality_score - issue_penalty)
        
        return {
            "score": round(final_score, 4),
            "issues_found": len(paper["issues"]),
            "recommendation": self.get_recommendation(final_score)
        }
    
    def get_recommendation(self, score: float) -> str:
        """生成推荐意见"""
        if score >= 0.8:
            return "accept"
        elif score >= 0.6:
            return "minor_revision"
        elif score >= 0.4:
            return "major_revision"
        else:
            return "reject"
    
    def evaluate(self, episode_result: dict) -> dict:
        """评估评审质量"""
        review = episode_result["review_result"]
        paper = episode_result
        
        # 计算utility（评审准确性）
        expected_score = {"excellent": 0.9, "good": 0.7, "average": 0.5, "poor": 0.3}
        expected = expected_score.get(paper["quality"], 0.5)
        
        accuracy = 1 - abs(review["score"] - expected)
        utility = accuracy * 0.7 + (review["score"] * 0.3)
        
        # violations：遗漏关键问题
        violations = max(0, len(paper["issues"]) - review["issues_found"])
        
        return {
            "utility": round(utility, 4),
            "violations": violations,
            "accuracy": round(accuracy, 4),
            "score": review["score"],
            "recommendation": review["recommendation"]
        }
    
    def generate_report(self) -> dict:
        """生成报告"""
        if not self.results:
            return {"error": "无结果"}
        
        utilities = [r["evaluation"]["utility"] for r in self.results]
        accuracies = [r["evaluation"]["accuracy"] for r in self.results]
        violations = [r["evaluation"]["violations"] for r in self.results]
        
        return {
            "domain": self.domain,
            "episode_count": len(self.results),
            "duration_seconds": (self.end_time - self.start_time).total_seconds(),
            "average_utility": sum(utilities) / len(utilities),
            "average_accuracy": sum(accuracies) / len(accuracies),
            "average_violations": sum(violations) / len(violations),
            "utility_trend": self.calculate_trend(utilities)
        }
```

**验收标准**:
- [ ] PaperReviewBenchmark类实现完整
- [ ] 生成30个测试论文
- [ ] 评审准确性评估正确
- [ ] 报告包含accuracy指标

**验证脚本**:
```bash
python scripts/benchmark/run-paper-review.py
# 预期: 生成报告，accuracy趋势可分析
```

---

#### 3.1.4 实现统一运行器（120分钟）
```python
# scripts/benchmark/run_all.py

from pathlib import Path
import sys
import argparse
from .code_review import CodeReviewBenchmark
from .paper_review import PaperReviewBenchmark

def main():
    parser = argparse.ArgumentParser(description='运行所有benchmark')
    parser.add_argument('--domain', '-d', choices=['code_review', 'paper_review', 'all'],
                        default='all', help='选择领域')
    parser.add_argument('--episodes', '-e', type=int, default=100,
                        help='episode数量')
    parser.add_argument('--output', '-o', type=Path, default=Path('references/benchmark/results'),
                        help='输出目录')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='详细输出')
    
    args = parser.parse_args()
    
    # 确保输出目录存在
    args.output.mkdir(parents=True, exist_ok=True)
    
    benchmarks = []
    if args.domain in ['code_review', 'all']:
        benchmarks.append(CodeReviewBenchmark(args.output))
    if args.domain in ['paper_review', 'all']:
        benchmarks.append(PaperReviewBenchmark(args.output))
    
    all_reports = {}
    
    for benchmark in benchmarks:
        if args.verbose:
            print(f"\n运行 {benchmark.domain} benchmark...")
        
        report = benchmark.run(episode_count=args.episodes)
        all_reports[benchmark.domain] = report
        
        # 保存结果
        result_file = benchmark.save_results()
        
        if args.verbose:
            print(f"结果已保存到: {result_file}")
            print(f"平均utility: {report.get('average_utility', 'N/A')}")
            print(f"趋势: {report.get('utility_trend', 'N/A')}")
    
    # 生成汇总报告
    summary = generate_summary(all_reports)
    summary_file = args.output / "summary.json"
    summary_file.write_text(
        __import__('json').dumps(summary, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    
    print(f"\n汇总报告已保存到: {summary_file}")
    
    return 0

def generate_summary(reports: dict) -> dict:
    """生成汇总报告"""
    summary = {
        "timestamp": __import__('datetime').datetime.now().isoformat(),
        "domains": {}
    }
    
    total_episodes = 0
    total_duration = 0
    
    for domain, report in reports.items():
        summary["domains"][domain] = {
            "average_utility": report.get("average_utility"),
            "utility_trend": report.get("utility_trend"),
            "episode_count": report.get("episode_count"),
            "duration_seconds": report.get("duration_seconds")
        }
        total_episodes += report.get("episode_count", 0)
        total_duration += report.get("duration_seconds", 0)
    
    summary["total_episodes"] = total_episodes
    summary["total_duration_seconds"] = total_duration
    summary["average_duration_per_episode"] = total_duration / max(total_episodes, 1)
    
    return summary

if __name__ == "__main__":
    sys.exit(main())
```

**验收标准**:
- [ ] 可运行单领域benchmark
- [ ] 可运行所有领域benchmark
- [ ] 汇总报告正确生成
- [ ] 详细输出模式正常工作

**验证脚本**:
```bash
python scripts/benchmark/run_all.py --domain all --episodes 50 --verbose
# 预期: 运行两个benchmark，生成汇总报告
```

---

#### 3.1.5 添加可视化报告（60分钟）
```python
# scripts/benchmark/visualize.py

import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 非交互式后端

def visualize_benchmark(result_file: Path, output_dir: Path):
    """生成可视化报告"""
    
    # 读取结果
    with open(result_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    results = data.get("results", [])
    if not results:
        print(f"无结果可可视化: {result_file}")
        return
    
    # 提取数据
    episodes = [r["episode"] for r in results]
    utilities = [r["evaluation"]["utility"] for r in results]
    violations = [r["evaluation"]["violations"] for r in results]
    
    # 创建图表
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    
    # Utility趋势
    ax1 = axes[0]
    ax1.plot(episodes, utilities, 'b-', linewidth=1.5, label='Utility')
    ax1.axhline(y=sum(utilities)/len(utilities), color='r', linestyle='--', 
                label=f'Average: {sum(utilities)/len(utilities):.4f}')
    ax1.set_xlabel('Episode')
    ax1.set_ylabel('Utility')
    ax1.set_title(f'{data.get("domain", "Unknown")} - Utility Trend')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Violations趋势
    ax2 = axes[1]
    ax2.plot(episodes, violations, 'g-', linewidth=1.5, label='Violations')
    ax2.axhline(y=sum(violations)/len(violations), color='r', linestyle='--',
                label=f'Average: {sum(violations)/len(violations):.2f}')
    ax2.set_xlabel('Episode')
    ax2.set_ylabel('Violations')
    ax2.set_title(f'{data.get("domain", "Unknown")} - Violations Trend')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # 保存图表
    chart_file = output_dir / f"{data.get('domain', 'unknown')}-trend.png"
    plt.savefig(chart_file, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"图表已保存到: {chart_file}")
    
    return chart_file

def generate_html_report(results_dir: Path, output_file: Path):
    """生成HTML报告"""
    import json
    
    # 读取所有结果
    result_files = list(results_dir.glob("benchmark-*.json"))
    
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>Benchmark Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .domain { margin-bottom: 40px; padding: 20px; border: 1px solid #ddd; }
        .metric { display: inline-block; margin-right: 30px; }
        .trend-up { color: green; }
        .trend-down { color: red; }
        .trend-stable { color: gray; }
    </style>
</head>
<body>
    <h1>Benchmark Report</h1>
    <p>Generated: """ + __import__('datetime').datetime.now().isoformat() + """</p>
"""
    
    for result_file in result_files:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        domain = data.get("domain", "unknown")
        avg_utility = data.get("results", [{}])[0].get("evaluation", {}).get("utility", 0) if data.get("results") else 0
        trend = data.get("results", [{}])[0].get("evaluation", {}).get("trend", "stable") if data.get("results") else "stable"
        
        trend_class = f"trend-{trend}" if trend in ["up", "down", "stable"] else "trend-stable"
        
        html_content += f"""
    <div class="domain">
        <h2>{domain}</h2>
        <div class="metric">Episodes: {data.get('episode_count', 0)}</div>
        <div class="metric">Duration: {data.get('duration_seconds', 0):.1f}s</div>
        <div class="metric">Avg Utility: {avg_utility:.4f}</div>
        <div class="metric Trend: {trend} ({trend_class})</div>
        <img src="{domain}-trend.png" width="600">
    </div>
"""
    
    html_content += """
</body>
</html>
"""
    
    output_file.write_text(html_content, encoding='utf-8')
    print(f"HTML报告已保存到: {output_file}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        result_file = Path(sys.argv[1])
        output_dir = result_file.parent
        visualize_benchmark(result_file, output_dir)
    else:
        print("用法: python visualize.py <result_file.json>")
```

**验收标准**:
- [ ] 可视化函数正确生成图表
- [ ] HTML报告格式正确
- [ ] 图表包含趋势线和平均值

**验证脚本**:
```bash
python scripts/benchmark/visualize.py references/benchmark/results/benchmark-code_review-*.json
# 预期: 生成图表和HTML报告
```

---

### Phase 3.1 验收清单

- [ ] Benchmark框架设计完整（base.py）
- [ ] 代码评审benchmark实现通过（code_review.py）
- [ ] 论文评审benchmark实现通过（paper_review.py）
- [ ] 统一运行器测试通过（run_all.py）
- [ ] 可视化报告生成通过（visualize.py）
- [ ] 至少运行1个完整benchmark（100 episodes）
- [ ] 生成性能报告（references/benchmark/results/）
- [ ] 文档更新（SKILL.md添加benchmark说明）

**预计耗时**: 10小时  
**预期评分**: 85→95（+10分）

---

## 全局验收清单

### 代码验收
- [ ] Phase 1.1: M1自动触发逻辑正确（metacog.py修改）
- [ ] Phase 1.2: 棘轮自适应逻辑正确（metacog.py修改）
- [ ] Phase 2.1: 元认知日志系统完整（metacog.py新增）
- [ ] Phase 2.2: 领域模板系统完整（scripts/domains/新增）
- [ ] Phase 3.1: Benchmark框架完整（scripts/benchmark/新增）

### 测试验收
- [ ] 所有原有测试通过（test-core.py 13/13, test-boundary-cases.py 40/40）
- [ ] 新增测试通过（test-m1-trigger.py, test-adaptive-ratchet.py等）
- [ ] 集成测试通过（test-meta-log-integration.py）
- [ ] 跨领域测试通过（test-domain-migration.py）
- [ ] Benchmark测试通过（run_all.py）

### 文档验收
- [ ] SKILL.md更新（添加新功能说明）
- [ ] CHANGELOG.md更新（v2.0.0记录）
- [ ] 设计文档完整（references/design/）
- [ ] 用户指南更新（新增领域初始化示例）

### 安全验收
- [ ] 红线测试10/10通过
- [ ] 不动点保护正常
- [ ] A3 append-only正常
- [ ] M1自动触发仍需--human-ok确认
- [ ] 无新增安全漏洞

---

## 实施时间线

| 日期 | 阶段 | 任务 | 预计完成 |
|------|------|------|----------|
| Day 1 | Phase 1.1 | M1自动触发 | 17:00 |
| Day 1 | Phase 1.2 | 棘轮自适应 | 21:00 |
| Day 2 | Phase 2.1 | 元认知日志 | 13:00 |
| Day 2 | Phase 2.2 | 跨领域模板 | 19:00 |
| Day 3 | Phase 3.1 | 性能Benchmark | 15:00 |
| Day 3 | 验收 | 全局验收 | 18:00 |

**总计**: 3个工作日，30小时

---

## 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| M1自动触发误判 | 中 | 高 | 仍需--human-ok确认 |
| 棘轮阈值震荡 | 低 | 中 | epsilon容差+平滑处理 |
| 模板匹配错误 | 中 | 低 | 人工审核+用户配置 |
| Benchmark数据偏差 | 高 | 中 | 多次运行取平均 |
| 向后兼容性破坏 | 低 | 高 | 保持API兼容+逐步迁移 |

---

## 成功标准

### 功能成功
- [ ] M1自动触发正常工作
- [ ] 棘轮自适应正常工作
- [ ] 元认知日志正确记录
- [ ] 3个领域模板可用
- [ ] Benchmark可运行并生成报告

### 质量成功
- [ ] 评分达到95/100
- [ ] 所有测试通过（100+用例）
- [ ] 无安全漏洞
- [ ] 文档完整准确

### 性能成功
- [ ] 至少1个领域有真实性能数据
- [ ] Utility趋势可分析
- [ ] Violation_rate可监控

---

**落地清单制定完成**。按此清单执行，预计30小时完成v2.0，评分从59提升至95。

---

## 参考文档索引

- [参考文档索引](INDEX.md)
