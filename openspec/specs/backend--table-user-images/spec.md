# user_images

## Purpose

定义镜像 CUSTOM 可见名单的持久化授权关联、唯一配对和整组更新语义。查看授权不转移创建者归属，不赋予编辑方法权限，也不扩大仅看我创建的筛选结果。

## Requirements

### Requirement: user_images 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `UserImage`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: user_images 生产职责与生命周期

user_images SHALL 保存唯一 user_id/image_id 的 CUSTOM 查看授权配对，名单仅在 custom 范围下可管理，private/everyone 不依该名单决定可见性。创建者保有自己的资源归属，名单增删 MUST NOT 转让所有权、授予编辑方法能力或扩大“仅看我的”结果。

#### Scenario: 整组更新名单
- **WHEN** 镜像范围为 custom 且用户 ids 均有效
- **THEN** 落定去重后的查看授权集合；非 custom 范围的名单变更仍被服务拒绝

#### Scenario: 授权别人查看
- **WHEN** 创建者把另一用户加入 CUSTOM 名单
- **THEN** 对方可在满足方法权限时查看或使用该镜像，但镜像不会成为对方创建的资源，原所有权不变

## Data model appendix

### user_images 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 8 |
| `user_id` | `db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)` | 9 |
| `image_id` | `db.Column(db.Integer, db.ForeignKey('images.id', ondelete='CASCADE'), nullable=False, index=True)` | 10 |
| `granted_at` | `db.Column(db.DateTime, default=db.func.now(), nullable=False)` | 11 |

### 表级约束

表级约束：
- `(db.UniqueConstraint('user_id', 'image_id', name='uq_user_images_user_image'),)`

## Source references

- [models/userimage.py](../../../models/userimage.py)：UserImage，第 5 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；运行结果以当前隔离安全套件为准。
