# Spec Delta

## MODIFIED Requirements

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
