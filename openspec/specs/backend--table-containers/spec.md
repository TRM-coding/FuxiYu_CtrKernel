# containers

## Purpose

定义容器资源的持久化字段、账号关联、配方留痕、构建版本与恢复行为。区分资源身份与实际制品版本，保持旧容器留痕，并约束恢复内容选择及挂载数据边界。

## Requirements

### Requirement: containers 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Container`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: containers 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：Ctrl DB id 为页面与 API 的身份；删除保留无效行并生成恢复快照；Node WSS 状态对账更新运行事实，详情合成 effective_status。创建容器的共享内存 SHALL 同时受两条上限约束：机器共享上限 `max_shared_gb` 与本次申请的 `MEMORY`；任一越界 MUST 以 `invalid_config` 拒绝并给出具体数值，MUST NOT 只校验其中一条。

#### Scenario: 创建资源校验

- **WHEN** 创建请求包含 CPU、内存、共享内存、GPU 数量
- **THEN** 依机器允许上限校验；共享内存不得超过此次请求内存，失败返回 invalid_config 和具体资源数值

#### Scenario: 共享内存双重上限

- **WHEN** 机器共享上限 16GB、本次申请内存 32GB，而请求共享内存为 20GB
- **THEN** 以 `invalid_config` 拒绝并给出 20 与 16 两个数值；即使 20GB 未超过本次申请内存也不放行

### Requirement: containers 镜像归属与平台解析

系统 SHALL 以 `image_id` 作为容器镜像归属的唯一身份来源（外键指向 `images.id`，可空），MUST NOT 从镜像标签字符串反解归属。

运行镜像 SHALL 一律由平台按模板解析，请求体携带的镜像名（含旧通路的 `image` / `IMAGE`）MUST NOT 被采信。

#### Scenario: 运行镜像由平台解析

- **WHEN** 创建或恢复的请求体里带了镜像名
- **THEN** 下发的运行镜像一律是平台按归属与版本戳解析出的目标，请求体中的值被忽略

### Requirement: containers 构建版本戳与运行标签

系统 SHALL 以 last_build_at 保存本次实际标签的版本戳，与本次配方解析结果同源；缓存命中时复用已选版本，不命中时选择可区分的新版本。运行镜像标签 SHALL 由 image_id 和 last_build_at 推导，MUST NOT 另存入容器行；两者缺一 SHALL 返回空值。恢复是否需要选择内容 SHALL 优先比较容器留痕与当前模板的基础镜像、业务片段及入口命令，MUST NOT 将逻辑递增的构建版本当作模板内容版本。无完整留痕的存量数据才采用构建版本戳与模板更新时间比较，容器 created_at MUST NOT 参与。

#### Scenario: 落后判据只看版本戳
- **WHEN** 存量容器没有可供比较的配方留痕，构建版本戳早于模板当前版本
- **THEN** 时间戳回落判定为落后；不比较容器创建时间。有完整留痕时按内容比较，不适用此回落

#### Scenario: 标签推导不出时不编造
- **WHEN** 容器的 image_id 或 last_build_at 缺失
- **THEN** 运行镜像标签推导为空值，不用当前时间替代缺失输入

#### Scenario: 秒级版本递增不掩盖内容差异
- **WHEN** 容器构建版本因连续换代而晚于当前墙钟，但模板正文随后发生改变
- **THEN** 仍能通过配方比较识别内容不同，恢复前提供内容选择；仅改名或描述不制造内容差异

### Requirement: containers 构建配方留痕与运行基底展示

本次构建的配方 SHALL 以输入留痕在容器行上：`base_image`（FROM 段）与 `dockerfile_body`（业务片段）；渲染后的完整文本与平台注入 MUST NOT 落库，平台注入 SHALL 在每次渲染时取自当下的系统设置。判「有无留痕」SHALL 以 `base_image` 是否为空为准。运行基底的展示 SHALL 一律取该容器留痕渲染，MUST NOT 依据新鲜度改取当前模板。

#### Scenario: 运行基底展示不随模板编辑失真

- **WHEN** 模板被编辑后查询一个依据旧版本构建的容器的运行基底
- **THEN** 返回由该容器 `base_image`、`dockerfile_body` 与当下平台注入渲染出的内容；仅无留痕的存量容器回落当前模板，既无留痕又无归属时返回空值

### Requirement: containers 恢复内容来源选择

恢复软删容器 SHALL 以留痕为前提。归属为空或模板非 READY 时取容器留痕；模板 READY 且模板侧配方相同时可取当前模板；模板侧配方不同时，未指定内容来源 SHALL 返回选择响应而不恢复，指定 snapshot 取留痕，指定 template 取当前模板。两种来源 SHALL 均使用当前平台注入，并按实际最终配方选择标签和刷新 last_build_at，不复用与当前组合不一致的历史标签。

#### Scenario: 内容会变时先交回两份
- **WHEN** 容器留痕与当前 READY 模板内容不同，调用方未指定来源
- **THEN** 不执行恢复，响应带 requires_choice=true、两份内容及不含平台注入的分段差异，container_id 为空

### Requirement: containers 恢复挂载与数据位置

恢复的挂载行为 SHALL 与内容来源无关：两种来源取同一挂载路径与同一数据位置；容器改名 MUST NOT 改变数据位置。

#### Scenario: 恢复来源与改名不迁移数据

- **WHEN** 调用方选择任一内容来源恢复容器，并调整容器名称
- **THEN** 恢复使用同一挂载路径和数据位置，容器改名不改变数据位置

### Requirement: 镜像换代保持容器留痕与关联有效

模板或平台注入换代 SHALL 保留已有容器的 image_id、构建版本、账号绑定和机器关联。新建或恢复实际采用的新配方 MUST 使用与该配方一致的构建标签及留痕，不将旧标签与变化后的平台注入组合；历史版本的查询不能因当前缓存已更新而凭空改为新版本标签。

#### Scenario: 缓存换代后读取旧容器
- **WHEN** 模板缓存已指向新版本，查询旧容器
- **THEN** 旧容器归属及实际版本仍可识别，不被改写为新派发的版本

#### Scenario: 恢复采用历史正文与当前注入
- **WHEN** 恢复使用容器保留的正文，但当前平台注入已变化
- **THEN** 发送与该实际组合一致的构建版本，不因旧标签已存在而跳过新组合的构建

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
- 共享内存双重上限校验：[`repositories/containers_repo.py`](../../../repositories/containers_repo.py) `validate_shared_request`，第 420-448 行（机器共享上限 + 本次申请内存）；回归见 [`test/container/test_container_shared_memory_limit.py`](../../../test/container/test_container_shared_memory_limit.py)。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；运行结果以当前隔离安全套件为准。
