# operation_logs

## Purpose

用户操作的结果与结构化差异审计。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: operation_logs 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `OperationLog`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: operation_logs 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：服务门户记录 operation、目标、success/error_reason、detail；查询按时段和目标过滤，响应补齐展示名并提供统计；目标 id 是审计引用。

#### Scenario: 失败操作留痕

- **WHEN** 受审计服务操作失败
- **THEN** 记录 success=False 与 error_reason，详情保留失败上下文，不把目标不存在视作可删除历史依据

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

### Requirement: 密码类操作的日志复用与无密码约束

容器密码重置、新增协作者、ROOT 交接与创建/恢复审计 SHALL 复用既有 `operation_logs`：重置使用新增操作码 `reset_container_password`（`target_type=container`、`target_id=container_id`，detail 至少含目标 `user_id` 与 `login_name`）；新增协作者沿用既有 `ADD_COLLABORATOR`，MUST NOT 为密码另建操作码或第二条记录；ROOT 交接的每个步骤沿用 `UPDATE_COLLABORATOR_ROLE`；创建/恢复保持现有 `CREATE_CONTAINER` 单条结果日志，MUST NOT 因生成密码、后台执行或返回凭据新增第二条创建日志。任何 detail、`error_reason`、审计文本 MUST NOT 含密码、`credentials` 对象、请求体、Node 原始错误体或可重建密码的片段。

#### Scenario: 重置成功后记一条无密码日志

- **GIVEN** 容器密码重置已被受理，Node 返回成功
- **WHEN** 后台任务完成
- **THEN** `operation_logs` 恰新增一条 `reset_container_password` 成功记录，`target_type=container`、`target_id=container_id`，detail 含目标 `user_id`/`login_name` 且不含密码或 `credentials`

#### Scenario: 新增协作者成功记无密码日志

- **GIVEN** 新增 ADMIN 或 COLLABORATOR 协作者已被受理，Node 创建账号与 Ctrl 写绑定成功
- **WHEN** 后台任务完成
- **THEN** 恰新增一条 `ADD_COLLABORATOR` 成功记录，detail 含目标用户与角色且不含密码

#### Scenario: ROOT 交接每一步单独留痕

- **GIVEN** ROOT 交接已受理，旧 ROOT 降 ADMIN 与目标升 ROOT 都成功
- **WHEN** 后台任务完成
- **THEN** 每个成功步骤各新增一条 `UPDATE_COLLABORATOR_ROLE` 成功记录（旧 ROOT 为 ROOT→ADMIN，目标为 ADMIN/COLLABORATOR→ROOT），detail 可区分目标与角色，且不含密码；不新增第二条创建日志

#### Scenario: 创建和恢复保持单条日志

- **GIVEN** 一次创建或实际恢复成功并已返回 root 密码
- **WHEN** 检查 `operation_logs`
- **THEN** 该容器只新增一条 `CREATE_CONTAINER` 结果记录；密码生成、凭据响应和后台执行都不产生第二条日志

#### Scenario: Node 错误体含敏感值时审计仍脱敏

- **GIVEN** Node 返回的错误体意外包含本次密码或完整请求体
- **WHEN** Ctrl 写失败 oplog
- **THEN** 记录的 `error_reason`/detail 只含稳定错误分类与目标标识，不含该密码、请求体或原始错误体

### Requirement: 密码类异步操作的结果日志时序

重置、新增协作者与 ROOT 交接在 HTTP 受理时 SHALL NOT 写结果日志；Node 结果返回后 SHALL 恰好追加对应步骤的成功或失败日志，`success`/`error_reason` 反映真实结果。Node 超时/未知结果 MUST 记为失败或未知，MUST NOT 写成 Node 确认成功。ROOT 交接 MUST NOT 在任何一步未完成时写“整体交接成功”；已完成步骤 SHALL 保留其成功日志，失败步骤写失败日志。失败日志 MUST 使用稳定、脱敏的 `error_reason` 与 detail。日志写入失败 MUST NOT 改变已受理操作的结果，也 MUST NOT 抛回调用方（沿用现有 `write_operation_log` 语义）。

#### Scenario: 结果返回后记一条成功日志

- **GIVEN** 重置、新增协作者或某个交接步骤的 Node 调用成功
- **WHEN** 对应绑定/账号处理完成
- **THEN** 恰新增一条该步骤的成功日志，且不含密码

#### Scenario: 受理时不写结果日志

- **GIVEN** 重置、新增协作者或 ROOT 交接刚刚返回 `accepted: true`
- **WHEN** 在后台任务完成前查询 `operation_logs`
- **THEN** 尚无该次操作的结果日志；此前已有的日志保持不变

#### Scenario: 重置失败记一条失败日志

- **GIVEN** 重置已被受理，Node 返回失败或抛异常
- **WHEN** 后台任务完成
- **THEN** 恰新增一条 `reset_container_password` 失败记录，`success=False` 且 `error_reason` 稳定，detail 含目标标识且不含密码、请求体或 Node 原始错误体；不新增成功记录

#### Scenario: 新增协作者失败不写成功日志

- **GIVEN** 新增协作者已被受理，Node 创建账号或 Ctrl 写绑定失败
- **WHEN** 后台任务完成
- **THEN** 只新增 `ADD_COLLABORATOR` 失败记录，不新增成功记录，不写协作者绑定，记录不含密码

#### Scenario: ROOT 交接部分失败如实记录

- **GIVEN** ROOT 交接已受理，旧 ROOT 降 ADMIN 成功，但目标升 ROOT 失败
- **WHEN** 后台任务完成
- **THEN** 旧 ROOT 的成功日志保留，目标步骤记失败日志；不写整体交接成功、不回滚旧 ROOT、不伪装完成，记录不含密码

#### Scenario: 超时或未知结果不写成功

- **GIVEN** 某密码类步骤的 Node 调用超时，或返回无法确认 success
- **WHEN** 后台记录结果
- **THEN** 写失败或未知原因记录，`success=False`；不得写成 Node 确认成功，detail 不含密码或原始错误体

#### Scenario: 日志写入失败不影响已受理结果

- **GIVEN** 后台任务已经完成 Node 调用，但写 oplog 时数据库异常
- **WHEN** 日志层抛出异常
- **THEN** 错误不抛回 HTTP 调用方（响应早已返回），不伪造成功日志，也不把密码写入备用日志

## Data model appendix

### operation_logs 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 9 |
| `operator_user_id` | `db.Column(db.Integer, nullable=True)` | 10 |
| `operation` | `db.Column(db.String(80), nullable=False)` | 11 |
| `target_type` | `db.Column(db.String(80), nullable=False)` | 12 |
| `target_id` | `db.Column(db.Integer, nullable=False)` | 13 |
| `detail` | `db.Column(db.JSON, nullable=True)` | 14 |
| `success` | `db.Column(db.Boolean, nullable=False, default=True)` | 15 |
| `error_reason` | `db.Column(db.String(255), nullable=True)` | 16 |
| `created_at` | `db.Column(db.DateTime, default=datetime.utcnow, nullable=False)` | 17 |

## Source references

- [models/operation_log.py](../../../models/operation_log.py)：OperationLog，第 6 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

