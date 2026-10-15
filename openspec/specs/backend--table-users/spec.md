# users

## Purpose

平台用户身份、登录凭据哈希和毕业年份。本规格按表结构记录当前持久化与生命周期契约，字段声明以模型与服务为依据。未完成问题见 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: users 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `User`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: users 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：username/email 各自唯一；身份由有效 token 和 RBAC 组派生，已不使用 users.permission；用户删除先处理容器归属与绑定。

#### Scenario: 创建用户

- **WHEN** 用户名和邮箱未占用且注册校验通过
- **THEN** 保存 password_hash 和用户信息，不在返回数据中暴露口令哈希

### Requirement: 用户删除与认证记录同事务清理

删除用户 SHALL 在最终删除事务中清理该用户所有 Token，MUST NOT 删除其他用户的 Token。存在不允许遗弃的容器时 SHALL 拒绝删除并返回 wild_container；认证记录不属于容器关联，MUST NOT 被解释为野容器。

#### Scenario: 有 Token 但无阻塞容器
- **WHEN** 删除仅有多个 Token 关联、没有其他业务记录阻止删除的用户
- **THEN** 用户及其全部 Token 被删除，其他用户及其 Token 保留

#### Scenario: 容器阻止删除
- **WHEN** 删除将产生不允许的野容器
- **THEN** 返回 wild_container，用户与 Token 均保留

#### Scenario: 删除事务失败
- **WHEN** 最终删除用户的数据库事务失败
- **THEN** 同事务 Token 清理回滚，不将非容器异常统一归因为 wild_container

## Data model appendix

### users 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 10 |
| `username` | `db.Column(db.String(80), unique=True, nullable=False, index=True)` | 11 |
| `email` | `db.Column(db.String(120), unique=True, nullable=False, index=True)` | 12 |
| `password_hash` | `db.Column(db.String(255), nullable=False)` | 13 |
| `created_at` | `db.Column(db.DateTime, default=datetime.utcnow)` | 14 |
| `graduation_year` | `db.Column(db.String(120), unique=False, nullable=False)` | 15 |

## Source references

- [models/user.py](../../../models/user.py)：User，第 7 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[test/user/test_user_tasks_profile.py](../../../test/user/test_user_tasks_profile.py)；运行结果以当前隔离安全套件为准。
