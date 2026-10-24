## Test Plan

| Requirement | Scenario | Test File | Test Name | Initial State |
|-------------|----------|-----------|-----------|---------------|
| specs/backend--table-containers/spec.md → 容器创建与恢复生成一次性 root 密码 | 创建受理后返回 root 密码 | test/container/test_password_contracts.py | test_create_restore_credentials_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器创建与恢复生成一次性 root 密码 | 创建失败不返回密码 | test/container/test_password_contracts.py | test_create_restore_credentials_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器创建与恢复生成一次性 root 密码 | 恢复实际执行时生成新密码 | test/container/test_password_contracts.py | test_create_restore_credentials_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器创建与恢复生成一次性 root 密码 | 内容二选一不生成密码 | test/container/test_password_contracts.py | test_create_restore_credentials_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器创建与恢复生成一次性 root 密码 | 内部创建入口也不使用默认密码 | test/container/test_password_contracts.py | test_create_restore_credentials_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器账号密码重置的权限与目标校验 | ROOT 绑定用户重置协作者 | test/container/test_password_contracts.py | test_reset_permission_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器账号密码重置的权限与目标校验 | ROOT 绑定固定使用 root 登录名 | test/container/test_password_contracts.py | test_reset_permission_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器账号密码重置的权限与目标校验 | 资源管理通配可重置 | test/container/test_password_contracts.py | test_reset_permission_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器账号密码重置的权限与目标校验 | 仅实体通配被资源层拒绝 | test/container/test_password_contracts.py | test_reset_permission_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器账号密码重置的权限与目标校验 | ADMIN 或 COLLABORATOR 不能重置 | test/container/test_password_contracts.py | test_reset_permission_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器账号密码重置的权限与目标校验 | 目标用户未绑定被拒绝 | test/container/test_password_contracts.py | test_reset_permission_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器账号密码重置的权限与目标校验 | 绑定登录名非法被拒绝 | test/container/test_password_contracts.py | test_reset_permission_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器账号密码重置的权限与目标校验 | 机器离线时不生成密码 | test/container/test_password_contracts.py | test_reset_permission_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器账号密码重置的权限与目标校验 | 容器非 online 时不生成密码 | test/container/test_password_contracts.py | test_reset_permission_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器账号密码重置的权限与目标校验 | 额外字段不能指定登录名 | test/container/test_password_contracts.py | test_reset_permission_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器账号密码重置的权限与目标校验 | 错误按现有 reason 映射且不拼原始错误体 | test/container/test_password_contracts.py | test_reset_permission_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器密码重置的后台执行与一次性响应 | 受理后立即返回并后台请求 Node | test/container/test_password_contracts.py | test_reset_background_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器密码重置的后台执行与一次性响应 | 客户端断开不取消后台任务 | test/container/test_password_contracts.py | test_reset_background_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器密码重置的后台执行与一次性响应 | Node 失败只写失败 oplog | test/container/test_password_contracts.py | test_reset_background_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器密码重置的后台执行与一次性响应 | 后台复核失败只写 oplog | test/container/test_password_contracts.py | test_reset_background_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器密码重置的后台执行与一次性响应 | 密码响应不可缓存 | test/container/test_password_contracts.py | test_reset_background_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 新增协作者的一次性账号密码 | 新增 ADMIN 协作者返回密码 | test/container/test_password_contracts.py | test_add_collaborator_password_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 新增协作者的一次性账号密码 | 新增 COLLABORATOR 协作者返回密码 | test/container/test_password_contracts.py | test_add_collaborator_password_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 新增协作者的一次性账号密码 | Node 或绑定失败不写成功 | test/container/test_password_contracts.py | test_add_collaborator_password_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 新增协作者的一次性账号密码 | 前置校验失败不生成密码 | test/container/test_password_contracts.py | test_add_collaborator_password_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 新增协作者的一次性账号密码 | 后台最小 guard 复核失败只写失败日志 | test/container/test_password_contracts.py | test_add_collaborator_password_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 恢复协作者账号的瞬时密码兼容 | 恢复协作者账号使用瞬时随机密码 | test/container/test_password_contracts.py | test_restore_accounts_password_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 恢复协作者账号的瞬时密码兼容 | Node 拒绝瞬时密码时不回退弱默认值 | test/container/test_password_contracts.py | test_restore_accounts_password_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器密码不持久化且不可回查 | 一次性密码只在响应中出现 | test/container/test_password_contracts.py | test_password_persistence_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器密码不持久化且不可回查 | 失败响应与异常脱敏 | test/container/test_password_contracts.py | test_password_persistence_contract | 🟢 green |
| specs/backend--table-containers/spec.md → 容器密码不持久化且不可回查 | 无密码回查入口 | test/container/test_password_contracts.py | test_password_persistence_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类操作的日志复用与无密码约束 | 重置成功后记一条无密码日志 | test/operation_log/test_password_logs.py | test_password_log_codes_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类操作的日志复用与无密码约束 | 新增协作者成功记无密码日志 | test/operation_log/test_password_logs.py | test_password_log_codes_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类操作的日志复用与无密码约束 | ROOT 交接每一步单独留痕 | test/operation_log/test_password_logs.py | test_password_log_codes_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类操作的日志复用与无密码约束 | 创建和恢复保持单条日志 | test/operation_log/test_password_logs.py | test_password_log_codes_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类操作的日志复用与无密码约束 | Node 错误体含敏感值时审计仍脱敏 | test/operation_log/test_password_logs.py | test_password_log_codes_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类异步操作的结果日志时序 | 结果返回后记一条成功日志 | test/operation_log/test_password_logs.py | test_password_log_timing_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类异步操作的结果日志时序 | 受理时不写结果日志 | test/operation_log/test_password_logs.py | test_password_log_timing_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类异步操作的结果日志时序 | 重置失败记一条失败日志 | test/operation_log/test_password_logs.py | test_password_log_timing_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类异步操作的结果日志时序 | 新增协作者失败不写成功日志 | test/operation_log/test_password_logs.py | test_password_log_timing_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类异步操作的结果日志时序 | ROOT 交接部分失败如实记录 | test/operation_log/test_password_logs.py | test_password_log_timing_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类异步操作的结果日志时序 | 超时或未知结果不写成功 | test/operation_log/test_password_logs.py | test_password_log_timing_contract | 🟢 green |
| specs/backend--table-operation-logs/spec.md → 密码类异步操作的结果日志时序 | 日志写入失败不影响已受理结果 | test/operation_log/test_password_logs.py | test_password_log_timing_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → 单目标 ROOT 提升（transfer_root=false） | 详情页单目标升 ROOT 只返回 root 一项 | test/container/test_password_contracts.py | test_single_root_promotion_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → 单目标 ROOT 提升（transfer_root=false） | 单目标升 ROOT 不生成旧 owner 账号 | test/container/test_password_contracts.py | test_single_root_promotion_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → 单目标 ROOT 提升（transfer_root=false） | 机器/容器/目标不可用时不生成密码 | test/container/test_password_contracts.py | test_single_root_promotion_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接（transfer_root=true） | 正常单旧 ROOT 交接返回两项不同登录名 | test/container/test_password_contracts.py | test_root_handover_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接（transfer_root=true） | 旧 ROOT 降 ADMIN 的独立账号使用其系统用户名 | test/container/test_password_contracts.py | test_root_handover_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接（transfer_root=true） | 直接 ROOT 降 ADMIN 也返回独立账号密码 | test/container/test_password_contracts.py | test_root_handover_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接（transfer_root=true） | 多个旧 ROOT 时逐项处理并返回 | test/container/test_password_contracts.py | test_root_handover_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接（transfer_root=true） | `transfer_root=false` 不进入交接循环 | test/container/test_password_contracts.py | test_root_handover_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接（transfer_root=true） | 机器或容器不可用时不生成密码 | test/container/test_password_contracts.py | test_root_handover_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接（transfer_root=true） | 目标未绑定或用户名不可用时不生成密码 | test/container/test_password_contracts.py | test_root_handover_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接（transfer_root=true） | 调用者先被降级也不影响后续步骤 | test/container/test_password_contracts.py | test_root_handover_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接的逐步执行与失败边界 | 两步成功各记一条真实日志 | test/container/test_password_contracts.py | test_root_handover_steps_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接的逐步执行与失败边界 | 第一步失败不继续第二步 | test/container/test_password_contracts.py | test_root_handover_steps_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接的逐步执行与失败边界 | 第二步失败不伪报整体成功 | test/container/test_password_contracts.py | test_root_handover_steps_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接的逐步执行与失败边界 | 绑定更新失败也停止后续步骤 | test/container/test_password_contracts.py | test_root_handover_steps_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接的逐步执行与失败边界 | 后台最小 guard 复核失败只记失败 | test/container/test_password_contracts.py | test_root_handover_steps_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → ROOT 交接的逐步执行与失败边界 | Node 只改指定目标 | test/container/test_password_contracts.py | test_root_handover_steps_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → 删除用户内部 ROOT 提升的密码兼容 | 删除用户内部提升生成随机 root 密码 | test/container/test_password_contracts.py | test_delete_user_root_password_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → 删除用户内部 ROOT 提升的密码兼容 | 内部提升失败不回退弱密码 | test/container/test_password_contracts.py | test_delete_user_root_password_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → user_container 生产职责与生命周期 | 协作角色变更 | test/container/test_password_contracts.py | test_role_change_semantics_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → user_container 生产职责与生命周期 | 普通非 ROOT 角色互换不改密码 | test/container/test_password_contracts.py | test_role_change_semantics_contract | 🟢 green |
| specs/backend--table-user-container/spec.md → user_container 生产职责与生命周期 | 旧 ROOT 降为 ADMIN 保留独立账号密码 | test/container/test_password_contracts.py | test_role_change_semantics_contract | 🟢 green |
| specs/backend--table-users/spec.md → 权限快照区分方法能力与镜像资源通配 | 只有方法实体通配 | test/user/test_password_permission_snapshot.py | test_container_resource_snapshot_contract | 🟢 green |
| specs/backend--table-users/spec.md → 权限快照区分方法能力与镜像资源通配 | 具备全局资源通配 | test/user/test_password_permission_snapshot.py | test_container_resource_snapshot_contract | 🟢 green |
| specs/backend--table-users/spec.md → 权限快照区分方法能力与镜像资源通配 | 容器方法通配不等于资源通配 | test/user/test_password_permission_snapshot.py | test_container_resource_snapshot_contract | 🟢 green |
| specs/backend--table-users/spec.md → 权限快照区分方法能力与镜像资源通配 | 直持容器管理或全局资源通配 | test/user/test_password_permission_snapshot.py | test_container_resource_snapshot_contract | 🟢 green |
| specs/backend--table-users/spec.md → 权限快照区分方法能力与镜像资源通配 | 派生字段不落库 | test/user/test_password_permission_snapshot.py | test_container_resource_snapshot_contract | 🟢 green |
| specs/backend--table-users/spec.md → 权限快照区分方法能力与镜像资源通配 | 容器资源通配与镜像资源通配互不冒充 | test/user/test_password_permission_snapshot.py | test_container_resource_snapshot_contract | 🟢 green |

## Coverage Notes

- 测试只使用现有 SQLite 隔离夹具与 mock Node；后台线程在单测中由 fake spawn 同步执行，另设真实线程/断开用例。
- 每个 contract test 覆盖其 Requirement 下所有列出的 Scenario，并为每个 Scenario 保留独立断言；红灯以缺失行为/接口为准，不伪造。
- 完整安全套件优先 WSL Linux（有 du），Windows 隔离环境仅作补充；不连远程、不跑生产测试。
- 额外独立 wire contract：`test/container/test_account_wire_contracts.py`（父代理提供，未修改），13 passed，纳入 verify 证据。
