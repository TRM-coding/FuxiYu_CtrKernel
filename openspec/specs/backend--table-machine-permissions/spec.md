# machine_permissions

## Purpose

用户获得某机器资源访问权的关联表。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: machine_permissions 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `MachinePermission`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: machine_permissions 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：唯一配对 user_id/machine_id；权限检查实时查询，添加为幂等语义，移除立即影响后续资源鉴权；机器和用户外键声明 CASCADE。

#### Scenario: 重复授权

- **WHEN** 对已有 user_id/machine_id 再次授权
- **THEN** 保持一条有效配对，不创建重复资源权限

## Data model appendix

### machine_permissions 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 7 |
| `machine_id` | `db.Column(db.Integer, db.ForeignKey('machines.id', ondelete='CASCADE'), nullable=False, index=True)` | 8 |
| `user_id` | `db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)` | 9 |

### 表级约束

表级约束：
- `(db.UniqueConstraint('machine_id', 'user_id', name='uq_machine_permissions_machine_user'),)`

## Source references

- [models/machine_permission.py](../../../models/machine_permission.py)：MachinePermission，第 4 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

