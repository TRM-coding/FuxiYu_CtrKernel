## ADDED Requirements

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
