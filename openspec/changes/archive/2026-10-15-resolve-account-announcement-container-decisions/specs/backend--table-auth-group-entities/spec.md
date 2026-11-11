## ADDED Requirements

### Requirement: 自定义权限组允许清空实体

拥有组编辑权限的用户 SHALL 能将自定义组的实体集合替换为空，即使该组是其唯一管理能力来源。变更后 SHALL 按新的有效权限鉴权；内置 operator 组的既有锁定权限规则 SHALL 保留。

#### Scenario: 清空自身唯一管理组
- **WHEN** 用户将提供其唯一 rbac:manage 权限的自定义组清空
- **THEN** 更新成功，该用户随后失去该组提供的管理能力，后续受保护操作按新权限拒绝
