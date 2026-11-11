# Spec Delta

## MODIFIED Requirements

### Requirement: deleted_container_restore_snapshot 生产职责与生命周期

系统 SHALL 以 snapshot 保存重建输入、mount_cleaned 标识挂载可复用性，并在恢复成功后才消费一次性快照及对应清理记录。恢复在产生任何副作用前 SHALL 按 `(machine_id, 规范化 mount_path)` 取得恢复占位并检查同一键的清理状态；清理为 `accepted`/`running` 时 MUST 以 `cleanup_in_progress` 拒绝，保留快照与清理记录，MUST NOT 调用 Node 创建或路径复核、MUST NOT 消费快照或写成功审计。恢复占位 SHALL 覆盖挂载路径复核、`Create_container`、长期状态恢复、快照与清理记录消费直到成功/失败返回。清理失败或结果未知时恢复 SHALL 重新开放，实际能否恢复由 Node 路径复核决定；目录可能已部分删除，用户明确接受该风险。

#### Scenario: 完成复活

- **WHEN** 恢复门户成功重建容器、完成账号与长期状态还原，并消费快照和对应清理记录
- **THEN** 释放该键的恢复占位，后续清理可按新状态重新登记；一次成功恢复只消费一次快照

#### Scenario: not_found 不消费快照

- **WHEN** 同一键没有活动的清理占位，而恢复动作前的 Node 路径检查返回 `not_found`
- **THEN** 恢复以 `data_not_recoverable` 拒绝并释放恢复占位；恢复快照与对应清理记录保留、`mount_cleaned` 保持原值，MUST NOT 删除快照或写成功审计

#### Scenario: 权限与非法路径不消费快照

- **WHEN** 同一键没有活动的清理占位，而恢复动作前的 Node 路径检查返回 `permission_denied` 或 `invalid_path`
- **THEN** 恢复以各自稳定原因拒绝并释放恢复占位；快照与清理记录保留，MUST NOT 消费快照、改写清理状态或写成功审计

#### Scenario: 无法得出结论必须阻断并保留快照

- **WHEN** 同一键没有活动的清理占位，而恢复动作前的路径检查因旧 Node 不支持、超时、离线或坏响应无法得出结论
- **THEN** Ctrl 以对应的 `node_unsupported`/`node_timeout`/`node_unavailable`/`node_bad_response` 阻断并释放恢复占位；快照与清理记录保留，MUST NOT 继续 `Create_container`、消费快照或写成功审计，也不把结果写成 `not_found`/`data_not_recoverable`

#### Scenario: 清理中拒绝恢复

- **WHEN** 同一键的手动清理处于 `accepted` 或 `running`
- **THEN** 恢复 MUST 以 HTTP 409 与 `cleanup_in_progress` 拒绝；快照与清理记录保持原样，MUST NOT 调用 Node 路径复核或创建、MUST NOT 消费快照、MUST NOT 返回凭据或写成功审计

#### Scenario: 恢复占位覆盖关键阶段

- **WHEN** 恢复已取得同一键的占位并正在进行挂载路径复核、`Create_container`、长期状态恢复或快照消费
- **THEN** 新清理 MUST 被 `restore_in_progress` 拒绝；恢复占位 MUST 持续到这些阶段完成或因异常退出

#### Scenario: 恢复二选一或失败时释放占位

- **WHEN** 恢复返回 `requires_choice=true` 而未创建容器，或恢复因任何错误终止
- **THEN** 在返回调用方前释放恢复占位；失败分支保留快照与清理记录，不写成功审计，后续清理或恢复可重新登记

#### Scenario: 清理失败后恢复重新开放

- **WHEN** 同一键的清理终态为 `failed`
- **THEN** 恢复 SHALL 重新开放，不再因该清理终态返回冲突；Node 路径复核为 `present` 时按既有恢复流程继续，目录不存在时以 `data_not_recoverable` 拒绝；用户接受目录可能已被部分删除

#### Scenario: 清理结果未知后恢复重新开放

- **WHEN** 同一键的清理结果因超时、任务丢失或 Node 重启而为未知
- **THEN** 恢复 SHALL 重新开放，不再因该未知结果返回冲突；Ctrl MUST NOT 把快照标为已清理或阻止恢复请求，实际能否恢复仍由 Node 路径复核决定

#### Scenario: Ctrl 重启后恢复重新开放

- **WHEN** Ctrl 重启丢失全部进程内清理占位与未知终态
- **THEN** 同一删除记录的恢复 SHALL 重新开放，MUST NOT 等待或补查旧轮询结果；快照与清理记录按数据库现状读取

#### Scenario: 重复恢复冲突

- **WHEN** 同一键已有恢复占位又收到第二次恢复请求
- **THEN** 第二次请求 MUST 以 `restore_in_progress` 拒绝，不调用 Node 创建、不消费快照，也不释放第一次的占位

#### Scenario: 清理成功消费后不可恢复

- **WHEN** 清理已明确成功并已消费快照或写入 `mount_cleaned=true`
- **THEN** 恢复按既有 `data_not_recoverable` 拒绝，不因进程内终态摘要过期而重新开放

## ADDED Requirements

### Requirement: Node realpath 恢复预留与共享登记

Node SHALL 在 `/create_container` 受理前对 `restore_mount_path` 取 realpath 并登记恢复预留；该预留 MUST 与同步 `/clean_mount`、异步 `start_clean_mount` 的 realpath 登记共用同一身份集合。同一 realpath 已有清理或恢复预留时，Node MUST 在受理前拒绝创建，MUST NOT 启动容器创建；预留 SHALL 覆盖后台创建/账号恢复完成或失败，并在 `finally` 释放。预留释放后 Node 不再保留恢复互斥；Ctrl 词法键只覆盖词法同路径，系统 MUST NOT 宣称两锁对符号链接别名全程等价，也 MUST NOT 增加 Docker Source 活挂载门禁来补尾段。

#### Scenario: 创建受理前 realpath 预留

- **WHEN** Ctrl 发起恢复，Node 在 `/create_container` 受理前发现 `restore_mount_path` 的 realpath 已有清理或恢复预留
- **THEN** Node MUST 在受理前以 `cleanup_in_progress` 或 `restore_in_progress` 拒绝，MUST NOT 启动容器创建；Ctrl 保留快照与清理记录，不写成功审计、不返回凭据

#### Scenario: 词法别名由 Node realpath 拒绝

- **WHEN** Ctrl 词法键不同但 Node realpath 指向同一真实路径，另一清理或恢复正在使用该路径
- **THEN** Node MUST 以共享 realpath 登记拒绝第二个操作；Ctrl 词法前置未拦截不构成放行理由，冲突按失败/未知处理且不写成功

#### Scenario: 预留释放与创建/账号恢复失败

- **WHEN** Node 恢复预留期间后台创建/账号恢复成功、失败或进程退出
- **THEN** 成功/失败路径 SHALL 在 `finally` 释放预留；Node 重启丢失预留属于已接受的重启边界；释放后同一 realpath 的清理可重新登记，不追加 Docker Source 活挂载检查；若此时 Ctrl 尚未完成快照消费，词法别名清理属于已知尾段边界

### Requirement: 已删除容器列表清理状态投影

Ctrl SHALL 在 `POST /api/containers/list_deleted_containers` 每条记录中返回由本进程清理登记导出的 `mount_cleanup_state` 与可空 `mount_cleanup_error_reason`，取值 SHALL 为 null、`cleaning`、`failed`、`unknown`。清理占位存在时 MUST 返回 `cleaning`，且 `data_recoverable=false`；失败/未知终态摘要存在时 SHALL 返回对应状态，`data_recoverable` 按 `mount_path` 存在且 `mount_cleaned=false` 计算；无相关登记时为 null。列表读取 MUST NOT 写数据库、调用 Node 或因目录不存在而失败。

#### Scenario: 清理中列表展示

- **WHEN** 某条已删除记录的清理任务处于 `accepted` 或 `running`
- **THEN** 列表记录返回 `mount_cleanup_state="cleaning"`、`mount_cleanup_error_reason=null`、`data_recoverable=false`，并保留 `cleaned_at=null` 与 `mount_cleaned=false`

#### Scenario: 失败终态列表展示

- **WHEN** 同一键的清理任务已明确失败且终态摘要在保留期内
- **THEN** 列表返回 `mount_cleanup_state="failed"` 与稳定 `mount_cleanup_error_reason`；存在挂载路径且未清理时 `data_recoverable=true`

#### Scenario: 未知终态列表展示

- **WHEN** 同一键的清理结果未知且终态摘要在保留期内
- **THEN** 列表返回 `mount_cleanup_state="unknown"` 与稳定 `mount_cleanup_error_reason`；存在挂载路径且未清理时 `data_recoverable=true`，不把未知写成已清理

#### Scenario: 无进程内登记

- **WHEN** 同一键没有活动清理、失败摘要或未知摘要
- **THEN** 列表返回 `mount_cleanup_state=null`，`data_recoverable` 继续按“存在挂载路径且 `mount_cleaned=false`”计算

#### Scenario: 清理成功后的列表

- **WHEN** 清理已明确成功并提交 `cleaned_at`/`mount_cleaned`
- **THEN** 列表返回 `mount_cleaned=true`、`cleaned_at` 非空、`data_recoverable=false`；不因进程内成功摘要过期而回退为可恢复

#### Scenario: Ctrl 重启后的列表

- **WHEN** Ctrl 重启清理了全部进程内状态，而数据库记录仍未清理
- **THEN** 列表返回 `mount_cleanup_state=null`，仍按数据库显示未清理与可恢复；MUST NOT 补写 `cleaning`、`failed` 或 `unknown`

#### Scenario: 目录不存在仍正常展示

- **WHEN** 已删除记录的保留目录在 Node 上已不存在
- **THEN** 列表仍返回该记录、历史挂载路径与数据库清理状态，不因目录不存在而报错、隐藏记录或伪造 `mount_cleaned=true`

#### Scenario: 列表读取只读且不联系 Node

- **WHEN** 读取已删除容器列表
- **THEN** `mount_cleanup_state`/`mount_cleanup_error_reason` 只从本进程登记与既有数据库行投影，列表读取 MUST NOT 写数据库、调用 Node、探测文件系统或创建清理任务
