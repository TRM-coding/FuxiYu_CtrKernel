# Proposal

## Why

六个身份与设置相关 backend 表能力共有 49 个 Scenario，现有断言分散在 repository、user、settings、operation_log、container 与 machine 测试中，缺少一份逐 Scenario 的可审查映射。部分 THEN 尚无直接断言，例如登录清理过期 token、容器资源通配与列表范围同判定、系统设置 min/max 拒绝、密码类日志的精确字段与时序、SSH 锚点在不可用补偿后保持不变。为避免后续 apply 把“已有测试”误当成“完整覆盖”，需要先建立映射与真实缺口清单。

## What Changes

- 为 `backend--table-authentications`、`backend--table-users`、`backend--table-registration-codes`、`backend--table-system-settings`、`backend--table-operation-logs`、`backend--table-container-ssh-login-records` 六个既有能力建立 no-op MODIFIED delta：原 Requirement 逐字保留，业务契约不变。
- 在本 change 的 test plan 中，把 49 个 Scenario 逐一映射到真实 existing test locator 或明确标记为待补的 planned test；中文 Assertion scope 描述实际断言边界，不记录运行结果。
- 计划新增 `test/repository/test_anvil_identity_settings.py` 承载真实缺口；缺口覆盖真实唯一 ROOT 绑定触发的野容器删除拒绝、403 后其他 token 存续与容器状态无关性、方法/资源通配分离、容器列表 `container:view` 门、每次请求派生且请求不新增表、ROOT 绑定独立判定、验证码哈希与无残留用户行、操作日志时段/目标过滤与完整请求体/Node 原始错误体脱敏、SSH 全部记录补偿。只使用现有 SQLite 隔离 fixture、factory 与 session，不修改生产代码、主 spec、sidecar、其他测试、共享 fixture、config、CI 或数据库。
- 只允许在外部边界使用替代：Node HTTP、SMTP、后台调度线程；不得 mock 被验证的目标逻辑，也不以静态源字符串或模型反射替代行为断言。

## Capabilities

### New Capabilities

无。本 change 不引入新能力。

### Modified Capabilities

- `backend--table-authentications`: 3 个 Requirement、5 个 Scenario；仅补映射，契约不变。
- `backend--table-users`: 5 个 Requirement、13 个 Scenario；仅补映射，契约不变。
- `backend--table-registration-codes`: 2 个 Requirement、5 个 Scenario；仅补映射，契约不变。
- `backend--table-system-settings`: 3 个 Requirement、5 个 Scenario；仅补映射，契约不变。
- `backend--table-operation-logs`: 6 个 Requirement、19 个 Scenario；仅补映射，契约不变。
- `backend--table-container-ssh-login-records`: 2 个 Requirement、2 个 Scenario；仅补映射，契约不变。

## Impact

- 受影响：本 change 的 proposal、delta specs、design、test plan，以及 apply 阶段计划新增的单一测试文件。
- 不受影响：业务源码、模型/迁移、主规格、主 sidecar、共享 fixture、配置、skills、CI、数据库、commit/push。
- 风险：恢复路径的单条 `CREATE_CONTAINER` 日志需要走真实软删与恢复流程；密码类日志的毫秒级时序需注入外部 Node 失败/超时并同步运行后台任务。两者都必须由 fresh review 先确认可测试性。
- 本 change 不含 review、tasks、tests 的实际写入；这些由父代理在独立 review 批准后继续。
