# Proposal

## Why

2026-10-17 的 Sylvan（`containers.id=201`）事故暴露了长期容器的服务端门禁缺口：容器因磁盘硬超限被冻结后，用户于 18:43 将其转为非长期；该操作在冻结态下被放行，随后磁盘调度按“非长期”跳过响应，长期保护被解除。19:33 的两次 unpause 又暴露出 Node 缓存旧快照覆盖、失败 pending 长期优先的问题；Ctrl 曾以单行 CAS 复位，但被 WSS 快照在 15 秒内覆盖，最终只能靠 Node 重启清除 pending。当前代码仍未修复，且长期设置入口只校验配额和状态矩阵：暂停态可以取消长期，恢复长期快照只校验配额，详情/列表的磁盘超限判断仍依赖前端自行拼装。必须在更多 UI 入口接入前，把“能否启用/取消长期”统一为服务端权威判断。

## What Changes

- 新增一个服务端长期资格评估器，所有手工设置、恢复长期快照及后续同类新增标记入口共用；读取面统一返回只读 DTO `long_term_eligibility`，字段固定为 `can_enable`、`can_disable`、`enable_reason`、`disable_reason`、`evaluated_at`、`disk_total_bytes`、`disk_limit_bytes`、`disk_measured_at`，在容器 detail 与 brief 中同源返回。
- 实际启用长期（非长期 → 长期）MUST 同时通过：当前状态为已确认的稳定 `online`/`offline`、无未确认运行过渡、长期配额未满、机器 `max_disk_size_gb` 已配置、业务路径上的磁盘测量有效且未过期、`disk_total_bytes` 已知且低于磁盘硬阈值。测量缺失、未验证、过期、路径与样本不一致或限额缺失 MUST 明确拒绝，不得以 0 用量或 `disk_checked_at` 冒充可信样本。软阈值只提醒，不阻断启用。
- 实际取消长期（长期 → 非长期）MUST 只在已确认未冻结且状态守卫允许时执行：`paused`、`pausing`/`unpausing` 未确认、`failed`、`status_unknown`、主机离线/维护及其他不稳定状态 MUST NOT 取消。取消不新增磁盘超限或配额拒绝条件；`freeze_state` 行仍存在本身不是拒绝理由，已确认恢复 `online` 后不得被永久阻挡。
- 为 `pausing`/`unpausing` 增加本地动作绑定，消费 Node 可选 `action_ref` 与 `last_action`。只有精确 ref 的终结记录、或实际运行态方向成功才能结束过渡；`failed` 只结束动作、不把容器写成 failed，`unconfirmed`/`timed_out` 不按 TTL 放行。旧 Node 缺 ref 时只能依赖方向成功或同步明确失败，反向状态不能推断动作失败；明确此混合版本限制。
- 恢复长期快照执行与手工新启用相同的硬超限规则，但实际恢复时自动静默授予一次现有 `container.disk_freeze_grace_days` 时长的磁盘宽限并恢复原长期标记：不增加超限确认框、宽恕按钮、确认 token 或前端状态机，`requires_choice` 等只读阶段不消耗宽限。恢复仍按保留路径创建，不因旧 Docker/inode/缓存拒绝；新实例路径/测量走正常磁盘链路，宽限有效时不得立即暂停或升级，结束后按标准策略处理。宽限与长期标记必须在同一事务中先持久化再对调度可见；以 `deleted_id` 为稳定来源幂等，重复请求/轮询/重试不刷新 `restore_grace.until`；失败未恢复不消耗宽限。手工新启用仍无恢复特例。
- 同目标值的重复请求为纯幂等 no-op：不新增/删除标记、不新增审计、不改变冻结锚点 `first_frozen_at`、宽限 `grace_until`、`deferral_seconds` 或累计计时；实际切换仍必须阻断冻结态和磁盘超限。
- 事务内重读容器行、长期标记、状态、配额与可信样本，并用条件插入/条件删除缩小本地竞态；不宣称修复 Q67 的跨容器配额并发，也不宣称获得 Q70 的跨进程/跨 Node 原子性。
- 与 `unify-disk-freeze-workflow` 共享同一动作引用契约：冻结状态只把精确 ref 的失败/终结绑定到当前 `pause_request_seq`，WSS `online` 不等于 `pause_failed`；旧链路帧按当前 `link_generation` 丢弃。

**BREAKING**：手工新启用从此依赖路径/测量字段与统一有效谓词；缺少真实测量时间、机器限额或新鲜可信测量时返回 409，旧 Node 样本标测量未验证，不是“缺目录身份”。恢复长期快照会执行硬超限规则，但在真实恢复时自动静默授予一次宽限并恢复原长期标记；不因 inode/旧缓存拒绝，也不强制临时短期。旧 Node 缺 action_ref/last_action 时不能反推动作失败，只能安全阻断；依赖未部署期间旧自动化可能被拒绝。该拒绝是保守停用，不是“已经修复”。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-long-term-containers`：长期容器新增服务端资格策略、冻结态取消守卫、磁盘/配额启用门禁、恢复路径/配额/长期标记与静默恢复宽限、幂等 DTO 契约。
- `backend--table-containers`：新增 Ctrl 动作绑定字段、恢复宽限字段与可选 `action_ref`/`last_action` 消费规则；不改变固定资格 DTO、磁盘字段或冻结累计语义。

## Impact

涉及 `services/container_tasks.py`、`services/container_module/long_term.py`、`actions.py`、`restore.py`、`queries.py`、`information.py`、`pydantic_models.py`、`node_comms_modules/snapshots.py`、`repositories/long_term_container_repo.py`、`repositories/containers_repo.py`、`schemas/container.py`、`api/container_api.py`、`models/containers.py`、迁移与隔离测试。

配套但不属于本仓库写范围：Web 变更 `align-container-action-eligibility-and-recovery` 必须消费完全相同的 `long_term_eligibility` 契约；Node 变更 `guard-runtime-state-reconciliation` 负责实现可选 `action_ref`/`last_action` 并修复 failed pending 与旧快照覆盖。本变更在 Ctrl 侧定义并消费该跨仓契约，不修改 Node 仓库、不自动修复线上 Sylvan 行，不执行 SSH、生产操作、业务代码提交或 push。

依赖顺序：先落地 `gate-disk-check-on-mount-identity` 的 Ctrl 字段/路径接收/测量谓词，再逐机部署 Node 路径/测量协议与 action_ref/last_action，然后部署本变更；本变更不得把旧样本或旧 Node 缺 ref 当可用。`unify-disk-freeze-workflow` 同步消费同一 action_ref、路径测量与恢复宽限。Web 可先按契约渲染但服务端拒绝仍是最终裁决。Q67 的跨容器数量并发、Q70 的跨进程动作代际、Node `guard-runtime-state-reconciliation` 的缓存修复均不在本变更内。
