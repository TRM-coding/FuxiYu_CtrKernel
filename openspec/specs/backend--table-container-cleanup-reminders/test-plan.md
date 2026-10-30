# backend--table-container-cleanup-reminders Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: container_cleanup_reminders 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_r01_cleanup_reminder_readback_and_unique
  - [X] test/repository/test_container_cleanup_reminder_repo.py::test_container_cleanup_reminder_repo_mark_and_check_sent
  - [X] test/repository/test_container_cleanup_reminder_repo.py::test_container_cleanup_reminder_repo_advances_level_in_place
- Assertion scope: `mark_sent` 首次 True、`was_sent` True，重复 mark False；同一收件人两档推进后仅一行且 `reminder_key=24h`。 无按主键新会话读取 id/container_id/reminder_key/cleanup_at/recipient_email/sent_at 类型与 default 的断言，也未直接触发既有 `(container_id, recipient_email)` 唯一键；R01 补齐后一约束，但不证明“每个 container_id 只有一条”（Q81 未覆盖/暂缓）。
- Coverage note: `advances_level_in_place` 只覆盖同一收件人原地推进；body 的“每个 container_id 只有一条”与唯一键 `(container_id, recipient_email)` 冲突，未覆盖/暂缓，见父 Global Q81。

### Requirement: container_cleanup_reminders 生产职责与生命周期

#### Scenario: 同档提醒判重

- Test/check:
  - [X] test/repository/test_container_cleanup_reminder_repo.py::test_container_cleanup_reminder_repo_mark_and_check_sent
  - [X] test/container/test_container_cleanup_reminders.py::test_send_cleanup_reminder_skips_when_already_sent
  - [X] test/repository/test_container_cleanup_reminder_repo.py::test_container_cleanup_reminder_repo_separates_level_and_email
  - [X] test/repository/test_container_cleanup_reminder_repo.py::test_container_cleanup_reminder_repo_advances_level_in_place
  - [X] test/e2e/test_ctrl_cleanup_reminder_flow.py::test_ctrl_e2e_cleanup_reminder_not_resent_while_machine_unavailable
  - [X] test/e2e/test_ctrl_cleanup_reminder_flow.py::test_ctrl_e2e_cleanup_reminder_rearms_after_real_login
  - [X] test/container/test_container_cleanup_reminders.py::test_send_cleanup_reminder_marks_sent_after_mail_success
  - [X] test/container/test_container_cleanup_reminders.py::test_send_cleanup_reminder_does_not_mark_sent_after_mail_failure
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_r02_reminder_audit_snapshot_fields
- Assertion scope: 同一 `reminder_key` 已发后不重复；不同档/不同收件人分开判；同一收件人档位推进只更新一行；清理时间顺延但同一周期只发一封；真实 SSH 登录时间变化把档位打回 NEVER 并重新提醒；邮件成功后 `was_sent=True`，失败后 False。 `cleanup_at`/`sent_at` 作为当次审计快照的具体值未断言；R02 补齐。
- Coverage note: body 的“每个 container_id 只有一条当前提醒记录”与模型/仓储 `(container_id, recipient_email)` 唯一键及不同收件人分开判重的既有测试冲突；`advances_level_in_place` 只证明同一收件人一行，不能证明该 clause。父 Global Q81 已登记，本轮标为未覆盖/暂缓，不改 app、主规格或业务实现；其余提醒档位映射继续。
