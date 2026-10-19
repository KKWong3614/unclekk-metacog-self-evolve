# 改造计划书：unclekk-metacog-self-evolve v1.4.8 → v1.5.0

**制定日期**: 2026-09-08  
**基于**: 独立审计报告（45/100）  
**目标版本**: v1.5.0  
**目标评分**: 85/100 (+30分)

---

## 一、改造总览

### 当前状态
- **版本**: v1.4.8
- **评分**: 55/100（D级）
- **核心问题**: 声称是"元认知Agent"，实际是"规则演化引擎"
- **生产状态**: 部分就绪（可作为规则管理工具）

### 改造目标
- **版本**: v1.5.0
- **评分**: 85/100（B+级）
- **核心目标**: 实现M1自动触发、棘轮自适应、红线正则完善
- **生产状态**: 完全就绪

---

## 二、详细改造计划

### Phase 1: M1自动触发机制（预计6小时）

#### 1.1 设计阶段（1小时）
- 定义自动触发条件（连续3次REVERT）
- 设计M1提议模板
- 确定触发时机（任务结束后自动检查）

**输入**: 
- 独立审计报告P2-1
- metacog.py:776-789（现有连续REVERT检测）

**输出**:
- `references/design/m1-auto-trigger-spec.md`
- 触发条件定义文档

#### 1.2 实现阶段（3小时）
```python
# metacog.py 新增代码（约+80行）

def check_m1_auto_trigger(st):
    """检查是否需要自动触发M1提议"""
    r = st.get_ratchet()
    recent = [h["action"] for h in r["history"][-3:]]
    
    if len(recent) == 3 and all(a == "revert" for a in recent):
        # 自动创建M1提议
        m1_proposal = {
            "id": new_id("M1-AUTO"),
            "artifact": "M1",
            "op": "replace",
            "content": "## 元层自省\n连续3次REVERT，建议检查M1策略",
            "reason": "自动触发：连续REVERT",
            "triggered": True,
            "requires_human": True  # 仍需人工确认
        }
        st.save_proposal(m1_proposal)
        return True
    return False
```

**关键设计点**:
1. 自动检测连续3次REVERT
2. 自动创建M1提议（进入隔离区）
3. 仍需`--human-ok`确认（不破坏安全机制）
4. 记录触发日志（可追溯）

#### 1.3 测试阶段（2小时）
- 单元测试：触发条件检测
- 集成测试：完整流程验证
- 边界测试：误触发防护

**测试用例**:
```
test_m1_auto_trigger.py:
- 连续3次REVERT → 应触发
- 连续2次REVERT → 不应触发
- REVERT后PROMOTE → 不应触发
- 混合历史 → 不应触发
```

**验收标准**:
- ✅ 自动触发正确性
- ✅ 不破坏安全机制
- ✅ 日志完整可追溯

---

### Phase 2: 棘轮自适应机制（预计5小时）

#### 2.1 设计阶段（1小时）
- 设计自适应阈值算法
- 定义violation_rate对threshold的影响
- 确定更新频率

**算法设计**:
```python
# 自适应阈值
def adaptive_threshold(baseline_utility, violation_rate):
    """根据violation_rate动态调整阈值"""
    if violation_rate > 0.3:
        # 高违规率，降低阈值（更严格）
        return baseline_utility * 0.95
    elif violation_rate < 0.1:
        # 低违规率，提高阈值（更宽松）
        return baseline_utility * 1.05
    else:
        return baseline_utility

# 滑动窗口均值
def sliding_window_mean(window, epsilon=0.02):
    """滑动窗口均值，带epsilon容差"""
    if len(window) < 2:
        return None
    current_mean = sum(window) / len(window)
    prev_mean = sum(window[:-1]) / (len(window) - 1)
    
    # 如果变化在epsilon内，不更新
    if abs(current_mean - prev_mean) < epsilon:
        return prev_mean
    return current_mean
```

#### 2.2 实现阶段（3小时）
```python
# metacog.py 修改（约+50行）

class Ratchet:
    def __init__(self, base_utility=0.5, epsilon=0.02):
        self.base_utility = base_utility
        self.epsilon = epsilon
        self.window = []
    
    def update(self, utility, violation_rate):
        """更新棘轮状态"""
        self.window.append(utility)
        if len(self.window) > 5:
            self.window.pop(0)  # 保持窗口大小
        
        # 自适应阈值
        threshold = self.adaptive_threshold(violation_rate)
        
        # 滑动窗口均值
        new_base = self.sliding_window_mean(self.window)
        if new_base:
            self.base_utility = new_base
        
        return threshold
    
    def adaptive_threshold(self, violation_rate):
        """根据违规率调整阈值"""
        if violation_rate > 0.3:
            return self.base_utility * 0.95
        elif violation_rate < 0.1:
            return self.base_utility * 1.05
        return self.base_utility
```

#### 2.3 测试阶段（1小时）
- 阈值调整测试
- 滑动窗口测试
- 边界条件测试

**验收标准**:
- ✅ 高违规率时阈值降低
- ✅ 低违规率时阈值提高
- ✅ 窗口满时正确更新

---

### Phase 3: 红线正则完善（预计2小时）

#### 3.1 补充绕过模式（1小时）
```python
# metacog.py:48-49 修改

REDLINES = [
    # ... 现有正则 ...
    ("绕过安全检查", r"(跳过|绕过|忽略|关闭|禁用|免去|不做|无视|省略)[^\n]{0,8}?(审计|检查|确认|校验|验证|审核|闸门|门禁|gate|guard|review|测试)"),
    ("免人工确认", r"(无需|不用|不必|免|不再|别)[^\n]{0,6}?(用户|人工|人类|KK)?[^\n]{0,4}?(确认|询问|批准|授权)|auto[-_ ]?approve|自动(同意|批准|审批|通过)|先做了再说|skip.*?(approve|confirm|check)|自动执行|直接运行|无需确认|马上执行"),
    # 新增绕过模式
    ("规避审查", r"(暂时|临时|先|快速|简单)[^\n]{0,5}?(执行|运行|部署|发布)[^\n]{0,10}?(然后|之后再)?(审计|检查|测试)"),
    ("权限降级", r"(降权|降级|限制|缩小)[^\n]{0,10}?(权限|scope|范围)[^\n]{0,5}?(安全|审查)"),
]
```

#### 3.2 自动化测试（1小时）
```python
# test-boundary-cases.py 新增测试用例

def test_redline_bypass_patterns():
    """测试红线正则的绕过模式覆盖"""
    test_cases = [
        ("先执行再审计", True),
        ("快速运行然后检查", True),
        ("临时降权安全范围", True),
        ("自动执行无需确认", True),
        ("直接运行没问题", True),
        ("正常修改规则", False),
        ("添加新条目", False),
    ]
    
    for text, should_block in test_cases:
        result = check_redlines(text)
        assert result == should_block, f"误判: {text}"
```

---

## 三、实施时间表

### Week 1: M1自动触发（6小时）
- Day 1: 设计 + 实现（3小时）
- Day 2: 测试 + 验证（2小时）
- Day 3: 文档 + 提交（1小时）

### Week 2: 棘轮自适应（5小时）
- Day 1: 设计 + 实现（3小时）
- Day 2: 测试 + 验证（2小时）

### Week 3: 红线完善（2小时）
- Day 1: 实现 + 测试（2小时）

### 总时间: 13小时

---

## 四、验收标准

### 功能验收
| 功能 | 验收标准 | 权重 |
|------|----------|------|
| M1自动触发 | 连续3次REVERT自动创建M1提议 | 30% |
| 棘轮自适应 | 高violation_rate降低阈值 | 25% |
| 红线完善 | 覆盖新增绕过模式 | 20% |
| 测试覆盖 | 新增测试用例全部通过 | 25% |

### 性能验收
- 自动触发延迟 < 100ms
- 阈值计算 overhead < 1%
- 正则匹配性能无退化

### 安全验收
- 不引入新安全漏洞
- 不破坏现有安全机制
- 所有红线测试通过

---

## 五、风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| M1自动触发误判 | 中 | 高 | 仍需--human-ok确认 |
| 棘轮阈值震荡 | 低 | 中 | 添加epsilon容差 |
| 正则误匹配 | 中 | 中 | 自动化测试覆盖 |
| 向后不兼容 | 低 | 高 | 保持API兼容 |

---

## 六、预期成果

### 评分提升
- **当前**: 55/100
- **目标**: 85/100
- **提升**: +30分

### 功能增强
1. **M1自动触发**: 减少人工干预，提高演化效率
2. **棘轮自适应**: 动态调整阈值，适应不同环境
3. **红线完善**: 防止更多绕过模式

### 生产就绪
- ✅ 可作为"规则演化引擎"使用
- ✅ 可作为"元认知Agent原型"使用
- ✅ 评分达到B+级（85/100）

---

## 七、后续迭代（v1.6.0+）

### 可选优化
1. **跨领域迁移工具**: 添加领域模板自动化工具
2. **性能benchmark集成**: 自动记录性能数据
3. **可视化界面**: 规则演化监控面板

### 长期愿景
- 实现真正的"元认知自优化Agent"
- 支持多领域协同演化
- 自主发现并修复自身缺陷

---

**计划制定完成**。预计13小时实现v1.5.0，评分从55提升至85分。
