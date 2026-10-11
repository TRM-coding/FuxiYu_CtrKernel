# images

## Purpose

可维护的镜像模板与可见范围。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: images 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Image`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: images 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：删除为 disabled；可见性仅由 valid_range(private/everyone/custom) 判定，custom 名单在 user_images；创建容器只使用 ready 模板并保存 image_id。

#### Scenario: 模板停用

- **WHEN** 用户通过删除门户停用模板
- **THEN** 保留历史模板行及来源，普通列表和新建选择过滤 disabled

### Requirement: images 模板名称唯一性

模板名称的唯一性 SHALL 由应用层保证，且只约束「未停用」的模板之间：`name` 列 MUST NOT 依赖数据库唯一约束；创建与改名 SHALL 在写入前查重，命中未停用同名模板 SHALL 拒绝。

#### Scenario: 同名判定只看未停用

- **WHEN** 创建一个与某个已停用模板同名的模板
- **THEN** 允许创建；与未停用模板同名则拒绝

### Requirement: images 模板启停与构建记录失效

模板停用 SHALL 可逆：重新启用 SHALL 走更新门户（`status` 在可更新字段白名单内），MUST NOT 为启用而新建一行；模板的归属标识 SHALL 在其整个生命周期内不改变。停用 SHALL 只挡「用于新建」，管理路径与恢复链路 SHALL 仍能按主键读到停用行，MUST NOT 因停用让历史容器与历史构建记录失去可读性。模板被更新时 SHALL 在同一事务内删除该模板在所有机器上的构建记录，使后续派发重新解析并插入标签与版本戳；Node 是否跳过构建仍由本机 Docker 标签查验决定。

#### Scenario: 停用后可重新启用

- **WHEN** 管理员对已停用模板执行启用
- **THEN** 同一行的 `status` 回到可用状态、归属标识不变；此前依据该模板创建的容器与构建记录仍能读出模板内容

#### Scenario: 模板更新促使机器重建

- **WHEN** 模板被更新
- **THEN** 该模板在所有机器上的构建记录在同一事务内被删除，后续派发重新解析并写入版本戳与标签，Node 根据本机 Docker 标签查验决定是否构建

### Requirement: images 内置模板幂等收敛

内置模板 SHALL 由幂等 seed 写入：同名已存在 SHALL 跳过、MUST NOT 覆盖人工修改；内置模板改过名时 SHALL 按旧名集合找回那条系统行（限定 `created_by_user_id` 为空）就地改名并同步 FROM，MUST NOT 插入新行，且 MUST NOT 覆盖管理员已设置的停用状态；名称查重在此处 SHALL 使用不过滤停用的名称原语，以免停用行被查漏而插入第二个同名模板。

#### Scenario: 内置模板改名收敛

- **WHEN** 内置模板在代码中的名称变化后再次启动 seed
- **THEN** 按旧名找回那条系统行就地改名并同步 FROM，保留原归属标识与原停用状态，不新增行；重复执行结果不变

## Data model appendix

### images 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 16 |
| `name` | `db.Column(db.String(120), nullable=False, index=True)` | 21 |
| `description` | `db.Column(db.String(500), nullable=True)` | 22 |
| `base_image` | `db.Column(db.String(255), nullable=False)` | 23 |
| `dockerfile_body` | `db.Column(db.Text, nullable=False, default='')` | 24 |
| `entrypoint` | `db.Column(db.String(255), nullable=True)` | 36 |
| `valid_range` | `db.Column(db.Enum(ImageValidRange, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=ImageValidRange.CUSTOM)` | 44 |
| `status` | `db.Column(db.Enum(ImageStatus, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=ImageStatus.DRAFT)` | 49 |
| `created_by_user_id` | `db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)` | 54 |
| `created_at` | `db.Column(db.DateTime, default=db.func.now(), nullable=False)` | 60 |
| `updated_at` | `db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now(), nullable=False)` | 61 |

## Source references

- [models/image.py](../../../models/image.py)：Image，第 7 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

