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
- Assertion scope: 定时清理超 14 天记录：向 `/clean_mount` 发送一次，cleanup.`cleaned_at` 非空；手动入口同样发送并置 `cleaned_at`；已 cleaned 但 snapshot.`mount_cleaned=false` 时只同步快照为 true 且不发 Node；磁盘升级清理写 `escalation=True`、`cleaned_at` 非空并调 Node；维护中手动入口仍可执行。 M02 补“Node 成功清理后在同一事务内同时写 cleanup.`cleaned_at` 与关联 snapshot.`mount_cleaned`”：成功路径断言双写，并在 snapshot 标记注入异常，断言事务回滚后两行均未写 cleaned_at/mount_cleaned、无成功日志。
- Coverage note: 手动、定时、磁盘升级三条入口均有行为断言，但未直接证明共享同一服务门户；M02 以关联 snapshot 同步与事务回滚作为共同落点，不把只写 `cleaned_at` 当成事务原子性证明。
