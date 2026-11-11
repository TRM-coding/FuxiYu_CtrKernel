# Design

## Context

动机见 [proposal.md](proposal.md)，行为见三个 delta：[containers](specs/backend--table-containers/spec.md)、[container_mount_cleanup](specs/backend--table-container-mount-cleanup/spec.md)、[deleted_container_restore_snapshot](specs/backend--table-deleted-container-restore-snapshot/spec.md)。

当前 Ctrl 的恢复预检只读 `deleted_container_restore_snapshot.mount_cleaned`（`services/container_module/restore.py:218-222`），不向 Node 查询目录；`resurrect_container` 在 `Create_container` 前还会读账号、解析镜像（`services/container_tasks.py:267-290`）。Node 的 `/create_container` 先返回 200 受理，目录检查在后台 `create_container` 内执行（`FuxiYu_NodeKernel/network/api.py:194-269`、`services/container_service.py:287-304`）。目录缺失时 Ctrl 已复活行、消费快照并写成功审计，Node 后台才失败。

清理侧 `_clean_mount_path_impl` 解析路径后直接请求 Node `/clean_mount`（`services/container_module/mount_cleanup.py:144-162`），没有动作前的存在性检查；Node `rm -rf` 对不存在路径返回成功，权限/网络失败则被 API 压成通用 500。手动清理与定时/升级清理共用该门户，但二者语义不同：手动是用户动作，定时/升级是服务端生命周期。

已删除列表的 `data_recoverable` 是 `bool(mount_path and not mount_cleaned)`（`services/container_module/deleted_containers.py:370`），只能表达记录上是否保留路径，不能表达原容器行当前是否有效。

Node 现有 `POST /api/check_mount_usage` 已实现按路径的新鲜门禁：`_validate_mount_path` 用 `os.stat` 区分 `not_found`/`permission_denied`/`invalid_path`（`FuxiYu_NodeKernel/docker_operates/disk_usage_cache.py:500-547`），通过门禁后才进入 du。本设计复用它作为 Ctrl 动作前的新鲜证据来源。

## Goals / Non-Goals

**Goals:**

- 恢复在产生副作用前，对精确的 `(machine_id, mount_path)` 取得 Node 的新鲜路径结论；`not_found` 明确拒绝并保留快照/清理记录。
- 手动清理在产生副作用前执行同一检查；`not_found` 明确拒绝并保留 `cleaned_at=null`/`mount_cleaned=false`。
- 权限、非法路径分别保留自己的原因；旧 Node、超时、离线、坏响应必须阻断并返回可重试原因，不误称 `not_found`。
- 恢复与手动清理在原容器行 `is_valid=true` 时均以既有 `container_exists` 拒绝，保护活挂载。
- 已删除列表以只读投影返回 `original_container_is_valid`，不新增数据库列。
- 复用现有 Node 查询能力，不要求 Node 新增表/列，也不改 Node `clean_mount`。

**Non-Goals:**

- 不实现 Node/Web 代码；不修改 `clean_mount` 的实际删除算法。
- 不新增数据库列/表/JSON 迁移，不改变 WSS 周期快照。
- 不消除“检查通过后目录又被删除”的 TOCTOU 竞态；本变更只消除基于陈旧 DB 状态的放行。
- 不改变自动清理与磁盘升级清理的生命周期；它们不新增动作前检查。
- 不自动解决手动清理 `not_found` 的遗留记录；记录保留，后续仍由既有生命周期或人工处理。

## Decisions

### 1. 复用 Node `/api/check_mount_usage` 单路径结果作为新鲜检查

Ctrl 在 `services/container_module/mount_usage.py` 增加只读探测：

```python
probe_mount_path(machine_id, mount_path) -> {
    "state": "present" | "missing" | "permission_denied" | "invalid_path" | "node_*",
    ...
}
```

它向目标机器 Node 发送：

```json
{"config": {"mount_paths": ["<mount_path>"]}}
```

只取回显 path 与请求 path 精确匹配的那一项，经 `classify_mount_path_state` 投影：

| Node 单路径结果 | 动作检查 state | 说明 |
| --- | --- | --- |
| `pending=true`，`error=null` | `present` | 已通过 `_validate_mount_path`，du 未完成不影响存在性 |
| `error=null` 且 `bytes` 为非负整数、`measured_at` 合法 UTC | `present` | 已通过门禁且测量成功 |
| `error="not_found"` | `missing` | 目录不存在 |
| `error="permission_denied"` | `permission_denied` | 存在性无法确认，权限不足 |
| `error="invalid_path"` | `invalid_path` | 路径非法、越界、非目录或 Node 拒绝的 symlink |
| 其余稳定 per-path 错误（`non_zero_exit`/`timeout`/`empty_output`/`parse_error`/`du_unavailable`/`du_failed` 等） | `present` | 路径已过存在性门禁；du 失败不阻断动作 |
| HTTP 404/405 | `node_unsupported` | 旧 Node 无该查询能力 |
| 请求超时 | `node_timeout` | 与 per-path du `timeout` 区分 |
| 机器缺失/离线/连接失败/5xx | `node_unavailable` | 未能取得新鲜证据 |
| 2xx 缺 path、重复 path、形状错误 | `node_bad_response` | 不确定即失败关闭 |

选择复用现有查询而不是新增端点：路径门禁、`not_found`/`permission_denied` 区分和旧 Node 错误映射都已在 Node/Ctrl 两侧存在，Ctrl 只需新增单路径动作消费者。代价是该接口可能触发 du；动作检查只等路径门禁结果，不等待 bytes，`pending` 即视为存在。

替代方案是新增专用 Node 存在性端点。它语义更纯、不会触发 du，但需要新增 Node 契约和部署协调；若后续 du 开销不可接受，可替换探测函数内部的 Node 调用而不改变动作语义。

### 2. 恢复：明确缺失与无法得出结论都必须阻断

在 `resurrect_container` 中，`_load_restore_target` 成功之后、`_load_restore_accounts`/`_resolve_restore_image` 之前调用 `_ensure_restore_mount_source`（对应 `services/container_tasks.py:267-269`）。

状态映射：

| state | 恢复动作 |
| --- | --- |
| `present` | 继续既有恢复 |
| `missing` | 抛 `NodeServiceError(reason="data_not_recoverable")`，保留快照/清理记录，不复活行、不创建、不返回凭据 |
| `permission_denied` | 抛 `NodeServiceError(reason="permission_denied")`，保留记录 |
| `invalid_path` | 抛 `NodeServiceError(reason="invalid_path")`，保留记录 |
| `node_unsupported`/`node_timeout`/`node_unavailable`/`node_bad_response` | 抛对应 `node_*` 可重试原因，保留快照/清理记录；不继续 `Create_container`、不消费快照、不写成功审计，也不误报 `not_found`/`data_not_recoverable` |

原容器行存在且 `is_valid=true` 时，恢复沿用既有 `_ensure_create_target` 的 `container_exists` 守卫（`services/container_module/creation.py:46-52`）；该守卫在任何 Node 创建、落库或快照消费之前触发。若前置检查更早发现同一状态，也 MUST 使用既有 `container_exists`，不新增平行 reason。

`_ensure_restore_mount_source` 在 `Create_container` 之前执行；所有非 `present` 状态由既有最外层 `except` 调用 `_audit_restore_failure`（`services/container_module/restore.py:125-156`）后原样上抛。这样在 `_persist_container_record`、`_delete_restore_artifacts` 之前终止。

无结论分支不再退回复活动作端点：旧 Node、超时、离线、坏响应都表示“无法证明目录仍然存在”，必须失败关闭并保留可重试记录。只有 `present` 才允许进入创建；这消除了“未知结果继续异步创建并消费快照”的旧放行方案。

### 3. 手动清理：缺失与活挂载都拒绝，自动/升级清理不变

`clean_mount_path` 新增 `verify_mount_path: bool = False`；只有 `clean_deleted_container_mount`（手动入口）传 `True`。定时清理与磁盘升级即时清理保持默认 `False`，继续由服务端保留期/升级策略驱动，不新增动作前检查。

在 `_clean_mount_path_impl` 中，记录读取和幂等分支之后、请求 Node `/clean_mount` 之前先检查原容器行：原行存在且 `is_valid=true` 时抛既有 `NodeServiceError(reason="container_exists")`，保留清理记录与 `mount_cleaned=false`，不调用 Node。原行不存在或 `is_valid=false` 时才调用 `_ensure_manual_clean_mount_path`（对应 `services/container_module/mount_cleanup.py:144-162`）。该位置覆盖手动入口；失败由 `clean_mount_path` 门户的 `except` 统一写失败 op-log 并原样上抛（`mount_cleanup.py:33-90`）。

状态映射（原容器行不存在或 `is_valid=false` 后）：

| state | 手动清理动作 |
| --- | --- |
| `present` | 继续 `/clean_mount` |
| `missing` | 抛 `NodeServiceError(reason="not_found")`；不调用 `/clean_mount`，不写 `cleaned_at`/`mount_cleaned` |
| `permission_denied` | 抛 `NodeServiceError(reason="permission_denied")`；记录保持 |
| `invalid_path` | 抛 `NodeServiceError(reason="invalid_path")`；记录保持 |
| `node_unsupported`/`node_timeout`/`node_unavailable`/`node_bad_response` | 抛对应 `node_*`；记录保持，不误称 `not_found` |

`deleted.mount_cleaned=true` 或 `cleanup.cleaned_at` 非空时仍走 `already_cleaned`，不请求 Node、不做新鲜检查。手动路径的 `resolve_mount_cleanup_request` 对历史 cleanup-only 记录的 ensure/adopt 行为不变；检查保护的是真正的目录清理动作。

自动/升级清理不检查 `not_found`，因此仍可能在目录缺失时按既有 `/clean_mount` 幂等语义标记 cleaned；这是有意保留的既有生命周期，不由本变更改变。手动 `not_found` 的记录保留后，后续仍可能被自动清理按既有规则处理；若自动清理关闭，则需要人工核实/修复。

### 4. 错误原因与 API 映射

在 `services/container_module/exceptions.py` 的 `SAFE_REASON_CODES` 增加：

- `permission_denied`
- `invalid_path`
- `node_unsupported`
- `node_timeout`
- `node_unavailable`
- `node_bad_response`

`container_exists` 已存在于 `SAFE_REASON_CODES` 且映射 409，恢复与手动清理复用，不新增平行 reason。

这些 reason 必须进入白名单，否则 `safe_reason` 会把 Node 原始 reason 降级成 `create_failed`。在 `api/container_api.py` 的 `REASON_STATUS_MAP` 增加：

| reason | 状态码 |
| --- | --- |
| `permission_denied` | 403 |
| `invalid_path` | 400 |
| `node_unsupported` | 502 |
| `node_timeout` | 504 |
| `node_unavailable` | 503 |
| `node_bad_response` | 502 |

恢复 `not_found` 复用既有 `data_not_recoverable` 409；手动清理 `not_found` 复用既有 `not_found` 404（message 明确 `mount path no longer exists; nothing was cleaned`，与记录不存在区分）。原容器 `is_valid=true` 的恢复/手动清理统一复用既有 `container_exists`（409），不新增平行 reason。

所有失败分支只允许既有失败审计（op-log），不得写成功审计；恢复的 `not_found`/权限/非法路径/`node_*` 均不消费快照、不继续创建，手动清理失败不写 `cleaned_at`/`mount_cleaned`。

### 5. 列表字段 `original_container_is_valid`

在 `DeletedContainerRecord` 增加：

```python
original_container_is_valid: bool | None = None
```

在 `serialize_deleted_container_record` 中：

```python
"original_container_is_valid": getattr(context.get("container"), "is_valid", None)
```

`_get_deleted_container_context` 已用 `containers_repo.get_by_id(..., include_invalid=True)` 读取原行（`deleted_containers.py:264-292`），因此：

- 原行存在且 `is_valid=true` → `true`；
- 原行存在且 `is_valid=false`（正常软删）→ `false`；
- 原行不存在 → `None`，不是 `false`。

该字段只读、只投影；不写 `deleted_container_restore_snapshot`，不新增数据库列/表/JSON 迁移，也不调用 Node。不要用 `data_recoverable` 或 `mount_cleaned` 代替它：前者是挂载保留状态，后者是清理状态，都不是原容器行有效性。

### 6. 统计展示、动作 guard 与旧 Node 的边界

复用 `/api/check_mount_usage` 后，旧 Node 的 404/405 对不同消费者有不同后果：

- 统计展示：逐项 `node_unsupported`，不影响列表。
- 恢复：无法取得结论，以 `node_unsupported`/`node_timeout`/`node_unavailable`/`node_bad_response` 可重试原因拒绝并保留记录，不冒充 `not_found`，不继续异步创建。
- 手动清理：无法取得结论，以对应 `node_*` 拒绝并保留记录。
- 自动/升级清理：不触发该检查，维持既有语义。

du 类 per-path 错误（`non_zero_exit`、du `timeout`、`du_unavailable` 等）发生在路径门禁之后，说明目录存在性已经确认；动作探测按 `present` 继续，只有 `not_found`/`permission_denied`/`invalid_path` 参与动作拒绝。该区分必须在 `classify_mount_path_state` 中显式编码，不能把所有 `error` 一律当成不存在。

## Risks / Trade-offs

- [恢复在旧 Node/网络不确定时失败关闭] → 可用性下降：旧 Node、离线、超时、坏响应都会阻断恢复，需修复 Node/网络后重试。记录保留，不会因 unknown 继续异步创建并消费快照；这是本次审计要求的有意取舍。
- [手动 `not_found` 记录保留] → 手动清理不会自动丢弃记录；若自动清理开启，后续仍可能按既有生命周期处理；若关闭，需要人工核实/修复。这是 fail-closed 的明确代价。
- [手动清理活挂载保护] → 原容器行 `is_valid=true` 时以既有 `container_exists` 拒绝；若记录与原行状态不一致，需先修复记录/容器关系，不能直接删挂载。该检查先于 Node 路径探测，避免误删活容器数据。
- [每次手动清理/恢复多一次 Node 调用] → 探测使用短超时；`pending` 即视为存在，不等待 du；同一动作只查一条路径。若 du 触发造成负担，后续可替换为专用存在性端点，不改变动作语义。
- [自动/升级清理不检查] → 缺失目录仍会按既有 `/clean_mount` 幂等成功并标记 cleaned；这是有意隔离，避免后台生命周期被手动 guard 改变。若产品要求后台也检查，应另做变更。
- [symlink 策略更严格] → `/api/check_mount_usage` 的路径门禁拒绝 symlink，而 Node restore 的 `realpath` 可能允许 base 内 symlink；动作探测会按 `invalid_path` 拒绝。该差异应在实现/测试中显式覆盖，避免把合法历史路径误判。
- [失败审计噪声] → 手动 `not_found` 每次重试都会写失败 op-log；自动清理仍可能后续成功。若需要抑制，应另做调度层限流，不能改变记录保留语义。

## Migration Plan

1. 确认目标 Node 已部署 `/api/check_mount_usage` 的路径门禁结果；旧 Node/网络不确定时恢复与手动清理都会失败关闭并保留记录。
2. 先部署 Ctrl 探测与错误映射，再接入恢复/手动清理调用点；无数据库迁移，无需回填。
3. 列表字段是响应增量，Web 可独立采用；旧 Web 忽略新字段。
4. 回滚只需回退 Ctrl 代码；数据库无变更，记录保留语义随代码回退。

## Open Questions

无。自动/升级清理是否也要引入动作前检查、以及是否新增专用 Node 存在性端点，都属于后续独立变更，不影响本变更的规格、方案或任务拆分。
