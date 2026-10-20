# Tasks

## 1. 详情字段

- [x] 1.1 在 `_build_container_detail`、服务层 `container_detail_information` 与响应 `ContainerDetailInformation` 中追加可空 `bind_mount_path`，值只取 `container.bind_mount_path`；验证：现有 Ctrl 隔离 SQLite 详情用例断言有值原样返回、空值为 null，且不调用 Node。
- [x] 1.2 补详情契约测试：旧响应缺字段时消费方按未记录，读取不新增/修改 DB 行；验证：测试落在现有 `test/container/` 目录，不新建测试工作流。

## 2. 已删除统计 API

- [x] 2.1 增加 `POST /api/containers/get_deleted_container_mount_usage` 请求/响应模型与端点：`deleted_ids` 为正整数、最多 100；成功响应 `{success:1,usages:[{deleted_id,bytes,measured_at,pending,error}]}` 且不含 path；非法体 400 `invalid_payload`，缺 `container:manage` 403 `insufficient_permission`。验证：现有 Ctrl API 测试目录覆盖形状、上限、403、无挂载/已清理省略、不接受浏览器路径。
- [x] 2.2 实现只读解析：复用现有 `_get_deleted_container_context` 的只读语义，从既有删除快照/清理记录读取 `machine_id`/`mount_path`，按 `machine_id` 定向 Node；不新增机器角色门禁；禁止调用 `resolve_mount_cleanup_request` 或 ensure/adopt/insert/update/delete。验证：现有 Ctrl 测试目录断言不写 `disk_*`/snapshot/cleanup/其他行，缺 `machine_id` 不向其他机器发送。
- [x] 2.3 实现 Ctrl→Node 批量调用：按 `(machine_id, path)` 去重、最多 100、限制并发、短超时；同一路径跨机器分开请求；一机失败不阻塞其他机器。验证：mock Node 覆盖同机同路径一次调用、跨机同路径不混、离线/超时/5xx/坏响应逐 id 回退。
- [x] 2.4 实现严格响应映射与错误契约：按机器和回显 path 逐 `deleted_id` 匹配；成功 `bytes>=0`/真实 UTC `measured_at`/`pending=false`/`error=null`，pending 三 null/true/null，错误三 null/false/稳定原因；404/405→`node_unsupported`，超时→`node_timeout`，离线/连接/5xx→`node_unavailable`，缺 path/形状错/重复 path→`node_bad_response`。验证：现有 Ctrl 测试目录覆盖三态、path 不匹配、旧 Node 404、不得填 0 或假成功。

## 3. 隔离验证与范围

- [x] 3.1 用现有 Ctrl 隔离 SQLite + mock Node 回放：详情路径、当前页 deleted_ids、只读解析、`machine_id` 定向、同路径去重、Node pending/success/error、旧 Node、重复 pending 查询；验证：无 DB 写入、无 `disk_*`/snapshot/cleanup 改写、无周期 WSS 变化，测试不触真实 Node/DB/服务。
- [x] 3.2 对照两个 delta 与 design 做范围核验：无新列/表/JSON/迁移，无 inode/dev/PID/Docker ID 授权，无全盘扫描/全局总计/清理门禁/自动冻结，不改 `clean_mount`；验证：`git diff --check`、新文件空白检查、`openspec validate show-mount-path-and-deleted-usage --strict` 与文件范围审查通过。

## Workflow follow-up

- 本轮按用户实施授权完成代码、测试与任务勾选；不 commit/push，提交与归档由主代理处理。
- 验证：`pytest test/container/test_deleted_mount_usage.py test/container/test_container_api_information.py test/container/test_container_tasks_information.py test/container/test_deleted_containers.py test/test_testing_safety_contract.py -q` 通过 180 项；`openspec validate show-mount-path-and-deleted-usage --strict` 与 `git diff --check` 通过。
- 调度验收：Ctrl→Node 单请求 timeout 5 秒、整批 deadline 8 秒、按机器并发≤8；预算到期保留已完成结果，未完成/排队项返回 `node_timeout` 并取消未启动 future（不新增持久化/状态）。
- Node/Web 由各自同名 change 负责，本 change 不写他仓。

## 主代理最终验收

- 本地 WSL 隔离 SQLite 定向与相关回归共 **227 passed**，包含本变更、详情、已删除列表、测试安全约束、原 WSS 协议回放、磁盘测量和挂载清理入参解析；未使用远程服务。
- `test/container/test_mount_usage_cross_repo.py` 的 3 项回放实际执行：Node HTTP + 临时目录真实 du → Ctrl API 序列化与只读解析 → Web 真实纯函数。SQL 捕获无 INSERT/UPDATE/DELETE；真实成功样本、pending、TTL 命中、目录消失、未知错误均核对，零值与稳定失败使用明确的缓存种子态。
- 主代理收紧已知 `du_failed` 的跨仓断言：必须保留 error/reason，不接受以通用 unavailable 掩盖已支持的契约错误。代码、测试与规格按阶段本地提交，生产部署不属于本轮验收。
