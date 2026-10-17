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

