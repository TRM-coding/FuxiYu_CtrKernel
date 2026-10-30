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

身份权限响应 SHALL 以 entities 表达生效方法权限，以布尔字段 image_resource_unrestricted 表达真实镜像资源通配能力。客户端 MUST NOT 仅凭方法通配展开出的 image:manage 推断用户有全部镜像资源范围；资源能力 SHALL 与后端实际资源门和列表范围使用同一判定。身份权限响应 SHALL 同时以布尔字段 container_resource_unrestricted 表达真实容器资源通配能力，其值 SHALL 等于 `has_resource_wildcard(user_id, "container")` 的派生结果，MUST NOT 持久化或新增表列。客户端 MUST NOT 仅凭 container:manage、hasAnyManage 或其他方法通配推断容器资源通配；容器资源通配 SHALL 与后端 `has_resource_wildcard` 及容器列表通配范围使用同一判定，ROOT 绑定仍按具体容器绑定另行判断。

#### Scenario: 只有方法实体通配

- **WHEN** 用户只有 bypass_auth_entity，没有直接镜像管理或全局资源通配
- **THEN** 即使方法权限列表包含 image:manage，快照也不将其表述为全部镜像资源可管理

#### Scenario: 具备全局资源通配

- **WHEN** 用户具备 bypass_resource
- **THEN** 快照如实表达镜像资源通配能力，相应方法权限仍按方法规则表达

#### Scenario: 容器方法通配不等于资源通配

- **GIVEN** 用户只有 bypass_auth_entity，因此 entities 可能包含 container:manage
- **WHEN** 请求 `/api/users/me/permissions`
- **THEN** `container_resource_unrestricted` 为 false，客户端不得据此显示全部容器资源管理能力

#### Scenario: 直持容器管理或全局资源通配

- **GIVEN** 用户直持 container:manage，或直持 bypass_resource
- **WHEN** 请求 `/api/users/me/permissions`
- **THEN** `container_resource_unrestricted` 为 true；该字段与 image_resource_unrestricted 各自独立判定

#### Scenario: 派生字段不落库

- **GIVEN** 权限快照响应包含 container_resource_unrestricted
- **WHEN** 检查 users 表列或数据库迁移
- **THEN** 不存在同名持久化列，也不新增表；该值每次请求由 has_resource_wildcard 派生

#### Scenario: 容器资源通配与镜像资源通配互不冒充

- **GIVEN** 用户直持 container:manage 但不直持 image:manage/bypass_resource
- **WHEN** 请求权限快照
- **THEN** `container_resource_unrestricted` 为 true 而 `image_resource_unrestricted` 为 false

### Requirement: 验证码注册按成功提交确认

带验证码注册 SHALL 复用现行用户名、邮箱、口令与毕业年份规则，在同一事务内完成用户创建与验证码消费。接口返回注册失败时 MUST NOT 因此前已通过验证码校验而消耗该码；默认用户组等必要注册步骤失败 SHALL 遵守同一成功边界。普通建号入口的既有行为及注册错误分类 SHALL 保留。

#### Scenario: 非法输入不消费有效验证码
- **WHEN** 有效验证码对应的注册输入不满足现有规则
- **THEN** 返回相应注册失败原因，验证码保持未消费，不创建部分用户记录

#### Scenario: 成功后不可重用
- **WHEN** 带验证码注册事务成功提交
- **THEN** 新用户及必要身份关联已生效，验证码不能再次用于注册

### Requirement: 用户删除原子清理所属草稿

删除用户的最终事务 SHALL 继续在同一工作单元内清理该用户认证记录并删除用户行；用户行删除成功时，`announcement_drafts.created_by` 的 `ON DELETE CASCADE` SHALL 删除该用户所属全部草稿。存在不允许遗弃的容器时 SHALL 按既有行为拒绝删除并保留用户、认证记录和草稿。事务任一步失败 MUST 整体回滚，MUST NOT 提交用户已删而草稿尚存、或草稿已删而用户尚存的半完成状态。其他用户草稿及公告、公告模板 MUST 保留。

#### Scenario: 有认证记录和草稿但无阻塞容器

- **WHEN** 删除仅有关联认证记录与所属草稿、没有阻塞容器的用户
- **THEN** 用户、其认证记录和所属草稿在同一事务提交后不存在，其他用户草稿、公告和模板保留

#### Scenario: 容器阻止删除

- **WHEN** 删除将产生不允许的野容器
- **THEN** 返回既有 `wild_container` 语义，用户、认证记录和所属草稿均保留

#### Scenario: 最终事务在级联后失败

- **WHEN** 最终删除事务在用户行及其草稿已被级联处理之后回滚
- **THEN** 用户、认证记录和草稿全部恢复到删除前状态，不出现半删除结果，其他用户与公告类数据不受影响

### Requirement: 密码修改与重置不吊销其他会话

用户成功修改密码或管理员成功重置密码时，系统 SHALL 只更新该用户的 `password_hash`；MUST NOT 删除该用户的 `authentications` 行，也 MUST NOT 删除其他用户的会话。修改/重置前已签发的 token SHALL 继续有效，直到自然过期、用户主动登出、用户被删除或既有认证规则使其失效。本变更 MUST NOT 新增会话吊销开关或新的 token 表结构。

#### Scenario: 修改密码保留其他会话

- **WHEN** 用户拥有多个有效 token，并成功修改自己的密码
- **THEN** 所有既有 token 仍存在且仍可解析为该用户；口令哈希已更新

#### Scenario: 重置密码保留其他会话

- **WHEN** 管理员成功重置某用户密码，该用户及其他用户已有有效 token
- **THEN** 该用户及其他用户的 token 均不被删除；只有目标用户的口令哈希更新

#### Scenario: 不新增吊销机制

- **WHEN** 检查密码修改/重置路径和认证表
- **THEN** 不存在因改密/重置而批量删除 token 的代码，也不存在新增的会话吊销字段或表

### Requirement: 毕业年份不可清空且保持非空

`users.graduation_year` 列 SHALL 保持 `nullable=False`。更新用户时，请求中的空字符串或 `null` MUST NOT 清空已保存的毕业年份；请求层空字符串 SHALL 继续归一为未提供，服务层 SHALL 忽略空值/空字符串。正常数值/非空字符串更新 SHALL 继续生效。

#### Scenario: 空字符串不阻塞其他更新且不清空

- **WHEN** 更新请求包含新的用户名和空字符串毕业年份
- **THEN** 用户名更新成功，数据库中的毕业年份保持原值

#### Scenario: null 不清空

- **WHEN** 更新请求只包含 `graduation_year: null` 或其他字段加 `graduation_year: null`
- **THEN** 毕业年份保持原值，不写入 NULL

#### Scenario: 服务层防御空字符串

- **WHEN** 内部调用更新用户时传入空字符串毕业年份
- **THEN** 该字段被忽略，已有毕业年份不变

#### Scenario: 列保持非空

- **WHEN** 检查 `users` 表模型或实际 DDL
- **THEN** `graduation_year` 仍为 `nullable=False`，不新增可空迁移或默认空串

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
