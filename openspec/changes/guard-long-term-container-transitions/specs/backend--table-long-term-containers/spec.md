# Spec Delta

## ADDED Requirements

### Requirement: 长期资格由服务端统一裁决

系统 SHALL 对所有实际新增或移除长期标记的入口使用同一套服务端资格判断，至少覆盖手工设置、恢复长期快照及后续新增入口；客户端字段、按钮状态和既有 `long_term_container_can_enable` 不得成为授权依据。服务端 MUST 在写入前重读当前容器、长期标记、绑定、机器与磁盘测量，MUST NOT 信任请求方提交的资格或磁盘值，也 MUST NOT 以目录 dev/inode 或 `mount_path_status` 作为长期业务门禁。

#### Scenario: 不同 UI 入口不能绕过

- **WHEN** 两个不同页面分别发起设置长期或恢复长期快照请求
- **THEN** 两个请求都由同一服务端判断决定允许或拒绝，客户端未提交或提交错误的资格字段不改变结果

#### Scenario: 旧的配额展示字段不授权

- **WHEN** 响应中的既有 `long_term_container_can_enable` 为真，但当前路径测量已过期或不可信
- **THEN** 服务端仍拒绝实际启用，并在新资格对象中给出对应拒绝原因

### Requirement: 只读长期资格 DTO

容器 detail 与 brief SHALL 同源返回 `long_term_eligibility` 对象，字段固定为 `can_enable: bool`、`can_disable: bool`、`enable_reason: str | null`、`disable_reason: str | null`、`evaluated_at: str`、`disk_total_bytes: int | null`、`disk_limit_bytes: int | null`、`disk_measured_at: str | null`。`evaluated_at` 与 `disk_measured_at` MUST 为 UTC 字符串；时间不得使用本地时区或 `disk_checked_at` 冒充测量时间。理由为 null 表示该方向当前可执行。

#### Scenario: detail 与 brief 同源

- **WHEN** 同一容器在同一时刻分别查询详情与列表
- **THEN** 两个响应中的 `long_term_eligibility` 字段集合、布尔结论与拒绝原因一致

#### Scenario: 已长期与未长期的方向语义

- **WHEN** 容器已是长期，或当前不是长期
- **THEN** 前者 `can_enable=false` 且 `enable_reason=long_term_already_enabled`，后者 `can_disable=false` 且 `disable_reason=long_term_not_enabled`；另一方向按实际门禁裁决

#### Scenario: 数值不可用时不伪造零

- **WHEN** 磁盘总量未知、测量未验证或机器未配置限额
- **THEN** `disk_total_bytes`、`disk_limit_bytes` 或 `disk_measured_at` 按真实缺失返回 null，不得写成 0，也不得用 `disk_checked_at` 补位；`can_enable` 必须为 false 并带明确原因

### Requirement: 启用长期必须通过状态、数量与测量门禁

实际从非长期设为长期时，系统 SHALL 要求当前为已确认的稳定 `online` 或 `offline`、无未确认运行过渡、root 用户长期数量未超限、机器 `max_disk_size_gb` 已配置、业务路径上的测量有效且未过期、`disk_total_bytes` 已知且未达到磁盘硬阈值。测量缺失、未验证、过期、路径与样本不一致、限额缺失或总量未知 MUST 拒绝启用；软阈值只提醒，MUST NOT 阻断。`disk_total_bytes` 为 null MUST NOT 按 0 放行。路径核对状态 `unresolved` 本身 MUST NOT 拒绝同一业务路径上的有效测量；Docker 明确 `no_bind` 的 overlay-only 测量可为测量路径 null，但不得携带旧 bind 样本或把异常当 0。

#### Scenario: 达到硬阈值时拒绝启用

- **WHEN** 机器限额为 512 GiB、硬阈值为 100%，可信总量为 600 GiB 的非长期容器申请启用
- **THEN** 服务端以 409 策略原因拒绝，不新增长期标记，不改变冻结锚点、宽限或累计计时

#### Scenario: 仅超过软阈值仍可启用

- **WHEN** 可信磁盘总量达到软阈值但低于硬阈值，其余门禁均通过
- **THEN** 启用成功，响应仍可通过既有磁盘字段提示软阈值风险，不把软提醒写成拒绝原因

#### Scenario: 稳定 offline 且测量有效可启用

- **WHEN** 容器为稳定 `offline`、机器可达且非维护、业务路径测量在有效期内、`measurement_mount_path` 与当前路径一致、总量低于硬阈值
- **THEN** 保留旧允许语义并允许启用，服务端在写入前重新确认这些事实

#### Scenario: 路径 unresolved 但同路径测量成功

- **WHEN** `mount_path_status=unresolved`，但已有业务路径且本次测量针对该路径成功、时间有效、总量低于硬阈值
- **THEN** 启用不被路径诊断阻断；原因不写成目录身份缺失，也不把诊断失败伪装成 measurement_error

#### Scenario: 缺测量或路径样本不一致时明确拒绝

- **WHEN** 容器在线或稳定 offline，但缺少真实测量时间、测量未验证/过期、`measurement_mount_path` 与当前路径不一致或无法取得限额
- **THEN** 服务端明确拒绝启用并返回对应原因，不以 0 用量、旧 `disk_checked_at` 或空值假定安全

#### Scenario: 长期数量限额保持

- **WHEN** 容器各 root 用户的长期数量已达到配置上限
- **THEN** 拒绝新增标记并保留既有 `long_term_limit_reached` 原因与 used/limit 数量信息

### Requirement: 未确认解冻时不得取消长期

实际从长期改为非长期时，系统 SHALL 仅在已确认未冻结且状态守卫允许时执行：当前为稳定 `online` 或 `offline`、无 `pausing`/`unpausing` 未确认过渡、无 `status_unknown_since`、非 `failed`/`paused`/不稳定状态、机器可达且非维护。`paused` 或任一未确认过渡 MUST 拒绝取消；`container_disk_freeze_state` 行仍然存在本身 MUST NOT 作为永久拒绝条件。取消长期 MUST NOT 新增磁盘超限或数量限制条件，也不得重置冻结锚点、宽限或累计计时。

#### Scenario: 冻结中取消被拒绝

- **WHEN** 长期容器当前为 `paused`，或已收到 pause/unpause 受理但尚无终态确认
- **THEN** 取消长期返回 409 策略原因，长期标记保留，磁盘冻结记录与 `first_frozen_at`、`grace_until`、`deferral_seconds` 均不变

#### Scenario: 已确认解冻后允许取消

- **WHEN** 旧冻结记录仍存在，但 WSS 已确认容器为终态 `online` 且无未确认过渡
- **THEN** 取消长期允许执行，不因冻结记录行仍存在而永久阻断，也不删除或重置该冻结记录

#### Scenario: 稳定 offline 保留旧语义

- **WHEN** 长期容器为稳定 `offline`、机器可达且非维护、没有未确认过渡
- **THEN** 按既有状态守卫允许取消长期，不额外要求磁盘测量或磁盘未超限

### Requirement: 同目标值请求为无副作用幂等

当容器当前长期状态已等于请求目标时，系统 SHALL 返回成功且不新增或删除长期标记、不新增成功审计、不改变冻结锚点/宽限/累计计时，也不要求再次通过磁盘或数量门禁。并发下若初始读取与目标一致但事务内重读发现状态已变化，系统 MUST 按变化后的实际状态重新判断，MUST NOT 直接报告成功。

#### Scenario: 重复启用不产生新标记

- **WHEN** 已是长期的容器重复提交 `is_long_term=true`
- **THEN** 返回当前长期状态，长期记录仍只有一条，不新增审计，不改变冻结记录

#### Scenario: 重复取消不产生新副作用

- **WHEN** 已是非长期的容器重复提交 `is_long_term=false`
- **THEN** 返回当前状态，不执行删除，不新增审计，不触碰冻结记录

#### Scenario: 并发状态变化不沿用旧判断

- **WHEN** 请求开始读取时目标值与当前一致，但同一容器随后被另一请求改为相反状态
- **THEN** 事务内重读后按新状态重新判断，不把旧读取结果当作成功写入依据

### Requirement: 资格原因与 HTTP 映射稳定

长期资格拒绝 SHALL 使用稳定的 `enable_reason`/`disable_reason` 值，实际写入口的 `error_reason` MUST 与之一致；策略阻断默认映射 HTTP 409，机器离线或维护沿用既有 503，权限与不存在分别沿用 403/404。失败审计 MUST 记录实际原因，MUST NOT 因资格拒绝而新增或删除长期标记。缺少真实测量时使用测量未验证原因，MUST NOT 说成目录身份缺失。

#### Scenario: 策略阻断返回 409

- **WHEN** 启用因磁盘超限、测量不可信、限额缺失或取消因冻结/过渡被拒绝
- **THEN** API 返回 409，`error_reason` 为稳定原因，长期标记保持原状

#### Scenario: 主机不可用沿用既有映射

- **WHEN** 主机离线或维护导致实际切换被拒绝
- **THEN** 返回既有 503 原因，不伪装成磁盘超限或长期数量超限

### Requirement: 恢复长期快照的静默宽限

实际执行长期快照恢复时，系统 SHALL 恢复原长期标记并自动授予一次现有 `container.disk_freeze_grace_days` 宽限，不增加确认框/按钮/token/新前端状态机，也不要求提前知道新实例是否超限。宽限 SHALL 持久化在 `containers.restore_grace`，与长期标记在容器可见前同一事务写入；不伪造冻结行/`first_frozen_at`。`source=resurrect:<deleted_id>` 幂等，重复请求/轮询/重试不刷新 `until`；只读选择、取消、未恢复失败不消耗；宽限内不暂停/升级，结束后按新实例有效测量和标准硬限额/Q72 处理。

#### Scenario: 实际恢复自动授一次宽限

- **WHEN** 长期快照实际恢复成功
- **THEN** 原长期标记恢复，容器行写入一次 `restore_grace`，无确认框/token；调度可见时标记与宽限已经同时存在

#### Scenario: 只读选择不消耗宽限

- **WHEN** 恢复因 image/内容差异进入 requires_choice 并返回，尚未实际恢复
- **THEN** 不写长期标记或 `restore_grace`；第二次带选择实际恢复时才授一次宽限

#### Scenario: 重复请求不刷新宽限

- **WHEN** 同一 `deleted_id` 的恢复被重复请求、轮询或重试，且 `restore_grace.source` 已存在
- **THEN** 复用原 `until/granted_at`，不延长、不重新计算宽限

#### Scenario: 宽限有效时不立即冻结

- **WHEN** 新实例测量已超硬阈值，但 `restore_grace` 或既有有效宽限尚未到期
- **THEN** 统一冻结入口跳过暂停、超限通知和升级删除；宽限结束后用新实例有效测量按标准策略处理

#### Scenario: 无冻结记录也不伪造

- **WHEN** 恢复前没有冻结行、没有 first_frozen_at
- **THEN** 只写容器行 `restore_grace`，不创建假冻结行/锚点；Q72 累计从后续真实冻结周期开始

#### Scenario: 失败未恢复不消耗

- **WHEN** 路径/配额/机器/image/创建或事务在真正恢复前失败
- **THEN** 不写有效长期标记/`restore_grace`，不报告完整成功；重试仍可授一次宽限

#### Scenario: 手工新启用无恢复特例

- **WHEN** 已存在非长期容器通过手工 set_long_term 启用
- **THEN** 仍执行硬超限拒绝，不自动授予恢复宽限

## MODIFIED Requirements

### Requirement: 恢复长期标记遵守数量限额

恢复快照中的长期标记 SHALL 使用与普通设置入口一致的配额主体、计数口径和豁免规则；需要新增标记时 MUST 先校验容量。已存在标记 SHALL 保持幂等，非长期快照 SHALL 不新增标记。超限 SHALL 返回长期容器数量限制的具体失败原因及相关数量，不静默跳过标记。恢复按保留业务路径创建，MUST NOT 因旧 Docker ID/PID/dev/inode 不同而拒绝，也 MUST NOT 新增目录身份前置。恢复长期标记的实际执行 SHALL 同时遵守本 delta 的静默宽限要求；路径、权限、机器和创建错误沿用既有检查。

#### Scenario: 长期限额已满

- **WHEN** 限额为 1 且计数主体已有 1 个长期容器，又尝试恢复一个长期容器
- **THEN** 拒绝新增长期标记并向调用方报告已用数量及上限，不产生第 2 个长期容器

#### Scenario: 幂等与普通快照

- **WHEN** 恢复目标已具有长期标记，或快照没有长期标记
- **THEN** 已存在的标记不重复计数，普通快照不因长期配额已满而被拒绝；非长期快照不新增长期标记也不授恢复宽限

#### Scenario: 按路径恢复不查旧对象编号

- **WHEN** 删除快照保留了目录路径，原 Docker 对象/PID/dev/inode 已失效或不可比较
- **THEN** 恢复仍按保留路径创建，不因旧对象编号不同而拒绝，也不新增 inode 清理/授权门禁
