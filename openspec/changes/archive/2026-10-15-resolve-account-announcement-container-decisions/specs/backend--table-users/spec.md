## ADDED Requirements

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
