# Tasks

## 1. 基线与测试骨架

- [x] 1.1 记录 6 个目标 main spec 与全部 main spec 的 SHA256、6 个 main sidecar 的存在/缺失状态、`review.md` 的 APPROVE 判定和 test-plan 的 49/130/32/29 计数，写入外部 `E:\AI\Fuxi_audit_artifacts\anvil-rollout-2026-10-28\ctrl-batch-3\pre-baseline.json`；验证：JSON 可解析、`openspec validate --strict` 通过。
- [x] 1.2 新建 `test/repository/test_anvil_identity_settings.py`，只含本地 helper/fixture，继续使用现有 SQLite fixture、factory 与真实 cookie token；Node/SMTP/后台调度仅作为外部边界替换；验证：`python -m py_compile` 退出码 0，文件中无 monkeypatch `has_resource_wildcard`、`remove_user_from_all_containers`、`Delete_user`、`list_operation_logs` 等目标逻辑。

## 2. 认证

- [x] 2.1 实现 `test_login_cleans_expired_tokens_and_issues_new_token`、`test_internal_runtime_source_gate_uses_real_client_host`、`test_internal_runtime_token_is_not_persisted_as_authentication`，对应 `backend--table-authentications` 的“验证过期会话”和“内部运行态凭据与来源校验”；验证：指定 WSL env 下定向运行三条测试，退出码 0。
- [x] 2.2 实现 `test_403_preserves_other_tokens_and_container_state_is_irrelevant`，对应“有身份但权限不足”及 Requirement 正文“Token 生命周期不受容器状态决定”；验证：403 后两个 token 仍有效，容器离线/软删后仍有效，定向运行退出码 0。

## 3. 用户与权限快照

- [x] 3.1 实现 `test_delete_user_real_sole_root_container_blocks_and_keeps_tokens`、`test_register_api_response_omits_password_hash`，对应“容器阻止删除”和“创建用户”；验证：真实唯一 ROOT 容器触发 `wild_containers` 且用户/token 保留，注册 API 响应无 `password_hash`，定向运行退出码 0。
- [x] 3.2 实现 `test_bypass_resource_does_not_grant_method_entities`、`test_container_resource_snapshot_agrees_with_container_list_scope`，对应“具备全局资源通配”“容器方法通配不等于资源通配”“直持容器管理或全局资源通配”；验证：资源位、方法实体、`container:view` 门和列表可见范围断言均通过，定向运行退出码 0。
- [x] 3.3 实现 `test_permission_snapshot_is_derived_per_request_without_schema_change`、`test_root_binding_does_not_create_resource_wildcard`、`test_users_table_has_no_resource_unrestricted_columns`，对应“派生字段不落库”；验证：连续请求布尔位随绑定变化、`sqlite_master` 表集合不变、ROOT 绑定只可见已绑定容器、PRAGMA 无派生列，定向运行退出码 0。
- [x] 3.4 实现 `test_rejected_registration_does_not_create_user_row`，对应“非法输入不消费有效验证码”；验证：用新用户名的拒绝路径查询 `users` 无该用户名，重复冲突路径行数不增加，定向运行退出码 0。

## 4. 注册码与设置

- [x] 4.1 实现 `test_registration_code_stores_hash_not_plaintext`、`test_expired_registration_code_response_does_not_echo_hash`、`test_stale_registration_transaction_leaves_no_second_user`，对应 `backend--table-registration-codes` 的“读取有效记录”“验证码过期”“同码并发注册”；验证：DB 只存哈希、错误响应不回显 `code_hash`、stale reader 不产生第二个用户，定向运行退出码 0。
- [x] 4.2 实现 `test_integer_setting_rejects_values_outside_declared_range`，对应 `backend--table-system-settings` 的“合法输入与范围校验保留”；验证：越界整数被拒绝且原值不变，定向运行退出码 0。

## 5. 操作日志

- [x] 5.1 实现 `test_operation_log_repo_filters_by_target_type_and_id`、`test_operation_log_list_keeps_existing_response_fields`，对应“失败操作留痕”“混合目标类型”；验证：目标过滤只返回匹配行，列表响应字段集合仍为既有 12 个，定向运行退出码 0。
- [x] 5.2 实现 `test_reset_password_success_log_has_target_and_no_secret`、`test_add_collaborator_success_log_has_user_and_role`、`test_root_handover_logs_distinguish_each_step`，对应密码类日志复用要求；验证：target_type/id、detail 用户/角色/新旧角色均正确，无密码，定向运行退出码 0。
- [x] 5.3 实现 `test_restore_writes_exactly_one_create_container_log`，对应“创建和恢复保持单条日志”；验证：真实软删 + 恢复流程只新增一条 `CREATE_CONTAINER`，detail 标记 `trigger=resurrect` 且无密码，定向运行退出码 0。
- [x] 5.4 实现 `test_accepted_password_operation_keeps_existing_logs_unchanged`、`test_reset_failure_writes_exactly_one_redacted_log`、`test_add_collaborator_failure_writes_only_one_log`、`test_unknown_node_result_writes_failure_not_success`、`test_operation_log_write_failure_does_not_raise_or_leak_password`，对应结果日志时序、未知结果与写入失败；验证：受理不改旧日志、失败恰一条、未知结果不写成功、DB 写失败不抛回且不泄露密码/请求体/Node 原始错误体，定向运行退出码 0。

## 6. SSH 登录记录

- [x] 6.1 实现 `test_machine_unavailable_deferral_keeps_last_ssh_anchor`、`test_new_ssh_login_resets_deferral_and_cleanup_reminder`，对应 `backend--table-container-ssh-login-records` 的“机器不可用补偿”；验证：窗口补偿后 `last_ssh_login_time` 不变，真登录同时清零 deferral 并复位提醒，定向运行退出码 0。

## 7. 测试执行与映射收口

- [x] 7.1 以用户指定的 WSL Ubuntu Python 与 env 运行 `test/repository/test_anvil_identity_settings.py` 全文件；验证：29 个 planned test 全部执行、退出码 0，记录 passed/failed 数与完整命令到外部 `ctrl-batch-3/test-run.json`。
- [x] 7.2 运行相关既有 identity/user/auth/settings/operation_log/SSH/repository 套件（按实际相关性选择，不重复全基线）；验证：退出码 0，记录每条命令、节点数与结果到外部 `ctrl-batch-3/related-suites.json`。
- [x] 7.3 在 `test-plan.md` 中把实际已创建并确认断言的 32 个 `[ ]` 映射逐项改为 `[X]`，不改 locator、Assertion scope 或 Coverage note；验证：49/49 Scenario 仍有映射，行数仍为 162，`[X]` 为 162、`[ ]` 为 0，`openspec validate --strict` 通过。

## 8. 官方 verify、no-op sync 与 sidecar

- [x] 8.1 按 `openspec-verify-change` advisory 检查 implementation 与 artifacts 一致，不创建 `verify.md`；验证：所有 tracked tasks 完成、相关测试通过、无未解释的规格差异，外部记录 advisory 结果。
- [x] 8.2 执行 no-op sync 评估：逐 capability 比较 delta 与 main spec，不写任何 main spec；验证：6 个目标 main spec 与全部 main spec SHA256 与 1.1 基线逐一相同。
- [x] 8.3 使用 `anvil-test-plan` 维护 6 个 canonical sidecar：`backend--table-authentications`、`backend--table-users`、`backend--table-registration-codes`、`backend--table-system-settings`、`backend--table-operation-logs`、`backend--table-container-ssh-login-records`；验证：每个 sidecar 的 Scenario 路径与 main spec 49 条一一对应、含 Test/check/Assertion scope、无运行台账。
- [x] 8.4 运行最终 `openspec validate --strict`、`openspec status` 与 6 sidecar 结构审计；验证：change 通过、specs 通过、6 sidecar 结构有效、无待补 `[ ]`。

## Workflow follow-up

- 官方 archive：目标 `openspec/changes/archive/2026-10-28-complete-anvil-identity-settings-mappings`（北京时间 2026-10-28），同步评估为 no-op 后归档，验证归档目录含 `.openspec.yaml`、tasks/review/test-plan 与 6 delta。
- 归档后复核 6 个 main sidecar 与 6 个 main spec SHA，报告 changed paths、测试数、命令退出码、archive 状态；不 commit/push。
