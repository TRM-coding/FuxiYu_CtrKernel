# Tasks

## 1. 数据模型与仓储原语

- [ ] 1.1 在 `ContainerDiskFreezeState` 增加暂停阶段、工作流租约、通知状态/事实/代际/尝试/租约/下次尝试/更新时间/JSON 列及到期扫描索引；新增 `migrations/2026-10_disk_freeze_workflow.sql`，并扩展 `__init__._ensure_freeze_state_schema` 的幂等补列。验证：在隔离 SQLite 用旧结构建表后执行补列，确认列、默认值、索引存在且重复执行不改变已有行；对照 MySQL DDL 与模型声明一致。
- [ ] 1.2 实现原子 `get_or_create_first_frozen`（MySQL `ON DUPLICATE KEY`/SQLite `ON CONFLICT` 单语句）以及条件租约获取/释放、暂停请求序号认领原语；`upsert_first_frozen` 改为复用该原语，`reset` 改为只在无有效工作流租约时删除。验证：两个独立 session 同时首次建立只保留一行，两个进程只一个拿到租约，租约过期可接管，已存在行的 `first_frozen_at` 不变；reset 与租约并发时要么 reset 先赢使工作流 busy，要么租约先赢使 reset 延后，不能中途删行。
- [ ] 1.3 实现通知 payload 校验、条件认领、按 `notification_generation`/`notification_fact`/`notification_attempt` 条件回写和到期扫描仓储；到期扫描包含租约过期的 `sending` 残留，超过自动次数上限的残留收敛为 failed。验证：两个 session 同时认领只有一个成功；旧 attempt 的晚到回写不覆盖新结果；`partial` 只返回失败收件人；`no_recipient` 到期可重试；`sending` 租约过期后可接管且不会双写结果；attempt=5 后不再自动认领。

## 2. 暂停语义与 WSS 确认

- [ ] 2.1 重构 `actions.py`/`container_tasks.py`：新增无审计副作用的 `request_pause`，普通 `pause_container` 返回结构化 `PauseRequestResult`，移除 `_persist_paused_status` 的即时 `PAUSED` 写入；明确失败写 failed，传输超时/无有效回执写 unconfirmed。验证：Node 返回 `success=1, container_status=pausing` 时数据库仍为原状态、结果为 requested/accepted；Node 明确失败/不可暂停/传输异常分别返回 failed/not_pauseable/unconfirmed，且普通 pause 不创建冻结周期。
- [ ] 2.2 在 WSS 状态落库后调用 `reconcile_pause_status`：paused 确认、明确 pause_failed 标失败、仅实际转换写一条审计；Ctrl 侧按机器维护 `link_generation`，确认只接受当前代际，旧链路帧不得确认。验证：多帧 paused 只写一次确认审计；`requested` 不被 pausing/online 帧误确认；旧 `pause_request_seq` 的失败回执不能覆盖新请求；旧链路晚到 paused 帧被丢弃且不写通知；确认前没有“已冻结”通知。
- [ ] 2.3 实现确认超时与已暂停补齐：`requested` 超过 120 秒且状态非 paused 时按序号标 `unconfirmed`/`pause_confirmation_timeout`；入口看到已 paused 且无周期时建立当前锚点、直接 confirmed 并补通知，不重复请求。验证：超时保留锚点并进入待确认通知；传输异常不写成 failed；已暂停无周期只建一行且只发一次补齐通知；已有 requested 的容器在 WSS paused 后只确认不重发请求。

## 3. 统一冻结服务与通知

- [ ] 3.1 实现 `evaluate_disk_freeze_policy`，按固定顺序检查容器/机器 `in_scope`、长期、检查与响应开关、机器磁盘限额、可信样本门禁、用量完整、硬限额和有效宽限；`FREEZE_ONLY` 遇到低于 reset 只返回 `below_reset` 不删周期。验证：逐项构造不合格样本，确认不 reset、不 upsert、不暂停、不通知、不升级；错位/未知/过期样本返回具体原因；gate 检查发生在 reset 之前（与 gate 变更联合用例）。
- [ ] 3.2 实现 `run_disk_freeze` 的两种模式、原子锚点、条件租约和分阶段结果：首次合格 hard 建锚点并保留失败/宽限；真正 pause/remove 前重读并允许 `stale_decision` 退出；`FULL_POLICY` 允许升级，`FREEZE_ONLY` 只冻结并返回 `escalation_due`。验证：手工仅冻结不调用删除且周期/锚点不变；调度完整策略可升级；两个并发调用一个 busy；暂停失败、通知失败都保留锚点且结果不报告完成；评估后状态变化时不调用 Node。
- [ ] 3.3 实现通知事实状态机：requested 阶段不发“已冻结”，confirmed/failed/timeout/not_actionable 才生成对应事实；事实变化或手工重置递增 generation、重置 pending/attempt 并保留旧租约，最终回写同时匹配 generation/fact/attempt；条件认领、收件人快照、no_recipient 重读当前邮箱、partial 只补失败者、开发模式记失败、退避 5 分钟/15 分钟/1 小时/6 小时、最多 5 次并可由手工重置；调度器每轮执行到期通知扫描（含过期 sending）。验证：两个 session 不重复发送同一事实；暂停失败文案不称已冻结；部分失败重试不重发成功者；无收件人新增后重试能取得新邮箱；事实从 failed 转 confirmed 或手工重置时旧发送不能覆盖新状态；SMTP accepted 不被断言为最终送达。
- [ ] 3.4 把升级收敛到完整策略路径：宽限和 Q72 累计天数通过后调用既有 `remove_container`/mount 清理，删除前重读用量/门禁/宽限，发现已低于 reset 或样本失效则放弃并释放租约；删除成功后才产生 `escalation_removed` 通知，失败产生 `escalation_failed` 并保留锚点；`FREEZE_ONLY` 永不删除；升级不以容器 online/paused 为前提，`not_pauseable` 只跳过暂停请求。验证：手工冻结遇到到期周期返回 due 且容器仍在；Q72 恢复可信高用量可直接升级；离线/不可暂停但已到期的完整策略仍删除；评估后用量回落或样本失效时不删除；采集异常期间不删除；删除失败不会出现“已清除”成功通知。

## 4. 调度、API 与审计

- [ ] 4.1 改造 `container_disk_check_task`：hard 分支只调用 `run_disk_freeze(FULL_POLICY)`，删除暂停前“已冻结”邮件和直接 `pause_container` 调用，保留软限额提醒与 reset 的既有职责，并接入到期通知扫描。验证：mock Node/邮件下 hard 受理不发已冻结邮件；确认后才发；调度不再产生即时 PAUSED；软限额 24 小时提醒行为不变。
- [ ] 4.2 新增 `POST /api/containers/freeze_disk_once`，使用 `container:manage` 和机器归属校验，记录 operator，返回分阶段结果：确认/已暂停 200，仅受理或待确认 202，跳过/租约占用 409，明确暂停失败 502，通知失败但冻结成功 200+partial；该入口不删除。验证：API 契约测试覆盖各状态码、权限、operator 审计和重复调用重试通知；手工入口不触发 `remove_container`。
- [ ] 4.3 写入冻结汇总审计和 WSS 确认审计：`success` 只在本次目标动作完成时为 true（应升级则须删除完成；其余须暂停确认/已暂停），仅受理、待确认、跳过、暂停失败、应升级但删除失败为 false；detail 带 trigger/mode/cycle/pause/notification/escalation，WSS 确认带 link_generation 和请求序号；`send_mail` 的 accepted 不被写成已送达。验证：操作日志测试断言 accepted 请求没有 success=true，确认后另有一条成功确认记录，升级删除失败为 false，通知失败不改变暂停成功记录，手工触发 operator 正确。
- [ ] 4.4 更新冻结状态模型/仓储的源引用与字段附录说明，并在隔离套件中确认查询层仍能读取 `first_frozen_at/grace_until/deferral_seconds`；新增阶段字段不改变既有 `days_frozen` 口径。验证：`test_freeze_days_consistency.py` 等既有查询/调度一致性用例通过，详情字段空值语义不变。

## 5. 联合验收与文档

- [ ] 5.1 与 `gate-disk-check-on-mount-identity` 和 Node `verify-bind-mount-identity` 回放：错位/未知/过期样本不动作；旧 Node 样本 unverified；恢复可信高用量按 Q72 升级；paused 确认链、accepted 未确认链和旧链路晚到 paused 帧；记录来源与状态收敛结果。验证：模拟 Node/WSS/邮件 + 隔离 SQLite，安全套件通过，不触达真实 Node/SMTP/Docker/生产库。
- [ ] 5.2 演练迁移与部署顺序：旧结构补列可重复、旧行默认不补通知、先 gate、再 Node 逐机升级、最后本变更、回滚保留新列；在无生产数据的临时库验证。验证：迁移/回滚步骤在隔离环境可重复执行，混合版本下不会把 unverified 样本送入冻结，也不会恢复即时 PAUSED 语义。
- [ ] 5.3 完成实现后的文档收尾：核对模型字段说明与 delta 附录一致，补充源引用；运行 `openspec validate unify-disk-freeze-workflow`、`--strict` 与默认安全测试套件。验证：普通校验无 ERROR；strict 的 warning 逐条记录并确认非致命（若仅 warning 导致非零，不作为真实错误）；测试结果和任何未覆盖风险写入交付说明。

## Workflow follow-up

- 评审通过后按仓库流程 archive；archive 时把本变更 delta 的新增列合并进主规格 `openspec/specs/backend--table-container-disk-freeze-state/spec.md`，否则主规格附录会滞后。
- 普通 unpause 的 accepted 后立即授宽限、软限额提醒的跨进程去重不在本变更范围，需父代理决定是否另立变更。
- Q71 若改为按 actual 对象计量并允许冻结，必须同步扩展 Node/Ctrl 协议和清理目标身份，不能只改本入口。
- Node `verify-bind-mount-identity` 的 change 文档/协议若尚未落盘，需父代理确认其字段与 gate design 引用一致后再部署。
