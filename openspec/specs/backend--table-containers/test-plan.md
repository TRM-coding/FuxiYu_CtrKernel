# backend--table-containers Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: containers 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c01_container_readback_and_defaults
  - [X] test/container/test_container_tasks_lifecycle.py::test_create_container_success_sends_node_then_creates_db_record_and_root_binding
  - [X] test/container/test_container_tasks_information.py::test_get_container_detail_keeps_default_status_from_db
- Assertion scope: 创建用例确认落库行、`container_status=creating` 与 ROOT 绑定（user_id/username/role）；详情用例只断言服务返回默认 `effective_status=online`，未单独证明非内存，新会话按主键读回由 C01 覆盖。 规划项按主键用新会话读取最小行与完整行，断言字符串/整数/枚举/时间类型、可空列 NULL、`is_valid` 与状态默认值，并用裸 SQL 省略 `is_valid` 验证数据库 server_default=1。
- Coverage note: 现有 `[X]` 为同会话读取且只覆盖创建状态/绑定与默认状态；新会话按主键的类型/空值语义与 DB server_default 由 C01 补齐。

#### Scenario: 不新增观测列

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_no_new_disk_observation_columns
  - [X] test/container/test_gate_disk_measurement.py::test_api_output_uses_only_existing_disk_fields
  - [X] test/container/test_gate_disk_measurement.py::test_dev_inode_pid_are_not_consumed_or_persisted
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c29_disk_facts_use_only_container_columns
- Assertion scope: 列集合断言禁止的观测/身份列不存在，且 `disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_total_bytes`、`disk_checked_at`、`bind_mount_path` 五个既有列存在；磁盘输出恰为 overlay/bind/total/bind_mount_path 四项；带 st_dev/st_ino/pid/source 的帧只写路径与字节，不产生新列。 该场景是表结构约束，列反射是直接检查，不据此宣称磁盘行为；C29 补“不以 JSON 或其他表替代磁盘业务状态”的结构检查。

### Requirement: containers 生产职责与生命周期

#### Scenario: 创建资源校验

- Test/check:
  - [X] test/container/test_container_tasks_lifecycle.py::test_create_container_rejects_invalid_resource_payload
  - [X] test/container/test_container_shared_memory_limit.py::test_shared_above_machine_limit_rejected
  - [X] test/container/test_container_shared_memory_limit.py::test_shared_above_requested_memory_rejected
  - [X] test/container/test_container_shared_memory_limit.py::test_create_params_sequence_enforces_machine_limit
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c02_create_resource_limits_report_specific_values
- Assertion scope: 内存 8GB 超过机器 4GB 时抛 `invalid_config`；共享内存 20 超过机器 16、共享 16 超过申请内存 8 时均抛 `invalid_config`，错误文本分别含 20/16 与 16/8；完整创建校验序列同样拒绝共享 24 超过机器 16。 现有断言覆盖内存越界与共享内存具体数值；CPU/GPU 越界及 CPU/GPU 错误文本中的具体数值由 C02 补齐。
- Coverage note: C02 需断言 CPU 超过机器核数、GPU 超过 allowance 均 `invalid_config` 且文本含请求值与上限值，并在校验失败时不发 Node。Requirement 正文的删除保留无效行/快照、WSS 对账与 effective_status 由 `test/container/test_container_tasks_lifecycle.py::test_remove_container_success_marks_container_invalid_and_keeps_bindings`、`test/container/test_deleted_containers.py::test_remove_container_records_deleted_snapshot_and_mount_cleanup`、`test/container/test_cross_repo_protocol_replay.py::test_node_creating_payload_keeps_ctrl_creating_record`、`test/container/test_container_tasks_information.py::test_get_container_detail_reads_status_from_db` 与 `test/container/test_container_effective_status.py::test_status_unknown_when_machine_collect_error` 的既有用例覆盖；本计划不重复列行。 Q74 已定删除/恢复边界（删除在同一事务重置冻结/宽限；无冻结行正常；回滚保留；重复删除幂等；恢复按新建，不继承冻结、不授予宽限）不属于 94 Scenario 的独立 THEN，但属于本 Requirement 正文。以下 `::` 均指同文件 `test/container/test_long_term_transitions.py`：`::test_generic_soft_delete_clears_only_target_freeze_row`（目标冻结行删除、其他容器三字段不变）、`::test_generic_soft_delete_without_freeze_row_is_normal`（无冻结行正常）、`::test_delete_rollback_keeps_container_and_freeze_row`（事务回滚保留容器与冻结行）、`::test_repeated_soft_delete_is_idempotent`（重复删除幂等、deleted_at 不变、无冻结行）、`::test_api_and_cleanup_removal_clear_freeze_row`（API/cleanup 删除均清冻结行，operator=1/None）、`::test_delete_then_restore_long_term_does_not_inherit_freeze_or_grace`（恢复按新建，不继承冻结/宽限，长期标记保留且仅一条）。不新增字段、表、DTO 或协议。

#### Scenario: 共享内存双重上限

- Test/check:
  - [X] test/container/test_container_shared_memory_limit.py::test_shared_above_machine_limit_rejected
  - [X] test/container/test_container_shared_memory_limit.py::test_shared_above_requested_memory_rejected
  - [X] test/container/test_container_shared_memory_limit.py::test_shared_above_8_accepted_when_within_machine_and_memory
- Assertion scope: 机器共享上限 16、申请内存 32、请求共享 20：`invalid_config` 且文本含 20 与 16；机器共享上限 32、申请内存 8、请求共享 16：`invalid_config` 且文本含 16 与 8；共享 16、内存 24、机器上限 16 时放行。

### Requirement: containers 镜像归属与平台解析

#### Scenario: 运行镜像由平台解析

- Test/check:
  - [X] test/container/test_container_image_id.py::test_create_container_api_ignores_client_supplied_image
  - [X] test/container/test_container_image_id.py::test_create_container_api_requires_image_id
  - [X] test/container/test_container_image_id.py::test_resurrect_sends_image_build_and_keeps_image_id
  - [X] test/container/test_container_image_id.py::test_dangling_image_id_cannot_be_written
  - [X] test/container/test_container_image_id.py::test_recipe_never_decides_identity_or_staleness
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c03_restore_ignores_client_image_name
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c39_create_wire_config_image_uses_platform_tag
- Assertion scope: 创建请求同时带 `image_id=1` 与客户端 `image=evil` 时，服务层收到 `image_id=1`，且 `captured[0]["container"].image == image_build["image_tag"]`、不含 evil；缺 `image_id` 返回 400 `invalid_payload` 且不调用服务；恢复实际发送 `image_build` 并保留 `image_id`；悬空 `image_id` 被外键拒绝；配方内容不参与归属与落后判定。 该 `[X]` 只证明服务层对象，不证明发给 Node 的 wire；创建 wire 的 `config.image` 由 C39 补，恢复 wire 已由 `test_resurrect_sends_image_build_and_keeps_image_id` 覆盖，恢复请求体镜像名忽略由 C03 补。

### Requirement: containers 构建版本戳与运行标签

#### Scenario: 落后判据只看版本戳

- Test/check:
  - [X] test/container/test_container_image_id.py::test_behind_judgement_ignores_created_at
  - [X] test/container/test_container_image_id.py::test_display_shows_snapshot_when_behind
  - [X] test/container/test_container_image_id.py::test_restore_without_template_choice_when_not_behind
  - [X] test/container/test_container_image_id.py::test_restore_uses_snapshot_when_template_not_ready
- Assertion scope: `is_version_behind` 只接收版本时间：相等不落后、早一天落后、晚一天不落后、缺版本戳按落后、模板版本未知不落后；创建时间较新的容器在 `last_build_at=2020` 时仍展示旧留痕；配方 FROM 与模板一致时不要求选择；模板非 READY 直接取快照。 未验证生产 MySQL；创建时间不参与判据由纯函数与展示用例共同证明。

#### Scenario: 标签推导不出时不编造

- Test/check:
  - [X] test/container/test_container_image_id.py::test_image_tag_is_never_fabricated
  - [X] test/container/test_container_image_id.py::test_restore_without_binding_uses_snapshot_without_tag_fallback
  - [X] test/container/test_container_image_id.py::test_restore_rejects_when_tag_cannot_be_derived
- Assertion scope: `image_id` 或 `last_build_at` 任一缺失时 `format_image_build_tag` 返回 None，且不等于用当天日期编造的标签；无归属有留痕时恢复解析的 tag 为 None；真实恢复在 tag 不可推导时抛 `invalid_payload`。

#### Scenario: 秒级版本递增不掩盖内容差异

- Test/check:
  - [X] test/container/test_container_image_id.py::test_same_second_recipe_change_still_supersedes_the_tag
  - [X] test/container/test_container_image_id.py::test_template_recipe_change_replaces_the_same_cache_row
  - [X] test/container/test_container_image_id.py::test_metadata_only_edit_keeps_the_cache_hit
  - [X] test/container/test_container_image_id.py::test_restore_marks_choice_when_template_is_newer
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c04_future_stamp_recipe_change_still_marks_choice
- Assertion scope: 已种未来版本戳时新标签严格递进一秒；模板配方正文变化后同一 `(machine,image)` 行替换为新 tag/版本戳/指纹；只改名或描述时 tag 与版本戳不变；配方内容不同时恢复标 `needs_choice`。 现有断言分别覆盖未来版本戳、配方变化与元数据不变；“未来版本戳 + 模板正文随后变化仍识别内容差异”的组合由 C04 补齐。

### Requirement: containers 构建配方留痕与运行基底展示

#### Scenario: 运行基底展示不随模板编辑失真

- Test/check:
  - [X] test/container/test_container_image_id.py::test_display_shows_snapshot_when_behind
  - [X] test/container/test_container_image_id.py::test_display_always_prefers_snapshot_regardless_of_freshness
  - [X] test/container/test_container_image_id.py::test_display_falls_back_to_template_without_snapshot
  - [X] test/container/test_container_image_id.py::test_display_survives_template_being_disabled
  - [X] test/container/test_container_image_id.py::test_container_always_renders_the_current_injection
  - [X] test/container/test_container_image_id.py::test_image_dockerfile_falls_back_to_snapshot_without_binding
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c30_rendered_dockerfile_and_injection_not_persisted
- Assertion scope: 旧留痕容器展示旧 `FROM`/业务片段而非当前模板；无留痕时回落当前模板；模板停用仍展示留痕；平台注入改动后渲染立即使用新注入且不改留痕；无归属有留痕展示留痕，无归属无留痕返回 None。 C30 以列集合直接检查渲染后的完整文本与平台注入不在 `containers` 表；这是结构约束，不据此宣称渲染行为。

### Requirement: containers 恢复内容来源选择

#### Scenario: 内容会变时先交回两份

- Test/check:
  - [X] test/container/test_container_image_id.py::test_restore_returns_choice_when_behind
  - [X] test/container/test_container_image_id.py::test_resurrect_api_returns_choice_without_restoring
  - [X] test/container/test_container_image_id.py::test_resurrect_snapshot_choice_uses_the_container_recipe
  - [X] test/container/test_container_image_id.py::test_resurrect_uses_template_only_when_explicitly_asked
  - [X] test/container/test_container_image_id.py::test_restore_uses_template_when_not_behind
  - [X] test/container/test_container_image_id.py::test_restore_uses_snapshot_when_template_not_ready
  - [X] test/container/test_container_image_id.py::test_restore_without_binding_uses_snapshot_without_tag_fallback
  - [X] test/container/test_container_image_id.py::test_restore_without_snapshot_raises_instead_of_degrading
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c05_restore_source_uses_current_injection_and_refreshes_stamp
- Assertion scope: 未指定来源且两份不同：`requires_choice=true`，snapshot/template 的 Dockerfile 分别来自留痕与当前模板，sections 只列 `base_image`/`dockerfile_body` 且无平台注入，`container_id` 为空，HTTP 层不发送 `create_container`；指定 snapshot/template 分别走对应配方；模板非 READY 或无归属走快照；无留痕时以 `data_not_recoverable` 拒绝而不降级。 现有断言覆盖选择响应与来源分支；两种来源均使用当前注入并在实际恢复时刷新 `last_build_at`、选择一致标签的完整组合由 C05 补齐。

### Requirement: containers 恢复挂载与数据位置

#### Scenario: 恢复来源与改名不迁移数据

- Test/check:
  - [X] test/container/test_container_image_id.py::test_restore_mount_follows_snapshot_not_new_name
  - [X] test/container/test_container_image_id.py::test_restore_mount_is_identical_across_content_sources
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c06_restore_mount_same_path_across_sources
- Assertion scope: 原容器名被占用时恢复改名，但 `restore_mount_path` 仍以原容器名 `_data` 结尾；两种内容来源都发送构建段。 改名不改数据位置已断言；现有跨来源用例为不同容器名，无法证明同一数据位置。C06 构造两份等价快照（同一容器数据、不同 `deleted_id`），分别指定 snapshot/template，避免首恢复消费同一行；比较 `restore_mount_path` 完全相同。
- Coverage note: 不使用同一快照重复恢复；两份等价快照共享同一容器数据/挂载路径，仅 `deleted_id` 不同，以隔离消费副作用。

### Requirement: 镜像换代保持容器留痕与关联有效

#### Scenario: 缓存换代后读取旧容器

- Test/check:
  - [X] test/container/test_container_image_id.py::test_delete_image_disables_and_keeps_binding
  - [X] test/container/test_container_image_id.py::test_display_shows_snapshot_when_behind
  - [X] test/container/test_container_image_id.py::test_common_fields_expose_ownership_and_template_name
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c07_old_container_version_survives_new_cache_dispatch
- Assertion scope: 模板停用后容器行仍在且 `image_id` 保持 1；旧容器 `last_build_at` 落后时展示自身留痕；公共字段返回 `image_id` 与模板名且不返回 `container_image` 标签字段。 未构造“同一 machine/image 已派发新版本后读取旧容器”的完整序列；旧容器 `image_id`/`last_build_at`/配方不被新派发改写的断言由 C07 补齐。

#### Scenario: 恢复采用历史正文与当前注入

- Test/check:
  - [X] test/container/test_container_image_id.py::test_container_always_renders_the_current_injection
  - [X] test/container/test_container_image_id.py::test_resurrect_snapshot_choice_uses_the_container_recipe
  - [X] test/container/test_container_image_id.py::test_sections_never_include_platform_injection
  - [X] test/container/test_container_image_id.py::test_restore_marks_choice_when_template_is_newer
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c05_restore_source_uses_current_injection_and_refreshes_stamp
- Assertion scope: 平台注入设置变化后容器渲染立即使用新注入，`image_id`/`base_image` 不变；选择 snapshot 时下发的 Dockerfile 等于容器留痕按当前注入渲染的结果；分段从不包含平台注入；留痕命中缓存时复用与该配方一致的 planted tag，模板路径使用另一 tag。 恢复实际发送的构建段同时刷新 `last_build_at` 且 tag 与最终配方一致的断言由 C05 补齐。

### Requirement: 名称缺席不构成删除依据

#### Scenario: 创建受理后快照缺席

- Test/check:
  - [X] test/container/test_vanish_guard.py::test_snapshot_missing_marks_pending_and_keeps_record_binding_and_long_term
  - [X] test/container/test_cross_repo_protocol_replay.py::test_node_snapshot_missing_marks_pending_not_deleted
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c33_starting_transition_snapshot_absence_is_protected
- Assertion scope: CREATING/ONLINE 两种状态在非空快照缺席后：行仍有效、id 不变、`status_source=snapshot_missing`、`status_unknown_since` 非空、删除触发为空，账号绑定与长期标记保留，无成功删除审计与恢复快照；真实 Node creating 帧同样只标待核实。 C33 补 Requirement 正文“创建和启动过渡态同等保护”中的 STARTING/RESTARTING/STOPPING 缺席分支。

#### Scenario: 运行中容器快照暂时缺席

- Test/check:
  - [X] test/container/test_vanish_guard.py::test_snapshot_missing_marks_pending_and_keeps_record_binding_and_long_term
  - [X] test/container/test_vanish_guard.py::test_snapshot_missing_only_marks_absent_container_same_machine
  - [X] test/container/test_vanish_guard.py::test_snapshot_missing_does_not_cross_machine_same_name
  - [X] test/container/test_cross_repo_protocol_replay.py::test_node_snapshot_missing_marks_pending_not_deleted
- Assertion scope: ONLINE 容器缺席：记录、绑定、长期标记保留，标记待核实且无成功删除审计；同机只标本容器；跨机同名不误标。

#### Scenario: 旧代名称删除帧

- Test/check:
  - [X] test/container/test_vanish_guard.py::test_delete_frame_marks_current_record_without_soft_delete
  - [X] test/container/test_vanish_guard.py::test_old_delete_frame_after_same_name_recreate_marks_new_record_only
  - [X] test/container/test_vanish_guard.py::test_late_vanish_clue_after_api_delete_does_not_touch_invalid_row
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c36_delete_frame_preserves_accounts_and_long_term
- Assertion scope: 仅名称/机器的 delete 帧：当前有效行不软删、无删除日志/快照，只标 `delete_frame` 与时间；同名重建后旧帧只标新行，旧软删行保持 api 删除事实；主动删除后的迟到线索不改无效行、不新增快照/日志。 现有用例未断言“保留其关联”中的账号绑定与长期标记；C36 预置 ROOT 绑定和长期标记后收到 delete 帧，断言行有效、绑定仍在、长期标记仍为真、无删除审计/快照。

### Requirement: 不可判定采集不制造消失

#### Scenario: Node 采集错误

- Test/check:
  - [X] test/container/test_cross_repo_protocol_replay.py::test_node_collect_error_payload_does_not_mark_or_delete
  - [X] test/container/test_container_effective_status.py::test_status_unknown_when_machine_collect_error
- Assertion scope: collect_error 帧：`vanished=0`，容器仍有效且 `status_source` 为空，机器 `collect_error_at` 落库，无删除日志；`effective_status` 为 `status_unknown`。

### Requirement: 正向观察清除待核实状态

#### Scenario: 容器重新出现在快照

- Test/check:
  - [X] test/container/test_vanish_guard.py::test_positive_status_clears_absence_marker
  - [X] test/container/test_vanish_guard.py::test_positive_status_on_other_machine_does_not_clear_marker
  - [X] test/container/test_vanish_guard.py::test_soft_deleted_same_name_is_not_resurrected_by_status_snapshot
- Assertion scope: online/offline/paused/failed 明确状态重新出现：保留原 id，更新 `container_status`，清空 `status_unknown_since`/`status_source`；其他机器同名或已软删同名不因此清标记/复活。

#### Scenario: 重新出现但状态仍未知

- Test/check:
  - [X] test/container/test_vanish_guard.py::test_unknown_or_transition_status_keeps_absence_marker
- Assertion scope: unknown 与 pausing/unpausing/building/creating/starting/restarting/stopping 八种状态仍保留 `status_unknown_since`/`status_source`，不当作恢复或删除。

### Requirement: 消失线索可追溯

#### Scenario: 两种线索先后到达

- Test/check:
  - [X] test/container/test_vanish_guard.py::test_vanish_sources_are_distinguishable_and_throttled
  - [X] test/container/test_cross_repo_protocol_replay.py::test_node_delete_then_snapshot_frames_do_not_soft_delete
- Assertion scope: 同一容器先 `delete_frame` 后 `snapshot_missing`：日志分别含 `source=delete_frame`/`source=snapshot_missing`、machine_id/container_id/observed_at；`status_source` 为 snapshot_missing，容器有效且无删除审计；真实 WSS delete+snapshot 串行处理后仍有效、无快照/删除日志。

### Requirement: Node 路径修正与业务路径

#### Scenario: resolved 路径修正

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_resolved_path_updates_and_accepts_same_frame
  - [X] test/container/test_cross_repo_protocol_replay.py::test_node_resolved_payload_updates_path_and_measurement
  - [X] test/container/test_gate_disk_measurement.py::test_dev_inode_pid_are_not_consumed_or_persisted
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c34_wrong_machine_or_inactive_container_frame_is_ignored
- Assertion scope: resolved 帧同帧落路径 B 并接收 total/overlay/bind/measured_at；真实 Node payload 同样；帧带 st_dev/st_ino/pid/source 时只写路径与字节，模型无这些身份列。 C34 补 Requirement 正文“仅对当前认证机器上的活跃容器应用修正/测量”的负例：错误机器、已软删或非活跃容器帧不得改写 `bind_mount_path`/`disk_*`。

#### Scenario: 原有 bind 路径转为明确 no_bind

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_no_bind_clears_path_and_old_measurement_then_accepts_overlay_only
  - [X] test/container/test_cross_repo_protocol_replay.py::test_node_no_bind_payload_clears_path_and_uses_overlay_only
- Assertion scope: 明确 no_bind：`bind_mount_path` 清空、bind bytes 为 None，total/overlay 用新 overlay-only 样本，`disk_checked_at` 更新；不保留旧 bind 22。

#### Scenario: unresolved 只保留路径不清空

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_unresolved_preserves_path_and_accepts_same_path_measurement
  - [X] test/container/test_cross_repo_protocol_replay.py::test_node_unresolved_and_not_running_keep_path_and_accept_measurement
- Assertion scope: unresolved/not_running 且同路径测量成功：路径保留，total/checked_at 接收，`updated=1`；不因 unresolved 阻断测量。

#### Scenario: 旧 Node 不改写已校正路径

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_legacy_frame_does_not_overwrite_corrected_path
  - [X] test/container/test_gate_disk_measurement.py::test_old_node_rollback_after_correction_stops_actions_once_stale
- Assertion scope: 已校正为 B 后旧帧带 A：路径保持 B，A 的字节不写入且旧 `disk_checked_at` 不变，`updated=0`；回滚旧 Node 后 A 持续被拒，B 过期后调度不做动作。

#### Scenario: 旧 Node 首次建立路径

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_legacy_frame_establishes_path_only_when_current_path_empty
  - [X] test/container/test_gate_disk_measurement.py::test_legacy_frame_with_both_paths_empty_does_not_claim_no_bind
- Assertion scope: 当前路径为空且旧帧带 A+完整测量：建立 A、接收字节并写非空 `disk_checked_at`（旧协议接收时间兼容）；两路径都空时 `updated=0` 且不声称 no_bind。

#### Scenario: no_bind 后旧 Node 不得重建路径

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_no_bind_marker_blocks_legacy_path_rebuild
  - [X] test/container/test_gate_disk_measurement.py::test_no_bind_marker_lost_after_restart_is_documented_residual
- Assertion scope: 明确 no_bind 后旧帧带 A：进程内标记拒绝重建，路径保持 None、旧测量保持 500；标记仅进程内，重启后旧帧可重建路径是已登记残差。 该残差由现测锁定，不是本计划新行为；未新增持久化列。

#### Scenario: 路径修正不批量改历史

- Test/check:
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c08_path_correction_does_not_rewrite_history
- Assertion scope: 规划项：创建容器并修正路径 B，同时预置使用旧路径 A 的恢复快照、挂载清理记录与其他机器同名容器；断言只更新当前活跃容器，历史快照/清理记录/其他机器路径保持 A。 现有路径用例只覆盖当前容器更新，未覆盖历史记录隔离。
- Coverage note: 现有 `[X]` 不覆盖该 THEN，故本场景无既有断言行；C08 补齐。

### Requirement: 磁盘测量接收与路径一致性

#### Scenario: 错误样本不伪造零

- Test/check:
  - [X] test/container/test_container_disk_check_task.py::TestDiskUsageSnapshotCompleteness::test_apply_disk_usage_snapshot_skips_missing_total_without_clobbering_existing_fields
  - [X] test/container/test_container_disk_check_task.py::TestDiskUsageSnapshotCompleteness::test_apply_disk_usage_snapshot_skips_missing_bind_bytes_when_bind_mount_exists
  - [X] test/container/test_container_disk_check_task.py::TestDiskUsageSnapshotCompleteness::test_apply_disk_usage_snapshot_skips_missing_overlay_without_clobbering_existing_fields
  - [X] test/container/test_gate_disk_measurement.py::test_path_change_clears_old_measurement_and_late_old_sample_is_rejected
  - [X] test/container/test_gate_disk_measurement.py::test_update_container_none_does_not_clear_disk_facts
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c37_disk_rejection_logs_reason_without_zero
- Assertion scope: 缺 total/bind/overlay 的样本 `updated=0`，旧 bytes 与 `checked_at` 不变且不写 0；新协议路径变化帧先清空 `disk_*` 与 `disk_checked_at` 再等新样本；普通 None 不清，`clear_fields` 才清。 现有断言未覆盖 THEN 的“日志记录拒绝原因”；C37 用 caplog 对缺 total/bind/overlay/路径不一致样本断言 `apply disk snapshot rejected` 且 reason 为 `total_bytes_missing`/`bind_bytes_missing`/`overlay_incomplete`/`path_inconsistent`，同时 bytes 不写 0、旧值不刷新。

#### Scenario: 重复缓存帧不刷新测量时间

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_repeated_cached_frame_does_not_advance_measurement_time
  - [X] test/container/test_gate_disk_measurement.py::test_legacy_cache_heartbeat_advances_receipt_time_compat
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c09_repeated_frame_same_timestamp_conflicting_path_rejected
- Assertion scope: 同一 `measured_at` 重复帧两次后 `checked_at` 仍等于真实测量时间，bytes 不变；无 `measured_at` 的旧帧按接收时间推进。 现有重复帧使用同一路径，未变化路径；重复帧不得改写路径与同时间戳路径冲突由 C09 补齐。

#### Scenario: 已知旧测量不回退

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_measured_at_older_than_checkpoint_rejects_path_and_measurement
  - [X] test/container/test_gate_disk_measurement.py::test_future_measured_at_is_rejected_without_touching_existing_facts
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c09_repeated_frame_same_timestamp_conflicting_path_rejected
- Assertion scope: 真实 `measured_at` 早于现有 `checked_at` 时 `updated=0`，路径与旧值保持；未来时间超过偏差时同样拒绝，旧 bytes/`checked_at` 不变。 时间相同但路径冲突的分支由 C09 补齐。

#### Scenario: 明确 no_bind 的 overlay 测量

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_no_bind_clears_path_and_old_measurement_then_accepts_overlay_only
  - [X] test/container/test_cross_repo_protocol_replay.py::test_node_no_bind_payload_clears_path_and_uses_overlay_only
- Assertion scope: no_bind + 完整 overlay + 有效 `measured_at`：路径 None，bind bytes None，total/overlay 为新值，`checked_at` 更新；不混入旧 bind 字节。

#### Scenario: 无效 measured_at 只拒绝测量

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_invalid_measured_at_rejects_measurement_but_still_applies_path
  - [X] test/container/test_gate_disk_measurement.py::test_new_protocol_missing_measured_at_rejects_measurement_but_keeps_path
  - [X] test/container/test_gate_disk_measurement.py::test_future_measured_at_is_rejected_without_touching_existing_facts
- Assertion scope: 无效/缺失 `measured_at`：bytes 与 `checked_at` 不更新（保持 None 或旧值），同帧合法路径仍落库；未来时间拒绝测量且不动既有事实。

### Requirement: 路径变化清空旧测量

#### Scenario: 路径改变后旧样本晚到

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_path_change_clears_old_measurement_and_late_old_sample_is_rejected
  - [X] test/container/test_gate_disk_measurement.py::test_old_node_rollback_after_correction_stops_actions_once_stale
- Assertion scope: 路径改为 B 后旧 A 样本 `updated=0`，路径保持 B，A 的 33 bytes 不写入 B；旧 Node 回滚的 A 持续被拒。

#### Scenario: 路径变化先清空再回填

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_path_change_clears_old_measurement_and_late_old_sample_is_rejected
  - [X] test/container/test_gate_disk_measurement.py::test_resolved_path_updates_and_accepts_same_frame
  - [X] test/container/test_gate_disk_measurement.py::test_update_container_none_does_not_clear_disk_facts
- Assertion scope: A→B 帧先清空旧 `disk_*` 与 `disk_checked_at`（断言 None），同帧完整 B 才回填；普通 None 不清，专用 `clear_fields` 才清。

### Requirement: 评估只使用当前可信测量

#### Scenario: 测量过期不动作

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_scheduler_skips_all_actions_when_measurement_stale
  - [X] test/container/test_gate_disk_measurement.py::test_old_node_rollback_after_correction_stops_actions_once_stale
  - [X] test/container/test_gate_disk_measurement.py::test_usage_from_db_requires_fresh_measurement
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c38_stale_measurement_does_not_reopen_or_extend_freeze_cycle
- Assertion scope: `checked_at` 超过最大年龄：`_usage_from_db` 返回 None；调度不调用 hard-limit handler、不创建冻结记录；回滚旧 Node 后同样无动作。 “不 pause/邮件/升级删除/挂载清理”通过不调用统一 hard-limit handler 与无冻结记录观察；未分别 spy 每个下游副作用。现有断言未覆盖“不重开或顺延既有冻结周期”；C38 预置 `first_frozen_at`/`grace_until`/`deferral` 后跑 stale 调度，断言三字段不变、无新冻结行、无动作。

#### Scenario: unresolved 路径上的有效测量

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_unresolved_preserves_path_and_accepts_same_path_measurement
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c10_unresolved_fresh_measurement_reaches_evaluation
- Assertion scope: unresolved + 同路径成功测量：路径保留、total/`checked_at` 更新。 该样本能否通过 `_usage_from_db` 进入磁盘评估未断言；C10 补齐。

#### Scenario: resolved 但测量失败

- Test/check:
  - [X] test/container/test_gate_disk_measurement.py::test_invalid_measured_at_rejects_measurement_but_still_applies_path
  - [X] test/container/test_gate_disk_measurement.py::test_future_measured_at_is_rejected_without_touching_existing_facts
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c11_resolved_failed_measurement_does_not_drive_scheduler
- Assertion scope: resolved 但 `measured_at` 无效/未来：不刷新 bytes/`checked_at`，路径合法时仍落库；未来帧不动既有事实。 失败帧后同路径最后成功样本的有效年龄与调度动作未断言；C11 补齐。

#### Scenario: 路径修正不等于删除授权

- Test/check:
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c12_path_correction_does_not_authorize_remove_or_cleanup
- Assertion scope: 规划项：只做路径修正/磁盘测量，不改变权限或业务资格；随后调用删除/挂载清理仍按既有权限、路径和业务检查，路径修正本身不产生 remove/clean_mount。 现有路径/调度用例不覆盖删除授权边界。
- Coverage note: 本场景无既有断言行；C12 补齐，且不把 Q70 跨进程原子性写成已证明。

### Requirement: 容器详情返回既有宿主 bind 路径

#### Scenario: 有记录时原样返回

- Test/check:
  - [X] test/container/test_container_api_information.py::test_get_container_detail_api_returns_bind_mount_path
  - [X] test/container/test_container_tasks_information.py::test_get_container_detail_returns_bind_mount_path_from_row
- Assertion scope: API 详情返回的 `bind_mount_path` 与 DB 值完全一致；服务层读取行值且行未被改写。 非空值读取未显式断言不调用 Node；由 C13 补齐。
- Coverage note: 现有断言覆盖原样返回与行不变；非空路径的“不调 Node”缺口在 C13。Requirement 正文的“不新增列/表/JSON、不改变 WSS”属结构约束，未在运行测试中单独断言；本轮不据此宣称行为。

#### Scenario: 空值或旧响应按未记录处理

- Test/check:
  - [X] test/container/test_container_api_information.py::test_container_detail_information_schema_treats_missing_bind_mount_path_as_none
  - [X] test/container/test_container_api_information.py::test_get_container_detail_api_legacy_payload_missing_bind_mount_path
  - [X] test/container/test_container_tasks_information.py::test_get_container_detail_bind_mount_path_none_without_node
- Assertion scope: schema 缺字段解析为 None；旧服务响应缺字段时 API 200 且返回 null，无 DML、行值不变；DB null 时服务返回 null，不从名称/机器/端口拼路径且不联系 Node。

#### Scenario: 只读查询不写库

- Test/check:
  - [X] test/container/test_container_api_information.py::test_get_container_detail_api_legacy_payload_missing_bind_mount_path
  - [X] test/container/test_container_tasks_information.py::test_get_container_detail_bind_mount_path_none_without_node
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c13_detail_non_null_bind_path_readonly_without_node
- Assertion scope: 旧响应路径：端点期间无 INSERT/UPDATE/DELETE，行值不变；null 场景不联系 Node。 非空 `bind_mount_path` 读取不写库且不联系 Node 由 C13 补齐。

### Requirement: containers entrypoint 留痕说明符合构建语义

#### Scenario: 容器模型与创建流程说明一致

- Test/check:
  - [X] test/test_entrypoint_docs.py::test_entrypoint_docs_describe_build_stage_at_all_four_locations
- Assertion scope: 静态检查 `models/containers.py` 与 `services/container_module/creation.py` 不含旧短语，`containers` 含“参与构建”“ENTRYPOINT”，`creation` 含“ENTRYPOINT”“模板侧的三项”。 该场景本身是文档约束，源码文本是断言对象，不用它证明运行行为。

### Requirement: 容器创建与恢复生成一次性 root 密码

#### Scenario: 创建受理后返回 root 密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_create_restore_credentials_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c14_create_password_absent_and_message_preserved
- Assertion scope: 创建成功响应 `success=1`、`accepted=true`、`credentials` 恰一项 root、password 非空且等于发给服务层的 `root_password`，`Cache-Control=no-store`，且非 `owner123`。 容器行与创建 oplog 不含密码、既有 message 保留未断言；C14 同时覆盖两段：行/oplog 无密码，成功响应保留既有 message。

#### Scenario: 创建失败不返回密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_create_restore_credentials_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c15_create_failure_sends_password_but_redacts
- Assertion scope: 创建服务抛 `NodeServiceError` 时 HTTP 500，响应无 `credentials`。 Node 仍收到顶层 `root_password`、错误响应/日志/容器行不含该密码未断言；C15 补齐。

#### Scenario: 恢复实际执行时生成新密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_create_restore_credentials_contract
  - [X] test/container/test_deleted_containers.py::test_resurrect_container_reuses_snapshot_mount_and_restores_bindings
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c16_restore_password_differs_from_creation
- Assertion scope: 恢复契约响应 `accepted=true`、一项 root 凭据与 no-store；实际恢复用例断言结果 `container_id` 等于原 id、`root_password` 与发给 Node 的顶层字段一致且非空。 契约用例未显式断言 `container_id` 与旧密码差异；C16 补齐“新密码与创建时不同”。

#### Scenario: 内容二选一不生成密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_create_restore_credentials_contract
  - [X] test/container/test_container_image_id.py::test_resurrect_api_returns_choice_without_restoring
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c17_requires_choice_no_password_delivery
- Assertion scope: `requires_choice` 响应 `accepted=false`、`credentials=[]`；HTTP 恢复未发送 `create_container`。 C17 以真实 API 断言无 credentials、未发送 `create_container`；不生成密码是内部状态，以不交付凭据/不调用 Node 的可观察结果为准。

#### Scenario: 内部创建入口也不使用默认密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_create_restore_credentials_contract
- Assertion scope: 直接调用 `Create_container` 且不传密码时，发给 Node 的顶层 `root_password` 非空且不等于 `{owner}123`。

### Requirement: 容器账号密码重置的权限与目标校验

#### Scenario: ROOT 绑定用户重置协作者

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_permission_contract
- Assertion scope: ROOT 绑定重置 COLLABORATOR：结果 `login_name` 为绑定 username，Node `config.user_name` 与 password 对应。 资源层 `container:manage`/`bypass_resource` 通配分支由 C18 补齐；本行覆盖 ROOT 绑定主路径。

#### Scenario: ROOT 绑定固定使用 root 登录名

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_permission_contract
- Assertion scope: 目标绑定 ROOT 时结果 `login_name=root`，Node `config.user_name=root`，不使用绑定历史值。

#### Scenario: 资源管理通配可重置

- Test/check:
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c18_reset_allows_container_manage_and_bypass_resource
- Assertion scope: 规划项：分别以直持 `container:manage` 与 `bypass_resource` 的非绑定调用方请求重置，断言通过资源层并返回 accepted+一次性密码。 现有测试用 monkeypatch `user_has_resource=True` 模拟放行，没有真实区分 `container:manage`/`bypass_resource` 与绑定角色。
- Coverage note: 本场景无既有断言行；C18 补齐真实资源通配分支，并同时断言无密码/无 Node 的拒绝分支。

#### Scenario: 仅实体通配被资源层拒绝

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_permission_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c35_reset_rejections_do_not_deliver_credentials_or_call_node
- Assertion scope: `bypass_auth_entity` 为真但资源权限为假时返回 403 `resource_access_denied`。 现有断言只覆盖 403；C35 对 `bypass_auth_entity` 分支断言无密码生成（生成器 tripwire 未触发）、无 Node 调用、无 credentials/密码字段。

#### Scenario: ADMIN 或 COLLABORATOR 不能重置

- Test/check:
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c19_reset_rejects_admin_and_collaborator_bindings
- Assertion scope: 规划项：以该容器 ADMIN/COLLABORATOR 绑定身份请求重置，断言 403 `resource_access_denied`、无密码、无 Node。 现有测试在资源层 monkeypatch 放行后未再构造绑定角色拒绝。
- Coverage note: 本场景无既有断言行；C19 补齐。

#### Scenario: 目标用户未绑定被拒绝

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_permission_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c35_reset_rejections_do_not_deliver_credentials_or_call_node
- Assertion scope: 目标 `user_id` 未绑定 -> `target_not_bound`。 现有断言只覆盖 `error_reason`；C35 对 `target_not_bound` 分支用密码生成器 tripwire、Node send 替身与 API 响应断言无密码生成、无 Node 调用、无 credentials/密码字段。

#### Scenario: 绑定登录名非法被拒绝

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_permission_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c20_reset_rejects_empty_and_illegal_usernames
- Assertion scope: 非 ROOT 绑定 username='root' -> `invalid_target_account`。 空字符串与非法字符未覆盖；C20 补齐。

#### Scenario: 机器离线时不生成密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_permission_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c35_reset_rejections_do_not_deliver_credentials_or_call_node
- Assertion scope: 机器 OFFLINE -> `machine_offline`。 现有断言只覆盖 `error_reason`；C35 对 `machine_offline` 分支断言无密码生成（生成器 tripwire 未触发）、无 Node 调用、无 credentials/密码字段。

#### Scenario: 容器非 online 时不生成密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_permission_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c21_reset_rejects_paused_failed_and_transition_states
- Assertion scope: 容器 OFFLINE -> `container_offline`。 paused/failed/过渡态未覆盖；C21 补齐。

#### Scenario: 额外字段不能指定登录名

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_permission_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c35_reset_rejections_do_not_deliver_credentials_or_call_node
- Assertion scope: 额外 `login_name` 字段 -> 400 `invalid_payload`。 现有断言只覆盖 400；C35 对额外字段分支断言 service/密码生成器/Node 均未调用，响应无 credentials/密码字段。

#### Scenario: 错误按现有 reason 映射且不拼原始错误体

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_permission_contract
  - [X] test/container/test_password_contracts.py::test_untrusted_reason_redaction_contract
- Assertion scope: `not_found`/`target_not_bound`/`internal_error` 分别 404/409/500，响应不含 Node 原始 `SECRET`；伪造含密码的 reason 只落白名单 `reset_failed`。

### Requirement: 容器密码重置的后台执行与一次性响应

#### Scenario: 受理后立即返回并后台请求 Node

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
  - [X] test/container/test_password_contracts.py::test_reset_permission_contract
- Assertion scope: 受理时 Node 未调用，返回 password 并交给后台；执行后请求 `/api/reset_container_password`，成功 oplog 无密码；HTTP 响应 accepted+credentials+no-store。

#### Scenario: 客户端断开不取消后台任务

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
- Assertion scope: HTTP 响应返回后独立执行后台 target，Node 请求仍发生，成功/失败 oplog 按真实结果写入。 以请求返回后独立调用模拟断开，不是真实 socket 断开。
- Coverage note: 未建立真实断连通道；保留该限界，不把模拟写成真实网络断开证明。

#### Scenario: Node 失败只写失败 oplog

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c22_reset_failure_writes_only_failed_oplog
- Assertion scope: Node 失败：写 `success=False` 的 `reset_container_password` oplog，password 不在 detail。 未断言不存在成功 oplog；C22 补齐。

#### Scenario: 后台复核失败只写 oplog

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
  - [X] test/container/test_password_contracts.py::test_reset_binding_recheck_contract
- Assertion scope: 后台 guard 失败/解绑/username/role 变化：不调 Node，写 `success=False` 且稳定 reason（`container_offline`/`target_not_bound`/`target_changed`），不含密码。

#### Scenario: 密码响应不可缓存

- Test/check:
  - [X] test/container/test_password_contracts.py::test_reset_permission_contract
- Assertion scope: 重置成功响应头 `Cache-Control=no-store`。

### Requirement: 新增协作者的一次性账号密码

#### Scenario: 新增 ADMIN 协作者返回密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_add_collaborator_password_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c23_add_admin_binding_and_no_success_on_failure
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c31_add_collaborator_survives_response_disconnect
- Assertion scope: ADMIN 协作者：返回 `login_name=目标用户名` 与非空密码，Node `config.password` 等于该密码；失败分支不写绑定、失败日志不含密码。 ADMIN 绑定角色是否写入、成功是否只记一条既有 `add_collaborator` 且不新增密码专用日志、Node 失败是否绝无成功 oplog 均未断言；C23 补齐。Requirement 正文“客户端断开不取消”在新增协作者路径未覆盖；C31 用响应后独立执行后台任务模拟断开补齐。
- Coverage note: C31 以响应后独立执行后台任务模拟断开，不是真实 socket 断开；与 reset 后台用例同限界，不把模拟写成真实网络断开证明。

#### Scenario: 新增 COLLABORATOR 协作者返回密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_add_collaborator_password_contract
- Assertion scope: COLLABORATOR 协作者：返回目标用户名凭据，Node `config.password` 对应，成功写 COLLABORATOR 绑定并记一条 `add_collaborator` 日志且不含密码。

#### Scenario: Node 或绑定失败不写成功

- Test/check:
  - [X] test/container/test_password_contracts.py::test_add_collaborator_password_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c23_add_admin_binding_and_no_success_on_failure
- Assertion scope: Node 返回失败：不写绑定，写 `success=False` 的 `add_collaborator` 日志，密码不在 detail。 未断言没有成功日志；绑定写入失败分支未覆盖；C23 补齐。

#### Scenario: 前置校验失败不生成密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_add_collaborator_password_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c24_add_precheck_no_password_delivery
- Assertion scope: 容器 OFFLINE 前置校验失败：抛 `container_offline`，Node 调用列表为空。 C24 以真实服务断言不调用 Node、不写绑定/成功日志；不生成密码是内部状态，以不交付凭据/不调用 Node 的可观察结果为准。

#### Scenario: 后台最小 guard 复核失败只写失败日志

- Test/check:
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c25_add_background_guard_failure_writes_only_failed_oplog
- Assertion scope: 规划项：受理后把容器置 OFFLINE，执行后台 guard，断言不调 Node、不写绑定/成功日志，只写 `success=False` 的 `add_collaborator` 日志且不含密码。 现有测试未覆盖新增协作者的后台 guard 失败。
- Coverage note: 本场景无既有断言行；C25 补齐。

### Requirement: 恢复协作者账号的瞬时密码兼容

#### Scenario: 恢复协作者账号使用瞬时随机密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_restore_accounts_password_contract
  - [X] test/container/test_deleted_containers.py::test_resurrect_container_reuses_snapshot_mount_and_restores_bindings
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c26_restore_account_password_not_persisted
- Assertion scope: `restore_accounts` 每项含非空 `password`，不等于 `{username}123`；调用方传入的 accounts 列表未被写回密码；实际恢复响应仍只交付 root 一项。 恢复快照/DB/日志不含该瞬时密码未断言；C26 补齐。

#### Scenario: Node 拒绝瞬时密码时不回退弱默认值

- Test/check:
  - [X] test/container/test_password_contracts.py::test_restore_accounts_password_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c27_restore_account_failure_no_retry_or_credentials
- Assertion scope: Node 拒绝恢复协作者密码时抛 `NodeServiceError`，已发送的 password 仍不等于 `{username}123`。 是否重试、是否返回凭据、错误输出是否含密码未断言；C27 补齐。

### Requirement: 容器密码不持久化且不可回查

#### Scenario: 一次性密码只在响应中出现

- Test/check:
  - [X] test/container/test_password_contracts.py::test_password_persistence_contract
  - [X] test/container/test_password_contracts.py::test_update_role_root_always_handover_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c28_detail_and_list_do_not_return_password
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c32_password_not_in_wire_env_labels_or_wss
- Assertion scope: 容器/用户绑定/oplog 模型无 password 列；oplog detail/error_reason 不含本次密码；路由中不存在 GET 密码回查；ROOT 交接后 DB 各列、oplog、日志文件均不含两项密码。 详情/列表响应与运行时缓存不含密码未断言；C28 补齐。C32 补创建/新增/重置 wire 只把密码放在 `root_password`/`config.password`，不放进 `config.env`/labels；WSS 帧与运行时缓存不含密码。
- Coverage note: Node 侧 Docker env/config/labels 的最终落盘仍不可由 Ctrl 隔离测试证明；C32 只对 Ctrl 发出的 wire 与可观察 WSS 帧做否定断言，不宣称 Node 侧存储已证明。

#### Scenario: 失败响应与异常脱敏

- Test/check:
  - [X] test/container/test_password_contracts.py::test_password_persistence_contract
  - [X] test/container/test_password_contracts.py::test_untrusted_reason_redaction_contract
- Assertion scope: Node 错误体含本次密码时，失败 oplog 的 detail/error_reason 不含密码；reset/add/create 的不可信 reason 被替换为稳定白名单，HTTP 错误文本不含 secret。

#### Scenario: 无密码回查入口

- Test/check:
  - [X] test/container/test_password_contracts.py::test_password_persistence_contract
  - [X] test/container/test_anvil_cleanup_contracts.py::test_anvil_c28_detail_and_list_do_not_return_password
- Assertion scope: 遍历容器路由，凡路径含 password 的路由均无 GET 方法。 未检查详情/列表/日志/审计响应是否含密码字段；C28 补齐。
