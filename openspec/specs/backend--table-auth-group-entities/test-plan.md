# backend--table-auth-group-entities Test Plan

Spec: [spec.md](spec.md)

> 范围：本映射基于隔离 SQLite 的真实行为断言（`PRAGMA foreign_keys=ON`），不承诺 MySQL 等价；复选框只表示映射已核对，不表示运行结果。

## Current Mapping

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
- Assertion scope: 现有用例经 API 把内置 `user` 组的实体整组替换为 `["machine:view","image:view"]`，断言响应 `entity_codes` 等于该集合、`group_has_entity(machine:view)` 为真且旧 `container:create` 不再持有（"清理旧关联再插入新集合"）；只含目录外 code 的请求返回 400 `unknown_auth_entity`（"请求只含目录中有效 code"这一前提的边界）；`test_seed_prunes_stale_entity_bindings` 断言常量中已删除的 `user:view` 既不出现在矩阵 `entities` 中、也不在该组的落库绑定集合里，即本 Requirement 正文"AUTH_ENTITIES 为权限点目录的唯一来源"。用例把请求写成**反序** `["image:view","machine:view"]`，断言返回与落库集合按 `AUTH_ENTITIES` 声明顺序（`machine:view` 在 `image:view` 之前）而不是请求顺序、也不是字母序；另一条用例断言 `auth_group_entities.entity_code` 的取值全部落在目录 code 集合内，且 `list_rbac_matrix()` 给出的 `entities[].id`（序数占位）不出现在该列。
- Coverage note: 现有用例的请求顺序恰好等于目录顺序，无法区分"按稳定目录顺序返回"与"按请求顺序返回"（此处目录顺序与请求顺序一致，字母序反而是相反结论），这一半 THEN 无直证；"不把矩阵序号当实体 id"亦无用例断言。两项为用例。

### Requirement: 自定义权限组允许清空实体

#### Scenario: 清空自身唯一管理组

- Test/check:
  - [X] test/user/test_rbac_api.py::test_update_group_entities_allows_clearing_last_manage_group_at_service_level
  - [X] test/user/test_rbac_api.py::test_update_group_entities_can_drop_editors_own_manage_via_api
  - [X] test/user/test_rbac_api.py::test_update_operator_keeps_locked_bypass_entities
  - [X] test/repository/test_anvil_rbac_mapping.py::test_clearing_operator_group_keeps_locked_entities
- Assertion scope: 服务层直证：把用户唯一持有 `rbac:manage` 的自定义组替换为空集合后 `entity_codes == []`、`locked_entity_codes == []`，且该用户 `user_has_entity("rbac:manage")` 变为 False。API 层同一路径：POST `/api/rbac/groups/{id}/entities` 传空集合返回 200、响应 `entity_codes == []`，随后同一有效会话再访问受保护的 `/api/rbac/matrix` 得到 403（不是 401），即"后续受保护操作按新权限拒绝"。`test_update_operator_keeps_locked_bypass_entities` 只断言把 operator 组替换为 `["machine:view"]` 后响应 `entity_codes` 的集合包含 `{"machine:view","bypass_resource","bypass_auth_entity"}`。用例补齐同一 THEN 的另一条公开路径：直接 `update_group_entities(operator_group_id, [])`，断言返回的 `entity_codes` 仍含 `bypass_resource` 与 `bypass_auth_entity`、`locked_entity_codes` 为这两者的全集，且落库绑定里同样保留两者——即"内置 operator 组的既有锁定权限规则 SHALL 保留"在清空路径上成立。
- Coverage note: "后续受保护操作"只以 `/api/rbac/matrix` 这一个受保护端点取证，未逐端点验证其它管理写操作；operator 锁定规则在"替换为子集"路径只由 `entity_codes` 包含关系部分覆盖，`locked_entity_codes` 字段本身在既有用例中从未被读取，其断言全部落在用例里。
