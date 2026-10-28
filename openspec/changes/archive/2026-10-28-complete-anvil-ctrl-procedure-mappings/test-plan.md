# Test Plan

> 映射约定：`[X]` 表示 locator 存在、且其断言已从测试代码或实际命令逐段核对，能覆盖所列的可观察面；`[ ]` 表示用例、locator 或断言尚未确认。本计划中的自动化缺口统一规划到 `test/test_anvil_workflow_safety.py`，该文件本步不创建。
>
> 复选框只表示映射有效性，不表示运行/通过，也不表示整条 Scenario 已全覆盖；部分覆盖、配置文本检查的边界与人工步骤一律写在 Coverage note。
>
> 范围是 `procedure--repository-workflow` 的 8 个 Requirement / 16 个 Scenario 与 `procedure--testing-safety` 的 7 个 Requirement / 19 个 Scenario，合计 35 个 Scenario。本计划不记录运行结果、通过率或时间戳。
>
> 程序性且无自动化对象的步骤使用 `manual check` 行，写明可复现命令或 scratch clone 操作与检查范围；`manual check` 标 `[X]` 仅表示检查命令、预期观察与覆盖范围的映射已确认，不表示一次执行或通过；标 `[ ]` 表示映射尚待确认。不把源码字符串检查当作规则执行，也不为测试执行真实 commit、部署或删除。

## procedure--repository-workflow

### Requirement: 提交信息条目格式

#### Scenario: 合规提交

- Test/check:
  - [X] test/test_anvil_workflow_safety.py::test_commit_msg_accepts_only_well_formed_item_lines
- Assertion scope: 在临时 `git init` 目录中直接调用仓库 `githooks/commit-msg`，不执行 commit。合法消息 `- NEW 新增测试映射` 返回 0；同一合法消息夹带空行与 `#` 注释行时仍返回 0，证明这两类行被跳过；`-NEW 缺空格`、`- ADD 自造关键字`、只有空行或 `#` 注释的消息返回非 0，stderr 含“第 N 行不符合条目格式”或“至少需要一条实际变更”；失败行在 stderr 重复原文。命令路径与消息文件内容都由用例构造，不依赖当前仓库的暂存区。
- Coverage note: apply 已新增 commit-msg 用例；本行对应用例已创建。hook 需要 bash 与 git；用例不调用 `git commit`。Requirement 正文“提交关键字与 PR 栏目是两套独立体系、不得互相推导”是结构约束，未由该 hook 测试取证；PR 正文校验也不读取提交关键字，本计划不把两者互推。

#### Scenario: 合并提交豁免

- Test/check:
  - [X] test/test_anvil_workflow_safety.py::test_commit_msg_merge_head_bypasses_item_format
- Assertion scope: 在临时 git 目录写入 `.git/MERGE_HEAD` 后，传入不符合条目格式的默认合并信息，`commit-msg` 返回 0（hook 在 `MERGE_HEAD` 存在时提前 `exit 0`）；删除 `MERGE_HEAD` 后同一消息返回非 0，证明豁免只由合并态触发。
- Coverage note: apply 已新增本行用例；本行只验证 hook 的文件级分支，不实际执行 `git merge` 或 `git commit`。

#### Scenario: 署名尾注被拒

- Test/check:
  - [X] test/test_anvil_workflow_safety.py::test_commit_msg_rejects_attribution_trailers_and_lists_hits
- Assertion scope: 分别写含 `Co-authored-by:`、`Generated with`、`🤖` 的消息，hook 返回非 0，stderr 含“提交信息不得包含署名尾注或生成标记”并逐行列出命中的原文（`grep -inE` 输出）；合法条目与尾注并存时也被拒，证明尾注检查独立于条目格式。
- Coverage note: hook 的 regex 只覆盖 `co-authored-by` / `generated with` / `🤖` 三类。规格中的“机器人标记”若指其它字面量，未被 hook 覆盖；这是实现边界，本计划不造额外断言。

### Requirement: 钩子启用与书写

#### Scenario: 目标克隆已有钩子配置

- Test/check:
  - [X] git config --local --get core.hooksPath
  - [ ] manual check (scratch clone): 在预置 `core.hooksPath` 或 `.git/hooks/pre-commit` 的临时克隆中记录旧值与旧入口，再执行 `git config --local core.hooksPath githooks`，确认旧入口未被静默覆盖，保留/迁移方案有记录；若已有会话授权覆盖该调整，直接按授权执行，不重复索要确认
- Assertion scope: 第一条命令直读当前克隆的本地配置，期望输出 `githooks`，证明本克隆已启用仓库内钩子（不是源码字符串推断）。第二条 manual check 在 scratch clone 上核对“先检查现有配置与自定义钩子、再按已有授权调整”的顺序，以及 `core.hooksPath` 是替换而非叠加：设置后 `.git/hooks/` 不再被读取，手写入口必须被显式保留或迁移；已有授权时不再重复确认。
- Coverage note: 当前克隆已配置；保留/迁移是人工判断，无自动化对象。第一条只证明当前克隆的配置值，不证明其它克隆也已启用，也不证明历史调整过程没有覆盖自定义入口。

#### Scenario: 换行与可执行位

- Test/check:
  - [X] git ls-files -s githooks/commit-msg githooks/pre-commit
  - [X] python -c "from pathlib import Path; print([p.read_bytes().count(bytes([13,10])) for p in (Path('githooks/commit-msg'), Path('githooks/pre-commit'))])"
- Assertion scope: 第一条命令读 Git index，两个文件都应显示模式 `100755`；第二条逐字节统计两个文件的 CRLF 数，期望均为 0，即 LF。Windows 上 `core.filemode=false`，索引中的 100755 需由 `git update-index --chmod=+x` 显式补，不能从工作树权限推断。
- Coverage note: 两条命令只证明当前克隆的索引模式与文件字节；其它克隆检出后的工作树模式仍取决于平台，不能由本检查外推。规格所述 Permission denied（exit 126）或钩子静默不执行是缺执行位/换行的后果，本计划不另造故障注入。

### Requirement: 能力命名与粒度

#### Scenario: 叠加前缀被拒

- Test/check:
  - [X] test/test_anvil_workflow_safety.py::test_pre_commit_rejects_double_prefix_capability
- Assertion scope: 在临时 `git init` 仓库中用 `git hash-object -w` 与 `git update-index --add --cacheinfo 100644,<blob>,openspec/specs/backend--standard--xxx/spec.md` 暂存新增文件，运行 `githooks/pre-commit`；退出非 0，stderr 含“capability 不得叠加门类前缀”及该路径；不执行 commit。
- Coverage note: apply 已新增本行用例；本行只走 `openspec/specs/*/spec.md` 的新增分支，不覆盖 archive、`git mv` 改名或 delta 路径。

#### Scenario: 缺前缀被拒

- Test/check:
  - [X] test/test_anvil_workflow_safety.py::test_pre_commit_rejects_capability_without_prefix
  - [ ] manual check: `Get-ChildItem openspec/specs -Directory | Select-Object -ExpandProperty Name`，核对 Ctrl 的 `backend--table-*` 能力目录以数据表为单位（一个数据表对应一个 capability，不把多表合成一个能力、也不把一个表拆成多个能力）；`procedure--` / `standard--` 等流程或跨端能力不属于数据表粒度
- Assertion scope: 同上暂存 `openspec/specs/calendar/spec.md`，hook 退出非 0，stderr 含“capability 名缺少门类前缀”与四类前缀提示；暂存 `openspec/specs/backend--calendar/spec.md` 时 hook 退出 0，证明它拒绝的是缺前缀而不是所有新增 capability。manual check 直接列出现有 `openspec/specs/` 目录，核对 Ctrl 的 `backend--table-*` 粒度是数据表；本仓库不承载 Node 的 8 个能力单元与 Web 页面规格，因此只核对 Ctrl 这一端。
- Coverage note: apply 已新增本行用例；本行不执行 commit，也不构造真实业务文件。粒度约束没有独立 Scenario，故以 manual check 补在命名 Requirement 下；它检查的是现有目录清单，不新增或改名任何 capability。Node/Web 的粒度约束不在本仓库取证范围。

#### Scenario: README 位置

- Test/check:
  - [X] Test-Path README.md
  - [X] git ls-files -- ':(glob)openspec/**/README*'
  - [X] Get-ChildItem openspec -Recurse -File -Filter 'README*' | Select-Object -ExpandProperty FullName
  - [X] manual check (仅核对文件名): 对 `FuxiYu_CtrKernel`、`FuxiYu_NodeKernel`、`FuxiYu_Web` 的 `openspec/` 做 `Get-ChildItem -Recurse -File -Filter 'README*'` 文件名枚举，期望均为空
- Assertion scope: 第一条期望 `True`，仓库根 README 存在；第二条用 Git index 检查 `openspec/` 下没有名为 `README*` 的跟踪文件；第三条用文件系统枚举检查全 `openspec/` 没有 README 文件名；第四条对三仓 `openspec/` 做同样的文件名枚举，期望均为空；只核对文件名，不读取 README 内容。四条检查覆盖文件名与路径，不是源码文本匹配。
- Coverage note: 全 `openspec/` 的 README 规则可由上述命令直接检查；本映射不保存执行或通过状态。本 change 只做文件名存在检查，不读取 README 内容、不重建 README、不重构文档树、不改主规格。若未来生成 README，第二、三条会失败。

### Requirement: 命名检查的作用边界

#### Scenario: 修改既有 capability 正文

- Test/check:
  - [ ] manual check (scratch clone): 在已有 HEAD 的临时克隆中只修改 `openspec/specs/procedure--repository-workflow/spec.md` 并 `git add`，运行 `githooks/pre-commit`，期望 exit 0；`git diff --cached --find-renames --name-only --diff-filter=A` 不含该路径
  - [ ] manual check (scratch clone): 对既有主规格执行 `git mv openspec/specs/<cap>/spec.md openspec/specs/<new-cap>/spec.md` 并暂存，另把 `openspec/changes/archive/<old>/specs/<cap>/spec.md` 暂存，分别运行 `githooks/pre-commit`，期望 exit 0
- Assertion scope: hook 只读 `--diff-filter=A` 的新增路径；已存在主规格的正文修改记为 M，不进入命名检查；`git mv` 改名记为 R，archive 路径在 hook 开头的 `case` 中直接 `continue`，两类都自动放行。manual check 直接观察 hook 退出码与暂存 diff 过滤结果，证明修改/改名/存档不被强制迁移或改名。
- Coverage note: 该分支需要 HEAD 基线才能让修改呈 M 状态；为避免测试执行真实 commit，本项用 scratch clone manual check，不写入 `test/test_anvil_workflow_safety.py`。`git mv` 与 archive 的 manual check 只验证放行，不改本仓库历史。

#### Scenario: 旧 capability 的第一次改动

- Test/check:
  - [ ] manual check (scratch clone): 在 HEAD 已有 `openspec/specs/<cap>/spec.md` 的临时克隆中新增 `openspec/changes/<change>/specs/<cap>/spec.md` 并 `git add`，运行 `githooks/pre-commit`，期望 exit 0；同时 `git cat-file -e HEAD:openspec/specs/<cap>/spec.md` 成功
- Assertion scope: delta 文件在暂存区是 A，但 hook 用 `git cat-file -e HEAD:openspec/specs/<cap>/spec.md` 判断既有主规格；HEAD 中存在时 continue，不要求补前缀。manual check 同时核对 HEAD 对象存在与 hook 放行，证明“delta 文件新增不等于 capability 新增”。
- Coverage note: 该分支同样需要 HEAD 基线；本项用 scratch clone manual check，不执行真实 commit。没有自动化用例，因为构造 HEAD 需要 commit，而本步禁止真实 commit。

### Requirement: PR 正文栏目

#### Scenario: 只填了计划栏

- Test/check:
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_plan_only_is_not_delivery
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_plan_items_do_not_satisfy_empty_delivery
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_bare_plan_heading_stops_delivery
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_empty_column_with_wu_is_allowed
- Assertion scope: 前三条都直接调用 `check_pr.validate_body`。第一条只有 `### 下一步计划 | Coming Up` 的真实条目，`assert_invalid` 断言 errors 非空；第二条在 `### 新增内容` 只有 `- 无` 时，计划栏的真实条目仍不能让正文通过；第三条没有 `###` 的 bare plan heading 会终止交付栏识别，后续计划栏不产生交付。第四条在交付栏写 `- 无`、另一交付栏有真实条目时 `assert_valid`，即空栏可写 `- 无`。断言的是 errors 空/非空，不读源码字符串。
- Coverage note: 没有断言具体错误文案；只证明校验函数拒绝计划栏替代交付。运行结果不写入本计划。

#### Scenario: 全为占位或注释

- Test/check:
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_comment_only_body_fails
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_commented_items_do_not_satisfy_a_column
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_fenced_items_do_not_satisfy_a_column
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_fenced_copy_of_a_whole_pr_fails
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_placeholder_items_are_rejected
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_only_wu_in_every_column_fails
- Assertion scope: 逐项调用 `validate_body` 并断言 errors 非空：整段 HTML 注释正文；注释掉的 bullet；围栏代码块中的 bullet；整段围栏的 PR 副本；`-`、`- ...`、`- TODO`、`- 待填写`、`- <在此填写>`、`- 无`、`- （请填写）` 等占位 bullet；每栏都只有 `- 无`。这些是占位/注释/围栏内容不计为交付条目的可观察结果。
- Coverage note: 占位 bullet 集合是测试参数化的子集，不是所有可能占位词的穷举；断言只到 errors 非空，不逐条核对错误原因。

#### Scenario: 旧栏目过渡

- Test/check:
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_new_only_is_valid
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_fix_only_is_valid
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_both_columns_are_valid
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_heading_styles_and_pipe_spacing
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_new_or_fix_needs_no_suffix
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_node_pr_four_columns
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_missing_verification_is_valid
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_optional_verification_with_only_code_block_is_valid
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_optional_verification_with_only_html_comment_is_valid
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_optional_verification_placeholder_is_not_required
- Assertion scope: `## NEW | 新增内容`、`## FIX | 修复漏洞`、两者并存均通过；`NEW|新增内容`、`### NEW|...`、无 `##` 前缀等旧式标题与空格变体通过；`NEW`/`FIX` 标题无后缀也通过；四栏 `### 新增内容 | WHAT'S NEW` 等新格式通过。缺验证段仍通过；验证段只有代码块、只有 HTML 注释、或只写“待填写”占位也都通过，证明验证方式与通过率是可选的，不参与交付条目判定。旧栏目被识别，新四栏也被接受。
- Coverage note: 没有断言“新写 PR 必须使用四栏”的强制拒绝；校验器对旧栏目保持兼容，这是规格的过渡语义，不把兼容等同于强制。`validate_body` 只接收正文，不读取 PR 标题，因此“标题是自然描述、不强制 conventional 前缀”不由这些用例证明；标题形式在“未实现的自动检查不得声称”下按人工检查处理。

### Requirement: 校验实现与其边界

#### Scenario: 未实现的自动检查不得声称

- Test/check:
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_event_metadata_with_quotes_and_backticks_stays_data
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_body_file_option_validates_local_pr_body
  - [X] scripts/ci/tests/test_check_pr.py::ValidateBodyTests::test_checker_does_not_eval_or_shell_out
  - [X] test/test_anvil_workflow_safety.py::test_check_pr_does_not_execute_body_sentinel
  - [ ] manual check: 用结构合规但内容虚构的 `--body-file` 运行 `python scripts/ci/check_pr.py --body-file <临时文件>`，期望 exit 0；再对照 `githooks/commit-msg`、`githooks/pre-commit`、`scripts/ci/check_pr.py` 与 `.github/workflows/pr-format.yml`，确认自动化只有提交信息条目格式、暂存区新增 capability 前缀、PR 正文栏目与条目三项；并核对工作流先取被审提交基线的脚本、首次接入使用固定 SHA
- Assertion scope: 第一条实际断言是：event JSON 正文含 `__import__("os").system(...)` 等代码样文本时，`check_pr.main(["--event", path])` 返回 0 且 stdout 含“通过”；它只证明校验器接受该文本并退出 0，没有观察 payload 是否被执行，不能证明“未求值”。第二条断言合法 `--body-file` 通过（exit 0）、占位正文失败（exit 1）。第三条是**源码 token 扫描**，只断言 `check_pr.py` 当前源码不含 `eval(`、`exec(`、`subprocess`、`os.system(`、`shell=True`、`pickle`，不是行为证据。拟补 sentinel 用例写入含 `__import__("pathlib").Path(<sentinel>).write_text("pwned")` 的结构合规正文，调用 `check_pr.main(["--body-file", ...])`，断言 exit 0、stdout 含“通过”、且 sentinel 文件不存在；这是“正文未被求值”的真实行为断言，本步保持 `[ ]`。manual check 用虚构条目证明校验只覆盖栏目/条目，不校验中文真实性；hooks 分别覆盖提交信息格式与新增 capability 前缀；CI 只调用 `check_pr.py --event`，并先取基线脚本、首次接入用固定 SHA。标题的自然描述与“不强制 conventional 前缀”由人工评审，不由 `check_pr.py` 校验；检查范围不把“标题是否合规”“中文是否真实”说成已自动校验。
- Coverage note: 第一、三条 `[X]` 只覆盖实际断言的退出码/输出与源码 token；**“不执行正文”这个 THEN 在既有 `[X]` 中没有行为 oracle**；apply 已创建的 `test_check_pr_does_not_execute_body_sentinel` 的真实 sentinel 断言覆盖；该行按已实现用例标 `[X]`。源码 token 扫描不能冒充行为验证；manual check 也只能核对当前实现与文案。“不得声称”是文档/评审约束，没有自动 oracle。命令只读临时 body 文件，不执行正文内容。

### Requirement: 规范独立与问题登记

#### Scenario: 问题登记区分状态

- Test/check:
  - [ ] manual check: 抽查 `../FuxiYu_Global/QUESTIONS.md` 的条目状态，确认按「受控本地复现（复现）/ 源码确认 / 待外部验证（待验证）/ 已修复」四类区分，且未把「已复现」写成「已修复」；同时通读本仓库主规格，确认正文自足、不要求读取已退役的 Global 规范文件
- Assertion scope: 检查范围是 Global 问题登记文件中条目的状态文字与上下文，确认四类状态被区分；Global 文件当前使用的证据等级标签是「受控本地复现 / 源码确认 / 待外部验证」，另以「已修复」表示修复状态，本检查按语义对应规格的「复现 / 源码确认 / 待验证 / 已修复」，不要求逐字相同。规范条款满足不作为业务缺陷已修复的证据。检查不改变任何问题状态，也不读取生产数据库。主规格通读只确认它不依赖已退役 Global 规范即可执行；Global QUESTIONS 仅作为问题登记入口。
- Coverage note: 这是登记流程与规范独立性的 manual check，没有自动化对象；不能由一个测试穷举未来条目。`已复现` 与 `已修复` 的边界需要读条目上下文，不能仅凭关键词计数。

### Requirement: 规范入口不使用代理说明文件

#### Scenario: 生成代理说明文件

- Test/check:
  - [ ] manual check: `git ls-files | Select-String -Pattern '(^|/)AGENTS?\.md$'`，并用 `Get-ChildItem -Recurse -Force -File -Include AGENT.md,AGENTS.md` 搜索工作区；若外部工具生成，移除文件并从暂存区排除，适用规范整理到本仓库 OpenSpec
- Assertion scope: 当前索引与工作区都没有 `AGENT.md` / `AGENTS.md`；检查范围是当前仓库工作树与索引，不把“工具不会生成”写成已被 hook 自动拒绝。规格要求的是维护与评审落实，本项不声称有自动钩子。
- Coverage note: 生成动作由外部工具触发，无法用一个测试证明未来不会生成；manual check 只守住当前不存在/未被跟踪，并给出生成后的处理步骤。

## procedure--testing-safety

### Requirement: 默认安全命令与隔离边界

#### Scenario: 安全默认命令

- Test/check:
  - [X] test/test_testing_safety_contract.py::test_default_safe_collection_excludes_legacy_tests
  - [X] test/test_testing_safety_contract.py::test_safe_test_config_uses_isolated_database
  - [X] test/test_anvil_workflow_safety.py::test_default_suite_deselects_integration_and_legacy_probes
  - [X] test/test_anvil_workflow_safety.py::test_safe_config_uses_exact_in_memory_sqlite
- Assertion scope: 第一条断言 `pytest.ini` 文本含 `addopts = -m "not integration and not legacy"`；第二条断言 `TEST_CONFIG_OVERRIDES["SQLALCHEMY_DATABASE_URI"]` 以 `sqlite://` 开头。拟补第一条 `test_default_suite_deselects_integration_and_legacy_probes` 在 `tmp_path` 写三个只导入 pytest、不导入应用的探针（integration marker、legacy marker、无 marker），用子进程 `sys.executable -m pytest --collect-only -q -c <仓库 pytest.ini 绝对路径> <probe>` 收集；子进程环境只保留 `PATH`、`SYSTEMROOT`、`TEMP`/`TMP`、`HOME`、`PYTHONIOENCODING` 与指向 `tmp_path` 的 `PYTHONPATH`，不含 `MAIL_*` 或真实 `.env` 变量；`tmp_path/sitecustomize.py` 用 `socket.socket` 的子类覆盖 `connect`/`connect_ex` 使其抛 `AssertionError`，并让 `socket.create_connection` / `socket.getaddrinfo` 抛错，禁止 socket 出站。断言 integration/legacy 探针 exit 5 且测试名不被收集，无 marker 探针 exit 0 且被收集；socket 拦截若被触发则用例失败。拟补第二条断言常量与 `create_app(overrides=...)` 的 URI 精确为 `sqlite:///:memory:`。
- Coverage note: 现有两条是配置文本/常量检查，不证明真实收集；apply 已新增的探针只覆盖代表性 marker，不跑全仓 `--collect-only`。`pytest.ini` 登记的是 `addopts` 条目，不是完整 pytest 命令。探针在 `tmp_path`、不导入应用、子进程最小环境并禁 socket，避免把“安全收集”建立在继承的真实环境上。Requirement 正文的“默认套件可在生产服务仍运行时执行”是隔离设计约束（内存 SQLite、禁用后台任务、外部服务被拦截），没有单独的运行时并行测试；本计划不以该用例声称已做生产并行验证。

#### Scenario: 测试配置注入

- Test/check:
  - [X] test/test_safe_pytest_app.py::test_app_factory_testing_disables_background_tasks
  - [X] test/test_safe_pytest_app.py::test_app_fixture_uses_test_database
  - [X] test/test_testing_safety_contract.py::test_safe_test_config_disables_background_tasks
  - [X] test/test_anvil_workflow_safety.py::test_create_app_overrides_clear_mysql_engine_options_and_ignore_flask_config
- Assertion scope: 第一条 `create_app(overrides=TEST_CONFIG_OVERRIDES)` 后断言 `app.state.config.TESTING is True`、`DISABLE_BACKGROUND_TASKS is True`；第二条 app fixture 的 `SQLALCHEMY_DATABASE_URI` 以 `sqlite://` 开头；第三条断言常量中两者为 True。拟补用例设置一个假的 `FLASK_CONFIG` 环境变量后仍用 `overrides` 创建 app，断言 URI 以 `sqlite://` 开头、`SQLALCHEMY_ENGINE_OPTIONS == {}`（清除 MySQL `init_command`），即 overrides 不靠 `FLASK_CONFIG`。
- Coverage note: `test_no_tests_call_create_app_without_testing_config` 是 `read_text` 文本检查，不计为行为证明；apply 已新增的用例直接读 `app.state.config`。`create_app` 会初始化 DB 与日志，用例沿用现有 app 测试的隔离环境，不改真实 `.env`，也不读取其中密钥值。

#### Scenario: 非 SQLite 隔离被拒

- Test/check:
  - [X] test/test_anvil_workflow_safety.py::test_assert_sqlite_database_uri_rejects_non_sqlite
- Assertion scope: 直接调用 `test/conftest.py` 的 `_assert_sqlite_database_uri`，传入 `config={"SQLALCHEMY_DATABASE_URI": "mysql+pymysql://..."}` 的假 app，断言抛 `RuntimeError` 且消息含 `Refusing to run tests against non-SQLite database URI` 与原 URI；传入以 `sqlite://` 开头的 URI 时不抛。该调用不连接任何数据库。
- Coverage note: apply 已新增反向用例；`test_app_fixture_uses_test_database` 只证正向 SQLite。apply 已新增的用例用假 URI，不读真实 MySQL/开发库，也不打印凭据。`test/conftest.py` 的 `app` 与 `db_session` fixture 都调用 `_assert_sqlite_database_uri`，直接测 helper 即覆盖这两个夹具共用守卫的行为；不构造真实非 SQLite 应用。

### Requirement: 安全套件不得触达真实外部资源

#### Scenario: 真实 HTTP 被拦截

- Test/check:
  - [X] test/test_testing_safety_contract.py::test_real_network_is_blocked_by_default
  - [X] test/container/test_container_common.py::test_default_container_tests_do_not_call_requests_post
  - [X] test/test_anvil_workflow_safety.py::test_pinned_adapter_http_path_is_blocked_before_network
- Assertion scope: 第一条在安全套件中调用 `requests.post("http://127.0.0.1")`，断言抛 `AssertionError` 且消息匹配 `Real HTTP requests are blocked`；第二条经真实门户 `node_comms.send("http://127.0.0.1", ...)` 同样抛该断言（`send` 只捕 `requests.RequestException`，不会吞 `AssertionError`）。拟补用例用临时 dummy pin 文件调用 `transport._post_node_json(..., verify=<pin>)`，走 `requests.Session().mount(_PinnedNodeAdapter)` + `.post` 的自定义适配器路径，在 `Session.request` 处抛同一断言；不发出网络请求。
- Coverage note: 现有覆盖 `requests.post` 与无 pin 的门户路径，未覆盖带自定义适配器的 Session 路径；apply 已新增用例补齐；该用例不写 `import requests` 字面量，避免触发既有 `read_text` 文本契约，但仍经过 conftest 的 `Session.request` 守卫。Requirement 正文的“真实 Node、真实 Docker、后台调度器、私网资源”中，Node 出站走同一 HTTP 守卫；调度器由 `DISABLE_BACKGROUND_TASKS` 关闭（见“测试配置注入”）；本仓库默认套件不直接调用 Docker 守护进程，容器执行在 Node 侧并经被 mock 的 `node_comms` 访问；私网出站同受 `Session.request` 拦截。本计划不声称已单独为 Docker/调度器造故障注入。

#### Scenario: 真实 SMTP 被拦截

- Test/check:
  - [X] test/test_testing_safety_contract.py::test_real_smtp_is_blocked_by_default
  - [X] test/test_anvil_workflow_safety.py::test_real_smtp_ssl_is_blocked_by_default
  - [X] test/test_anvil_workflow_safety.py::test_mail_send_uses_local_success_stub_without_smtp
  - [X] test/test_anvil_workflow_safety.py::test_mail_send_batch_uses_local_success_stub_without_smtp
- Assertion scope: 现有用例调用 `smtplib.SMTP("localhost")`，断言抛 `AssertionError` 且消息匹配 `Real SMTP`。拟补第一条调用 `smtplib.SMTP_SSL("localhost")`，断言抛消息匹配 `Real SMTP_SSL` 的断言；拟补第二条直接调用 `utils.mail.send(...)`，断言返回 `ok is True`、`mode == "pytest-mock"`、收件人列表正确，且没有构造真实 SMTP（conftest 的 `_send_smtp` 替身）；拟补第三条调用 `utils.mail.send_batch([...])`，断言每条结果 `ok is True`、`mode == "pytest-mock"`、收件人列表正确，并写入本地审计，不构造真实 SMTP（conftest 的 `_send_batch_smtp` 替身）。
- Coverage note: 现有只覆盖 SMTP；apply 已新增 SMTP_SSL 与邮件发送/批量发送替身用例。`mode` 字段是测试替身标识，不据此声称依赖 pytest-mock 库。

#### Scenario: 集成用例豁免替身

- Test/check:
  - [X] test/test_anvil_workflow_safety.py::test_integration_marker_bypasses_external_stubs
- Assertion scope: 用例自身标 `@pytest.mark.integration`，只在 `pytest -m integration` 下运行；不显式请求 `app` / `db_session`；autouse fixture 仍会创建临时测试 SQLite，不触真实数据库或网络。autouse 的 `mock_external_services` 在 integration marker 下直接走豁免分支；用例只通过 `importlib.import_module("requests")` 取模块，断言 `requests.sessions.Session.request` 仍是原始函数、`smtplib.SMTP` 仍是原始类，未被 conftest 替身替换。用例不调用 `mock_external_services.__wrapped__`，避免未推进生成器造成假证据。
- Coverage note: 该用例用 `importlib.import_module("requests")` 取模块，避免在非模块级豁免文件里写 `import requests` 触发既有 `read_text` 文本契约；默认安全套件按 marker 排除它，这本身就是被验证的行为。观察它需要显式 `pytest -m integration`；它不显式请求 `app`/`db_session`；autouse 的临时测试 SQLite 仍会运行，不触真实数据库或网络。

### Requirement: integration 与 legacy 的选择

#### Scenario: 默认不收集集成用例

- Test/check:
  - [X] test/test_testing_safety_contract.py::test_pytest_markers_are_registered
  - [X] test/test_testing_safety_contract.py::test_integration_tests_are_not_selected_by_safe_command
  - [X] test/test_testing_safety_contract.py::test_default_safe_collection_excludes_legacy_tests
  - [X] test/test_anvil_workflow_safety.py::test_default_suite_deselects_integration_and_legacy_probes
- Assertion scope: 第一条遍历 `pytest.ini` 文本，断言 `unit:`、`api:`、`db:`、`e2e:`、`integration:`、`legacy:` 六个 marker 都登记；第二条断言 `test/test_mail.py` 有模块级 `pytestmark = pytest.mark.integration`（`_module_has_pytestmark` 确实用 `ast.parse` 读取赋值，不是简单字符串匹配）；第三条断言 `pytest.ini` 的默认 `addopts` 含相同 marker 表达式。拟补探针同“安全默认命令”的规划项：`tmp_path` 临时模块级 `pytestmark = pytest.mark.integration`，子进程最小环境、`sitecustomize` 禁 socket，在 `-c pytest.ini` 下执行 `--collect-only`，断言退出 5 且测试名不被收集。
- Coverage note: 现有三条是 marker 登记/配置检查，不是实际收集；apply 已新增的探针只覆盖一个代表性 integration 模块，不跑全仓收集。`pytest -m integration` 只在环境被有意准备时显式运行，这是操作步骤，不由默认套件测试证明；本计划不执行需要真实外部服务的 integration 用例。

#### Scenario: legacy 仅防止误收集

- Test/check:
  - [X] test/test_testing_safety_contract.py::test_legacy_tests_are_removed
  - [X] test/test_testing_safety_contract.py::test_no_new_unmarked_legacy_style_tests
  - [X] test/test_testing_safety_contract.py::test_pytest_markers_are_registered
  - [X] test/test_anvil_workflow_safety.py::test_default_suite_deselects_integration_and_legacy_probes
  - [ ] manual check: `Get-ChildItem test -Recurse -File -Include *.py | Where-Object { $_.Name -ne 'test_anvil_workflow_safety.py' } | Select-String -Pattern 'pytest\.mark\.legacy'`，期望无匹配；`legacy` 只作为 `pytest.ini` 的收集排除 marker，探针文件中的 marker 只写入临时探针，不作为受维护契约
- Assertion scope: 第一条断言六个旧文件路径都不存在；第二条断言除旧名外的根级 `test_*.py` 不以 `_sql.py` 结尾；第三条断言 `pytest.ini` 登记六类 marker（含 `legacy`）。拟补探针同“安全默认命令”的规划项：`tmp_path` 临时模块级 `pytestmark = pytest.mark.legacy`，子进程最小环境、`sitecustomize` 禁 socket，在默认配置下执行 `--collect-only`，断言退出 5 且测试名不被收集，证明 legacy marker 使残留文件不被默认收集。manual check 排除探针文件本身后扫描 `test/`，确认没有其它测试把 `legacy` 当第二套契约使用。
- Coverage note: “不得据此把旧测试当作受维护契约”是评审/流程约束，测试只能守住删除与不收集两个机械面；manual check 也只证明当前 `test/` 没有 `pytest.mark.legacy` 使用，不证明未来不会有人添加。探针使用临时文件，不把旧测试留在工作区。

### Requirement: factory 与 mock 职责

#### Scenario: 常规测试优先复用 factory

- Test/check:
  - [X] test/test_testing_platform.py::test_user_factory_creates_unique_users
  - [X] test/test_testing_platform.py::test_container_factory_creates_root_binding_by_default
  - [X] test/repository/test_authentications_repo.py::test_auth_repo_create_validate_delete_token
- Assertion scope: 第一条连续 `create_user()`，断言两个用户的 username 与 email 不同；第二条 `create_container_graph()` 后读绑定，断言 `user_id == root.id` 且 role 为 `ROOT`。第三条是真实业务 repository 测试：用 `create_user()` 建用户，再创建 token、验证有效、删除、验证失效，证明常规测试确实复用了 factory 构造 ORM 数据。
- Coverage note: “优先复用”是使用/评审约定，不是可由单个测试穷举的全称命题；直接构造仍被下一条 Scenario 允许。上述是代表性证据，不证明每个业务测试都使用 factory。

#### Scenario: 约束与隔离 fixture 可直接构造

- Test/check:
  - [X] test/user/test_rbac_api.py::test_update_rbac_group_entities_replaces_user_group_permissions
  - [X] test/test_anvil_workflow_safety.py::test_ensure_auth_users_builds_rows_on_test_sqlite
- Assertion scope: 现有用例所在模块挂 `usefixtures("ensure_auth_users")`；该 fixture 在 `test/conftest.py` 中直接 `User(id=1, ...)` / `User(id=7, ...)`，用例随后经 API 修改 user 组实体并断言 200、响应集合与落库绑定，证明直接构造的固定用户确实可用。拟补用例显式接收 `ensure_auth_users`，断言 `db_session.get(User, 1)` / `7` 的用户名符合 fixture 写入值，且 `str(db_session.get_bind().url)` 以 `sqlite://` 开头，证明直接构造只落在测试 SQLite。
- Coverage note: 现有用例只间接依赖 fixture，没有直接断言 `User(...)` 的行；apply 已新增用例直接取证。“只作用于测试 SQLite”还依赖 `_assert_sqlite_database_uri`（见“非 SQLite 隔离被拒”），该用例读 session bind URL 作为补充。

#### Scenario: 在真实调用位置打桩

- Test/check:
  - [X] test/test_testing_platform.py::test_mock_node_response_records_calls
  - [X] test/test_testing_platform.py::test_mock_mail_success_records_recipient_subject_content
  - [X] test/container/test_container_api_lifecycle.py::test_create_container_without_owner_creates_for_self
  - [X] test/repository/test_authentications_repo.py::test_auth_repo_create_validate_delete_token
  - [X] test/operation_log/test_mail_audit.py::test_single_mail_audits_result_once_without_body_or_config
  - [X] test/utils/test_mail.py::test_batch_reuses_connection_and_audits_groups
- Assertion scope: 第一条把 `node_comms.send` 打在模块对象上，调用后断言返回值与记录到的 args；第二条把 `container_cleanup_task.send_mail` 打在模块对象上，调用后断言返回 `ok is True` 且记录到的 `to`/`subject` 参数；第三条经 API 创建容器，断言 200 且捕获的 service kwarg `owner_user_id == 1`；第四条断言 repository 最终 SQLite 状态（token 有效、删除成功、再验证失效）；第五条把 `mail._send_smtp` 打在模块对象上，断言结果、仅一次调用、`OperationLog` 成功/字段，以及正文、密码、附件等私有值不出现在审计 detail；第六条把 `mail.smtplib.SMTP` 换成 `_MixedSMTP`，断言只建一个连接、逐封尝试、结果 `[True, False, True]`、两条审计分组及计数/错误原因。
- Coverage note: 这是任务/API/repository 三种观察面的代表性证据，不是每条业务测试都按同一形状断言；Scenario 正文描述的是职责分工，无法由单个测试穷举“所有测试”。共享 mock 辅助位于 `test/mocks.py`，`test/test_testing_platform.py` 直接 `from . import mocks` 使用；上列用例的 monkeypatch 目标就是被测代码实际调用位置的模块对象（`node_comms.send`、`container_cleanup_task.send_mail`、`mail._send_smtp`、`mail.smtplib.SMTP`）。

#### Scenario: 隔离验证可触发被拦截入口

- Test/check:
  - [X] test/test_testing_safety_contract.py::test_real_network_is_blocked_by_default
  - [X] test/test_testing_safety_contract.py::test_real_smtp_is_blocked_by_default
  - [X] test/test_testing_safety_contract.py::test_no_tests_import_requests_without_integration_marker
- Assertion scope: 前两条就是规格点名的 `test_real_network_is_blocked_by_default` 与 `test_real_smtp_is_blocked_by_default`，分别断言 HTTP 与 SMTP 被拦截；第三条遍历 `test/**/test_*.py`，跳过 `test_testing_safety_contract.py` 本身与模块级 integration 文件，用 `read_text` 子串检查断言其它文件不含 `import requests` / `from requests` 文本。两条触发入口在该豁免文件内，`read_text` 文本契约对其它常规业务测试仍生效。
- Coverage note: 第三条是 `read_text` 文本契约检查，不是 AST 分析、也不是运行时保证；它正是规格所述的“非 integration 测试不得 import requests”文本契约。SMTP_SSL 与自定义适配器的触发分支分别在“真实 SMTP 被拦截”“真实 HTTP 被拦截”下另列。

### Requirement: 已删除的旧测试文件与替换覆盖

#### Scenario: 旧测试删除名单与替换覆盖

- Test/check:
  - [X] test/test_testing_safety_contract.py::test_legacy_tests_are_removed
  - [X] test/test_testing_safety_contract.py::test_integration_tests_are_not_selected_by_safe_command
  - [X] test/utils/test_mail.py::test_mail_send_success_with_mock_smtp
  - [X] test/user/test_user_api_auth.py::test_register_success
  - [X] test/user/test_user_tasks_profile.py::test_register_success
  - [X] test/machine/test_machine_api_permission.py::test_add_machine_permission_success
  - [X] test/machine/test_machine_tasks_crud.py::test_register_machine_persists_identity_hardware_and_limits
  - [X] test/container/test_container_api_lifecycle.py::test_create_container_api_success
  - [X] test/container/test_container_cleanup_task.py::test_cleanup_expired_containers_skips_long_term
  - [X] test/test_anvil_workflow_safety.py::test_legacy_replacement_paths_exist
- Assertion scope: 第一条断言六个旧文件路径都不存在；第二条断言 `test/test_mail.py` 有模块级 integration marker。邮件替换用例用假 SMTP 断言发送成功且收件人正确；用户 API 替换用例断言注册 201 与 `success == 1`；用户任务替换用例断言注册成功、用户落库、密码哈希不等于明文；机器 API 替换用例断言授权接口 200；机器任务替换用例断言注册结果、机器行字段与硬件返回值；容器 API 替换用例断言创建 200 与 `success == 1`；容器清理替换用例断言长期容器不被删除。拟补用例断言规格列出的每个替换路径存在且含至少一个 `def test_`，不重跑这些用例。
- Coverage note: 行为覆盖用每个替换族的代表用例取证，不是逐文件等价性证明；apply 已新增的存在性用例覆盖规格的 bullet 路径清单，不声称行为等价。部分替换文件（如 repository integration）可能依赖更多夹具，本计划只对其做存在性检查。旧测试中仍可能触达真实 Node / 真实 SMTP / 非 SQLite 数据库的路径：六文件已删除，`test/test_mail.py` 留在 integration；`test/integration/` 下的真实服务用例不属于默认安全套件。上述边界按现有目录与 marker 事实陈述，不另造真实外部调用。

#### Scenario: 旧测试文件不得复活

- Test/check:
  - [X] test/test_testing_safety_contract.py::test_legacy_tests_are_removed
  - [X] test/test_testing_safety_contract.py::test_no_new_unmarked_legacy_style_tests
- Assertion scope: 第一条断言六个旧文件路径都不存在；第二条遍历根级 `test/test_*.py`，跳过旧文件名后断言没有文件以 `_sql.py` 结尾。旧名重新出现由第一条抓住，新的根级 `*_sql.py` 由第二条抓住。
- Coverage note: 第二条只覆盖 `_sql.py` 后缀与旧六名，不覆盖其它“旧式”命名；规格的“同名或 `*_sql.py` 形态”按这两条实现取证。

#### Scenario: 替换覆盖存在

- Test/check:
  - [X] test/utils/test_mail.py::test_mail_send_success_with_mock_smtp
  - [X] test/user/test_user_api_auth.py::test_register_success
  - [X] test/machine/test_machine_api_permission.py::test_add_machine_permission_success
  - [X] test/container/test_container_api_lifecycle.py::test_create_container_api_success
  - [X] test/test_anvil_workflow_safety.py::test_legacy_replacement_paths_exist
- Assertion scope: 现有用例分别在 `test/utils/`、`test/user/`、`test/machine/`、`test/container/` 分类目录中真实运行，证明等价覆盖落在分类目录而不是恢复旧文件；拟补用例断言规格列出的每个替换路径存在且含测试函数，覆盖“查找位置”的完整清单。
- Coverage note: 现有四条是分类目录的代表性行为证据，不是全部替换文件的穷举；apply 已新增的存在性用例只证明文件存在，不证明每个旧行为的等价性。

### Requirement: 邮件集成测试的真实标记

#### Scenario: 缺少真实配置则跳过

- Test/check:
  - [ ] manual check (未验证，不执行): 当前仓库不运行 `test/test_mail.py` 的 integration 邮件用例。包导入时 `__init__.py` 会 `load_dotenv(_DOTENV_PATH, override=True)` 读取仓库根 `.env`；`test/test_mail.py` 在导入后读取四个 `MAIL_*` 环境变量；`test/conftest.py` 又对 integration 用例跳过 HTTP/SMTP 替身。仅在外层清空四个变量不能保证导入后仍缺失，`.env` 可能补回，存在进入 `send` 并尝试真实 SMTP 的风险。只有同时满足“临时无 `.env` 副本/临时克隆 + 子进程清除四个变量 + `sitecustomize` 拦截 socket 出站”才可执行；本计划不执行，skip 分支保持未验证
- Assertion scope: 未验证：不声称“1 skipped、exit 0、零连接”。`test/test_mail.py` 的 `test_send_mail_integration` 从 `os.getenv` 读四个变量，并在 `if not all([...])` 时 `pytest.skip(...)`，但本计划没有该分支的行为证据。检查范围是风险边界：不读取真实 `.env`/凭据、不触真实 SMTP、不在当前仓库运行 integration 邮件测试。
- Coverage note: skip 分支未验证；源码里的 skip 条件不能当作执行证据。若未来要验证，必须在无 `.env` 的临时副本中清除四个变量并用 socket 出站拦截，观察 skip 且零连接；本步不执行、不声称通过。manual check 也不覆盖“四个变量中只缺一个”的逐项矩阵。

#### Scenario: 安全套件用桩 SMTP

- Test/check:
  - [X] test/utils/test_mail.py::test_mail_send_success_with_mock_smtp
  - [X] test/utils/test_mail.py::test_batch_reuses_connection_and_audits_groups
  - [X] test/test_testing_platform.py::test_mock_mail_success_records_recipient_subject_content
- Assertion scope: 第一条把 `mail.smtplib.SMTP` 换成 `_SMTP`，调用 `mail.send` 后断言 `ok is True` 且收件人为目标地址；第二条把 `mail.smtplib.SMTP` 换成 `_MixedSMTP`，断言只建一个连接、逐封尝试、结果 `[True, False, True]`、两条审计分组与计数/错误原因；第三条把 `container_cleanup_task.send_mail` 打在模块对象上，断言调用参数与返回值。三条都不构造真实 `smtplib.SMTP`。
- Coverage note: 这些用例通过 `importlib.reload(mail)` 走真实 `mail.send` 路径并用假 SMTP 类替换，属于真实行为测试而非源码字符串检查；与 conftest 的 `_send_smtp` 替身是两条不同的隔离路径。

### Requirement: 规范入口不使用代理说明文件

#### Scenario: 生成代理说明文件

- Test/check:
  - [ ] manual check: `git ls-files | Select-String -Pattern '(^|/)AGENTS?\.md$'`，并用 `Get-ChildItem -Recurse -Force -File -Include AGENT.md,AGENTS.md` 搜索工作区；若外部工具生成，移除文件并从暂存区排除，适用规范整理到本仓库 OpenSpec
- Assertion scope: 当前索引与工作区都没有 `AGENT.md` / `AGENTS.md`；检查范围是当前仓库工作树与索引。规格要求由维护与评审落实，本项不声称现有 hook 会自动拒绝这些文件。
- Coverage note: 生成动作由外部工具触发，测试/命令只能守住当前不存在/未被跟踪；不能证明未来不会生成。与仓库工作流同名 Scenario 共用同一检查范围，但两个 capability 的规范入口都要各自保持。本 Scenario 还包含 `openspec/` 内不得放 README；父级 `d97d6a7` 已清理生成物，当前三仓 `openspec/` 的 README 文件名检查为 0，该规则已由仓库工作流“README 位置”的直接检查覆盖，不再有外部冲突。

#### Scenario: 不恢复旧文档

- Test/check:
  - [X] test/test_anvil_workflow_safety.py::test_retired_testing_docs_are_not_restored
- Assertion scope: 断言 `docs/testing.md`、`docs/testing_legacy_migration.md`、`test/README.md` 都不存在；同时确认 `openspec/specs/procedure--testing-safety/spec.md` 存在并作为当前权威入口。用例不读取已退役文档内容。
- Coverage note: 文件不存在可直接检查；“MUST NOT 声称已退役的 Global 文档仍然权威”是文档/评审约束，没有自动 oracle。现有 `test_legacy_tests_are_removed` 只覆盖六个根级旧测试文件，不覆盖这三个 docs/README 路径。
