# Spec Delta

> 本 delta 为测试对账用途：完整复制 `openspec/specs/backend--table-user-groups/spec.md` 中既有的 Requirement 块，Requirement 名、SHALL 语义、Scenario 名与 WHEN/THEN 原文均保持不变。不新增业务行为、不新增表或字段、不新增权限规则；不得为了迁就现有测试而削弱规格。

## MODIFIED Requirements

### Requirement: user_groups 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `UserGroup`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: user_groups 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：复合主键绑定；有效方法权限为所属组实体并集，再应用管理域和通配规则；注册绑定默认 user 组，未绑定任何组的存量用户按默认 user 组兜底，seed 当前没有回填这些用户绑定。

#### Scenario: 更换用户权限组

- **WHEN** 所有 group_ids 存在且自锁保护校验通过
- **THEN** 用去重后的新集合替换旧绑定，后续鉴权即时采用新权限
