# Spec Delta

## MODIFIED Requirements

### Requirement: announcement_templates 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `AnnouncementTemplate`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。`AnnouncementTemplate` MUST NOT 持久化 `created_by`、`creator` 或指向 `users.id` 的创建者外键。模板详情与列表出参 MUST NOT 包含 `created_by`。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键，且不存在 `created_by` 字段或 `creator` 关系

#### Scenario: 创建者删除后保留模板内容

- **WHEN** 删除一条历史模板所记录的操作员用户
- **THEN** 该模板行及其名称、类别、描述、主题模板、正文模板、来源公告引用和时间字段 SHALL 原样保留，编辑器仍能读取其内容

#### Scenario: 模板出参不含创建者

- **WHEN** 客户端查询模板列表、模板详情，或把公告转为模板后读取响应
- **THEN** 模板对象 MUST NOT 包含 `created_by`，其他既有字段与分页形状保持不变

## ADDED Requirements

### Requirement: SYSTEM 模板类别不可变更

当前类别为 SYSTEM 的公告模板 SHALL 禁止改为任何其他类别。更新请求省略 `category` 或传入 `system` 时 SHALL 允许编辑名称、描述、主题模板和正文模板；传入其他类别 MUST 返回 HTTP 400，`error_reason` 为 `cannot_change_system_template_category`，且同一请求中的其他字段 MUST NOT 部分落库。CUSTOM 模板改为 SYSTEM 的既有行为 SHALL 保留。该限制 MUST NOT 新增模板状态、类别值、持久化列或后台修复。

#### Scenario: SYSTEM 改为其他类别被拒绝

- **WHEN** 对当前 SYSTEM 模板提交 `category=custom`
- **THEN** 返回 400 和 `cannot_change_system_template_category`，模板类别仍为 SYSTEM

#### Scenario: 多字段更新失败不部分落库

- **WHEN** 对当前 SYSTEM 模板在同一请求中同时修改名称、描述、主题模板、正文模板和 `category=custom`
- **THEN** 请求被拒绝且上述所有字段与更新前逐项相同，不出现名称或正文已改而类别未改的半更新

#### Scenario: 省略类别可编辑其他内容

- **WHEN** 对当前 SYSTEM 模板提交不含 `category` 的名称、描述、主题模板或正文模板更新
- **THEN** 更新成功，类别保持 SYSTEM，提交的其他字段按请求生效

#### Scenario: 同类别可编辑其他内容

- **WHEN** 对当前 SYSTEM 模板提交 `category=system` 并修改其他内容字段
- **THEN** 更新成功，类别保持 SYSTEM，其他字段按请求生效

#### Scenario: CUSTOM 改为 SYSTEM 保持允许

- **WHEN** 对当前 CUSTOM 模板提交 `category=system` 和其他内容更新
- **THEN** 更新成功，类别变为 SYSTEM，其他字段按请求生效

## Data model appendix

### 本次附录变更

- 删除 `created_by` 字段、引用 `users.id` 的外键与 `creator` 关系。
- 其余字段不变。

