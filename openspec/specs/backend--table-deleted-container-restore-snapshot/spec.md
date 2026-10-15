# deleted_container_restore_snapshot

## Purpose

删除后用于复活的配置和挂载目录保留记录。本规格按表结构记录当前持久化与生命周期契约，字段声明以模型与服务为依据。未完成问题见 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: deleted_container_restore_snapshot 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `DeletedContainerRestoreSnapshot`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: deleted_container_restore_snapshot 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：snapshot 保存重建输入；mount_cleaned 标识挂载目录可复用性；保留窗口加 deferral_seconds；恢复成功删除一次性快照及对应清理记录。

#### Scenario: 完成复活

- **WHEN** 恢复门户成功重建容器并完成账号还原
- **THEN** 消费恢复快照并清除对应挂载清理记录，避免同一快照被再次使用

### Requirement: 长期配额失败保留可重试恢复状态

长期容量校验 SHALL 在真正恢复操作的副作用之前进行。容量不足时 MUST NOT 复活容器、请求 Node 创建、消费恢复快照或清除挂载保留记录；调用方 SHALL 收到明确的超限失败，不能靠事后静默丢弃长期标记收尾。

#### Scenario: 失败后仍可恢复
- **WHEN** 长期恢复因数量已满而被拒绝
- **THEN** 原容器保持已删除，恢复快照及挂载清理记录保留；释放配额后可以重试

#### Scenario: 完成长期恢复
- **WHEN** 有容量且恢复成功
- **THEN** 长期标记和账号按快照恢复，并沿用原有成功时消费快照的规则

## Data model appendix

### deleted_container_restore_snapshot 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 11 |
| `original_container_id` | `db.Column(db.Integer, nullable=False, index=True)` | 12 |
| `container_name` | `db.Column(db.String(120), nullable=False)` | 13 |
| `machine_id` | `db.Column(db.Integer, nullable=True, index=True)` | 14 |
| `mount_cleanup_id` | `db.Column(db.Integer, nullable=True, index=True)` | 15 |
| `removed_trigger` | `db.Column(db.String(64), nullable=False, default='api')` | 16 |
| `snapshot` | `db.Column(db.JSON, nullable=False)` | 17 |
| `removed_at` | `db.Column(db.DateTime, nullable=False, default=dt.datetime.utcnow, index=True)` | 18 |
| `mount_cleaned` | `db.Column(db.Boolean, nullable=False, default=False, server_default=db.text('0'), index=True)` | 19 |
| `deferral_seconds` | `db.Column(db.Integer, nullable=True, default=0, server_default=db.text('0'))` | 23 |

### 表级约束

表级约束：
- `(db.Index('idx_deleted_container_removed', 'removed_at'),)`

## Source references

- [models/deleted_container_restore_snapshot.py](../../../models/deleted_container_restore_snapshot.py)：DeletedContainerRestoreSnapshot，第 8 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[test/container/test_restore_long_term_capacity.py](../../../test/container/test_restore_long_term_capacity.py)；运行结果以当前隔离安全套件为准。
