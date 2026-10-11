# authentications

## Purpose

不透明登录 token、归属用户和到期时间。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: authentications 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Authentication`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: authentications 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：登录清理过期 token 并创建新会话；API 依赖先检验 token，再解析 user_id；有效性同时依赖 expires_at。

#### Scenario: 验证过期会话

- **WHEN** expires_at 早于当前时间
- **THEN** 鉴权返回无效，不把过期会话当作有效身份

## Data model appendix

### authentications 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `token` | `db.Column(db.String(255), primary_key=True, unique=True, nullable=False, index=True)` | 8 |
| `expires_at` | `db.Column(db.DateTime, nullable=False)` | 9 |
| `user_id` | `db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)` | 10 |

## Source references

- [models/authentications.py](../../../models/authentications.py)：Authentication，第 5 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

