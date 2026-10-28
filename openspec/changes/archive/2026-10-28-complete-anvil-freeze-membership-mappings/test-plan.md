# Test Plan

本计划是 63 个 Scenario 到测试/检查的映射，不是运行台账：`[X]` 表示该 locator 存在，且其断言已从测试代码逐段核对；`[ ]` 表示测试、映射或断言尚未确认，本计划当前已无 `[ ]` 行。两者都不代表执行结果、通过/失败或自动等于场景全覆盖。计划测试统一位于 `test/container/test_anvil_freeze_membership.py`，该文件已创建。

## backend--table-long-term-containers

### Requirement: long_term_containers 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt01_long_term_readback_contract
- Assertion scope: 计划项持久化一行带 `created_by_user_id`、一行不带，换新 session 按 `container_id` 读取；断言 `container_id` 为 `int` 且等于容器主键，`created_by_user_id` 分别为创建者整数主键与 `NULL`（不是用户名/展示名），`created_at` 为插入窗口内的 `datetime`，同一 `container_id` 只有一行。
- Coverage note: 既有 `test_long_term_transitions.py::test_repeated_switch_requests_keep_one_marker_and_one_success_audit` 只断言主键列名为 `container_id` 及重复 add 后计数 1，没有按主键重开或检查类型/空值，不能支撑本 Scenario。

### Requirement: long_term_containers 生产职责与生命周期

#### Scenario: 重复标记

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_repeated_switch_requests_keep_one_marker_and_one_success_audit
  - [X] test/container/test_container_tasks_long_term.py::test_set_long_term_success_for_root_owner
  - [X] test/container/test_container_tasks_long_term.py::test_unset_long_term_removes_record
  - [X] test/container/test_container_cleanup_task.py::test_cleanup_expired_containers_skips_long_term
  - [X] test/container/test_container_cleanup_task.py::test_cleanup_expired_containers_removes_due_container_after_snapshot
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt07_marker_removal_restores_short_term_cleanup
- Assertion scope: 连续两次启用后 `long_term_container_repo.is_long_term` 为真、该容器长期记录计数为 1、主键列仅 `container_id`、成功审计仅 1 条；第二次 `add` 返回 `True` 但不插入第二行；取消长期后标记行被移除；带标记的到期容器被清理任务跳过，无标记的到期容器仍被清理。计划项在同一容器上先移除长期标记再运行到期清理，断言清理恢复删除该容器。
- Coverage note: 既有清理/取消用例分别覆盖“带标记跳过”“无标记到期删除”“移除标记行”，没有在同一容器上连续断言“移除标记后清理策略恢复”。

### Requirement: 恢复长期标记遵守数量限额

#### Scenario: 长期限额已满

- Test/check:
  - [X] test/container/test_restore_long_term_capacity.py::test_preflight_rejects_owner_at_limit_with_counts
  - [X] test/container/test_restore_long_term_capacity.py::test_restore_rejects_at_capacity_before_any_restore_work
  - [X] test/container/test_restore_long_term_capacity.py::test_resurrect_api_maps_capacity_to_409_and_keeps_snapshot
- Assertion scope: 配额预检抛出 `long_term_limit_reached`，异常文本含 `(1/1)`；恢复入口在超限时不发送 `/create_container`，容器仍软删，删除快照与挂载清理记录均未消费，失败日志原因为 `long_term_limit_reached`；HTTP 入口返回 409、`error_reason=long_term_limit_reached`、`message` 含 `(1/1)`，快照仍在且容器仍为软删，不产生第 2 个长期容器。

#### Scenario: 幂等与普通快照

- Test/check:
  - [X] test/container/test_restore_long_term_capacity.py::test_restore_keeps_existing_marker_idempotent
  - [X] test/container/test_restore_long_term_capacity.py::test_restore_of_short_term_snapshot_ignores_capacity
- Assertion scope: 恢复已带长期标记的快照后，按 `container_id` 查只有 1 行、用户长期计数为 1；普通快照在配额已满时仍成功恢复，恢复后该容器不是长期容器，不因长期配额被拒绝。

### Requirement: 长期切换由服务端静态守卫裁决

#### Scenario: 不同客户端入口不能绕过

- Test/check:
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt02_extra_client_fields_do_not_change_guard
- Assertion scope: 计划项对同一 `set_long_term_container` 端点分别发送只含 `container_id`/`is_long_term` 的请求与附加 `page`、`source`、`can_enable`、`force` 等客户端字段的请求；在配额满、磁盘硬超限、冻结中取消三种场景下，两种请求得到相同的状态码与 `error_reason`，长期标记/冻结字段/审计不因附加字段改变；额外字段被请求模型忽略。
- Coverage note: 既有测试没有发送额外客户端字段；三个页面入口在 Ctrl 共用同一端点，后端 `SetLongTermContainerRequest` 使用 `extra="ignore"`。本计划不把 Web 页面按钮状态当作后端授权证据。

#### Scenario: 既有权限与状态矩阵保留

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_status_matrix_remains_authoritative[True-ContainerStatus.FAILED-container_failed]
  - [X] test/container/test_long_term_transitions.py::test_status_matrix_remains_authoritative[False-ContainerStatus.CREATING-container_busy]
  - [X] test/container/test_long_term_transitions.py::test_host_and_unknown_conditions_still_rejected
  - [X] test/container/test_long_term_transitions.py::test_api_keeps_host_unavailable_503
  - [X] test/container/test_rbac_container_role.py::test_container_role_resource_points
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt03_permission_and_not_found_contract
- Assertion scope: 启用 `failed` 容器抛 `container_failed`，取消 `creating` 容器抛 `container_busy`；主机离线、维护中、状态未知分别抛 `container_host_offline`、`container_host_maintenance`、`container_status_unknown`；RBAC 资源点断言 ROOT 满足 `container:root`、ADMIN/COLLABORATOR 不满足、无绑定者不满足。计划项补 HTTP 层：缺 `container:operation` 实体权限返回 403 `insufficient_permission`，缺 `container:root` 资源返回 403 `resource_access_denied`，缺机器访问权返回 403 `machine_access_denied`，容器不存在返回 404 `container_not_found`，均无标记/冻结/审计副作用。
- Coverage note: 既有测试覆盖状态矩阵与 RBAC 纯函数，但没有 `set_long_term_container` 的 API 级 403/404 断言。

#### Scenario: 守卫不依赖新增结构

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_repeated_switch_requests_keep_one_marker_and_one_success_audit
  - [X] test/container/test_container_tasks_long_term.py::test_set_long_term_success_for_root_owner
- Assertion scope: 成功切换只写入既有 `long_term_containers` 主键 `container_id` 行；服务路径在没有安装 Node 替身的情况下完成，证明该守卫不依赖 Node 前置请求/字段。
- Coverage note: “不新增列、库表变更、资格对象或 Node 前置字段”是设计/评审约束，不是单个运行断言能穷尽证明的；既有测试只证明所用字段与主键是既有的，本计划不新增 ORM 反射列清单或源码字符串断言来冒充该约束。

### Requirement: 启用长期检查 root 用户配额

#### Scenario: 配额已满时拒绝启用

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_enable_rejected_when_root_quota_full
  - [X] test/container/test_long_term_transitions.py::test_api_maps_quota_to_409
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt04_guard_rejections_keep_freeze_and_audit
- Assertion scope: 服务层抛 `long_term_limit_reached`，文本含 `(1/1)`，容器长期标记为假且长期计数为 0；HTTP 层返回 409 与同一 reason，标记仍为假。计划项在目标容器预先存在冻结行时重放配额拒绝，断言 `first_frozen_at`/`grace_until`/`deferral_seconds` 三元组不变，并写一条 `SET_LONG_TERM` 失败审计（reason 同一稳定值）。
- Coverage note: 既有两个用例没有预置目标冻结行，因此“不修改冻结字段”和配额拒绝的失败审计仍缺断言。

#### Scenario: 配额未满时继续检查磁盘

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_enable_disk_hard_limit_is_static_and_unknown_is_not_zero[549755813888-True]
  - [X] test/container/test_long_term_transitions.py::test_soft_threshold_and_unconfigured_limit_do_not_block_enable
- Assertion scope: 配额未满（默认上限下只有一个长期容器或无其他长期容器）时，磁盘 512 GiB 达到硬限制被拒，证明服务继续进入磁盘判断而不是只凭配额通过；约 85% 用量（高于软阈值、低于硬限制）与未配置机器上限两种情况下启用成功。

### Requirement: 启用长期检查磁盘硬限制

#### Scenario: 已知用量达到硬限制时拒绝

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_enable_disk_hard_limit_is_static_and_unknown_is_not_zero[549755813888-True]
  - [X] test/container/test_long_term_transitions.py::test_enable_disk_hard_limit_is_static_and_unknown_is_not_zero[550829555712-True]
  - [X] test/container/test_long_term_transitions.py::test_enable_disk_hard_limit_is_static_and_unknown_is_not_zero[548682072064-False]
  - [X] test/container/test_long_term_transitions.py::test_api_maps_disk_hard_limit_to_409_and_logs_failure
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt04_guard_rejections_keep_freeze_and_audit
- Assertion scope: 512 GiB（正好等于 512 GiB 上限的 100%）与 513 GiB 均抛 `disk_usage_over_limit` 且不新增长期标记；511 GiB 启用成功。HTTP 层返回 409、写入 `disk_usage_over_limit` 失败审计、无成功审计、标记仍为假。计划项补目标已有冻结行时拒绝前后三元组不变。
- Coverage note: 既有用例的目标容器没有冻结行，冻结字段不变仍缺断言。

#### Scenario: 用量未知或未配置上限时不误拒

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_enable_disk_hard_limit_is_static_and_unknown_is_not_zero[None-False]
  - [X] test/container/test_long_term_transitions.py::test_soft_threshold_and_unconfigured_limit_do_not_block_enable
- Assertion scope: `disk_total_bytes=None` 时启用成功；机器 `max_disk_size_gb=0` 且用量 999 GiB 时仍启用成功，不把未知/未配置当 0 或超限。

#### Scenario: 仅超过软阈值仍可启用

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_soft_threshold_and_unconfigured_limit_do_not_block_enable
- Assertion scope: 机器上限 512 GiB、用量约 85%（高于 80% 软阈值、低于 100% 硬限制）时启用成功，长期标记落库；软提醒不阻断。

### Requirement: 取消长期按实际状态拦截冻结

#### Scenario: 冻结中取消被拒绝

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_cancel_rejected_while_paused_and_freeze_fields_unchanged
  - [X] test/container/test_long_term_transitions.py::test_api_maps_frozen_cancel_to_409
- Assertion scope: `paused` 容器取消长期抛 `container_paused`；长期标记仍为真，`first_frozen_at`/`grace_until`/`deferral_seconds` 三元组在调用前后完全相等；HTTP 层返回 409 与同一 reason，标记保留。

#### Scenario: 已确认恢复后允许取消

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_cancel_allowed_after_resume_even_with_legacy_freeze_row[ContainerStatus.ONLINE]
  - [X] test/container/test_long_term_transitions.py::test_cancel_allowed_after_resume_even_with_legacy_freeze_row[ContainerStatus.OFFLINE]
- Assertion scope: 旧冻结行仍存在但实际状态为 `online`/`offline` 时取消成功，返回 `is_long_term=False` 且长期记录被移除；冻结三元组保持不变，证明冻结行存在不永久阻断取消，也未删除/重置该行。

#### Scenario: 取消长期不等于删除容器

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_cancel_allowed_after_resume_even_with_legacy_freeze_row[ContainerStatus.ONLINE]
  - [X] test/container/test_long_term_transitions.py::test_generic_soft_delete_clears_only_target_freeze_row
- Assertion scope: 仅取消长期后冻结行与 Q72 三元组原样保留；只有真正软删除目标容器时冻结行才被删除，且同一机器下另一容器的冻结三元组不变。

#### Scenario: 状态矩阵优先于方向规则

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_status_matrix_remains_authoritative[True-ContainerStatus.FAILED-container_failed]
  - [X] test/container/test_long_term_transitions.py::test_status_matrix_remains_authoritative[False-ContainerStatus.CREATING-container_busy]
  - [X] test/container/test_long_term_transitions.py::test_host_and_unknown_conditions_still_rejected
- Assertion scope: `failed` 启用、`creating` 取消仍分别被既有状态矩阵以 `container_failed`/`container_busy` 拒绝；主机离线/维护/状态未知仍抛对应原因，方向规则不绕过矩阵。

### Requirement: 同目标值请求无额外副作用

#### Scenario: 重复启用不产生新标记

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_same_target_repeated_enable_has_no_side_effects
  - [X] test/container/test_long_term_transitions.py::test_api_noop_returns_200_without_new_audit
- Assertion scope: 已是长期的容器再次提交 `true` 后仍只有 1 条长期记录，无新增成功审计，冻结三元组不变；API 返回 200 与 `is_long_term=true`，同样不新增审计。

#### Scenario: 重复取消不产生删除

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_same_target_repeated_cancel_has_no_side_effects
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt08_repeated_cancel_keeps_container_valid
- Assertion scope: 既有用例断言已非长期的容器再次提交 `false` 后长期计数仍为 0、无新增成功审计、冻结三元组不变。计划项在重复取消后按 `include_invalid=True` 重读容器行，断言 `is_valid=True`、`deleted_at` 与调用前一致（未被删除）、无 `DELETE_CONTAINER` 删除审计，并复核长期计数/成功审计/冻结三元组不变。
- Coverage note: 既有用例没有读取容器行、`is_valid` 或 `deleted_at`，因此“不执行删除”的容器有效性仍缺断言，由计划项补齐。

#### Scenario: 切换失败保留原标记

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_api_maps_disk_hard_limit_to_409_and_logs_failure
  - [X] test/container/test_long_term_transitions.py::test_cancel_rejected_while_paused_and_freeze_fields_unchanged
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt04_guard_rejections_keep_freeze_and_audit
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt05_cancel_rejection_keeps_freeze_and_writes_failure
- Assertion scope: 磁盘拒绝时标记仍为假、写 `disk_usage_over_limit` 失败审计；冻结中取消被拒时标记仍为真、冻结三元组不变。计划项补配额拒绝的失败审计与冻结不动，以及取消拒绝的 API 级失败审计/冻结不动。
- Coverage note: 既有用例未同时断言“失败审计 + 原标记 + 冻结字段”三件事；配额拒绝的失败审计和取消拒绝的失败审计仍缺。

### Requirement: 实际写入前重读既有事实

#### Scenario: 重读后发现目标已变化

- Test/check:
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt06_reread_changed_facts_rejudged
- Assertion scope: 计划项在既有命名 seam `services.container_tasks._read_long_term_target` 上确定性地返回“模拟另一请求已把目标改成当前请求目标值”的事实（启用方向 `existing=True`，取消方向 `existing=False`），再走真实 `set_long_term_container` 守卫/落库路径；断言同目标状态不新增第二条长期记录、不写成功审计、冻结三元组不变。
- Coverage note: 该用例是确定性模拟：`_read_long_term_target` 被替换为给定事实，不执行第二次真实读取；fake SQLite `:memory:` + `StaticPool` 下不同 `Session` 共享同一 DBAPI 连接，不是独立事务，也不证明真实并发/提交交错。当前实现只在事务开头读取一次、成功审计由初始 `existing` 决定；真实同容器重读/审计窗口与 Q67 的长期并发范围相邻，按父级要求优先关联 Q67/Global，不在本变更修 app 或弱化规格。

#### Scenario: 重读后发现状态已冻结

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_single_session_reread_rejudges_changed_status
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt06_reread_changed_facts_rejudged
- Assertion scope: 既有测试在 `_read_long_term_target` seam 返回 `paused` 容器，断言取消长期抛 `container_paused`，即判断使用该读取结果；计划项在同一 seam 返回模拟 `paused` 事实，覆盖“重读事实为冻结时拒绝”的守卫分支。
- Coverage note: 既有与计划项都是确定性模拟，不证明真实并发重读；fake SQLite 的 Session 共享同一连接，与该限制同源。

### Requirement: 错误原因与既有契约稳定

#### Scenario: 策略阻断返回 409

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_api_maps_disk_hard_limit_to_409_and_logs_failure
  - [X] test/container/test_long_term_transitions.py::test_api_maps_quota_to_409
  - [X] test/container/test_long_term_transitions.py::test_api_maps_frozen_cancel_to_409
  - [X] test/container/test_container_api_long_term.py::test_set_long_term_api_validates_required_fields
- Assertion scope: 磁盘硬超限、root 配额满、冻结中取消分别返回 409，`error_reason` 为 `disk_usage_over_limit`、`long_term_limit_reached`、`container_paused`；对应长期标记保持拒绝前状态；缺少 `is_long_term` 的入参仍返回 400，既有入参契约不变。

#### Scenario: 主机不可用沿用 503

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_api_keeps_host_unavailable_503
- Assertion scope: 机器离线时 API 返回 503 与 `container_host_offline`，不伪装成磁盘或配额超限。

#### Scenario: 失败审计不改变状态

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_api_maps_disk_hard_limit_to_409_and_logs_failure
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt04_guard_rejections_keep_freeze_and_audit
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_lt05_cancel_rejection_keeps_freeze_and_writes_failure
- Assertion scope: 磁盘拒绝写失败审计且无成功审计，长期标记仍为假。计划项补配额/取消拒绝的失败审计与冻结三元组不变。
- Coverage note: 既有磁盘失败用例没有冻结行，不能证明冻结字段不变；取消拒绝的失败审计仍缺。

## backend--table-container-disk-freeze-state

### Requirement: container_disk_freeze_state 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/container/test_container_disk_check_task.py::TestFreezeStateRepo::test_get_returns_record_when_exists
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_dfs01_freeze_readback_contract
- Assertion scope: 既有用例断言按 `container_id` 读到的记录非空、`container_id` 相同、`first_frozen_at` 非空。计划项用新 session 按主键重开最小行与完整行，断言 `container_id` 为 `int`、`first_frozen_at`/`created_at` 为插入窗口内 `datetime`、`deferral_seconds` 默认/显式值为 `int`（含 0/`NULL` 语义）、`grace_until` 未设置为 `NULL`、设置后为 `datetime`，并确认同一主键只有一行。
- Coverage note: 既有断言只覆盖 `container_id` 与 `first_frozen_at` 存在性，未覆盖类型、`grace_until` 空值、`deferral_seconds` 默认值或 `created_at`。

### Requirement: container_disk_freeze_state 生产职责与生命周期

#### Scenario: 容量恢复

- Test/check:
  - [X] test/container/test_container_disk_check_task.py::TestFreezeReset::test_freeze_state_reset_on_usage_below_reset
  - [X] test/container/test_container_disk_check_task.py::TestFreezeReset::test_grace_cleared_on_usage_below_reset
  - [X] test/container/test_container_disk_check_task.py::TestFreezeStateMachineTimeline::test_reset_after_reclaim_restarts_anchor
- Assertion scope: 用量回落到重置阈值以下后冻结记录被删除，soft/hard handler 均未触发；宽限期随整行删除；再次超限时创建新记录，`first_frozen_at` 等于新时钟点且不同于旧锚点，整行删除使旧周期（含补偿）不再存在。
- Coverage note: 既有重置/新锚点用例没有先设置非零 `deferral_seconds` 再重置；“旧周期补偿不延续”由整行删除推得，不是该用例单独断言。计划项 `dfs02` 在恢复后的新冻结中断言 `deferral_seconds=0`，但不回填本场景“非零补偿被重置”的断言。

### Requirement: 有效冻结天数在查询和调度中一致

#### Scenario: 扣除累计补偿

- Test/check:
  - [X] test/container/test_freeze_days_consistency.py::TestEffectiveDaysFrozenPure::test_deferral_is_subtracted_in_whole_days
  - [X] test/container/test_freeze_days_consistency.py::TestQueryAndSchedulerShareOneFormula::test_twenty_days_frozen_with_ten_days_deferral_reads_ten_in_both
  - [X] test/container/test_freeze_days_consistency.py::TestQueryAndSchedulerShareOneFormula::test_detail_and_list_display_use_the_effective_value
  - [X] test/container/test_freeze_days_consistency.py::TestMaintenanceWindowIsConsistent::test_open_window_defers_action_and_both_sides_read_the_same_value
  - [X] test/container/test_freeze_days_consistency.py::TestMaintenanceWindowIsConsistent::test_only_settled_window_credit_changes_both_sides
- Assertion scope: 20 天冻结、10 天补偿时，查询 `_get_container_freeze_state` 与调度 `_days_frozen` 都返回 10；详情 `freeze_state.days_frozen` 与列表项 `freeze_days_frozen` 同样为 10；机器不可用窗口未关闭时调度不动作、两侧读同一个未顺延值，窗口关闭把整段时长计入 `deferral_seconds` 后两侧一起变小并据此升级；不把累计自然天数当作有效天数。

#### Scenario: 不满一天或补偿超过经过时间

- Test/check:
  - [X] test/container/test_freeze_days_consistency.py::TestEffectiveDaysFrozenPure::test_partial_day_is_floored
  - [X] test/container/test_freeze_days_consistency.py::TestEffectiveDaysFrozenPure::test_over_credited_deferral_clamps_to_zero
  - [X] test/container/test_freeze_days_consistency.py::TestQueryAndSchedulerShareOneFormula::test_partial_and_negative_agree_between_query_and_scheduler
- Assertion scope: 5 天 23 小时按 5 天；补偿超过经过时间时夹为 0；查询与调度对 5.5 天减 1 天得 4、1 天减 30 天得 0 的结果一致，不返回负数。

#### Scenario: 尚未冻结

- Test/check:
  - [X] test/container/test_freeze_days_consistency.py::TestQueryAndSchedulerShareOneFormula::test_unfrozen_container_has_no_freeze_state_and_no_days
- Assertion scope: 无冻结记录时查询返回 `None`，详情 `freeze_state` 为 `None`，列表项 `freeze_days_frozen` 为 `None`；不凭空生成 0 天或伪造冻结对象。

### Requirement: 删除容器重置冻结状态

#### Scenario: 成功删除清空冻结状态

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_generic_soft_delete_clears_only_target_freeze_row
  - [X] test/container/test_long_term_transitions.py::test_api_and_cleanup_removal_clear_freeze_row[1]
  - [X] test/container/test_long_term_transitions.py::test_api_and_cleanup_removal_clear_freeze_row[None]
- Assertion scope: 带 `first_frozen_at`/`grace_until`/`deferral_seconds` 的容器成功软删后，容器行 `is_valid=False`、`deleted_trigger` 为 `api` 或 `cleanup`，该 `container_id` 的冻结行不存在；删除走实际 `remove_container` 入口而非只删行。

#### Scenario: 无冻结记录正常完成

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_generic_soft_delete_without_freeze_row_is_normal
- Assertion scope: 无冻结记录的容器软删返回 `True`、容器行不可见且冻结行仍为 `None`；不因无行可删报错或回滚。

#### Scenario: 删除失败或事务回滚保留冻结状态

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_delete_rollback_keeps_container_and_freeze_row
- Assertion scope: 在 `session_scope` 内软删后抛出 `RuntimeError` 触发回滚，重读容器 `is_valid=True`、冻结三元组与删除前完全一致；不出现半软删/半清空。

#### Scenario: 重复删除幂等

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_repeated_soft_delete_is_idempotent
- Assertion scope: 同一容器第二次软删仍返回 `True`，`deleted_at` 保持第一次的值，冻结行保持不存在；不因容器已失效或冻结行已删而失败。

#### Scenario: 不影响其他容器

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_generic_soft_delete_clears_only_target_freeze_row
- Assertion scope: 删除目标容器后只清除该 `container_id` 的冻结行；同机器下另一容器的 `first_frozen_at`/`grace_until`/`deferral_seconds` 三元组保持不变。

### Requirement: 恢复新建不继承冻结周期

#### Scenario: 恢复不继承旧冻结状态

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_delete_then_restore_long_term_does_not_inherit_freeze_or_grace
- Assertion scope: 带冻结记录与宽限的长期容器软删后从快照恢复，恢复结果复用原容器 id、长期标记仍为真且计数 1；恢复后冻结记录数为 0，既无继承的 `first_frozen_at`/`grace_until`/`deferral_seconds`，也没有因恢复新建冻结行。

#### Scenario: Q72 累计不被恢复续期

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_delete_then_restore_long_term_does_not_inherit_freeze_or_grace
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_dfs02_restore_then_new_freeze_starts_new_cycle
- Assertion scope: 既有用例证明删除终止旧周期、恢复后无冻结记录；计划项在恢复后让调度真实触发一次硬超限冻结，断言新 `first_frozen_at` 晚于旧锚点、`deferral_seconds=0`、`grace_until=None`，只有实际冻结才建立新周期，不继承旧累计。
- Coverage note: 既有用例只断言恢复时无记录，没有触发恢复后的新冻结，因此“之后实际发生冻结才建立新锚点与累计”仍缺断言。

#### Scenario: 同一未删除容器累计不变

- Test/check:
  - [X] test/container/test_long_term_transitions.py::test_cancel_rejected_while_paused_and_freeze_fields_unchanged
  - [X] test/container/test_long_term_transitions.py::test_cancel_allowed_after_resume_even_with_legacy_freeze_row[ContainerStatus.ONLINE]
  - [X] test/container/test_long_term_transitions.py::test_same_target_repeated_enable_has_no_side_effects
  - [X] test/container/test_long_term_transitions.py::test_same_target_repeated_cancel_has_no_side_effects
- Assertion scope: 未删除容器在取消被拒、取消成功、重复启用、重复取消后，冻结三元组均与操作前相等；长期设置/取消不提前重置 Q72 累计。

## backend--table-user-container

### Requirement: user_container 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc01_user_container_readback_contract
- Assertion scope: 计划项持久化一条完整绑定（带 `public_key`）与一条最小绑定（`public_key=NULL`），换新 session 按 `(user_id, container_id)` 复合主键读取；断言 `user_id`/`container_id` 为 `int` 且等于真实主键，`role` 为 `ROLE` 枚举，`granted_at` 为插入窗口内 `datetime`，`public_key` 按 `str`/`NULL` 往返，`username` 为 `str` 原样往返，同一复合键只有一行，不用用户名/展示名替代稳定主键。
- Coverage note: 既有 `test_role_change_semantics_contract` 等只读同一 session 的绑定 role/username；主 sidecar 把本场景标为“待复核”，没有完整的跨 session 类型/空值断言。

### Requirement: user_container 生产职责与生命周期

#### Scenario: 协作角色变更

- Test/check:
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc02_update_role_persists_binding
- Assertion scope: 计划项对已绑定的普通用户调用真实 `update_role`，Node 替身记录一次 `update_role` wire；断言该复合主键绑定的 `role` 被更新为目标非 ROOT 角色、`username` 保持其系统用户名、旧/新角色写入成功审计，Node 请求不含密码字段。
- Coverage note: 既有 `test_role_change_semantics_contract` 调用了 `update_role`，但只断言 Node config 无密码；没有读回绑定 role。`test_container_api_collaborators.py::test_update_role_api_success` 把 service 整个替换，不能作为落库证据。

#### Scenario: 普通非 ROOT 角色互换不改密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_role_change_semantics_contract
  - [X] test/container/test_password_contracts.py::test_update_role_legacy_transfer_root_does_not_affect_non_root
- Assertion scope: `update_role` 把 COLLABORATOR 切到 ADMIN 时，Node `config` 不含 `password` 与 `root_password`；`transfer_root=true` 的非 ROOT 请求仍只把 `updated_role`/`operator_user_id` 等原参数传给 service，兼容字段不改变路由；不生成或重置 root/目标账号密码。绑定 role 的落库部分不在本行断言范围内，由 `[X] test_anvil_uc02_update_role_persists_binding` 覆盖。
- Coverage note: 测试断言的是 Node wire 不含密码字段，没有比较密码值；在该 wire 合同下已足以证明本路径不交付密码，未额外读取密码哈希。“Ctrl 只更新该绑定 role”的落库断言见 `[X] test_anvil_uc02_update_role_persists_binding`，本条不冒充已覆盖。

#### Scenario: 旧 ROOT 降为 ADMIN 保留独立账号密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_role_change_semantics_contract
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc02_user_binding_changes_keep_other_bindings
- Assertion scope: `start_root_demotion` 生成一项凭据，`login_name` 等于旧 ROOT 用户表系统用户名；Node `config.password` 等于该凭据密码；成功绑定落为 ADMIN 且 `username` 为该系统用户名。计划项在同一容器另有一条 collaborator 绑定时执行降级，断言该其他绑定仍存在且 role/username 不变。
- Coverage note: 既有用例没有读回其他绑定，不能证明“不删除其他绑定”。

### Requirement: 外部 ROOT 请求统一完整交接

#### Scenario: flag 省略、false、true 执行同一完整交接

- Test/check:
  - [X] test/container/test_password_contracts.py::test_update_role_root_always_handover_contract[omitted]
  - [X] test/container/test_password_contracts.py::test_update_role_root_always_handover_contract[false]
  - [X] test/container/test_password_contracts.py::test_update_role_root_always_handover_contract[true]
- Assertion scope: 三个参数分支都返回 200、`accepted=true`、`Cache-Control: no-store`，`credentials` 恰为 root 与旧 ROOT 系统用户名两项且密码不同；Node 调用顺序为 `admin` 后 `root`，旧 ROOT 用其系统用户名/密码降级，目标用 root 新密码升级；最终只有目标一个 ROOT，Node config 均不含 `transfer_root`；密码不出现在日志与日志文件中。

#### Scenario: 多个旧 ROOT 逐个降级后目标成为唯一 ROOT

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_contract
- Assertion scope: 历史多 ROOT 时凭据数为旧 ROOT 数 + 1，登录名集合包含 root 与各旧 ROOT 系统用户名且密码互异；Node wire 逐个 `admin`、最后 `root`；所有旧 ROOT 绑定落为 ADMIN，目标落为 ROOT/`username=root`，最终 ROOT 集合仅目标；不丢弃涉及人或为凑两项篡改角色。

### Requirement: ROOT 交接的受理与凭据

#### Scenario: 正常单个旧 ROOT 交接返回两项不同登录名

- Test/check:
  - [X] test/container/test_password_contracts.py::test_update_role_root_always_handover_contract[omitted]
  - [X] test/container/test_password_contracts.py::test_root_handover_contract
- Assertion scope: 响应 `accepted=true`，`credentials` 恰为 root 与旧 ROOT 系统用户名两项，密码不同；后台先以旧 ROOT 系统用户名/密码降 ADMIN，再以 root 新密码升目标；Node wire 与凭据密码一一对应。

#### Scenario: 旧 ROOT 降 ADMIN 的独立账号使用其系统用户名

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_contract
- Assertion scope: 旧 ROOT 绑定 `username="root"`、用户表系统用户名为另一个名字时，降级 Node `config.user_name` 与凭据 `login_name` 都使用后者；Node wire 携带该系统用户名与该密码，成功绑定落为 ADMIN/该系统用户名。
- Coverage note: 真实 Node 是否创建/确保独立账号不在本仓库测试范围；Ctrl 侧断言的是 wire 内容与绑定结果。

#### Scenario: 直接 ROOT 降 ADMIN 也返回独立账号密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_role_change_semantics_contract
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc07_direct_root_demotion_api_returns_credential
- Assertion scope: 目标当前为 ROOT 时调用 ROOT→ADMIN，服务返回一项 `login_name` 为系统用户名的凭据；Node `config.password` 等于该凭据；绑定更新为 ADMIN/系统用户名；该路径不经过外部 ROOT 交接的多旧 ROOT 遍历，也不当作普通非 ROOT 互换（普通互换无密码字段）。计划项走 HTTP 入口，断言 200、`accepted=true`、`Cache-Control: no-store`、恰一项凭据，且 Node wire 与绑定符合上述内容。
- Coverage note: 既有用例在 service 层断言凭据/Node/绑定，没有断言 API 的 `accepted` 与 `Cache-Control`。

#### Scenario: 机器或容器不可用时不生成密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_preflight_contract
- Assertion scope: 目标未绑定、容器离线、机器离线分别抛 `target_not_bound`、`container_offline`、`machine_offline`；密码生成器调用记录为空，Node 调用记录为空，不返回凭据。

#### Scenario: 目标未绑定或用户名不可用时不生成密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_preflight_contract
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[target-root]
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[target-leading-dash]
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[old-root-leading-dash]
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc08_handover_preflight_api_maps_409
- Assertion scope: 目标未绑定为 `target_not_bound`；旧 ROOT 系统用户名不可用为 `invalid_root_owner_account`；目标系统用户名为 `root` 或前导 `-` 为 `invalid_target_account`；旧 ROOT 前导 `-` 为 `invalid_root_owner_account`。以上均在生成密码/Node 前失败，密码生成记录为空。计划项走 HTTP 入口，断言目标未绑定/用户名不可用分别返回 409 与对应 reason、无 `credentials`、无 Node 调用。
- Coverage note: 既有用例在 service 层断言 reason 与密码生成器未调用；API 的 409 映射与无凭据响应仍缺断言。

#### Scenario: 调用者先被降级也不影响后续步骤

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_contract
  - [X] test/container/test_role_adversarial.py::test_accepted_handover_survives_caller_permission_revocation
- Assertion scope: 调用者本身是旧 ROOT 时，后台仍完成旧 ROOT 降级与目标升 ROOT；受理后收回调用者机器权限，已受理任务仍完成，目标成为唯一 ROOT。

### Requirement: ROOT 交接的逐步执行与失败边界

#### Scenario: 两步成功各记一条真实日志

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_password_contracts.py::test_root_handover_contract
- Assertion scope: Node 恰好两次调用，顺序 `admin`、`root`；两条 `update_collaborator_role` 成功日志；旧 ROOT 绑定 ADMIN/系统用户名，目标绑定 ROOT/`username=root`；日志文本不含密码。

#### Scenario: 第一步失败不继续第二步

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_role_adversarial.py::test_node_failure_during_demotion_stops_before_promotion[timeout]
  - [X] test/container/test_role_adversarial.py::test_node_failure_during_demotion_stops_before_promotion[exception]
- Assertion scope: 第一个旧 ROOT 降级失败后只发生一次 Node 调用，目标仍为 COLLABORATOR、不会被升 ROOT；失败路径写 `update_collaborator_role` 失败日志；Node 超时与异常两个分支一致。

#### Scenario: 多个旧 ROOT 中任一降级失败也不提拔目标

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc03_multi_root_demotion_failure_writes_failure
- Assertion scope: 既有用例让前一个旧 ROOT 成功降 ADMIN、后一个失败，断言只发生两次 `admin` Node 调用、目标仍 COLLABORATOR、仍有一个旧 ROOT 保留。计划项补失败步骤的 `update_collaborator_role` 失败日志、没有目标 ROOT 成功日志，且日志不含密码。
- Coverage note: 既有用例没有断言失败 oplog 内容。

#### Scenario: 第二步失败不伪报整体成功

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
- Assertion scope: 旧 ROOT 已成功降 ADMIN 的绑定保留；目标仍 COLLABORATOR、不记 ROOT 成功；失败步骤写 `update_collaborator_role` 失败日志。
- Coverage note: 用例没有单独统计成功日志条数；目标绑定未落 ROOT 且失败日志存在，已覆盖“不伪报整体成功”的可观察结果。

#### Scenario: 绑定更新失败也停止后续步骤

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_role_adversarial.py::test_binding_failure_during_demotion_stops_before_promotion
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc04_binding_failure_writes_failure_oplog
- Assertion scope: 第二步 Node 成功后写目标绑定失败时，旧 ROOT 保持 ADMIN、目标保持 COLLABORATOR，后续不再执行；降级步骤绑定失败时旧 ROOT 保持 ROOT，目标不升。计划项补失败步骤的失败 oplog、不写该步成功日志，且日志不含密码。
- Coverage note: 既有两个用例只断言停止与角色状态，没有断言失败 oplog。

#### Scenario: 后台最小 guard 复核失败只记失败

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc05_background_guard_failure_writes_failure_oplog
- Assertion scope: 已受理后容器离线，后台执行前 guard 失败时不调用 Node，目标保持 COLLABORATOR。计划项补失败 oplog、无该步成功日志、无新增 DTO/持久状态，且日志不含密码。
- Coverage note: 既有用例没有断言失败 oplog。

#### Scenario: Node 只改指定目标

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_account_wire_contracts.py::test_ctrl_legacy_transfer_root_never_enters_node_wire
- Assertion scope: Ctrl 按旧 ROOT 与目标逐个发起 `update_role`，每个 Node payload 只暴露该步的 `config.user_name`/`updated_role` 等单目标字段；Node wire 不含 `transfer_root`。
- Coverage note: 既有测试没有也不应由 Ctrl 断言真实 Node 内部是否扫描其他账号；这里只能证明 Ctrl 每次只发送一个目标，Node 自身不自动扫描的承诺不在本仓库测试范围内。

### Requirement: ROOT 交接的并发串行化与已受理冲突

#### Scenario: 真实线程同容器并发只允许一个交接完成

- Test/check:
  - [X] test/container/test_role_adversarial.py::test_threaded_handover_barrier_keeps_one_root_and_attributes_commands
- Assertion scope: 两个真实线程在 barrier 后竞争同一容器锁；恰好一个完成降旧 ROOT、升目标并发送 `admin`/`root` 两次 Node，另一个 stale 退出且零 Node；最终 ROOT 集合恰好一个，Node 命令只归属胜出任务的凭据，失败任务密码不出现在 wire/日志。

#### Scenario: 同机独立进程竞争同一容器锁

- Test/check:
  - [X] test/container/test_role_adversarial.py::test_container_role_lock_nested_reentrant_and_empty_marker
  - [X] test/container/test_role_adversarial.py::test_container_role_lock_cross_process
  - [X] test/container/test_container_role_lock.py::test_thread_lock_fallback_works_without_fcntl
  - [X] test/container/test_container_role_lock.py::test_role_lock_rejects_symlink_directory_without_chmod
  - [X] test/container/test_container_role_lock.py::test_forked_child_does_not_inherit_parent_reentrancy_or_lock_descriptor
- Assertion scope: 同线程嵌套获取可重入且锁文件为空标记；独立子进程持锁时另一子进程阻塞，释放后才获得；无 fcntl 时线程锁仍能阻塞同进程竞争者；符号链接锁目录被拒且未改权限/写文件；fork 子进程不继承父进程重入资格。锁文件只作空标记，不含密码或业务状态。
- Coverage note: 跨进程用例仅在 POSIX（`fcntl`/`fork`）有效，Windows 上按既有 skip 条件不执行；本计划不宣称 Windows 跨进程互斥。

### Requirement: ROOT 交接的身份预检与获锁复核

#### Scenario: 已受理的同容器交接冲突以 stale 结束

- Test/check:
  - [X] test/container/test_role_adversarial.py::test_repeated_handover_to_same_target_keeps_one_root_and_stales_second
  - [X] test/container/test_role_adversarial.py::test_interleaved_handover_to_two_targets_must_not_leave_two_roots
- Assertion scope: 第二次任务持锁后重读发现当前 ROOT 集合与受理快照不同，写一条 `root_handover_stale` 失败并在任何 Node 前退出；第二个响应中的密码不出现在 Node wire/日志；最终恰好一个 ROOT，后受理目标不增加额外 ROOT。
- Coverage note: 既有断言隔离的是 `expected_root_ids`/`current_root_ids` 的 ROOT 集合差异；目标角色与用户名的单独比较没有被这些用例分开断言。

#### Scenario: Node 不可用用户名在预检被拒

- Test/check:
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[target-root]
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[target-leading-dash]
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[old-root-leading-dash]
  - [X] test/container/test_password_contracts.py::test_root_handover_preflight_contract
- Assertion scope: 目标系统用户名 `root`/前导 `-` 返回 `invalid_target_account`，旧 ROOT 系统用户名前导 `-` 或与保留 `root` 冲突返回 `invalid_root_owner_account`；均在生成密码、返回 200、调用 Node 前失败，不产生凭据。

### Requirement: ROOT 交接保留逐步提交事实

#### Scenario: 机器中途维护或 DB/审计异常不整批回滚

- Test/check:
  - [X] test/container/test_role_adversarial.py::test_machine_offline_between_steps_keeps_first_committed_fact
  - [X] test/container/test_role_adversarial.py::test_db_or_audit_exception_does_not_rollback_committed_step[binding]
  - [X] test/container/test_role_adversarial.py::test_db_or_audit_exception_does_not_rollback_committed_step[audit]
- Assertion scope: 第一步旧 ROOT 已成功降 ADMIN 并提交绑定/成功日志；下一步前机器离线或该步绑定/审计抛 DB 异常时，第一步 ADMIN 与成功日志保留。`binding` 分支目标仍未升 ROOT，`audit` 分支目标绑定虽已实际落 ROOT 但不写该步成功日志；两种情况都不整批回滚，失败步骤只影响自身。

### Requirement: 删除用户内部 ROOT 提升的密码兼容

#### Scenario: 删除用户内部提升生成随机 root 密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_delete_user_root_password_contract
- Assertion scope: 删除用户触发内部提升时，Node 第一次调用是目标单目标 `updated_role=root`，携带非空 `config.root_password` 且不等于 `{user_name}123`；不带 `transfer_root`；目标最终成为 ROOT。第一次调用即为 root 提升（而非外部交接的旧 ROOT 降级），证明没有使用外部完整交接编排；不产生 HTTP 凭据响应。
- Coverage note: 用例没有断言总 Node 调用次数；第一次调用形态与后续删除流程已覆盖“不是外部交接编排”的可观察部分。

#### Scenario: 内部提升失败不回退弱密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_delete_user_root_password_contract
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc06_delete_user_internal_promotion_failure_no_retry
- Assertion scope: Node 内部提升失败时删除返回 `False`，用户/绑定保留；失败调用的 `root_password` 仍不是 `{user_name}123`。计划项补断言没有第二次用弱密码/空密码重试，且不存在伪造凭据或持久状态，失败日志不含密码或 Node 原始请求/响应体。
- Coverage note: 既有用例只检查第一次调用的密码值，没有断言失败后的重试次数。
