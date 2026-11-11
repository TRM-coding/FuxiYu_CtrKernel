## ADDED Requirements

### Requirement: 权限快照区分方法能力与镜像资源通配

身份权限响应 SHALL 以 entities 表达生效方法权限，以布尔字段 image_resource_unrestricted 表达真实镜像资源通配能力。客户端 MUST NOT 仅凭方法通配展开出的 image:manage 推断用户有全部镜像资源范围；资源能力 SHALL 与后端实际资源门和列表范围使用同一判定。

#### Scenario: 只有方法实体通配
- **WHEN** 用户只有 bypass_auth_entity，没有直接镜像管理或全局资源通配
- **THEN** 即使方法权限列表包含 image:manage，快照也不将其表述为全部镜像资源可管理

#### Scenario: 具备全局资源通配
- **WHEN** 用户具备 bypass_resource
- **THEN** 快照如实表达镜像资源通配能力，相应方法权限仍按方法规则表达
