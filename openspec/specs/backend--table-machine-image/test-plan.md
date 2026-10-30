# backend--table-machine-image Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: machine_image 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_machine_image_repo.py::test_composite_key_scopes_rows_per_machine_and_template
  - [X] test/repository/test_machine_image_repo.py::test_schema_upgrade_adds_recipe_fingerprint_column
  - [X] test/repository/test_anvil_machine_images.py::test_machine_image_model_roundtrip_enforces_composite_identity
- Assertion scope: 既有用例按 (machine_id, image_id) 读写并验证不同机器/模板互不串行；旧库升级补 nullable recipe_fingerprint 且存量行为 NULL。`[X]` 行核对 SQLite 往返的主键稳定、machine_id/image_id 外键与 (machine_id, image_id) 唯一约束、image_tag 非空、recipe_fingerprint 可 NULL、created_at 非空，并按主键读回同一条记录。
- Coverage note: 复合键读取与补列已有断言；完整列语义与表级唯一约束见对应 `[X]` 行。

### Requirement: machine_image 生产职责与生命周期

#### Scenario: 模板构建内容变化

- Test/check:
  - [X] test/image/test_image_build_cache_version.py::test_template_recipe_change_and_metadata_edit_converge_on_the_same_row
  - [X] test/container/test_container_image_id.py::test_template_recipe_change_replaces_the_same_cache_row
  - [X] test/container/test_container_entrypoint.py::test_template_entrypoint_roundtrip
  - [X] test/repository/test_anvil_machine_images.py::test_base_image_change_changes_cached_recipe
  - [X] test/repository/test_anvil_machine_images.py::test_entrypoint_change_changes_cached_recipe
- Assertion scope: 模板构建内容变化后产生新配方与新标签，同一配对行就地更换；新版本一经分配可稳定复用；旧容器、授权和机器关联不被删除或重建。既有用例覆盖 entrypoint 的存储、读取与清除；`test_template_recipe_change_and_metadata_edit_converge_on_the_same_row` 覆盖元数据编辑仍命中；`[X]` 行分别核对同一机器上 base_image 与 entrypoint 变化改变配方指纹和缓存标签。
- Coverage note: Node 的 images.get(tag) 与真实构建成功属跨仓外部行为；Ctrl 断言到配方/标签下发与缓存行语义。base_image 与 entrypoint 的机器上下文配方分支见两条 `[X]` 行。

### Requirement: machine_image 派发记录与构建缓存

#### Scenario: 构建失败也留观测

- Test/check:
  - [X] test/image/test_image_build_cache_version.py::test_failed_build_keeps_the_dispatch_row
  - [X] test/container/test_container_image_id.py::test_machine_image_is_observational_only
  - [X] test/container/test_container_image_id.py::test_machine_image_not_written_without_build_segment
  - [X] test/container/test_container_image_id.py::test_resurrect_sends_image_build_and_keeps_image_id
  - [X] test/repository/test_anvil_machine_images.py::test_node_rejection_keeps_reserved_row_and_next_dispatch_still_sends_build
- Assertion scope: 既有用例断言版本选择会留下记录、记录存在不导致跳过构建段、没有构建段则不写记录、恢复会携带构建段并保留 image_id。`[X]` 行让 Node 拒绝创建后断言行仍保留、下一次相同配方仍下发构建段，并明确记录存在不等于 Node 已受理或构建成功。
- Coverage note: 后台构建失败发生在 Node 内部，Ctrl 不可观测；Node 未受理这一可观测失败分支见对应 `[X]` 行。

#### Scenario: 派发回写前连续修改

- Test/check:
  - [X] test/image/test_image_version_allocation.py::test_different_recipes_resolved_before_dispatch_have_distinct_tags
  - [X] test/repository/test_machine_image_repo.py::test_record_dispatch_never_moves_the_version_backwards
  - [X] test/image/test_image_build_cache_version.py::test_same_second_recipe_change_never_reuses_the_old_tag
- Assertion scope: 首个配方已解析但未回写时解析不同配方，两者得到不同标签；重复解析第二个配方返回同一版本；迟到的旧派发确认不能把缓存回退；同秒不同配方仍严格递增版本戳。

#### Scenario: 独立会话交错预留

- Test/check:
  - [X] test/repository/test_machine_image_interleaving.py::test_stale_session_cannot_relabel_another_sessions_reserved_tag
  - [X] test/image/test_image_reservation_conflict.py::test_conflicting_reservation_does_not_return_other_recipe_tag
  - [X] test/repository/test_machine_image_repo.py::test_record_dispatch_refuses_to_relabel_the_same_tag
- Assertion scope: 较早会话不能覆盖另一会话刚占用的标签；解析器遇到竞争写入时重试或安全失败，不交付与本次配方不一致的标签；同一标签不能替换配方指纹。

### Requirement: machine_image 复合键与读写入口

#### Scenario: 有行时更新陈旧版本

- Test/check:
  - [X] test/repository/test_machine_image_repo.py::test_record_dispatch_replaces_values_in_place_for_newer_version
  - [X] test/container/test_container_image_id.py::test_template_recipe_change_replaces_the_same_cache_row
  - [X] test/container/test_container_image_id.py::test_machine_image_repo_has_no_delete_entry
- Assertion scope: 为已有配对记录写入更新版本时，行 id 与复合键不变，标签、版本戳和配方指纹来自同一次解析；不新增行，标签和版本戳不在写入点重新生成；仓储没有按标签删行或“删整行才能换代”的入口。

#### Scenario: 有行即返回不改写

- Test/check:
  - [X] test/repository/test_machine_image_repo.py::test_record_dispatch_keeps_identity_and_row_count
  - [X] test/container/test_container_image_id.py::test_repeated_dispatch_of_the_same_recipe_keeps_the_row
  - [X] test/container/test_container_image_id.py::test_cache_hit_reuses_the_stored_tag_verbatim
  - [X] test/container/test_container_image_id.py::test_stale_cache_row_is_not_reused
- Assertion scope: 相同值重复写入不增行、不改值；缓存命中直接返回行内标签与版本戳；重复解析或重复回写不生成新版本；陈旧指纹不进入复用分支。

### Requirement: machine_image 缓存新鲜度与失败回退

#### Scenario: 陈旧行退回现造

- Test/check:
  - [X] test/image/test_image_build_cache_version.py::test_legacy_row_without_fingerprint_converges_once
  - [X] test/container/test_container_image_id.py::test_stale_cache_row_is_not_reused
  - [X] test/image/test_image_build_cache_version.py::test_snapshot_recipe_is_not_mistaken_for_the_template_cache
  - [X] test/image/test_image_build_cache_version.py::test_resolve_fails_safe_when_the_cache_is_unreadable
  - [X] test/repository/test_anvil_machine_images.py::test_reservation_write_failure_prevents_dispatch_without_cache_row
  - [X] test/repository/test_anvil_machine_images.py::test_same_value_confirmation_is_idempotent_noop
- Assertion scope: 无指纹或指纹不符的历史行不复用旧标签；就地补齐指纹后同一配方恢复命中；快照配方不冒用当前模板缓存；缓存读取异常直接抛出，不把旧标签和新配方拼接。正常派发确认使用与预留相同的 tag/version/fingerprint；`record_dispatch` 的 CAS 以 `created_at < created_at` 判断，同值不命中任何行，因此同值确认是幂等 no-op。`[X]` 行用 `BEFORE INSERT ON machine_image` 触发器制造预留写入失败，断言解析失败、Node 不被调用且无缓存行；另一条 `[X]` 行核对预留成功后重复同值确认不增行、不改标签/版本戳/指纹，后续解析仍返回同一预留版本。规格未定义同值确认失败，本计划不构造不会命中的 `BEFORE UPDATE` 触发器。
- Coverage note: 预留失败是可触发的记录失败边界，覆盖“无法可靠记录派发时不宣称缓存已更新”；同值确认是既有 CAS 下的幂等 no-op，不是可触发的 DB 失败。既有用例不把“记录存在”当作 Node 构建成功凭据。

#### Scenario: 同秒内连续更新

- Test/check:
  - [X] test/image/test_image_build_cache_version.py::test_same_second_recipe_change_never_reuses_the_old_tag
  - [X] test/container/test_container_image_id.py::test_same_second_recipe_change_still_supersedes_the_tag
- Assertion scope: 模板或平台注入在同一秒内连续修改并派发时，新版本戳严格晚于既有版本至少一秒；不同最终配方得到不同标签，不因秒级时间戳相同命中旧镜像。

#### Scenario: 未修改配方重复解析

- Test/check:
  - [X] test/image/test_image_build_cache_version.py::test_platform_injection_change_changes_cache_version
  - [X] test/container/test_container_image_id.py::test_metadata_only_edit_keeps_the_cache_hit
  - [X] test/container/test_container_image_id.py::test_repeated_dispatch_of_the_same_recipe_keeps_the_row
  - [X] test/image/test_image_build_cache_version.py::test_read_only_resolution_never_writes_the_cache
- Assertion scope: 配方未改变且该机器已有有效版本时返回同一标签与版本戳；改名/改描述不换代；重复派发只保留一行；只读解析不写缓存。

### Requirement: 缓存换代不破坏旧运行制品

#### Scenario: 新旧容器并存

- Test/check:
  - [X] test/image/test_image_build_cache_version.py::test_template_recipe_change_and_metadata_edit_converge_on_the_same_row
  - [X] test/container/test_container_image_id.py::test_template_recipe_change_replaces_the_same_cache_row
  - [X] test/container/test_container_image_id.py::test_display_survives_template_being_disabled
  - [X] test/image/test_image_build_cache_version.py::test_restore_sends_the_recipe_it_actually_dispatched
  - [X] test/image/test_image_build_cache_version.py::test_snapshot_recipe_is_not_mistaken_for_the_template_cache
- Assertion scope: 模板换代后新建容器使用新标签；旧容器的 machine_id、image_id、构建留痕、容器绑定与用户授权保持有效；模板停用后旧容器展示仍可读；恢复历史配方时使用实际派发配方对应的标签；快照配方不会被误记为当前模板缓存；没有迁移或覆盖旧运行制品记录。
- Coverage note: 真实 Docker 制品不删除属 Node 侧；Ctrl 断言旧引用与留痕不被迁移、覆盖或解绑。
