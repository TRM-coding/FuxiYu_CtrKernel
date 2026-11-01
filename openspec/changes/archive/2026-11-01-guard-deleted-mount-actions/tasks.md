# Tasks

## 1. 新鲜探测 helper 与错误映射

- [x] 1.1 在 `services/container_module/mount_usage.py` 增加只读 `probe_mount_path(machine_id, mount_path)` 与 `classify_mount_path_state`：解析机器端点，调用 Node `POST /api/check_mount_usage` 单路径，投影 `present`/`missing`/`permission_denied`/`invalid_path`/`node_*`；`pending`/成功/du 类错误视为 present，只有 per-path `not_found` 视为 missing；不写 DB、不依赖 `deleted_id`。验证：新增单测覆盖 pending、success、路径门禁错误、du 测量错误、传输错误和旧 Node；SQL 捕获无 INSERT/UPDATE/DELETE。
- [x] 1.2 在 `services/container_module/exceptions.py` 的 `SAFE_REASON_CODES` 与 `api/container_api.py` 的 `REASON_STATUS_MAP` 增加 `permission_denied`、`invalid_path`、`node_unsupported`、`node_timeout`、`node_unavailable`、`node_bad_response`，按 design 表映射 403/400/502/504/503/502；复用既有 `container_exists`（409）表示原容器仍有效，不新增平行 reason。验证：单测断言新 reason 不会被 `safe_reason` 降级为 `create_failed`，`container_exists` 仍返回 409，且各 reason 返回 design 表所列状态码。

## 2. 恢复动作 guard

- [x] 2.1 在 `resurrect_container` 的 `_load_restore_target` 成功之后、`_load_restore_accounts`/`_resolve_restore_image` 之前调用 `_ensure_restore_mount_source`；任何非 `present` 状态都必须阻断：`missing` 抛 `data_not_recoverable`，`permission_denied`/`invalid_path` 抛各自 reason，`node_unsupported`/`node_timeout`/`node_unavailable`/`node_bad_response` 抛各自可重试 reason；全部保留快照与 cleanup 记录，MUST NOT 继续 `Create_container`、消费快照、写成功审计或返回凭据。同时保留既有 `_ensure_create_target` 守卫：原容器行存在且 `is_valid=true` 时抛既有 `container_exists`，并在任何 Node 创建/落库/快照消费前阻断。验证：mock Node 的 present/missing/permission/invalid/旧 Node/超时/离线结果，断言非 present 分支原容器行仍为已删除、快照与 cleanup 行仍在、无 `create_container` 调用、无成功 op-log、响应无凭据；原行 `is_valid=true` 时以 `container_exists` 拒绝且无副作用。
- [x] 2.2 补充恢复链路测试，覆盖 `not_found` 拒绝、权限/非法路径区分、旧 Node/离线/超时/坏响应阻断且不冒充 `not_found`、原容器 `is_valid=true` 以 `container_exists` 拒绝、`mount_cleaned=true` 仍在探测前拒绝、检查通过后按原内容来源恢复。验证：`pytest test/container/test_deleted_containers.py test/container/test_restore_long_term_capacity.py -q` 通过。

## 3. 手动清理动作 guard

- [x] 3.1 在 `clean_mount_path` 增加 `verify_mount_path: bool = False`，仅 `clean_deleted_container_mount` 传 `True`；在 `_clean_mount_path_impl` 的已清理幂等分支之后、请求 Node `/clean_mount` 之前先读取原容器行：原行存在且 `is_valid=true` 时抛既有 `container_exists`，保留记录并直接返回；原行不存在或 `is_valid=false` 时才执行 `_ensure_manual_clean_mount_path`。路径检查 `missing` 抛 `not_found`，`permission_denied`/`invalid_path` 抛各自 reason，`node_*` 原样上抛；失败时不调用 `/clean_mount`、不写 `cleaned_at`、不同步 `mount_cleaned`、不写成功审计。验证：手动入口 mock 各状态，断言活容器被 `container_exists` 拒绝、其余失败记录状态不变且失败审计恰好一条；自动/定时/磁盘升级入口默认不触发探测。
- [x] 3.2 补充清理链路测试，覆盖手动 present 成功、`not_found` 拒绝且保留 `cleaned_at=null`/`mount_cleaned=false`、原容器 `is_valid=true` 以 `container_exists` 拒绝且不请求 Node、权限/非法路径/网络/旧 Node 区分、已清理幂等不触发探测、自动与升级清理维持既有语义。验证：`pytest test/container/test_deleted_containers.py test/container/test_container_mount_cleanup_task.py -q` 通过。

## 4. 已删除列表字段

- [x] 4.1 在 `schemas/container.py` 的 `DeletedContainerRecord` 增加 `original_container_is_valid: bool | None = None`，在 `serialize_deleted_container_record` 用 `context["container"].is_valid` 投影；原行缺失时为 `null`，MUST NOT 用 `mount_cleaned`/`data_recoverable` 替代。验证：更新 `test/container/test_deleted_validity_projection.py` 覆盖 true/false/null，并断言响应模型接受该字段。
- [x] 4.2 补充列表 API/已删除容器测试，断言字段与原容器行 `include_invalid=True` 读取一致，列表读取不修改容器行、恢复快照或清理记录。验证：`pytest test/container/test_deleted_containers.py test/container/test_anvil_cleanup_contracts.py -q` 通过；检查无数据库模型列新增或迁移文件。

## 5. 集成与规格验证

- [x] 5.1 运行定向 Ctrl 安全套件：`pytest test/container/test_deleted_containers.py test/container/test_deleted_mount_usage.py test/container/test_deleted_validity_projection.py test/container/test_container_mount_cleanup_task.py test/container/test_restore_long_term_capacity.py -q`。验证：全部通过，不触真实 Node/DB/SMTP。
- [x] 5.2 回放 Node `/api/check_mount_usage` 契约：pending、success、`not_found`、`permission_denied`、`invalid_path`、du 类错误、404/405、超时、5xx、坏响应；验证：恢复与手动清理在 unknown（旧 Node/离线/超时/坏响应）下均阻断且不创建/不消费快照，明确拒绝分支不写 `mount_cleaned`/`cleaned_at`；原容器 `is_valid=true` 时恢复与手动清理均以 `container_exists` 拒绝；自动/升级清理不触发探测。
- [x] 5.3 运行 `openspec validate guard-deleted-mount-actions --strict` 与 `git diff --check`；验证：规格校验通过，且本变更没有数据库模型/迁移改动、没有 Node/Web 代码改动。
