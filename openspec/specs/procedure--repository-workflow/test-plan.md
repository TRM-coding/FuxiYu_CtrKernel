# procedure--repository-workflow Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: 提交信息条目格式

#### Scenario: 合规提交

- Test/check:
  - [X] test/test_anvil_workflow_safety.py::test_commit_msg_accepts_only_well_formed_item_lines
- Assertion scope: 在临时 `git init` 目录中直接调用仓库 `githooks/commit-msg`，不执行 commit。五种合法关键字 `NEW`、`AMEND`、`FIX`、`SPEC`、`TEST` 的单条消息分别返回 0；同一合法消息夹带空行与 `#` 注释行时仍返回 0，证明这两类行被跳过；`-NEW 缺空格`、`- ADD 自造关键字`、小写关键字、缺少短句及只有空行或 `#` 注释的消息返回非 0，stderr 含“第 N 行不符合条目格式”或“至少需要一条实际变更”；失败行在 stderr 重复原文。命令路径与消息文件内容都由用例构造，不依赖当前仓库的暂存区。
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
