# Proposal

## Why

`backend--table-containers`、`backend--table-deleted-container-restore-snapshot`、`backend--table-container-cleanup-reminders`、`backend--table-container-mount-cleanup` 四个能力共 94 个 Scenario 目前缺少可 review 的 canonical 场景到断言映射：`containers` 主 sidecar 仍是“待复核”的旧表格与运行台账，另外三个能力没有 sidecar；部分现有测试只覆盖成功形状或同会话对象，不能直接证明 Requirement 正文的默认值、空值、路径、来源、脱敏与失败分支。本变更只补齐规划与映射，不改变任何业务行为、表结构或主规格语义。

## What Changes

- 为四个能力共 94 个 Scenario 建立 canonical 映射：Requirement → Scenario → Test/check（`[X]`/`[ ]`）→ Assertion scope → 可选实际限界 Coverage note。
- 逐条阅读现有测试断言，按“真实可观察断言”判定 `[X]`；不以测试名、反射或源码字串替代行为证据。对只覆盖部分 THEN 的条目明确写出缺口，不把既有覆盖误报为完整覆盖。
- 将现有断言无法覆盖的缺口集中规划到新文件 `test/container/test_anvil_cleanup_contracts.py`；缺口只描述可执行的断言意图，不写运行结果台账。
- 四份 delta 仅以 `MODIFIED` 逐字复制原 Requirement 块（含全部 Scenario 与正文），作为映射锚点；Requirement 内不插入本轮解释句，sync 后主规格应无业务与文本变化。
- 不改主规格、主 sidecar、现有测试、应用代码、共享 fixture、依赖、配置、数据库、CI、hooks、skills 或 secrets；不写 `review.md` 与 `tasks.md`。
- 记录 Q74 已定业务边界：删除重置冻结/宽限，恢复按新建处理且不旁路宽限；本变更不改表、不改该行为。Q74 在 test-plan 中落到 `test/container/test_long_term_transitions.py` 的既有用例（目标冻结行删除、其他容器不变、无冻结行正常、事务回滚、重复删除幂等、API/cleanup 删除、恢复不继承冻结/宽限），不新增字段、表、DTO 或协议。
- 记录父 Global Q81/Q82：Q81 为提醒表单容器单行与逐收件人实现的冲突，Q82 为宿主路径 400 与 `not_found` 分支的冲突；本 change 只暂缓各自断言并保留现有业务返回，不改 app、主规格或 sidecar。

## Capabilities

### New Capabilities

- 无。本变更不引入新能力。

### Modified Capabilities

- `backend--table-containers`：无行为变更。delta 逐字复制 24 个既有 Requirement（73 个 Scenario），仅作为 test-plan 映射锚点。
- `backend--table-deleted-container-restore-snapshot`：无行为变更。delta 逐字复制 7 个既有 Requirement（17 个 Scenario），仅作为映射锚点。
- `backend--table-container-cleanup-reminders`：无行为变更。delta 逐字复制 2 个既有 Requirement（2 个 Scenario），仅作为映射锚点。
- `backend--table-container-mount-cleanup`：无行为变更。delta 逐字复制 2 个既有 Requirement（2 个 Scenario），仅作为映射锚点。

## Impact

- 规格与台账：新增 `openspec/changes/complete-anvil-container-cleanup-mappings/` 下的 `proposal.md`、`design.md`、4 份 delta `spec.md` 与 `test-plan.md`。
- 代码与测试：本变更的规划范围不修改任何业务代码、表结构、API、主规格或主 sidecar；实现阶段只新增一个测试文件 `test/container/test_anvil_cleanup_contracts.py`。
- 数据与依赖：无迁移、无新依赖、无配置或全局 defaultSchema 变更；测试只使用隔离 SQLite、Node 通信替身与假快照数据，不能真实清理目录。
- 并行批次：本变更与已完成/进行中的第 1–4 批文件集合不重叠；本变更不读写其目录。
