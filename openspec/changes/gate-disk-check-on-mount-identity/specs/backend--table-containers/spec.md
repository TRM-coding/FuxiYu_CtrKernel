# Spec Delta

## MODIFIED Requirements

### Requirement: containers 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Container`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。磁盘证据 SHALL 以独立列保存挂载身份状态、测量状态、结构化身份证据、身份观测时间、真实测量时间和本地接收时间；协议版本、Docker 对象、观测代际与测量身份保存在结构化证据中。旧行及缺少协议字段的样本默认未验证，MUST NOT 以 `disk_checked_at` 回填测量时间。字段定义见本变更数据附录增量，归档时同步主 spec 的 Data model appendix。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

## ADDED Requirements

### Requirement: 容器磁盘测量的证据持久化

Ctrl SHALL 持久化最新磁盘身份状态、测量状态、原因和观测代际，分别记录真实测量时间、身份验证时间及本地接收时间；协议版本、Docker 对象 ID、双方对象、进程与测量对象作为结构化证据保存。错位、缺失、未知、未验证、测量中、停止、过期或采集失败样本 SHALL 更新状态，即使没有有效字节数；显式错误字段即使值为空也必须落库，不能由仓储的通用 None 过滤丢弃。最近成功用量可保留供排障，MUST NOT 因收到失败样本或重复旧样本而刷新其测量时间。

#### Scenario: 已有正常数字后收到错位样本

- **WHEN** 当前存有正常磁盘用量，Node 随后报告 Source 与实际挂载不一致
- **THEN** 保存错位状态及证据；保留旧数字时必须将其标为历史值，不能保留正常结论

#### Scenario: 收到显式错误帧

- **WHEN** Node 报告 `measurement_status=error` 且 `total_bytes` 为 null
- **THEN** 保存错误状态、原因和接收时间；历史用量标为历史值，不刷新真实测量时间

#### Scenario: 同一结果反复推送

- **WHEN** Ctrl 连续收到同一用量结果
- **THEN** 本地接收时间可更新，但真实测量时间保持不变，样本随实际年龄失效

### Requirement: 磁盘自动处置的有效样本门禁

磁盘检查 SHALL 仅使用身份匹配或经成功 Docker 观测确认无 bind、测量完整、身份和测量均未过期且属于当前观测代际的样本；`no_bind` 只要求 overlay 测量完整。无效样本 MUST NOT 调用暂停接口，MUST NOT 触发自动冻结、容量恢复导致的冻结记录重置、冻结锚点创建、超限通知、升级删除及其挂载清理；MUST NOT 把无效数字改为零或当作仍然超限。样本校验 SHALL 在任何状态写入或处置前执行；门禁只阻止处置，不阻止异常状态与证据落库。

#### Scenario: 历史高用量现在不可验证

- **WHEN** 历史用量超过硬限额，但最新身份状态是未知或错位
- **THEN** 跳过磁盘自动处置，不新增冻结锚点，不调用暂停，不按历史值删除或发送超限通知

#### Scenario: 历史低用量现在不可验证

- **WHEN** 已存在冻结记录，历史数字低于重置阈值，但当前测量不可验证
- **THEN** 保留冻结记录，不能以历史低用量或空值触发容量恢复重置

#### Scenario: Node 停止推送或重复过期样本

- **WHEN** Node 不再提供新身份观测或新用量，导致任一证据过期
- **THEN** 即使机器仍在线或接收时间很新，也不能执行磁盘自动处置

#### Scenario: 确认无 bind 的容器

- **WHEN** Docker 观测成功确认容器没有 `/root` bind，overlay 测量完整且未过期
- **THEN** 允许按 overlay 总量执行标准磁盘处置；不得把探测失败或字段缺失当作 `no_bind`

#### Scenario: 恢复后的全新匹配测量

- **WHEN** 修复目录名后，Node 完成针对正确目录的新测量且身份和时间均有效
- **THEN** 以该测量按机器限额与长期标记执行标准磁盘检查，按原冻结锚点计算累计天数

### Requirement: 验证中断不额外顺延冻结倒计时

按照 Q72 用户决策，已经冻结的周期出现无效观测时 SHALL 保留原冻结锚点，MUST NOT 仅因采集或身份验证中断增加倒计时补偿，也不新增 review/invalid 状态阻止恢复后的累计删除。恢复可信高用量后 SHALL 按原累计有效天数判断升级删除；机器不可用窗口补偿及人工宽限 SHALL 继续遵守现有规则，不得一并取消。无效观测本身仍 MUST NOT 触发删除，且不得重开冻结周期。

#### Scenario: 超过升级阈值的采集盲区后恢复

- **WHEN** 冻结后失去可信测量，数日后恢复且用量仍超限
- **THEN** 若累计有效冻结天数达到阈值、机器可管辖且不在人工宽限期，允许本轮按既有规则升级删除；采集异常期不另行扣除

#### Scenario: 重启 Ctrl 或存在机器不可用补偿

- **WHEN** 验证中断后 Ctrl 重启，或冻结周期已有机器不可用补偿和人工宽限
- **THEN** 保留原冻结锚点、已有补偿及宽限，不重开冻结周期，也不为采集异常新增补偿

### Requirement: 未验证存量与兼容写入边界

迁移后的存量记录和缺少身份协议的旧 Node 样本 SHALL 默认未验证，不自动认定可信。WSS、手动磁盘刷新及其他磁盘写入口 SHALL 使用同一有效性规则，不能借旧入口刷新可信时间或清除异常；手动刷新 MUST NOT 把缺失或错误字节强制转成零。新 WSS 连接在收到首个完整新协议观测前 SHALL NOT 恢复磁盘自动处置资格；晚于当前观测才到达的旧连接结果、同 epoch 倒序结果或旧 HTTP 响应不能恢复当前正常结论。

#### Scenario: 旧 Node 仅上报数字

- **WHEN** 字节数字齐全但缺少协议版本、身份或真实测量时间
- **THEN** 可保存为历史展示值，标记 `unverified` 并跳过磁盘自动处置

#### Scenario: 手动刷新仍返回旧协议

- **WHEN** 手动刷新接口返回只有数字的旧格式数据，或缺失字段被解析为空
- **THEN** 不能绕过验证门禁、清除 mismatch、把空值写成零或用当前时间冒充真实测量时间

#### Scenario: 旧扫描晚于错误观测回填

- **WHEN** 已接受较新错位观测后，又收到此前代际启动的正常扫描结果
- **THEN** 拒绝该结果覆盖当前状态，并保留诊断原因

#### Scenario: 退役连接或旧 HTTP 响应晚到

- **WHEN** 新连接已接受较新观测后，退役 WSS 连接或较早的 HTTP 手动刷新才返回结果
- **THEN** 拒绝其覆盖当前状态，不刷新真实测量时间，并记录被拒原因

### Requirement: 身份异常的可观测与修复边界

查询及诊断 SHALL 区分最后成功用量、当前可信用量及异常原因，并提供 Source、双方对象身份和观测时间；当前用量只在有效样本时非空，历史值必须显式标注。异常日志 SHALL 节流且可检索。inode MUST NOT 替代数据库容器 ID，Ctrl MUST NOT 根据 inode 自动选择宿主路径、改写挂载或触发目录清理；本门禁不能被宣称为删除路径的原子身份保证，清理前身份验证与清理保护属 Q71 待选扩展，跨进程操作代际属 Q70。

#### Scenario: 管理员查看仍保留数字的异常容器

- **WHEN** 最新状态为 mismatch 而数据库保留最后成功用量
- **THEN** 返回明确的历史值标签和错位证据，不能显示为刚测得的正常用量

## Data model appendix (delta)

### containers 磁盘证据增量

以下列在实现迁移时加入 `containers`；归档时须同步更新主 spec 的 Data model appendix。设备号、inode 与进程计数在 JSON 中以十进制字符串保存，避免通用 JSON 数值舍入。

| 字段 | 建议类型及默认 | 语义 |
| --- | --- | --- |
| `disk_identity_status` | `String(24)`，默认 `unknown` | 最新挂载验证状态：`match / mismatch / missing / unknown / not_running / no_bind` |
| `disk_measurement_status` | `String(24)`，默认 `unverified` | 最新测量资格：`ok / measuring / stale / error / unverified` |
| `disk_identity` | 可空 JSON | version 1 结构化证据：`protocol_version`、`docker_id`、`collector_epoch`、`observation_seq`、`bind_identity.*`、`measurement_identity`、双方原因等；不保存 proc 路径为清理目标 |
| `disk_identity_checked_at` | 可空 UTC DateTime | Node `bind_identity.checked_at` 身份观测完成时间 |
| `disk_measured_at` | 可空 UTC DateTime | Node `measured_at` 最后成功测量真正发生的时间 |
| `disk_received_at` | 可空 UTC DateTime | Ctrl 本地收到该磁盘事实的时间，只用于接收顺序与排障 |

既有 `disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_total_bytes` 保留最近一次有效数值供查询历史展示；`bind_mount_path` 语义不变。兼容列 `disk_checked_at` 只随成功有效的新测量更新为 `disk_measured_at`，不得充当真实测量时间或本地接收时间。
