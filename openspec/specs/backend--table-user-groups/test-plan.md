# backend--table-user-groups Test Plan

Spec: [spec.md](spec.md)

> 范围：本映射基于隔离 SQLite 的真实行为断言（`PRAGMA foreign_keys=ON`），不承诺 MySQL 等价；复选框只表示映射已核对，不表示运行结果。

## Current Mapping

### Requirement: user_groups 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_anvil_rbac_mapping.py::test_user_group_composite_pk_read
  - [X] test/repository/test_anvil_rbac_mapping.py::test_user_group_rows_cascade_on_user_and_group_delete
- Assertion scope: 第一条用例真实写入后真实读取：`auth_repo.ensure_user_group(user.id, group.id, ...)` + commit，按复合主键 `session.get(UserGroup, (user_id, group_id))` 命中，断言两列都是对应表的整数主键值（不是用户名或组名）。约束行为断言：重复调用 `ensure_user_group` 后该配对行数仍为 1；直接 `session.add(UserGroup(user_id=..., group_id=...))` 插入已存在的复合主键并 `flush` 抛 `IntegrityError`；`session.add(UserGroup(user_id=null(), group_id=<真实组>))` 后 `flush` 抛 `IntegrityError`（主键列非空，用 `sqlalchemy.null()`）；`session.add(UserGroup(user_id=<真实用户>, group_id=999999))` 后 `flush` 抛 `IntegrityError`（`auth_groups.id` 外键在 `PRAGMA foreign_keys=ON` 下生效）。每个 `IntegrityError` 断言后 `session.rollback()`。本表无自增主键，不存在"省略 `id` 应被拒绝"的断言。第二条用例覆盖双向级联：删 `users` 行后该用户的 `user_groups` 行消失；删 `auth_groups` 行后该组的 `user_groups` 行消失（两列均为 `ondelete="CASCADE"`），其它配对行不受影响。
- Coverage note: 现有用例只经 `auth_repo.list_user_group_ids` 读组 id 集合，无用例按复合主键读取 `user_groups`，也未触发该表的复合主键、非空与外键约束，更没有 `ON DELETE CASCADE` 断言。

### Requirement: user_groups 生产职责与生命周期

#### Scenario: 更换用户权限组

- Test/check:
  - [X] test/user/test_rbac_api.py::test_set_user_groups_replaces_and_union_semantics
  - [X] test/user/test_rbac_api.py::test_set_user_groups_unknown_group_400
  - [X] test/user/test_rbac_api.py::test_set_user_groups_cannot_remove_own_rbac_manage
  - [X] test/user/test_rbac_api.py::test_get_user_groups_returns_bound_ids
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_success_consumes_code_and_creates_user
  - [X] test/repository/test_anvil_rbac_mapping.py::test_set_user_groups_dedupes_duplicate_group_ids
  - [X] test/repository/test_anvil_rbac_mapping.py::test_unbound_user_falls_back_to_default_user_group
- Assertion scope: 现有用例 POST `/api/rbac/users/7/groups` 从 `user` 组换成 `operator` 组后 `group_ids == [operator.id]` 且 `bypass_auth_entity` 立即出现在生效集；改绑 `[user, operator]` 时返回排序后的两 id 且 operator 侧 `bypass_auth_entity` 生效（既有用例未证明 user 组侧仍生效）；再改回 `[user]` 后 operator 的权限立即消失，落库 `list_user_group_ids == [user.id]`——即"用新集合替换旧绑定，后续鉴权即时采用新权限"。`group_ids` 含不存在 id 时 400 `unknown_group:`；目标是自己且新集合不含任何持 `rbac:manage` 的组时 400 `cannot_remove_own_manage` 且绑定不变；`GET` 返回已绑定 id。`test_register_with_code_success_consumes_code_and_creates_user` 断言正文"注册绑定默认 user 组"：注册成功后 `auth_repo.list_user_group_ids(new_user.id)` 含内置 `user` 组 id。用例两条：① 传重复的 `[user, operator, user, operator]`，断言响应与落库 `list_user_group_ids` 都只有 `[user.id, operator.id]`（"去重后的新集合"）；再按这两个组 id 直接查 `auth_repo.list_group_entity_codes(session=...)`，断言两组直接实体并集等于 `user` 组默认实体与 operator 组 `{bypass_resource, bypass_auth_entity}` 的并集，其中含 user 侧 `container:create` 与 operator 侧 `bypass_auth_entity`——operator 的 `bypass_auth_entity` 会把 `list_user_entities` 扩到全量，故该并集只断言为 `list_user_entities` 的子集，不以 `user_has_entity`/`list_user_entities` 等值反证 user 组侧未漏；② 正文"未绑定任何组的存量用户按默认 user 组兜底，seed 当前没有回填这些用户绑定"——建一个不绑任何组的用户后调用 `seed_rbac_defaults()`，断言 `auth_repo.list_user_group_ids(uid)` 仍为空，再断言 `auth_repo.user_has_any_group` 为假且 `rbac_service.user_has_entity(uid, "container:create") is True`、`user_has_entity(uid, "rbac:manage") is False`（命中默认组兜底分支）；显式绑到 operator 组后断言 `user_has_any_group` 为真且 `bypass_auth_entity` 生效（改走显式组分支）；解绑回空集后回到兜底结论。
- Coverage note: "去重后的新集合"无既有用例直证——现有用例输入均无重复 group_id，去重只在 `set_user_groups` 的 `sorted({int(g) ...})` 代码层成立。既有双组用例只直证 operator 侧 `bypass_auth_entity`，user 组侧 `container:create`/`machine:view` 在两组并存时未被断言；且 `bypass_auth_entity` 会让 `user_has_entity`/`list_user_entities` 对非 bypass 权限点一律为真，故用例改按两组直接实体并集取证，不用它们反证 user 组侧。无组用户的默认 user 组兜底此前只在 `user_has_entity` 代码里成立、无任何用例命中该分支，现由用例在调用 `seed_rbac_defaults()` 后断言绑定仍为空再直证。
