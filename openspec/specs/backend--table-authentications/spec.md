# authentications

## Purpose

不透明登录 token、归属用户和到期时间。本规格按表结构记录当前持久化与生命周期契约，字段声明以模型与服务为依据。未完成问题见 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

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

### Requirement: 认证失效与授权拒绝分离

受保护 API SHALL 将缺失、无效或过期的认证凭据判为 401；有效身份缺少业务权限 SHALL 返回 403。Token SHALL 仅关联用户身份及有效期，删除用户时随用户清理，MUST NOT 以容器状态决定 Token 生命周期。

#### Scenario: 无有效凭据
- **WHEN** 请求受保护 API 未带有效 Token
- **THEN** 返回 401，不能以一般权限拒绝的 403 代替

#### Scenario: 有身份但权限不足
- **WHEN** 有效登录用户缺少目标操作所需权限
- **THEN** 返回 403，不撤销该用户其他有效会话

#### Scenario: 内部运行态凭据与来源校验
- **WHEN** 内部运行态请求来自允许的本地来源但缺失或提供错误的共享 Token
- **THEN** 返回 401 invalid_token；非本地来源仍返回 403 forbidden，内部共享 Token 不作为用户 authentications 行处理

## Data model appendix

### authentications 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `token` | `db.Column(db.String(255), primary_key=True, unique=True, nullable=False, index=True)` | 16 |
| `expires_at` | `db.Column(db.DateTime, nullable=False)` | 17 |
| `user_id` | `db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)` | 18 |

## Source references

- [models/authentications.py](../../../models/authentications.py)：Authentication，第 5 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[test/user/test_auth_dependency_status.py](../../../test/user/test_auth_dependency_status.py)；运行结果以当前隔离安全套件为准。
