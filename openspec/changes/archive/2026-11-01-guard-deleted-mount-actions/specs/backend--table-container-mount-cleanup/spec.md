# Spec Delta

## MODIFIED Requirements

### Requirement: container_mount_cleanup 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：deleted 快照为保留生命周期权威，本表保存执行路径、removed_at、cleaned_at、escalation；手动、定时及磁盘升级清理共用服务门户。手动清理在产生任何副作用前 SHALL 先检查原容器行：原容器行存在且 `is_valid=true` 时 MUST 以既有 `container_exists` 拒绝，保留本表记录与 deleted 快照的 `mount_cleaned=false`，MUST NOT 调用 Node `clean_mount`。原容器行不存在或 `is_valid=false` 时，手动清理 SHALL 由目标机器上的 Node 对该 `(machine_id, mount_path)` 执行一次新鲜目录检查；Ctrl MUST NOT 仅凭 `cleaned_at`、`mount_cleaned`、列表字段或历史用量结果判定目录存在。检查结果为 `not_found` 时 MUST 拒绝手动清理并保留本表记录与 deleted 快照的 `mount_cleaned=false`，MUST NOT 调用 Node `clean_mount`、写 `cleaned_at`、同步 `mount_cleaned` 或写成功审计。权限不足、路径非法分别以 `permission_denied`、`invalid_path` 拒绝；旧 Node 不支持、超时、离线、坏响应以各自 `node_*` 原因拒绝并保留记录，MUST NOT 报告为 `not_found`。定时清理与磁盘升级即时清理维持既有生命周期语义，不新增本动作前检查。

#### Scenario: 清理成功

- **WHEN** Node 完成指定挂载目录清理
- **THEN** 在事务中记录 cleaned_at，并同步 deleted 快照的 mount_cleaned

#### Scenario: 手动清理前新鲜检查通过

- **WHEN** Ctrl 在手动清理副作用前向目标 Node 查询到该 `(machine_id, mount_path)` 为现存目录
- **THEN** Ctrl 继续执行既有清理流程，并仅在 Node `clean_mount` 成功后记录 `cleaned_at` 与 `mount_cleaned`

#### Scenario: 原容器已恢复为有效时拒绝手动清理

- **WHEN** 手动清理对应的原容器行存在且 `is_valid=true`
- **THEN** Ctrl 以既有 `container_exists` 拒绝手动清理，保留 `container_mount_cleanup` 记录与 `mount_cleaned=false`，MUST NOT 调用 Node `clean_mount`、写 `cleaned_at` 或写成功审计；该拒绝先于新鲜目录检查发生

#### Scenario: not_found 拒绝手动清理并保留记录

- **WHEN** Node 的新鲜目录检查结果为 `not_found`
- **THEN** Ctrl 以 `not_found` 拒绝手动清理；`container_mount_cleanup` 记录的 `cleaned_at` 保持为空，deleted 快照的 `mount_cleaned` 保持 false，MUST NOT 调用 Node `clean_mount` 或写成功审计

#### Scenario: 权限、非法路径与网络错误不误称 not_found

- **WHEN** 手动清理的新鲜目录检查返回 `permission_denied`、`invalid_path`，或因旧 Node 不支持、超时、离线、坏响应而失败
- **THEN** Ctrl 分别以 `permission_denied`、`invalid_path` 或对应的 `node_unsupported`/`node_timeout`/`node_unavailable`/`node_bad_response` 拒绝，并保留 `container_mount_cleanup` 记录与 `mount_cleaned=false`；MUST NOT 返回 `not_found`，也不得把错误写成目录不存在

#### Scenario: 自动与升级清理维持既有语义

- **WHEN** 定时清理或磁盘升级即时清理处理一条记录
- **THEN** 不执行本变更的手动动作前新鲜检查，继续按既有服务端生命周期调用 `/clean_mount`；缺失目录仍按既有幂等语义处理，不由该分支判定 `not_found`
