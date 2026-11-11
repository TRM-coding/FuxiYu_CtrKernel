# backend--table-container-mount-cleanup Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: container_mount_cleanup 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_m01_mount_cleanup_readback_and_defaults
  - [X] test/repository/test_container_mount_cleanup_repo.py::TestMountCleanupRepo::test_insert_creates_record
  - [X] test/repository/test_container_mount_cleanup_repo.py::TestMountCleanupRepo::test_insert_with_escalation_and_cleaned
- Assertion scope: insert 后 id 非空，`container_name`、`escalation=False`、`cleaned_at=None`；带 `escalation=True`/`cleaned_at` 时原值返回。 无按主键新会话读取全部字段/类型/默认值的断言；M01 补齐。

### Requirement: container_mount_cleanup 生产职责与生命周期

#### Scenario: 清理成功

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_success_commits_cleanup_and_snapshot_in_one_transaction
  - [ ] test/container/test_mount_cleanup_async.py::test_success_log_keeps_trigger_and_escalation
- Assertion scope: Node 状态明确 `succeeded` 后，`container_mount_cleanup.cleaned_at` 非空、deleted 快照 `mount_cleaned=true`，两者在同一事务提交；日志写入成功时成功结果日志恰好一条、失败日志不存在；手动/自动/升级分别保留 `manual_clean_mount`/`auto_mount_cleanup`/`disk_escalation` trigger，升级同时 `escalation=true`；若快照标记抛错，事务回滚后两边都未标记且不写成功日志。

#### Scenario: 手动清理前新鲜检查通过

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_manual_fresh_check_then_start_keeps_running_until_succeeded
- Assertion scope: Ctrl 后台先对手动路径发送 `check_mount_usage` 并得到 present，再向 Node 发送 `start_clean_mount`（请求体 `{"config":{"mount_path":<记录路径>}}`）；返回非空 `task_id` 后任务保持 `running`，数据库仍未写 `cleaned_at`/`mount_cleaned`；不调用旧 `/clean_mount`；只有后续 `succeeded` 才落清理标记。

#### Scenario: 原容器已恢复为有效时拒绝手动清理

- Test/check:
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_refuses_live_mount_of_restored_valid_container
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_refuses_live_legacy_record_before_adoption
- Assertion scope: 原容器行 `is_valid=true` 时以 `container_exists` 拒绝，Node 未被调用；`cleaned_at` 保持空、`mount_cleaned=false`；legacy cleanup-only 记录也不会在拒绝前被收养/补建快照。

#### Scenario: not_found 拒绝手动清理并保留记录

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_manual_fresh_not_found_fails_without_starting_node
- Assertion scope: 手动后台新鲜检查返回 `not_found` 后任务终态为失败，写恰好一条失败日志；`cleaned_at=null`、`mount_cleaned=false`；`start_clean_mount`/旧 `/clean_mount` 均未调用、未写成功日志；列表显示 `failed` 且恢复重新开放。

#### Scenario: 权限、非法路径与网络错误不误称 not_found

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_manual_fresh_path_errors_keep_distinct_reasons
  - [ ] test/container/test_mount_cleanup_async.py::test_auto_and_escalation_node_errors_keep_distinct_reasons
- Assertion scope: 手动前置检查的 `permission_denied`/`invalid_path` 分别保留稳定原因；自动/升级启动/轮询的 `permission_denied`/`invalid_path`/旧 Node 404/超时/离线/坏响应分别映射 `permission_denied`/`invalid_path`/`node_unsupported`/`node_timeout`/`node_unavailable`/`node_bad_response`；全部不写 `cleaned_at`/`mount_cleaned`、不写成功日志，且不误报 `not_found`。

#### Scenario: 自动与升级清理维持既有语义

- Test/check:
  - [ ] test/container/test_container_mount_cleanup_task.py::test_scheduled_cleanup_submits_async_task_and_does_not_mark_on_accepted
  - [ ] test/container/test_container_disk_check_task.py::TestEscalationMountCleanup::test_escalation_submits_async_with_trigger_and_escalation
  - [ ] test/container/test_container_mount_cleanup_task.py::test_missing_directory_async_task_succeeds_idempotently
- Assertion scope: 定时扫描与磁盘升级清理都提交同一 `start_clean_mount` 异步任务并保留 `auto_mount_cleanup`/`disk_escalation` trigger、`operator=None`、升级 `escalation=true`；提交返回 accepted 后调度器不写 `cleaned_at`/`mount_cleaned`、不写成功日志，只有 Node 明确 `succeeded` 才落库；缺失目录按旧 `rm -rf` 幂等语义由异步任务成功处理；旧 `/clean_mount` 未被调用。

#### Scenario: 已清理记录幂等

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_manual_cleanup_already_cleaned_is_idempotent
- Assertion scope: 手动 API 对已清理记录返回 `accepted=false`/`already_cleaned=true`，不创建任务、不请求 Node、不新增结果日志、不改变时间戳；旧同步函数若保留仅供旧调用方，不作为当前入口。

### Requirement: 手动挂载清理的受理与异步终态

#### Scenario: 受理不等待清理完成

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_manual_cleanup_accepted_then_succeeds
- Assertion scope: 手动清理在 Node 终态前返回 `accepted=true`、`mount_cleanup_state="cleaning"`；此时数据库尚未完成清理；终态由后台任务落库。该用例未用事件阻塞证明“响应早于启动请求”，只证明受理语义。

#### Scenario: Node 任务运行中

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_running_keeps_polling_without_total_deadline
- Assertion scope: 状态返回 `running` 时数据库仍 `cleaned_at=null`/`mount_cleaned=false`，不写成功日志；fake Node 可访问并持续返回 `running` 多个周期后成功，Ctrl 不因累计时长转 unknown/释放键（不设固定总期限）。

#### Scenario: 瞬时通信失败重试

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_transient_failures_retry_and_running_resets_count
- Assertion scope: 状态查询连续出现 timeout/5xx/连接类失败但未达上限时，任务保持进行中、不写结果日志；随后收到 `running` 重置计数，再经一次瞬时失败后收到 `succeeded` 仍能成功落库；状态调用次数覆盖两次重试。

#### Scenario: 连续通信失败达到上限

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_consecutive_status_timeouts_reach_unknown
- Assertion scope: 连续 timeout 达到配置上限后任务为未知，写失败/未知结果日志；`cleaned_at=null`、`mount_cleaned=false`，无成功日志；状态请求次数等于上限，未继续无限重试。

#### Scenario: Node task_not_found 直接未知

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_node_task_not_found_is_unknown_not_success
  - [ ] test/container/test_mount_cleanup_async.py::test_node_status_404_not_found_is_node_task_lost
- Assertion scope: Node 明确返回 `task_not_found`，或实际返回 HTTP 404 + `error_reason=not_found` 时，任务为未知，失败日志原因为 `node_task_lost`；不标记已清理、不写成功日志，也不把任务丢失当成功。

#### Scenario: 旧 Node 状态端点直接未知

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_old_status_endpoint_is_unknown_not_success
- Assertion scope: 状态查询返回 404/405 且无 `task_not_found`/`error_reason=not_found` 任务缺失结构时，任务为未知，失败日志原因为 `node_unsupported`；不标记已清理、不写成功日志，不继续无限重试。

#### Scenario: Node 明确失败

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_node_failed_status_keeps_cleanup_unmarked
- Assertion scope: Node 状态为 `failed` 时写一条 `success=false` 结果日志、trigger 为 `disk_escalation`；数据库保持未清理、无成功日志；清理占位释放，列表显示 `failed`。该用例未覆盖手动/自动 trigger 的失败日志。

#### Scenario: 结果未知不伪造成功

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_consecutive_status_timeouts_reach_unknown
  - [ ] test/container/test_mount_cleanup_async.py::test_node_task_not_found_is_unknown_not_success
  - [ ] test/container/test_mount_cleanup_async.py::test_old_status_endpoint_is_unknown_not_success
- Assertion scope: 连续通信失败达到上限、`task_not_found`、旧端点缺失均进入未知并写失败/未知结果日志；`cleaned_at=null`、`mount_cleaned=false`；无成功日志；不把任何未知写成成功。该组测试分别覆盖对应原因，不宣称覆盖所有坏响应形状。

#### Scenario: 明确成功但落库失败

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_persist_failure_becomes_unknown
- Assertion scope: Node 返回 `succeeded` 后让 `mark_mount_cleaned` 抛错；事务回滚，`cleaned_at`/`mount_cleaned` 均未写，任务为未知，失败日志原因为 `cleanup_persist_failed`，无成功日志。

#### Scenario: 重复终态只留一条结果

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_terminal_transition_and_result_log_are_idempotent
- Assertion scope: 同一任务重复收到相同终态或并发回调时，只发生一次非终态到终态迁移，只写一条对应结果日志；重复响应不产生第二条成功/失败记录。

### Requirement: 清理登记、重复冲突与恢复互斥

#### Scenario: 同键并发清理只有一次受理

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_same_key_concurrent_requests_only_one_accepted
- Assertion scope: 两个线程同时以同一 `(machine_id, canonical_path)` 请求清理；恰好一个返回 200 `accepted=true`，另一个返回 409 `cleanup_in_progress`；Node `start_clean_mount` 只收到一次；登记表中只有一个活动任务。

#### Scenario: 不同机器或不同真实路径不冲突

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_distinct_machine_or_realpath_keys_are_independent
- Assertion scope: 相同路径不同机器、同一机器上 Node realpath 不同的路径均可分别受理；两个 Node 启动请求都发出；两个键各自持有，不互相返回冲突。

#### Scenario: 词法别名由 Node realpath 兜底

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_lexical_alias_is_rejected_by_node_realpath
- Assertion scope: 两个请求的 Ctrl 词法键不同但 Node realpath 相同；Ctrl 前置可放行，Node 共享登记拒绝第二个清理/恢复；Ctrl 不把词法键不同当安全凭据、不重试绕过，被拒操作失败且不写成功。

#### Scenario: 清理中拒绝恢复

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_restore_rejected_while_cleanup_active
- Assertion scope: 同键清理处于 `accepted`/`running` 时，恢复 API 返回 409 `cleanup_in_progress`；Node 路径探测与创建均未调用；快照与清理记录保留、`mount_cleaned` 不变、无成功审计、无凭据返回。

#### Scenario: 恢复中拒绝清理

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_cleanup_rejected_while_restore_active
- Assertion scope: 恢复占位存在时，新的手动清理返回 409 `restore_in_progress`；Node 启动未调用，无任务、无成功日志；恢复占位不受影响。

#### Scenario: 定时与升级清理在恢复中跳过

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_scheduled_and_escalation_cleanup_skip_during_restore
- Assertion scope: 恢复占位存在时，定时扫描与磁盘升级清理均不调用 `start_clean_mount` 或旧 `/clean_mount`、不写 `cleaned_at`/`mount_cleaned`、不写成功审计；释放恢复占位后下一轮可正常提交异步任务。

#### Scenario: 终态或未知后释放清理占位

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_terminal_cleanup_releases_key_for_restore_and_retry
- Assertion scope: 任务进入 `succeeded`/`failed`/未知后，同键恢复或新的清理不再被拒绝；终态摘要仍可被列表读取，但不构成活动清理占位。

### Requirement: 清理状态的有界性与 Ctrl 重启丢失

#### Scenario: 活动任务达到上限

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_active_task_capacity_rejects_new_cleanup
  - [ ] test/container/test_container_mount_cleanup_task.py::test_capacity_defers_scheduled_cleanup
  - [ ] test/container/test_container_disk_check_task.py::test_capacity_keeps_escalation_record
- Assertion scope: 填满活动任务上限后，新手动清理返回 503 `cleanup_capacity_exhausted`，不登记任务、不请求 Node；定时入口停止本轮并留待下一轮，升级入口保留 escalation 记录且不标 cleaned；已有任务不受影响。

#### Scenario: 终态摘要过期

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_terminal_summary_expiry_hides_state_without_db_change
- Assertion scope: 推进时钟超过终态 TTL 或触发淘汰后，列表不再返回该 `failed`/`unknown` 摘要；数据库清理记录与 `mount_cleaned` 不变。

#### Scenario: Ctrl 重启丢失轮询

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_registry_reset_loses_tasks_without_backfill
- Assertion scope: 清空进程内登记（模拟重启）后，不恢复轮询、不补写成功/失败日志、不补写 `cleaned_at`/`mount_cleaned`；列表 `mount_cleanup_state=null`，恢复重新开放。

#### Scenario: 重启后 Node 已成功也不回填

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_restart_after_node_success_does_not_mark_cleaned
- Assertion scope: 模拟 Node 已删除但 Ctrl 在提交前重启；重启后清理记录仍 `cleaned_at=null`/`mount_cleaned=false`，无成功日志，列表不伪造成功，恢复按钮开放。

#### Scenario: 重启后目录不存在正常展示

- Test/check:
  - [ ] test/container/test_mount_cleanup_list_state.py::test_restart_missing_directory_still_lists_record
- Assertion scope: 目录不存在且无进程内登记时，已删除列表仍返回记录与历史路径，`mount_cleanup_state=null`、`mount_cleaned=false`；接口不报 500、不调用 Node、不伪造已清理。

### Requirement: Node 异步清理协议与旧端点兼容

#### Scenario: 启动成功响应

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_start_success_requires_and_stores_non_empty_task_id
- Assertion scope: 启动请求体为 `{"config":{"mount_path":...}}`；严格接受 `success=1` 加非空 `task_id`，任务进入 `running`；启动成功本身不写 `cleaned_at`、不写成功日志。

#### Scenario: Node 重复启动冲突

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_node_start_conflict_marks_failed_without_cleaning
- Assertion scope: Node 对重复启动返回 409 或结构化 `cleanup_in_progress` 时，本次任务终态为失败，写失败日志；不标记已清理、不写成功日志；不会把冲突当成功。

#### Scenario: 状态响应严格匹配

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_status_response_shape_is_strict
- Assertion scope: 合法 `running`/`succeeded`/`failed` 三态被识别；`task_id` 不匹配、缺失、重复歧义、非法 state、`running`/`succeeded` 带错误原因、`failed` 缺错误原因均按坏响应进入未知；任何坏形状都不写成功。

#### Scenario: 旧 Node 缺新端点

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_start_404_marks_node_unsupported_without_legacy_fallback
- Assertion scope: 手动、定时、升级三种入口启动返回 404/405 时均失败/保留待处理，`node_unsupported`；旧 `/clean_mount` 未被调用，数据库未清理、无成功日志；不回退旧端点。

#### Scenario: Node 重启丢失任务

- Test/check:
  - [ ] test/container/test_mount_cleanup_async.py::test_status_task_not_found_becomes_unknown
- Assertion scope: 启动成功后状态查询返回 404/405 或任务不存在，Ctrl 记为未知并写未知/失败日志；`cleaned_at`/`mount_cleaned` 不变，无成功日志；清理占位释放，列表 `unknown`，恢复重新开放。

#### Scenario: Node 退出终止清理子进程

- Test/check:
  - [ ] test/container/test_cross_repo_protocol_replay.py::test_clean_mount_protocol_documents_node_exit_contract
- Assertion scope: 本仓库只回放协议文档与 Ctrl 侧分支：Node 重启后旧 `task_id` 不可查、Ctrl 按未知处理且不补记成功。真实“退出时终止清理子进程”属于 Node 仓库测试，本仓库不宣称已验证该进程行为。
- Coverage note: 跨仓外部契约；需要 Node 仓库的进程退出/子进程测试，本仓库只验证 Ctrl 在任务丢失后的未知处理。

#### Scenario: 缺失目录按旧幂等语义处理

- Test/check:
  - [ ] test/container/test_container_mount_cleanup_task.py::test_missing_directory_async_task_succeeds_idempotently
  - [ ] test/container/test_container_disk_check_task.py::TestEscalationMountCleanup::test_escalation_missing_directory_async_success
- Assertion scope: 定时/升级入口不运行手动前置检查；Node 异步任务对缺失目录按旧 `rm -rf` 幂等语义成功；Ctrl 只在 Node `succeeded` 后写 cleaned 与成功日志，不在 accepted 时落库；手动入口的 `not_found` 仍由前置检查在启动前拒绝。

#### Scenario: 路径规范化以 Node 为准

- Test/check:
  - [ ] test/container/test_mount_cleanup_registry.py::test_lexical_prefilter_and_node_realpath_authority
- Assertion scope: 尾随 `/`、重复 `/`、`.`/`..` 的词法归一化得到同一 Ctrl 前置键；不同机器相同路径不共键；Ctrl 词法键不同但 Node realpath 相同的别名由 Node 共享登记拒绝；Node 返回 `invalid_path`/symlink 拒绝时任务失败，Ctrl 不绕过 Node 继续删除或创建。
