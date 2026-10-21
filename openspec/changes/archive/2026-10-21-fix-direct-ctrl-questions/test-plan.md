# 测试计划

| Requirement | Scenario | 测试位置 | 状态与断言 |
| --- | --- | --- | --- |
| system_settings 设置输入不得静默改变语义 | 小数设置 | `test/settings/test_settings_validation.py::test_integer_setting_rejects_non_integer_without_writing`、`test_settings_api_rejects_fractional_integer`、`test_single_setting_entrypoint_also_rejects_fractional_integer` | 🟢 通过；服务与 API 均拒绝且不落库 |
| system_settings 设置输入不得静默改变语义 | 非法提醒节点 | `test/settings/test_settings_validation.py::test_reminder_hours_rejects_malformed_input_without_writing`、`test_settings_api_rejects_malformed_reminder_hours` | 🟢 通过；空项/非整数/0/负数整次拒绝并指出键或非法项 |
| system_settings 设置输入不得静默改变语义 | 合法输入与范围校验保留 | `test/settings/test_settings_validation.py::test_integer_setting_accepts_integral_number`、`test_reminder_hours_accepts_positive_values_and_stays_parser_compatible` | 🟢 通过；合法值可保存，提醒解析兼容 |
| 操作日志目标回填批量读取并保持返回契约 | 混合目标类型 | `test/operation_log/test_operation_log_tasks.py::test_list_enriches_every_supported_target_type` | 🟢 通过；machine/container/user/image/rbac_group/历史目标名称与 root owner 保持 |
| 操作日志目标回填批量读取并保持返回契约 | User 查询失败 | `test/operation_log/test_operation_log_tasks.py::test_user_query_failure_blanks_root_owner_only` | 🟢 通过；容器 target_name 保留、root_owner 为空、后续类型仍回填 |
| 操作日志目标回填批量读取并保持返回契约 | 事务级失败隔离 | `test/operation_log/test_operation_log_tasks.py::test_user_dbapi_failure_does_not_poison_later_type_sessions` | 🟢 通过；User 的 OperationalError 后镜像仍由新 session 读取 |
| 操作日志目标回填批量读取并保持返回契约 | 25 行不线性增长 | `test/operation_log/test_operation_log_tasks.py::test_target_enrichment_query_count_does_not_grow_per_row` | 🟢 通过；25 行容器日志整页 SELECT ≤ 8 |
| 统计失败使用独立错误原因 | 统计查询失败 | `test/operation_log/test_operation_log_api.py::test_stats_failure_uses_stats_failed`、`test_list_failure_keeps_list_failed` | 🟢 通过；分别断言 `stats_failed` / `list_failed` |
| images entrypoint 说明符合构建语义 | 模型与 schema 说明一致 | `test/test_entrypoint_docs.py::test_entrypoint_docs_describe_build_stage_at_all_four_locations`；`git grep -n "utils/Container.py" -- models/image.py schemas/image.py` 无输出 | 🟢 通过；旧表述消失，指向实际渲染入口 |
| containers entrypoint 留痕说明符合构建语义 | 容器模型与创建流程说明一致 | `test/test_entrypoint_docs.py::test_entrypoint_docs_describe_build_stage_at_all_four_locations`；`test/container/test_container_entrypoint.py` | 🟢 通过；四处说明一致，现有构建/恢复行为回归通过 |
| announcement_templates 列表分页参数有界且可分页 | 界内分页参数 | `test/announcement/test_api.py::test_a06c_list_templates_paginates_beyond_200` | 🟢 通过；limit=100/200 正常，total 保持完整数量 |
| announcement_templates 列表分页参数有界且可分页 | 越界或非整数参数 | `test/announcement/test_api.py::test_a06b_list_templates_rejects_invalid_pagination` | 🟢 通过；limit=0/201、offset=-1、非整数均 400 `invalid_payload` |
| announcement_templates 列表分页参数有界且可分页 | 205 条模板分页 | `test/announcement/test_api.py::test_a06c_list_templates_paginates_beyond_200` | 🟢 通过；offset=0 返回 200、offset=200 返回 5，total 均为 205 |

## 最近验证

Windows 环境使用 `PYTHON_DOTENV_DISABLED=1`、`DATABASE_URL=sqlite:///:memory:`、`DISABLE_BACKGROUND_TASKS=1`：

- 定向：`python -m pytest test/operation_log/test_operation_log_tasks.py test/operation_log/test_operation_log_api.py test/settings/test_settings_validation.py test/test_entrypoint_docs.py test/container/test_container_entrypoint.py test/announcement/test_api.py -q --disable-warnings` → **98 passed**。
- 完整安全套件（排除需 WSL/Docker 的两个 Node 跨仓探针文件）：`python -m pytest -q --disable-warnings --ignore=test/container/test_cross_repo_protocol_replay.py --ignore=test/container/test_mount_usage_cross_repo.py` → **1381 passed, 3 skipped, 1 deselected, 24 subtests passed**。
- `openspec validate fix-direct-ctrl-questions --strict` → **valid**。

真实 du / Node 跨仓探针未在本机 Windows 运行；需在 WSL `fuxi` 或具备 Docker 的环境执行，不能以本表推断其通过。

## 父任务最终验收（第 2 轮审查后）

- 最终 Windows 定向测试：110 通过。
- WSL 完整默认安全套件（不忽略跨仓探针）：1358 通过、0 失败、0 跳过、6 排除、1 既有警告；环境与命令详见 verify.md。
- 独立第 2 轮审查 APPROVE；本表全部场景已通过，不再处于等待复核状态。
