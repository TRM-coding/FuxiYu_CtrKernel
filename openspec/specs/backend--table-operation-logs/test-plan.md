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
| 密码类操作的日志复用与无密码约束 | 重置成功后记一条无密码日志 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_codes_contract | 断言 reset_container_password/ADD_COLLABORATOR/UPDATE_COLLABORATOR_ROLE/CREATE_CONTAINER 单条、无密码、Node 错误体不回写。 |
| 密码类操作的日志复用与无密码约束 | 新增协作者成功记无密码日志 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_codes_contract | 断言 reset_container_password/ADD_COLLABORATOR/UPDATE_COLLABORATOR_ROLE/CREATE_CONTAINER 单条、无密码、Node 错误体不回写。 |
| 密码类操作的日志复用与无密码约束 | ROOT 交接每一步单独留痕 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_codes_contract | 断言 reset_container_password/ADD_COLLABORATOR/UPDATE_COLLABORATOR_ROLE/CREATE_CONTAINER 单条、无密码、Node 错误体不回写。 |
| 密码类操作的日志复用与无密码约束 | 创建和恢复保持单条日志 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_codes_contract | 断言 reset_container_password/ADD_COLLABORATOR/UPDATE_COLLABORATOR_ROLE/CREATE_CONTAINER 单条、无密码、Node 错误体不回写。 |
| 密码类操作的日志复用与无密码约束 | Node 错误体含敏感值时审计仍脱敏 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_codes_contract | 断言 reset_container_password/ADD_COLLABORATOR/UPDATE_COLLABORATOR_ROLE/CREATE_CONTAINER 单条、无密码、Node 错误体不回写。 |
| 密码类异步操作的结果日志时序 | 结果返回后记一条成功日志 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_timing_contract | 断言受理不写结果、成功/失败/部分成功/超时未知/日志写入失败语义。 |
| 密码类异步操作的结果日志时序 | 受理时不写结果日志 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_timing_contract | 断言受理不写结果、成功/失败/部分成功/超时未知/日志写入失败语义。 |
| 密码类异步操作的结果日志时序 | 重置失败记一条失败日志 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_timing_contract | 断言受理不写结果、成功/失败/部分成功/超时未知/日志写入失败语义。 |
| 密码类异步操作的结果日志时序 | 新增协作者失败不写成功日志 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_timing_contract | 断言受理不写结果、成功/失败/部分成功/超时未知/日志写入失败语义。 |
| 密码类异步操作的结果日志时序 | ROOT 交接部分失败如实记录 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_timing_contract | 断言受理不写结果、成功/失败/部分成功/超时未知/日志写入失败语义。 |
| 密码类异步操作的结果日志时序 | 超时或未知结果不写成功 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_timing_contract | 断言受理不写结果、成功/失败/部分成功/超时未知/日志写入失败语义。 |
| 密码类异步操作的结果日志时序 | 日志写入失败不影响已受理结果 | 已覆盖 | ../../../test/operation_log/test_password_logs.py::test_password_log_timing_contract | 断言受理不写结果、成功/失败/部分成功/超时未知/日志写入失败语义。 |

## 历史验证

- 时间：2026-10-21 03:03:42 +08:00（父任务最终 WSL 套件原始输出落盘时间）
- 版本：`f68d54bacc15ecd401c1d83d8030fe140696b9e1`；本次仅同步文档，未改源代码/测试，未重跑业务套件。
- 主 spec SHA256：`fc86196438cc89ca52e3ccb4c5bca4c7146d071b2fca9db268f1cdb2afe435ff`
- 命令与环境：
  - WSL 完整默认安全套件：`PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:///:memory: DISABLE_BACKGROUND_TASKS=1 /home/chest/miniconda3/envs/fuxi/bin/python -m pytest test -q --no-header`
  - Windows 定向：`E:\Miniconda3\envs\lianjue\python.exe -m pytest test/operation_log test/settings test/test_entrypoint_docs.py test/container/test_container_entrypoint.py test/announcement/test_api.py -q --no-header`
- 结果：WSL 完整套件 1358 passed、0 failed、0 skipped、6 deselected、1 warning（既有 SAWarning），170.53s；Windows 定向 110 passed。原始输出：`.git/direct-q-final-suite.log`（本地记录，未提交）。
- 限制：6 项按 `integration/legacy` 策略排除，未运行真实 Docker/GPU/SMTP 或生产数据库；完整套件包含 Node 跨仓回放和真实 du 探针。上表既有场景未在本轮重新审计；套件总数不替代逐场景断言。

## 最近验证

- 时间：2026-10-24 17:30 +08:00
- 版本：4e6830dfa35e584d5232360d5c06b0ea0ed18f50（实现/测试提交）
- 主 spec SHA256：6796EA6F621A2EAAED884D7D45DB4AAA1459B71B3C07FF0DF31F6CB2BD89FF6B
- 命令与环境：WSL 离线 venv 根目录 `/home/chest/.cache/fuxi-password-tests-offline/bin/python -m pytest -q --no-header`
- 结果：1431 passed、0 failed、6 deselected、24 subtests passed（224.04s）；Node wire 另由 ../../../test/container/test_account_wire_contracts.py 覆盖（13 passed）。
- 限制：6 项 integration/legacy 按策略排除；上述完整套件为 SQLite 隔离与 mock Node；未运行真实生产 Docker/MySQL；新增密码日志场景由 `test_password_logs.py` 两个 contract test 覆盖。