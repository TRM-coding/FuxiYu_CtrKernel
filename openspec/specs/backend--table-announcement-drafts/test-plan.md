# announcement_drafts 测试覆盖

规格：[spec.md](spec.md)

本台账只记录当前主规格的断言覆盖，不等同于最近一次运行结果；运行证据见文末“最近验证”。

## 当前场景映射

| Requirement | Scenario | 覆盖状态 | 测试层级 | 测试位置（稳定 nodeid） | 覆盖范围或缺口 |
| --- | --- | --- | --- | --- | --- |
| announcement_drafts 持久化结构 | 读取有效记录 | 已覆盖 | 模型 / 持久化集成（隔离 SQLite） | [test/announcement/test_models.py::test_m02b_draft_readback_contract](../../../test/announcement/test_models.py)<br>[test/announcement/test_models.py::test_m02_draft_create_full_fields](../../../test/announcement/test_models.py) | 新 session 按主键重开：`id`/`title`/`content`/`created_by` 类型正确且 `created_by` 是用户主键而非展示名；`raw_content`、`targets` 未赋值时回读为 `NULL`，赋值时按文本原样往返；`created_at`/`updated_at` 是插入时生成的 `datetime` 默认值。该表没有业务唯一键；本场景不验证数据库级 NULL 拒绝。 |
| announcement_drafts 生产职责与生命周期 | 保存与列出草稿 | 已覆盖 | API 集成 + 仓储 | [test/announcement/test_template_decoupling.py::test_q07_save_draft_ignores_template_id_input](../../../test/announcement/test_template_decoupling.py)<br>[test/announcement/test_template_decoupling.py::test_q07_reopening_draft_never_replays_template_over_edited_content[edited]](../../../test/announcement/test_template_decoupling.py)<br>[test/announcement/test_template_decoupling.py::test_q07_reopening_draft_never_replays_template_over_edited_content[deleted]](../../../test/announcement/test_template_decoupling.py)<br>[test/announcement/test_draft_ownership.py::test_q08_repo_list_only_returns_own_drafts](../../../test/announcement/test_draft_ownership.py)<br>[test/announcement/test_draft_ownership.py::test_q08_api_two_operator_isolation](../../../test/announcement/test_draft_ownership.py) | 保存时落 `created_by`，忽略旧客户端 `template_id` 输入；列表只返回创建者自己的草稿。保存 `title`、`content`、`raw_content`、`targets` 完整快照后，修改/删除模板，详情与列表仍返回同一快照且不含 `template_id`。未覆盖前端“选模板复制初值”的 UI 行为（不在本后端规格内）。 |
| announcement_drafts 生产职责与生命周期 | 其他操作员尝试操作 | 已覆盖 | API 集成 + 仓储 + 服务 | [test/announcement/test_draft_ownership.py::test_q08_api_two_operator_isolation](../../../test/announcement/test_draft_ownership.py)<br>[test/announcement/test_draft_ownership.py::test_q08_repo_read_and_delete_are_owner_scoped](../../../test/announcement/test_draft_ownership.py)<br>[test/announcement/test_draft_ownership.py::test_q08_repo_update_other_operators_draft_rejected_and_unchanged](../../../test/announcement/test_draft_ownership.py)<br>[test/announcement/test_draft_ownership.py::test_q08_batch_send_rejects_other_operators_draft_without_side_effects](../../../test/announcement/test_draft_ownership.py) | 对他人 `draft_id` 的读取、更新、删除、批量发送均返回 404。API 测试逐次比对完整草稿字段（含 `raw_content`、`targets`、`created_at`、`updated_at`）和对全部公告的快照，确认没有改写或新增公告、没有留下 `SENDING` 半成品，且创建者自己的读取/更新路径仍可用。服务测试验证发送在同步校验阶段即拒绝。未覆盖真实后台投递、真实 SMTP 和并发竞态。 |
| announcement_drafts 生产职责与生命周期 | 模板变化后重开草稿 | 已覆盖 | API 集成 + 仓储 / 服务 | [test/announcement/test_template_decoupling.py::test_q07_reopening_draft_never_replays_template_over_edited_content[edited]](../../../test/announcement/test_template_decoupling.py)<br>[test/announcement/test_template_decoupling.py::test_q07_reopening_draft_never_replays_template_over_edited_content[deleted]](../../../test/announcement/test_template_decoupling.py)<br>[test/announcement/test_template_decoupling.py::test_q06_edit_or_rename_template_does_not_touch_generated_content](../../../test/announcement/test_template_decoupling.py)<br>[test/announcement/test_template_decoupling.py::test_q06_legacy_sqlite_draft_reference_is_safely_detached](../../../test/announcement/test_template_decoupling.py) | 分别以 `[edited]`（模板仍存在但正文已改）和 `[deleted]`（模板已删）重开草稿，返回已保存的 `title`/`content`/`raw_content`/`targets`，不重新套用模板，也不因模板缺失失败；仓储层回归覆盖“编辑/改名/删除模板不改写草稿与公告”，旧 SQLite 的残留 `template_id` 列自愈另由兼容测试覆盖。`test_q06_edit_or_rename...` 只覆盖 `title`/`content`，完整字段由 `test_q07_reopening...` 覆盖。未验证生产 MySQL 上的旧列迁移/删列行为。 |

## 最近验证

- 时间：2026-10-20T23:53:09+08:00。
- 版本：基线提交 `5dcc8b57cdb38ab081d898c151520f88c439dd92`；存在未提交的 3 个测试文件修改及本台账新增。测试变更包括新增读回契约用例、增强所有权失败的无副作用断言，以及模板重开用例的 `edited` / `deleted` 参数分支。业务代码和主 `spec.md` 未改。
- 主 spec SHA256：`1a087b6cc8b4969d18ddfb0e1adecfdcaa96f61537dae3c13d8a6e6798777a46`。
- 环境：本地 WSL Ubuntu，SQLite `:memory:`，后台任务关闭，HTTP/SMTP 使用现有测试夹具 mock。
- 最终改动后的命令（从项目根目录运行）：

  ```bash
  export DATABASE_URL="sqlite:///:memory:" DISABLE_BACKGROUND_TASKS=1 PYTHONDONTWRITEBYTECODE=1 CTRL_LOG_DIR="$(mktemp -d)"
  /home/chest/miniconda3/envs/fuxi/bin/python -m pytest test/announcement/test_models.py test/announcement/test_draft_ownership.py test/announcement/test_template_decoupling.py -q
  ```

- 最终结果：`20 passed in 4.19s`，覆盖本表引用的全部测试，包括两个模板参数分支；没有 skipped/xfail。
- 此前目录回归：2026-10-20 23:48 +08:00，`python -m pytest test/announcement -q` 得到 `89 passed in 54.86s`。该次运行发生在模板用例拆分参数之前；之后只重跑上述发生变化及相关的三个测试文件，不把 89 项结果冒充最终整目录重跑。
- 限制：未验证生产 MySQL 方言、迁移和旧列删除；邮件被 mock，不证明真实 SMTP 投递；未执行后台投递/并发竞态。沿用 `pytest.ini` 默认排除 integration/legacy 标记的规则，没有扩大到依赖外部服务的测试。
