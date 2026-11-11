# Spec Delta

> 本 delta 仅复制既有 Requirement 完整块；Requirement 名、SHALL 语义、Scenario 名与 WHEN/THEN 原文均与主规格逐字一致，语义无变更，不新增业务行为。

## MODIFIED Requirements

### Requirement: 默认安全命令与隔离边界

默认安全套件 SHALL 以 `pytest -m "not integration and not legacy"` 运行；`pytest.ini` 的默认 `addopts` MUST 含相同的 marker 选择表达式 `-m "not integration and not legacy"`（文件登记的是 `addopts = ...` 条目，并非整条 `pytest` 命令）。测试应用 MUST 通过 `create_app(overrides=...)` 注入只含 SQLite 的测试配置，MUST NOT 靠运行应用时的 `FLASK_CONFIG` 之类环境开关替代测试 overrides。套件 SHALL 在校验到非 SQLite 的数据库 URI 时直接拒绝运行。默认套件 SHALL 设计为可在生产服务仍运行时执行。

#### Scenario: 安全默认命令

- **WHEN** 在仓库根执行默认命令，或未显式覆盖 marker 选择地执行 pytest
- **THEN** 只收集非 `integration`、非 `legacy` 的用例，且使用内存 SQLite；`pytest.ini` 的 `addopts` 含相同 marker 表达式

#### Scenario: 测试配置注入

- **WHEN** 测试创建应用
- **THEN** 经 `create_app(overrides=...)` 注入 `SQLALCHEMY_DATABASE_URI` 以 `sqlite://` 开头、`TESTING` 与 `DISABLE_BACKGROUND_TASKS` 为真、清除 MySQL 专属 `init_command` 的配置；不得靠运行应用时的 `FLASK_CONFIG` 之类环境开关替代，此约束不得被读成否定 `create_app` 内的 `TESTING=True`

#### Scenario: 非 SQLite 隔离被拒

- **WHEN** 测试应用的数据库 URI 不以 `sqlite://` 开头
- **THEN** 会话夹具抛错拒绝运行，而不是连上生产或开发数据库

### Requirement: 安全套件不得触达真实外部资源

默认套件 MUST NOT 触达：生产或开发数据库、真实 Node 服务、真实 Docker、真实 SMTP 服务、后台调度器、私网资源。`test/conftest.py` SHALL 在非 `integration` 用例中拦截出站 HTTP 与 SMTP：钉在 `requests.Session.request` 这一出站唯一咽喉上，并让 `smtplib.SMTP`、`smtplib.SMTP_SSL` 抛错；邮件发送 SHALL 以 `utils.mail` 的 `_send_smtp` / `_send_batch_smtp` 替身返回本地构造的成功结果（其 `mode` 字段固定为 `pytest-mock`，仅是本仓库测试替身的标识，MUST NOT 据此声称依赖 pytest-mock 库）。标记为 `integration` 的用例 SHALL 豁免这些替身，以便在有意的环境中访问真实服务。

#### Scenario: 真实 HTTP 被拦截

- **WHEN** 安全套件中的用例调用 `requests.post` 或带自定义适配器的 `requests.Session().post`
- **THEN** 在 `Session.request` 处抛出「Real HTTP requests are blocked」断言，不发真实请求

#### Scenario: 真实 SMTP 被拦截

- **WHEN** 安全套件中的用例构造 `smtplib.SMTP` 或 `smtplib.SMTP_SSL`
- **THEN** 抛出「Real SMTP」/「Real SMTP_SSL」断言；邮件发送走模块替身

#### Scenario: 集成用例豁免替身

- **WHEN** 用例所属模块带 `integration` marker
- **THEN** 外部服务替身不生效，允许访问有意准备的真实服务

### Requirement: integration 与 legacy 的选择

`integration` 用例 SHALL 被默认套件排除，因其可能依赖真实外部服务；只有在环境被有意准备时才以 `pytest -m integration` 显式运行。`legacy` marker SHALL 仅在 `pytest.ini` 中登记，用于防止旧本地文件被意外收集，MUST NOT 作为第二套契约长期维护；迁移前的旧测试 SHALL 删除，而不是保留。`pytest.ini` SHALL 登记 `unit`、`api`、`db`、`e2e`、`integration`、`legacy` 六类 marker。

#### Scenario: 默认不收集集成用例

- **WHEN** 执行默认安全命令
- **THEN** 带 `integration` marker 的模块被排除，不算失败

#### Scenario: legacy 仅防止误收集

- **WHEN** 工作区残留旧的未迁移测试文件
- **THEN** `legacy` marker 使其不被默认收集；不得据此把旧测试当作受维护契约

### Requirement: factory 与 mock 职责

常规业务测试 SHALL 优先复用 `test/factories.py` 构造数据库数据，共享 mock 辅助 SHALL 放在 `test/mocks.py`。特定约束、旧 DDL 迁移或隔离边界类 fixture SHALL 允许直接构造模型对象或执行 DDL/SQL，但 MUST 只作用于测试 SQLite，MUST NOT 触达生产或开发数据库。外部服务 SHALL 在**被测代码实际使用的模块导入位置**打桩。常规业务测试 MUST NOT 绕过保护进行真实通信。

#### Scenario: 常规测试优先复用 factory

- **WHEN** 常规业务测试需要用户、机器、容器等 ORM 数据
- **THEN** 优先通过 `test/factories.py` 的工厂函数构造

#### Scenario: 约束与隔离 fixture 可直接构造

- **WHEN** 特定约束、旧 DDL 迁移或隔离边界 fixture 需要直接构造模型或执行 DDL/SQL
- **THEN** 允许直接构造（如 `test/conftest.py` 的 `ensure_auth_users` 直接 `User(...)`）或执行 DDL，但只作用于测试 SQLite

#### Scenario: 在真实调用位置打桩

- **WHEN** 被测代码通过某模块的 `send_mail` 或 `send` 发出外部调用
- **THEN** mock 打在该模块对象上，可断言调用记录；任务测试断言返回值、异常原因与本地库状态，API 测试断言 HTTP 状态、响应体与 service 层调用，repository 测试断言最终 SQLite 状态

#### Scenario: 隔离验证可触发被拦截入口

- **WHEN** 需要验证 HTTP/SMTP 保护确实生效
- **THEN** `test/test_testing_safety_contract.py` 的 `test_real_network_is_blocked_by_default`、`test_real_smtp_is_blocked_by_default` SHALL 允许触发被拦截入口；该文件整体豁免「非 `integration` 测试不得 `import requests`」的 AST 契约，常规业务测试仍受该契约与「不得绕过保护真实通信」约束

### Requirement: 已删除的旧测试文件与替换覆盖

迁移前的旧测试文件 SHALL 视为 deleted，不保留为第二套契约；新增覆盖 SHALL 落在 `test/` 下的分类目录中。仍可能触达真实 Node、真实 SMTP 或非 SQLite 数据库的旧测试 MUST 留在安全套件之外。

#### Scenario: 旧测试删除名单与替换覆盖

- **WHEN** 检查迁移前的旧测试文件
- **THEN** 六个文件均为 deleted，`test/test_mail.py` 为 `integration`，替换覆盖如下：
  - `test/test_api_web.py` — deleted，替换覆盖 `test/user/test_user_api_auth.py`、`test/user/test_user_api_profile.py`
  - `test/test_user_sql.py` — deleted，替换覆盖 `test/user/test_user_tasks_*.py`、`test/user/test_user_repository_integration.py`
  - `test/test_api_web_machine.py` — deleted，替换覆盖 `test/machine/test_machine_api_*.py`
  - `test/test_machine_sql.py` — deleted，替换覆盖 `test/machine/test_machine_tasks_*.py`、`test/machine/test_machine_repository_integration.py`
  - `test/test_api_web_containers.py` — deleted，替换覆盖 `test/container/test_container_api_*.py`
  - `test/test_container_sql.py` — deleted，替换覆盖 `test/container/test_container_tasks_*.py`、`test/container/test_container_cleanup_*.py`
  - `test/test_mail.py` — `integration`，替换覆盖 `test/utils/test_mail.py`

#### Scenario: 旧测试文件不得复活

- **WHEN** 检查上表列出的六个旧文件路径
- **THEN** 均不存在；新增同名或 `*_sql.py` 形态的根级旧式测试被视为违规

#### Scenario: 替换覆盖存在

- **WHEN** 需要某旧文件的等价覆盖
- **THEN** 在对应的 `test/` 分类目录中查找，而不是恢复旧文件

### Requirement: 邮件集成测试的真实标记

`test/test_mail.py` SHALL 以模块级 `pytestmark = pytest.mark.integration` 标为真实邮件集成测试，并 SHALL 从 `MAIL_TEST_TO` / `MAIL_HOST` / `MAIL_SENDER` / `MAIL_PORT` 读取真实配置；任一缺失时 SHALL `skip` 而不是失败。安全套件对邮件模块的覆盖 SHALL 落在 `test/utils/test_mail.py`，以桩 SMTP 断言发送成功、失败与批量连接的本地数据库审计，MUST NOT 依赖真实 SMTP。

#### Scenario: 缺少真实配置则跳过

- **WHEN** 邮件集成测试所需环境变量未配置
- **THEN** 用例 skip，默认安全套件不因此失败

#### Scenario: 安全套件用桩 SMTP

- **WHEN** 在默认套件中测试 `utils.mail`
- **THEN** 通过 `test/utils/test_mail.py` 的桩 SMTP 覆盖，不构造真实 `smtplib.SMTP`

### Requirement: 规范入口不使用代理说明文件

测试安全规范 SHALL 维护在 OpenSpec 中，SHALL NOT 生成、保留或提交 `AGENT.md`、`AGENTS.md`，`openspec/` 内 MUST NOT 放置 README。已退役的 `docs/testing.md`、`docs/testing_legacy_migration.md` 与 `test/README.md` MUST NOT 在仓库内恢复；规范以本文件为准，MUST NOT 声称已退役的 Global 文档仍然权威。

#### Scenario: 生成代理说明文件

- **WHEN** 工具在仓库中生成 `AGENT.md` 或 `AGENTS.md`
- **THEN** 移除该文件并从暂存区排除，适用规范整理到本仓库 OpenSpec

#### Scenario: 不恢复旧文档

- **WHEN** 需要查阅测试安全约定
- **THEN** 读取本 OpenSpec 规范，而不是恢复已退役的 docs 或 test README
