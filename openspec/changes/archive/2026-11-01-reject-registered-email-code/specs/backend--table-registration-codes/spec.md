## ADDED Requirements

### Requirement: 注册验证码邮件的基本防重复

系统 SHALL 在发送注册验证码前检查邮箱是否已注册；已注册时返回 `email_exists` 且不写验证码、不发送邮件。对同一邮箱忽略大小写检查已有验证码创建时间；60 秒内重复请求返回 `rate_limited`，不创建新验证码或发送邮件。同进程内检查与创建 SHALL 串行化；不新增数据库结构，不声称跨进程、跨机器或按 IP 完整限流。

#### Scenario: 已注册邮箱

- **WHEN** 已注册邮箱请求注册验证码
- **THEN** 返回 HTTP 409 `email_exists`，不创建验证码、不发邮件

#### Scenario: 同邮箱冷却

- **WHEN** 同一邮箱在上次创建验证码后 60 秒内再次请求
- **THEN** 返回 HTTP 429 `rate_limited`，不覆盖上次验证码、不重复发邮件

#### Scenario: 邮件发送失败

- **WHEN** 已创建验证码但邮件发送失败
- **THEN** 该验证码的创建时间仍参与冷却，不因发送失败立即重复投递

### Requirement: 验证码响应提供实际冷却时间

注册验证码请求 SHALL 仅在发送成功或返回 `rate_limited` 时，在响应体顶层提供非负整数 `retry_after_seconds`。其值 SHALL 由该邮箱同一条用于节流判断的创建时间和冷却期限计算，剩余不足一秒向上取整；成功发信所耗时间 SHALL 计入。其他失败响应 MUST NOT 包含该字段。

#### Scenario: 发送成功

- **WHEN** 验证码创建并成功发送
- **THEN** 成功响应提供该邮箱当前实际剩余冷却秒数，不固定返回完整 60 秒

#### Scenario: 请求命中冷却

- **WHEN** 同一邮箱再次请求并触发 `rate_limited`
- **THEN** HTTP 429 响应提供该邮箱当时的最新剩余冷却秒数，不刷新原冷却期限

#### Scenario: 发送失败后再次请求

- **WHEN** 验证码记录已创建但发信失败，随后同邮箱在冷却期内再次请求
- **THEN** 原失败响应不含 `retry_after_seconds`；后一次返回 `rate_limited` 和根据已有记录计算的剩余秒数

#### Scenario: 其他失败

- **WHEN** 请求因邮箱已注册、输入无效或其他错误失败，且不是 `rate_limited`
- **THEN** 响应不包含 `retry_after_seconds`
