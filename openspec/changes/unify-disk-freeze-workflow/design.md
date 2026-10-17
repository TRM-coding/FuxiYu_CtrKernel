# Design

## Context

动机见 [proposal.md](proposal.md)。当前实现有三处事实需要在设计里正面处理：

- [services/container_tasks.py](../../../services/container_tasks.py) 的 `pause_container`（第 312-325 行）只做守卫、请求 Node、落库和审计；它没有冻结周期、资格、通知或升级概念。
- [services/container_module/actions.py](../../../services/container_module/actions.py) 的 `_request_pause_action`（第 60-93 行）在 Node 返回 `success=1` 后即视为成功，`_persist_paused_status`（第 96-103 行）立刻把 `containers.container_status` 写成 `PAUSED`。Node 的 `/pause_container`（`FuxiYu_NodeKernel/network/api.py` 第 468-500 行）实际是启动后台线程后立即返回 `container_status=pausing`；真正暂停/失败由 `status_cache` 推进，再由 Ctrl 的 WSS 状态快照落到 `container_status`（[snapshots.py](../../../services/container_module/node_comms_modules/snapshots.py) 第 16-27、109-131 行）。因此当前 Ctrl 把 accepted 当成了 confirmed。
- 调度器的 hard limit 响应（[container_disk_check_task.py](../../../schedulers/container_disk_check_task.py) 第 268-358 行）先发“已冻结”邮件、再检查在线并 pause；冻结锚点由调度器自己 `upsert_first_frozen`，宽限和升级也在调度器里。`_DISK_CHECK_CACHE` 是进程内去重，`upsert_first_frozen`（[repo](../../../repositories/container_disk_freeze_state_repo.py) 第 38-52 行）是 get-then-insert，两个进程会竞争同一主键。
- WSS 的旧连接处理还有一个窄窗口：`_consume_link` 断开时会取消消费者，但已经进入 `asyncio.to_thread(apply_snapshot_batch)` 的帧仍可能晚于新连接的帧落库。暂停确认不能把这种旧链路晚到 paused 当成当前事实；Ctrl 接收层需要按机器维护 `link_generation`，并让状态确认与磁盘门禁共用它；该代际本身不要求 Node 新增线路字段，动作引用 action_ref 另行可选。

路径回填与测量有效门禁由配套 Ctrl 变更 `gate-disk-check-on-mount-identity` 提供；本设计只消费其业务路径、测量状态/真实时间/路径一致与连接/采样排序规则，不修改字段，也不比较 dev/inode 或要求 `mount_path_status=resolved`。Node 路径/测量协议沿用 `verify-bind-mount-identity` 名称，但只返回校正后的业务 `bind_mount_path`、`measurement_mount_path`、`measurement_status`、`measured_at` 与采样排序；不再传 `bind_identity`/`measurement_identity` 作为 Ctrl 业务门禁。

暂停动作引用由 `guard-long-term-container-transitions` 定义、Node `guard-runtime-state-reconciliation` 实现：动作受理响应可选 `action_ref={node_epoch,generation,seq}`，HTTP 状态/WSS 容器条目可选 `last_action={ref,action,phase,error_reason}`。本变更把 ref 绑定到 `pause_request_seq`，只消费精确匹配的终结 phase；旧 Ctrl 可忽略，旧 Node 缺字段按本设计第 3 节的 unconfirmed 降级。action_ref 是 pause/unpause 局部关联，不是 Q70 的全局删除身份。

## Goals / Non-Goals

**Goals:**

- 让调度器与按容器 ID 的受控运维共用同一套资格、周期、暂停、通知和升级语义。
- 把“请求已受理”和“WSS 确认已暂停”做成持久化阶段，失败/未知不伪造成功。
- 用数据库原子操作、条件认领和带过期租约替代内存去重与 get-then-insert，并如实标注重试的重复副作用边界。
- 保留 Q72 已决的累计升级口径、机器不可用 deferral 和人工解冻宽限。

**Non-Goals:**

- 不把 action_ref 当作 Q70 的全局动作 ID/删除身份；不承诺 Node 后台动作与后续 unpause 的端到端顺序。
- 不新增 actual 对象计量或清理对象身份门禁；测量无效、路径与样本不一致或过期时跳过动作。
- 不新增独立通知表、动作请求表或调度器；不改变软限额的 24 小时提醒语义。
- 不修生产数据，不改变机器限额，不把普通 pause 写成磁盘冻结。

## Decisions

### 1. 单一业务入口、两种模式

新增 `services/container_module/disk_freeze.py`，对调度器和运维暴露同一入口：

```python
class DiskFreezeMode(str, Enum):
    FULL_POLICY = "full_policy"
    FREEZE_ONLY = "freeze_only"

class DiskFreezeTrigger(str, Enum):
    SCHEDULER = "scheduler"
    MANUAL = "manual"

def run_disk_freeze(
    container_id: int,
    *,
    mode: DiskFreezeMode,
    trigger: DiskFreezeTrigger,
    operator_user_id: int | None = None,
    usage: dict | None = None,
) -> DiskFreezeResult: ...

def evaluate_disk_freeze_policy(container, usage, *, now) -> DiskPolicyDecision: ...
def reconcile_pause_status(
    container_id, raw_status, failed_reason, last_action, link_generation, observed_at,
) -> None: ...
def retry_due_notifications(limit: int = 50) -> int: ...
```

- 调度器的 hard 分支只调用 `run_disk_freeze(..., mode=FULL_POLICY, trigger=SCHEDULER)`；不再直接调用 `pause_container`、不再在调用前发“已冻结”邮件。
- 受控运维入口调用 `FREEZE_ONLY`，只冻结和通知，不删除；即使已到升级阈值也只返回 `escalation_due`。
- 普通 `container_tasks.pause_container` 保留为低层普通暂停门面：不创建周期、不发磁盘通知、不再直接写 `PAUSED`，返回结构化 `PauseRequestResult`。调度器不再使用它。
- `run_disk_freeze` 返回结构化结果，而不是 bool：

```text
status: frozen | already_paused | pause_requested | pause_unconfirmed |
        pause_failed | not_actionable | skipped | grace_active | stale_decision | busy |
        escalation_due | escalated | error
policy: eligible, skip_reason, usage_percent, hard_limit, trusted_sample
cycle: created, first_frozen_at, days_frozen, grace_active, escalation_due
pause: state, request_seq, requested_at, accepted_at, confirmed_at, action_ref, last_phase, error
notification: state, fact, attempt, accepted_count, failed_count, next_attempt_at
escalation: due, executed, error
```

### 2. 资格判断顺序固定，先门禁后副作用

`evaluate_disk_freeze_policy` 按以下顺序返回第一个不满足项，且在任何 reset/upsert/mail/pause/remove 之前执行：

1. 容器存在且有效、机器存在；
2. `machine_in_scope`（在线且非维护）；
3. `container.disk_check_enabled`；
4. `container.disk_response_enabled`；
5. 长期容器；
6. `machine.max_disk_size_gb > 0`；
7. 有效测量：`disk_measurement_status == ok`、`disk_measured_at` 真实未过期/无时钟异常、`measurement_mount_path` 与当前 `bind_mount_path` 一致（明确 no_bind 的 overlay-only 可为 null）、采样排序未失效；字段缺失/未验证按无效处理；`mount_path_status=unresolved` 不单独拒绝；
8. 用量组成完整（total/overlay/bind；明确 no_bind 时仅 overlay，不混入旧 bind bytes）；
9. `usage_percent >= hard_limit`；
10. 有效宽限：`max(effective_grace_until(freeze_state), effective_restore_grace_until(container))`；恢复宽限来自容器行 `restore_grace`，不要求冻结行、不使用旧冻结累计。任一未到期返回 `grace_active`，不暂停/通知/升级；到期后重新评估标准策略。

`FREEZE_ONLY` 不执行“用量低于 reset 即删除周期”的维护动作；低于 reset 时返回 `below_reset` 并保留原行。调度器的 reset 仍保留在完整策略路径中，但按 gate 变更的要求，门禁必须早于 reset；本变更不复制门禁实现，联合测试覆盖“无效样本不 reset”。

在真正调用 Node pause 或 remove 之前，入口重读一次容器、用量、门禁和宽限；若已低于 reset、样本失效或宽限生效，返回 `stale_decision`，不调用网络并释放租约。该重读缩小但不消除采样后状态变化的竞态，不能当作删除路径的原子授权。

**恢复宽限**：恢复长期快照在容器行写入一次 `restore_grace`，本入口只把它作为有效宽限来源，不创建/伪造冻结行，也不写 `first_frozen_at`。若已有冻结行，其锚点/累计/旧 deferral 原样保留；恢复宽限的机器不可用补偿由 `restore_grace.deferral_seconds` 只计授予后窗口。宽限有效期间入口返回 `grace_active`，不暂停、不发超限/升级通知、不删除；到期后按新实例有效测量和正常硬限额/Q72 累计处理。

软限额提醒不在本入口内，仍是调度器的独立提醒；它不创建周期，也不参与升级。

### 3. 暂停状态机：requested/accepted 与 confirmed 分离

`_persist_paused_status` 从暂停路径移除。`request_pause`（放在 `actions.py`，无审计副作用）只做守卫和 Node 请求，返回：

```text
PauseRequestResult(state=requested|not_pauseable|failed|unconfirmed,
                   accepted: bool, action_ref: dict|None,
                   last_phase: str|None, response: dict|None, error_reason: str|None)
```

`container_tasks.pause_container` 的普通门面据此写自己的审计，不写 `PAUSED`；是否真正暂停只由 WSS/实际状态决定。动作 `failed` 不是容器 `failed`。

持久化状态：

| pause_state | 含义 |
| --- | --- |
| `not_requested` | 当前周期未请求暂停 |
| `requested` | 已发出请求，可能已受理，尚无 confirmed |
| `confirmed` | 实际 WSS paused，或入口确认当前已暂停 |
| `failed` | 同步 HTTP 明确失败，或精确 ref 的 `last_action.failed`；不覆盖容器状态 |
| `unconfirmed` | 缺 ref/缺回执、超时、`unconfirmed`/`timed_out`，结果未知 |
| `not_pauseable` | 当前容器状态不允许发起暂停 |

**动作绑定**：在 `ContainerDiskFreezeState` 增加可空 JSON `pause_action_ref`，保存 `{ref, link_generation, bound_at, last_phase, last_phase_at, error_reason}`。它绑定当前 `pause_request_seq`，不新增 `node_epoch/generation/seq` 多列，也不进入长期资格 DTO。同一 ref 一旦记录终结 phase，后续 accepted/其他 phase 只作诊断，不再改写暂停阶段；实际 paused 仍可按状态确认。

关键转换：

1. **认领请求**：条件 UPDATE 把 `pause_state` 置 `requested`，`pause_request_seq = pause_request_seq + 1`，写 `pause_requested_at`，清空 accepted/confirmed/error 与 `pause_action_ref`。条件允许 `not_requested/failed/unconfirmed/not_pauseable`；`confirmed` 仅当当前 `container_status` 不是 paused（例如人工解冻后）才允许；`requested` 仅在超过重试间隔后允许。
2. **Node 受理**：条件 `WHERE pause_request_seq=:seq` 写 `pause_accepted_at` 和 `pause_state=requested`。响应若带 `action_ref`，只在 seq 仍匹配且 `last_phase` 尚未 terminal 时写入 `pause_action_ref.ref`，phase=accepted；相同 ref 的旧 accepted 不覆盖 failed/confirmed 等终结。`success=1, container_status=pausing` 只代表 accepted，不代表 paused。
3. **实际确认**：WSS 当前链路快照实际为 paused 时，条件 UPDATE 写 `pause_state=confirmed`、`pause_confirmed_at=observed_at`。只在该转换实际发生时写一条确认审计。`last_action.confirmed`/`idempotent_confirmed` 是动作成功证据，但在实际 WSS 仍为 online 时不得把 pause_state 写成 confirmed，也不得写容器 PAUSED。
4. **明确失败与取代**：仅同步 HTTP 明确失败，或当前 `pause_action_ref.ref` 与 `last_action.ref` 精确相等且 action/phase 匹配 `failed` 时，按 `pause_request_seq` 条件写 `pause_state=failed` 和错误原因；**不得**把 `containers.container_status` 写成 failed，运行态继续由 WSS/Docker 决定。若实际 WSS 已 paused，实际确认优先，不把暂停成功改写成失败。`superseded` 是旧动作被新动作取代，不写 failed；无实际 paused 时按序号写 `unconfirmed`/`pause_superseded`，等待新请求或实际状态。
5. **未确认**：缺 ref/缺回执、只收到 `unconfirmed`/`timed_out`、超时、连接异常，均按 `pause_request_seq` 写 `unconfirmed`、`pause_error_reason=pause_confirmation_timeout` 或传输原因；保留锚点并允许重试。WSS `online` 只表示当前未暂停，不得推断 `pause_failed`；反过来 `paused` 也不得推断 unpause 成功。没有方向成功或同步明确失败时不按 TTL 释放。
6. **已暂停补齐**：入口看到 `container_status=paused` 且无周期时，先原子建立锚点（`first_frozen_at=now`），直接写 `confirmed`，不重复请求；通知事实为 `pause_confirmed`，`confirmation_source=already_paused`。

**旧请求/旧链路/过期 ref**：每次请求递增 `pause_request_seq`；同步回执、失败回写、超时回写都带 `WHERE pause_request_seq=:seq`，旧尝试不能覆盖新阶段。WSS/HTTP `last_action` 必须精确匹配 `pause_action_ref.ref` 且 action 方向一致；相同 ref 的旧 accepted 不得覆盖 terminal phase。WSS 只接受当前机器 `link_generation`，旧链路或旧代际的帧直接丢弃；该代际是进程内接收排序，不是 Q70 动作 ID。Node epoch 变化后旧 ref 永不匹配；只有当前链路新鲜运行态、机器在线且非维护/无采集异常、无在途当前动作/更新请求时，才允许把旧绑定受控标为 `superseded`/`stale_node_epoch`，按实际 paused 确认或保持 unconfirmed，不伪造成功。早到 WSS 终结可在进程内按 ref 有界暂存，HTTP 回执匹配后应用；回执丢失/进程重启保持 unconfirmed。

**旧 Node**：没有 `action_ref`/`last_action` 时，只有实际 paused 成功或同步 HTTP 明确失败能结束 requested；WSS `failed`/`online` 不能反推 `pause_failed`，超时只记 unconfirmed 并安全阻断。部署说明必须列出旧 Node 覆盖率和该限制。

**普通 pause**：低层请求返回 accepted 后，`containers.container_status` 仍由 WSS 推进；接口/调用方只能报告 `pause_requested` 或 `pause_request_accepted`，不能报告 paused。由于当前没有普通 pause 的公开 API，本次只改服务契约和调度调用，不扩大生命周期动作范围。

### 4. 原子锚点、条件租约与阶段认领

**锚点建立**：`container_disk_freeze_state_repo.get_or_create_first_frozen` 用一条数据库语句完成：

- MySQL：`INSERT ... ON DUPLICATE KEY UPDATE container_id=container_id`；
- SQLite：`INSERT ... ON CONFLICT(container_id) DO NOTHING`；
- 随后按主键 `SELECT`；已存在时 `first_frozen_at` 不变。

不再先查后插，不依赖 `IntegrityError` 重试来掩盖竞争。`upsert_first_frozen` 改为调用该原语，保留既有调用方签名。

**工作流租约**：周期建立后，入口用条件 UPDATE 认领：

```sql
UPDATE container_disk_freeze_state
SET workflow_lease_owner = :token,
    workflow_lease_until = :now_plus_ttl
WHERE container_id = :id
  AND (workflow_lease_until IS NULL OR workflow_lease_until < :now)
```

`rowcount=1` 才执行策略；否则返回 `busy`。租约初值 180 秒，覆盖策略、暂停请求和升级删除；通知发送使用独立通知租约。结束时按 `workflow_lease_owner=:token` 条件释放。进程崩溃时租约自然过期，新进程可接管；接管可能重发网络请求，这是 at-least-once，不是 exactly-once。

容量恢复的 `reset` 也条件化：`DELETE ... WHERE container_id=:id AND (workflow_lease_until IS NULL OR workflow_lease_until < :now)`。如果 reset 先赢，工作流随后的租约 UPDATE 返回 0 并退出 busy；如果租约先赢，reset 延后到下一轮，避免在暂停/升级中途删除周期行。手工 `FREEZE_ONLY` 不调用 reset。

**暂停认领**与**通知认领**都用条件 UPDATE，不把“读-判断-写”拆成两个事务：

```sql
UPDATE container_disk_freeze_state
SET notification_state='sending',
    notification_attempt=notification_attempt+1,
    notification_lease_until=:now_plus_ttl,
    notification_updated_at=:now
WHERE container_id=:id
  AND (
    notification_state IN ('pending','failed','partial','no_recipient')
    OR (notification_state='sending' AND (notification_lease_until IS NULL OR notification_lease_until < :now))
  )
  AND (notification_next_attempt_at IS NULL OR notification_next_attempt_at <= :now)
  AND (notification_lease_until IS NULL OR notification_lease_until < :now)
  AND notification_attempt < 5
```

发送完成后的回写再带 `WHERE notification_generation=:generation AND notification_fact=:fact AND notification_attempt=:attempt`，防止租约过期或事实切换后旧发送覆盖新结果。通知租约初值 300 秒。

### 5. 通知状态机与重试

通知不跟暂停请求同时发“已冻结”。事实转换：

| notification_fact | 触发 | 文案事实 |
| --- | --- | --- |
| `pause_confirmed` | WSS/当前状态确认暂停 | 已冻结 |
| `pause_failed` | Node 明确失败 | 超限，暂停失败 |
| `pause_confirmation_timeout` | 受理后超时/传输未知 | 超限，暂停结果待确认 |
| `pause_not_actionable` | 当前状态不可暂停 | 超限，当前状态不可暂停 |
| `escalation_removed` | 删除完成后 | 已按累计冻结天数清除 |
| `escalation_failed` | 删除失败 | 达到清除条件，但清除失败 |

- `requested` 阶段只写 `notification_state=idle`/无事实，不发邮件；确认或失败后才进入 `pending`。
- 收件人快照：首次认领时读取当前 root owner 邮箱并写入 payload；`no_recipient` 重试时重新读取当前邮箱并更新 payload，仍为空则保持 no_recipient/退避。其余 `partial` 重试沿用 payload 中未成功的地址，避免给已成功者重发。
- 事实变化（例如 `pause_failed` → `pause_confirmed`）时，在同一条件更新中递增 `notification_generation`、写新 `notification_fact`、`notification_state=pending`、`notification_attempt=0`、`notification_next_attempt_at=now` 并重置 payload 的收件人结果；旧事实的 accepted 不阻止新事实发送。仍在有效期内的发送租约不强行清除，旧发送的最终回写必须同时匹配 `notification_generation`、`notification_fact` 和 `notification_attempt`，不能覆盖新事实。
- 同一事实已 `accepted` 时不重发；`partial` 只补发失败收件人；`failed/no_recipient` 按退避重试。
- `notification_payload` 保存事实、容器名、用量文本、days_frozen、收件人、accepted/failed 名单、`mail_mode`、最后错误和 `fact_at`；不保存正文、密码或 SMTP 配置。
- 判定：
  - 全部收件人返回 `ok=True` 且不是 development 模式 → `accepted`；
  - 部分成功 → `partial`；
  - 全部失败 → `failed`；
  - 没有 root owner 邮箱 → `no_recipient`；
  - development 模式（未配置密码，未真实发送）→ `failed`，`error_reason=mail_not_configured`，不能记成提供方接受。
- 自动重试退避：立即、5 分钟、15 分钟、1 小时、6 小时，最多 5 次；到上限后保留 `failed` 且 `next_attempt_at=NULL`，由手工仅冻结再次触发时递增 `notification_generation`、重置 attempt/next 并保留历史错误。
- 手工重置同样递增 `notification_generation`，使重置前仍在途的旧发送回写失效；重置只重试同一事实，不改变暂停/升级事实本身。
- 调度器每轮调用 `retry_due_notifications`，按 `(notification_state, notification_next_attempt_at)` 索引扫描到期行（含租约已过期的 `sending` 残留），**不要求容器仍有效**，因此升级删除后的 `escalation_removed` 通知仍可重试；扫描只发已持久化事实，不重新判断资格。扫描先把租约过期且 attempt 已达 5 的 `sending` 收敛为 failed/next=NULL，再处理可认领行。
- 通知失败不阻塞暂停、不增加冻结天数、不自动延长宽限。

**不承诺最终送达**：`send_mail` 的 `ok=True` 仅表示 SMTP 接受；设计、审计和 API 都不得写“保证送达”。发送过程中崩溃或租约过期可能重发，明确为 at-least-once，允许重复。

**软限额提醒**：仍保留现有 24 小时节流和独立提醒语义，不使用冻结通知状态；本变更只移除冻结/升级通知对 `_DISK_CHECK_CACHE` 的依赖，不宣称软提醒跨进程去重。

### 6. 升级保留在完整策略路径，手工冻结永不删除

- `FULL_POLICY` 在资格、宽限和 Q72 天数判断通过且 `days_frozen >= escalation_days` 时调用现有 `container_tasks.remove_container`，随后执行既有 mount 清理。升级判断不依赖 `container_status` 是否 online/paused：只要机器在管辖、gate/长期/开关/限额通过且不在宽限内，到期就删除；`not_pauseable` 只影响冻结阶段的 pause 请求，不得阻止完整策略升级。调度器仍是自动升级的唯一触发者，只是把资格判断收敛到同一入口。
- `FREEZE_ONLY` 不调用 `remove_container`、不清理 mount、不删除周期；返回 `escalation_due=true, escalation_executed=false` 和 `scope=freeze_only`。
- 删除成功后写 `notification_fact=escalation_removed`，再发通知；删除失败写 `escalation_failed`，保留锚点，下一轮重试。mount 清理仍是删除后的尽力而为，失败单独记录 `mount_cleanup_error`，不回滚删除结果。通知与删除结果分开，不再在删除前宣称“已清除”。
- 删除前仍检查宽限、gate、长期、开关和机器范畴；Q72 下恢复可信高用量不重设锚点、不新增顺延、不设 invalid/review，达到原累计有效天数即可升级。
- 删除使用现有软删和 `remove_container` 的 not_found 幂等语义；租约降低并发删除概率，但进程在 Node 删除成功、本地软删/通知回写之间崩溃仍是可见的 at-least-once 窗口，不声称 exactly-once。
- 删除前在同一进程重读容器的当前用量、有效测量、宽限和累计天数：若已低于 reset、测量失效/路径不一致或宽限生效，则放弃本轮删除并释放租约，让恢复清除/下一轮重新判断；只有重读仍满足硬限额和升级条件才调用 remove。该重读缩小但不消除“采样后目录/用量变化”的竞态，不宣称删除路径的原子身份保证。

### 7. 数据模型与迁移

在 `ContainerDiskFreezeState` 增加以下列（完整类型/默认值见 delta spec 的 data model appendix）：

- 暂停阶段：`pause_state`、`pause_requested_at`、`pause_accepted_at`、`pause_confirmed_at`、`pause_request_seq`、`pause_error_reason`、`pause_action_ref`（可空 JSON，集中保存 ref/link_generation/last_phase/时间/error）；
- 工作流租约：`workflow_lease_owner`、`workflow_lease_until`；
- 通知：`notification_state`、`notification_fact`、`notification_generation`、`notification_attempt`、`notification_lease_until`、`notification_next_attempt_at`、`notification_updated_at`、`notification_payload`；
- 索引：`(notification_state, notification_next_attempt_at)`。

生产迁移新增 `migrations/2026-10_disk_freeze_workflow.sql`（MySQL `ALTER TABLE ... ADD COLUMN`，可重复执行的部署检查），并扩展 `__init__._ensure_freeze_state_schema` 作为开发/测试与漏迁移的幂等兜底；两处列名、类型、默认值必须一致。SQLite 测试由模型 `create_all` 建表，不执行 MySQL DDL。

旧行默认 `not_requested`/`idle`/0，保留 `first_frozen_at`、`grace_until`、`deferral_seconds`；不补发历史通知，不追溯确认旧暂停。字符列用 VARCHAR 而非数据库 ENUM，避免新增状态要改列类型。

### 8. 审计

冻结业务每次实际执行冻结、暂停、通知或升级阶段时写一条 `operation=pause_container` 的汇总行；纯策略跳过只在日志留因，手工触发另写一条带 skip_reason 的失败审计。`detail` 至少：

```json
{
  "entry": "disk_freeze",
  "trigger": "scheduler|manual",
  "mode": "full_policy|freeze_only",
  "policy": {"eligible": true, "skip_reason": null},
  "cycle": {"created": true, "first_frozen_at": "...", "days_frozen": 2},
  "pause": {"state": "requested", "request_seq": 1, "accepted": true, "confirmed": false, "action_ref": {"node_epoch": "...", "generation": 0, "seq": 1}, "last_phase": "accepted"},
  "notification": {"state": "pending", "fact": null, "generation": 0, "attempt": 0},
  "escalation": {"due": false, "executed": false},
  "partial": false
}
```

- `success=true` 仅当本次运行的目标动作完成：本应升级删除的完整策略须删除完成；其余模式须暂停已确认或当前已暂停。仅受理、超时、跳过、暂停失败、应升级但删除失败均为 false，并带具体 `error_reason`；通知失败不翻转已完成的冻结成功，用 `partial=true` 表达。
- WSS 的 requested→confirmed 转换另写一条确认审计（`trigger=wss_confirmation`、`operator_user_id=NULL`、当前 `link_generation`、请求序号，以及匹配的 action_ref/last_phase），不每帧重复。
- 通知失败不把已确认冻结改成失败；用 `partial=true`、`notification.state=failed/partial/no_recipient` 表达，`send_mail` 的既有行继续记录真实邮件结果。
- 汇总行不复制邮件正文、地址列表或 SMTP 配置；收件人明细保留在既有 `send_mail` 审计和 `notification_payload` 的计数/状态中。

### 9. 受控按 ID 入口

新增 `POST /api/containers/freeze_disk_once`，请求 `{"container_id": int}`，权限沿用 `container:manage` + `require_machine_of_container("container_id")`，并记录操作者为 `operator_user_id`：

- 调用 `run_disk_freeze(mode=FREEZE_ONLY, trigger=MANUAL)`；
- 暂停已确认/当前已暂停 → 200，`result.status=frozen|already_paused`；
- 仅受理、待 WSS → 202，`pause.state=requested`，`confirmed=false`；超时/传输未知 → 202，`pause.state=unconfirmed`；
- 策略跳过 → 409 + `skip_reason`，不写锚点、不暂停；
- 暂停明确失败 → 502 + 保留的周期/阶段；
- 通知失败但冻结已确认 → 200 + `partial=true` 和通知失败状态；同一入口再次调用会重试未完成通知；
- 租约被占用 → 409 `freeze_in_progress`，可重试；
- 该入口永不调用升级删除。

### 10. 被否决的替代方案

- **新增动作请求表/通知表**：会复制周期状态、增加新能力边界；本变更复用 freeze-state 的行级阶段列即可。
- **`SELECT ... FOR UPDATE` 后跨 SMTP 发送**：把数据库锁跨网络持有，连接池和超时不可控；改用短租约 + 条件认领。
- **进程内锁或 `_DISK_CHECK_CACHE`**：多 worker/多进程下无效，正是当前重复邮件和锚点竞争来源。
- **严格 exactly-once / 事务性 outbox**：本轮不引入独立投递器；网络副作用只能做到 at-least-once + 可重试幂等，设计明确不宣称更强保证。
- **把 Node action_ref 当成 Q70 全局删除身份**：action_ref 只关联 pause/unpause 的 node_epoch/generation/seq，不能授权跨进程删除；本变更只用它精确关联暂停阶段，删除仍保持既有软删与租约边界。完全不使用 action_ref、只靠时间戳/方向猜动作失败同样被否决。

## Risks / Trade-offs

- [WSS 延迟或丢帧导致确认超时] → 保留 requested/unconfirmed，超时后标记待确认并可重试；不把超时当成功，也不在超时后直接改容器状态。WSS `online` 不推断 pause_failed。
- [pause 动作失败但容器实际 online] → 精确 ref 的 `last_action.failed` 写 pause_state=failed、保留锚点，但不写容器 failed；长设门禁按实际 online 解除过渡。旧 Node 缺 ref 时只能 unconfirmed 安全阻断，部署说明明确该限制。
- [Node 后台旧 pause 在后续 unpause 后落地] → WSS 以实际状态为准并如实展示；action_ref 不是端到端动作代际，本变更不宣称解决 Q70。
- [旧链路晚到 paused/failed 帧] → Ctrl 侧 `link_generation` 在每次认证连接递增，状态落库、last_action 与确认只接受当前代际；旧代际帧丢弃。该代际是进程内接收排序，不持久化、不替代 Q70。
- [早到 WSS 或 ack 丢失] → 早到终结按 ref 有界暂存，回执匹配后应用；ack 丢失/重启保持 unconfirmed，不伪造成功。Node epoch 变化只在新鲜就绪/无在途当前动作时受控标 superseded；若没有可观察的新 epoch/终结记录，不按时间推断，保持 unconfirmed 安全阻断。
- [租约过期后接管造成重复 pause/邮件/删除] → 条件认领与尝试序号降低范围，明确 at-least-once；审计保留每次尝试，不承诺 exactly-once。
- [通知服务不可用或没有收件人] → 持久化 failed/partial/no_recipient 和退避，不阻塞暂停、不补偿天数；最终送达不作保证。
- [升级删除后进程在通知回写前崩溃] → 软删/删除审计已落，通知可能缺失；通过到期通知扫描可补发已持久化事实，但崩溃窗口仍是已知边界。
- [gate 测量字段未部署] → 缺真实测量/协议按未验证跳过，自动冻结停摆但不误动作；部署顺序必须先完成 Ctrl 测量接收/Node 路径测量协议。
- [普通 unpause 仍是 accepted 后立即授宽限] → 这是既有边界，本变更不扩大；人工解冻宽限的确认语义需另行决策，不能在本文假装已修。
- [主规格 data model appendix 不会随 delta 自动合并] → archive 时需把本 delta 的附录列合并进 `openspec/specs/backend--table-container-disk-freeze-state/spec.md`；本变更只写 change 目录。

## Migration Plan

1. 先执行 `migrations/2026-10_disk_freeze_workflow.sql`（或确认应用启动补列已执行），验证重复执行不报错、旧行默认值正确、索引存在；只在隔离库演练。
2. 先部署 `gate-disk-check-on-mount-identity` 的 Ctrl 测量/路径字段和有效谓词，核对旧样本显示测量 unverified；再逐机部署 Node 路径/测量协议与 action_ref/last_action，核对路径回填覆盖率、真实测量年龄、路径样本一致、旧 Node 缺口和 action_ref 覆盖；最后部署本冻结业务变更。若因排期提前部署本变更，它会对未验证测量 fail closed（自动冻结停摆），不能当作已完成上线。
3. 用模拟 Node/WSS/邮件和隔离 SQLite 回放：accepted→paused、精确 failed+online、confirmed+online 保留屏障、同 ref 旧 accepted、超时/unconfirmed、早到 WSS、epoch 变化/旧链路、已暂停补齐、并发锚点/租约、通知部分失败、Q72 恢复升级、仅冻结不删除。
4. 回滚：保留新增列（旧代码忽略它们）；回滚 Ctrl 会恢复“即时 PAUSED”和调度器旧邮件顺序的风险，不能在未核对 gate/冻结策略时直接撤销防护。Node 回滚只降级样本为未验证，不应删除列或绕过门禁。

## Dependencies / Follow-ups

- 依赖 `gate-disk-check-on-mount-identity` 的 `disk_measurement_status/disk_measured_at/disk_received_at/disk_observation`、业务路径回填与统一测量有效谓词；依赖 Node 路径/测量协议（原 `verify-bind-mount-identity` 名称保留）的测量状态/真实时间/测量路径/采样排序；依赖 `guard-long-term-container-transitions` 定义的 Node 可选 `action_ref`/`last_action` 契约及共享 `link_generation`。本变更只消费这些字段，不修改 Node 协议；不比较 dev/inode、不要求 mount_path_status=resolved，旧 Node 缺 ref 时按 unconfirmed 降级。
- Node 只负责内部定位并回填业务路径；冻结/清理按该路径与既有权限执行，不新增 actual 对象计量或清理对象身份门禁。
- 普通 unpause 的 accepted→宽限确认、软限额提醒的跨进程去重不在本变更范围，需由父代理决定是否另立变更。
- archive 时把 data model appendix 合并进主规格；本变更的写范围只到 change 目录。
