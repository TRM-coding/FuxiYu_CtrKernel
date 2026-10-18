# Proposal

## Why

2026-10-17 的 Sylvan 事故（`containers.id=201`）暴露了长期容器的服务端缺口：容器因磁盘硬超限被冻结后，用户把长期容器改为非长期；磁盘调度随后按“非长期”跳过响应，长期保护被解除。当前设置入口只做数量配额和既有状态矩阵，取消长期没有按实际冻结状态拦截，启用长期也没有比较磁盘用量与机器上限。

Q74 同日另行确认：恢复容器等同新建，无冻结记录即保持无记录，不再授予恢复宽限；删除容器时必须在同一事务重置冻结类状态。该边界只复用既有删除仓储与冻结仓储原语，不引入恢复旁路或补偿清理。

## What Changes

- 在既有手工长期设置入口内增加一个窄的、按方向判断的服务端静态守卫，复用现有权限、既有 `set_long_term` 状态矩阵、root 用户长期配额、容器当前状态、`disk_total_bytes`、`machine.max_disk_size_gb` 与既有硬限制百分比。
- 实际启用长期时，root 用户配额已满则拒绝；机器配置了磁盘上限且已知用量达到硬限制时拒绝。磁盘用量未知或机器未配置上限本身不构成新的拒绝理由，软阈值不阻断。
- 实际取消长期时，仅当实际状态为 `paused`（冻结中）拒绝；`online`/`offline` 且通过既有状态矩阵时允许。`container_disk_freeze_state` 行是否存在不是永久门禁，成功取消也不删除、重置该行或 Q72 累计字段。
- 实际写入前在同一会话/事务内重读容器、账号绑定、长期标记、机器磁盘配置和当前状态，再判断并用既有长期仓储原语写入。同目标值请求返回当前状态，不新增/删除标记、不写成功审计、不修改冻结锚点/宽限/累计字段。
- 上一版新增的持久化结构、资格响应对象与动作关联已直接删除，不保留兼容层；本变更只改现有服务逻辑，不引入新的状态机或 Node 协议前置。
- 恢复长期快照继续走既有 `Create_container` / `restore_container_record` 和既有 root 配额预检、长期标记恢复路径；恢复容器等同新建，不读取、复制或续期删除前的冻结状态，不人工授予恢复宽限，也不为表示宽限创建冻结行。无冻结记录时恢复后仍无记录。
- 删除容器时，通用软删除入口 `containers_repo.delete_container` 在同一事务内复用既有 `container_disk_freeze_state_repo.reset` 删除该容器的冻结状态行（`first_frozen_at`、`grace_until`、`deferral_seconds` 等随之清除）。正常 API/清理删除与 Node 消失删除共用该入口；无冻结行视为正常完成，重复删除幂等；删除失败或事务回滚保留原冻结状态，不提交半软删。
- 该删除重置只作用于被删除的 `container_id`，不影响其他容器；不新增删除旁路、恢复补偿清理、字段/表/JSON、迁移或后台修复，也不回填历史已软删记录。Q72 对同一未删除容器的累计不变；真正删除终止旧冻结周期，恢复新建不属于 Q72 续期。
- Web 变更继续使用既有 `is_long_term`、`long_term_container_can_enable`、`disk_usage_percent`/`disk_usage.usage_percent` 与 `effective_status` 做静态展示，后端仍是最终裁决；不要求新增资格响应对象。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-long-term-containers`：新增手工启用/取消长期的静态守卫、同目标值幂等和既有权限/状态/错误契约保持。
- `backend--table-container-disk-freeze-state`：删除容器时在同一事务重置冻结状态；恢复等同新建，不继承冻结状态或授予恢复宽限。

## Impact

涉及 `services/container_module/long_term.py`、`services/container_tasks.py`、`api/container_api.py` 的原因映射与失败审计，以及 `repositories/containers_repo.py` 的通用软删除入口复用 `repositories/container_disk_freeze_state_repo.py` 的既有 `reset`，并补对应隔离测试。

不改 `models/`、数据库结构、响应模型、Node 仓库、Web 仓库或正式 `openspec/specs/`。不新增恢复宽限机制、删除旁路、恢复补偿清理、字段/表/JSON、迁移或后台修复；历史已软删记录不回填。
