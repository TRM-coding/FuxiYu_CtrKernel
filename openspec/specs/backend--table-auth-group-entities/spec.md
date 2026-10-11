# auth_group_entities

## Purpose

权限组与稳定权限 code 的映射。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

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

## Data model appendix

### auth_group_entities 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `group_id` | `db.Column(db.Integer, db.ForeignKey('auth_groups.id', ondelete='CASCADE'), primary_key=True)` | 26 |
| `entity_code` | `db.Column(db.String(120), nullable=False, primary_key=True, index=True)` | 27 |

## Source references

- [models/auth_group.py](../../../models/auth_group.py)：AuthGroupEntity，第 21 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

