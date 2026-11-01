# Test Plan

## backend--table-announcements

### Requirement: announcements 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_announcement_and_template_models_have_no_creator
  - [X] test/announcement/test_models.py::test_m01_announcement_create_full_fields
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_a01_announcement_readback_contract
- Assertion scope: 第一条用新 session/反射检查 `announcements` 的列与 mapper，断言不存在 `created_by` 列、`creator` 关系或指向 `users.id` 的创建者外键；`test_m01` 与 `test_anvil_a01` 不再传/断言 `created_by`，仍断言标题、正文、原始正文、状态、目标快照、计数、来源草稿与时间字段按原语义往返。

#### Scenario: 创建者删除后保留公告

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_delete_author_keeps_announcements_and_templates
- Assertion scope: 先建用户 A、B，A 的草稿作为来源，模板含非空描述，公告含非空 `template_id`/`source_draft_id`/`sent_at` 与计数、正文、原文、targets、target_snapshot；删除 A 前在独立 session 对公告与模板全部标量字段做快照，删除后新 session 断言公告/模板快照逐字段完全相等、A 草稿消失、B 草稿保留；随后重发，断言邮件收件人为 B、标题/正文来自公告已保存内容且公告仍为 SENT。

#### Scenario: 公告出参不含创建者

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_announcement_and_template_api_views_omit_creator
  - [X] test/announcement/test_api.py::test_a15_list_announcements
- Assertion scope: 新建 3 条时间互异的模板与公告后，请求 `limit=2&offset=1`：断言列表响应键分别为 `{success,templates,total}` 与 `{success,announcements,total,sent_count,partial_count,failed_count}`，`total=3`，按 `created_at` 降序返回第 2、3 条对应 id；详情响应键为 `{success,template}`/`{success,announcement}`。每个详情和列表项的键集合精确等于既有模板/公告视图字段集合（公告 14 键、模板 9 键），不含 `created_by`；`test_a15` 另断言公告列表项不含 `created_by`。

### Requirement: 公告发送与复用不依赖创建者归属

#### Scenario: 批量发送与重发保持内容

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_batch_send_and_resend_do_not_require_creator
  - [X] test/announcement/test_services.py::test_s10_send_draft_all_success
  - [X] test/announcement/test_services.py::test_s17_resend_from_sent
- Assertion scope: `test_s10`/`test_s17` 不再传创建公告时的 `created_by`，捕获 mock 传输消息并断言收件人来自目标用户邮箱、`subject` 与 `content` 来自草稿/公告已保存内容；批量发送产生 SENT 公告，逐项断言 `title`、`content`、`raw_content`、`targets`、`source_draft_id`、`recipient_count` 与计数；重发沿用同一公告并回到 SENT，标题/正文/目标/来源未变。归属契约测试断言公告模型无 `created_by`/`creator`。

#### Scenario: 复制公告为草稿归属当前操作员

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_copy_announcement_as_draft_assigns_current_operator
  - [X] test/announcement/test_services.py::test_s19_copy_as_draft_content_match
- Assertion scope: 用户 A 的公告由用户 B 复制为草稿时，新草稿 `created_by == B.id`、标题与 targets 复制自公告；公告 `raw_content` 有值时草稿 `content` 与 `raw_content` 都等于该原文（原公告 content 与 raw 使用不同 fixture）；另验证 raw 缺失时草稿 `content` 回退公告 content 且 `raw_content is None`。B 能列出该草稿而 A 的列表不含它，公告本身无创建者字段。

#### Scenario: 公告转模板不写创建者

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_convert_announcement_to_template_without_creator
  - [X] test/announcement/test_services.py::test_s21_convert_to_template_preserves_content
  - [X] test/announcement/test_services.py::test_s23_convert_to_template_source_tracked
- Assertion scope: 调用转模板服务时不再传 `created_by`；断言模板 `subject_template`/`body_template` 等于公告内容、`source_announcement_id` 指向原公告，且模板模型/出参无 `created_by`。两条服务测试与归属契约测试分别断言模板无 `created_by`/`creator`。

### Requirement: 公告归属旧库迁移

#### Scenario: 旧约束名可发现且迁移幂等

- Test/check:
  - [X] test/announcement/test_ownership_migration_plan.py::test_planner_selects_auto_and_explicit_fk_names
  - [X] test/announcement/test_ownership_migration_plan.py::test_planner_compiles_mysql_ddl_and_rejects_other_dialects
  - [X] test/announcement/test_ownership_migration_plan.py::test_migrate_entry_rejects_sqlite_before_ddl
  - [X] cd /mnt/e/AI/Fuxi/FuxiYu_CtrKernel && /home/chest/miniconda3/envs/fuxi/bin/python /mnt/e/AI/Fuxi_audit_artifacts/q68-q51-20261029/check_mysql_migration.py
- Assertion scope: 单元行只验证规划与入口边界：fake Inspector 元数据断言自动名与显式名外键均被选中，DDL 使用实际发现的名称；非预期复合列、错误 target/列或同一列多个 FK 必须在生成任何 DDL 前抛 `MigrationError`；实际 `migrate(url)` 入口收到 SQLite URL 时必须在任何 DDL 前拒绝，测试 SQLite 的 schema 前后不变。root harness 无 CLI 参数，读取同目录 `mysql-instance.json`/`legacy-mysql-before.json`，重置其自有 `q68_fixture` 与 `q68_fixture_explicit`；分别用自动名和 `q68_<table>_explicit_author` 显式名建旧四表，对每个 schema 调用产品迁移 CLI 两次，断言两次退出 0、公告/模板 `created_by` 列及外键消失、草稿 `created_by` 外键为 `ON DELETE CASCADE`，并输出 `mysql-migration-acceptance.json`。不得用静态 SQL 字符串断言代替真实执行。
- Coverage note: 单元行不连接 MySQL，只证明元数据/编译/入口拒绝；真实迁移、自动/显式外键名与两次幂等由 root harness 覆盖，最终脚本重跑结果以 root 报告为准。生产 MySQL 未执行；产品仓不复制 harness。

#### Scenario: 迁移保留既有内容

- Test/check:
  - [X] cd /mnt/e/AI/Fuxi/FuxiYu_CtrKernel && /home/chest/miniconda3/envs/fuxi/bin/python /mnt/e/AI/Fuxi_audit_artifacts/q68-q51-20261029/check_mysql_migration.py
- Assertion scope: root harness 对两个自有 schema 按 `legacy-mysql-before.json` 重放旧 DDL 与数据；迁移后逐行比较所有迁移不应改动的数据：公告/模板除被删的 `created_by` 外全部字段，草稿含 `created_by` 的全部字段。比较范围包括标题、`content`/`raw_content`、目标、目标快照、状态、成功/失败/收件计数、时间、`source_draft_id`、`template_id`、草稿 `created_by` 与行数；文本按原值、数值/时间/空值按稳定规范化比较。随后 harness 插入新的无作者公告与模板，事务删除 user3 并确认其草稿级联后回滚，再提交删除 user1，断言草稿 2/3、3 条公告和 4 条模板保留。不把 SQLite 结果当作该证据，也不虚构临时用户/草稿插入。
- Coverage note: 真实 MySQL 内容比较、无作者插入、user3 回滚与 user1 提交均由 root 执行上述 harness；脚本完成后生产库仍未被迁移，不能据此宣称已部署。

#### Scenario: 普通启动不自动删列

- Test/check:
  - [X] test/announcement/test_ownership_startup.py::test_ensure_announcement_schema_does_not_drop_creator_columns
  - [X] manual check (source call chain): `__init__.py` `create_app` → `_init_database` → `_ensure_announcement_schema`，确认该链未 import/调用 `migrations.migrate_announcement_ownership`
- Assertion scope: 自动测试只覆盖启动链中的一个 helper：在一次性 SQLite 表上补旧 `created_by` 列，给迁移入口装哨兵，调用 `_ensure_announcement_schema`，断言哨兵未触发且两列仍存在。它不冒充完整 `create_app` 启动；完整边界由源码调用链检查补充，确认普通启动不会导入或执行迁移。
- Coverage note: 未在自动测试中启动完整 `create_app`（避免重绑全局引擎/种子副作用）；已明确 helper 测试边界，并用 `create_app → _init_database → _ensure_announcement_schema` 的完整源码链检查补足“启动不删列/不调迁移”的证据，不把它外推为 MySQL 迁移证据。

## backend--table-announcement-templates

### Requirement: announcement_templates 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_announcement_and_template_models_have_no_creator
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t01_template_readback_contract
- Assertion scope: 模型测试断言 `announcement_templates` 不存在 `created_by` 列、`creator` 关系或 `users.id` 创建者外键；`test_anvil_t01` 用新 session 读回名称、类别、描述、主题/正文模板、来源公告和时间字段，并断言无创建者属性。

#### Scenario: 创建者删除后保留模板内容

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_delete_author_keeps_announcements_and_templates
- Assertion scope: 删除历史模板作者后，模板行、名称、类别、描述、`subject_template`、`body_template`、`source_announcement_id` 与时间字段逐项不变，模板仍可被列表/详情读取。

#### Scenario: 模板出参不含创建者

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_announcement_and_template_api_views_omit_creator
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t02_api_template_detail_returns_editor_initial_values
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t05_api_template_pagination_order_default_and_filtered_total
- Assertion scope: 模板列表、详情和公告转模板响应均不含 `created_by`；`test_anvil_t02` 保留主题/正文/来源公告断言并断言字段缺失，请求前后草稿与公告行数不变；`test_anvil_t05` 不再构造 `created_by`，仍断言默认 100/offset、`category` 过滤后的 `total` 与顺序、205 条分页切片和既有模板字段不变，且列表项不含 `created_by`。

### Requirement: SYSTEM 模板类别不可变更

#### Scenario: SYSTEM 改为其他类别被拒绝

- Test/check:
  - [X] test/announcement/test_system_template_category_guard.py::test_system_to_custom_rejected_with_reason
  - [X] test/announcement/test_system_template_category_guard.py::test_repository_rejects_system_category_change
- Assertion scope: API 对 SYSTEM 模板提交 `category=custom` 返回 400、`success=0`、`error_reason=cannot_change_system_template_category`，数据库类别仍为 SYSTEM；仓储直调同一变更抛同原因且不 flush 任何字段修改，证明路由和仓储两层都不放行。

#### Scenario: 多字段更新失败不部分落库

- Test/check:
  - [X] test/announcement/test_system_template_category_guard.py::test_system_multi_field_update_is_atomic_on_rejection
- Assertion scope: 同一请求同时提交新名称、描述、主题模板、正文模板与 `category=custom`，断言 400 后从新 session 读回的五个字段全部等于更新前值；不出现类别仍 SYSTEM 而名称/正文已改的半更新。

#### Scenario: 省略类别可编辑其他内容

- Test/check:
  - [X] test/announcement/test_system_template_category_guard.py::test_system_content_update_without_category_allowed[omitted]
  - [X] test/announcement/test_system_template_category_guard.py::test_system_content_update_without_category_allowed[null]
- Assertion scope: 同一参数化测试分别提交“不含 `category`”和 `category: null` 的名称/描述/主题/正文更新，均断言 200、提交字段全部生效、类别仍为 SYSTEM；显式 null 沿用既有“忽略 None 字段”语义，不新增业务规则。

#### Scenario: 同类别可编辑其他内容

- Test/check:
  - [X] test/announcement/test_system_template_category_guard.py::test_system_content_update_with_same_category_allowed
- Assertion scope: 对 SYSTEM 模板提交 `category=system` 并修改名称/描述/主题/正文，断言 200，四个提交字段全部生效，类别仍为 SYSTEM。

#### Scenario: CUSTOM 改为 SYSTEM 保持允许

- Test/check:
  - [X] test/announcement/test_system_template_category_guard.py::test_custom_to_system_allowed
- Assertion scope: 对 CUSTOM 模板提交 `category=system` 及名称/描述/主题/正文更新，断言 200，类别变为 SYSTEM，四个内容字段按请求全部生效，不返回类别守卫错误。

## backend--table-announcement-drafts

### Requirement: announcement_drafts 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/announcement/test_models.py::test_m02b_draft_readback_contract
  - [X] test/announcement/test_models.py::test_m02_draft_create_full_fields
- Assertion scope: 新 session 读回草稿，断言 `created_by` 为稳定整数且等于创建者主键、`creator.id` 一致，标题/正文/原始正文/目标/时间字段类型与空值语义不变；确认模型仍无 `template_id`。

#### Scenario: 草稿创建者外键为级联删除

- Test/check:
  - [X] test/announcement/test_draft_ownership.py::test_fresh_sqlite_draft_fk_is_cascade_and_pragma_on
- Assertion scope: 新建 SQLite 测试库后用 `PRAGMA foreign_keys` 断言为 1，用 `PRAGMA foreign_key_list(announcement_drafts)` 断言 `created_by` 指向 `users.id` 且 `on_delete=CASCADE`。
- Coverage note: 既有 `test_user_delete_is_blocked_by_token_without_explicit_cleanup` 只证明 token FK 真实执行，未检查草稿 FK，故不作为本场景证据；只作为 PRAGMA/外键引擎的旁证记录在案。

### Requirement: 草稿私有归属继续隔离

#### Scenario: 他人草稿不可读写删发

- Test/check:
  - [X] test/announcement/test_draft_ownership.py::test_q08_repo_read_and_delete_are_owner_scoped
  - [X] test/announcement/test_draft_ownership.py::test_q08_repo_update_other_operators_draft_rejected_and_unchanged
  - [X] test/announcement/test_draft_ownership.py::test_q08_batch_send_rejects_other_operators_draft_without_side_effects
  - [X] test/announcement/test_draft_ownership.py::test_q08_api_two_operator_isolation
- Assertion scope: 仓储层他人读取返回 None、删除返回 False、更新抛 `draft_not_found` 且原草稿不变；服务层他人批量发送抛 `draft_not_found`，原草稿保留且不产生 SENDING 公告；API 隔离测试断言他人五条路径被拒且完整草稿快照不变。

#### Scenario: 所属者仍可读写自己的草稿

- Test/check:
  - [X] test/announcement/test_models.py::test_m02b_draft_readback_contract
  - [X] test/announcement/test_draft_ownership.py::test_q08_api_two_operator_isolation
- Assertion scope: 模型读回确认 `created_by`/`creator` 保留；API 隔离测试的所属者分支断言列表 `total=1`、`drafts[0]["created_by"] == owner.id`、详情 `created_by` 为稳定整数且标题/正文/原始正文/目标与保存值一致，更新后仍属于同一创建者。

### Requirement: 用户删除级联所属草稿

#### Scenario: 成功删除只清理目标用户草稿

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_cascades_own_drafts_and_keeps_others
  - [X] test/announcement/test_ownership_contracts.py::test_delete_author_keeps_announcements_and_templates
- Assertion scope: 服务路径建目标 token、目标草稿、其他用户草稿、公告/模板；把 `announcement_repo.delete_draft` 替换为“被调用即失败”的 spy，`Delete_user` 成功后断言目标用户、token、所属草稿不存在、spy 未触发，其他用户草稿与公告/模板快照不变。删作者用例另在全新 session 比较公告/模板全部标量快照，并验证删除后重发内容。

#### Scenario: 最终事务失败整体回滚

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_cascade_rolls_back_on_transaction_failure
- Assertion scope: 包裹真实 `delete_user` 调用，在用户行及所属草稿已经 flush/级联后抛出异常，断言 `Delete_user` 向上抛出且新 session 中用户、认证记录、所属草稿全部保留，其他用户草稿、公告和模板不受影响。

#### Scenario: 无草稿用户仍可删除

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_success_unbinds_before_delete
- Assertion scope: 无草稿用户仍按既有路径成功删除，移除绑定先于最终删除，不因缺少草稿级联行而报错。

## backend--table-users

### Requirement: 用户删除原子清理所属草稿

#### Scenario: 有认证记录和草稿但无阻塞容器

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_cascades_own_drafts_and_keeps_others
  - [X] test/user/test_user_api_profile.py::test_delete_user_with_drafts_actually_deletes_them
- Assertion scope: 服务路径建目标用户 token、目标草稿、其他用户草稿、公告/模板，删除后断言目标用户/token/所属草稿不存在、其他草稿保留、公告/模板快照不变，且 `delete_draft` spy 未触发。API 路径建目标 token、目标草稿、其他用户草稿，通过真实删除接口断言目标用户/token/所属草稿消失、其他草稿保留；该行不重复公告/模板 fixture。两条路径合计覆盖本 Scenario；未对 `session_scope` 造 spy，最终事务边界由 `Delete_user` 代码审查和既有 token 失败回滚测试确认。

#### Scenario: 容器阻止删除

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_wild_container_keeps_user_and_tokens
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_wild_container_keeps_drafts
- Assertion scope: 既有测试证明 wild_container 分支保留用户与 token；wild-container 草稿测试建目标 token/草稿、其他用户草稿、公告/模板，断言异常后目标用户/token/草稿、其他草稿及公告/模板快照均不变。wild 分支的可观察数据边界由该测试覆盖；未对最终事务入口造 spy。

#### Scenario: 最终事务在级联后失败

- Test/check:
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_token_delete_failure_rolls_back_user
  - [X] test/user/test_user_tasks_profile.py::test_delete_user_cascade_rolls_back_on_transaction_failure
- Assertion scope: 既有测试覆盖 token 删除在用户删除前失败时用户与 token 回滚；after-cascade 测试建目标 token/草稿、其他用户草稿、公告/模板，并在失败前后比较公告/模板标量快照；断言用户、token、目标草稿恢复，其他草稿及公告/模板内容不变。两条合起来覆盖最终事务的前后失败点。
- Coverage note: 既有 token 失败测试不覆盖级联之后失败；after-cascade 用例是“级联后回滚”的直接证据。
