# backend--table-users Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

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

### Requirement: 用户删除原子清理所属草稿

#### Scenario: 有认证记录和草稿但无阻塞容器

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_cascades_own_drafts_and_keeps_others
  - [X] test/user/test_user_api_profile.py::test_delete_user_with_drafts_actually_deletes_them
- Assertion scope: 服务路径建 token/目标草稿/其他草稿/公告模板，删除后目标用户、token、草稿消失，其他草稿与公告/模板快照保留，manual `delete_draft` spy 未触发；API 路径真实删除目标用户及其 token/草稿并保留他人草稿。两条路径合计覆盖，不把 API 行夸大为公告/模板 fixture 或 `session_scope` spy。

#### Scenario: 容器阻止删除

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_wild_container_keeps_user_and_tokens
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_wild_container_keeps_drafts
- Assertion scope: wild_container 分支保留用户与 token；草稿测试另有其他用户草稿、公告/模板，异常后目标 token/草稿及其他数据快照均不变。

#### Scenario: 最终事务在级联后失败

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_token_delete_failure_rolls_back_user
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_cascade_rolls_back_on_transaction_failure
- Assertion scope: token 删除在用户删除前失败时用户/token 回滚；after-cascade 测试在级联后失败，断言用户/token/目标草稿恢复，其他草稿与公告/模板快照不变。
