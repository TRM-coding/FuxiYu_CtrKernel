# Proposal

## Why

Ctrl 已持久化 `containers.bind_mount_path`，但详情 builder 与响应模型没有透出，用户看不到或复制完整宿主路径。已删除容器页目前只有 `mount_path` 与清理状态，无法显示遗留目录当前占用；Node 已有按路径缓存和后台 du，但 Ctrl 没有安全的只读查询编排。

本 change 只定义 Ctrl 侧契约；Node/Web 由各自同名配套 change 实现：

- Node：[show-mount-path-and-deleted-usage](../../../../../FuxiYu_NodeKernel/openspec/changes/archive/2026-10-20-show-mount-path-and-deleted-usage/proposal.md)
- Web：[show-mount-path-and-deleted-usage](../../../../../FuxiYu_Web/openspec/changes/archive/2026-10-20-show-mount-path-and-deleted-usage/proposal.md)

本仓契约以下文为准，不依赖跳转阅读。

## What Changes

- **详情字段**：Ctrl 在既有详情响应追加可空 `bind_mount_path`，值只取既有 `containers.bind_mount_path`；不调用 Node 核实，不改 Node→Ctrl 推送，不新增 DB 列/表/JSON。Web 展示完整路径并可复制，空值只写“未记录”，不拼猜，不称实时验证。
- **已删除统计 API**：新增 `POST /api/containers/get_deleted_container_mount_usage`，只接收当前页 `deleted_ids`（正整数，最多 100）；成功响应 `{success:1,usages:[{deleted_id,bytes,measured_at,pending,error}]}`，不向 Web 返回 `path`。无挂载/已清理可省略项且不扫描。
- **权限与只读解析**：沿用既有 `container:manage`，不新增必须持有机器角色的门禁；`machine_id` 仅用于把服务端解析出的路径定向到对应 Node。只从既有删除快照/清理记录只读解析 `machine_id`/`mount_path`，禁止调用 `resolve_mount_cleanup_request` 等 ensure/adopt 写库路径，不写 `disk_*`、恢复快照、清理记录或其他 DB 行。
- **Ctrl→Node 契约**：按 `(machine_id, path)` 去重后调用 Node `POST /api/check_mount_usage`，请求 `{config:{mount_paths:[绝对路径]}}`，最多 100；Node 响应 `{success:1,mounts:[{path,bytes,measured_at,pending,error}]}`。Ctrl 按机器与回显 path 严格匹配、逐 `deleted_id` 映射，同路径跨机不混用。Node 侧只接受 `NODE_CONTAINERS_BASE`/`containers` 范围内的绝对真实目录，复用按 path 内存缓存/后台 du（900 秒 TTL、600 秒超时、同路径单飞、失败冷却、小并发，不建通用队列），`not_found`/`invalid_path` 不测量，慢 du 只返回 pending。
- **三态与错误**：成功 `bytes>=0`/真实 UTC `measured_at`/`pending=false`/`error=null`；pending 三项为 null/true/null；错误三项为 null/false/稳定原因。旧 Node 404/405→`node_unsupported`，超时→`node_timeout`，离线/连接失败/5xx→`node_unavailable`，缺 path/形状错→`node_bad_response`；均不填 0、不伪造成功。单机失败不阻塞其他机器。
- **Web 消费契约**：列表先出，统计异步；当前页仅对 pending 行每 5 秒重查、单页最多 120 次，success/error 停；离开/翻页/刷新/清理/恢复取消并丢弃旧响应；预算耗尽提示未完成并允许手动刷新，不无限轮询、不新增周期 WSS。清理后不扫描、不展示旧缓存。
- **不做**：不新增数据库列/表/JSON 迁移；不改原冻结/恢复/清理资格；不扩周期 WSS；不以 inode/dev/PID/Docker ID 做授权或协议；不做全盘扫描、全局总计、清理门禁或自动冻结；不改 `clean_mount`；不把 `du -sb` 逻辑字节称为物理块。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-containers`：新增容器详情 response 的 `bind_mount_path` 字段；复用既有列，不新增 DB schema。
- `backend--table-deleted-container-restore-snapshot`：新增已删除容器遗留挂载用量的只读 API、权限/解析/机器定向、Node 查询映射与错误回退；不写该表或任何其他 DB 行。

## Impact

- Ctrl：`schemas/container.py`、`services/container_module/information.py`、`services/container_module/pydantic_models.py`、`api/container_api.py`、`services/container_tasks.py`，以及已删除记录的只读解析和 Node HTTP 编排。
- 无数据库模型/迁移变更，无 WSS 快照变化；统计字段只是 HTTP 响应和进程内结果。
- Node/Web 由各自同名 change 承担；本 change 不实现、不修改他仓。
- 兼容：旧 Ctrl 详情缺字段时按未记录；旧 Node 无统计接口时显示不可用，不影响原列表、恢复、清理。
