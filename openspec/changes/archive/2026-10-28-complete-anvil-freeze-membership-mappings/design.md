# Design

## Context

本变更覆盖 3 个既有表能力，但只交付规划产物（proposal / design / delta / test-plan），不交付实现：

- 主规格：`openspec/specs/backend--table-long-term-containers/spec.md`（10 Requirement / 24 Scenario）、`backend--table-container-disk-freeze-state/spec.md`（5 / 13）、`backend--table-user-container/spec.md`（9 / 26），合计 24 Requirement / 63 Scenario。
- 既有资产：`test/container/test_long_term_transitions.py`、`test_restore_long_term_capacity.py`、`test_freeze_days_consistency.py`、`test_container_disk_check_task.py`、`test_container_tasks_long_term.py`、`test_password_contracts.py`、`test_role_adversarial.py`、`test_account_wire_contracts.py`、`test_container_role_lock.py`、`test_rbac_container_role.py`；公共夹具为仓库级 `db_session` / `client`、`test/container/conftest.py` 的 `mock_node_send` 与 `test/factories.py`。
- sidecar：前两个能力没有 `test-plan.md`；`backend--table-user-container/test-plan.md` 是旧表格，除“读取有效记录”外均标“已覆盖”，但其中“协作角色变更”“第一步失败写失败 oplog”“绑定更新失败”“后台 guard 失败”“内部提升不触发旧 ROOT 遍历”等结论只覆盖了部分 THEN，不能直接照抄。
- 约束（来自任务与项目 config）：描述用中文，结构标题与 SHALL/MUST 保留英文；不写 `review.md` / `tasks.md`；不创建测试文件、不改主规格、主 sidecar、既有测试或业务实现；不读取 `.env`/密钥、不触达生产；不 commit/push。本变更唯一可写目录为 `openspec/changes/complete-anvil-freeze-membership-mappings/`。

## Goals / Non-Goals

**Goals**

1. 63 个 Scenario 全部落到 canonical 映射：Requirement → Scenario → Test/check（每行独立 `[X]`/`[ ]`）→ Assertion scope → 可选 Coverage note。
2. `[X]` 必须建立在逐段读过真实断言之上，说明测试实际断言了什么、未断言什么；不把旧 sidecar 的“已覆盖”或运行数字当证据。
3. 真实缺口只要能按既定规格补测，就写 `[ ]` 计划项并给出可执行断言意图；计划项全部指向 `test/container/test_anvil_freeze_membership.py`，本步不创建。
4. 三个 delta 的 MODIFIED Requirement 块与主规格逐字一致，Requirement 内不掺入本轮解释，使 sync 无净业务与文本变更。

**Non-Goals**

- 不修任何 app 缺陷，不改表、不做 unify/迁移/回填，不新增资格对象、Node 字段或持久化工作流。
- 不重构测试目录、不新增/修改共享 fixture、不用反射 ORM 列清单或源码字符串冒充行为断言。
- 不连接真实 Node/Docker/MySQL、不发送真实邮件、不执行真实 pause/delete；Node 仅作外部替身。
- 不验证 Windows 跨进程文件锁、多 Ctrl 主机或生产 MySQL 互斥；并发范围按规格限定为当前单 Linux Ctrl 主机。
- 不写执行结果、通过数、时间戳或运行台账；test-plan 只做映射。

## Decisions

1. **delta 用 MODIFIED 逐字复制，而不是 ADDED 或空 delta。**
   三个能力本轮都没有行为变化，但 test-plan 与 review 需要一个锚定到能力的规格载体。选择 MODIFIED + 完整 Requirement 块逐字复制，可同时满足“delta 必须包含完整 Requirement 块”的官方规则与“sync 后主规格无净变更”的约束。Requirement 文本、Scenario 的 WHEN/THEN、空行位置均按主规格原样保留；本轮意图只写在 proposal 与 design。

2. **以“断言范围”而不是“测试存在”判定 `[X]`。**
   逐条读测试代码：确认被测字段/分支，也确认它是否真的验证了 Scenario 的 THEN。例如 `test_role_change_semantics_contract` 只断言普通非 ROOT 互换的 Node 请求不含密码，并未读回绑定 role，因此“协作角色变更”不能整条标 `[X]`；`test_root_handover_steps_contract` 的失败分支只断言停止与目标未升 ROOT，并未断言失败 oplog，因此对应 Scenario 需要 `[ ]` 补失败日志。反过来，`test_restore_long_term_capacity.py` 已同时覆盖“带 used/limit 的拒绝、Node 未创建、快照未消费、失败留痕”，不再误报为缺口。

3. **缺口集中到一个新测试文件，按能力分段。**
   所有 `[ ]` 计划项写入 `test/container/test_anvil_freeze_membership.py`，文件内按 `long_term` / `disk_freeze` / `user_container` 分节，函数名用 `ltNN` / `dfsNN` / `ucNN` 前缀。复用既有 `db_session`、`client`、`mock_node_send`、`create_container_graph` / `create_user` / `bind_user_container` 等夹具，不新建 conftest、不改公共夹具。备选方案是按层拆多个文件，但与“限定单一文件、不重构目录”的约束冲突。

4. **持久化读回用新 session 按主键重开。**
   三个“读取有效记录”Scenario 都要求字段类型与空值语义。计划项先持久化最小行与完整行，再换新 session 按主键读取，断言稳定主键、可空字段的 `NULL`、Python 默认值/数据库默认值、`datetime` 插值窗口与文本/枚举往返；不在创建时的内存对象上断言，也不用展示名替代主键。

5. **常规行为测试只替换外部系统；重读场景单独标明为 seam 模拟。**
   长期切换、删除、恢复、冻结状态机与用户角色测试均使用隔离 SQLite；Node 通过既有 `mock_node_send` / 记录式 `node_comms.send` 替身捕获 wire，不连接真实 Node。权限拒绝用既有 `user_has_entity` / `user_has_resource` 依赖边界模拟，不断言源码里存在某个 guard 字符串。计划的“拒绝时冻结字段不变/失败审计”直接读持久化行与 `OperationLog`；不 mock 被测 service 的写入路径。例外是 LT06：它在既有 `_read_long_term_target` 命名 seam 上注入确定性重读事实，只证明给定事实后的守卫/no-op，不证明真实重读或并发；其范围与 fake SQLite 连接限界见决策 6 与 Risks。

6. **写入前重读只在既有命名 seam 上做确定性模拟。**
   既有 `test_single_session_reread_rejudges_changed_status` 通过替换 `services.container_tasks._read_long_term_target` 的返回结果模拟写入前事实变化，能证明守卫使用该读取结果，但不能证明真实并发重读。计划项 `test_anvil_lt06_reread_changed_facts_rejudged` 在同一命名 seam 上分别返回“模拟另一请求已把目标改成当前请求目标值”和“模拟目标已变为 `paused`”的事实，再走真实 `set_long_term_container` 守卫/落库路径，断言同目标不新增第二条标记、不写成功审计、冻结三元组不变，以及取消被 `container_paused` 拒绝。该用例不新增 seam，也不新增事务机制。fake SQLite `:memory:` + `StaticPool` 下不同 `Session` 共享同一 DBAPI 连接，不是独立事务；该测试只证明给定重读事实后的行为，不证明真实并发/提交交错。真实同容器重读/审计窗口与既有 Q67 的长期并发范围相邻，按父级要求优先关联 Q67/Global，不在本变更修 app 或改规格。

7. **ROOT 交接的失败步骤用 `OperationLog` 而非返回文案断言。**
   计划项补多旧 ROOT 降级失败、绑定写入失败、后台 guard 失败三类失败日志：断言失败步骤有对应 `update_collaborator_role` 失败行、目标未升 ROOT、已完成步骤保留，且日志不含密码。不修改既有 `test_root_handover_steps_contract` 或 `test_role_adversarial.py`。

## Risks / Trade-offs

- **逐字复制的 delta 在 sync 时可能被判为“无变更”。** 这是预期结果；若 CLI 把“无净变更”当错误，应在 sync 阶段显式说明并跳过写入，而不是为了制造变更去改 Requirement 文本。由 review 与父代理确认。
- **跨文件 locator 的稳定性。** 映射依赖 `test_password_contracts.py`、`test_role_adversarial.py`、`test_freeze_days_consistency.py` 等既有文件；若后续重构搬走测试，nodeid 会失效。缓解：nodeid 写全路径，并在 Assertion scope 中点明被复用的是服务/仓储/渲染边界。
- **POSIX 锁用例在 Windows 会跳过。** `test_container_role_lock_cross_process` 与 `test_forked_child_...` 依赖 `fcntl`/`fork`；本计划只声明它们在 POSIX 主机上有效，不宣称 Windows 跨进程互斥。当前并发承诺仍限定单 Linux Ctrl 主机。
- **长期并发边界（关联 Q67，仅记录）**：`services/container_tasks.py::set_long_term_container` 在 `session_scope` 开头读取一次 `container`/`existing`，随后 `_persist_long_term_state` 的 `add` 虽会再次查重，但 `changed` 与成功审计仍由初始 `existing` 决定；取消时 `remove` 幂等也不回传是否真的删除。若另一请求在读取后、写入前改变目标或状态，本请求可能写成功审计或沿用旧状态，未满足“重读后同目标不重复审计/状态重判”。现有 `test_single_session_reread_rejudges_changed_status` 只替换命名 seam 的读取结果，fake SQLite 的 Session 共享连接，不构成独立事务，因此不证明真实并发/提交交错。该同容器重读/审计窗口与 Q67 的长期并发范围相邻，按父级要求优先关联 Q67/Global；Q67 现文只描述跨容器长期配额超限，不能声称本问题已被 Q67 关闭。本变更不修改 app、不弱化规格、不新增跨进程锁/DDL/unify/资格 DTO，是否另开实现变更由父级决定。
- **补测项可能暴露更多问题。** 计划项只写规格要求的真实断言；若 apply 时某个计划项失败，按父级规则报告具体证据并停止，不通过删除断言、放宽 Coverage note 或改主规格来“转绿”。
