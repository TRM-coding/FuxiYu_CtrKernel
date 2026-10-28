# Spec Delta

> 本 delta 为测试对账用途：完整复制 `openspec/specs/backend--table-machine-permissions/spec.md` 中既有的 Requirement 块，Requirement 名、SHALL 语义、Scenario 名与 WHEN/THEN 原文均保持不变。不新增业务行为、不新增表或字段、不新增权限规则；不得为了迁就现有测试而削弱规格。

## MODIFIED Requirements

### Requirement: machine_permissions 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `MachinePermission`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: machine_permissions 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：唯一配对 user_id/machine_id；权限检查实时查询，添加为幂等语义，移除立即影响后续资源鉴权；机器和用户外键声明 CASCADE。

#### Scenario: 重复授权

- **WHEN** 对已有 user_id/machine_id 再次授权
- **THEN** 保持一条有效配对，不创建重复资源权限
