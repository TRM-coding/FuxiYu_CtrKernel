# Proposal

## Why

六个 RBAC 关联表 capability（`backend--table-auth-group-entities`、`backend--table-auth-groups`、`backend--table-user-groups`、`backend--table-machine-permissions`、`backend--table-user-images`、`backend--table-user-managed-users`）的主规格已经记录业务契约，但没有 Anvil 测试对账前沿：现有断言散落在 `test/user`、`test/machine`、`test/image` 与 `test/assertions.py`，`test/repository/` 下缺少这六张表的专属对账用例，无法确认每个 Requirement/Scenario 的覆盖边界。本次变更只做测试对账，把 14 个 Scenario 逐一映射到已有测试或显式缺口，供后续 apply 补齐。

## What Changes

- 为六个既有 capability 各写一份 spec delta，只包含 `MODIFIED Requirements`：完整复制当前主规格中的 Requirement 块（Requirement 标题、SHALL 语义、Scenario 名、WHEN/THEN 原文不变）。
- delta 中不复制主规格的 Purpose 与 Data model appendix，不新增表、字段、唯一约束或权限规则。
- 明确记录本变更不引入任何新业务行为：它是测试对账，不是规格变更；禁止为了迁就现有测试而削弱规格或改写 THEN。
- 在 `design.md` 记录对账方法与既有测试复用策略：优先复用现有断言；确认缺失的 THEN 规划到专属新文件 `test/repository/test_anvil_rbac_mapping.py`，不重构目录、fixture 或业务实现。
- 在 `test-plan.md` 按 `Requirement → Scenario → Test/check（[X]/[ ]） → Assertion scope → Coverage note` 逐场景完整枚举 14 个 Scenario，且不写入任何运行结果。
- Requirement 正文里的既有约束同样必须有映射行，不以 Coverage note 或"待决策项"替代：seed 幂等（默认 user/operator 组不增生、id 稳定）、无组用户按默认 user 组兜底、`machine_permissions`/`auth_group_entities`/`user_groups`/`user_images` 声明的 `ondelete="CASCADE"`、清空 operator 组后锁定实体保留、被授权查看详情时创建者归属不变。这些都在既有 Scenario 下补 `[ ]` 用例，不新增表、字段或权限规则。
- 持久化结构的对账按行为断言而非 ORM 声明反射：真实写入/读回后故意违约并以 `sqlalchemy.exc.IntegrityError` 断言约束生效；非空默认列要断言 NULL 拒绝必须用 `sqlalchemy.null()`；自增主键未赋值是合法行为，不作拒绝断言。
- 不写 `review.md` 与 `tasks.md`：两者由独立 reviewer 在 test-plan 完成后处理。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-auth-group-entities`: Requirement 与 Scenario 语义不变；delta 以 MODIFIED 完整块形式纳入对账范围，覆盖 3 个 Scenario（`读取有效记录`、`替换权限点`、`清空自身唯一管理组`）。
- `backend--table-auth-groups`: Requirement 与 Scenario 语义不变；delta 以 MODIFIED 完整块形式纳入对账范围，覆盖 2 个 Scenario（`读取有效记录`、`重复组名`）。
- `backend--table-user-groups`: Requirement 与 Scenario 语义不变；delta 以 MODIFIED 完整块形式纳入对账范围，覆盖 2 个 Scenario（`读取有效记录`、`更换用户权限组`）。
- `backend--table-machine-permissions`: Requirement 与 Scenario 语义不变；delta 以 MODIFIED 完整块形式纳入对账范围，覆盖 2 个 Scenario（`读取有效记录`、`重复授权`）。
- `backend--table-user-images`: Requirement 与 Scenario 语义不变；delta 以 MODIFIED 完整块形式纳入对账范围，覆盖 3 个 Scenario（`读取有效记录`、`整组更新名单`、`授权别人查看`）。
- `backend--table-user-managed-users`: Requirement 与 Scenario 语义不变；delta 以 MODIFIED 完整块形式纳入对账范围，覆盖 2 个 Scenario（`读取有效记录`、`查询管理范围`）。

## Impact

- 规格：`openspec/specs/` 下六个既有 capability 在 sync/archive 后被以“完全相同内容”重新写入，不产生语义差异。
- 测试：需要在 `test/repository/test_anvil_rbac_mapping.py` 新增缺口用例；既有 `test/user/test_rbac_api.py`、`test/machine/test_machine_tasks_permission.py`、`test/machine/test_machine_repository_integration.py`、`test/image/test_image_api.py`、`test/image/test_image_resource_scope.py`、`test/container/test_rbac_container_role.py`、`test/user/test_user_tasks_registration_code.py` 作为复用来源被引用；`test/machine/test_machine_api_permission.py` 仅作为"不触表"的对照被引用（成功/未找到分支用替身，认证/权限/缺参分支 API 层短路）。以上文件本次一律不修改。
- 业务代码、模型、迁移、fixture、测试目录结构：无影响。
- 运行影响：无，本次仅规划；规划阶段不执行测试、不记录运行结果。
