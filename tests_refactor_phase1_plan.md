# Ctrl Tests Refactor Phase 1 Plan

## 背景与边界

本阶段只处理 `FuxiYu_CtrKernel` 内部测试重构，不触碰 `FuxiYu_NodeKernel`。目标不是一次性重写全部测试，而是先把 `user` 与 `machine` 两组 task/API 的测试计划收口，使后续重构可以稳定推进，并避免测试期间误触真实业务数据、后台清理调度、Node 心跳或邮件发送。

现状主要风险：

- 多个测试在 `create_app()` 之后才设置 `TESTING=True`，而 `create_app()` 当前会根据 debug/reloader 条件启动 SSH 刷新与容器清理后台线程。
- 部分 SQL/API 测试直接依赖真实配置库，且 teardown 明确避免 `drop_all`，存在污染开发/生产库的风险。
- API 测试与 task 测试混杂，有些测试验证 HTTP 状态，有些测试实际穿透 repository、数据库甚至外部服务。
- `machine` 相关测试需要明确阻断 Node 通信，只验证 Ctrl 内部决策与调用边界。

## 阶段 0：测试安全底座与目录范式

### 0. 新增的常量定义

建议新增测试专用配置常量，优先放在 `config.py` 或测试配置类中：

- `TESTING = True`
- `DISABLE_BACKGROUND_TASKS = True`
- `SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"` 或测试临时文件库 URI
- `WTF_CSRF_ENABLED = False`，如后续引入表单/CSRF 测试再使用
- `TEST_AUTH_TOKEN = "test-token"`，仅测试 fixture 使用
- `TEST_OPERATOR_TOKEN = "test-operator-token"`，仅测试 fixture 使用

如不希望污染业务配置，也可以放入 `test/conftest.py` 的 `TEST_CONFIG_OVERRIDES`。

### 1. 影响的文件范围

- `__init__.py`
- `config.py`
- `pytest.ini`
- `test/conftest.py`
- `test/user/`
- `test/machine/`
- 旧测试文件：
  - `test/test_api_web.py`
  - `test/test_api_web_machine.py`
  - `test/test_user_sql.py`
  - `test/test_machine_sql.py`

### 2. 函数级收口的完整数据流

测试启动数据流：

1. `pytest` 读取 `test/conftest.py`。
2. `app` fixture 调用 `create_app(config="testing")` 或 `create_app(test_config_overrides)`。
3. `create_app()` 先加载测试配置，再初始化扩展、注册蓝图。
4. `create_app()` 判断 `app.config["DISABLE_BACKGROUND_TASKS"]`，测试环境不启动：
   - `start_container_ssh_refresh_scheduler`
   - `start_container_cleanup_scheduler`
5. `db` fixture 在测试上下文内建表。
6. 每个测试通过事务或表级清理隔离数据。
7. `client` fixture 只负责 Flask HTTP 层调用，不自行创建业务数据。
8. `auth_token`、`operator_token`、`user_factory`、`machine_factory` 等 fixture 统一提供身份与数据。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`create_app(config=None, overrides=None)`：

- 输入：
  - `config`: 配置名，可为 `"testing"`。
  - `overrides`: dict，可覆盖配置项。
- 输出：
  - Flask `app`。
- 内部逻辑：
  - 配置加载必须早于 `db.init_app()` 与后台任务判断。
  - 当 `app.config["TESTING"]` 或 `app.config["DISABLE_BACKGROUND_TASKS"]` 为真时，不启动任何后台线程。
  - 生产路径保持原行为。

`app` fixture：

- 输入：无。
- 输出：已加载测试配置且不会启动后台线程的 Flask app。
- 内部逻辑：
  - 导入所有 model。
  - `db.create_all()`。
  - yield app。
  - 测试库可安全 `drop_all()`，前提是 URI 明确为测试库。

`db_session` fixture：

- 输入：`app` fixture。
- 输出：隔离后的 SQLAlchemy session。
- 内部逻辑：
  - 每个测试前开始事务或清空相关表。
  - 每个测试后 rollback 或 truncate 测试表。
  - 不连接真实业务库。

`mock_external_services` fixture：

- 输入：`monkeypatch`。
- 输出：无显式输出。
- 内部逻辑：
  - 默认 mock 邮件发送。
  - 默认 mock machine heartbeat `send`。
  - 默认 mock `start_machine_maintenance_transition_heartbeat`。
  - 默认 mock 容器清理/SSH 刷新调度启动函数，作为第二道保险。

### 4. 测试用例的构建描述

新增基础设施测试：

- `test_app_factory_testing_does_not_start_background_tasks`
  - 输入：测试配置。
  - 断言：两个 scheduler 启动函数未被调用。
- `test_app_fixture_uses_test_database`
  - 输入：`app` fixture。
  - 断言：数据库 URI 包含 `sqlite` 或明确测试库标记，禁止真实生产库。
- `test_client_fixture_can_access_registered_blueprints`
  - 输入：`client`。
  - 断言：访问一个需要鉴权的 API 返回 401，而不是 404 或 500。

## 阶段 1：User Task 单元测试收口

### 0. 新增的常量定义

- `VALID_REGISTER_EMAIL_DOMAIN = "bjtu.edu.cn"`
- `VALID_REGISTER_CODE = "123456"`
- `DEFAULT_GRADUATION_YEAR = "2026"`
- `TEST_USER_PASSWORD = "Password_123"`

### 1. 影响的文件范围

- `services/user_tasks.py`
- `repositories/user_repo.py`
- `repositories/authentications_repo.py`
- `repositories/registration_code_repo.py`
- `repositories/usercontainer_repo.py`
- `repositories/long_term_container_repo.py`
- `test/user/test_user_tasks_auth.py`
- `test/user/test_user_tasks_profile.py`
- `test/user/test_user_tasks_registration_code.py`

### 2. 函数级收口的完整数据流

注册数据流：

1. 测试输入 `username/email/password/graduation_year`。
2. `Register()` 校验长度、用户名格式、ASCII、用户名重复、邮箱重复。
3. `create_user()` 写入用户。
4. 返回 `(True, User, None)` 或 `(False, error_reason, None)`。

登录数据流：

1. 测试输入 `username/password`。
2. `Login()` 通过 `User.query.filter_by(username=...)` 查询用户。
3. 校验密码 hash。
4. 调用 `authentications_repo.create_auth(token, user.id, expires_at)`。
5. 返回 `(True, User, token)` 或 `(False, error_reason, None)`。

用户信息数据流：

1. `Get_user_detail_information(user_id)` 查询用户。
2. `usercontainer_repo.compute_user_container_counts(user.id)` 计算容器统计。
3. `long_term_container_repo.count_by_user(user.id)` 计算长期容器数量。
4. 返回 `user_detail_information`。

用户列表数据流：

1. `List_all_user_bref_information(page_number, page_size)` 规范化分页参数。
2. `list_users(limit, offset)` 获取用户。
3. 对每个用户计算容器统计与长期容器数量。
4. 返回 `list[user_bref_information]`。

验证码注册数据流：

1. `Request_register_code(email)` 解析邮箱域名。
2. 非允许域名直接返回 `email_domain_not_allowed`。
3. 生成验证码并写入 `registration_code_repo.create_code()`。
4. 调用 `send_mail()`。
5. 返回 `(True, "code_sent")` 或错误 reason。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`Register(username, email, password, graduation_year)`：

- 成功输入：`("u_1", "u_1@bjtu.edu.cn", "Password_123", "2026")`
- 成功输出：`(True, User(username="u_1"), None)`
- 失败输出：
  - 用户名超过 75：`(False, "username_too_long", None)`
  - 邮箱超过 115：`(False, "email_too_long", None)`
  - 用户名含中文、空格、横杠：`(False, "invalid_username", None)`
  - 邮箱或密码含非 ASCII：`(False, "no_none_ascii", None)`
  - 用户名重复：`(False, "username_exists", None)`
  - 邮箱重复：`(False, "email_exists", None)`
- 内部逻辑重点：
  - 用户名校验优先于邮箱/密码 ASCII 校验。
  - 重复检查必须在格式校验之后。
  - 创建用户时密码必须是 hash，不保存明文。

`Login(username, password)`：

- 成功输出：`(True, User, token)`，token 非空且 auth 表存在记录。
- 失败输出：
  - 用户不存在：`(False, "user_not_found", None)`
  - 密码错误：`(False, "password_incorrect", None)`
- 内部逻辑重点：
  - 密码错误不得创建 auth token。
  - token 过期时间应晚于当前 UTC 时间。

`Change_password(user, old_password, new_password)`：

- 成功输出：`True`，旧密码登录失败，新密码登录成功。
- 失败输出：
  - 旧密码错误：`False`。
  - hash 校验异常：`False`。
  - update 异常：`False`。
- 内部逻辑重点：
  - 失败时不得改变原密码。

`Delete_user(user_id)`：

- 成功输出：`True`。
- 失败输出：
  - `remove_user_from_all_containers` 返回 `{"ok": False}`：`False`。
  - 返回 wild containers：抛出携带 `wild_containers` 属性的异常。
- 内部逻辑重点：
  - 必须先解绑容器，再删除用户。
  - wild container 场景不得继续删用户。

`Get_user_detail_information(user_id)`：

- 成功输出：包含 `user_id/username/email/graduation_year/permission/containers/amount_*`。
- 失败输出：
  - 空 user_id、非法 user_id、不存在用户：`None`。
- 内部逻辑重点：
  - 长期容器数量按实际用户 id 调 `long_term_container_repo.count_by_user(user.id)`。

`List_all_user_bref_information(page_number, page_size)`：

- 成功输出：`list[user_bref_information]`。
- 输入规范化：
  - 非法页码或小于等于 0：页码按 1。
  - 非法 page_size 或小于等于 0：page_size 按 10。
- 内部逻辑重点：
  - `offset = (pn - 1) * ps`。
  - 每个用户都应包含长期容器数量。

`Update_user(user_id, **fields)`：

- 成功输出：更新后的 `User` 或 repository 返回值。
- 输入过滤：
  - `permission/password_hash/email` 被忽略。
- 失败输出：
  - 非法用户名：抛 `ValueError("invalid_username")`。
  - 非 ASCII 字段：抛 `ValueError("no_none_ascii")`。
  - 用户名过长：抛 `ValueError`。
- 内部逻辑重点：
  - 禁止通过此 task 修改权限、密码 hash、邮箱。

`Reset_password(user_id)`：

- 成功输出：`"{graduation_year}{username}"`。
- 失败输出：用户不存在返回 `None`。
- 内部逻辑重点：
  - 数据库保存 hash，返回值才是明文临时密码。

`Request_register_code(email)`：

- 成功输出：`(True, "code_sent")`。
- 失败输出：
  - 非允许域名：`(False, "email_domain_not_allowed")`。
  - 写 code 异常：`(False, "code_creation_failed")`。
  - 邮件发送失败：`(False, "mail_send_failed")`。
- 内部逻辑重点：
  - 验证码为 6 位数字字符串。
  - 过期时间约为当前 UTC 后 3 分钟。

`Register_with_code(...)`：

- 成功输出：透传 `Register()` 成功结果。
- 失败输出：
  - 空验证码：`(False, "registration_code_required", None)`。
  - 非允许域名：`(False, "email_domain_not_allowed", None)`。
  - 验证失败：`(False, "registration_code_invalid", None)`。
- 内部逻辑重点：
  - 只有验证码通过后才调用 `Register()`。

### 4. 测试用例的构建描述

建议拆分：

- `test_user_tasks_auth.py`
  - `test_login_success_creates_auth_token`
  - `test_login_user_not_found`
  - `test_login_wrong_password_does_not_create_token`
  - `test_change_password_success`
  - `test_change_password_wrong_old_password_keeps_original`
  - `test_reset_password_success_returns_expected_plain_password_and_saves_hash`
  - `test_reset_password_missing_user_returns_none`

- `test_user_tasks_profile.py`
  - `test_register_success`
  - `test_register_rejects_long_username`
  - `test_register_rejects_long_email`
  - `test_register_rejects_invalid_username`
  - `test_register_rejects_non_ascii_email_or_password`
  - `test_register_rejects_duplicate_username`
  - `test_register_rejects_duplicate_email`
  - `test_delete_user_success_unbinds_before_delete`
  - `test_delete_user_returns_false_when_unbind_fails`
  - `test_delete_user_raises_wild_containers`
  - `test_get_user_detail_information_returns_counts_and_long_term_count`
  - `test_get_user_detail_information_missing_user_returns_none`
  - `test_list_all_user_bref_information_normalizes_pagination_and_returns_counts`
  - `test_update_user_filters_forbidden_fields`
  - `test_update_user_rejects_invalid_username`
  - `test_update_user_rejects_non_ascii_field`

- `test_user_tasks_registration_code.py`
  - `test_request_register_code_success_creates_code_and_sends_mail`
  - `test_request_register_code_rejects_unallowed_domain`
  - `test_request_register_code_handles_create_failure`
  - `test_request_register_code_handles_mail_failure`
  - `test_register_with_code_requires_code`
  - `test_register_with_code_rejects_unallowed_domain`
  - `test_register_with_code_rejects_invalid_code`
  - `test_register_with_code_calls_register_after_verify_success`

## 阶段 2：User API 测试收口

### 0. 新增的常量定义

- `API_TOKEN_HEADER = {"token": TEST_AUTH_TOKEN}`
- `API_OPERATOR_HEADER = {"token": TEST_OPERATOR_TOKEN}`

### 1. 影响的文件范围

- `blueprints/user_api.py`
- `services/user_tasks.py`
- `repositories/authentications_repo.py`
- `repositories/user_repo.py`
- `test/user/test_user_api_auth.py`
- `test/user/test_user_api_profile.py`

### 2. 函数级收口的完整数据流

API 请求数据流：

1. `client` 发送 JSON 与 token header。
2. blueprint 解析 request。
3. blueprint 执行 token 校验。
4. blueprint 调用 `user_tasks`。
5. blueprint 将 task 结果映射为 HTTP status 与 JSON payload。

本阶段 API 测试不验证数据库写入细节，数据库细节留给 task/repository 测试。API 测试应 mock `user_tasks` 与 `authentications_repo`，重点验证 HTTP 合同。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`POST /api/register`：

- 输入：username、email、password、graduation_year、registration_code。
- 输出：
  - 成功：201，`success=1`，返回 `user_id/username/email`。
  - invalid json：400。
  - 缺 username/email/password：400。
  - username/email 重复：409。
  - 其他已知注册失败：400。
  - task 异常：500。
- 内部逻辑重点：
  - 只调用 `Register_with_code()`，不直接调用 `Register()`。

`POST /api/request_register_code`：

- 输出：
  - 成功：200。
  - 缺 email：400，`missing_email`。
  - 非允许域名：400。
  - code 创建或邮件失败：500。

`POST /api/login`：

- 输出：
  - 成功：200，JSON 返回 token，并设置 `auth_token` cookie。
  - invalid json：400。
  - 缺 username/password：400。
  - user_not_found：404。
  - password_incorrect：400。

`GET /api/users/get_user_detail_information`：

- 输出：
  - token 无效：401。
  - 缺 user_id：400。
  - 用户不存在：404。
  - 成功：200，`user_info` 为 dict。

`GET /api/users/list_all_user_bref_information`：

- 输出：
  - token 无效：401。
  - task 异常：500，`list_failed`。
  - 成功：200，返回 users 列表。

`POST /api/users/change_password`：

- 输出：
  - token 无效：401。
  - 缺字段：400。
  - 用户不存在：404。
  - 旧密码错误：400。
  - 成功：200。

`POST /api/users/delete_user`：

- 输出：
  - token 无效：401。
  - 缺 user_id：400。
  - wild containers：400，包含 `wild_containers`。
  - 删除返回 False：404。
  - 成功：200。

`POST /api/users/update_user`：

- 输出：
  - token 无效：401。
  - 缺 user_id/fields：400。
  - `invalid_username`、`no_none_ascii`：400。
  - 用户不存在：404。
  - 成功：200。

### 4. 测试用例的构建描述

建议拆分：

- `test_user_api_auth.py`
  - `test_register_success`
  - `test_register_invalid_json`
  - `test_register_missing_required_fields`
  - `test_register_duplicate_username_returns_409`
  - `test_register_registration_code_required_returns_400`
  - `test_request_register_code_success`
  - `test_request_register_code_missing_email`
  - `test_request_register_code_domain_not_allowed`
  - `test_login_success_sets_cookie`
  - `test_login_user_not_found`
  - `test_login_wrong_password`

- `test_user_api_profile.py`
  - `test_get_user_detail_requires_token`
  - `test_get_user_detail_requires_user_id`
  - `test_get_user_detail_not_found`
  - `test_get_user_detail_success`
  - `test_list_users_requires_token`
  - `test_list_users_success`
  - `test_list_users_task_failure`
  - `test_change_password_success`
  - `test_change_password_wrong_old_password`
  - `test_delete_user_success`
  - `test_delete_user_wild_containers`
  - `test_update_user_success`
  - `test_update_user_invalid_username`

## 阶段 3：Machine Task 单元测试收口

### 0. 新增的常量定义

- `DEFAULT_MACHINE_PAYLOAD`
- `DEFAULT_MACHINE_ID = 1`
- `DEFAULT_MACHINE_IP = "127.0.0.1"`
- `REMOTE_ONLINE_RESPONSE = {"success": 1, "machine_status": "online"}`
- `REMOTE_OFFLINE_RESPONSE = {"success": 1, "machine_status": "offline"}`

### 1. 影响的文件范围

- `services/machine_tasks.py`
- `repositories/machine_repo.py`
- `repositories/machine_permission_repo.py`
- `repositories/user_repo.py`
- `repositories/containers_repo.py`
- `utils/heartbeat.py`
- `test/machine/test_machine_tasks_crud.py`
- `test/machine/test_machine_tasks_status.py`
- `test/machine/test_machine_tasks_permission.py`

### 2. 函数级收口的完整数据流

机器新增数据流：

1. 测试输入机器属性。
2. `Add_machine()` 校验字段长度与 `max_shared_gb`。
3. 调用 `create_machine()`。
4. 返回 `True` 或抛出携带 `error_reason` 的异常。

机器更新数据流：

1. `Update_machine(machine_id, **fields)` 读取机器。
2. 机器不存在返回 `False`。
3. 校验 shared/max_memory 相关字段。
4. 如果当前 online 且请求 maintenance：
   - 不立即写入 `machine_status=maintenance`。
   - 先更新非状态字段。
   - 调用 `start_machine_maintenance_transition_heartbeat(machine_id)`。
5. 其他情况直接 `update_machine(machine_id, **fields)`。
6. 返回 `True`。

机器列表数据流：

1. `List_all_machine_bref_information()` 构造查询、排序、权限过滤。
2. 对每台机器调用 `is_machine_online_remote()`。
3. 根据远端在线状态刷新机器状态。
4. 离线时将机器下属容器标为 offline。
5. 重新读取 latest machine。
6. 返回 `(list[machine_bref_information], total_pages)`。

机器权限数据流：

1. `Add_machine_permission(machine_id, user_id)` 校验机器存在。
2. 校验用户存在。
3. 调用 `machine_permission_repo.add_permission()`。
4. 返回 `True`。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`Add_machine(...)`：

- 成功输出：`True`。
- 失败输出：
  - `machine_name` 长度超过 115：抛 `ValueError`。
  - `gpu_type` 长度超过 115：抛 `ValueError`。
  - `machine_type` 长度超过 255：抛 `ValueError`。
  - `max_shared_gb` 非整数：抛 `ValueError` 且 `error_reason="create_failed"`。
  - `max_shared_gb <= 0`：抛 `ValueError` 且 `error_reason="create_failed"`。
  - `max_memory_gb` 非整数：抛 `ValueError` 且 `error_reason="create_failed"`。
  - `max_shared_gb > max_memory_gb`：抛 `ValueError` 且 `error_reason="create_failed"`。
- 内部逻辑重点：
  - 成功路径必须调用一次 `create_machine()`。

`Remove_machine(machine_id: list[int])`：

- 成功输出：`True`。
- 内部逻辑重点：
  - 对输入列表逐个调用 `delete_machine(id)`。
  - 空列表当前行为为 `True`，测试需固定该合同。

`Update_machine(machine_id, **fields)`：

- 成功输出：`True`。
- 失败输出：
  - 机器不存在：`False`。
  - shared 字段非法：抛 `ValueError` 且 `error_reason="update_failed"`。
- 内部逻辑重点：
  - online -> maintenance 只触发过渡心跳，不直接写 maintenance 状态。
  - online -> maintenance 且有其他字段时，其他字段仍应更新。
  - 非过渡场景直接调用 `update_machine()`。

`Get_detail_information(machine_id)`：

- 成功输出：`machine_detail_information`。
- 失败输出：机器不存在返回 `None`。
- 内部逻辑重点：
  - `machine_type` 与 `machine_status` 输出 `.value`。
  - `containers` 输出容器 id 列表。

`is_machine_online_remote(machine_id, timeout=2.0)`：

- 成功输出：
  - Node 返回 `{"success": 1, "machine_status": "online"}`：`True`。
  - 其他返回：`False`。
- 失败输出：
  - 机器不存在、无 IP、heartbeat 异常：`False`。
- 内部逻辑重点：
  - 只判断远端状态，不写数据库。

`List_all_machine_bref_information(...)`：

- 成功输出：`(machines, total_pages)`。
- 输入：
  - `page_number` 从 0 开始。
  - `page_size` 为分页大小。
  - `machine_name_prefix` 可过滤名称。
  - `sort_by` 支持 `id/machine_name/machine_ip`。
  - 普通 `user_id` 只返回被授权机器。
- 内部逻辑重点：
  - operator 用户绕过机器权限过滤。
  - maintenance 机器在线时保持 maintenance。
  - maintenance 机器离线时刷新为 offline，并标记容器 offline。
  - 非 maintenance 机器在线刷新为 online，离线刷新为 offline。

`Add_machine_permission(machine_id, user_id)`：

- 成功输出：`True`。
- 失败输出：
  - 机器不存在：抛 `ValueError("machine_not_found")`。
  - 用户不存在：抛 `ValueError("user_not_found")`。

`Remove_machine_permission(machine_id, user_id)`：

- 输出：透传 `machine_permission_repo.remove_permission()` 的 bool。

`List_machine_permissions(machine_id)`：

- 输出：`list[int]`。

### 4. 测试用例的构建描述

建议拆分：

- `test_machine_tasks_crud.py`
  - `test_add_machine_success_calls_repo`
  - `test_add_machine_rejects_long_machine_name`
  - `test_add_machine_rejects_long_gpu_type`
  - `test_add_machine_rejects_long_machine_type`
  - `test_add_machine_rejects_non_integer_max_shared`
  - `test_add_machine_rejects_non_positive_max_shared`
  - `test_add_machine_rejects_max_shared_greater_than_max_memory`
  - `test_remove_machine_deletes_each_id`
  - `test_remove_machine_empty_list_returns_true`
  - `test_get_detail_information_success`
  - `test_get_detail_information_missing_machine_returns_none`

- `test_machine_tasks_status.py`
  - `test_update_machine_missing_machine_returns_false`
  - `test_update_machine_regular_update_calls_repo`
  - `test_update_machine_rejects_invalid_shared_size`
  - `test_update_machine_rejects_shared_size_out_of_range`
  - `test_update_machine_rejects_max_shared_greater_than_target_memory`
  - `test_update_machine_online_to_maintenance_starts_transition_without_status_update`
  - `test_is_machine_online_remote_true_when_node_online`
  - `test_is_machine_online_remote_false_when_machine_missing`
  - `test_is_machine_online_remote_false_when_node_offline`
  - `test_is_machine_online_remote_false_when_heartbeat_raises`
  - `test_list_machine_bref_marks_online_machine_online`
  - `test_list_machine_bref_marks_offline_machine_and_containers_offline`
  - `test_list_machine_bref_keeps_maintenance_when_remote_online`
  - `test_list_machine_bref_marks_maintenance_offline_when_remote_offline`
  - `test_list_machine_bref_filters_non_operator_by_machine_permission`
  - `test_list_machine_bref_operator_bypasses_machine_permission`

- `test_machine_tasks_permission.py`
  - `test_add_machine_permission_success`
  - `test_add_machine_permission_machine_not_found`
  - `test_add_machine_permission_user_not_found`
  - `test_remove_machine_permission_returns_repo_result`
  - `test_list_machine_permissions_returns_repo_result`

## 阶段 4：Machine API 测试收口

### 0. 新增的常量定义

- `MACHINE_API_OPERATOR_HEADERS = {"token": TEST_OPERATOR_TOKEN}`
- `MACHINE_API_USER_HEADERS = {"token": TEST_AUTH_TOKEN}`

### 1. 影响的文件范围

- `blueprints/machine_api.py`
- `services/machine_tasks.py`
- `repositories/authentications_repo.py`
- `repositories/user_repo.py`
- `test/machine/test_machine_api_crud.py`
- `test/machine/test_machine_api_permission.py`
- `test/machine/test_machine_api_listing.py`

### 2. 函数级收口的完整数据流

机器 API 通用数据流：

1. `client` 发送 JSON、token header 或 Bearer/cookie。
2. `_resolve_auth_token()` 在需要的接口中提取 token。
3. `authentications_repo.is_token_valid()` 判定登录态。
4. operator 接口额外调用 `user_repo.check_permission()`。
5. blueprint 调用 `machine_service`。
6. blueprint 将 service 返回值或异常映射为 HTTP status 与 JSON payload。

API 测试不连接 Node，不验证心跳细节；所有 machine service 调用均可 monkeypatch。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`POST /api/machines/add_machine`：

- 输出：
  - token 无效：401。
  - 非 operator：403。
  - service 成功：201。
  - `IntegrityError`：409，`duplicate_entry`。
  - 带 `error_reason` 异常：422。
  - 其他异常：500。
  - service 返回 False：500，`create_failed`。

`POST /api/machines/remove_machine`：

- 输出：
  - token 无效：401。
  - 非 operator：403。
  - service 成功：200。
  - service 返回 False：500，`remove_failed`。

`POST /api/machines/update_machine`：

- 输出：
  - token 无效：401。
  - 非 operator：403。
  - service 成功：200。
  - 带 `error_reason` 异常：422。
  - 其他异常：500。
  - service 返回 False：500，`update_failed`。

`POST /api/machines/get_detail_information`：

- 输出：
  - token 无效：401。
  - 机器不存在：404。
  - 成功：200，返回机器详细字段。
- 内部逻辑重点：
  - 当前 payload 未返回 `machine_status`，测试应先固化现状；后续如修 API 再同步更新测试。

`POST /api/machines/list_all_machine_bref_information`：

- 输出：
  - token 无效：401。
  - 成功：200，返回 `machines` 与 `total_pages`。
- 内部逻辑重点：
  - `user_id` 来自 `authentications_repo.get_user_id_by_token(token)`。
  - 调用 service 时必须传入 `user_id`。

`POST /api/machines/add_machine_permission`：

- 输出：
  - token 无效：401。
  - 非 operator：403。
  - 缺 machine_id/user_id：400。
  - `machine_not_found/user_not_found`：404。
  - 成功：200。

`GET /api/machines/list_machine_permissions`：

- 输出：
  - token 无效：401。
  - 缺 machine_id：400。
  - 成功：200，返回 `user_ids`。

### 4. 测试用例的构建描述

建议拆分：

- `test_machine_api_crud.py`
  - `test_add_machine_requires_token`
  - `test_add_machine_requires_operator`
  - `test_add_machine_success`
  - `test_add_machine_duplicate_entry_returns_409`
  - `test_add_machine_validation_error_returns_422`
  - `test_remove_machine_requires_token`
  - `test_remove_machine_requires_operator`
  - `test_remove_machine_success`
  - `test_update_machine_requires_token`
  - `test_update_machine_requires_operator`
  - `test_update_machine_success`
  - `test_update_machine_validation_error_returns_422`
  - `test_get_machine_detail_requires_token`
  - `test_get_machine_detail_not_found`
  - `test_get_machine_detail_success`

- `test_machine_api_listing.py`
  - `test_list_machine_bref_resolves_token_from_header`
  - `test_list_machine_bref_resolves_token_from_bearer`
  - `test_list_machine_bref_resolves_token_from_cookie`
  - `test_list_machine_bref_requires_token`
  - `test_list_machine_bref_success_passes_user_id_to_service`

- `test_machine_api_permission.py`
  - `test_add_machine_permission_requires_token`
  - `test_add_machine_permission_requires_operator`
  - `test_add_machine_permission_missing_fields`
  - `test_add_machine_permission_machine_not_found`
  - `test_add_machine_permission_user_not_found`
  - `test_add_machine_permission_success`
  - `test_list_machine_permissions_requires_token`
  - `test_list_machine_permissions_missing_machine_id`
  - `test_list_machine_permissions_success`

## 阶段 5：Repository-backed 小型集成测试

### 0. 新增的常量定义

无。沿用阶段 0 的测试库与 fixture 常量。

### 1. 影响的文件范围

- `models/user.py`
- `models/machine.py`
- `models/containers.py`
- `models/usercontainer.py`
- `models/machine_permission.py`
- `repositories/user_repo.py`
- `repositories/machine_repo.py`
- `repositories/machine_permission_repo.py`
- `repositories/usercontainer_repo.py`
- `repositories/long_term_container_repo.py`
- `test/user/test_user_repository_integration.py`
- `test/machine/test_machine_repository_integration.py`

### 2. 函数级收口的完整数据流

集成测试数据流：

1. 使用测试库建表。
2. factory 创建用户、机器、容器、绑定关系。
3. 调用 task 函数，但不 mock repository。
4. mock 外部服务，包括邮件、Node heartbeat、后台线程。
5. 断言 task 返回值与数据库最终状态。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

本阶段只覆盖 repository 与 task 的交界，不覆盖 API 映射：

- `Register()` 成功后，用户真实存在，密码为 hash。
- `Login()` 成功后，auth token 真实存在。
- `Get_user_detail_information()` 能从真实 user-container 绑定计算统计。
- `Add_machine()` 成功后，机器真实存在。
- `Update_machine()` 成功后，机器字段真实更新。
- `List_all_machine_bref_information()` 在 mock heartbeat 的条件下，真实更新机器状态。
- `Add_machine_permission()` 成功后，权限关系真实存在。

### 4. 测试用例的构建描述

建议最小集合：

- `test_register_and_login_with_real_repositories`
- `test_user_detail_counts_with_real_usercontainer_and_long_term_rows`
- `test_add_and_update_machine_with_real_repository`
- `test_list_machine_bref_updates_status_with_mocked_heartbeat`
- `test_machine_permission_create_and_list_with_real_repository`

这些测试数量应保持少，作为 task 单元测试与 repository 行为之间的烟雾测试，不扩大为完整业务回归。

## 阶段 6：旧测试迁移与风险封存

### 0. 新增的常量定义

建议在 `pytest.ini` 增加 marker：

- `unit`: 纯 Ctrl 内部单元测试。
- `api`: Flask API 合同测试。
- `db`: 使用隔离测试库的 repository-backed 测试。
- `integration`: 可能访问外部服务的测试。
- `legacy`: 尚未完成重构的旧测试。

### 1. 影响的文件范围

- `pytest.ini`
- `test/test_api_web.py`
- `test/test_api_web_machine.py`
- `test/test_user_sql.py`
- `test/test_machine_sql.py`
- `test/test_mail.py`
- 新目录：
  - `test/user/`
  - `test/machine/`

### 2. 函数级收口的完整数据流

迁移数据流：

1. 新测试先落地并通过。
2. 旧测试逐个对照新测试覆盖表。
3. 已被新测试覆盖的旧用例删除或迁移。
4. 暂未迁移且可能触真实依赖的旧测试加 `@pytest.mark.legacy` 或 `@pytest.mark.integration`。
5. 默认 CI/本地快速回归只跑 `unit/api/db`，不跑 `legacy/integration`。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`pytest` 默认命令建议：

- 输入：`pytest -m "not integration and not legacy"`。
- 输出：只执行安全测试。

旧测试封存规则：

- 凡是调用真实 Node、真实邮件、真实业务库的测试，必须标为 `integration`。
- 凡是依赖随机用户名但不隔离数据库的测试，必须迁移到 factory 或标为 `legacy`。
- 凡是覆盖点已由新测试替代的旧测试，应删除，避免双轨断言互相矛盾。

### 4. 测试用例的构建描述

迁移检查清单：

- `test/test_api_web.py`
  - 注册/登录 HTTP 测试迁移到 `test/user/test_user_api_auth.py`。
  - 删除直接写真实库的清理逻辑。

- `test/test_user_sql.py`
  - 用户 task 测试迁移到 `test/user/test_user_tasks_*.py`。
  - 真实 repository 验证只保留少量到 `test_user_repository_integration.py`。

- `test/test_api_web_machine.py`
  - 机器 HTTP 测试迁移到 `test/machine/test_machine_api_*.py`。
  - 修正 GET/POST 方法与现有 API 定义不一致的旧断言。

- `test/test_machine_sql.py`
  - 机器 task 测试迁移到 `test/machine/test_machine_tasks_*.py`。
  - 所有 heartbeat/Node 通信必须 mock。

- `test/test_mail.py`
  - 保持 `integration`。
  - 默认测试命令不执行。

## 阶段验收顺序

1. 先完成阶段 0，并确认 `pytest -m "not integration and not legacy"` 不会启动后台线程、不连接真实业务库。
2. 完成阶段 1，确保 user task 的输入输出合同稳定。
3. 完成阶段 2，确保 user API 错误码与 JSON 映射稳定。
4. 完成阶段 3，确保 machine task 不访问 Node 且状态刷新逻辑可预测。
5. 完成阶段 4，确保 machine API 权限、token、错误码映射稳定。
6. 完成阶段 5，用少量隔离库测试确认 repository-backed 数据流成立。
7. 完成阶段 6，逐步删除或封存旧测试。

## 本阶段不做的事

- 不重构 Node。
- 不把容器创建、清理、SSH 刷新测试纳入第一阶段主体。
- 不依赖生产库、开发库、真实 Node、真实邮件服务完成默认测试。
- 不一次性追求覆盖全部历史测试，只先把 user/machine 的 task/API 合同立稳。
