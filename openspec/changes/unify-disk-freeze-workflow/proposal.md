# Proposal

## Why

`pause_container` 虽被描述为磁盘冻结，却只请求 Node 暂停、即时回写 PAUSED 和审计；Node 实际是异步受理并返回 pausing，真正暂停要等 WSS 状态。冻结记录、超限通知、宽限及升级判断又分散在调度器中，运维直接调用 pause 无法得到标准冻结业务；现有调度还在暂停前发送“已冻结”邮件，暂停失败时会造成结果误报。

## What Changes

- 提供统一磁盘冻结业务入口，让调度与按容器 ID 的受控运维触发复用资格检查、冻结锚点、暂停、通知及结果追踪；普通暂停仍保持独立动作语义。
- 返回分阶段结果，区分策略周期建立、暂停请求受理、WSS 确认暂停、状态回写和通知结果；Node accepted/pausing 不是暂停成功，失败可按同一周期重试。
- 统一冻结周期和通知的跨进程幂等规则，使用数据库原子锚点、阶段认领和带过期租约；保留人工解冻宽限及 Q72 已决的累计升级口径；运维“冻结一次”入口默认不能隐含执行升级删除。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-container-disk-freeze-state`：完整冻结业务入口、周期重入、失败恢复及累计升级规则。
- `backend--table-operation-logs`：暂停与磁盘冻结业务的分阶段结果、真实通知结果和触发来源。

## Impact

涉及 `services/container_tasks.py`、`services/container_module/actions.py`、新增磁盘策略服务、`services/container_module/node_comms_modules/snapshots.py`（WSS 确认）、`schedulers/container_disk_check_task.py`、`api/container_api.py`（受控按 ID 触发）、冻结状态仓储与迁移、通知/审计及隔离测试。与 `gate-disk-check-on-mount-identity` 共用测量有效性门禁，协议字段不由本变更修改；本变更不修生产数据，不扩大到所有生命周期动作，不改变机器限额或把所有 pause 都写成磁盘超限冻结。
