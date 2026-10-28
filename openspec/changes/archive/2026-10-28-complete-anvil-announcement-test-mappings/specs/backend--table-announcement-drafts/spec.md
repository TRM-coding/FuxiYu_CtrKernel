# Spec Delta

## MODIFIED Requirements

### Requirement: announcement_drafts 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `AnnouncementDraft`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: announcement_drafts 生产职责与生命周期

草稿 SHALL 保存创建者自己的 title、content、raw_content 与 targets 内容快照。模板 SHALL 仅用于初始化编辑内容，草稿 MUST NOT 依赖模板引用；兼容的历史 template_id SHALL 解除。列表、按 id 读取、更新、删除和发送草稿 SHALL 校验创建者，普通操作员权限不授予访问他人草稿的能力。

#### Scenario: 保存与列出草稿
- **WHEN** 用户创建新草稿
- **THEN** 记录 created_by，仅在该创建者列表返回；内容独立于模板，未建立有效 template_id 引用

#### Scenario: 其他操作员尝试操作
- **WHEN** 操作员通过他人的 draft_id 读取、更新、删除或发送草稿
- **THEN** 操作被拒绝且原草稿的创建者、内容、目标与状态不变

#### Scenario: 模板变化后重开草稿
- **WHEN** 初始化草稿使用的模板被修改或删除，创建者重新打开草稿
- **THEN** 返回已保存内容，不重新套用模板，也不因模板缺失导致失败
