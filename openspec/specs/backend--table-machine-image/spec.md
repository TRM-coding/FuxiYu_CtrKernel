# machine_image

## Purpose

某机器已构建镜像模板版本的缓存记录。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: machine_image 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `MachineImage`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: machine_image 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：machine_id/image_id 配对映射到 image_tag；镜像模板编辑使记录失效，entrypoint 参与最终 Dockerfile 的 ENTRYPOINT 构建段。实际渲染以 image_tasks 为准，模型内仍有旧注释，差异见 Global QUESTIONS。

#### Scenario: 模板构建内容变化

- **WHEN** 模板 Dockerfile 内容更新
- **THEN** 使对应机器构建记录失效，后续创建重新构建所需镜像

## Data model appendix

### machine_image 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 27 |
| `machine_id` | `db.Column(db.Integer, db.ForeignKey('machines.id', ondelete='CASCADE'), nullable=False, index=True)` | 28 |
| `image_id` | `db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False, index=True)` | 31 |
| `image_tag` | `db.Column(db.String(200), nullable=False)` | 34 |
| `created_at` | `db.Column(db.DateTime, default=db.func.now(), nullable=False)` | 35 |

### 表级约束

表级约束：
- `(db.UniqueConstraint('machine_id', 'image_id', name='uq_machine_image_machine_id_image_id'),)`

## Source references

- [models/machine_image.py](../../../models/machine_image.py)：MachineImage，第 6 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

