# Archive Review

## Review Record

- Change: complete-anvil-announcement-test-mappings（归档于 `openspec/changes/archive/2026-10-28-complete-anvil-announcement-test-mappings/`）
- Reviewer: independent read-only re-reviewer（复审作者 30562a33 的归档/侧车收尾；未参与撰写，未复用作者上下文）
- Access: read-only；本文件是唯一写入
- Reviewed: 归档 `test-plan.md`、3 个 canonical main sidecar（`openspec/specs/backend--table-announcement-{drafts,templates,announcements}/test-plan.md`）、`test/announcement/test_anvil_announcement_mappings.py`（定向）、相关既有测试（定向）及 3 个 main spec
- 核对基准: 归档 test-plan 为 23 个 Scenario、9 个 Requirement、69 个 locator 行且全部 `[X]`；3 个 main sidecar 合计同为 69 行、23 Scenario、9 Requirement，逐 Scenario 的 locator 集合与归档 test-plan 完全一致；10 个新增测试函数均存在，全部 locator 可解析到现有 test 函数/参数，未发现 checkbox 与真实 locator 不一致。
- 重点核对: t05 实际以互异 `created_at` 建 205 条模板并断言默认 100/0、`total=205`、custom 过滤 `total=120`、显式/中间/末页逐 id 顺序切片；t03 实际比较删除前后公告标题/正文/目标/快照/计数/状态与草稿全字段，并比较投递日志行；a01 实际覆盖 `source_draft_id` 的 NULL 与赋值往返；a04 实际记录发送入口对纯文本/Markdown 的同一 renderer 调用及直接渲染对照，并保留“不能黑盒排除内部内容分支”的限制；a05 实际覆盖发送前、传输捕获点、发送后（草稿删除语义）与重发后的模板/公告字段快照及两次审计详情。新增测试与既有测试的断言归属按 Scenario 核对，未发现把新增断言记到既有测试或反向归属。
- 一致性: 3 个 main spec 的工作区 SHA-256 与 `HEAD` blob 一致；其 Requirement 块仍与归档 no-op MODIFIED delta 逐字一致。3 个 main sidecar 已转为当前时态，未保留“缺口/计划项/尚未创建”等旧状态，也没有 pass/fail、运行时间或结果 ledger；仍保留 SQLite/MySQL、真实 SMTP/客户端及 a04 内部不可黑盒观察等真实限制。归档 test-plan 按指示保留审批时的 Assertion scope 文本，仅重算 checkbox 为 `[X]`，未把运行结果写入 mapping。
- Invalidation scope: 任何对 Requirement、Scenario、test/check locator、Assertion scope 或 Coverage note 的语义修改，都会使本 verdict 失效。核对未变断言后重算 checkbox，或仅外部运行/日志变化，不会使其失效。
- Scope limit: 仅做归档 test-plan、canonical main sidecar 与真实测试的定向一致性审查；不重审实现、不执行 pytest、不写计划/sidecar/test/app/main spec，也不把测试运行结果写成 ledger。

## Findings

### Blocking

None.

### Non-blocking

None.

## Verdict

VERDICT: APPROVE
