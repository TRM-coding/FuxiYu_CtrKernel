# Plan Review

## Review Record

- Change: async-mount-cleanup
- Reviewer: fresh-context reviewer（独立复审，未参与计划编写）
- Access: read-only; this file is the only write
- Reviewed plan: proposal.md、specs/backend--table-container-mount-cleanup/spec.md、specs/backend--table-deleted-container-restore-snapshot/spec.md、specs/backend--table-operation-logs/spec.md、design.md、test-plan.md
- Cross-repo read-only context: `FuxiYu_NodeKernel/network/api.py`、`FuxiYu_NodeKernel/openspec/changes/async-mount-cleanup/` 与 `FuxiYu_Web/openspec/changes/async-mount-cleanup/specs/frontend--page-deleted-containers/spec.md`，用于核对 Node 当前 HTTP 返回与 Web 列表字段。
- 复审焦点：状态查询 timeout/断线/5xx 的连续有限重试、`running` 重置计数、Node 任务缺失 `404 + error_reason=not_found` → `node_task_lost`、端点缺失 `404/405` → `node_unsupported`，以及任何路径不得误写成功。
- Invalidation scope: 任何对 requirement、scenario、design decision、scenario mapping、test/check locator、Assertion scope 或 Coverage note 的语义变更都会使本 verdict 失效；仅重新计算 checkbox 或外部运行/日志变化不失效。
- Scope limit: 仅审阅计划。实现、任务完成、测试执行与归档就绪不在范围内。

## Findings

### Blocking

None.

### Non-blocking

- `design.md:320-328` 与 `tasks.md:6` 的 `SAFE_REASON_CODES` 增加清单未列 `node_task_lost`，但 `specs/backend--table-container-mount-cleanup/spec.md:73`、`design.md:153,192` 和 `test-plan.md:87` 都以它作为稳定失败原因。当前实现已包含该值，但计划清单应补上（或注明它已存在），避免实现按清单收紧白名单时把任务丢失降级成其他原因。
- `design.md:193` 写“传输超时、连接失败、5xx 在启动阶段归未知”，而 Node 当前 `/start_clean_mount` 的 500 返回是 `{"success":0,"error_reason":"internal_error"}`（`FuxiYu_NodeKernel/network/api.py:721-724`）；Ctrl 当前实现会把带明确 `error_reason` 的启动 5xx 归为明确失败，而不是未知。建议把措辞区分为“有明确失败结构的 5xx 记失败，无法判定结构的 5xx 记未知”，并补相应断言。两种分类都不写成功，但会影响失败/未知日志语义。
- `test-plan.md:58-62` 的“受理不等待清理完成”用例明确说明它未用事件阻塞证明“响应早于 Node 启动”，只证明受理语义；而 `specs/backend--table-container-mount-cleanup/spec.md:48` 的 THEN 包含 MUST NOT 等待 Node 完成。建议补一个事件阻塞用例，或正式加 Coverage note 记录该时序断言缺口，避免把受理断言误当非阻塞语义已覆盖。

## Verdict

VERDICT: APPROVE
