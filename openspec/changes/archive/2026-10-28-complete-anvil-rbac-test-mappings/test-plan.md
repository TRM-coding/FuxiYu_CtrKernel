# Test Plan

> 映射约定：`[X]` 表示该 locator 存在、且其断言已从测试代码逐条核对，能覆盖所列的可观察面；`[ ]` 表示用例、locator 或断言尚未确认（本计划中均为拟补用例，位于 `test/repository/test_anvil_rbac_mapping.py`）。
>
> 复选框只表示映射有效性，不表示运行/通过，也不表示整条 Scenario 已全覆盖；缺口一律写在 Coverage note。
>
> 运行环境限定：所有拟补用例都在 `db_session` 提供的隔离 SQLite 上运行，不连接真实 MySQL。SQLite 已由 `extensions._make_engine` 在连接事件里执行 `PRAGMA foreign_keys=ON`（`test/conftest.py` 的 `ensure_auth_users` 文档亦记录该 2026-09 决策），因此外键、`ON DELETE CASCADE`、非空与唯一约束都是**可真实触发**的行为，约束错误统一以 `sqlalchemy.exc.IntegrityError` 断言。SQLite 与 MySQL 在约束错误文本、约束检查时机上存在差异，本计划只承诺隔离安全套件上的结论，不承诺 MySQL 等价。
>
> 两条硬约束已在断言清单里落实：非空且有列默认值的列（如 `user_images.granted_at`、`user_managed_users.granted_at`）显式传 `None` 会被 ORM 用列默认值补齐而不报错，要断言"数据库拒绝 NULL"必须用 `sqlalchemy.null()` 真正写入 DB NULL；自增主键未赋值由数据库补齐是合法行为，任何用例都不得把"省略 `id`"断言成应被拒绝。
>
> 本计划不记录任何运行结果。6 个 capability 共 14 个 Scenario 全部列入。

## backend--table-auth-group-entities

### Requirement: auth_group_entities 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_anvil_rbac_mapping.py::test_auth_group_entity_pk_read_returns_stable_code
  - [X] test/repository/test_anvil_rbac_mapping.py::test_auth_group_entity_rows_cascade_on_group_delete
- Assertion scope: 第一条用例真实写入后真实读取：用 `auth_repo.ensure_group_entity(user_group_id, "machine:view", session=...)` 落库并 commit，再用 `session.get(AuthGroupEntity, (user_group_id, "machine:view"))` 按复合主键命中，断言 `entity_code` 就是 `AUTH_ENTITIES` 里的 code 原文——不是权限点中文展示名，也不是 `list_rbac_matrix()` 返回的 `entities[].id` 序数；反向以展示名（如 `"机器查看"`）为键读取时读不到任何行。约束行为断言（不依赖反射 ORM 属性）：同一 `(group_id, entity_code)` 再 `session.add` 同一主键行并 `flush` 抛 `IntegrityError`（复合主键）；`session.add(AuthGroupEntity(group_id=<真实组>, entity_code=null()))` 后 `flush` 抛 `IntegrityError`（`nullable=False`；该列无列默认值，统一用 `sqlalchemy.null()` 明确写 DB NULL）；`session.add(AuthGroupEntity(group_id=999999, entity_code="machine:view"))` 后 `flush` 抛 `IntegrityError`（`ondelete="CASCADE"` 外键在 `PRAGMA foreign_keys=ON` 下真实生效）。每个 `IntegrityError` 断言后 `session.rollback()`，保持用例间隔离。本表无自增主键，因此不存在"省略 `id` 应被拒绝"的断言。第二条用例覆盖级联：建自定义组并绑定实体后 `session.delete(group)` + commit，断言 `auth_group_entities` 中该组的行为 0（`ON DELETE CASCADE` 真实执行），且不受影响的其它组绑定行不变。
- Coverage note: 现有 `test/` 无任何用例按主键读取 `auth_group_entities`；`test/user/test_rbac_api.py` 只经 `auth_repo.list_group_entity_codes` / `group_has_entity` 读集合或做存在性判定，未核对"不把关联展示名替代稳定主键"，也未触发过该表的非空/主键/外键约束。

### Requirement: auth_group_entities 生产职责与生命周期

#### Scenario: 替换权限点

- Test/check:
  - [X] test/user/test_rbac_api.py::test_update_rbac_group_entities_replaces_user_group_permissions
  - [X] test/user/test_rbac_api.py::test_update_rbac_group_entities_rejects_unknown_entity
  - [X] test/user/test_rbac_api.py::test_seed_prunes_stale_entity_bindings
  - [X] test/repository/test_anvil_rbac_mapping.py::test_replace_group_entities_returns_catalog_order_not_request_order
  - [X] test/repository/test_anvil_rbac_mapping.py::test_group_entity_rows_store_codes_not_matrix_ordinals
- Assertion scope: 现有用例经 API 把内置 `user` 组的实体整组替换为 `["machine:view","image:view"]`，断言响应 `entity_codes` 等于该集合、`group_has_entity(machine:view)` 为真且旧 `container:create` 不再持有（"清理旧关联再插入新集合"）；只含目录外 code 的请求返回 400 `unknown_auth_entity`（"请求只含目录中有效 code"这一前提的边界）；`test_seed_prunes_stale_entity_bindings` 断言常量中已删除的 `user:view` 既不出现在矩阵 `entities` 中、也不在该组的落库绑定集合里，即本 Requirement 正文"AUTH_ENTITIES 为权限点目录的唯一来源"。拟补用例把请求写成**反序** `["image:view","machine:view"]`，断言返回与落库集合按 `AUTH_ENTITIES` 声明顺序（`machine:view` 在 `image:view` 之前）而不是请求顺序、也不是字母序；另一条用例断言 `auth_group_entities.entity_code` 的取值全部落在目录 code 集合内，且 `list_rbac_matrix()` 给出的 `entities[].id`（序数占位）不出现在该列。
- Coverage note: 现有用例的请求顺序恰好等于目录顺序，无法区分"按稳定目录顺序返回"与"按请求顺序返回"（此处目录顺序与请求顺序一致，字母序反而是相反结论），这一半 THEN 无直证；"不把矩阵序号当实体 id"亦无用例断言。两项为拟补用例。

### Requirement: 自定义权限组允许清空实体

#### Scenario: 清空自身唯一管理组

- Test/check:
  - [X] test/user/test_rbac_api.py::test_update_group_entities_allows_clearing_last_manage_group_at_service_level
  - [X] test/user/test_rbac_api.py::test_update_group_entities_can_drop_editors_own_manage_via_api
  - [X] test/user/test_rbac_api.py::test_update_operator_keeps_locked_bypass_entities
  - [X] test/repository/test_anvil_rbac_mapping.py::test_clearing_operator_group_keeps_locked_entities
- Assertion scope: 服务层直证：把用户唯一持有 `rbac:manage` 的自定义组替换为空集合后 `entity_codes == []`、`locked_entity_codes == []`，且该用户 `user_has_entity("rbac:manage")` 变为 False。API 层同一路径：POST `/api/rbac/groups/{id}/entities` 传空集合返回 200、响应 `entity_codes == []`，随后同一有效会话再访问受保护的 `/api/rbac/matrix` 得到 403（不是 401），即"后续受保护操作按新权限拒绝"。`test_update_operator_keeps_locked_bypass_entities` 只断言把 operator 组替换为 `["machine:view"]` 后响应 `entity_codes` 的集合包含 `{"machine:view","bypass_resource","bypass_auth_entity"}`。拟补用例补齐同一 THEN 的另一条公开路径：直接 `update_group_entities(operator_group_id, [])`，断言返回的 `entity_codes` 仍含 `bypass_resource` 与 `bypass_auth_entity`、`locked_entity_codes` 为这两者的全集，且落库绑定里同样保留两者——即"内置 operator 组的既有锁定权限规则 SHALL 保留"在清空路径上成立。
- Coverage note: "后续受保护操作"只以 `/api/rbac/matrix` 这一个受保护端点取证，未逐端点验证其它管理写操作；operator 锁定规则在"替换为子集"路径只由 `entity_codes` 包含关系部分覆盖，`locked_entity_codes` 字段本身在既有用例中从未被读取，其断言全部落在拟补用例里。

## backend--table-auth-groups

### Requirement: auth_groups 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_anvil_rbac_mapping.py::test_auth_group_pk_read_preserves_identity_and_nulls
- Assertion scope: 真实写入后真实读取：`session.add(AuthGroup(name="anvil_probe_group", description=None))` + commit，`id` 由自增补齐（**省略 `id` 是合法行为，不作拒绝断言**），再 `session.get(AuthGroup, id)` 读回，断言 `name` 是写入的组名原文、`description is None`（该列可空，真写 NULL 成功且不被服务层文案覆盖）。约束行为断言：`session.add(AuthGroup(name=null()))` 后 `flush` 抛 `IntegrityError`（`name` `nullable=False`，用 `sqlalchemy.null()` 写 DB NULL）；同名唯一约束另见下一 Scenario 的拟补用例，此处不重复造断言。
- Coverage note: 现有 `test/` 无用例按主键读取 `auth_groups`；`test/user/test_rbac_api.py` 一律经 `auth_repo.get_group(name)` 或 API 读组，`description` 的空值语义与 `name` 的非空约束从未被触发断言。

### Requirement: auth_groups 生产职责与生命周期

#### Scenario: 重复组名

- Test/check:
  - [X] test/user/test_rbac_api.py::test_create_rbac_group_rejects_duplicate_name
  - [X] test/user/test_rbac_api.py::test_create_rbac_group_uses_requested_permissions
  - [X] test/repository/test_anvil_rbac_mapping.py::test_auth_group_name_unique_constraint_blocks_second_row
  - [X] test/repository/test_anvil_rbac_mapping.py::test_seed_rbac_defaults_is_idempotent
  - [X] test/repository/test_anvil_rbac_mapping.py::test_replacing_group_entities_keeps_user_bindings_intact
- Assertion scope: 现有用例连续两次创建同名组，断言第一次 201、第二次 409 且 `error_reason == "group_exists"`。`test_create_rbac_group_uses_requested_permissions` 断言本 Requirement 正文"自定义组通过 RBAC API 创建"：POST `/api/rbac/groups` 返回 201、响应 `group.name == "teacher"` 且 `entity_codes` 等于请求集合，落库 `auth_repo.get_group("teacher")` 非空并 `group_has_entity(container:create)` 为真。拟补用例三条：① 绕过服务 `get_group` 预检，直接 `session.add(AuthGroup(name=<已存在同名>))` + `flush`，断言数据库层抛 `IntegrityError`（唯一约束本身生效）；先 `session.rollback()` 恢复 session，再断言 `select(func.count()).select_from(AuthGroup).where(AuthGroup.name == 同名)` 仍为 1，即"不产生两条同名组记录"；② 连续两次调用 `services.rbac_service.seed_rbac_defaults()`，断言 `auth_groups` 中 `user`/`operator` 各恰好一行且 `id` 与首次记录一致，`auth_group_entities` 中同一 `(group_id, entity_code)` 不出现重复行（按 `group_id, entity_code` 分组的计数全为 1），即"默认 user/operator 组由幂等 seed 创建"；③ 先给某组绑定实体并给用户绑定该组，再 `replace_group_entities` 换成另一组 code，断言用户绑定 `list_user_group_ids` 与 `user_groups` 行完全不变、只有 `auth_group_entities` 变化，即正文"实体关联和用户绑定各在独立关联表"。
- Coverage note: 现有 409 来自 `rbac_service.create_group` 里的 `get_group` 预检，不是唯一约束本身，也没有断言同名行数；THEN 的"唯一约束"这一半无既有用例直证。seed 幂等（含组 id 稳定性）与"实体关联/用户绑定分表互不影响"两句正文此前没有落点，现由两条拟补用例直证。`test_seed_prunes_stale_entity_bindings` 已覆盖 seed 的清理口径，拟补用例只补"重复调用不增生"，不重复该断言。

## backend--table-user-groups

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
- Assertion scope: 现有用例 POST `/api/rbac/users/7/groups` 从 `user` 组换成 `operator` 组后 `group_ids == [operator.id]` 且 `bypass_auth_entity` 立即出现在生效集；改绑 `[user, operator]` 时返回排序后的两 id 且 operator 侧 `bypass_auth_entity` 生效（既有用例未证明 user 组侧仍生效）；再改回 `[user]` 后 operator 的权限立即消失，落库 `list_user_group_ids == [user.id]`——即"用新集合替换旧绑定，后续鉴权即时采用新权限"。`group_ids` 含不存在 id 时 400 `unknown_group:`；目标是自己且新集合不含任何持 `rbac:manage` 的组时 400 `cannot_remove_own_manage` 且绑定不变；`GET` 返回已绑定 id。`test_register_with_code_success_consumes_code_and_creates_user` 断言正文"注册绑定默认 user 组"：注册成功后 `auth_repo.list_user_group_ids(new_user.id)` 含内置 `user` 组 id。拟补用例两条：① 传重复的 `[user, operator, user, operator]`，断言响应与落库 `list_user_group_ids` 都只有 `[user.id, operator.id]`（"去重后的新集合"）；再按这两个组 id 直接查 `auth_repo.list_group_entity_codes(session=...)`，断言两组直接实体并集等于 `user` 组默认实体与 operator 组 `{bypass_resource, bypass_auth_entity}` 的并集，其中含 user 侧 `container:create` 与 operator 侧 `bypass_auth_entity`——operator 的 `bypass_auth_entity` 会把 `list_user_entities` 扩到全量，故该并集只断言为 `list_user_entities` 的子集，不以 `user_has_entity`/`list_user_entities` 等值反证 user 组侧未漏；② 正文"未绑定任何组的存量用户按默认 user 组兜底，seed 当前没有回填这些用户绑定"——建一个不绑任何组的用户后调用 `seed_rbac_defaults()`，断言 `auth_repo.list_user_group_ids(uid)` 仍为空，再断言 `auth_repo.user_has_any_group` 为假且 `rbac_service.user_has_entity(uid, "container:create") is True`、`user_has_entity(uid, "rbac:manage") is False`（命中默认组兜底分支）；显式绑到 operator 组后断言 `user_has_any_group` 为真且 `bypass_auth_entity` 生效（改走显式组分支）；解绑回空集后回到兜底结论。
- Coverage note: "去重后的新集合"无既有用例直证——现有用例输入均无重复 group_id，去重只在 `set_user_groups` 的 `sorted({int(g) ...})` 代码层成立。既有双组用例只直证 operator 侧 `bypass_auth_entity`，user 组侧 `container:create`/`machine:view` 在两组并存时未被断言；且 `bypass_auth_entity` 会让 `user_has_entity`/`list_user_entities` 对非 bypass 权限点一律为真，故拟补用例改按两组直接实体并集取证，不用它们反证 user 组侧。无组用户的默认 user 组兜底此前只在 `user_has_entity` 代码里成立、无任何用例命中该分支，现由拟补用例在调用 `seed_rbac_defaults()` 后断言绑定仍为空再直证。

## backend--table-machine-permissions

### Requirement: machine_permissions 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_anvil_rbac_mapping.py::test_machine_permission_pk_read_and_columns
- Assertion scope: 真实写入后真实读取：`machine_permission_repo.add_permission(machine.id, user.id, session=...)` + commit，再 `session.get(MachinePermission, record.id)` 读回，断言 `machine_id` 与 `user_id` 分别等于 `machines.id` / `users.id` 的真实主键值（不是机器名或用户名）；`id` 由自增补齐（**省略 `id` 是合法行为，不作拒绝断言**）。约束行为断言：`session.add(MachinePermission(machine_id=null(), user_id=user.id))` 与 `session.add(MachinePermission(machine_id=machine.id, user_id=null()))` 各自 `flush` 抛 `IntegrityError`（两列 `nullable=False`，用 `sqlalchemy.null()` 写 DB NULL）。唯一配对 `uq_machine_permissions_machine_user` 的断言归入下一 Scenario 的拟补用例，此处不重复。
- Coverage note: 现有用例只经 `list_user_ids_by_machine` / `List_machine_permissions` 读 id 列表，无用例按主键读取 `machine_permissions`，也未触发该表的非空约束。

### Requirement: machine_permissions 生产职责与生命周期

#### Scenario: 重复授权

- Test/check:
  - [X] test/machine/test_machine_tasks_permission.py::test_add_machine_permission_success
  - [X] test/machine/test_machine_tasks_permission.py::test_remove_machine_permission_returns_repo_result
  - [X] test/machine/test_machine_repository_integration.py::test_machine_permission_create_and_list_with_real_repository
  - [X] test/repository/test_anvil_rbac_mapping.py::test_add_machine_permission_twice_keeps_single_pair
  - [X] test/repository/test_anvil_rbac_mapping.py::test_remove_machine_permission_immediately_denies_resource
  - [X] test/repository/test_anvil_rbac_mapping.py::test_machine_permission_rows_cascade_on_machine_and_user_delete
- Assertion scope: 现有用例经真实仓储授予权限，断言 `Add_machine_permission` 返回 True 且 `list_user_ids_by_machine` / `List_machine_permissions` 均为 `[user.id]`；移除返回 True，再次移除返回 False。拟补用例三条：① 对同一 `(machine_id, user_id)` 连续授权两次，断言两次执行后该配对行数仍为 1、`list_user_ids_by_machine` 不出现重复元素，并对第二次绕过仓储直接 `session.add` 同一配对 + `flush` 断言抛 `IntegrityError`（`uq_machine_permissions_machine_user` 真实生效），即"保持一条有效配对，不创建重复资源权限"；② 在授权前、授权后、移除后分别调用 `rbac_service.user_has_resource(user_id, "machine", machine_id)`，断言 False → True → False，即"权限检查实时查询、移除立即影响后续资源鉴权"；③ 正文"机器和用户外键声明 CASCADE"：在同一用例里分两组独立数据分别验证两个外键方向——建最小 `machines`/`users` 行并授权后 `session.delete(machine)` + commit 断言该配对行消失；另建一对数据后 `session.delete(user)` + commit 断言该配对行消失（`PRAGMA foreign_keys=ON` 下 `ondelete="CASCADE"` 真实执行），且其它机器的配对行不受影响。
- Coverage note: "重复授权保持一条有效配对"无既有用例直证——`test/machine/test_machine_api_permission.py` 的 14 个用例均不触表；成功/未找到分支使用 `Add_machine_permission`/`Remove_machine_permission`/`List_machine_permissions` 替身，认证/权限/缺参分支在 API 层提前短路——因此不能拿这些用例证明幂等分支。"移除影响后续资源鉴权"同样无 `user_has_resource(..., "machine", ...)` 的前后翻转断言（现有对 machine 资源的唯一断言是 `test/container/test_rbac_container_role.py` 里"`container:manage` 不影响 machine 判定"的反例）。两列 `ondelete="CASCADE"` 此前无任何用例触发，现由拟补用例直证。级联结论只在隔离 SQLite（已开 `PRAGMA foreign_keys=ON`）成立，未在真实 MySQL 验证。

## backend--table-user-images

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
- Assertion scope: 现有用例断言：范围非 custom（everyone）时 POST `/api/images/set_image_visible_users` 返回 400 `not_custom_range`，即"非 custom 范围的名单变更仍被服务拒绝"；`user_ids` 含不存在用户时 400 `unknown_user`；`custom` 态提交 `[granted.id]` 后响应 `user_ids == [granted.id]`，切到 everyone 再切回 custom 后 `get_image_detail_information` 的 `visible_user_ids` 仍为 `[granted.id]`；非 custom 态不回显 `visible_user_ids`；`test_visibility_matrix` 断言给 `private` 也发授权行后该模板仍对接收者不可见、`everyone` 对全员可见而 `custom` 只认名单，即"名单只在 custom 范围决定可见性"；`test_mine_only_is_strictly_owned_and_wildcard_does_not_leak` 断言 `Set_image_visible_users` 返回已落定的 `[granted.id]`。拟补用例：传入重复用户 id，断言服务返回与 `userimage_repo.list_user_ids_by_image` 都是去重后的集合（保留 first/second 两个不同 id），并断言再次整组更新为另一集合时不在新集合中的旧行被删除（"整组替换"语义）；同一用例追加 everyone 态对照——在 everyone 模板上直接写入一行授权后，未授权用户的列表可见性与资源门口径不变（名单不参与非 custom 判定）。
- Coverage note: "落定去重后的查看授权集合"无既有用例直证——现有调用都只传一个 id，去重只在 `Set_image_visible_users` 的 `sorted({int(uid) ...})` 代码层成立；"整组替换会删除旧行"也只由 `test_switching_range_keeps_the_grant_list` 的单元素往返间接体现，未断言替换后旧行消失；everyone 态"给模板发授权行"的对照断言此前缺失。三项全部落在同一条拟补用例里。

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
- Assertion scope: 被加入 CUSTOM 名单的用户在持有 `image:edit`/`image:view` 时能读到该模板详情（`get_image_detail_information` 200）、`Can_use_image_for_container` 返回 `OK`（"满足方法权限时查看或使用"）；对别人的模板发 `update_image` 得 403 `resource_access_denied`（"不授予编辑能力"）；名单变化后列表谓词与点判定结论一致；`test_mine_only_is_strictly_owned_and_wildcard_does_not_leak` 在 `mine_only=true` 列表里断言被授权者（`granted`）的名字集合与 `SCENE_NAMES` 不相交，而同用例的 `total_number == 0` 只对 `operator/manager/wildcard/entity_only` 四类观众断言，不包含 `granted`；`test_operator_full_chain_list_detail_edit_and_container` 断言资源通配编辑他人模板后 `created_by_user_id` 仍是原作者。拟补用例补"授权入口上的原所有权不变"：owner 建 CUSTOM 镜像并 `Set_image_visible_users([granted])`，以被授权者身份 `GET /api/images/get_image_detail_information` 断言 200 且 `image.created_by_user_id == owner.id`（授权前后一致），并断言 `rbac_service.user_has_resource(granted.id, "image:owner", image_id) is False`，即名单只给查看/使用、不转移归属。
- Coverage note: "镜像不会成为对方创建的资源，原所有权不变"在授权入口上此前只有 mine_only 与列表可见性的间接证据，`created_by_user_id` 相等断言只出现在 operator 资源通配编辑链路；现由拟补用例在授权入口直证。`test_point_check_agrees_with_list_predicate` 使用手工构造的 `ImageScope`，覆盖的是谓词一致性而非授权入口本身。

## backend--table-user-managed-users

### Requirement: user_managed_users 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_anvil_rbac_mapping.py::test_user_managed_user_pk_read_and_unique_pair
- Assertion scope: 真实写入后真实读取：`session.add(UserManagedUser(manager_user_id=manager.id, managed_user_id=student.id))` + commit，再 `session.get(UserManagedUser, record.id)` 读回，断言两列保存写入的用户 id、`granted_at` 非空（由 `datetime.utcnow` 列默认填充）；`id` 由自增补齐（**省略 `id` 是合法行为，不作拒绝断言**）。约束行为断言：重复写入同一配对并 `flush` 抛 `IntegrityError`（`uq_user_managed_pair` 真实生效）；非空断言必须用 `sqlalchemy.null()`——`session.add(UserManagedUser(manager_user_id=null(), managed_user_id=student.id))` 与 `managed_user_id=null()` 各自 `flush` 抛 `IntegrityError`（`granted_at` 同理，显式传 `None` 会被列默认补齐而不报错）。每个 `IntegrityError` 断言后 `session.rollback()`。本表两列在模型中均为裸 `db.Integer`，主规格数据附录同样未记 ForeignKey，因此**不规划外键约束与级联断言**——这是模型与规格的声明事实，不是环境限制。
- Coverage note: 现有唯一触表处是 `test/container/test_rbac_container_role.py::test_container_role_resource_points` 直接 `session.add(UserManagedUser(...))` 造数据，未断言主键、`granted_at` 的非空行为或唯一配对约束。本表未声明外键，故无级联可测；若将来声明外键应在该用例补对应断言。

### Requirement: user_managed_users 生产职责与生命周期

#### Scenario: 查询管理范围

- Test/check:
  - [X] test/container/test_rbac_container_role.py::test_container_role_resource_points
  - [X] test/repository/test_anvil_rbac_mapping.py::test_list_managed_ids_and_user_scope_includes_self
- Assertion scope: 现有用例插入 `(manager, stranger)` 后断言 `rbac_service.user_has_resource(manager.id, "user", stranger.id)` 为 True、反向 `(stranger, manager)` 为 False，即受管关系确实进入 user 资源判定。拟补用例断言三层：`user_managed_user_repo.list_managed_ids(manager_user_id=manager.id, session=...)` 返回已存在的 `managed_user_id` 集合（无记录时为空集）；`user_tasks.List_all_user_bref_information(viewer_user_id=manager.id, ...)` 的可见集合等于 `{manager 自身} ∪ managed`——受管学生出现、无关用户不出现，即"由服务加入当前用户自身"；对照无 `bypass_resource`/`user:manage` 的 viewer 才走该过滤，持通配者不受限。
- Coverage note: "由服务加入当前用户自身"无既有用例直证（`visible_ids = {int(viewer_user_id)} | managed` 只在 `user_tasks` 代码层成立），`user_managed_user_repo.list_managed_ids` 目前无任何测试调用者；现由拟补用例直证。本 Requirement 正文"当前无对应公开写入口"陈述的是一个"不存在"的事实（没有任何写入端点），无法用正向测试表达，因此本计划不为它规划用例。
