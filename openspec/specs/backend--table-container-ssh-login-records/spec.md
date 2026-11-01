# container_ssh_login_records

## Purpose

按机器及容器记录真实 SSH 登录锚点。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: container_ssh_login_records 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `ContainerSSHLogin`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: container_ssh_login_records 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：WSS last_ssh 快照更新真实登录时间；没有新观测保留旧值；登录变化清零补偿并复位清理提醒；软删查询排除无效容器。

#### Scenario: 机器不可用补偿

- **WHEN** 机器不可用窗口结束
- **THEN** 累加 deferral_seconds；清理倒计时扣除不可用时间，真实登录锚点保持不变

## Data model appendix

### container_ssh_login_records 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `machine_id` | `db.Column(db.Integer, db.ForeignKey('machines.id', ondelete='CASCADE'), primary_key=True, nullable=False, index=True)` | 9 |
| `container_id` | `db.Column(db.Integer, db.ForeignKey('containers.id', ondelete='CASCADE'), primary_key=True, nullable=False, index=True)` | 16 |
| `last_ssh_login_time` | `db.Column(db.String(255), nullable=True)` | 24 |
| `deferral_seconds` | `db.Column(db.Integer, nullable=True, default=0)` | 27 |
| `updated_at` | `db.Column(db.DateTime, nullable=False, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)` | 28 |

## Source references

- [models/container_ssh_login.py](../../../models/container_ssh_login.py)：ContainerSSHLogin，第 5 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

