# 仓库工作流程规范

## Purpose

本仓库自有的流程规范，覆盖提交信息、钩子启用与书写、能力命名、PR 正文四件事。它替代已退役的 Global 三篇流程规范（编码风格 / 规范命名 / PR 格式），并只保留其中仍然适用、且与本仓库既有做法一致的部分。本规范不依赖 Global 仓库即可执行；各仓库的同类规范彼此独立。规范只约束流程与文本：满足规范不代表业务缺陷已修复，也不代表代码行为已被验证。

## Requirements

### Requirement: 提交信息条目格式

提交信息 SHALL 由一或多条条目行组成，每行 MUST 形如 `- <关键字> <中文短句>`：连字符后必须有空格；关键字仅限 `NEW`（新增）/ `AMEND`（修改既有行为或结构）/ `FIX`（修复缺陷）三者之一，MUST NOT 自造；短语 SHALL 是一句自足的中文描述，脱开上下文也能读出改了什么。空行与 `#` 注释行 SHALL 跳过。提交信息 MUST NOT 出现工具署名尾注或生成标记。因合并产生的默认提交信息（存在 `MERGE_HEAD`）SHALL 豁免本格式。提交信息的关键字与 PR 正文的栏目是两套独立体系，MUST NOT 互相推导或复用。

#### Scenario: 合规提交

- **WHEN** 提交信息是一条或多条 `- NEW|AMEND|FIX 中文短句`
- **THEN** 通过；`-NEW` 这类连字符后缺空格、关键字自造拼写、以及整条没有任何条目行，均不通过

#### Scenario: 合并提交豁免

- **WHEN** 提交由 git 合并生成，使用默认合并信息
- **THEN** 不适用条目格式，不因此被拒

#### Scenario: 署名尾注被拒

- **WHEN** 正文含 co-authored-by、generated with 或机器人标记
- **THEN** 拒绝该提交，并列出命中行

### Requirement: 钩子启用与书写

每个克隆 SHALL 各做一次 `git config --local core.hooksPath githooks` 来启用仓库内钩子；执行前 SHALL 先检查现有配置与自定义钩子，确定保留或迁移方案后调整，MUST NOT 静默覆盖已有自定义入口；已有会话授权覆盖该调整时 SHALL NOT 重复索要确认。`core.hooksPath` 是替换而非叠加——设置后 `.git/hooks/` 完全不再被读，因此钩子 MUST 入库在本仓库的 `githooks/` 目录。新增或修改的 shell 钩子 SHALL 使用 LF 换行，并 SHALL 以可执行位（Git 模式 100755）登记；在不跟踪文件模式的平台上改完钩子 SHALL 显式补执行位。

#### Scenario: 目标克隆已有钩子配置

- **WHEN** 某克隆已设置 `core.hooksPath`，或 `.git/hooks/` 中已有手写钩子
- **THEN** 先核对保留或迁移方案，再按已有授权调整，不直接覆盖自定义入口

#### Scenario: 换行与可执行位

- **WHEN** 新增或修改 `githooks/` 下的脚本
- **THEN** 换行为 LF 且 `git ls-files -s` 对该文件显示 100755；否则其它克隆上会出现 Permission denied（exit 126）或钩子静默不执行

### Requirement: 能力命名与粒度

`openspec/specs/<capability>/` 以及变更内新增的 delta capability 目录 SHALL 取四类前缀之一、且只取一个：`standard--`（跨两端或不属于任何一端：提交信息、仓库布局、忽略规则、脚本与钩子的书写机制）、`frontend--`（客户端一侧）、`backend--`（服务端一侧）、`procedure--`（人怎么做事：原型流程、流水线、规格自身的撰写与命名）。MUST NOT 叠加两个前缀；判定看它落在哪一端，拿不准归 `standard--`。

粒度 SHALL 为：Ctrl 以数据表为单位；Node 以 8 个能力单元为单位，每个单元 SHALL 给出完整的类型契约；Web 以页面为单位（页面规格一律进 `frontend--`，即使其中夹带业务规则）。

仓库根 `README` SHALL 保留；`openspec/` 目录内 MUST NOT 放置 README。

#### Scenario: 叠加前缀被拒

- **WHEN** 新增 capability 形如 `backend--standard--xxx`
- **THEN** 拒绝，并指出不得叠加门类前缀

#### Scenario: 缺前缀被拒

- **WHEN** 新增 capability 目录没有四类前缀之一
- **THEN** 拒绝，并给出四类前缀的含义与合规范例

#### Scenario: README 位置

- **WHEN** 需要说明仓库用法
- **THEN** 写在仓库根 README；`openspec/` 内不放 README

### Requirement: 命名检查的作用边界

命名检查 SHALL 只作用于本次暂存区中状态为新增（A）的 capability 标记文件：主规格 `openspec/specs/<cap>/spec.md`，或变更内 `openspec/changes/<change>/specs/<cap>/spec.md`。既有 capability 的正文修改、`git mv` 改名，以及 `openspec/changes/archive/` 下的存档 SHALL 自动放行，MUST NOT 被强制迁移或改名。对既有 capability 的 delta SHALL 以「HEAD 中是否已存在对应主规格」为判据——delta 文件是新增不等于 capability 是新增，否则对旧 capability 的第一次改动也会被错误拦截。以文件而非目录作判据，是因为 git 不追踪空目录。

#### Scenario: 修改既有 capability 正文

- **WHEN** 只修改已存在的 `openspec/specs/<cap>/spec.md` 内容
- **THEN** 不触发命名检查（记为修改，不是新增）

#### Scenario: 旧 capability 的第一次改动

- **WHEN** 为一个尚无前缀的既有 capability 首次新增 delta
- **THEN** 因 HEAD 中已有对应主规格而放行，不要求补前缀；检查只约束新增 capability

### Requirement: PR 正文栏目

PR 正文 SHALL 使用四栏，标题照抄以下中英双语形式：

- `### 新增内容 | WHAT'S NEW`
- `### 漏洞修复 | Bug Fixes`
- `### 优化工作 | Enhancements & Patches`
- `### 下一步计划 | Coming Up`

前三栏为交付栏，其中 SHALL 至少有一栏包含至少一条真实条目；`下一步计划 | Coming Up` 是可选计划栏，其条目 MUST NOT 被计入交付；空栏可以删除，也可以写 `- 无`；验证方式与通过率可选。标题 SHALL 是本次改动的自然描述，MUST NOT 强制 conventional commit 前缀。HTML 注释、模板占位文字与代码块内容 MUST NOT 被计为交付条目。旧的 `NEW` / `FIX` 栏目 SHALL 仅作为接入期的过渡兼容保留，新 PR SHALL 使用四栏。

#### Scenario: 只填了计划栏

- **WHEN** 前三栏为空或只有占位文字，只有 `下一步计划` 有真实条目
- **THEN** 视为缺少交付，不通过

#### Scenario: 全为占位或注释

- **WHEN** 正文只有模板注释、代码块与占位符
- **THEN** 视为没有可校验内容或没有真实条目，不通过

#### Scenario: 旧栏目过渡

- **WHEN** 接入期沿用旧的 `NEW` / `FIX` 栏目
- **THEN** 仍被识别；新写的 PR 使用四栏

### Requirement: 校验实现与其边界

PR 正文校验 SHALL 以脚本消费事件 JSON 的方式执行，MUST NOT 执行正文内容（不 eval、不起 shell、不把正文当代码）。校验 SHALL 优先使用被审提交基线里的脚本；首次接入且基线尚无脚本时，SHALL 使用固定 SHA 的脚本。现有自动化 SHALL 只覆盖三件事：提交信息条目格式、暂存区新增 capability 的前缀、PR 正文的栏目与条目。MUST NOT 声称钩子或 CI 会校验中文表述的真实性、PR 标题的形式等尚未实现的检查；规范要求与人实际遵守之间的差距 SHALL 如实说明。

#### Scenario: 未实现的自动检查不得声称

- **WHEN** 描述本仓库的流程保障
- **THEN** 只说明上述三件已实现的自动检查；不得把「中文是否写得真实」「标题是否合规」说成已被自动校验

### Requirement: 规范独立与问题登记

各仓库的规范 SHALL 独立自足，不依赖已退役的 Global 规范文件即可执行；本仓库的流程规范以本文件为准。业务与流程问题 SHALL 统一登记在 Global `QUESTIONS.md`，并按「复现 / 源码确认 / 待验证 / 已修复」区分状态。规范条款的满足 SHALL NOT 作为业务缺陷已修复的证据。

#### Scenario: 问题登记区分状态

- **WHEN** 记录一个尚未定位或尚未验证的问题
- **THEN** 按上述四类之一标注状态，不把「已复现」写成「已修复」


### Requirement: 规范入口不使用代理说明文件

本仓库的流程规范 SHALL 维护在 OpenSpec 中，SHALL NOT 生成、保留或提交 AGENT.md、AGENTS.md。此规则由维护与评审落实，MUST NOT 声称现有 hook 会自动拒绝这些文件。

#### Scenario: 生成代理说明文件

- **WHEN** 工具在仓库中生成 AGENT.md 或 AGENTS.md
- **THEN** 移除该文件并从暂存区排除，适用规范整理到本仓库 OpenSpec

## Source references

- 提交信息检查：[`githooks/commit-msg`](../../../githooks/commit-msg)，第 37-39 行（合并豁免）、45-49 行（署名尾注）、63-80 行（条目格式与至少一条）。
- 能力命名检查：[`githooks/pre-commit`](../../../githooks/pre-commit)，第 47-52 行（只读暂存区新增、存档放行）、68-70 行（既有主规格放行）、82-99 行（前缀叠加与缺失）。
- PR 正文检查：[`scripts/ci/check_pr.py`](../../../scripts/ci/check_pr.py)，第 20-42 行（四栏与计划栏、旧栏目兼容）、228-279 行（正文校验）。
- PR 正文模板：[`.github/pull_request_template.md`](../../../.github/pull_request_template.md)。
- 工作流：[`.github/workflows/pr-format.yml`](../../../.github/workflows/pr-format.yml)，第 20-34 行（优先基线脚本与首次接入选择）、第 59 行（首次接入的固定 SHA）。
- 换行与文件模式：[`.gitattributes`](../../../.gitattributes)；Windows 上 `core.filemode=false`，需 `git update-index --chmod=+x` 显式补执行位。
- 问题登记：[Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。
