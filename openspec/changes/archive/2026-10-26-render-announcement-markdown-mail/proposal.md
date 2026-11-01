# Proposal

## Why

公告当前以纯文本正文发送，正文中的 Markdown 标记只会原样出现在收件人邮箱里，无法获得标题、列表、引用、表格、链接与代码等基本结构。需要在保持现有公告的保存、收件人、发送节奏、状态与审计语义不变的前提下，让同一份正文在邮件中同时提供原始的纯文本正文和由 Markdown 派生的 HTML 正文。

## What Changes

- 公告正文在**发送时**按 Markdown 渲染为邮件 HTML；HTML 仅在内存中派生，不写回数据库、不新增持久化字段或格式标记，公告/草稿/模板原有的 `content` 与 `raw_content` 均按原文保存和读取。
- 所有公告正文（含历史纯文本）统一按同一套 Markdown 规则解析，启用 `breaks` 以保留单换行；不通过内容特征猜测是否为 Markdown，也不为旧内容提供另一条解析分支。
- Markdown 基础支持标题、列表、引用、表格、链接、行内代码与围栏代码块；原始 HTML 关闭并按文本转义；链接仅接受 `http`、`https`、`mailto` 绝对目标，相对、协议相对和危险协议不生成可点击链接；图片语法不生成真正的 `<img>`/`src` 或远程请求，通过校验的图片 token 降级为 alt 文本，被解析器拒绝的图片语法可保留字面文本；不新增图片上传、目录、追踪、自写预处理或格式探测。
- 邮件正文采用纯文本 + HTML 的双正文 `multipart/alternative`；纯文本部分仍为公告原始正文，HTML 部分使用简单内联样式，避免依赖外部 CSS 或在线资源。附件存在时 HTML 替代正文排在附件之前。
- 发送草稿与重发共用同一个公告投递入口：在投递前为每条公告只渲染一次 HTML，再复用于该公告的所有收件邮件；渲染异常沿用既有后台投递失败收尾；不改变 `send_batch` 的连接复用、逐封间隔、收件人解析、重试、状态回写、成功/失败计数与审计。
- `utils/mail.py` 仅做最小接入：`EmailMessage` 构建支持可选的 HTML 正文，先写入原始纯文本再追加 HTML 替代正文；`send_batch` 透传每条消息的可选 HTML；未提供 HTML 的既有调用保持纯文本行为不变。
- 新增 Markdown 渲染依赖 `markdown-it-py`，仅由公告邮件渲染模块使用；不引入 Node 改动、前端预览、数据库迁移、图片上传、附件目录或追踪能力。
- 增加渲染、转义、安全链接/图片结构、双正文与附件 MIME 顺序、普通 `send` 纯文本、发送/重发复用、原文存储/审计及渲染异常失败收尾测试。

## Capabilities

### New Capabilities

- 无：本变更在现有公告能力内新增 Requirement，不新建 capability。

### Modified Capabilities

- `backend--table-announcements`：新增公告投递的 Markdown 邮件渲染与双正文要求，并明确原文保存、历史纯文本统一解析及安全边界。

## Impact

- **Ctrl 代码**：`services/announcement_tasks.py`（在发送/重发共用的投递入口附加 HTML）、`utils/mail.py`（可选 HTML 替代正文与批量透传），以及新增的公告 Markdown 渲染工具模块；不改 `api/announcement_api.py` 的请求/响应合同。
- **依赖**：`requirements.txt` 增加 `markdown-it-py`；不启用链接自动识别，不引入额外 Markdown 插件。
- **数据与迁移**：不改数据库表、模型、迁移、`content`/`raw_content` 语义或公告状态机；不新增 HTML 缓存、预览字段或格式标记。
- **不变行为**：群发节奏与逐封间隔、收件人解析与去重、发送/重发入口、审计 `mail_type`/`detail`、公告状态与成功/失败计数、草稿删除规则、其他系统邮件均保持现状。
- **前端与外部系统**：无前端预览、无 Node 改动、无新接口；不连接或修改任何生产机器。
- **测试**：使用现有 SQLite 隔离夹具与 SMTP/线程替身；覆盖渲染器单测、邮件 MIME 结构单测及公告发送/重发服务回归；不触达真实 SMTP、真实数据库或远程主机。
