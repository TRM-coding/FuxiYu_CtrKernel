# container_disk_freeze_state

## Purpose

磁盘超限冻结升级锚点与不可用时长补偿。本规格按表结构记录当前持久化与生命周期契约，字段声明以模型与服务为依据。未完成问题见 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: container_disk_freeze_state 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `ContainerDiskFreezeState`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: container_disk_freeze_state 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：first_frozen_at 为冻结周期起点，grace_until 为人工宽限；机器不可用窗口关闭累加 deferral_seconds；用量低于限额 95% 时删除冻结状态。

#### Scenario: 容量恢复

- **WHEN** 磁盘用量回落至限额的 95% 以下
- **THEN** 清除冻结状态和该周期补偿，下一次冻结建立新锚点

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

## Data model appendix

### container_disk_freeze_state 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `container_id` | `db.Column(db.Integer, db.ForeignKey('containers.id', ondelete='CASCADE'), primary_key=True, nullable=False)` | 15 |
| `first_frozen_at` | `db.Column(db.DateTime, nullable=False)` | 21 |
| `grace_until` | `db.Column(db.DateTime, nullable=True)` | 24 |
| `created_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)` | 27 |
| `deferral_seconds` | `db.Column(db.Integer, nullable=True, default=0, server_default=db.text('0'))` | 33 |

## Source references

- [models/container_disk_freeze_state.py](../../../models/container_disk_freeze_state.py)：ContainerDiskFreezeState，第 6 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[test/container/test_freeze_days_consistency.py](../../../test/container/test_freeze_days_consistency.py)；运行结果以当前隔离安全套件为准。
