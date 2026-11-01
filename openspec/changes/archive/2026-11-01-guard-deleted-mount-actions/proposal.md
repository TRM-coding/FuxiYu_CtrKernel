# Proposal

## Why

Ctrl 目前用数据库里的 `mount_cleaned`/`data_recoverable` 判断已删除容器的挂载是否可用，这不是目标机器上的新鲜证据。目录已经消失但 `mount_cleaned=false` 时，恢复会被放行，Node 在后台创建阶段才失败；此时 Ctrl 已经复活容器行、消费恢复快照并写成功审计，留下一个通常为 `status_unknown`、且不能正常删除的幽灵容器。手动清理也会在没有动作前证据的情况下直接请求 Node；`/clean_mount` 对不存在路径的 `rm -rf` 幂等成功，会把“目录不存在”误标成已清理。

本变更把“动作前由 Node 执行一次新鲜目录检查”固化为 Ctrl 契约，明确 `not_found` 与权限、非法路径、网络/旧 Node 错误的边界，并让已删除容器列表能只读地看到原容器行当前是否有效。

## What Changes

- **BREAKING** 恢复前新鲜检查：Ctrl 在恢复产生任何副作用前，请求目标机器上的 Node 对 `(machine_id, mount_path)` 做一次新鲜目录检查。检查结果为 `not_found` 时 MUST 拒绝恢复，以 `data_not_recoverable` 返回，并保留恢复快照与挂载清理记录；MUST NOT 复活容器行、请求 Node 创建、消费快照、写成功审计或返回 root 凭据。
- 恢复检查遇到 `permission_denied`、`invalid_path` 时以各自稳定错误拒绝并保留记录。旧 Node 不支持、超时、离线、坏响应等“无法得出结论”的结果 MUST 阻断恢复：以对应 `node_unsupported`/`node_timeout`/`node_unavailable`/`node_bad_response` 可重试原因拒绝，保留快照与清理记录，MUST NOT 继续 `Create_container`、消费快照或写成功审计；MUST NOT 将其误报为 `not_found`/`data_not_recoverable`。
- **BREAKING** 手动清理前新鲜检查：Ctrl 在手动清理产生任何副作用前执行同一检查。检查结果为 `not_found` 时 MUST 拒绝清理，保留 `container_mount_cleanup` 记录并保持 `deleted.mount_cleaned=false`；MUST NOT 调用 Node `clean_mount`、写 `cleaned_at`、同步 `mount_cleaned` 或写成功审计。权限不足、路径非法分别以 `permission_denied`/`invalid_path` 拒绝；旧 Node、超时、离线、坏响应以各自 `node_*` 原因拒绝并保留记录，MUST NOT 报告为 `not_found`。
- **BREAKING** 恢复与手动清理共同保护：原容器行存在且 `is_valid=true` 时，恢复与手动清理 MUST 以既有 `container_exists` 拒绝。恢复保留快照/清理记录，不继续 `Create_container`、不返回凭据；手动清理保留清理记录与 `mount_cleaned=false`，MUST NOT 调用 `/clean_mount`。只有原容器行不存在或 `is_valid=false` 时才继续执行动作。
- 自动清理与磁盘升级即时清理维持既有生命周期语义：不新增动作前新鲜检查，仍由服务端保留期/升级策略驱动，缺失目录的 `rm -rf` 幂等成功不改。本变更的手动清理 guard 不改变这些后台路径。
- 复用 Node 现有 `POST /api/check_mount_usage` 的单路径结果作为新鲜检查：`pending` 或成功表示路径已通过存在性门禁；`not_found`、`permission_denied`、`invalid_path` 分别作为路径门禁结果；`non_zero_exit`、`timeout`、`du_unavailable` 等测量类错误表示路径已通过门禁，MUST NOT 阻断动作。
- 已删除容器列表响应新增可空布尔字段 `original_container_is_valid`。该字段 SHALL 在列表读取时按 `original_container_id`（回落快照中的 `container_id`）从既有 `containers.is_valid` 动态派生：原容器行存在且有效为 `true`，存在且无效为 `false`，原容器行不存在为 `null`。MUST NOT 新增数据库列、表或 JSON 迁移，MUST NOT 用 `mount_cleaned`/`data_recoverable` 替代。
- 本变更只定义 Ctrl 侧契约；Node 复用现有按路径查询能力，Web 消费新增字段由各自变更/代理负责。本轮不改代码、不改测试、不提交、不归档。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-containers`：恢复挂载要求增加动作前 Node 新鲜目录检查与原容器有效态保护；`not_found` 拒绝恢复并保留记录，权限/非法路径各自拒绝，无法得出结论（旧 Node/离线/超时/坏响应）必须以可重试原因阻断且不得继续异步创建；原容器 `is_valid=true` 时以 `container_exists` 拒绝；保留既有恢复来源/改名不迁移数据场景。
- `backend--table-container-mount-cleanup`：手动清理生命周期增加同一新鲜检查与原容器有效态保护；`not_found` 拒绝清理并保留 `cleaned_at`/`mount_cleaned`；原容器 `is_valid=true` 时以 `container_exists` 拒绝；自动/升级清理维持既有语义；保留既有清理成功场景。
- `backend--table-deleted-container-restore-snapshot`：恢复快照在检查未通过时不得消费；路径查询错误映射区分统计展示、恢复与手动清理；新增已删除列表 `original_container_is_valid` 动态派生要求，且不新增数据库列。

## Impact

- Ctrl：`schemas/container.py`、`services/container_module/deleted_containers.py`、`services/container_module/restore.py`、`services/container_module/mount_cleanup.py`、`services/container_module/mount_usage.py`、`services/container_tasks.py`、`api/container_api.py`、`services/container_module/exceptions.py`，以及对应服务/API 测试。
- Node：复用现有 `POST /api/check_mount_usage` 的路径门禁结果；不新增 Node 表/列，不改 Node `clean_mount`。恢复与手动清理在旧 Node、离线、超时、坏响应下均失败关闭并保留记录。
- 数据库：无新列、无新表、无 JSON 迁移；列表新字段是 HTTP 响应投影。
- Web：可使用 `original_container_is_valid` 展示原容器行状态；本变更不实现 Web。
- 兼容性：手动清理对“目录不存在”从幂等成功变为拒绝；恢复对明确 `not_found` 从可能放行变为拒绝；恢复和手动清理在旧 Node/网络不确定时也必须失败关闭，需 Node 支持路径查询后才能执行。
