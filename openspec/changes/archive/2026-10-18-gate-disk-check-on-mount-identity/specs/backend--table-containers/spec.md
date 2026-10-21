# Spec Delta

## MODIFIED Requirements

### Requirement: containers 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Container`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。磁盘事实 SHALL 仅使用既有 `disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_total_bytes`、`disk_checked_at` 和 `bind_mount_path` 表达；本变更 MUST NOT 新增 `disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation` 或 `disk_identity_*` 列，也 MUST NOT 以 JSON、日志或其他表替代磁盘业务状态。`bind_mount_path` 是唯一业务路径（用户通称 `mount_path`）。`disk_checked_at` 表示最后被接受的磁盘测量时间：Node 提供真实 `measured_at` 时写该值；旧 Node 未提供时，既有 `disk_checked_at` 保存接收时间作为兼容值。除该兼容值外，收到时间、拒绝原因和路径诊断只用于日志/进程内，不新增表列或业务状态存储。字段定义见主 spec 数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

#### Scenario: 不新增观测列

- **WHEN** 实现本变更
- **THEN** 不为测量状态、测量时间、接收时间或观测 JSON 新增列；路径修正只使用既有 `bind_mount_path`，测量时间只使用既有 `disk_checked_at`，且不新增迁移

## ADDED Requirements

### Requirement: Node 路径修正与业务路径

Ctrl SHALL 只消费 Node 校正后的 `bind_mount_path` 作为业务路径；dev/inode/PID MUST NOT 进入 Ctrl 持久化、比较或业务门禁。Ctrl SHALL 仅对当前认证机器上的活跃容器应用修正：`resolved` 且路径非空时更新；`no_bind` 时清空并允许同帧 overlay-only；`unresolved`/`not_running`/路径空/字段缺失时保留已有或最后确认路径，不清空、不猜测、不写 `/proc`。`mount_path_status` 只用于更新/保留/清空，不是测量或业务门禁。不带 `mount_path_status` 的旧 Node 帧 MUST NOT 改写或清空已有路径；当前路径为空且帧内路径非空时可建立该路径并按接收时间接收测量（新 Node 已明确 no_bind 的容器除外），这是旧协议兼容而非 Node 校正。路径修正 MUST NOT 按 inode 批量改写历史恢复快照、旧清理记录或其他机器记录。

#### Scenario: resolved 路径修正

- **WHEN** 当前认证机器上的活跃容器本次路径核对为 resolved，Node 返回校正后的 `bind_mount_path`
- **THEN** Ctrl 将该业务路径持久化到当前容器；不保存、不比较 dev/inode/PID，也不因该状态单独授权任何业务动作

#### Scenario: 原有 bind 路径转为明确 no_bind

- **WHEN** 当前活跃容器原有 `bind_mount_path`，随后成功 Docker 观测明确 no_bind，Node 返回 `bind_mount_path=null`、`mount_path_status=no_bind`
- **THEN** Ctrl 同步清空 `containers.bind_mount_path`；overlay 组成完整且测量时间有效时允许按 overlay-only 写入新测量；旧 bind 字节/旧路径样本不进入新测量

#### Scenario: unresolved 只保留路径不清空

- **WHEN** 路径核对为 unresolved，Node 保留已有/最后确认路径，且该路径测量成功、组成完整
- **THEN** Ctrl 保留 `bind_mount_path`，按测量事实判断是否接收；不得因 `mount_path_status=unresolved` 阻断同路径有效测量，也不得清空或把诊断失败写成测量失败

#### Scenario: 旧 Node 不改写已校正路径

- **WHEN** 当前业务路径已由新 Node 校正为 B，随后收到不带 `mount_path_status` 的旧 Node 帧，其 `bind_mount_path` 为 A
- **THEN** Ctrl 保留 B，不用 A 覆盖路径，也不把 A 的字节贴到 B；该路径不一致帧的测量被拒绝，旧帧的兼容接收条件仍按本规格其他场景执行

#### Scenario: 旧 Node 首次建立路径

- **WHEN** 当前 `bind_mount_path` 为空，旧 Node 帧带来非空路径 A 和完整测量
- **THEN** Ctrl 可建立 A 并按接收时间语义接收测量，用于兼容旧 Node 新建容器；这是旧协议兼容而非 Node 校正，后续新 Node 的 `resolved` 修正仍可覆盖，旧帧不得再改写 A

#### Scenario: no_bind 后旧 Node 不得重建路径

- **WHEN** 新 Node 已明确 no_bind 清空路径，随后收到旧 Node 帧带非空路径 A
- **THEN** 进程内 no_bind 保护拒绝重建 A，保留空路径并拒绝该帧测量；不得因此新增持久化列

#### Scenario: 路径修正不批量改历史

- **WHEN** 某容器路径从旧 Source 修正为新业务路径
- **THEN** 只更新该活跃容器；既有恢复快照、旧清理记录和其他机器记录保持各自路径，不按 inode 追溯改写

### Requirement: 磁盘测量接收与路径一致性

Ctrl SHALL 在更新有效字节和测量时间前同时确认：样本来自当前认证机器/当前活跃容器；`total_bytes` 非空、overlay 非空、当前路径非空时 bind 字节非空，当前路径为空时只有 `mount_path_status=no_bind` 才允许 overlay-only；帧内业务路径与当前业务路径一致（路径修正帧先落路径，再判断测量）；`measured_at` 存在时格式有效且不在未来超过允许时钟偏差；缺少 `measured_at` 的旧 Node 帧只在当前路径为空且帧内路径非空（兼容建立）或当前路径非空且帧内路径一致时按接收时间兼容。失败、缺组成、路径不一致或时间无效 MUST NOT 刷新 `disk_checked_at`、MUST NOT 写入 0 或把旧值标成新测量。

#### Scenario: 错误样本不伪造零

- **WHEN** `total_bytes` 为空、overlay 缺失，或 bind 路径存在但 bind 字节为空
- **THEN** 不把该样本的字节或接收时间写成有效测量，不写 0，不把旧值标成当前测量；若同帧路径发生变化，仍按路径规则先落路径并清空旧测量；日志记录拒绝原因

#### Scenario: 重复缓存帧不刷新测量时间

- **WHEN** Node 在一个测量周期内多次推送同一 `measured_at` 的缓存结果
- **THEN** `disk_checked_at` 保持该真实测量时间；新的发送/接收时间不得把它推进，重复帧也不得改写路径

#### Scenario: 已知旧测量不回退

- **WHEN** 帧内真实 `measured_at` 早于现有 `disk_checked_at`，或时间相同但路径冲突
- **THEN** 不回写旧测量，不以冲突帧改路径；先拒绝旧帧再执行路径更新，不新增排序列，也不宣称无时间的路径纠正具备跨进程隔离

#### Scenario: 明确 no_bind 的 overlay 测量

- **WHEN** Node 明确返回 `mount_path_status=no_bind`、`bind_mount_path=null`，overlay 组成完整且 `measured_at` 有效
- **THEN** Ctrl 清空当前 `bind_mount_path` 后按 overlay 总量写入有效测量；不得把探测失败、路径不可读或字段缺失推断为 no_bind，也不得混入旧 bind 字节

#### Scenario: 无效 measured_at 只拒绝测量

- **WHEN** 新 Node 帧的 `measured_at` 无法解析或超出现在允许时钟偏差
- **THEN** 不更新字节和 `disk_checked_at`，但同帧的合法路径修正仍可落库并按路径规则清空旧测量；不得把该帧解释成旧 Node，也不得用接收时间替代

### Requirement: 路径变化清空旧测量

路径变化或明确 no_bind 清空时，接收链路 SHALL 使用既有更新能力显式清空旧路径相关 `disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_total_bytes` 和 `disk_checked_at`，再按新路径的完整样本回填；MUST NOT 把旧路径字节/总量贴到新路径。显式清空 MUST 使用专用清除语义，MUST NOT 把普通 `None` 一律当清空，且只作用于当前活跃容器。

#### Scenario: 路径改变后旧样本晚到

- **WHEN** 当前业务路径已修正为新路径 B，随后收到 `bind_mount_path=A` 且总量对应旧路径的样本
- **THEN** 拒绝该样本更新字节和 `disk_checked_at`，保留 B；不对 A 的数字做新路径标注，也不清空 B

#### Scenario: 路径变化先清空再回填

- **WHEN** 当前容器路径从 A 修正为 B，或明确转为 no_bind
- **THEN** 先用既有更新链路显式清空旧路径相关 `disk_*` 与 `disk_checked_at`；同帧只有 B（或 overlay-only）的完整新样本才可回填，旧 A 的字节不进入新路径

### Requirement: 评估只使用当前可信测量

磁盘调度和动作前检查 SHALL 使用与接收相同的完整性、路径一致性条件，并要求 `disk_checked_at` 非空且未超过允许最大年龄（初值 3600 秒，且 MUST NOT 小于 Node 既有缓存 TTL 900 秒与 du 超时 600 秒之和 1500 秒）。不满足时 MUST NOT pause、重置冻结、发超限邮件、升级删除或清理挂载；仍保留既有冻结记录、机器不可用补偿与人工宽限。

`mount_path_status=unresolved` 本身 MUST NOT 阻断同路径有效测量；`mount_path_status=resolved` 本身 MUST NOT 使失败测量有效。本变更 MUST NOT 改变恢复、冻结、长期、删除或清理资格，MUST NOT 重写 Q72 累计，MUST NOT 新增 review/invalid 保护，也 MUST NOT 把路径修正当删除/清理授权。

#### Scenario: 测量过期不动作

- **WHEN** `disk_total_bytes` 仍存在，但 `now - disk_checked_at` 超过允许最大年龄
- **THEN** 调度跳过 pause、冻结重置、邮件、升级删除和挂载清理；保留最后已知值作历史，不写 0，不重开或顺延冻结周期

#### Scenario: unresolved 路径上的有效测量

- **WHEN** `mount_path_status=unresolved`，但已有业务路径、该路径测量成功、组成完整且 `disk_checked_at` 在允许年龄内
- **THEN** 样本可用于磁盘评估；日志保留 unresolved 诊断但不阻断，`resolved` 不是额外前置

#### Scenario: resolved 但测量失败

- **WHEN** `mount_path_status=resolved`，但 du 失败、组成缺失或 `measured_at` 无效
- **THEN** 不因路径已确认而接受该失败帧的数字，不刷新既有成功时间；同路径最后成功样本仍按原有效年龄判断，路径变化清空或旧样本过期后按无当前可信测量跳过动作，不持久化最新尝试状态

#### Scenario: 路径修正不等于删除授权

- **WHEN** Node 修正了 `bind_mount_path`
- **THEN** 后续删除/清理仍走既有权限、路径和业务检查；不得仅凭路径修正或目录对象编号调用删除，也不宣称 Q70 跨进程原子
