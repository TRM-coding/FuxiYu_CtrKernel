# Spec Delta

## ADDED Requirements

### Requirement: 磁盘冻结业务分阶段审计

每次实际执行冻结、暂停、通知或升级阶段的磁盘冻结业务运行 SHALL 写入一条 `operation_logs` 记录，`operation` 复用 `pause_container`，`detail` 至少包含 `entry=disk_freeze`、`trigger`、`mode`、策略跳过原因、周期锚点、暂停阶段、通知阶段（state/fact/generation/attempt）和升级阶段。`success` SHALL 只在本次运行的目标动作完成时记为 true：本应升级删除的完整策略须删除完成，其余模式须暂停已确认或当前已暂停。仅 Node 受理、待确认、策略跳过、暂停失败或应升级但删除失败 MUST NOT 记为成功。

#### Scenario: 暂停已确认

- **WHEN** 冻结业务确认容器实际处于暂停状态且周期已建立
- **THEN** 审计记录 success=true，detail 的 pause.state=confirmed，并保留 trigger、mode、锚点和请求序号

#### Scenario: 暂停仅被受理

- **WHEN** Node 返回 success=1 且容器状态为 pausing
- **THEN** 审计记录 success=false、error_reason=pause_pending_confirmation，detail.accepted=true 且 confirmed=false，不写成已冻结

#### Scenario: 应升级但删除失败

- **WHEN** 完整策略判定 escalation_due，但 remove_container 失败
- **THEN** 审计记录 success=false、upgrade.error 和已保留的周期；不能因为此前暂停成功而写成整次成功。若删除成功而后续 mount 清理失败，则目标删除仍算完成，mount_cleanup_error 单独记录

#### Scenario: 策略跳过

- **WHEN** 容器非长期、响应开关关闭、样本未验证或处于有效人工宽限
- **THEN** 手工触发写一条带 skip_reason 的失败审计且不暂停；调度范畴外保持既有静默跳过，不伪造成功记录

### Requirement: 冻结通知结果与暂停结果分开记录

`operation_logs` SHALL 分别记录暂停阶段和通知阶段；`send_mail` 的 success SHALL 只表示邮件提供方接受，`detail` SHALL 保留 `mail_mode` 和失败原因，MUST NOT 被解释为最终送达。部分成功、无收件人、开发模式未发送和重试 SHALL 保留真实状态；通知失败 MUST NOT 把整次冻结记为成功或失败。

#### Scenario: 提供方接受

- **WHEN** SMTP 对全部收件人返回成功
- **THEN** 通知阶段记录 accepted、收件人数和尝试次数；不写“保证送达”

#### Scenario: 部分成功或无收件人

- **WHEN** 部分收件人失败、全部失败或没有 root owner 邮箱
- **THEN** 分别记录 partial、failed 或 no_recipient，并保留可重试状态和下次尝试时间

#### Scenario: 开发模式

- **WHEN** 邮件模块因未配置密码返回 development 模式
- **THEN** 记录 mail_mode=development 且不得把该次发送记为真实提供方接受

### Requirement: 触发来源与暂停确认事件可追溯

冻结审计 SHALL 带 `trigger`（`scheduler` / `manual`）和 `operator_user_id`；调度触发时 operator 为空，手工触发时记录操作者。暂停阶段 SHALL 在存在时记录 `action_ref` 与 `last_phase`，但不把它们当作删除授权。WSS 状态确认 SHALL 仅在暂停阶段发生实际转换时写一条确认审计，带 `trigger=wss_confirmation`、当前 `link_generation`、请求序号和匹配的 action_ref/last_phase，MUST NOT 每帧重复写。策略范畴外静默跳过 MUST NOT 伪造审计；手工触发的策略跳过 SHALL 留下具体原因。

#### Scenario: 手工仅冻结

- **WHEN** 管理员按容器 ID 触发仅冻结模式
- **THEN** 审计 trigger=manual、mode=freeze_only，并记录不执行升级删除的范围

#### Scenario: WSS 确认只记一次

- **WHEN** 连续多帧状态快照都为 paused 且暂停阶段已确认
- **THEN** 只在首次 requested→confirmed 转换时写确认审计，后续帧不重复记录

#### Scenario: 机器范畴外

- **WHEN** 调度发现机器离线或维护中
- **THEN** 沿用既有职责划分静默跳过，不写冻结成功或失败审计，也不发送磁盘通知

## Data model appendix (delta)

`operation_logs` 表结构不变。本变更只约定既有 `operation`、`success`、`error_reason`、`detail` 字段的冻结业务语义；不新增列，不改变日志保留期，也不把审计写入当作网络副作用成功的证明。
