# backend--table-long-term-containers Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

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
