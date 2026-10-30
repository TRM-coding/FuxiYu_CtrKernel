# Design

## Context

六个 capability 的主规格已固化契约，但测试对账前沿缺失。调查结论（只读，未运行测试）：

- `test/repository/` 现有 8 个仓储测试文件，覆盖 authentications、container_cleanup_reminder、container_mount_cleanup、container_ssh_login、machine_image、operation_log、registration_code，**没有任何文件**针对 `auth_groups`、`auth_group_entities`、`user_groups`、`machine_permissions`、`user_images`、`user_managed_users`。
- RBAC 组/实体/用户绑定语义集中在 `test/user/test_rbac_api.py`（18 个用例，服务层 + API 层双路径）。
- 机器权限的仓储/服务真实行为在 `test/machine/test_machine_tasks_permission.py`、`test/machine/test_machine_repository_integration.py`；`test/machine/test_machine_api_permission.py` 的 14 个用例均不触表；成功/未找到分支用 `Add_machine_permission`/`Remove_machine_permission`/`List_machine_permissions` 替身，认证/权限/缺参分支在 API 层提前短路，只验证 API 契约。
- 镜像 CUSTOM 名单在 `test/image/test_image_api.py`（范围三态 × 名单）与 `test/image/test_image_resource_scope.py`（两层 RBAC 矩阵）。
- 受管用户范围只有 `test/container/test_rbac_container_role.py::test_container_role_resource_points` 的间接一行。
- `test/conftest.py` 的 `db_session` fixture 是 autouse：每个用例 `drop_all`/`create_all` 后重跑 `seed_rbac_defaults`、`seed_image_defaults`、`seed_system_settings_defaults`，因此内置 `user`/`operator` 组与镜像内置模板在每个用例里都存在。
- `pytest.ini` 默认 `-m "not integration and not legacy"`，安全套件禁止非 SQLite 数据库（`conftest._assert_sqlite_database_uri`）。
- `extensions._make_engine` 在 SQLite 连接的 `connect` 事件里执行 `PRAGMA foreign_keys=ON`（2026-09 决策，与生产 MySQL 行为对齐），测试与生产共用同一个 `_make_engine`。因此**外键、`ON DELETE CASCADE`、非空与唯一约束在隔离测试里都是可真实触发、可真实断言的行为**，不属于"环境不可测"。

约束：本次只做对账规划，不改测试、业务、主规格，不运行测试，不记录运行结果。

## Goals / Non-Goals

**Goals:**

- 为 6 个 capability、14 个 Scenario 建立 `Requirement → Scenario → Test/check → Assertion scope → Coverage note` 的完整映射。
- 让每条 Requirement 正文里的既有业务约束（seed 幂等、无组用户默认 user 组兜底、声明式 `ondelete="CASCADE"`、operator 锁定实体保留、授权不转移归属）都有可执行的映射行，而不是被 Coverage note 或"待决策项"顶替。
- 明确区分「已有确认断言」与「缺口」：只有 locator 与断言都核对过的才标 `[X]`。
- 缺口收敛到一个专属新文件 `test/repository/test_anvil_rbac_mapping.py`，并给出每个待补用例的断言范围（不写实现代码）。

**Non-Goals:**

- 不改任何业务实现、模型、迁移、fixture、`conftest.py`、测试目录结构或既有测试文件。
- 不为缺口新增业务行为、表、字段、权限规则；不削弱规格以迁就现有测试。
- 不重复既有测试已断言的结论（例如 seed 的清理口径已由 `test_seed_prunes_stale_entity_bindings` 覆盖，补测只补"重复调用不增生"）。
- 不写 `review.md`、`tasks.md`（由独立 reviewer 与后续 apply 处理）。
- 不在本阶段运行测试，不把运行结果写入计划。

## Decisions

### D1：delta 采用 MODIFIED 完整 Requirement 块，语义零差异

测试对账需要让 14 个 Scenario 出现在 change 的 spec delta 里，才能被 test-plan 与 review 逐条引用。做法是每个 capability 一份 `specs/<capability-path>/spec.md`，只含 `## MODIFIED Requirements`，逐字复制主规格的 Requirement 块（标题、SHALL 语义、Scenario 名、WHEN/THEN 原文），不复制 `## Purpose` 与 `## Data model appendix`。

- 备选：用 `ADDED` 新增"测试对账要求"——被否决，会凭空造出业务需求。
- 备选：delta 里缩写 Requirement 文本——被否决，`MODIFIED` 不允许部分内容，且会引入语义漂移。
- 校验手段：已按行比对 delta 的 `## MODIFIED Requirements` 与主规格的 `## Requirements`，6/6 完全一致（忽略空行与行首尾空白）。主规格与 delta 的业务原文在本轮修订中均未改动。

### D2：既有测试复用优先，缺口集中到一个新文件

映射顺序：先找该 Scenario 的 THEN 与所挂 Requirement 正文的约束是否已被现有用例断言；能覆盖的标 `[X]` 并写明断言到哪一步；不能覆盖的标 `[ ]` 并规划到 `test/repository/test_anvil_rbac_mapping.py`。

选 `test/repository/` 的理由：缺口绝大多数是"表级/仓储级直证"（按主键读取、约束行为、级联删除、幂等落库、去重集合、受管范围），与既有 `test/repository/` 的定位一致（`db_session` + 模型 + 仓储直调）。新建单一文件而不是散落到 `test/user`/`test/machine`/`test/image`，避免改动既有目录归属与 fixture 组织。

- 备选：补进各自域目录——被否决，会形成"同一批对账用例散在四处"，且更易触发对既有文件的改动。
- 新文件遵循现有相对导入约定（`from ...models...` / `from ...repositories...` / `from ..factories import ...`），不新增 fixture、不改 `conftest.py`。

### D3：`[X]` 的判定标准

只有同时满足才算 `[X]`：(a) locator 精确到 `文件::用例名`；(b) 该用例的断言语句确实覆盖所列可观察面，且断言不是 monkeypatch 替身返回值的回声。仅"调用了相关服务"或"断言了状态码"不算。

Assertion scope 里出现的每一个断言都必须能在所列 locator 的代码里找到；找不到的断言要么删除，要么挪进一条 `[ ]` 拟补用例。典型纠正：`locked_entity_codes` 与 `total_number == 0` 在既有用例中的实际归属范围被逐条收紧，不外推到未断言的观众类别或字段。

### D4：约束断言必须是行为断言，不能反射 ORM 声明

"持久化结构"类 Scenario 的 THEN 讲的是数据库行为。阅读 `db.Column(... primary_key=True/nullable=False)` 只能证明声明存在，不能证明约束生效。因此所有 `[ ]` 用例改成：真实写入 → 真实读回 → 故意违反约束 → `flush()`/`commit()` 断言 `sqlalchemy.exc.IntegrityError`，每个违约断言后 `session.rollback()` 保持用例隔离。模型声明只作为补充说明，不作为覆盖依据。

覆盖的约束类别：主键/复合主键重复、非空、唯一配对、外键引用、`ON DELETE CASCADE`。

### D5：NULL 与自增主键的两条硬规则

- **NULL**：非空且有列默认值的列（`user_images.granted_at`、`user_managed_users.granted_at`）显式传 `None` 会被 ORM 用列默认值补齐，不会报错；要断言"数据库拒绝 NULL"必须用 `sqlalchemy.null()` 真正让 INSERT 写 DB NULL。
- **自增主键**：`id` 未赋值由数据库补齐是**合法行为**。任何用例不得把"省略 `id`"断言成应被拒绝；只有显式写入冲突主键（重复行）才断言 `IntegrityError`。

### D6：级联与"无外键"按声明事实分别处理

- `auth_group_entities.group_id`、`user_groups.user_id/group_id`、`machine_permissions.machine_id/user_id`、`user_images.user_id/image_id` 在模型里声明了 `ForeignKey(..., ondelete="CASCADE")`，且 SQLite 已开 `PRAGMA foreign_keys=ON`，因此规划真实的删除父行 → 断言关联行消失的用例（双向的，两个外键方向都测）。
- `user_managed_users.manager_user_id/managed_user_id` 是裸 `db.Integer`，主规格数据附录同样未记 ForeignKey，因此不规划外键/级联断言。这是模型与规格的声明事实，不是环境限制。

### D7：`Assertion scope` 写"断言什么"，`Coverage note` 写"没覆盖什么"

`Assertion scope` 描述已有/拟补用例实际能证明的可观察事实（含既有用例只覆盖一半的说明）；`Coverage note` 只留真实局限：既有用例被 monkeypatch 掉从而不触表、某条 THEN 只能间接取证、SQLite 与 MySQL 的约束错误差异等。不写"全部覆盖"之类结论，也不把可实现的对账工作留成"待决策"。

## Risks / Trade-offs

- **风险：`[X]` 高估。** 缓解：D3 的判定标准 + 每条 `[X]` 都写明既有用例断言到哪一步，并把超出实际断言的表述删掉或移到拟补用例。
- **风险：新文件与既有约定冲突。** 缓解：只新增 `test/repository/` 下一个文件，复用 `db_session`/`ensure_auth_users` 与 `test/factories.py`，不新增 fixture、不改 `conftest.py`。
- **风险：约束与级联断言依赖 SQLite 行为。** 缓解：仓库已统一开启 `PRAGMA foreign_keys=ON` 与生产 MySQL 对齐，结论以隔离安全套件为准；SQLite 与 MySQL 在约束错误类型/文本、检查时机上的差异在 test-plan 顶部与涉及处如实限界，不承诺 MySQL 等价，也不需要真实 MySQL。
- **风险：某个约束在 SQLite 上的错误类型与预期不同。** 计划只承诺"抛 `sqlalchemy.exc.IntegrityError`"，不承诺具体驱动错误码；若某条在 apply 阶段行为不符，应按实际行为回写 Coverage note 而不是放宽断言。
- **权衡：不运行测试。** 计划中的 `[ ]` 用例未经验证，实际可写性留给 apply 阶段确认；计划不承诺它们必然通过。
- **权衡：MODIFIED 零差异 delta 在 sync 时重写主规格文件。** 因文本逐字一致，sync 后主规格内容不变（仅文件被重写）；若后续 review 对"对账用 MODIFIED"有异议，替代做法是在同一 delta 内调整表述方式，而不是改业务原文。
- **权衡：范围严格限定 6 个 capability。** 相关但不在范围内的能力（如 `backend--table-users`、`backend--table-machines`、`backend--table-images`）不在本次对账，其 Scenario 不纳入计数。
