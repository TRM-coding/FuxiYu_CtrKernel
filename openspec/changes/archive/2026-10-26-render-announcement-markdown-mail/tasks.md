# Tasks

## 1. Markdown 渲染器

- [x] 1.1 在 `requirements.txt` 增加 `markdown-it-py>=4.0`，新增 `utils/announcement_markdown.py`：CommonMark、`html=False`、`breaks=True`、表格；解析期链接/图片共用 `http`/`https`/`mailto` 允许列表；有效图片 token 只在正文输出转义 alt；关键元素注入简单内联样式。验证：渲染含标题、表格、危险链接、有效/拒绝图片和 alt 含 HTML 的样例，确认无真实 `img`/`style`/`script` 元素。
- [x] 1.2 新增 `test/utils/test_announcement_markdown.py`，按计划 locator 使用 `HTMLParser` 覆盖基础结构、原始 HTML/代码转义、安全链接、图片/外部资源、历史纯文本单换行；在图片用例加入 alt 含 HTML/引号样例，断言 alt 仅作为文本数据出现。验证：`pytest test/utils/test_announcement_markdown.py -q` 通过；覆盖 `backend--table-announcements` 的「基础结构渲染」「原始 HTML 与代码转义」「安全链接」「不加载图片或外部资源」「历史纯文本按同一规则解析」「内联样式边界」Scenario。

## 2. 邮件 MIME 接入

- [x] 2.1 修改 `utils/mail.py`：`_build_message` 增加可选 `html_content`，固定 `set_content` → `add_alternative` → `_attach_files`；`_send_batch_smtp` 透传每条消息的 `html_content`；无 HTML 的 `send`/batch 保持原纯文本路径。验证：检查 `EmailMessage` 在无附件/有附件时的 MIME 结构。
- [x] 2.2 扩展 `test/utils/test_mail.py`，按计划 locator 覆盖纯文本+HTML alternative、无 HTML batch、无 HTML `send`、带附件时 mixed/alternative 顺序；验证：`pytest test/utils/test_mail.py -q` 通过；覆盖「发送草稿生成双正文」Scenario 的 MIME 边界。

## 3. 公告共用投递接入

- [x] 3.1 修改 `services/announcement_tasks.py`：新增小的 `_attach_announcement_html`，在 `_deliver_prepared_send` 调用 `send_batch` 前对每条公告只渲染一次 HTML，复用同一字符串；渲染异常沿用既有后台失败收尾。验证：发送/重发消息均带 `html_content`，无其他工作流改动。
- [x] 3.2 扩展 `test/announcement/test_services.py`，按计划 locator 覆盖发送/重发共用 HTML 且只渲染一次、原始内容与审计不写 HTML、渲染异常后公告 `FAILED` 且不调用传输。验证：`pytest test/announcement/test_services.py -q` 通过；覆盖「发送草稿生成双正文」「重发复用同一渲染」「HTML 不进入持久化与审计」「渲染异常沿用投递失败收尾」Scenario。

## 4. 集成验证与计划勾选

- [x] 4.1 使用 WSL 指定 Python 和 `DATABASE_URL=sqlite:///:memory: DISABLE_BACKGROUND_TASKS=1 CTRL_WSS_ENABLED=0` 运行 `pytest test/announcement test/utils/test_mail.py test/utils/test_announcement_markdown.py test/operation_log/test_mail_audit.py`，日志放入 `.git/announcement-markdown-2026-10-26/` 或 `E:/AI/Fuxi_audit_artifacts/announcement-markdown-2026-10-26/`；验证：退出码 0，记录总数与日志路径。
- [x] 4.2 对照真实断言将 `test-plan.md` 中已实现且断言成立的计划 locator 从 `[ ]` 改为 `[X]`；不修改 locator/Assertion scope/Coverage note 语义，不写运行结果。验证：所有计划 locator 在对应测试文件中存在。
- [x] 4.3 运行 `openspec validate render-announcement-markdown-mail --strict --json` 并检查 git diff，确认仅改本 change、渲染器、`utils/mail.py` 最小接入、公告服务接入、依赖和测试；未触碰 DB/迁移/前端/Node/Global。验证：valid 为 true，diff 范围符合。

## Workflow follow-up

- 主规格 sync、归档和 commit 不在本轮执行；完成 review/verify 流程后按用户后续指令处理。
