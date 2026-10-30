# Test Plan

## backend--table-authentications

### Requirement: authentications 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_authentications_repo.py::test_auth_repo_create_validate_delete_token
  - [X] test/repository/test_authentications_repo.py::test_auth_repo_get_user_id_by_token
- Assertion scope: 创建并 flush 后 `is_token_valid` 为 True；按 token 删除后为 False；`get_user_id_by_token` 返回真实用户主键，而不是展示名。

### Requirement: authentications 生产职责与生命周期

#### Scenario: 验证过期会话

- Test/check:
  - [X] test/repository/test_authentications_repo.py::test_auth_repo_expired_token_is_invalid
  - [X] test/user/test_auth_dependency_status.py::test_expired_credential_is_401_not_403
  - [X] test/repository/test_anvil_identity_settings.py::test_login_cleans_expired_tokens_and_issues_new_token
- Assertion scope: `expires_at` 早于当前时间时 repo 判定无效；真实 cookie token 走 API 依赖返回 401 `invalid_token`；`[ ]` 行断言登录成功后旧过期行被清理、新 token 可验证且旧 token 仍无效。
- Coverage note: 登录时清理过期 token 属于 Requirement 正文约束，已列 `[X]` locator 只覆盖“过期即无效”；清理动作由 `[ ]` 行覆盖。

### Requirement: 认证失效与授权拒绝分离

#### Scenario: 无有效凭据

- Test/check:
  - [X] test/user/test_auth_dependency_status.py::test_missing_credential_is_401_not_403
  - [X] test/user/test_auth_dependency_status.py::test_unknown_credential_is_401_not_403
- Assertion scope: 缺失 cookie 与未知 token 均返回 401 `invalid_token`，不返回 403。

#### Scenario: 有身份但权限不足

- Test/check:
  - [X] test/user/test_auth_dependency_status.py::test_valid_credential_without_permission_is_403
  - [X] test/user/test_auth_dependency_status.py::test_valid_credential_with_permission_is_200
  - [X] test/user/test_auth_dependency_status.py::test_logout_deletes_only_its_own_token
  - [X] test/user/test_auth_dependency_status.py::test_unrelated_user_token_untouched_by_other_users_logout
  - [X] test/repository/test_anvil_identity_settings.py::test_403_preserves_other_tokens_and_container_state_is_irrelevant
- Assertion scope: 有效 token 但缺少 `rbac:manage` 时返回 403 `insufficient_permission`；具备权限时 200；登出只删本轮 token，同用户其他 token 与无关用户 token 保留；`[ ]` 行用同一用户两个有效 token，带其中一个请求受保护 API 得 403 后断言两 token 仍有效，并在容器状态变化后再次断言 token 有效，证明容器状态不参与 token 生命周期。
- Coverage note: 403 状态码与登出隔离由已列 `[X]` locator 断言；403 后其他 session 保留、容器状态无关性由 `[ ]` 行补齐，不用 logout 测试替代。

#### Scenario: 内部运行态凭据与来源校验

- Test/check:
  - [X] test/machine/test_machine_tasks_status.py::test_internal_runtime_api_requires_shared_token
  - [X] test/repository/test_anvil_identity_settings.py::test_internal_runtime_source_gate_uses_real_client_host
  - [X] test/repository/test_anvil_identity_settings.py::test_internal_runtime_token_is_not_persisted_as_authentication
- Assertion scope: 已列参数化 `[X]` locator 覆盖 `containers` 与 `machines` 两个端点：本地来源无/错共享 token 返回 401 `invalid_token`，正确 token 返回 200，非本地来源返回 403 `forbidden`；`[ ]` 行用真实 client host 复核 loopback 判定，并断言内部 token 请求不会新增 `authentications` 行。
- Coverage note: 已列 `[X]` locator 用 monkeypatch 固定 `_is_loopback` 分类，状态码断言有效但来源分类本身由 `[ ]` 行以真实 client host 覆盖。

## backend--table-users

### Requirement: users 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_register_success
  - [X] test/user/test_user_repository_integration.py::test_register_and_login_with_real_repositories
  - [X] test/user/test_user_tasks_profile.py::test_update_user_filters_forbidden_fields
- Assertion scope: 注册后按 username 可读回真实用户行，`password_hash` 不是明文；repo 按 username 取回同一 id；更新后 username、email、graduation_year 与 hash 的保留/过滤语义可观察。
- Coverage note: `created_at` 由模型默认值承载，`[X]` 行未逐字段核验时间戳类型。

### Requirement: users 生产职责与生命周期

#### Scenario: 创建用户

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_register_success
  - [X] test/user/test_user_tasks_profile.py::test_register_rejects_invalid_inputs
  - [X] test/user/test_user_tasks_profile.py::test_register_rejects_duplicate_username
  - [X] test/user/test_user_tasks_profile.py::test_register_rejects_duplicate_email
  - [X] test/user/test_user_api_auth.py::test_register_success
  - [X] test/repository/test_anvil_identity_settings.py::test_register_api_response_omits_password_hash
- Assertion scope: 合法注册保存 username/email 与 hash（hash 不等于明文）；非法输入、重复用户名、重复邮箱分别返回既定原因；API 注册成功返回 201 与 success=1；`[ ]` 行断言 API 响应体不含 `password_hash`。
- Coverage note: 服务层 locator 断言不保存明文，但“返回数据不暴露口令哈希”只由 `[ ]` 行覆盖。

### Requirement: 用户删除与认证记录同事务清理

#### Scenario: 有 Token 但无阻塞容器

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_removes_its_authentication_tokens
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_leaves_other_users_tokens_untouched
  - [X] test/user/test_user_api_profile.py::test_delete_user_with_token_actually_deletes_user_and_token
- Assertion scope: 目标用户及其多个 token 在同一删除事务后消失；其他用户 token 保留；真实 API 删除路径同样清 token。

#### Scenario: 容器阻止删除

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_raises_wild_containers
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_wild_container_keeps_user_and_tokens
  - [X] test/user/test_user_api_profile.py::test_delete_user_wild_containers
  - [X] test/user/test_user_tasks_profile.py::test_user_delete_is_blocked_by_token_without_explicit_cleanup
  - [X] test/repository/test_anvil_identity_settings.py::test_delete_user_real_sole_root_container_blocks_and_keeps_tokens
- Assertion scope: 已列 `[X]` locator 覆盖 `wild_containers` 异常到 `wild_container` API 响应的映射、mocked wild 分支下用户/token 保留，以及仅有 token 时外键阻止裸删 users 行；`[ ]` 行用 `create_container_graph()` 造一个仅该用户为 ROOT 的真实容器，调用真实 `Delete_user`，断言 `wild_containers` 含该容器、用户行与其 token 均保留。
- Coverage note: 真实数据下的野容器判定（唯一 ROOT 绑定）由 `[ ]` 行覆盖；mocked `remove_user_from_all_containers` 或 `Delete_user` 的分支不作为该 THEN 的行为证据。

#### Scenario: 删除事务失败

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_token_delete_failure_rolls_back_user
  - [X] test/user/test_user_api_profile.py::test_delete_user_non_wild_failure_is_not_reported_as_wild_container
- Assertion scope: token 删除抛异常时用户与 token 均保留且异常向上抛出；API 对非野容器失败返回 `delete_user_failed`，响应不含 `wild_containers`，不冒充 `wild_container`。

### Requirement: 权限快照区分方法能力与镜像资源通配

#### Scenario: 只有方法实体通配

- Test/check:
  - [X] test/user/test_password_permission_snapshot.py::test_container_resource_snapshot_contract
  - [X] test/image/test_image_resource_scope.py::test_my_permissions_exposes_real_image_resource_wildcard
- Assertion scope: 只有 `bypass_auth_entity` 时 entities 可含 `container:manage`/`image:manage`，但 `container_resource_unrestricted` 与 `image_resource_unrestricted` 均为 False。

#### Scenario: 具备全局资源通配

- Test/check:
  - [X] test/user/test_password_permission_snapshot.py::test_container_resource_snapshot_contract
  - [X] test/image/test_image_resource_scope.py::test_my_permissions_exposes_real_image_resource_wildcard
  - [X] test/repository/test_anvil_identity_settings.py::test_bypass_resource_does_not_grant_method_entities
- Assertion scope: 直持 `bypass_resource` 时两个资源布尔位均为 True；`[ ]` 行断言 `bypass_resource` 不把方法实体误展开为 `bypass_auth_entity`、`container:manage` 或 `image:manage`，且需要 `rbac:manage` 的方法门仍返回 403。
- Coverage note: 资源布尔位由 `[X]` locator 断言；方法实体与方法门分离由 `[ ]` 行补齐。

#### Scenario: 容器方法通配不等于资源通配

- Test/check:
  - [X] test/user/test_password_permission_snapshot.py::test_container_resource_snapshot_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_container_resource_snapshot_agrees_with_container_list_scope
- Assertion scope: 只有 `bypass_auth_entity` 时 `/api/users/me/permissions` 返回 `container_resource_unrestricted=False`；`[ ]` 行在显式授予 `container:view` 后调用真实列表接口，断言该用户看不到未绑定容器，不能按方法通配展开全部容器资源。
- Coverage note: 快照布尔位由 `[X]` locator 断言；列表接口的 `container:view` 方法门与列表可见范围由 `[ ]` 行补齐，不把仅有资源通配的请求当作可通过。

#### Scenario: 直持容器管理或全局资源通配

- Test/check:
  - [X] test/user/test_password_permission_snapshot.py::test_container_resource_snapshot_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_container_resource_snapshot_agrees_with_container_list_scope
- Assertion scope: 直持 `container:manage` 或 `bypass_resource` 时 `container_resource_unrestricted=True`，且与 `image_resource_unrestricted` 各自独立；`[ ]` 行先验证只有 `bypass_resource`、没有 `container:view` 时列表 API 返回 403，再显式补 `container:view` 后断言其可见未绑定容器；直持 `container:manage` 且显式 `container:view` 的列表范围与布尔位一致。
- Coverage note: 快照布尔位由 `[X]` locator 断言；`container:view` 方法门与资源通配列表范围由 `[ ]` 行补齐；ROOT 绑定另行判断见“派生字段不落库”的 `[ ]` 行。

#### Scenario: 派生字段不落库

- Test/check:
  - [X] test/repository/test_anvil_identity_settings.py::test_users_table_has_no_resource_unrestricted_columns
  - [X] test/repository/test_anvil_identity_settings.py::test_permission_snapshot_is_derived_per_request_without_schema_change
  - [X] test/repository/test_anvil_identity_settings.py::test_root_binding_does_not_create_resource_wildcard
- Assertion scope: `[ ]` 行用 SQLite `PRAGMA table_info(users)` 断言不存在 `container_resource_unrestricted` 或 `image_resource_unrestricted` 列；同组测试先记录 `sqlite_master` 表集合，连续请求并在两次请求之间增删 `bypass_resource` 绑定，断言布尔位 false→true→false、表集合不变（每次请求派生、不新增表）；ROOT 绑定用户授予 `container:view` 但无资源通配时布尔位为 false，列表只含其已绑定容器，证明 ROOT 绑定按具体容器另行判断。
- Coverage note: 仅列检查不足以覆盖 Scenario；三行分别补列、请求期派生/不新增表、ROOT 绑定独立判定。SQLite PRAGMA/`sqlite_master` 断言只代表隔离测试库，不外推生产 schema。

#### Scenario: 容器资源通配与镜像资源通配互不冒充

- Test/check:
  - [X] test/user/test_password_permission_snapshot.py::test_container_resource_snapshot_contract
- Assertion scope: 直持 `container:manage` 时容器位 True 而镜像位 False；只有 `bypass_auth_entity` 时两位均 False；`bypass_resource` 时两位均 True。

### Requirement: 验证码注册按成功提交确认

#### Scenario: 非法输入不消费有效验证码

- Test/check:
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_rejects_invalid_code
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_rejects_expired_code
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_duplicate_username_keeps_code_for_retry
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_duplicate_email_keeps_code
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_invalid_username_does_not_consume_code
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_non_ascii_password_does_not_consume_code
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_unique_constraint_backstops_precheck_race
  - [X] test/repository/test_anvil_identity_settings.py::test_rejected_registration_does_not_create_user_row
- Assertion scope: 错误码、过期码、重复用户名/邮箱、非法用户名、非 ASCII 口令与预检竞态均返回对应失败原因，`consumed_at` 保持为空；`[ ]` 行对使用新用户名的拒绝路径（错误/过期码、非法用户名、非 ASCII 口令、预检竞态）查询 `users` 无该用户名，对重复用户名/邮箱路径断言 `users` 行数不增加。
- Coverage note: 已列 `[X]` locator 只断言返回原因与验证码未消费，未查询 `users`；无残留用户行由 `[ ]` 行补齐。

#### Scenario: 成功后不可重用

- Test/check:
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_success_consumes_code_and_creates_user
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_success_is_not_reusable
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_default_group_failure_rolls_back
- Assertion scope: 成功注册后用户、默认 user 组绑定与 `consumed_at` 同时生效；同码再次注册返回 `registration_code_invalid`；默认组绑定失败时用户与消费整体回滚。

## backend--table-registration-codes

### Requirement: registration_codes 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_registration_code_repo.py::test_verify_code_is_read_only
  - [X] test/repository/test_registration_code_repo.py::test_verify_and_consume_code_success_is_not_reusable
  - [X] test/repository/test_anvil_identity_settings.py::test_registration_code_stores_hash_not_plaintext
- Assertion scope: 只读校验连续两次成功且 `consumed_at` 保持 None；成功消费后 `consumed_at` 非空，再次消费失败；`[ ]` 行创建明文 code 后读取 DB，断言 `code_hash` 存在且不等于明文，明文可验证成功，DB 记录中不保存明文 code。
- Coverage note: 已列 `[X]` locator 只覆盖只读/消费与 `consumed_at`，未读取 `code_hash`；哈希存储与明文不落库由 `[ ]` 行补齐；错误响应不回显哈希见“验证码过期”的 `[ ]` 行。

### Requirement: registration_codes 生产职责与生命周期

#### Scenario: 验证码过期

- Test/check:
  - [X] test/repository/test_registration_code_repo.py::test_registration_code_repo_rejects_expired_code
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_rejects_expired_code
  - [X] test/repository/test_anvil_identity_settings.py::test_expired_registration_code_response_does_not_echo_hash
  - [X] test/repository/test_anvil_identity_settings.py::test_rejected_registration_does_not_create_user_row
- Assertion scope: 超过 `expires_at` 的码在 repo 与注册服务均被拒绝，服务返回 `registration_code_invalid`；`[ ]` 行断言 API 错误响应不包含库内 `code_hash`，并直接查询 `users` 确认该次尝试没有留下用户行。
- Coverage note: 已列 `[X]` locator 覆盖过期拒绝；响应不回显哈希与无残留用户行由两条 `[ ]` 行补齐。

#### Scenario: 注册冲突后修正重试

- Test/check:
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_duplicate_username_keeps_code_for_retry
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_duplicate_email_keeps_code
- Assertion scope: 用户名冲突时首次返回 `username_exists` 且不消费验证码，有效期内修正用户名后同一码可再次提交并成功；邮箱冲突时返回 `email_exists` 且不消费验证码，但不对“换邮箱后复用同码”作重试承诺。

#### Scenario: 注册持久化失败

- Test/check:
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_default_group_failure_rolls_back
  - [X] test/user/test_user_tasks_registration_code.py::test_register_with_code_db_failure_rolls_back_consumption_and_retry_succeeds
- Assertion scope: 默认组绑定或用户写入抛异常时，同一事务中的用户创建与验证码消费一起回滚；码保持未消费，随后重试可成功。

#### Scenario: 同码并发注册

- Test/check:
  - [X] test/repository/test_registration_code_repo.py::test_consume_code_rejects_stale_reader
  - [X] test/repository/test_anvil_identity_settings.py::test_stale_registration_transaction_leaves_no_second_user
- Assertion scope: 已列 `[X]` locator 让两个读者都看到有效行，条件消费只允许第一个成功，第二个返回 False；`[ ]` 行在同一事务语义下完成第一个用户建档与消费，并断言第二个 stale reader 不能消费、不能留下第二个用户。
- Coverage note: 已列 `[X]` locator 只覆盖条件 UPDATE 的“至多一次消费”；用户创建与无遗留用户由 `[ ]` 行补齐。

## backend--table-system-settings

### Requirement: system_settings 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/image/test_image_platform_injection_setting.py::test_system_settings_matrix_is_seeded
  - [X] test/image/test_image_platform_injection_setting.py::test_platform_injection_setting_can_be_updated
  - [X] test/image/test_image_platform_injection_setting.py::test_system_settings_api_update_roundtrip
- Assertion scope: seed 后可按 key 读取 value 等序列化设置；更新后读取方取得新字符串值；API 批量更新后 getter 返回新值。
- Coverage note: `created_at`/`updated_at` 由模型默认值与 onupdate 承载，`[X]` 行未逐字段核验时间戳。

### Requirement: system_settings 生产职责与生命周期

#### Scenario: 修改已知设置

- Test/check:
  - [X] test/image/test_image_platform_injection_setting.py::test_system_settings_api_update_roundtrip
  - [X] test/image/test_image_platform_injection_setting.py::test_platform_injection_setting_can_be_updated
  - [X] test/image/test_image_platform_injection_setting.py::test_system_settings_seed_removes_deprecated_parallel_keys
  - [X] test/image/test_image_platform_injection_setting.py::test_settings_batch_target_is_order_independent
- Assertion scope: 具备 `settings:manage` 的测试身份更新已知键后，API/getter 读取新值；审计记录 before/after 与 `setting_keys`；重复 seed 可执行并删除废弃键；批量更新 target_id 与键顺序无关。

### Requirement: system_settings 设置输入不得静默改变语义

#### Scenario: 小数设置

- Test/check:
  - [X] test/settings/test_settings_validation.py::test_integer_setting_rejects_non_integer_without_writing
  - [X] test/settings/test_settings_validation.py::test_single_setting_entrypoint_also_rejects_fractional_integer
  - [X] test/settings/test_settings_validation.py::test_settings_api_rejects_fractional_integer
- Assertion scope: `1.5`、`"1.5"`、`True`、`"abc"`、空串均被拒绝，原值不变；单键入口同样拒绝；API 返回 422 `invalid_setting`，message 指出设置键，不把值截断成 1。

#### Scenario: 非法提醒节点

- Test/check:
  - [X] test/settings/test_settings_validation.py::test_reminder_hours_rejects_malformed_input_without_writing
  - [X] test/settings/test_settings_validation.py::test_settings_api_rejects_malformed_reminder_hours
- Assertion scope: 空串、空白、空项、非整数、0、负数、`12.5` 均使整次写入失败，原值不变；审计保留 `requested`；API 返回 422 `invalid_setting`，message 含设置键与非法项。

#### Scenario: 合法输入与范围校验保留

- Test/check:
  - [X] test/settings/test_settings_validation.py::test_integer_setting_accepts_integral_number
  - [X] test/settings/test_settings_validation.py::test_reminder_hours_accepts_positive_values_and_stays_parser_compatible
  - [X] test/repository/test_anvil_identity_settings.py::test_integer_setting_rejects_values_outside_declared_range
- Assertion scope: `12.0` 保存为 `"12"`；`"72, 24,12"` 原样保存且可被提醒解析器解析为 `[72,24,12]`；`[ ]` 行对声明了 min/max 的整数键提交越界值，断言 `ValueError`、原值不变且不静默截断。
- Coverage note: 已列 `[X]` locator 覆盖合法值与格式校验；既有 `min_value`/`max_value` 越界拒绝未见直接断言，由 `[ ]` 行覆盖。

## backend--table-operation-logs

### Requirement: operation_logs 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_operation_log_repo.py::test_write_and_list_desc_order
  - [X] test/repository/test_operation_log_repo.py::test_serialize_shape
  - [X] test/repository/test_operation_log_repo.py::test_stats_aggregation
- Assertion scope: 写入后按 id 倒序读回三条记录；serialize 恰含 id、operator_user_id、operation、target_type、target_id、detail、success、error_reason、created_at；success 为 bool，created_at 非空，detail 保留 JSON；统计聚合 total/succeeded/failed/by_operation/by_target_type/by_day。

### Requirement: operation_logs 生产职责与生命周期

#### Scenario: 失败操作留痕

- Test/check:
  - [X] test/operation_log/test_operation_log_tasks.py::test_each_repeated_failure_is_audited
  - [X] test/operation_log/test_operation_log_tasks.py::test_manual_failures_are_not_suppressed
  - [X] test/container/test_deleted_containers.py::test_manual_mount_preflight_failure_is_audited
  - [X] test/container/test_deleted_containers.py::test_each_automatic_and_manual_mount_failure_is_audited
  - [X] test/operation_log/test_operation_log_tasks.py::test_deleted_container_keeps_owner_without_navigation
  - [X] test/operation_log/test_operation_log_tasks.py::test_list_enriches_user_name_and_tolerates_deleted_target
  - [X] test/repository/test_operation_log_repo.py::test_list_filter_by_operator_and_operation
  - [X] test/repository/test_operation_log_repo.py::test_list_filter_by_success
  - [X] test/repository/test_operation_log_repo.py::test_list_time_range
  - [X] test/repository/test_anvil_identity_settings.py::test_operation_log_repo_filters_by_target_type_and_id
- Assertion scope: 每次失败各写一条 success=False 且 error_reason 稳定的记录；detail 保留触发方式/目标上下文；重复失败不被合并或抑制；目标已删除时日志仍可查询并保留历史展示名；已列 `[X]` locator 覆盖 operator/operation、success、start/end 时间过滤；`[ ]` 行用 repo `list_logs(target_type=..., target_id=...)` 写入不同 target_type/target_id 的日志，断言按目标过滤只返回匹配行。
- Coverage note: 时间与操作者/操作/success 过滤由 `[X]` locator 覆盖；target_type/target_id 过滤由 `[ ]` 行补齐。

### Requirement: 操作日志目标回填批量读取并保持返回契约

#### Scenario: 混合目标类型

- Test/check:
  - [X] test/operation_log/test_operation_log_tasks.py::test_list_enriches_every_supported_target_type
  - [X] test/operation_log/test_operation_log_tasks.py::test_deleted_container_keeps_owner_without_navigation
  - [X] test/operation_log/test_operation_log_tasks.py::test_list_enriches_user_name_and_tolerates_deleted_target
  - [X] test/operation_log/test_operation_log_tasks.py::test_list_skips_identity_mapping_for_previous_generation_log
  - [X] test/repository/test_anvil_identity_settings.py::test_operation_log_list_keeps_existing_response_fields
- Assertion scope: 一页内机器、容器、用户、镜像、权限组、设置与历史目标均按原语义回填 target_name/target_display_name/root_owner；目标已删除时保留历史展示名且不错误导航；日志早于当前容器 created_at 时不映射名称与超管；`[ ]` 行断言返回字段集合仍为既有 12 个，不新增缓存字段。
- Coverage note: 回填语义覆盖；“不新增返回字段”由 `[ ]` 行补齐。

#### Scenario: User 查询失败

- Test/check:
  - [X] test/operation_log/test_operation_log_tasks.py::test_user_query_failure_blanks_root_owner_only
- Assertion scope: User 批量查询抛错时主日志列表仍返回；容器 target_name 保留、root_owner 为空；后续 image 类型仍使用独立会话回填。

#### Scenario: 事务级失败隔离

- Test/check:
  - [X] test/operation_log/test_operation_log_tasks.py::test_user_dbapi_failure_does_not_poison_later_type_sessions
- Assertion scope: 对 `FROM USERS` 注入 DBAPI/事务级异常后，容器 target_name 保留、root_owner 为空，image 仍能新开 session 回填，失败事务不毒化后续类型。

#### Scenario: 25 行不线性增长

- Test/check:
  - [X] test/operation_log/test_operation_log_tasks.py::test_target_enrichment_query_count_does_not_grow_per_row
- Assertion scope: 25 条容器日志全部回填成功，SELECT 语句总数不超过 8，不随 25 行线性增长。

### Requirement: 统计失败使用独立错误原因

#### Scenario: 统计查询失败

- Test/check:
  - [X] test/operation_log/test_operation_log_api.py::test_stats_failure_uses_stats_failed
  - [X] test/operation_log/test_operation_log_api.py::test_list_failure_keeps_list_failed
- Assertion scope: 统计服务抛异常时 API 返回 500 `stats_failed`；列表服务抛异常时返回 500 `list_failed`；两者 message 分别为 `stats failed` 与 `query failed`，不混用。

### Requirement: 密码类操作的日志复用与无密码约束

#### Scenario: 重置成功后记一条无密码日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_codes_contract
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_reset_password_success_log_has_target_and_no_secret
- Assertion scope: Node 成功后恰新增一条 `reset_container_password` 成功日志，无第二条；已列 `[X]` locator 断言 success=True 且密码不出现在 detail；`[ ]` 行补 target_type=container、target_id=container_id、detail 含 user_id/login_name 且不含密码或 credentials。
- Coverage note: 条数与无密码覆盖；稳定目标字段与 detail 身份字段由 `[ ]` 行补齐。

#### Scenario: 新增协作者成功记无密码日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_codes_contract
  - [X] test/container/test_password_contracts.py::test_add_collaborator_password_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_add_collaborator_success_log_has_user_and_role
- Assertion scope: Node 创建账号与绑定成功后恰新增一条 `ADD_COLLABORATOR` 成功日志，不新增密码专用操作码；已列 `[X]` locator 断言 len=1、success=True、密码不在 detail；`[ ]` 行补 detail 含目标 user_id/username 与 role。
- Coverage note: 条数与无密码覆盖；目标用户与角色字段由 `[ ]` 行补齐。

#### Scenario: ROOT 交接每一步单独留痕

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_codes_contract
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_root_handover_logs_distinguish_each_step
- Assertion scope: 两步成功时恰有 2 条 `UPDATE_COLLABORATOR_ROLE` 成功日志，旧 ROOT 与目标各一条；已列 `[X]` locator 断言条数、success 与无密码；`[ ]` 行补 detail 可区分目标与新旧角色，且不新增第二条创建日志。
- Coverage note: 条数与无密码覆盖；角色/目标区分与“无额外创建日志”由 `[ ]` 行补齐。

#### Scenario: 创建和恢复保持单条日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_codes_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_restore_writes_exactly_one_create_container_log
- Assertion scope: 已列创建路径 `[X]` locator 断言恰写一条 `CREATE_CONTAINER` 结果日志，密码生成与凭据响应不产生第二条；`[ ]` 行走真实软删与恢复流程，断言恢复同样只写一条 `CREATE_CONTAINER`，detail 标记 resurrect 且不含密码。
- Coverage note: 创建侧覆盖；恢复侧的单条日志与无密码无直接断言。

#### Scenario: Node 错误体含敏感值时审计仍脱敏

- Test/check:
  - [X] test/container/test_password_contracts.py::test_untrusted_reason_redaction_contract
  - [X] test/container/test_password_contracts.py::test_password_persistence_contract
  - [X] test/container/test_role_adversarial.py::test_node_failure_during_demotion_stops_before_promotion
  - [X] test/repository/test_anvil_identity_settings.py::test_reset_failure_writes_exactly_one_redacted_log
- Assertion scope: Node error_reason 回显密码时，重置/新增协作者只存白名单 `reset_failed`/`add_failed`，创建异常 reason 为 `create_failed`；HTTP 错误不回显未受信 reason；detail/error_reason 不含密码；`[ ]` 行在真实 reset 失败路径注入完整请求体哨兵与 Node 原始错误体哨兵，断言审计记录的任何字段和拼接文本都不含这两个哨兵。
- Coverage note: 密码位于 error_reason/detail 的路径由 `[X]` locator 覆盖；请求体与 Node 原始错误体的脱敏由 `[ ]` 行补齐。

### Requirement: 密码类异步操作的结果日志时序

#### Scenario: 结果返回后记一条成功日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
  - [X] test/container/test_password_contracts.py::test_root_handover_steps_contract
- Assertion scope: 后台 target 执行前无结果日志；执行成功后重置恰新增一条成功日志且不含密码；ROOT 两步成功恰有两条角色成功日志。

#### Scenario: 受理时不写结果日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_accepted_password_operation_keeps_existing_logs_unchanged
- Assertion scope: `start_reset_container_password` 返回后、后台执行前，`reset_container_password` 日志为空且未调用 Node；`[ ]` 行预置一条无关日志，断言受理只新增凭据响应，不改变既有日志。
- Coverage note: “受理时不写结果日志”覆盖；“此前已有日志保持不变”由 `[ ]` 行补齐。

#### Scenario: 重置失败记一条失败日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_password_contracts.py::test_reset_background_contract
  - [X] test/container/test_password_contracts.py::test_untrusted_reason_redaction_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_reset_failure_writes_exactly_one_redacted_log
- Assertion scope: Node 返回失败或抛异常后存在失败记录，success=False、error_reason 稳定为 `reset_failed`，detail/error_reason 不含密码；`[ ]` 行断言恰一条失败且无新增成功，target_type=container、target_id=container_id、detail 含 user_id/login_name，并注入完整请求体与 Node 原始错误体哨兵后断言任何日志字段/拼接文本都不含哨兵。
- Coverage note: 失败方向与密码脱敏由 `[X]` locator 覆盖；精确条数、无新增成功、稳定目标字段、请求体/Node 原始错误体脱敏由 `[ ]` 行补齐。

#### Scenario: 新增协作者失败不写成功日志

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_password_contracts.py::test_add_collaborator_password_contract
  - [X] test/container/test_password_contracts.py::test_untrusted_reason_redaction_contract
  - [X] test/repository/test_anvil_identity_settings.py::test_add_collaborator_failure_writes_only_one_log
- Assertion scope: Node 创建账号或写绑定失败时不写协作者绑定、不新增成功日志，存在 `ADD_COLLABORATOR` 失败记录；已列 `[X]` locator 断言无成功、无绑定、error_reason `add_failed` 且无密码；`[ ]` 行补恰一条失败与 detail 目标字段。
- Coverage note: 失败方向覆盖；精确条数与稳定目标字段由 `[ ]` 行补齐。

#### Scenario: ROOT 交接部分失败如实记录

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_role_adversarial.py::test_machine_offline_between_steps_keeps_first_committed_fact
  - [X] test/container/test_role_adversarial.py::test_node_failure_during_demotion_stops_before_promotion
  - [X] test/container/test_role_adversarial.py::test_binding_failure_during_demotion_stops_before_promotion
  - [X] test/container/test_role_adversarial.py::test_db_or_audit_exception_does_not_rollback_committed_step
- Assertion scope: 旧 ROOT 降级成功后保留其成功日志与已提交绑定；目标步骤失败只写失败日志，不写“整体交接成功”，不回滚旧 ROOT；成功/失败计数可观察，所有日志不含密码。

#### Scenario: 超时或未知结果不写成功

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_role_adversarial.py::test_node_failure_during_demotion_stops_before_promotion
  - [X] test/repository/test_anvil_identity_settings.py::test_unknown_node_result_writes_failure_not_success
- Assertion scope: Node 超时/异常时存在 success=False 的失败记录，detail/error_reason 不含密码或原始错误体；已列 `[X]` locator 覆盖 TimeoutError/RuntimeError；`[ ]` 行覆盖返回无法确认 success 的未知结果，并断言不新增成功记录。
- Coverage note: 超时与异常覆盖；“未知结果不写成功”由 `[ ]` 行补齐。

#### Scenario: 日志写入失败不影响已受理结果

- Test/check:
  - [X] test/operation_log/test_password_logs.py::test_password_log_timing_contract
  - [X] test/container/test_role_adversarial.py::test_db_or_audit_exception_does_not_rollback_committed_step
  - [X] test/repository/test_anvil_identity_settings.py::test_operation_log_write_failure_does_not_raise_or_leak_password
- Assertion scope: `log_success` 在 oplog 写入异常时返回 None、不抛回调用方；已提交的角色绑定不被日志异常回滚，成功/失败计数不出现第二条成功；`[ ]` 行在 Node 调用完成后对 operation_logs INSERT 注入 DBAPI 异常，断言后台任务不抛、不伪造成功日志、密码不进入备用日志。
- Coverage note: 已列 `[X]` locator 覆盖“不抛回/不回滚”；“不伪造成功日志/不泄露密码”由 `[ ]` 行补齐。

## backend--table-container-ssh-login-records

### Requirement: container_ssh_login_records 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/repository/test_container_ssh_login_repo.py::test_container_ssh_login_repo_upsert_insert_and_update
  - [X] test/repository/test_container_ssh_login_repo.py::test_container_ssh_login_repo_get_missing_returns_none
  - [X] test/repository/test_container_ssh_login_repo.py::test_container_ssh_login_repo_list_all_filters_invalid_containers
- Assertion scope: 按 machine_id/container_id 插入后 `last_ssh_login_time` 与 `updated_at` 可读；再次 upsert 更新登录时间；缺失记录返回 None；软删容器默认从 list 排除，`include_invalid=True` 可读回。

### Requirement: container_ssh_login_records 生产职责与生命周期

#### Scenario: 机器不可用补偿

- Test/check:
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_offline_window_adds_deferral_on_recovery
  - [X] test/machine/test_cleanup_deferral_window.py::TestUnavailableWindow::test_deferral_applies_to_all_records_of_machine
  - [X] test/machine/test_cleanup_deferral_window.py::TestDeferralLifecycle::test_add_deferral_accumulates
  - [X] test/machine/test_cleanup_deferral_window.py::TestCleanupInfoDeferral::test_deferral_shifts_cleanup_and_rescues_due
  - [X] test/machine/test_cleanup_deferral_window.py::TestDeferralLifecycle::test_same_value_frame_keeps_deferral
  - [X] test/machine/test_cleanup_deferral_window.py::TestDeferralLifecycle::test_value_change_clears_deferral
  - [X] test/repository/test_container_cleanup_reminder_repo.py::test_container_cleanup_reminder_repo_reset_to_never_only_touches_that_container
  - [X] test/repository/test_container_ssh_login_repo.py::test_container_ssh_login_repo_list_all_filters_invalid_containers
  - [X] test/repository/test_anvil_identity_settings.py::test_machine_unavailable_deferral_keeps_last_ssh_anchor
  - [X] test/repository/test_anvil_identity_settings.py::test_new_ssh_login_resets_deferral_and_cleanup_reminder
- Assertion scope: 机器离线窗口结束把整段时长累加到该机器全部记录的 deferral_seconds，清理倒计时按 deferral 顺延；同值心跳保留 deferral，真登录值变化清零；提醒仓储可把目标容器复位为 NEVER 且不碰其他容器；软删容器被排除；`[ ]` 行断言窗口补偿后 `last_ssh_login_time` 不变，以及 upsert 新登录值时同一事务同时清零 deferral 并复位提醒。
- Coverage note: 已列 `[X]` locator 覆盖补偿、倒计时、同值/变化与提醒仓储；“窗口后锚点不变”和“upsert 联动复位提醒”两个正文约束由 `[ ]` 行补齐。
