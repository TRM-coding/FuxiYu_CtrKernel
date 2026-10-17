# Proposal

## Why

Ctrl 目前只要收到完整字节数就更新磁盘用量与 `disk_checked_at`，但 `bind_mount_path` 可能是旧的 Docker Source，调度和清理随后会使用错误路径。Node 在内部用 dev/inode 等对象事实定位真实宿主目录后，应把**业务路径**校正并返回；Ctrl 不应保存或比较目录身份。前版把 `match/mismatch/unknown`、proc 可读性等作为业务门禁，混淆了“Node 内部定位路径”和“Ctrl 使用路径测量”两个阶段。

## What Changes

- 采用精简路径契约：Node 在无法唯一确认时不猜目录、不返回 `/proc` 临时路径；`unresolved`/`not_running`/字段缺失/不可读时保留原有/最后已确认路径并标记诊断。**成功 Docker 明确 `no_bind` 是路径事实**：Node 返回 `bind_mount_path=null`、`measurement_mount_path=null` 的 overlay-only；Ctrl 必须在当前认证机器/活跃容器/有效排序下同步清空 `containers.bind_mount_path`，不得保留旧 bind 路径再以 no_bind 豁免同路径检查。未知诊断绝不能被当成 no_bind。
- `bind_mount_path` 继续是唯一业务路径；`configured_mount_path` 只是 Docker Source 诊断，`mount_path_status`（`resolved/unresolved/not_running/no_bind`，缺省 `unresolved`）和 `mount_path_observed_at` 只用于诊断。路径核对状态 MUST NOT 作为恢复、长期资格、冻结、删除或清理的业务门禁；`unresolved` 不阻断同路径有效测量，`no_bind` 清空后 overlay-only 有效。
- 删除旧 `bind_identity`/`measurement_identity` 跨端依赖和 Ctrl 的 `disk_identity_status/disk_identity_checked_at/disk_identity` 身份门禁。dev/inode/PID 只留在 Node 内部路径定位与调试，Ctrl 不比较、不落库、不据此授权。
- 测量保留 `disk_protocol_version=1`（尚未实现可收窄）、`collector_epoch/observation_seq`（仅采样会话排序）、`measurement_status`（`ok/measuring/stale/error/unverified`）、`measured_at`（合计真实测量时间）和 `measurement_mount_path`（测量使用的业务路径）；Ctrl 持久化 `disk_measurement_status/disk_measured_at/disk_received_at/disk_observation`。
- 测量有效性只检查：测量成功、组成完整、真实测量未过期、样本与当前业务路径同路径、响应排序未过期；不检查 `mount_path_status=resolved`，不检查 dev/inode。overlay-only 必须由 Docker 明确 `no_bind`；异常不得写成 0。
- WSS、HTTP 手动刷新及其他写入口共用同一路径修正、乱序拒绝和测量新鲜性规则；路径与样本不得错配。旧 Node 缺真实 `measured_at` 时标测量未验证，不能解释为“缺目录身份”。
- 保留 Q72：验证中断不新增冻结倒计时补偿，恢复可信高用量后按原累计有效天数继续；机器不可用补偿与人工宽限不变。路径修正不构成删除授权，也不新增 inode 清理门禁。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-containers`：持久化业务路径修正、测量状态/时间/观测和路径诊断，约束有效测量与自动处置；移除目录身份授权字段。

## Impact

涉及 `services/container_module/node_comms_modules/snapshots.py`、`node_comms.py`、`node_comms_modules/websocket.py`、`schedulers/container_disk_check_task.py`、磁盘查询/手动刷新、`models/containers.py`、`repositories/containers_repo.py`、`services/container_module/information.py`、迁移与隔离测试。Node 配套变更沿用 `verify-bind-mount-identity` 名称，但契约改为路径定位/回填与测量；不再传 dev/inode/PID 作为 Ctrl 业务身份。**BREAKING**：旧 Node 缺真实 `measured_at` 的样本视为测量未验证，暂停自动处置；路径 `unresolved` 本身不阻断业务。Node 校正业务路径后，删除/清理仍按路径与既有权限，不新增对象身份门禁；本变更不宣称 Q70 跨进程原子，不执行 SSH/生产操作，不修改正式 specs 或 archive。
