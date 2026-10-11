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

### Requirement: containers 镜像归属与平台解析

系统 SHALL 以 `image_id` 作为容器镜像归属的唯一身份来源（外键指向 `images.id`，可空），MUST NOT 从镜像标签字符串反解归属。

运行镜像 SHALL 一律由平台按模板解析，请求体携带的镜像名（含旧通路的 `image` / `IMAGE`）MUST NOT 被采信。

#### Scenario: 运行镜像由平台解析

- **WHEN** 创建或恢复的请求体里带了镜像名
- **THEN** 下发的运行镜像一律是平台按归属与版本戳解析出的目标，请求体中的值被忽略

### Requirement: containers 构建版本戳与运行标签

系统 SHALL 以 `last_build_at` 记录本次运行标签的版本戳：缓存命中时取该机器上 `machine_image.created_at`，现造时取派发时刻；它与标签同源同生，容器行照抄。运行镜像标签 SHALL 由 `image_id` 与 `last_build_at` 推导并 MUST NOT 落库；两者缺一时 SHALL 返回空值，MUST NOT 用当前时间等替代值拼出标签。容器是否落后于模板 SHALL 由 `last_build_at` 早于模板当前版本（`images.updated_at`）判定，MUST NOT 用容器 `created_at` 参与该判定。

#### Scenario: 落后判据只看版本戳

- **WHEN** 容器的 `last_build_at` 早于其模板的当前版本
- **THEN** 判定为落后；`created_at` 不参与判定，按最新模板恢复过的容器不因创建时间早被误判

#### Scenario: 标签推导不出时不编造

- **WHEN** 容器的 `image_id` 或 `last_build_at` 缺失
- **THEN** 运行镜像标签推导为空值；不落库，也不用当前时间顶替缺失的输入拼出一个从未存在过的标签

### Requirement: containers 构建配方留痕与运行基底展示

本次构建的配方 SHALL 以输入留痕在容器行上：`base_image`（FROM 段）与 `dockerfile_body`（业务片段）；渲染后的完整文本与平台注入 MUST NOT 落库，平台注入 SHALL 在每次渲染时取自当下的系统设置。判「有无留痕」SHALL 以 `base_image` 是否为空为准。运行基底的展示 SHALL 一律取该容器留痕渲染，MUST NOT 依据新鲜度改取当前模板。

#### Scenario: 运行基底展示不随模板编辑失真

- **WHEN** 模板被编辑后查询一个依据旧版本构建的容器的运行基底
- **THEN** 返回由该容器 `base_image`、`dockerfile_body` 与当下平台注入渲染出的内容；仅无留痕的存量容器回落当前模板，既无留痕又无归属时返回空值

### Requirement: containers 恢复内容来源选择

恢复软删容器 SHALL 以容器留痕为前提；内容来源按归属与模板状态判定：归属为空或模板非 READY 时取容器留痕；模板 READY 且容器不落后时取当前模板；模板 READY 但容器落后且未指定内容来源时 SHALL 返回选择响应而不执行恢复；指定容器留痕时取留痕，显式指定 `content_source=template` 时取当前模板。恢复 SHALL 刷新 `last_build_at` 与配方留痕，使其反映本次实际采用的内容。

#### Scenario: 内容会变时先交回两份

- **WHEN** 容器落后于模板且调用方未指定内容来源
- **THEN** 不执行恢复，响应带 `requires_choice=true`、两份内容与按配方分段（不含平台注入段）的差异，且 `container_id` 为空

### Requirement: containers 恢复挂载与数据位置

恢复的挂载行为 SHALL 与内容来源无关：两种来源取同一挂载路径与同一数据位置；容器改名 MUST NOT 改变数据位置。

#### Scenario: 恢复来源与改名不迁移数据

- **WHEN** 调用方选择任一内容来源恢复容器，并调整容器名称
- **THEN** 恢复使用同一挂载路径和数据位置，容器改名不改变数据位置

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

