# Spec Delta

## ADDED Requirements

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
