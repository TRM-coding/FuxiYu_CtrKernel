# backend--table-announcement-templates Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: announcement_templates 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t01_template_readback_contract
  - [X] test/announcement/test_models.py::test_m03_template_unique_name
  - [X] test/announcement/test_models.py::test_m06_template_source_announcement_id
  - [X] test/announcement/test_repository.py::test_r07_create_template
- Assertion scope: `test_anvil_t01` 用新 session 按主键重开“最小模板”和“完整模板”，断言 `id`/`name`/`subject_template`/`body_template` 是 `str`、`created_by` 是 `int` 且等于创建者用户主键（不是展示名）、`category` 为默认 `custom`、未赋值的 `description` 与 `source_announcement_id` 回读为 `NULL`、`created_at`/`updated_at` 是插入时间窗内的 `datetime`，赋值时按原值往返；`test_m03` 断言同名模板第二次 commit 抛 `IntegrityError`；`test_m06` 断言 `source_announcement_id` 未赋值 `None`、赋 42 后读回 42；`test_r07` 断言创建后 `id`/`name`/`description` 与写入一致。
- Coverage note: 未验证生产 MySQL 方言下的默认值行为。

### Requirement: announcement_templates 生产职责与生命周期

#### Scenario: 读取模板

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t02_api_template_detail_returns_editor_initial_values
  - [X] test/announcement/test_api.py::test_a07_get_template_by_id
  - [X] test/announcement/test_services.py::test_s23_convert_to_template_source_tracked
- Assertion scope: `test_anvil_t02` 断言详情出参的 `subject_template`/`body_template` 等于模板落库值、`source_announcement_id` 原样返回，且请求前后草稿与公告行数不变（取模板不新增持久依赖）；`test_a07` 断言详情 `template.id`；`test_s23` 断言由公告转换出的模板其 `source_announcement_id` 指向原公告，仅作来源追溯。
- Coverage note: 该场景未涉及前端实际填充编辑器的行为。

#### Scenario: 删除被历史内容引用的自定义模板

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t03_delete_template_preserves_announcement_and_draft_snapshots
  - [X] test/announcement/test_template_decoupling.py::test_q06_delete_template_referenced_by_announcement_keeps_content
  - [X] test/announcement/test_models.py::test_m07_draft_has_no_template_association
  - [X] test/announcement/test_template_decoupling.py::test_q06_legacy_sqlite_draft_reference_is_safely_detached
  - [X] test/announcement/test_repository.py::test_r10_delete_template_system
  - [X] test/announcement/test_api.py::test_a10_delete_system_template
- Assertion scope: `test_anvil_t03` 先建模板、草稿和带历史 `template_id` 的公告，经既有传输替身产生一条 `send_mail` 操作日志；删除模板后断言公告 `title`/`content`/`raw_content`/`targets`/`target_snapshot`/`recipient_count`/`status` 与草稿 `title`/`content`/`raw_content`/`targets` 逐项保留，公告仅 `template_id` 解除，日志行（`success`/`target_type`/`target_id`/`detail`）不变。`test_q06_delete...` 断言自定义模板删除成功、模板查询为空、公告正文不变与 `template_id` 解除；`test_m07` 断言草稿无 `template_id` 列/属性且删模板不改写正文；`test_q06_legacy...` 断言旧库残留外键先挡住删除、启动自愈清零残留引用（幂等）后删除成功；`test_r10`/`test_a10` 分别断言 SYSTEM 模板删除在仓储返回 `False`、在 API 返回 400 `cannot_delete_system_template`。
- Coverage note: `test_r10`/`test_a10` 是 Requirement 级 SYSTEM 删除拒绝检查，不是本 Scenario 的“删除被历史内容引用的自定义模板”THEN 证据。未验证生产 MySQL 外键与真实 SMTP。

### Requirement: announcement_templates 列表分页参数有界且可分页

#### Scenario: 界内分页参数

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t05_api_template_pagination_order_default_and_filtered_total
  - [X] test/announcement/test_api.py::test_a06_list_templates
  - [X] test/announcement/test_api.py::test_a06c_list_templates_paginates_beyond_200
- Assertion scope: `test_anvil_t05` 用互异 `created_at` 建 205 条模板（custom/system 两类），断言无参数默认请求返回 100 条、`total=205` 且 id 顺序等于 `created_at` 降序期望切片（等价于 `limit=100&offset=0`），并断言 `category=custom` 的 `total` 为过滤后完整数量、过滤结果的 `limit`/`offset` 仍按同一顺序切片；`test_a06` 保留默认请求成功形状；`test_a06c` 断言显式 `limit=200&offset=0` 返回 200 条且 `total=205`、`limit=200&offset=200` 返回 5 条且 `total=205`、`limit=100` 返回 100 条。
- Coverage note: 前端分页交互与深链不在本后端规格内。

#### Scenario: 越界或非整数参数

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t04_api_template_list_rejects_non_integer_offset
  - [X] test/announcement/test_api.py::test_a06b_list_templates_rejects_invalid_pagination[limit=0]
  - [X] test/announcement/test_api.py::test_a06b_list_templates_rejects_invalid_pagination[limit=201]
  - [X] test/announcement/test_api.py::test_a06b_list_templates_rejects_invalid_pagination[offset=-1]
  - [X] test/announcement/test_api.py::test_a06b_list_templates_rejects_invalid_pagination[limit=not-a-number]
- Assertion scope: `test_anvil_t04` 断言 `offset=not-a-number` 返回 400 与 `error_reason=invalid_payload`；四个既有参数化分支分别以 `limit=0`、`limit=201`、`offset=-1`、`limit=not-a-number` 请求并断言同样的 400 形状。
- Coverage note: 前端取值方式与 Web 分页交互不在本规格内。

#### Scenario: 205 条模板分页

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t05_api_template_pagination_order_default_and_filtered_total
  - [X] test/announcement/test_api.py::test_a06c_list_templates_paginates_beyond_200
- Assertion scope: `test_anvil_t05` 为 205 条模板设置互异 `created_at`，按 `created_at` 降序断言第一页 id 序列等于 `expected[0:200]`、第二页 id 序列等于 `expected[200:205]`，两页无重复且并集为全部 205 条；`test_a06c` 断言两页长度与 `total=205`。排序证据是逐 id 与期望顺序一致，ID 集合关系只是附带结果。
- Coverage note: `test_a06c` 本身不比对跨页顺序；排序与 `offset`/`limit` 的先后关系由 `test_anvil_t05` 的期望切片承接。未验证生产 MySQL 方言。
