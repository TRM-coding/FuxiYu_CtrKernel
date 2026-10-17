# Design

## Context

Ctrl 从 Node WSS 接收显式 `delete` 帧，也把非空状态快照中缺少的数据库容器名称交给同一个 `_handle_container_deleted` 软删函数。该函数按 `(machine_id, name)` 找当前有效记录，不知道帧对应的 Docker 对象 ID。`containers` 表已有 `status_unknown_since/status_source`，可表示暂时无法确认的状态。本变更是既有 `backend--table-containers` 的增量，按数据表组织，不新增独立能力或近似 capability。

## Goals / Non-Goals

**Goals:**

- 停止两条名称线索直接软删有效记录，保留用户绑定与恢复上下文。
- 后续正向快照可清除待核实标记，且操作审计能区分线索来源。

**Non-Goals:**

- 不把已软删除的历史 `jyz`、`test2` 自动复活；其数据修复需要核对所有关联和 Docker 对象。
- 不在此变更中新增 Docker ID 列或更改 Node `delete` 帧；严格代际身份见 Q70。

## Decisions

### 1. 两条消失线索只标记待核实

显式 `delete` 帧和快照缺席各自保留来源，统一调用无破坏性的异常标记入口。该入口先检查机器和当前有效记录，设置 `status_unknown_since`、`status_source`，写结构化诊断日志；来源至少区分 `delete_frame` 与 `snapshot_missing`，不再只用 `node_vanished` 概括。不调用软删及删除快照生成。平台主动删除、到期清理等已获明确动作的路径保持原有删除语义。

直接用名称软删无法区分同名新代；在现有协议下再问一次 Node 是否存在仍有查询后重建窗口，因此暂不把此查询当作删除授权。

### 2. 正向快照解除异常

沿用状态快照更新时对有效容器清除 `status_unknown_since/status_source` 的现有行为，但仅限可映射的明确状态；`unknown` 或仍处于过渡态时保留待核实标记。快照中缺席的记录只标待核实；`collect_error`、空快照走既有机器异常分支，不为每个容器制造删除事实。按机器作用域查找，避免跨机器同名影响。

### 3. 审计和恢复边界

异常标记写可检索日志，明确来源，并与成功删除审计分开；不生成 `delete_container success` 操作日志。历史软删行不靠名称快照自动复活，因为可能已有同名新代；须在独立数据修复中对照真实 Docker 对象和关联。两条线索都保留来源，便于区分 Q70 中的显式删帧与快照差集。

## Risks / Trade-offs

- [外部手工删 Docker 后 Ctrl 留有有效孤儿记录] → 展示待核实状态，提供管理员核对路径；最终自动清除机制待 Q70 的身份协议决策后实现。
- [两种消失线索重复到达] → 标记更新幂等，诊断日志保留来源且节流，避免重复审计。
- [Node 与 Ctrl 分别部署] → 先部署 Ctrl 防护，再部署 Node 对账修复；任一阶段都不把暂时缺席当作确认删除。配套 Node 文档若写了不同顺序，以 Ctrl 先行为准，并在联合验收前统一。

## Migration Plan

无需数据库迁移。先在隔离库验证旧名称帧及缺席快照不软删，再部署 Ctrl 防护；随后部署 Node `prevent-false-container-vanished`。回滚 Ctrl 将恢复旧的名称缺席软删风险，故在身份协议未补齐前不应单独回滚防护。已软删除记录不自动批量修改。

## Source references

- `services/container_module/node_comms_modules/snapshots.py`：状态快照应用与 `status_unknown_since/status_source` 清除。
- `services/container_module/node_comms.py`：`apply_container_status_snapshot` 的缺席名称处理。
- `services/container_module/node_comms_modules/deletion.py`：`_handle_container_deleted` 与 `node_vanished` 审计。
- `services/container_module/node_comms_modules/websocket.py`：`delete` 帧消费入口。
