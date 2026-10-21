# container_cleanup_reminders

## Purpose

短期容器清理周期内提醒档位的发送记录。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: container_cleanup_reminders 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `ContainerCleanupReminder`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: container_cleanup_reminders 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：每个 container_id 只有一条当前提醒记录；reminder_key 精确判重；真实 SSH 登录时间变化把提醒重置为 NEVER；cleanup_at/sent_at 为当次审计快照。

#### Scenario: 同档提醒判重

- **WHEN** 同一周期已发送当前 reminder_key
- **THEN** 不重复投递该档提醒；清理时间顺延不单独触发重发

## Data model appendix

### container_cleanup_reminders 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True, autoincrement=True)` | 13 |
| `container_id` | `db.Column(db.Integer, nullable=False, index=True)` | 14 |
| `reminder_key` | `db.Column(db.String(32), nullable=False)` | 19 |
| `cleanup_at` | `db.Column(db.DateTime, nullable=False)` | 21 |
| `recipient_email` | `db.Column(db.String(120), nullable=False)` | 22 |
| `sent_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)` | 23 |

### 表级约束

表级约束：
- `(db.UniqueConstraint('container_id', 'recipient_email', name='uq_container_cleanup_reminder_once'),)`

## Source references

- [models/container_cleanup_reminder.py](../../../models/container_cleanup_reminder.py)：ContainerCleanupReminder，第 10 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

