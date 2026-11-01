# Spec Delta

## MODIFIED Requirements

### Requirement: machines 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Machine`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: machines 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：Node 注册固定 uid 和证书指纹；port=NULL 使用全局 Node 端口；gpu_list 为硬件事实、gpu_allow_list 为管理许可；WSS 更新状态、硬件和 last_seen_at。

#### Scenario: 维护或离线窗口

- **WHEN** 机器进入不可用状态后再次可用
- **THEN** 记录 unavailable_since，结束时为 SSH 清理、冻结和删除挂载保留窗口累加补偿

### Requirement: machines 共享内存上限为机器可配置限额

`max_shared_gb` SHALL 是逐机器可配置的分配上限，系统 MUST NOT 以全局固定上限（如 8GB）拒绝更大的合法配置。管理入口更新时输入 SHALL 为可解析为整数且不小于 0 的值，负值、不可解析为整数的值与非整小数 MUST 被拒绝，MUST NOT 静默截断。只要本次更新携带共享上限或内存上限任一字段，系统 SHALL 按实际落库后的状态校验「有效共享 ≤ 有效内存」：本次携带非 null 值取该值，未携带或显式传 null 沿用当前记录，当前记录该字段为 NULL 时视为未知并跳过比较。校验失败 MUST 以 `update_failed` 拒绝且不写入任何字段。请求模型层与容器创建边界见对应 Scenario。

#### Scenario: 超过 8GB 但在内存上限内可保存

- **WHEN** 一台内存上限 32GB 的机器被更新为共享上限 16GB
- **THEN** 更新成功并持久化 `max_shared_gb=16`，不再因固定 8GB 上限被拒

#### Scenario: 只下调内存上限到既有共享之下被拒

- **WHEN** 机器共享上限 16GB、内存上限 32GB，请求只把内存上限改为 8GB（同一请求还夹带改名）
- **THEN** 以 `update_failed` 拒绝；两个上限与机器名都不变，用户的值不被静默改写

#### Scenario: 内存下调到等于既有共享上限可保存

- **WHEN** 机器共享上限 16GB、内存上限 32GB，请求只把内存上限改为 16GB
- **THEN** 更新成功；共享上限保持 16GB，内存上限落库为 16GB

#### Scenario: 同请求把共享与内存设为相等可保存

- **WHEN** 一个请求同时把共享上限与内存上限都设为 8GB
- **THEN** 更新成功，两个字段都落库为 8GB

#### Scenario: 共享上限超过有效内存上限被拒

- **WHEN** 组合后的有效共享上限超过组合后的有效内存上限（如共享 16GB 而内存只有 8GB）
- **THEN** 以 `update_failed` 拒绝，机器记录保持原值

#### Scenario: 负值、非整数与非整小数被拒

- **WHEN** 请求携带负数、无法解析为整数的值，或带小数部分的 3.5
- **THEN** 服务层以 `update_failed`（管理 API 422）拒绝且不落库，3.5 MUST NOT 被截断成 3；请求模型层由整数类型与 `ge=0` 先行挡下，返回 400 与既有 `invalid_payload`

#### Scenario: 显式 null 不能绕过组合约束

- **WHEN** 既有共享上限 16GB、内存上限 32GB，请求分别为 `{max_shared_gb: null, max_memory_gb: 8}` 或 `{max_memory_gb: null, max_shared_gb: 40}`
- **THEN** 两次都以 `update_failed` 拒绝；null 不写入、落库后另一侧仍是原值，两个字段与同请求其它字段都不变

#### Scenario: 没有内存上限的旧记录保持空值语义

- **WHEN** 当前记录的内存上限或共享上限本身为 NULL，请求以非 null 值设置另一侧，或对该 NULL 字段显式传 null
- **THEN** NULL 侧视为未知、跳过比较，非 null 值可保存；不发明全局默认上限，也不把 NULL 顶替成某个数值

#### Scenario: 错误边界分层

- **WHEN** 同一共享内存约束分别在请求模型层传入非整小数、在更新服务层组合越界、在创建容器时共享越界
- **THEN** 三者分别返回 400 与 `invalid_payload`、422 与 `update_failed`、容器创建侧的 `invalid_config`；它们是不同边界，MUST NOT 互相替代或合并为一个错误原因

### Requirement: machines Node 端点解析

系统 SHALL 以「裸主机 + 独立端口列」表达 Node 端点：`machine_ip` 只承载纯 IPv4，MUST NOT 携带 `host:port`（管理入口拒绝含 `:` 的值）；`port` 留空表示使用全局默认端口，取值 SHALL 在调用时现读 `CommsConfig.NODE_PORT`，MUST NOT 在导入期冻结或在登记时把默认值固化进记录。HTTPS 动作请求、WSS 出站拨号与 TOFU 取对端证书三条路径 SHALL 共用同一解析实现；pin 文件键 SHALL 使用不含端口的裸主机。

#### Scenario: 默认端口改动对已登记机器生效

- **WHEN** 某机器记录的 `port` 为空，管理员随后改动全局默认 Node 端口
- **THEN** 该机器的后续出站请求使用改动后的端口；记录里仍留空，不被固化成旧默认值

### Requirement: machines 端点登记与链路重拨

端点字段（`machine_ip` / `port`）的修改 SHALL 是纯登记：MUST NOT 在修改时做出站取证或信任判定，可达性 MUST NOT 作为登记的前置条件；登记后由链路进程负责拨通，由对端 uid 校验身份。

#### Scenario: 端点变更不改信任

- **WHEN** 管理员修改已登记机器的 `machine_ip` 或 `port`
- **THEN** 只更新登记字段，不发起取证、不改写 pin 与证书指纹；链路进程按新地址重新拨号，身份仍由对端 uid 校验

### Requirement: machines 信任重钉与身份处理

「重新钉信任锚」SHALL 由独立操作 `renew_machine_trust` 承担，只更新既有机器行的信任凭证、MUST NOT 增删机器行；对端证书与 enrollment profile SHALL 全部取证成功、必要的身份下发成功后才改动本地 pin 与凭证字段，取证或身份下发失败时 SHALL 保持本地原值。`node_uid` SHALL 仅在对端丢失身份牌时重发、库中无 uid 时采纳对端自报值、两侧都有则保持库值并报出不一致；成功与失败 SHALL 均写操作日志。

#### Scenario: 重钉失败不动旧信任

- **WHEN** `renew_machine_trust` 在取对端证书或取 enrollment profile 时失败
- **THEN** 操作以对应 error_reason 失败，pin 与全部凭证字段保持原值，并留下失败日志

### Requirement: machines 信任重钉持久化失败边界

当前实现先写 pin 文件再提交数据库，数据库持久化失败时返回 persist_failed，不保证 pin 文件回滚；MUST NOT 将整个操作描述为文件与数据库的原子事务。

#### Scenario: 数据库持久化失败不承诺 pin 回滚

- **WHEN** 重新钉信任锚已写入 pin 文件，但后续数据库持久化失败
- **THEN** 返回 persist_failed；pin 文件不保证恢复原值，不能据此认定文件与数据库均保持原状

### Requirement: machines 不可用窗口与期限顺延

不可用 SHALL 定义为 `machine_status != online` 或 `is_maintenance`。窗口起点 `unavailable_since` SHALL 在该机器不可用且起点为空时置为当前时刻；窗口关闭时 SHALL 在状态已更新的**同一事务内**把整段故障时长批量累加到该机器全部以时长计的期限（SSH 登录清理、磁盘冻结、删除挂载保留），再清空起点。窗口结算 SHALL 只在窗口关闭时发生，因此清理倒计时的读侧 SHALL 同时计入已结算的 `deferral_seconds` 与进行中窗口（自 `unavailable_since` 起算）两段，MUST NOT 只看其中一段。

#### Scenario: 窗口关闭后一次结算

- **WHEN** 一台机器从不可用恢复为 online 且非维护
- **THEN** 该机器上全部 SSH 登录、冻结状态与删除挂载保留记录的 `deferral_seconds` 在同一事务内各累加整段故障时长，`unavailable_since` 清空；事务失败则窗口不关闭

#### Scenario: 窗口未关时倒计时照延

- **WHEN** 机器仍处不可用窗口内，清理倒计时被读取
- **THEN** 除已结算的 `deferral_seconds` 外，还按 `unavailable_since` 折算进行中的窗口，两者叠加而非二选一

### Requirement: machines 采集心跳与启动窗口回填

`last_seen_at` SHALL 记录「Ctrl 听到过这台机器」：成功应用一批 Node 快照帧时以 Ctrl 自身时钟更新（含采集异常批），同一机器 SHALL 有写入节流，写失败只告警且 MUST NOT 影响本批快照落库。Ctrl 启动时 SHALL 以 `last_seen_at` 回填「窗口未开」的机器起点，作为「至少到这时它还是好的」的下界；已有窗口的机器 MUST NOT 被改写，`last_seen_at` 为空 SHALL 跳过，该扫描 SHALL 幂等，且 MUST 先于链路首次拨号执行。

#### Scenario: 停机期间的进窗被兜住

- **WHEN** Ctrl 停机期间机器失联，重启后执行窗口回填扫描
- **THEN** 窗口起点回填为 `last_seen_at`（早于重启时刻）；已有窗口不改写、无心跳记录不凭空开窗，且扫描在链路首次拨号之前完成

### Requirement: machines 出站链路集合对齐

链路 SHALL 由 machines 全表（含 OFFLINE 行）驱动出站拨号，连接成功即判 online、断开即判 offline，MUST NOT 另做二次探活；不在拨号清单内的机器 SHALL 被置为 offline。机器行的增删 SHALL 由下一轮集合对齐自动跟随、MUST NOT 需要重启进程，且对齐 MUST NOT 打断存活链路；重连失败 SHALL 按机器独立退避（单机失败不影响他机），连接成功后恢复常规节奏。

#### Scenario: 机器集合变化保持其他存活链路

- **WHEN** machines 表增删机器行或某台机器连接失败
- **THEN** 下一轮集合对齐跟随增删，存活链路不被打断，失败机器独立退避

### Requirement: machines 动作任务管辖范围

动作类定时任务（容器清理、挂载清理、磁盘检测）SHALL 共用同一「管辖范畴」判据：机器可达且非维护；机器记录缺失 SHALL 并入范畴外且不抛异常，范畴外 SHALL 静默跳过、不写审计与常规日志。

#### Scenario: 范畴外不动作也不留痕

- **WHEN** 动作类定时任务遇到维护中或不可达的机器
- **THEN** 该次动作不发生，且不写审计与常规日志；机器记录缺失同样按范畴外处理，不抛异常

### Requirement: 机器详情保留配置端口

机器详情响应 SHALL 提供 port: int | null，非空取值范围为 1–65535，保留机器实际配置的 Node 端口；配置为空时 SHALL 表达使用全局默认端口，MUST NOT 将默认值硬编码写入机器记录或伪装成逐机配置。接口响应模型 MUST NOT 丢弃服务返回的端口，现有机器读取与资源权限 SHALL 保持生效。

#### Scenario: 自定义端口可读取
- **WHEN** 已登记机器配置 port=6789，用户具备该机器详情读取权限
- **THEN** 实际 API 响应保留 6789，不被模型过滤或默认端口覆盖

#### Scenario: 空配置仍使用平台默认
- **WHEN** 机器记录 port 为空
- **THEN** 响应保留空配置语义，出站解析仍按现行全局默认配置执行
