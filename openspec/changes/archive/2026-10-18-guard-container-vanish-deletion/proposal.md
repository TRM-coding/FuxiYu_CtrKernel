# Proposal

## Why

Ctrl 目前把非空 Node 状态快照中缺席的数据库容器直接软删除，也会按机器和名称接受 `delete` 帧。创建刚受理但 Node 后台线程尚未登记状态、或 Node 缓存短暂失准时，仍在运行的容器会失去有效数据库记录；`jyz`、`test2` 已出现这类后果。

## What Changes

- 快照缺席和仅含名称的 `delete` 帧不再直接软删除有效容器记录；以待核实标记表达无法确认的状态，保留原记录有效性、账号绑定与恢复信息。
- 后续同名在线快照可清除待核实标记并更新状态；采集错误或空快照不制造删除事实。
- 记录异常来源、机器与名称，使显式删除帧和快照缺席可区分审计；为后续明确的外部删除确认策略留出接口。
- **BREAKING**：在缺少代际身份协议前，Node 外部直接删除的容器不会再由名称缺席自动从 Ctrl 数据库软删除，需要管理端核实或后续身份协议收敛。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-containers`：Ctrl 对 Node 消失线索的保守处理、待核实标记与恢复；不新增近似能力或独立表规范。

## Impact

涉及 Ctrl 的 `services/container_module/node_comms_modules/snapshots.py`、`deletion.py`、`node_comms.py` 及相关测试；复用 `backend--table-containers` 已有的 `status_unknown_since/status_source`，无需立即增加表列。部署顺序为先 Ctrl 防护、后 Node `prevent-false-container-vanished`，再联合验证；任一阶段都不把暂时缺席当作确认删除。严格同名代际身份和自动清除外部已删记录的终局策略留在 Global `QUESTIONS.md` Q70。
