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

### Requirement: machine_image 派发记录与构建缓存

本表 SHALL 记录 Ctrl 已派发构建的标签与版本戳，MUST NOT 单凭记录存在认定 Docker 制品已成功建成。有效缓存行 SHALL 参与 Ctrl 下次构建标签与版本戳的选择；Node 是否真正跳过构建仍由本机 Docker 标签查验决定。创建请求已被 Node 受理且 Ctrl 已记录派发后，后台构建失败不会自动删除该记录。

#### Scenario: 构建失败也留观测

- **WHEN** 创建请求已被 Node 受理、Ctrl 已记录派发，但后台镜像构建随后失败
- **THEN** 既有派发记录仍保留，不被当作构建成功凭据；后续使用该缓存标签时仍由 Node 查验本机制品

### Requirement: machine_image 复合键与读写入口

检索 SHALL 一律按 `(machine_id, image_id)` 复合键；`image_tag` 只 SHALL 作为值读出，MUST NOT 进入查询谓词、MUST NOT 参与身份判定。

写入 SHALL 只有一个入口且为「有行即返回」：已存在 SHALL 原样返回、MUST NOT 就地改写（改写等于凭空换代，而宿主机上的制品仍挂在旧标签下成为孤儿）；`image_tag` 与其版本戳 SHALL 来自同一次标签解析，MUST NOT 在写入点另取当前时间。删除 SHALL 只有「按模板清理该模板在所有机器上的行」这一个入口，由模板更新在同一事务内调用；该清理 SHALL 宁可多删——改配方之外的编辑（改名、改描述）也一并触发重建。

#### Scenario: 有行即返回不改写

- **WHEN** 对已有 `(machine_id, image_id)` 调用 record_dispatch 写入口
- **THEN** 返回既有行，行内标签与版本戳保持原值，不被改写；构建标签的解析另按新鲜度检查处理

### Requirement: machine_image 缓存新鲜度与失败回退

读取缓存时 SHALL 另有第二道闸：行的时间戳不晚于模板当前版本即视为陈旧，退回现造一条新标签并告警；读表失败同样退回现造，MUST NOT 因此返回错误结果。

#### Scenario: 陈旧行退回现造

- **WHEN** 读到的行时间戳不晚于模板当前版本（删行未生效或有人直连改库）
- **THEN** 不返回该行的标签，退回现造一条新标签并告警，代价仅是一次多余的重建

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

