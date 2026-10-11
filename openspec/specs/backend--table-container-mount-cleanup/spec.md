# container_mount_cleanup

## Purpose

删除容器挂载目录清理的执行记录。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: container_mount_cleanup 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `ContainerMountCleanup`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: container_mount_cleanup 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：deleted 快照为保留生命周期权威，本表保存执行路径、removed_at、cleaned_at、escalation；手动、定时及磁盘升级清理共用服务门户。

#### Scenario: 清理成功

- **WHEN** Node 完成指定挂载目录清理
- **THEN** 在事务中记录 cleaned_at，并同步 deleted 快照的 mount_cleaned

## Data model appendix

### container_mount_cleanup 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 16 |
| `deleted_id` | `db.Column(db.Integer, nullable=True, index=True)` | 17 |
| `container_id` | `db.Column(db.Integer, nullable=False)` | 18 |
| `container_name` | `db.Column(db.String(120), nullable=False)` | 19 |
| `machine_id` | `db.Column(db.Integer, nullable=False)` | 20 |
| `mount_path` | `db.Column(db.String(512), nullable=False)` | 21 |
| `escalation` | `db.Column(db.Boolean, nullable=False, default=False)` | 22 |
| `removed_at` | `db.Column(db.DateTime, nullable=False)` | 23 |
| `cleaned_at` | `db.Column(db.DateTime, nullable=True)` | 24 |

### 表级约束

表级约束：
- `(db.Index('idx_mount_cleanup_pending', 'cleaned_at', 'removed_at'),)`

## Source references

- [models/container_mount_cleanup.py](../../../models/container_mount_cleanup.py)：ContainerMountCleanup，第 13 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

