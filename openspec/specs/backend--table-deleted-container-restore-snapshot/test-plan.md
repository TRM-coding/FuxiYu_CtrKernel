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
  - [X] test/container/test_restore_long_term_capacity.py::test_restore_retry_succeeds_after_capacity_is_freed
  - [X] test/container/test_deleted_containers.py::test_resurrect_container_rejects_cleaned_mount
- Assertion scope: 恢复成功：容器行重建，账号绑定/GPU/挂载路径沿用快照；snapshot 与 cleanup 行均删除；`mount_cleaned=true` 的快照拒绝恢复且不产生半恢复。

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
- Assertion scope: 404/405 -> `node_unsupported`，bytes/measured_at=null、pending=false。 D03 补 Requirement 正文的“只影响统计显示，不影响原列表、恢复或清理；不改变资格、不做全盘扫描/全局总计/清理门禁/自动冻结、不改 clean_mount”。

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
