# announcement_templates 测试覆盖

规格：[spec.md](spec.md)

## 当前场景映射

| Requirement | Scenario | 覆盖状态 | 测试位置与 nodeid/参数 | 验证范围或缺口 |
| --- | --- | --- | --- | --- |
| announcement_templates 持久化结构 | 读取有效记录 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只同步列表分页新增契约，未复核持久化读取断言。 |
| announcement_templates 生产职责与生命周期 | 读取模板 | 待复核 | —（本轮未审计） | 主规格既有场景；未在本轮审计，不能用本 change 的套件总数推断已覆盖。 |
| announcement_templates 生产职责与生命周期 | 删除被历史内容引用的自定义模板 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核模板解耦与历史引用断言。 |
| announcement_templates 列表分页参数有界且可分页 | 界内分页参数 | 已覆盖 | `../../../test/announcement/test_api.py::test_a06_list_templates`；`::test_a06c_list_templates_paginates_beyond_200` | 默认请求返回成功；`limit=100`、`limit=200`、`offset=0` 正常分页，205 条时首页 `total=205`，Web 默认 100 条不受破坏。 |
| announcement_templates 列表分页参数有界且可分页 | 越界或非整数参数 | 部分覆盖 | `../../../test/announcement/test_api.py::test_a06b_list_templates_rejects_invalid_pagination`（参数 `limit=0`、`limit=201`、`offset=-1`、`limit=not-a-number`） | 场景列出的四类参数均断言 400 `invalid_payload`；Requirement 正文还要求非整数 `offset` 被拒绝，但没有定向参数（review Suggestion 2），该分支不记为已覆盖。 |
| announcement_templates 列表分页参数有界且可分页 | 205 条模板分页 | 已覆盖 | `../../../test/announcement/test_api.py::test_a06c_list_templates_paginates_beyond_200` | 205 条时 `limit=200&offset=0` 返回 200 条且 `total=205`，`offset=200` 返回剩余 5 条且 `total=205`；排序后分页由 `repositories/announcement_repo.py:179-183` 实现。 |

## 最近验证

- 时间：2026-10-21 03:03:42 +08:00（父任务最终 WSL 套件原始输出落盘时间）
- 版本：`f68d54bacc15ecd401c1d83d8030fe140696b9e1`；本次仅同步文档，未改源代码/测试，未重跑业务套件。
- 主 spec SHA256：`6979d81a45f304e652e68c55f2f509d7b03f3dfc1752843bab2fcbcf1e082b81`
- 命令与环境：
  - WSL 完整默认安全套件：`PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:///:memory: DISABLE_BACKGROUND_TASKS=1 /home/chest/miniconda3/envs/fuxi/bin/python -m pytest test -q --no-header`
  - Windows 定向：`E:\Miniconda3\envs\lianjue\python.exe -m pytest test/operation_log test/settings test/test_entrypoint_docs.py test/container/test_container_entrypoint.py test/announcement/test_api.py -q --no-header`
- 结果：WSL 完整套件 1358 passed、0 failed、0 skipped、6 deselected、1 warning（既有 SAWarning），170.53s；Windows 定向 110 passed。原始输出：`.git/direct-q-final-suite.log`（本地记录，未提交）。
- 限制：6 项按 `integration/legacy` 策略排除，未运行真实 Docker/GPU/SMTP 或生产数据库；完整套件包含 Node 跨仓回放和真实 du 探针。本表只覆盖 Ctrl 列表 API 的分页参数；Web 分页/深链由 Web change 承接，不在本台账冒充已覆盖。上表既有场景未在本轮重新审计。
