# backend--table-user-images Test Plan

Spec: [spec.md](spec.md)

> 范围：本映射基于隔离 SQLite 的真实行为断言（`PRAGMA foreign_keys=ON`），不承诺 MySQL 等价；复选框只表示映射已核对，不表示运行结果。

## Current Mapping

### Requirement: user_images 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_anvil_rbac_mapping.py::test_user_image_pk_read_and_granted_at
  - [X] test/repository/test_anvil_rbac_mapping.py::test_user_image_rows_cascade_on_user_and_image_delete
- Assertion scope: 第一条用例真实写入后真实读取：`userimage_repo.grant_image(user.id, image.id, session=...)` + commit，再 `session.get(UserImage, record.id)` 读回，断言 `user_id`/`image_id` 为对应实体主键值、`granted_at` 非空（由列默认填充）；`id` 由自增补齐（**省略 `id` 是合法行为，不作拒绝断言**）。约束行为断言：**`granted_at` 的 NULL 必须用 `sqlalchemy.null()` 写**——显式 `granted_at=None` 会被 ORM 用列默认值补齐而不报错，只有 `session.add(UserImage(user_id=user.id, image_id=image.id, granted_at=null()))` 后 `flush` 才抛 `IntegrityError`（`nullable=False` 真实生效）；同一 `(user_id, image_id)` 再插一行 `flush` 抛 `IntegrityError`（`uq_user_images_user_image` 真实生效）。每个 `IntegrityError` 断言后 `session.rollback()`。第二条用例覆盖双向级联：删授权接收者用户（刻意用**非镜像创建者**的用户，避免 `images.created_by_user_id` 的无关外键拦截）后该 `user_images` 行消失；删该镜像行后该 `user_images` 行消失（两列均 `ondelete="CASCADE"`）。
- Coverage note: 现有 `test/image/test_image_api.py::test_point_check_agrees_with_list_predicate` 直接 `db_session.add(UserImage(...))` 只是在默认值情况下造数据，未断言主键、`granted_at` 的非空行为、唯一配对或级联；无用例按主键读取 `user_images`。

### Requirement: user_images 生产职责与生命周期

#### Scenario: 整组更新名单

- Test/check:
  - [X] test/image/test_image_api.py::test_set_visible_users_rejected_outside_custom
  - [X] test/image/test_image_api.py::test_set_visible_users_rejects_unknown_user
  - [X] test/image/test_image_api.py::test_switching_range_keeps_the_grant_list
  - [X] test/image/test_image_api.py::test_visible_user_ids_only_exposed_for_custom
  - [X] test/image/test_image_api.py::test_visibility_matrix
  - [X] test/image/test_image_resource_scope.py::test_mine_only_is_strictly_owned_and_wildcard_does_not_leak
  - [X] test/repository/test_anvil_rbac_mapping.py::test_set_image_visible_users_dedupes_and_replaces
- Assertion scope: 现有用例断言：范围非 custom（everyone）时 POST `/api/images/set_image_visible_users` 返回 400 `not_custom_range`，即"非 custom 范围的名单变更仍被服务拒绝"；`user_ids` 含不存在用户时 400 `unknown_user`；`custom` 态提交 `[granted.id]` 后响应 `user_ids == [granted.id]`，切到 everyone 再切回 custom 后 `get_image_detail_information` 的 `visible_user_ids` 仍为 `[granted.id]`；非 custom 态不回显 `visible_user_ids`；`test_visibility_matrix` 断言给 `private` 也发授权行后该模板仍对接收者不可见、`everyone` 对全员可见而 `custom` 只认名单，即"名单只在 custom 范围决定可见性"；`test_mine_only_is_strictly_owned_and_wildcard_does_not_leak` 断言 `Set_image_visible_users` 返回已落定的 `[granted.id]`。用例：传入重复用户 id，断言服务返回与 `userimage_repo.list_user_ids_by_image` 都是去重后的集合（保留 first/second 两个不同 id），并断言再次整组更新为另一集合时不在新集合中的旧行被删除（"整组替换"语义）；同一用例追加 everyone 态对照——在 everyone 模板上直接写入一行授权后，未授权用户的列表可见性与资源门口径不变（名单不参与非 custom 判定）。
- Coverage note: "落定去重后的查看授权集合"无既有用例直证——现有调用都只传一个 id，去重只在 `Set_image_visible_users` 的 `sorted({int(uid) ...})` 代码层成立；"整组替换会删除旧行"也只由 `test_switching_range_keeps_the_grant_list` 的单元素往返间接体现，未断言替换后旧行消失；everyone 态"给模板发授权行"的对照断言此前缺失。三项全部落在同一条用例里。

#### Scenario: 授权别人查看

- Test/check:
  - [X] test/image/test_image_resource_scope.py::test_detail_requires_image_edit_method_and_resource_visibility
  - [X] test/image/test_image_resource_scope.py::test_container_image_usability_follows_scope_and_ready_gate
  - [X] test/image/test_image_resource_scope.py::test_mine_only_is_strictly_owned_and_wildcard_does_not_leak
  - [X] test/image/test_image_api.py::test_update_requires_ownership_not_just_visibility
  - [X] test/image/test_image_api.py::test_visibility_matrix
  - [X] test/image/test_image_api.py::test_point_check_agrees_with_list_predicate
  - [X] test/image/test_image_resource_scope.py::test_operator_full_chain_list_detail_edit_and_container
  - [X] test/repository/test_anvil_rbac_mapping.py::test_granted_viewer_reads_original_owner
- Assertion scope: 被加入 CUSTOM 名单的用户在持有 `image:edit`/`image:view` 时能读到该模板详情（`get_image_detail_information` 200）、`Can_use_image_for_container` 返回 `OK`（"满足方法权限时查看或使用"）；对别人的模板发 `update_image` 得 403 `resource_access_denied`（"不授予编辑能力"）；名单变化后列表谓词与点判定结论一致；`test_mine_only_is_strictly_owned_and_wildcard_does_not_leak` 在 `mine_only=true` 列表里断言被授权者（`granted`）的名字集合与 `SCENE_NAMES` 不相交，而同用例的 `total_number == 0` 只对 `operator/manager/wildcard/entity_only` 四类观众断言，不包含 `granted`；`test_operator_full_chain_list_detail_edit_and_container` 断言资源通配编辑他人模板后 `created_by_user_id` 仍是原作者。用例补"授权入口上的原所有权不变"：owner 建 CUSTOM 镜像并 `Set_image_visible_users([granted])`，以被授权者身份 `GET /api/images/get_image_detail_information` 断言 200 且 `image.created_by_user_id == owner.id`（授权前后一致），并断言 `rbac_service.user_has_resource(granted.id, "image:owner", image_id) is False`，即名单只给查看/使用、不转移归属。
- Coverage note: "镜像不会成为对方创建的资源，原所有权不变"在授权入口上此前只有 mine_only 与列表可见性的间接证据，`created_by_user_id` 相等断言只出现在 operator 资源通配编辑链路；现由用例在授权入口直证。`test_point_check_agrees_with_list_predicate` 使用手工构造的 `ImageScope`，覆盖的是谓词一致性而非授权入口本身。
