# Design

## Context

本变更处理 Ctrl 第 5 波中的容器清理相关四能力：`containers`（73 Scenario）、`deleted_container_restore_snapshot`（17）、`container_cleanup_reminders`（2）、`container_mount_cleanup`（2），合计 94 Scenario。原 attempt `fc130b46` 因明确 `quota_exceeded` 终止，本任务走官方 fallback；当前只做规划，fresh review 通过后才进入 apply。本文件已按 review `29120923` 的 REVISE 意见修订，四份 delta 文本仍保持逐字 no-op。

可用资产：

- 主规格：`openspec/specs/backend--table-containers/spec.md` 等四份，共 35 个 Requirement、94 个 Scenario。
- 主 sidecar：仅 `backend--table-containers/test-plan.md` 存在，但仍是旧表格与运行台账，且把 41 个既有 Scenario 标为“待复核”；其余三个能力无 sidecar。旧表只作线索，不复抄。
- 真实测试：`test/container/` 下的生命周期、信息、镜像、磁盘门禁、消失保护、删除/恢复、清理提醒、挂载清理、密码契约等文件；另有 `test/repository/`、`test/machine/`、`test/e2e/` 与 `test/test_entrypoint_docs.py` 的相关断言。
- 契约测试只使用隔离 SQLite、工厂与 Node 通信替身；没有真实 Docker、真实目录删除、真实 SMTP、真实 Node 服务或生产 MySQL。

约束：描述与产物用中文，结构标题与 SHALL/MUST 保持英文；本变更唯一可写目录是 `openspec/changes/complete-anvil-container-cleanup-mappings/`；不写 review/tasks/tests，不改主规格、主 sidecar、应用与共享资产；不 commit。

## Goals / Non-Goals

**Goals:**

1. 94 个 Scenario 全部落到 canonical 映射，且每个 Scenario 至少有一个 `[X]` 现有断言或 `[ ]` 规划缺口。
2. `[X]` 必须来自已读测试的真实断言；只覆盖部分 THEN 的，用 Coverage note 写清缺哪一段，不把“文件存在/测试名/反射/源码字串”当行为证据。
3. 缺口集中规划到单一新文件 `test/container/test_anvil_cleanup_contracts.py`，按能力分节、函数名统一 `test_anvil_` 前缀；复用既有 `db_session`、`client`、factories、`mock_node_send`、`session_scope`，不新建 conftest 或共享 fixture。
4. delta 的 MODIFIED Requirement 逐字复制主规格，Requirement 内不插入本轮说明；sync 后主规格业务与文本不变。

**Non-Goals:**

- 不修复应用缺陷，不调整表结构，不新增迁移，不改 Q74 已定的删除重置冻结/宽限与“恢复按新建、不旁路宽限”行为。
- 不重构测试目录，不新建共享 fixture，不改依赖、配置、CI、hooks、skills、SSH/secrets。
- 不验证真实 Docker 目录清理、真实 SMTP、真实 Node 服务或生产 MySQL；删除/恢复只使用假数据与通信替身。
- 不做实现或运行验证；规划产物不写运行结果台账。

## Decisions

1. **delta 用 MODIFIED 逐字 no-op。**
   四个能力本轮都没有行为变化，但 anvil 的 review 与同步需要能力级锚点。选择 `MODIFIED Requirements` + 完整 Requirement 块逐字复制，而不是 ADDED、空 delta 或 `skip_specs`；这样 delta 可解析、可对照，sync 后主规格无净变化。提取由脚本按 `### Requirement:` 边界完成，避免手抄漂移。

2. **`[X]` 按“断言是否证明 THEN”判定，不按测试是否存在。**
   例如：`test_create_container_success...` 只证明同会话落库与 root 绑定，不能证明新会话读取的类型/空值语义；`test_reset_permission_contract` 用 monkeypatch 放行资源层，不能证明真实 `container:manage`/`bypass_resource` 分支；`test_container_mount_cleanup_task::test_cleans_old_pending_mount` 只证明 `cleaned_at`，未证明关联 snapshot 同步与事务回滚；`test_container_cleanup_reminder_repo_advances_level_in_place` 只证明同一收件人一行，不能证明“每个 container_id 只有一条”（Q81）。此类条目保留 `[X]` 的部分断言，并用 `[ ]` 规划项补齐缺段。Q74 不新增 Scenario，统一落到 `test/container/test_long_term_transitions.py` 的既有删除/恢复用例，并在 test-plan 的 Requirement Coverage note 中登记。

3. **缺口集中到一个新测试文件。**
   新文件 `test/container/test_anvil_cleanup_contracts.py` 按 `containers`、`deleted_container_restore_snapshot`、`container_cleanup_reminders`、`container_mount_cleanup` 分节；函数名如 `test_anvil_c01_container_readback_and_defaults`、`test_anvil_d01_restore_snapshot_readback_and_defaults`、`test_anvil_r01_cleanup_reminder_readback_and_unique`、`test_anvil_m01_mount_cleanup_readback_and_defaults`。计划项覆盖读回/默认值、资源上限数值、恢复来源与挂载、历史隔离、评估门禁、密码交付与脱敏、重置/新增协作者拒绝分支、清理审计同步等缺口。复用既有 fixtures，不 mock 被测业务结果；只对 Node 通信、邮件、时间与后台调度等外部边界或测试接缝做替身。

4. **只使用隔离 SQLite 与通信替身，明确实际限界。**
   读回类缺口用新 `session_scope(commit=False)` 按主键读取；DB `server_default` 用裸 SQL 省略 `is_valid`/`mount_cleaned`/`deferral_seconds` 验证；Node 相关缺口用 `mock_node_send` 或 `node_comms.send` 替身；删除/恢复只构造快照与假路径，不断言真实目录被清空。该限界写进 design 与相关 Coverage note，不用“测试通过”替代真实外部行为。

5. **真实业务矛盾只报告，不改 app、不弱化规格。**
   已发现 `deleted_container_restore_snapshot` 的“浏览器路径或记录不完整”Scenario 正文称携带宿主路径应返回 `not_found` 或省略，但同一 Requirement 又规定 body 只含 `deleted_ids`、请求模型失败走 400 `invalid_payload`；父已核实该文字为规格误述并登记 Global Q82。test-plan 将 400 模型拒绝与 `not_found` 分支分开限界，host path 的 `not_found` 分支保留未覆盖/暂缓，不改应用或弱化规格。

## Review Follow-up

review `29120923` 的 REVISE 意见已按“先记录、独立补测继续”处理：

- Q74：在 `containers` 的 `生产职责与生命周期` Coverage note 中引用 `test/container/test_long_term_transitions.py` 的目标冻结行删除、其他容器不变、无冻结行、事务回滚、重复删除、API/cleanup 删除、恢复不继承冻结/宽限用例；不新增字段/表/DTO/协议。
- Q81：父已核实为规格误述（model/appendix 按 `(container_id, recipient_email)`，正文“每容器一条”错误）；test-plan 删除“`advances_level_in_place` 已覆盖单容器单行”的说法，保留该 clause 未覆盖/暂缓，不改 app、主规格或 sidecar。
- Q82：父已核实为规格误述（请求 schema 与非法请求 Scenario 确定额外宿主路径走 400；记录缺信息才 `not_found`）；test-plan 将 400 模型拒绝与 `not_found` 分支分开限界，host path 的 `not_found` 分支保留未覆盖/暂缓，不改业务返回。
- 真实补测：新增 pending 项 C35（reset 的 `bypass_auth_entity`/`target_not_bound`/`machine_offline`/额外字段拒绝分支无密码/无 Node/无凭据）、C36（旧代 delete 帧保留账号/长期关联）、C37（错误测量拒绝日志）、C38（过期不重开/不顺延既有冻结周期）、C39（创建 wire `config.image`）。
- Non-blocking 收口：C06 改为两份等价快照避免消费复用；M02 增加双写事务回滚故障注入；C31 明确“响应后独立执行后台任务”是断连模拟而非真实 socket；C14 明确同时覆盖 message 保留；S1 收窄为详情只断言默认状态，不宣称非内存。

## Risks / Trade-offs

- **映射可能随测试重构漂移。** nodeid 写全路径；若后续改名/移动测试，需同步更新映射并重新 review。缓解：优先引用稳定、语义明确的既有测试，并在 Assertion scope 写清被断言的字段与分支。
- **部分 `[X]` 只覆盖 THEN 的一部分。** 例如详情非空路径未断言“不调 Node”、重置拒绝分支未断言“不生成密码”、挂载清理成功未断言 snapshot 同步。已在 Coverage note 标明，并用 `[ ]` 规划项补齐；不把 `[X]` 当完整覆盖。
- **SQLite 与替身不能证明生产 MySQL、真实 Docker 目录清理、SMTP 或真实 Node。** 这是本阶段刻意限界；计划项只证明 Ctrl 侧可观察契约，不宣称跨进程原子性或真实外部副作用。
- **逐字 no-op delta 在 sync 时可能被判“无净变更”。** 这是预期结果，不是失败；若 CLI 对无净变更报错，应在 sync 阶段显式说明并按既有 no-op 处理，不为制造变更而改 Requirement 文本。
- **Q81 是已核实的规格误述，不需要新的业务/表结构决定。** 父已源码核对并登记 Global Q81：model/appendix 确定按 `container + recipient`；主规格正文“每个 `container_id` 只有一条”是误述。test-plan 继续保留该 clause 未覆盖/暂缓的限制，不把 `advances_level_in_place` 当作单容器单行证据，不改表、返回或主规格。
- **Q82 是已核实的规格误述，不需要新的业务决定。** 父已源代码核对并登记 Global Q82：请求 schema 与非法请求 Scenario 确定额外宿主路径走 400 `invalid_payload`，记录缺机器信息才走 `not_found`。test-plan 将 400 模型拒绝与记录不完整的 `not_found` 分支分开，host path 的 `not_found` 分支保留未覆盖/暂缓，不改业务返回。
