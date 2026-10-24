## Context

当前 Node 创建容器时把 root 密码设为 `{owner_name}123`；`add_collaborator` 用 `{user_name}123` 创建协作者账号；`update_role(ROOT)` 把共享 root 密码设为 `{user_name}123` 并归档/删除目标原有的独立账号；`update_role(ADMIN)` 在独立账号不存在时创建它。Ctrl 没有容器账号密码重置接口。

真实的 ROOT 交接已经存在于 Web `src/components/EditUserModal.jsx`：把目标用户设为 ROOT 时，先遍历当前 ROOT 账号（目标除外）逐个调用 `updateRole(ADMIN)`，再调用目标 `updateRole(ROOT)`；UI 同步把旧 ROOT 显示为 ADMIN，并从用户列表恢复其用户名。这个多步编排先降级调用者，后续请求可能 403，也无法一次交付两个账号密码。本变更保留这条既有角色结果，把编排移入 Ctrl 后台，并只增加密码生成/下发、后台执行与审计；不新增角色规则、不新增持久状态。

`/api/users/me/permissions` 已有 `image_resource_unrestricted` 的先例：资源通配不能从 `entities`/方法通配反推。容器需要同样的派生布尔字段。

## Goals / Non-Goals

**Goals:**

- 创建/恢复：Ctrl 生成 root 密码，经创建载荷顶层 `root_password` 交给 Node；Node 必须使用，不得回退到 owner/username 派生值。
- 新增 ADMIN/COLLABORATOR 协作者：Ctrl 生成密码，经 `add_collaborator config.password` 设置；受理后返回一次性凭据，后台完成 Node + 绑定 + 既有 `ADD_COLLABORATOR` 审计。
- 手动重置：新增 `POST /api/containers/reset_container_password`，完成权限、目标绑定、机器/容器在线校验后立即返回随机密码，后台调用 Node 同步 `chpasswd`，结果只写 `reset_container_password` oplog。
- ROOT 交接：保留现有“旧 ROOT 先降 ADMIN、目标再升 ROOT”的角色结果；Ctrl 后台按同一顺序逐步调用 Node 并落绑定，一次返回 root 与旧 ROOT 独立账号的凭据。
- 权限快照新增派生非持久的 `container_resource_unrestricted`，供 Web 判断资源级重置权限。
- 统一一次性凭据响应、后台执行、审计脱敏和 `no-store`；不新增表/列/迁移/队列/租约。

**Non-Goals:**

- 不新增、减少或重排现有 ROOT 交接角色结果；不新增独立账号规则；Node `update_role` 仍只处理指定目标。
- 不改变协作者移除、普通非 ROOT 角色互换、目录/账号归档规则的现有语义。
- 不实现平台用户密码重置（ManageUser）的改造；Web 可复用外观组件，但不在 Ctrl 变更内。
- 不新增密码回查接口，不持久化密码，不重构测试目录，不添加 Home 重置按钮。
- 不做持久队列、租约、重试、自动回滚或跨进程交接恢复；不新增全局角色唯一约束、repo 原子双绑定函数、迁移或新表列。

## Decisions

### D1：密码生成与生命周期

- 使用 `secrets.token_urlsafe(16)`（约 128 bit 熵，URL-safe ASCII）生成容器账号密码；创建、恢复、新增协作者、重置、ROOT 交接各步骤各自生成，互不复用。
- 密码只在进程内局部变量、后台线程参数和一次性 HTTP 响应中出现；不写数据库、oplog detail、日志、运行时缓存/WSS/action 缓存/Docker 环境或 labels。
- 生成时机放在请求前校验通过之后、启动后台任务或调用 Node 之前；预检失败不生成密码。
- 备选：复用 `user_tasks.Reset_password` 的 `token_urlsafe(12)`。不采用，容器/root 权限更高，16 字节熵更稳妥；不新增可配置项。

### D2：创建/恢复接入

- `Create_container` 增加可选 `root_password`；未显式传入时 Service 生成非空密码，保证直接调用不漏传。
- `_build_create_payload` 始终写顶层 `root_password`；`create_container_api` 生成并传入，成功后返回 `success`/原 `message`/`accepted:true`/root 一项 `credentials`。
- `resurrect_container` 只在真正执行恢复时生成密码并随响应返回；`requires_choice=true` 不生成、不返回。
- 创建/恢复审计仍只走 `_audit_create`/`_audit_restore_success` 单条 `CREATE_CONTAINER`；不新增密码生成/下发日志。

### D3：新增协作者

- `add_collaborator_api` 保留现有权限/在线/目标/角色校验；角色仍只接受 ADMIN/COLLABORATOR（ROOT 走交接）。
- 校验通过后生成随机密码，立即返回 `success`/`message`/`accepted:true`/`credentials:[{login_name:<target username>,password}]`；保留现有 201 状态码。
- 后台调用 Node `POST /api/add_collaborator`，`config` 增加 `password`；Node 用该密码创建账号。成功后调用现有 `_add_collaborator_binding` 并沿用既有 `_audit_collaborator`/`ADD_COLLABORATOR` 成功记录；MUST NOT 为密码新增操作码或第二条日志。失败不写绑定，只记失败。
- 现有协作者删除、绑定冲突和 Node 角色规则不改；如果 Node 失败，密码已返回但账号不可用，结果只由 oplog 反映。
- 备选：保持同步并在 Node 成功后返回密码。不采用，与“请求立即受理返回、实际结果 oplog”一致性和统一客户端弹窗不一致。

### D4：手动重置

- 路由：`POST /api/containers/reset_container_password`；严格请求模型仅 `container_id`/`user_id`，未知字段（含 `login_name`）返回 400 `invalid_payload`。
- 权限依赖复用：`require_permission("container:operation")` + `require_resource("container:root", "container_id")` + `require_machine_of_container("container_id")`。资源层沿用 `has_resource_wildcard` 的“直持”语义：ROOT 绑定、直持 `bypass_resource` 或直持 `container:manage`；`bypass_auth_entity`、ADMIN/COLLABORATOR 绑定不通过。
- Service 预检顺序：加载容器/机器端点 → 目标绑定存在 → `username` 安全（ROOT 固定 `root`；非 ROOT 为空/`root`/非法字符拒绝）→ 机器在线非维护 → 容器 `effective_status=online` → 生成密码 → 启动后台。
- 后台调用 Node `POST /api/reset_container_password`，body `{config:{container_name,user_name,password}}`；Node 同步 `chpasswd` 返回 success。Ctrl 不等待；成功或失败只写一条 `reset_container_password` oplog，detail 仅含 `user_id`/`login_name`。预检错误按现有 `REASON_STATUS_MAP`/`error_reason` 映射 404/409/500；Ctrl 不拼接 Node 原始错误体。
- 后台启动失败视为未受理：500 `reset_not_accepted`，不返回密码、不写成功日志。所有含凭据响应统一 `Cache-Control: no-store`。

### D5：ROOT 请求的 transfer_root 分支

- `update_role` 请求增加纯布尔 `transfer_root:false`（默认）；只影响 Ctrl 的编排，MUST NOT 发给 Node。Node 永远只收到单目标 `update_role` primitive。
- **`transfer_root=false`（详情页现有单目标行为）**：目标升 ROOT 时只生成 root 新密码，后台调 `update_role(ROOT, config.root_password)` 更新目标绑定为 ROOT/`username=root`，返回 root 一项；MUST NOT 遍历/降级旧 ROOT，MUST NOT 创建旧 owner 独立账号。旧 ROOT 绑定保持原样，即使出现多 ROOT 也不新增唯一约束。
- **`transfer_root=true`（Home/EditUserModal 现有交接）**：
  1. 取当前 ROOT 绑定（目标除外）作为 `old_roots`，保持 Web 遍历顺序。
  2. 预检目标绑定存在；`old_roots` 与目标用户都有非空、安全的系统用户名；机器在线非维护；容器 online。HTTP 权限只在受理时校验一次。
  3. 为每个旧 ROOT 生成独立账号密码，为目标生成共享 root 新密码；立即返回 `accepted:true` 与 `credentials`：正常一个旧 ROOT 两项（`root`、旧 ROOT 用户名），多个旧 ROOT 时 root + 每个旧 ROOT 一项，顺序 root 在前；不得丢涉及人或为凑恰好两项篡改角色。响应 `no-store`。
  4. 后台逐步执行：每个旧 ROOT 调 Node `update_role(ADMIN, config.password)`，成功后绑定改 ADMIN/系统用户名并记成功；全部成功后调 Node `update_role(ROOT, config.root_password)`，目标绑定改 ROOT/`username=root` 并记成功。每步前复用最小在线 guard；失败即停止后续，仅记该步失败。
  5. 任一步失败不写“整体交接成功”，不回滚，不新增持久交接状态；Node 只处理本次指定用户。
- 直接 `update_role(target, ADMIN)` 且目标当前为 ROOT 时，是独立的单目标降级：生成独立账号密码、立即返回 `accepted:true` + 一项凭据，后台用 `config.password` 调 Node 并更新绑定；不依赖 `transfer_root`，普通非 ROOT 互换仍同步、无密码。
- 调用者本身是旧 ROOT 且 `transfer_root=true` 时，受理后权限变化不影响后台；这是把既有编排移入 Ctrl 的原因。
- 备选：保留 Web 两次调用。不采用：第一次降级后第二次可能 403、两个响应无法合并成一个弹窗。备选：新增专用 handover 端点。不采用：扩大合同；用请求布尔即可区分两入口。
- 旧 ROOT 独立账号：Node 在 `update_role(ADMIN)` 收到 `config.password` 时创建/确保账号并设置密码；目录与归档规则沿用现有实现。目标升 ROOT 时 Node 仍归档/删除目标原独立账号，登录取共享 root。

### D6：权限快照

- `/api/users/me/permissions` 增加 `container_resource_unrestricted`，值等于 `has_resource_wildcard(user_id, "container")`；与 `image_resource_unrestricted` 并列、各自独立，不落库、不新增表列。ROOT 绑定仍由具体容器的账号数据另行判断，不由该字段替代。
- Web 权限上下文新增 `containerResourceUnrestricted`；重置按钮可见/可用条件为 `isRoot || containerResourceUnrestricted`。不得从 `entities.includes('container:manage')`、`hasAnyManage()` 或其他方法通配推断资源能力。
- 备选：Web 继续从 entities 反推。不采用：`bypass_auth_entity` 会展开出 `container:manage`，但资源层并不放行，已有镜像字段的同类教训。

### D7：后台执行方式

- 复用 `announcement_tasks` 现有的 `threading.Thread(daemon=True)` 模式，新增一个很小的启动 helper（可注入/可 join），在返回响应前启动。
- 不采用 FastAPI `BackgroundTasks`：它绑定在响应发送之后执行，客户端断开/发送失败时存在不执行的风险，不满足“受理后断开不取消”。daemon 线程与请求生命周期解耦；进程退出会终止任务，这是可接受边界（不引入持久队列/租约）。
- 后台线程捕获 Node 调用与绑定更新，所有异常收敛为脱敏 oplog；不上抛、不记录请求/响应体。
- “受理”仅表示进程内任务已启动并返回凭据，不是持久/可恢复承诺；不引入持久队列/租约。
- 测试可替换启动 helper 为同步执行；另设真实线程测试验证断开后仍执行。

### D8：Secret 卫生与错误处理

- 创建/新增/重置/ROOT 交接的 Node 响应不进入 debug 日志；密码类出口只保留 `error_reason`/状态码，不拼接原始响应体到异常。
- `NodeServiceError` 消息不得包含密码或原始请求/响应；后台 failure detail 不含 `str(exc)`，只含稳定 `error_reason` 与目标标识。
- 含密码的成功响应设置 `Cache-Control: no-store`；错误响应不含 `credentials`/密码。
- Node 侧合同要求：密码字段使用 `SecretStr` 等防 repr 类型；`chpasswd` 通过 stdin 或安全 exec，不把密码拼进 shell 命令/日志/异常。
- 不引入全局请求体日志；现有 uvicorn access 日志只记录 method/path。

### D9：oplog 与 OperationType

- 新增 `OperationType.RESET_CONTAINER_PASSWORD = "reset_container_password"`；重置使用该码。新增协作者沿用 `ADD_COLLABORATOR`；ROOT 交接每一步沿用 `UPDATE_COLLABORATOR_ROLE`；创建/恢复保持 `CREATE_CONTAINER` 单条。
- 异步操作受理时不写结果；每个后台步骤结果返回后写一条成功/失败日志。ROOT 交接按步骤如实记录，不写整体成功。Node 超时/未知结果 MUST 写失败或未知原因，MUST NOT 写成 Node 确认成功。日志写入失败不影响已受理操作（沿用 `write_operation_log` 吞异常语义）。
- 详情/日志查询不新增密码字段，不提供回查。

### D10：数据与兼容边界

- 不改表结构、模型持久化、迁移、Docker 环境、WSS 协议、action 缓存。
- 不改现有协作者移除、普通非 ROOT 角色互换、目录/账号归档规则；不复用旧 owner 交接以外的角色迁移。
- `update_role(ROOT)` 的 HTTP 返回取决于 `transfer_root`：false 为详情页单目标受理 + root 一项；true 为 Home/EditUserModal 受理 + root/旧 ROOT 多项。两者最终角色结果分别与对应现有 Web 入口一致；不新增全局唯一 ROOT 约束。

### D11：内部调用兼容（恢复协作者、删除用户）

- **恢复 `restore_accounts`**：Service 在组包恢复账户时为每个非 ROOT 协作者生成互不复用的瞬时随机密码，写入 Node wire 的 `restore_accounts[].password`；该值不得进入恢复快照、数据库 JSON、日志或凭据回查。实际恢复响应仍只交付 root 一项凭据；`requires_choice` 不生成/不返回凭据。Node 若拒绝瞬时密码，恢复失败，不回退 `{username}123` 或空密码。
- **删除用户内部 ROOT 提升**：`Delete_user` 现有步骤（`update_role(new_root, ROOT)` → 降旧 ROOT → 移除绑定 → 删除用户）必须保持同步和原有顺序。内部提升使用单独的同步 helper：生成随机 `root_password`，调用 Node `update_role(ROOT, config.root_password)`，成功后更新目标绑定并记既有 `UPDATE_COLLABORATOR_ROLE`；不触发完整 Web 交接循环、不返回 HTTP 凭据、不改变删除用户规则。失败按现有删除失败路径处理，不回退弱密码。
- 这两条只补密码参数与内部调用兼容，不顺手改恢复/删用户的业务规则、账号归档规则或页面。

### D12：后台最小 guard

- 受理前的机器/容器在线 guard 保持不变；后台在每次 Node 调用前复用最小既有 guard（机器在线非维护、容器 online），失败即不调用 Node、只写该步失败 oplog。
- 不新增 DTO、持久 guard 状态、队列或租约；guard 结果不改变已返回的凭据，只决定 oplog 成功/失败。

## Fixed Cross-Repo Contract

以下字段已由父代理对齐；`credentials` 项只需 `login_name`/`password`，可省略 `user_id`。所有含 `credentials` 的响应统一带 `Cache-Control: no-store`。

### Ctrl HTTP 响应（本仓库约定）

| 端点 | 成功响应关键字段 |
| --- | --- |
| `POST /api/containers/create_container` | 保留 `success`/`message`；新增 `accepted:true`、`credentials:[{login_name:"root",password}]` |
| `POST /api/containers/resurrect_container` | 实际恢复时保留 `container_id`；新增 `accepted:true`、`credentials`（root 一项）；`requires_choice` 时 `accepted:false`、`credentials:[]` |
| `POST /api/containers/add_collaborator` | 保留 201 与 `success`/`message`；新增 `accepted:true`、一项 `credentials`（目标用户名） |
| `POST /api/containers/reset_container_password` | 新增端点，body `{container_id,user_id}`；成功 `success`/`message`/`accepted:true`/`credentials:[{login_name,password}]` |
| `POST /api/containers/update_role`（ROOT，`transfer_root:false`/省略） | `accepted:true` + root 一项；不降旧 ROOT |
| `POST /api/containers/update_role`（ROOT，`transfer_root:true`） | `accepted:true` + root 一项 + 每个旧 ROOT 用户名一项；正常单旧 ROOT 为两项不同登录名 |
| `POST /api/containers/update_role`（ROOT→ADMIN） | `accepted:true` + 一项旧 ROOT 用户名凭据 |
| `POST /api/containers/update_role`（非 ROOT 互换） | 保持现有 `success`/`message`；可带 `accepted:false`、`credentials:[]` |
| `GET /api/users/me/permissions` | 新增派生布尔 `container_resource_unrestricted` |

`update_role` 请求新增 `transfer_root:false` 默认；仅 Ctrl 使用，Node 不接收该字段。

### Ctrl → Node（已对齐）

| 场景 | 方法/路径 | 已对齐字段 |
| --- | --- | --- |
| 创建/恢复 | `POST /api/create_container` | 顶层 `root_password`（必填、非空）；恢复协作者项含瞬时 `password` |
| 新增协作者 | `POST /api/add_collaborator` | 现有 `{config:{container_name,user_name,role}}` 增加 `config.password` |
| 手动重置 | `POST /api/reset_container_password` | `{config:{container_name,user_name,password}}`；同步 `chpasswd` 返回 success |
| ROOT 升目标（详情单目标） | `POST /api/update_role` | 现有 config 增加 `config.root_password`；Node MUST NOT 收到 `transfer_root` 字段 |
| ROOT 升目标（Home/EditUserModal 交接，Ctrl 逐步调用） | `POST /api/update_role` | 同上；Ctrl 每步单目标传 `config.root_password` |
| 旧 ROOT 降 ADMIN | `POST /api/update_role` | 现有 config 增加 `config.password`，用于创建/确保旧 ROOT 独立账号；Node 仍只处理指定用户，不自动扫描 |

Node contract notes:

- Node MUST NOT 在响应中返回 secret；创建/重置/角色变更只返回 success/error_reason。
- Node MUST NOT 接收 `transfer_root` 字段；`update_role` 仍是单目标 primitive，不自动扫描/降级其他账号。
- Node 目标升 ROOT 时摘除不存在的 sudo/wheel 按既有“预期最终组状态”做最小幂等判断；不改变角色最终结果、归档规则，普通角色行为不扩张。
- Node 的 422 脱敏仅限密码相关路由，并保留其他路由的默认错误形状；密码字段的错误 `input` MUST NOT 回显 secret；helper MUST NOT 把 secret 放入 argv，`chpasswd` 走 stdin/安全 exec。
- 本地 FakeDocker 可验证 socket I/O；不宣称真实生产 Docker 验证。

### Web（已对齐）

- 没有额外 Home 重置按钮；重置只在详情页账号卡。创建（Home/CreateContainer）、新增协作者（EditUserModal）、ROOT 交接（Home/EditUserModal 传 `transfer_root:true`）、详情重置/单目标 ROOT（ContainerDetailPage 默认 false）共用同一密码弹窗；组件只渲染 `credentials` 数组，正常交接两项，历史多 ROOT 可多于两项，不得丢涉及人或为凑恰好两项篡改角色。
- 恢复：`DeletedContainers` 成功 restore 最小复用 `CredentialModal` 展示 root 凭据；`requires_choice` 不展示。不改变恢复其他业务/页面布局，不新增恢复队列/日志。
- 权限：`isRoot || containerResourceUnrestricted`；重置 UI 的只读/可用性与后端 `container:operation` + `container:root` + 机器访问/在线三层 guard 一致，不得用 `container:manage`/`hasAnyManage` 等方法通配推断资源通配。详情页本身已通过机器守卫，按钮可见性不额外放宽。
- 凭据 API 去掉 secret 字段和 unsafe 原始 body，但保留安全 `message`（如资源超限的具体数值），不能为脱敏丢掉原有具体错误信息。
- 密码只在内存态；DOM 清除组件状态和引用/关闭后不可回看，不承诺 JS 字符串物理零化；不使用全局错误日志持久化，不写 localStorage/sessionStorage。
- 新增协作者/ROOT 交接改为受理式后，Web 不应只靠本地乐观更新；以后台结果/oplog 为准刷新账号列表。
- 操作日志展示需识别新码 `reset_container_password`；既有 `ADD_COLLABORATOR`/`UPDATE_COLLABORATOR_ROLE` 标签不变。

## Risks / Trade-offs

- **[ROOT 交接部分成功]** → 任一步失败即停止；已完成步骤保留并记成功，失败步骤记失败；不回滚、不写整体成功。用户可能看到旧 ROOT 已变 ADMIN 但目标未升 ROOT，这是“无持久回滚工作流”的明确代价。
- **[调用者自己先被降级]** → 权限只在受理时校验一次，后台不重新做 HTTP 资源门；后台继续执行剩余步骤。
- **[多个旧 ROOT]** → 按现有 Web 循环逐个降 ADMIN，每个旧 ROOT 各一项凭据；正常单旧 ROOT 为两项。弹窗需支持列表，不新增/删除账号。
- **[Node 失败但已返回密码]** → 产品要求受理即返回；失败只写 oplog，Web 后续查 oplog。不伪装完成，不重试。
- **[新增协作者改为受理式]** → 现有 Web 的本地乐观更新可能短暂显示未完成状态；以后台结果/oplog/刷新为准。Node 失败时不写绑定，密码不可用。
- **[旧 Node 忽略新密码字段]** → 旧 Node 若忽略 `root_password`/`config.password`，会继续使用 `owner123`/`user_name123`。部署必须先升级 Node 并验证创建、新增协作者、重置、`update_role` 的密码字段且拒绝缺失/空密码，再启用 Ctrl 生成与下发。
- **[共享 root 密码影响所有 ROOT 用户]** → 这是现有共享 root 语义；交接后旧 ROOT 已降 ADMIN，目标使用 root。本变更不引入按用户 root 密码。
- **[daemon 线程随进程退出]** → 客户端断开不取消；进程重启/退出会丢失在途任务；无持久队列/租约是明确非目标。
- **[并发重置/交接/新增]** → 无租约，最后写入者生效；同一容器并发操作可能互相覆盖密码。按现有运维边界接受。
- **[Node 错误体可能回显请求]** → Ctrl 不拼接原始响应体到异常/日志/oplog；Node 侧仍须保证不把 secret 放进错误文本/422 input。
- **[恢复协作者与删除用户内部路径]** → `restore_accounts` 使用瞬时随机密码且不落 snapshot；`Delete_user` 内部 ROOT 提升保持同步并生成 root_password。若漏改，Node 新必填密码会中断恢复/删用户；实现时以这两条兼容用例为门禁。
- **[后台 guard 复核失败]** → 受理后状态变化时，后台最小 guard 失败只写失败 oplog；已返回密码可能不可用，这是受理式语义，不新增 DTO/回滚。
- **[测试隔离]** → 后续只用现有 SQLite 测试配置和 mock Node；完整套件优先 WSL Linux（有 `du`，`/home/chest/.cache/fuxi-password-tests-offline/bin/python`），Windows 隔离环境（`C:/Users/chest/AppData/Local/fuxi-password-tests/Scripts/python.exe`）可作补充；Node 的 FakeDocker 本地验证 socket I/O，不宣称真实生产 Docker 验证；不连远程、不运行生产测试。本阶段不运行。

## Migration Plan

- 无数据库迁移、无表结构变更、无数据回填。
- 部署顺序：先 Node（创建 `root_password`、`add_collaborator config.password`、`reset_container_password`、`update_role` 的 `config.root_password`/`config.password` 且不打印），再 Ctrl（生成/下发与后台编排），最后 Web（统一密码弹窗、`container_resource_unrestricted`、详情重置）。
- 回滚：Ctrl 可回退到旧同步/旧 Web 编排；无持久化与迁移，回滚不涉及数据清理。已返回的密码无法撤回，只能再次重置覆盖。

## Contract Status

无待决问题：跨仓合同已由父代理对齐。实现时按本设计的固定字段与既有业务路径落地。
