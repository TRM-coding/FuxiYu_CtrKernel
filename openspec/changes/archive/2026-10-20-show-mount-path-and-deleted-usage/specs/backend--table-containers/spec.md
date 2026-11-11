# Spec Delta

## ADDED Requirements

### Requirement: 容器详情返回既有宿主 bind 路径

Ctrl 的容器详情响应 SHALL 在既有字段之外追加可空 `bind_mount_path`，值只取 `containers.bind_mount_path`；MUST NOT 调用 Node 核对、不得从容器名/机器名/端口推导，也不得把已有值描述为实时验证。该字段只扩展既有详情 response，不新增数据库列/表/JSON，不改变 Node→Ctrl 推送或周期 WSS；旧 Ctrl 缺字段时按未记录降级。

#### Scenario: 有记录时原样返回

- **WHEN** 容器行存在非空 `bind_mount_path` 且请求详情
- **THEN** 详情响应的该字段与数据库值完全一致，不调用 Node，也不改变容器行

#### Scenario: 空值或旧响应按未记录处理

- **WHEN** 数据库值为 null，或旧 Ctrl 详情响应没有该字段
- **THEN** 消费方按“未记录”处理，不从名称、机器名或端口拼出候选路径

#### Scenario: 只读查询不写库

- **WHEN** 读取容器详情
- **THEN** 不新增/修改任何数据库行，也不因该字段触发 Node 请求或周期 WSS 变化
