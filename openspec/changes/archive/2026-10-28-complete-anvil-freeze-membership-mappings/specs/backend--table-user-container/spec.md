# Spec Delta

## MODIFIED Requirements

### Requirement: user_container 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `UserContainer`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: user_container 生产职责与生命周期

系统 SHALL 以 user_id/container_id 复合主键记录唯一用户绑定，以 ROLE 控制协作权限，以 public_key/username 作为 Node 账号输入。普通非 ROOT 的 ADMIN/COLLABORATOR 互换 MUST NOT 生成或重置密码。外部 ROOT 请求 SHALL 统一执行下文规定的完整交接；旧 ROOT 降为 ADMIN 后保留独立系统账号，目标成为 ROOT 后 username=root。现有目录和账号归档规则保持，MUST NOT 为本能力新增表、字段、持久化工作流或全局唯一 ROOT 数据库约束。

#### Scenario: 协作角色变更

- **WHEN** 服务接受某用户某容器的角色变更
- **THEN** 更新唯一绑定上的 role，供后续鉴权及 Node 协作账号同步读取

#### Scenario: 普通非 ROOT 角色互换不改密码

- **GIVEN** 目标用户已绑定容器，当前角色为 ADMIN 或 COLLABORATOR
- **WHEN** 通过 `update_role` 切换到另一个非 ROOT 角色
- **THEN** Ctrl 只更新该绑定的 role，Node 请求不含密码字段；root 密码与目标账号密码均不变

#### Scenario: 旧 ROOT 降为 ADMIN 保留独立账号密码

- **GIVEN** 目标用户当前是 ROOT 绑定，Ctrl 已生成其独立账号密码
- **WHEN** 执行 ROOT 降 ADMIN 的交接步骤
- **THEN** Node 用该密码创建/确保目标系统用户名的独立账号，Ctrl 把该绑定改为 ADMIN 且 `username` 写为目标用户系统用户名；不删除其他绑定

### Requirement: 外部 ROOT 请求统一完整交接

任何外部 `update_role` 请求只要 `updated_role=ROOT`，Ctrl MUST 执行同一条完整交接，不得因 `transfer_root` 省略、false 或 true 走不同路径。Ctrl SHALL 以该容器现有 ROOT（目标除外）为旧 ROOT，逐个降为 ADMIN；全部成功后再把目标升为 ROOT，最终只保留目标一个 ROOT。MUST NOT 保留或新增“只升目标、不降旧 ROOT”的外部单目标旁路。预检通过后为目标生成共享 root 新密码、为每个旧 ROOT 生成独立账号密码，并立即返回 `accepted:true` 与 `credentials`：正常单个旧 ROOT 两项（root + 旧 ROOT 系统用户名），历史多 ROOT 返回 root + 所有旧 ROOT 各项。`transfer_root` 仅作旧客户端兼容输入，MUST NOT 进入 Node wire，MUST NOT 改变路由、顺序或凭据数量。含凭据响应 SHALL 带 `Cache-Control: no-store`。

#### Scenario: flag 省略、false、true 执行同一完整交接

- **GIVEN** 容器 online，已有旧 ROOT 绑定 A，目标 B 是非 ROOT 绑定
- **WHEN** 分别以 `transfer_root` 省略/false/true 调用 `update_role(user_id=B, updated_role=ROOT)`
- **THEN** 三种请求都返回 `accepted:true` 且 `credentials` 恰有两项：`root` 与 A 的系统用户名，密码互不相同；后台都先降 A 为 ADMIN，再升 B 为 ROOT；最终只有 B 一个 ROOT，Node 请求均不含 `transfer_root`

#### Scenario: 多个旧 ROOT 逐个降级后目标成为唯一 ROOT

- **GIVEN** 容器有多个 ROOT 绑定，目标为另一个非 ROOT 绑定
- **WHEN** 执行外部 ROOT 请求的完整交接
- **THEN** 按现有 handover 循环逐个把旧 ROOT 降为 ADMIN，全部成功后才把目标升为 ROOT；每个旧 ROOT 返回一项以其系统用户名为 `login_name` 的凭据，再加 root 一项；不得丢弃任何涉及人、不得为凑恰好两项篡改角色；最终只有目标一个 ROOT

### Requirement: ROOT 交接的受理与凭据

外部 ROOT 请求的完整交接 SHALL 按旧 ROOT（目标除外）先降 ADMIN、目标再升 ROOT 的顺序执行。预检通过后为每个旧 ROOT 生成独立账号密码、为目标生成共享 root 新密码，并立即返回 `accepted:true` 与 `credentials`：正常单个旧 ROOT 两项（root + 旧 ROOT 用户名），历史多 ROOT 返回 root + 所有旧 ROOT 各项，MUST NOT 丢涉及人或为凑恰好两项篡改角色。后台按旧 ROOT 降级、目标升级顺序执行；调用者是旧 ROOT 也不得中断。Node 请求 MUST NOT 含 `transfer_root`；含凭据响应 SHALL 带 `Cache-Control: no-store`。

#### Scenario: 正常单个旧 ROOT 交接返回两项不同登录名

- **GIVEN** 容器 online，恰有一个旧 ROOT 绑定 A，目标 B 是非 ROOT 绑定
- **WHEN** 调用外部 `update_role(user_id=B, updated_role=ROOT)` 请求
- **THEN** 响应 `accepted:true` 且 `credentials` 恰有两项：`root` 一项与 A 的系统用户名一项，两个密码不同；后台先以 A 的系统用户名和密码降 ADMIN，再以 root 新密码升 B

#### Scenario: 旧 ROOT 降 ADMIN 的独立账号使用其系统用户名

- **GIVEN** 旧 ROOT 绑定 A 的 `username` 是 `root`，A 在用户表中的用户名为 `alice`
- **WHEN** 执行交接第一步
- **THEN** Node 收到的 `config.user_name` 与凭据 `login_name` 都是 `alice`，Node 用响应中提供的密码创建/确保 `alice` 独立账号；成功后 A 的绑定为 ADMIN/`username=alice`

#### Scenario: 直接 ROOT 降 ADMIN 也返回独立账号密码

- **GIVEN** 目标绑定当前为 ROOT，调用方请求 `updated_role=ADMIN`
- **WHEN** 执行该降级
- **THEN** Ctrl 生成独立账号密码、立即返回 `accepted:true` 与该用户名的一项凭据，后台用 `config.password` 调 Node 降 ADMIN 并更新绑定；该路径不受旧兼容字段影响，也不把该路径当成普通非 ROOT 角色互换

#### Scenario: 机器或容器不可用时不生成密码

- **GIVEN** 机器离线/维护，或容器 `effective_status` 不是 online
- **WHEN** 发起外部 ROOT 请求
- **THEN** 返回对应错误，不生成密码、不调用 Node

#### Scenario: 目标未绑定或用户名不可用时不生成密码

- **GIVEN** 目标 `user_id` 不是该容器有效绑定，或任一涉及用户没有安全可用的系统用户名
- **WHEN** 发起外部 ROOT 请求
- **THEN** 返回 409 `target_not_bound`/`invalid_target_account`/`invalid_root_owner_account`，不生成密码、不调用 Node

#### Scenario: 调用者先被降级也不影响后续步骤

- **GIVEN** 发起交接的调用者本身就是旧 ROOT 之一
- **WHEN** 后台先把调用者降为 ADMIN
- **THEN** 后台继续执行剩余旧 ROOT 与目标升 ROOT 步骤，不因 HTTP 资源权限变化返回 403 或中断

### Requirement: ROOT 交接的逐步执行与失败边界

外部 ROOT 请求的交接后台 SHALL 按现有目标逐步调用 Node `update_role`：旧 ROOT 使用 `config.password` 降 ADMIN，成功后把该绑定改为 ADMIN/系统用户名并记成功；全部旧 ROOT 成功后才用 `config.root_password` 升目标 ROOT，成功后把目标绑定改为 ROOT/`username=root` 并记成功。每步执行前 SHALL 复用最小既有机器/容器在线 guard；复核失败 MUST NOT 调用 Node，只记失败。任一步失败 MUST 停止后续步骤，降级失败时 MUST NOT 继续提拔目标；已完成步骤如实保留并记成功，失败步骤记失败，MUST NOT 伪报整体完成，MUST NOT 回滚或新增持久/DTO 状态。Node `update_role` 仍只处理指定目标，MUST NOT 自动扫描或修改其他账号。所有输出 MUST NOT 含密码。含凭据响应 SHALL 带 `Cache-Control: no-store`。

#### Scenario: 两步成功各记一条真实日志

- **GIVEN** ROOT 交接后台正常执行
- **WHEN** 旧 ROOT 降 ADMIN 与目标升 ROOT 都成功
- **THEN** 两个步骤各记一条 `UPDATE_COLLABORATOR_ROLE` 成功日志，绑定分别落为 ADMIN/系统用户名与 ROOT/`username=root`，日志不含密码

#### Scenario: 第一步失败不继续第二步

- **GIVEN** ROOT 交接已受理并返回凭据
- **WHEN** 某个旧 ROOT 的 Node `update_role(ADMIN)` 失败
- **THEN** Ctrl 停止后续步骤，目标不会被升为 ROOT；该失败步骤写失败 oplog，任何已完成的前序步骤保留，日志不含密码

#### Scenario: 多个旧 ROOT 中任一降级失败也不提拔目标

- **GIVEN** ROOT 交接已受理，容器有多个旧 ROOT
- **WHEN** 前一个旧 ROOT 已降为 ADMIN，后一个旧 ROOT 的 `update_role(ADMIN)` 失败
- **THEN** Ctrl 立即停止，不再调用目标升 ROOT；目标保持非 ROOT，已完成降级与失败步骤如实记录，不会新增目标 ROOT

#### Scenario: 第二步失败不伪报整体成功

- **GIVEN** 全部旧 ROOT 已成功降为 ADMIN
- **WHEN** 目标升 ROOT 的 Node 请求或目标绑定更新失败
- **THEN** 旧 ROOT 已完成的 ADMIN 变更保留并如实记录，目标不记 ROOT 成功；写失败 oplog，不写整体交接成功，不回滚、不含密码

#### Scenario: 绑定更新失败也停止后续步骤

- **GIVEN** 某一步 Node 已返回成功，但 Ctrl 写入对应绑定失败
- **THEN** 停止后续步骤，记录该步失败（如 `root_handover_binding_failed`），不把该步或整体描述为完成，不回滚已完成的 Node/绑定结果，输出不含密码

#### Scenario: 后台最小 guard 复核失败只记失败

- **GIVEN** ROOT 交接已受理，但后台执行下一步前机器/容器已不满足最小在线 guard
- **WHEN** 后台任务运行
- **THEN** 不调用该步 Node、不写该步成功日志；写失败 oplog，已完成步骤保留，不新增 DTO/持久状态，输出不含密码

#### Scenario: Node 只改指定目标

- **GIVEN** Ctrl 后台逐步调用 Node `update_role`
- **WHEN** 处理某个旧 ROOT 或目标
- **THEN** Node 只处理该次请求指定的用户，不自动扫描、降级或修改其他 ROOT/账号；Ctrl 负责按既有循环逐个发起；Node 请求不含 `transfer_root`

### Requirement: ROOT 交接的并发串行化与已受理冲突

同一容器的外部角色变更、ROOT 交接与降级、删除用户内部 ROOT 提升及同容器移交段 MUST 共用同一把可重入容器锁。实现 SHALL 仅使用标准库：POSIX 私有临时目录中的空标记文件与 fcntl.flock 提供同机进程互斥，threading.RLock 提供线程互斥；无 fcntl 时 SHALL 使用线程锁，模块仍能正常导入、运行。锁标记 MUST NOT 保存密码或业务状态，MUST NOT 新增表、字段、租约或持久化工作流。

并发范围 MUST 如实限定为“当前部署的单 Linux Ctrl 主机”：POSIX 文件锁覆盖同机多个 Ctrl 进程，线程锁覆盖同进程；多 Ctrl 主机、Windows 跨进程与真实生产 MySQL 互斥不在本轮承诺。已受理交接是异步的，后受理任务允许以 `root_handover_stale` 结束，但其已返回凭据 MUST NOT 被执行；成功完成后最终仍恰好一个 ROOT。

#### Scenario: 真实线程同容器并发只允许一个交接完成

- **GIVEN** 两个真实线程在 barrier 后同时执行同一容器、不同目标的已受理交接
- **WHEN** 两个任务竞争同容器线程锁/文件锁
- **THEN** 只有一个任务完成降旧 ROOT、升目标并发送对应 Node 命令；另一个任务 stale 退出且零 Node；最终 ROOT 集合恰为一个，Node 命令只归属胜出任务的凭据

#### Scenario: 同机独立进程竞争同一容器锁

- **GIVEN** 同一 Ctrl 主机上两个独立进程使用同一锁 helper
- **WHEN** 一个进程持有某 `container_id` 的锁，另一个进程尝试获取同一锁
- **THEN** 第二个进程阻塞到第一个释放后才获得锁；锁文件保持空标记，不含密码或业务状态

### Requirement: ROOT 交接的身份预检与获锁复核

外部 ROOT 交接后台 SHALL 在整个交接 job 期间持锁。获得锁后、任何 Node 命令前，Ctrl SHALL 用独立只读 session 重读当前 ROOT `user_id`/系统用户名集合、目标绑定角色与目标系统用户名，并与受理快照比较；不一致时 MUST 记录固定 `root_handover_stale` 失败并退出，MUST NOT 使用受理时返回的旧密码调用 Node。外部请求预检 SHALL 在生成密码/返回 200/调用 Node 前拒绝目标系统用户名为 `root` 或以 `-` 开头、旧 ROOT 系统用户名以 `-` 开头的情况；保留既有目标未绑定、机器/容器 guard 与多旧 ROOT 逐个回收语义。

#### Scenario: 已受理的同容器交接冲突以 stale 结束

- **GIVEN** 同一容器先后受理两个不同目标的 ROOT 交接，且都返回凭据
- **WHEN** 第一个后台任务完成交接，第二个后台任务随后获得同容器锁
- **THEN** 第二个任务重读发现 ROOT 集合/目标角色/用户名已变化，记录一条 `root_handover_stale` 失败并在任何 Node 命令前退出；最终恰好一个 ROOT，第二个响应中的密码不出现在 Node wire 或日志

#### Scenario: Node 不可用用户名在预检被拒

- **GIVEN** 目标系统用户名为 `root` 或以 `-` 开头，或旧 ROOT 系统用户名以 `-` 开头
- **WHEN** 发起外部 ROOT 交接
- **THEN** 在生成任何密码、返回 200 或调用 Node 前返回对应 `invalid_target_account`/`invalid_root_owner_account` 错误，不产生凭据

### Requirement: ROOT 交接保留逐步提交事实

交接的每一步 SHALL 继续使用各自的 `session_scope`/repo 提交，机器/容器 guard 与成功/失败审计 SHALL 每步新鲜读取；MUST NOT 用一个长事务包住全部步骤。某一步的机器中途维护、DB 或审计异常只影响该步，已完成步骤的绑定与成功日志 MUST 保留，MUST NOT 整批回滚。删除用户既有步骤、角色与顺序 MUST NOT 重构：同一容器的“提升新 ROOT → 旧 owner 降级 → 移除旧 owner”移交段可用同一锁包住，并在开始前核实旧 owner 仍为 ROOT，核实失败即按既有失败路径退出。

#### Scenario: 机器中途维护或 DB/审计异常不整批回滚

- **GIVEN** 第一个旧 ROOT 已成功降 ADMIN 并完成绑定/成功日志提交
- **WHEN** 下一步前机器进入维护/离线，或该步绑定/审计写抛 DB/审计异常
- **THEN** 第一步的 ADMIN 绑定与成功日志保留；目标不因该异常被伪报成功；不出现整批回滚

### Requirement: 删除用户内部 ROOT 提升的密码兼容

删除用户触发 ROOT 提升时，Ctrl SHALL 保持现有删除用户的同步步骤与角色规则，生成随机 root 密码并随 Node `update_role(ROOT)` 的 `config.root_password` 传入；MUST NOT 使用外部 ROOT 请求的完整交接编排，MUST NOT 回退弱密码，MUST NOT 要求额外 HTTP 凭据或把该内部提升改成后台受理。该路径 MUST NOT 改变删除用户页面/业务规则、后续降级/移除/删除顺序或新增持久状态。

#### Scenario: 删除用户内部提升生成随机 root 密码

- **GIVEN** 删除用户前发现某容器需要把 ROOT 转给另一绑定用户
- **WHEN** 执行现有删除用户的内部提升步骤
- **THEN** Ctrl 生成非空随机 root 密码，Node 收到单目标 `config.root_password` 且该值不是 `{user_name}123`；不触发外部 ROOT 请求的旧 ROOT 遍历，随后继续现有降级/移除/删除步骤，不产生 HTTP 凭据响应

#### Scenario: 内部提升失败不回退弱密码

- **GIVEN** Node 对删除用户触发内部 ROOT 提升返回失败
- **WHEN** 删除用户流程继续判定
- **THEN** 按现有删除失败路径返回，不重试 `{user_name}123`/空密码，不新增持久状态或伪造凭据；日志不含密码或 Node 原始请求/响应体
