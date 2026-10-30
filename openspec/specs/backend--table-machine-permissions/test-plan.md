# backend--table-machine-permissions Test Plan

Spec: [spec.md](spec.md)

> 范围：本映射基于隔离 SQLite 的真实行为断言（`PRAGMA foreign_keys=ON`），不承诺 MySQL 等价；复选框只表示映射已核对，不表示运行结果。

## Current Mapping

### Requirement: machine_permissions 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_anvil_rbac_mapping.py::test_machine_permission_pk_read_and_columns
- Assertion scope: 真实写入后真实读取：`machine_permission_repo.add_permission(machine.id, user.id, session=...)` + commit，再 `session.get(MachinePermission, record.id)` 读回，断言 `machine_id` 与 `user_id` 分别等于 `machines.id` / `users.id` 的真实主键值（不是机器名或用户名）；`id` 由自增补齐（**省略 `id` 是合法行为，不作拒绝断言**）。约束行为断言：`session.add(MachinePermission(machine_id=null(), user_id=user.id))` 与 `session.add(MachinePermission(machine_id=machine.id, user_id=null()))` 各自 `flush` 抛 `IntegrityError`（两列 `nullable=False`，用 `sqlalchemy.null()` 写 DB NULL）。唯一配对 `uq_machine_permissions_machine_user` 的断言归入下一 Scenario 的用例，此处不重复。
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
- Assertion scope: 现有用例经真实仓储授予权限，断言 `Add_machine_permission` 返回 True 且 `list_user_ids_by_machine` / `List_machine_permissions` 均为 `[user.id]`；移除返回 True，再次移除返回 False。用例三条：① 对同一 `(machine_id, user_id)` 连续授权两次，断言两次执行后该配对行数仍为 1、`list_user_ids_by_machine` 不出现重复元素，并对第二次绕过仓储直接 `session.add` 同一配对 + `flush` 断言抛 `IntegrityError`（`uq_machine_permissions_machine_user` 真实生效），即"保持一条有效配对，不创建重复资源权限"；② 在授权前、授权后、移除后分别调用 `rbac_service.user_has_resource(user_id, "machine", machine_id)`，断言 False → True → False，即"权限检查实时查询、移除立即影响后续资源鉴权"；③ 正文"机器和用户外键声明 CASCADE"：在同一用例里分两组独立数据分别验证两个外键方向——建最小 `machines`/`users` 行并授权后 `session.delete(machine)` + commit 断言该配对行消失；另建一对数据后 `session.delete(user)` + commit 断言该配对行消失（`PRAGMA foreign_keys=ON` 下 `ondelete="CASCADE"` 真实执行），且其它机器的配对行不受影响。
- Coverage note: "重复授权保持一条有效配对"无既有用例直证——`test/machine/test_machine_api_permission.py` 的 14 个用例均不触表；成功/未找到分支使用 `Add_machine_permission`/`Remove_machine_permission`/`List_machine_permissions` 替身，认证/权限/缺参分支在 API 层提前短路——因此不能拿这些用例证明幂等分支。"移除影响后续资源鉴权"同样无 `user_has_resource(..., "machine", ...)` 的前后翻转断言（现有对 machine 资源的唯一断言是 `test/container/test_rbac_container_role.py` 里"`container:manage` 不影响 machine 判定"的反例）。两列 `ondelete="CASCADE"` 此前无任何用例触发，现由用例直证。级联结论只在隔离 SQLite（已开 `PRAGMA foreign_keys=ON`）成立，未在真实 MySQL 验证。
