# Tasks

> 实现边界：只新建 `test/container/test_anvil_freeze_membership.py`，只实现已审 test-plan 的 19 个 unique planned test；不改业务代码、模型、schema、DB、CI、config、旧测试或共享 fixture。若实现需要改变已审的 Scenario 映射、locator、Assertion scope 或 Coverage note，停止并回到 fresh review，不自行弱化断言。真实缺陷只记录并报告父级。

## 1. long-term 能力测试（lt01–lt08）

- [x] 1.1 创建 `test/container/test_anvil_freeze_membership.py` 的测试骨架与本地 helper：隔离 SQLite、外部 Node 替身、API auth helper、长/freeze 状态快照 helper；不新增 conftest 或共享 fixture。验证：文件可被 pytest 收集，且不触发真实 HTTP/SMTP/Node。
- [x] 1.2 实现 `test_anvil_lt01_long_term_readback_contract`，覆盖 `backend--table-long-term-containers` / `long_term_containers 持久化结构` / `读取有效记录`：新 session 按主键读回带/不带 `created_by_user_id` 的行，断言类型、NULL、`created_at` 与单行。验证：由 1.9 命令覆盖。
- [x] 1.3 实现 `test_anvil_lt02_extra_client_fields_do_not_change_guard`，覆盖 `长期切换由服务端静态守卫裁决` / `不同客户端入口不能绕过`：配额满、磁盘硬超限、冻结中取消三场景的基线请求与附加客户端字段请求得到相同状态/reason，标记/冻结/审计不变。验证：由 1.9 命令覆盖。
- [x] 1.4 实现 `test_anvil_lt03_permission_and_not_found_contract`，覆盖 `既有权限与状态矩阵保留`：API 缺实体权限、缺 `container:root`、缺机器访问权分别为 403 对应 reason，容器不存在为 404；无状态/审计副作用。验证：由 1.9 命令覆盖。
- [x] 1.5 实现 `test_anvil_lt04_guard_rejections_keep_freeze_and_audit`，覆盖 `启用长期检查 root 用户配额` / `配额已满时拒绝启用`、`启用长期检查磁盘硬限制` / `已知用量达到硬限制时拒绝`、`同目标值请求无额外副作用` / `切换失败保留原标记`、`错误原因与既有契约稳定` / `失败审计不改变状态`：预置冻结行后配额/磁盘拒绝仍保持三元组，并写 `SET_LONG_TERM` 失败审计。验证：由 1.9 命令覆盖。
- [x] 1.6 实现 `test_anvil_lt05_cancel_rejection_keeps_freeze_and_writes_failure`，覆盖 `切换失败保留原标记`、`失败审计不改变状态`、`取消长期按实际状态拦截冻结` / `冻结中取消被拒绝`：paused 取消保持长期标记/冻结三元组，API 级失败审计存在。验证：由 1.9 命令覆盖。
- [x] 1.7 实现 `test_anvil_lt06_reread_changed_facts_rejudged`，覆盖 `实际写入前重读既有事实` / `重读后发现目标已变化`、`重读后发现状态已冻结`：仅在既有 `_read_long_term_target` 命名 seam 注入确定性事实，断言同目标 no-op 与 paused 拒绝；不得声称真实并发/独立事务。验证：由 1.9 命令覆盖。
- [x] 1.8 实现 `test_anvil_lt07_marker_removal_restores_short_term_cleanup` 与 `test_anvil_lt08_repeated_cancel_keeps_container_valid`，覆盖 `重复标记` 的“移除后清理恢复”和 `重复取消不产生删除` 的容器有效性/无删除审计。验证：由 1.9 命令覆盖。
- [x] 1.9 运行 long-term 8 个定向测试，保存 raw 输出与 exit 到 `E:/AI/Fuxi_audit_artifacts/anvil-rollout-2026-10-28/ctrl-batch-6/targeted-long-term.log`；若失败先判断是实现/测试问题还是真实业务缺陷，不修业务、不放宽断言。

## 2. freeze-state 能力测试（dfs01–dfs02）

- [x] 2.1 实现 `test_anvil_dfs01_freeze_readback_contract`，覆盖 `backend--table-container-disk-freeze-state` / `container_disk_freeze_state 持久化结构` / `读取有效记录`：新 session 按主键读回默认/完整/显式 NULL 行，断言类型、默认值、`grace_until` 空值与 `created_at`。验证：由 2.3 命令覆盖。
- [x] 2.2 实现 `test_anvil_dfs02_restore_then_new_freeze_starts_new_cycle`，覆盖 `恢复新建不继承冻结周期` / `Q72 累计不被恢复续期`：删除/恢复后无冻结行，再由调度真实触发硬超限冻结，断言新锚点晚于旧锚点、`deferral_seconds=0`、`grace_until=None`。验证：由 2.3 命令覆盖。
- [x] 2.3 运行 freeze-state 2 个定向测试，保存 raw 输出与 exit 到 `E:/AI/Fuxi_audit_artifacts/anvil-rollout-2026-10-28/ctrl-batch-6/targeted-disk-freeze.log`；不连接真实 Node/邮件。

## 3. user-container 能力测试（uc01–uc08）

- [x] 3.1 实现 `test_anvil_uc01_user_container_readback_contract`，覆盖 `user_container 持久化结构` / `读取有效记录`：新 session 按复合主键读回完整/最小绑定，断言主键、role、granted_at、public_key NULL/str、username。验证：由 3.9 命令覆盖。
- [x] 3.2 实现 `test_anvil_uc02_update_role_persists_binding`，覆盖 `user_container 生产职责与生命周期` / `协作角色变更`：真实 `update_role` 后读回绑定 role/username，Node wire 无密码，旧/新角色成功审计存在。验证：由 3.9 命令覆盖。
- [x] 3.3 实现 `test_anvil_uc02_user_binding_changes_keep_other_bindings`，覆盖 `旧 ROOT 降为 ADMIN 保留独立账号密码`：降级后旧绑定为 ADMIN/系统用户名，其他 collaborator 绑定仍存在且 role/username 不变。验证：由 3.9 命令覆盖。
- [x] 3.4 实现 `test_anvil_uc07_direct_root_demotion_api_returns_credential`，覆盖 `ROOT 交接的受理与凭据` / `直接 ROOT 降 ADMIN 也返回独立账号密码`：HTTP 200、accepted、no-store、恰一项凭据、Node password 与绑定一致。验证：由 3.9 命令覆盖。
- [x] 3.5 实现 `test_anvil_uc08_handover_preflight_api_maps_409`，覆盖 `目标未绑定或用户名不可用时不生成密码`：API 409 对应 reason、无 credentials、无 Node、密码生成器未调用。验证：由 3.9 命令覆盖。
- [x] 3.6 实现 `test_anvil_uc03_multi_root_demotion_failure_writes_failure`，覆盖 `ROOT 交接的逐步执行与失败边界` / `多个旧 ROOT 中任一降级失败也不提拔目标`：失败步骤有 `update_collaborator_role` 失败日志、无目标 ROOT 成功日志、日志不含密码。验证：由 3.9 命令覆盖。
- [x] 3.7 实现 `test_anvil_uc04_binding_failure_writes_failure_oplog` 与 `test_anvil_uc05_background_guard_failure_writes_failure_oplog`，覆盖 `绑定更新失败也停止后续步骤`、`后台最小 guard 复核失败只记失败`：失败 oplog 存在、无该步成功日志、角色状态不前进。验证：由 3.9 命令覆盖。
- [x] 3.8 实现 `test_anvil_uc06_delete_user_internal_promotion_failure_no_retry`，覆盖 `删除用户内部 ROOT 提升的密码兼容` / `内部提升失败不回退弱密码`：失败后删除返回 False、用户/绑定保留、无第二次弱/空密码调用、日志不含密码或 Node 原始请求/响应体。验证：由 3.9 命令覆盖。
- [x] 3.9 运行 user-container 9 个定向测试，保存 raw 输出与 exit 到 `E:/AI/Fuxi_audit_artifacts/anvil-rollout-2026-10-28/ctrl-batch-6/targeted-user-container.log`；不修改既有联调测试。

## 4. 定向汇总、相关回归与验证

- [x] 4.1 运行新文件的全部 19 个 unique test，保存 raw 输出与 exit 到 `E:/AI/Fuxi_audit_artifacts/anvil-rollout-2026-10-28/ctrl-batch-6/targeted-all-19.log`；断言数量与 test-plan 的 19 个 unique locator 一致。
- [x] 4.2 运行合理相关回归（long-term/freeze/user 角色的既有定向文件，不跑全 Ctrl）：`test_long_term_transitions.py`、`test_restore_long_term_capacity.py`、`test_freeze_days_consistency.py`、`test_container_disk_check_task.py`、`test_container_tasks_long_term.py`、`test_container_cleanup_task.py`、`test_container_api_long_term.py`、`test_password_contracts.py`、`test_role_adversarial.py`、`test_account_wire_contracts.py`、`test_container_role_lock.py`、`test_rbac_container_role.py`；raw 输出与 exit 保存到 `ctrl-batch-6/related-regression.log`。
- [x] 4.3 运行 `openspec validate complete-anvil-freeze-membership-mappings --strict` 并保存到 `ctrl-batch-6/openspec-validate.log`；确认三份 delta 仍逐字不变、test-plan 的 19 个 locator 未改语义、未创建 `tasks` 之外的新业务文件。若真实缺陷需改已审语义，停止回审。

## Workflow follow-up

- official `openspec-verify-change` advisory（不创建 `verify.md`），记录 actual coverage/limitations。
- 精确 no-op sync 三个 capability，保持 27 个主 spec SHA 不变。
- official sync 成功后用 `anvil-test-plan` 维护 3 个主 test-plan sidecar。
- 北京时间 2026-10-28 official archive；同步归档内 checkbox/未创建等机械状态，manual/缺口如实保留。
- 由父级执行 Git commit/push；本任务不 commit。
