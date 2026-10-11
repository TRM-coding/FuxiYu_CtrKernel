# announcement_templates

## Purpose

公告主题和正文模板。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: announcement_templates 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `AnnouncementTemplate`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: announcement_templates 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：模板按 category 分类；name 唯一，SYSTEM 模板删除被拒绝；正文由编辑器取用，当前没有模板变量渲染器。

#### Scenario: 读取模板

- **WHEN** 编辑器选取模板
- **THEN** 返回 subject_template 和 body_template；历史来源 id 作为追溯信息

## Data model appendix

### announcement_templates 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 48 |
| `name` | `db.Column(db.String(120), unique=True, nullable=False)` | 49 |
| `category` | `db.Column(db.Enum(AnnouncementTemplateCategory, values_callable=lambda obj: [e.value for e in obj]), default=AnnouncementTemplateCategory.CUSTOM, nullable=False)` | 50 |
| `description` | `db.Column(db.String(500), nullable=True)` | 55 |
| `subject_template` | `db.Column(db.String(200), nullable=False)` | 56 |
| `body_template` | `db.Column(db.Text, nullable=False)` | 57 |
| `source_announcement_id` | `db.Column(db.Integer, nullable=True)` | 58 |
| `created_by` | `db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)` | 59 |
| `created_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow)` | 60 |
| `updated_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)` | 61 |

## Source references

- [models/announcement.py](../../../models/announcement.py)：AnnouncementTemplate，第 45 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

