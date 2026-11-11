# Spec Delta

## ADDED Requirements

### Requirement: 公告 Markdown 邮件渲染与双正文

系统 SHALL 在发送草稿和重发公告时，将公告既有的 `content` 按同一套 Markdown 规则派生 HTML，并以 `multipart/alternative` 同封投递原始纯文本正文与 HTML 正文。HTML MUST 仅在发送期生成，MUST NOT 写回公告、草稿或模板，MUST NOT 新增持久化字段、格式标记，也不得依据内容特征猜测是否启用 Markdown。发送与重发 SHALL 共用同一投递入口，每条公告只派生一次 HTML，并复用于该公告的全部收件人；渲染异常 SHALL 沿用既有后台投递失败收尾。

#### Scenario: 发送草稿生成双正文

- **WHEN** 草稿正文包含 Markdown 并成功受理发送
- **THEN** 该公告对应邮件同时包含与公告 `content` 完全一致的纯文本正文和由同一正文派生的 HTML 正文，且公告持久化内容不被 HTML 替换

#### Scenario: 重发复用同一渲染

- **WHEN** 对一条已有公告发起重发
- **THEN** 重发邮件的纯文本与 HTML 正文均由该公告已保存的 `content` 按与首次发送相同的规则派生，公告原有字段不被改写

#### Scenario: 历史纯文本按同一规则解析

- **WHEN** 公告正文是没有 Markdown 标记的历史纯文本，并包含单个换行
- **THEN** 该正文仍按同一套 Markdown 规则解析，单个换行在 HTML 中保留为可见换行，不存在基于内容探测的另一条解析分支

#### Scenario: HTML 不进入持久化与审计

- **WHEN** 公告发送或重发完成
- **THEN** 公告的 `content`、`raw_content`、状态、计数及操作日志字段保持既有语义，派生 HTML 不以任何字段或日志内容持久化

#### Scenario: 渲染异常沿用投递失败收尾

- **WHEN** 共用投递入口在发信前派生 HTML 时发生异常
- **THEN** 该公告按既有后台失败收尾为 FAILED，不调用邮件传输，不停留在 SENDING

### Requirement: 公告 Markdown 渲染的内容与安全边界

公告 Markdown 渲染 SHALL 基础支持标题、列表、引用、表格、链接、行内代码和围栏代码块，并使用简单内联样式。原始 HTML MUST 按文本转义，代码内容 MUST 正确转义。链接 MUST 仅指向 `http`、`https` 或 `mailto` 的绝对目标；相对、协议相对及其他协议 MUST NOT 生成可点击链接。图片 MUST NOT 生成真正的 `<img>`、`src` 或远程资源请求；通过链接校验的图片 token SHALL 降级为 alt 文本，校验拒绝的图片语法 MAY 保留含可见 URL 的字面文本。渲染结果 MUST NOT 依赖脚本、`<style>`、外链 CSS 或远程字体。

#### Scenario: 基础结构渲染

- **WHEN** 公告正文包含标题、列表、引用、表格、链接、行内代码和围栏代码块
- **THEN** HTML 中生成对应的语义元素，链接指向安全目标，代码保留文本并正确转义，关键结构带有内联样式

#### Scenario: 原始 HTML 与代码转义

- **WHEN** 公告正文包含原始 HTML 标签或代码中的 HTML 片段
- **THEN** 这些内容以字面文本呈现，不生成可执行标签或脚本

#### Scenario: 安全链接

- **WHEN** 公告正文包含 `http`、`https`、`mailto` 链接，以及相对、协议相对、`javascript`、`data`、`file` 等目标
- **THEN** 仅安全绝对目标生成可点击链接，其余目标不生成链接目标，其可见文本仍保留

#### Scenario: 不加载图片或外部资源

- **WHEN** 公告正文包含 Markdown 图片语法，或代码/转义 HTML 中的资源引用文本
- **THEN** HTML 不生成真正的 `<img>`、`src`、脚本、外部样式或远程字体，也不触发远程资源请求；有效图片 token 仅呈现 alt 文本，解析器拒绝的图片语法可保持字面文本，但这些可见字符串不构成实际元素或属性

#### Scenario: 内联样式边界

- **WHEN** 公告正文被渲染为 HTML
- **THEN** 排版样式仅通过元素的内联 `style` 属性表达，不包含 `<style>`、`<link>`、`<script>`、`url()`、`@import`、外部 CSS 或远程字体依赖
