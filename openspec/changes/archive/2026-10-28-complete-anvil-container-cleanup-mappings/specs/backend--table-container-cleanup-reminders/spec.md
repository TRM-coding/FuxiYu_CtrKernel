# Spec Delta

## MODIFIED Requirements

### Requirement: container_cleanup_reminders 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `ContainerCleanupReminder`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: container_cleanup_reminders 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：每个 container_id 只有一条当前提醒记录；reminder_key 精确判重；真实 SSH 登录时间变化把提醒重置为 NEVER；cleanup_at/sent_at 为当次审计快照。

#### Scenario: 同档提醒判重

- **WHEN** 同一周期已发送当前 reminder_key
- **THEN** 不重复投递该档提醒；清理时间顺延不单独触发重发
