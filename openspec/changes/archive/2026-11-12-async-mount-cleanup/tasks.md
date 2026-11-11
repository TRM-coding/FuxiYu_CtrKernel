# Tasks

## 1. 进程内清理登记与互斥键

- [x] 1.1 新增 Ctrl 进程内清理任务/恢复占位模块，实现 `(machine_id, 词法路径)` 键、原子登记、重复冲突、恢复占位、活动任务上限、终态 TTL 与测试重置；词法键只作前置拦截，不实现 Docker Source 活容器门禁。验证：新增 registry 单测覆盖同键并发、不同机器/真实路径、容量、TTL、恢复冲突与释放；`test/container/test_mount_cleanup_registry.py` 通过。覆盖场景：`backend--table-container-mount-cleanup` / `清理登记、重复冲突与恢复互斥` 下全部 Scenario；`清理状态的有界性与 Ctrl 重启丢失` 下容量/TTL/重启 Scenario。
- [x] 1.2 在异常白名单与 API 状态映射中增加 `cleanup_in_progress`、`restore_in_progress`、`cleanup_capacity_exhausted`、`cleanup_not_accepted`、`cleanup_result_unknown`、`cleanup_persist_failed`、`cleanup_failed`。验证：单测断言 `safe_reason` 不降级、API 409/503/500 映射正确；`test/container/test_mount_cleanup_registry.py` 或 `test/container/test_mount_cleanup_async.py` 通过。

## 2. Node 异步客户端与后台任务状态机

- [x] 2.1 实现 `start_clean_mount`/`get_clean_mount_status` 的严格请求与响应解析（`task_id`、三态、`error_reason`、HTTP 404/405/超时/坏响应），无累计总期限；仅 Node 可达且 `running` 时持续间隔轮询。瞬时 timeout/连接失败/5xx 做有间隔、有连续失败上限的重试，`running` 重置计数；达上限才 unknown。`task_not_found` 或 HTTP 404 + `error_reason=not_found` 直接 unknown/`node_task_lost`，旧端点 404/405 直接 unknown/`node_unsupported`，不得误报成功。验证：新增 `test/container/test_mount_cleanup_async.py` 覆盖启动成功、重复冲突、严格三态、旧 Node、任务丢失、瞬时重试与 running 重置、连续失败上限、持续 running 不截断；通过。覆盖场景：`backend--table-container-mount-cleanup` / `Node 异步清理协议与旧端点兼容` 与 `手动挂载清理的受理与异步终态` 的相关 Scenario。
- [x] 2.2 实现后台 worker：手动前置路径检查、Node 启动、轮询、`succeeded` 同事务写 `cleaned_at`/`mount_cleaned`、成功/失败/未知 oplog、落库失败转 unknown、终态只记账一次。验证：`test/container/test_mount_cleanup_async.py` 成功、失败、未知、落库失败、重复终态用例通过；`test/operation_log/test_mount_cleanup_async_logs.py` 通过。覆盖场景：`backend--table-operation-logs` / `挂载清理的异步结果日志` 全部 Scenario；`手动挂载清理的受理与异步终态` 全部 Scenario。

## 3. 手动 API 与三入口接入

- [x] 3.1 扩展 `CleanDeletedContainerMountResponse` 与 `DeletedContainerRecord` 的响应字段（`accepted`、`already_cleaned`、`mount_cleanup_state`、`mount_cleanup_error_reason`），列表 `data_recoverable` 在 `cleaning` 时为 false。验证：`test/container/test_mount_cleanup_list_state.py` 覆盖 cleaning/failed/unknown/null/成功后/重启后/目录缺失/只读不联系 Node；通过。覆盖场景：`backend--table-deleted-container-restore-snapshot` / `已删除容器列表清理状态投影` 全部 Scenario。
- [x] 3.2 手动清理服务改为提交异步任务并返回已受理；已清理保持幂等；调度器将手动、定时、磁盘升级三入口统一提交同一异步任务，保留 trigger/operator/escalation/资格与日志语义，调度器不把 accepted 当 cleaned，旧 `/clean_mount` 不回退。验证：更新 `test/container/test_deleted_containers.py`、`test/container/test_container_mount_cleanup_task.py`、`test/container/test_container_disk_check_task.py` 相关断言；运行三文件通过。覆盖场景：`container_mount_cleanup 生产职责与生命周期` 与 `自动与升级清理维持既有语义`、`手动挂载清理的受理与异步终态`。

## 4. 恢复互斥与边界

- [x] 4.1 在 `resurrect_container` 的路径复核前取得 Ctrl 词法恢复占位，覆盖创建、长期状态恢复、快照/清理记录消费到成功/失败返回；并发的同词法清理返回 `cleanup_in_progress`，重复恢复返回 `restore_in_progress`；不增加 Docker Source 活容器门禁。验证：`test/container/test_mount_cleanup_registry.py` 覆盖清理中拒绝恢复、恢复中拒绝清理、关键阶段持锁、二选一/失败释放、清理失败/未知/重启后开放、重复恢复；通过。覆盖场景：`deleted_container_restore_snapshot 生产职责与生命周期` 下互斥相关 Scenario。
- [x] 4.2 保持 Node realpath 预留只通过既有 `/create_container` 请求携带 `restore_mount_path`，不新增 Node 门禁；对 Node 返回的 `cleanup_in_progress`/`restore_in_progress` 原样上抛，保留快照与清理记录。验证：fake Node 返回冲突的恢复用例断言无快照消费、无成功审计；`test/container/test_mount_cleanup_registry.py` 通过。覆盖场景：`Node realpath 恢复预留与共享登记` 下 `创建受理前 realpath 预留`、`词法别名由 Node realpath 拒绝`、`预留释放与创建/账号恢复失败`；尾段边界保持 design 的已知缺口说明。

## 5. 回归与规格校验

- [x] 5.1 运行定向回归：`pytest test/container/test_mount_cleanup_async.py test/container/test_mount_cleanup_registry.py test/container/test_mount_cleanup_list_state.py test/container/test_deleted_containers.py test/container/test_container_mount_cleanup_task.py test/container/test_container_disk_check_task.py test/container/test_mount_path_action_guard.py test/operation_log/test_mount_cleanup_async_logs.py -q`；修复本次改动造成的失败，确认不触真实 Node/DB/SMTP。验证：定向套件通过。
- [x] 5.2 运行 `openspec validate async-mount-cleanup --strict` 与 `git diff --check`；确认无数据库模型/迁移变更、无 Docker Source 活挂载门禁、无提交推送。验证：规格校验通过、diff 无空白错误、变更仅落在本 change 与约定 Ctrl 代码/测试范围内。

## Workflow follow-up

- 完成后使用官方 `openspec-verify-change` 流程；不创建 Anvil verify 工件。
- 别名尾段问题待用户异步答复；本轮不实现额外 Node/Docker Source 门禁。
