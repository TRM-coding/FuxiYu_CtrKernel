# Tasks

## 1. 专属测试文件与容器持久化/结构契约

- [x] 1.1 新建 `test/container/test_anvil_cleanup_contracts.py`，只复用既有 `db_session`、`client`、`factories`、`mock_node_send`、`session_scope`，不新增共享 fixture；实现 C01/C29/C30，定向运行该文件确认行读取、列约束与“渲染文本/平台注入不落库”断言通过。
- [x] 1.2 实现 C02/C39：创建资源上限的 CPU/GPU 具体数值与创建 wire `config.image`；定向运行并确认失败时未发 Node、wire 使用平台 tag。
- [x] 1.3 实现 C03/C04/C05/C07：恢复请求忽略客户端镜像名、未来版本戳与配方变化、两来源当前注入与 `last_build_at` 刷新、旧容器版本不被新派发改写；定向运行。
- [x] 1.4 实现 C06/C08/C13/C14/C15/C16/C17：两份等价快照的挂载一致性、路径修正不批量改历史、详情非空路径只读、创建密码/message、失败仍下发密码但脱敏、恢复新密码、requires_choice 不交付密码；定向运行。

## 2. 路径、测量、冻结与消失保护

- [x] 2.1 实现 C09/C10/C11/C12：同时间戳路径冲突拒绝、unresolved 有效测量进入评估、resolved 失败帧不驱动调度、路径修正不授权删除/清理；定向运行并核对 caplog/DB 状态。
- [x] 2.2 实现 C33/C34/C36/C37/C38：启动过渡态缺席保护、错误机器/非活跃容器帧忽略、delete 帧保留账号与长期标记、错误测量拒绝日志、过期测量不重开/不顺延既有冻结周期；定向运行并保留正常控制组。
- [x] 2.3 实现 C35：reset 的 `bypass_auth_entity`、`target_not_bound`、`machine_offline`、额外字段四个拒绝分支；用密码生成器 tripwire、Node send spy 与禁用目标 service mock，断言无密码生成、无 Node、无 credentials。

## 3. 密码重置/新增协作者与清理/恢复

- [x] 3.1 实现 C18/C19/C20/C21/C22：资源通配放行、ADMIN/COLLABORATOR 拒绝、空/非法 username、paused/failed/过渡态、失败只写失败 oplog；定向运行并核对真实 RBAC 与 Node 调用。
- [x] 3.2 实现 C23/C24/C25/C26/C27/C28/C31/C32：ADMIN 绑定与失败无成功日志、前置校验无密码交付、后台 guard、恢复协作者瞬时密码不持久化、失败不回退、详情/列表无密码、wire/WSS 否定断言、断连模拟边界；定向运行。
- [x] 3.3 实现 D01/D02/D03/M01/M02：恢复快照与挂载清理读回/默认值、用量 API 不新增 schema、旧 Node 不支持不影响列表/恢复资格、清理成功双写与事务回滚故障注入；定向运行并验证故障确实命中。
- [x] 3.4 实现 R01/R02：提醒记录按主键读回、`(container_id, recipient_email)` 唯一键、`cleanup_at`/`sent_at` 审计快照；定向运行并保持 Q81 错误 clause 的未覆盖限制。

## 4. 定向回归与交付

- [x] 4.1 运行新文件全部 46 个唯一 planned tests，确认 0 failure、0 error；任一失败先修测试实现，不弱化断言。
- [x] 4.2 运行映射涉及的 `test/container/test_container_*.py`、`test_deleted_*`、`test_restore_*`、`test_mount_*`、`test_cleanup_*`、`test_password_contracts.py`、`test_vanish_guard.py`、`test_gate_disk_measurement.py`、`test_long_term_transitions.py`、`test_cleanup_deferral_window.py` 与 `test/repository/test_container_*` 定向套件；记录完整命令、raw stdout、exit 到外部日志。
- [x] 4.3 执行 official verify advisory，不创建 `verify.md`；确认实现与 94 Scenario/46 planned tests 一致。

## Workflow follow-up

- official no-op sync 四能力主规格，保持 Ctrl 27 个主规格 SHA 不变。
- `anvil-test-plan` 维护四主 sidecar，archive 前更新本 change 的 test-plan 实施状态与真实 notes。
- official archive 到 `2026-10-28`（北京时间），保留真实 notes 与 Q81/Q82 限制。
- 根最终验收 Git；不 commit/push。
