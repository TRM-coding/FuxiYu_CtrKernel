# Design

## Context

- 当前发送路径：`start_batch_send_service` 在同步段校验草稿与目标，创建 `SENDING` 公告，并在 `_create_sending_announcement` 中把 `announcement.content` 组装成 `{"to", "subject", "content"}` 消息列表；后台 `_deliver_prepared_send` 调用 `utils.mail.send_batch`，再按结果回写状态、计数并删除草稿。
- 当前重发路径：`_prepare_resend` 读取公告自身的 `content` 与 `targets`，把公告置回 `SENDING`，组装同样形状的消息列表，之后复用同一个 `_deliver_prepared_send`。发送与重发共用该投递函数；消息列表仍在两处构造，但 HTML 只在这个共用函数内附加。
- `utils.mail._build_message` 目前只执行 `msg.set_content(content)`，即纯文本单正文；`_send_batch_smtp` 逐条读取 `to`、`subject`、`content`、`cc`、`bcc`、`attachments`，并预构建 `EmailMessage`。`send_batch` 的结果契约、逐封间隔与审计汇总不依赖正文内容。
- 公告模型同时保存 `content` 与 `raw_content`，但当前邮件投递只使用 `content`；本变更不切换到 `raw_content`，也不推断两者中谁是 Markdown 源，避免改变既有发送来源。Web 公告编辑器当前把同一份文本同时写入 `content` 与 `raw_content`，且没有公告预览，因此以 `content` 为源不会改变用户在编辑器中的输入语义。
- 仓库当前没有 Markdown 渲染依赖；本地开发环境已有 `markdown-it-py 4.0.0`，但 `requirements.txt` 未声明。既有测试使用 SQLite 隔离夹具、SMTP 替身与内联线程替身，不允许触达真实 SMTP。

## Goals / Non-Goals

**Goals:**

- 公告发送与重发都以现有 `content` 为唯一来源，派生出与原始纯文本并存的 HTML 正文。
- 历史纯文本与 Markdown 文本走同一解析规则，保留单换行，不引入格式探测或新的持久化标记。
- 提供标题、列表、引用、表格、安全链接、行内代码与围栏代码块的基础渲染和简单内联样式。
- 原始 HTML 与代码正确转义；危险链接不生成可点击目标；不输出真实 `<img>`、外部样式、远程字体或脚本等资源引用。
- 对 `utils.mail` 只做可选 HTML 替代正文的最小接入，不改变其他系统邮件的纯文本行为。
- 保持收件人、逐封节奏、状态、成功/失败计数、草稿删除和审计语义不变。

**Non-Goals:**

- 不做前端 Markdown 预览、编辑器改造、模板预览或公告详情 HTML 展示。
- 不新增数据库字段、迁移、HTML 缓存、格式标记或历史数据回填。
- 不新增图片上传、附件目录、图片托管、外链追踪、打开/点击统计或远程资源代理。
- 不改变发送/重发的接口合同、异步线程模型、收件人解析、群发节奏与审计字段。
- 不为所有系统邮件自动启用 Markdown，也不改变 `send` 单封路径的现有调用语义。
- 不实现完整富文本编辑器、HTML 白名单清洗器、自写 Markdown 预处理/格式探测或第三方 Markdown 插件生态。

## Decisions

### D1：以既有 `content` 作为唯一渲染来源，HTML 仅在发送期派生

- 发送和重发均使用公告持久化的 `content`，与当前纯文本邮件使用的字段完全一致；`raw_content` 继续按原样保存，不参与本次投递，也不做“优先 raw_content”之类的回退。
- 渲染发生在共用投递函数 `_deliver_prepared_send` 内、调用 `send_batch` 之前；生成结果只进入内存消息字典和 `EmailMessage`，不写回公告、草稿、模板，不新增持久化字段。
- 不对正文做格式探测，不依据是否存在 `#`、`|`、反引号等特征选择解析器；同一函数处理全部历史与新增内容。
- 解析启用 `breaks`，让单个换行在 HTML 中保留为换行；这是历史纯文本段落观感兼容的关键。
- 备选：用 `raw_content` 作为 Markdown 源、`content` 作为纯文本回退。不采用，因为当前邮件实际发送 `content`，切换来源会改变既有行为，也会引入两者不一致时的隐式选择。

### D2：使用 `markdown-it-py` 的 CommonMark 预设并收紧可选能力

- 新增独立的公告渲染模块 `utils/announcement_markdown.py`，导出纯函数 `render_announcement_html(source: str) -> str`；不依赖数据库、网络、配置或请求上下文。
- 解析器配置：`MarkdownIt("commonmark", {"html": False, "breaks": True})`，并启用 `table` 规则；不启用 `linkify`、`typographer` 或额外插件，避免自动识别文本中的链接和不可控的排版转换。
- 原始 HTML 关闭后由渲染器转义；代码块与行内代码使用渲染器的默认转义，不启用高亮器，不拼接未转义内容。
- 链接和图片共用解析期 `validateLink` 允许列表：仅接受带 `http`、`https` 或 `mailto` scheme 的绝对目标（scheme 大小写不敏感）；相对目标、协议相对目标和危险协议在 token 产生前被拒绝，链接保留可见字面文本，不生成 `<a>`。
- 通过 `validateLink` 的图片 token 由自定义图片渲染规则降级为转义后的 alt 文本（无 alt 时丢弃），绝不输出 `<img>`/`src`；被 `validateLink` 拒绝的图片语法保留字面文本，可能包含可见 URL，但不生成 `<img>`/`src`、不触发远程请求。不做自写 Markdown 预处理、格式探测或 URL 隐藏，有效图片与拒绝图片的差异只来自解析器结果。
- 使用一个外层 `<div>` 包装，并对标题、段落、列表、引用、表格、代码和链接注入静态内联 `style`；不生成 `<style>`、`<link>`、`<script>`、远程字体或外部 CSS。
- 备选：使用 `markdown` 包再叠加 `bleach` 清洗。不采用：多一个渲染依赖和一套 HTML 清洗规则，且 `markdown-it-py` 已能满足基础结构、转义与链接校验需求；也不采用前端预渲染 HTML，因为会产生持久化或接口合同变化。

### D3：`EmailMessage` 使用纯文本优先的 `multipart/alternative`

- `utils.mail._build_message` 增加可选参数 `html_content: str | None = None`；固定执行顺序为 `set_content(content)` → `add_alternative(html_content, subtype="html")` → `_attach_files`。HTML 替代正文 MUST 在附件之前追加；否则带附件的消息会从 `multipart/mixed` 反向转换并抛出 `ValueError`。未提供 HTML 时维持 `set_content` → `_attach_files`。
- 无附件时邮件为 `multipart/alternative`：第一个 part 是原始纯文本，第二个 part 是 HTML；纯文本内容不做任何 Markdown 替换或标签剥离。带附件时顶层为 `multipart/mixed`，首个 part 仍为 `multipart/alternative`（plain 在前），附件在其后。
- `_send_batch_smtp` 从每条消息读取可选的 `html_content` 并传给 `_build_message`；`send_batch` 的公开调用方式、结果列表、审计汇总和逐封间隔保持不变。消息未提供 `html_content` 时，构建结果与当前完全一致。
- 单封 `send`/`_send_smtp` 不新增参数或行为，普通系统邮件继续只构建单一 `text/plain`，不自动启用 Markdown；如果以后需要，可在同一 `_build_message` 参数上扩展。
- 备选：直接构造 `MIMEMultipart` 并手工设置 header。不采用：`EmailMessage` 已统一处理编码、CTE 和附件，手工替换会扩大改动面并与现有工具分叉。

### D4：发送与重发共用投递入口，在发信前附加 HTML

- 发送与重发已经共用 `_deliver_prepared_send`；新增一个小函数 `_attach_announcement_html(messages: list[dict]) -> list[dict]`，在该共用函数内、调用 `send_batch` 之前执行。小函数从消息列表首条的 `content` 调用一次 `render_announcement_html`，为每条消息生成带 `html_content` 的副本。
- 不修改 `_create_sending_announcement` 与 `_prepare_resend` 的消息构造，避免在同步准备段引入新的失败分支；消息列表为空时直接返回空列表，不渲染。
- 每条公告只渲染一次，而不是逐收件人渲染；HTML 字符串在同一公告的多封邮件之间共享，避免 200 个收件人产生 200 次解析。所有公告消息的正文相同，因此以首条 `content` 作为来源是明确的公告内约束。
- 渲染发生在后台投递线程中；若渲染抛出异常，`_deliver_batch_in_background` 的现有异常收尾负责把该公告置为 `FAILED`，不会停留在 `SENDING`，也不会调用 `_send_batch_smtp`。不新增重试，也不静默降级为纯文本。
- 渲染不读取收件人或目标信息，因此收件人解析、去重与上下文无关；公告正文中的 Markdown 也不会被用于识别目标或改变发送对象。
- 备选：抽出 `_build_announcement_messages` 并改写两个构造点。不采用：会改动同步准备段、增加新的失败位置，而现有共用投递函数已经能保证发送与重发同规则。

### D5：安全与转义由渲染器配置和少量自定义规则共同保证

- 原始 HTML 关闭是主要防线：正文中的 `<script>`、`<img>`、`<style>` 等标签不会成为可执行 HTML，而是可见文本。
- 代码内容由渲染器转义；围栏代码不做语法高亮，避免高亮器再次注入 HTML。
- 链接和图片使用同一解析期允许列表；不满足条件时不生成 `<a>` 或图片 token，避免 `javascript:`、`data:`、`file:`、相对和协议相对目标进入可点击或可加载结构。
- 图片规则显式覆盖为文本降级，确保不产生远程图片请求；不新增图片下载、缓存或代理逻辑，也不为隐藏可见 URL 另写预处理。
- 输出层不引入第三方 HTML 清洗器或自写安全模块：在原始 HTML 关闭、链接受限、图片禁用、无脚本/样式注入的前提下，渲染器生成的标签集合是固定且可控的。若未来开启原始 HTML 或新增插件，必须重新评估并补充清洗。
- 安全测试使用 stdlib `HTMLParser` 解析实际标签与属性：断言不存在真正的 `img`/`style`/`link`/`script` 元素、`src` 属性或含 `url()`/`@import` 的真实 `style` 属性；代码或转义 HTML 中可见的 `<script>`、`url(...)`、`src=` 等字符串只作为文本数据，不能当作实际资源加载。不得用输出字符串中是否出现这些子串作为安全判据。
- 审计只读取收件人、主题、发送模式等既有元数据，HTML 与正文均不进入审计；“HTML 不进入审计”由现有 `_mail_audit_detail` 的选择性字段逻辑继续保证，无需新增脱敏分支。

### D6：历史纯文本兼容与持久化边界

- 历史正文没有格式标记，也不需要迁移；`breaks=True` 让普通多行文本保持逐行显示，而不是被 CommonMark 合并为一段。
- 单换行、连续空行、中文标点和常见符号都走同一解析器；不新增“检测到旧内容就按纯文本”的分支，也不把历史内容回填或改写。
- 正文中的 Markdown 标记会被按语法解释，这是统一解析的明确结果；需要显示字面标记的用户可使用反斜杠转义。该行为在文档中记录为预期，不通过内容猜测规避。
- `content` 与 `raw_content` 的持久化语义不变：保存时仍按原文写入，读取和 API 展示不转换为 HTML；公告发送成功后的内容仍可直接作为纯文本复用。

### D7：依赖与部署

- `requirements.txt` 增加 `markdown-it-py>=4.0`；不增加 `linkify-it-py`，因为不启用自动链接识别。
- 渲染模块在导入时初始化解析器实例即可；解析器不持有请求状态。部署时必须先安装新增依赖，再启动 Ctrl；没有数据库迁移或配置项。
- 滚动回滚只需回退 Ctrl 代码与依赖；已持久化的正文未改变，回滚后恢复纯文本发送即可，不需要数据清理。

## Risks / Trade-offs

- **[历史正文中的 Markdown 字符被解释]** → 统一解析会让历史内容中的 `#`、`*`、`|` 等产生格式，而不是逐字显示。这是“同一规则解析、不猜格式”的直接代价；用户可用反斜杠转义。备选的内容探测会让相同文本在不同时间呈现不同结果，故不采用。
- **[邮件客户端样式差异]** → 只使用简单内联样式，不保证各客户端完全一致；复杂布局、暗色模式和响应式排版不在范围内。内联样式优于被大量客户端剥离的 `<style>`，但不宣称像素级一致。
- **[HTML 体积增加]** → 每封邮件同时携带纯文本与 HTML，体积和传输时间会上升；每次公告只渲染一次并复用字符串，避免重复解析，但不消除双正文本身的体积成本。
- **[安全边界依赖配置正确]** → 若后续有人把 `html` 改为开启、放宽链接校验或启用图片规则，现有转义与禁止远程资源的保证会失效。设计把这些点固定为安全不变量，并由测试覆盖，阻止无意放宽。
- **[图片语法不可用]** → 有效图片 token 按 alt 文本显示，不显示实际图片；被解析器拒绝的图片语法保留字面文本，可能显示原 URL，但绝不生成 `<img>`/`src` 或请求。不为了让 URL 不可见而增加预处理，这是“不隐藏可见文本、不新增图片能力”的明确边界。
- **[链接与图片共用解析期校验]** → 相对、协议相对和危险 scheme 在 token 产生前被拒绝；链接不可点击，图片不生成 `<img>`。被拒绝的图片语法可能留下可见 URL，但不会产生资源加载；若未来放宽允许列表，必须同时重新验证链接与图片两条路径。
- **[新增运行时依赖]** → 未安装 `markdown-it-py` 时，公告发送路径会在导入阶段失败。要求与依赖清单同步部署；不采用惰性导入或静默降级，以免运行到发送时才暴露缺失依赖。
- **[渲染异常]** → 渲染在后台投递入口、发信之前执行；异常由现有 `_deliver_batch_in_background` 捕获并将公告收尾为 `FAILED`，不会留下 `SENDING`，也不会调用 `_send_batch_smtp`。不伪造 HTML，不悄悄切换解析器，不新增 try/except 降级或重试分支。
- **[审计与状态不变]** → HTML 仅存在于投递前的内存消息与 `EmailMessage` 中；`send_batch` 的结果、状态回写、计数、草稿删除与审计字段都不感知 HTML。没有新增审计字段，也没有新增“HTML 已生成”的成功标记。
