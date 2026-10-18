# Design

## Context

动机见 [proposal.md](proposal.md)，行为见两个 ADDED delta：[containers](specs/backend--table-containers/spec.md)、[deleted_container_restore_snapshot](specs/backend--table-deleted-container-restore-snapshot/spec.md)。

Ctrl 已持久化 `containers.bind_mount_path`，详情 builder/响应模型未透出。已删除页已有 `deleted_id`、`mount_path`、`cleaned_at`、`machine_id`，可从既有删除快照/清理记录读取；现有清理入参解析可能 ensure/adopt 写库，不能用于统计。Node 的按路径缓存和 du 由配套 change 提供；本 change 只实现 Ctrl 的只读解析、查询编排与响应归一。

配套 change（仅链接，契约以本文件与 delta 为准）：

- Node：[show-mount-path-and-deleted-usage](../../../../FuxiYu_NodeKernel/openspec/changes/show-mount-path-and-deleted-usage/proposal.md)
- Web：[show-mount-path-and-deleted-usage](../../../../FuxiYu_Web/openspec/changes/show-mount-path-and-deleted-usage/proposal.md)

## Goals / Non-Goals

**Goals:** 详情返回既有路径；已删除页按当前页 `deleted_id` 异步取统计；Ctrl 沿用 `container:manage`，只读解析 machine/path 并按机器定向 Node；严格映射三态，失败/旧 Node 不填 0。

**Non-Goals:** 不新增 DB 列/表/JSON，不扩周期 WSS，不改冻结/恢复/清理资格，不扫全盘/做全局总计，不引入 inode/dev/PID/Docker ID 授权，不改 `clean_mount`，不把 `du -sb` 逻辑字节称为物理块。不实现 Node/Web。

## Decisions

### 1. 修改两个既有 capability，仅 Ctrl

- `backend--table-containers`：新增详情 response 字段，复用既有 `bind_mount_path`，无 schema 改动。
- `backend--table-deleted-container-restore-snapshot`：新增只读统计 API、解析/定向/映射契约，不写该表或其他表。
- 本 change 不新增 capability，不定义 Node/Web 实现；配套仓各自维护同名 change。

### 2. 详情字段

在 `_build_container_detail`、服务层 `container_detail_information`、响应 `ContainerDetailInformation` 三处补可空 `bind_mount_path`，值只取 `container.bind_mount_path`。不调用 Node、不读 WSS、不拼猜；旧 Ctrl 缺字段时消费方按未记录。Web 用完整路径 + 复制，空值“未记录”，标注最近记录而非实时核对。该字段不是 DB 变更。

### 3. Web→Ctrl 契约

`POST /api/containers/get_deleted_container_mount_usage`

```json
{"deleted_ids": [12, 13]}
```

- `deleted_ids`：正整数数组，最多 100；MUST NOT 接受 `mount_path` 或其他宿主路径。模型校验失败走现有 400：`{success:0,message:"invalid request payload",error_reason:"invalid_payload",detail:[...]}`；缺 `container:manage` 走现有 403：`{success:0,message:"insufficient permissions",error_reason:"insufficient_permission"}`。
- 成功：`{success:1,usages:[{deleted_id,bytes,measured_at,pending,error}]}`，不含 `path`。`deleted_id` 按请求逐项映射；`deleted_ids` 先按原顺序去重。
- 无 `mount_path`、`mount_cleaned=true` 或 `cleaned_at` 非空：可从 `usages` 省略，Ctrl 不请求 Node；Web 直接用列表已有状态展示“无挂载/已清理”。
- 未知 `deleted_id` 返回错误项 `not_found`；记录无法解析 `machine_id` 同样按 `not_found`，不向其他机器发送。

### 4. 权限、只读解析与机器定向

- 只沿用既有 `container:manage`，不新增必须持有机器角色的门禁；若现有链路已有 scope 约束则复用。
- 从 `deleted_container_restore_snapshot_repo.get_by_id` 及对应清理记录只读读取；复用现有 `_get_deleted_container_context` 的只读语义，不调用任何 ensure/adopt 分支。`machine_id` 只用于选择 Node 端点，防止路径送错机器，不解释为 RBAC 授权。
- 禁止调用 `resolve_mount_cleanup_request` 或任何 ensure/adopt/insert/update/delete 路径；不写 `disk_*`、`deleted_container_restore_snapshot`、`container_mount_cleanup` 或其他 DB 行。
- 解析成功项按 `(machine_id, path)` 去重；同路径跨机器分开请求。机器端点缺失/离线只影响该机器的 id。

### 5. Ctrl→Node 契约与映射

`POST /api/check_mount_usage`

```json
{"config": {"mount_paths": ["/home/alice/containers/c1"]}}
```

Node 成功响应：

```json
{"success": 1, "mounts": [
  {"path": "/home/alice/containers/c1", "bytes": 123,
   "measured_at": "2026-10-18T12:00:00Z", "pending": false, "error": null}
]}
```

- 最多 100 条路径；Ctrl 按 `(machine_id, path)` 去重后批量发送。`path` 按请求回显，Node 内部按规范化路径去重缓存。
- Node 侧仅接受绝对路径：realpath 在 `NODE_CONTAINERS_BASE` 内且含 `containers`，目标为目录且非 symlink；`not_found`/`invalid_path` 不执行 du，也不返回旧缓存。
- Node 复用按 path 的内存 `get_bind` 缓存与后台 `du -sb`：成功样本 TTL 900 秒，du 超时 600 秒；慢 du 返回 pending，Ctrl 不等待。Node 侧同路径单飞、失败冷却、小并发，不建通用队列；Ctrl 只限制批量/并发。
- 成功项必须 `bytes>=0`、`measured_at` 为真实 UTC、`pending=false`、`error=null`；pending 项必须 `bytes=null`、`measured_at=null`、`pending=true`、`error=null`；错误项必须 `bytes=null`、`measured_at=null`、`pending=false`、稳定 `error`。任一组合不符按 `node_bad_response`，不采纳部分字段。
- Ctrl 按机器和回显 path 严格匹配后逐 `deleted_id` 映射；缺 path、重复 path、path 不匹配或跨机器混用均返回 `node_bad_response`，不借用其他结果。

错误映射：

- HTTP 404/405 → `node_unsupported`。
- HTTP 超时 → `node_timeout`。
- 机器离线、连接失败、5xx → `node_unavailable`。
- 2xx 缺 path/形状错误/三态非法 → `node_bad_response`。
- Node 的 per-path `invalid_path`、`not_found` 及 du 稳定错误（如 `non_zero_exit`、`timeout`、`permission_denied`、`empty_output`、`parse_error`、`du_unavailable`、`du_failed`）原样返回，不附 stderr。

所有错误项 `bytes=null`、`measured_at=null`、`pending=false`；MUST NOT 填 0 或伪造成功。单机失败不阻塞其他机器；旧 Node 无接口只影响统计。

### 6. Web 轮询契约（由 Web change 实现）

列表先出，统计后到；Ctrl 接口无状态，可重复查询同一 `deleted_ids`。Web 只对当前页 pending 行每 5 秒重查，单页最多 120 次（约 10 分钟，匹配 600 秒 du 超时）；success/error 停止；离开/翻页/刷新/清理/恢复取消计时器与在途请求并丢弃旧响应；预算耗尽显示“测量未完成”并允许手动刷新，不无限轮询、不新增周期 WSS。清理后不扫描、不展示旧缓存。Ctrl 只返回 pending/success/error，不自行轮询或持久化。

### 7. 兼容、字段与不变边界

- 旧 Ctrl 详情缺字段 → Web 未记录；旧 Ctrl 无统计接口 → Web 显示不可用，不影响原列表/恢复/清理。
- 旧 Node 无统计接口 → 逐条 `node_unsupported`；超时/离线/坏响应同理，不把 404 当 0。
- Node 重启丢失内存缓存、900 秒 TTL 内可能复用删除前样本，故只展示真实 `measured_at`，不称瞬时。
- 所有新字段都是 HTTP/进程内结果：详情 `bind_mount_path` 复用既有列；统计响应字段不落库。无数据库新列/表/JSON 迁移，无周期 WSS 变化，无 inode/dev/PID/Docker ID 协议。
- 不扫全盘、不做全局总计/清理门禁/自动冻结；不改 `clean_mount`，不把逻辑字节说成物理块。

## Risks / Trade-offs

- [路径缓存无法证明样本发生在删除后] → 返回真实 `measured_at`，页面标注最近记录，不称实时。
- [清理后旧缓存] → 已清理项不请求；Node 侧对不存在目录返回 `not_found`，Ctrl 不填 0。
- [du 慢/失败放大] → 只触发 pending，Web 有界轮询；Ctrl 不重试、不建队列。
- [旧 Node 或单机故障] → 逐 id 稳定错误，其他机器正常，列表不受阻。

## Open Questions

无。
