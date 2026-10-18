# Design

## Context

动机见 [proposal.md](proposal.md)。当前接收链路的事实：

- `services/container_module/node_comms_modules/snapshots.py` 的 `_apply_disk_usage_entry` 先取 `total_bytes`、`overlay_rw_bytes`、`bind_mount_path`、`bind_mount_bytes`；`total_bytes is None`、overlay 不完整或 bind 路径存在但 bind 字节为空时直接 `return False`，路径修正与测量被绑在同一条件里。成功时该函数写 `disk_*_bytes`、`bind_mount_path`，并以 `datetime.datetime.utcnow()` 写 `disk_checked_at`（第 160-180 行）。
- `repositories/containers_repo.py` 的 `update_container` 把 `disk_*_bytes`、`disk_checked_at`、`bind_mount_path` 列入 allowed（第 228-232 行），但 `nullable_clear_fields`（第 237-246 行）不含这些字段；传入 `None` 会被 `continue` 跳过，所以 `no_bind` 要清空路径、路径变化要清空旧测量，现有通用 None 过滤都做不到。
- `api/container_api.py` 的 `_refresh_disk_async`（第 136-165 行）调用 `get_container_disk_usage`；后者在 `services/container_tasks.py` 第 419-427 行已改为只读 DB、不联系 Node。随后 `_refresh_disk_async` 用 `int(cd.get(...) or 0)` 把缺失值补成 0，并写 `disk_checked_at=datetime.utcnow()`。这不是一次真实测量，却会刷新测量时间。
- `disk_checked_at` 只有两个生产写点：上述 `_refresh_disk_async` 与 `snapshots.py` 第 178 行；生产代码没有读点（本变更仅在评估侧新增年龄读点）。因此把它从“接收时间”改为“最后被接受的测量时间”不需要迁移，也没有下游语义依赖。
- 调度 `schedulers/container_disk_check_task.py` 的 `_usage_from_db`（第 54-83 行）只检查 `disk_total_bytes`、`disk_overlay_rw_bytes`、`bind_mount_path`/`disk_bind_mount_bytes` 的完整性；不读 `disk_checked_at`，也没有测量年龄判断。
- Node 磁盘采样在 `docker_operates/disk_usage_cache.py`：bind 缓存 TTL 900 秒（`BIND_CACHE_TTL_SEC`）、du 超时 600 秒（`BIND_DU_TIMEOUT_SEC`）、滚动 sweep TTL 900 秒（`DISK_SWEEP_TTL_SEC`）。`collect_container` 按 Docker `Mounts.Source` 调 `get_bind`，并在没有 bind Source 时用 `rw + (bm or 0)` 发布 overlay-only 总量（第 168-189 行）；`get_bind` 的缓存键是路径（第 253-326 行）。这些是 Node 内部定位与测量的既有事实，Ctrl 只接收结果。

## Goals / Non-Goals

**Goals:** 让 Ctrl 持久化 Node 校正后的业务路径；在路径变化时清掉旧路径测量；用既有 `disk_checked_at` 保存真实测量时间；失败/缺组成不写 0；评估只使用当前可信测量；不新增列、不迁移、不改变业务资格。

**Non-Goals:** 不在 Ctrl 比较 dev/inode/PID；不新增状态/观测/接收时间列；不把 `mount_path_status=resolved` 当业务门禁；不把路径修正当删除/清理授权；不建立 Q70 跨进程操作代际；不重写冻结、恢复、长期或 Q72 政策；不新增 review/invalid；不改 Node guard-runtime 的对象代际/动作票/ready_identity；不修改 Node 内部路径定位。

## Decisions

### 1. 逐列结论：只用既有列

| 列 | 结论 | 可核验理由 |
| --- | --- | --- |
| `bind_mount_path` | 保留（既有） | `models/containers.py` 第 104 行；`containers_repo.update_container` allowed 第 232 行；删除/清理/恢复均读它（`services/container_module/deletion.py` 第 78 行、`mount_cleanup.py` 第 71/152 行、`restore.py` 第 211-213 行）。本变更只改写入语义，不新增列。 |
| `disk_overlay_rw_bytes` / `disk_bind_mount_bytes` / `disk_total_bytes` | 保留（既有） | 模型第 97-99 行；接收与调度用它判断组成完整性；没有其他字段能表达“哪部分字节已测到”。 |
| `disk_checked_at` | 保留（既有），语义改为“最后被接受的测量时间” | 模型第 100 行；只有 `snapshots.py` 第 178 行与 `api/container_api.py` 第 161 行两个生产写点；生产代码无读点（本变更仅在评估侧新增年龄读点）。把真实 `measured_at` 写入该列即可，重复缓存帧写同一个值不会刷新；旧 Node 缺 `measured_at` 时写接收时间，保持既有兼容行为。不需要新增 `disk_measured_at`。 |
| `disk_measurement_status` | **删除，不新增** | 现有字节与 `disk_checked_at` 表达最后成功测量及其年龄，过期直接计算。最新尝试的失败/测量中只在帧内和日志诊断，不要求持久化为业务状态。保留旧成功值时，数据库不能反推最新尝试是否失败，不能宣称所有观测状态都可从现有列派生；本次修补也未提出这种持久化需求。 |
| `disk_measured_at` | **删除，不新增** | 同上，`disk_checked_at` 可承载真实测量时间；该列没有必须独立存在的业务状态差异。新增它只会让同一事实有两个列。 |
| `disk_received_at` | **删除，不新增** | 接收时间本身不参与业务判断；旧 Node 缺 `measured_at` 的兼容值写入既有 `disk_checked_at`，不需要独立列。HTTP 手动刷新已不联系 Node，WSS 消费是串行队列；其余接收时间只用于日志/排障。没有现有字段无法表达的业务状态。 |
| `disk_observation` | **删除，不新增** | 采样序号、测量路径、Source、路径诊断都是观测/诊断信息，不是业务状态。落库会形成“诊断即状态”的第二来源；换名、拆列或迁入其他 JSON/日志同样禁止。日志只用于排障，不能被回读为业务状态。 |
| `disk_identity_status` / `disk_identity_checked_at` / `disk_identity` / dev-inode-PID 列 | **删除，不新增** | Node 内部对象事实只用于定位真实宿主目录；Ctrl 只用业务路径，身份列不能表达新的业务状态，且会引入第二身份与越权路径。既有删除/清理仍按路径和权限，不新增对象身份门禁。 |

**结论：本变更不新增任何列，不新增迁移。** `disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation` 四列全部删除；路径校正只使用既有 `bind_mount_path`，测量时间只使用既有 `disk_checked_at`。

### 2. 业务路径与 no_bind

与本变更路径/测量时间相关的 Node 线路字段只有三个：

| 字段 | 语义 |
| --- | --- |
| `bind_mount_path` | 业务路径（用户通称 `mount_path`）；Node 校正后回填；`unresolved`/`not_running` 保留已有/最后确认路径；`no_bind` 为 null |
| `mount_path_status` | `resolved / unresolved / not_running / no_bind`；只用于让 Ctrl 区分“更新/保留/清空”，缺省按 `unresolved` |
| `measured_at` | 本次合计样本的真实测量时间（overlay/bind 组成中较早者）；UTC ISO 8601；旧 Node 可缺省 |

Ctrl 只消费 `bind_mount_path` 作为业务路径；`mount_path_status` 是控制位，不落库、不返回、不参与资格判断。`resolved` 不是测量有效性的前置：Node 返回 `resolved` 但 du 失败时，`total_bytes` 为空，Ctrl 不得因路径状态发布数字；Node 返回 `unresolved` 但已有路径且同路径测量成功时，Ctrl 仍可按测量事实接收。

两个线路字段的必要性：`mount_path_status` 是唯一能区分“null = 明确 no_bind 应清空”与“null = unresolved/not_running 应保留”的控制信号；`measured_at` 是唯一能区分新测量与 5 秒缓存心跳的真实时间事实。二者都只在线路上，不落库、不新增列。

路径写入规则（只作用于当前认证机器上的活跃容器，接收入口已按机器名映射）：

1. 新协议帧（带 `mount_path_status`）且 `resolved`、`bind_mount_path` 非空：若与当前值不同，先更新 `bind_mount_path` 并清空旧路径相关测量；相同则不动路径。
2. `no_bind`：清空 `bind_mount_path`，并使用既有显式清除清空 `disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_total_bytes`、`disk_checked_at`；若同帧 overlay 完整且有有效 `measured_at`，再按 overlay-only 写入新测量。
3. `unresolved`/`not_running`/路径为空/字段缺失：保留当前路径，不清空、不改写；测量仅在帧内路径与当前路径一致且组成完整时接收。
4. 旧 Node 帧（无 `mount_path_status`）：不得改写或清空已有 `bind_mount_path`；当前路径为 None 且帧内路径非空时，可按旧协议建立该路径（这不是 Node 校正，只用于兼容旧 Node 新建容器），并按接收时间语义接收测量。当前路径非空时，只有帧内路径一致才接收其字节；两者皆空时旧协议无法证明 no_bind，不得按 overlay-only 接收。新 Node 已确认 no_bind 的容器，进程内标记阻止旧帧重新建立路径；该标记不持久化，重启后无法区分“从未有路径”与“明确清空”，写入 Risks。
5. `resolved` 但路径为空按第 3 条保留处理，不猜测、不清空。

不按 inode 批量改写历史恢复快照、旧清理记录或其他机器记录；路径修正只影响当前活跃容器，后续新记录读取新路径。路径修正不是删除/清理授权。

### 3. 接收顺序与失败语义

WSS 快照是唯一正式测量入口；HTTP 手动刷新不得再写磁盘事实。统一顺序：

1. 校验机器/容器归属与当前链路；`apply_disk_usage_snapshot` 的 updated/skipped 返回值和日志是当次通信结果，不落成状态列。
   真实 `measured_at` 早于现有 `disk_checked_at` 的帧不回写测量；同时间但路径冲突的帧不改路径。先拒绝已知旧帧再处理路径，不新增排序列。无有效测量时间的独立路径纠正只依赖当前链路顺序，不宣称跨进程旧帧隔离。
2. **先路径，后测量**：按第 2 节更新/保留/清空 `bind_mount_path`；路径发生变化时，用既有更新链路显式清空 `disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_total_bytes`、`disk_checked_at`。显式清空必须是专用清除参数/哨兵，不能把普通 `None` 一律当清空，以免其他 `update_container` 调用误清路径或测量。
3. 测量完整性：`total_bytes` 非空；overlay 非空；当前路径非空时 bind 字节非空；当前路径为空时只有 `mount_path_status=no_bind` 才允许 overlay-only。缺任一条件即视为无当前测量。
4. 时间：`measured_at` 存在时必须可解析、且不在未来超过允许时钟偏差；解析失败或超偏差按无效测量处理（不刷新字节/时间，路径修正仍可落库）。`measured_at` 缺省（旧 Node）时写 `datetime.utcnow()`，保持既有接收时间语义。重复缓存帧携带同一个 `measured_at`，写入同值即不变化，不刷新测量时间。
5. 通过后写 `disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_total_bytes` 和 `disk_checked_at`：新 Node 用真实 `measured_at`，缺省旧 Node 用接收时间；失败/缺组成/路径不一致不写 0、不刷新 `disk_checked_at`。日志记录 machine_id、容器名、拒绝原因和帧内关键值，供排障；日志不是业务状态库，不被回读。
   当前失败帧不提供可用样本；同路径最后成功值仍按原有效年龄判断，过期后跳过处置。路径改变必须清空旧测量。这不等于持久化最新尝试的失败状态。

HTTP 手动刷新：`_refresh_disk_async` 当前只是把 DB 现值补零后重写，必须删除该回写（或改为纯读），不得写 `disk_checked_at=utcnow()`，也不得把缺失值补成 0。若未来恢复“主动查询 Node”的 HTTP 入口，必须复用同一路径/测量接收函数，不得另起一套规则。

### 4. `disk_checked_at` 与评估年龄

`disk_checked_at` 在新 Node 下是真实测量时间，在旧 Node 下是接收时间；两者都表示“Ctrl 最后一次接受该容器磁盘测量的时间”。评估侧用同一列判断年龄：

- `disk_checked_at` 为空，或 `now - disk_checked_at` 超过允许最大年龄：无当前可信测量，跳过自动处置。
- 允许最大年龄初值 3600 秒，且 MUST NOT 小于 Node 既有 `BIND_CACHE_TTL_SEC=900` 与 `BIND_DU_TIMEOUT_SEC=600` 之和（1500 秒）；该阈值是评估策略，不是数据列，也不是版本门禁。
- 旧 Node 帧每批刷新接收时间，因此仍保持既有“在线即可评估”的行为；代价是旧 Node 的缓存心跳无法与真实新测量区分。这是为“不因缺 `measured_at` 让旧 Node 自动处置全停”付出的兼容成本，写入 Risks。

评估只读 DB，不回写 `disk_*`/`disk_checked_at`。`_usage_from_db` 现有的组成检查保留，并增加 `disk_checked_at` 年龄判断。路径 `unresolved` 不进入该判断；路径非空且字节完整、时间有效即可评估。

### 5. 调度、恢复、长期与 Q72 边界

磁盘调度的 pause、冻结状态 upsert/reset、超限邮件、升级删除和挂载清理只在当前可信测量存在时执行；无效/过期/路径不一致样本不写零、不重置冻结记录、不创建冻结锚点、不发超限邮件、不 pause、不升级删除、不清理挂载。

本变更不定义、不修改恢复/冻结/长期/删除/清理资格，也不重写 Q72：既有累计、机器不可用补偿与人工宽限不变，不新增 review/invalid 阻断。路径修正不是删除/清理授权；既有路径/权限检查和失败审计保留，不新增 inode 清理门禁，不宣称 Q70 跨进程原子。

### 6. 被否决的替代方案

- **新增四列后再论证必要性**：现有 `disk_*_bytes`、`disk_checked_at`、`bind_mount_path` 已能表达完整测量、失败、路径和测量时间；新增列没有现有字段不能表达的业务差异，且 `stale`/`unverified` 是派生状态。删除。
- **`disk_observation` 保存采样序号/测量路径/Source/诊断**：这是诊断不是业务状态；换名、拆列或迁入 JSON/日志同样是把诊断当状态库。删除。
- **`disk_measured_at` 与 `disk_checked_at` 并存**：同一事实两个列；`disk_checked_at` 无生产读点，可直接承载真实测量时间。
- **`disk_measurement_status` 作为门禁**：状态会随时间过期，且把“路径诊断失败”误写成“测量失败”的风险更高；改用字节完整性 + 路径一致 + 时间年龄。
- **`mount_path_status=resolved` 作为测量/业务门禁**：Node 已校正的路径才是业务依据；`unresolved` 下同路径成功测量仍可信。
- **失败时写 0 或保留旧值并刷新时间**：会把失败伪装成新测量；应保留最后可信值和旧 `disk_checked_at`，由年龄判断暴露过期。
- **路径变化后保留旧字节并贴新路径**：旧路径字节不是新路径的测量；应显式清空旧测量，等新路径完整样本。
- **把收到时间落库用于排序**：WSS 串行消费、重连丢弃旧队列，已有进程内顺序边界；接收时间只进日志。

## Risks / Trade-offs

- [旧 Node 无 `measured_at`] → 路径匹配或当前为空而旧帧建立路径时写接收时间，保持既有自动处置；代价是缓存心跳会被当成新测量。不覆盖已校正路径；不新增版本门禁。
- [旧 Node 无 bind 且无路径] → 旧协议无法证明 no_bind，不接收其 overlay-only 新测量；最后值在 `disk_checked_at` 过期后不再驱动动作，不误当 no_bind。仅影响无匹配路径的旧容器，不是全局停处置。
- [no_bind 后旧 Node 重建路径] → 同进程内用 no_bind 标记阻止旧帧重建；Ctrl 重启后标记丢失，旧帧可能重新建立路径。缺少既有列可持久化区分“从未有路径”与“明确清空”，本变更为不新增列接受该回滚/重启边界。
- [旧 Node 无法表达 no_bind] → 旧帧不会清空路径；路径保持最后已知，路径不一致或两者皆空时其测量不被接受。确认 no_bind 需要新 Node；这是旧协议能力边界，不新增列补救。
- [路径已校正后回滚旧 Node] → 旧帧的 `bind_mount_path` 与当前值不一致时拒绝其测量、且不改写路径；相关容器在 `disk_checked_at` 过期后不再自动处置，直到新 Node 恢复测量。这是“旧路径数据不贴新路径”的必然代价，写入回滚说明。
- [路径变化与测量同帧] → 先落路径并清空旧测量，再按同帧完整样本回填；旧路径字节不会被贴到新路径。
- [`disk_checked_at` 命名仍像“接收时间”] → 不新增列/不迁移；在模型注释、接收函数和设计说明中明确它是“最后被接受的测量时间”，旧 Node 为接收时间兼容值。
- [最大年龄阈值是策略值] → 初值 3600 秒，且不低于 Node 缓存 TTL 与 du 超时之和；若 Node 滚动 sweep 延迟更大，只会让评估更保守，不影响路径修正。
- [手动刷新历史行为] → 删除回写后，手动刷新不再改变磁盘事实；这是修正“补零/假装新测量”，不是功能回退。
- [路径修正与动作之间仍有竞态] → 本变更不宣称 Q70 跨进程原子；删除/清理仍按路径与既有权限，不新增对象身份门禁。

## Migration Plan

1. 无数据库迁移、无模型列变更。先部署 Ctrl 接收修正（路径先落、显式清空、`measured_at` 写 `disk_checked_at`、失败不写 0），再逐机部署 Node 路径/`measured_at` 协议。
2. 旧 Node 帧继续按路径一致 + 接收时间兼容；路径不一致的旧帧不覆盖已校正路径。旧行无需回填，`disk_checked_at` 既有值按“最后接受时间”沿用。
3. 隔离回放：resolved/unresolved/not_running/no_bind、路径 A→B 后旧样本、失败/缺组成、重复缓存帧、手动刷新、旧 Node 路径一致/不一致、`disk_checked_at` 过期。
4. 回滚 Ctrl 不涉及 schema；回滚 Node 后已校正路径的容器可能因旧帧路径不一致而停止自动处置（见 Risks），不回落旧路径数据。

## Source references

- [services/container_module/node_comms_modules/snapshots.py](../../../services/container_module/node_comms_modules/snapshots.py)：`_apply_disk_usage_entry` 第 160-180 行（早退与 `disk_checked_at=utcnow()`）。
- [repositories/containers_repo.py](../../../repositories/containers_repo.py)：`update_container` allowed 第 228-232 行、`nullable_clear_fields` 第 237-246 行。
- [api/container_api.py](../../../api/container_api.py)：`_refresh_disk_async` 第 136-165 行、调用点第 933-937 行。
- [services/container_tasks.py](../../../services/container_tasks.py)：`get_container_disk_usage` 第 419-427 行（只读 DB）。
- [schedulers/container_disk_check_task.py](../../../schedulers/container_disk_check_task.py)：`_usage_from_db` 第 54-83 行、`_evaluate_limits` 第 86-191 行。
- [models/containers.py](../../../models/containers.py)：磁盘与路径列第 94-104 行。
- Node 配套：`verify-bind-mount-identity`（名称保留）只回填业务路径并提供 `mount_path_status`/`measured_at`；Node 采样事实见 `docker_operates/disk_usage_cache.py` 第 24-27、134-208、253-326 行。本变更不修改 Node 仓库。
