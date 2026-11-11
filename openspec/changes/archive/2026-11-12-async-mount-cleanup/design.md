# Design

## Context

动机见 [proposal.md](proposal.md)，行为见三个 delta：[container_mount_cleanup](specs/backend--table-container-mount-cleanup/spec.md)、[deleted_container_restore_snapshot](specs/backend--table-deleted-container-restore-snapshot/spec.md)、[operation_logs](specs/backend--table-operation-logs/spec.md)。

当前手动、定时与磁盘升级清理都走同步长请求：API 入口 `api/container_api.py:383-408` 调用 `services/container_tasks.py:399-428`，定时/升级分别从 `schedulers/container_mount_cleanup_task.py:27-76`、`schedulers/container_disk_check_task.py:461-509` 进入同一门户 `services/container_module/mount_cleanup.py:75-139` 和动作序列 `142-269`。它先做原容器有效态检查和手动路径探测，然后同步请求 Node `/clean_mount`，成功后才在 `services/container_module/mount_cleanup.py:230-250` 同一事务写 `cleaned_at` 与 deleted 快照的 `mount_cleaned`，最后写成功日志。Node 慢、超时或重启时 HTTP/调度循环只能失败或悬挂；三个入口之间没有统一登记；恢复与清理之间也没有互斥。

恢复入口在 `services/container_tasks.py:249-309`：`_load_restore_target` 只读快照，`_ensure_restore_mount_source`（`services/container_module/restore.py:269-305`）在创建前向 Node 查询路径，随后依次恢复账号、镜像、长期状态、`Create_container`、消费快照与清理记录（`services/container_tasks.py:271-305`）。本变更要求 Node 在 `/create_container` 受理前对 `restore_mount_path` 取 realpath 预留，并与同步/异步清理共用登记；Ctrl 的词法键只作前置拦截，最终别名身份由 Node realpath 兜底。没有 Node 预留时，Ctrl 无法仅凭本进程词法键覆盖别名。

已删除列表由 `services/container_module/deleted_containers.py:376-400` 分页，记录投影在 `342-373`；`data_recoverable` 目前只是 `bool(mount_path and not mount_cleaned)`，不能表达“清理中”。列表读取不调用 Node，也不应新增数据库写入。

进程内后台执行的既有先例是 `services/container_module/passwords.py:34-39` 的 daemon 线程；操作日志统一入口是 `services/operation_log_tasks.py:49-97`，日志写入失败不影响主流程。Node 通信入口 `services/container_module/node_comms.py:81-97` 会保留 HTTP 状态与结构化错误，`services/container_module/mount_usage.py:184-208` 已有把 404/405、超时、5xx、坏响应映射为稳定原因的写法，可复用其口径。

约束：

- 不新增数据库列、表、JSON 迁移或迁移文件；不引入持久任务表、消息队列、外键或新的工作流状态机。
- 清理进度只存在于 Ctrl 进程内；Ctrl 重启或进程退出后允许全部丢失，且不做启动补偿。
- 暂定三仓协议：Node 新增 `POST /api/start_clean_mount` 与 `POST /api/get_clean_mount_status`，旧同步 `/clean_mount` 仅为旧客户端/旧 Ctrl 兼容；当前 Ctrl 不使用。Node 任务状态是进程内有界的，Node 退出必须终止清理子进程，重启后旧任务丢失。
- 同一 Ctrl 进程内完成互斥；不承诺多进程、多实例之间的锁。部署若使用多个 worker，必须另行提供共享协调，否则本设计不成立。

## Goals / Non-Goals

**Goals:**

- Web 只等待 Ctrl 受理；Node 启动和清理结果轮询在 Ctrl 后台执行。
- 只有 Node 明确 `succeeded` 且清理记录事务提交后，才标记 `cleaned_at`/`mount_cleaned` 并写成功日志。
- 失败、超时、任务丢失、Node/ Ctrl 重启都不伪造成功；可观测失败或未知写失败/未知结果日志。
- 用 `(machine_id, 规范化绝对路径)` 为键，在 Ctrl 内原子登记清理和恢复，阻止同一键的重复清理与清理/恢复交叉。
- 恢复互斥覆盖路径复核、创建、长期状态恢复、快照与清理记录消费等关键阶段。
- 列表从进程内状态投影“清理中/失败/未知”，不新增持久字段；Ctrl 重启后按数据库现状显示。
- 保留自动清理、磁盘升级清理的入口资格、trigger、escalation 与日志语义；改为异步提交，不保留同步等待语义。旧 `/clean_mount` 仅为旧客户端/旧 Ctrl 兼容。

**Non-Goals:**

- 不实现 Node 端任务管理器、子进程终止逻辑或 Web 页面。
- 不新增数据库列/表/JSON，不把进程内任务状态持久化，不做 Ctrl 启动恢复、重放或成功补记。
- 不在本变更中解决多 Ctrl 进程之间的分布式互斥。
- 不改变 Node `rm -rf` 的删除算法；失败或中断仍可能留下部分删除的目录。
- 不改变长期配额、容器删除、用量查询、冻结或既有 WSS 周期快照。
- 不把旧同步 `/clean_mount` 保留为当前 Ctrl 的回退路径；旧端点只为旧客户端/旧 Ctrl 兼容，当前手动、定时、升级入口都只调用异步端点。

## Decisions

### 1. 受理式提交：先登记，再后台启动与轮询

手动 API、定时扫描和磁盘升级清理共用同一个提交服务；区别只在入口资格与参数：

| 入口 | trigger | operator | escalation | 手动路径新鲜检查 |
| --- | --- | --- | --- | --- |
| 手动 API | `manual_clean_mount` | 当前用户 | 不改变 | 是 |
| 定时扫描 | `auto_mount_cleanup` | `None` | false/不改变 | 否 |
| 磁盘升级 | `disk_escalation` | `None` | true | 否 |

提交服务的流程固定为：

1. 用只读方式解析 `deleted_id`/`mount_cleanup_id`，取得清理记录、`machine_id`、容器当前 `bind_mount_path` 或清理记录路径、`deleted_id`；此阶段不 ensure/adopt、不写库、不调用 Node。
2. 手动入口执行既有只读原容器有效态检查；原容器 `is_valid=true` 时以 `container_exists` 拒绝并保留记录。
3. 计算键 `(machine_id, canonical_mount_path(path))`，在进程内登记表中占位；占位成功后才允许后续副作用。
4. 在占位内执行既有的 `resolve_mount_cleanup_request` 收养/补建逻辑，并重新读取最终清理记录；若最终路径的键发生变化，在登记锁内把占位移到新键，新键已有占位则释放并返回冲突。
5. 复核记录存在、未清理；手动入口再复核不是活容器路径，自动/升级沿用既有资格检查；失败时释放占位并沿用既有失败审计。
6. 启动 daemon 后台线程。手动 API 返回 `accepted=true`；定时/升级入口只拿到“已提交/冲突/容量不足”的提交结果，不等待 Node 完成。Node 启动、手动路径新鲜检查与轮询都由该线程完成。

选择“先返回受理”而不是在 HTTP 内同步等 Node 启动 `task_id`，原因是：Node 启动若超时，Ctrl 无法区分“Node 未收到”“Node 已受理但响应丢失”，HTTP 语义会变得不可判定；先登记再异步启动可以让 HTTP 只表达 Ctrl 已接管，把 Node 结果的不确定性统一收敛到任务状态。代价是路径不存在、权限不足、非法路径等手动检查失败要等后台任务进入失败态后才能被 Web 看到；这是“Web 只等待受理”的直接取舍。定时/升级没有 HTTP 响应，提交后由任务终态落库/日志决定结果，MUST NOT 在提交时把记录标成 cleaned。

`CleanDeletedContainerMountResponse` 增加受理字段：

```text
success=1, message, accepted=true,
deleted_id, mount_cleanup_id,
mount_cleanup_state="cleaning"
```

已清理记录返回 `success=1, accepted=false, already_cleaned=true, mount_cleanup_state=null`，不创建任务、不写结果日志。登记冲突或容量不足在 HTTP 阶段直接返回稳定错误；不进入 `accepted`。

后台线程启动失败（线程创建异常）时释放占位并返回 `cleanup_not_accepted`，不留下“已受理但无执行者”的条目。

### 2. 进程内键、路径规范化与原子登记

键定义为：

```text
cleanup_key = (machine_id: int, canonical_mount_path: str)
```

Node 是单机进程，它的任务键只需路径；Ctrl 的键加入 `machine_id`，避免不同机器上相同的路径互相阻塞。Ctrl 词法键只用于本进程内的前置互斥；Node 以 realpath 作为最终路径身份，并在 `/create_container` 受理前对 `restore_mount_path` 做恢复预留，与同步 `/clean_mount`、异步 `start_clean_mount` 共用同一 realpath 登记。别名或 symlink 导致的词法键差异，由 Node realpath 登记在最终动作前拒绝；Ctrl 的词法键不同不构成放行理由。

`canonical_mount_path` 只做词法规范化，不访问文件系统，不解析 symlink：

1. `strip()` 后必须非空且以 `/` 开头（绝对 POSIX 路径）。
2. 用 `posixpath.normpath` 折叠重复 `/`、`.`、`..` 和末尾 `/`。
3. 规范化后不得为 `/` 或空；否则以 `invalid_path` 拒绝。
4. 不改变大小写，不做 `realpath`，不读取目录。

路径语义以 Node 为权威：Node 在清理启动/同步清理/恢复预留时对路径取 realpath，并继续负责绝对路径、越界、symlink、权限、是否真实目录等校验；Node 拒绝时 Ctrl 只记录失败，不得用自己的词法键继续删除或创建。Ctrl 的词法键只负责在明显同字符串的请求间提前拦截；realpath 相同但词法不同的别名，只有在 Node 预留或清理任务仍持有时才由 Node 共享登记拒绝。两者不是对符号链接别名全程等价的锁：Ctrl 词法键只作前置，Node realpath 恢复预留只覆盖 `/create_container` 受理前到后台创建/账号恢复结束；预留释放后 Node 不追加 Docker Source 活挂载门禁，Ctrl 尾段只剩词法键，别名不保证被拦截（见第 5 节）。

登记表由一把 `threading.RLock` 保护，包含：

- `by_key`: 键到活动清理、恢复占位或终态摘要的映射。
- `by_cleanup_id`: 清理记录 id 到任务的映射，供已删除列表投影。
- 终态摘要：`failed`/`unknown` 状态、稳定原因、结束时间；按 TTL 和数量上限清理。
- 活动清理任务：状态、Node `task_id`、操作者、`deleted_id`、路径、接受时间、终态标志。

手动清理的原子性通过“占位后再做权威复核”实现：先用只读解析算出候选键，在锁内占位；占位期间其他清理或恢复请求看到该键即冲突，不会有两个请求同时进入 ensure/adopt 或 Node 启动。占位内的复核若失败，锁内释放；若路径键变化，锁内迁移；迁移失败则释放并返回冲突。这里不把数据库读写放进全局锁，避免长事务；锁只保护登记表的状态迁移。

恢复占位使用同一把锁和同一个键：先只读加载恢复目标，再在锁内检查同键是否有活动清理/恢复；有清理则为 `cleanup_in_progress`，有恢复则为 `restore_in_progress`。恢复占位不保留终态，随请求在 `finally` 中释放。

自动清理与磁盘升级清理也使用同一个提交服务和同一把键：

- 通过入口资格检查后提交异步任务，保留各自的 trigger、operator、escalation 和结果日志语义；提交成功即继续下一项/返回，不等待 Node 删除。
- 同键已有清理/恢复占位时，定时入口跳过该记录留待下一轮，磁盘升级记录错误/保留 escalation 记录；MUST NOT 调用旧同步 `/clean_mount`，也 MUST NOT 把提交成功当 cleaned。
- 任务在后台完成手动入口的路径新鲜检查（如适用）、Node 启动与轮询；终态才释放键并写结果日志。列表会显示 `cleaning`。
- 这样恢复占位可以阻止自动/升级清理在恢复关键阶段删除同一目录；Node 侧的 realpath 共享登记再兜底算法别名。

不同机器或 Node realpath 不同的路径不复用 Ctrl 键；同一机器不同 realpath、不同机器相同路径均允许并行。该 Ctrl 互斥只覆盖同一进程；多进程部署不在保证范围内，最终 realpath 冲突仍由 Node 拒绝。

### 3. 状态机、终态与审计

所有清理入口共用同一任务状态机（手动/定时/升级只在 trigger、operator、escalation 与入口资格上不同）：

| 状态 | 进入条件 | 数据库 | 结果日志 | 键 |
| --- | --- | --- | --- | --- |
| `accepted` | 本地登记成功、线程已启动 | 未清理 | 不写 | 持有 |
| `running` | Node 启动返回合法 `task_id` | 未清理 | 不写 | 持有 |
| `succeeded` | Node 状态 `succeeded` 且清理事务提交 | `cleaned_at`/`mount_cleaned` 已写 | 恰一条成功 | 释放，保留终态摘要 |
| `failed` | Node 明确失败、启动被明确拒绝 | 未清理 | 恰一条失败 | 释放，保留终态摘要 |
| `unknown` | 超时、任务丢失、坏响应、Node 重启、落库失败 | 未清理 | 恰一条失败/未知 | 释放，保留终态摘要 |

关键规则：

- `accepted`、`running`、Node 启动成功都不等于清理成功；只有 `succeeded` 才能进入成功事务。
- 成功事务复用现有 `container_mount_cleanup_repo.mark_cleaned` 与 deleted 快照 `mark_mount_cleaned`，在同一个 `session_scope()` 中提交；清理记录或快照缺失时按既有语义处理，不能只写其中一边。
- 成功事务提交后才写成功日志。日志写入是既有 `write_operation_log` 语义：不抛异常、不影响已提交的清理结果。
- Node `succeeded` 但事务失败时，任务进入 `unknown`，原因 `cleanup_persist_failed`，写失败结果日志；不得重试成成功、不得写成功日志。目录可能已删除，这是无法用本变更消除的不一致。
- Node 明确 `failed` 或启动拒绝时进入 `failed`，失败原因经 `safe_reason` 白名单收敛；未知原因落到 `cleanup_failed`。
- 超时、离线、坏响应、`task_id` 丢失、Node 重启、`task_id` 不匹配进入 `unknown`，未知原因落到 `cleanup_result_unknown` 或对应的 `node_*`；不得写成功。
- 终态迁移在锁内完成，只有一个线程能把任务从非终态改为终态；结果日志由赢得迁移的线程写一次。进程在迁移与日志之间崩溃时日志可能缺失，属于本变更接受的进程内状态丢失，不补记。
- 成功/失败日志与 `escalation` 写入使用任务提交时保存的 trigger/operator/escalation；定时/升级调度器只读取提交结果，MUST NOT 在 `accepted` 时写 `cleaned_at`、`mount_cleaned` 或成功日志。
- 已清理记录再次请求时走幂等分支：不创建任务、不写结果日志、不改时间戳。

轮询参数作为模块常量，测试可替换：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| 启动请求超时 | 10 秒 | 避免 HTTP 请求长时间占用 |
| 状态请求超时 | 5 秒 | 单次轮询预算 |
| 轮询间隔 | 1 秒 | Ctrl 后台轮询频率 |
| 瞬时通信失败重试间隔 | 2 秒 | timeout/连接失败/5xx 的短退避 |
| 连续通信失败上限 | 3 次 | 达到后进入 `unknown` |
| 轮询总期限 | 无 | 只要 Node 可访问且持续返回 `running`，Ctrl 必须继续间隔轮询 |
| 启动后任务状态上限 | 进程内有界 | 由 Node 协作约定保证；Ctrl 不依赖无限历史 |

Node 的异步删除没有固定时限，Ctrl 不得设置累计总期限把持续 `running` 的结果误判为未知。状态查询遇到 timeout、连接失败或 5xx 时，Ctrl 以短间隔重试；连续失败达到上限才进入 `unknown`，期间不写结果日志、不释放占位。成功收到 `running` 会把连续失败计数重置为 0。`task_not_found` 或 Node 实际返回的 HTTP 404 + `error_reason=not_found` 是 Node 重启/任务状态丢失的明确信号，直接进入 `unknown` 并记 `node_task_lost`，不继续重试；状态端点 404/405 且无该任务缺失结构直接进入 `unknown` 并记 `node_unsupported`；坏响应、`task_id` 不匹配等同样不得当成功。达到失败上限或明确任务丢失后释放键，但 Node 可能仍在删除；恢复按钮会重新开放，用户已明确接受目录部分删除的风险。Ctrl 不再追查该 `task_id`，也不在后续列表中把该结果补写为成功。

### 4. Node 协议、错误映射与旧端点

Ctrl 对 Node 的调用严格按暂定协议：

启动请求：

```json
{"config": {"mount_path": "<最终清理路径>"}}
```

成功响应必须为：

```json
{"success": 1, "task_id": "<非空任务标识>"}
```

状态请求：

```json
{"config": {"task_id": "<启动返回的标识>"}}
```

状态响应必须包含：

```json
{"task_id": "<与请求匹配>", "state": "running|succeeded|failed", "error_reason": null|"<稳定原因>"}
```

解析规则：

- `task_id` 接受非空字符串或正整数，统一转字符串比较；空值、布尔值、对象、数组、缺失均为坏响应。
- `state` 只接受小写三值；`running`/`succeeded` 的 `error_reason` 必须为空；`failed` 的 `error_reason` 必须是非空稳定字符串。
- 状态响应的 `task_id` 必须与请求完全匹配；不匹配、缺字段、重复歧义或形状错误按 `node_bad_response` 处理为未知。
- 启动响应 `success=1` 但缺 `task_id` 是未知，不是失败；Ctrl 不启动轮询。
- 启动返回重复冲突（HTTP 409 或结构化 `cleanup_in_progress`）是明确失败，不标记已清理。
- 启动返回 404/405 是 `node_unsupported` 失败，说明旧 Node 无异步端点；手动、定时、升级入口都不回退旧 `/clean_mount`。
- 手动入口在启动前由 Ctrl 后台执行新鲜路径检查；`not_found`/权限/非法路径在启动前失败。定时/升级不执行该前置检查，Node 启动对缺失路径按旧 `/clean_mount` 的 `rm -rf` 幂等语义成功。
- 状态查询明确返回 `task_not_found`，或 HTTP 404 + `error_reason=not_found`（Node 实际任务缺失形状）时直接按未知处理并记 `node_task_lost`；状态查询返回 404/405 且响应体没有该任务缺失结构时直接按未知处理并记 `node_unsupported`，不得当成功或无限重试。
- 传输超时、连接失败、5xx 在启动阶段归未知；在轮询阶段按短间隔重试，连续失败达到上限才归未知；成功收到 `running` 重置连续失败计数。Node 可访问且持续返回 `running` 时，Ctrl MUST 继续按间隔轮询，MUST NOT 以累计时长转未知或释放键。坏响应、`task_id` 不匹配不走瞬时重试，直接未知。
- 所有原因经 `safe_reason` 白名单；未知 Node 文本不得进入 HTTP 或审计。

Node 侧协作约定（不在本仓库实现）：

- 同一 realpath 的启动必须原子校验并登记，重复启动返回冲突。
- Node 的同步 `/clean_mount`、异步 `start_clean_mount` 和恢复预留共用同一 realpath 登记。
- `/create_container` 在受理前对 `restore_mount_path` 取 realpath 并登记恢复预留；同一 realpath 已有清理或恢复时，Node MUST 在受理前拒绝，MUST NOT 启动创建；Node 预留覆盖后台创建/账号恢复结束或失败，并在 `finally` 释放。
- 预留释放后 Node 不再保留恢复互斥；清理启动不额外检查 Docker Source 活挂载，正常按既有路径语义登记/删除。Ctrl 词法键只覆盖同词法路径，别名尾段不由 Node 兜底。
- 任务状态是进程内有界状态，任务完成后可保留有限时间；异步删除没有固定时限。
- Node 退出时必须终止本次清理派生的子进程；重启后旧 `task_id` 与恢复预留不可查。Ctrl 以未知处理，不补记成功；Node 重启导致预留丢失是用户接受的边界。
- 旧同步 `/clean_mount` 仅保留给旧客户端/旧 Ctrl；当前 Ctrl 的手动、定时、升级入口都只调用新端点，不回退旧端点。
- `start_clean_mount` 对缺失路径的幂等成功语义与旧 `/clean_mount` 一致；手动 `not_found` 由 Ctrl 前置检查拦截，不由 Node 启动拒绝。

### 5. 恢复互斥与关键阶段覆盖

在 `resurrect_container` 中，`_load_restore_target` 仍保持只读，并在其成功后、`_ensure_restore_mount_source` 之前取得恢复占位：

```text
target = _load_restore_target(deleted_id)
with restore_guard(target.machine_id, target.mount_path, deleted_id):
    _ensure_restore_mount_source(target)
    _load_restore_accounts(target)
    _resolve_restore_image(target, content_source)
    if requires_choice: return ...   # with 退出即释放
    _ensure_restore_long_term_capacity(...)
    Create_container(...)
    _restore_long_term_state(...)
    _delete_restore_artifacts(...)
    _audit_restore_success(...)
    return ...
```

`restore_guard` 在锁内检查同键：

- 有活动清理（`accepted`/`running`）→ 抛既有 `NodeServiceError(reason="cleanup_in_progress")`；不调用路径探测、不创建、不消费快照、不写成功审计。
- 有另一个恢复占位 → `restore_in_progress`；不开始第二次恢复。
- 只有终态 `failed`/`unknown` 摘要 → 允许，因为用户明确接受清理中断后目录可能部分删除；实际能否恢复由 `_ensure_restore_mount_source` 的 Node 新鲜路径检查决定。目录不存在仍以 `data_not_recoverable` 拒绝；目录存在但内容已部分删除时恢复继续，风险由用户承担。
- 占位从路径复核前一直持有到成功/失败返回；`requires_choice` 没有创建副作用，也在返回前释放。

Ctrl 的词法键覆盖 Ctrl 整个恢复过程，但只对词法相同的路径生效；Node 的 realpath 预留覆盖 `/create_container` 受理前到后台创建/账号恢复结束（或失败），两者对符号链接别名并非全程等价。`Create_container` 在 Node 请求中携带 `restore_mount_path`；Node 在 `/create_container` 受理前取 realpath，和同步/异步清理共用登记。若同一 realpath 已有清理或恢复，Node 在受理前返回 `cleanup_in_progress`/`restore_in_progress`，Ctrl 必须原样上抛，保留快照与清理记录，不写成功审计、不返回凭据。Ctrl 词法键不同不构成重试或放行理由。

明确尾段缺口：Node 预留随创建/账号恢复结束释放后，Ctrl 仍在做长期状态恢复、快照与清理记录消费；此时另一条清理若用不同词法别名指向同一 realpath，Ctrl 词法键不会拦，Node 预留也已释放。本变更不为该尾段增加 Docker Source 活挂载检查、数据库、分布式锁或旁路；Node 清理按既有路径登记/删除语义执行。因此系统 MUST NOT 宣称两个锁对符号链接别名全程等价，Ctrl 词法键只能保证同词法路径；该尾段是已明确的边界。若要消除它，应另开变更让 Node 预留持续到 Ctrl 显式释放（需要协议层显式释放），不属于本变更。

互斥范围汇总：

| 机制 | 键 | 实际覆盖 |
| --- | --- | --- |
| Ctrl 清理任务 | `(machine_id, 词法路径)` | 同一 Ctrl 内，从登记到 Node 终态/未知；词法别名不互相阻塞 |
| Ctrl 恢复占位 | `(machine_id, 词法路径)` | 同一 Ctrl 内，从路径复核前到快照/清理记录消费完成；词法别名不互相阻塞 |
| Node 清理/恢复登记 | 单机 realpath | 清理任务或恢复预留持有期间，同一 realpath 的重复清理/恢复被拒绝 |
| Node 恢复预留 | 单机 realpath | `/create_container` 受理前到后台创建/账号恢复结束；释放后 Node 不保留恢复互斥 |
| 恢复预留释放后的尾段 | 无 Node 预留 | 仅 Ctrl 词法键；词法别名不保证被拦截，不增加 Docker Source 活挂载门禁 |

失败审计 `_audit_restore_failure` 放在占位作用域内，在快照未被消费时完成，保持“成功/失败返回前不放开清理”的一致性。

Ctrl 重启后恢复占位全部丢失，恢复立即重新开放；不查询旧清理任务、不补写状态。若旧 Node 清理仍在运行，恢复可能与其交叉；这是“Ctrl 重启丢状态”的已接受风险，单进程设计无法消除。

自动/升级清理在恢复期间必须跳过：调度器在提交异步任务前尝试同键清理占位，失败则继续下一条记录/保留 escalation 记录，不写成功审计。这样恢复关键阶段不会被同 Ctrl 的词法同路径清理删除目录；Node 侧 realpath 共享登记只在恢复预留/清理任务持有期间兜底别名，预留释放后的尾段不保证。

### 6. 已删除列表的清理状态投影

`DeletedContainerRecord` 增加两个响应字段，不新增数据库列：

```text
mount_cleanup_state: "cleaning" | "failed" | "unknown" | null
mount_cleanup_error_reason: str | null
```

`serialize_deleted_container_record` 在拼装记录时：

1. 用既有 `cleanup.id`（或 `row.mount_cleanup_id`）查进程内任务；没有则用 `(context.machine_id, canonical(context.mount_path))` 查。
2. 活动 `accepted`/`running` → `cleaning`。
3. 终态 `failed`/`unknown` 且在保留期内 → 对应状态与稳定原因。
4. 无任务、已成功、摘要过期或 Ctrl 重启 → `null`。
5. `data_recoverable` 改为：

```text
bool(mount_path and not mount_cleaned) and state != "cleaning"
```

因此失败/未知后 `data_recoverable=true`，恢复按钮重新开放；清理中为 false。已清理记录仍由 `mount_cleaned=true` 使 `data_recoverable=false`。

列表读取只查进程内登记和既有数据库行，不写库、不调用 Node、不 `os.stat`；目录不存在仍返回记录与历史路径，不报 500、不伪造已清理。进程内摘要过期只是不再显示状态，不改变数据库记录。

### 7. 有界性、容量与 Ctrl 重启

登记表和后台执行都是有界的：

| 限制 | 默认值 | 行为 |
| --- | --- | --- |
| 活动清理任务数 | 128 | 超过后新手动清理返回 `cleanup_capacity_exhausted`（503），不登记、不请求 Node |
| 终态摘要数 | 512 | 超过后按结束时间淘汰最旧摘要 |
| 终态摘要 TTL | 900 秒 | 过期后不再出现在列表，不改变数据库 |
| 后台轮询线程 | 每任务一个 daemon 线程，受活动上限约束 | 线程在终态/未知/异常时结束 |
| 恢复占位 | 仅活动请求持有 | 成功/失败/二选一返回时 `finally` 释放，不保留终态 |

后台线程必须在最外层 `try/except/finally` 中收敛异常：任何未预期异常都转入 `unknown`、释放键、尽力写失败日志，不能让任务永久停留在 `running` 或让线程泄漏。线程停止不依赖进程内持久队列。

Ctrl 重启或进程退出：

- 所有活动任务、终态摘要、Node `task_id`、轮询线程和恢复占位丢失。
- 不执行启动补偿，不读取 Node 历史，不根据目录是否存在补写 `cleaned_at`、`mount_cleaned` 或成功日志。
- 列表按数据库现状显示，`mount_cleanup_state=null`，`data_recoverable` 按未清理口径为 true（除非 `mount_cleaned=true`）。
- 目录不存在时列表仍正常展示历史路径；恢复请求仍由 Node 新鲜路径检查决定是否 `data_not_recoverable`。

### 8. 异步入口、调度器与旧同步端点

当前 Ctrl 的三个入口统一调用提交服务，不再调用旧同步 `clean_mount_path`/`/clean_mount`：

- 手动 API：`trigger="manual_clean_mount"`、`operator_user_id` 为当前用户、不改变 escalation；后台先做手动新鲜路径检查，再启动 Node。
- `schedulers/container_mount_cleanup_task.py:27-76`：保留 14 天/机器在范畴等资格检查，ensure/adopt 后提交 `trigger="auto_mount_cleanup"`、`operator=None`、`escalation` 不改变；提交成功只记录运行日志“已受理”并继续，MUST NOT 标记 cleaned、MUST NOT 写结果 oplog；同键忙则跳过本轮，容量不足则停止本轮并留待下一轮。
- `schedulers/container_disk_check_task.py:461-509` 的 `_clean_mount_immediately`：在容器删除后确保 `escalation=True` 的清理记录，提交 `trigger="disk_escalation"`、`operator=None`、`escalation=True`；提交成功即返回，不等待删除，后续成功/失败由后台任务写入并保留 escalation 记录；同键忙/容量不足记录错误，不自动重试。
- `services/container_module/mount_cleanup.py` 的同步 `clean_mount_path` 不再是生产入口；如保留只能作为旧调用方适配或测试 seam，MUST NOT 被当前三种入口调用。

旧同步 `/clean_mount` 只保留给旧客户端/旧 Ctrl；Node 仍让它与异步清理/恢复预留共用 realpath 登记。兼容矩阵：

| Ctrl | Node | 手动 | 自动/升级 | 恢复互斥 |
| --- | --- | --- | --- | --- |
| 新 | 新 | 异步任务 | 异步任务 | Ctrl 词法前置 + Node realpath 兜底 |
| 新 | 旧 | `node_unsupported` 失败 | `node_unsupported` 失败；自动记录留待重试，升级保留 escalation 记录 | Ctrl 词法前置仅同路径；旧 Node 无 realpath 兜底 |
| 旧 | 新 | 旧同步 `/clean_mount` | 旧同步 `/clean_mount` | 旧 Ctrl 无异步互斥保证 |

API 兼容性：`POST /api/containers/clean_deleted_container_mount` 的路径与请求体不变；响应从“已完成”变为“已受理”，新增 `accepted`/`already_cleaned`/`mount_cleanup_state`。旧 Web 若把 `success=1` 当完成，会误判；Web 必须随本变更更新。`list_deleted_containers` 只新增字段，旧 Web 可忽略。

### 9. 错误原因与 HTTP 状态

在 `services/container_module/exceptions.py` 的 `SAFE_REASON_CODES` 增加：

- `cleanup_in_progress`
- `restore_in_progress`
- `cleanup_capacity_exhausted`
- `cleanup_not_accepted`
- `cleanup_result_unknown`
- `cleanup_persist_failed`
- `cleanup_failed`

在 `api/container_api.py` 的 `REASON_STATUS_MAP` 增加：

| reason | 状态码 | 使用场景 |
| --- | --- | --- |
| `cleanup_in_progress` | 409 | 同键已有清理；或恢复被清理阻止 |
| `restore_in_progress` | 409 | 同键已有恢复；或清理被恢复阻止 |
| `cleanup_capacity_exhausted` | 503 | 活动任务达到上限 |
| `cleanup_not_accepted` | 500 | 后台线程无法启动，登记已回滚 |

`cleanup_result_unknown`、`cleanup_persist_failed`、`cleanup_failed` 只作为结果日志/内部状态原因，不作为已受理请求的 HTTP 响应。Node 的 `node_unsupported`/`node_timeout`/`node_unavailable`/`node_bad_response` 继续沿用既有 502/504/503/502 映射；`not_found` 404、`container_exists` 409、`permission_denied` 403、`invalid_path` 400 不变。

登记冲突和容量拒绝不写清理结果日志，因为没有创建清理任务；既有预检失败（记录不存在、活容器等）仍按 `_audit_mount_preflight_failure` 留失败审计。任务创建后的所有可观测失败/未知都写结果日志。

## Risks / Trade-offs

- [失败或中断可能部分删除目录] → 清理记录保持未清理，失败/未知后恢复按钮重新开放；用户明确接受目录可能只剩一部分。恢复仍先做 Node 路径检查，但存在性通过不代表内容完整，这是无法自动消除的数据风险。
- [通信失败达到上限后 Node 可能仍在删除] → 没有固定总期限；只要 Node 可访问且持续 `running`，Ctrl 会一直轮询。timeout/连接失败/5xx 只做有限连续重试，达到上限后转 unknown 并释放键，恢复可能与仍在运行的 Node 删除交叉。Node 退出终止子进程、Ctrl 重启丢状态是用户接受的边界；单进程 Ctrl 无法在失去 `task_id` 后继续确认。
- [Ctrl 重启丢失且可能与旧 Node 任务交叉] → 重启后不补查、不补记，恢复立即开放；旧 Node 任务可能继续。这是进程内状态设计的直接代价，需在部署说明中明确。
- [Ctrl 词法键与 Node realpath 预留并非全程等价] → Ctrl 词法键覆盖整个恢复但只对词法同路径；Node realpath 预留覆盖 `/create_container` 受理前到后台创建/账号恢复结束。预留释放后到 Ctrl 完成快照消费之间存在尾段；本变更不增加 Docker Source 活挂载检查、数据库、分布式锁或旁路，Node 按既有路径语义清理。因此该尾段的词法别名清理不被保证拦截，不能宣称别名全程安全；若需覆盖应另开变更延长 Node 预留或引入显式释放协议。
- [多 Ctrl 进程没有共享锁] → 每个进程各自登记，跨进程仍可能重复清理或与恢复交叉。本设计只保证单进程；多 worker 部署必须改为单 worker/sticky 或另做共享协调，不能声称已有跨进程互斥。
- [全局登记锁的临界区] → 锁只覆盖登记/状态迁移，不覆盖 Node 调用和长事务；ensure/adopt 在占位内执行但仍可能短暂阻塞同进程的其他登记。手动清理频率低，优先正确性。
- [进程内摘要不是持久事实] → 列表的 `cleaning`/`failed`/`unknown` 会随重启或 TTL 消失；数据库只保留 `cleaned_at`/`mount_cleaned`。UI 必须把摘要当“尽力提示”，不能当成功凭据。
- [审计可能缺失] → 进程在终态迁移与日志写入之间崩溃会丢一条日志；不补记。成功日志只在事务提交后写，绝不在受理或 Node 启动成功时写。
- [旧 Node 所有清理入口不可用] → 新 Ctrl 对旧 Node 的手动、自动、升级异步任务都以 `node_unsupported` 失败/保留待处理；当前 Ctrl 不回退旧 `/clean_mount`。部署必须先把 Node 升级到含新端点与 realpath 共享登记的版本；旧端点只为旧客户端/旧 Ctrl 保留。
- [内存与线程上限拒绝服务] → 活动任务达到 128 时手动清理返回 503，定时清理延后一轮，升级清理保留 escalation 记录；这是有界性的代价，避免无界线程/内存。常量需按实际并发调整。

## Migration Plan

1. 先部署 Node：实现 `start_clean_mount`/`get_clean_mount_status`、`/create_container` realpath 恢复预留、同步/异步清理共享 realpath 登记、进程内有界任务、退出终止清理子进程；旧 `/clean_mount` 仅为旧客户端/旧 Ctrl 保留。
2. 部署 Ctrl：上线登记表、状态机、Node 调用与日志，手动 API 返回受理；定时扫描与磁盘升级清理改为提交同一异步任务，保留资格、trigger、escalation 与日志语义，调度器不把 accepted 当 cleaned。无数据库迁移，不需要回填。
3. 更新 Web：清理按钮只等 `accepted=true`，通过已删除列表的 `mount_cleanup_state` 与操作日志展示清理中/失败/未知；恢复按钮在 `data_recoverable=true` 时开放，并提示失败/未知/重启后目录可能部分删除。
4. 验证：用假 Node 覆盖协议形状、瞬时通信失败重试与 running 重置、连续失败上限、`task_not_found`、HTTP 404 + `error_reason=not_found`、旧端点缺失、持续 running 不截断、重复/别名冲突、三种 trigger/escalation 日志、调度器 accepted≠cleaned、恢复关键阶段和 Ctrl 重启；再做一次真实 Node 冒烟，确认旧 `/clean_mount` 仅旧客户端可用且当前 Ctrl 未调用。
5. 回滚：回退 Ctrl 代码即可；数据库无变更。回退会恢复旧同步三入口语义，进程内登记和异步任务全部消失；Node 新端点可保留，旧 `/clean_mount` 仍兼容。

## Open Questions

无。三仓协议字段、错误码或路径规范化若在实现前变更，必须回到 proposal/design/specs 更新并重新评审，不在实现中自行扩展；多 Ctrl 进程互斥属于独立变更，不在本变更内承诺。
