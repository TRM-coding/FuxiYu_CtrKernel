# announcement_drafts

## Purpose

公告编辑草稿及创建者归属。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: announcement_drafts 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `AnnouncementDraft`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: announcement_drafts 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：列表按 created_by 筛选；保存以 draft_id 创建或更新；批量发送将草稿内容复制为公告，发送线程结束后清理草稿。

#### Scenario: 保存与列出草稿

- **WHEN** 用户创建新草稿
- **THEN** 记录 created_by，按该创建者的列表条件返回草稿；template_id 为可空模板引用

## Data model appendix

### announcement_drafts 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 72 |
| `title` | `db.Column(db.String(200), nullable=False)` | 73 |
| `content` | `db.Column(db.Text, nullable=False)` | 74 |
| `raw_content` | `db.Column(db.Text, nullable=True)` | 75 |
| `created_by` | `db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)` | 76 |
| `targets` | `db.Column(db.Text, nullable=True)` | 77 |
| `template_id` | `db.Column(db.Integer, db.ForeignKey('announcement_templates.id'), nullable=True)` | 78 |
| `created_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow)` | 79 |
| `updated_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)` | 80 |

## Source references

- [models/announcement.py](../../../models/announcement.py)：AnnouncementDraft，第 69 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

