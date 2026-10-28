# Design

## Context

- 范围是两个既有 procedure capability：`procedure--repository-workflow`（8 个 Requirement、16 个 Scenario）与 `procedure--testing-safety`（7 个 Requirement、19 个 Scenario），合计 35 个 Scenario。
- 两份主规格已固化流程契约，但 `openspec/specs/procedure--repository-workflow/` 与 `openspec/specs/procedure--testing-safety/` 下都没有 test-plan sidecar；本次是该对账前沿的首次规划。
- 既有覆盖来源已只读核对：
  - `scripts/ci/tests/test_check_pr.py`：PR 正文校验的真实单元测试（unittest）。
  - `test/test_testing_safety_contract.py`：marker、旧文件删除、HTTP/SMTP 触发入口与 `read_text` 文本契约；其中多项是配置/源码文本检查，不能冒充规则执行。
  - `test/conftest.py`：`TEST_CONFIG_OVERRIDES`、`_assert_sqlite_database_uri`、`mock_external_services`（HTTP/SMTP/邮件替身与 `integration` 分支）。
  - `test/utils/test_mail.py`、`test/test_mail.py`、`test/operation_log/test_mail_audit.py`：邮件真实发送标记、桩 SMTP 行为与本地审计。
  - `test/test_safe_pytest_app.py`、`test/test_testing_platform.py`、`test/repository/test_authentications_repo.py`、`test/container/test_container_*.py`、`test/machine/test_machine_*.py`：应用工厂、factory、任务/API/repository 观察面的代表性证据。
- `githooks/commit-msg` 与 `githooks/pre-commit` 是 bash 脚本：前者只读消息文件与 `MERGE_HEAD`，后者读暂存区新增路径并在 delta 场景用 `HEAD` 判断既有主规格；两者都不需要执行 commit 即可覆盖多数分支。
- `pytest.ini` 的默认 `addopts` 是 `-m "not integration and not legacy"`；`test/test_mail.py` 是模块级 `pytestmark = pytest.mark.integration`。
- 约束：本步只写 change 内的 proposal/design/specs/test-plan；不改主规格、业务、既有测试、共享 fixture、依赖、DB、config、CI、skills；不执行测试、不写 review/tasks/sidecar；不真实 commit、部署或删除；不打开或解析真实 `.env` 以取得密钥，不读取 APIKEY/PASSCODE 值或生产数据库。

## Goals / Non-Goals

**Goals:**

- 为 35 个 Scenario 建立 `Requirement → Scenario → Test/check → Assertion scope → Coverage note` 的完整、可审计映射。
- 区分三类证据：逐段读过的既有真实断言、明确标记为拟补的自动化用例、以及无自动化对象时的人工可复现检查。
- 把可自动化缺口收敛到一个专属新文件 `test/test_anvil_workflow_safety.py`，并写清每个待补用例的断言范围；本步不创建该文件。
- 如实记录部分覆盖、配置文本检查的边界，以及 README 清理等已核实仓库事实。

**Non-Goals:**

- 不改任何业务实现、模型、迁移、既有测试、`conftest.py`、共享 fixture 或测试目录结构。
- 不新增业务行为、表、字段、规则；不为了迁就现有测试而削弱规格或改写 THEN。
- 不把静态文本检查包装成“规则已被执行”；不为程序性步骤造机械的源码字符串测试。
- 不写 `review.md`、`tasks.md`、主规格 sidecar；不记录运行结果、通过率或时间戳。

## Decisions

### D1：delta 采用 MODIFIED 完整 Requirement 块，逐字零差异

两份 delta 只含 `## MODIFIED Requirements`，逐字复制主规格的 Requirement 块（标题、正文、Scenario 名、WHEN/THEN），不复制 Purpose 与 Source references。生成后用脚本对主规格 `## Requirements` 与 delta 的 `## MODIFIED Requirements` 做逐字符比较：两份均完全一致，Requirement 数 8/7、Scenario 数 16/19。

- 备选：用 ADDED 写“测试对账要求”——否决，会凭空造业务需求。
- 备选：在 Requirement 正文里插入本轮说明——否决，会污染主规格；说明只放在 delta 标题下的引用块与 proposal/design 中。
- 备选：缩写 Requirement——否决，MODIFIED 不接受部分内容。

### D2：`[X]` 的证据标准

只有同时满足才算 `[X]`：locator 精确到文件与用例名；已读过该用例的断言语句；断言确实覆盖 Assertion scope 所列的可观察面，且不是 monkeypatch 替身返回值的回声。仅“调用了相关函数”“断言了状态码”或“源码里有这段文字”不算。

- 配置文本检查（如 `pytest.ini` 的 `addopts`、conftest 的源码字符串）只证明配置/实现文本存在，不证明真实的收集、拦截或执行行为；这类行可以标 `[X]`，但 Assertion scope 必须写明它只证明配置事实，真实行为另列拟补用例或 manual check。
- 一个 Scenario 可以由多条 locator 共同覆盖；某条 THEN 没有直接证据时，Coverage note 明确写出缺哪一半，不把“部分覆盖”写成“全覆盖”。

### D3：缺口集中到一个专属新文件

可自动化缺口统一规划到 `test/test_anvil_workflow_safety.py`，不修改任何既有测试、`conftest.py` 或共享 fixture。计划中的用例名在 test-plan 中给出；本步不创建文件，因此所有拟补行都是 `[ ]`。新文件遵循现有相对导入与 `db_session`/`ensure_auth_users`/`monkeypatch` 约定，不新增 fixture。

### D4：程序性步骤用 manual check，不造机械文本测试

以下 Scenario 或 Requirement 正文约束没有可自动执行的对象，或执行它需要越过本步的禁止项，规划为可复现 manual check，并在 Assertion scope 写清检查范围：

- 钩子启用时对既有 `core.hooksPath` / `.git/hooks` 自定义入口的保留或迁移判断（仓库工作流“目标克隆已有钩子配置”）。
- 需要 HEAD 基线才能区分的 pre-commit 分支：修改既有 capability 正文、旧 capability 的第一次 delta、`git mv` 改名与 archive 放行（不执行真实 commit）。
- 能力粒度：Ctrl 的 `backend--table-*` 能力以数据表为单位（命名 Requirement 的正文约束，没有独立 Scenario）。
- “未实现的自动检查不得声称”：用真实 `check_pr.py` 跑一条结构合规但内容虚构的正文，再对照三个自动化入口，确认没有真实性/标题校验。
- Global `QUESTIONS.md` 的问题状态登记与规范独立性通读。
- 邮件集成测试缺少真实配置时的 skip 行为：当前仓库不执行；包导入会 `load_dotenv(..., override=True)` 读取 `.env`，integration marker 又豁免 SMTP 替身，仅清空外层变量不安全。该分支标为未验证 manual，只有“临时无 `.env` 副本/临时克隆 + 子进程清除四个变量 + `sitecustomize` 拦截 socket 出站”同时具备时才可执行。
- `legacy` 只作为 `pytest.ini` 收集排除 marker，不在 `test/` 中作为第二套契约使用。
- 生成 `AGENT.md`/`AGENTS.md` 时的移除与排除动作。

这些 manual check 不写成源码字符串测试，也不声称已经执行；它们与自动化缺口一样在 test-plan 中有明确 locator/command 与 Coverage note。

### D5：commit-msg / pre-commit 在临时 git 目录中测真实脚本，不 commit

- `commit-msg`：在临时 `git init` 目录中准备消息文件；需要合并豁免时写 `.git/MERGE_HEAD`；直接调用仓库 `githooks/commit-msg`。不调用 `git commit`，不触碰当前仓库历史。
- `pre-commit`：在临时 `git init` 目录中用 `git hash-object -w` + `git update-index --add --cacheinfo` 暂存新增的 spec 路径，再调用仓库 `githooks/pre-commit`；只读索引，不 commit。需要 HEAD 才能区分的两个分支留给 D4 的 scratch clone manual check。
- Windows 上 `bash` 可能解析到 WSL；测试显式使用 Git for Windows 自带的 bash（由 Git 安装目录下 `bin/bash.exe` 定位，而不是 `C:\Windows\System32\bash.exe`），避免 WSL 对 Windows 路径与 `GIT_DIR` 的语义差异。若 Git Bash 不可用，apply 阶段必须报告环境缺失，不得静默跳过并宣称覆盖。

### D6：测试安全规则只做隔离的真实行为验证

- HTTP/SMTP：复用 `test/conftest.py` 的 `Session.request`、`smtplib.SMTP`、`smtplib.SMTP_SSL` 与 `utils.mail._send_smtp` 替身；只触发被拦截入口，不发出真实请求。自定义适配器路径通过生产 `transport._post_node_json` 加临时 dummy pin 触发，仍在 `Session.request` 处被拦。
- SQLite 隔离：直接调用 `_assert_sqlite_database_uri` 的纯 helper 分支；用假的非 SQLite URI 断言 `RuntimeError`，不连接任何真实数据库。
- 应用工厂：用 `create_app(overrides=TEST_CONFIG_OVERRIDES)` 读 `app.state.config`，断言 `TESTING`、`DISABLE_BACKGROUND_TASKS`、SQLite URI 与空 `SQLALCHEMY_ENGINE_OPTIONS`；用一个假 `FLASK_CONFIG` 环境变量证明 overrides 不依赖它。
- `integration` 豁免：拟补用例自身标 `@pytest.mark.integration`，只在 `pytest -m integration` 下运行；autouse 的 `mock_external_services` 直接走豁免分支。用例不显式请求 `app`/`db_session`，autouse fixture 仍会创建临时测试 SQLite，不触真实数据库或网络；只断言原始 `requests.Session.request` / `smtplib.SMTP` 未被替换；不调用 `__wrapped__` 或直接驱动 fixture 生成器（当前删除该冗余调用）。requests 用 `importlib.import_module("requests")` 取模块，避免在非模块级豁免文件里写 `import requests`。
- 邮件：`mail.send` / `mail.send_batch` 走 conftest 的 `_send_smtp` / `_send_batch_smtp` 替身，断言本地成功结果与 `mode == "pytest-mock"`；`test/utils/test_mail.py` 的桩 SMTP 覆盖发送、失败与批量审计。
- 收集探针：`test_default_suite_deselects_integration_and_legacy_probes` 的探针放在 `tmp_path`、只导入 pytest、不导入应用；子进程使用最小环境（不继承 `MAIL_*`/真实 `.env` 变量），并由 `tmp_path/sitecustomize.py` 用 `socket.socket` 子类覆盖 `connect`/`connect_ex`、替换 `socket.create_connection`/`socket.getaddrinfo` 为抛错，禁止 socket 出站。探针只验证 `pytest --collect-only` 的 marker 过滤，不运行真实用例。
- PR 正文“不执行正文”：既有 `test_event_metadata_with_quotes_and_backticks_stays_data` 只断言 `check_pr.main` 返回 0 且输出“通过”，源码 token 检查只证明当前源码不含 `eval/exec/subprocess` 等，二者都不是“未求值”的行为 oracle；拟补 `test_check_pr_does_not_execute_body_sentinel`，在正文里放会写 sentinel 文件的 Python payload，断言退出 0、输出“通过”、sentinel 不存在。该用例保持 `[ ]`，未创建。
- 不打开或解析真实 `.env` 以取得密钥，不读取 APIKEY/PASSCODE 值，不连接生产数据库；不以反射 ORM 声明或源码字符串代替行为断言。

### D7：README 生成物已由父级清理，全 `openspec/` 规则可直接检查

父级 `d97d6a7` 已移除本轮生成、仅重复 proposal 摘要的两个 README（1 活动 1 归档），原文备份在外部 `removed-generated-readmes.md`。当前三仓 `openspec/` 树内 README 文件名检查为 0（Ctrl/Node/Web），因此全 `openspec/` 规则可直接检查，不再有未解决冲突或新增 Global 问题。本 change 只做文件名存在检查，不读取 README 内容、不重建 README、不重构文档树、不改主规格；若未来新增 README，直接检查会失败。

### D8：计划不写运行 ledger

test-plan 只写映射、断言范围与覆盖边界；不写通过数、失败数、时间戳、执行证据或“已运行”状态。manual check 只写可复现命令与期望观察，不写本次是否执行的结果。

## Risks / Trade-offs

- **风险：`[X]` 高估。** 缓解：D2 的逐段读断言标准；静态配置检查在 Assertion scope 中明说，真实行为另列 `[ ]` 或 manual check。
- **风险：bash 跨平台差异。** 缓解：D5 显式使用 Git for Windows bash；apply 阶段若环境缺失，报告而不是跳过。
- **风险：`create_app` 全局配置副作用。** 缓解：沿用既有 app 测试的隔离环境；拟补用例读取 `app.state.config`，不修改真实 `.env`；必要时在用例内保存/恢复 `AppConfig` 属性。
- **风险：manual check 无法自动化回归。** 权衡：这些步骤本身依赖人工判断或需要真实 commit/HEAD 基线；用明确命令与范围换取可复现，而不是造一个只检查文本的假测试。
- **风险：delta 与主规格漂移。** 缓解：D1 的逐字符比较；review 前若主规格变化，重新生成并复审。
- **风险：README 规则回退。** 父级 `d97d6a7` 已清理生成物；D7 用 `git ls-files` 与文件名枚举直接检查全 `openspec/`，若未来新增 README 会失败。本 change 不重建 README。
- **风险：拟补用例未创建、未运行。** 权衡：本步只规划；实际可写性与行为留给 apply 确认，若与计划不符，应更新计划并重新 review，而不是放宽断言。
