# deleted_container_restore_snapshot

## Purpose

删除后用于复活的配置和挂载目录保留记录。本规格按表结构记录当前持久化与生命周期契约，字段声明以模型与服务为依据。未完成问题见 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: deleted_container_restore_snapshot 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `DeletedContainerRestoreSnapshot`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

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

### Requirement: 长期配额失败保留可重试恢复状态

长期容量校验 SHALL 在真正恢复操作的副作用之前进行。容量不足时 MUST NOT 复活容器、请求 Node 创建、消费恢复快照或清除挂载保留记录；调用方 SHALL 收到明确的超限失败，不能靠事后静默丢弃长期标记收尾。

#### Scenario: 失败后仍可恢复
- **WHEN** 长期恢复因数量已满而被拒绝
- **THEN** 原容器保持已删除，恢复快照及挂载清理记录保留；释放配额后可以重试

#### Scenario: 完成长期恢复
- **WHEN** 有容量且恢复成功
- **THEN** 长期标记和账号按快照恢复，并沿用原有成功时消费快照的规则

### Requirement: 已删除容器遗留挂载用量查询接口

Ctrl SHALL 提供 `POST /api/containers/get_deleted_container_mount_usage`。请求体 SHALL 只含 `deleted_ids`：正整数数组，最多 100；MUST NOT 接受宿主路径。成功响应 SHALL 为 `{success:1,usages:[{deleted_id,bytes,measured_at,pending,error}]}`，MUST NOT 返回 `path`。无挂载路径的项 MAY 省略且不得触发扫描；有历史路径的项 SHALL 不因清理标记而跳过查询。请求模型失败 SHALL 走现有 400 `invalid_payload`；缺 `container:manage` SHALL 走现有 403 `insufficient_permission`。该接口不改变周期 WSS 或既有列表/恢复/清理接口，也不新增 DB 列/表/JSON 迁移。

#### Scenario: 成功响应形状固定

- **WHEN** 请求合法且所有可查询项均成功
- **THEN** 返回 `success:1` 与 `usages` 数组；每项只有 `deleted_id`、`bytes`、`measured_at`、`pending`、`error`，不含 `path`

#### Scenario: 无挂载或已清理可省略

- **WHEN** 某个 `deleted_id` 没有可解析的挂载路径（包括已清理且无路径）
- **THEN** 该项可从 `usages` 省略，Ctrl 不请求 Node，也不返回旧缓存

#### Scenario: 已清理记录查询历史路径

- **WHEN** 某个 `deleted_id` 已标记清理，但仍有可解析的历史挂载路径
- **THEN** 按既有规则向对应 Node 查询该路径，返回成功、等待或错误结果，不更改清理记录、历史路径或恢复资格

#### Scenario: 非法请求与权限错误

- **WHEN** `deleted_ids` 非正整数、超过 100、混入宿主路径，或调用者缺少 `container:manage`
- **THEN** 分别返回现有 400 `invalid_payload` 或 403 `insufficient_permission`，且不发起 Node 请求

### Requirement: 已删除用量只读解析与目标机器定向

Ctrl SHALL 沿用既有 `container:manage`，MUST NOT 新增必须持有机器角色的门禁。`machine_id`/`mount_path` SHALL 从既有删除快照或挂载清理记录只读解析；`machine_id` 仅用于定向对应 Node，MUST NOT 接受浏览器路径，也不得把路径送错机器。MUST NOT 调用 `resolve_mount_cleanup_request` 或任何 ensure/adopt/insert/update/delete 写库路径，MUST NOT 写 `disk_*`、恢复快照、清理记录或其他 DB 行，也不以 inode/dev/PID/Docker ID 作为授权或匹配身份。

#### Scenario: 只读解析并定向

- **WHEN** 请求包含存在且有挂载路径的 `deleted_id`
- **THEN** Ctrl 从既有记录读取 `machine_id` 与 `mount_path`，只向该机器对应的 Node 发请求；不新增或改写任何 DB 行

#### Scenario: 浏览器路径或记录不完整

- **WHEN** 请求携带宿主路径，或记录无法解析出 `machine_id`
- **THEN** 不按浏览器路径扫描；该 id 返回 `not_found` 或省略，且不把请求发到其他机器

#### Scenario: 不调用写库解析

- **WHEN** 查询进行中
- **THEN** 不调用 `resolve_mount_cleanup_request`、不创建/采用清理记录、不写 `disk_*`/恢复快照/清理记录

### Requirement: Ctrl 对 Node 的批量路径查询

Ctrl SHALL 按 `(machine_id, path)` 去重并限制批量/并发，调用 Node `POST /api/check_mount_usage`，请求 `{config:{mount_paths:[绝对路径]}}`，最多 100 条。Node 成功响应 SHALL 为 `{success:1,mounts:[{path,bytes,measured_at,pending,error}]}`，Ctrl SHALL 按机器与回显 `path` 严格匹配。成功项 SHALL 为 `bytes>=0`、`measured_at` 真实 UTC、`pending=false`、`error=null`；pending 项 SHALL 为 `bytes=null`、`measured_at=null`、`pending=true`、`error=null`；错误项 SHALL 为 `bytes=null`、`measured_at=null`、`pending=false`、稳定 `error`。`bytes` 为 du -sb 逻辑字节，非物理块。

#### Scenario: 同机同路径合并，跨机不混

- **WHEN** 多个 `deleted_id` 属于同一机器且路径相同，或不同机器使用相同路径
- **THEN** 前者只向 Node 发送一个路径并共享同一结果；后者按机器分别发送，结果不得跨机混用

#### Scenario: 三态与字段组合

- **WHEN** Node 返回成功、pending 或错误项
- **THEN** `bytes`、`measured_at`、`pending`、`error` 严格按上述三态组合，不混填

#### Scenario: 重复查询 pending

- **WHEN** Web 对仍有 pending 的 `deleted_ids` 再次调用
- **THEN** Ctrl 可重复执行同一只读查询并返回最新 pending/success/error，不持久化上次结果

### Requirement: Ctrl 查询错误映射与逐 id 回退

Ctrl SHALL 将 Node HTTP 404/405 映射 `node_unsupported`，超时 `node_timeout`，离线/连接失败/5xx `node_unavailable`，2xx 缺 `path` 或形状错误 `node_bad_response`；Node 的 per-path `invalid_path`、`not_found` 及 du 稳定错误 SHALL 原样返回。任一路径或机器失败 MUST 只影响对应 `deleted_id`，不得阻塞其他机器；错误项 `bytes`/`measured_at` MUST 为 null、`pending=false`，MUST NOT 填 0 或伪造成功。旧 Node 无统计接口时只影响统计展示，不影响原列表；恢复动作无法取得结论时 SHALL 以 `node_unsupported` 等可重试原因拒绝并保留快照，MUST NOT 报告为 `not_found`/`data_not_recoverable`，也 MUST NOT 继续异步创建；手动清理动作同样以对应 `node_*` 原因拒绝并保留记录；自动/升级清理不触发该检查。du 稳定错误中，`not_found`、`permission_denied`、`invalid_path` 是路径门禁失败；`non_zero_exit`、`timeout`、`du_unavailable` 等表示路径已通过存在性检查，MUST NOT 据此阻断恢复或手动清理。该变更不改变冻结/长期/删除资格，不做全盘扫描/全局总计/自动冻结，不改 `clean_mount`。

#### Scenario: 旧 Node 无接口

- **WHEN** Node 对新查询返回 HTTP 404/405
- **THEN** 受影响的 `deleted_id` 返回 `node_unsupported`，不得把 404 当 0 或空成功

#### Scenario: 超时、离线与坏响应

- **WHEN** Node 超时、机器离线/连接失败，或 2xx 响应缺路径/形状错误
- **THEN** 分别返回 `node_timeout`、`node_unavailable`、`node_bad_response`，字段保持 null/false 组合

#### Scenario: 单机失败不阻塞其他机器

- **WHEN** 一台机器请求失败，而当前页还有另一台机器
- **THEN** 失败机器的 id 返回稳定错误，其他机器仍正常映射结果，列表不被阻塞

#### Scenario: 严格匹配失败

- **WHEN** Node 响应缺少请求的 path、path 重复/歧义，或 path 与机器映射不一致
- **THEN** 对应 `deleted_id` 返回 `node_bad_response`，不借用其他机器或其他路径的 bytes

#### Scenario: 统计展示与动作 guard 分离

- **WHEN** 旧 Node 不支持路径查询，统计展示返回 `node_unsupported`，随后用户发起恢复或手动清理
- **THEN** 统计项仍按 `node_unsupported` 展示；恢复以 `node_unsupported` 可重试原因拒绝并保留快照，不把该错误当作 `not_found`，也不继续异步创建；手动清理以 `node_unsupported` 拒绝并保留快照/清理记录；自动/升级清理不触发该检查

#### Scenario: du 类错误不阻断动作

- **WHEN** Node 对路径返回 `non_zero_exit`、du `timeout`、`du_unavailable` 等测量类错误，但路径已通过存在性门禁
- **THEN** 统计展示保留该测量错误；恢复与手动清理的动作前检查按“路径存在”继续，MUST NOT 因测量失败拒绝动作

### Requirement: 已删除容器列表返回原容器有效态

Ctrl SHALL 在 `POST /api/containers/list_deleted_containers` 的每条记录中返回可空布尔字段 `original_container_is_valid`，并在读取时按 `original_container_id`（回落快照中的 `container_id`）从既有 `containers.is_valid` 动态派生：原容器行存在且 `is_valid=true` 时为 `true`，存在且为 `false` 时为 `false`，原容器行不存在时为 `null`。MUST NOT 新增数据库列/表/JSON 迁移，MUST NOT 用 `mount_cleaned`/`data_recoverable` 替代，列表读取 MUST NOT 修改任何数据库行。

#### Scenario: 原容器仍有效

- **WHEN** 已删除记录关联的原容器行存在且 `is_valid=true`
- **THEN** 列表记录的 `original_container_is_valid` 为 `true`

#### Scenario: 原容器已软删

- **WHEN** 已删除记录关联的原容器行存在且 `is_valid=false`
- **THEN** 列表记录的 `original_container_is_valid` 为 `false`，不把软删行误报为缺失

#### Scenario: 原容器行缺失

- **WHEN** 已删除记录找不到对应的原容器行
- **THEN** 列表记录的 `original_container_is_valid` 为 `null`，不得填 `false`

#### Scenario: 动态派生且只读

- **WHEN** 读取已删除容器列表
- **THEN** `original_container_is_valid` 只从既有 `containers.is_valid` 读取并投影到响应；不新增数据库列/表/JSON 迁移，不写容器行、删除快照或清理记录

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

## Data model appendix

### deleted_container_restore_snapshot 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 11 |
| `original_container_id` | `db.Column(db.Integer, nullable=False, index=True)` | 12 |
| `container_name` | `db.Column(db.String(120), nullable=False)` | 13 |
| `machine_id` | `db.Column(db.Integer, nullable=True, index=True)` | 14 |
| `mount_cleanup_id` | `db.Column(db.Integer, nullable=True, index=True)` | 15 |
| `removed_trigger` | `db.Column(db.String(64), nullable=False, default='api')` | 16 |
| `snapshot` | `db.Column(db.JSON, nullable=False)` | 17 |
| `removed_at` | `db.Column(db.DateTime, nullable=False, default=dt.datetime.utcnow, index=True)` | 18 |
| `mount_cleaned` | `db.Column(db.Boolean, nullable=False, default=False, server_default=db.text('0'), index=True)` | 19 |
| `deferral_seconds` | `db.Column(db.Integer, nullable=True, default=0, server_default=db.text('0'))` | 23 |

### 表级约束

表级约束：
- `(db.Index('idx_deleted_container_removed', 'removed_at'),)`

## Source references

- [models/deleted_container_restore_snapshot.py](../../../models/deleted_container_restore_snapshot.py)：DeletedContainerRestoreSnapshot，第 8 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[test/container/test_restore_long_term_capacity.py](../../../test/container/test_restore_long_term_capacity.py)；运行结果以当前隔离安全套件为准。
