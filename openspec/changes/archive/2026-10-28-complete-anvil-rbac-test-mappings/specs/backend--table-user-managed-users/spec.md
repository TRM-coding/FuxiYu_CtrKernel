# Spec Delta

> 本 delta 为测试对账用途：完整复制 `openspec/specs/backend--table-user-managed-users/spec.md` 中既有的 Requirement 块，Requirement 名、SHALL 语义、Scenario 名与 WHEN/THEN 原文均保持不变。不新增业务行为、不新增表或字段、不新增权限规则；不得为了迁就现有测试而削弱规格。

## MODIFIED Requirements

### Requirement: user_managed_users 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `UserManagedUser`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: user_managed_users 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：管理查询读取 manager_user_id/managed_user_id 生成受管用户范围；当前无对应公开写入口，不将该未完成功能误记为全量可用。

#### Scenario: 查询管理范围

- **WHEN** 读取指定 manager_user_id
- **THEN** 返回已存在的 managed_user_id 集合，并由服务加入当前用户自身
