# Design

## Context

动机见 [proposal.md](proposal.md)。当前 `_apply_disk_usage_entry` 只检查字节是否齐全，完整即以接收时刻刷新 `disk_checked_at`；`bind_mount_path` 可能仍是旧 Docker Source。调度和清理只读数字/路径，不检查真实测量年龄或路径是否与样本一致。`api/container_api.py` 的手动刷新也会写 disk 字段，并把缺失字节 `int(... or 0)` 成零。

Node 可以在内部用 Docker/宿主进程/dev/inode 事实定位实际目录，并把结果收窄为**业务路径修正**；Ctrl 不获取也不比较这些对象编号。本设计把“Node 定位路径”和“Ctrl 校验测量”分阶段，路径核对状态只作诊断，不作为业务门禁。

## Goals / Non-Goals

**Goals:** 让 Ctrl 持久化 Node 确认真实路径后的业务路径；只在测量成功、完整、真实时间未过期、与当前业务路径一致且响应不乱序时认可样本；无法定位时不猜路径、不把缺失写成零；保留 Q72 累计与既有补偿/宽限。

**Non-Goals:** 不在 Ctrl 比较 dev/inode/PID，不用目录对象编号授权冻结、删除、清理、恢复或长期资格；不把 `/proc` 临时路径当业务路径；不新增清理前对象身份门禁；不建立 Q70 跨进程操作代际；不实现恢复或长期业务政策。

## Decisions

### 1. 业务路径与路径诊断

`bind_mount_path` 是唯一业务路径（用户通称 `mount_path`）。Node 在内部能唯一确定实际宿主目录时，返回校正后的 `bind_mount_path`；成功 Docker 明确 `no_bind` 是“当前没有 bind”的确定事实，Node 返回 `bind_mount_path=null`、`measurement_mount_path=null`、overlay-only。`unresolved`/`not_running`/字段缺失/不可读不是 no_bind：这些情况保留原有/最后已确认路径并标记诊断，无已有路径才是 null；不猜目录、不返回 `/proc/...` 临时路径。

Node `usage` version 1 的可选路径诊断字段：

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `configured_mount_path` | `str \| null` | Docker Source 诊断；不直接当业务路径 |
| `mount_path_status` | `resolved / unresolved / not_running / no_bind`，缺省 `unresolved` | 路径核对诊断，不是业务门禁 |
| `mount_path_observed_at` | UTC 字符串或 null | 本次路径核对时间 |

- `resolved` 只表示 Node 内部已唯一确认路径；Ctrl 不要求提供 dev/inode/PID，也不保存这些值。
- `unresolved`/`not_running`/字段缺失/不可读：只保留已有/最后确认路径，MUST NOT 清空，也不能当 no_bind；同一路径的成功测量不受该诊断阻断。
- 成功 Docker 明确 `no_bind`：Node 返回业务路径与 measurement_mount_path 均为 null；Ctrl 在当前认证机器/活跃容器/有效排序下同步清空 `containers.bind_mount_path`，不得保留旧路径再豁免同路径检查。清空后以 overlay-only 组成判断测量，旧 bind bytes/旧路径样本只作历史诊断，不得写入有效测量。
- 路径修正只持久化到当前认证机器上的活跃 `containers.bind_mount_path`。不按 inode/对象编号批量改写历史恢复快照、旧清理记录或其他机器记录；后续新记录读取新路径。
- 路径修正不是删除/清理授权。既有路径/权限检查与失败审计保留，不新增 inode 清理门禁。

### 2. Ctrl 持久化字段

在 `containers` 增加/使用以下字段，迁移需显式 ALTER 存量表：

| 字段 | 建议类型及语义 |
| --- | --- |
| `disk_measurement_status` | String(24)，默认 `unverified`；`ok/measuring/stale/error/unverified` |
| `disk_measured_at` | 可空 UTC DateTime；合计真实测量发生时间 |
| `disk_received_at` | 可空 UTC DateTime；Ctrl 接收该事实时间，只用于排序/排障 |
| `disk_observation` | 可空 JSON；`protocol_version/collector_epoch/observation_seq/measurement_mount_path/mount_path_status/configured_mount_path/mount_path_observed_at/reason` |

**不新增** `disk_identity_status`、`disk_identity_checked_at`、`disk_identity`，也不新增 dev/inode/PID/目录对象列。既有 `disk_*_bytes` 保留最近一次有效数值；`disk_checked_at` 只作兼容字段，MUST NOT 充当 `disk_measured_at` 或路径核对时间。

`disk_observation` 可保存路径修正证据（恢复后的业务路径、来源、状态、时间），但不保存 proc 路径为清理目标，也不作为业务授权。

### 3. 统一接收、路径修正与乱序规则

WSS、HTTP 手动刷新及其他写入口共用同一接收入口：

1. 校验当前机器链路/HTTP 响应是否为当前观测；退役连接、旧连接代际和旧 HTTP 响应不得回填。
2. 若本次提供 `bind_mount_path` 且为该机器活跃容器、`mount_path_status=resolved`，先把校正路径持久化到 `containers.bind_mount_path`；若成功 Docker 明确 `mount_path_status=no_bind`，先把 `bind_mount_path` 清空为 null（仅当前认证机器/活跃容器/有效排序）；`unresolved`/`not_running`/字段缺失/不可读时保留已有/最后确认路径，MUST NOT 清空或推断 no_bind，不猜、不写 `/proc`。
3. 路径更新后，bind 测量只有 `measurement_mount_path == 当前 bind_mount_path` 才可写入；明确 no_bind/overlay-only 时两边都为 null，按 overlay 组成判断，不要求 bind 路径相等；不得把旧路径样本改贴到新路径或清空后的 null。旧 bind bytes/旧路径样本只保留历史诊断，不进入有效测量。路径修正与测量同帧时先定路径，再判断样本；unresolved 但已有路径与样本一致时仍有效。
4. `collector_epoch/observation_seq` 只用于采样会话排序；同一 epoch 内拒绝较小 seq，等于当前 seq 只允许内容一致的心跳，不刷新测量时间；Node 重启/新 epoch 要求新的完整观测，不复用旧数字。
5. 形状损坏、协议缺失/不支持、真实测量时间缺失、组成不完整或测量状态非 `ok` 的样本必须落库状态/观测/接收时间，但不得刷新有效 bytes 或 `disk_measured_at`；不得把缺失值写成 0。
6. 新链路在收到首个完整新协议观测前，旧连接遗留数值只作历史展示，不驱动动作；磁盘样本排序不宣称 Q70 的跨进程操作授权。

手动刷新不得用当前接收时间冒充测量时间，也不得因为返回的是 HTTP 就绕过同一路径/乱序规则。

### 4. 测量有效谓词

样本有效必须同时满足：

- 协议已识别；当前按 version 1 处理（尚未实现时可收窄，但旧缺失协议按 unverified）；
- `measurement_status=ok`；
- `total_bytes` 已知；overlay 完整；有 bind 时 bind bytes 完整；overlay-only 必须由 Docker 明确 `no_bind`，缺失/异常不得推断为 no_bind；
- `measured_at` 存在、可解析、未超过测量最大年龄（初值 900 秒），且不在未来超过允许时钟偏差（初值 30 秒）；
- `measurement_mount_path` 与当前业务路径一致；成功 Docker 明确 `no_bind` 时当前 `bind_mount_path` 已清空、measurement_mount_path 也为 null，按 overlay-only 有效，不要求 bind 路径相等，但不得携带旧 bind bytes/旧路径样本；
- 样本来自当前连接/当前响应，未违反 collector_epoch/observation_seq 排序；
- 没有路径/样本错配或退役链路回填。

谓词 MUST NOT 检查 `mount_path_status=resolved`、dev/inode、PID、proc 可读性或 Docker 对象编号。路径核对失败只是诊断；同一路径的成功测量仍可使用。

### 5. 调度、恢复与长期入口的边界

磁盘调度的自动冻结、重置、通知、升级删除和挂载清理只在上述有效测量存在时执行；无效样本不写零、不重置冻结记录、不创建冻结锚点、不发超限邮件、不暂停、不删除。Q72 已决：采集中断不新增冻结顺延，恢复可信高用量后按原累计有效天数继续；机器不可用补偿和人工宽限不变。

本变更不定义恢复长期标记、长期启用/取消或清理目标政策。路径修正和测量有效性可供其他变更消费，但不能反过来用 inode 或 `mount_path_status` 授权这些业务。

### 6. 查询与可观测性

查询/详情/列表 SHALL 返回业务路径、测量状态、真实测量时间、接收时间、最后已知数值和路径诊断（configured/source、mount path status、observed_at）。历史数值必须标注为历史/不可处置，不能显示成当前正常样本；`unresolved` 与测量错误分开呈现，不能把诊断失败伪装成 `measurement_error`。日志/证据保留被拒原因和排序信息，不保存 proc 临时路径。

### 7. 被否决的替代方案

- **Ctrl 比较 dev/inode/Docker ID 决定测量或业务授权**：跨对象/跨阶段错用；Node 内部定位已足够，Ctrl 只用路径。
- **路径 `unresolved` 作为冻结/恢复/长期/清理门禁**：会把诊断失败扩大成业务拒绝，且同一业务路径的成功测量仍可信。
- **`configured_mount_path` 直接当业务路径**：Docker Source 可能是旧配置；只作诊断，业务路径由 Node 唯一确认。
- **缺失 `measured_at` 按当前接收时间补**：伪装新鲜，旧样本会驱动动作。
- **把目录对象编号写进 Ctrl 或用于删除清理**：引入第二身份与越权路径；Node 校正业务路径后，删除/清理仍只按路径与既有权限，不新增对象身份门禁。

## Risks / Trade-offs

- [Node 内部无法唯一定位路径] → unresolved/not_running/字段缺失/不可读只保留已有/最后确认路径，不清空；若该路径测量成功仍可用，若无路径则不能编造。诊断状态不阻断业务。
- [成功明确 no_bind] → 同步清空当前活跃容器的 bind_mount_path，measurement_mount_path 也为 null，按 overlay-only 判断；旧 bind bytes/旧路径样本只作历史诊断，旧 HTTP/旧链路不得把路径恢复。未明确 no_bind 不得清空。
- [路径修正与样本同帧] → 先落路径，再要求 `measurement_mount_path` 匹配；旧路径样本拒绝贴到新路径，避免错配。
- [旧 Node 缺 `measured_at`/协议] → 标 `unverified`，保留数字供展示但不驱动自动处置；这是测量版本限制，不是目录身份缺失。
- [路径修正回填历史] → 只更新当前认证机器活跃容器的 `bind_mount_path`，不批量改旧快照/清理记录；旧记录后续按各自路径处理。
- [新链路/手动刷新乱序] → 连接代际、epoch/seq、HTTP 响应比较共同拒绝旧结果；不宣称 Q70 全序。
- [样本有效到动作之间仍有竞态] → 本变更是采样有效性门禁，不构成删除路径原子身份保证；删除/清理仍按路径与既有权限，不宣称 Q70 跨进程原子。
- [Q72 恢复后立即升级] → 按用户已决累计口径执行，不用无效样本删除，也不新增 deferral。

## Migration Plan

1. 在隔离库验证新增字段/迁移可重复执行、旧行 `unverified`、`disk_identity*` 不新增/不回填、`disk_checked_at` 不冒充测量时间。
2. 先部署 Ctrl 接收路径修正和测量规则，再逐机部署 Node 路径/测量协议；旧 Node 样本显示测量未验证，自动处置暂停但不误删。
3. 回放 resolved/unresolved/not_running/no_bind、路径变更后旧样本、乱序、手动刷新、旧连接和 Q72 恢复；生产不使用真实目录删除/冻结演练。
4. 回滚 Node 时保留 Ctrl 字段，旧样本降级 unverified；回滚 Ctrl 会恢复旧数字驱动动作的风险，需先核对测量覆盖。

## Source references

- [services/container_module/node_comms_modules/snapshots.py](../../../services/container_module/node_comms_modules/snapshots.py)：`_apply_disk_usage_entry` 与状态快照。
- [services/container_module/node_comms.py](../../../services/container_module/node_comms.py)：磁盘/状态快照入口。
- [api/container_api.py](../../../api/container_api.py)：手动磁盘刷新与回写。
- [repositories/containers_repo.py](../../../repositories/containers_repo.py)：更新白名单/显式空值。
- [schedulers/container_disk_check_task.py](../../../schedulers/container_disk_check_task.py)：有效测量门禁与 Q72 累计。
- [services/container_module/information.py](../../../services/container_module/information.py)：路径/测量查询展示。
- Node 配套：`verify-bind-mount-identity`（名称保留）改为路径定位/回填与测量协议；本变更不修改 Node 仓库。
