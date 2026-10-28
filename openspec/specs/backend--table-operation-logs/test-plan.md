# backend--table-operation-logs Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: operation_logs 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_operation_log_repo.py::test_write_and_list_desc_order
  - [X] test/repository/test_operation_log_repo.py::test_serialize_shape
  - [X] test/repository/test_operation_log_repo.py::test_stats_aggregation
- Assertion scope: 写入后按 id 倒序读回三条记录；serialize 恰含 id、operator_user_id、operation、target_type、target_id、detail、success、error_reason、created_at；success 为 bool，created_at 非空，detail 保留 JSON；统计聚合 total/succeeded/failed/by_operation/by_target_type/by_day。

### Requirement: operation_logs 生产职责与生命周期

#### Scenario: 失败操作留痕

- Test/check:
  - [X] test/operation_log/test_operation_log_tasks.py::test_each_repeated_failure_is_audited
  - [X] test/operation_log/test_operation_log_tasks.py::test_manual_failures_are_not_suppressed
  - [X] test/container/test_deleted_containers.py::test_manual_mount_preflight_failure_is_audited
  - [X] test/container/test_deleted_containers.py::test_each_automatic_and_manual_mount_failure_is_audited
  - [X] test/operation_log/test_operation_log_tasks.py::test_deleted_container_keeps_owner_without_navigation
  - [X] test/operation_log/test_operation_log_tasks.py::test_list_enriches_user_name_and_tolerates_deleted_target
  - [X] test/repository/test_operation_log_repo.py::test_list_filter_by_operator_and_operation
  - [X] test/repository/test_operation_log_repo.py::test_list_filter_by_success
  - [X] test/repository/test_operation_log_repo.py::test_list_time_range
  - [X] test/repository/test_anvil_identity_settings.py::test_operation_log_repo_filters_by_target_type_and_id
- Assertion scope: 每次失败各写一条 success=False 且 error_reason 稳定的记录；detail 保留触发方式/目标上下文；重复失败不被合并或抑制；目标已删除时日志仍可查询并保留历史展示名；已列 `[X]` locator 覆盖 operator/operation、success、start/end 时间过滤；`[ ]` 行用 repo `list_logs(target_type=..., target_id=...)` 写入不同 target_type/target_id 的日志，断言按目标过滤只返回匹配行。
- Coverage note: 时间与操作者/操作/success 过滤由 `[X]` locator 覆盖；target_type/target_id 过滤由 `[ ]` 行补齐。

### Requirement: 操作日志目标回填批量读取并保持返回契约

#### Scenario: 混合目标类型

- Test/check:
  - [X] test/operation_log/test_operation_log_tasks.py::test_list_enriches_every_supported_target_type
  - [X] test/operation_log/test_operation_log_tasks.py::test_deleted_container_keeps_owner_without_navigation
  - [X] test/operation_log/test_operation_log_tasks.py::test_list_enriches_user_name_and_tolerates_deleted_target
  - [X] test/operation_log/test_operation_log_tasks.py::test_list_skips_identity_mapping_for_previous_generation_log
  - [X] test/repository/test_anvil_identity_settings.py::test_operation_log_list_keeps_existing_response_fields
- Assertion scope: 一页内机器、容器、用户、镜像、权限组、设置与历史目标均按原语义回填 target_name/target_display_name/root_owner；目标已删除时保留历史展示名且不错误导航；日志早于当前容器 created_at 时不映射名称与超管；`[ ]` 行断言返回字段集合仍为既有 12 个，不新增缓存字段。
- Coverage note: 回填语义覆盖；“不新增返回字段”由 `[ ]` 行补齐。

#### Scenario: User 查询失败

- Test/check:
  - [X] test/operation_log/test_operation_log_tasks.py::test_user_query_failure_blanks_root_owner_only
- Assertion scope: User 批量查询抛错时主日志列表仍返回；容器 target_name 保留、root_owner 为空；后续 image 类型仍使用独立会话回填。

#### Scenario: 事务级失败隔离

- Test/check:
  - [X] test/operation_log/test_operation_log_tasks.py::test_user_dbapi_failure_does_not_poison_later_type_sessions
- Assertion scope: 对 `FROM USERS` 注入 DBAPI/事务级异常后，容器 target_name 保留、root_owner 为空，image 仍能新开 session 回填，失败事务不毒化后续类型。

#### Scenario: 25 行不线性增长

- Test/check:
  - [X] test/operation_log/test_operation_log_tasks.py::test_target_enrichment_query_count_does_not_grow_per_row
- Assertion scope: 25 条容器日志全部回填成功，SELECT 语句总数不超过 8，不随 25 行线性增长。

### Requirement: 统计失败使用独立错误原因

#### Scenario: 统计查询失败

- Test/check:
  - [X] test/operation_log/test_operation_log_api.py::test_stats_failure_uses_stats_failed
  - [X] test/operation_log/test_operation_log_api.py::test_list_failure_keeps_list_failed
- Assertion scope: 统计服务抛异常时 API 返回 500 `stats_failed`；列表服务抛异常时返回 500 `list_failed`；两者 message 分别为 `stats failed` 与 `query failed`，不混用。

### Requirement: 密码类操作的日志复用与无密码约束

#### Scenario: 重置成功后记一条无密码日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_codes_contract
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_reset_password_success_log_has_target_and_no_secret
- Assertion scope: Node 成功后恰新增一条 `reset_container_password` 成功日志，无第二条；已列 `[X]` locator 断言 success=True 且密码不出现在 detail；`[ ]` 行补 target_type=container、target_id=container_id、detail 含 user_id/login_name 且不含密码或 credentials。
- Coverage note: 条数与无密码覆盖；稳定目标字段与 detail 身份字段由 `[ ]` 行补齐。

#### Scenario: 新增协作者成功记无密码日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_codes_contract
  - [X] test/container/test_password_contracts.py::test_add_collaborator_password_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_add_collaborator_success_log_has_user_and_role
- Assertion scope: Node 创建账号与绑定成功后恰新增一条 `ADD_COLLABORATOR` 成功日志，不新增密码专用操作码；已列 `[X]` locator 断言 len=1、success=True、密码不在 detail；`[ ]` 行补 detail 含目标 user_id/username 与 role。
- Coverage note: 条数与无密码覆盖；目标用户与角色字段由 `[ ]` 行补齐。

#### Scenario: ROOT 交接每一步单独留痕

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_codes_contract
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_root_handover_logs_distinguish_each_step
- Assertion scope: 两步成功时恰有 2 条 `UPDATE_COLLABORATOR_ROLE` 成功日志，旧 ROOT 与目标各一条；已列 `[X]` locator 断言条数、success 与无密码；`[ ]` 行补 detail 可区分目标与新旧角色，且不新增第二条创建日志。
- Coverage note: 条数与无密码覆盖；角色/目标区分与“无额外创建日志”由 `[ ]` 行补齐。

#### Scenario: 创建和恢复保持单条日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_codes_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_restore_writes_exactly_one_create_container_log
- Assertion scope: 已列创建路径 `[X]` locator 断言恰写一条 `CREATE_CONTAINER` 结果日志，密码生成与凭据响应不产生第二条；`[ ]` 行走真实软删与恢复流程，断言恢复同样只写一条 `CREATE_CONTAINER`，detail 标记 resurrect 且不含密码。
- Coverage note: 创建侧覆盖；恢复侧的单条日志与无密码无直接断言。

#### Scenario: Node 错误体含敏感值时审计仍脱敏

- Test/check:
  - [X] test/container/test_password_contracts.py::test_untrusted_reason_redaction_contract
  - [X] test/container/test_password_contracts.py::test_password_persistence_contract
  - [X] test/container/test_role_adversarial.py::test_node_failure_during_demotion_stops_before_promotion
  - [X] test/repository/test_anvil_identity_settings.py::test_reset_failure_writes_exactly_one_redacted_log
- Assertion scope: Node error_reason 回显密码时，重置/新增协作者只存白名单 `reset_failed`/`add_failed`，创建异常 reason 为 `create_failed`；HTTP 错误不回显未受信 reason；detail/error_reason 不含密码；`[ ]` 行在真实 reset 失败路径注入完整请求体哨兵与 Node 原始错误体哨兵，断言审计记录的任何字段和拼接文本都不含这两个哨兵。
- Coverage note: 密码位于 error_reason/detail 的路径由 `[X]` locator 覆盖；请求体与 Node 原始错误体的脱敏由 `[ ]` 行补齐。

### Requirement: 密码类异步操作的结果日志时序

#### Scenario: 结果返回后记一条成功日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
- Assertion scope: 后台 target 执行前无结果日志；执行成功后重置恰新增一条成功日志且不含密码；ROOT 两步成功恰有两条角色成功日志。

#### Scenario: 受理时不写结果日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_accepted_password_operation_keeps_existing_logs_unchanged
- Assertion scope: `start_reset_container_password` 返回后、后台执行前，`reset_container_password` 日志为空且未调用 Node；`[ ]` 行预置一条无关日志，断言受理只新增凭据响应，不改变既有日志。
- Coverage note: “受理时不写结果日志”覆盖；“此前已有日志保持不变”由 `[ ]` 行补齐。

#### Scenario: 重置失败记一条失败日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
  - [X] test/container/test_password_contracts.py::test_untrusted_reason_redaction_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_reset_failure_writes_exactly_one_redacted_log
- Assertion scope: Node 返回失败或抛异常后存在失败记录，success=False、error_reason 稳定为 `reset_failed`，detail/error_reason 不含密码；`[ ]` 行断言恰一条失败且无新增成功，target_type=container、target_id=container_id、detail 含 user_id/login_name，并注入完整请求体与 Node 原始错误体哨兵后断言任何日志字段/拼接文本都不含哨兵。
- Coverage note: 失败方向与密码脱敏由 `[X]` locator 覆盖；精确条数、无新增成功、稳定目标字段、请求体/Node 原始错误体脱敏由 `[ ]` 行补齐。

#### Scenario: 新增协作者失败不写成功日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_password_contracts.py::test_add_collaborator_password_contract
  - [X] test/container/test_password_contracts.py::test_untrusted_reason_redaction_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_add_collaborator_failure_writes_only_one_log
- Assertion scope: Node 创建账号或写绑定失败时不写协作者绑定、不新增成功日志，存在 `ADD_COLLABORATOR` 失败记录；已列 `[X]` locator 断言无成功、无绑定、error_reason `add_failed` 且无密码；`[ ]` 行补恰一条失败与 detail 目标字段。
- Coverage note: 失败方向覆盖；精确条数与稳定目标字段由 `[ ]` 行补齐。

#### Scenario: ROOT 交接部分失败如实记录

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_role_adversarial.py::test_machine_offline_between_steps_keeps_first_committed_fact
  - [X] test/container/test_role_adversarial.py::test_node_failure_during_demotion_stops_before_promotion
  - [X] test/container/test_role_adversarial.py::test_binding_failure_during_demotion_stops_before_promotion
  - [X] test/container/test_role_adversarial.py::test_db_or_audit_exception_does_not_rollback_committed_step
- Assertion scope: 旧 ROOT 降级成功后保留其成功日志与已提交绑定；目标步骤失败只写失败日志，不写“整体交接成功”，不回滚旧 ROOT；成功/失败计数可观察，所有日志不含密码。

#### Scenario: 超时或未知结果不写成功

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_role_adversarial.py::test_node_failure_during_demotion_stops_before_promotion
  - [X] test/repository/test_anvil_identity_settings.py::test_unknown_node_result_writes_failure_not_success
- Assertion scope: Node 超时/异常时存在 success=False 的失败记录，detail/error_reason 不含密码或原始错误体；已列 `[X]` locator 覆盖 TimeoutError/RuntimeError；`[ ]` 行覆盖返回无法确认 success 的未知结果，并断言不新增成功记录。
- Coverage note: 超时与异常覆盖；“未知结果不写成功”由 `[ ]` 行补齐。

#### Scenario: 日志写入失败不影响已受理结果

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_role_adversarial.py::test_db_or_audit_exception_does_not_rollback_committed_step
  - [X] test/repository/test_anvil_identity_settings.py::test_operation_log_write_failure_does_not_raise_or_leak_password
- Assertion scope: `log_success` 在 oplog 写入异常时返回 None、不抛回调用方；已提交的角色绑定不被日志异常回滚，成功/失败计数不出现第二条成功；`[ ]` 行在 Node 调用完成后对 operation_logs INSERT 注入 DBAPI 异常，断言后台任务不抛、不伪造成功日志、密码不进入备用日志。
- Coverage note: 已列 `[X]` locator 覆盖“不抛回/不回滚”；“不伪造成功日志/不泄露密码”由 `[ ]` 行补齐。
