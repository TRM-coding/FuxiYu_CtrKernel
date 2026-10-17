# users

## Purpose

定义用户身份字段、权限快照及账号生命周期的当前契约。权限快照分别表达生效方法权限与真实镜像资源能力，用户删除遵守关联资源约束和认证记录事务清理边界。

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

### Requirement: 权限快照区分方法能力与镜像资源通配

身份权限响应 SHALL 以 entities 表达生效方法权限，以布尔字段 image_resource_unrestricted 表达真实镜像资源通配能力。客户端 MUST NOT 仅凭方法通配展开出的 image:manage 推断用户有全部镜像资源范围；资源能力 SHALL 与后端实际资源门和列表范围使用同一判定。

#### Scenario: 只有方法实体通配
- **WHEN** 用户只有 bypass_auth_entity，没有直接镜像管理或全局资源通配
- **THEN** 即使方法权限列表包含 image:manage，快照也不将其表述为全部镜像资源可管理

#### Scenario: 具备全局资源通配
- **WHEN** 用户具备 bypass_resource
- **THEN** 快照如实表达镜像资源通配能力，相应方法权限仍按方法规则表达

### Requirement: 验证码注册按成功提交确认

带验证码注册 SHALL 复用现行用户名、邮箱、口令与毕业年份规则，在同一事务内完成用户创建与验证码消费。接口返回注册失败时 MUST NOT 因此前已通过验证码校验而消耗该码；默认用户组等必要注册步骤失败 SHALL 遵守同一成功边界。普通建号入口的既有行为及注册错误分类 SHALL 保留。

#### Scenario: 非法输入不消费有效验证码
- **WHEN** 有效验证码对应的注册输入不满足现有规则
- **THEN** 返回相应注册失败原因，验证码保持未消费，不创建部分用户记录

#### Scenario: 成功后不可重用
- **WHEN** 带验证码注册事务成功提交
- **THEN** 新用户及必要身份关联已生效，验证码不能再次用于注册

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
