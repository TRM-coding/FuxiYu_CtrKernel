# Proposal

## Why

2026-10-17 的 Sylvan 事故（`containers.id=201`）暴露了长期容器的服务端缺口：容器因磁盘硬超限被冻结后，用户把长期容器改为非长期；磁盘调度随后按“非长期”跳过响应，长期保护被解除。当前设置入口只做数量配额和既有状态矩阵，取消长期没有按实际冻结状态拦截，启用长期也没有比较磁盘用量与机器上限。

## What Changes

- 在既有手工长期设置入口内增加一个窄的、按方向判断的服务端静态守卫，复用现有权限、既有 `set_long_term` 状态矩阵、root 用户长期配额、容器当前状态、`disk_total_bytes`、`machine.max_disk_size_gb` 与既有硬限制百分比。
- 实际启用长期时，root 用户配额已满则拒绝；机器配置了磁盘上限且已知用量达到硬限制时拒绝。磁盘用量未知或机器未配置上限本身不构成新的拒绝理由，软阈值不阻断。
- 实际取消长期时，仅当实际状态为 `paused`（冻结中）拒绝；`online`/`offline` 且通过既有状态矩阵时允许。`container_disk_freeze_state` 行是否存在不是永久门禁，成功取消也不删除、重置该行或 Q72 累计字段。
- 实际写入前在同一会话/事务内重读容器、账号绑定、长期标记、机器磁盘配置和当前状态，再判断并用既有长期仓储原语写入。同目标值请求返回当前状态，不新增/删除标记、不写成功审计、不修改冻结锚点/宽限/累计字段。
- 上一版新增的持久化结构、资格响应对象与动作关联已直接删除，不保留兼容层；本变更只改现有服务逻辑，不引入新的状态机或 Node 协议前置。
- 恢复长期快照继续走既有 root 配额预检和长期标记恢复路径。用户已确认的“恢复原长期资格时静默授予一次既有时长宽限”政策保留；但既有冻结仓储只在冻结行上保存 `grace_until`，无冻结行时没有承载位置，详见 design 的表示缺口。该缺口独立上报，不与静态切换守卫捆绑，也不作为本变更的前置。
- Web 变更继续使用既有 `is_long_term`、`long_term_container_can_enable`、`disk_usage_percent`/`disk_usage.usage_percent` 与 `effective_status` 做静态展示，后端仍是最终裁决；不要求新增资格响应对象。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-long-term-containers`：新增手工启用/取消长期的静态守卫、同目标值幂等和既有权限/状态/错误契约保持。

## Impact

涉及 `services/container_module/long_term.py`、`services/container_tasks.py`、`api/container_api.py` 的原因映射与失败审计，以及对应隔离测试。

不改 `models/`、数据库结构、响应模型、Node 仓库、Web 仓库或正式 `openspec/specs/`。恢复宽限的承载方式不在本变更内；本变更只上报现有仓储无法表达该边界的证据，不据此新增结构，也不把它变成静态守卫的前置。
