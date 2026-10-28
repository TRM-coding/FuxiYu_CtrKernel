# Test Plan

本计划是场景到测试/检查的映射，不是运行台账：`[X]` 表示该映射已按测试源码核对过断言，`[ ]` 表示计划中或尚未确认，两者都不代表执行结果、通过与否或自动等于场景全覆盖。

## backend--table-announcement-drafts

### Requirement: announcement_drafts 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/announcement/test_models.py::test_m02b_draft_readback_contract
  - [X] test/announcement/test_models.py::test_m02_draft_create_full_fields
- Assertion scope: `test_m02b` 用新 session 按主键重开“最小草稿”和“完整草稿”，断言 `id`/`title`/`content` 是 `str`、`created_by` 是 `int` 且等于创建者用户主键、`creator.id` 与主键一致（未用展示名替代）、`created_at`/`updated_at` 是插入时间窗内的 `datetime`、`raw_content` 与 `targets` 未赋值时回读为 `NULL`、赋值时按文本原样往返且 `targets` 不被解析成对象；`test_m02` 断言创建后 `title`/`content`/`created_by`/`creator.id` 与写入一致，并确认模型无 `template_id`。
- Coverage note: 该表没有业务唯一键，因此未断言数据库级 NULL 拒绝；未验证生产 MySQL 方言下的默认值行为。

### Requirement: announcement_drafts 生产职责与生命周期

#### Scenario: 保存与列出草稿

- Test/check:
  - [X] test/announcement/test_template_decoupling.py::test_q07_save_draft_ignores_template_id_input
  - [X] test/announcement/test_template_decoupling.py::test_q07_reopening_draft_never_replays_template_over_edited_content[edited]
  - [X] test/announcement/test_template_decoupling.py::test_q07_reopening_draft_never_replays_template_over_edited_content[deleted]
  - [X] test/announcement/test_draft_ownership.py::test_q08_repo_list_only_returns_own_drafts
  - [X] test/announcement/test_draft_ownership.py::test_q08_api_two_operator_isolation
- Assertion scope: `test_q07_save_draft_ignores_template_id_input` 经 API 保存带旧 `template_id` 的草稿，断言详情出参不含 `template_id`、持久化对象无该属性、再次保存仍是同一份独立快照（`content` 反映第二次编辑）；两个 `test_q07_reopening...` 参数分支断言重开与列表返回的 `title`/`content`/`raw_content`/`targets`/`created_by` 是保存时的完整快照；`test_q08_repo_list_only_returns_own_drafts` 断言 `list_drafts(created_by=owner.id)` 只返回 1 条该创建者草稿；`test_q08_api_two_operator_isolation` 断言两个操作员的列表 `total` 分别为 0 与 1、所属者详情 `created_by` 是稳定 int 主键。
- Coverage note: 前端“选模板复制初值”的 UI 行为不在本后端规格内。

#### Scenario: 其他操作员尝试操作

- Test/check:
  - [X] test/announcement/test_draft_ownership.py::test_q08_repo_read_and_delete_are_owner_scoped
  - [X] test/announcement/test_draft_ownership.py::test_q08_repo_update_other_operators_draft_rejected_and_unchanged
  - [X] test/announcement/test_draft_ownership.py::test_q08_batch_send_rejects_other_operators_draft_without_side_effects
  - [X] test/announcement/test_draft_ownership.py::test_q08_api_two_operator_isolation
- Assertion scope: 仓储层带 `created_by=other.id` 的 `get_draft_by_id` 返回 `None`、`delete_draft` 返回 `False` 且原行仍在、`save_draft` 抛 `draft_not_found` 且 `title`/`content`/`created_by` 不变；服务层批量发送抛 `draft_not_found`，之后草稿仍在且不存在 `SENDING` 公告；API 层对他人的 `draft_id` 逐项被拒（列表 `total=0`、读取 404、保存 404 `draft_not_found`、删除 404、批量发送 404 `draft_not_found`），每次失败后完整草稿快照（含 `raw_content`、`targets`、`created_at`、`updated_at`）与全部公告逐字段快照都不变，且所属者自己的读取/更新路径仍可用。
- Coverage note: 未覆盖真实后台投递、真实 SMTP 与并发竞态。

#### Scenario: 模板变化后重开草稿

- Test/check:
  - [X] test/announcement/test_template_decoupling.py::test_q07_reopening_draft_never_replays_template_over_edited_content[edited]
  - [X] test/announcement/test_template_decoupling.py::test_q07_reopening_draft_never_replays_template_over_edited_content[deleted]
  - [X] test/announcement/test_template_decoupling.py::test_q06_edit_or_rename_template_does_not_touch_generated_content
- Assertion scope: `[edited]` 分支在模板正文被改后重开草稿，`[deleted]` 分支在模板被删后重开；两次都断言详情与列表返回相同的 `title`/`content`/`raw_content`/`targets`/`created_by`、出参无 `template_id`、列表 `total=1`，即不重新套用模板也不因模板缺失失败；`test_q06_edit_or_rename...` 断言改名+改正文+删除模板后草稿 `title`/`content` 与公告 `content` 都不被改写。
- Coverage note: `test_q06_edit_or_rename...` 只比对 `title`/`content`，完整字段由两个 reopening 分支覆盖。同属模板解耦的 `test_q06_legacy_sqlite_draft_reference_is_safely_detached` 验证的是旧库残留 `template_id` 列的启动自愈（可重复执行、残留引用清零后才可删模板），属主规格“旧库兼容”附录的线索，不映射为本场景证据；未验证生产 MySQL 上的旧列迁移/删列行为。

## backend--table-announcement-templates

### Requirement: announcement_templates 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t01_template_readback_contract
  - [X] test/announcement/test_models.py::test_m03_template_unique_name
  - [X] test/announcement/test_models.py::test_m06_template_source_announcement_id
  - [X] test/announcement/test_repository.py::test_r07_create_template
- Assertion scope: `test_m03` 断言第二次写入同名模板 commit 时抛 `IntegrityError`（`name` 唯一键）；`test_m06` 断言 `source_announcement_id` 未赋值时为 `None`、赋 42 后读回 42；`test_r07` 断言创建后 `id`/`name`/`description` 与写入一致。三者都在同一 session 断言，未按主键重开。计划项 `test_anvil_t01` 用新 session 按主键重开模板，断言 `id`/`name`/`subject_template`/`body_template` 是 `str`、`created_by` 是 `int` 且等于创建者用户主键（不是展示名）、`category` 为默认 `custom`、未赋值的 `description` 与 `source_announcement_id` 回读为 `NULL`、`created_at`/`updated_at` 是插入时间窗内的 `datetime`、赋值时按文本原样往返。
- Coverage note: 既有 `[X]` 只覆盖同 session 的唯一键与 `source_announcement_id` 取值；跨 session 的类型、默认 `category` 与可空列空值语义仍是缺口。

### Requirement: announcement_templates 生产职责与生命周期

#### Scenario: 读取模板

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t02_api_template_detail_returns_editor_initial_values
  - [X] test/announcement/test_api.py::test_a07_get_template_by_id
  - [X] test/announcement/test_services.py::test_s23_convert_to_template_source_tracked
- Assertion scope: `test_a07` 断言 `GET /api/announcements/templates/{id}` 成功且返回的 `template.id` 等于被创建模板；`test_s23` 断言由公告转换出的模板其 `source_announcement_id` 指向原公告（仅作来源追溯）。两者都没有断言编辑器初值 `subject_template`/`body_template` 从详情出参返回，也没有断言取模板不建立草稿或公告的持久依赖。计划项 `test_anvil_t02` 断言详情出参的 `subject_template`/`body_template` 等于模板落库值、`source_announcement_id` 原样返回，且请求前后草稿行数与公告行数不变。
- Coverage note: 既有 `[X]` 覆盖详情 id 与来源追溯；编辑初值返回、请求前后无新增草稿/公告仍是缺口；该场景未涉及前端实际填充编辑器的行为。

#### Scenario: 删除被历史内容引用的自定义模板

- Test/check:
  - [X] test/announcement/test_template_decoupling.py::test_q06_delete_template_referenced_by_announcement_keeps_content
  - [X] test/announcement/test_models.py::test_m07_draft_has_no_template_association
  - [X] test/announcement/test_template_decoupling.py::test_q06_legacy_sqlite_draft_reference_is_safely_detached
  - [X] test/announcement/test_repository.py::test_r10_delete_template_system
  - [X] test/announcement/test_api.py::test_a10_delete_system_template
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t03_delete_template_preserves_announcement_and_draft_snapshots
- Assertion scope: `test_q06_delete...` 断言删除被公告引用的自定义模板返回 `True`、模板查询为空、重读公告 `content` 不变且 `template_id` 被置空；`test_m07` 断言草稿无 `template_id` 列/属性、删除模板后草稿 `content` 不变；`test_q06_legacy...` 断言旧库残留外键先挡住删除、启动自愈把残留引用清零（可重复执行）后删除成功；`test_r10` 断言仓储删除 SYSTEM 模板返回 `False` 且模板仍在；`test_a10` 断言 API 删除 SYSTEM 模板返回 400 `cannot_delete_system_template`。计划项 `test_anvil_t03` 先建模板、草稿和带历史 `template_id` 的公告，并用 `utils.mail.send_batch` 经既有测试替身产生一条真实 `send_mail` 操作日志；删除前快照公告的 `title`/`content`/`raw_content`/`targets`/`target_snapshot`/`recipient_count`/`status`、草稿的 `title`/`content`/`raw_content`/`targets` 及日志行，删除后断言公告 `title`、草稿 `title` 和上述主题/正文/目标/投递字段逐项保留，公告仅 `template_id` 解除，投递日志（`success`、`target_type`、`target_id`、`detail`）仍在且未被改写。
- Coverage note: `test_r10`/`test_a10` 是 Requirement 级 SYSTEM 删除拒绝检查，不是本 Scenario 的“删除被历史内容引用的自定义模板”THEN 证据；既有 `[X]` 覆盖解除引用与正文快照，公告主题、目标与投递记录的全字段保留仍是缺口。未验证生产 MySQL 外键与真实 SMTP。

### Requirement: announcement_templates 列表分页参数有界且可分页

#### Scenario: 界内分页参数

- Test/check:
  - [X] test/announcement/test_api.py::test_a06_list_templates
  - [X] test/announcement/test_api.py::test_a06c_list_templates_paginates_beyond_200
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t05_api_template_pagination_order_default_and_filtered_total
- Assertion scope: `test_a06` 只断言默认请求（无参数）成功，未断言返回条数、`offset=0` 或 `total`；`test_a06c` 在 205 条模板下断言 `limit=200&offset=0` 返回 200 条且 `total=205`、`limit=200&offset=200` 返回 5 条且 `total=205`、`limit=100` 返回 100 条。计划项 `test_anvil_t05` 用互异 `created_at` 建 205 条模板（含 `custom`/`system` 两类），断言无参数默认请求返回 100 条、`total=205` 且 id 顺序等于 `created_at` 降序期望切片（等价于 `limit=100&offset=0`）；再断言 `category=custom` 的 `total` 等于过滤后完整数量，过滤结果的 `limit`/`offset` 切片仍按同一 `created_at` 降序。
- Coverage note: `test_a06` 只断言成功形状；`test_a06c` 只覆盖显式 100/200 的长度与 `total`；默认 100/0、过滤后 `total` 与真实排序仍是缺口。

#### Scenario: 越界或非整数参数

- Test/check:
  - [X] test/announcement/test_api.py::test_a06b_list_templates_rejects_invalid_pagination[limit=0]
  - [X] test/announcement/test_api.py::test_a06b_list_templates_rejects_invalid_pagination[limit=201]
  - [X] test/announcement/test_api.py::test_a06b_list_templates_rejects_invalid_pagination[offset=-1]
  - [X] test/announcement/test_api.py::test_a06b_list_templates_rejects_invalid_pagination[limit=not-a-number]
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t04_api_template_list_rejects_non_integer_offset
- Assertion scope: 四个参数化分支分别以 `limit=0`、`limit=201`、`offset=-1`、`limit=not-a-number` 请求列表，断言 400 且 `error_reason=invalid_payload`。计划项 `test_anvil_t04` 补 Requirement 明文要求、但场景参数列表与既有分支都未覆盖的“非整数 `offset`”：断言 `GET /api/announcements/templates?offset=not-a-number` 返回 400 与 `error_reason=invalid_payload`。
- Coverage note: 场景列出的 4 类参数已由 `[X]` 覆盖；非整数 `offset` 仍是缺口。前端取值方式与 Web 分页交互不在本规格内。

#### Scenario: 205 条模板分页

- Test/check:
  - [X] test/announcement/test_api.py::test_a06c_list_templates_paginates_beyond_200
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t05_api_template_pagination_order_default_and_filtered_total
- Assertion scope: `test_a06c` 断言 `limit=200&offset=0` 返回 200 条且 `total=205`、`limit=200&offset=200` 返回 5 条且 `total=205`，但不比对跨页顺序。计划项 `test_anvil_t05` 为 205 条模板设置互异 `created_at`，按 `created_at` 降序计算期望顺序，断言第一页 id 序列等于 `expected[0:200]`、第二页 id 序列等于 `expected[200:205]`，并断言两页无重复、并集为全部 205 条；两页 id 集合关系只是切片正确后的附带结果，排序证据是逐 id 与期望顺序一致。该检查能证明查询在排序后应用 `offset`/`limit`。
- Coverage note: `test_a06c` 只覆盖长度与 `total`，不证明排序或 `offset`/`limit` 的先后关系；跨页真实顺序仍是缺口。ID 集合的不重不漏本身不能证明排序。

## backend--table-announcements

### Requirement: announcements 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/announcement/test_repository.py::test_r02_get_announcement_by_id_exists
  - [X] test/announcement/test_models.py::test_m01_announcement_create_full_fields
  - [X] test/announcement/test_models.py::test_m05_targets_json_roundtrip
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_a01_announcement_readback_contract
- Assertion scope: `test_r02` 按存在 id 读取并断言返回对象非空、`id` 相同；`test_m01` 创建后断言 `id`/`title`/`content`/`raw_content`/`created_by`/`status`/`recipient_count`/`source_draft_id` 与写入一致，但断言的是同一 session 的内存对象而非按主键重开；`test_m05` 断言 `targets` JSON 文本读出后 `json.loads` 等于原始列表。计划项 `test_anvil_a01` 用新 session 按主键重开“最小公告”和“完整公告”，断言 `title`/`content` 是 `str`、`status` 为枚举值、`created_by` 是 `int` 且等于创建者用户主键、未赋值的 `recipient_count`/`success_count`/`fail_count` 回读为默认 0、未赋值的 `targets`/`target_snapshot`/`raw_content`/`sent_at`/`source_draft_id`/`template_id` 回读为 `NULL`、赋值的 `targets`/`target_snapshot` 按文本原样往返、赋值的 `source_draft_id` 按原值往返、`created_at` 是插入时间窗内的 `datetime`。
- Coverage note: 既有 `[X]` 未覆盖默认计数、`target_snapshot`、`sent_at`、`source_draft_id` 与跨 session 空值语义，这些仍是缺口；未验证生产 MySQL 方言。

### Requirement: announcements 生产职责与生命周期

#### Scenario: 批量发送受理

- Test/check:
  - [X] test/announcement/test_api.py::test_a30b_batch_send_returns_accepted_without_waiting
  - [X] test/announcement/test_api.py::test_a30_batch_send
  - [X] test/announcement/test_services.py::test_s10_send_draft_all_success
  - [X] test/announcement/test_services.py::test_s15_batch_send_three_drafts
  - [X] test/announcement/test_services.py::test_s24_settle_stuck_sending_on_startup
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_a02_batch_send_persists_target_snapshot
- Assertion scope: `test_a30b` 用空转线程断言受理即返回 `total=1` 与公告 id、公告仍为 `SENDING`、`source_draft_id` 指向草稿、尚无 `send_mail` 日志；`test_a30` 断言回执 `total=2`、两条公告、两条 `send_mail` 日志且 `detail.name` 与草稿标题对应；`test_s10` 断言内联投递后公告 `SENT`、`success_count=1`、`fail_count=0`、草稿被删除、`content` 等于草稿正文；`test_s15` 断言 3 条草稿各得到一条 `SENT` 公告；`test_s24` 是 Requirement 级启动收尾检查：构造一条遗留 `SENDING` 与一条 `SENT`，断言 `settle_stuck_sending_announcements()` 返回 1、遗留公告变为 `FAILED`、`SENT` 公告不变且不再有 `SENDING`。计划项 `test_anvil_a02` 补 `target_snapshot`：向单个用户发送一条草稿后从持久化公告读取 `target_snapshot`，断言其 JSON 可解析、包含当次解析快照条目（含 `display_name` 等字段）、且 `recipient_count` 与解析结果总数一致。
- Coverage note: `test_s24` 验证 Requirement 正文的启动收尾分支，不是本 Scenario 的“受理时 source_draft_id/target_snapshot”THEN 证据；`test_a30b` 覆盖 `source_draft_id`，`target_snapshot` 与 `recipient_count` 的对应关系仍是缺口。不覆盖真实 SMTP 投递。

#### Scenario: 模板已删除

- Test/check:
  - [X] test/announcement/test_template_decoupling.py::test_q06_delete_template_referenced_by_announcement_keeps_content
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_a03_resend_after_template_deleted_uses_saved_content
- Assertion scope: `test_q06_delete...` 断言删除模板后公告 `content` 不变、`template_id` 解除。计划项 `test_anvil_a03` 在该公告（模板引用已解除）上调用 `start_resend_service` 并让后台线程就地执行，捕获传输层消息后断言邮件 `content` 等于公告已保存的 `content`、公告终态回到 `SENT`、`template_id` 保持 `NULL`，且公告 `title`/`raw_content`/`targets`/`source_draft_id` 未被改写，即不要求恢复模板引用、也不重新套用模板。
- Coverage note: 既有 `[X]` 只证明删除后内容快照保留，未走投递/重发路径；重发路径仍是缺口。不覆盖真实 SMTP。

### Requirement: 公告 Markdown 邮件渲染与双正文

#### Scenario: 发送草稿生成双正文

- Test/check:
  - [X] test/announcement/test_services.py::test_s28_send_and_resend_share_html_messages
  - [X] test/announcement/test_services.py::test_s10_send_draft_all_success
  - [X] test/utils/test_mail.py::test_batch_builds_plain_and_html_alternative
  - [X] test/utils/test_mail.py::test_batch_without_html_keeps_plain_text
  - [X] test/utils/test_mail.py::test_send_without_html_remains_plain_text
  - [X] test/utils/test_mail.py::test_batch_html_with_attachment_keeps_alternative_first
- Assertion scope: `test_s28` 捕获投递消息，断言每条消息 `content` 与草稿 Markdown 正文完全一致、所有收件人共用同一 `html_content`、渲染函数只被调用一次、HTML 含 `<h1` 与 `<strong>`，且公告持久化 `content` 未被 HTML 替换；`test_s10` 覆盖发送终态、计数、草稿删除与 `content`；四条 `test_mail` 分别断言含 `html_content` 时消息解析为 `multipart/alternative`（`text/plain` 在前、`text/html` 正文正确）、无 `html_content` 的 batch/send 仍是单一 `text/plain`、带附件时顶层为 `multipart/mixed` 且首个子 part 为 `multipart/alternative`、附件在最后。
- Coverage note: `test_mail` 的附件与无 HTML 用例只验证 `utils.mail` 边界，不表示公告支持附件或普通邮件启用 Markdown；未验证真实 SMTP 与客户端对 alternative part 的选择。

#### Scenario: 重发复用同一渲染

- Test/check:
  - [X] test/announcement/test_services.py::test_s17_resend_from_sent
  - [X] test/announcement/test_services.py::test_s28_send_and_resend_share_html_messages
- Assertion scope: `test_s17` 断言重发沿用同一条公告（返回同一 id）并回到 `SENT`；`test_s28` 断言重发时渲染函数再次被调用、捕获消息的 `content` 与 `html_content` 均由该公告已保存的 `content` 派生且 HTML 与首次发送一致，重发后 `title`/`content`/`raw_content`/`targets` 未被改写。
- Coverage note: 未覆盖真实 SMTP 与客户端渲染；重发不新建公告属既有行为回归。

#### Scenario: 历史纯文本按同一规则解析

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_preserves_single_newlines
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_a04_plain_and_markdown_use_same_renderer_call
- Assertion scope: `test_render_preserves_single_newlines` 渲染无 Markdown 标记的多行纯文本后用 `HTMLParser` 断言输出含真实 `<br>`、三行文本都出现在可见文本中，并用 `inspect.signature` 断言渲染函数只有单一 `source` 入参（仅作接口线索，不当作不存在内部探测分支的行为证据）。计划项 `test_anvil_a04` 从同一发送入口分别发送纯文本（含单个换行）与 Markdown 草稿，把 `services.announcement_tasks.render_announcement_html` 包装成记录调用的真实 renderer，断言两次发送都经过同一个 recorder、每个正文各调用一次、入参分别为对应 `content`，捕获的纯文本 HTML 含 `<br>`、Markdown HTML 含 `<h1`/`<strong>`，且两者与直接调用真实 renderer 的输出一致。
- Coverage note: `test_anvil_a04` 能证明发送入口对纯文本与 Markdown 使用同一 renderer 调用，且输出与直接渲染一致；仍不能黑盒排除 renderer 内部按内容分支，`inspect.signature` 只作接口线索。不承诺各邮件客户端的最终视觉换行，本变更无历史回填。

#### Scenario: HTML 不进入持久化与审计

- Test/check:
  - [X] test/announcement/test_services.py::test_s29_send_preserves_source_and_audit
  - [X] test/announcement/test_services.py::test_s10_send_draft_all_success
  - [X] test/announcement/test_services.py::test_s11_send_draft_partial_failure
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_a05_send_and_resend_do_not_write_html_into_draft_or_template
- Assertion scope: `test_s29` 经 `start_batch_send_service` 发送含 Markdown 的草稿后断言公告 `content`/`raw_content` 原样、`success_count`/`fail_count` 与草稿删除保持既有语义，且投递日志 `detail` 的序列化文本不含 `html_content`、`<h1>`、`<strong>`；`test_s10` 断言 `SENT` 终态、计数、草稿删除与公告 `content`，不断言日志；`test_s11` 断言 `PARTIAL` 终态、计数与日志形状（`success` 序列、`target_type`/`target_id`、`detail.batch_total`/`detail.message_count`），不断言日志中是否出现 HTML。计划项 `test_anvil_a05` 建一条模板和一条显式设置 `content`/`raw_content` 的 Markdown 草稿，发送前对草稿与模板做全字段快照，在传输层捕获点重读并断言两者与快照一致；发送完成后断言公告 `content`/`raw_content` 分别等于草稿原文、模板逐字段不变、草稿按既有语义删除；随后重发该公告，在捕获点与完成后再次断言模板逐字段不变、公告 `title`/`content`/`raw_content`/`targets`/`source_draft_id` 未被改写且终态为 `SENT`；两次审计详情都不含 `html_content`、`<h1>`、`<strong>`。
- Coverage note: `test_s29` 的日志断言只覆盖发送路径的“HTML 不进入审计”，`test_s10` 不检查日志，`test_s11` 只检查终态/计数/日志形状；发送与重发期间草稿/模板是否被 HTML 写回仍是缺口。使用隔离 SQLite 与本地传输替身，未在生产 MySQL 验证。

#### Scenario: 渲染异常沿用投递失败收尾

- Test/check:
  - [X] test/announcement/test_services.py::test_s30_render_exception_settles_failed_without_send
- Assertion scope: monkeypatch 公告投递模块使用的渲染函数抛出异常，经就地执行的“后台线程”后断言公告终态为 `FAILED`、`_send_batch_smtp` 未被调用（捕获列表为空）、且不存在残留 `SENDING` 公告。
- Coverage note: 只在服务级验证本地失败收尾，不覆盖真实 SMTP/客户端。

### Requirement: 公告 Markdown 渲染的内容与安全边界

#### Scenario: 基础结构渲染

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_basic_markdown_structures
- Assertion scope: 用 `HTMLParser` 收集真实节点与属性，断言存在 `div`/`h1`/`h2`/`p`/`ul`/`ol`/`li`/`blockquote`/`table`/`thead`/`tbody`/`tr`/`th`/`td`/`a`/`code`/`pre`，关键 opening tag 带内联 `style`，不存在 `style`/`link`/`script` 元素，行内代码与围栏代码中的 `<b>&`、`<script>` 以字面文本出现。
- Coverage note: 只做结构级断言，不验证邮件客户端排版、暗色模式或响应式效果。

#### Scenario: 原始 HTML 与代码转义

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_escapes_raw_html_and_code
- Assertion scope: 断言正文中的原始 `<script>`/`<b>`/`<img src=...>` 不成为真实元素（`tags` 中无 `script`/`b`/`img`），其原文以可见文本出现；行内代码与围栏代码里的 HTML 片段同样转义为文本。
- Coverage note: 未执行浏览器级 XSS 扫描，依赖渲染器 `html=False` 与默认代码转义。

#### Scenario: 安全链接

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_allows_only_safe_links
- Assertion scope: 断言真实 `<a>` 的 `href` 恰好 4 个且全部以 `http://`/`https://`/`mailto:` 开头（含大小写混合与带 query 的写法），`relative`、`//evil.example`、`javascript:`、`data:`、`file:` 目标不产生 `href` 而其可见字面文本保留，输出中的 `&` 被转义。
- Coverage note: 覆盖代表性目标，不宣称穷尽所有编码绕过；未做真实浏览器点击验证。

#### Scenario: 不加载图片或外部资源

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_suppresses_images_without_resource_requests
- Assertion scope: 断言输出无 `img`/`script`/`style`/`link`/`a` 元素、任何标签都不带 `src` 属性；有效图片 token 只留 alt 文本（含已转义的 `&lt;b&gt;`、`&quot;`），被拒绝的图片语法保留含 URL 的字面文本；真实 `style` 属性不含 `url()`/`@import`；代码与转义 HTML 中的 `url(...)`、`@import` 仅作为文本数据出现。
- Coverage note: 只证明输出结构不产生资源加载/请求，不验证邮件客户端自身预取；代码字面中的 `src="x"` 未被单独断言，`src` 层面由“无 `img`、任何标签无 `src` 属性”的结构断言覆盖。

#### Scenario: 内联样式边界

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_basic_markdown_structures
- Assertion scope: 断言样式只出现在真实元素的 `style` 属性上，不存在 `style`/`link`/`script` 元素，所有 `style` 值都不含 `url()` 与 `@import`（即无外部 CSS 或远程字体依赖）。
- Coverage note: 与“基础结构渲染”共用同一计划用例；只断言样式形式，不保证客户端最终视觉。
