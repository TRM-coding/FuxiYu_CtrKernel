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

