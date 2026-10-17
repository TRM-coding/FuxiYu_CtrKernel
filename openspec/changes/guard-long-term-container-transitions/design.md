# Design

## Context

动机见 [proposal.md](proposal.md)。当前相关事实如下：

- [services/container_module/long_term.py](../../../services/container_module/long_term.py) 的 `_load_long_term_target` 只用 `ensure_container_operation_allowed(..., "set_long_term")`；当前矩阵允许 `paused`/`offline` 切换长期，`failed` 才拒绝。`_ensure_long_term_capacity` 只做数量校验。
- [services/container_tasks.py](../../../services/container_tasks.py) 的 `set_long_term_container` 顺序是“读目标 → 数量校验（仅新增） → 落库 → 审计”，没有磁盘门禁；`unpause_container` 在 Node 受理后立即返回成功并写宽限，真实状态仍由 WSS 推进。
- [services/container_module/restore.py](../../../services/container_module/restore.py) 的恢复路径只在 `Create_container` 前做长期数量预检，`_restore_long_term_state` 在创建后补标记；磁盘证据没有参与。
- [services/container_module/node_comms_modules/snapshots.py](../../../services/container_module/node_comms_modules/snapshots.py) 把 `pausing`/`unpausing` 放入 `_NODE_STATUS_SKIP`，只打印 debug，不落库；因此 Ctrl 只能靠“unpause 不写 ONLINE，保持 PAUSED”间接挡住取消长期，无法显式识别未确认过渡。
- [services/container_module/utils.py](../../../services/container_module/utils.py) 的 `build_long_term_container_state` 只返回长期标记、root 用户剩余额度和旧的 `long_term_container_can_enable`；详情与列表分别调用，磁盘超限由 Web 自己按 `disk_total_gb/disk_limit_gb` 判断。
- `gate-disk-check-on-mount-identity` 已设计 `disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation` 和统一测量有效谓词，但尚未实施。Node 路径/测量协议（原 `verify-bind-mount-identity` 名称保留）提供业务路径回填与测量事实，也未实施。
- 事故报告 `FuxiYu_Global/reports/sylvan-unpause-2026-10-17-{ctrl,node}.md` 证明：18:43 的合法“转非长期”发生在冻结态，服务端没有阻止；19:33 两次 unpause 被 Node accepted 后，Ctrl DB 仍为 paused，随后 Node failed pending 把状态长期钉在 `failed/unpause_failed`；单行 DB 复位被 WSS 覆盖。

本变更只写 Ctrl 的规划文档。Web 的 `align-container-action-eligibility-and-recovery` 和 Node 的 `guard-runtime-state-reconciliation` 由其他代理/变更负责，本设计只约定边界和契约。

## Goals / Non-Goals

**Goals:**

- 以一份服务端判断统一“能否启用/取消长期”，所有入口不能绕过。
- 冻结态、未确认过渡、磁盘硬超限、样本不可信、限额缺失时明确拒绝，而不是假定安全。
- 已确认解冻后允许取消长期，不让遗留 `freeze_state` 行变成永久锁。
- 保留长期数量配额、root 用户计数口径、既有幂等语义和冻结锚点/宽限/累计计时。
- 以 DTO 固化 Web/其他调用方需要的资格事实，并给出稳定原因与 HTTP 映射。
- 用事务内重读和条件写入缩小本地竞态；明确不声称 Q67/Q70。

**Non-Goals:**

- 不实现 `gate-disk-check-on-mount-identity` 或 Node 路径/测量协议，不复制其测量有效性判据；不比较目录 dev/inode。
- 不修 Node status cache 的 failed pending/旧 reconcile 覆盖；那是 `guard-runtime-state-reconciliation`。
- 不新增 Q70 的动作 ID、严格链路代际或跨进程删除授权；不宣称长设/取消与 Node pause/unpause 端到端原子。
- 不修 Q67 的跨容器长期数量并发；配额仍是现有 check-then-insert 语义。
- 不修改 `container_disk_freeze_state` 的锚点、宽限、顺延或累计语义，不删除遗留冻结行；普通 unpause 仍按既有逻辑授宽限，本变更只保证长期设置/取消不触碰这些字段。
- 不自动修复线上 Sylvan 行，不执行 SSH、生产 DB、Node 或 Docker 操作。
- 不修改 Web/Node 仓库，也不在归档前修改主规格；主规格合并留给 archive。

## Decisions

### 1. 一个资格评估器，两个方向，固定 DTO

在长期容器族中新增纯读评估入口（建议 `evaluate_long_term_eligibility(container, machine, bindings, now)`），所有写入口和 detail/brief 共用；`build_long_term_container_state` 继续保留旧字段，但把新对象一并加入返回值：

```json
{
  "is_long_term": true,
  "long_term_container_can_enable": true,
  "long_term_container_blocked_user_ids": [],
  "long_term_container_remaining_by_user": {"1": 0},
  "long_term_eligibility": {
    "can_enable": false,
    "can_disable": true,
    "enable_reason": "long_term_already_enabled",
    "disable_reason": null,
    "evaluated_at": "2026-10-17T12:05:05Z",
    "disk_total_bytes": 761000000000,
    "disk_limit_bytes": 549755813888,
    "disk_measured_at": "2026-10-17T12:05:00Z"
  }
}
```

字段和类型固定，不得增删：

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `can_enable` | `bool` | 当前非长期时表示能否实际启用；当前已是长期时为 `false`，原因 `long_term_already_enabled` |
| `can_disable` | `bool` | 当前是长期时表示能否实际取消；当前不是长期时为 `false`，原因 `long_term_not_enabled` |
| `enable_reason` | `str \| null` | `can_enable=false` 时为稳定原因；为 `true` 时为 `null` |
| `disable_reason` | `str \| null` | `can_disable=false` 时为稳定原因；为 `true` 时为 `null` |
| `evaluated_at` | `str` | 评估时刻，UTC，RFC3339 字符串；必须有值 |
| `disk_total_bytes` | `int \| null` | 持久化的最近磁盘总量；未知为 `null`，绝不补 0 |
| `disk_limit_bytes` | `int \| null` | `machine.max_disk_size_gb * 1024**3`；未配置或 `<=0` 为 `null` |
| `disk_measured_at` | `str \| null` | 真实测量时间 UTC；只取 gate 的 `disk_measured_at`，绝不回退 `disk_checked_at` |

方向语义用于消除“两个方向都可点”的歧义：已长期时 `can_enable=false` 只是表示不需要再启用，同目标 API 仍是 200 幂等成功；未长期时同理 `can_disable=false`。`can_enable=true`/`can_disable=true` 才是实际切换授权。

`disk_total_bytes`/`disk_measured_at` 是“最后已知证据”，即使样本已过期或路径与样本不一致也照实返回，便于 UI 展示；它们不是授权。授权只看 `can_enable`/`can_disable` 与理由。测量字段完全缺失时，`disk_measured_at=null`，绝不把 `disk_checked_at` 当测量时间。

旧字段 `is_long_term`、`long_term_container_can_enable`、`long_term_container_blocked_user_ids`、`long_term_container_remaining_by_user` 保留。旧 `long_term_container_can_enable` 继续只表达数量配额，不扩成综合授权；Web 和其他调用方必须以新对象为服务端裁决结果，旧字段只用于兼容展示。

### 2. 资格判断顺序与稳定原因

评估器返回第一个不满足项，保证同一状态的原因稳定、可测试。

**实际启用（非长期 → 长期）顺序：**

1. 当前不是长期（已长期由服务层短路为幂等 no-op）；
2. `runtime_transition` 为空；
3. `effective_status` 为 `online` 或 `offline`；`paused`、`failed`、`pausing`/`unpausing` 未确认、未知、主机离线/维护、`creating`/`building`/`starting`/`stopping`/`restarting` 均拒绝；
4. root 用户长期数量未达到 `container.long_term_limit`；
5. `machine.max_disk_size_gb > 0`；
6. 业务路径上存在有效测量：`disk_measurement_status=ok`、真实测量未过期、`measurement_mount_path` 与当前 `bind_mount_path` 一致、用量组成完整、无乱序回填；不检查 `mount_path_status`、dev/inode 或 Docker 对象；
7. `disk_total_bytes * 100 < disk_limit_bytes * hard_percent`。`hard_percent` 取 `container.disk_hard_limit_percent`；`disk_total_bytes` 为 null 不得按 0 通过。

**实际取消（长期 → 非长期）顺序：**

1. 当前是长期（已非长期由服务层短路为幂等 no-op）；
2. `runtime_transition` 为空；
3. `effective_status` 为 `online` 或 `offline`，且 `status_unknown_since` 为空；`paused`、`failed`、不稳定、主机离线/维护、未知均拒绝；
4. 直接允许，不再检查磁盘、数量或 `freeze_state`。

`freeze_state` 行不是取消门禁的输入。只要 WSS 已确认终态 `online`/`offline` 且无未确认过渡，即使行仍存在也允许取消；门禁只读运行事实，绝不重置 `first_frozen_at`、`grace_until`、`deferral_seconds`。

稳定原因与映射：

| reason | 类别 | 方向 | 含义 | HTTP |
| --- | --- | --- | --- | --- |
| `long_term_already_enabled` | DTO/no-op | enable | 已是长期，仅表示无需启用 | no-op 200 |
| `long_term_not_enabled` | DTO/no-op | disable | 当前非长期，仅表示无需取消 | no-op 200 |
| `long_term_transition_unconfirmed` | 运行过渡 | 双向 | `runtime_transition` 非空，pause/unpause 未确认 | 409 |
| `container_paused` | 运行状态 | 双向 | 已确认 `paused` | 409 |
| `container_busy` | 运行状态 | 双向 | `creating`/`building`/`starting`/`stopping`/`restarting` | 409 |
| `container_failed` | 运行状态 | 双向 | `failed` | 409 |
| `container_status_unknown` | 运行状态 | 双向 | 采集异常或 `status_unknown_since` | 409 |
| `container_host_offline` | 主机状态 | 双向 | 机器不可达 | 503（沿用） |
| `container_host_maintenance` | 主机状态 | 双向 | 机器维护 | 503（沿用） |
| `long_term_limit_reached` | 数量配额 | enable | root 用户数量已满 | 409 |
| `disk_limit_not_configured` | 磁盘配置 | enable | 机器未配置 `max_disk_size_gb` | 409 |
| `disk_sample_untrusted` | 磁盘测量 | enable | 测量缺失、未验证、过期、路径与样本不一致或不完整 | 409 |
| `disk_usage_over_limit` | 磁盘阈值 | enable | 已知总量达到硬阈值 | 409 |
| `long_term_state_changed` | 并发/条件写 | 双向 | 事务重读/条件写发现状态已变化 | 409 |

策略阻断统一 409，主机不可用沿用 503，权限 403、容器不存在 404、入参错误 400 不变。`long_term_already_enabled`/`long_term_not_enabled` 只出现在只读 DTO；同目标 API 返回 200，不当作错误。

### 3. 磁盘测量只复用 gate 的同一份有效谓词

启用门禁不新写一套“测量、过期、路径一致”算法，而是调用 `gate-disk-check-on-mount-identity` 实现后暴露的共享有效谓词（建议由 gate 变更提供 `disk_measurement_trusted(container, now)` 或在现有调度门禁函数上抽出的纯函数）。本变更只做适配：

- 字段不存在、`measured_at` 缺失/不可解析、协议不可识别或谓词抛错 → `disk_sample_untrusted`，不得放行；说明是测量未验证，不是缺目录身份。
- 谓词返回不可信 → `disk_sample_untrusted`；原因可细化记录在日志/失败审计。总量为负数、非整数或不可解析同样按不可信处理，不返回 0。
- 谓词通过后，本变更只额外做长期特有的“总量 vs 硬阈值”比较；硬阈值配置缺失/非法也 fail closed，不重复或放宽 gate 的测量年龄/组成/路径一致规则。
- `disk_limit_bytes` 从 `machine.max_disk_size_gb` 现算；软阈值不进入 `can_enable`，软提醒继续由既有磁盘检测/展示负责。
- 明确 `no_bind` 的 overlay-only 测量可按 gate 语义有效；不能因为 `bind_mount_bytes` 为空就推断为 0，也不检查目录 dev/inode。
- `mount_path_status=unresolved` 不单独拒绝：只要业务路径一致、测量成功且时间有效，仍可启用。
- 所有数值保持字节整数；不做 `int(x or 0)`。

这与调度使用同一 `max_disk_size_gb`、同一 `container.disk_hard_limit_percent` 和同一测量谓词，避免“调度认为超限、长期门禁认为未超限”的分裂。

### 4. Node 动作引用契约与本地动作绑定

本变更消费 Node 的可选动作引用，作为暂停/解冻动作的**局部关联**，不是 Q70 的全局删除身份：

```json
action_ref = {
  "node_epoch": "UUID 字符串，Node 进程启动代际",
  "generation": 0,
  "seq": 0
}
last_action = {
  "ref": action_ref,
  "action": "pause | unpause",
  "phase": "accepted | confirmed | idempotent_confirmed | failed | unconfirmed | superseded | timed_out",
  "error_reason": "string | null"
}
```

其中 `node_epoch` 是 Node 进程启动生成的 UUID 字符串，`generation` 是 prevent 对象的代际整数，`seq` 是该对象上的动作序号整数；三者一起构成动作的局部身份，不是 Q70 的全局删除 ID。线路位置：动作受理响应在顶层增加可选 `action_ref`；HTTP 状态响应与 WSS 容器条目在每容器条目增加可选 `last_action`，既有 `status`/`failed_reason` 等字段不变。旧 Ctrl 完全可忽略，运行态收敛不依赖这些字段。
- 旧 Node 缺字段不是协议错误；新 Ctrl 必须按第 4.6 条兼容，不能因为缺 ref 就假定成功或失败。
- ref 的三个字段缺任一、类型不符或值不合法时按“缺 ref”处理；`last_action` 的 `phase` 只按上述枚举解释，未知 phase 按 `unconfirmed` 保守处理，不得放行。

**本地持久化**：在 `containers` 增加 `runtime_transition`（String(24)，`pausing`/`unpausing`）和 `runtime_action_binding`（JSON 可空）；不新增 `runtime_transition_at`，不用时间窗口做跨动作隔离。JSON 形如：

```json
{
  "action_ref": {"node_epoch": "...", "generation": 0, "seq": 0},
  "local_request_id": "每次动作发起生成的 UUID",
  "local_request_seq": 3,
  "link_generation": 7,
  "bound_at": "2026-10-17T12:00:00Z",
  "last_phase": "accepted",
  "last_phase_at": "2026-10-17T12:00:01Z",
  "stale_reason": null
}
```

`local_request_id` 在每次 pause/unpause 调用 Node 前生成并持久化；包括尚未取得 Node ref 的普通动作，HTTP 受理绑定、明确拒绝和传输异常回写都必须 CAS 匹配此 ID。旧 HTTP 回执不得绑定到同方向的新请求。`local_request_seq` 在磁盘冻结路径额外绑定 `pause_request_seq`，普通动作可为空；不能用空序号区分两次普通请求。`link_generation` 记录受理时当前链路代际，用于诊断；WSS 处理仍以处理时的当前代际为准。

生命周期的实现边界：

1. **动作发起**：通过状态守卫后、调用 Node 前，在独立事务写 `runtime_transition` 与初始绑定（ref=null、本地请求序号、当前 link_generation）；写失败则不调用 Node。
2. **受理绑定**：HTTP 响应带 `action_ref` 时，仅当本地过渡/冻结 request_seq 仍是本次请求且尚未被替换，条件写入精确 ref 和 `last_phase=accepted`。相同 ref 的 accepted 在已记录终结 phase 后 MUST 被忽略；不同 epoch/ref 一律不匹配。
3. **last_action 处理**：WSS 只接受当前 `link_generation` 的快照；HTTP 状态响应必须来自当前请求链且 ref 精确匹配。必须同时匹配三元组与 action 方向；同一 ref 一旦记录终结 phase，后续 accepted/其他 phase 只作诊断，不再改写过渡（实际方向状态仍可结束/确认）。phase 语义：
   - `accepted`、`unconfirmed`、`timed_out`：记录 phase，但不结束过渡，不按 TTL 释放；`unconfirmed`/`timed_out` 只是“不完整”，不是完成或失败证据。
   - `failed`、`superseded`：结束在途过渡并条件清空 `runtime_transition`/binding（终结原因写诊断）；`failed` 只表示动作失败，运行态仍由 Docker/WSS 决定，**不得**把 `container_status` 直接写成 `failed`。`superseded` 表示被新动作取代，旧绑定不再阻塞，但新动作若有自己的绑定必须独立保留。
   - `confirmed`、`idempotent_confirmed`：成功证据，但只有当前运行态方向相符（pause→`paused`、unpause→`online`）或安全 `offline` 时才结束过渡；若运行态仍反向，保留收敛屏障，等待实际状态或受控核对，不能仅凭 action phase 改状态。
   - 实际 WSS `paused` 对 pausing、`online` 对 unpausing、`offline` 对两者都可结束过渡；这是无 ref 时唯一的方向成功路径。
4. **早到 WSS**：若终结 `last_action` 先于 HTTP `action_ref` 到达，可在进程内按 ref 有界暂存；受理回执到达且精确匹配后再应用。回执丢失或进程重启时保持未确认，不伪造成完成。
5. **Node epoch 变化**：旧 ref 永不匹配。只有同时满足“当前链路新鲜运行实态、机器在线且非维护/无采集异常、容器终态可判定、无在途当前动作或更新请求”时，才允许受控重建：把旧绑定标为 `superseded`、记录 `stale_node_epoch`，按实际状态重新评估；不得伪造 confirmed，也不宣称 Q70 已解。
6. **旧 Node 缺 ref**：只能靠方向成功（paused/online/offline）或同步 HTTP 明确失败解除；反向 online 不能推断 pause_failed，reverse paused 不能推断 unpause 成功/失败；无方向证据时保持 `unconfirmed` 安全阻断。该混合版本限制必须写入部署说明。
7. **软删后复活**：`restore_container_record` 必须清空 `runtime_transition` 与 `runtime_action_binding`，不得把旧 ref/链路代际/未确认动作带进新实例。
8. **无 TTL 放行**：没有匹配终结、没有方向成功时，宁可保持未确认；时间戳只作诊断。受控重建是显式条件核对，不是定时器。

该绑定不是 `container_status` 的替代，也不取代 `unify-disk-freeze-workflow` 的 pause 状态机；它只提供动作关联与“是否存在未确认动作”的事实。WSS 处理必须复用 gate/unify 的当前 `link_generation`，旧连接帧不得结束过渡；但该代际是进程内接收排序，不是 Q70 的跨进程删除授权。

### 5. 同目标幂等与事务内条件写

`set_long_term_container` 的流程改为：

1. 在单个 session 中按主键读取容器（MySQL 使用 `SELECT ... FOR UPDATE`；SQLite 依赖写事务串行化），同事务读取长期标记、绑定和机器。
2. 如果当前长期状态等于目标：直接构造返回状态，**不**做配额/磁盘/状态门禁，不写长期表、不写审计、不碰冻结表。
3. 否则调用评估器；失败抛 `NodeServiceError(reason=...)`，由 API 记失败审计并映射状态码。
4. 成功：
   - 启用用条件插入（MySQL `INSERT ... ON DUPLICATE KEY UPDATE container_id=container_id`，SQLite `ON CONFLICT(container_id) DO NOTHING`）；不把数据库驱动不稳定的 rowcount 当作唯一依据，插入后按主键回读/捕获唯一冲突确认是否由本请求实际新增，已存在则按幂等成功返回且不重复审计；
   - 取消用条件删除，`WHERE EXISTS` 同时校验容器有效、`container_status IN ('online','offline')`、`status_unknown_since IS NULL`、`runtime_transition IS NULL`，并可连接 machines 校验在线、非维护、无采集异常。rowcount=1 才写成功审计；rowcount=0 时重读，若已被并发取消则幂等返回，否则按新状态返回具体 reason 或 `long_term_state_changed`。
5. 审计只在实际新增/删除长期标记时写一条；失败路径保留现有 API 失败审计。详情/列表只读评估不写审计。

配额仍在同一事务内按 root 用户计数，但 `count → insert` 对**不同容器**的并发没有串行化保证；本变更不引入跨容器锁或 advisory lock，因此不声称修复 Q67。相同容器的并发由主键/条件插入和行锁收敛。也不引入 Q70 的跨进程动作代际：Node 已受理的 pause/unpause 与本地长期切换之间仍可能交错，本设计只缩小同一 Ctrl 进程/数据库事务内的窗口。

### 6. 手工设置、恢复长期快照及后续入口

**手工设置**：`POST /api/containers/set_long_term_container` 保持请求/响应兼容，内部走上面的评估与条件写。`is_long_term=true/false` 与当前相同即为 no-op；实际切换失败时返回稳定 reason，长期标记不变。

**恢复长期快照（同硬阈值规则 + 静默宽限）**：

- 恢复仍按保留路径创建：`_load_restore_target`/`_build_restore_container` 使用快照保留目录作为本次 bind source，不检查、不比较旧 Docker ID/PID/dev/inode，也不因目录对象不同拒绝。
- `_ensure_restore_long_term_capacity` 继续只按现有 root 用户配额预检，仍在 `Create_container` 之前；配额失败保留原 reason/数量。路径、机器、权限、image choice 和创建错误均沿用既有检查；不新增仅为此的 Node preflight 端点。
- 快照为长期且实际执行恢复时，自动恢复长期标记并授予一次静默宽限；快照非长期不新增标记也不授宽限。宽限时长取现有 `settings_tasks.get_container_disk_freeze_grace_days()`，不要求提前知道新实例是否超限，不增加确认框/按钮/token/前端状态机。
- **最小持久化**：在 `containers` 增加可空 JSON `restore_grace`，形如 `{"until":"UTC","granted_at":"UTC","deferral_seconds":0,"source":"resurrect:<deleted_id>"}`。不新增冻结表列、不伪造 `first_frozen_at`/冻结行；无冻结记录时仍可单独授恢复宽限。
- **原子可见性**：在把恢复容器 `is_valid=True` 的同一数据库事务内写入长期标记、`restore_grace`，并完成 `restore_container_record`；提交前调度看不到有效行，提交后标记与宽限同时可见，不允许“先有效、后宽限”的窗口。若事务/标记/宽限写入失败，回滚为未恢复状态并记失败审计，不报告完整成功。
- **幂等认领**：`source` 用稳定的 `resurrect:<deleted_id>`；恢复事务内对软删容器行做短 `SELECT ... FOR UPDATE` 条件认领，只有 `is_valid=False` 且 `restore_grace` 为空或 source 相同才写入/复用。同一 source 已存在时复用原 `until`/`granted_at`，不刷新；不同 source 不得覆盖，按冲突/复核处理。重复请求/轮询/真实恢复重试在看到同一 source 时只读返回/继续既有恢复流程，MUST NOT 重算宽限。`requires_choice` 只读阶段、取消、创建前失败不写 `restore_grace`，因此不消耗宽限。
- **生效与恢复**：新实例真实路径/测量继续走正常磁盘链路；`restore_grace` 不替代测量，不把未知当 0。宽限有效时统一冻结入口不得暂停、通知超限或升级删除；宽限结束按标准策略使用新实例有效测量和硬阈值。若已有冻结行，保留其 `first_frozen_at`/累计/既有 deferral 按 Q72；不得用恢复清零。机器不可用补偿只累加到 `restore_grace.deferral_seconds` 的授予后窗口，不套旧冻结累计；没有冻结行时不创建假冻结。
- **手工新启用无特例**：`POST /set_long_term_container` 非长期→长期仍执行硬阈值门禁，超限拒绝，不自动授恢复宽限。恢复仅对原长期标记走上述静默宽限。
- `restore_container_record` 同时清空旧 `runtime_transition`/`runtime_action_binding`，避免旧实例在途动作污染新实例；不清理或批量改写旧目录对象、快照或清理记录。产物清理失败时容器已恢复/宽限已消费，只能报告失败/部分完成，不得报告完整成功或刷新宽限。

**后续新增入口**：任何直接写 `long_term_containers` 的新代码必须先调用同一策略服务或明确登记为迁移/修复脚本；不得绕过 `set_long_term_container`/恢复预检直接 `add`。`repositories.long_term_container_repo.add` 保持低层原语语义，不承担策略；策略集中在门户/策略服务。

**稳定 offline**：启用时若状态为终态 `offline`、机器可达且非维护、业务路径测量有效且新鲜、低于硬阈值，仍允许；若无法取得有效测量则明确拒绝。取消时稳定 `offline` 允许，不额外要求磁盘测量。路径 `unresolved` 本身不阻断同一业务路径上的有效测量。由此保留旧允许的 offline 语义，同时不把“离线”当作安全假定。

### 7. 持久化、迁移与兼容

- 迁移文件建议 `migrations/2026-10_long_term_transition_guard.sql`：给 `containers` 增加三个可空列 `runtime_transition`（VARCHAR(24) NULL）、`runtime_action_binding`（JSON NULL）和 `restore_grace`（JSON NULL），不设 server default，不据此回填旧行；附带可重复执行的列存在检查。**不新增** `runtime_transition_at`、拆散的 `node_epoch/generation/seq` 列、假冻结行或只为宽限的第二张表。
- `__init__._ensure_container_lifecycle_schema`（或现有容器自愈入口）增加同样的幂等补列，供开发/测试和漏迁移兜底；列名、类型、默认可空必须与模型和迁移一致。
- `repositories/containers_repo.update_container` 把三个字段加入 allowed/显式清空规则；`restore_container_record` 清空旧动作绑定，并在恢复事务中写 `restore_grace`/长期标记；不得用通用 None 过滤丢掉宽限 JSON。
- 旧行三个字段为 NULL，意味着“没有未确认动作/恢复宽限证据”，不是“已确认 online/已冻结”。不会因迁移自动放开或收紧某个旧行的磁盘/长期标记。
- 不新增表、不新增长期表字段、不改变 `LongTermContainer` 主键/配额/审计字段；固定 8 字段资格 DTO 不因动作引用或恢复宽限扩张。

### 8. 读取面与 Web 契约

- 定义唯一的 `LongTermEligibility` 嵌套模型（8 个字段、精确类型、禁止额外字段），评估器返回该模型或等价的 `model_dump()`；服务层 `container_detail_information`/`container_bref_information` 与 API 层 `ContainerDetailInformation`/`ContainerBriefInformation` 都复用它，避免 Pydantic 双层模型把字段静默丢弃或两处类型漂移。
- detail 和 list 使用同一次评估函数、同一 `now`；不得一个读 `disk_usage` 百分比、另一个读新门禁。
- `evaluated_at` 用 UTC RFC3339（带 `Z`）；`disk_measured_at` 由真实测量时间转换，数据库 naive UTC 显式补 UTC，不输出本地时间。
- 旧字段保留，避免现有 Web 解析崩；但旧 `long_term_container_can_enable` 不再是完整授权。Web 变更必须使用 `long_term_eligibility.can_enable/can_disable` 与 reason 渲染，不再自行用 `disk_total_gb/disk_limit_gb` 推断服务端是否允许。
- 不改变 `SetLongTermContainerResponse` 的既有字段集合；成功后的最新资格可由 detail/brief 重新读取，避免把只读 DTO 复制成写响应契约。
- 鉴权仍沿用现有 FastAPI 依赖（`container:operation`、`container:root`、机器归属校验）；新门禁只增加业务拒绝原因，不放宽、不改写既有权限与账号字段。
- `long_term_eligibility` 永远不写数据库；相同输入和同一 `now` 可重算，不做缓存或旁路状态。

### 9. 审计、冻结与配额边界

- 成功审计：只在长期标记实际新增/删除时写；no-op 不写成功审计。
- 失败审计：实际切换被门禁拒绝时写，至少包含 `container_id`、目标值、稳定 reason 和评估依据（不含敏感信息）；恢复失败沿用 `CREATE_CONTAINER` 的 trigger=resurrect 失败审计。
- 动作引用终结：匹配的 failed/superseded、方向成功或受控 `stale_node_epoch` 重建写可检索诊断，包含 action_ref/phase/原因，但不冒充动作成功或长期成功审计；failed 不产生容器 failed 状态。
- 冻结表边界：普通长期启用/取消和 no-op 不调用 `upsert_first_frozen`、`set_grace`、`clear_grace`、`reset`、`add_deferral_seconds`，既有 `first_frozen_at`/`grace_until`/`deferral_seconds` 不变。恢复长期快照只写 `containers.restore_grace`，不创建冻结行、不伪造 `first_frozen_at`、不调用 `set_grace`；现有冻结行原样保留。
- 恢复宽限消费：统一冻结入口把 `effective_restore_grace_until(container)` 与既有 `effective_grace_until(freeze_state)` 一起判断；任一未到期则不暂停/通知/升级。机器不可用补偿只累加 `restore_grace.deferral_seconds` 的授予后窗口，不套旧冻结累计；宽限结束用新实例有效测量按标准策略处理。
- 配额：继续 root 用户计数、`container.long_term_limit` 配置、现有 `long_term_limit_reached` 文案与 used/limit。恢复长期快照的配额失败仍在 Node 调用前，保持现有测试语义。
- 不删除遗留 `freeze_state` 行；取消长期后磁盘调度按既有“非长期跳过响应”逻辑处理，遗留行只影响诊断，不授权任何动作。

### 10. 被否决的替代方案

- **只靠 Web 的 `isDiskOverLimit`/按钮禁用**：可绕过，且旧页面与新页面容易不一致；服务端必须裁决。
- **用 `freeze_state` 行存在作为取消门禁**：会永久挡住已确认解冻的容器，正是用户明确禁止的行为。
- **用 `disk_checked_at` 当作测量时间**：该时间只表示 Ctrl 收到/写入，旧目录/缓存样本也会刷新，不能证明可信。
- **null 当 0、缺样本放行**：会把未知用量伪装成安全；本变更明确拒绝。
- **新增长期资格表/缓存表**：资格是可重算的只读派生值，新增表会制造第二事实源；本次只加动作绑定/恢复宽限字段。
- **持有数据库行锁跨越 Node 创建/SMTP**：事务时间不可控；恢复在创建后的短事务中原子写长期标记+`restore_grace`，不把 Node 调用包进长事务。
- **为恢复宽限伪造冻结行或 `first_frozen_at`**：会把“宽限”伪装成“已冻结”，污染 Q72 累计；改用容器行独立 `restore_grace`。
- **为恢复宽限增加确认框/token/临时短期/Node preflight 端点**：用户已要求静默宽恕并恢复；只用一次持久化宽限字段，不新增交互或 API。
- **给运行过渡加自动 TTL 放行**：会在仍可能冻结/未解冻时解除长期保护；改用精确 action_ref 终结、方向成功或受控核对。
- **仅用 `runtime_transition_at <= 接收时间` 做跨动作隔离**：时间只能证明接收先后，不能证明是哪一个 Node 动作；改用精确 action_ref + 终结 phase + 当前链路代际。
- **用 Node action_ref 做跨进程删除授权**：action_ref 只是 pause/unpause 的局部动作关联，不是 Q70 的全局对象删除身份。
- **宣称 Q67/Q70 已修**：跨容器配额并发和跨进程动作代际都需要独立协议/锁设计，本变更不涉及。

## Risks / Trade-offs

- [旧 Node/旧 gate 未部署导致启用全部被拒] → 这是预期的 fail-closed；部署顺序先 gate、再 Node、再本变更。运维应把 `can_enable=false` 的 `disk_sample_untrusted` 当部署状态检查，不得回退成 0 或关闭门禁。
- [稳定 offline 容器因测量过期/路径不一致无法启用] → 保留状态语义但拒绝无效测量；用户可先保持在线取得新测量，不能静默假定安全。路径 `unresolved` 本身不拒绝同路径有效测量。
- [运行过渡字段因 WSS 长时间缺失而保留] → 机器不可达/未知本身会阻断切换；WSS 恢复后的方向终态或精确 ref 终结可收敛。没有 TTL 自动放行，避免把未确认当完成。
- [动作先写过渡后 Node 失败，短暂阻断长期切换] → 匹配 ref 的 failed 会结束过渡且不把容器写成 failed；这比在 DB 没记录时让切换穿过更安全。若数据库写失败，动作直接失败且不调用 Node。
- [新 Node 的 pause 失败但实际 online] → 精确 ref 的 `failed` 结束过渡，容器保持 online，长期取消可按稳定状态继续；不再等待无意义的 pausing 清理。
- [旧 Node 没有 action_ref/last_action] → 只能靠方向成功或同步 HTTP 明确失败解除；反向 online 不能推断 pause_failed，保持 unconfirmed 安全阻断。部署说明必须把旧 Node 覆盖率列为前置条件，不能承诺旧版本同等的可恢复性。
- [ack 丢失或早到 WSS 终结] → 早到终结可在进程内有界暂存，回执到达精确匹配后应用；回执丢失/进程重启保持未确认，不伪造成完成。Node epoch 变化后的受控重建只标 superseded，不伪造成功。
- [没有可观察的新 epoch/终结记录] → 当前线路只通过 action_ref/last_action 暴露 epoch；若没有新动作或状态证据，不能仅凭时间推断 epoch 已变化，保持 unconfirmed 安全阻断，等待新证据或人工核对，不自动放行。
- [superseded 与新动作绑定之间的窄窗口] → 旧绑定结束后，新动作必须写入自己的过渡/ref；窗口内的长期切换仍受当前实际状态与行锁约束，不宣称 Q70 级端到端原子。
- [Q67 配额并发仍可能多插一个长期标记] → 保留现有计数语义并明确不修；需要独立的用户级锁/唯一配额约束变更。
- [Q70 下 Node 已受理的动作与本地长期切换交错] → 条件写、行锁和运行过渡只缩小窗口；端到端动作代际仍由 Q70 负责。
- [旧 Web 仍按旧字段自行判断] → 服务端仍会拒绝，旧 UI 可能显示可点但收到 409；Web 变更必须迁移到新 DTO，服务端不作为绕过路径。
- [恢复长期快照被误加磁盘/身份门禁] → 按路径+配额+长期标记+一次静默宽限恢复，不用 inode 拒绝、不强制短期；宽限内不立即冻结，到期后标准硬阈值处理。恢复成功/幂等/普通快照用例保留。
- [运行过渡格式/历史数据] → 新列可空，旧行为不受影响；只接受 `pausing`/`unpausing`，未知 phase/字符串按未确认保守处理。

## Migration Plan

1. **前置依赖**：先在隔离库/测试环境落地 `gate-disk-check-on-mount-identity` 的 Ctrl 测量/路径字段、统一有效谓词和接收规则；确认旧 Node 样本显示测量 `unverified`，不会驱动磁盘动作。再逐机部署 Node 路径/测量协议，核对业务路径回填覆盖率、真实测量年龄和 unresolved 诊断，不核对 dev/inode。
2. **迁移**：执行新增两列（`runtime_transition` + `runtime_action_binding` JSON）的迁移或让应用启动自愈补齐；验证重复执行无错、旧行两列为 NULL、绑定 JSON 不被回填、不把旧 `disk_checked_at` 当测量时间。开发/测试 SQLite 由模型 `create_all` 建表。
3. **部署 Ctrl**：先以只读方式检查 detail/brief 的 `long_term_eligibility`；在旧样本/旧 Node 未覆盖时确认 `can_enable=false` 且 `disable` 仍按运行状态工作。逐机核对新 Node 是否返回 action_ref/last_action，记录旧版本缺口。实际启用/取消先在隔离环境回放事故与边界用例。
4. **联合验收**：与 Web 变更核对完全一致的字段/原因；与 Node 变更核对 action_ref/last_action、终态/过渡帧和 failed pending 收敛；与 `unify-disk-freeze-workflow` 核对绑定阶段。生产不执行真实删除/冻结演练。
5. **回滚**：保留新增列（旧代码忽略）；回滚本变更会恢复“暂停态可取消长期、无样本可启用”的旧风险，未核对 gate/Node 覆盖率前不应回滚门禁。回滚 Node 只应让新样本降级 unverified，不应删除列或绕过 Ctrl 门禁。

## Dependencies / Follow-ups

- **硬依赖** `gate-disk-check-on-mount-identity`：`disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation`、业务路径回填及统一测量有效谓词。未部署时缺测量按 `disk_sample_untrusted` 拒绝；不依赖目录身份字段。
- **硬依赖** Node 路径/测量协议（原 `verify-bind-mount-identity` 名称保留）：业务路径回填、测量状态/真实时间/测量路径与采样排序。未部署的旧 Node 样本缺真实测量时间时标测量未验证，不能当作目录身份缺失。
- **配套 Node 动作引用契约**：Node `guard-runtime-state-reconciliation`（或其同级变更）按本设计实现可选 `action_ref` 与 `last_action`；旧 Node 缺字段时按第 4.6 条安全降级，不承诺同等恢复能力。Ctrl 只消费，不修改 Node 仓库。
- **配套** Web `align-container-action-eligibility-and-recovery`：消费同一 `long_term_eligibility` 契约；不得增加同义字段或自行实现门禁。
- **配套** Node `guard-runtime-state-reconciliation`：修复 failed pending 永久优先、旧 reconcile 快照覆盖和 unpause 幂等；本变更只消费其终态/动作引用输出，不把事故中的 Node 行为宣称为已修。
- **恢复政策已决**：恢复原有长期资格执行相同硬超限规则，但实际恢复时静默授予一次宽限并恢复原长期标记；不增加确认 UI/token、不强制临时短期、无 Node preflight。宽限持久化在容器行 `restore_grace`，由统一冻结入口消费；`first_frozen_at`/累计按 Q72 保留。
- **Global 边界**：Q67 跨容器数量并发、Q70 跨进程动作代际不在本变更。归档时需把两个 delta 的新增字段/要求合并进对应主规格；本变更只写 change 目录。

## Source references

- [services/container_tasks.py](../../../services/container_tasks.py)：`set_long_term_container`、`unpause_container`、`resurrect_container`。
- [services/container_module/long_term.py](../../../services/container_module/long_term.py)：`_load_long_term_target`、`_ensure_long_term_capacity`、`_persist_long_term_state`、`_audit_long_term`。
- [services/container_module/restore.py](../../../services/container_module/restore.py)：`_load_restore_target`、`_ensure_restore_long_term_capacity`、`_restore_long_term_state`。
- [services/container_module/actions.py](../../../services/container_module/actions.py)：`_request_pause_action`、`_persist_paused_status`、`_grant_unpause_grace`。
- [services/container_module/node_comms_modules/snapshots.py](../../../services/container_module/node_comms_modules/snapshots.py)：`_NODE_STATUS_SKIP`、`_apply_container_status_entry`。
- [services/container_module/utils.py](../../../services/container_module/utils.py)：`build_long_term_container_state`。
- [services/container_module/information.py](../../../services/container_module/information.py)：detail/brief 组装。
- [services/container_module/pydantic_models.py](../../../services/container_module/pydantic_models.py)、[schemas/container.py](../../../schemas/container.py)：响应模型。
- [repositories/long_term_container_repo.py](../../../repositories/long_term_container_repo.py)、[repositories/containers_repo.py](../../../repositories/containers_repo.py)：长期标记与容器更新原语。
- [models/containers.py](../../../models/containers.py)、[models/long_term_container.py](../../../models/long_term_container.py)：持久化结构。
- 事故证据：`FuxiYu_Global/reports/sylvan-unpause-2026-10-17-ctrl.md`、`...-node.md`（只读参考，不写入产物）。
- 依赖变更：[gate-disk-check-on-mount-identity](../gate-disk-check-on-mount-identity/design.md)、[unify-disk-freeze-workflow](../unify-disk-freeze-workflow/design.md)；Node 侧 `FuxiYu_NodeKernel/openspec/changes/verify-bind-mount-identity/` 与 `guard-runtime-state-reconciliation`。
