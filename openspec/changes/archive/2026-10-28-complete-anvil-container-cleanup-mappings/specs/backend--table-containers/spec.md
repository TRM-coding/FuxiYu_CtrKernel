# Spec Delta

## MODIFIED Requirements

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

### Requirement: 容器详情返回既有宿主 bind 路径

Ctrl 的容器详情响应 SHALL 在既有字段之外追加可空 `bind_mount_path`，值只取 `containers.bind_mount_path`；MUST NOT 调用 Node 核对、不得从容器名/机器名/端口推导，也不得把已有值描述为实时验证。该字段只扩展既有详情 response，不新增数据库列/表/JSON，不改变 Node→Ctrl 推送或周期 WSS；旧 Ctrl 缺字段时按未记录降级。

#### Scenario: 有记录时原样返回

- **WHEN** 容器行存在非空 `bind_mount_path` 且请求详情
- **THEN** 详情响应的该字段与数据库值完全一致，不调用 Node，也不改变容器行

#### Scenario: 空值或旧响应按未记录处理

- **WHEN** 数据库值为 null，或旧 Ctrl 详情响应没有该字段
- **THEN** 消费方按“未记录”处理，不从名称、机器名或端口拼出候选路径

#### Scenario: 只读查询不写库

- **WHEN** 读取容器详情
- **THEN** 不新增/修改任何数据库行，也不因该字段触发 Node 请求或周期 WSS 变化

### Requirement: containers entrypoint 留痕说明符合构建语义

`models/containers.py` 与 `services/container_module/creation.py` 的 entrypoint 说明 SHALL 表明它与 FROM、业务片段一样属于构建配方，渲染为最终 Dockerfile 最后一行 `ENTRYPOINT`；创建流程落库模板侧三项（FROM、业务片段、启动命令），平台注入不落库。说明 MUST NOT 再称其不参与构建或只是运行期参数。该修正 MUST NOT 改变容器字段、恢复行为或构建行为。

#### Scenario: 容器模型与创建流程说明一致

- **WHEN** 开发者依据 `models/containers.py` 或创建流程理解 entrypoint
- **THEN** 两处都描述为构建配方的一段，创建流程明确模板侧三项落库、平台注入现取

### Requirement: 容器创建与恢复生成一次性 root 密码

Ctrl SHALL 在实际创建或恢复容器时用密码学安全随机源生成 root 密码，并通过 Ctrl→Node 创建载荷顶层字段 `root_password` 下发。该密码 MUST NOT 由 owner 名、用户名、机器名、时间或固定后缀派生，MUST NOT 缺省或回退为 `owner_name + "123"`、`user123` 等默认值；Service 入口未显式收到密码时 SHALL 生成非空密码。Node 受理后，Ctrl SHALL 保留既有 `success`/`message`，追加 `accepted: true` 与 `credentials: [{"login_name": "root", "password": <本次密码>}]`。未受理、创建失败或恢复二选一时 MUST NOT 返回密码。实际恢复 MUST 生成新密码。含密码的成功响应 SHALL 带 `Cache-Control: no-store`。

#### Scenario: 创建受理后返回 root 密码

- **GIVEN** 机器在线、镜像模板可用，调用方有创建权限
- **WHEN** 调用 `POST /api/containers/create_container` 且 Node 返回受理成功
- **THEN** Ctrl 发给 Node 的创建载荷含顶层非空 `root_password`，响应为 `success: 1`、保留原 `message`、`accepted: true`、`credentials` 恰有一项且 `login_name` 为 `root`，并带 `Cache-Control: no-store`；容器行与创建 oplog 中不存在该密码

#### Scenario: 创建失败不返回密码

- **GIVEN** Node 对创建请求返回失败
- **WHEN** 调用创建接口
- **THEN** 响应 `success: 0` 且不含 `credentials`/密码；Node 仍收到顶层 `root_password`，但该密码不出现在错误响应、日志或容器表

#### Scenario: 恢复实际执行时生成新密码

- **GIVEN** 一个已软删、可恢复且不需要内容二选一的容器
- **WHEN** 调用 `POST /api/containers/resurrect_container` 且恢复成功
- **THEN** Ctrl 发送的创建载荷含新生成的顶层 `root_password`，响应保留 `container_id` 并追加 `accepted: true` 与一项 `login_name` 为 `root` 的 `credentials`，该密码与创建时的旧密码不同

#### Scenario: 内容二选一不生成密码

- **GIVEN** 恢复请求未指定 `content_source`，且容器留痕与当前模板内容不同
- **WHEN** 调用恢复接口
- **THEN** 响应 `requires_choice: true`，Ctrl 不调用 Node、不生成密码，响应 `accepted: false` 且 `credentials` 为空

#### Scenario: 内部创建入口也不使用默认密码

- **GIVEN** 代码直接调用 `Create_container` 且未显式传入 root 密码
- **WHEN** 组装 Ctrl→Node 创建载荷
- **THEN** 载荷仍含非空顶层 `root_password`，且该值不等于 owner 名、用户名或任何固定默认值

### Requirement: 容器账号密码重置的权限与目标校验

Ctrl SHALL 提供 `POST /api/containers/reset_container_password`，body 仅 `container_id`/`user_id`，未知字段 MUST 拒绝。接口 SHALL 要求 `container:operation` + `container:root`，并叠加现有机器访问/在线守卫：资源层只允许 ROOT 绑定、直持 `bypass_resource` 或 `container:manage`；`bypass_auth_entity` 与 ADMIN/COLLABORATOR 绑定 MUST NOT 放行。返回密码前 SHALL 校验容器存在、机器访问与在线非维护、容器 online、目标绑定存在、`username` 非空且安全；`login_name` 取绑定 `username`，ROOT 固定 `root`，非 ROOT 的空/`root`/非法值 MUST 拒绝。预检错误按现有 `error_reason` 映射 404/409/500，不拼 Node 原始错误体。

#### Scenario: ROOT 绑定用户重置协作者

- **GIVEN** 容器 online，调用方是该容器 ROOT 绑定，目标 `user_id` 绑定角色为 COLLABORATOR 且 `username` 为 `alice`
- **WHEN** 调用重置接口
- **THEN** 返回 200 `accepted: true` 且 `credentials.login_name` 为 `alice`；后台 Node 请求的 `config.user_name` 为 `alice`

#### Scenario: ROOT 绑定固定使用 root 登录名

- **GIVEN** 目标 `user_id` 的绑定角色为 ROOT，绑定 `username` 即使为历史值
- **WHEN** 调用重置接口
- **THEN** 返回密码的 `credentials.login_name` 为 `root`，后台 Node 请求的 `config.user_name` 为 `root`，不使用绑定历史值或任何前端传入值

#### Scenario: 资源管理通配可重置

- **GIVEN** 调用方不是该容器任何绑定，但直持 `container:manage` 或 `bypass_resource`
- **WHEN** 调用重置接口且目标用户是该容器绑定
- **THEN** 请求通过资源层，返回 `accepted: true` 与一次性密码

#### Scenario: 仅实体通配被资源层拒绝

- **GIVEN** 调用方只持有 `bypass_auth_entity`，不直持 `container:manage`/`bypass_resource`，也不是该容器 ROOT 绑定
- **WHEN** 调用重置接口
- **THEN** 返回 403 `resource_access_denied`，不生成密码、不调用 Node

#### Scenario: ADMIN 或 COLLABORATOR 不能重置

- **GIVEN** 调用方是该容器的 ADMIN 或 COLLABORATOR 绑定
- **WHEN** 调用重置接口
- **THEN** 返回 403 `resource_access_denied`，不生成密码、不调用 Node

#### Scenario: 目标用户未绑定被拒绝

- **GIVEN** 调用方通过资源层校验，但目标 `user_id` 不是该容器的有效绑定
- **WHEN** 调用重置接口
- **THEN** 返回 409 `target_not_bound`，不生成密码、不调用 Node

#### Scenario: 绑定登录名非法被拒绝

- **GIVEN** 目标绑定不是 ROOT，`username` 为空、等于 `root` 或含非法字符
- **WHEN** 调用重置接口
- **THEN** 返回 409 `invalid_target_account`，不生成密码、不调用 Node

#### Scenario: 机器离线时不生成密码

- **GIVEN** 目标容器所在机器离线或处于维护态
- **WHEN** 调用重置接口
- **THEN** 返回对应机器错误（如 `machine_offline`/`machine_maintenance`），不生成密码、不调用 Node

#### Scenario: 容器非 online 时不生成密码

- **GIVEN** 容器 `effective_status` 为 offline、paused、failed 或过渡态
- **WHEN** 调用重置接口
- **THEN** 返回对应的状态错误（如 `container_offline`/`container_busy`），不生成密码、不调用 Node

#### Scenario: 额外字段不能指定登录名

- **GIVEN** 请求体除 `container_id`/`user_id` 外还带 `login_name`
- **WHEN** 调用重置接口
- **THEN** 返回 400 `invalid_payload`，不生成密码、不调用 Node

#### Scenario: 错误按现有 reason 映射且不拼原始错误体

- **GIVEN** 预检遇到容器不存在、目标未绑定或内部异常
- **WHEN** 调用重置接口
- **THEN** 按现有 `error_reason` 映射为 404/409/500，响应只含稳定 `message`/`error_reason`，不含 Node 原始错误体、请求体或密码

### Requirement: 容器密码重置的后台执行与一次性响应

校验通过后，Ctrl SHALL 生成安全随机密码并立即返回 `success`/`message`、`accepted: true`、`credentials`；发给 Node 的 `POST /api/reset_container_password`（`config:{container_name,user_name,password}`）MUST 在后台执行，HTTP 响应 MUST NOT 等待。后台 SHALL 复用最小机器/容器在线 guard；复核或 Node 失败只写一条 `reset_container_password` oplog，detail 至少含 `user_id`/`login_name`、MUST NOT 含密码。客户端断开 MUST NOT 取消已受理任务；含密码响应 SHALL 带 `Cache-Control: no-store`。

#### Scenario: 受理后立即返回并后台请求 Node

- **GIVEN** 重置预检全部通过
- **WHEN** 调用重置接口
- **THEN** 响应在 Node 执行前返回 `success: 1`、`accepted: true`、一项 `credentials`（登录名为绑定 `username` 或 `root`）和 `Cache-Control: no-store`；随后后台向 Node 发送 `{config: {container_name, user_name, password}}`，成功 oplog 为 `reset_container_password` 且不含密码

#### Scenario: 客户端断开不取消后台任务

- **GIVEN** 重置请求已通过全部校验并已启动后台任务
- **WHEN** 客户端在收到受理响应后立即断开
- **THEN** 后台 Node 请求仍会执行，并按真实结果写入成功或失败 oplog

#### Scenario: Node 失败只写失败 oplog

- **GIVEN** 重置请求已返回 `accepted: true`
- **WHEN** Node 的 `reset_container_password` 返回失败或抛异常
- **THEN** Ctrl 写一条 `success=False` 的 `reset_container_password` oplog，`error_reason` 稳定且脱敏；不写成功 oplog，日志/审计/异常均不含密码

#### Scenario: 后台复核失败只写 oplog

- **GIVEN** 重置已受理，但后台执行前机器/容器已不满足最小在线 guard
- **WHEN** 后台任务运行
- **THEN** 不调用 Node，写一条 `success=False` 的 `reset_container_password` oplog，`error_reason` 为现有状态错误且不含密码；不新增持久状态或 DTO

#### Scenario: 密码响应不可缓存

- **GIVEN** 重置成功并返回密码
- **WHEN** 检查该 HTTP 响应头
- **THEN** `Cache-Control` 含 `no-store`，响应不指示浏览器或代理缓存密码

### Requirement: 新增协作者的一次性账号密码

新增 ADMIN 或 COLLABORATOR 协作者时，Ctrl SHALL 生成随机密码，经 Node `add_collaborator` 的 `config.password` 设置，MUST NOT 使用用户名派生弱默认值。沿用现有权限、在线、用户与角色校验；通过后立即返回 `success`/`message`、`accepted: true` 与一项凭据。后台写账号/绑定，执行前复用最小在线 guard；成功只沿用 `ADD_COLLABORATOR`，MUST NOT 新增密码专用日志；失败不写绑定/成功日志且不含密码。客户端断开不取消；含密码响应 SHALL 带 `Cache-Control: no-store`。

#### Scenario: 新增 ADMIN 协作者返回密码

- **GIVEN** 容器 online，调用方有 `container:root` 资源权限，目标用户存在且未被现有规则拒绝
- **WHEN** 调用 `add_collaborator` 且角色为 ADMIN
- **THEN** 响应 `accepted: true` 与一项 `login_name` 为目标用户名的 `credentials`；后台 Node 收到 `config.password` 等于该密码，成功后写入 ADMIN 绑定并记一条无密码 `ADD_COLLABORATOR` 成功 oplog

#### Scenario: 新增 COLLABORATOR 协作者返回密码

- **GIVEN** 容器 online，调用方有资源权限，目标用户存在且未被现有规则拒绝
- **WHEN** 调用 `add_collaborator` 且角色为 COLLABORATOR
- **THEN** 同样生成随机密码、返回一项 `login_name` 为目标用户名的凭据，并在后台用该密码创建账号、写绑定和 `ADD_COLLABORATOR` 日志

#### Scenario: Node 或绑定失败不写成功

- **GIVEN** 新增协作者已返回 `accepted: true`
- **WHEN** Node `add_collaborator` 返回失败/抛异常，或 Node 成功后 Ctrl 写绑定失败
- **THEN** 不把该协作者描述为已添加、不写成功 oplog；写一条 `success=False` 的 `ADD_COLLABORATOR` 日志，`error_reason` 稳定且不含密码

#### Scenario: 前置校验失败不生成密码

- **GIVEN** 机器离线、容器非 online，或目标用户/角色不满足现有新增校验
- **WHEN** 调用 `add_collaborator`
- **THEN** 返回既有错误，不生成密码、不调用 Node

#### Scenario: 后台最小 guard 复核失败只写失败日志

- **GIVEN** 新增协作者已受理，但后台执行前机器/容器已不满足最小在线 guard
- **WHEN** 后台任务运行
- **THEN** 不调用 Node、不写绑定或成功日志；写一条 `success=False` 的 `ADD_COLLABORATOR` 日志，`error_reason` 为现有状态错误且不含密码

### Requirement: 恢复协作者账号的瞬时密码兼容

实际恢复容器时，Ctrl SHALL 为 Node `restore_accounts` 中每个非 ROOT 协作者生成互不复用的瞬时随机密码，并随创建 wire 的对应账号项传入；MUST NOT 使用 `{username}123` 等弱默认值，MUST NOT 写入恢复快照、数据库、日志或响应回查。该密码仅用于 Node 账号创建，不改变恢复的 root 凭据交付（实际恢复仍交付 root 一项）和 `requires_choice` 无凭据语义。

#### Scenario: 恢复协作者账号使用瞬时随机密码

- **GIVEN** 恢复快照包含一个非 ROOT 协作者 `alice`
- **WHEN** 实际恢复容器
- **THEN** Ctrl 发给 Node 的 `restore_accounts` 对应项含非空 `password`，不等于 `alice123`/任何弱默认值；恢复快照、数据库和日志中不含该密码；响应仍只按共享创建交付 root 一项凭据

#### Scenario: Node 拒绝瞬时密码时不回退弱默认值

- **GIVEN** Node 对恢复协作者账号的密码处理返回失败
- **WHEN** 执行恢复
- **THEN** 恢复失败，不重试 `{username}123` 或空密码，不返回凭据；错误输出不含密码或 Node 原始请求/响应体

### Requirement: 容器密码不持久化且不可回查

Ctrl MUST NOT 将容器密码写入数据库、迁移、JSON 持久化、oplog/审计 detail、应用日志、错误日志、Docker 环境/config/labels、WSS 帧、action 缓存或运行时缓存。密码 SHALL 只存在于生成它的进程内局部变量、后台任务参数和带 `Cache-Control: no-store` 的一次性 HTTP 响应中。Ctrl MUST NOT 提供按容器或用户读取密码的接口，也 MUST NOT 从哈希、日志或设备状态重建密码。失败响应、异常、oplog 的 error_reason/detail MUST NOT 含密码、哈希或可重建片段；Node 错误体 MUST 在进入响应/日志/异常前被拒绝或脱敏。Ctrl MUST NOT 记录密码类接口的请求体或响应体。

#### Scenario: 一次性密码只在响应中出现

- **GIVEN** 创建、恢复、新增协作者、重置或 ROOT 交接已成功返回密码
- **WHEN** 检查容器表、user_container 表、operation_logs、应用日志与运行时缓存
- **THEN** 均不存在该密码字符串；再次查询容器详情或列表也不返回密码

#### Scenario: 失败响应与异常脱敏

- **GIVEN** Node 返回的错误体或异常文本意外包含本次提交的密码
- **WHEN** Ctrl 构造错误响应、oplog 或日志
- **THEN** 输出只含稳定的 `error_reason`/状态码，不含该密码或包含它的原始错误体

#### Scenario: 无密码回查入口

- **GIVEN** 已有一个创建、新增或重置过密码的容器
- **WHEN** 枚举容器相关 API 并尝试查询密码
- **THEN** 不存在返回该密码的端点；详情、列表、日志与审计响应均无密码字段
