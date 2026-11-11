# backend--table-deleted-container-restore-snapshot Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: deleted_container_restore_snapshot 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_d01_restore_snapshot_readback_and_defaults
  - [X] test/container/test_deleted_containers.py::test_remove_container_records_deleted_snapshot_and_mount_cleanup
  - [X] test/machine/test_cleanup_deferral_window.py::TestDeferralAppliesToOtherDeadlines::test_window_close_credits_pending_deleted_snapshot
- Assertion scope: 删除流程生成一条 snapshot，关联 cleanup 行，snapshot 内保存 `container_name`、accounts 与 `mount_cleanup_id`；窗口关闭把 10 天可用性顺延累加到 `deferral_seconds`。 无按主键新会话读取全部字段/类型/默认值的断言；D01 补齐，并以裸 SQL 省略 `mount_cleaned`/`deferral_seconds` 验证 server_default=0。
- Coverage note: 现有 `[X]` 只覆盖创建时部分字段与 deferral 累加；D01 覆盖新会话读取、JSON 原样、默认值与可空列。

### Requirement: deleted_container_restore_snapshot 生产职责与生命周期

#### Scenario: 完成复活

- Test/check:
  - [X] test/container/test_deleted_containers.py::test_resurrect_container_reuses_snapshot_mount_and_restores_bindings
  - [ ] test/container/test_mount_cleanup_registry.py::test_restore_success_releases_restore_key
- Assertion scope: 成功恢复重建容器、恢复绑定，删除恢复快照与对应清理记录；新增用例断言恢复占位在成功返回后释放，随后同键清理可以重新登记。

#### Scenario: not_found 不消费快照

- Test/check:
  - [X] test/container/test_mount_path_action_guard.py::test_restore_missing_path_rejected_before_any_create
- Assertion scope: 无活动清理时，Node 路径检查 `not_found` 使恢复以 `data_not_recoverable` 拒绝；快照与清理记录保留，`cleaned_at` 为空，未创建容器、未写成功审计。

#### Scenario: 权限与非法路径不消费快照

- Test/check:
  - [X] test/container/test_mount_path_action_guard.py::test_restore_permission_denied_is_not_reported_as_missing
  - [ ] test/container/test_mount_path_action_guard.py::test_restore_invalid_path_does_not_consume_snapshot
- Assertion scope: `permission_denied` 行只证明原因、未误称缺失、未创建；`invalid_path` 计划行覆盖原因、快照/清理记录保留与未创建。`permission_denied` 的保留快照/清理记录事实未被现有用例断言。
- Coverage note: 不新增机械 permission 用例；保留 `[X]` 仅证明原因与未创建，保留事实由待建 `invalid_path` 用例覆盖其分支，permission 分支的保留断言仍是缺口。

#### Scenario: 无法得出结论必须阻断并保留快照

- Test/check:
  - [X] test/container/test_mount_path_action_guard.py::test_restore_unknown_path_state_blocks_with_retryable_reason
  - [X] test/container/test_mount_path_action_guard.py::test_restore_timeout_blocks_with_timeout_reason
  - [X] test/container/test_mount_path_action_guard.py::test_restore_offline_machine_blocks_without_node_call
  - [X] test/container/test_mount_path_action_guard.py::test_restore_api_unknown_is_5xx_not_not_found
- Assertion scope: 四行证明旧 Node/404/405、坏响应、超时、离线/API 的原因映射与未继续创建；只有 `test_restore_unknown_path_state_blocks_with_retryable_reason` 另断言快照/清理记录保留，其余三行未断言保留事实。
- Coverage note: timeout/offline/API 的“快照与清理记录保留、cleaned_at 为空”未被现有用例断言；不新增机械用例，保留 `[X]` 仅证明原因与未创建，不宣称四行都覆盖保留事实。

#### Scenario: 清理中拒绝恢复

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_restore_rejected_while_cleanup_active
- Assertion scope: 同键清理活动时恢复返回 409 `cleanup_in_progress`；Node 路径探测与创建未调用；快照/清理记录保留、`mount_cleaned` 不变、无成功审计、无凭据。

#### Scenario: 恢复占位覆盖关键阶段

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_restore_guard_blocks_cleanup_through_create_and_consume
- Assertion scope: 用事件阻塞 `Create_container` 或快照消费阶段，期间同键清理始终 409 `restore_in_progress`；恢复成功/失败返回后占位才释放，未在路径复核后提前放开。

#### Scenario: 恢复二选一或失败时释放占位

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_restore_requires_choice_and_failure_release_key
- Assertion scope: 返回 `requires_choice=true` 且未创建容器时恢复占位释放；恢复因异常失败时占位也释放；快照与清理记录按既有失败语义保留，后续可重新恢复或清理。

#### Scenario: 清理失败后恢复重新开放

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_restore_opens_after_cleanup_failed
- Assertion scope: 清理终态 `failed` 后恢复不再返回冲突；Node 路径检查 `present` 时继续恢复，`not_found` 时仍以 `data_not_recoverable` 拒绝；不把失败清理写成成功。

#### Scenario: 清理结果未知后恢复重新开放

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_restore_opens_after_cleanup_unknown
- Assertion scope: 清理未知后恢复不再返回冲突；Ctrl 不把未知当已清理，实际恢复由 Node 路径检查决定；路径存在时允许继续，目录不存在时拒绝。

#### Scenario: Ctrl 重启后恢复重新开放

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_restore_opens_after_registry_reset
- Assertion scope: 清空进程内登记（模拟 Ctrl 重启）后，同一删除记录的恢复请求不再被 `cleanup_in_progress` 阻止；不补查旧任务，快照与清理记录按数据库现状读取。

#### Scenario: 重复恢复冲突

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_duplicate_restore_conflicts
- Assertion scope: 第一次恢复持有占位时，第二次恢复返回 409 `restore_in_progress`；第二次不调用 Node 创建、不消费快照，第一次占位不被释放。

#### Scenario: 清理成功消费后不可恢复

- Test/check:
  - [X] test/container/test_deleted_containers.py::test_resurrect_container_rejects_cleaned_mount
- Assertion scope: 只证明 `mount_cleaned=true` 后恢复返回 `data_not_recoverable`；未断言进程内成功摘要过期或 Ctrl 重启后的行为。
- Coverage note: 摘要过期/重启后的不可恢复行为未由现有用例覆盖；不新增机械用例，`[X]` 仅证明 mount_cleaned 拒绝，不宣称已覆盖过期/重启。

### Requirement: Node realpath 恢复预留与共享登记

#### Scenario: 创建受理前 realpath 预留

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_node_realpath_restore_reservation_blocks_create_acceptance
  - [ ] test/container/test_cross_repo_protocol_replay.py::test_create_container_realpath_restore_reservation_contract
- Assertion scope: Ctrl 发起恢复时 Node 在 `/create_container` 受理前对 `restore_mount_path` 取 realpath；同 realpath 已有清理/恢复时，Node 在受理前返回 `cleanup_in_progress`/`restore_in_progress`，不启动创建；Ctrl 保留快照与清理记录、不写成功审计、不返回凭据。

#### Scenario: 词法别名由 Node realpath 拒绝

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_realpath_alias_blocks_second_cleanup_or_restore
  - [ ] test/container/test_cross_repo_protocol_replay.py::test_sync_async_cleanup_and_restore_share_realpath_registration
- Assertion scope: 在 Node 恢复预留/清理任务仍持有期间，Ctrl 词法键不同但 Node realpath 相同的第二个清理/恢复被共享登记拒绝；Ctrl 不因词法前置未拦截而继续创建或删除，冲突按失败/未知处理且不写成功。预留释放后的尾段不在本行保证范围。

#### Scenario: 预留释放与创建/账号恢复失败

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_node_restore_reservation_releases_after_create_failure
  - [ ] test/container/test_cross_repo_protocol_replay.py::test_restore_reservation_releases_on_create_failure
- Assertion scope: Node 恢复预留覆盖后台创建/账号恢复成功、失败并在 `finally` 释放；失败后同一 realpath 清理可重新登记，不追加 Docker Source 活挂载检查；Node 重启丢失预留按已接受边界处理，Ctrl 不补写成功。
- Coverage note: 预留释放后到 Ctrl 快照消费完成之间的词法别名尾段不保证互斥；本计划不新增该场景的机械测试，也不宣称 Docker 活挂载门禁。Node 侧预留/共享登记是跨仓契约，本仓库用 fake Node 与协议回放验证 Ctrl 对冲突/释放的消费。

### Requirement: 已删除容器列表清理状态投影

#### Scenario: 清理中列表展示

- Test/check:
  - [ ] test/container/test_mount_cleanup_list_state.py::test_list_shows_cleaning_and_disables_recoverable
- Assertion scope: 活动清理时列表记录 `mount_cleanup_state="cleaning"`、`mount_cleanup_error_reason=null`、`data_recoverable=false`，并保持 `cleaned_at=null`、`mount_cleaned=false`；不写数据库、不调用 Node。

#### Scenario: 失败终态列表展示

- Test/check:
  - [ ] test/container/test_mount_cleanup_list_state.py::test_list_shows_failed_with_reason_and_recoverable
- Assertion scope: 失败摘要在保留期内时返回 `mount_cleanup_state="failed"` 与稳定 `mount_cleanup_error_reason`；存在路径且未清理时 `data_recoverable=true`。

#### Scenario: 未知终态列表展示

- Test/check:
  - [ ] test/container/test_mount_cleanup_list_state.py::test_list_shows_unknown_without_faking_success
- Assertion scope: 未知摘要返回 `mount_cleanup_state="unknown"` 与稳定原因；`mount_cleaned=false`、`data_recoverable=true`；不把未知显示为已清理。

#### Scenario: 无进程内登记

- Test/check:
  - [X] test/container/test_deleted_containers.py::test_list_deleted_containers_returns_cleanup_state
  - [ ] test/container/test_mount_cleanup_list_state.py::test_list_without_registry_uses_existing_recoverable_rule
- Assertion scope: 既有用例确认无登记时列表仍返回记录且 `data_recoverable=true`；新增用例补齐 `mount_cleanup_state=null`、`mount_cleanup_error_reason=null` 与不调用 Node 的断言。

#### Scenario: 清理成功后的列表

- Test/check:
  - [ ] test/container/test_mount_cleanup_list_state.py::test_list_after_success_keeps_cleaned_facts
- Assertion scope: 成功清理后列表返回 `mount_cleaned=true`、`cleaned_at` 非空、`data_recoverable=false`；进程内成功摘要过期也不回退为可恢复。

#### Scenario: Ctrl 重启后的列表

- Test/check:
  - [ ] test/container/test_mount_cleanup_list_state.py::test_list_after_registry_reset_uses_database_only
- Assertion scope: 清空登记后列表 `mount_cleanup_state=null`，按数据库显示未清理与可恢复；不补写 `cleaning`/`failed`/`unknown`，不调用 Node。

#### Scenario: 目录不存在仍正常展示

- Test/check:
  - [ ] test/container/test_mount_cleanup_list_state.py::test_missing_directory_does_not_hide_or_fake_cleaned
- Assertion scope: 目录不存在时列表仍返回记录与历史路径，`mount_cleanup_state` 按登记为 null/failed/unknown，`mount_cleaned` 保持数据库值；不报 500、不隐藏记录、不伪造 `mount_cleaned=true`。

#### Scenario: 列表读取只读且不联系 Node

- Test/check:
  - [ ] test/container/test_mount_cleanup_list_state.py::test_list_cleanup_state_is_read_only_and_node_free
- Assertion scope: 列表读取前后数据库行、快照、清理记录不变；SQL 捕获无 INSERT/UPDATE/DELETE；fake Node sender 调用次数为 0；不探测文件系统。

### Requirement: 长期配额失败保留可重试恢复状态

#### Scenario: 失败后仍可恢复

- Test/check:
  - [X] test/container/test_restore_long_term_capacity.py::test_restore_rejects_at_capacity_before_any_restore_work
  - [X] test/container/test_restore_long_term_capacity.py::test_restore_retry_succeeds_after_capacity_is_freed
  - [X] test/container/test_restore_long_term_capacity.py::test_resurrect_api_maps_capacity_to_409_and_keeps_snapshot
- Assertion scope: 长期配额满：Node 无 create，容器仍软删，snapshot/cleanup 保留，失败日志 `long_term_limit_reached`；释放配额后同一 deleted_id 重试成功。

#### Scenario: 完成长期恢复

- Test/check:
  - [X] test/container/test_restore_long_term_capacity.py::test_restore_retry_succeeds_after_capacity_is_freed
  - [X] test/container/test_restore_long_term_capacity.py::test_restore_re_adds_marker_when_capacity_available
  - [X] test/container/test_restore_long_term_capacity.py::test_restore_keeps_existing_marker_idempotent
  - [X] test/container/test_deleted_containers.py::test_resurrect_container_reuses_snapshot_mount_and_restores_bindings
- Assertion scope: 恢复后长期标记存在且每个 root 仅一条；已有标记不重复插入；账号按快照恢复，snapshot/cleanup 消费。

### Requirement: 已删除容器遗留挂载用量查询接口

#### Scenario: 成功响应形状固定

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_api_success_returns_fixed_shape_without_path
  - [X] test/container/test_deleted_mount_usage.py::test_returns_three_states_omits_cleaned_and_unknown
- Assertion scope: HTTP 200 `success=1`，`usages` 一项；每项恰含 `deleted_id`/`bytes`/`measured_at`/`pending`/`error`，无 `path`；bytes=321、measured_at 为 Node 值、pending=false、error=null。

#### Scenario: 无挂载或已清理可省略

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_api_omits_cleaned_and_no_mount_without_node
  - [X] test/container/test_deleted_mount_usage.py::test_cleaned_rows_are_omitted_without_send
  - [X] test/container/test_deleted_mount_usage.py::test_row_without_mount_path_is_omitted_without_send
- Assertion scope: `mount_cleaned=true` 或 cleanup.`cleaned_at` 非空、或 snapshot 无 `mount_path` 的 id 从 usages 省略，且不向 Node 发请求、不返回缓存。

#### Scenario: 非法请求与权限错误

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_api_rejects_invalid_payload_and_extra_fields
  - [X] test/container/test_deleted_mount_usage.py::test_api_missing_body_returns_invalid_payload
  - [X] test/container/test_deleted_mount_usage.py::test_api_accepts_exactly_100_ids
  - [X] test/container/test_deleted_mount_usage.py::test_api_requires_container_manage
- Assertion scope: 空 body、0/-1/bool/float/str/None/字符串、>100、额外 `mount_path`/`machine_id` 均 400 `invalid_payload` 且不触达 Node；恰 100 个 id 通过；缺 `container:manage` 403 `insufficient_permission` 且不触达 Node。

### Requirement: 已删除用量只读解析与目标机器定向

#### Scenario: 只读解析并定向

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_uses_machine_specific_node_port
  - [X] test/container/test_deleted_mount_usage.py::test_readonly_resolution_does_not_write_or_call_write_helpers
  - [X] test/container/test_deleted_mount_usage.py::test_machine_id_falls_back_to_cleanup_record
- Assertion scope: 按记录 `machine_id` 解析 Node URL（IP:port），无写入 helper 调用、无 INSERT/UPDATE/DELETE，snapshot/cleanup 行与 `mount_cleaned` 不变；snapshot machine_id 缺失时回落 cleanup machine_id。

#### Scenario: 浏览器路径或记录不完整

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_missing_machine_id_is_not_found_and_not_sent
  - [X] test/container/test_deleted_mount_usage.py::test_api_rejects_invalid_payload_and_extra_fields
- Assertion scope: 记录缺 `machine_id` -> `not_found`、不发送（合法 id 的记录不完整分支）；请求带 host path -> 400 `invalid_payload`、不发送（请求模型非法字段分支）。该 400 行只证明模型拒绝，不证明携带宿主路径时的 `not_found`/省略分支。 父 Global Q82 已登记该规格冲突；本轮保留现有严格请求体校验，host path 的 `not_found`/省略分支未覆盖/暂缓，不改 app、主规格或业务返回。
- Coverage note: 两个分支分开限界：`test_missing_machine_id_is_not_found_and_not_sent` 只覆盖记录不完整 -> not_found；`test_api_rejects_invalid_payload_and_extra_fields` 只覆盖 host path -> 400。Q82 决定前不把 400 测试写成 not_found 证据。

#### Scenario: 不调用写库解析

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_readonly_resolution_does_not_write_or_call_write_helpers
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_d02_mount_usage_query_adds_no_schema
- Assertion scope: 查询期间 `resolve_mount_cleanup_request`、`ensure_mount_cleanup_record`、`ensure_deleted_record_for_cleanup` 均未被调用，无 DML，snapshot/cleanup 保持原值。 D02 以列/表集合直接检查该查询未新增 DB 列、表或 JSON 迁移；这是结构约束，不据此宣称查询行为。

### Requirement: Ctrl 对 Node 的批量路径查询

#### Scenario: 同机同路径合并，跨机不混

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_same_machine_same_path_sends_one_path_and_shares_result
  - [X] test/container/test_deleted_mount_usage.py::test_same_path_across_machines_is_queried_per_machine
- Assertion scope: 同机同路径只发一个 path，两个 id 共享 456；跨机同路径各发一次，111/222 不混。

#### Scenario: 三态与字段组合

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_returns_three_states_omits_cleaned_and_unknown
  - [X] test/container/test_deleted_mount_usage.py::test_pending_state_requires_all_explicit_fields
  - [X] test/container/test_deleted_mount_usage.py::test_missing_mount_field_is_bad_response
  - [X] test/container/test_deleted_mount_usage.py::test_empty_mount_field_is_bad_response
  - [X] test/container/test_deleted_mount_usage.py::test_valid_utc_iso_timestamp_variants_are_accepted
  - [X] test/container/test_deleted_mount_usage.py::test_non_utc_iso_timestamp_is_bad_response
- Assertion scope: 成功项 bytes>=0、measured_at=UTC ISO、pending=false、error=null；pending 项 bytes/measured_at=null、pending=true、error=null；错误项 bytes/measured_at=null、pending=false、稳定 error；缺字段/空串/非 UTC 时间均 `node_bad_response`。

#### Scenario: 重复查询 pending

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_repeated_query_has_no_ctrl_cache
- Assertion scope: 同一 id 连续两次查询：第一次 pending，第二次成功 999，两次 Node 调用，无 Ctrl 缓存。

### Requirement: Ctrl 查询错误映射与逐 id 回退

#### Scenario: 旧 Node 无接口

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_old_node_http_status_maps_unsupported
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_d03_node_unsupported_does_not_change_list_or_restore_eligibility
- Assertion scope: 404/405 -> `node_unsupported`，bytes/measured_at=null、pending=false。 D03 只补统计展示与列表 `data_recoverable` 不变；旧 Node 现在对恢复/手动清理失败关闭，由下方“统计展示与动作 guard 分离”覆盖。

#### Scenario: 超时、离线与坏响应

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_node_timeout_maps_timeout
  - [X] test/container/test_deleted_mount_usage.py::test_transport_error_string_timeout_is_classified_locally
  - [X] test/container/test_deleted_mount_usage.py::test_connection_failure_and_5xx_map_unavailable
  - [X] test/container/test_deleted_mount_usage.py::test_offline_machine_returns_unavailable_without_send
  - [X] test/container/test_deleted_mount_usage.py::test_bad_node_response_is_never_success
- Assertion scope: 超时（异常或文本）-> `node_timeout`；连接失败/5xx/离线 -> `node_unavailable`；2xx 缺 path/形状错误/缺 success -> `node_bad_response`；字段保持 null/false。

#### Scenario: 单机失败不阻塞其他机器

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_one_machine_failure_does_not_block_other_machine
  - [X] test/container/test_deleted_mount_usage.py::test_one_bad_path_does_not_poison_other_paths
  - [X] test/container/test_deleted_mount_usage.py::test_batch_deadline_keeps_fast_machine_success
- Assertion scope: 一台 500/一个坏 path 只影响对应 id，另一台/另一 path 仍返回 777/42，正确项不停滞。

#### Scenario: 严格匹配失败

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_bad_node_response_is_never_success
  - [X] test/container/test_deleted_mount_usage.py::test_one_bad_path_does_not_poison_other_paths
- Assertion scope: 缺 path、重复 path、path 与请求不一致、entry 非 dict、mounts 非 list 均 `node_bad_response`，不借用其他机器/path 的 bytes；一个坏 path 不污染同批好 path。

#### Scenario: 统计展示与动作 guard 分离

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_old_node_http_status_maps_unsupported
  - [X] test/container/test_mount_path_action_guard.py::test_restore_unknown_path_state_blocks_with_retryable_reason
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_unverified_paths_keep_a_distinct_reason
  - [X] test/container/test_mount_path_action_guard.py::test_restore_api_unknown_is_5xx_not_not_found
- Assertion scope: 旧 Node 404/405 在统计项仍为 `node_unsupported`；恢复以 `node_unsupported` 可重试原因拒绝且不调用 `/create_container`；手动清理以 `node_unsupported` 拒绝且不调用 `/clean_mount`；API 返回 502，不返回 `not_found`/`data_not_recoverable`。

#### Scenario: du 类错误不阻断动作

- Test/check:
  - [X] test/container/test_deleted_mount_usage.py::test_stable_node_error_reason_is_passed_through
- Assertion scope: 统计展示对 `non_zero_exit`/`du_unavailable`/`du_failed` 等 du 稳定错误原样保留 `error`，不填 0、不伪造成功。
- Coverage note: 动作 guard 对 du 类错误按 present 继续的分支未直接构造测试；现有用例只覆盖统计展示的透传，恢复/手动清理的该分支待补。

### Requirement: 已删除容器列表返回原容器有效态

#### Scenario: 原容器仍有效

- Test/check:
  - [X] test/container/test_deleted_validity_projection.py::test_deleted_record_projects_original_container_validity
- Assertion scope: 参数化 `valid=True` 时序列化结果与 `DeletedContainerRecord` 的 `original_container_is_valid` 均为 true。

#### Scenario: 原容器已软删

- Test/check:
  - [X] test/container/test_deleted_validity_projection.py::test_deleted_record_projects_original_container_validity
- Assertion scope: 参数化 `valid=False` 时字段为 false，不把软删行误报为缺失。

#### Scenario: 原容器行缺失

- Test/check:
  - [X] test/container/test_deleted_validity_projection.py::test_deleted_record_projects_original_container_validity
- Assertion scope: 参数化 `valid=None`（容器上下文无原行）时字段为 None，不填 false。

#### Scenario: 动态派生且只读

- Test/check:
  - [X] test/container/test_deleted_validity_projection.py::test_deleted_record_projects_original_container_validity
  - [X] test/container/test_deleted_containers.py::test_list_deleted_containers_returns_cleanup_state
- Assertion scope: 序列化直接取 `context["container"].is_valid`，不读取 `mount_cleaned`/`data_recoverable`；列表测试确认既有列表响应仍正常返回记录。
- Coverage note: 列表读取不写数据库与“无新列/迁移”未由 API 级测试直接断言；由 schema diff 与序列化测试间接覆盖，未新增数据库列。
