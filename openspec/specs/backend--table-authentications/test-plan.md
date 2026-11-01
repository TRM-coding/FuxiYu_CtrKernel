# backend--table-authentications Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

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
