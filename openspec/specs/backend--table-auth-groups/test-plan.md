# backend--table-auth-groups Test Plan

Spec: [spec.md](spec.md)

> 范围：本映射基于隔离 SQLite 的真实行为断言（`PRAGMA foreign_keys=ON`），不承诺 MySQL 等价；复选框只表示映射已核对，不表示运行结果。

## Current Mapping

### Requirement: auth_groups 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_anvil_rbac_mapping.py::test_auth_group_pk_read_preserves_identity_and_nulls
- Assertion scope: 真实写入后真实读取：`session.add(AuthGroup(name="anvil_probe_group", description=None))` + commit，`id` 由自增补齐（**省略 `id` 是合法行为，不作拒绝断言**），再 `session.get(AuthGroup, id)` 读回，断言 `name` 是写入的组名原文、`description is None`（该列可空，真写 NULL 成功且不被服务层文案覆盖）。约束行为断言：`session.add(AuthGroup(name=null()))` 后 `flush` 抛 `IntegrityError`（`name` `nullable=False`，用 `sqlalchemy.null()` 写 DB NULL）；同名唯一约束另见下一 Scenario 的用例，此处不重复造断言。
- Coverage note: 现有 `test/` 无用例按主键读取 `auth_groups`；`test/user/test_rbac_api.py` 一律经 `auth_repo.get_group(name)` 或 API 读组，`description` 的空值语义与 `name` 的非空约束从未被触发断言。

### Requirement: auth_groups 生产职责与生命周期

#### Scenario: 重复组名

- Test/check:
  - [X] test/user/test_rbac_api.py::test_create_rbac_group_rejects_duplicate_name
  - [X] test/user/test_rbac_api.py::test_create_rbac_group_uses_requested_permissions
  - [X] test/repository/test_anvil_rbac_mapping.py::test_auth_group_name_unique_constraint_blocks_second_row
  - [X] test/repository/test_anvil_rbac_mapping.py::test_seed_rbac_defaults_is_idempotent
  - [X] test/repository/test_anvil_rbac_mapping.py::test_replacing_group_entities_keeps_user_bindings_intact
- Assertion scope: 现有用例连续两次创建同名组，断言第一次 201、第二次 409 且 `error_reason == "group_exists"`。`test_create_rbac_group_uses_requested_permissions` 断言本 Requirement 正文"自定义组通过 RBAC API 创建"：POST `/api/rbac/groups` 返回 201、响应 `group.name == "teacher"` 且 `entity_codes` 等于请求集合，落库 `auth_repo.get_group("teacher")` 非空并 `group_has_entity(container:create)` 为真。用例三条：① 绕过服务 `get_group` 预检，直接 `session.add(AuthGroup(name=<已存在同名>))` + `flush`，断言数据库层抛 `IntegrityError`（唯一约束本身生效）；先 `session.rollback()` 恢复 session，再断言 `select(func.count()).select_from(AuthGroup).where(AuthGroup.name == 同名)` 仍为 1，即"不产生两条同名组记录"；② 连续两次调用 `services.rbac_service.seed_rbac_defaults()`，断言 `auth_groups` 中 `user`/`operator` 各恰好一行且 `id` 与首次记录一致，`auth_group_entities` 中同一 `(group_id, entity_code)` 不出现重复行（按 `group_id, entity_code` 分组的计数全为 1），即"默认 user/operator 组由幂等 seed 创建"；③ 先给某组绑定实体并给用户绑定该组，再 `replace_group_entities` 换成另一组 code，断言用户绑定 `list_user_group_ids` 与 `user_groups` 行完全不变、只有 `auth_group_entities` 变化，即正文"实体关联和用户绑定各在独立关联表"。
- Coverage note: 现有 409 来自 `rbac_service.create_group` 里的 `get_group` 预检，不是唯一约束本身，也没有断言同名行数；THEN 的"唯一约束"这一半无既有用例直证。seed 幂等（含组 id 稳定性）与"实体关联/用户绑定分表互不影响"两句正文此前没有落点，现由两条用例直证。`test_seed_prunes_stale_entity_bindings` 已覆盖 seed 的清理口径，用例只补"重复调用不增生"，不重复该断言。
