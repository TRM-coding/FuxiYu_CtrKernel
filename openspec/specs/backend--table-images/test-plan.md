# images 测试覆盖

规格：[spec.md](spec.md)

## 当前场景映射

| Requirement | Scenario | 覆盖状态 | 测试位置与 nodeid/参数 | 验证范围或缺口 |
| --- | --- | --- | --- | --- |
| images 持久化结构 | 读取有效记录 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只同步 entrypoint 说明契约，未复核持久化读取断言。 |
| images 生产职责与生命周期 | 模板停用 | 待复核 | —（本轮未审计） | 主规格既有场景；未在本轮审计，不能用本 change 的套件总数推断已覆盖。 |
| images 模板名称唯一性 | 同名判定只看未停用 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核应用层唯一性断言。 |
| images 模板启停与构建记录失效 | 停用后可重新启用 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核启停与构建记录测试。 |
| images 模板启停与构建记录失效 | 模板更新促使机器重建 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核配方新鲜度与派发断言。 |
| images 内置模板幂等收敛 | 内置模板改名收敛 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核 seed 幂等断言。 |
| 平台注入改变构建缓存版本 | 注入变化后派发 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核平台注入与构建标签断言。 |
| 镜像资源通配与方法权限分别生效 | 资源通配者操作他人镜像 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核资源通配与方法权限组合断言。 |
| 镜像资源通配与方法权限分别生效 | 仅有方法通配或缺少方法能力 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核权限组合断言。 |
| 镜像资源通配与方法权限分别生效 | 停用模板仍不能新建 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核业务状态门断言。 |
| 仅看我的严格按创建者过滤 | 通配者勾选仅看我的 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核 `mine_only` 过滤断言。 |
| 仅看我的严格按创建者过滤 | 创建者不在可见名单 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核创建者归属断言。 |
| images entrypoint 说明符合构建语义 | 模型与 schema 说明一致 | 已覆盖 | `../../../test/test_entrypoint_docs.py::test_entrypoint_docs_describe_build_stage_at_all_four_locations`；机械检查 `ENTRYPOINT_DOC_CHECK: PASS`（4 文件，5 个旧短语均不存在，必需构建语义短语存在）；`git grep -n 'utils/Container.py' -- models/image.py schemas/image.py` 无输出 | 测试断言 `models/image.py` 与 `schemas/image.py` 不含“不参与构建”“不进 Dockerfile”“默认值只写在 Node”“utils/Container.py”，且含“参与构建”“DockerfileParts”“PLATFORM_DEFAULT_ENTRYPOINT”以及 `render_final_dockerfile`、`ENTRYPOINT`；机械检查额外确认“只是运行期参数”不存在。 |

## 最近验证

- 时间：2026-10-21 03:03:42 +08:00（父任务最终 WSL 套件原始输出落盘时间）
- 版本：`f68d54bacc15ecd401c1d83d8030fe140696b9e1`；本次仅同步文档，未改源代码/测试，未重跑业务套件。
- 主 spec SHA256：`f111b55177eacca8e682c9d8610181da7176cda31a0bc37cefa18d178504ef0a`
- 命令与环境：
  - WSL 完整默认安全套件：`PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:///:memory: DISABLE_BACKGROUND_TASKS=1 /home/chest/miniconda3/envs/fuxi/bin/python -m pytest test -q --no-header`
  - Windows 定向：`E:\Miniconda3\envs\lianjue\python.exe -m pytest test/operation_log test/settings test/test_entrypoint_docs.py test/container/test_container_entrypoint.py test/announcement/test_api.py -q --no-header`
- 结果：WSL 完整套件 1358 passed、0 failed、0 skipped、6 deselected、1 warning（既有 SAWarning），170.53s；Windows 定向 110 passed。原始输出：`.git/direct-q-final-suite.log`（本地记录，未提交）。
- 限制：6 项按 `integration/legacy` 策略排除，未运行真实 Docker/GPU/SMTP 或生产数据库；完整套件包含 Node 跨仓回放和真实 du 探针。entrypoint 说明场景为文档约束，使用现有文档扫描测试加静态机械检查验证，不涉及运行时行为；上表既有场景未在本轮重新审计。
