# Spec Delta

## MODIFIED Requirements

### Requirement: containers 恢复挂载与数据位置

恢复的挂载行为 SHALL 与内容来源无关：两种来源取同一挂载路径与同一数据位置；容器改名 MUST NOT 改变数据位置。恢复在产生任何副作用前 SHALL 由目标机器上的 Node 对该 `(machine_id, mount_path)` 执行一次新鲜目录检查；Ctrl MUST NOT 以 `deleted_container_restore_snapshot.mount_cleaned`、列表字段、WSS 快照、历史用量结果或缓存替代该检查。检查结果为 `not_found` 时 MUST 拒绝恢复，以 `data_not_recoverable` 返回，并保留恢复快照与挂载清理记录；MUST NOT 复活容器行、请求 Node 创建、消费快照、写成功审计或返回 root 凭据。原容器行存在且 `is_valid=true` 时 MUST 以既有 `container_exists` 拒绝恢复，保留恢复快照与挂载清理记录，MUST NOT 继续 `Create_container`、返回凭据或写成功审计。检查结果为 `permission_denied` 或 `invalid_path` 时 SHALL 以各自稳定错误拒绝并保留记录。检查无法得出结论时（旧 Node 不支持、超时、离线、坏响应），MUST 阻断恢复：以对应 `node_unsupported`/`node_timeout`/`node_unavailable`/`node_bad_response` 可重试原因拒绝并保留恢复快照与挂载清理记录；MUST NOT 继续 `Create_container`、消费快照或写成功审计，也 MUST NOT 将其报告为 `not_found` 或 `data_not_recoverable`。

#### Scenario: 恢复来源与改名不迁移数据

- **WHEN** 调用方选择任一内容来源恢复容器，并调整容器名称
- **THEN** 恢复使用同一挂载路径和数据位置，容器改名不改变数据位置

#### Scenario: 动作前新鲜检查通过

- **WHEN** Ctrl 在恢复副作用前向目标 Node 查询到该容器的 `(machine_id, mount_path)` 为现存目录
- **THEN** Ctrl 继续按既有内容来源规则恢复，并沿用同一挂载路径

#### Scenario: not_found 拒绝恢复并保留记录

- **WHEN** Node 的新鲜目录检查结果为 `not_found`
- **THEN** Ctrl 以 `data_not_recoverable` 拒绝恢复；恢复快照与挂载清理记录保持原状，容器行保持已删除，MUST NOT 请求 Node 创建、写成功审计或返回 root 凭据

#### Scenario: 原容器已恢复为有效时拒绝恢复

- **WHEN** 恢复对应的原容器行存在且 `is_valid=true`
- **THEN** Ctrl 以既有 `container_exists` 拒绝恢复，保留恢复快照与挂载清理记录；MUST NOT 继续 `Create_container`、写成功审计或返回 root 凭据；该拒绝先于任何恢复副作用

#### Scenario: 权限与非法路径不误称 not_found

- **WHEN** 新鲜目录检查返回 `permission_denied` 或 `invalid_path`
- **THEN** Ctrl 分别以 `permission_denied` 或 `invalid_path` 拒绝恢复，并保留恢复快照与挂载清理记录；MUST NOT 返回 `not_found` 或 `data_not_recoverable`

#### Scenario: 无法得出结论必须阻断且不冒充 not_found

- **WHEN** 新鲜目录检查因旧 Node 不支持、Node 不可达/超时或坏响应而无法给出结论
- **THEN** Ctrl 以对应的 `node_unsupported`/`node_unavailable`/`node_timeout`/`node_bad_response` 可重试原因拒绝恢复，保留恢复快照与挂载清理记录，MUST NOT 继续 `Create_container`、消费快照或写成功审计；MUST NOT 返回 `not_found` 或 `data_not_recoverable`
