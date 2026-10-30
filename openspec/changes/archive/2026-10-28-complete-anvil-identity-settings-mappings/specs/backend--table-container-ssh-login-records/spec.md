# Spec Delta

## MODIFIED Requirements

### Requirement: container_ssh_login_records 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `ContainerSSHLogin`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: container_ssh_login_records 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：WSS last_ssh 快照更新真实登录时间；没有新观测保留旧值；登录变化清零补偿并复位清理提醒；软删查询排除无效容器。

#### Scenario: 机器不可用补偿

- **WHEN** 机器不可用窗口结束
- **THEN** 累加 deferral_seconds；清理倒计时扣除不可用时间，真实登录锚点保持不变
