# system_settings 测试覆盖

规格：[spec.md](spec.md)

## 当前场景映射

| Requirement | Scenario | 覆盖状态 | 测试位置与 nodeid/参数 | 验证范围或缺口 |
| --- | --- | --- | --- | --- |
| system_settings 持久化结构 | 读取有效记录 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只同步设置校验新增契约，未复核该表的持久化读取断言。 |
| system_settings 生产职责与生命周期 | 修改已知设置 | 待复核 | —（本轮未审计） | 主规格既有场景；未在本轮审计，不能用本 change 的套件总数推断已覆盖。 |
| system_settings 设置输入不得静默改变语义 | 小数设置 | 已覆盖 | `../../../test/settings/test_settings_validation.py::test_integer_setting_rejects_non_integer_without_writing`（参数 `1.5`、`"1.5"`、`True`、`"abc"`、`""`）；`::test_single_setting_entrypoint_also_rejects_fractional_integer`；`::test_settings_api_rejects_fractional_integer` | 服务与单键入口拒绝小数/非整数且原值不变；API 返回 422 `invalid_setting` 并指出设置键；失败审计 `success=False` 且保留请求值。 |
| system_settings 设置输入不得静默改变语义 | 非法提醒节点 | 已覆盖 | `../../../test/settings/test_settings_validation.py::test_reminder_hours_rejects_malformed_input_without_writing`（空串、空白、`72,bad,24`、`72,,24`、`0,24`、`-1,24`、`12.5`）；`::test_settings_api_rejects_malformed_reminder_hours` | 空项/非整数/0/负数使整次写入失败，原值不变，失败审计保留请求值；API 422 并指出非法项 `'bad'`。 |
| system_settings 设置输入不得静默改变语义 | 合法输入与范围校验保留 | 部分覆盖 | `../../../test/settings/test_settings_validation.py::test_integer_setting_accepts_integral_number`；`::test_reminder_hours_accepts_positive_values_and_stays_parser_compatible` | 已断言 `12.0` 存为 `12`、`72, 24,12` 原值保存且解析为 `[72, 24, 12]`；超出既有 min/max 的拒绝没有定向测试断言（实现保留于 `services/settings_tasks.py:321-327`，review Suggestion 1），该分支不记为已覆盖。 |

## 最近验证

- 时间：2026-10-21 03:03:42 +08:00（父任务最终 WSL 套件原始输出落盘时间）
- 版本：`f68d54bacc15ecd401c1d83d8030fe140696b9e1`；本次仅同步文档，未改源代码/测试，未重跑业务套件。
- 主 spec SHA256：`b6ff738310b877e4cdfb6ccb40e1d4a6e2afa592db0f0a7653c2fd9abc1158f4`
- 命令与环境：
  - WSL 完整默认安全套件：`PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:///:memory: DISABLE_BACKGROUND_TASKS=1 /home/chest/miniconda3/envs/fuxi/bin/python -m pytest test -q --no-header`
  - Windows 定向：`E:\Miniconda3\envs\lianjue\python.exe -m pytest test/operation_log test/settings test/test_entrypoint_docs.py test/container/test_container_entrypoint.py test/announcement/test_api.py -q --no-header`
- 结果：WSL 完整套件 1358 passed、0 failed、0 skipped、6 deselected、1 warning（既有 SAWarning），170.53s；Windows 定向 110 passed。原始输出：`.git/direct-q-final-suite.log`（本地记录，未提交）。
- 限制：6 项按 `integration/legacy` 策略排除，未运行真实 Docker/GPU/SMTP 或生产数据库；完整套件包含 Node 跨仓回放和真实 du 探针。上表既有场景未在本轮重新审计；套件总数不替代逐场景断言。
