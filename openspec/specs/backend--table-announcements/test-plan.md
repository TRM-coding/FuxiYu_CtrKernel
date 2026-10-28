# backend--table-announcements Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: announcements 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_a01_announcement_readback_contract
  - [X] test/announcement/test_repository.py::test_r02_get_announcement_by_id_exists
  - [X] test/announcement/test_models.py::test_m01_announcement_create_full_fields
  - [X] test/announcement/test_models.py::test_m05_targets_json_roundtrip
- Assertion scope: `test_anvil_a01` 用新 session 按主键重开“最小公告”和“完整公告”，断言 `title`/`content` 是 `str`、`status` 为枚举值、`created_by` 是 `int` 且等于创建者用户主键、未赋值的 `recipient_count`/`success_count`/`fail_count` 回读为默认 0、未赋值的 `targets`/`target_snapshot`/`raw_content`/`sent_at`/`source_draft_id`/`template_id` 回读为 `NULL`、赋值的 `targets`/`target_snapshot` 按文本原样往返、赋值的 `source_draft_id` 按原值往返、`created_at` 是插入时间窗内的 `datetime`；`test_r02` 断言按存在 id 读取返回同一 id；`test_m01` 断言创建字段（同 session）；`test_m05` 断言 `targets` JSON 文本可解析回原列表。
- Coverage note: 未验证生产 MySQL 方言；`test_m01` 不是跨 session 读回证据。

### Requirement: announcements 生产职责与生命周期

#### Scenario: 批量发送受理

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_a02_batch_send_persists_target_snapshot
  - [X] test/announcement/test_api.py::test_a30b_batch_send_returns_accepted_without_waiting
  - [X] test/announcement/test_api.py::test_a30_batch_send
  - [X] test/announcement/test_services.py::test_s10_send_draft_all_success
  - [X] test/announcement/test_services.py::test_s15_batch_send_three_drafts
  - [X] test/announcement/test_services.py::test_s24_settle_stuck_sending_on_startup
- Assertion scope: `test_anvil_a02` 发送单条草稿后从持久化公告读取 `target_snapshot`，断言 JSON 可解析、含当次解析摘要（`type`/`id`/`display_name`）且 `recipient_count` 与解析总数一致；`test_a30b` 用空转线程断言受理即返回 `total=1` 与公告 id、公告仍 `SENDING`、`source_draft_id` 指向草稿、尚无 `send_mail` 日志；`test_a30` 断言回执 `total=2`、两条公告与两条对应日志；`test_s10` 断言内联投递后 `SENT`、计数、草稿删除与正文；`test_s15` 断言 3 条草稿各得到一条 `SENT` 公告；`test_s24` 构造遗留 `SENDING` 与 `SENT`，断言启动收尾返回 1、遗留转 `FAILED`、`SENT` 不变且无残留 `SENDING`。
- Coverage note: `test_s24` 是 Requirement 级启动收尾检查，不是本 Scenario 的受理/`target_snapshot` THEN 证据；`test_a30b` 覆盖 `source_draft_id`，`test_anvil_a02` 覆盖 `target_snapshot` 与 `recipient_count`。不覆盖真实 SMTP 投递。

#### Scenario: 模板已删除

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_a03_resend_after_template_deleted_uses_saved_content
  - [X] test/announcement/test_template_decoupling.py::test_q06_delete_template_referenced_by_announcement_keeps_content
- Assertion scope: `test_anvil_a03` 在模板引用已解除的公告上调用 `start_resend_service` 并就地执行后台线程，捕获传输消息后断言邮件 `content` 等于公告已保存 `content`、公告终态 `SENT`、`template_id` 保持 `NULL`，且 `title`/`raw_content`/`targets`/`target_snapshot`/`recipient_count`/`source_draft_id` 未被改写；`test_q06_delete...` 断言删除模板后公告正文与 `template_id` 解除。两者结合证明重发不要求恢复模板引用、不重新套用模板。
- Coverage note: 未覆盖真实 SMTP 与客户端渲染。

### Requirement: 公告 Markdown 邮件渲染与双正文

#### Scenario: 发送草稿生成双正文

- Test/check:
  - [X] test/announcement/test_services.py::test_s28_send_and_resend_share_html_messages
  - [X] test/announcement/test_services.py::test_s10_send_draft_all_success
  - [X] test/utils/test_mail.py::test_batch_builds_plain_and_html_alternative
  - [X] test/utils/test_mail.py::test_batch_without_html_keeps_plain_text
  - [X] test/utils/test_mail.py::test_send_without_html_remains_plain_text
  - [X] test/utils/test_mail.py::test_batch_html_with_attachment_keeps_alternative_first
- Assertion scope: `test_s28` 捕获投递消息，断言每条消息 `content` 与草稿 Markdown 正文完全一致、所有收件人共用同一 `html_content`、渲染函数只被调用一次、HTML 含 `<h1` 与 `<strong>`，且公告持久化 `content` 未被 HTML 替换；`test_s10` 覆盖发送终态、计数、草稿删除与 `content`；四条 `test_mail` 分别断言含 `html_content` 时消息为 `multipart/alternative`（`text/plain` 在前、`text/html` 正文正确）、无 `html_content` 的 batch/send 仍是单一 `text/plain`、带附件时顶层为 `multipart/mixed` 且首个子 part 为 `multipart/alternative`、附件在最后。
- Coverage note: `test_mail` 的附件与无 HTML 用例只验证 `utils.mail` 边界，不表示公告支持附件或普通邮件启用 Markdown；未验证真实 SMTP 与客户端对 alternative part 的选择。

#### Scenario: 重发复用同一渲染

- Test/check:
  - [X] test/announcement/test_services.py::test_s17_resend_from_sent
  - [X] test/announcement/test_services.py::test_s28_send_and_resend_share_html_messages
- Assertion scope: `test_s17` 断言重发沿用同一条公告（返回同一 id）并回到 `SENT`；`test_s28` 断言重发时渲染函数再次被调用、捕获消息的 `content` 与 `html_content` 均由该公告已保存的 `content` 派生且 HTML 与首次发送一致，重发后 `title`/`content`/`raw_content`/`targets` 未被改写。
- Coverage note: 未覆盖真实 SMTP 与客户端渲染；重发不新建公告属既有行为回归。

#### Scenario: 历史纯文本按同一规则解析

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_a04_plain_and_markdown_use_same_renderer_call
  - [X] test/utils/test_announcement_markdown.py::test_render_preserves_single_newlines
- Assertion scope: `test_anvil_a04` 从同一发送入口分别发送纯文本（含单个换行）与 Markdown 草稿，包装并记录真实 renderer 调用，断言两次都调用同一 recorder、每个正文各一次、入参分别为对应 `content`，捕获的纯文本 HTML 含真实 `<br>` 标签、Markdown HTML 含 `<h1`/`<strong>`，且两者与直接调用真实 renderer 一致；`test_render_preserves_single_newlines` 断言纯文本单换行渲染为 `<br>` 且可见文本保留，`inspect.signature` 只作接口线索。
- Coverage note: `test_anvil_a04` 能证明发送入口对纯文本与 Markdown 使用同一 renderer 调用且输出与直接渲染一致；仍不能黑盒排除 renderer 内部按内容分支，`inspect.signature` 不是行为证据。不承诺各邮件客户端的最终视觉换行，本变更无历史回填。

#### Scenario: HTML 不进入持久化与审计

- Test/check:
  - [X] test/announcement/test_anvil_announcement_mappings.py::test_anvil_a05_send_and_resend_do_not_write_html_into_draft_or_template
  - [X] test/announcement/test_services.py::test_s29_send_preserves_source_and_audit
  - [X] test/announcement/test_services.py::test_s10_send_draft_all_success
  - [X] test/announcement/test_services.py::test_s11_send_draft_partial_failure
- Assertion scope: `test_anvil_a05` 建模板与显式 `content`/`raw_content` 的 Markdown 草稿，发送前快照草稿/模板，在传输捕获点重读并断言与快照一致；发送完成后断言公告 `content`/`raw_content` 分别等于草稿原文、模板逐字段不变、草稿按既有语义删除；重发后再次断言模板不变、公告既有字段未被改写、终态 `SENT`，且两次审计详情都不含 `html_content`/`<h1>`/`<strong>`。`test_s29` 断言发送后公告正文原样、计数与草稿删除保持语义，日志序列化文本不含 HTML；`test_s10` 断言 `SENT` 终态/计数/正文与草稿删除，不检查日志；`test_s11` 断言 `PARTIAL` 终态/计数与日志形状，不断言日志中是否出现 HTML。
- Coverage note: 使用隔离 SQLite 与本地传输替身；未在生产 MySQL 验证，未验证真实 SMTP/客户端。

#### Scenario: 渲染异常沿用投递失败收尾

- Test/check:
  - [X] test/announcement/test_services.py::test_s30_render_exception_settles_failed_without_send
- Assertion scope: monkeypatch 公告投递模块使用的渲染函数抛出异常，经就地执行的“后台线程”后断言公告终态为 `FAILED`、`_send_batch_smtp` 未被调用（捕获列表为空）、且不存在残留 `SENDING` 公告。
- Coverage note: 只在服务级验证本地失败收尾，不覆盖真实 SMTP/客户端。

### Requirement: 公告 Markdown 渲染的内容与安全边界

#### Scenario: 基础结构渲染

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_basic_markdown_structures
- Assertion scope: 用 `HTMLParser` 收集真实节点与属性，断言存在 `div`/`h1`/`h2`/`p`/`ul`/`ol`/`li`/`blockquote`/`table`/`thead`/`tbody`/`tr`/`th`/`td`/`a`/`code`/`pre`，关键 opening tag 带内联 `style`，不存在 `style`/`link`/`script` 元素，行内代码与围栏代码中的 `<b>&`、`<script>` 以字面文本出现。
- Coverage note: 只做结构级断言，不验证邮件客户端排版、暗色模式或响应式效果。

#### Scenario: 原始 HTML 与代码转义

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_escapes_raw_html_and_code
- Assertion scope: 断言正文中的原始 `<script>`/`<b>`/`<img src=...>` 不成为真实元素（`tags` 中无 `script`/`b`/`img`），其原文以可见文本出现；行内代码与围栏代码里的 HTML 片段同样转义为文本。
- Coverage note: 未执行浏览器级 XSS 扫描，依赖渲染器 `html=False` 与默认代码转义。

#### Scenario: 安全链接

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_allows_only_safe_links
- Assertion scope: 断言真实 `<a>` 的 `href` 恰好 4 个且全部以 `http://`/`https://`/`mailto:` 开头（含大小写混合与带 query 的写法），`relative`、`//evil.example`、`javascript:`、`data:`、`file:` 目标不产生 `href` 而其可见字面文本保留，输出中的 `&` 被转义。
- Coverage note: 覆盖代表性目标，不宣称穷尽所有编码绕过；未做真实浏览器点击验证。

#### Scenario: 不加载图片或外部资源

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_suppresses_images_without_resource_requests
- Assertion scope: 断言输出无 `img`/`script`/`style`/`link`/`a` 元素、任何标签都不带 `src` 属性；有效图片 token 只留 alt 文本（含已转义的 `&lt;b&gt;`、`&quot;`），被拒绝的图片语法保留含 URL 的字面文本；真实 `style` 属性不含 `url()`/`@import`；代码与转义 HTML 中的 `url(...)`、`@import` 仅作为文本数据出现。
- Coverage note: 只证明输出结构不产生资源加载/请求，不验证邮件客户端自身预取；代码字面中的 `src="x"` 未被单独断言，`src` 层面由“无 `img`、任何标签无 `src` 属性”的结构断言覆盖。

#### Scenario: 内联样式边界

- Test/check:
  - [X] test/utils/test_announcement_markdown.py::test_render_basic_markdown_structures
- Assertion scope: 断言样式只出现在真实元素的 `style` 属性上，不存在 `style`/`link`/`script` 元素，所有 `style` 值都不含 `url()` 与 `@import`（即无外部 CSS 或远程字体依赖）。
- Coverage note: 与“基础结构渲染”共用同一测试；只断言样式形式，不保证客户端最终视觉。
