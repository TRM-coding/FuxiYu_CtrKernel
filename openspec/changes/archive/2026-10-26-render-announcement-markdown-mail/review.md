# Plan Review

## Review Record

- Change: render-announcement-markdown-mail
- Schema/root: `anvil`；repo-local planning root `E:\AI\Fuxi\FuxiYu_CtrKernel`（`nearest`，由 `openspec status` 确认）
- Reviewer: 新一轮独立复审者（未参与该 change 的规划；本机 DeepSeek Harness 会话）
- Access: read-only；本次仅写 `openspec/changes/render-announcement-markdown-mail/review.md`
- Reviewed plan: 当前版本 `proposal.md`、`specs/backend--table-announcements/spec.md`、`design.md`、`test-plan.md`
- Read-only context: 主规格 `openspec/specs/backend--table-announcements/spec.md`、`services/announcement_tasks.py`、`utils/mail.py`、`test/announcement/test_services.py`、`test/utils/test_mail.py`、`test/announcement/conftest.py`、`test/conftest.py`；仅用于核对计划 locator 与行为可行性
- Invalidation scope: 任何对 Requirement、Scenario、设计决策、场景映射、测试定位、Assertion scope 或 Coverage note 的语义变更都会使本审查失效；在断言未变的情况下重算复选框，或仅外部运行与日志变化，不使本审查失效。
- Scope limit: 仅审查计划；实现、任务完成、测试执行和归档准备度均不在本次审查范围内。
- Review note: 本次复审覆盖修正后的当前计划，不审实现结果、tasks、verify 或归档。

## Findings

### Blocking

- None.

### Non-blocking

- `design.md:47` 与 `test-plan.md:79`：图片自定义渲染规则要求“转义后的 alt 文本”，但图片用例只使用普通 `alt`，未覆盖 alt 内含 HTML、`&` 或引号的情况；若渲染规则直接拼接 `token.content`，HTMLParser 用例仍可能通过而产出真实元素/属性。建议在 `test_render_suppresses_images_without_resource_requests` 增加一个带 HTML/引号 alt 的 https 图片，使用 HTMLParser 断言 alt 仅作为文本数据出现、无真实 `b`/`img` 元素或属性，并按需核对原始输出中的实体转义；不要求隐藏被拒绝图片语法中的可见 URL。

## Verdict

VERDICT: APPROVE
