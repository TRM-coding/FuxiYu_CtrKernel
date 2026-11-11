## ADDED Requirements

### Requirement: 有效冻结天数在查询和调度中一致

查询返回的 days_frozen 及详情 freeze_days_frozen SHALL 使用与调度相同的有效冻结天数口径，扣除 deferral_seconds 并按完整天数计算，下限为零。既有宽限和机器不可用的调度门控 SHALL 保持其职责，不把累计自然天数误报为有效天数。

#### Scenario: 扣除累计补偿
- **WHEN** 冻结起点为 20 天前且补偿为 10 天
- **THEN** 查询和调度均按 10 个有效冻结天数处理

#### Scenario: 不满一天或补偿超过经过时间
- **WHEN** 扣除补偿后的冻结时间不足一天或小于零
- **THEN** 有效冻结天数为零，不返回负数

#### Scenario: 尚未冻结
- **WHEN** 不存在有效冻结起点
- **THEN** 不凭空生成冻结天数，维持查询与详情原有的未冻结字段空值语义
