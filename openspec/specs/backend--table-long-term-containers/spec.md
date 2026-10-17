# long_term_containers

## Purpose

容器长期保留标记及授权者审计。本规格按表结构记录当前持久化与生命周期契约，字段声明以模型与服务为依据。未完成问题见 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)。

## Requirements

### Requirement: long_term_containers 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `LongTermContainer`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: long_term_containers 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：以 container_id 唯一存在表示长期标记；服务执行配额和磁盘条件校验；移除标记后恢复短期清理策略。

#### Scenario: 重复标记

- **WHEN** 同一容器再次申请长期标记
- **THEN** 不生成第二条长期记录，容器身份通过主键保持唯一

### Requirement: 恢复长期标记遵守数量限额

恢复快照中的长期标记 SHALL 使用与普通设置入口一致的配额主体、计数口径和豁免规则；需要新增标记时 MUST 先校验容量。已存在标记 SHALL 保持幂等，非长期快照 SHALL 不新增标记。超限 SHALL 返回长期容器数量限制的具体失败原因及相关数量，不静默跳过标记。

#### Scenario: 长期限额已满
- **WHEN** 限额为 1 且计数主体已有 1 个长期容器，又尝试恢复一个长期容器
- **THEN** 拒绝新增长期标记并向调用方报告已用数量及上限，不产生第 2 个长期容器

#### Scenario: 幂等与普通快照
- **WHEN** 恢复目标已具有长期标记，或快照没有长期标记
- **THEN** 已存在的标记不重复计数，普通快照不因长期配额已满而被拒绝

## Data model appendix

### long_term_containers 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `container_id` | `db.Column(db.Integer, db.ForeignKey('containers.id', ondelete='CASCADE'), primary_key=True, nullable=False)` | 9 |
| `created_by_user_id` | `db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)` | 15 |
| `created_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)` | 21 |

## Source references

- [models/long_term_container.py](../../../models/long_term_container.py)：LongTermContainer，第 6 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[test/container/test_restore_long_term_capacity.py](../../../test/container/test_restore_long_term_capacity.py)；运行结果以当前隔离安全套件为准。
