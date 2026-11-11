# Proposal

## Why

已删除容器的挂载清理目前是同步调用：手动 Web 请求与定时/升级调度都等待整个 `rm -rf` 完成，Node 慢、超时或重启时只能报错或悬挂；Ctrl 也没有跨入口的“正在清理”登记，两个清理请求或清理与恢复可能同时操作同一台机器上的同一个目录。清理结果只以一次同步响应为准，无法区分“Node 已确认删除”“明确失败”和“结果未知”，列表也无法展示清理中。

本变更把手动、定时与磁盘升级清理统一改为“Ctrl 受理/提交 + 后台轮询 Node 任务”，并用进程内、按 `(machine_id, 词法规范化 mount_path)` 的原子登记把清理、重复清理和恢复串行化。Node 在 `/create_container` 受理前对 `restore_mount_path` 取 realpath 预留，并与同步/异步清理共用同一路径登记；Ctrl 的词法路径只作前置拦截，别名由 Node realpath 兜底。成功只在 Node 明确返回 `succeeded` 后落库；失败和未知绝不写成成功。用户明确接受 Ctrl 重启丢失进程内状态，以及 Node 重启造成清理中断、目录可能部分删除后恢复按钮重新开放。

## What Changes

- **BREAKING** 所有清理入口改为受理式：手动 API 在同一临界区内完成可登记性校验与进程内登记，返回 `accepted=true`；定时扫描与磁盘升级清理也提交同一异步任务，由后台线程调用 Node `POST /api/start_clean_mount` 并轮询 `POST /api/get_clean_mount_status`，不再等待旧同步 `/clean_mount` 完成。各入口保留自己的资格、trigger、escalation 与最终日志语义；调度器 MUST NOT 把“已受理”当作“已清理”。
- **BREAKING** 成功条件收紧：只有 Node 状态明确为 `succeeded`，且 Ctrl 在事务中同时写入 `cleaned_at` 与 deleted 快照的 `mount_cleaned` 后，才允许写成功 oplog。Node `failed`、启动拒绝、状态轮询失败、任务丢失、超时、Node/ Ctrl 重启等一律不得标记已清理，也不得写成功 oplog。
- 失败与未知分途留痕：Node 明确失败写失败 oplog；超时、任务丢失、坏响应等结果未知写失败/未知原因的失败 oplog；Ctrl 重启导致轮询丢失时不补记、不补成功记录，记录保持未清理。
- Ctrl 维护有界进程内清理登记：键为 `(machine_id, 规范化绝对路径)`；登记、状态迁移、释放和恢复占位共用同一把进程内锁。重复清理请求返回冲突；恢复在清理为 `accepted`/`running` 时必须拒绝。登记不落库、不持久化、不引入工作流引擎。
- 清理与恢复互斥覆盖恢复关键阶段：恢复从挂载路径复核开始，经 `Create_container`、长期状态恢复、快照与清理记录消费，直到成功/失败返回都持有同一键的 Ctrl 恢复占位；清理请求在恢复占位期间返回冲突。Node 的 realpath 预留覆盖 `/create_container` 受理前到后台创建/账号恢复结束；同路径已有清理/恢复时 Node 在受理前拒绝创建。Ctrl 词法键与 Node realpath 预留对符号链接别名并非全程等价：预留释放后 Node 不再保留恢复互斥，也不增加 Docker Source 活挂载检查；Ctrl 尾段只按词法键保护同路径，别名尾段是已知边界，不新增数据库/分布式锁/旁路。定时清理与磁盘升级清理同样先取得该键的 Ctrl 清理占位，再提交统一异步任务，避免与恢复交叉。
- 列表增加由 Ctrl 进程内状态导出的清理状态：清理中、失败、未知可被已删除容器列表看到；`data_recoverable` 在清理中为 false，在失败/未知后按既有“路径存在且未清理”口径重新开放，由用户承担目录可能部分删除的风险。列表读取 MUST NOT 写库或调用 Node。
- Node 协议按暂定协作约定落地：`start_clean_mount` 返回 `success=1` 与 `task_id`，同一 realpath 的重复启动冲突；`get_clean_mount_status` 返回 `task_id`、`state=running|succeeded|failed`、`error_reason`。同步 `/clean_mount`、异步清理与恢复预留共用 Node realpath 登记；旧同步 `/clean_mount` 的 URL 保留给旧客户端/旧 Ctrl 兼容，当前 Ctrl 的所有清理入口 MUST NOT 调用它或回退到它。
- 路径规范化以 Node 为准：Node 以 realpath 负责最终路径身份、越界、symlink、权限和真实目录校验；Ctrl 仅用词法规范化绝对路径构造进程内前置拦截键，MUST NOT 以自身键相同/不同替代 Node 的 realpath 校验，也 MUST NOT 把未知结果当成成功。Ctrl 词法键不同但 Node realpath 相同的别名，仅在 Node 预留/清理任务仍持有时由共享登记拒绝；两个锁不被描述为对别名全程等价，不增加 Docker Source 活挂载门禁。
- 不新增数据库列/表/JSON 迁移，不引入持久任务表、消息队列或跨进程锁；Ctrl 重启后进程内登记、轮询和终态全部丢失，已发生的 Node 成功不会回填，已删除列表按数据库现状正常显示（目录不存在也正常展示，不报 500）。
- 本变更只写 Ctrl 仓库的 proposal/design/specs/test-plan；不实现 Ctrl/Node/Web 代码，不提交、不推送、不归档。三仓协议仍是暂定，Node/Web 的最终实现以各自仓库变更为准。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-container-mount-cleanup`：手动、定时与磁盘升级清理统一改为受理式异步任务；增加按机器与词法路径的 Ctrl 原子登记、重复请求冲突、Node 任务状态跟踪、明确成功才落库、失败/未知留痕、进程内有界状态和 Ctrl 重启丢失语义；保留各入口资格、trigger、escalation 与日志语义，Node realpath 共享登记仅在清理任务/恢复预留持有期间兜底别名。
- `backend--table-deleted-container-restore-snapshot`：恢复必须与同机器同词法路径的清理互斥并覆盖恢复关键阶段；Node 在 `/create_container` 受理前以 realpath 预留 `restore_mount_path`，与清理共用登记，覆盖到后台创建/账号恢复结束；预留释放后的词法别名尾段不保证互斥，也不增加 Docker Source 活挂载门禁；已删除列表增加进程内清理状态投影，清理中禁止恢复，失败/未知后恢复按钮重新开放；目录不存在正常展示。
- `backend--table-operation-logs`：挂载清理异步结果日志只在 Node 明确成功后写成功；失败与结果未知写失败/未知原因，受理时不写结果日志，未知和重启不得伪造成功，失败执行可能部分删除但不得标记已清理。

## Impact

- Ctrl：`api/container_api.py`、`schemas/container.py`、`services/container_tasks.py`、`services/container_module/mount_cleanup.py`、新增的进程内清理任务/登记模块、`schedulers/container_mount_cleanup_task.py`、`schedulers/container_disk_check_task.py`、`services/container_module/restore.py`、`services/container_module/deleted_containers.py`、`services/container_module/exceptions.py`、`services/container_module/node_comms.py` 及对应 API/服务/调度器测试。
- Node：新增异步启动与状态查询端点及进程内任务登记；`/create_container` 在受理前对 `restore_mount_path` 取 realpath 预留，并与同步 `/clean_mount`、异步清理共用登记；旧 `/clean_mount` URL 保留给旧客户端/旧 Ctrl；不新增 Node 数据库表/列。三仓路径规范化与错误码需按暂定协议对齐。
- Web：清理调用方只等 Ctrl `accepted=true`，通过已删除列表的清理状态和操作日志获知结果；旧“调用返回即已清理”的展示需改为“已受理/清理中/成功/失败/未知”。
- 数据库：无新列、无新表、无 JSON 迁移；清理状态只存在于 Ctrl 进程内。
- 兼容性：手动清理的响应语义从“已完成”变为“已受理”，改由列表与日志反映终态；自动与升级清理仍保留原资格、trigger、escalation 与结果日志，但同样只返回“已受理”，最终结果由后台任务落库。旧同步 `/clean_mount` 仅为旧客户端/旧 Ctrl 保留，当前 Ctrl 的三种入口都不再调用它；旧 Node 缺少新端点时手动、自动、升级清理均以 `node_unsupported` 失败，不回退为同步清理。旧 Node 未实现 realpath 共享登记时，Ctrl 词法键只能拦截显式同路径，别名恢复/清理无最终保证，因此部署要求 Node 先升级。Ctrl 重启会丢失进行中的轮询与状态，这是本变更明确接受的可用性取舍。
