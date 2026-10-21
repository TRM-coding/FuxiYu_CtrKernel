# user_container

## Purpose

用户与容器的协作角色及账号映射。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: user_container 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `UserContainer`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: user_container 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：复合主键 user_id/container_id；role 使用 ROLE 枚举控制协作操作；public_key 和 username 为 Node 账号操作的持久化输入。

#### Scenario: 协作角色变更

- **WHEN** 服务接受某用户某容器的角色变更
- **THEN** 更新唯一绑定上的 role，供后续鉴权及 Node 协作账号同步读取

## Data model appendix

### user_container 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `user_id` | `db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)` | 11 |
| `container_id` | `db.Column(db.Integer, db.ForeignKey('containers.id', ondelete='CASCADE'), primary_key=True, nullable=False)` | 16 |
| `role` | `db.Column(db.Enum(ROLE), nullable=False)` | 23 |
| `granted_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)` | 24 |
| `public_key` | `db.Column(db.String(500), nullable=True)` | 25 |
| `username` | `db.Column(db.String(120), nullable=False)` | 26 |

## Source references

- [models/usercontainer.py](../../../models/usercontainer.py)：UserContainer，第 8 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

