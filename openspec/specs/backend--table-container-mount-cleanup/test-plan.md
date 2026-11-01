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
  - [X] test/container/test_container_mount_cleanup_task.py::TestMountCleanupTask::test_cleans_old_pending_mount
  - [X] test/container/test_deleted_containers.py::test_clean_deleted_container_mount_calls_node_and_marks_cleaned
  - [X] test/container/test_deleted_containers.py::test_clean_mount_path_persists_deleted_state_when_cleanup_is_already_cleaned
  - [X] test/container/test_container_disk_check_task.py::TestEscalationMountCleanup::test_clean_mount_immediately_inserts_record
  - [X] test/container/test_container_disk_check_task.py::TestEscalationMountCleanup::test_clean_mount_immediately_sends_to_node
  - [X] test/container/test_container_mount_cleanup_task.py::TestMountCleanupTask::test_manual_cleanup_still_runs_in_maintenance
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_m02_clean_success_syncs_snapshot_in_transaction
- Assertion scope: 定时清理超 14 天记录：向 `/clean_mount` 发送一次，cleanup.`cleaned_at` 非空；手动入口先经 `check_mount_usage`、再发送 `/clean_mount` 并置 `cleaned_at`；已 cleaned 但 snapshot.`mount_cleaned=false` 时只同步快照为 true 且不发 Node；磁盘升级清理写 `escalation=True`、`cleaned_at` 非空并调 Node；维护中手动入口仍可执行。 M02 补“Node 成功清理后在同一事务内同时写 cleanup.`cleaned_at` 与关联 snapshot.`mount_cleaned`”：成功路径断言双写，并在 snapshot 标记注入异常，断言事务回滚后两行均未写 cleaned_at/mount_cleaned、无成功日志。
- Coverage note: 手动、定时、磁盘升级三条入口均有行为断言，但未直接证明共享同一服务门户；M02 以关联 snapshot 同步与事务回滚作为共同落点，不把只写 `cleaned_at` 当成事务原子性证明。

#### Scenario: 手动清理前新鲜检查通过

- Test/check:
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_pending_means_present_then_cleans
- Assertion scope: Node 单路径 pending（已过存在性门禁）时，手动清理依次调用 `/check_mount_usage` 与 `/clean_mount`；成功后 cleanup.`cleaned_at` 非空、snapshot.`mount_cleaned=true`。

#### Scenario: 原容器已恢复为有效时拒绝手动清理

- Test/check:
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_refuses_live_mount_of_restored_valid_container
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_refuses_live_legacy_record_before_adoption
- Assertion scope: 原容器行 `is_valid=true` -> `container_exists`，不触达 Node；cleanup.`cleaned_at` 为空、snapshot.`mount_cleaned=false`；legacy cleanup-only 记录拒绝先于收养/补建快照。

#### Scenario: not_found 拒绝手动清理并保留记录

- Test/check:
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_missing_path_is_rejected_and_not_marked_cleaned
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_api_missing_path_is_404_not_found
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_legacy_cleanup_only_record_is_guarded
- Assertion scope: per-path `not_found` -> reason `not_found`，API 404；不调用 `/clean_mount`；cleanup.`cleaned_at` 保持空、snapshot.`mount_cleaned=false`；失败 op-log 的 trigger 为 `manual_clean_mount`。

#### Scenario: 权限、非法路径与网络错误不误称 not_found

- Test/check:
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_unverified_paths_keep_a_distinct_reason
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_transport_timeout_keeps_timeout_reason
  - [X] test/container/test_mount_path_action_guard.py::test_manual_cleanup_offline_machine_never_calls_node_or_marks_cleaned
- Assertion scope: permission_denied/invalid_path/旧 Node 404/5xx/坏形状分别映射 `permission_denied`/`invalid_path`/`node_unsupported`/`node_unavailable`/`node_bad_response`；超时映射 `node_timeout`；均不调用 `/clean_mount`，cleanup.`cleaned_at` 为空、`mount_cleaned=false`，不误报 `not_found`。

#### Scenario: 自动与升级清理维持既有语义

- Test/check:
  - [X] test/container/test_container_mount_cleanup_task.py::TestMountCleanupTask::test_cleans_old_pending_mount
  - [X] test/container/test_container_disk_check_task.py::TestEscalationMountCleanup::test_clean_mount_immediately_sends_to_node
- Assertion scope: 定时清理与磁盘升级即时清理按既有生命周期直接调用 `/clean_mount`，不先发 `check_mount_usage`；成功路径仍写 `cleaned_at`/同步 `mount_cleaned`。
- Coverage note: 现有用例未断言“绝不发 check_mount_usage”的调用序列；以入口默认 `verify_mount_path=False` 和 Node 调用记录作为间接覆盖。
