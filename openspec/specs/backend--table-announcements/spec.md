# announcements

## Purpose

公告投递与重发的持久化记录。本规格按表结构记录当前持久化与生命周期契约，字段声明以模型与服务为依据。未完成问题见 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: announcements 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Announcement`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: announcements 生产职责与生命周期

服务 SHALL 使用已校验的私有草稿内容创建 SENDING 公告并保存目标集合；后台顺序投递并回写 SENT/FAILED 及成功、失败计数，启动时收尾中断的发送。公告 SHALL 保留独立正文和当次目标快照，MUST NOT 依赖模板继续存在或在发送时重新套用模板。

#### Scenario: 批量发送受理
- **WHEN** 当前创建者的草稿和目标通过校验
- **THEN** 返回公告 id，后台投递通过计数与状态反馈；source_draft_id、target_snapshot 保留来源与当次解析快照

#### Scenario: 模板已删除
- **WHEN** 公告源自模板填充后的草稿且模板已删除
- **THEN** 仍按公告自身持久化的内容投递或重发，不要求恢复模板引用

## Data model appendix

### announcements 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 18 |
| `title` | `db.Column(db.String(200), nullable=False)` | 19 |
| `content` | `db.Column(db.Text, nullable=False)` | 20 |
| `raw_content` | `db.Column(db.Text, nullable=True)` | 21 |
| `created_by` | `db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)` | 22 |
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
