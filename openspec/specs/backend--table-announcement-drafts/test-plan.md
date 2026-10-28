# backend--table-announcement-drafts Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

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
- Coverage note: `test_q06_edit_or_rename...` 只比对 `title`/`content`，完整字段由两个 reopening 分支覆盖。旧库残留 `template_id` 列的启动自愈由 `test_q06_legacy_sqlite_draft_reference_is_safely_detached` 另测，不映射为本场景证据；未验证生产 MySQL 上的旧列迁移/删列行为。
