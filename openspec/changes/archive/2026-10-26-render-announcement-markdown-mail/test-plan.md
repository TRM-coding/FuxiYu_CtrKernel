# Test Plan

> 约定：`[X]` 表示 locator 与断言已核对；Coverage note 只记录该场景的实际覆盖局限。

## backend--table-announcements

### Requirement: 公告 Markdown 邮件渲染与双正文

#### Scenario: 发送草稿生成双正文

- Test/check:
  - [X] test/announcement/test_services.py::test_s10_send_draft_all_success
  - [X] test/utils/test_mail.py::test_batch_builds_plain_and_html_alternative
  - [X] test/utils/test_mail.py::test_batch_without_html_keeps_plain_text
  - [X] test/utils/test_mail.py::test_send_without_html_remains_plain_text
  - [X] test/utils/test_mail.py::test_batch_html_with_attachment_keeps_alternative_first
  - [X] test/announcement/test_services.py::test_s28_send_and_resend_share_html_messages
- Assertion scope: 发送服务捕获的每条消息都含与公告 `content` 完全一致的纯文本和同源 HTML；同一公告的多收件人复用同一 HTML 字符串且只渲染一次；公告持久化的 `content` 与发送前一致。解析 `EmailMessage` 断言双正文为 `multipart/alternative`、plain part 在前；无 HTML 的 batch/send 仍为单一 `text/plain`；带附件时顶层为 `multipart/mixed`，首个 part 为 `multipart/alternative`（plain 在前），附件最后。既有 `test_s10` 只覆盖纯文本内容与 SENT 状态。
- Coverage note: 附件与无 HTML 的 send/batch 用例只验证 `utils.mail` 边界，不表示公告支持附件或普通邮件启用 Markdown；未验证真实 SMTP 与客户端对 alternative part 的选择。

#### Scenario: 重发复用同一渲染

- Test/check:
  - [X] test/announcement/test_services.py::test_s17_resend_from_sent
  - [X] test/announcement/test_services.py::test_s28_send_and_resend_share_html_messages
- Assertion scope: 重发捕获消息的纯文本与 HTML 均由该公告已保存的 `content` 派生，HTML 与首次发送一致且经同一投递入口附加；重发前后公告 `title`、`content`、`raw_content`、`targets` 不被改写。既有 `test_s17` 只验证沿用同一公告与终态，不检查正文结构。
- Coverage note: 未覆盖真实 SMTP 与客户端渲染；重发不新建公告、不改写正文属现有行为回归。

#### Scenario: 历史纯文本按同一规则解析

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_preserves_single_newlines
- Assertion scope: 用 `HTMLParser` 解析无 Markdown 标记的多行纯文本，断言输出保留为相邻文本与真实的 `<br>`，没有被合并成一行；同一渲染函数不接收也不推断“旧格式”标志。
- Coverage note: 只断言渲染结构，不承诺各邮件客户端的最终视觉换行；本变更无历史回填。

#### Scenario: HTML 不进入持久化与审计

- Test/check:
  - [X] test/announcement/test_services.py::test_s10_send_draft_all_success
  - [X] test/announcement/test_services.py::test_s11_send_draft_partial_failure
  - [X] test/announcement/test_services.py::test_s29_send_preserves_source_and_audit
- Assertion scope: 通过实际 `start_batch_send_service` 发送带 Markdown 的草稿，断言公告 `content`、`raw_content` 原样保留，状态、计数与草稿删除保持既有语义；操作日志 detail 不含 `html_content` 或由正文渲染出的 HTML 标签/正文。既有 `test_s10`/`test_s11` 只覆盖部分状态、计数与审计形状。
- Coverage note: 使用隔离 SQLite 与本地传输替身，未在生产 MySQL 验证；本变更无迁移/回填。发送路径不写草稿或模板，模板不参与投递。

#### Scenario: 渲染异常沿用投递失败收尾

- Test/check:
  - [X] test/announcement/test_services.py::test_s30_render_exception_settles_failed_without_send
- Assertion scope: monkeypatch 渲染函数抛出异常后走内联后台线程，断言公告终态为 `FAILED`、不存在 `SENDING` 残留，且 `_send_batch_smtp` 未被调用；不新增重试或纯文本降级。
- Coverage note: 仅覆盖服务级本地失败收尾，不覆盖真实 SMTP/客户端。

### Requirement: 公告 Markdown 渲染的内容与安全边界

#### Scenario: 基础结构渲染

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_basic_markdown_structures
- Assertion scope: 用 `HTMLParser` 收集真实节点与属性，断言存在 `h1`/`h2`、`ul`/`ol`/`li`、`blockquote`、`table`/`thead`/`tbody`/`tr`/`th`/`td`、安全 `a[href]`、`code`、`pre`；代码内容保留并转义；关键 opening tag 带内联 `style`，不存在真实的 `style`/`link`/`script` 元素。
- Coverage note: 只做结构级断言，不验证邮件客户端排版、暗色模式或响应式效果。

#### Scenario: 原始 HTML 与代码转义

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_escapes_raw_html_and_code
- Assertion scope: 用 `HTMLParser` 断言正文中的 `<script>`、`<b>`、`<img>` 等原始标签不成为真实元素；其可见内容以转义文本出现，行内代码与围栏代码中的 HTML 片段同样转义，输出无真实 `script` 元素。
- Coverage note: 未执行浏览器级 XSS 扫描；依赖 `html=False` 与渲染器默认代码转义，不引入自写清洗器。

#### Scenario: 安全链接

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_allows_only_safe_links
- Assertion scope: 用 `HTMLParser` 断言真实 `<a>` 的 `href` 仅来自 `http`/`https`/`mailto` 绝对目标；`[x](relative)`、`[x](//evil.example)`、`javascript`、`data`、`file` 目标不产生 `<a>`/`href`，其可见字面文本保留；scheme 大小写混用仍按同一允许列表判定，属性值正确转义。
- Coverage note: 覆盖代表性目标，不宣称穷尽所有编码绕过；未做真实浏览器点击验证。

#### Scenario: 不加载图片或外部资源

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_suppresses_images_without_resource_requests
- Assertion scope: 用 `HTMLParser` 断言不存在真实的 `img`/`script`/`style`/`link` 元素、任何 `src` 属性，也不存在由图片语法生成的可点击 `<a>` 或 `<img>`；`![alt](https://img.example/x.png)` 只留下 alt 文本，`![alt](relative)`、`![alt](//evil.example/x.png)`、`![alt](javascript:...)` 可保留含 URL 的字面文本但不生成实际元素。真实 `style` 属性不含 `url()`/`@import`/远程字体；代码或转义 HTML 中的 `<script>`、`url(...)`、`src=`、`@import` 仅作为文本数据出现。
- Coverage note: 只证明输出结构不产生真实资源加载/请求，不验证邮件客户端自身预取；不要求隐藏被拒绝图片语法中的可见 URL，也不新增图片或追踪能力。

#### Scenario: 内联样式边界

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_basic_markdown_structures
- Assertion scope: 用 `HTMLParser` 断言样式只存在于真实元素的 `style` 属性；不存在 `style`/`link`/`script` 元素，真实 `style` 值不含 `url()`、`@import` 或外部 CSS/远程字体依赖。
- Coverage note: 与基础结构共享计划用例；只断言样式形式，不保证客户端最终视觉。
