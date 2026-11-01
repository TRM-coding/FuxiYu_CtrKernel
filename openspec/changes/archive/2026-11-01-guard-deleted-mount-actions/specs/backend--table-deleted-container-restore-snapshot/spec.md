# Spec Delta

## MODIFIED Requirements

### Requirement: deleted_container_restore_snapshot 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：snapshot 保存重建输入；mount_cleaned 标识挂载目录可复用性；保留窗口加 deferral_seconds；恢复成功删除一次性快照及对应清理记录。恢复动作前的新鲜目录检查明确返回 `not_found`、`permission_denied`、`invalid_path`，或因旧 Node、超时、离线、坏响应而无法得出结论时，快照与对应清理记录 SHALL 保持原样；MUST NOT 因这些拒绝删除、消费或改写 `mount_cleaned`。无法得出结论时恢复 MUST 以对应 `node_*` 可重试原因阻断，MUST NOT 继续 `Create_container` 或消费快照。只有检查通过且恢复成功后才 SHALL 删除快照及对应清理记录。

#### Scenario: 完成复活

- **WHEN** 恢复门户成功重建容器并完成账号还原
- **THEN** 消费恢复快照并清除对应挂载清理记录，避免同一快照被再次使用

#### Scenario: not_found 不消费快照

- **WHEN** 恢复动作前的新鲜目录检查返回 `not_found`
- **THEN** 恢复快照与对应挂载清理记录保留，`mount_cleaned` 保持原值；MUST NOT 删除快照或清理记录，也 MUST NOT 把本次恢复记为成功

#### Scenario: 权限与非法路径不消费快照

- **WHEN** 恢复动作前的新鲜目录检查返回 `permission_denied` 或 `invalid_path`
- **THEN** 恢复快照与对应挂载清理记录保留，`mount_cleaned` 保持原值；MUST NOT 因这些拒绝消费快照或改写清理状态

#### Scenario: 无法得出结论必须阻断并保留快照

- **WHEN** 恢复动作前的新鲜目录检查因旧 Node 不支持、超时、离线或坏响应无法得出结论
- **THEN** Ctrl 以对应的 `node_unsupported`/`node_timeout`/`node_unavailable`/`node_bad_response` 可重试原因阻断恢复，快照与清理记录保留、`mount_cleaned` 保持原值；MUST NOT 继续 `Create_container`、消费快照或写成功审计，也不把结果写成 `not_found`/`data_not_recoverable`

### Requirement: Ctrl 查询错误映射与逐 id 回退

Ctrl SHALL 将 Node HTTP 404/405 映射 `node_unsupported`，超时 `node_timeout`，离线/连接失败/5xx `node_unavailable`，2xx 缺 `path` 或形状错误 `node_bad_response`；Node 的 per-path `invalid_path`、`not_found` 及 du 稳定错误 SHALL 原样返回。任一路径或机器失败 MUST 只影响对应 `deleted_id`，不得阻塞其他机器；错误项 `bytes`/`measured_at` MUST 为 null、`pending=false`，MUST NOT 填 0 或伪造成功。旧 Node 无统计接口时只影响统计展示，不影响原列表；恢复动作无法取得结论时 SHALL 以 `node_unsupported` 等可重试原因拒绝并保留快照，MUST NOT 报告为 `not_found`/`data_not_recoverable`，也 MUST NOT 继续异步创建；手动清理动作同样以对应 `node_*` 原因拒绝并保留记录；自动/升级清理不触发该检查。du 稳定错误中，`not_found`、`permission_denied`、`invalid_path` 是路径门禁失败；`non_zero_exit`、`timeout`、`du_unavailable` 等表示路径已通过存在性检查，MUST NOT 据此阻断恢复或手动清理。该变更不改变冻结/长期/删除资格，不做全盘扫描/全局总计/自动冻结，不改 `clean_mount`。

#### Scenario: 旧 Node 无接口

- **WHEN** Node 对新查询返回 HTTP 404/405
- **THEN** 受影响的 `deleted_id` 返回 `node_unsupported`，不得把 404 当 0 或空成功

#### Scenario: 超时、离线与坏响应

- **WHEN** Node 超时、机器离线/连接失败，或 2xx 响应缺路径/形状错误
- **THEN** 分别返回 `node_timeout`、`node_unavailable`、`node_bad_response`，字段保持 null/false 组合

#### Scenario: 单机失败不阻塞其他机器

- **WHEN** 一台机器请求失败，而当前页还有另一台机器
- **THEN** 失败机器的 id 返回稳定错误，其他机器仍正常映射结果，列表不被阻塞

#### Scenario: 严格匹配失败

- **WHEN** Node 响应缺少请求的 path、path 重复/歧义，或 path 与机器映射不一致
- **THEN** 对应 `deleted_id` 返回 `node_bad_response`，不借用其他机器或其他路径的 bytes

#### Scenario: 统计展示与动作 guard 分离

- **WHEN** 旧 Node 不支持路径查询，统计展示返回 `node_unsupported`，随后用户发起恢复或手动清理
- **THEN** 统计项仍按 `node_unsupported` 展示；恢复以 `node_unsupported` 可重试原因拒绝并保留快照，不把该错误当作 `not_found`，也不继续异步创建；手动清理以 `node_unsupported` 拒绝并保留快照/清理记录；自动/升级清理不触发该检查

#### Scenario: du 类错误不阻断动作

- **WHEN** Node 对路径返回 `non_zero_exit`、du `timeout`、`du_unavailable` 等测量类错误，但路径已通过存在性门禁
- **THEN** 统计展示保留该测量错误；恢复与手动清理的动作前检查按“路径存在”继续，MUST NOT 因测量失败拒绝动作

## ADDED Requirements

### Requirement: 已删除容器列表返回原容器有效态

Ctrl SHALL 在 `POST /api/containers/list_deleted_containers` 的每条记录中返回可空布尔字段 `original_container_is_valid`，并在读取时按 `original_container_id`（回落快照中的 `container_id`）从既有 `containers.is_valid` 动态派生：原容器行存在且 `is_valid=true` 时为 `true`，存在且为 `false` 时为 `false`，原容器行不存在时为 `null`。MUST NOT 新增数据库列/表/JSON 迁移，MUST NOT 用 `mount_cleaned`/`data_recoverable` 替代，列表读取 MUST NOT 修改任何数据库行。

#### Scenario: 原容器仍有效

- **WHEN** 已删除记录关联的原容器行存在且 `is_valid=true`
- **THEN** 列表记录的 `original_container_is_valid` 为 `true`

#### Scenario: 原容器已软删

- **WHEN** 已删除记录关联的原容器行存在且 `is_valid=false`
- **THEN** 列表记录的 `original_container_is_valid` 为 `false`，不把软删行误报为缺失

#### Scenario: 原容器行缺失

- **WHEN** 已删除记录找不到对应的原容器行
- **THEN** 列表记录的 `original_container_is_valid` 为 `null`，不得填 `false`

#### Scenario: 动态派生且只读

- **WHEN** 读取已删除容器列表
- **THEN** `original_container_is_valid` 只从既有 `containers.is_valid` 读取并投影到响应；不新增数据库列/表/JSON 迁移，不写容器行、删除快照或清理记录
