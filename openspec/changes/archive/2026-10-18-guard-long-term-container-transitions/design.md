# Design

## Context

动机见 [proposal.md](proposal.md)。当前实现的关键事实：

- [services/container_module/long_term.py](../../../services/container_module/long_term.py) 的 `_load_long_term_target` 只调用 `ensure_container_operation_allowed(..., "set_long_term")`；`_ensure_long_term_capacity` 只校验 root 用户配额。`_persist_long_term_state` 用 `long_term_container_repo.add/remove` 落库，`_audit_long_term` 目前对同目标请求也会写成功审计。
- [services/container_module/operation_guard.py](../../../services/container_module/operation_guard.py) 的既有矩阵对 `set_long_term` 拒绝 `building/creating/starting/stopping/restarting/failed/host_offline/host_maintenance/status_unknown`，允许 `online/offline/paused`。本变更不重写该矩阵。
- [services/container_tasks.py](../../../services/container_tasks.py) 的 `set_long_term_container` 顺序是“读目标 → 仅新增时配额 → 落库 → 审计”，各步使用独立会话，没有在写入前统一重读，也没有磁盘判断。
- 容器行已有 [models/containers.py](../../../models/containers.py) 的 `disk_total_bytes`、`disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_checked_at` 与 `bind_mount_path`；机器行已有 `max_disk_size_gb`。磁盘硬限制百分比由 [services/settings_tasks.py](../../../services/settings_tasks.py) 的 `get_container_disk_hard_limit_percent()` 提供，调度侧 [schedulers/container_disk_check_task.py](../../../schedulers/container_disk_check_task.py) 也使用同一上限口径。
- 冻结仓储 [repositories/container_disk_freeze_state_repo.py](../../../repositories/container_disk_freeze_state_repo.py) 的 `get(..., include_invalid=True)` 可直接取到软删容器的冻结行；`reset`（第 77-85 行）取行后 `session.delete(row)` 并 flush，无行返回 `False`。`set_grace` 只在已有冻结行时可用；[services/container_module/actions.py](../../../services/container_module/actions.py) 的 `_grant_unpause_grace` 在无冻结行时直接返回，不是恢复宽限入口。
- 通用软删入口 [repositories/containers_repo.py](../../../repositories/containers_repo.py) 的 `delete_container`（第 258-279 行）只置 `is_valid=false`、写 `deleted_*` 并 flush，不删除容器行。`container_disk_freeze_state.container_id` 虽有 `ondelete=CASCADE`，但软删不会触发外键级联，冻结行会原样留下。
- 当前删除入口只有实际软删的 API/清理路径 [services/container_module/deletion.py](../../../services/container_module/deletion.py) 的 `_persist_container_deletion`（第 65-71 行，经 [services/container_tasks.py](../../../services/container_tasks.py) 的 `remove_container` 调用）。Node 名称消失线索在 `guard-container-vanish-deletion` 后只标待核实、不再软删，因此不经过该函数。`session_scope` 成功才 commit、异常 rollback（[extensions.py](../../../extensions.py) 第 106-123 行）。
- 恢复路径 [services/container_module/creation.py](../../../services/container_module/creation.py) 的 `_persist_container_record` 在 `reuse_container_id` 时调用 `restore_container_record` 复活原软删行（第 174-181 行）；[services/container_module/restore.py](../../../services/container_module/restore.py) 的 `_restore_long_term_state` 只恢复长期标记（第 566-578 行），不读写冻结状态或宽限。删除快照只保存 `is_long_term`，不保存冻结字段（[services/container_module/deleted_containers.py](../../../services/container_module/deleted_containers.py) 第 132-154 行）。
- Web 当前已能从既有响应读取 `is_long_term`、`long_term_container_can_enable`、`long_term_container_blocked_user_ids`、`long_term_container_remaining_by_user`、`disk_usage_percent`（列表）或 `disk_usage.usage_percent`（详情）以及 `effective_status`。本变更不新增响应字段。

本设计只写 Ctrl 的规划文档；Web 的 `align-container-action-eligibility-and-recovery` 使用既有字段，Node 不参与本守卫。

## Goals / Non-Goals

**Goals:**

- 用一个小型服务端静态守卫覆盖手工启用/取消长期，复用现有权限、配额、状态和磁盘数据。
- 满配额或已知磁盘硬超限时阻止启用；实际冻结时阻止取消；解除冻结后不因遗留冻结行永久阻止取消。
- 同目标值无副作用；实际切换前重读当前事实；保留 Q72 对同一未删除容器的累计语义。
- 删除容器时在同一事务清除冻结类状态；恢复等同新建，不继承旧冻结状态或授予恢复宽限。
- 不新增表、列、库表变更、资格响应对象或 Node 协议前置。

**Non-Goals:**

- 不实现或保留任何恢复宽限政策；不为无冻结行的恢复创建冻结行、宽限字段或等效 JSON 状态。
- 不为历史已软删容器回填或后台清理遗留冻结行；不在恢复侧增加补偿清理，不新增迁移。
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

### 4. 删除重置冻结状态，恢复等同新建

Q74 已决，覆盖此前恢复宽限政策：恢复容器等同新建，无冻结记录即保持无记录；删除容器时在同一事务清除冻结类状态。

#### 4.1 删除入口在同一事务复用既有 reset

位置选在通用软删除函数 `containers_repo.delete_container`，不放在 service wrapper、restore 旁路或新的删除 helper：

- 正常 API/清理删除（`remove_container` → `_persist_container_deletion`）调用该函数；在这层加一次 reset 即可覆盖实际软删除入口。名称消失线索只标待核实、不调用该函数，故不重置冻结行。
- 两个调用方都已经在 `session_scope()` 内传入显式 session，`session_scope` 成功才 commit、异常 rollback；因此软删字段与冻结行删除共享同一事务。
- 在设置软删字段后调用既有 `container_disk_freeze_state_repo.reset(container_id, session=session)`；`reset` 用 `include_invalid=True` 取行、`session.delete(row)`、flush。无行返回 `False`，不视为删除失败。
- 删除失败、reset/flush 异常或 commit 异常都由外层 rollback，容器行与冻结行保持删除前状态，不会出现“软删已提交但冻结行未清”或相反的半完成。
- 重复调用 `delete_container` 时，`get_by_id(..., include_invalid=True)` 仍能找到已软删行；冻结行已不存在时 reset 返回 `False`，函数仍按既有语义成功返回。本要求以该通用软删函数为验收边界；API 对已软删容器的再次调用仍受既有加载/权限语义约束，不新增 API 幂等层。
- 容器不存在时保持既有 `False` 返回，不额外清理孤儿冻结行；不在删除路径之外做后台修复或迁移。

#### 4.2 恢复路径不读取、不复制、不授予冻结状态

恢复长期快照继续走既有 `_ensure_restore_long_term_capacity` 的 root 配额预检、`Create_container` → `restore_container_record` 的原行复活和 `_restore_long_term_state` 的长期标记恢复；不额外套用本守卫的磁盘启用门禁，也不新增 Node preflight。恢复路径：

- 不查询、不复制删除前的冻结状态，不调用 `set_grace`，不为表示宽限新建冻结行。
- 删除已按 4.1 清除冻结行的容器，恢复后同一 `container_id` 没有冻结记录；无冻结记录时就保持无记录。
- 不改变 Q72 对同一未删除容器的累计口径；真正删除终止旧冻结周期，恢复新建不是旧周期的续期，之后只有实际冻结才建立新锚点。
- 不新增恢复侧补偿清理。历史已软删且遗留冻结行的记录不在本次回填范围；本变更不迁移、不后台修复，也不把该清理塞进恢复路径。

### 5. 边界与替代方案

- **不新增结构**：不需要新列、库表变更、资格对象或 Node 字段。上一版的这些要求在本次直接删除，而不是改成 JSON/日志承载同一套伪状态。
- **不用冻结行做取消门禁**：行存在只说明曾经进入冻结倒计时，不能证明当前仍冻结；取消看实际 `effective_status`。这样已确认解冻后不会被永久锁死。
- **不把未知磁盘当 0 或当超限**：未知就是未知，不作为拒绝理由；只有已知用量达到硬限制才拒绝。
- **不引入测量新鲜度/路径门禁**：那会把磁盘采集协议变成长期设置的前置；本变更只读取已有字节数。
- **不改权限/状态矩阵**：不因为去掉资格对象就顺手删掉原 403/状态拒绝规则；方向规则只叠加在矩阵之后。
- **不把删除重置做成旁路**：只在通用 `delete_container` 内复用既有 `reset`；不新增删除 wrapper、恢复补偿、后台任务、字段/JSON 或迁移。历史遗留行不回填。
- **恢复不做补偿清理**：删除已清行的容器恢复后自然没有冻结记录；恢复路径不读取、不复制、不授予冻结状态或宽限。

## Risks / Trade-offs

- **磁盘样本滞后** → 守卫用当前 `disk_total_bytes` 判断，采集未更新时可能放行；随后既有磁盘调度会按同一上限处理。不增加新鲜度门禁是避免把采集故障变成长期入口全阻。
- **Q67 跨容器配额并发** → 同一 root 用户的两个容器可能同时通过最后一个名额；本变更只缩小同容器请求内窗口，不声称修复。
- **同容器并发** → 单会话重读降低旧快照概率，但没有新增条件写/行锁原语；极端交错仍可能以最后一次提交为准，不宣称 Q70。
- **冻结时仍可启用** → 既有矩阵允许 `paused` 下 set_long_term；本变更只按用户要求阻止冻结时取消。若产品要禁止冻结时启用，应另行决定，不在本次偷偷扩大。
- **删除重置影响全部实际删除调用方** → 这是有意的：API/清理删除都应清冻结行；名称消失线索只标待核实、不再删除，因此不在此列。直接调用 `delete_container` 的测试 fixture 也会看到冻结行消失，验收需显式建行后删除断言。
- **历史遗留行不修复** → 本变更只覆盖新删除；禁止后台修复/迁移，故既有已软删容器的遗留冻结行不回填。验收以“新删除 → 恢复”链路为准，不宣称历史数据已清。
- **前端静态展示可能落后** → Web 使用既有字段，后端 409/403 仍是最终裁决；不新增资格对象。

## Rollout / Rollback

1. 在隔离测试中实现守卫、单会话重读与删除重置，先跑长期配额、磁盘、冻结取消、同目标 no-op、Q72 字段不变、删除清行、删除回滚、重复删除、恢复配额与恢复不继承回归。
2. 不需要数据回填或库表变更；部署只改服务代码、原因映射与通用软删除函数。
3. Web 可独立按既有字段上线，无先后硬依赖；Node 无需改动。
4. 回滚只回滚服务代码。由于没有新增列/表，无需清理结构；已写入的长期标记和既有冻结行保持原样。已由新删除路径清除的冻结行不会因回滚代码恢复，这是删除动作的既有结果。
5. 验收时对比变更前后的模型/数据库结构差异，确认没有新增结构；同时核对没有新增删除旁路、恢复补偿、迁移或后台任务。

## Dependencies / Follow-ups

- 无新增 Node、磁盘采集或 Web 契约前置；磁盘字节与机器上限是现有字段。
- Web `align-container-action-eligibility-and-recovery` 使用既有 `is_long_term`、配额和磁盘展示字段，不消费新对象。
- Q74 已决：恢复等同新建，删除重置冻结状态；本变更承接该边界，不再保留恢复宽限待决项。历史已软删记录的遗留行不回填，不另开恢复补偿或后台修复。
- 归档时把两个 delta 分别合并进 `backend--table-long-term-containers` 与 `backend--table-container-disk-freeze-state` 主规格；本变更只写 change 目录。

## Source references

- [services/container_module/long_term.py](../../../services/container_module/long_term.py)：`_load_long_term_target`、`_ensure_long_term_capacity_for_users`、`_persist_long_term_state`、`_audit_long_term`。
- [services/container_tasks.py](../../../services/container_tasks.py)：`set_long_term_container`、`resurrect_container`。
- [services/container_module/operation_guard.py](../../../services/container_module/operation_guard.py)：`CONTAINER_OPERATION_DENY_MATRIX`、`ensure_container_operation_allowed`。
- [services/container_module/information.py](../../../services/container_module/information.py)：`_disk_limit_bytes`、`_build_brief_disk_usage`。
- [schedulers/container_disk_check_task.py](../../../schedulers/container_disk_check_task.py)：`_usage_from_db`、`_evaluate_limits`。
- [models/container_disk_freeze_state.py](../../../models/container_disk_freeze_state.py)、[repositories/container_disk_freeze_state_repo.py](../../../repositories/container_disk_freeze_state_repo.py)：冻结行字段、`get(include_invalid=True)`、`reset`、`set_grace` 的既有边界。
- [repositories/containers_repo.py](../../../repositories/containers_repo.py)：`delete_container`（软删入口，第 258-279 行）、`restore_container_record`（第 282 行起）。
- [services/container_module/deletion.py](../../../services/container_module/deletion.py)：`_persist_container_deletion`（API/清理删除入口）。
- [services/container_module/node_comms_modules/deletion.py](../../../services/container_module/node_comms_modules/deletion.py)：名称消失线索 `_handle_container_vanish`（只标待核实，不软删、不触发冻结重置）。
- [services/container_tasks.py](../../../services/container_tasks.py)：`set_long_term_container`、`remove_container`、`resurrect_container`。
- [services/container_module/creation.py](../../../services/container_module/creation.py)：`_persist_container_record` 的 `restore_container_record` 分支。
- [services/container_module/restore.py](../../../services/container_module/restore.py)：`_ensure_restore_long_term_capacity`、`_restore_long_term_state`。
- [services/container_module/deleted_containers.py](../../../services/container_module/deleted_containers.py)：删除快照只保存 `is_long_term`，不含冻结字段。
- [extensions.py](../../../extensions.py)：`session_scope` 的 commit/rollback 边界。
- [repositories/long_term_container_repo.py](../../../repositories/long_term_container_repo.py)：`add`、`remove`、`count_by_user`。
- [api/container_api.py](../../../api/container_api.py)：`REASON_STATUS_MAP`、`set_long_term_container_api`。
