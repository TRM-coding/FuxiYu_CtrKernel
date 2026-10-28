# backend--table-images Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

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
