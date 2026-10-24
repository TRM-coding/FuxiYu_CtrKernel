# user_container 测试覆盖

规格：[spec.md](spec.md)

## 当前场景映射

| Requirement | Scenario | 覆盖状态 | 测试位置与 nodeid/参数 | 验证范围或缺口 |
| --- | --- | --- | --- | --- |
| user_container 持久化结构 | 读取有效记录 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只审计角色/密码/ROOT 交接契约。 |
| user_container 生产职责与生命周期 | 协作角色变更 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_role_change_semantics_contract | 断言普通非 ROOT 互换无密码、ROOT 降 ADMIN 独立账号密码与绑定 username。 |
| user_container 生产职责与生命周期 | 普通非 ROOT 角色互换不改密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_role_change_semantics_contract | 断言普通非 ROOT 互换无密码、ROOT 降 ADMIN 独立账号密码与绑定 username。 |
| user_container 生产职责与生命周期 | 旧 ROOT 降为 ADMIN 保留独立账号密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_role_change_semantics_contract；::test_root_handover_contract | 断言 Node 降级使用独立账号密码、绑定改为 ADMIN/系统用户名；交接路径同样断言。 |
| 外部 ROOT 请求统一完整交接 | flag 省略、false、true 执行同一完整交接 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_update_role_root_always_handover_contract[omitted]；[false]；[true] | 三种请求都走 handover：两份不同凭据、旧 ROOT 降 ADMIN、目标唯一 ROOT、Node 先 admin 后 root 且无 transfer_root。 |
| 外部 ROOT 请求统一完整交接 | 多个旧 ROOT 逐个降级后目标成为唯一 ROOT | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_contract | 断言历史多 ROOT 的 N+1 凭据、逐个 admin 后 root、旧 ROOT 均 ADMIN、最终只有目标 ROOT。 |
| ROOT 交接的受理与凭据 | 正常单个旧 ROOT 交接返回两项不同登录名 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_update_role_root_always_handover_contract[omitted]、[false]、[true]；::test_root_handover_contract | 断言 root + 旧 ROOT 系统用户名两项、密码不同、Cache-Control: no-store。 |
| ROOT 交接的受理与凭据 | 旧 ROOT 降 ADMIN 的独立账号使用其系统用户名 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_contract | 断言旧 ROOT 绑定 username=root 时，降级 wire user_name 与凭据 login_name 使用用户表系统用户名。 |
| ROOT 交接的受理与凭据 | 直接 ROOT 降 ADMIN 也返回独立账号密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_role_change_semantics_contract | 断言 ROOT→ADMIN 生成一项独立账号凭据、wire 使用 config.password、绑定改为 ADMIN/系统用户名。 |
| ROOT 交接的受理与凭据 | 机器或容器不可用时不生成密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_preflight_contract | 断言容器离线/机器离线时抛对应 reason，密码生成器未调用且无 Node 请求。 |
| ROOT 交接的受理与凭据 | 目标未绑定或用户名不可用时不生成密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_preflight_contract | 断言目标未绑定为 target_not_bound、旧 ROOT 系统用户名不可用为 invalid_root_owner_account；均不生成密码且无 Node 请求。 |
| ROOT 交接的受理与凭据 | 调用者先被降级也不影响后续步骤 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_contract | 断言调用者本身是旧 ROOT 时后台仍完成旧 ROOT 降级与目标升 ROOT。 |
| ROOT 交接的逐步执行与失败边界 | 两步成功各记一条真实日志 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言两步成功各一条 update_collaborator_role 成功日志，绑定分别 ADMIN/系统用户名与 ROOT/root，日志不含密码。 |
| ROOT 交接的逐步执行与失败边界 | 第一步失败不继续第二步 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言第一个旧 ROOT 降级失败后只发一次 Node，目标保持非 ROOT。 |
| ROOT 交接的逐步执行与失败边界 | 多个旧 ROOT 中任一降级失败也不提拔目标 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言前一个旧 ROOT 已降 ADMIN、后一个降级失败时停止，仅两次 admin wire，目标保持 COLLABORATOR。 |
| ROOT 交接的逐步执行与失败边界 | 第二步失败不伪报整体成功 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言旧 ROOT 已 ADMIN 保留、目标不记 ROOT 成功、写失败日志。 |
| ROOT 交接的逐步执行与失败边界 | 绑定更新失败也停止后续步骤 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言第二步绑定更新失败后目标保持非 ROOT、旧 ROOT 保留 ADMIN、无后续步骤。 |
| ROOT 交接的逐步执行与失败边界 | 后台最小 guard 复核失败只记失败 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract | 断言后台执行前容器离线则不调用 Node，目标保持非 ROOT。 |
| ROOT 交接的逐步执行与失败边界 | Node 只改指定目标 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_root_handover_steps_contract；../../../test/container/test_account_wire_contracts.py::test_ctrl_legacy_transfer_root_never_enters_node_wire | 断言 Ctrl 逐步调用单目标 update_role，Node wire 不含 transfer_root 或额外目标。 |
| ROOT 交接的身份预检与获锁复核 | 已受理的同容器交接冲突以 stale 结束 | 已覆盖 | ../../../test/container/test_role_adversarial.py::test_repeated_handover_to_same_target_keeps_one_root_and_stales_second；::test_interleaved_handover_to_two_targets_must_not_leave_two_roots | 断言后执行任务在任何 Node 前 `root_handover_stale` 退出，旧响应密码不入 wire/日志，最终唯一 ROOT。 |
| ROOT 交接的并发串行化与已受理冲突 | 真实线程同容器并发只允许一个交接完成 | 已覆盖 | ../../../test/container/test_role_adversarial.py::test_threaded_handover_barrier_keeps_one_root_and_attributes_commands | barrier 后两真实线程竞争同容器 RLock/文件锁；恰好一个成功、一个 stale，零额外 Node，最终唯一 ROOT，Node 命令只归属胜出凭据。 |
| ROOT 交接的并发串行化与已受理冲突 | 同机独立进程竞争同一容器锁 | 已覆盖 | ../../../test/container/test_role_adversarial.py::test_container_role_lock_cross_process；::test_container_role_lock_nested_reentrant_and_empty_marker | 独立子进程持锁时另一子进程阻塞；释放后获得；嵌套同线程可重入；锁文件为空标记。 |
| ROOT 交接保留逐步提交事实 | 机器中途维护或 DB/审计异常不整批回滚 | 已覆盖 | ../../../test/container/test_role_adversarial.py::test_machine_offline_between_steps_keeps_first_committed_fact；::test_db_or_audit_exception_does_not_rollback_committed_step[binding/audit] | 第一步 ADMIN 绑定与成功日志保留；下一步 fresh guard 失败或 DB/审计异常只影响该步。 |
| ROOT 交接的身份预检与获锁复核 | Node 不可用用户名在预检被拒 | 已覆盖 | ../../../test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[target-root/target-leading-dash/old-root-leading-dash] | 目标 `root`/前导 `-`、旧 ROOT 前导 `-` 在生成密码/200/Node 前被拒。 |
| 删除用户内部 ROOT 提升的密码兼容 | 删除用户内部提升生成随机 root 密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_delete_user_root_password_contract | 断言内部同步提升传非默认随机 config.root_password、不触发 Web 交接编排。 |
| 删除用户内部 ROOT 提升的密码兼容 | 内部提升失败不回退弱密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_delete_user_root_password_contract | 断言内部提升失败时删除失败、用户保留、不回退 {user_name}123。 |

## 附加合同证据（非新增 Scenario）

- 旧 `transfer_root` 仅为兼容输入，不参与路由：`../../../test/container/test_password_contracts.py::test_update_role_root_always_handover_contract[omitted]`、`[false]`、`[true]`、`::test_update_role_legacy_transfer_root_does_not_affect_non_root`；`UpdateRoleRequest.updated_role` 公开大写枚举与非法角色 400：`../../../test/container/test_container_api_collaborators.py::test_update_role_api_rejects_unknown_role_before_node`、`::test_collaborator_openapi_role_enums_are_public_uppercase`。
- 凭据响应不落密码：`../../../test/container/test_password_contracts.py::test_update_role_root_always_handover_contract` 扫描 `OperationLog` 与 `CTRL_LOG_DIR` 下日志文件；`::test_password_persistence_contract` 断言模型无密码列且日志不含密码。
- 真实 Node Pydantic/HTTP wire：`../../../test/container/test_account_wire_contracts.py`，本轮 13 passed；大写角色被 Node 422 拒绝，helper 小写 wire 被接受且 no-store，`transfer_root` 不进入 wire。
- 同机锁 helper 证据：`../../../test/container/test_role_adversarial.py::test_container_role_lock_nested_reentrant_and_empty_marker`（RLock 嵌套重入、空标记）与 `::test_container_role_lock_cross_process`（独立进程阻塞/释放）；锁文件在私有临时目录，不写业务状态。

## 对抗性补测（2026-10-24，先红后绿；双 ROOT 已收住）

文件：`../../../test/container/test_role_adversarial.py`。默认用显式后台队列固定顺序；另有真实线程 + barrier 与独立子进程文件锁用例。结果均可重复。

| 探针 | 测试 | 本轮结果 | 说明 |
| --- | --- | --- | --- |
| 同一目标重复受理 | `::test_repeated_handover_to_same_target_keeps_one_root_and_stales_second` | 通过 | 第一次任务完成；第二次持锁发现 ROOT/目标角色/用户名已变，stale 退出且零 Node；最终唯一 ROOT，第二次响应密码不入 wire/日志。 |
| 两个不同目标交错受理 | `::test_interleaved_handover_to_two_targets_must_not_leave_two_roots` | 通过 | 固定顺序“降 A → 升 B → 降 A → 升 C”；第二个任务在降 A 前 stale 退出，最终只有 B 为 ROOT，C 保持 COLLABORATOR，零额外 Node。 |
| 真实线程 barrier 并发 | `::test_threaded_handover_barrier_keeps_one_root_and_attributes_commands` | 通过 | 两线程同时开始；恰好一个完成、一个 stale；最终唯一 ROOT；Node 命令只归属胜出任务凭据，失败任务密码不入 wire/日志。 |
| 同机独立进程锁 | `::test_container_role_lock_nested_reentrant_and_empty_marker`、`::test_container_role_lock_cross_process` | 通过 | RLock 同线程嵌套重入；POSIX 空文件 flock 使另一独立子进程阻塞到释放；锁文件为空标记。 |
| 预检 Node 不可用用户名 | `::test_root_handover_preflight_rejects_node_unusable_names[target-root/target-leading-dash/old-root-leading-dash]` | 通过 | 目标 `root`/前导 `-`、旧 ROOT 前导 `-` 在密码生成/200/Node 前被拒。 |
| 机器中途维护 | `::test_machine_offline_between_steps_keeps_first_committed_fact` | 通过 | 第一旧 ROOT 的 ADMIN 绑定/成功日志已提交；第二步 fresh guard 失败，零第二步 Node，不整批回滚。 |
| DB/审计异常 | `::test_db_or_audit_exception_does_not_rollback_committed_step[binding/audit]` | 通过 | 第一步 ADMIN 与成功日志保留；第二步 DB/审计异常只写该步失败。 |
| 受理后调用者失权 | `::test_accepted_handover_survives_caller_permission_revocation` | 通过 | 受理后收回机器权限，快照未变，后台仍完成，目标唯一 ROOT。 |
| 目标已是 ROOT | `::test_handover_to_already_root_target_demotes_other_roots` | 通过 | 旧 ROOT 降 ADMIN，目标保持/重新成为 ROOT，最终唯一。 |
| 无旧 ROOT | `::test_handover_without_old_root_promotes_target_with_one_root_credential` | 通过 | 只返回 root 一项（不伪造旧 owner 凭据），目标升 ROOT，最终唯一。 |
| 畸形 ID/role/flag | `::test_malformed_root_request_has_no_role_or_node_side_effects` | 11/11 通过 | 非整数 `container_id` 由 `require_resource` 固定 400；bool ID 由 `UpdateRoleRequest` 拒绝为 400；同一非整数用例还验证只挂 `require_machine_of_container` 的 `unpause_container` 返回 400。全部无角色/Node/后台任务副作用。 |
| Node 超时/异常 | `::test_node_failure_during_demotion_stops_before_promotion[timeout]`、`[exception]` | 通过 | 第一个旧 ROOT 降级失败即停，不升目标，最终仍为原 ROOT 集合。 |
| 降级绑定写入失败 | `::test_binding_failure_during_demotion_stops_before_promotion` | 通过 | Node 成功但绑定失败也停止，不升目标，最终仍为原 ROOT 集合。 |

复现命令（WSL）：

```bash
/home/chest/miniconda3/envs/fuxi/bin/python -m pytest test/container/test_role_adversarial.py -q --no-header
```

本轮结果：**28 passed、0 failed（28 项）**。

### 并发互斥实现与范围

- 新增 `utils/container_lock.py`：同一 `container_id` 用 `threading.RLock` 覆盖同进程并支持嵌套重入；POSIX 用私有临时目录空锁文件 + `fcntl.flock` 覆盖同机跨进程；Windows 无 fcntl 时仅线程锁。
- 锁文件只做空标记，不保存密码、角色或业务状态；未新增表/字段/租约/持久化工作流。
- 所有 ROOT 集合变更入口共用该锁：外部普通 `update_role`、直接 ROOT 降 ADMIN、ROOT 交接后台 job、删除用户内部 `promote_root_sync`，以及删除用户同容器移交段。
- ROOT 交接后台在整个 job 期间持锁；获锁后用独立只读 session 重读 ROOT `user_id`/系统用户名集合、目标角色与目标用户名，与受理快照比较；变化则固定 `root_handover_stale` 并在任何 Node 前退出。
- 交接每步仍独立 `session_scope`/repo 提交；机器/容器 guard 每步新鲜读取；DB/审计异常只影响该步，已提交绑定/成功日志不回滚。
- 删除用户既有步骤/角色/顺序未改：仅用同一锁包住移交段，开始前核实旧 owner 仍 ROOT。
- 异步受理不等待后台完成：后受理任务允许 `root_handover_stale`，其凭据不执行；最终唯一 ROOT 断言未放松。
- 边界：当前部署单 Linux Ctrl 主机；多 Ctrl 主机、Windows 跨进程、真实生产 MySQL 互斥不在本轮承诺。

### 本轮输入验证修复

- `UpdateRoleRequest.container_id/user_id` 增加 `mode="before"` 校验：bool 直接拒绝；整数与既有兼容数字字符串仍被接受（schema 探针：`1`/`"1"` accepted，`true` rejected）。
- `api/deps.py` 增加 `_coerce_resource_id`：`ValueError`/`TypeError`/`OverflowError` 统一收敛为 400 `invalid_resource_id`；`require_resource` 与 `require_machine_of_container` 共用，未改全局 schema。
- 使用 `PydanticCustomError` 避免 `ValueError` 进入全局 400 响应时再次 JSON 序列化失败。
- 预检拒绝目标 `root`/前导 `-`、旧 ROOT 前导 `-`，在生成密码/200/Node 前失败。

### 契约不一致记录（本轮只记录，不扩大修复）

- 目标无旧 ROOT 时，Ctrl 只返回 `root` 一项（`test_handover_without_old_root_promotes_target_with_one_root_credential` 已断言）。
- 目标本身已是唯一 ROOT 且无其他旧 ROOT 时，`_root_owner_names` 排除目标后同样只返回 `root` 一项。
- Web 侧“至少两项”合同与上述两种边界不一致；本轮未改 Web 或凭据数量语义，留待父级评估。

## 最近验证

- 上轮全量（新增对抗性文件前）：2026-10-24 21:00 +08:00；工作区基于 4dff54a（含未提交改动）；相关套件 39 passed；全量 1434 passed、6 deselected、1 warning、24 subtests passed（233.21s）。
- 本轮对抗性（最终）：2026-10-24 21:47 +08:00；命令见上；结果 **28 passed、0 failed（28 项）**，含真实线程 barrier、独立进程 flock、预检用户名、机器中途维护、DB/审计异常回归；随后连跑 3 次均 28 passed。
- 本轮原 ROOT 与依赖回归：`test/container/test_password_contracts.py`、`test/container/test_container_api_collaborators.py`、`test/container/test_account_wire_contracts.py`、`test/operation_log/test_password_logs.py`、`test/container/test_container_api_information.py`、`test/user/test_user_api_profile.py`，结果 **78 passed**。
- 本轮完整默认套件：WSL `/home/chest/miniconda3/envs/fuxi/bin/python -m pytest -q --no-header`；结果 **1462 passed、6 deselected、1 warning、24 subtests passed（220.86s）**。
- Schema 兼容探针：整数与数字字符串 accepted，bool rejected（`invalid_id`）。
- 主 spec SHA256：3F7C70DBF2559B775048894C2D0E50DD8DBA3C7371FAE8D47D3CB3876B152356
- 限制：6 项 integration/legacy 按策略排除；未连接真实生产 Docker/MySQL/Node；互斥范围仅当前单 Linux Ctrl 主机（POSIX 文件锁 + 同进程 RLock），Windows 无 fcntl 时仅线程锁；多 Ctrl 主机、Windows 跨进程、真实生产 MySQL 互斥未验证；锁在 Node 调用期间持有，慢 Node 会延迟同容器角色变更；持久化“读取有效记录”场景本轮未重新审计。

## 最终锁边界与兼容复验（2026-10-24）

| Requirement | 场景或边界 | 覆盖状态 | 测试位置 | 验证范围 |
| --- | --- | --- | --- | --- |
| ROOT 交接并发收敛 | 无 fcntl 时线程锁仍可重入并串行 | 已覆盖 | ../../../test/container/test_container_role_lock.py::test_thread_lock_fallback_works_without_fcntl | 不引入跨平台新依赖；另在 Windows 原生解释器实际导入工具并嵌套加锁成功。 |
| ROOT 交接并发收敛 | 拒绝被替换为符号链接的锁目录 | 已覆盖 | ../../../test/container/test_container_role_lock.py::test_role_lock_rejects_symlink_directory_without_chmod | 拒绝前不更改链接目标权限或写入文件。 |
| ROOT 交接并发收敛 | 解锁异常也关闭描述符 | 已覆盖 | ../../../test/container/test_container_role_lock.py::test_role_lock_closes_descriptor_even_when_unlock_raises | 异常退出后不残留本进程描述符。 |
| ROOT 交接并发收敛 | fork 子进程不继承父进程重入资格 | 已覆盖 | ../../../test/container/test_container_role_lock.py::test_forked_child_does_not_inherit_parent_reentrancy_or_lock_descriptor | 独立解释器内实际 fork，父进程持锁时子进程阻塞，释放后正常获得。 |

- 上述新增三项文件边界先实测 RED（3 failed），修复后与原对抗文件合跑 31 passed；再补无 fcntl 降级测试，最终默认全量为 **1466 passed、6 deselected、1 warning、24 subtests passed**（230.46s）。
- 当前代码基于本轮未提交工作区；主规格未因这些实现边界改写，哈希沿用上节所列值。
- 日志：外部 `adversarial-ctrl/lock-edge-red.log`、`lock-edge-green.log`、`27-full-final-portability.log`；Windows 实测脚本位于外部 `windows-lock-smoke.py`。
- 该 Windows 验证只证明工具的导入和线程锁降级，不宣称 Windows 跨进程互斥或完整应用部署验收。
- 最终主规格按职责拆分长段落，未改变业务约束；当前 SHA256：b796604f9f6749223068cd53cffa3c65f2bcf0d09feac8af1ce2c0c3dd93d2c3。
