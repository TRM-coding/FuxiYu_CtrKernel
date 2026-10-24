# user_container

## Purpose

用户与容器的协作角色及账号映射。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: user_container 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `UserContainer`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: user_container 生产职责与生命周期

系统 SHALL 按以下生命周期使用本表：复合主键 user_id/container_id；role 用 ROLE 枚举控制协作操作；public_key/username 是 Node 账号操作输入。普通非 ROOT 的 ADMIN/COLLABORATOR 互换只更新该绑定 role，Ctrl MUST NOT 生成/发送/重置密码。ROOT 请求用 `transfer_root` 区分：false（默认）只升目标、不降旧 ROOT；true 先降旧 ROOT 为 ADMIN，再升目标。旧 ROOT 降 ADMIN MUST 用其系统用户名创建/确保独立账号并设随机密码；目标升 ROOT 后 `username=root`。MUST NOT 新增全局唯一 ROOT 约束；其他绑定/账号规则不变，现有目录与账号归档规则保持。

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

### Requirement: 单目标 ROOT 提升（transfer_root=false）

当 `updated_role=ROOT` 且 `transfer_root` 为 false/省略时，Ctrl SHALL 沿用 ContainerDetailPage 单目标行为：只把目标绑定升 ROOT、生成共享 root 新密码，MUST NOT 遍历/降级旧 ROOT 或创建旧 owner 独立账号。预检通过后立即返回 `accepted:true` 与一项 `login_name=root` 凭据；后台以 Node `update_role(ROOT)` 的 `config.root_password` 设置共享 root，成功后更新目标绑定并记一条 `UPDATE_COLLABORATOR_ROLE`。Node 请求 MUST NOT 含 `transfer_root`；含凭据响应 SHALL 带 `Cache-Control: no-store`。

#### Scenario: 详情页单目标升 ROOT 只返回 root 一项

- **GIVEN** 容器 online，已有旧 ROOT 绑定 A，目标 B 是非 ROOT 绑定，`transfer_root` 省略
- **WHEN** 调用 `update_role(user_id=B, updated_role=ROOT)`
- **THEN** 响应 `accepted:true` 且 `credentials` 恰有一项 `login_name=root`；A 的绑定仍为 ROOT/原 username；Node 只收到 B 的单目标 `update_role(ROOT)` 与 `config.root_password`

#### Scenario: 单目标升 ROOT 不生成旧 owner 账号

- **GIVEN** `transfer_root=false`，容器已有 ROOT 绑定
- **WHEN** 目标升 ROOT
- **THEN** 不生成旧 ROOT 的独立账号密码、不调用旧 ROOT 的 `update_role(ADMIN)`、不返回第二项凭据；既有共享 root 密码按本次新值设置

#### Scenario: 机器/容器/目标不可用时不生成密码

- **GIVEN** 机器离线/维护、容器非 online，或目标未绑定/用户名不可用
- **WHEN** 调用单目标 ROOT 提升
- **THEN** 返回对应现有错误，不生成密码、不调用 Node

### Requirement: ROOT 交接（transfer_root=true）

当 `updated_role=ROOT` 且 `transfer_root=true` 时，Ctrl SHALL 按 Home/EditUserModal 既有顺序执行完整交接：旧 ROOT（目标除外）先降 ADMIN，目标再升 ROOT。预检通过后为每个旧 ROOT 生成独立账号密码、为目标生成共享 root 新密码，并立即返回 `accepted:true` 与 `credentials`：正常单旧 ROOT 两项（root + 旧 ROOT 用户名），历史多 ROOT 返回 root + 所有旧 ROOT 各项，MUST NOT 丢涉及人或为凑恰好两项篡改角色。后台按旧 ROOT 降级、目标升级顺序执行；调用者是旧 ROOT 也不得中断。Node 请求 MUST NOT 含 `transfer_root`；含凭据响应 SHALL 带 `Cache-Control: no-store`。

#### Scenario: 正常单旧 ROOT 交接返回两项不同登录名

- **GIVEN** 容器 online，恰有一个旧 ROOT 绑定 A，目标 B 是非 ROOT 绑定，`transfer_root=true`
- **WHEN** 调用 `update_role(user_id=B, updated_role=ROOT)`
- **THEN** 响应 `accepted:true` 且 `credentials` 恰有两项：`root` 一项与 A 的系统用户名一项，两个密码不同；后台先以 A 的系统用户名和密码降 ADMIN，再以 root 新密码升 B

#### Scenario: 旧 ROOT 降 ADMIN 的独立账号使用其系统用户名

- **GIVEN** 旧 ROOT 绑定 A 的 `username` 是 `root`，A 在用户表中的用户名为 `alice`，`transfer_root=true`
- **WHEN** 执行交接第一步
- **THEN** Node 收到的 `config.user_name` 与凭据 `login_name` 都是 `alice`，Node 用响应中提供的密码创建/确保 `alice` 独立账号；成功后 A 的绑定为 ADMIN/`username=alice`

#### Scenario: 直接 ROOT 降 ADMIN 也返回独立账号密码

- **GIVEN** 目标绑定当前为 ROOT，调用方请求 `updated_role=ADMIN`
- **WHEN** 执行该降级
- **THEN** Ctrl 生成独立账号密码、立即返回 `accepted:true` 与该用户名的一项凭据，后台用 `config.password` 调 Node 降 ADMIN 并更新绑定；不依赖 `transfer_root`，也不把该路径当成普通非 ROOT 角色互换

#### Scenario: 多个旧 ROOT 时逐项处理并返回

- **GIVEN** 容器有多个 ROOT 绑定，目标为另一个非 ROOT 绑定，`transfer_root=true`
- **WHEN** 执行 ROOT 交接
- **THEN** 按现有 Web 循环逐个把旧 ROOT 降为 ADMIN，每个旧 ROOT 返回一项以其系统用户名为 `login_name` 的凭据，再加 root 一项；不得丢弃任何涉及人、不得为凑恰好两项篡改角色，不新增或删除账号，不改变该循环的角色规则

#### Scenario: `transfer_root=false` 不进入交接循环

- **GIVEN** 容器有旧 ROOT 绑定，请求 `updated_role=ROOT` 但 `transfer_root` 为 false 或省略
- **WHEN** 调用 `update_role`
- **THEN** 走单目标 ROOT 提升，不遍历/降级旧 ROOT，不生成旧 owner 独立账号，只返回 root 一项；不得因实现交接而改变详情页既有角色结果

#### Scenario: 机器或容器不可用时不生成密码

- **GIVEN** 机器离线/维护，或容器 `effective_status` 不是 online
- **WHEN** 请求 ROOT 交接
- **THEN** 返回对应错误，不生成密码、不调用 Node

#### Scenario: 目标未绑定或用户名不可用时不生成密码

- **GIVEN** 目标 `user_id` 不是该容器有效绑定，或任一涉及用户没有安全可用的系统用户名
- **WHEN** 请求 ROOT 交接
- **THEN** 返回 409 `target_not_bound`/`invalid_target_account`，不生成密码、不调用 Node

#### Scenario: 调用者先被降级也不影响后续步骤

- **GIVEN** 发起交接的调用者本身就是旧 ROOT 之一，`transfer_root=true`
- **WHEN** 后台先把调用者降为 ADMIN
- **THEN** 后台继续执行剩余旧 ROOT 与目标升 ROOT 步骤，不因 HTTP 资源权限变化返回 403 或中断

### Requirement: ROOT 交接的逐步执行与失败边界

`transfer_root=true` 的 ROOT 交接后台 SHALL 按现有目标逐步调用 Node `update_role`：旧 ROOT 使用 `config.password` 降 ADMIN，成功后把该绑定改为 ADMIN/系统用户名并记成功；全部旧 ROOT 成功后才用 `config.root_password` 升目标 ROOT，成功后把目标绑定改为 ROOT/`username=root` 并记成功。每步执行前 SHALL 复用最小既有机器/容器在线 guard；复核失败 MUST NOT 调用 Node，只记失败。任一步失败 MUST 停止后续步骤，已完成步骤如实保留并记成功，失败步骤记失败，MUST NOT 伪报整体完成，MUST NOT 回滚或新增持久/DTO 状态。Node `update_role` 仍只处理指定目标，MUST NOT 自动扫描或修改其他账号。所有输出 MUST NOT 含密码。含凭据响应 SHALL 带 `Cache-Control: no-store`。

#### Scenario: 两步成功各记一条真实日志

- **GIVEN** ROOT 交接后台正常执行
- **WHEN** 旧 ROOT 降 ADMIN 与目标升 ROOT 都成功
- **THEN** 两个步骤各记一条 `UPDATE_COLLABORATOR_ROLE` 成功日志，绑定分别落为 ADMIN/系统用户名与 ROOT/`username=root`，日志不含密码

#### Scenario: 第一步失败不继续第二步

- **GIVEN** ROOT 交接已受理并返回凭据
- **WHEN** 某个旧 ROOT 的 Node `update_role(ADMIN)` 失败
- **THEN** Ctrl 停止后续步骤，目标不会被升为 ROOT；该失败步骤写失败 oplog，任何已完成的前序步骤保留，日志不含密码

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

### Requirement: 删除用户内部 ROOT 提升的密码兼容

删除用户触发 ROOT 提升时，Ctrl SHALL 保持现有删除用户的同步步骤与角色规则，生成随机 root 密码并随 Node `update_role(ROOT)` 的 `config.root_password` 传入；MUST NOT 使用 `transfer_root=true` 的 Web 交接编排，MUST NOT 回退弱密码，MUST NOT 要求额外 HTTP 凭据或把该内部提升改成后台受理。该路径 MUST NOT 改变删除用户页面/业务规则、后续降级/移除/删除顺序或新增持久状态。

#### Scenario: 删除用户内部提升生成随机 root 密码

- **GIVEN** 删除用户前发现某容器需要把 ROOT 转给另一绑定用户
- **WHEN** 执行现有删除用户的内部提升步骤
- **THEN** Ctrl 生成非空随机 root 密码，Node 收到单目标 `config.root_password` 且该值不是 `{user_name}123`；不触发 `transfer_root=true` 的旧 ROOT 遍历，随后继续现有降级/移除/删除步骤，不产生 HTTP 凭据响应

#### Scenario: 内部提升失败不回退弱密码

- **GIVEN** Node 对删除用户触发内部 ROOT 提升返回失败
- **WHEN** 删除用户流程继续判定
- **THEN** 按现有删除失败路径返回，不重试 `{user_name}123`/空密码，不新增持久状态或伪造凭据；日志不含密码或 Node 原始请求/响应体

## Data model appendix

### user_container 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `user_id` | `db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)` | 11 |
| `container_id` | `db.Column(db.Integer, db.ForeignKey('containers.id', ondelete='CASCADE'), primary_key=True, nullable=False)` | 16 |
| `role` | `db.Column(db.Enum(ROLE), nullable=False)` | 23 |
| `granted_at` | `db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)` | 24 |
| `public_key` | `db.Column(db.String(500), nullable=True)` | 25 |
| `username` | `db.Column(db.String(120), nullable=False)` | 26 |

## Source references

- [models/usercontainer.py](../../../models/usercontainer.py)：UserContainer，第 8 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

