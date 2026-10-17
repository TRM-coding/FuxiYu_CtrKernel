# Spec Delta

## MODIFIED Requirements

### Requirement: containers 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Container`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。磁盘事实 SHALL 以 `disk_measurement_status`、`disk_measured_at`、`disk_received_at` 和 `disk_observation` 保存测量状态、真实测量时间、接收时间与观测 JSON；路径使用既有 `bind_mount_path` 作为业务路径。MUST NOT 新增或依赖 `disk_identity_status`、`disk_identity_checked_at`、`disk_identity` 或 dev/inode/PID 目录身份列；旧行默认测量未验证，不得以 `disk_checked_at` 回填真实测量时间。字段定义见本变更数据附录增量，归档时同步主 spec 的 Data model appendix。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

## ADDED Requirements

### Requirement: Node 路径修正与业务路径

Node SHALL 在内部唯一确定实际目录后，通过 `bind_mount_path` 返回校正业务路径；成功 Docker 明确 no_bind 时返回 `bind_mount_path=null`、`measurement_mount_path=null`、overlay-only，其余诊断状态 MUST NOT 清空或当 no_bind。Ctrl SHALL 只对当前认证机器/活跃容器/有效排序下的修正与 no_bind 清空持久化；unresolved/not_running/缺字段/不可读保留已有路径；不猜目录、不返回 proc、不按 inode 批量改历史，也不把路径状态当业务门禁。

#### Scenario: resolved 路径修正

- **WHEN** 当前认证机器上的活跃容器本次路径核对为 resolved，Node 返回校正后的 bind_mount_path
- **THEN** Ctrl 将该业务路径持久化到当前容器；不保存也不比较 dev/inode/PID

#### Scenario: 原有 bind 路径转为明确 no_bind

- **WHEN** 当前活跃容器原有 bind_mount_path，随后成功 Docker 观测明确 no_bind，Node 返回 bind_mount_path=null、measurement_mount_path=null
- **THEN** Ctrl 同步清空 containers.bind_mount_path；overlay-only 组成完整且测量有效时允许有效测量；旧 bind bytes/旧路径样本只保留历史诊断，不进入有效测量，也不保留旧路径后以 no_bind 豁免同路径检查

#### Scenario: unresolved 只保留路径不清空

- **WHEN** 路径核对为 unresolved，Node 保留已有/最后确认路径，且 measurement_mount_path 与该路径一致并测量成功
- **THEN** 测量仍按有效谓词判断，不得因 mount_path_status=unresolved 阻断业务；Ctrl 不得清空 bind_mount_path，不得把 unresolved/not_running/字段缺失/不可读当成 no_bind，也不得把诊断失败写成 measurement_error

#### Scenario: 无已有路径时不猜

- **WHEN** 路径无法唯一定位且当前没有已确认/原有业务路径
- **THEN** bind_mount_path 保持 null，不猜测目录、不返回 proc 临时路径，等待后续可确认观测

#### Scenario: 路径修正不批量改历史

- **WHEN** 某容器路径从旧 Source 修正为新业务路径
- **THEN** 只更新该活跃容器；既有恢复快照、旧清理记录和其他机器记录保持各自路径，不按 inode 追溯改写

### Requirement: 磁盘测量事实与路径一致性

Ctrl SHALL 持久化协议、`collector_epoch/observation_seq`、测量状态、`measured_at`、`measurement_mount_path` 和路径诊断。样本仅在 `measurement_mount_path` 与当前业务路径一致时更新有效 bytes/时间；明确 no_bind 时当前路径与测量路径都为 null，按 overlay-only 判断，不得携带旧 bind bytes/旧路径样本，旧值仅作历史诊断。异常/缺失 MUST NOT 写 0；错误/过期/未验证只落状态，不刷新有效测量。

#### Scenario: 路径改变后旧样本晚到

- **WHEN** 当前业务路径已修正为新路径，随后收到 measurement_mount_path 仍为旧路径的样本
- **THEN** 拒绝该样本更新 bytes/测量时间，保留路径与诊断；不得把旧路径数字标成新路径测量

#### Scenario: 明确 no_bind 的 overlay 测量

- **WHEN** Docker 明确返回 no_bind，overlay 组成完整且测量状态 ok、时间有效，Node 返回 bind_mount_path=null、measurement_mount_path=null
- **THEN** Ctrl 清空当前 bind_mount_path 后允许按 overlay 总量作为有效测量；不得把探测失败、路径缺失、不可读或字段缺失推断为 no_bind，也不得混入旧 bind bytes/旧路径样本

#### Scenario: 错误样本不伪造零

- **WHEN** measurement_status=error 且 total_bytes 为 null，或组成缺失
- **THEN** 保存 error/unverified 状态、原因和接收时间；历史数字仅作展示，不把缺失写成 0，不刷新真实测量时间

### Requirement: 测量有效谓词不带目录身份

有效测量 SHALL 只要求：协议已识别（当前 version 1；旧缺失按未验证）、measurement_status=ok、用量组成完整、measured_at 存在且未过期/不在未来超时钟偏差、measurement_mount_path 与当前业务路径一致、样本未违反当前连接/HTTP 与 collector_epoch/observation_seq 排序。MUST NOT 检查 mount_path_status=resolved、dev/inode、PID、proc 可读性或 Docker 对象编号；路径诊断失败不得单独使同一路径的成功测量失效。

#### Scenario: unresolved 路径上的有效测量

- **WHEN** mount_path_status=unresolved，但已有业务路径、measurement_mount_path 与之一致，测量成功且时间在有效期内
- **THEN** 样本有效，可用于磁盘自动处置；日志保留 unresolved 诊断但不阻断

#### Scenario: 身份不可读但测量成功

- **WHEN** Node 无法读取某目录对象编号/进程信息，但已确定业务路径且测量成功、组成完整
- **THEN** 仍按测量有效性判断，不因 dev/inode/proc 不可读拒绝样本

#### Scenario: 旧 Node 缺真实测量时间

- **WHEN** 旧 Node 只给字节数或缺少 measured_at，但没有目录身份字段
- **THEN** 标记测量 unverified，说明缺真实测量时间；不得解释成缺目录身份，也不得放行自动处置

### Requirement: 统一接收与乱序/新鲜性

WSS、HTTP 手动刷新及其他磁盘写入口 SHALL 共用同一路径修正、测量接收和排序规则。退役连接、旧连接代际、旧于当前观测的 HTTP 响应、同 epoch 较小 seq 或同 seq 内容不同的样本 MUST NOT 覆盖当前状态；新链路在首个完整新协议观测前不恢复自动处置资格。路径修正也受同一顺序约束，旧响应不得把已修正路径改回旧 Source。手动刷新 MUST NOT 把缺失/错误字节转成零，也不得用当前接收时间冒充 measured_at。

#### Scenario: 旧 HTTP 刷新晚到

- **WHEN** 当前已接受较新的路径/测量后，较早发起的手动刷新响应才返回
- **THEN** 拒绝其覆盖路径或刷新测量时间，记录被拒原因；不得回退到旧 configured_mount_path

#### Scenario: 同 epoch 倒序样本

- **WHEN** 同 collector_epoch 内收到较小 observation_seq，或同 seq 内容不同的样本
- **THEN** 拒绝覆盖当前测量；等于当前 seq 且内容一致的心跳不刷新 measured_at

#### Scenario: 手动刷新缺字段

- **WHEN** 手动刷新返回只有数字的旧格式，或缺失字段被解析为空
- **THEN** 按测量未验证保存，不写零、不用接收时间冒充测量时间、不解除已有异常

### Requirement: 验证中断不额外顺延冻结倒计时

按照 Q72 用户决策，已经冻结的周期出现路径/测量无效观测时 SHALL 保留原冻结锚点，MUST NOT 仅因采集、路径诊断或测量中断增加倒计时补偿，也不新增 review/invalid 状态阻止恢复后的累计删除。恢复可信高用量后 SHALL 按原累计有效天数判断升级删除；机器不可用窗口补偿及人工宽限 SHALL 继续遵守现有规则。无效观测本身 MUST NOT 触发删除，也不得重开冻结周期。

#### Scenario: 超过升级阈值的采集盲区后恢复

- **WHEN** 冻结后失去可信测量，数日后恢复且用量仍超限
- **THEN** 若累计有效冻结天数达到阈值、机器可管辖且不在人工宽限期，允许本轮按既有规则升级删除；采集异常期不另行扣除

#### Scenario: 路径 unresolved 中断

- **WHEN** 冻结期间路径诊断长期 unresolved，但已有业务路径和有效高用量测量
- **THEN** 仍按有效测量与 Q72 累计处理，不因诊断状态额外跳过或顺延

### Requirement: 路径/测量可观测且不越权

查询及诊断 SHALL 分开呈现业务路径、configured_mount_path、mount_path_status、mount_path_observed_at、测量状态、真实测量时间、接收时间和最后已知数值；历史值必须标注不可处置，路径诊断 unresolved 与 measurement_error 分开。路径修正和测量日志 SHALL 可检索、节流。Ctrl MUST NOT 依据 inode 或路径修正执行自动删除/清理授权；既有路径/权限检查和失败审计保留，不新增 inode 清理门禁，也不宣称 Q70 的跨进程删除原子性。

#### Scenario: 历史数字与路径诊断并存

- **WHEN** 最新测量为 error/stale，但数据库保留最后成功数字和 unresolved 路径诊断
- **THEN** 查询显示历史值标签、测量状态与独立路径诊断，不显示为当前正常用量

#### Scenario: 路径修正不等于删除授权

- **WHEN** Node 修正了 bind_mount_path
- **THEN** 后续删除/清理仍走既有权限、路径和业务检查；不得仅凭路径/目录编号修正调用删除

## Data model appendix (delta)

### containers 磁盘测量增量

以下列在实现迁移时加入 `containers`；归档时同步主 spec 的 Data model appendix。不新增目录身份列。

| 字段 | 建议类型及默认 | 语义 |
| --- | --- | --- |
| `disk_measurement_status` | `String(24)`，默认 `unverified` | `ok / measuring / stale / error / unverified` |
| `disk_measured_at` | 可空 UTC DateTime | 合计真实测量发生时间 |
| `disk_received_at` | 可空 UTC DateTime | Ctrl 接收该事实时间，只用于排序/排障 |
| `disk_observation` | 可空 JSON | `protocol_version`、`collector_epoch`、`observation_seq`、`measurement_mount_path`、`mount_path_status`、`configured_mount_path`、`mount_path_observed_at`、原因；不保存 proc 临时路径或 dev/inode 授权 |

既有 `bind_mount_path` 为业务路径；`disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_total_bytes` 保留最近一次有效数值。`disk_checked_at` 只作兼容字段，MUST NOT 充当真实测量时间、路径核对时间或授权依据。
