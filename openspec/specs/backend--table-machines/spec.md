# machines

## Purpose

宿主机身份、信任锚、硬件事实及分配上限。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: machines 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Machine`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: machines 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：Node 注册固定 uid 和证书指纹；port=NULL 使用全局 Node 端口；gpu_list 为硬件事实、gpu_allow_list 为管理许可；WSS 更新状态、硬件和 last_seen_at。

#### Scenario: 维护或离线窗口

- **WHEN** 机器进入不可用状态后再次可用
- **THEN** 记录 unavailable_since，结束时为 SSH 清理、冻结和删除挂载保留窗口累加补偿

## Data model appendix

### machines 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 8 |
| `machine_name` | `db.Column(db.String(120), unique=True, nullable=False, index=True)` | 9 |
| `machine_ip` | `db.Column(db.String(120), unique=True, nullable=False, index=True)` | 10 |
| `port` | `db.Column(db.Integer, nullable=True)` | 14 |
| `machine_type` | `db.Column(db.Enum(MachineTypes), nullable=False)` | 15 |
| `machine_status` | `db.Column(db.Enum(MachineStatus, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=MachineStatus.ONLINE)` | 16 |
| `is_maintenance` | `db.Column(db.Boolean, nullable=False, default=False)` | 21 |
| `cpu_core_number` | `db.Column(db.Integer, nullable=True)` | 22 |
| `memory_size_gb` | `db.Column(db.Integer, nullable=True)` | 23 |
| `gpu_number` | `db.Column(db.Integer, nullable=True)` | 24 |
| `gpu_type` | `db.Column(db.String(120), nullable=True)` | 25 |
| `gpu_list` | `db.Column(db.JSON, nullable=True)` | 29 |
| `gpu_allow_list` | `db.Column(db.JSON, nullable=True)` | 30 |
| `max_shared_gb` | `db.Column(db.Integer, nullable=True)` | 31 |
| `disk_size_gb` | `db.Column(db.Integer, nullable=True)` | 32 |
| `machine_description` | `db.Column(db.String(500), nullable=True)` | 33 |
| `max_memory_gb` | `db.Column(db.Integer, nullable=True)` | 34 |
| `max_cpu_core_number` | `db.Column(db.Integer, nullable=True)` | 35 |
| `max_disk_size_gb` | `db.Column(db.Integer, nullable=True)` | 38 |
| `node_uid` | `db.Column(db.String(128), unique=True, nullable=True, index=True)` | 43 |
| `node_cert_fingerprint` | `db.Column(db.String(128), unique=True, nullable=True, index=True)` | 44 |
| `cert_pinned_at` | `db.Column(db.DateTime, nullable=True)` | 45 |
| `collect_error_at` | `db.Column(db.DateTime, nullable=True)` | 49 |
| `unavailable_since` | `db.Column(db.DateTime, nullable=True)` | 52 |
| `last_seen_at` | `db.Column(db.DateTime, nullable=True)` | 57 |

## Source references

- [models/machine.py](../../../models/machine.py)：Machine，第 5 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

