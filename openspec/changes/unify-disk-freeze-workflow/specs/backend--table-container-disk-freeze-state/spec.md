# Spec Delta

## MODIFIED Requirements

### Requirement: container_disk_freeze_state 生产职责与生命周期

系统 SHALL 按以下周期语义使用本表：first_frozen_at 为冻结周期起点，grace_until 为人工宽限；机器不可用窗口关闭累加 deferral_seconds；用量低于限额 95% 且没有进行中的冻结业务租约时删除冻结状态，租约有效时清除 SHALL 延后。暂停阶段、工作流租约和通知结果 SHALL 与周期同行持久化，用于跨进程幂等和可重试，但 MUST NOT 取代 first_frozen_at、grace_until 或 deferral_seconds 的既有语义。

#### Scenario: 容量恢复

- **WHEN** 磁盘用量回落至限额的 95% 以下且没有进行中的冻结业务租约
- **THEN** 清除冻结状态和该周期通知/阶段数据，下一次冻结建立新锚点

#### Scenario: 恢复与冻结并发

- **WHEN** 用量已低于重置阈值，但另一进程正持有该周期的工作流租约
- **THEN** 本次不删除周期，进行中的冻结结束/租约释放后的下一轮再按恢复清除；不得在冻结动作中途删除行

#### Scenario: 旧行升级

- **WHEN** 存量行在新增阶段列后首次被读取
- **THEN** 使用 not_requested、idle 和零次尝试等安全默认值，保留原 first_frozen_at/grace_until/deferral_seconds，不补发历史通知，也不在迁移时写 confirmed；后续状态快照或业务运行看到实际 paused 时，才按当前事实确认

#### Scenario: 进程在阶段中重启

- **WHEN** 进程在已写入 requested 阶段或持有租约时退出
- **THEN** 租约到期后新进程按持久化阶段继续，不把已受理当作已确认，且不重建或刷新 first_frozen_at

## ADDED Requirements

### Requirement: 磁盘冻结使用统一业务入口

系统 SHALL 提供统一磁盘冻结业务入口，供调度器与受控按容器 ID 的运维触发复用；入口 SHALL 支持完整策略与仅冻结两种模式。普通暂停 MUST NOT 创建冻结周期；任何入口 MUST NOT 把低层 Node 暂停受理视为完整冻结完成。入口 SHALL 返回策略、周期、暂停、通知和升级的分阶段结果。

#### Scenario: 运维按 ID 仅冻结

- **WHEN** 指定容器满足硬限额资格且运维选择仅冻结模式
- **THEN** 入口建立或复用周期、尝试暂停并处理通知，不执行升级删除，结果明确标记 freeze_only

#### Scenario: 调度执行完整策略

- **WHEN** 调度器对合格容器调用完整策略模式
- **THEN** 入口在同一资格判断后处理冻结、通知及已到期的升级，结果分别记录各阶段

#### Scenario: 普通暂停

- **WHEN** 非磁盘冻结业务调用普通暂停
- **THEN** 只请求 Node 暂停并等待 WSS 状态，不创建冻结周期、不发送磁盘超限通知

#### Scenario: 不合格不动作

- **WHEN** 容器不满足资格或样本不可信
- **THEN** 返回具体跳过原因，不暂停、不写锚点、不发送磁盘通知、不升级

### Requirement: 磁盘冻结资格与有效测量门禁

入口 SHALL 在任何锚点写入、暂停、通知或升级前验证：容器有效、机器在管辖范围、长期容器、磁盘检查与响应开关、机器磁盘限额、业务路径上的有效测量、硬限额及有效宽限（人工 `grace_until` 与容器行 `restore_grace` 一起判断）。测量未验证、状态非 ok、真实时间过期、路径与样本不一致或采样乱序时 MUST 跳过全部磁盘处置；明确 `no_bind` 的 overlay-only 测量路径可为 null，但不得混入旧 bind bytes/旧路径样本。`mount_path_status=unresolved` 本身 MUST NOT 阻断同一业务路径上的有效测量，也不检查 dev/inode；Node 只校正业务路径，不新增 actual 对象计量或清理对象身份门禁。

#### Scenario: 测量无效或未验证

- **WHEN** 测量状态非 ok、缺真实 measured_at、测量过期，或 measurement_mount_path 与当前 bind_mount_path 不一致
- **THEN** 返回 disk_sample_untrusted 及原因，不重置周期、不建立锚点、不暂停、不通知、不升级

#### Scenario: 路径 unresolved 但同路径测量有效

- **WHEN** mount_path_status=unresolved，但已有业务路径、measurement_mount_path 与之一致，测量成功且真实时间有效
- **THEN** 允许按该测量继续资格判断，不以路径诊断拒绝，也不把诊断失败伪装成 measurement_error

#### Scenario: 非长期或开关关闭

- **WHEN** 容器不是长期容器、磁盘检查关闭或响应开关关闭
- **THEN** 不创建周期也不发生磁盘动作，继续展示既有状态

#### Scenario: 机器限额不可用

- **WHEN** 机器 max_disk_size_gb 未设置或非正数
- **THEN** 不计算超限、不建立周期，返回 limit_unset

#### Scenario: 人工宽限有效

- **WHEN** 周期存在且有效 grace_until（含机器不可用 deferral 平移）尚未到期
- **THEN** 保留原锚点和宽限，不暂停、不通知、不升级；手工触发也不能绕过

#### Scenario: 恢复宽限有效

- **WHEN** 恢复长期快照的容器已有未到期 restore_grace，且新实例测量超过硬限额
- **THEN** 返回 grace_active，不暂停、不通知超限/升级、不删除；不创建或伪造冻结行，已有 first_frozen_at/累计原样保留；到期后按新实例有效测量标准处理

#### Scenario: 动作前状态已变化

- **WHEN** 入口评估合格后、真正调用 pause 或 remove 前重读发现用量已低于 reset、测量失效/路径不一致或宽限生效
- **THEN** 返回 stale_decision，不调用暂停/删除并释放租约；不得凭评估时的旧状态或旧路径样本执行动作

### Requirement: 暂停请求受理与 WSS 确认分离

系统 SHALL 区分暂停请求已受理、动作失败、结果未知和实际 WSS 暂停。Node accepted/pausing 回执 MUST NOT 直接写 containers.container_status=PAUSED；仅实际 WSS paused 或入口确认当前已暂停时，才 SHALL 记录暂停确认。入口 SHALL 为每次尝试分配单调序号，并把可选 `action_ref` 绑定到该序号；只有精确 ref 的 failed/superseded、方向相符的 confirmed/idempotent_confirmed 或实际方向成功才结束对应动作尝试，unconfirmed/timed_out 不结束；failed 写失败，superseded 写 unconfirmed/pause_superseded；旧尝试、旧链路和旧 accepted 不得覆盖新阶段。该序号、ref 和链路代际 MUST NOT 被宣称为 Q70 的全局动作 ID 或端到端删除协议；具体失败、未确认和旧 Node 语义见场景。

#### Scenario: 受理后由 WSS 确认

- **WHEN** Node 返回 pausing 且后续 WSS 快照报告 paused
- **THEN** 先记录 pause_state=requested、accepted，再由状态同步写 confirmed 和确认审计，通知这时才可使用“已冻结”

#### Scenario: 精确 ref 的动作失败但仍 online

- **WHEN** 当前 `pause_request_seq` 已绑定 action_ref，`last_action` 精确匹配且 phase=failed，WSS 当前为 online
- **THEN** 按序号条件更新 pause_state=failed 和错误原因，保留锚点；不写 containers.container_status=failed，容器保持 online，通知说明动作失败

#### Scenario: 缺 ref 的 WSS failed/online

- **WHEN** Node 没有 action_ref/last_action，只有 WSS failed 或 online；或只收到 online
- **THEN** 不得推断 pause_failed；超时后只写 unconfirmed/pause_confirmation_timeout，保留锚点并允许后续重试，不伪造确认也不写成确定失败

#### Scenario: 受理后超时未确认

- **WHEN** 请求已受理但超过确认超时仍未收到 paused、匹配的 failed 或方向成功
- **THEN** 标记 pause_state=unconfirmed、pause_confirmation_timeout，保留锚点，返回未完成并允许后续重试，不按 TTL 释放

#### Scenario: 传输异常但结果未知

- **WHEN** 暂停请求因超时或连接错误没有得到 Node 的有效回执
- **THEN** 记录 unconfirmed 和传输原因，等待方向成功、精确 ref 终结或后续重试；没有明确失败证据时不得写成 failed

#### Scenario: 同 ref 旧 accepted 不覆盖终结

- **WHEN** 已记录匹配 ref 的 failed/confirmed 后，又收到相同 ref 的旧 accepted
- **THEN** 旧 accepted 被忽略，pause_state 与终结 phase 不回退

#### Scenario: 旧动作被新动作取代

- **WHEN** 当前 `pause_request_seq` 的精确 ref 收到 superseded，且实际状态不是 paused
- **THEN** 不写 failed 或容器 failed，按序号写 unconfirmed/pause_superseded，等待新请求或实际方向状态

#### Scenario: WSS 早于 HTTP 受理

- **WHEN** WSS 的匹配 last_action 终结先于 HTTP action_ref 回执到达，且当前 link_generation 有效
- **THEN** 进程内有界暂存该终结记录，回执到达且精确匹配后应用；回执丢失或进程重启保持 unconfirmed，不伪造完成

#### Scenario: Node epoch 或旧链路变化

- **WHEN** Node epoch 已变化使旧 ref 永不匹配，或机器旧链路晚到终结帧
- **THEN** 旧 ref/旧链路帧不结束当前暂停；只有新鲜运行态、就绪门禁和无在途当前动作时才可受控标 superseded，按实际状态重评，不写 confirmed

#### Scenario: 已暂停但无周期

- **WHEN** 容器实际已暂停，现又满足磁盘冻结资格且尚无周期
- **THEN** 建立以当前时刻为起点的周期，直接记录 confirmed 并补齐该周期通知，不重复发送 pause 请求

#### Scenario: 旧请求/旧 ref 结果晚到

- **WHEN** 旧序号或旧 action_ref 的失败/终结记录在新请求之后到达
- **THEN** 条件更新因序号或三元组不匹配而不生效，新阶段保持；WSS 的真实 paused 仍可确认实际状态，旧 ref 不结束新过渡

#### Scenario: 旧链路晚到 paused 帧

- **WHEN** 机器已建立新链路，旧链路在断开前发出的 paused 帧才被应用
- **THEN** 该帧因链路代际不是当前代际而被丢弃，不确认暂停、不写通知；新链路的当前快照才是确认依据

### Requirement: 同一冻结周期重入与跨进程幂等

同一容器同一周期的重复、并发和重试 SHALL 复用原锚点，并分别持久化暂停与通知阶段。锚点建立 SHALL 使用数据库原子插入，工作流 SHALL 使用带过期时间的条件租约；暂停请求和通知 SHALL 使用条件更新、尝试次数和尝试序号认领。租约过期后的重试 MAY 重复网络副作用；系统 MUST NOT 声称暂停、邮件或删除严格 exactly-once。

#### Scenario: 并发建立首个锚点

- **WHEN** 两个工作进程同时处理同一容器的首次合格硬限额
- **THEN** 数据库原子插入只保留一个周期，两个进程读到同一 first_frozen_at，不因主键冲突使其中一次业务失败

#### Scenario: 调度器与运维同时触发

- **WHEN** 调度器和按 ID 运维在同一时刻触发同一容器
- **THEN** 条件租约只允许一个执行者，另一个返回 busy；不得只依赖单进程内存锁

#### Scenario: 租约过期后接管

- **WHEN** 执行进程崩溃或超时，租约到期
- **THEN** 新进程可接管并按阶段继续；允许重发网络请求，但必须保留原锚点并记录新的尝试序号

#### Scenario: 通知并发认领

- **WHEN** 两个进程同时尝试发送同一周期的同一通知事实
- **THEN** 条件更新只让一个获得发送租约，另一个跳过；进程在发送后崩溃时允许租约到期后重试

### Requirement: 冻结通知与暂停事实一致

通知 SHALL 与暂停事实一致：未确认暂停时 MUST NOT 使用“已冻结”；暂停失败 SHALL 说明超限及失败。通知状态、事实、尝试次数、租约、下次尝试和收件人结果 SHALL 持久化，通知失败 MUST NOT 阻止必要暂停或伪造成功；事实变化后 SHALL 重新认领，旧事实的晚到回写 MUST NOT 覆盖新事实。SMTP/邮件提供方接受不等于最终送达；系统 MUST NOT 承诺最终送达，且通知失败 MUST NOT 自动增加冻结天数。

#### Scenario: 确认后发送已冻结通知

- **WHEN** 暂停已由 WSS 或当前状态确认
- **THEN** 通知事实为 pause_confirmed，正文说明已冻结；发送结果单独记录

#### Scenario: 暂停失败但邮件可用

- **WHEN** 实际暂停失败而超限通知被邮件服务接受
- **THEN** 通知说明暂停失败或待确认，不宣称已冻结，周期保留 pause_failed

#### Scenario: 暂停已确认但通知失败

- **WHEN** 暂停成功而通知全部失败、部分失败或没有收件人
- **THEN** 暂停事实仍有效，通知记录 failed/partial/no_recipient 和下次尝试时间，返回明确的部分完成，不报告所有阶段成功

#### Scenario: 后续确认修正先前失败通知

- **WHEN** 先前已发送暂停失败通知，之后重试确认暂停成功
- **THEN** 生成新的 pause_confirmed 通知事实并说明更新，不修改历史通知记录；旧事实发送的晚到回写不得覆盖新事实

#### Scenario: 通知重试

- **WHEN** 通知处于 failed、partial 或 no_recipient 且退避时间已到
- **THEN** 重新认领并只重试未成功的收件人；no_recipient 重新读取当前 root owner 邮箱；达到自动尝试上限后保留可见失败，可由手工仅冻结再次触发

### Requirement: 累计升级与仅冻结边界

完整策略模式 SHALL 按首次锚点的累计有效冻结天数、机器不可用 deferral 和人工宽限决定升级；达到阈值且不在宽限内 MAY 执行删除。仅冻结模式 MUST NOT 删除容器或暗中消费到期周期，SHALL 返回 escalation_due。按 Q72，采集异常不新增顺延、不设 invalid/review 保护；恢复可信高用量后按原累计有效天数继续。通知失败 MUST NOT 自动增加补偿。

#### Scenario: 运维冻结遇到已到期周期

- **WHEN** 仅冻结模式触发时发现该周期已达到升级删除条件
- **THEN** 返回 escalation_due=true、escalation_executed=false 和 freeze_only 范围说明，不把暂停请求扩大为删除

#### Scenario: 常规调度恢复可信高用量

- **WHEN** 采集异常后恢复可信高用量，原累计有效冻结天数已达到阈值且不在人工宽限内
- **THEN** 完整策略按 Q72 允许该轮升级删除，不重设锚点、不新增顺延、不进入 invalid/review

#### Scenario: 到期时容器不可暂停

- **WHEN** 完整策略达到删除阈值且无有效宽限，但容器当前离线或处于不可暂停状态
- **THEN** 仍按累计天数执行升级删除；不可暂停只影响暂停阶段，不得成为跳过升级的理由

#### Scenario: 删除前用量已回落

- **WHEN** 完整策略评估时已到期，但真正删除前重读发现用量已低于 reset、测量失效/路径不一致或宽限生效
- **THEN** 放弃本轮删除并释放租约，让恢复清除或下一轮重新判断；不得凭过期/错配样本删除

#### Scenario: 采集异常期间

- **WHEN** 测量未验证、状态非 ok、真实时间过期或路径与样本不一致
- **THEN** 不依据无效测量暂停、通知或删除，锚点和既有 deferral/grace 保留；路径 unresolved 本身不构成该场景

#### Scenario: 人工解冻宽限内

- **WHEN** 人工解冻授予的有效宽限尚未到期
- **THEN** 不暂停、不升级，保留原锚点和宽限，仅冻结模式也不能绕过

### Requirement: 冻结阶段、租约与通知结果持久化

本表 SHALL 持久化 pause_state、请求/受理/确认时间、暂停请求序号、可空 pause_action_ref JSON、工作流租约、notification_state/fact/generation/attempt/lease/next_attempt/updated_at 和 notification_payload。pause_action_ref SHALL 集中保存精确 Node ref、链路代际、phase 与时间，不拆成多个业务列，也不进入长期资格 DTO。notification_payload SHALL 只保存生成通知所需事实与收件人结果，MUST NOT 保存正文、凭据或 SMTP 配置。新增列 SHALL 对旧行提供安全默认值，迁移 MUST 可重复执行；字段定义见本变更数据附录增量，归档时同步主 spec 的 Data model appendix。

#### Scenario: 阶段认领

- **WHEN** 工作进程认领暂停请求或通知发送
- **THEN** 通过条件 UPDATE 增加尝试序号/次数并取得租约，失败方不得执行网络调用

#### Scenario: 发送中崩溃后的租约接管

- **WHEN** 通知已置 sending 后进程崩溃，通知租约到期
- **THEN** 到期扫描按 generation/fact/attempt 条件接管并重试，旧发送的晚到回写不覆盖新结果；允许重复发送，不宣称 exactly-once。若已达自动尝试上限，则将残留收敛为 failed 并等待手工重置

#### Scenario: 通知 JSON 可重试

- **WHEN** 读取一条待重试通知
- **THEN** 从 notification_payload 取得事实、收件人和已成功名单，只补发未成功者，不需要重新查询邮件正文

#### Scenario: 存量表补列

- **WHEN** 对已有 container_disk_freeze_state 表重复执行迁移
- **THEN** 缺失列被补齐，已有列和行数据不变，旧行默认 not_requested/idle 且不触发通知

## Data model appendix (delta)

新增列以模型声明为准；生产 MySQL 与测试 SQLite 使用相同语义。字符列使用 VARCHAR 而非数据库 ENUM，避免后续状态扩展需要改列类型。

| 字段 | 建议类型与空值 | 默认 | 语义 |
| --- | --- | --- | --- |
| `pause_state` | VARCHAR(24) NOT NULL | `not_requested` | not_requested / requested / confirmed / failed / unconfirmed / not_pauseable |
| `pause_requested_at` | DATETIME NULL | NULL | 最近一次暂停请求发出时间 |
| `pause_accepted_at` | DATETIME NULL | NULL | Node 受理回执时间，不等于确认 |
| `pause_confirmed_at` | DATETIME NULL | NULL | WSS 或当前状态确认暂停的时间 |
| `pause_request_seq` | INTEGER NOT NULL | 0 | 单调尝试序号，用于拒绝旧回执覆盖 |
| `pause_error_reason` | VARCHAR(255) NULL | NULL | 最近暂停失败、超时或结果未知原因 |
| `pause_action_ref` | JSON NULL | NULL | 集中保存精确 action_ref、link_generation、bound_at、last_phase、last_phase_at、error_reason；不拆成多列，不进入长期资格 DTO |
| `workflow_lease_owner` | VARCHAR(64) NULL | NULL | 冻结业务条件租约持有者令牌 |
| `workflow_lease_until` | DATETIME NULL | NULL | 租约到期时间，过期可接管 |
| `notification_state` | VARCHAR(24) NOT NULL | `idle` | idle / pending / sending / accepted / partial / failed / no_recipient |
| `notification_fact` | VARCHAR(32) NULL | NULL | pause_confirmed / pause_failed / pause_confirmation_timeout / pause_not_actionable / escalation_removed / escalation_failed |
| `notification_generation` | INTEGER NOT NULL | 0 | 通知代际；每次事实变化或手工重置重试窗口递增，旧代际发送回写不得覆盖新代际 |
| `notification_attempt` | INTEGER NOT NULL | 0 | 当前事实代际内已认领发送次数 |
| `notification_lease_until` | DATETIME NULL | NULL | 通知发送租约到期时间 |
| `notification_next_attempt_at` | DATETIME NULL | NULL | 自动重试退避到期时间 |
| `notification_updated_at` | DATETIME NULL | NULL | 最近一次通知状态变更时间 |
| `notification_payload` | JSON NULL | NULL | 事实、收件人、已成功/失败名单、邮件模式、最后错误；不含正文与凭据 |

建议索引：`(notification_state, notification_next_attempt_at)`，供到期通知重试扫描；不改变 `container_id` 主键、外键和现有 `first_frozen_at/grace_until/deferral_seconds` 语义。
