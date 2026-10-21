# operation_logs 测试覆盖

规格：[spec.md](spec.md)

## 当前场景映射

| Requirement | Scenario | 覆盖状态 | 测试位置与 nodeid/参数 | 验证范围或缺口 |
| --- | --- | --- | --- | --- |
| operation_logs 持久化结构 | 读取有效记录 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只同步目标回填与统计错误原因的新增契约，未复核持久化读取断言。 |
| operation_logs 生产职责与生命周期 | 失败操作留痕 | 待复核 | —（本轮未审计） | 主规格既有场景；未在本轮审计，不能用本 change 的套件总数推断已覆盖。 |
| 操作日志目标回填批量读取并保持返回契约 | 混合目标类型 | 已覆盖 | `../../../test/operation_log/test_operation_log_tasks.py::test_list_enriches_every_supported_target_type`；`::test_list_enriches_user_name_and_tolerates_deleted_target`；`::test_list_skips_identity_mapping_for_previous_generation_log` | 断言 machine/container/user/image/rbac_group/system_setting/container_mount_cleanup 的 `target_name` 和容器 `root_owner`；删除目标保留 `target_display_name` 历史名回退；上一代容器日志不映射名称/root_owner，验证代际判断。 |
| 操作日志目标回填批量读取并保持返回契约 | User 查询失败 | 已覆盖 | `../../../test/operation_log/test_operation_log_tasks.py::test_user_query_failure_blanks_root_owner_only` | User 查询抛错时容器 `target_name` 保持、`root_owner` 为空、User 目标名为空，后续 image 类型仍正常回填。 |
| 操作日志目标回填批量读取并保持返回契约 | 事务级失败隔离 | 已覆盖 | `../../../test/operation_log/test_operation_log_tasks.py::test_user_dbapi_failure_does_not_poison_later_type_sessions` | 在 `FROM USERS` 上触发 `OperationalError` 后，容器名称保留、`root_owner` 为空、image 仍由独立只读会话回填。 |
| 操作日志目标回填批量读取并保持返回契约 | 25 行不线性增长 | 已覆盖 | `../../../test/operation_log/test_operation_log_tasks.py::test_target_enrichment_query_count_does_not_grow_per_row` | 25 行容器日志整页 SELECT 数 `<= 8`，不随日志行数线性增长；同时断言名称与 root_owner 回填正确。 |
| 统计失败使用独立错误原因 | 统计查询失败 | 已覆盖 | `../../../test/operation_log/test_operation_log_api.py::test_stats_failure_uses_stats_failed`；`::test_list_failure_keeps_list_failed` | stats 异常返回 500 `stats_failed` 与对应 message；list 异常仍返回 `list_failed`，两条路径未混用。 |

## 最近验证

- 时间：2026-10-21 03:03:42 +08:00（父任务最终 WSL 套件原始输出落盘时间）
- 版本：`f68d54bacc15ecd401c1d83d8030fe140696b9e1`；本次仅同步文档，未改源代码/测试，未重跑业务套件。
- 主 spec SHA256：`fc86196438cc89ca52e3ccb4c5bca4c7146d071b2fca9db268f1cdb2afe435ff`
- 命令与环境：
  - WSL 完整默认安全套件：`PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:///:memory: DISABLE_BACKGROUND_TASKS=1 /home/chest/miniconda3/envs/fuxi/bin/python -m pytest test -q --no-header`
  - Windows 定向：`E:\Miniconda3\envs\lianjue\python.exe -m pytest test/operation_log test/settings test/test_entrypoint_docs.py test/container/test_container_entrypoint.py test/announcement/test_api.py -q --no-header`
- 结果：WSL 完整套件 1358 passed、0 failed、0 skipped、6 deselected、1 warning（既有 SAWarning），170.53s；Windows 定向 110 passed。原始输出：`.git/direct-q-final-suite.log`（本地记录，未提交）。
- 限制：6 项按 `integration/legacy` 策略排除，未运行真实 Docker/GPU/SMTP 或生产数据库；完整套件包含 Node 跨仓回放和真实 du 探针。上表既有场景未在本轮重新审计；套件总数不替代逐场景断言。
