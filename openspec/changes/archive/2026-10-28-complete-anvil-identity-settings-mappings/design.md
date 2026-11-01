# Design

## Context

本 change 覆盖 6 个既有 backend 表能力、21 个 Requirement、49 个 Scenario。主规格已经定义了持久化结构、生命周期、权限快照、设置输入、操作日志与 SSH 补偿契约；本 change 不改变这些契约，只建立逐 Scenario 的测试映射并登记真实缺口。

现有断言分散在 `test/repository`、`test/user`、`test/settings`、`test/operation_log`、`test/container` 与 `test/machine`。测试运行在按用例重建并 seed 的内存 SQLite 上，外部 Node、SMTP 与后台调度线程是现有测试已经隔离的边界。规划阶段受以下约束：只写 proposal/design/specs/test-plan；不写 review、tasks、实际测试、主规格、sidecar、业务源码、共享 fixture、配置、CI、数据库或提交。

## Goals / Non-Goals

**Goals:**

- 49 个 Scenario 每个都有具体 test/check locator，并明确区分已确认的 existing assertion 与待补 planned test。
- 用 no-op MODIFIED delta 承载 6 个既有能力，原 Requirement 逐字保留，业务语义不变。
- 把所有真实缺口收敛到一个计划文件 `test/repository/test_anvil_identity_settings.py`，不新建共享 fixture 或测试目录。
- 让 fresh reviewer 能仅凭 locator、Assertion scope 与 Coverage note 判断覆盖边界，而不依赖运行台账。

**Non-Goals:**

- 不修复实现、不调整主规格、不同步 sidecar、不生成 tasks/review。
- 不在本阶段创建或运行测试，不修改现有测试的 mock 方式。
- 不引入真实 Node、SMTP、SSH、生产数据库或外部网络。
- 不用静态源码字符串、模型反射或 mock 目标逻辑来“补”行为断言。

## Decisions

### D1. no-op MODIFIED delta 逐字复制

每个能力建立 `specs/<capability>/spec.md`，只含 `## MODIFIED Requirements`，Requirement 正文与全部 Scenario 从主规格逐字复制。理由：本 change 没有 spec-level 行为变化，但 Anvil 的 specs artifact 需要能力 delta；逐字复制可让 sync 保持主规格不变，并让 review 只审映射。已用 `openspec validate --strict` 验证当前 6 个 delta。

### D2. 先 locator，后断言范围

test plan 以 Scenario 路径为唯一标识，不引入额外 ASCII ID。每个 Scenario 下使用 `- Test/check:` 与嵌套复选框；`[X]` 只给已从测试代码确认存在的 locator 与断言，`[ ]` 只给本 change 计划新增的专属测试。Assertion scope 使用中文描述实际可观察断言，不写“已验证/已通过”；不增加执行结果、时间戳、状态或台账段。

### D3. 单一计划文件承载缺口

计划文件固定为 `test/repository/test_anvil_identity_settings.py`，复用现有 `db_session`、`client` 同步 fixture 与 `test/factories.py` 中的 factory。文件内按能力分节，不修改 `test/conftest.py` 或任何共享 fixture。该文件虽然位于 repository 目录，但缺口包含 service/API 边界；这是用户指定的唯一新增文件，review 需按实际行为而非目录名判断。

### D4. 只 mock 外部边界，失败注入走真实代码路径

允许替换的边界：

- Node HTTP：`services.container_module.node_comms.send`（外部服务）。
- 后台调度：`password_utils.spawn_background` / `collaborator_utils.spawn_background`，测试同步执行捕获的 target（线程调度边界）。
- SMTP：`utils.mail._send_smtp` / `_send_batch_smtp`（外部服务）。
- 数据库写入失败：用 SQLAlchemy `before_cursor_execute` 事件对 `INSERT INTO operation_logs` 注入异常，而不是 monkeypatch `log_success` 或 `write_operation_log` 让目标逻辑短路。

不替换 `user_tasks.Register_with_code`、`container_tasks.start_*`、`operation_log_tasks.list_operation_logs`、`rbac_service.has_resource_wildcard`、`usercontainer_repo.remove_user_from_all_containers` 等被验证逻辑。API 鉴权测试尽量使用真实 cookie token 与真实 `authentications` 行；现有测试中 monkeypatch auth repo 的 locator 可以列为 existing，但不能据此宣称 401/403 行为已由该测试覆盖。野容器判定必须用真实容器/绑定数据触发，不能以 monkeypatch `remove_user_from_all_containers` 或 `Delete_user` 代替。

### D5. 缺口分类与落点

- 认证：登录清理过期 token、内部共享 token 不落 `authentications` 行；同一用户两 token 中一个遭遇 403 后其余 token 仍有效，容器状态变化不改变 token 有效性。
- 用户：注册 API 响应不含 `password_hash`；用真实唯一 ROOT 绑定触发野容器删除拒绝；容器资源通配与容器列表可见范围同判定；列表 API 的 `container:view` 方法门单独校验；`bypass_resource` 不派生方法实体；ROOT 绑定按具体容器另行判断；`users` 表无派生列（数据库 PRAGMA），快照按请求派生且请求不新增表。
- 注册码：过期错误响应不回显 `code_hash`；数据库只存哈希、明文 code 不出现；被拒绝注册后查询 `users` 确认无残留行；同一码的消费与用户创建在事务边界内至多成功一次且不遗留第二个用户。
- 设置：既有 `min_value`/`max_value` 越界仍拒绝且原值不变。
- 操作日志：列表响应不新增字段；重置/新增协作者/ROOT 交接日志的 target 标识、detail 角色/用户字段；恢复只写一条 `CREATE_CONTAINER`；受理时不写结果日志且既有日志不变；失败日志恰一条且脱敏；未知 Node 结果只写失败；日志写入失败不抛回、不伪造成功、不泄露密码；按时段/目标过滤；完整请求体与 Node 原始错误体不进入审计。
- SSH：不可用窗口补偿不改变 `last_ssh_login_time`，并作用于该机器全部记录；真实登录变化同时清零 `deferral_seconds` 并复位清理提醒。

无独立 Scenario 的 Requirement 正文约束（例如登录清理过期 token、资源列表同判定、提醒复位）挂到最相关的 Scenario 下，用已列 locator 或计划测试明确覆盖；不伪造新 Scenario，也不把约束写进主规格。

### D6. 状态码与持久化边界

认证失效与授权拒绝分离仍以 401/403 为可观察契约；内部运行态以 loopback + 共享 token 为边界，测试使用显式 client host 或真实 token 文件，不 monkeypatch `_is_loopback`。持久化断言优先直接查询真实 SQLite 行；只有 Scenario 本身要求检查表列时才用数据库 PRAGMA，并说明这不是模型反射。所有计划测试只在 per-test 内存 SQLite 上运行，PRAGMA/`sqlite_master` 只证明该隔离库的表列状态，不外推生产 schema；每请求派生用真实 `/api/users/me/permissions` 请求和真实 RBAC 行验证，不以反射或静态字符串替代。

## Risks / Trade-offs

- **恢复单条日志测试最重**：需要真实软删、快照、Node 成功响应与恢复流程；若现有 factory 不足以稳定构造，review 应要求缩小到可执行的恢复入口，而不是弱化“只写一条 `CREATE_CONTAINER`”的规格。
- **SQLite 并发测试有限**：同码并发缺口以“两个 stale reader + 条件消费 + 同一事务创建用户”的确定性事务测试表达，不承诺真实多线程竞争；这能验证数据库条件消费与无遗留用户，但不能替代生产并发压测。
- **既有测试的 mock 口径不统一**：部分 API 测试 monkeypatch `deps.authentications_repo` 或 `rbac_service.user_has_entity`。计划只把这些 locator 当作它们实际断言的那一部分覆盖，新增缺口测试优先走真实 cookie/RBAC 行，避免用目标逻辑 mock 冒充行为。
- **容器列表谓词重复实现**：`_get_visible_container_ids` 直接调用 `_has_entity_direct` 与 `_has_resource_manage_direct`，而快照调用 `has_resource_wildcard`。当前语义应一致；计划用列表/快照交叉断言钉住这一致性。若实现漂移，这是规格要求的真实缺陷，应报告父代理，不通过改测试或弱化规格掩盖。
- **未发现业务矛盾**：规划期未发现 Requirement 与现有实现直接冲突；发现的是覆盖缺口与一处判定重复风险，均不得通过修改实现或放宽规格“修复”。
