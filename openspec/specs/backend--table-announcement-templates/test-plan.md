# backend--table-announcement-templates Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: announcement_templates 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_announcement_and_template_models_have_no_creator
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t01_template_readback_contract
  - [X] test/announcement/test_models.py::test_m03_template_unique_name
  - [X] test/announcement/test_models.py::test_m06_template_source_announcement_id
  - [X] test/announcement/test_repository.py::test_r07_create_template
- Assertion scope: 模型测试断言 `announcement_templates` 不存在 `created_by` 列/关系或创建者外键；`test_anvil_t01` 用新 session 按主键重开模板，断言 `id`/`name`/`subject_template`/`body_template` 是 `str`、无创建者属性、`category` 为默认 `custom`、未赋值的 `description`/`source_announcement_id` 回读 `NULL`、时间字段为插入窗内 `datetime`，赋值时按原值往返；`test_m03` 断言同名第二次 commit 抛 `IntegrityError`；`test_m06` 断言来源公告 id 往返；`test_r07` 断言创建字段。
- Coverage note: 未验证生产 MySQL 方言下的默认值行为。

#### Scenario: 创建者删除后保留模板内容

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_delete_author_keeps_announcements_and_templates
- Assertion scope: 删除作者前后在独立 session 比较模板全部标量字段快照，断言名称、类别、描述、主题/正文模板、来源公告与时间字段完全不变，模板仍可读取。

#### Scenario: 模板出参不含创建者

- Test/check:
  - [X] test/announcement/test_ownership_contracts.py::test_announcement_and_template_api_views_omit_creator
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t02_api_template_detail_returns_editor_initial_values
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_t05_api_template_pagination_order_default_and_filtered_total
- Assertion scope: 3 条模板的列表 `limit=2&offset=1` 断言响应键、`total=3`、降序 id、模板视图精确 9 键（不含 `created_by`）；详情键与既有字段不变，`test_anvil_t02` 断言主题/正文/来源与请求前后行数，`test_anvil_t05` 断言分页/过滤顺序及列表项不含创建者。

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

### Requirement: SYSTEM 模板类别不可变更

#### Scenario: SYSTEM 改为其他类别被拒绝

- Test/check:
  - [X] test/announcement/test_system_template_category_guard.py::test_system_to_custom_rejected_with_reason
  - [X] test/announcement/test_system_template_category_guard.py::test_repository_rejects_system_category_change
- Assertion scope: API 对 SYSTEM→custom 返回 400 `cannot_change_system_template_category` 且类别仍 SYSTEM；仓储直调抛同原因，重新读取的字段快照不变。

#### Scenario: 多字段更新失败不部分落库

- Test/check:
  - [X] test/announcement/test_system_template_category_guard.py::test_system_multi_field_update_is_atomic_on_rejection
- Assertion scope: 同一请求修改名称/描述/主题/正文并提交 category=custom，400 后新 session 的五字段快照与更新前完全相等。

#### Scenario: 省略类别可编辑其他内容

- Test/check:
  - [X] test/announcement/test_system_template_category_guard.py::test_system_content_update_without_category_allowed[omitted]
  - [X] test/announcement/test_system_template_category_guard.py::test_system_content_update_without_category_allowed[null]
- Assertion scope: 不含 category 与 category=null 两参数分别提交名称/描述/主题/正文，均 200、四字段生效、类别保持 SYSTEM；null 沿用既有忽略 None 语义。

#### Scenario: 同类别可编辑其他内容

- Test/check:
  - [X] test/announcement/test_system_template_category_guard.py::test_system_content_update_with_same_category_allowed
- Assertion scope: category=system 时名称/描述/主题/正文四字段全部生效，类别保持 SYSTEM。

#### Scenario: CUSTOM 改为 SYSTEM 保持允许

- Test/check:
  - [X] test/announcement/test_system_template_category_guard.py::test_custom_to_system_allowed
- Assertion scope: CUSTOM 提交 category=system 及名称/描述/主题/正文，200 后类别 SYSTEM，四字段均生效。
