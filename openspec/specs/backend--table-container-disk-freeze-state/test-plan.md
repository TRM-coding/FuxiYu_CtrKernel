# backend--table-container-disk-freeze-state Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

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
