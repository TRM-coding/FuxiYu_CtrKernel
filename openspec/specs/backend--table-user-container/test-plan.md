# backend--table-user-container Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: user_container 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc01_user_container_readback_contract
- Assertion scope: 计划项持久化一条完整绑定（带 `public_key`）与一条最小绑定（`public_key=NULL`），换新 session 按 `(user_id, container_id)` 复合主键读取；断言 `user_id`/`container_id` 为 `int` 且等于真实主键，`role` 为 `ROLE` 枚举，`granted_at` 为插入窗口内 `datetime`，`public_key` 按 `str`/`NULL` 往返，`username` 为 `str` 原样往返，同一复合键只有一行，不用用户名/展示名替代稳定主键。
- Coverage note: 既有 `test_role_change_semantics_contract` 等只读同一 session 的绑定 role/username；旧版主侧车曾把本场景标为“待复核”，没有完整的跨 session 类型/空值断言。

### Requirement: user_container 生产职责与生命周期

#### Scenario: 协作角色变更

- Test/check:
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc02_update_role_persists_binding
- Assertion scope: 计划项对已绑定的普通用户调用真实 `update_role`，Node 替身记录一次 `update_role` wire；断言该复合主键绑定的 `role` 被更新为目标非 ROOT 角色、`username` 保持其系统用户名、旧/新角色写入成功审计，Node 请求不含密码字段。
- Coverage note: 既有 `test_role_change_semantics_contract` 调用了 `update_role`，但只断言 Node config 无密码；没有读回绑定 role。`test_container_api_collaborators.py::test_update_role_api_success` 把 service 整个替换，不能作为落库证据。

#### Scenario: 普通非 ROOT 角色互换不改密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_role_change_semantics_contract
  - [X] test/container/test_password_contracts.py::test_update_role_legacy_transfer_root_does_not_affect_non_root
- Assertion scope: `update_role` 把 COLLABORATOR 切到 ADMIN 时，Node `config` 不含 `password` 与 `root_password`；`transfer_root=true` 的非 ROOT 请求仍只把 `updated_role`/`operator_user_id` 等原参数传给 service，兼容字段不改变路由；不生成或重置 root/目标账号密码。绑定 role 的落库部分不在本行断言范围内，由 `[X] test_anvil_uc02_update_role_persists_binding` 覆盖。
- Coverage note: 测试断言的是 Node wire 不含密码字段，没有比较密码值；在该 wire 合同下已足以证明本路径不交付密码，未额外读取密码哈希。“Ctrl 只更新该绑定 role”的落库断言见 `[X] test_anvil_uc02_update_role_persists_binding`，本条不冒充已覆盖。

#### Scenario: 旧 ROOT 降为 ADMIN 保留独立账号密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_role_change_semantics_contract
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc02_user_binding_changes_keep_other_bindings
- Assertion scope: `start_root_demotion` 生成一项凭据，`login_name` 等于旧 ROOT 用户表系统用户名；Node `config.password` 等于该凭据密码；成功绑定落为 ADMIN 且 `username` 为该系统用户名。计划项在同一容器另有一条 collaborator 绑定时执行降级，断言该其他绑定仍存在且 role/username 不变。
- Coverage note: 既有用例没有读回其他绑定，不能证明“不删除其他绑定”。

### Requirement: 外部 ROOT 请求统一完整交接

#### Scenario: flag 省略、false、true 执行同一完整交接

- Test/check:
  - [X] test/container/test_password_contracts.py::test_update_role_root_always_handover_contract[omitted]
  - [X] test/container/test_password_contracts.py::test_update_role_root_always_handover_contract[false]
  - [X] test/container/test_password_contracts.py::test_update_role_root_always_handover_contract[true]
- Assertion scope: 三个参数分支都返回 200、`accepted=true`、`Cache-Control: no-store`，`credentials` 恰为 root 与旧 ROOT 系统用户名两项且密码不同；Node 调用顺序为 `admin` 后 `root`，旧 ROOT 用其系统用户名/密码降级，目标用 root 新密码升级；最终只有目标一个 ROOT，Node config 均不含 `transfer_root`；密码不出现在日志与日志文件中。

#### Scenario: 多个旧 ROOT 逐个降级后目标成为唯一 ROOT

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_contract
- Assertion scope: 历史多 ROOT 时凭据数为旧 ROOT 数 + 1，登录名集合包含 root 与各旧 ROOT 系统用户名且密码互异；Node wire 逐个 `admin`、最后 `root`；所有旧 ROOT 绑定落为 ADMIN，目标落为 ROOT/`username=root`，最终 ROOT 集合仅目标；不丢弃涉及人或为凑两项篡改角色。

### Requirement: ROOT 交接的受理与凭据

#### Scenario: 正常单个旧 ROOT 交接返回两项不同登录名

- Test/check:
  - [X] test/container/test_password_contracts.py::test_update_role_root_always_handover_contract[omitted]
  - [X] test/container/test_password_contracts.py::test_root_handover_contract
- Assertion scope: 响应 `accepted=true`，`credentials` 恰为 root 与旧 ROOT 系统用户名两项，密码不同；后台先以旧 ROOT 系统用户名/密码降 ADMIN，再以 root 新密码升目标；Node wire 与凭据密码一一对应。

#### Scenario: 旧 ROOT 降 ADMIN 的独立账号使用其系统用户名

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_contract
- Assertion scope: 旧 ROOT 绑定 `username="root"`、用户表系统用户名为另一个名字时，降级 Node `config.user_name` 与凭据 `login_name` 都使用后者；Node wire 携带该系统用户名与该密码，成功绑定落为 ADMIN/该系统用户名。
- Coverage note: 真实 Node 是否创建/确保独立账号不在本仓库测试范围；Ctrl 侧断言的是 wire 内容与绑定结果。

#### Scenario: 直接 ROOT 降 ADMIN 也返回独立账号密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_role_change_semantics_contract
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc07_direct_root_demotion_api_returns_credential
- Assertion scope: 目标当前为 ROOT 时调用 ROOT→ADMIN，服务返回一项 `login_name` 为系统用户名的凭据；Node `config.password` 等于该凭据；绑定更新为 ADMIN/系统用户名；该路径不经过外部 ROOT 交接的多旧 ROOT 遍历，也不当作普通非 ROOT 互换（普通互换无密码字段）。计划项走 HTTP 入口，断言 200、`accepted=true`、`Cache-Control: no-store`、恰一项凭据，且 Node wire 与绑定符合上述内容。
- Coverage note: 既有用例在 service 层断言凭据/Node/绑定，没有断言 API 的 `accepted` 与 `Cache-Control`。

#### Scenario: 机器或容器不可用时不生成密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_preflight_contract
- Assertion scope: 目标未绑定、容器离线、机器离线分别抛 `target_not_bound`、`container_offline`、`machine_offline`；密码生成器调用记录为空，Node 调用记录为空，不返回凭据。

#### Scenario: 目标未绑定或用户名不可用时不生成密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_preflight_contract
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[target-root]
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[target-leading-dash]
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[old-root-leading-dash]
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc08_handover_preflight_api_maps_409
- Assertion scope: 目标未绑定为 `target_not_bound`；旧 ROOT 系统用户名不可用为 `invalid_root_owner_account`；目标系统用户名为 `root` 或前导 `-` 为 `invalid_target_account`；旧 ROOT 前导 `-` 为 `invalid_root_owner_account`。以上均在生成密码/Node 前失败，密码生成记录为空。计划项走 HTTP 入口，断言目标未绑定/用户名不可用分别返回 409 与对应 reason、无 `credentials`、无 Node 调用。
- Coverage note: 既有用例在 service 层断言 reason 与密码生成器未调用；API 的 409 映射与无凭据响应仍缺断言。

#### Scenario: 调用者先被降级也不影响后续步骤

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_contract
  - [X] test/container/test_role_adversarial.py::test_accepted_handover_survives_caller_permission_revocation
- Assertion scope: 调用者本身是旧 ROOT 时，后台仍完成旧 ROOT 降级与目标升 ROOT；受理后收回调用者机器权限，已受理任务仍完成，目标成为唯一 ROOT。

### Requirement: ROOT 交接的逐步执行与失败边界

#### Scenario: 两步成功各记一条真实日志

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_password_contracts.py::test_root_handover_contract
- Assertion scope: Node 恰好两次调用，顺序 `admin`、`root`；两条 `update_collaborator_role` 成功日志；旧 ROOT 绑定 ADMIN/系统用户名，目标绑定 ROOT/`username=root`；日志文本不含密码。

#### Scenario: 第一步失败不继续第二步

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_role_adversarial.py::test_node_failure_during_demotion_stops_before_promotion[timeout]
  - [X] test/container/test_role_adversarial.py::test_node_failure_during_demotion_stops_before_promotion[exception]
- Assertion scope: 第一个旧 ROOT 降级失败后只发生一次 Node 调用，目标仍为 COLLABORATOR、不会被升 ROOT；失败路径写 `update_collaborator_role` 失败日志；Node 超时与异常两个分支一致。

#### Scenario: 多个旧 ROOT 中任一降级失败也不提拔目标

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc03_multi_root_demotion_failure_writes_failure
- Assertion scope: 既有用例让前一个旧 ROOT 成功降 ADMIN、后一个失败，断言只发生两次 `admin` Node 调用、目标仍 COLLABORATOR、仍有一个旧 ROOT 保留。计划项补失败步骤的 `update_collaborator_role` 失败日志、没有目标 ROOT 成功日志，且日志不含密码。
- Coverage note: 既有用例没有断言失败 oplog 内容。

#### Scenario: 第二步失败不伪报整体成功

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
- Assertion scope: 旧 ROOT 已成功降 ADMIN 的绑定保留；目标仍 COLLABORATOR、不记 ROOT 成功；失败步骤写 `update_collaborator_role` 失败日志。
- Coverage note: 用例没有单独统计成功日志条数；目标绑定未落 ROOT 且失败日志存在，已覆盖“不伪报整体成功”的可观察结果。

#### Scenario: 绑定更新失败也停止后续步骤

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_role_adversarial.py::test_binding_failure_during_demotion_stops_before_promotion
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc04_binding_failure_writes_failure_oplog
- Assertion scope: 第二步 Node 成功后写目标绑定失败时，旧 ROOT 保持 ADMIN、目标保持 COLLABORATOR，后续不再执行；降级步骤绑定失败时旧 ROOT 保持 ROOT，目标不升。计划项补失败步骤的失败 oplog、不写该步成功日志，且日志不含密码。
- Coverage note: 既有两个用例只断言停止与角色状态，没有断言失败 oplog。

#### Scenario: 后台最小 guard 复核失败只记失败

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc05_background_guard_failure_writes_failure_oplog
- Assertion scope: 已受理后容器离线，后台执行前 guard 失败时不调用 Node，目标保持 COLLABORATOR。计划项补失败 oplog、无该步成功日志、无新增 DTO/持久状态，且日志不含密码。
- Coverage note: 既有用例没有断言失败 oplog。

#### Scenario: Node 只改指定目标

- Test/check:
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/container/test_account_wire_contracts.py::test_ctrl_legacy_transfer_root_never_enters_node_wire
- Assertion scope: Ctrl 按旧 ROOT 与目标逐个发起 `update_role`，每个 Node payload 只暴露该步的 `config.user_name`/`updated_role` 等单目标字段；Node wire 不含 `transfer_root`。
- Coverage note: 既有测试没有也不应由 Ctrl 断言真实 Node 内部是否扫描其他账号；这里只能证明 Ctrl 每次只发送一个目标，Node 自身不自动扫描的承诺不在本仓库测试范围内。

### Requirement: ROOT 交接的并发串行化与已受理冲突

#### Scenario: 真实线程同容器并发只允许一个交接完成

- Test/check:
  - [X] test/container/test_role_adversarial.py::test_threaded_handover_barrier_keeps_one_root_and_attributes_commands
- Assertion scope: 两个真实线程在 barrier 后竞争同一容器锁；恰好一个完成降旧 ROOT、升目标并发送 `admin`/`root` 两次 Node，另一个 stale 退出且零 Node；最终 ROOT 集合恰好一个，Node 命令只归属胜出任务的凭据，失败任务密码不出现在 wire/日志。

#### Scenario: 同机独立进程竞争同一容器锁

- Test/check:
  - [X] test/container/test_role_adversarial.py::test_container_role_lock_nested_reentrant_and_empty_marker
  - [X] test/container/test_role_adversarial.py::test_container_role_lock_cross_process
  - [X] test/container/test_container_role_lock.py::test_thread_lock_fallback_works_without_fcntl
  - [X] test/container/test_container_role_lock.py::test_role_lock_rejects_symlink_directory_without_chmod
  - [X] test/container/test_container_role_lock.py::test_forked_child_does_not_inherit_parent_reentrancy_or_lock_descriptor
- Assertion scope: 同线程嵌套获取可重入且锁文件为空标记；独立子进程持锁时另一子进程阻塞，释放后才获得；无 fcntl 时线程锁仍能阻塞同进程竞争者；符号链接锁目录被拒且未改权限/写文件；fork 子进程不继承父进程重入资格。锁文件只作空标记，不含密码或业务状态。
- Coverage note: 跨进程用例仅在 POSIX（`fcntl`/`fork`）有效，Windows 上按既有 skip 条件不执行；当前并发承诺限定单 Linux Ctrl 主机，多 Ctrl 主机、Windows 跨进程与真实生产 MySQL 互斥未验证。

### Requirement: ROOT 交接的身份预检与获锁复核

#### Scenario: 已受理的同容器交接冲突以 stale 结束

- Test/check:
  - [X] test/container/test_role_adversarial.py::test_repeated_handover_to_same_target_keeps_one_root_and_stales_second
  - [X] test/container/test_role_adversarial.py::test_interleaved_handover_to_two_targets_must_not_leave_two_roots
- Assertion scope: 第二次任务持锁后重读发现当前 ROOT 集合与受理快照不同，写一条 `root_handover_stale` 失败并在任何 Node 前退出；第二个响应中的密码不出现在 Node wire/日志；最终恰好一个 ROOT，后受理目标不增加额外 ROOT。
- Coverage note: 既有断言隔离的是 `expected_root_ids`/`current_root_ids` 的 ROOT 集合差异；目标角色与用户名的单独比较没有被这些用例分开断言。

#### Scenario: Node 不可用用户名在预检被拒

- Test/check:
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[target-root]
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[target-leading-dash]
  - [X] test/container/test_role_adversarial.py::test_root_handover_preflight_rejects_node_unusable_names[old-root-leading-dash]
  - [X] test/container/test_password_contracts.py::test_root_handover_preflight_contract
- Assertion scope: 目标系统用户名 `root`/前导 `-` 返回 `invalid_target_account`，旧 ROOT 系统用户名前导 `-` 或与保留 `root` 冲突返回 `invalid_root_owner_account`；均在生成密码、返回 200、调用 Node 前失败，不产生凭据。

### Requirement: ROOT 交接保留逐步提交事实

#### Scenario: 机器中途维护或 DB/审计异常不整批回滚

- Test/check:
  - [X] test/container/test_role_adversarial.py::test_machine_offline_between_steps_keeps_first_committed_fact
  - [X] test/container/test_role_adversarial.py::test_db_or_audit_exception_does_not_rollback_committed_step[binding]
  - [X] test/container/test_role_adversarial.py::test_db_or_audit_exception_does_not_rollback_committed_step[audit]
- Assertion scope: 第一步旧 ROOT 已成功降 ADMIN 并提交绑定/成功日志；下一步前机器离线或该步绑定/审计抛 DB 异常时，第一步 ADMIN 与成功日志保留。`binding` 分支目标仍未升 ROOT，`audit` 分支目标绑定虽已实际落 ROOT 但不写该步成功日志；两种情况都不整批回滚，失败步骤只影响自身。

### Requirement: 删除用户内部 ROOT 提升的密码兼容

#### Scenario: 删除用户内部提升生成随机 root 密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_delete_user_root_password_contract
- Assertion scope: 删除用户触发内部提升时，Node 第一次调用是目标单目标 `updated_role=root`，携带非空 `config.root_password` 且不等于 `{user_name}123`；不带 `transfer_root`；目标最终成为 ROOT。第一次调用即为 root 提升（而非外部交接的旧 ROOT 降级），证明没有使用外部完整交接编排；不产生 HTTP 凭据响应。
- Coverage note: 用例没有断言总 Node 调用次数；第一次调用形态与后续删除流程已覆盖“不是外部交接编排”的可观察部分。

#### Scenario: 内部提升失败不回退弱密码

- Test/check:
  - [X] test/container/test_password_contracts.py::test_delete_user_root_password_contract
  - [X] test/container/test_anvil_freeze_membership.py::test_anvil_uc06_delete_user_internal_promotion_failure_no_retry
- Assertion scope: Node 内部提升失败时删除返回 `False`，用户/绑定保留；失败调用的 `root_password` 仍不是 `{user_name}123`。计划项补断言没有第二次用弱密码/空密码重试，且不存在伪造凭据或持久状态，失败日志不含密码或 Node 原始请求/响应体。
- Coverage note: 既有用例只检查第一次调用的密码值，没有断言失败后的重试次数。
