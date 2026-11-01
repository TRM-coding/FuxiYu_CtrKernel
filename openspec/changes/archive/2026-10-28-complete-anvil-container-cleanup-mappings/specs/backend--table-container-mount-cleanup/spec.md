# Spec Delta

## MODIFIED Requirements

### Requirement: container_mount_cleanup 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `ContainerMountCleanup`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: container_mount_cleanup 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：deleted 快照为保留生命周期权威，本表保存执行路径、removed_at、cleaned_at、escalation；手动、定时及磁盘升级清理共用服务门户。

#### Scenario: 清理成功

- **WHEN** Node 完成指定挂载目录清理
- **THEN** 在事务中记录 cleaned_at，并同步 deleted 快照的 mount_cleaned
