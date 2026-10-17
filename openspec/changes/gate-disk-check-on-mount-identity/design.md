# Design

## Context

动机见 [proposal.md](proposal.md)。`_apply_disk_usage_entry` 遇到不完整样本直接跳过，完整样本则以接收时刻刷新 `disk_checked_at`。调度只读数字，不检查真实测量年龄。`repositories/containers_repo.py` 默认跳过多数 None 更新，不能通过推送 null 安全地废止旧正常值。`api/container_api.py` 的手动刷新也写 disk 字段，并把缺失值 `int(... or 0)` 成零，必须纳入相同规则。

Node 配套协议详见 [Node design](../../../../FuxiYu_NodeKernel/openspec/changes/verify-bind-mount-identity/design.md)。新增规格落在既有 `backend--table-containers`，遵守 Ctrl 按表组织能力的规范。

## Goals / Non-Goals

**Goals:** 保留可追溯的最后数字，让最新异常和证据过期真实影响磁盘调度；恢复可信测量后遵循用户已确定的累计删除规则。

**Non-Goals:** 不自动修复 daity 历史挂载业务记录，不在此补丁修改机器 512 GiB 限额，不以 inode 替代数据库资源身份，不自动按 inode 查找目录，不把磁盘样本验证当成清理路径的原子授权，不实现 Q71 的清理前身份验证或实际对象计量。

## Decisions

### 1. 当前验证事实与最后成功数字分开持久化

在 containers 增加下列字段；迁移需显式 ALTER 存量表及测试，不能只依赖 create_all。身份 JSON 保存无损十进制字符串。旧行默认为 unverified，不能以最近一次 disk_checked_at 回填真实测量时间。

| 字段 | 建议类型及语义 |
| --- | --- |
| `disk_identity_status` | String(24)，默认 `unknown`，最新挂载验证结果 |
| `disk_measurement_status` | String(24)，默认 `unverified`，最新测量资格 |
| `disk_identity` | 可空 JSON，版本、Docker ID、双方对象、进程、测量对象、原因、epoch/seq 等结构化证据 |
| `disk_identity_checked_at` | 可空 UTC DateTime，Node 身份观测完成时间 |
| `disk_measured_at` | 可空 UTC DateTime，最后成功有效测量真正发生的时间 |
| `disk_received_at` | 可空 UTC DateTime，Ctrl 本地收到磁盘事实的时间 |

下表左列逐字采用 Node design 的 version 1 线路名，Ctrl 不重命名线路字段；右列只是本地持久化位置，不改变线路契约。若 Node 后续改名字段，先改 Node 契约再同步 Ctrl，本补丁不自行造名。

| Node `usage` version 1 字段 | Ctrl 持久化位置 |
| --- | --- |
| `disk_protocol_version` | `disk_identity.protocol_version`；缺失或非 1 按未验证 |
| `docker_id` | `disk_identity.docker_id` |
| `collector_epoch` / `observation_seq` | `disk_identity.collector_epoch` / `.observation_seq` |
| `bind_identity.status` | `disk_identity_status`，并保留在 `disk_identity.bind_identity.status` |
| `bind_identity.source_path` | `disk_identity.bind_identity.source_path`；现有 `bind_mount_path` 语义不变，不写入 proc 路径 |
| `bind_identity.source` / `bind_identity.actual` | `disk_identity.bind_identity.source` / `.actual`，device 与 inode 存十进制字符串 |
| `bind_identity.process` | `disk_identity.bind_identity.process`，pid、start_ticks、boot_id 原样保存 |
| `bind_identity.mount_id` | `disk_identity.bind_identity.mount_id`，仅诊断，不作永久身份 |
| `bind_identity.checked_at` / `bind_identity.reason` | `disk_identity_checked_at` / `disk_identity.bind_identity.reason` |
| `measurement_status` | `disk_measurement_status` |
| `measured_at` | `disk_measured_at` |
| `measurement_identity` / `measurement_reason` | `disk_identity.measurement_identity` / `.measurement_reason` |
| `total_bytes` / `overlay_rw_bytes` / `bind_mount_bytes` | 既有 `disk_total_bytes` / `disk_overlay_rw_bytes` / `disk_bind_mount_bytes`，只在有效测量时更新 |
| `bind_mount_path` | 既有 `bind_mount_path`，语义不变 |

原有 disk_* bytes 保留最近一次可信数值，供查询历史展示。disk_checked_at 作为兼容字段只随成功有效的新测量更新为 measured_at；新增 received_at 专门表示接收时间。迁移后旧数值仍可看见，但在首个新协议有效测量前不具备处置资格。查询层同时返回当前资格、当前可信用量和最后正常数值/时间，避免把历史值展示成新测量。

### 2. 所有写入口共用接收规则

同一次事务先保存经过校验的最新状态、证据与接收时间，再按测量资格决定是否更新 bytes 和 measured_at。合法的错误样本也必须落库，不能因 total 为 null 就整帧跳过；形状损坏、版本缺失或版本不支持时保存 unverified 及原因，不放行已有正常状态。

仓储更新白名单和显式 nullable/clear 规则必须同时覆盖新增状态、证据、原因和时间字段；错误样本的 `total_bytes=None` 不能触发通用 None 过滤而丢掉整帧状态。bytes 与 measured_at 只在有效测量时更新，不能用空值清空历史展示值，也不能把缺失写成 0。

WSS 按已认证机器链路处理；连接建立时生成连接代际，apply 在写入事务内校验当前连接。退役连接不得回填新连接的事实；新连接在收到首个完整新协议观测前，不把旧连接遗留的磁盘状态当作当前可信，旧值只保留历史展示、不驱动动作。同 collector_epoch 内拒绝较小 observation_seq，等于当前 seq 只允许字段完全一致的心跳，不刷新 measured_at，内容不同则拒绝覆盖。Node 重启后新 epoch 要求完整有效测量，不能复用旧 epoch 字节数。此机制用于磁盘样本排序，不宣称解决 Q70 中旧操作帧与新数据库资源的跨进程身份授权。

`api/container_api.py` 手动磁盘刷新、WSS apply 及其它写入路径统一调用该规则；手动刷新不得把缺失/错误字节强制转成零，也不得用当前接收时间恢复可信。HTTP 结果携带其采集身份并与当前 WSS 状态比较，旧于当前观测的响应不得覆盖新状态。核查查询回填、序列化和仓储 allowed/nullable 列表，防止遗漏入口。

### 3. 统一有效性谓词放在任何响应之前

有效条件：协议已识别且为 version 1；身份为 match 或经成功 Docker 观测确认 no_bind；measurement_status=ok；用量各组成完整；测量身份与当前身份/进程代际一致；身份和测量未过期；没有来自退役连接或旧 HTTP 响应的回填。no_bind 只要求 overlay 完整，bind bytes 缺失不构成无效；但 no_bind 必须由成功的 Docker 观测确认，不能由异常时 bind_path 缺失推断。

初始默认身份最大年龄 30 秒，测量最大年龄 900 秒，与 Node 相同；允许配置但两端不一致时按较严格限制处理。Node 时钟偏离 Ctrl 超过允许偏差（初值 30 秒）或时间在未来时降级并记录 clock_skew，不能只用接收时间遮蔽偏差。实现测试覆盖边界、时钟变化及配置缺省。

门禁在 `_usage_from_db` 和真正动作前共用，早于 reset/upsert/mail/pause/remove。检查失败不写零、不重置冻结记录、不创建冻结锚点、不发送超限邮件、不调用暂停接口、不执行解冻重置或升级清理。高用量恢复有效后可执行正常首次冻结或维持暂停；不自动 unpause。

### 4. 冻结期中断维持累计口径（Q72 已决）

用户已明确选择：采集/身份异常不产生额外补偿。异常期间跳过处置，保留 `first_frozen_at`；恢复有效高用量后按原累计有效天数继续，达到阈值即可在该轮升级删除。不添加 invalid/review 状态阻止恢复后的删除，也不在恢复时重设冻结起点；本变更不引入 `review_required` 分支或字段。

现有机器离线/维护的 `deferral_seconds` 与人工解冻宽限继续适用，不能把本次决定理解成全部改为自然日。有效低用量仍按既有低于 95% 规则 reset。用户的“冻结后理应已通知”是业务依据，不等于现有代码已保证：当前实现是在请求 pause 前就发送“已冻结”邮件；Node 异步 accepted/success 只表示请求被受理，不保证容器此刻已 pause；邮件被 SMTP 接受也不保证送达。完整业务入口由 `unify-disk-freeze-workflow` 配套解决，分别记录策略、暂停与通知结果；本门禁只保证采集异常不重开周期、不额外顺延。

### 5. 严格错位门禁作为首版边界

本变更按 source mismatch 跳过全部磁盘自动处置响应，但仍保存异常状态与证据供查询，防止在还未解决清理目标身份时，用实际目录触发冻结后按错误 Source 删除。首版不实现清理前身份验证，也不把清理保护当作已完成；验证后到删除之间仍可能有人替换目录，端到端清理对象保护仍是明确剩余风险。

若 Q71 选择实际对象计量且允许冻结，需同步扩展两端契约与清理入口，明确预期清理对象、所有手动/自动清理入口及动作时验证；不能只在本调度层放行，也不能仅把 du 改成 proc 路径后沿用路径字符串删除。

## Risks / Trade-offs

- [旧 Node 升级过渡期间磁盘自动响应暂停] → 以可见 unverified 状态暴露；先 Ctrl 后 Node，逐机验收，不静默兼容为 ok。
- [当前值保留容易被旧 UI 当成正常] → 查询明确 current/last-known/status/timestamps；核对 Web 消费方，必要变更单独列入 Q71。
- [扫描耗时或探测不及时导致响应跳过] → 展示测量时刻与原因，记录覆盖率；这是保守停用自动动作，不代表问题已修复。
- [未知期恢复时冻结天数已超阈值] → 按 Q72 可立即升级；必须使用恢复后的可信样本，并继续遵守机器范围及人工宽限。
- [旧连接或旧 HTTP 响应晚到] → 连接代际、collector_epoch 与 observation_seq 排序；同 seq 内容不同拒绝覆盖，旧响应不刷新 measured_at。
- [手动刷新把缺失写成零] → 保留错误状态和原始空值，不用 0 冒充未知，也不清除既有 mismatch。
- [样本有效到动作之间仍有竞态] → 限定本补丁声明为采样有效性门禁；不能声称是删除路径的原子身份保证，Q70/Q71 后续约束操作端。

## Migration Plan

1. 在隔离库检验可重复升级、旧行默认状态与 JSON/时间字段；先部署 Ctrl，检查旧 Node 被标未验证且没有误动作。
2. 逐机部署 Node 新协议，检查 match 覆盖率、无效原因、真实测量年龄和查询输出。Node 无法访问宿主 proc 的部署保持 unknown，先修部署权限边界。
3. 完成两端模拟联合验收；Q71 使用保守基线，Q72 验证恢复高用量可按累计升级、恢复低用量正常重置。生产不以真实删目录作为测试。
4. 回滚 Node 时保留 Ctrl 门禁与新增列，旧样本降级 unverified；回滚 Ctrl 可能恢复旧值驱动动作的风险，不能在未核对策略时直接撤销防护。

## Source references

- `services/container_module/node_comms_modules/snapshots.py`：`_apply_disk_usage_entry`。
- `services/container_module/node_comms.py`：`apply_disk_usage_snapshot` 及快照入口。
- `services/container_module/node_comms_modules/websocket.py`：连接消费顺序与断线丢弃。
- `api/container_api.py`：手动磁盘检查及 disk 字段回写。
- `repositories/containers_repo.py`：更新字段白名单与 nullable 清空规则。
- `schedulers/container_disk_check_task.py`：完整性检查、冻结记录重置、首次冻结与升级删除。
- `services/container_module/information.py`：磁盘信息查询；`services/container_module/mount_cleanup.py`：当前清理路径选择。
