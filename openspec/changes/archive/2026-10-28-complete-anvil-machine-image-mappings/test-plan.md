# Test Plan

## backend--table-images

### Requirement: images 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/image/test_image_api.py::test_list_and_detail_image
  - [X] test/image/test_image_api.py::test_create_image_persists_entrypoint
  - [X] test/image/test_image_api.py::test_update_and_delete_image
  - [X] test/repository/test_anvil_machine_images.py::test_image_model_roundtrip_preserves_id_and_null_semantics
- Assertion scope: `test_list_and_detail_image` 断言详情读回 base_image、dockerfile_body；`test_create_image_persists_entrypoint` 断言 entrypoint 读回；`test_update_and_delete_image` 断言改名后的 name 与 status=ready。`[X]` 行核对 SQLite 往返的主键稳定、description/entrypoint/created_by_user_id 可为 NULL、status 与 valid_range 的 Python 默认落库、created_at/updated_at 非空，以及 name 非数据库唯一约束。
- Coverage note: 既有断言覆盖详情、entrypoint、改名与 status；完整列、默认值与时间戳语义见对应 `[X]` 行。

### Requirement: images 生产职责与生命周期

#### Scenario: 模板停用

- Test/check:
  - [X] test/container/test_container_image_id.py::test_delete_image_disables_and_keeps_binding
  - [X] test/container/test_container_image_id.py::test_disabled_template_hidden_from_business_reads
  - [X] test/image/test_image_api.py::test_update_and_delete_image
- Assertion scope: 删除门户把 status 置为 disabled；模板行与 container.image_id 保留；业务列表与计数过滤停用行；Can_use_image_for_container 返回 DISABLED 且可与 NOT_FOUND 区分；API 删除成功。Requirement 正文的停用语义、历史可读与新建选择过滤由这些断言覆盖。
- Coverage note: 同 Requirement 正文的普通列表三态、资源通配默认列表、详情/编辑方法门与 READY 建容器约束，见“资源通配者操作他人镜像”“仅有方法通配或缺少方法能力”“停用模板仍不能新建”场景的 `[X]` 行，本场景不重复列出。

### Requirement: images 模板名称唯一性

#### Scenario: 同名判定只看未停用

- Test/check:
  - [X] test/container/test_container_image_id.py::test_disabled_template_frees_its_name
  - [X] test/image/test_image_api.py::test_legacy_images_unique_name_index_is_relaxed
  - [X] test/repository/test_anvil_machine_images.py::test_rename_checks_active_names_and_allows_disabled_name
- Assertion scope: 停用行不参与查重，同名新建成功；两个未停用同名模板在创建时被拒；旧库 images.name 唯一索引已降为非唯一索引。`[X]` 行核对改名路径：改名撞未停用同名被拒、改名到停用同名允许、改回自身当前名称允许。

### Requirement: images 模板启停与构建记录失效

#### Scenario: 停用后可重新启用

- Test/check:
  - [X] test/container/test_container_image_id.py::test_disabled_template_still_readable_by_management_paths
  - [X] test/container/test_container_image_id.py::test_display_survives_template_being_disabled
  - [X] test/image/test_image_resource_scope.py::test_operator_full_chain_list_detail_edit_and_container
  - [X] test/repository/test_anvil_machine_images.py::test_machine_image_row_stays_readable_after_template_disabled
- Assertion scope: 停用后 get_by_id 仍可读、可编辑，status 可恢复为 READY；同一模板行保持可读；引用它的容器展示不因停用变空；operator 编辑他人镜像后 created_by_user_id 保持原创建者。`[X]` 行核对先有 machine_image 行、停用模板后仍按复合键读回同一标签与配方指纹。
- Coverage note: 既有断言覆盖模板行、容器展示与归属；machine_image 构建记录在停用后的可读性见对应 `[X]` 行。

#### Scenario: 模板更新促使机器重建

- Test/check:
  - [X] test/image/test_image_build_cache_version.py::test_template_recipe_change_and_metadata_edit_converge_on_the_same_row
  - [X] test/image/test_image_build_cache_version.py::test_platform_injection_change_changes_cache_version
  - [X] test/container/test_container_image_id.py::test_template_recipe_change_replaces_the_same_cache_row
  - [X] test/container/test_container_image_id.py::test_machine_image_repo_has_no_delete_entry
- Assertion scope: 模板配方变化后解析出新标签与新版本戳；派发确认就地更新同一 (machine_id, image_id) 行；后续相同配方命中更新后的标签；旧容器字段、绑定与授权不被删除；未改配方只改元数据时缓存继续命中；仓储没有删行换代入口。
- Coverage note: Node 按标签查本机制品并决定是否构建属跨仓外部行为；Ctrl 断言到新配方、新标签和构建段下发，未伪造 Node 的构建结果。

### Requirement: images 内置模板幂等收敛

#### Scenario: 内置模板改名收敛

- Test/check:
  - [X] test/image/test_image_api.py::test_seed_image_defaults_idempotent
  - [X] test/image/test_image_api.py::test_seed_skips_existing_name
  - [X] test/repository/test_anvil_machine_images.py::test_seed_legacy_name_converges_in_place_without_overwriting_status
- Assertion scope: 既有用例断言重复 seed 不新增行、同名已存在时不覆盖人工修改的内容。`[X]` 行构造旧名系统行，核对按 legacy_names 找回后原地改名并同步 FROM，保留 created_by_user_id 与停用状态，不插入第二行，重复运行仍只有原行，且不收敛用户自建的同名模板。
- Coverage note: 既有断言覆盖同名跳过与幂等；旧名就地收敛、FROM 同步与停用状态保留见对应 `[X]` 行。

### Requirement: 平台注入改变构建缓存版本

#### Scenario: 注入变化后派发

- Test/check:
  - [X] test/image/test_image_build_cache_version.py::test_platform_injection_change_changes_cache_version
  - [X] test/image/test_image_build_cache_version.py::test_same_second_recipe_change_never_reuses_the_old_tag
  - [X] test/image/test_image_build_cache_version.py::test_restore_sends_the_recipe_it_actually_dispatched
  - [X] test/repository/test_anvil_machine_images.py::test_platform_injection_change_keeps_ownership_grants_and_old_container
- Assertion scope: 仅平台注入变化时，下发 Dockerfile 文本包含新注入，标签换代且版本戳递增；相同新内容重复派发稳定命中；同秒修改仍产生不同标签；恢复发送的是实际派发配方。`[X]` 行核对注入变化后 created_by_user_id、user_images 授权、旧容器 image_id/绑定/构建留痕不变。
- Coverage note: 既有断言覆盖标签、文本、同秒与恢复配方；所有权、授权和旧容器不变见对应 `[X]` 行。

### Requirement: 镜像资源通配与方法权限分别生效

#### Scenario: 资源通配者操作他人镜像

- Test/check:
  - [X] test/image/test_image_resource_scope.py::test_default_list_scope_reflects_resource_wildcard
  - [X] test/image/test_image_resource_scope.py::test_operator_full_chain_list_detail_edit_and_container
  - [X] test/image/test_image_resource_scope.py::test_direct_manage_with_entity_wildcard_keeps_full_resource_range
  - [X] test/container/test_container_image_id.py::test_create_container_api_ignores_client_supplied_image
- Assertion scope: 资源通配者的默认列表覆盖全部非停用模板；可读取他人 private 模板详情、编辑并以 READY 模板创建容器；编辑后 created_by_user_id 仍为原创建者；创建门户采用服务端解析的 image_id 与标签，不采信客户端镜像名。Requirement 正文的默认列表范围、详情/编辑门与 READY 建容器由这些断言覆盖。

#### Scenario: 仅有方法通配或缺少方法能力

- Test/check:
  - [X] test/image/test_image_resource_scope.py::test_entity_wildcard_only_has_no_image_resource_range
  - [X] test/image/test_image_resource_scope.py::test_resource_wildcard_without_edit_cannot_edit_or_read_detail
  - [X] test/image/test_image_resource_scope.py::test_edit_and_visibility_entrances_need_resource_wildcard
  - [X] test/image/test_image_resource_scope.py::test_detail_requires_image_edit_method_and_resource_visibility
  - [X] test/image/test_image_resource_scope.py::test_my_permissions_exposes_real_image_resource_wildcard
- Assertion scope: 仅实体通配不扩大镜像资源范围；仅有 bypass_resource 与 view 时列表可见但详情/编辑被方法门拒绝；资源范围不能绕过 image:edit；me/permissions 区分真实资源通配与仅方法通配。

#### Scenario: 停用模板仍不能新建

- Test/check:
  - [X] test/image/test_image_resource_scope.py::test_container_image_usability_follows_scope_and_ready_gate
  - [X] test/image/test_image_resource_scope.py::test_operator_full_chain_list_detail_edit_and_container
- Assertion scope: operator、manager、wildcard 与 owner 对 draft/disabled 模板均得到 DISABLED；创建 API 返回 400 image_not_ready；不存在模板返回 NOT_FOUND；只有 READY 模板能通过创建可用性判断。

### Requirement: 仅看我的严格按创建者过滤

#### Scenario: 通配者勾选仅看我的

- Test/check:
  - [X] test/image/test_image_resource_scope.py::test_mine_only_is_strictly_owned_and_wildcard_does_not_leak
  - [X] test/image/test_image_resource_scope.py::test_explicit_mine_filter_precedes_unrestricted_scope
  - [X] test/image/test_image_api.py::test_mine_only_list_uses_created_by_not_user_image_binding
- Assertion scope: mine_only 只返回 created_by_user_id 等于当前用户的模板；operator、manager、wildcard、entity_only 无自有模板时结果为空且 total_number 为 0；显式 mine 过滤优先于 unrestricted；user_images 授权行不会混入“仅看我的”。

#### Scenario: 创建者不在可见名单

- Test/check:
  - [X] test/image/test_image_resource_scope.py::test_mine_only_is_strictly_owned_and_wildcard_does_not_leak
  - [X] test/image/test_image_api.py::test_mine_only_list_uses_created_by_not_user_image_binding
  - [X] test/image/test_image_api.py::test_point_check_agrees_with_list_predicate
  - [X] test/image/test_image_resource_scope.py::test_operator_full_chain_list_detail_edit_and_container
- Assertion scope: 创建者被移出自己 CUSTOM 模板的授权名单后，该模板仍留在其 mine_only 结果；被授权者不会因授权成为“我的”；列表 SQL 与点判定对同一组样本结论一致；operator 编辑他人镜像后 created_by_user_id 仍为原创建者，授权或编辑都不改变所有权。

### Requirement: images entrypoint 说明符合构建语义

#### Scenario: 模型与 schema 说明一致

- Test/check:
  - [X] test/test_entrypoint_docs.py::test_entrypoint_docs_describe_build_stage_at_all_four_locations
- Assertion scope: models/image.py 与 schemas/image.py 不再包含“不参与构建”“不进 Dockerfile”“默认值只写在 Node”“utils/Container.py”；models 描述构建段、DockerfileParts、PLATFORM_DEFAULT_ENTRYPOINT，schema 描述 render_final_dockerfile 与 ENTRYPOINT。该场景是文档约束，断言不声称运行时行为变化。

## backend--table-machine-image

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

## backend--table-machines

### Requirement: machines 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/machine/test_machine_tasks_crud.py::test_get_detail_information_success
  - [X] test/machine/test_machine_repository_integration.py::test_update_machine_with_real_repository
  - [X] test/repository/test_anvil_machine_images.py::test_machine_model_roundtrip_preserves_columns_and_null_semantics
- Assertion scope: 既有用例按 id 读回详情与更新后的 machine_name，断言 status、containers、port 的读取口径。`[X]` 行核对 SQLite 往返的主键稳定、machine_name/machine_ip 唯一且非空、node_uid/node_cert_fingerprint 唯一且可空、port 与各类上限/GPU JSON 可空、machine_status/is_maintenance Python 默认落库，并核对数据附录列名与类型。
- Coverage note: 既有断言覆盖详情与仓库读取的部分字段；完整表级约束与空值语义见对应 `[X]` 行。

### Requirement: machines 生产职责与生命周期

#### Scenario: 维护或离线窗口

- Test/check:
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_offline_window_adds_deferral_on_recovery
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_maintenance_window_opens_and_closes
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_deferral_applies_to_all_records_of_machine
  - [X] test/machine/test_machine_tasks_crud.py::test_register_machine_persists_identity_hardware_and_limits
  - [X] test/machine/test_machine_node_endpoint.py::test_register_blank_port_falls_back_and_stores_null
  - [X] test/machine/test_machine_tasks_crud.py::TestGpuAllowance::test_allow_list_length_wins
  - [X] test/machine/test_machine_tasks_status.py::test_apply_sys_snapshot_drift_updates_db_and_trims_limits
  - [X] test/machine/test_machine_tasks_status.py::test_apply_sys_snapshot_gpu_enum_updates_gpu_list_not_allow
  - [X] test/machine/test_cleanup_deferral_window.py::TestLastSeenHeartbeat::test_snapshot_batch_updates_last_seen
  - [X] test/machine/test_node_link.py::test_run_machine_link_marks_online_on_connect_offline_on_close
- Assertion scope: 注册写入 node_uid、证书指纹、硬件事实和资源上限；port 留空存 NULL；gpu_allow_list 决定许可上限；WSS 快照把 gpu_list 作为事实更新、允许列表保持人工维护，并写 last_seen_at；链路连接成功写 online、断开写 offline；离线/维护开窗，恢复时给该机器全部 SSH 记录累加 deferral。Requirement 正文的 Node 注册固定 uid/证书、端口空值、GPU 事实/许可与 WSS 更新由这些断言覆盖。

### Requirement: machines 共享内存上限为机器可配置限额

#### Scenario: 超过 8GB 但在内存上限内可保存

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_accepts_shared_above_8_within_memory
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_saves_shared_above_8_within_memory
- Assertion scope: 32GB 内存的机器通过服务层和真实 API 把 max_shared_gb 从 8GB 更新为 16GB 均成功并落库，不再有固定 8GB 上限。

#### Scenario: 只下调内存上限到既有共享之下被拒

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_memory_lowered_below_existing_shared
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_memory_lowered_below_existing_shared
- Assertion scope: 既有 shared=16/mem=32，请求只把 mem 改为 8 并夹带改名时，服务层与 API 均以 update_failed/422 拒绝；两个上限与机器名都不落库。

#### Scenario: 内存下调到等于既有共享上限可保存

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_accepts_memory_lowered_to_existing_shared
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_accepts_memory_lowered_to_shared
- Assertion scope: shared=16/mem=32，请求把 mem 改为 16 成功；shared 保持 16，mem 落库为 16。

#### Scenario: 同请求把共享与内存设为相等可保存

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_accepts_equal_shared_and_memory_in_one_request
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_accepts_equal_shared_and_memory
- Assertion scope: 同一请求把 max_shared_gb 与 max_memory_gb 都设为 8 时，服务层与 API 均成功，两个字段都落库为 8。

#### Scenario: 共享上限超过有效内存上限被拒

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_max_shared_greater_than_target_memory
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_shared_above_current_memory
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_shared_above_memory
- Assertion scope: 组合后的有效 shared 大于有效 mem 时，服务层与 API 均以 update_failed 拒绝且不落库；覆盖本次请求值和当前记录值两种来源。

#### Scenario: 负值、非整数与非整小数被拒

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_non_integer_or_negative_shared_size
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_fractional_shared_size
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_invalid_shared_input
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_accepts_integral_string_and_float_shared_size
- Assertion scope: 服务层拒绝负数、不可解析值和 3.5，返回 update_failed，3.5 不被截断为 3；请求模型层对同一组非法值返回 400 与 invalid_payload；可解析的整数字符串和整值浮点仍兼容。

#### Scenario: 显式 null 不能绕过组合约束

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_null_shared_with_memory_lowered
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_rejects_null_memory_with_shared_raised
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_null_shared_with_memory_lowered
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_null_memory_with_shared_raised
- Assertion scope: 显式 null 不写入字段，落库后另一侧仍是原值；两种组合都因有效 shared 大于有效 mem 被 update_failed/422 拒绝，同请求其它字段也不变。

#### Scenario: 没有内存上限的旧记录保持空值语义

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_update_machine_skips_comparison_when_memory_limit_is_null
  - [X] test/repository/test_anvil_machine_images.py::test_null_shared_limit_with_known_memory_skips_comparison
- Assertion scope: 既有用例覆盖当前内存上限为 NULL 时设置 shared=16 成功、显式传 null 不写入且内存仍为 NULL。`[X]` 行核对当前共享上限为 NULL 而内存已知的对称分支：请求只设置 max_memory_gb，断言 NULL 共享视为未知、跳过比较、内存值可保存，且不把 NULL 顶替成数值或发明全局默认值。
- Coverage note: 内存 NULL 分支已有断言；共享 NULL 的对称分支见对应 `[X]` 行。

#### Scenario: 错误边界分层

- Test/check:
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_invalid_shared_input
  - [X] test/machine/test_machine_api_crud.py::test_update_machine_api_rejects_shared_above_memory
  - [X] test/container/test_container_shared_memory_limit.py::test_create_params_sequence_enforces_machine_limit
- Assertion scope: 请求模型层的非整小数返回 400 与 invalid_payload；更新服务层的组合越界返回 422 与 update_failed；容器创建边界的共享越界返回 invalid_config。三者是不同边界，未互相替代或合并错误原因。

### Requirement: machines Node 端点解析

#### Scenario: 默认端口改动对已登记机器生效

- Test/check:
  - [X] test/machine/test_machine_node_endpoint.py::test_default_is_read_at_call_time_not_frozen
  - [X] test/machine/test_machine_node_endpoint.py::test_register_blank_port_falls_back_and_stores_null
  - [X] test/machine/test_machine_node_endpoint.py::test_empty_port_falls_back_to_global_default
  - [X] test/machine/test_machine_node_endpoint.py::test_resolve_endpoint_pairs_host_and_port
  - [X] test/machine/test_machine_node_endpoint.py::test_bare_host_drops_port_segment
  - [X] test/machine/test_machine_node_endpoint.py::test_https_action_url_uses_machine_port
  - [X] test/machine/test_machine_node_endpoint.py::test_link_url_uses_machine_port
  - [X] test/machine/test_machine_node_endpoint.py::test_peer_cert_probe_uses_machine_port
- Assertion scope: 全局默认端口在调用时现读，导入期不冻结；已登记机器 port 留空时记录保持 NULL，端点解析使用改动后的全局默认；不会把旧默认值固化进机器记录；裸主机与端口配对，HTTPS 动作、WSS 拨号与 TOFU 取证书三条出站路径分别使用机器端口。

### Requirement: machines 端点登记与链路重拨

#### Scenario: 端点变更不改信任

- Test/check:
  - [X] test/machine/test_machine_tasks_crud.py::test_update_machine_ip_change_is_pure_registration
  - [X] test/machine/test_machine_tasks_crud.py::test_update_machine_ip_change_succeeds_while_new_address_unreachable
  - [X] test/machine/test_node_link.py::test_sync_links_restarts_link_when_host_changes
  - [X] test/machine/test_node_link.py::test_sync_links_restarts_link_when_port_changes
  - [X] test/machine/test_node_link.py::test_sync_links_restarts_link_when_uid_changes
  - [X] test/machine/test_machine_tasks_crud.py::test_update_machine_rejects_address_carrying_port
  - [X] test/machine/test_machine_node_endpoint.py::test_register_rejects_address_carrying_port
  - [X] test/machine/test_machine_node_endpoint.py::test_pin_written_and_read_under_the_same_bare_host_key
  - [X] test/machine/test_machine_node_endpoint.py::test_pin_survives_port_change
  - [X] test/repository/test_anvil_machine_images.py::test_endpoint_update_keeps_pin_fingerprint_without_probe
- Assertion scope: 修改 machine_ip 或 port 只更新登记字段，不发出站取证；新地址不可达仍可登记；链路按新主机/端口重建，uid 变化也作为链路目标变化处理；machine_ip 拒绝 host:port 写法，pin 文件按裸主机命名且换端口不影响既有 pin。`[X]` 行核对证书指纹与 pin 文件字节不变、没有 TLS 取证或 pin 重写。
- Coverage note: 既有用例分别覆盖纯登记与链路重拨；证书指纹和 pin 文件内容不变见对应 `[X]` 行。规格要求 machine_ip 只承载纯 IPv4，当前实现只拒绝冒号写法；本映射不声称 IPv4 字面校验已覆盖，该规格差异交父任务按 Global 登记处理。

### Requirement: machines 信任重钉与身份处理

#### Scenario: 重钉失败不动旧信任

- Test/check:
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_unreachable_leaves_everything_intact
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_writes_op_log_on_failure
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_writes_op_log_on_success
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_keeps_uid_when_certificate_only_changed
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_reissues_uid_when_peer_lost_identity
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_adopts_reported_uid_when_db_has_none
  - [X] test/machine/test_machine_tasks_crud.py::test_renew_machine_trust_flags_uid_mismatch_without_overwriting
  - [X] test/repository/test_anvil_machine_images.py::test_renew_profile_failure_keeps_pin_and_credentials
- Assertion scope: 取对端证书失败时返回 machine_unreachable，node_uid、证书指纹与 pin 集合保持原值，并写失败操作日志；成功与失败均写操作日志；对端身份牌完好时保留 uid，丢失时重发，库中无 uid 时采纳对端自报值，两侧都有且不一致时保持库值并报告 mismatch。`[X]` 行核对 enrollment profile 取证失败同样不改动 pin 与全部凭证字段，且写失败日志。
- Coverage note: 既有用例覆盖证书取证失败；enrollment profile 失败分支见对应 `[X]` 行。pin 文件写入失败不在当前规格的已定义分支内，本映射不新增该承诺；该未定义策略交父任务按 Global 登记处理。

### Requirement: machines 信任重钉持久化失败边界

#### Scenario: 数据库持久化失败不承诺 pin 回滚

- Test/check:
  - [X] test/repository/test_anvil_machine_images.py::test_renew_persist_failure_keeps_pin_file_and_returns_persist_failed
- Assertion scope: `[X]` 行先让 pin 文件成功写入，再以 SQLite `BEFORE UPDATE ON machines` 触发器使数据库更新失败；断言返回 persist_failed、写失败日志、数据库指纹保持旧值、pin 文件仍保留新证书，并且不声称文件与数据库为原子回滚。
- Coverage note: 该场景见对应 `[X]` 行；失败注入使用数据库触发器，不替换被测仓储或服务的成功路径。

### Requirement: machines 不可用窗口与期限顺延

#### Scenario: 窗口关闭后一次结算

- Test/check:
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_offline_window_adds_deferral_on_recovery
  - [X] test/machine/test_cleanup_deferral_window.py::TestDeferralAppliesToOtherDeadlines::test_window_close_credits_freeze_state
  - [X] test/machine/test_cleanup_deferral_window.py::TestDeferralAppliesToOtherDeadlines::test_window_close_credits_pending_deleted_snapshot
  - [X] test/repository/test_anvil_machine_images.py::test_window_close_failure_keeps_window_open
- Assertion scope: 恢复为 online 且非维护时，SSH 登录、磁盘冻结与删除挂载保留记录在同一事务内各累加整段故障时长，随后清空 unavailable_since；已有用例覆盖三类期限。`[X]` 行先构造真实已存在的 `container_ssh_login_records` 行，并把 unavailable_since 设为过去使结算 delta>0；恢复时用 `BEFORE UPDATE OF deferral_seconds ON container_ssh_login_records` 触发器命中实际 UPDATE 后失败，断言恢复调用抛出 DB 错误、事务回滚、机器状态与 unavailable_since 未部分更新。
- Coverage note: 既有用例覆盖三类期限的同事务累加；同场景 `test_offline_window_adds_deferral_on_recovery` 是同一 SSH 记录与 delta 路径的无触发器正常控制组，证明触发组不是无条件失败。事务失败时窗口不关闭见对应 `[X]` 行。

#### Scenario: 窗口未关时倒计时照延

- Test/check:
  - [X] test/machine/test_cleanup_deferral_window.py::TestCleanupInfoDeferral::test_open_window_freezes_the_countdown
  - [X] test/machine/test_cleanup_deferral_window.py::TestCleanupInfoDeferral::test_open_window_adds_on_top_of_settled_deferral
  - [X] test/machine/test_cleanup_deferral_window.py::TestCleanupInfoDeferral::test_detail_read_path_picks_up_the_open_window
- Assertion scope: 窗口未关闭时读侧同时计入已结算的 deferral_seconds 与 unavailable_since 起的进行中窗口；两者叠加而非二选一；详情读路径与纯函数口径一致。

### Requirement: machines 采集心跳与启动窗口回填

#### Scenario: 停机期间的进窗被兜住

- Test/check:
  - [X] test/machine/test_cleanup_deferral_window.py::TestLastSeenHeartbeat::test_snapshot_batch_updates_last_seen
  - [X] test/machine/test_cleanup_deferral_window.py::TestLastSeenHeartbeat::test_collect_error_batch_still_counts_as_heard
  - [X] test/machine/test_cleanup_deferral_window.py::TestLastSeenHeartbeat::test_throttle_writes_once_within_window
  - [X] test/machine/test_cleanup_deferral_window.py::TestSeedUnavailableWindows::test_seeds_window_from_last_seen
  - [X] test/machine/test_cleanup_deferral_window.py::TestSeedUnavailableWindows::test_skips_machine_without_last_seen
  - [X] test/machine/test_cleanup_deferral_window.py::TestSeedUnavailableWindows::test_does_not_touch_open_window
  - [X] test/machine/test_cleanup_deferral_window.py::TestSeedUnavailableWindows::test_is_idempotent
  - [X] test/machine/test_node_link.py::test_run_links_forever_seeds_windows_before_first_dial
  - [X] test/repository/test_anvil_machine_images.py::test_last_seen_write_failure_does_not_block_snapshot_apply
- Assertion scope: 成功应用快照批（含 collect_error 批）会更新 last_seen_at；启动扫描只对窗口未开且有 last_seen_at 的机器回填起点，已有窗口不改写、无心跳不凭空开窗、重复扫描幂等，并且先于链路首次拨号。`[X]` 行以 SQLite `BEFORE UPDATE OF last_seen_at ON machines` 触发器让心跳写入失败，断言只告警且本批快照仍落库。
- Coverage note: 既有用例覆盖心跳更新、播种边界与拨号顺序；last_seen_at 写失败不影响本批快照见对应 `[X]` 行。

### Requirement: machines 出站链路集合对齐

#### Scenario: 机器集合变化保持其他存活链路

- Test/check:
  - [X] test/machine/test_node_link.py::test_load_link_targets_includes_offline_machines
  - [X] test/machine/test_node_link.py::test_sync_links_starts_link_for_new_machine
  - [X] test/machine/test_node_link.py::test_sync_links_keeps_live_links_untouched
  - [X] test/machine/test_node_link.py::test_sync_links_cancels_link_for_removed_machine
  - [X] test/machine/test_node_link.py::test_sync_links_restarts_dead_link
  - [X] test/machine/test_node_link.py::test_run_machine_link_marks_online_on_connect_offline_on_close
  - [X] test/machine/test_node_link.py::test_undialable_machine_without_uid_is_marked_offline
  - [X] test/repository/test_anvil_machine_images.py::test_link_backoff_is_per_machine_and_resets_on_connect
- Assertion scope: 链路清单包含 OFFLINE 行；新增机器起链路、存活链路不重建、删除机器取消链路、死亡链路重起；连接成功写 ONLINE，断开写 OFFLINE，不做二次探活；不在拨号清单内的机器被置为 OFFLINE。`[X]` 行核对单机连续失败独立退避、其他机器链路不受影响，连接成功后退避恢复初始值。
- Coverage note: 既有用例覆盖集合对齐与连接状态；单机独立退避及成功后恢复见对应 `[X]` 行。

### Requirement: machines 动作任务管辖范围

#### Scenario: 范畴外不动作也不留痕

- Test/check:
  - [X] test/machine/test_machine_scope.py::test_online_without_maintenance_is_in_scope
  - [X] test/machine/test_machine_scope.py::test_offline_machine_is_out_of_scope
  - [X] test/machine/test_machine_scope.py::test_maintenance_machine_is_out_of_scope_while_online
  - [X] test/machine/test_machine_scope.py::test_missing_machine_is_out_of_scope
  - [X] test/machine/test_machine_scope.py::test_none_machine_id_is_out_of_scope
  - [X] test/container/test_container_cleanup_task.py::test_out_of_scope_produces_no_records_across_rounds
  - [X] test/container/test_container_cleanup_task.py::test_maintenance_machine_is_out_of_scope
  - [X] test/container/test_container_cleanup_task.py::test_in_scope_failure_is_still_audited
  - [X] test/container/test_container_mount_cleanup_task.py::TestMountCleanupTask::test_skips_when_machine_unreachable
  - [X] test/container/test_container_mount_cleanup_task.py::TestMountCleanupTask::test_skips_when_machine_in_maintenance
  - [X] test/container/test_container_disk_check_task.py::TestEvaluateLimitsMachineGate::test_offline_machine_skips_evaluate
  - [X] test/container/test_container_disk_check_task.py::TestEvaluateLimitsMachineGate::test_maintenance_machine_skips_evaluate
- Assertion scope: 共享判据是“可达且非维护”；OFFLINE、维护中、记录缺失与 machine_id=None 均为范畴外且不抛异常；容器清理不动作且 op-log/常规日志零增长；挂载清理不发请求、不标记 cleaned；磁盘检测不触发 handler、不写冻结状态且不留日志。范畴内失败仍照常审计的对照断言也保留。

### Requirement: 机器详情保留配置端口

#### Scenario: 自定义端口可读取

- Test/check:
  - [X] test/machine/test_machine_tasks_crud.py::test_get_detail_information_returns_configured_port
  - [X] test/machine/test_machine_api_crud.py::test_get_machine_detail_returns_configured_port
- Assertion scope: 服务层详情与真实 API 响应都保留 port=6789；响应模型没有过滤或覆盖为全局默认。

#### Scenario: 空配置仍使用平台默认

- Test/check:
  - [X] test/machine/test_machine_tasks_crud.py::test_get_detail_information_success
  - [X] test/machine/test_machine_api_crud.py::test_get_machine_detail_keeps_null_port_without_default_filling
  - [X] test/machine/test_machine_node_endpoint.py::test_register_blank_port_falls_back_and_stores_null
- Assertion scope: 机器记录 port 为空时详情响应保留 null；数据库记录仍为 NULL；出站端点解析按当前全局默认端口执行，不把默认值写回机器记录。
