# announcement_drafts

## Purpose

公告编辑草稿及创建者归属。本规格按表结构记录当前持久化与生命周期契约，字段声明以模型与服务为依据。未完成问题见 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: announcement_drafts 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `AnnouncementDraft`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。草稿 SHALL 保留 `created_by` 与 `creator`，其 `created_by` 外键 SHALL 指向 `users.id` 并声明 `ON DELETE CASCADE`；草稿 MUST NOT 恢复模板持久关联。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，`created_by` 是稳定用户主键且 `creator` 对应当前用户，不把关联展示名替代稳定主键

#### Scenario: 草稿创建者外键为级联删除

- **WHEN** 检查新建 SQLite 库或迁移后 MySQL 库的 `announcement_drafts.created_by` 外键
- **THEN** 该外键引用 `users.id` 且删除规则为 `ON DELETE CASCADE`，不是 `SET NULL`、`RESTRICT` 或无动作

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

### Requirement: 草稿私有归属继续隔离

公告草稿 SHALL 继续以 `created_by` 作为私有归属。列表、按 id 读取、更新、删除和批量发送 SHALL 只允许该创建者操作；普通操作员权限 MUST NOT 授予访问他人草稿的能力。草稿详情与列表 SHALL 继续返回稳定 `created_by` 主键，但该字段 MUST NOT 被删除或改成可空、共享或仅展示字段。

#### Scenario: 他人草稿不可读写删发

- **WHEN** 操作员通过他人的 `draft_id` 读取、更新、删除或批量发送草稿
- **THEN** 请求按既有语义被拒绝，原草稿的创建者、内容、目标和状态不变，也不留下新的发送中公告

#### Scenario: 所属者仍可读写自己的草稿

- **WHEN** 草稿创建者列出、读取、更新或删除自己的草稿
- **THEN** 操作成功，详情与列表返回该草稿的 `created_by` 稳定主键，内容仍为该创建者的独立快照

### Requirement: 用户删除级联所属草稿

删除用户成功时，系统 SHALL 在同一最终数据库事务内通过 `announcement_drafts.created_by` 的 `ON DELETE CASCADE` 删除该用户所属的全部草稿。删除事务失败 MUST 回滚用户、认证记录和草稿的全部变化；其他用户草稿、公告和公告模板 MUST 保留。该清理 MUST 只作用于目标用户，MUST NOT 新增手工删除旁路或后台补偿任务。

#### Scenario: 成功删除只清理目标用户草稿

- **WHEN** 删除一个拥有多篇草稿且无阻塞容器的用户，同时其他用户拥有草稿、公告和模板
- **THEN** 目标用户、其认证记录和所属草稿均不存在；其他用户草稿、全部公告和模板及其内容保持存在

#### Scenario: 最终事务失败整体回滚

- **WHEN** 最终删除事务在用户行及所属草稿已进入级联删除后发生失败
- **THEN** 用户、认证记录和所属草稿全部保持删除前状态，其他用户草稿、公告和模板不受影响

#### Scenario: 无草稿用户仍可删除

- **WHEN** 删除一个没有草稿且无阻塞容器的用户
- **THEN** 删除成功，不因不存在级联草稿而报错

## Data model appendix

### announcement_drafts 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 75 |
| `title` | `db.Column(db.String(200), nullable=False)` | 76 |
| `content` | `db.Column(db.Text, nullable=False)` | 77 |
| `raw_content` | `db.Column(db.Text, nullable=True)` | 78 |
| `created_by` | `db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)` | 79 |
| `targets` | `db.Column(db.Text, nullable=True)` | 80 |
| `created_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow)` | 81 |
| `updated_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)` | 82 |


旧库兼容：启动升级先清空历史模板引用，再尝试删除旧 template_id 列；无法删列时允许保留全空的兼容列，新模型和保存流程均不使用它。

## Source references

- [models/announcement.py](../../../models/announcement.py)：AnnouncementDraft，第 69 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[test/announcement/test_draft_ownership.py](../../../test/announcement/test_draft_ownership.py)；运行结果以当前隔离安全套件为准。
