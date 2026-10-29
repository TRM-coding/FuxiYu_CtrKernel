# announcements

## Purpose

公告投递与重发的持久化记录。本规格按表结构记录当前持久化与生命周期契约，字段声明以模型与服务为依据。未完成问题见 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: announcements 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Announcement`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。`Announcement` MUST NOT 持久化 `created_by`、`creator` 或指向 `users.id` 的创建者外键。公告列表与详情出参 MUST NOT 包含 `created_by`。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键，且不存在 `created_by` 字段或 `creator` 关系

#### Scenario: 创建者删除后保留公告

- **WHEN** 删除一条历史公告所记录的操作员用户
- **THEN** 该公告行及其标题、正文、原始正文、目标、状态、计数、时间、来源草稿和历史模板引用 SHALL 原样保留，重发仍使用公告已保存内容

#### Scenario: 公告出参不含创建者

- **WHEN** 客户端查询公告列表或公告详情
- **THEN** 每个公告对象 MUST NOT 包含 `created_by`，其他既有字段与分页形状保持不变

### Requirement: announcements 生产职责与生命周期

服务 SHALL 使用已校验的私有草稿内容创建 SENDING 公告并保存目标集合；后台顺序投递并回写 SENT/FAILED 及成功、失败计数，启动时收尾中断的发送。公告 SHALL 保留独立正文和当次目标快照，MUST NOT 依赖模板继续存在或在发送时重新套用模板。

#### Scenario: 批量发送受理
- **WHEN** 当前创建者的草稿和目标通过校验
- **THEN** 返回公告 id，后台投递通过计数与状态反馈；source_draft_id、target_snapshot 保留来源与当次解析快照

#### Scenario: 模板已删除
- **WHEN** 公告源自模板填充后的草稿且模板已删除
- **THEN** 仍按公告自身持久化的内容投递或重发，不要求恢复模板引用

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

### Requirement: 公告发送与复用不依赖创建者归属

批量发送、重发、复制为草稿和转为模板 SHALL 继续使用已保存的公告或草稿内容与目标。发送产生的公告 MUST NOT 记录创建者；复制为草稿 SHALL 以当前操作员作为新草稿的 `created_by`；转为模板 MUST NOT 要求或写入创建者。上述流程 MUST NOT 新增归属列、模板持久关联或草稿归属旁路。

#### Scenario: 批量发送与重发保持内容

- **WHEN** 当前操作员批量发送自己的草稿，随后重发其中一条公告
- **THEN** 新公告不记录创建者，标题、正文、原始正文、目标与来源草稿仍按草稿快照保存，重发沿用该公告已保存内容

#### Scenario: 复制公告为草稿归属当前操作员

- **WHEN** 任一操作员把一条已有公告复制为草稿
- **THEN** 新草稿的 `created_by` 是该操作员；公告 `raw_content` 有值时草稿 `content` 取该原文，缺失时回退公告 `content`；草稿 `raw_content` 始终等于公告 `raw_content`（缺失时为 NULL），目标复制自公告，且不会从公告继承创建者字段

#### Scenario: 公告转模板不写创建者

- **WHEN** 操作员把一条已有公告转为模板
- **THEN** 新模板保留公告标题与正文内容，`source_announcement_id` 指向原公告，且不要求、不写入 `created_by`

### Requirement: 公告归属旧库迁移

对已有 MySQL/MariaDB 库，手工迁移 SHALL 从实际元数据发现 `announcements.created_by` 与 `announcement_templates.created_by` 的真实外键名，删除这些外键与列，并把 `announcement_drafts.created_by` 的真实外键收敛为 `ON DELETE CASCADE`。迁移 SHALL 幂等，只改变归属约束与列，MUST NOT 删除或重建公告、模板、草稿的正文、目标、状态、时间等内容。普通应用启动路径 MUST NOT 自动删除这两个 `created_by` 列；部署 MUST 先完成迁移，再启动依赖新模型的新代码。

#### Scenario: 旧约束名可发现且迁移幂等

- **WHEN** 对一个含自动命名或显式命名创建者外键的旧库执行迁移，并在成功后再次执行
- **THEN** 两次执行均成功；两个公告类创建者列及其外键不存在，草稿创建者外键为 `ON DELETE CASCADE`，第二次执行不重复报错或改坏数据

#### Scenario: 迁移保留既有内容

- **WHEN** 旧库中的公告、模板和草稿均含正文、目标、状态与时间数据，迁移执行完成
- **THEN** 这些非归属字段及行数逐项保持迁移前值，公告与模板内容不因删列被清空或重写

#### Scenario: 普通启动不自动删列

- **WHEN** 尚未执行手工迁移的旧库由新代码执行普通启动初始化
- **THEN** 初始化路径 MUST NOT 删除 `announcements.created_by` 或 `announcement_templates.created_by`，迁移只能由显式部署步骤完成

## Data model appendix

### announcements 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 18 |
| `title` | `db.Column(db.String(200), nullable=False)` | 19 |
| `content` | `db.Column(db.Text, nullable=False)` | 20 |
| `raw_content` | `db.Column(db.Text, nullable=True)` | 21 |
| `status` | `db.Column(db.Enum(AnnouncementStatus, values_callable=lambda obj: [e.value for e in obj]), nullable=False, index=True)` | 23 |
| `targets` | `db.Column(db.Text, nullable=True)` | 28 |
| `target_snapshot` | `db.Column(db.Text, nullable=True)` | 29 |
| `recipient_count` | `db.Column(db.Integer, default=0)` | 30 |
| `success_count` | `db.Column(db.Integer, default=0)` | 31 |
| `fail_count` | `db.Column(db.Integer, default=0)` | 32 |
| `created_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow)` | 33 |
| `sent_at` | `db.Column(db.DateTime, nullable=True)` | 34 |
| `source_draft_id` | `db.Column(db.Integer, nullable=True)` | 35 |
| `template_id` | `db.Column(db.Integer, db.ForeignKey('announcement_templates.id'), nullable=True)` | 36 |

template_id 仅保留兼容历史来源；新公告不继承草稿模板关联，删除对应模板时先解除历史引用。

## Source references

- [models/announcement.py](../../../models/announcement.py)：Announcement，第 15 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[test/announcement/test_services.py](../../../test/announcement/test_services.py)；运行结果以当前隔离安全套件为准。
