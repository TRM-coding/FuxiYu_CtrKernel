# Proposal

## Why

Ctrl 的 `backend--table-long-term-containers`、`backend--table-container-disk-freeze-state` 与 `backend--table-user-container` 三个能力共 63 个 Scenario，目前只有零散、口径不一的测试线索：前两个能力没有主规格旁 sidecar；`backend--table-user-container` 的旧表把“读取有效记录”标为待复核，其余行虽标“已覆盖”，但其中若干结论只凭测试名或单个断言得出，无法直接支撑 Requirement 正文的全部 THEN。上一轮规划尝试（`b74a900c`）已明确以 `quota_exceeded` 终止且没有留下产物，本轮按官方 fallback 重新规划。

本变更只做规划补齐：把 63 个 Scenario 逐条对到真实测试断言，把确实缺失的断言写成待建计划项。它不改变任何业务行为，也不把“文件存在”或“测试名”当作覆盖证据。

## What Changes

- 为 3 个能力共 63 个 Scenario 建立 canonical 映射：Requirement → Scenario → Test/check 嵌套勾选 → Assertion scope → 可选 Coverage note。
- 对既有测试做断言级复核：持久化读回按主键重开；服务/API 行为读真实断言；不凭 test 名、旧 sidecar 的运行数字或“文件存在”判覆盖。
- 把确认存在的断言标为 `[X]`；把未确认或缺失的部分标为 `[ ]`，计划项全部落在新文件 `test/container/test_anvil_freeze_membership.py`，本步不创建该文件。
- 计划补测重点：三个能力的持久化读回；长期切换的额外客户端字段、403/404、拒绝时冻结字段与失败审计、命名 seam 上的重读事实模拟；冻结状态在恢复后重新起算；用户绑定的角色变更落库；ROOT 交接失败步骤的失败审计与不继续提拔。
- 三个能力的 delta 只逐字承载原完整 Requirement 块（MODIFIED），Requirement 内不插入本轮说明句；因此 sync 后主规格应无净业务与文本变更。本变更不写 `review.md`、`tasks.md`、测试文件、主规格、主 sidecar，也不改业务代码。
- 已观察到一处需要父级决策的实现边界：`set_long_term_container` 只在事务开头读取一次既有事实，现有“重读”测试通过替换命名 seam 的读取结果模拟；真实并发/提交交错未被证明。该同容器重读/审计窗口与既有 Q67 的长期并发范围相邻，按父级要求优先关联 Q67/Global，不新增跨进程锁、DDL、unify、资格 DTO；本变更只记录并在 test-plan 中标缺口，不修 app、不弱化规格。

## Capabilities

### New Capabilities

- 无。本变更不引入新的能力。

### Modified Capabilities

- `backend--table-long-term-containers`：无行为变更。delta 逐字复制 10 个既有 Requirement 连同 24 个 Scenario，仅作为 test-plan 映射锚点。
- `backend--table-container-disk-freeze-state`：无行为变更。delta 逐字复制 5 个既有 Requirement 连同 13 个 Scenario。
- `backend--table-user-container`：无行为变更。delta 逐字复制 9 个既有 Requirement 连同 26 个 Scenario。

## Impact

- 规格与台账：新增 `openspec/changes/complete-anvil-freeze-membership-mappings/` 下的 `proposal.md`、`design.md`、3 个 delta `spec.md`、`test-plan.md`。
- 代码与测试：本变更不修改任何业务代码、表结构、API、主规格、主 sidecar 或既有测试；后续 apply 若被批准，只新增 1 个测试文件。
- 数据与依赖：无迁移、无新依赖、无配置或全局 default schema 变更；测试仍使用隔离 SQLite，Node 只作外部替身，不连接真实邮件、Docker、Node 或生产库。
- 与并行批次的关系：本变更不读写其他 change 目录、其他批次的测试文件或共享 fixture。
