## ADDED Requirements

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
