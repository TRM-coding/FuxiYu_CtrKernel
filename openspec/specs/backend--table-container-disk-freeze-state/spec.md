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

### Requirement: 删除容器重置冻结状态

当通用容器软删除入口成功删除容器时，系统 SHALL 在同一数据库事务内删除该容器的 `container_disk_freeze_state` 记录，使 `first_frozen_at`、`grace_until`、`deferral_seconds` 等冻结类状态不再存在。无冻结记录 SHALL 视为正常完成；删除失败或事务回滚 MUST 保留原冻结记录，MUST NOT 提交半软删。重复调用通用软删除入口 SHALL 幂等。该清理 MUST 只作用于目标 `container_id`，不得影响其他容器。本变更 MUST NOT 新增删除旁路、恢复补偿清理、字段/表/JSON、迁移或后台修复。

#### Scenario: 成功删除清空冻结状态

- **WHEN** 一个带有冻结记录（含 `first_frozen_at`、`grace_until`、`deferral_seconds`）的容器经 API/清理等实际软删除路径成功
- **THEN** 同一事务提交后该容器的 `container_disk_freeze_state` 记录不存在，所有冻结类字段随记录清除，容器行按既有语义软删

#### Scenario: 无冻结记录正常完成

- **WHEN** 删除一个没有冻结记录的容器
- **THEN** 删除按既有语义成功完成，不因无冻结行可删而报错或回滚

#### Scenario: 删除失败或事务回滚保留冻结状态

- **WHEN** 删除事务在提交前失败并回滚
- **THEN** 容器行与冻结记录都保持删除前状态，不出现容器已软删而冻结记录仍残留，或冻结记录已清除而容器未软删的半完成结果

#### Scenario: 重复删除幂等

- **WHEN** 对同一已软删容器再次调用通用软删除入口
- **THEN** 不因容器已失效或冻结记录已不存在而失败，冻结状态保持不存在，不产生新的副作用

#### Scenario: 不影响其他容器

- **WHEN** 删除一个容器而同一机器或同一 root 用户下还有其他带冻结记录的容器
- **THEN** 只删除目标 `container_id` 的冻结记录，其他容器的冻结锚点、宽限与累计保持不变

### Requirement: 恢复新建不继承冻结周期

恢复容器 SHALL 按新建语义处理冻结状态：恢复路径 MUST NOT 复制、读取或续期删除前的冻结状态，MUST NOT 授予恢复宽限，MUST NOT 为表示宽限创建冻结行。按本变更删除路径成功删除的容器，恢复后无冻结记录即保持无记录；长期标记仍按既有快照配额与恢复路径处理，本要求只约束冻结状态与宽限。Q72 对同一未删除容器的累计 SHALL 保持不变；真正删除终止旧冻结周期，恢复新建 MUST NOT 被当作 Q72 续期。本变更 MUST NOT 增加恢复侧补偿清理、历史回填或后台修复。

#### Scenario: 恢复不继承旧冻结状态

- **WHEN** 一个带冻结记录的容器按本变更删除后，从删除快照恢复同一原行
- **THEN** 恢复后的容器没有继承的 `first_frozen_at`、`grace_until`、`deferral_seconds`，也没有因恢复而新建冻结行或宽限

#### Scenario: Q72 累计不被恢复续期

- **WHEN** 容器经历冻结、真正删除、再恢复
- **THEN** 旧冻结周期随删除终止；恢复后的容器从无冻结记录开始，只有之后实际发生冻结才建立新锚点与累计

#### Scenario: 同一未删除容器累计不变

- **WHEN** 容器未被真正删除，仅发生长期设置或取消（包括取消被拒绝）
- **THEN** 既有 `first_frozen_at`、`grace_until`、`deferral_seconds` 保持不变，不因本变更被提前重置

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
