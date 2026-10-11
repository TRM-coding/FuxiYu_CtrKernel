# containers

## Purpose

容器身份、资源配置、软删标记及运行快照。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: containers 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Container`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: containers 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：Ctrl DB id 为页面与 API 的身份；删除保留无效行并生成恢复快照；Node WSS 状态对账更新运行事实，详情合成 effective_status。

#### Scenario: 创建资源校验

- **WHEN** 创建请求包含 CPU、内存、共享内存、GPU 数量
- **THEN** 依机器允许上限校验；共享内存不得超过此次请求内存，失败返回 invalid_config 和具体资源数值

## Data model appendix

### containers 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 10 |
| `created_at` | `db.Column(db.DateTime, nullable=True)` | 11 |
| `name` | `db.Column(db.String(120), nullable=False)` | 12 |
| `is_valid` | `db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('1'))` | 13 |
| `deleted_at` | `db.Column(db.DateTime, nullable=True)` | 14 |
| `deleted_trigger` | `db.Column(db.String(64), nullable=True)` | 15 |
| `deleted_reason` | `db.Column(db.String(255), nullable=True)` | 16 |
| `deleted_by_user_id` | `db.Column(db.Integer, nullable=True)` | 17 |
| `image_id` | `db.Column(db.Integer, db.ForeignKey('images.id'), nullable=True, index=True)` | 24 |
| `last_build_at` | `db.Column(db.DateTime, nullable=True)` | 30 |
| `base_image` | `db.Column(db.String(255), nullable=True)` | 46 |
| `dockerfile_body` | `db.Column(db.Text, nullable=True)` | 47 |
| `entrypoint` | `db.Column(db.String(255), nullable=True)` | 56 |
| `machine_id` | `db.Column(db.Integer, db.ForeignKey('machines.id', ondelete='CASCADE'), nullable=False, index=True)` | 62 |
| `container_status` | `db.Column(db.Enum(ContainerStatus, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=ContainerStatus.CREATING)` | 69 |
| `failed_reason` | `db.Column(db.String(255), nullable=True)` | 74 |
| `failed_detail` | `db.Column(db.Text, nullable=True)` | 75 |
| `status_unknown_since` | `db.Column(db.DateTime, nullable=True)` | 79 |
| `status_source` | `db.Column(db.String(40), nullable=True)` | 80 |
| `port` | `db.Column(db.Integer, nullable=False, index=True)` | 81 |
| `memory_gb` | `db.Column(db.Integer, nullable=False)` | 83 |
| `shared_gb` | `db.Column(db.Integer, nullable=False)` | 84 |
| `gpu_number` | `db.Column(db.Integer, nullable=False)` | 85 |
| `cpu_number` | `db.Column(db.Integer, nullable=False)` | 86 |
| `gpu_chosen_list` | `db.Column(db.JSON, nullable=True)` | 89 |
| `port_mappings` | `db.Column(db.JSON, nullable=True)` | 92 |
| `disk_overlay_rw_bytes` | `db.Column(db.BigInteger, nullable=True)` | 97 |
| `disk_bind_mount_bytes` | `db.Column(db.BigInteger, nullable=True)` | 98 |
| `disk_total_bytes` | `db.Column(db.BigInteger, nullable=True)` | 99 |
| `disk_checked_at` | `db.Column(db.DateTime, nullable=True)` | 100 |
| `bind_mount_path` | `db.Column(db.String(512), nullable=True)` | 104 |

### 表级约束

表级约束：
- `(db.Index('idx_containers_is_valid', 'is_valid'),)`

## Source references

- [models/containers.py](../../../models/containers.py)：Container，第 7 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

