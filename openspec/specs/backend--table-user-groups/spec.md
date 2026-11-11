# user_groups

## Purpose

用户所属 RBAC 权限组。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

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

## Data model appendix

### user_groups 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `user_id` | `db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)` | 8 |
| `group_id` | `db.Column(db.Integer, db.ForeignKey('auth_groups.id', ondelete='CASCADE'), primary_key=True)` | 9 |

## Source references

- [models/user_group.py](../../../models/user_group.py)：UserGroup，第 5 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

