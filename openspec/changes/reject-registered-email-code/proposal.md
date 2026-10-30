## Why

已注册邮箱仍可请求注册验证码，且现有服务端没有同邮箱请求冷却，容易造成重复邮件。

## What Changes

- 请求验证码时拒绝已注册邮箱，并对同一邮箱设置 60 秒冷却。
- 返回可区分的原因；复用现有验证码记录，不修改表结构。
- 发送成功或触发冷却时返回同一冷却记录计算出的剩余秒数，供注册页显示倒计时。

## Capabilities

### Modified Capabilities

- `backend--table-registration-codes`: 限制验证码发送。

## Impact

Ctrl 注册验证码入口、既有表读取和测试；不改变注册事务的唯一性保护。
