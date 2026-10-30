## ADDED Requirements

### Requirement: 操作日志目标类型多选过滤

`GET /api/admin/operation_logs` SHALL 接受重复的 `target_type` 查询参数，并把多个值按 OR（等价 SQL `IN`）过滤；单个旧参数 MUST 继续按单值过滤。未提供 `target_type`、提供空序列或空字符串时 MUST NOT 添加目标类型条件。`operator_user_id`、`operation`、`success`、`start`、`end` 等其余条件 SHALL 继续与目标类型条件按 AND 组合。分页 SHALL 先按完整过滤结果计算总数和页数；统计接口口径 MUST 保持原有时间范围聚合，不因本变更增加目标类型筛选。管理日志 API MUST NOT 新增 `target_id` 过滤参数；repo 内部既有的 `target_id` 过滤 SHALL 继续保留给容器操作历史等既有调用，repo 对单个字符串 `target_type` 的调用 MUST 保持兼容。

#### Scenario: 重复参数按多值 OR 过滤

- **WHEN** 请求同时传入 `target_type=container` 与 `target_type=machine`
- **THEN** 返回目标类型为 container 或 machine 的日志，不返回其他目标类型

#### Scenario: 单个旧参数兼容

- **WHEN** 请求只传入一个 `target_type=container`
- **THEN** 仍按 container 过滤，行为与改造前一致

#### Scenario: 无值不筛选

- **WHEN** 请求未传 `target_type`，或只传入空值
- **THEN** 不添加目标类型条件，结果由其他筛选条件决定

#### Scenario: 与其他条件 AND

- **WHEN** 同时传入多个 `target_type`、`success=false`、`operator_user_id` 和时间范围
- **THEN** 先按目标类型 OR 命中，再与其他条件 AND，只返回全部条件都满足的日志

#### Scenario: 分页与统计口径不变

- **WHEN** 多值过滤后存在多页结果，或调用统计接口
- **THEN** 分页总数和页数按过滤后的集合计算；统计接口仍只按原时间范围聚合

#### Scenario: 管理端不新增 target_id 过滤

- **WHEN** 检查管理日志查询参数与请求处理
- **THEN** 不存在新增的 `target_id` 参数；repo 的 `target_id` 仅供容器历史等内部调用使用

### Requirement: 管理日志与容器历史同表查询且展示字段各自补充

管理日志查询与容器操作历史 SHALL 继续以 `operation_logs` 为同一数据源，分别调用既有查询后补充展示字段。管理日志 SHALL 补充 `target_name`、`target_display_name`、`root_owner` 等目标展示信息；容器操作历史 SHALL 补充 `operator_username` 并按容器创建时间过滤 id 复用前的旧日志。两者 MUST NOT 被强制要求返回相同 DTO 或相同展示字段，也 MUST NOT 为对齐 DTO 新增数据库列、缓存或持久化状态。

#### Scenario: 同表查询

- **WHEN** 查询管理日志或某个容器的操作历史
- **THEN** 两者都从 `operation_logs` 读取，不引入第二张日志表或复制日志数据

#### Scenario: 管理日志补充目标展示字段

- **WHEN** 管理日志目标仍存在或日志中保留历史名称
- **THEN** 按既有规则补充 `target_name`、`target_display_name`、`root_owner`，不改变稳定主键

#### Scenario: 容器历史单独补充操作员名称

- **WHEN** 查询容器操作历史
- **THEN** 按既有规则补充 `operator_username`，不要求同时返回管理日志的目标展示字段

#### Scenario: 不强制 DTO 一致

- **WHEN** 同一行日志同时出现在管理日志和容器历史中
- **THEN** 两个响应的字段集合可以不同；测试只锁定各自既有字段，不要求统一 DTO
