# containers

## Purpose

定义容器资源的持久化字段、账号关联、配方留痕、构建版本与恢复行为。区分资源身份与实际制品版本，保持旧容器留痕，并约束恢复内容选择及挂载数据边界。

## Requirements

### Requirement: containers 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Container`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。磁盘事实 SHALL 仅使用既有 `disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_total_bytes`、`disk_checked_at` 和 `bind_mount_path` 表达；MUST NOT 新增磁盘观测/身份列，也 MUST NOT 以 JSON、日志或其他表替代磁盘业务状态。`bind_mount_path` 是唯一业务路径；`disk_checked_at` 是最后被接受的测量时间（旧 Node 可保存接收时间兼容值），收到时间、拒绝原因和路径诊断只用于日志或进程内，不新增表列。字段定义见主 spec 数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

#### Scenario: 不新增观测列

- **WHEN** 实现本变更
- **THEN** 不为 `disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation` 或 `disk_identity_*` 新增列；路径修正只使用既有 `bind_mount_path`，测量时间只使用既有 `disk_checked_at`，且不新增迁移

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

### Requirement: 名称缺席不构成删除依据

Ctrl SHALL 将非空容器状态快照中缺少某个有效记录、或仅含容器名称的 Node `delete` 帧，视为待核实线索，不得仅凭此将该记录软删除或清理账号绑定、长期标记及恢复信息；待核实应以独立标记表达，不改变记录有效性。创建和启动过渡态 MUST 受到同等保护。

#### Scenario: 创建受理后快照缺席

- **WHEN** Ctrl 已有 `creating` 记录，而一帧非空状态快照暂不包含该名称
- **THEN** Ctrl 保留有效记录和关联，设置待核实标记，并记录线索来源

#### Scenario: 运行中容器快照暂时缺席

- **WHEN** 容器在 Ctrl 与 Node 都处于 online，某一帧非空状态快照暂不包含该名称
- **THEN** Ctrl 保留有效记录、账号绑定和长期标记，设置待核实标记且不生成成功删除审计

#### Scenario: 旧代名称删除帧

- **WHEN** Ctrl 收到只含机器和名称的 `delete` 帧，当前同名有效记录仍存在
- **THEN** Ctrl 不软删除该记录，保留其关联并设置待核实标记

### Requirement: 不可判定采集不制造消失

Ctrl SHALL 区分采集失败、空快照和非空快照中的名称缺席；采集失败或空快照不得被当作任何容器消失的证据，不得清除既有可用记录。

#### Scenario: Node 采集错误

- **WHEN** Node 的状态快照携带 `collect_error`
- **THEN** Ctrl 记录机器采集异常，不对容器执行消失处理

### Requirement: 正向观察清除待核实状态

Ctrl SHALL 在同一机器、同一有效记录再次出现在 Node 状态快照并给出可映射的明确状态时，按该快照更新状态并清除本次缺席引起的待核实标记；unknown 或过渡态不得清除该标记。不同机器或已软删除的历史同名记录不得因此复活。

#### Scenario: 容器重新出现在快照

- **WHEN** 此前因快照缺席被标记待核实的有效容器再次出现在同机状态快照中，并给出明确运行状态
- **THEN** Ctrl 保留原数据库 ID，更新实际状态并清除待核实标记

#### Scenario: 重新出现但状态仍未知

- **WHEN** 此前待核实的容器再次出现，但快照状态为 unknown 或仍在过渡态
- **THEN** 保留待核实标记，不把它当作已恢复或已删除

### Requirement: 消失线索可追溯

Ctrl SHALL 记录待核实线索的机器、容器、来源（显式 `delete` 帧或快照缺席，二者可区分）和观察时间；该记录不得冒充成功删除操作审计，也不得只用单一的 `node_vanished` 概括两条路径。

#### Scenario: 两种线索先后到达

- **WHEN** 同一容器先收到 `delete` 帧，再在快照中缺席
- **THEN** 诊断记录可区分两种线索，容器仍保持有效且不会出现成功删除审计

### Requirement: Node 路径修正与业务路径

Ctrl SHALL 只消费 Node 校正后的 `bind_mount_path` 作为业务路径；dev/inode/PID MUST NOT 进入 Ctrl 持久化、比较或业务门禁。Ctrl SHALL 仅对当前认证机器上的活跃容器应用修正：`resolved` 且路径非空时更新；`no_bind` 时清空并允许同帧 overlay-only；`unresolved`/`not_running`/路径空/字段缺失时保留已有或最后确认路径，不清空、不猜测、不写 `/proc`。`mount_path_status` 只用于更新/保留/清空，不是测量或业务门禁。不带 `mount_path_status` 的旧 Node 帧 MUST NOT 改写或清空已有路径；当前路径为空且帧内路径非空时可建立该路径并按接收时间接收测量（新 Node 已明确 no_bind 的容器除外），这是旧协议兼容而非 Node 校正。路径修正 MUST NOT 按 inode 批量改写历史恢复快照、旧清理记录或其他机器记录。

#### Scenario: resolved 路径修正

- **WHEN** 当前认证机器上的活跃容器本次路径核对为 resolved，Node 返回校正后的 `bind_mount_path`
- **THEN** Ctrl 将该业务路径持久化到当前容器；不保存、不比较 dev/inode/PID，也不因该状态单独授权任何业务动作

#### Scenario: 原有 bind 路径转为明确 no_bind

- **WHEN** 当前活跃容器原有 `bind_mount_path`，随后成功 Docker 观测明确 no_bind，Node 返回 `bind_mount_path=null`、`mount_path_status=no_bind`
- **THEN** Ctrl 同步清空 `containers.bind_mount_path`；overlay 组成完整且测量时间有效时允许按 overlay-only 写入新测量；旧 bind 字节/旧路径样本不进入新测量

#### Scenario: unresolved 只保留路径不清空

- **WHEN** 路径核对为 unresolved，Node 保留已有/最后确认路径，且该路径测量成功、组成完整
- **THEN** Ctrl 保留 `bind_mount_path`，按测量事实判断是否接收；不得因 `mount_path_status=unresolved` 阻断同路径有效测量，也不得清空或把诊断失败写成测量失败

#### Scenario: 旧 Node 不改写已校正路径

- **WHEN** 当前业务路径已由新 Node 校正为 B，随后收到不带 `mount_path_status` 的旧 Node 帧，其 `bind_mount_path` 为 A
- **THEN** Ctrl 保留 B，不用 A 覆盖路径，也不把 A 的字节贴到 B；该路径不一致帧的测量被拒绝，旧帧的兼容接收条件仍按本规格其他场景执行

#### Scenario: 旧 Node 首次建立路径

- **WHEN** 当前 `bind_mount_path` 为空，旧 Node 帧带来非空路径 A 和完整测量
- **THEN** Ctrl 可建立 A 并按接收时间语义接收测量，用于兼容旧 Node 新建容器；这是旧协议兼容而非 Node 校正，后续新 Node 的 `resolved` 修正仍可覆盖，旧帧不得再改写 A

#### Scenario: no_bind 后旧 Node 不得重建路径

- **WHEN** 新 Node 已明确 no_bind 清空路径，随后收到旧 Node 帧带非空路径 A
- **THEN** 进程内 no_bind 保护拒绝重建 A，保留空路径并拒绝该帧测量；不得因此新增持久化列

#### Scenario: 路径修正不批量改历史

- **WHEN** 某容器路径从旧 Source 修正为新业务路径
- **THEN** 只更新该活跃容器；既有恢复快照、旧清理记录和其他机器记录保持各自路径，不按 inode 追溯改写

### Requirement: 磁盘测量接收与路径一致性

Ctrl SHALL 在更新有效字节和测量时间前同时确认：样本来自当前认证机器/当前活跃容器；`total_bytes` 非空、overlay 非空、当前路径非空时 bind 字节非空，当前路径为空时只有 `mount_path_status=no_bind` 才允许 overlay-only；帧内业务路径与当前业务路径一致（路径修正帧先落路径，再判断测量）；`measured_at` 存在时格式有效且不在未来超过允许时钟偏差；缺少 `measured_at` 的旧 Node 帧只在当前路径为空且帧内路径非空（兼容建立）或当前路径非空且帧内路径一致时按接收时间兼容。失败、缺组成、路径不一致或时间无效 MUST NOT 刷新 `disk_checked_at`、MUST NOT 写入 0 或把旧值标成新测量。

#### Scenario: 错误样本不伪造零

- **WHEN** `total_bytes` 为空、overlay 缺失，或 bind 路径存在但 bind 字节为空
- **THEN** 不把该样本的字节或接收时间写成有效测量，不写 0，不把旧值标成当前测量；若同帧路径发生变化，仍按路径规则先落路径并清空旧测量；日志记录拒绝原因

#### Scenario: 重复缓存帧不刷新测量时间

- **WHEN** Node 在一个测量周期内多次推送同一 `measured_at` 的缓存结果
- **THEN** `disk_checked_at` 保持该真实测量时间；新的发送/接收时间不得把它推进，重复帧也不得改写路径

#### Scenario: 已知旧测量不回退

- **WHEN** 帧内真实 `measured_at` 早于现有 `disk_checked_at`，或时间相同但路径冲突
- **THEN** 不回写旧测量，不以冲突帧改路径；先拒绝旧帧再执行路径更新，不新增排序列，也不宣称无时间的路径纠正具备跨进程隔离

#### Scenario: 明确 no_bind 的 overlay 测量

- **WHEN** Node 明确返回 `mount_path_status=no_bind`、`bind_mount_path=null`，overlay 组成完整且 `measured_at` 有效
- **THEN** Ctrl 清空当前 `bind_mount_path` 后按 overlay 总量写入有效测量；不得把探测失败、路径不可读或字段缺失推断为 no_bind，也不得混入旧 bind 字节

#### Scenario: 无效 measured_at 只拒绝测量

- **WHEN** 新 Node 帧的 `measured_at` 无法解析或超出现在允许时钟偏差
- **THEN** 不更新字节和 `disk_checked_at`，但同帧的合法路径修正仍可落库并按路径规则清空旧测量；不得把该帧解释成旧 Node，也不得用接收时间替代

### Requirement: 路径变化清空旧测量

路径变化或明确 no_bind 清空时，接收链路 SHALL 使用既有更新能力显式清空旧路径相关 `disk_overlay_rw_bytes`、`disk_bind_mount_bytes`、`disk_total_bytes` 和 `disk_checked_at`，再按新路径的完整样本回填；MUST NOT 把旧路径字节/总量贴到新路径。显式清空 MUST 使用专用清除语义，MUST NOT 把普通 `None` 一律当清空，且只作用于当前活跃容器。

#### Scenario: 路径改变后旧样本晚到

- **WHEN** 当前业务路径已修正为新路径 B，随后收到 `bind_mount_path=A` 且总量对应旧路径的样本
- **THEN** 拒绝该样本更新字节和 `disk_checked_at`，保留 B；不对 A 的数字做新路径标注，也不清空 B

#### Scenario: 路径变化先清空再回填

- **WHEN** 当前容器路径从 A 修正为 B，或明确转为 no_bind
- **THEN** 先用既有更新链路显式清空旧路径相关 `disk_*` 与 `disk_checked_at`；同帧只有 B（或 overlay-only）的完整新样本才可回填，旧 A 的字节不进入新路径

### Requirement: 评估只使用当前可信测量

磁盘调度和动作前检查 SHALL 使用与接收相同的完整性、路径一致性条件，并要求 `disk_checked_at` 非空且未超过允许最大年龄（初值 3600 秒，且 MUST NOT 小于 Node 既有缓存 TTL 900 秒与 du 超时 600 秒之和 1500 秒）。不满足时 MUST NOT pause、重置冻结、发超限邮件、升级删除或清理挂载；仍保留既有冻结记录、机器不可用补偿与人工宽限。

`mount_path_status=unresolved` 本身 MUST NOT 阻断同路径有效测量；`mount_path_status=resolved` 本身 MUST NOT 使失败测量有效。本变更 MUST NOT 改变恢复、冻结、长期、删除或清理资格，MUST NOT 重写 Q72 累计，MUST NOT 新增 review/invalid 保护，也 MUST NOT 把路径修正当删除/清理授权。

#### Scenario: 测量过期不动作

- **WHEN** `disk_total_bytes` 仍存在，但 `now - disk_checked_at` 超过允许最大年龄
- **THEN** 调度跳过 pause、冻结重置、邮件、升级删除和挂载清理；保留最后已知值作历史，不写 0，不重开或顺延冻结周期

#### Scenario: unresolved 路径上的有效测量

- **WHEN** `mount_path_status=unresolved`，但已有业务路径、该路径测量成功、组成完整且 `disk_checked_at` 在允许年龄内
- **THEN** 样本可用于磁盘评估；日志保留 unresolved 诊断但不阻断，`resolved` 不是额外前置

#### Scenario: resolved 但测量失败

- **WHEN** `mount_path_status=resolved`，但 du 失败、组成缺失或 `measured_at` 无效
- **THEN** 不因路径已确认而接受该失败帧的数字，不刷新既有成功时间；同路径最后成功样本仍按原有效年龄判断，路径变化清空或旧样本过期后按无当前可信测量跳过动作，不持久化最新尝试状态

#### Scenario: 路径修正不等于删除授权

- **WHEN** Node 修正了 `bind_mount_path`
- **THEN** 后续删除/清理仍走既有权限、路径和业务检查；不得仅凭路径修正或目录对象编号调用删除，也不宣称 Q70 跨进程原子

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
