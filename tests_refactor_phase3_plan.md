# Ctrl Tests Refactor Phase 3 Plan

## 背景与边界

Phase 1/2 已覆盖 Ctrl 的核心业务测试计划。Phase 3 不继续扩业务功能面，而是补齐“测试体系成熟度”：让测试能长期安全运行、能在本地与 GitHub Actions 中稳定执行、能产出可读报告，并逐步替代旧测试。

测试体系统一以隔离 SQLite 为数据库底座。默认测试、全量安全回归、GitHub Actions 均不引入 MySQL 平行库；MySQL 方言差异不作为当前阶段验收目标。

默认测试必须可在生产服务仍在运行时旁路执行：测试进程不得影响生产进程、生产数据库、真实 Node、真实邮件服务或后台定时任务。

CI 只规划 GitHub Actions 能使用的部分：

- 允许：checkout、setup-python、pip install、pytest、coverage、artifact 上传、静态安全保护检查。
- 不允许依赖：生产数据库、开发数据库、真实 Node、真实 Docker、真实邮件服务、内网机器、私有运行时状态。

## 阶段 0：默认测试命令与安全运行入口

### 0. 新增的常量定义

建议新增或固化：

- `PYTEST_SAFE_MARK_EXPR = "not integration and not legacy"`
- `PYTEST_SAFE_CMD = "pytest -m 'not integration and not legacy'"`
- `PYTEST_UNIT_CMD = "pytest -m unit"`
- `PYTEST_API_CMD = "pytest -m api"`
- `PYTEST_DB_CMD = "pytest -m db"`
- `TEST_DATABASE_URI = "sqlite:///:memory:"`

### 1. 影响的文件范围

- `pytest.ini`
- `test/conftest.py`
- `README.md` 或新增 `docs/testing.md`
- `.github/workflows/ctrl-tests.yml`
- `requirements.txt` 或项目实际依赖文件

### 2. 函数级收口的完整数据流

安全运行数据流：

1. 开发者或 GitHub Actions 执行默认安全测试命令。
2. pytest 读取 marker 配置。
3. `conftest.py` 强制注入测试配置。
4. pytest fixture 调用 `create_app(overrides=TEST_CONFIG_OVERRIDES)`，不通过业务配置名启动测试模式。
5. 测试数据库使用隔离 SQLite URI。
6. 真实网络、真实邮件、真实 scheduler 默认被拦截。
7. pytest 输出测试结果。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`pytest.ini`：

- 输入：pytest 启动。
- 输出：注册 marker，设置默认测试路径与基础参数。
- 内部逻辑重点：
  - marker 必须包含 `unit/api/db/integration/legacy`。
  - `integration` 与 `legacy` 不进入默认安全测试命令。

`docs/testing.md`：

- 输入：开发者阅读。
- 输出：明确如何安全运行测试。
- 内部逻辑重点：
  - 默认命令。
  - 禁止直接跑旧测试全集的说明。
  - 如何单独跑 user/machine/container。
  - 如何显式跑 integration。

`conftest safety guard`：

- 输入：pytest session。
- 输出：测试安全环境。
- 内部逻辑重点：
  - 检测数据库 URI，若不是 SQLite 则 fail fast。
  - 默认禁止真实 HTTP 请求。
  - 默认禁止真实 SMTP。
  - 默认禁止后台 scheduler 真实启动。

### 4. 测试用例的构建描述

- `test_pytest_markers_are_registered`
- `test_safe_test_config_disables_background_tasks`
- `test_safe_test_config_uses_isolated_database`
- `test_real_network_is_blocked_by_default`
- `test_real_smtp_is_blocked_by_default`
- `test_docs_testing_mentions_safe_default_command`

## 阶段 1：Fixture 与 Factory 平台化

### 0. 新增的常量定义

- `DEFAULT_TEST_USERNAME = "test_user"`
- `DEFAULT_TEST_OPERATOR = "test_operator"`
- `DEFAULT_TEST_MACHINE_NAME = "test_machine"`
- `DEFAULT_TEST_CONTAINER_NAME = "test_container"`
- `DEFAULT_TEST_TOKEN = "test-token"`
- `DEFAULT_TEST_OPERATOR_TOKEN = "test-operator-token"`

### 1. 影响的文件范围

- `test/conftest.py`
- `test/factories.py`
- `test/assertions.py`
- `test/mocks.py`
- `test/user/`
- `test/machine/`
- `test/container/`

### 2. 函数级收口的完整数据流

Factory 数据流：

1. 测试调用 `user_factory()`、`machine_factory()`、`container_factory()`。
2. factory 写入隔离测试库。
3. factory 返回 ORM 对象或轻量 DTO。
4. 测试调用 task/API。
5. assertion helper 验证数据库状态、HTTP payload、mock 调用。

Mock 数据流：

1. 测试调用 `mock_node_response()`、`mock_mail_success()`、`mock_auth_token()`。
2. mock 工具替换对应模块内被引用的函数。
3. 测试断言 mock 调用次数与参数。
4. 测试结束后 monkeypatch 自动恢复。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`user_factory(**overrides)`：

- 输入：username、email、password、permission 等覆盖字段。
- 输出：测试用户 ORM 对象。
- 内部逻辑重点：
  - 默认生成唯一 username/email。
  - password 默认写 hash。
  - permission 可设置 user/operator。

`machine_factory(**overrides)`：

- 输入：machine_name、machine_ip、machine_status、资源字段。
- 输出：测试机器 ORM 对象。
- 内部逻辑重点：
  - 默认 machine_status 为 online。
  - 默认资源足够创建标准容器。

`container_factory(**overrides)`：

- 输入：machine、owner、container_status、资源字段。
- 输出：测试容器 ORM 对象。
- 内部逻辑重点：
  - 默认创建 ROOT 绑定。
  - 可选创建 collaborator 绑定。

`auth_token_factory(user)`：

- 输入：User。
- 输出：token 字符串与 header。
- 内部逻辑重点：
  - token 默认未过期。
  - 可创建过期 token。

`mock_node_response(response)`：

- 输入：dict。
- 输出：记录调用的 mock 对象。
- 内部逻辑重点：
  - 不真实请求网络。
  - 能断言 endpoint 与 payload。

### 4. 测试用例的构建描述

- `test_user_factory_creates_unique_users`
- `test_user_factory_can_create_operator`
- `test_machine_factory_creates_online_machine_by_default`
- `test_container_factory_creates_root_binding_by_default`
- `test_auth_token_factory_creates_valid_token`
- `test_auth_token_factory_can_create_expired_token`
- `test_mock_node_response_records_calls`
- `test_mock_mail_success_records_recipient_subject_content`

## 阶段 2：GitHub Actions 可执行 CI

### 0. 新增的常量定义

建议在 workflow env 中只定义 pytest 可消费的安全覆盖项，不定义 `FLASK_CONFIG=testing`：

- `DISABLE_BACKGROUND_TASKS=1`
- `DATABASE_URL=sqlite:///:memory:`
- `LONG_TERM_CONTAINER_LIMIT=1`
- `CONTAINER_CLEANUP_AFTER_DAYS=7`
- `CONTAINER_CLEANUP_REMINDER_HOURS=72,24,12`
- `PYTHONUNBUFFERED=1`

### 1. 影响的文件范围

- `.github/workflows/ctrl-tests.yml`
- `pytest.ini`
- `requirements.txt` 或实际依赖锁文件
- `docs/testing.md`

### 2. 函数级收口的完整数据流

GitHub Actions 数据流：

1. `push` 或 `pull_request` 触发 workflow。
2. checkout 仓库。
3. setup Python。
4. 安装依赖。
5. 设置测试环境变量。
6. 执行安全测试命令。
7. 生成 coverage XML/HTML 或 pytest report。
8. 上传测试报告 artifact。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`ctrl-tests.yml`：

- 输入：GitHub Actions 事件。
- 输出：CI 通过/失败状态与测试报告 artifact。
- 内部逻辑重点：
  - 不启动 MySQL、Node、Docker service；数据库统一使用 SQLite。
  - 不读取生产 `.env`。
  - 不通过 `FLASK_CONFIG=testing` 启动应用；测试配置由 pytest fixture 的 overrides 注入。
  - 不需要私有内网资源。
  - 只跑 `pytest -m "not integration and not legacy"`。
  - 可按路径过滤只在 Ctrl 相关文件变更时运行，但第一版可先无路径过滤。

依赖安装步骤：

- 输入：依赖文件。
- 输出：可运行 pytest 的 Python 环境。
- 内部逻辑重点：
  - 如果项目无锁文件，先使用 `pip install -r requirements.txt`。
  - 如果存在测试依赖缺口，补 `pytest pytest-cov`。

Coverage 步骤：

- 输入：pytest 执行。
- 输出：coverage xml/html。
- 内部逻辑重点：
  - coverage 只统计 Ctrl 业务目录。
  - 排除 legacy/integration 测试。

### 4. 测试用例的构建描述

CI 本身不写 pytest 用例，使用 workflow 验收项：

- workflow 能在 GitHub Actions Ubuntu runner 启动。
- 不需要任何 secret。
- 不连接外部生产服务。
- 安全测试命令失败时 CI 失败。
- 上传 `pytest-report` 或 `coverage-html` artifact。
- workflow 日志中能看出 marker 表达式为 `not integration and not legacy`。

## 阶段 3：Coverage 与质量门槛

### 0. 新增的常量定义

- `COVERAGE_SOURCE = ["services", "blueprints", "repositories", "schemas", "utils", "config.py"]`
- `COVERAGE_FAIL_UNDER_INITIAL = 60`
- `COVERAGE_FAIL_UNDER_TARGET = 80`
- `CORE_SERVICE_TARGET = 85`

### 1. 影响的文件范围

- `pyproject.toml` 或 `.coveragerc`
- `pytest.ini`
- `.github/workflows/ctrl-tests.yml`
- `docs/testing.md`

### 2. 函数级收口的完整数据流

Coverage 数据流：

1. pytest 执行安全测试。
2. coverage 记录被测源码行。
3. coverage 生成终端报告与 XML/HTML。
4. CI 根据初始阈值判断是否失败。
5. 后续逐步提高阈值。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`.coveragerc`：

- 输入：coverage 运行。
- 输出：覆盖率统计规则。
- 内部逻辑重点：
  - source 限定 Ctrl 源码目录。
  - omit 排除：
    - `test/*`
    - migration 脚本，如暂无稳定 migration 测试。
    - `__pycache__/*`
    - 本地临时文件。

初始阈值策略：

- 输入：当前测试覆盖率。
- 输出：CI fail/pass。
- 内部逻辑重点：
  - 第一阶段阈值不要过高，避免阻塞重构。
  - user/machine/container 核心 task/API 完成后再提升。

### 4. 测试用例的构建描述

Coverage 本身通过配置验收：

- `pytest --cov` 能正常生成报告。
- coverage source 不包含测试目录。
- 初始阈值可通过。
- 手动降低覆盖时 CI 会失败。
- HTML artifact 可下载查看。

## 阶段 4：旧测试弃用、迁移表与防回流

### 0. 新增的常量定义

- `LEGACY_TEST_MARK = "legacy"`
- `INTEGRATION_TEST_MARK = "integration"`
- `SAFE_TEST_MARKS = ["unit", "api", "db"]`

### 1. 影响的文件范围

- `pytest.ini`
- `test/test_api_web.py`
- `test/test_api_web_machine.py`
- `test/test_api_web_containers.py`
- `test/test_user_sql.py`
- `test/test_machine_sql.py`
- `test/test_container_sql.py`
- `test/test_mail.py`
- `docs/testing_legacy_migration.md`

### 2. 函数级收口的完整数据流

迁移表数据流：

1. 建立旧测试文件清单。
2. 为每个旧测试标注：删除、迁移、legacy、integration。
3. 新测试覆盖后删除旧测试或标记跳过默认集。
4. CI 增加检查，防止未标记 legacy/integration 的旧测试进入安全集。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`docs/testing_legacy_migration.md`：

- 输入：旧测试文件与新测试覆盖表。
- 输出：迁移状态表。
- 内部逻辑重点：
  - 每个旧测试文件有明确去向。
  - 每个还保留的旧测试有 marker。
  - 不允许“看起来能跑但可能碰真实业务”的旧测试留在默认集。

`legacy guard`：

- 输入：pytest collection。
- 输出：发现未迁移旧测试时 fail 或 warning。
- 内部逻辑重点：
  - 初期可 warning。
  - 全量迁移后改为 fail。

### 4. 测试用例的构建描述

- `test_legacy_tests_are_marked_or_migrated`
- `test_default_safe_collection_excludes_legacy_tests`
- `test_integration_tests_are_not_selected_by_safe_command`
- `test_legacy_migration_doc_lists_all_old_test_files`

## 阶段 5：Ctrl 内部端到端模拟测试

### 0. 新增的常量定义

- `CTRL_E2E_MARK = "e2e"`
- `CTRL_E2E_TEST_USER = "e2e_user"`
- `CTRL_E2E_TEST_MACHINE = "e2e_machine"`
- `CTRL_E2E_TEST_CONTAINER = "e2e_container"`

### 1. 影响的文件范围

- `test/e2e/test_ctrl_user_machine_container_flow.py`
- `test/conftest.py`
- `test/factories.py`
- `services/user_tasks.py`
- `services/machine_tasks.py`
- `services/container_tasks.py`
- `blueprints/*_api.py`

### 2. 函数级收口的完整数据流

Ctrl 内部 E2E 数据流：

1. 使用隔离 SQLite 测试库创建用户。
2. 登录获得 token。
3. operator 创建机器或 factory 建机器。
4. 授权普通用户访问机器。
5. mock Node 创建容器成功。
6. 调用容器创建 API。
7. 查询 Home 所需容器列表。
8. 设置长期容器。
9. 再次查询列表，确认长期容器字段与清理展示数据可由前端消费。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`test_ctrl_user_machine_container_flow`：

- 输入：隔离 SQLite 测试库、mock Node、mock mail、mock scheduler。
- 输出：完整流程断言通过。
- 内部逻辑重点：
  - 不连接真实 Node。
  - 不发送真实邮件。
  - 不启动后台线程。
  - 只验证 Ctrl 内部跨模块契约。

`test_ctrl_cleanup_reminder_flow`：

- 输入：SSH 记录、容器、ROOT owner 邮箱、mock mail。
- 输出：提醒记录写入，邮件 mock 被调用。
- 内部逻辑重点：
  - 长期容器跳过提醒。
  - due 容器走删除路径，但删除 task 被 mock。

### 4. 测试用例的构建描述

- `test_ctrl_e2e_user_login_machine_permission_container_create_and_list`
- `test_ctrl_e2e_set_long_term_then_list_reflects_long_term_state`
- `test_ctrl_e2e_cleanup_reminder_sends_mail_for_countdown_container`
- `test_ctrl_e2e_cleanup_reminder_skips_long_term_container`

## 阶段 6：测试报告与失败分类

### 0. 新增的常量定义

- `PYTEST_JUNIT_XML = "reports/pytest.xml"`
- `COVERAGE_XML = "reports/coverage.xml"`
- `COVERAGE_HTML_DIR = "reports/htmlcov"`

### 1. 影响的文件范围

- `.github/workflows/ctrl-tests.yml`
- `pytest.ini`
- `.coveragerc`
- `docs/testing.md`
- `reports/`，只作为生成目录，不提交生成物。

### 2. 函数级收口的完整数据流

报告数据流：

1. pytest 运行。
2. 生成 JUnit XML。
3. coverage 生成 XML/HTML。
4. GitHub Actions 上传 artifact。
5. 开发者根据失败测试名称定位分类。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

`pytest --junitxml`：

- 输入：测试结果。
- 输出：`reports/pytest.xml`。
- 内部逻辑重点：
  - 便于 GitHub Actions 展示失败用例。

`coverage html/xml`：

- 输入：coverage 数据。
- 输出：XML/HTML 报告。
- 内部逻辑重点：
  - XML 用于后续接入 badge/codecov 类工具。
  - HTML 用于人工查看。

失败分类规则：

- `unit` 失败：优先视为函数合同变化。
- `api` 失败：优先视为 HTTP payload/status 映射变化。
- `db` 失败：优先视为 repository/model 合同变化。
- `e2e` 失败：优先视为跨模块数据流断裂。
- `integration` 失败：不阻塞默认安全回归。

### 4. 测试用例的构建描述

报告本身通过 CI 验收：

- CI 失败时能看到失败测试名称。
- CI 成功时 artifact 可下载。
- JUnit XML 路径稳定。
- coverage XML/HTML 路径稳定。

## 阶段 7：测试编码规范与维护约束

### 0. 新增的常量定义

无。

### 1. 影响的文件范围

- `docs/testing.md`
- `test/README.md`
- `test/conftest.py`
- `test/factories.py`
- 所有新测试目录

### 2. 函数级收口的完整数据流

维护数据流：

1. 新业务改动先明确属于 user/machine/container/schema/repository/utils 哪一类。
2. 新测试使用已有 factory/mock。
3. 新测试默认进入安全集。
4. 只有真实外部依赖测试才标 integration。
5. 旧测试不得新增。

### 3. 精确到输入输出的函数级收口，以及重要函数内部逻辑

测试命名规则：

- 输入：被测函数或 API。
- 输出：`test_<subject>_<condition>_<expected_result>`。
- 内部逻辑重点：
  - 名称体现条件和期望结果。

Mock 规则：

- 默认 mock 外部服务。
- 只在 integration 测试中允许真实外部服务。
- mock 应打在“被测模块实际引用的位置”，避免 mock 了定义处但业务仍调用真实函数。

数据规则：

- 测试数据必须由 factory 创建。
- 不使用随机数据掩盖唯一性问题，除非 factory 内部可追踪。
- 每个测试独立，不依赖执行顺序。

断言规则：

- task 测试断言返回值、异常 reason、本地状态。
- API 测试断言 status code、payload、service 调用。
- repository 测试断言数据库最终状态。

### 4. 测试用例的构建描述

维护约束可通过轻量检查实现：

- `test_no_new_unmarked_legacy_style_tests`
- `test_no_tests_import_requests_without_integration_marker`
- `test_no_tests_call_create_app_without_testing_config`
- `test_test_readme_documents_factory_and_mock_rules`

## 阶段验收顺序

1. 先完成默认安全命令与文档。
2. 平台化 fixture/factory/mock。
3. 接入 GitHub Actions，仅运行 GitHub runner 可执行的安全测试。
4. 接入 coverage，但初始阈值保守。
5. 建立旧测试迁移表与防回流检查。
6. 增加少量 Ctrl 内部 E2E 模拟测试。
7. 输出测试报告 artifact。
8. 固化测试编码规范。

## 本阶段不做的事

- 不在 CI 中连接生产/开发数据库。
- 不在 CI 或默认回归中引入 MySQL 平行库。
- 不在 CI 中启动 Node、Docker 或真实邮件服务。
- 不要求 GitHub Actions 访问内网资源。
- 不把 legacy/integration 纳入默认阻塞检查。
- 不把前端 E2E 纳入 Ctrl 测试计划。
