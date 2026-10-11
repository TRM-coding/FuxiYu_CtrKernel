# long_term_containers

## Purpose

容器长期保留标记及授权者审计。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: long_term_containers 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `LongTermContainer`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: long_term_containers 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：以 container_id 唯一存在表示长期标记；服务执行配额和磁盘条件校验；移除标记后恢复短期清理策略。

#### Scenario: 重复标记

- **WHEN** 同一容器再次申请长期标记
- **THEN** 不生成第二条长期记录，容器身份通过主键保持唯一

## Data model appendix

### long_term_containers 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `container_id` | `db.Column(db.Integer, db.ForeignKey('containers.id', ondelete='CASCADE'), primary_key=True, nullable=False)` | 9 |
| `created_by_user_id` | `db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)` | 15 |
| `created_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)` | 21 |

## Source references

- [models/long_term_container.py](../../../models/long_term_container.py)：LongTermContainer，第 6 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

