# Design

## Context

动机见 [proposal.md](proposal.md)。当前实现的关键事实：

- [services/container_module/long_term.py](../../../services/container_module/long_term.py) 的 `_load_long_term_target` 只调用 `ensure_container_operation_allowed(..., "set_long_term")`；`_ensure_long_term_capacity` 只校验 root 用户配额。`_persist_long_term_state` 用 `long_term_container_repo.add/remove` 落库，`_audit_long_term` 目前对同目标请求也会写成功审计。
- [services/container_module/operation_guard.py](../../../services/container_module/operation_guard.py) 的既有矩阵对 `set_long_term` 拒绝 `building/creating/starting/stopping/restarting/failed/host_offline/host_maintenance/status_unknown`，允许 `online/offline/paused`。本变更不重写该矩阵。
- [services/container_tasks.py](../../../services/container_tasks.py) 的 `set_long_term_container` 顺序是“读目标 → 仅新增时配额 → 落库 → 审计”，各步使用独立会话，没有在写入前统一重读，也没有磁盘判断。
- 容器行已有 [models/containers.py](../../../models/containers.py) 的 `disk_total_bytes`、`disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_checked_at` 与 `bind_mount_path`；机器行已有 `max_disk_size_gb`。磁盘硬限制百分比由 [services/settings_tasks.py](../../../services/settings_tasks.py) 的 `get_container_disk_hard_limit_percent()` 提供，调度侧 [schedulers/container_disk_check_task.py](../../../schedulers/container_disk_check_task.py) 也使用同一上限口径。
- 冻结仓储 [repositories/container_disk_freeze_state_repo.py](../../../repositories/container_disk_freeze_state_repo.py) 的 `set_grace` 只在已有冻结行时可用；`_grant_unpause_grace` 在无冻结行时直接返回。恢复路径 [services/container_module/restore.py](../../../services/container_module/restore.py) 的 `_restore_long_term_state` 只恢复长期标记，不写宽限。
- Web 当前已能从既有响应读取 `is_long_term`、`long_term_container_can_enable`、`long_term_container_blocked_user_ids`、`long_term_container_remaining_by_user`、`disk_usage_percent`（列表）或 `disk_usage.usage_percent`（详情）以及 `effective_status`。本变更不新增响应字段。

本设计只写 Ctrl 的规划文档；Web 的 `align-container-action-eligibility-and-recovery` 使用既有字段，Node 不参与本守卫。

## Goals / Non-Goals

**Goals:**

- 用一个小型服务端静态守卫覆盖手工启用/取消长期，复用现有权限、配额、状态和磁盘数据。
- 满配额或已知磁盘硬超限时阻止启用；实际冻结时阻止取消；解除冻结后不因遗留冻结行永久阻止取消。
- 同目标值无副作用；实际切换前重读当前事实；保留 Q72 冻结累计语义。
- 不新增表、列、库表变更、资格响应对象或 Node 协议前置。

**Non-Goals:**

- 不实现恢复宽限的新承载方式，不伪造冻结行。现有仓储无法表达“无冻结行时的恢复宽限”，该缺口独立上报。
- 不增加测量新鲜度、路径一致性、inode 或 Docker 对象身份判断；业务只用 `bind_mount_path`，inode 校正属于 Node 路径维护。
- 不修复 Q67 的跨容器配额并发，也不声称获得 Q70 的跨进程动作原子性。
- 不修改 Web/Node 仓库，不修改正式 `openspec/specs/` 或 archive。

## Decisions

### 1. 一个按方向判断的静态守卫

在长期容器族增加内部守卫函数（建议 `ensure_long_term_switch_allowed(container, bindings, existing, target, machine, session)`），由 `set_long_term_container` 在实际写入前调用。顺序固定，便于测试：

1. 读取有效容器；不存在返回既有 `container_not_found`。
2. 用 `_derive_effective_status` 得到实际状态，调用既有 `ensure_container_operation_allowed(status, "set_long_term")`。这一步保持原矩阵：`failed`、不稳定、主机离线/维护、状态未知仍拒绝；`online`、`offline`、`paused` 仍可进入后续判断。
3. 若 `existing == target`，返回当前状态，不再执行配额、磁盘或取消方向规则，也不写库和成功审计。
4. 目标为启用（`target=True`）：
   - 用现有 root 用户绑定和 `long_term_container_repo.count_by_user` 在同一会话内校验配置的长期容器上限（`settings_tasks.get_long_term_container_limit()`）；已满抛出既有 `long_term_limit_reached`，消息保留 used/limit。
   - 取机器 `max_disk_size_gb`；若 `> 0`，计算 `limit_bytes = int(max_disk_size_gb * 1024**3)`，取 `hard_percent = get_container_disk_hard_limit_percent()`。只有当 `disk_total_bytes is not None` 且 `disk_total_bytes * 100 >= limit_bytes * hard_percent` 时抛出 `disk_usage_over_limit`。`disk_total_bytes` 为空、机器上限 `<= 0` 时不因该缺失拒绝；软阈值不参与。
5. 目标为取消（`target=False`）：
   - 若实际状态为 `paused`，抛出既有 `container_paused`。不查询 `container_disk_freeze_state` 行；`online`/`offline` 即使仍有冻结行也允许继续。
6. 通过后用现有 `long_term_container_repo.add/remove` 在同一会话写入。实际新增或删除才写成功审计；失败路径保留 API 层既有失败审计。

`paused` 状态下的启用仍按既有矩阵允许（矩阵没有把 set_long_term 放进 paused 的拒绝集）。本变更只增加“冻结时禁止取消”，不扩大为“冻结时禁止一切长期操作”。

磁盘判断只使用当前持久化字节值和机器上限，不增加 `disk_checked_at` 新鲜度、路径一致性或测量字段。这样守卫不依赖磁盘采集协议，也不因旧样本缺失把所有人的长期入口变灰；采集滞后时可能放行，随后由既有磁盘调度处理，这是有意的静态边界。

### 2. 同会话重读与幂等

`set_long_term_container` 改为一个 `session_scope()`：

- 在同一会话读取容器、绑定、长期标记、机器（通过现有 `machine_repo`/`containers_repo` 原语），完成守卫判断和 `add/remove`，一次提交。
- 配额计数需要与写入同会话时，给现有 `_ensure_long_term_capacity_for_users` 增加可选 `session` 参数，或抽出同语义的只读 helper；不新增表或条件写原语。
- 提交后重新读取当前长期状态，复用 `build_long_term_container_state` 生成响应。
- 若重读发现标记已等于目标，走 no-op；若状态已变为 `paused`，取消按新状态拒绝。这样缩小同一容器在请求内的竞态窗口。
- 不引入新的并发拒绝原因，也不宣称跨容器配额并发已修复。不同容器同时占用最后一个名额仍可能都通过 count 检查，这是既有 Q67 边界；本变更不新增用户级锁。

### 3. 权限、状态与错误契约不变

- 路由继续使用既有 `container:operation`、`container:root`、`require_machine_of_container` 依赖；守卫不接收客户端提交的权限或资格字段。
- 既有原因继续使用：`container_busy`、`container_failed`、`container_paused`、`container_host_offline`、`container_host_maintenance`、`container_status_unknown`、`long_term_limit_reached`。
- 新增唯一原因 `disk_usage_over_limit`，在 [api/container_api.py](../../../api/container_api.py) 的 `REASON_STATUS_MAP` 映射 409。它只表达“已知用量达到硬限制”，不替换配额原因。
- 权限 403、容器不存在 404、入参 400、主机不可用 503 全部沿用现有映射。成功审计只在标记实际变化时写；失败审计记录 reason，不改变标记。

### 4. 恢复长期快照与恢复宽限的表示缺口

恢复长期快照不是手工启用：它继续走现有 `_ensure_restore_long_term_capacity` 的 root 用户配额预检和 `_restore_long_term_state` 的标记恢复，不额外套用本守卫的磁盘启用门禁，也不新增 Node preflight。恢复路径的配额、路径、机器、镜像和创建错误保持原语义。

用户已确认的“恢复原长期资格时静默授予一次既有时长宽限”政策保留，但现有仓储没有可复用的无冻结行承载位置：

- [models/container_disk_freeze_state.py](../../../models/container_disk_freeze_state.py) 第 9、21-25 行：类注释“记录存在 = 容器当前处于冻结升级倒计时”，`first_frozen_at` 为 `nullable=False`，`grace_until` 为 `nullable=True`。
- [repositories/container_disk_freeze_state_repo.py](../../../repositories/container_disk_freeze_state_repo.py) 第 55-63 行：`set_grace` 文档是“设置宽限期；无冻结记录时返回 False。”，实现为 `row = get(...); if row is None: return False`。
- [services/container_module/actions.py](../../../services/container_module/actions.py) 第 105-116 行：`_grant_unpause_grace` 先 `get` 冻结行，`if freeze_state is None: return`，不会为无行容器创建宽限。
- [services/container_module/restore.py](../../../services/container_module/restore.py) 第 566-578 行：`_restore_long_term_state` 只调用 `_persist_long_term_state(container_id, True, existing, operator_user_id)`，没有宽限写入点。
- [services/container_module/deleted_containers.py](../../../services/container_module/deleted_containers.py) 第 134-157 行：删除快照保存了 `is_long_term`，但没有 `grace_until` 或等效宽限字段。

因此：无冻结行时，要么新建冻结行（会伪造 `first_frozen_at` 并启动冻结倒计时/Q72 累计），要么新增容器承载字段；前者被明确禁止，后者已被“直接删”收敛移除。本变更不实现恢复宽限，也不声称已完成；将该具体表示缺口上报父代理，作为独立后续决策。该缺口与静态切换守卫解耦：守卫不读取、不写入、也不要求先解决恢复宽限，不能把它变成整个 guard 的前置。

### 5. 边界与替代方案

- **不新增结构**：不需要新列、库表变更、资格对象或 Node 字段。上一版的这些要求在本次直接删除，而不是改成 JSON/日志承载同一套伪状态。
- **不用冻结行做取消门禁**：行存在只说明曾经进入冻结倒计时，不能证明当前仍冻结；取消看实际 `effective_status`。这样已确认解冻后不会被永久锁死。
- **不把未知磁盘当 0 或当超限**：未知就是未知，不作为拒绝理由；只有已知用量达到硬限制才拒绝。
- **不引入测量新鲜度/路径门禁**：那会把磁盘采集协议变成长期设置的前置；本变更只读取已有字节数。
- **不改权限/状态矩阵**：不因为去掉资格对象就顺手删掉原 403/状态拒绝规则；方向规则只叠加在矩阵之后。
- **不把恢复宽限塞进本守卫**：无冻结行时现有仓储无法表达，新增结构又被删除；只上报缺口。

## Risks / Trade-offs

- **磁盘样本滞后** → 守卫用当前 `disk_total_bytes` 判断，采集未更新时可能放行；随后既有磁盘调度会按同一上限处理。不增加新鲜度门禁是避免把采集故障变成长期入口全阻。
- **Q67 跨容器配额并发** → 同一 root 用户的两个容器可能同时通过最后一个名额；本变更只缩小同容器请求内窗口，不声称修复。
- **同容器并发** → 单会话重读降低旧快照概率，但没有新增条件写/行锁原语；极端交错仍可能以最后一次提交为准，不宣称 Q70。
- **冻结时仍可启用** → 既有矩阵允许 `paused` 下 set_long_term；本变更只按用户要求阻止冻结时取消。若产品要禁止冻结时启用，应另行决定，不在本次偷偷扩大。
- **恢复宽限未实现** → 政策保留但无现有承载；本变更明确上报缺口，不用假冻结行或新列冒充完成。
- **前端静态展示可能落后** → Web 使用既有字段，后端 409/403 仍是最终裁决；不新增资格对象。

## Rollout / Rollback

1. 在隔离测试中实现守卫与单会话重读，先跑长期配额、磁盘、冻结取消、同目标 no-op、Q72 字段不变和恢复配额回归。
2. 不需要数据回填或库表变更；部署只改服务代码与原因映射。
3. Web 可独立按既有字段上线，无先后硬依赖；Node 无需改动。
4. 回滚只回滚服务代码。由于没有新增列/表，无需清理结构；已写入的长期标记和既有冻结行保持原样。
5. 验收时对比变更前后的模型/数据库结构差异，确认没有新增结构。

## Dependencies / Follow-ups

- 无新增 Node、磁盘采集或 Web 契约前置；磁盘字节与机器上限是现有字段。
- Web `align-container-action-eligibility-and-recovery` 使用既有 `is_long_term`、配额和磁盘展示字段，不消费新对象。
- 恢复宽限的承载缺口上报父代理；在独立决策前不在本变更添加结构，也不宣称恢复宽限已完成。
- 归档时把本 delta 合并进 `backend--table-long-term-containers` 主规格；本变更只写 change 目录。

## Source references

- [services/container_module/long_term.py](../../../services/container_module/long_term.py)：`_load_long_term_target`、`_ensure_long_term_capacity_for_users`、`_persist_long_term_state`、`_audit_long_term`。
- [services/container_tasks.py](../../../services/container_tasks.py)：`set_long_term_container`、`resurrect_container`。
- [services/container_module/operation_guard.py](../../../services/container_module/operation_guard.py)：`CONTAINER_OPERATION_DENY_MATRIX`、`ensure_container_operation_allowed`。
- [services/container_module/information.py](../../../services/container_module/information.py)：`_disk_limit_bytes`、`_build_brief_disk_usage`。
- [schedulers/container_disk_check_task.py](../../../schedulers/container_disk_check_task.py)：`_usage_from_db`、`_evaluate_limits`。
- [models/container_disk_freeze_state.py](../../../models/container_disk_freeze_state.py)、[repositories/container_disk_freeze_state_repo.py](../../../repositories/container_disk_freeze_state_repo.py)：冻结行与 `grace_until` 的既有边界。
- [services/container_module/actions.py](../../../services/container_module/actions.py)：`_grant_unpause_grace`。
- [services/container_module/restore.py](../../../services/container_module/restore.py)：`_ensure_restore_long_term_capacity`、`_restore_long_term_state`。
- [repositories/long_term_container_repo.py](../../../repositories/long_term_container_repo.py)：`add`、`remove`、`count_by_user`。
- [api/container_api.py](../../../api/container_api.py)：`REASON_STATUS_MAP`、`set_long_term_container_api`。
