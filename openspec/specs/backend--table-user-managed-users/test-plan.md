# backend--table-user-managed-users Test Plan

Spec: [spec.md](spec.md)

> 范围：本映射基于隔离 SQLite 的真实行为断言（`PRAGMA foreign_keys=ON`），不承诺 MySQL 等价；复选框只表示映射已核对，不表示运行结果。

## Current Mapping

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
- Assertion scope: 现有用例插入 `(manager, stranger)` 后断言 `rbac_service.user_has_resource(manager.id, "user", stranger.id)` 为 True、反向 `(stranger, manager)` 为 False，即受管关系确实进入 user 资源判定。用例断言三层：`user_managed_user_repo.list_managed_ids(manager_user_id=manager.id, session=...)` 返回已存在的 `managed_user_id` 集合（无记录时为空集）；`user_tasks.List_all_user_bref_information(viewer_user_id=manager.id, ...)` 的可见集合等于 `{manager 自身} ∪ managed`——受管学生出现、无关用户不出现，即"由服务加入当前用户自身"；对照无 `bypass_resource`/`user:manage` 的 viewer 才走该过滤，持通配者不受限。
- Coverage note: "由服务加入当前用户自身"无既有用例直证（`visible_ids = {int(viewer_user_id)} | managed` 只在 `user_tasks` 代码层成立），`user_managed_user_repo.list_managed_ids` 目前无任何测试调用者；现由用例直证。本 Requirement 正文"当前无对应公开写入口"陈述的是一个"不存在"的事实（没有任何写入端点），无法用正向测试表达，因此本映射不为它规划用例。
