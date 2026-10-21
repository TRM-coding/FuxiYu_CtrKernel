# Spec Delta

## ADDED Requirements

### Requirement: 操作日志目标回填批量读取并保持返回契约

日志列表 SHALL 保持既有 `target_name`、`target_display_name`、`root_owner` 字段、历史名称回退和容器代际判断；MUST NOT 新增缓存、持久化状态或返回字段。目标查询 MUST 按 `target_type` 批量执行，MUST NOT 按日志行逐行创建 session 或形成线性数量的查询。每类目标 SHALL 使用独立只读会话/事务：某类查询失败（含 DBAPI/事务级异常）时，主日志列表 SHALL 仍返回，该类型关联字段可为空，其他类型 SHALL 继续回填。

`root_owner` 是容器与 User 的联合展示字段：User 批量读取失败时 `root_owner` 可为空，容器自身的 `target_name` MUST NOT 因此丢失。25 行容器日志页的 SELECT 数量 SHALL 以目标类型数量为界，回归测试断言不超过 8 条。

#### Scenario: 混合目标类型

- **WHEN** 一页包含机器、容器、用户、镜像、权限组和历史目标
- **THEN** 各类型名称、历史名称与 root owner 回填结果保持原语义

#### Scenario: User 查询失败

- **WHEN** User 批量查询失败而容器查询成功
- **THEN** 主日志列表仍返回；容器 `target_name` 保持，`root_owner` 为空，后续类型仍正常回填

#### Scenario: 事务级失败隔离

- **WHEN** User 查询触发 DBAPI/事务级异常
- **THEN** 该类型字段安全为空，其他类型使用各自独立只读会话继续查询，不被失败事务毒化

#### Scenario: 25 行不线性增长

- **WHEN** 查询 25 条容器日志
- **THEN** 目标回填的 SELECT 数不随日志行数线性增长；测试断言整页不超过 8 条

### Requirement: 统计失败使用独立错误原因

统计接口异常 MUST 返回 `stats_failed`；日志列表接口异常 SHALL 继续返回 `list_failed`。两者不得混用。

#### Scenario: 统计查询失败

- **WHEN** 统计服务抛出异常
- **THEN** 响应中的 `error_reason` 为 `stats_failed`，列表失败路径仍为 `list_failed`
