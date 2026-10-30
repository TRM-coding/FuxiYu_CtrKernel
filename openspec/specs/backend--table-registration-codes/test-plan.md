# backend--table-registration-codes Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

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
