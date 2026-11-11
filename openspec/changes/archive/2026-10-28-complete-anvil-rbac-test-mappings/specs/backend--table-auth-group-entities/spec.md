# Spec Delta

> 本 delta 为测试对账用途：完整复制 `openspec/specs/backend--table-auth-group-entities/spec.md` 中既有的 Requirement 块，Requirement 名、SHALL 语义、Scenario 名与 WHEN/THEN 原文均保持不变。不新增业务行为、不新增表或字段、不新增权限规则；不得为了迁就现有测试而削弱规格。

## MODIFIED Requirements

### Requirement: auth_group_entities 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `AuthGroupEntity`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: auth_group_entities 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：AUTH_ENTITIES 为权限点目录的唯一来源；整组替换清理旧关联再插入新集合；operator 的锁定通配权限在服务层补齐。

#### Scenario: 替换权限点

- **WHEN** 请求只含目录中有效 code
- **THEN** 映射集合被整体替换并按稳定目录顺序返回，不把矩阵序号当实体 id

### Requirement: 自定义权限组允许清空实体

拥有组编辑权限的用户 SHALL 能将自定义组的实体集合替换为空，即使该组是其唯一管理能力来源。变更后 SHALL 按新的有效权限鉴权；内置 operator 组的既有锁定权限规则 SHALL 保留。

#### Scenario: 清空自身唯一管理组

- **WHEN** 用户将提供其唯一 rbac:manage 权限的自定义组清空
- **THEN** 更新成功，该用户随后失去该组提供的管理能力，后续受保护操作按新权限拒绝
