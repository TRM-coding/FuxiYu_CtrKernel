# Proposal

## Why

机器详情的响应模型丢弃真实 Node 端口，前端无法准确展示配置。注册验证码在用户注册成功前独立提交消费，导致用户修正注册冲突后无法重试。按已确认决策修复两个接口契约。

## What Changes

- 机器详情响应保留实际配置端口及空值语义，前端展示不硬编码默认端口。
- 验证码消费与用户创建在同一事务完成，失败保留验证码，成功后不可重复注册。
- 对并发校验和数据库异常提供安全的事务边界，沿用现有注册校验和错误语义。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-machines`: 机器详情端口响应与空值契约。
- `backend--table-registration-codes`: 验证码消费与成功注册一致，并发单次消费。
- `backend--table-users`: 注册流程组合事务及失败回滚。

## Impact

影响 Ctrl 机器详情响应、注册服务与验证码仓储，以及 Web 机器端口展示。数据库字段语义保持明确，注册错误与验证码有效期继续由后端裁决。
