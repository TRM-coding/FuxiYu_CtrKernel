## 1. 创建/恢复一次性 root 凭据（TDD）

- [ ] 1.1 写失败测试：`test_create_restore_credentials_contract`，覆盖创建/恢复凭据、失败无凭据、requires_choice、内部入口非默认密码；确认红。
- [ ] 1.2 实现：创建载荷顶层 `root_password`、API/恢复响应 `accepted/credentials`、no-store，保持既有创建日志。
- [ ] 1.3 重构并跑该测试，确认转绿且既有创建/恢复测试不退化。

## 2. 新增协作者与恢复协作者瞬时密码（TDD）

- [ ] 2.1 写失败测试：`test_add_collaborator_password_contract`、`test_restore_accounts_password_contract`；确认红。
- [ ] 2.2 实现：add `config.password`、后台受理/绑定/既有 `ADD_COLLABORATOR` 日志；恢复协作者项瞬时密码且不落 snapshot。
- [ ] 2.3 重构并跑这两条测试，确认转绿且协作者移除/恢复其余路径不退化。

## 3. 手动重置密码（TDD）

- [ ] 3.1 写失败测试：`test_reset_permission_contract`、`test_reset_background_contract`；确认红。
- [ ] 3.2 实现：新端点、三层 guard、绑定 login_name、`reset_container_password` oplog、后台最小复核与 no-store。
- [ ] 3.3 重构并跑重置契约测试，确认转绿且错误映射不泄原始错误体。

## 4. ROOT 单目标与交接（TDD）

- [ ] 4.1 写失败测试：`test_single_root_promotion_contract`、`test_root_handover_contract`、`test_root_handover_steps_contract`、`test_role_change_semantics_contract`；确认红。
- [ ] 4.2 实现：`transfer_root` 分支、单目标 root 一项、交接 root+旧 ROOT 多项、逐步执行/失败/guard、Node 单目标 primitive。
- [ ] 4.3 重构并跑 ROOT 契约测试，确认转绿且普通角色行为不变。

## 5. 内部删除用户 ROOT 提升兼容（TDD）

- [ ] 5.1 写失败测试：`test_delete_user_root_password_contract`；确认红。
- [ ] 5.2 实现：删除用户内部单目标同步提升生成 `root_password`，不走 `transfer_root=true` 编排，不回退弱密码。
- [ ] 5.3 重构并跑该测试，确认转绿且既有删除用户测试不退化。

## 6. 权限快照（TDD）

- [ ] 6.1 写失败测试：`test_container_resource_snapshot_contract`；确认红。
- [ ] 6.2 实现：`/api/users/me/permissions` 增加派生非持久 `container_resource_unrestricted`。
- [ ] 6.3 重构并跑该测试与既有权限测试，确认转绿。

## 7. 持久化与凭据卫生（TDD）

- [ ] 7.1 写失败测试：`test_password_persistence_contract`；确认红。
- [ ] 7.2 实现/补齐：密码不落库/日志/审计/缓存、无回查入口、失败脱敏、所有凭据响应 no-store。
- [ ] 7.3 重构并跑该测试，确认转绿。

## 8. oplog 合同（TDD）

- [ ] 8.1 写失败测试：`test_password_log_codes_contract`、`test_password_log_timing_contract`；确认红。
- [ ] 8.2 实现：新 `reset_container_password`、既有 `ADD_COLLABORATOR`/`UPDATE_COLLABORATOR_ROLE`/`CREATE_CONTAINER` 单条、无密码、超时未知不写成功。
- [ ] 8.3 重构并跑日志契约测试，确认转绿。

## 9. 全量回归与验证

- [ ] 9.1 跑聚焦安全测试（新增契约 + 相邻容器/用户/oplog 回归），修本次引入失败。
- [ ] 9.2 在 WSL 隔离环境跑完整安全套件，记录真实命令、pass/skip、失败定位。
- [ ] 9.3 读取 verify instructions，写 `verify.md`（真实 DECISION，不伪造 PASS）。
- [ ] 9.4 `git diff --check`，提交代码/测试/test-plan/tasks/verify。
