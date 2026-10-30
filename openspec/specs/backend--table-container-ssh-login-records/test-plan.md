# backend--table-container-ssh-login-records Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: container_ssh_login_records 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_container_ssh_login_repo.py::test_container_ssh_login_repo_upsert_insert_and_update
  - [X] test/repository/test_container_ssh_login_repo.py::test_container_ssh_login_repo_get_missing_returns_none
  - [X] test/repository/test_container_ssh_login_repo.py::test_container_ssh_login_repo_list_all_filters_invalid_containers
- Assertion scope: 按 machine_id/container_id 插入后 `last_ssh_login_time` 与 `updated_at` 可读；再次 upsert 更新登录时间；缺失记录返回 None；软删容器默认从 list 排除，`include_invalid=True` 可读回。

### Requirement: container_ssh_login_records 生产职责与生命周期

#### Scenario: 机器不可用补偿

- Test/check:
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_offline_window_adds_deferral_on_recovery
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_deferral_applies_to_all_records_of_machine
  - [X] test/machine/test_cleanup_deferral_window.py::TestDeferralLifecycle::test_add_deferral_accumulates
  - [X] test/machine/test_cleanup_deferral_window.py::TestCleanupInfoDeferral::test_deferral_shifts_cleanup_and_rescues_due
  - [X] test/machine/test_cleanup_deferral_window.py::TestDeferralLifecycle::test_same_value_frame_keeps_deferral
  - [X] test/machine/test_cleanup_deferral_window.py::TestDeferralLifecycle::test_value_change_clears_deferral
  - [X] test/repository/test_container_cleanup_reminder_repo.py::test_container_cleanup_reminder_repo_reset_to_never_only_touches_that_container
  - [X] test/repository/test_container_ssh_login_repo.py::test_container_ssh_login_repo_list_all_filters_invalid_containers
  - [X] test/repository/test_anvil_identity_settings.py::test_machine_unavailable_deferral_keeps_last_ssh_anchor
  - [X] test/repository/test_anvil_identity_settings.py::test_new_ssh_login_resets_deferral_and_cleanup_reminder
- Assertion scope: 机器离线窗口结束把整段时长累加到该机器全部记录的 deferral_seconds，清理倒计时按 deferral 顺延；同值心跳保留 deferral，真登录值变化清零；提醒仓储可把目标容器复位为 NEVER 且不碰其他容器；软删容器被排除；`[ ]` 行断言窗口补偿后 `last_ssh_login_time` 不变，以及 upsert 新登录值时同一事务同时清零 deferral 并复位提醒。
- Coverage note: 已列 `[X]` locator 覆盖补偿、倒计时、同值/变化与提醒仓储；“窗口后锚点不变”和“upsert 联动复位提醒”两个正文约束由 `[ ]` 行补齐。
