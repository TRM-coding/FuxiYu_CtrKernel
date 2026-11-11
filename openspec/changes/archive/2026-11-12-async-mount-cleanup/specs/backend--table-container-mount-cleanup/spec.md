# Spec Delta

## MODIFIED Requirements

### Requirement: container_mount_cleanup 生产职责与生命周期

系统 SHALL 以 deleted 快照为保留生命周期权威，本表保存执行路径、removed_at、cleaned_at、escalation；手动、定时与磁盘升级清理 SHALL 统一受理为 Ctrl 进程内异步任务，保留各自资格、trigger、escalation 与日志语义，MUST NOT 等待旧同步 `/clean_mount` 完成。手动清理在产生清理副作用前 MUST 完成原容器有效态检查、记录可执行检查、手动路径新鲜检查和按 `(machine_id, 词法规范化 mount_path)` 的原子登记；原容器有效时 MUST 以 `container_exists` 拒绝；记录已清理时 SHALL 返回幂等结果。只有 Node 任务明确 `succeeded` 后，Ctrl 才 SHALL 在同一事务写入 `cleaned_at` 与 deleted 快照的 `mount_cleaned`。

#### Scenario: 清理成功

- **WHEN** Node 异步任务对指定挂载目录明确返回 `succeeded`，且 Ctrl 成功提交清理记录与 deleted 快照的同一事务
- **THEN** `container_mount_cleanup.cleaned_at` 非空、deleted 快照的 `mount_cleaned=true`；结果日志写入成功时恰好一条成功日志，日志写入失败不改变已提交的清理状态

#### Scenario: 手动清理前新鲜检查通过

- **WHEN** Ctrl 受理后，后台先对目标路径执行手动新鲜检查并得到 `present`，随后 Node 的 `start_clean_mount` 返回 `task_id`
- **THEN** Ctrl 保持任务为清理中，只在后续状态明确 `succeeded` 后写入 `cleaned_at` 与 `mount_cleaned`；MUST NOT 回退调用旧同步 `/clean_mount` 完成删除

#### Scenario: 原容器已恢复为有效时拒绝手动清理

- **WHEN** 手动清理对应的原容器行存在且 `is_valid=true`
- **THEN** Ctrl 以 `container_exists` 拒绝并保留清理记录与 `mount_cleaned=false`，MUST NOT 创建任务、请求 Node 启动清理或写成功审计；该拒绝先于 Node 任务启动

#### Scenario: not_found 拒绝手动清理并保留记录

- **WHEN** 手动清理的后台新鲜路径检查返回 `not_found`
- **THEN** Ctrl 将任务记为失败并写失败结果日志；`cleaned_at` 保持为空、`mount_cleaned` 保持 false，MUST NOT 启动 Node 异步任务、调用旧同步 `/clean_mount` 或写成功审计

#### Scenario: 权限、非法路径与网络错误不误称 not_found

- **WHEN** 手动新鲜检查返回 `permission_denied`、`invalid_path`，或检查/Node 启动/轮询因旧 Node 不支持、超时、离线、坏响应而失败
- **THEN** Ctrl 以各自稳定原因记为失败或未知并保留清理记录未清理；MUST NOT 误报为 `not_found`、MUST NOT 标记已清理或写成功审计

#### Scenario: 自动与升级清理维持既有语义

- **WHEN** 定时清理或磁盘升级即时清理处理一条记录
- **THEN** 两者提交与手动相同的异步任务与后台轮询，分别保留 `auto_mount_cleanup`/`disk_escalation` trigger、`escalation` 标记、入口资格与最终日志语义；调度器 MUST NOT 把 `accepted` 当作 `cleaned`，缺失目录仍按旧 `/clean_mount` 的 `rm -rf` 幂等语义由 Node 任务成功处理，只有 Node 明确 `succeeded` 才落库并写成功日志

#### Scenario: 已清理记录幂等

- **WHEN** 手动清理请求对应的 `cleaned_at` 已非空或 deleted 快照的 `mount_cleaned=true`
- **THEN** Ctrl 返回既有的已清理结果，不创建清理任务、不请求 Node、不写第二条结果日志，也不改变既有时间戳

## ADDED Requirements

### Requirement: 手动挂载清理的受理与异步终态

Ctrl SHALL 在受理成功后返回 `accepted=true`，MUST NOT 在响应前等待 Node 清理完成。后台 SHALL 调用 `start_clean_mount` 获取 `task_id`，按有界间隔轮询 `get_clean_mount_status`。`running` 时保持清理中；只要 Node 可访问且持续 `running`，MUST 继续轮询，MUST NOT 设置累计总期限。状态查询遇到 timeout/连接失败/5xx SHALL 短间隔重试，`running` 重置连续失败计数；达到上限才 unknown。`task_not_found` 或 HTTP 404 + `error_reason=not_found` SHALL 直接 unknown；旧端点 404/405 且无该结构 SHALL 直接 unknown，不得重试成成功。仅 `succeeded` 可落库/成功审计；`failed` 写失败审计且不落清理标记；其他无法确认结果写未知/失败原因，MUST NOT 标记已清理或写成功审计。

#### Scenario: 受理不等待清理完成

- **WHEN** 手动清理的本地预检和原子登记成功
- **THEN** Ctrl 立即返回 `success=1`、`accepted=true`、清理记录标识与 `cleaning` 状态，不等待 Node 启动或删除完成；此时数据库 `cleaned_at` 仍为空且没有成功结果日志

#### Scenario: Node 任务运行中

- **WHEN** Ctrl 轮询到 Node 状态 `running`
- **THEN** 任务保持清理中，数据库不写 `cleaned_at`/`mount_cleaned`，不写成功结果日志，也不提前释放该键的清理占位；只要 Node 可访问且持续返回 `running`，Ctrl MUST 按间隔继续轮询，MUST NOT 因累计时长转未知或设置固定总期限

#### Scenario: 瞬时通信失败重试

- **WHEN** 状态查询连续出现 timeout、连接失败或 5xx，但未达到连续失败上限
- **THEN** Ctrl SHALL 等待短重试间隔后继续查询，任务保持清理中、不释放占位、不写结果日志；随后收到 `running` 时 SHALL 将连续失败计数重置为 0

#### Scenario: 连续通信失败达到上限

- **WHEN** timeout、连接失败或 5xx 连续出现并达到配置的连续失败上限
- **THEN** Ctrl 将任务记为未知并写失败/未知原因结果日志，保留清理记录未清理，释放占位；MUST NOT 标记 `cleaned_at`/`mount_cleaned` 或写成功结果日志

#### Scenario: Node task_not_found 直接未知

- **WHEN** 状态查询明确返回 `task_not_found`，或 Node 实际返回 HTTP 404 + `error_reason=not_found`（Node 重启或任务状态已丢失）
- **THEN** Ctrl SHALL 直接记为未知并写 `node_task_lost` 失败/未知原因日志，不得继续重试成成功，不得标记已清理或写成功日志

#### Scenario: 旧 Node 状态端点直接未知

- **WHEN** 状态查询返回 HTTP 404/405，且响应没有 `task_not_found` 或 `error_reason=not_found` 的任务缺失结构
- **THEN** Ctrl SHALL 直接记为未知并写 `node_unsupported` 失败/未知原因日志，不得把旧端点缺失当成功或无限重试

#### Scenario: Node 明确失败

- **WHEN** Node 状态为 `failed`，或启动请求被明确拒绝
- **THEN** Ctrl 将任务记为失败，写恰好一条失败结果日志，保留 `cleaned_at=null` 与 `mount_cleaned=false`，MUST NOT 写成功结果日志

#### Scenario: 结果未知不伪造成功

- **WHEN** 启动结果未知、状态查询达到连续失败上限、坏响应、`task_id` 丢失或 Node 重启导致无法确认终态
- **THEN** Ctrl 将任务记为未知并写失败/未知原因结果日志，保留清理记录未清理，MUST NOT 标记 `cleaned_at`/`mount_cleaned` 或写成功结果日志

#### Scenario: 明确成功但落库失败

- **WHEN** Node 返回 `succeeded`，但 Ctrl 写入 `cleaned_at` 与 `mount_cleaned` 的事务失败
- **THEN** Ctrl 不写成功结果日志，改记稳定失败原因，保留记录未清理；MUST NOT 用内存状态或后续推断补写成功

#### Scenario: 重复终态只留一条结果

- **WHEN** 同一任务的轮询重复返回相同终态或并发回调同时到达
- **THEN** Ctrl 只执行一次终态迁移，只写一条对应结果日志，不重复写成功或失败记录

### Requirement: 清理登记、重复冲突与恢复互斥

Ctrl SHALL 以 `(machine_id, 词法规范化绝对路径)` 为键维护进程内清理/恢复占位，并在同一临界区内完成校验与登记，使并发请求最多一个成功登记。该键仅作 Ctrl 前置拦截，最终 realpath 身份由 Node 共享登记兜底。同一键已有清理或恢复占位时，新的清理 MUST 以 `cleanup_in_progress` 或 `restore_in_progress` 冲突拒绝，MUST NOT 启动第二个 Node 任务。恢复占位 SHALL 从挂载路径复核前持有到创建、长期状态恢复、快照与清理记录消费完成；清理占位 SHALL 从登记持有到 Node 终态或结果未知。不同机器或 Node realpath 不同的路径 MUST NOT 互相阻塞。

#### Scenario: 同键并发清理只有一次受理

- **WHEN** 两个手动清理请求同时命中同一 `machine_id` 与同一规范化路径，且两者都通过预检
- **THEN** 只有一个请求返回 `accepted=true`，另一个返回 HTTP 409 与 `cleanup_in_progress`；Node 只收到一次启动请求

#### Scenario: 不同机器或不同真实路径不冲突

- **WHEN** 两个清理请求使用相同路径但不同机器，或同一机器上 Node realpath 不同的路径
- **THEN** 两个请求可分别登记并受理，不因进程内键而互相阻塞

#### Scenario: 词法别名由 Node realpath 兜底

- **WHEN** 两个清理/恢复请求的 Ctrl 词法键不同，但 Node 对路径取 realpath 后指向同一真实目录
- **THEN** Ctrl 的前置键可能放行两者，但 Node MUST 以共享 realpath 登记拒绝第二个清理或恢复；Ctrl MUST NOT 以词法键不同为由宣称安全或重试绕过，被拒任务/恢复按冲突失败且不写成功

#### Scenario: 清理中拒绝恢复

- **WHEN** 同一键的任务处于 `accepted` 或 `running`
- **THEN** 恢复请求 MUST 以 `cleanup_in_progress` 拒绝，快照与清理记录保持原样，MUST NOT 调用 Node 路径复核或创建、MUST NOT 消费快照或写成功审计

#### Scenario: 恢复中拒绝清理

- **WHEN** 同一键已有恢复占位覆盖恢复关键阶段
- **THEN** 新的手动清理 MUST 以 `restore_in_progress` 拒绝，MUST NOT 启动 Node 任务，也不写成功结果日志

#### Scenario: 定时与升级清理在恢复中跳过

- **WHEN** 定时清理或磁盘升级清理尝试处理一条记录，而同一键存在恢复占位
- **THEN** 本轮跳过该记录，不调用 `/clean_mount`、不写 `cleaned_at`/`mount_cleaned`、不写成功审计，留待后续周期

#### Scenario: 终态或未知后释放清理占位

- **WHEN** 手动清理任务进入 `succeeded`、`failed` 或未知终态
- **THEN** 该键不再阻止新的恢复或后续清理；终态摘要仅按有界保留规则存在，不构成新的清理占位

### Requirement: 清理状态的有界性与 Ctrl 重启丢失

Ctrl SHALL 仅在本进程内保存清理任务与终态摘要，并为任务数量、终态保留时间和后台轮询线程设置上限；超过活动任务上限时 MUST 拒绝新受理并返回稳定原因，终态摘要过期后 SHALL 被清理。Ctrl 重启或进程退出后，所有清理/恢复占位、任务 ID 与轮询 SHALL 丢失，MUST NOT 依据 Node 历史或目录状态补写成功记录、成功 oplog 或 `cleaned_at`；已删除列表 SHALL 按数据库现状显示，恢复按钮 SHALL 重新开放。

#### Scenario: 活动任务达到上限

- **WHEN** Ctrl 的进程内活动清理任务数已达配置上限
- **THEN** 新的手动清理 MUST 以稳定的容量原因拒绝，不登记任务、不请求 Node，也不静默丢弃请求

#### Scenario: 终态摘要过期

- **WHEN** 失败或未知终态摘要超过保留时间
- **THEN** Ctrl 清理该摘要，列表不再显示对应 `failed`/`unknown` 状态；数据库清理记录不被改写

#### Scenario: Ctrl 重启丢失轮询

- **WHEN** Ctrl 在任务 `accepted` 或 `running` 时重启
- **THEN** 进程内占位、Node `task_id` 和轮询全部丢失；Ctrl MUST NOT 恢复轮询、补写成功或失败日志、补写 `cleaned_at`/`mount_cleaned`

#### Scenario: 重启后 Node 已成功也不回填

- **WHEN** Ctrl 重启前 Node 已完成删除但 Ctrl 尚未提交清理标记
- **THEN** 重启后清理记录保持未清理、无成功结果日志；列表按数据库现状显示，恢复按钮重新开放，用户接受目录可能已不存在或部分删除

#### Scenario: 重启后目录不存在正常展示

- **WHEN** Ctrl 重启后已删除容器的保留目录已不存在
- **THEN** 已删除列表仍返回该记录与历史路径，不报 500、不伪造 `mount_cleaned=true`；后续用量或恢复查询按各自既有错误语义返回目录不存在

### Requirement: Node 异步清理协议与旧端点兼容

Ctrl SHALL 按暂定协议调用 Node：`start_clean_mount` 成功响应 MUST 为 `success=1` 且含非空 `task_id`；`get_clean_mount_status` MUST 含匹配的 `task_id`、`state=running|succeeded|failed`、`error_reason`。同一 realpath 的重复启动 MUST 冲突；Node 任务状态 SHALL 为进程内有界状态。Node 退出 MUST 终止本次清理子进程，重启后 MUST 丢弃旧任务；Node 启动对缺失目录 SHALL 保持旧 `/clean_mount` 的 `rm -rf` 幂等成功语义。旧同步 `/clean_mount` SHALL 仅保留给旧客户端/旧 Ctrl；当前 Ctrl 所有清理入口 MUST NOT 调用或回退到它。

#### Scenario: 启动成功响应

- **WHEN** Node 接受手动清理启动请求
- **THEN** 响应为 `success=1` 且 `task_id` 非空；Ctrl 以该 `task_id` 进行后续状态查询，不把启动成功当作清理成功

#### Scenario: Node 重复启动冲突

- **WHEN** Node 已存在同一规范化路径的清理任务，又收到新的启动请求
- **THEN** Node MUST 返回冲突而不是第二个任务；Ctrl 将本次任务记为失败或冲突，不标记已清理、不写成功结果日志

#### Scenario: 状态响应严格匹配

- **WHEN** Ctrl 查询 Node 任务状态
- **THEN** 只接受 `task_id` 与请求一致、`state` 属于三值之一且 `error_reason` 语义合法的响应；`running`/`succeeded` 的失败原因 MUST 为空，形状不符或任务 ID 不一致按坏响应处理为未知

#### Scenario: 旧 Node 缺新端点

- **WHEN** Node 对启动请求返回 HTTP 404/405
- **THEN** 手动、定时与升级清理均记为 `node_unsupported` 失败或保留待处理，保留记录未清理，MUST NOT 回退调用旧同步 `/clean_mount` 删除目录

#### Scenario: Node 重启丢失任务

- **WHEN** Node 重启后查询原 `task_id` 返回任务不存在或无法识别，或状态查询返回 HTTP 404/405
- **THEN** Ctrl 将结果记为未知，不标记已清理、不写成功结果日志，并释放该键的清理占位；恢复按钮重新开放，用户接受目录可能部分删除

#### Scenario: Node 退出终止清理子进程

- **WHEN** Node 进程退出或重启
- **THEN** Node MUST 终止本次清理已派生的子进程，不留下孤立删除进程；重启后旧 `task_id` MUST 不再可查，Ctrl SHALL 按未知处理，MUST NOT 补记成功

#### Scenario: 缺失目录按旧幂等语义处理

- **WHEN** 定时或磁盘升级清理的路径已不存在，且手动前置检查未参与该入口
- **THEN** Node 异步任务 SHALL 按旧 `/clean_mount` 的 `rm -rf` 幂等语义成功；Ctrl 只在 Node 明确 `succeeded` 后标记 cleaned，不得把 `accepted` 当作 cleaned；手动入口的 `not_found` 仍由 Ctrl 前置检查在启动前拒绝

#### Scenario: 路径规范化以 Node 为准

- **WHEN** Ctrl 的词法键与 Node realpath 身份相同，或 Ctrl 词法键不同但 Node realpath 指向同一真实路径
- **THEN** Ctrl 的词法键只作前置拦截，不替代 Node 的权限、symlink、越界或真实目录校验；Node 以 realpath 共享登记为最终身份，别名冲突 MUST 被 Node 拒绝，Ctrl MUST NOT 以自身键不同为由放行或重试删除
