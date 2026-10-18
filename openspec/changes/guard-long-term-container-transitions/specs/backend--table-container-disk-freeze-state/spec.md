# Spec Delta

## ADDED Requirements

### Requirement: 删除容器重置冻结状态

当通用容器软删除入口成功删除容器时，系统 SHALL 在同一数据库事务内删除该容器的 `container_disk_freeze_state` 记录，使 `first_frozen_at`、`grace_until`、`deferral_seconds` 等冻结类状态不再存在。无冻结记录 SHALL 视为正常完成；删除失败或事务回滚 MUST 保留原冻结记录，MUST NOT 提交半软删。重复调用通用软删除入口 SHALL 幂等。该清理 MUST 只作用于目标 `container_id`，不得影响其他容器。本变更 MUST NOT 新增删除旁路、恢复补偿清理、字段/表/JSON、迁移或后台修复。

#### Scenario: 成功删除清空冻结状态

- **WHEN** 一个带有冻结记录（含 `first_frozen_at`、`grace_until`、`deferral_seconds`）的容器经 API/清理删除或 Node 消失删除成功
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
