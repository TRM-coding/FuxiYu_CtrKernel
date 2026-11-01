# Proposal

## Why

Ctrl 目前只要收到完整字节数就更新磁盘用量与 `disk_checked_at`，但 `bind_mount_path` 可能仍是旧的 Docker Source，调度和清理随后会使用错误路径。更关键的是，`_apply_disk_usage_entry` 在 `total_bytes` 为空时整条跳过，连 Node 已校正的 `bind_mount_path` 也不会落库；手动刷新还会把缺失字节 `int(... or 0)` 成 0，并用接收时间刷新 `disk_checked_at`。

Node 可以在内部用 Docker `/root` bind Source、运行/暂停容器 `/proc/<pid>/root/root` 的实际目录对象 `(st_dev, st_ino)` 和 PID 定位真实宿主目录，只把校正后的业务路径回填 `bind_mount_path`。Ctrl 只消费该业务路径和测量事实，不保存、不比较目录对象，也不需要新的持久化观测列。

## What Changes

- `bind_mount_path` 继续是唯一业务路径（用户通称 `mount_path`）。Node 内部可用 dev/inode/PID 定位真实目录并回填；Ctrl MUST NOT 保存或比较这些对象事实，也不把 `mount_path_status=resolved` 当测量、恢复、冻结、长期、删除或清理的门禁。
- Node 明确 `no_bind` 时返回 `bind_mount_path=null`、`mount_path_status=no_bind`；Ctrl 同步清空当前认证机器/活跃容器的 `bind_mount_path`。`unresolved`/`not_running`/字段缺失/不可读时保留已有/最后确认路径，不清空、不猜目录、不写 `/proc` 临时路径。`mount_path_status` 只作清空/保留的控制信号，不落库。
- **不新增四列**：删除 `disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation` 的方案；也不新增 `disk_identity_status`、`disk_identity_checked_at`、`disk_identity` 或 dev/inode/PID 列。继续使用既有 `disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_total_bytes`、`disk_checked_at`、`bind_mount_path`。不得把诊断换名、拆列或迁入别的 JSON/日志充当业务状态库。
- `disk_checked_at` 语义改为“最后被接受的磁盘测量时间”：Node 提供真实 `measured_at` 时写该值，重复缓存帧不刷新；旧 Node 缺 `measured_at` 时沿用接收时间兼容语义，不因缺字段把旧 Node 自动处置全停。
- 路径变化或明确 no_bind 时，接收链路用既有更新能力显式清空旧路径相关 `disk_*` 与 `disk_checked_at`，再按新路径的完整样本回填；不得把旧路径字节/总量贴到新路径。失败、缺组成、路径不一致或时间无效不写 0、不刷新测量时间，只保留最后可信值和日志。
- 磁盘评估只使用完整、路径一致、测量时间可解析且未过期的当前测量；无当前测量时跳过 pause、冻结重置、超限邮件、升级删除和挂载清理。路径 `unresolved` 本身不阻断同路径有效测量；`resolved` 本身不能使失败测量有效。
- 手动刷新不得用 DB 现值补零、不得用接收时间冒充测量时间，也不得绕过同一接收规则。
- 不改变恢复、冻结、长期、删除、清理资格与 Q72 累计；不新增 review/invalid，不重写冻结流程。路径修正不是删除/清理授权，不宣称 Q70 跨进程原子。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-containers`：复用既有列持久化业务路径与真实测量时间，约束路径变化、失败样本和评估；不新增列。

## Impact

涉及 `services/container_module/node_comms_modules/snapshots.py`、`repositories/containers_repo.py`、`api/container_api.py`、`schedulers/container_disk_check_task.py` 的接收/评估逻辑与隔离测试。无模型或迁移变更；隔离测试覆盖接收/评估行为。Node 配套 `verify-bind-mount-identity` 只回填业务路径并提供 `mount_path_status`/`measured_at`；Ctrl 不新增列、不定义资格 DTO、不修改正式 specs 或 archive。

**兼容性**：旧 Node 帧保留既有接收时间语义；已有路径不改写，当前无路径时可按旧协议建立（新 Node 已确认 no_bind 后由进程内标记阻止重建）。路径已校正后回滚旧 Node 时，路径不一致的样本被拒绝，相关容器在样本过期后不再自动处置，直至新 Node 恢复测量。此边界写入 design 的残留风险，不作为新版本门禁。
