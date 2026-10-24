## Why

当前 Node 创建容器时把 root 密码固定为 `{owner_name}123`，新增协作者使用 `{user_name}123`，ROOT 交接只存在于 Web `EditUserModal` 的多步调用中（先遍历旧 ROOT 调 `updateRole(ADMIN)`，再调目标 `updateRole(ROOT)`）。这条现有编排会先降级调用者，导致后续请求可能 403，也无法在一次响应中交付两个账号密码。Ctrl 也没有容器账号密码重置接口。本变更保留现有 ROOT 交接的最终角色结果，把密码改为平台安全随机生成、一次性交付，并把已有 Web 多步交接移入 Ctrl 后台执行。

## What Changes

- **创建/恢复**：Ctrl 安全随机生成 root 密码，在 Ctrl→Node 创建载荷顶层传 `root_password`；Node 必须使用，MUST NOT 回退到 owner/username 派生值。Ctrl 受理成功后保留 `success`/`message`，追加 `accepted:true` 与 `credentials:[{login_name,password}]`（root 一项）。创建仍只记原有单条 `CREATE_CONTAINER`，不新增密码日志。恢复实际执行时复用同一机制；`requires_choice=true` 不恢复、不生成密码。
- **新增协作者**：不论 ADMIN 还是 COLLABORATOR，Ctrl 都生成随机密码，经 Node `add_collaborator` 的 `config.password` 设置；受理后立即返回 `accepted:true` 与该用户 `login_name` 的一项凭据，Node 与绑定写入在后台完成，结果只写既有 `ADD_COLLABORATOR` oplog。普通非 ROOT 的 ADMIN/COLLABORATOR 互换不改密码。
- **手动重置**：新增 `POST /api/containers/reset_container_password`，body 仅 `{container_id,user_id}`。Ctrl 校验 `container:operation` 与 `container:root` 资源（ROOT 绑定，或直持 `container:manage`/`bypass_resource`；仅 `bypass_auth_entity` 不放行），并沿用机器在线与容器 online 守卫；目标必须是该容器绑定，`login_name` 取绑定 `username`（ROOT 固定 `root`）。受理后立即返回随机密码，Node `POST /api/reset_container_password` 在后台执行 `chpasswd`；成功/失败只写 oplog，操作码为 `reset_container_password`，不带密码；客户端断开不取消已受理任务。
- **ROOT 交接（沿用现有 Web 角色结果）**：`update_role` 请求增加纯布尔 `transfer_root:false`（默认）。Home/EditUserModal 现有交接显式传 `true`，Ctrl 才按“遍历当前旧 ROOT（目标除外）先降为 ADMIN，再把目标升为 ROOT”的既有顺序在后台编排；详情页现有单目标改角色默认 `false`，升 ROOT 只重置共享 root 并返回 root 一项，绝不偷偷降旧 ROOT。`true` 时每个被降为 ADMIN 的旧 ROOT 使用其系统用户名创建/确保独立账号并设置 Ctrl 随机密码，新 ROOT 使用共享 root 账号并重置为另一 Ctrl 随机密码；正常单旧 ROOT 两项不同 `login_name`，历史多 ROOT 按既有遍历返回 root + 所有涉及旧 ROOT，不得丢弃涉及人或为凑恰好两项篡改角色。Node 无 `transfer_root` 字段，仍只处理单目标 primitive；内部删用户 ROOT 移交保持原单目标同步 primitive，不使用 Web 交接编排。后台逐步执行 Node `update_role` 并落对应 Ctrl 绑定；任何一步失败即停止，已完成步骤如实保留并记成功日志，失败步骤记失败日志，不伪报整体完成、不新增持久回滚工作流。
- **内部兼容路径**：容器恢复的 `restore_accounts` 协作者账号 SHALL 由 Ctrl 生成瞬时随机密码并随 Node 创建 wire 传入，MUST NOT 写入恢复快照/数据库/日志；实际恢复仍交付一次性 root 凭据，`requires_choice` 不交付凭据。删除用户触发的 ROOT 提升为保持现有删除业务同步步骤的内部调用，也必须生成随机 root 密码并传入 Node，MUST NOT 回退弱密码；不改变删除用户、恢复协作者的角色/页面规则。
- **角色规则边界**：普通非 ROOT 的 ADMIN/COLLABORATOR 互换仍走现有同步路径，Ctrl 不生成/发送密码。由 ROOT 降为 ADMIN 是上述交接步骤，必须生成旧 owner 独立账号密码；本变更不新增其他角色迁移或账号规则。
- **权限快照**：`/api/users/me/permissions` 新增派生、非持久字段 `container_resource_unrestricted`，值等于 `has_resource_wildcard(user_id, "container")`；Web MUST NOT 用 `container:manage`/`hasAnyManage` 等方法通配推断容器资源通配。
- **安全边界**：密码不落库、不进迁移/JSON、不进 oplog/审计/应用日志/错误日志、不进 Docker 环境/config/labels、不进 WSS/action 缓存/运行时缓存、不进 Web 的 localStorage/sessionStorage；不提供回查接口；失败响应、异常和 Node 错误体不得带密码；含密码响应带 `Cache-Control: no-store`。Node 侧 `chpasswd` 通过 stdin 或安全 exec 执行，命令与异常不得打印 secret，Pydantic 使用 `SecretStr` 等防 repr 泄露。
- **复用与边界**：复用现有 `operation_logs` 与后台线程模式；新增 `OperationType.RESET_CONTAINER_PASSWORD="reset_container_password"`，新增协作者沿用 `ADD_COLLABORATOR`（不新增密码专用 oplog），ROOT 交接每步沿用 `UPDATE_COLLABORATOR_ROLE`，创建保持 `CREATE_CONTAINER`。不新增表/列/迁移/持久队列/租约，不重构测试目录，不改 Node WSS 协议，不改协作者移除逻辑，不新增全局角色唯一约束、repo 原子双绑定函数。主机/容器状态 guard 在受理前执行；后台只复用最小既有 guard 复核，不新增 DTO 或持久状态。所有凭据响应带 `Cache-Control: no-store`。后台“受理”仅表示进程内任务已启动，不是持久/可恢复承诺；oplog 未知结果（如超时）不得写成 Node 确认成功。

## Capabilities

### New Capabilities

- 无：本变更在现有能力内新增或修改 Requirement，不新建 capability。

### Modified Capabilities

- `backend--table-containers`：创建/恢复 root 密码、新增协作者密码、容器账号密码重置、密码不持久化与不可回查。
- `backend--table-user-container`：明确普通角色切换、ROOT 降 ADMIN 的独立账号密码、ROOT 两步交接的角色结果与后台执行。
- `backend--table-users`：权限快照增加派生非持久的容器资源通配字段。
- `backend--table-operation-logs`：新增密码类操作的异步结果审计、`reset_container_password` 操作码与无密码约束。

## Impact

- **Ctrl API**：`/api/containers/create_container`、`/api/containers/resurrect_container`、`/api/containers/add_collaborator`、`/api/containers/update_role`（请求新增 `transfer_root:false` 默认）的响应/请求扩展；新增 `/api/containers/reset_container_password`；`/api/users/me/permissions` 增加 `container_resource_unrestricted`。
- **Ctrl 代码**：`api/container_api.py`、`api/user_api.py`、`schemas/container.py`、`services/container_tasks.py`、`services/container_module/creation.py`、`services/container_module/collaborators.py`、`services/container_module/restore.py`（`restore_accounts` 瞬时密码）、`services/user_tasks.py`（删除用户内部 ROOT 提升密码）、`services/container_module/operation_guard.py`、`constant.py`（新增 `RESET_CONTAINER_PASSWORD`），以及新增的密码/后台工具模块。不改表结构、模型持久化或迁移；不新增 `usercontainer_repo` 双绑定交接函数。
- **跨仓库合同（父代理已对齐）**：统一响应 `credentials:[{login_name,password}]`、`accepted:true`；创建顶层 `root_password`；新增协作者 `add_collaborator config.password`；重置 `reset_container_password config.password`；ROOT 交接 `update_role transfer_root:true` + `config.root_password`（目标升 ROOT）与 `config.password`（旧 ROOT 降 ADMIN 的独立账号）；详情单目标升 ROOT `transfer_root:false`（或省略）+ `config.root_password`。Node 无 `transfer_root` 字段，不返回 secret，仍只处理单目标；Ctrl 后台按既有顺序逐步调用并落绑定。Node 目标升 ROOT 的 sudo/wheel 摘除按既有预期最终组状态做最小幂等处理，不改变角色/归档结果；错误输出、密码路由 422 input 和 helper 不得把 secret 放进日志或 argv。
- **Web（父代理已对齐）**：没有额外 Home 重置按钮；重置只在详情页账号卡。创建、新增协作者、ROOT 交接、详情重置共用同一密码弹窗；Home/EditUserModal 交接显式传 `transfer_root:true`，详情页单目标默认 false。组件只渲染 `credentials` 数组，正常交接两项，历史多 ROOT 可多于两项；恢复成功最小复用 `CredentialModal` 展示 root 凭据，`requires_choice` 不展示。凭据 API 去掉 secret 字段/unsafe 原始 body 但保留安全 `message`（如资源超限数值）；DOM 清除组件状态和引用/关闭不可回看，不承诺 JS 字符串物理零化。密码只在内存态，不使用全局错误日志持久化，不写 localStorage/sessionStorage。重置按钮可见/可用条件为 ROOT 绑定或 `container_resource_unrestricted`，UI 与后端三层守卫一致。
- **数据与迁移**：不改表结构、模型持久化或迁移；不新增密码列/表。
- **测试**：后续本地隔离测试使用现有 SQLite 与 mock Node；完整套件优先父代理提供的 WSL Linux 环境（有 `du`），Windows 隔离环境可作补充；本 propose 阶段不运行测试、不连远程。
