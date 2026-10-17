# Spec Delta

## ADDED Requirements

### Requirement: 持久化动作引用绑定

系统 SHALL 在 `containers` 上持久化未确认动作：`runtime_transition` 为可空字符串，只记录 `pausing` 或 `unpausing`；`runtime_action_binding` 为可空 JSON，集中保存 Node `action_ref` 及本地绑定，不把 `node_epoch`/`generation`/`seq` 拆成多个业务列。绑定 JSON SHALL 支持 `action_ref`（精确三元组或 null）、`local_request_id`、`local_request_seq`、`link_generation`、`bound_at`、`last_phase`、`last_phase_at`、`error_reason`；时间一律 UTC 字符串。旧行的 `runtime_transition`/`runtime_action_binding` MUST 为 NULL，且 MUST NOT 用旧冻结记录或 `disk_checked_at` 回填。

#### Scenario: 存量行没有伪造绑定

- **WHEN** 升级后读取没有新动作证据的历史容器
- **THEN** 两个字段均为空，不因冻结记录存在而推定仍有在途动作

#### Scenario: 精确引用绑定

- **WHEN** Node 对 pause/unpause 返回 `action_ref={node_epoch,generation,seq}`
- **THEN** Ctrl 只把该精确三元组写入当前过渡的绑定 JSON，并同时保存本地请求序号与接收时链路代际；后续任何 last_action 必须三元组完全相等才可作用于该过渡

#### Scenario: 资格 DTO 不扩张

- **WHEN** 读取容器 detail/brief 或长期资格
- **THEN** 既有固定 8 字段 `long_term_eligibility` 不因动作引用新增字段；动作绑定只存在于容器行和进程内状态

### Requirement: Node 回执绑定前的本地请求身份

普通 pause/unpause 在取得 Node ref 前 SHALL 持久化每次唯一的 `local_request_id`；受理绑定、同步失败及传输异常回写 MUST CAS 匹配该 ID，MUST NOT 以可空的冻结请求序号、容器名或同方向过渡猜测本次请求。

#### Scenario: 普通动作的旧 HTTP 回执晚到

- **WHEN** 普通 pause/unpause 的旧 HTTP 回执晚到，而同容器已登记另一 `local_request_id` 的新请求
- **THEN** 旧回执不得绑定或清除新请求的过渡；冻结请求序号为空也不能绕过该检查

### Requirement: Node 动作受理与精确引用关联

Ctrl SHALL 消费 Node HTTP 动作受理响应的可选 `action_ref`，以及 HTTP 状态/WSS 容器条目的可选 `last_action={ref,action,phase,error_reason}`；`last_action` 的 phase 仅允许 `accepted`、`confirmed`、`idempotent_confirmed`、`failed`、`unconfirmed`、`superseded`、`timed_out`。Ctrl MUST 按精确 `action_ref` 三元组匹配，MUST NOT 按容器名、操作方向或时间窗口猜测归属；MUST NOT 因 `last_action` 存在就信任其运行状态。相同 ref 的晚到 `accepted`/`unconfirmed` MUST NOT 覆盖已记录的终结 phase。

#### Scenario: 受理回执绑定当前请求

- **WHEN** 当前本地过渡仍未被新请求替换，Node 受理返回带 action_ref 的响应
- **THEN** Ctrl 条件写入该 ref 与本地过渡/冻结 `request_seq`，不把 accepted 当作动作完成

#### Scenario: 同 ref 旧 accepted 不覆盖终结

- **WHEN** 已按同一 ref 记录 `failed` 或 `confirmed` 后，又收到相同 ref 的旧 `accepted` 帧
- **THEN** 旧 accepted 被忽略，终结 phase 与本地过渡状态不被回退

#### Scenario: WSS 早于 HTTP 受理

- **WHEN** WSS 的 `last_action` 终结记录先于 HTTP `action_ref` 回执到达，且当前链路代际有效
- **THEN** Ctrl 可在进程内有界暂存该终结记录；HTTP 回执到达且 ref 精确匹配后再应用；回执丢失或进程重启时保持未确认，不伪造成完成

#### Scenario: 旧 Node 缺 field

- **WHEN** Node 受理响应或状态条目没有 action_ref/last_action
- **THEN** Ctrl 仍按运行态方向成功或同步 HTTP 明确失败处理；反向状态不得反推动作失败，呈现 `unconfirmed` 安全阻断，并在部署说明中标明该混合版本限制

### Requirement: 终结动作与方向成功

只有精确 ref 匹配的终结动作记录才可结束对应动作阶段：`failed`/`superseded` SHALL 结束在途过渡，但动作结果处理 MUST NOT 直接写 `container_status=failed`，运行态仍以 Docker/WSS 为准；`confirmed`/`idempotent_confirmed` 是成功证据，但只有同一当前链路快照的实际状态方向相符（pause→`paused`，unpause→`online`，或安全的 `offline`）时才清除过渡；`unconfirmed`/`timed_out` MUST NOT 作为完成证据，MUST NOT 靠 TTL 或超时自动放行。实际 `paused`/`online` 仍可按方向确认成功，方向不符的状态 MUST NOT 被反推为动作失败。

#### Scenario: pause 失败但容器仍 online

- **WHEN** 精确 ref 的 last_action 为 pause/failed，WSS 当前终态为 `online`
- **THEN** 在途过渡结束，容器保持 `online`，不写 `failed`；长期取消可按稳定 online 继续评估

#### Scenario: unpause 失败但容器仍 online

- **WHEN** 精确 ref 的 last_action 为 unpause/failed，实际运行态已为 `online`
- **THEN** 过渡结束，容器保持 `online`；不得因动作失败把在线容器标记为 failed

#### Scenario: 超时或未确认不放行

- **WHEN** 只收到 unconfirmed 或 timed_out，且实际状态方向不匹配
- **THEN** 过渡保留，长期实际切换继续安全阻断；不按时间戳或 TTL 释放

#### Scenario: 实际方向成功

- **WHEN** 当前链路 WSS 报告 `paused`（pausing 过渡）或 `online`（unpausing 过渡）
- **THEN** 即使没有可匹配的最后动作记录，也按实际状态结束过渡；`offline` 可作为稳定终态结束过渡

### Requirement: 旧链路、旧 Node 与 Node epoch

Ctrl 接收 WSS 动作/状态时必须使用 gate/unify 共用的当前机器 `link_generation`，旧连接或旧代际的 last_action MUST NOT 结束当前过渡。action_ref 的 `node_epoch` 是 Node 进程启动代际，不是 Q70 的全局删除身份；epoch 变化后旧 ref MUST NOT 匹配。需要受控重建时 MUST 同时满足：当前链路已给出新鲜运行实态、机器在线且非维护/无采集异常、容器为可判定终态、且没有在途的当前动作或更新的本地请求；重建只能把旧绑定标为 `superseded` 并记录 `stale_node_epoch`，MUST NOT 伪造动作成功，MUST NOT 宣称实现 Q70 的跨进程删除原子性。

#### Scenario: 旧链路晚到终结帧

- **WHEN** 机器已建立新链路，旧链路才送达 last_action 终结帧
- **THEN** 该帧因链路代际不是当前代际而被丢弃，不结束过渡、不改变长期资格

#### Scenario: 过期 ref 不匹配当前动作

- **WHEN** 本地绑定已被新请求替换，旧 ref 的 accepted/终结帧才到达
- **THEN** 三元组不再匹配任何当前绑定，旧帧不改变新过渡；只能由新 ref、方向成功或受控核对收敛

#### Scenario: Node epoch 变化

- **WHEN** 观察到新 node_epoch，旧过渡仍绑定旧 epoch，且没有可匹配的新 ref
- **THEN** 旧 ref 永不匹配；只有新鲜就绪运行态且无在途当前动作时才受控标记 superseded，按实际状态重新评估，不伪造 confirmed

#### Scenario: 旧 Node 无 ref 的反向状态

- **WHEN** 旧 Node 只报告 online，没有 action_ref/last_action，当前过渡为 pausing
- **THEN** online 不是 pause 成功，也不能推断 pause 失败；过渡保持 unconfirmed 安全阻断，等待方向成功或同步明确失败

### Requirement: 复活不得继承旧动作绑定

软删容器复活时，系统 SHALL 清空 `runtime_transition` 与 `runtime_action_binding`；删除前的在途动作、Node ref 和链路代际 MUST NOT 被新实例继承。长期标记是否补回由长期恢复门禁另行决定，运行过渡清理不得代替该门禁。

#### Scenario: 旧动作不跨实例

- **WHEN** 容器在存在 pausing/unpausing 绑定时被软删，之后按删除快照恢复
- **THEN** 复活后的两个字段为空，新实例只按新的运行事实和长期策略评估

### Requirement: 动作绑定可重入且不制造长期副作用

动作绑定的写入 SHALL 幂等；相同 ref/phase 的重复帧不新增行、不改变容器身份。动作绑定的维护 MUST NOT 新增、删除或移动长期标记，MUST NOT 修改 `container_disk_freeze_state` 的锚点、宽限、顺延或累计计时。

#### Scenario: 重复终结帧

- **WHEN** 同一 ref 的相同 failed/confirmed 记录重复到达
- **THEN** 本地 phase 与容器状态幂等，不重复审计确认，不产生额外长期或冻结副作用

#### Scenario: 新动作替换旧过渡

- **WHEN** 同一容器开始新的 pause/unpause 动作
- **THEN** 新动作以新的本地请求和 ref 替换旧绑定；旧 ref 的晚到 accepted/terminal 不得结束或覆盖新过渡

## Data model appendix

### containers 持久化结构（新增字段）

| 字段 | 模型声明 | 说明 |
| --- | --- | --- |
| `runtime_transition` | `db.Column(db.String(24), nullable=True)` | 最近未确认方向：`pausing`/`unpausing`；终态清除；不作为 `container_status` |
| `runtime_action_binding` | `db.Column(db.JSON, nullable=True)` | 集中保存精确 action_ref、local_request_id/冻结序号、链路代际、phase 与时间；不对长期资格 DTO 暴露 |
| `restore_grace` | `db.Column(db.JSON, nullable=True)` | 恢复长期快照的一次性静默宽限：`until/granted_at/deferral_seconds/source`；不伪造冻结行/`first_frozen_at`，不进入资格 DTO |

## Source references

- [models/containers.py](../../../../../models/containers.py)：`Container.container_status`、`status_unknown_since` 与新增动作绑定/恢复宽限字段。
- [services/container_module/node_comms_modules/snapshots.py](../../../../../services/container_module/node_comms_modules/snapshots.py)：状态快照应用、当前 link_generation 与 last_action 消费。
- [services/container_module/actions.py](../../../../../services/container_module/actions.py)：pause/unpause 请求、受理 ref 和失败分支。
- [repositories/containers_repo.py](../../../../../repositories/containers_repo.py)：更新白名单与显式清空字段。
