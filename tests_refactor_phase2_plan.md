# Ctrl Tests Refactor Phase 2 Plan

## 背景与边界

Phase 2 在 Phase 1 的测试安全底座之上推进，主要覆盖 `container` 分类，以及 Phase 1 未覆盖但仍属于 Ctrl 内部验收面的项目。

本阶段仍只处理 `FuxiYu_CtrKernel`，不触碰 `FuxiYu_NodeKernel`。Node 交互统一通过 mock 响应完成：测试验证 Ctrl 是否构造正确调用、正确处理 Node 返回、正确更新本地数据库与权限状态；不把网络连通性、真实 HTTP、真实 Docker 行为作为一般软件验收目标。

默认测试命令仍应排除外部依赖：

```bash
pytest -m "not integration and not legacy"
```

## 阶段 0：Container 测试公共合同与 Node Mock 范式

### 0. 新增的常量定义

建议放入 `test/conftest.py` 或 `test/container/conftest.py`：

- `TEST_CONTAINER_ID = 1001`
- `TEST_CONTAINER_NAME = "test_container_1"`
- `TEST_CONTAINER_IMAGE = "ubuntu:22.04"`
- `TEST_CONTAINER_PORT = 22001`
- `TEST_MACHINE_ID = 2001`
- `TEST_MACHINE_IP = "127.0.0.1"`
- `TEST_ROOT_USER_ID = 3001`
- `TEST_COLLABORATOR_USER_ID = 3002`
- `NODE_SUCCESS_TRUE = {"success": 1}`
- `NODE_SUCCESS_BOOL = {"success": True}`
- `NODE_REMOVE_SUCCESS = {"success": 0}`
- `NODE_REMOVE_NOT_FOUND = {"success": 1}`
- `NODE_REMOVE_FAILED = {"success": 2, "error_reason": "remove_failed"}`
- `NODE_STATUS_ONLINE = {"success": 1, "container_status": "ONLINE"}`
- `NODE_STATUS_OFFLINE = {"success": 1, "container_status": "OFFLINE"}`
- `NODE_STATUS_404 = {"status_code": 404, "error": "not found", "text": "not found"}`
- `NODE_ENDPOINT_404_HTML = {"status_code": 404, "text": "<!doctype html> not found"}`
- `NODE_LAST_SSH_FOUND = {"success": 1, "last_ssh_connect_time": "2026-05-25T10:00:00"}`
- `NODE_LAST_SSH_NOT_FOUND = {"success": 0, "error_reason": "not_found"}`
- `NODE_UNEXPECTED = {"success": 0}`

### 1. 影响的文件范围

- `test/conftest.py`
- `test/container/conftest.py`
- `services/container_tasks.py`
- `blueprints/container_api.py`
- `schemas/container_cleanup_task.py`
- `schemas/container_ssh_refresh_task.py`
- `repositories/containers_repo.py`
- `repositories/usercontainer_repo.py`
- `repositories/container_ssh_login_repo.py`
- `repositories/long_term_container_repo.py`
- `repositories/container_cleanup_reminder_repo.py`

### 2. 函数级收口的完整数据流

Container 测试公共数据流：

1. fixture 创建测试用户、测试机器、测试容器、用户容器绑定。
2. 默认 mock `container_tasks.send()`，不触发真实 `requests.post()`。
3. 默认 mock `container_tasks.signature()` 与 `container_tasks.encryption()`，只保留“被调用且传入 payload 正确”的断言能力。
4. 默认 mock 心跳函数：
   - `container_starting_status_heartbeat`
   - `container_stopping_status_heartbeat`
   - `container_restart_status_heartbeat`
5. 默认 mock `is_machine_online_remote()` 为 `True`，需要测试离线时再局部覆盖。
6. task 测试直接调用 `container_tasks`。
7. API 测试 mock service 层，主要验证 HTTP 合同。
8. schema 测试 mock service 层与 mail 层，验证扫描、提醒、跳过、删除决策。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`mock_node_send(response)`：

- 输入：Node 响应 dict。
- 输出：替换后的 `container_tasks.send()`。
- 内部逻辑：
  - 记录调用参数 `ciphertext/signature/url/timeout`。
  - 返回给定响应。
  - 不进行真实网络请求。

`container_factory(status=ONLINE, machine_status=ONLINE)`：

- 输入：容器状态、机器状态、资源字段、绑定字段。
- 输出：数据库中的容器对象。
- 内部逻辑：
  - 建机器。
  - 建用户。
  - 建容器。
  - 建 ROOT 绑定。
  - 可选建 collaborator 绑定。

`assert_no_real_node_call`：

- 输入：monkeypatch。
- 输出：无。
- 内部逻辑：
  - 若测试未显式 mock `send()` 或 `requests.post()`，任何真实网络调用直接失败。

### 4. 测试用例的构建描述

基础测试：

- `test_container_fixture_creates_root_binding`
- `test_node_send_mock_records_url_and_payload`
- `test_default_container_tests_do_not_call_requests_post`
- `test_container_heartbeats_are_mocked_by_default`
- `test_machine_online_check_is_mocked_by_default`

## 阶段 1：Container 纯辅助函数与 Node 响应处理

### 0. 新增的常量定义

- `SYSLOG_LAST_SSH_SAMPLE = "May 25 10:20:30 sshd[1]: accepted"`
- `LAST_OUTPUT_SAMPLE = "Mon May 25 10:20 still logged in"`
- `ISO_LAST_SSH_SAMPLE = "2026-05-25T10:20:30"`

### 1. 影响的文件范围

- `services/container_tasks.py`
- `test/container/test_container_tasks_helpers.py`
- `test/container/test_container_tasks_node_errors.py`

### 2. 函数级收口的完整数据流

辅助函数数据流：

1. 输入原始 SSH 时间字符串。
2. `_parse_last_ssh_time()` 尝试按 ISO、syslog、last 输出格式解析。
3. `build_cleanup_info()` 基于解析结果与清理天数计算清理时间、剩余秒数、状态。
4. `_raise_on_node_error()` 将 Node 返回映射为 `NodeServiceError`。
5. `get_full_url()` 拼接 machine ip、Node 中间路径、endpoint。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`_parse_last_ssh_time(raw)`：

- 输入 ISO 字符串：返回对应 `datetime`。
- 输入 syslog 风格 `May 25 10:20:30 ...`：返回当前年份的 `datetime`。
- 输入 `last` 输出片段 `Mon May 25 10:20 ...`：返回当前年份的 `datetime`。
- 输入空值、不可解析字符串：返回 `None`。

`build_cleanup_info(last_ssh_login_time, cleanup_after_days)`：

- 输入不可解析时间：返回 `cleanup_status="unknown"`，`cleanup_at=None`，`seconds_until_cleanup=None`。
- 输入已过期时间：返回 `cleanup_status="due"`，`seconds_until_cleanup=0`。
- 输入未过期时间：返回 `cleanup_status="countdown"`，`cleanup_at` 为 ISO 字符串。
- 内部逻辑重点：
  - `cleanup_after_days <= 0` 时按 1 天处理。

`_raise_on_node_error(res, action)`：

- 输入非 dict：抛 `NodeServiceError(reason="unexpected_response")`。
- 输入包含 `error`：抛 `NodeServiceError(reason=error_reason or "NODE_error")`。
- 输入包含 `error_reason` 且 `success != 1`：抛对应 reason。
- 输入正常响应：不抛异常。

`get_full_url(machine_ip, endpoint)`：

- 输入：`"127.0.0.1"` 与 `"/create_container"`。
- 输出：`http://127.0.0.1{NODE_URL_MIDDLE}/create_container`。

### 4. 测试用例的构建描述

- `test_parse_last_ssh_time_accepts_iso`
- `test_parse_last_ssh_time_accepts_syslog_fragment`
- `test_parse_last_ssh_time_accepts_last_output_fragment`
- `test_parse_last_ssh_time_returns_none_for_empty_or_invalid`
- `test_build_cleanup_info_unknown_when_no_last_ssh`
- `test_build_cleanup_info_due_when_expired`
- `test_build_cleanup_info_countdown_when_not_expired`
- `test_build_cleanup_info_clamps_invalid_cleanup_days_to_one`
- `test_raise_on_node_error_rejects_non_dict`
- `test_raise_on_node_error_maps_network_error`
- `test_raise_on_node_error_maps_error_reason`
- `test_get_full_url_uses_node_middle_path`

## 阶段 2：Container 创建、删除、启动、停止、重启 Task

### 0. 新增的常量定义

- `DEFAULT_CONTAINER_INFO`
- `VALID_PUBLIC_KEY = "ssh-rsa AAAATEST"`
- `LONG_PUBLIC_KEY = "x" * 496`

### 1. 影响的文件范围

- `services/container_tasks.py`
- `repositories/containers_repo.py`
- `repositories/machine_repo.py`
- `repositories/usercontainer_repo.py`
- `utils/Container.py`
- `utils/heartbeat.py`
- `test/container/test_container_tasks_lifecycle.py`

### 2. 函数级收口的完整数据流

创建容器数据流：

1. `Create_container()` 校验操作者机器权限。
2. `_ensure_machine_online_for_operation()` 校验机器存在、非维护、远端在线。
3. 获取机器 IP、Node URL、空闲端口。
4. repository 校验机器、GPU、memory、shared、CPU、名称、镜像、公钥、重复名。
5. 构造 Node payload 并发送 mock Node 请求。
6. Node 成功后写本地容器记录，状态为 `CREATING`。
7. 建 ROOT 绑定，容器内用户名固定为 `root`。
8. 启动创建心跳。
9. 返回 `True`。

删除容器数据流：

1. `remove_container()` 通过 container_id 获取 machine_id。
2. 校验操作者机器权限。
3. 校验机器在线。
4. 向 Node 发送删除请求。
5. Node 返回 success 0 或 1 时，删除本地绑定与容器记录。
6. Node 返回 success 2 或错误时抛异常。

启动/停止/重启数据流：

1. 获取 machine_id，校验操作者机器权限。
2. 校验机器在线。
3. 构造 Node payload。
4. Node 成功后启动对应心跳。
5. restart 额外先将本地容器标记为 `OFFLINE`。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`Create_container(owner_name, machine_id, container, public_key, operator_user_id)`：

- 成功输出：`True`。
- 失败输出：
  - 操作者无机器权限：抛 `NodeServiceError(reason="machine_permission_denied")`。
  - 机器不存在：抛 `NodeServiceError(reason="machine_not_found")`。
  - 机器维护：抛 `NodeServiceError(reason="machine_maintenance")`。
  - 机器远端离线：抛 `NodeServiceError(reason="machine_offline")`。
  - repository 校验失败且有 `error_reason`：抛对应 `NodeServiceError`。
  - ValueError 校验失败：抛 `NodeServiceError(reason="invalid_payload")` 或原 ValueError。
  - Node 返回失败：抛 `NodeServiceError(reason=error_reason or "unexpected_response")`。
  - 心跳启动异常：返回 `False`。
- 内部逻辑重点：
  - Node 成功前不得写本地容器。
  - 本地容器初始状态为 `CREATING`。
  - ROOT 绑定 username 必须是 `root`。

`remove_container(container_id, operator_user_id)`：

- 成功输出：
  - Node `{"success": 0}`：`True`。
  - Node `{"success": 1}`：`True`，本地仍清理。
- 失败输出：
  - 容器不存在或无 machine：抛 `ValueError`。
  - 操作者无机器权限：抛 `NodeServiceError(reason="machine_permission_denied")`。
  - Node `{"success": 2}`：抛 `NodeServiceError(reason="remove_failed")`。
- 内部逻辑重点：
  - 删除成功后调用 `remove_binding(..., all=True)` 与 `delete_container()`。

`start_container(container_id, operator_user_id)`：

- 成功输出：`True`，调用 `container_starting_status_heartbeat()`。
- 失败输出：Node 非成功时抛 `NodeServiceError(reason="start_failed")`。

`stop_container(container_id, operator_user_id)`：

- 成功输出：`True`，调用 `container_stopping_status_heartbeat()`。
- 失败输出：Node 非成功时抛 `NodeServiceError(reason="stop_failed")`。

`restart_container(container_id, operator_user_id)`：

- 成功输出：`True`，先更新本地状态为 `OFFLINE`，再调用 `container_restart_status_heartbeat()`。
- 失败输出：Node 非成功时抛 `NodeServiceError(reason="restart_failed")`。

### 4. 测试用例的构建描述

- `test_create_container_success_sends_node_then_creates_db_record_and_root_binding`
- `test_create_container_denies_inaccessible_machine`
- `test_create_container_rejects_machine_not_found`
- `test_create_container_rejects_machine_maintenance`
- `test_create_container_rejects_machine_offline`
- `test_create_container_rejects_invalid_resource_payload`
- `test_create_container_rejects_duplicate_name_before_node_write`
- `test_create_container_node_failure_does_not_create_local_record`
- `test_create_container_heartbeat_failure_returns_false_after_local_write`
- `test_remove_container_success_deletes_bindings_and_container`
- `test_remove_container_node_not_found_still_deletes_local_record`
- `test_remove_container_node_failed_raises_and_keeps_local_record`
- `test_start_container_success_starts_heartbeat`
- `test_stop_container_success_starts_heartbeat`
- `test_restart_container_success_marks_offline_and_starts_heartbeat`
- `test_start_stop_restart_denies_inaccessible_machine`

## 阶段 3：Container 协作者、角色、长期容器 Task

### 0. 新增的常量定义

- `ROLE_ROOT = "ROOT"`
- `ROLE_COLLABORATOR = "COLLABORATOR"`
- `LONG_TERM_LIMIT = 1`

### 1. 影响的文件范围

- `services/container_tasks.py`
- `repositories/usercontainer_repo.py`
- `repositories/long_term_container_repo.py`
- `repositories/machine_permission_repo.py`
- `repositories/user_repo.py`
- `test/container/test_container_tasks_collaborators.py`
- `test/container/test_container_tasks_long_term.py`

### 2. 函数级收口的完整数据流

协作者数据流：

1. 操作前通过 machine_id 校验机器权限。
2. 机器必须在线。
3. 容器必须在线。
4. 用户名必须通过 sanitizer。
5. 向 Node 发送 mock 请求。
6. Node 成功后更新本地绑定。

长期容器数据流：

1. `set_long_term_container()` 解析 container_id。
2. 查询容器与绑定。
3. 操作者必须是 ROOT owner 或 operator。
4. 设置长期容器时，逐个 ROOT owner 检查长期容器上限。
5. 未超限则写入 long-term 表。
6. 取消长期容器时删除 long-term 表记录。
7. 返回长期容器状态、剩余额度、阻塞用户。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`add_collaborator(container_id, user_id, role, operator_user_id)`：

- 成功输出：`True`，新增绑定。
- 失败输出：
  - role 为 ROOT：返回 `False`，不得调用 Node。
  - 容器非 ONLINE：抛 `NodeServiceError(reason="container_offline")`。
  - 操作者无机器权限：抛 `NodeServiceError(reason="machine_permission_denied")`。
  - Node 失败：抛 `NodeServiceError(reason=error_reason or "add_failed")`。
- 内部逻辑重点：
  - collaborator 的容器内用户名使用系统用户名。

`remove_collaborator(container_id, user_id, operator_user_id)`：

- 成功输出：`True`，删除绑定。
- 失败输出：
  - ROOT owner 绑定：返回 `False`，不得删除 ROOT。
  - 容器非 ONLINE：抛 `NodeServiceError(reason="container_offline")`。
  - Node 失败：抛 `NodeServiceError(reason=error_reason or "remove_failed")`。

`update_role(container_id, user_id, updated_role, operator_user_id)`：

- 成功输出：`True`，更新绑定。
- 内部逻辑重点：
  - 变更为 ROOT 时，容器内用户名强制改为 `root`。
  - 其他角色使用系统用户名。

`set_long_term_container(container_id, is_long_term, operator_user_id)`：

- 成功输出：
  - `container_id`
  - `is_long_term`
  - `long_term_container_can_enable`
  - `long_term_container_blocked_user_ids`
  - `long_term_container_remaining_by_user`
- 失败输出：
  - container_id 非法：抛 `NodeServiceError(reason="invalid_payload")`。
  - 容器不存在：抛 `NodeServiceError(reason="container_not_found")`。
  - 非 ROOT owner 且非 operator：抛 `NodeServiceError(reason="container_permission_denied")`。
  - 任一 ROOT owner 达上限：抛 `NodeServiceError(reason="long_term_limit_reached")`。
- 内部逻辑重点：
  - operator 只绕过“操作者是否 owner”的权限检查，不绕过长期容器上限。
  - 统计依据是 ROOT owner，不按普通成员统计。

### 4. 测试用例的构建描述

- `test_add_collaborator_success_adds_binding_after_node_success`
- `test_add_collaborator_rejects_root_role_without_node_call`
- `test_add_collaborator_rejects_offline_container`
- `test_add_collaborator_denies_inaccessible_machine`
- `test_remove_collaborator_success_removes_binding_after_node_success`
- `test_remove_collaborator_rejects_root_owner`
- `test_update_role_success_updates_binding`
- `test_update_role_to_root_sets_container_username_root`
- `test_set_long_term_success_for_root_owner`
- `test_set_long_term_success_for_operator_on_owned_container`
- `test_set_long_term_rejects_non_owner_non_operator`
- `test_set_long_term_rejects_when_root_owner_limit_reached`
- `test_unset_long_term_removes_record`
- `test_build_long_term_state_blocks_only_when_not_already_long_term`

## 阶段 4：Container 信息查询、状态刷新、SSH 时间

### 0. 新增的常量定义

- `CLEANUP_AFTER_DAYS = 7`
- `SSH_RECORD_TIME = "2026-05-25T10:00:00"`

### 1. 影响的文件范围

- `services/container_tasks.py`
- `repositories/container_ssh_login_repo.py`
- `repositories/containers_repo.py`
- `repositories/usercontainer_repo.py`
- `test/container/test_container_tasks_information.py`
- `test/container/test_container_tasks_ssh.py`

### 2. 函数级收口的完整数据流

详情查询数据流：

1. `get_container_detail_information()` 读取本地容器。
2. 如机器 offline/maintenance，跳过 Node 状态检查。
3. 如机器 online，调用 `get_container_status()`。
4. Node 返回 404 时，清理本地绑定与容器，并抛 `ValueError`。
5. Node 返回状态时尝试更新本地状态。
6. 汇总机器 IP、资源、绑定、长期容器状态并返回。

列表查询数据流：

1. `list_all_container_bref_information()` 根据操作者权限过滤机器与容器。
2. operator 可按任意 user_id/machine_id 查询。
3. 普通用户只可见自己绑定且机器授权范围内的容器。
4. 对 online 机器执行 Node 状态检查。
5. 404 容器本地清理并跳过返回。
6. 读取 SSH 记录并计算清理倒计时。
7. 返回 containers、total_page，可选长期容器余量。

SSH 时间数据流：

1. `get_container_last_ssh_login_time()` 查询容器和机器 IP。
2. 构造 `/container_last_ssh_time` Node 请求。
3. Node 明确 `error_reason="not_found"` 时返回 `None` 并落库。
4. Node 成功时返回字符串并落库。
5. Node endpoint HTML 404 时抛 `node_endpoint_not_found`。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`get_container_detail_information(container_id)`：

- 成功输出：dict，包含 `container_id/name/image/machine_id/machine_ip/status/resources/owners/accounts/long_term_state`。
- 失败输出：
  - 本地容器不存在：抛 `ValueError("Container not found")`。
  - Node 404：删除本地记录后抛 `ValueError`。
- 内部逻辑重点：
  - Node 网络错误不应阻止返回本地信息。
  - 机器 offline/maintenance 时不做 Node 容器状态检查。

`list_all_container_bref_information(machine_id, request_user_id, page_number, page_size, user_id=None)`：

- 成功输出：`{"containers": list, "total_page": int}`。
- 当 `user_id is not None` 时额外返回：
  - `long_term_container_remaining`
  - `long_term_container_limit`
- 内部逻辑重点：
  - 普通用户使用 `request_user_id` 做可见性限制。
  - Node 404 触发本地清理并跳过返回。
  - 每个容器包含 SSH 清理信息与长期容器状态。

`get_container_last_ssh_login_time(container_id, timeout=5.0)`：

- 成功输出：
  - Node 返回 SSH 时间：时间字符串。
  - Node 明确无记录：`None`。
- 失败输出：
  - container_id 非法、本地容器不存在、机器查询失败：`None`。
  - endpoint HTML 404：抛 `NodeServiceError(reason="node_endpoint_not_found")`。
  - 其他 Node 错误：抛对应 `NodeServiceError`。
- 内部逻辑重点：
  - 成功与明确 not_found 都要 upsert SSH 记录。

### 4. 测试用例的构建描述

- `test_get_container_detail_success_skips_node_when_machine_offline`
- `test_get_container_detail_updates_status_when_node_returns_status`
- `test_get_container_detail_node_404_deletes_local_container_and_raises`
- `test_get_container_detail_ignores_node_network_error`
- `test_list_container_bref_operator_can_filter_by_user`
- `test_list_container_bref_non_operator_filters_by_machine_permission`
- `test_list_container_bref_node_404_removes_and_skips_container`
- `test_list_container_bref_includes_cleanup_info_from_ssh_record`
- `test_list_container_bref_includes_long_term_remaining_when_user_filter_present`
- `test_get_last_ssh_time_success_persists_record`
- `test_get_last_ssh_time_not_found_persists_none`
- `test_get_last_ssh_time_endpoint_404_raises_node_endpoint_not_found`
- `test_get_last_ssh_time_invalid_container_id_returns_none`

## 阶段 5：Container API 合同测试

### 0. 新增的常量定义

- `CONTAINER_API_HEADERS = {"token": TEST_AUTH_TOKEN}`
- `CONTAINER_API_OPERATOR_HEADERS = {"token": TEST_OPERATOR_TOKEN}`

### 1. 影响的文件范围

- `blueprints/container_api.py`
- `services/container_tasks.py`
- `repositories/authentications_repo.py`
- `repositories/containers_repo.py`
- `test/container/test_container_api_lifecycle.py`
- `test/container/test_container_api_collaborators.py`
- `test/container/test_container_api_information.py`
- `test/container/test_container_api_long_term.py`

### 2. 函数级收口的完整数据流

Container API 数据流：

1. client 发送 token 与 JSON。
2. blueprint 校验 token。
3. blueprint 解析 payload 并做轻量类型检查。
4. blueprint 调用 container service。
5. blueprint 将返回值或异常映射为 HTTP status 与 JSON。

本阶段 API 测试 mock service 层，不验证数据库细节。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`POST /api/containers/create_container`：

- 输出：
  - token 无效：401。
  - payload 非法：400，`invalid_payload`。
  - duplicate：409。
  - NodeServiceError：按 reason 映射。
  - service 返回 False：500，`create_failed`。
  - 成功：200。

`POST /api/containers/delete_container`：

- 输出：
  - token 无效：401。
  - Node not_found：404。
  - service 返回 False：500。
  - 成功：200。

`POST /api/containers/start_container|stop_container|restart_container`：

- 输出：
  - token 无效：401。
  - NodeServiceError 当前返回 500。
  - 其他带 reason 异常按 `REASON_STATUS_MAP`。
  - 成功：200。

`POST /api/containers/set_long_term_container`：

- 输出：
  - token 无效：401。
  - 缺字段：400。
  - container_id 非法：400。
  - is_long_term 非 bool：400。
  - container_not_found：404。
  - container_permission_denied：403。
  - long_term_limit_reached：409。
  - 成功：200。

`POST /api/containers/add_collaborator|remove_collaborator|update_role`：

- 输出：
  - token 无效：401。
  - container_offline：400。
  - service 返回 False：500。
  - 成功：201 或 200。

`POST /api/containers/get_container_detail_information`：

- 输出：
  - token 无效：401。
  - service 抛 ValueError：404。
  - 成功：200。

`POST /api/containers/container_status`：

- 输出：
  - token 无效：401。
  - 缺 container_name 或 machine_id：200，`container_status=None`。
  - 不存在容器：200，`container_status=None`。
  - 成功：200，返回状态字符串。

`POST /api/containers/refresh_last_ssh_login_time`：

- 输出：
  - token 无效：401。
  - container_id 非法：400。
  - 容器不存在：404。
  - NodeServiceError：按 reason 映射。
  - 成功：200，返回 SSH 与 cleanup 信息。

`POST /api/containers/list_all_container_bref_information`：

- 输出：
  - token 无效：401。
  - service 异常：按 reason 映射，默认 500。
  - 成功：200。
  - 当请求带 user_id 时，payload 包含长期容器余量与上限。

### 4. 测试用例的构建描述

- `test_create_container_api_requires_token`
- `test_create_container_api_rejects_invalid_payload`
- `test_create_container_api_duplicate_returns_409`
- `test_create_container_api_machine_permission_denied_returns_403`
- `test_create_container_api_success`
- `test_delete_container_api_not_found_returns_404`
- `test_delete_container_api_success`
- `test_start_stop_restart_api_success`
- `test_set_long_term_api_validates_required_fields`
- `test_set_long_term_api_maps_limit_to_409`
- `test_set_long_term_api_success`
- `test_add_collaborator_api_container_offline_returns_400`
- `test_add_collaborator_api_success_returns_201`
- `test_remove_collaborator_api_success`
- `test_update_role_api_success`
- `test_get_container_detail_api_not_found`
- `test_get_container_detail_api_success`
- `test_container_status_api_missing_fields_returns_none`
- `test_container_status_api_success`
- `test_refresh_last_ssh_login_time_api_node_endpoint_missing_returns_502`
- `test_refresh_last_ssh_login_time_api_success`
- `test_list_container_bref_api_includes_long_term_limit_when_user_filter_present`

## 阶段 6：容器 SSH 刷新、自动清理、邮件提醒

### 0. 新增的常量定义

- `DEFAULT_CLEANUP_AFTER_DAYS = 7`
- `REMINDER_HOURS = "72,24,12"`
- `REMINDER_EMAIL = "owner@bjtu.edu.cn"`

### 1. 影响的文件范围

- `schemas/container_ssh_refresh_task.py`
- `schemas/container_cleanup_task.py`
- `repositories/container_ssh_login_repo.py`
- `repositories/container_cleanup_reminder_repo.py`
- `repositories/long_term_container_repo.py`
- `services/container_tasks.py`
- `utils/mail.py`
- `test/container/test_container_ssh_refresh_task.py`
- `test/container/test_container_cleanup_task.py`
- `test/container/test_container_cleanup_reminders.py`

### 2. 函数级收口的完整数据流

SSH 刷新数据流：

1. `refresh_all_containers_last_ssh_login_time_once()` 分页列出容器。
2. 对每个容器调用 `get_container_last_ssh_login_time(c.id)`。
3. 单个容器失败只打印，不中断其他容器。

清理扫描数据流：

1. `cleanup_expired_containers_once(cleanup_after_days)` 确保 reminder 表存在。
2. 遍历 `ContainerSSHLogin` 记录。
3. 对长期容器跳过清理。
4. 计算 cleanup info。
5. 对 countdown 容器尝试发送提醒。
6. 对 due 容器打印 restore snapshot。
7. 调用 `remove_container(container_id=cid)`。
8. 单容器异常不影响其他记录。

提醒数据流：

1. `_parse_reminder_hours()` 解析配置。
2. `_send_cleanup_reminders_if_needed()` 只处理 countdown。
3. 根据 seconds_left 选择仍有效的最近提醒阈值。
4. 构造 restore snapshot。
5. 查询 ROOT owner 邮箱。
6. 已发送过同一 threshold/cleanup_at/email 则跳过。
7. 邮件发送成功后 mark_sent。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`refresh_all_containers_last_ssh_login_time_once(page_size=200)`：

- 输入：分页大小。
- 输出：无。
- 内部逻辑重点：
  - 多页遍历直到返回空或最后一页。
  - 单容器异常不终止整体刷新。

`cleanup_expired_containers_once(cleanup_after_days)`：

- 输入：清理天数。
- 输出：无。
- 内部逻辑重点：
  - `cleanup_after_days <= 0` 按 1。
  - 长期容器必须跳过。
  - due 容器删除前必须打印 restore snapshot。
  - countdown 容器只提醒，不删除。

`_parse_reminder_hours(raw)`：

- 输入：`"72,24,12"`。
- 输出：`[72, 24, 12]`。
- 内部逻辑重点：
  - 非法项忽略。
  - 去重。
  - 降序返回。

`_send_cleanup_reminders_if_needed(container_id, info, app)`：

- 输入：countdown cleanup info。
- 输出：无。
- 内部逻辑重点：
  - 无 ROOT owner email 时跳过。
  - 已发送同一 reminder_key 时跳过。
  - 邮件发送失败不 mark_sent。

`start_container_cleanup_scheduler(app, interval_seconds)` 与 `start_container_ssh_refresh_scheduler(app, interval_seconds)`：

- 输入：Flask app 与间隔。
- 输出：thread。
- 内部逻辑重点：
  - 同一 app 已有存活线程时返回已有线程。
  - 测试默认不启动真实 scheduler；只用显式 scheduler 单测验证去重逻辑，且需要 stop_event 收尾。

### 4. 测试用例的构建描述

- `test_refresh_all_containers_last_ssh_login_time_pages_until_empty`
- `test_refresh_all_containers_last_ssh_login_time_continues_after_single_failure`
- `test_cleanup_expired_containers_skips_long_term`
- `test_cleanup_expired_containers_sends_reminder_for_countdown`
- `test_cleanup_expired_containers_removes_due_container_after_snapshot`
- `test_cleanup_expired_containers_continues_after_remove_failure`
- `test_parse_reminder_hours_filters_invalid_and_deduplicates`
- `test_send_cleanup_reminder_skips_non_countdown`
- `test_send_cleanup_reminder_skips_without_owner_email`
- `test_send_cleanup_reminder_skips_when_already_sent`
- `test_send_cleanup_reminder_marks_sent_after_mail_success`
- `test_send_cleanup_reminder_does_not_mark_sent_after_mail_failure`
- `test_cleanup_scheduler_returns_existing_thread_when_alive`
- `test_ssh_refresh_scheduler_returns_existing_thread_when_alive`

## 阶段 7：其他 Ctrl 未测项目补齐

### 0. 新增的常量定义

无。沿用 Phase 1 与 Phase 2 的 fixture 常量。

### 1. 影响的文件范围

- `repositories/authentications_repo.py`
- `repositories/registration_code_repo.py`
- `repositories/container_cleanup_reminder_repo.py`
- `repositories/container_ssh_login_repo.py`
- `utils/mail.py`
- `utils/logging_config.py`
- `config.py`
- `test/repository/`
- `test/utils/`
- `test/config/`

### 2. 函数级收口的完整数据流

未测项目数据流：

1. repository 测试使用隔离测试库。
2. mail 测试只 mock SMTP，不发送真实邮件。
3. logging config 测试只验证 handler 装配，不写生产日志。
4. config 测试只验证 env 解析与默认值，不读取生产敏感配置。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`authentications_repo`：

- 创建 token 后 `is_token_valid(token)` 为真。
- 过期 token 为假。
- 删除 token 后为假。
- `get_user_id_by_token(token)` 返回绑定 user_id。

`registration_code_repo`：

- 创建 code 后，正确 code 在过期前可验证。
- 错误 code 不可验证。
- 过期 code 不可验证。
- 同邮箱重复创建时按现有 repository 合同更新或新增，测试需固化现状。

`container_ssh_login_repo`：

- upsert 新记录成功。
- 同 machine/container 再 upsert 会更新 last time 与 updated_at。
- get missing 返回 None。

`container_cleanup_reminder_repo`：

- `ensure_table()` 可重复调用。
- `mark_sent()` 后 `was_sent()` 为真。
- 不同 cleanup_at、email、reminder_key 互不串扰。

`utils.mail.send()`：

- SMTP 成功：返回 `{"ok": True}`。
- SMTP 异常：返回 `{"ok": False, ...}`。
- 缺必要配置：按现有行为返回失败或跳过，测试需固化。

`utils.logging_config.configure_daily_logging(app)`：

- 输入 Flask app。
- 输出无。
- 内部逻辑重点：
  - 不重复添加同类 handler。
  - 测试中日志路径应指向临时目录。

`config.py`：

- 输入 env var。
- 输出 config class/value。
- 内部逻辑重点：
  - `CONTAINER_CLEANUP_AFTER_DAYS`
  - `CONTAINER_CLEANUP_REMINDER_HOURS`
  - `LONG_TERM_CONTAINER_LIMIT`
  - 数据库 URI
  - CORS origins

### 4. 测试用例的构建描述

- `test_auth_repo_create_validate_delete_token`
- `test_auth_repo_expired_token_is_invalid`
- `test_auth_repo_get_user_id_by_token`
- `test_registration_code_repo_verify_success`
- `test_registration_code_repo_rejects_wrong_code`
- `test_registration_code_repo_rejects_expired_code`
- `test_container_ssh_login_repo_upsert_insert_and_update`
- `test_container_cleanup_reminder_repo_mark_and_check_sent`
- `test_container_cleanup_reminder_repo_separates_threshold_cleanup_at_and_email`
- `test_mail_send_success_with_mock_smtp`
- `test_mail_send_failure_with_mock_smtp_exception`
- `test_logging_config_does_not_duplicate_handlers`
- `test_config_reads_cleanup_and_long_term_defaults`
- `test_config_reads_env_overrides`

## 阶段 8：旧 Container 测试迁移与封存

### 0. 新增的常量定义

建议沿用 Phase 1 markers：

- `unit`
- `api`
- `db`
- `integration`
- `legacy`

### 1. 影响的文件范围

- `pytest.ini`
- `test/test_api_web_containers.py`
- `test/test_container_sql.py`
- `test/test_mail.py`
- 新目录：
  - `test/container/`
  - `test/repository/`
  - `test/utils/`
  - `test/config/`

### 2. 函数级收口的完整数据流

迁移数据流：

1. 新 container tests 先落地。
2. 对照旧测试逐条确认覆盖关系。
3. 已覆盖旧测试删除。
4. 暂时保留但可能触真实 Node/邮件/库的旧测试标记为 `legacy` 或 `integration`。
5. 默认命令只跑安全测试。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

默认命令：

- 输入：`pytest -m "not integration and not legacy"`。
- 输出：只执行安全、可在业务运行时执行的测试。

旧测试封存规则：

- 任何真实 Node 操作必须 `integration`。
- 任何真实邮件必须 `integration`。
- 任何无法证明使用隔离测试库的 SQL 测试必须 `legacy`。
- 被新测试覆盖的旧测试不得长期双轨保留。

### 4. 测试用例的构建描述

迁移检查清单：

- `test/test_api_web_containers.py`
  - 生命周期 API 迁移到 `test/container/test_container_api_lifecycle.py`。
  - 协作者 API 迁移到 `test/container/test_container_api_collaborators.py`。
  - 信息查询 API 迁移到 `test/container/test_container_api_information.py`。

- `test/test_container_sql.py`
  - 创建/删除/启动/停止/重启 task 迁移到 `test_container_tasks_lifecycle.py`。
  - 协作者/角色/长期容器 task 迁移到对应新文件。
  - 真实 Node 操作不进入默认测试集。

- `test/test_mail.py`
  - 真实 SMTP 测试保持 `integration`。
  - mock SMTP 单测迁移到 `test/utils/test_mail.py`。

## 阶段验收顺序

1. 完成阶段 0，确认 container 测试不会真实访问 Node。
2. 完成阶段 1，固定时间解析、清理计算、Node 错误映射。
3. 完成阶段 2，固定容器生命周期 task 合同。
4. 完成阶段 3，固定协作者、角色、长期容器权限与限额合同。
5. 完成阶段 4，固定详情、列表、SSH 时间与清理信息合同。
6. 完成阶段 5，固定 container API 错误码与 payload 映射。
7. 完成阶段 6，固定自动 SSH 刷新、清理、提醒逻辑。
8. 完成阶段 7，补齐 repository、utils、config 的低风险单测。
9. 完成阶段 8，迁移或封存旧 container 测试。

## 本阶段不做的事

- 不验证真实 Node 网络连通性。
- 不验证真实 Docker 行为。
- 不发送真实邮件。
- 不使用生产库或开发库。
- 不把前端行为纳入 Ctrl 测试范围。
