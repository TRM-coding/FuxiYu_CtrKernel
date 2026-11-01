# Spec Delta

## MODIFIED Requirements

### Requirement: announcements 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Announcement`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。`Announcement` MUST NOT 持久化 `created_by`、`creator` 或指向 `users.id` 的创建者外键。公告列表与详情出参 MUST NOT 包含 `created_by`。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键，且不存在 `created_by` 字段或 `creator` 关系

#### Scenario: 创建者删除后保留公告

- **WHEN** 删除一条历史公告所记录的操作员用户
- **THEN** 该公告行及其标题、正文、原始正文、目标、状态、计数、时间、来源草稿和历史模板引用 SHALL 原样保留，重发仍使用公告已保存内容

#### Scenario: 公告出参不含创建者

- **WHEN** 客户端查询公告列表或公告详情
- **THEN** 每个公告对象 MUST NOT 包含 `created_by`，其他既有字段与分页形状保持不变

## ADDED Requirements

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

### 本次附录变更

- 删除 `created_by` 字段、引用 `users.id` 的外键与 `creator` 关系。
- 其余字段不变。

