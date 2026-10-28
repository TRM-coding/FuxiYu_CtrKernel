# Tasks

## 1. backend--table-auth-group-entities

- [x] 1.1 实现并验证 `test_auth_group_entity_pk_read_returns_stable_code`：覆盖 `auth_group_entities 持久化结构 / 读取有效记录` 的真实写入读回、稳定 code、重复复合主键、NULL 与外键行为；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_auth_group_entity_pk_read_returns_stable_code -q`。
- [x] 1.2 实现并验证 `test_auth_group_entity_rows_cascade_on_group_delete`：覆盖 `auth_group_entities 持久化结构 / 读取有效记录` 的 `ON DELETE CASCADE` 且不影响其它组；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_auth_group_entity_rows_cascade_on_group_delete -q`。
- [x] 1.3 实现并验证 `test_replace_group_entities_returns_catalog_order_not_request_order`：覆盖 `auth_group_entities 生产职责与生命周期 / 替换权限点` 的目录顺序而非请求/字母顺序；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_replace_group_entities_returns_catalog_order_not_request_order -q`。
- [x] 1.4 实现并验证 `test_group_entity_rows_store_codes_not_matrix_ordinals`：覆盖 `auth_group_entities 生产职责与生命周期 / 替换权限点` 的落库 code 不是矩阵序数；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_group_entity_rows_store_codes_not_matrix_ordinals -q`。
- [x] 1.5 实现并验证 `test_clearing_operator_group_keeps_locked_entities`：覆盖 `自定义权限组允许清空实体 / 清空自身唯一管理组` 的 operator 锁定实体保留；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_clearing_operator_group_keeps_locked_entities -q`。

## 2. backend--table-auth-groups

- [x] 2.1 实现并验证 `test_auth_group_pk_read_preserves_identity_and_nulls`：覆盖 `auth_groups 持久化结构 / 读取有效记录` 的主键读回、可空 description、自增 id 与非空 name；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_auth_group_pk_read_preserves_identity_and_nulls -q`。
- [x] 2.2 实现并验证 `test_auth_group_name_unique_constraint_blocks_second_row`：覆盖 `auth_groups 生产职责与生命周期 / 重复组名` 的数据库唯一约束、rollback 后行数为 1；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_auth_group_name_unique_constraint_blocks_second_row -q`。
- [x] 2.3 实现并验证 `test_seed_rbac_defaults_is_idempotent`：覆盖 `auth_groups 生产职责与生命周期 / 重复组名` 的默认组幂等与 id 稳定、绑定不增生；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_seed_rbac_defaults_is_idempotent -q`。
- [x] 2.4 实现并验证 `test_replacing_group_entities_keeps_user_bindings_intact`：覆盖 `auth_groups 生产职责与生命周期 / 重复组名` 的实体关联与用户绑定分表独立；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_replacing_group_entities_keeps_user_bindings_intact -q`。

## 3. backend--table-user-groups

- [x] 3.1 实现并验证 `test_user_group_composite_pk_read`：覆盖 `user_groups 持久化结构 / 读取有效记录` 的复合主键读回、幂等、重复主键、NULL 与外键行为；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_user_group_composite_pk_read -q`。
- [x] 3.2 实现并验证 `test_user_group_rows_cascade_on_user_and_group_delete`：覆盖 `user_groups 持久化结构 / 读取有效记录` 的用户/组双向级联且不影响其它配对；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_user_group_rows_cascade_on_user_and_group_delete -q`。
- [x] 3.3 实现并验证 `test_set_user_groups_dedupes_duplicate_group_ids`：覆盖 `user_groups 生产职责与生命周期 / 更换用户权限组` 的重复组 ID 去重、两组直接实体并集、`container:create` 与 `bypass_auth_entity`；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_set_user_groups_dedupes_duplicate_group_ids -q`。
- [x] 3.4 实现并验证 `test_unbound_user_falls_back_to_default_user_group`：覆盖 `user_groups 生产职责与生命周期 / 更换用户权限组` 的 seed 后仍无组、默认 user 组兜底、显式 operator 切换与解绑回退；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_unbound_user_falls_back_to_default_user_group -q`。

## 4. backend--table-machine-permissions

- [x] 4.1 实现并验证 `test_machine_permission_pk_read_and_columns`：覆盖 `machine_permissions 持久化结构 / 读取有效记录` 的主键读回、自增 id 与两列非空；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_machine_permission_pk_read_and_columns -q`。
- [x] 4.2 实现并验证 `test_add_machine_permission_twice_keeps_single_pair`：覆盖 `machine_permissions 生产职责与生命周期 / 重复授权` 的重复授权单配对与唯一约束；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_add_machine_permission_twice_keeps_single_pair -q`。
- [x] 4.3 实现并验证 `test_remove_machine_permission_immediately_denies_resource`：覆盖 `machine_permissions 生产职责与生命周期 / 重复授权` 的授权/移除后资源鉴权即时翻转；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_remove_machine_permission_immediately_denies_resource -q`。
- [x] 4.4 实现并验证 `test_machine_permission_rows_cascade_on_machine_and_user_delete`：覆盖 `machine_permissions 生产职责与生命周期 / 重复授权` 的机器/用户双向级联且不影响其它配对；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_machine_permission_rows_cascade_on_machine_and_user_delete -q`。

## 5. backend--table-user-images

- [x] 5.1 实现并验证 `test_user_image_pk_read_and_granted_at`：覆盖 `user_images 持久化结构 / 读取有效记录` 的主键读回、`granted_at` 默认非空、唯一配对与 NULL 行为；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_user_image_pk_read_and_granted_at -q`。
- [x] 5.2 实现并验证 `test_user_image_rows_cascade_on_user_and_image_delete`：覆盖 `user_images 持久化结构 / 读取有效记录` 的用户/镜像双向级联；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_user_image_rows_cascade_on_user_and_image_delete -q`。
- [x] 5.3 实现并验证 `test_set_image_visible_users_dedupes_and_replaces`：覆盖 `user_images 生产职责与生命周期 / 整组更新名单` 的去重、整组替换旧行删除、everyone 态名单不参与判定；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_set_image_visible_users_dedupes_and_replaces -q`。
- [x] 5.4 实现并验证 `test_granted_viewer_reads_original_owner`：覆盖 `user_images 生产职责与生命周期 / 授权别人查看` 的被授权者读取详情、原所有权不变、不授予 `image:owner`；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_granted_viewer_reads_original_owner -q`。

## 6. backend--table-user-managed-users

- [x] 6.1 实现并验证 `test_user_managed_user_pk_read_and_unique_pair`：覆盖 `user_managed_users 持久化结构 / 读取有效记录` 的主键读回、`granted_at` 默认非空、唯一配对与 NULL 行为，不规划外键/级联；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_user_managed_user_pk_read_and_unique_pair -q`。
- [x] 6.2 实现并验证 `test_list_managed_ids_and_user_scope_includes_self`：覆盖 `user_managed_users 生产职责与生命周期 / 查询管理范围` 的 managed 集合、服务加入自身、通配 viewer 不受限；验证：`python -m pytest test/repository/test_anvil_rbac_mapping.py::test_list_managed_ids_and_user_scope_includes_self -q`。

## 7. 定向验证与映射确认

- [x] 7.1 运行唯一新文件全部 23 个用例：`python -m pytest test/repository/test_anvil_rbac_mapping.py -q`，确认 23 passed 且无新增失败。
- [x] 7.2 运行相关 RBAC/user/repository 映射文件套件：`python -m pytest test/repository test/user/test_rbac_api.py test/user/test_user_tasks_profile.py test/machine/test_machine_tasks_permission.py test/machine/test_machine_repository_integration.py test/image/test_image_api.py test/image/test_image_resource_scope.py test/container/test_rbac_container_role.py -q`，确认这些套件无新增失败；不跑全量 1478。
- [x] 7.3 核对 23 个 locator 均已在新文件落地、断言与 reviewed Assertion scope 一致；仅将 `test-plan.md` 对应映射复选框更新为 `[X]`，不写运行结果 ledger、不改 locator/Assertion scope/Coverage note。

## Workflow follow-up

- 运行 official verify（advisory，不创建 `verify.md`）。
- 运行 official no-op sync，保留 6 份主规格的 Purpose/Requirement/附录原文。
- 为 6 个 capability 生成/更新 canonical main sidecars，去除规划期时态描述、保留真实 Coverage notes。
- 执行 official archive，归档为 `2026-10-28-complete-anvil-rbac-test-mappings`。
