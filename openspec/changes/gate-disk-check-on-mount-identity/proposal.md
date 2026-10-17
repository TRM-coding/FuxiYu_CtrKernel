# Proposal

## Why

Ctrl 目前只要收到完整的字节数字就更新 `disk_checked_at`，即使 Node 的字节数来自旧目录或已过期缓存；磁盘调度随后仅按数据库字节数执行冻结及升级删除。Node 增加挂载身份验证后，Ctrl 必须保存验证事实并阻止不可靠用量驱动处置；同时旧 Node、退役连接与旧 HTTP 响应不能借接收路径恢复可信结论。

## What Changes

- 接收并持久化 Node 协议 version 1 的挂载身份、测量资格、异常原因、Docker 对象与观测代际；缺少协议或身份的旧 Node 样本显式标为未验证。
- 仅身份匹配或经成功 Docker 观测确认 `no_bind`、测量完整、身份与测量均未过期且属于当前观测代际的样本，才更新有效用量与真实测量时间；异常样本保留最近数值供排障，不刷新测量时间，不把缺失值写成零。
- 限额调度遇到错位、未知、未验证或过期样本时，不执行冻结、解冻重置、超限通知、升级删除及挂载清理，也不调用暂停接口；异常期不新增倒计时补偿。恢复可信样本后按 Q72 累计口径继续，机器不可用补偿与人工宽限保留。
- WSS、手动磁盘刷新及其他写入口共用同一接收与资格规则；退役连接、同 epoch 倒序结果和旧 HTTP 响应不得回填。首版对 source mismatch 一律跳过磁盘自动处置，但仍落库异常状态与证据；清理前身份验证属 Q71 待选扩展，不在本补丁内。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-containers`：持久化磁盘验证事实与真实测量时间，约束磁盘自动处置及查询展示。

## Impact

涉及 `services/container_module/node_comms_modules/snapshots.py`、`services/container_module/node_comms.py`、`services/container_module/node_comms_modules/websocket.py`、`schedulers/container_disk_check_task.py`、磁盘查询和手动刷新入口、`models/containers.py`、数据库迁移与测试；配套 Node 变更 `verify-bind-mount-identity`。**BREAKING**：缺少新协议字段的旧 Node 样本默认为未验证，保留展示但暂停磁盘自动处置；部署需逐机核对验证覆盖率。错位时允许冻结的扩展见 Q71；Q72 已由用户决定维持累计口径，恢复可信高用量后允许按既有阈值升级删除，机器不可用补偿及人工宽限继续保留。本门禁只做采样证据校验，不建立 Q70 的跨进程操作代际，也不宣称保证清理路径的原子对象身份。
