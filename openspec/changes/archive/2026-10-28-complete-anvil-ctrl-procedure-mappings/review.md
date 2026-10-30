# Plan Review

## Review Record

- 变更：complete-anvil-ctrl-procedure-mappings
- 复审者：全新上下文的独立复审者（第二轮独立复审；未使用作者上下文）
- 访问：只读；仅写本文件
- 审查计划：proposal.md、specs/procedure--repository-workflow/spec.md、specs/procedure--testing-safety/spec.md、design.md、test-plan.md；现有主规格、源文件、钩子与测试仅作只读上下文
- 计数（已核）：2 个 capability；8 + 7 个 Requirement；16 + 19 = 35 个 Scenario；75 个 `[X]` = 68 个测试定位行（52 个不同定位）+ 6 条精确命令 + 1 个 README 人工检查；32 个 `[ ]` = 21 个拟补测试行（18 个不同测试名）+ 11 个人工检查。68 个 `[X]` 测试定位均可解析；6 条命令可复现；Ctrl/Node/Web 的 `openspec/` README 文件名枚举为空；两份 delta 的 Requirement 块与主规格逐字一致；邮件跳过分支 `[ ]` 且未执行；收集探针子进程最小环境并拦截 socket；sentinel 为 `[ ]`；integration 豁免用例不再驱动 `__wrapped__`；requests 导入契约写为 `read_text` 文本检查。
- 本轮 diff 复核：`test-plan.md:9` 的人工检查 `[X]` 已改为命令、期望与范围的映射确认；`test-plan.md:77-79` 已删除“本次已核对/当前通过”，README 范围只写期望为空、仅核对文件名、不读内容；`test-plan.md:225-226` 写明不显式请求 `app`/`db_session`，autouse 临时测试 SQLite 仍会运行，但不触真实数据库或网络；`test-plan.md:237/248` 的“同 S1”均改为“同‘安全默认命令’的规划项”；`design.md:80/92` 与上述一致。未发现定位、计数或 Requirement 变化。
- 失效范围：对 Requirement、Scenario、设计决定、场景映射、test/check locator、Assertion scope 或 Coverage note 的任何语义改动。仅在断言未变时重新计算复选框，或外部运行/日志变化，不使本审查失效。
- 范围限制：仅计划审查。实现、任务完成、测试执行与归档就绪不在范围内。

## Findings

### Blocking

无。

### Non-blocking

无。

## Verdict

VERDICT: APPROVE
