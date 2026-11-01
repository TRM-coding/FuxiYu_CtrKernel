# Spec Delta

## MODIFIED Requirements

### Requirement: containers 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：Ctrl DB id 为页面与 API 的身份；删除保留无效行并生成恢复快照；Node WSS 状态对账更新运行事实，详情合成 effective_status。创建容器的共享内存 SHALL 同时受两条上限约束：机器共享上限 `max_shared_gb` 与本次申请的 `MEMORY`；任一越界 MUST 以 `invalid_config` 拒绝并给出具体数值，MUST NOT 只校验其中一条。

#### Scenario: 创建资源校验

- **WHEN** 创建请求包含 CPU、内存、共享内存、GPU 数量
- **THEN** 依机器允许上限校验；共享内存不得超过此次请求内存，失败返回 invalid_config 和具体资源数值

#### Scenario: 共享内存双重上限

- **WHEN** 机器共享上限 16GB、本次申请内存 32GB，而请求共享内存为 20GB
- **THEN** 以 `invalid_config` 拒绝并给出 20 与 16 两个数值；即使 20GB 未超过本次申请内存也不放行