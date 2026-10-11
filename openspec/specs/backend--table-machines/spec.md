# machines

## Purpose

宿主机身份、信任锚、硬件事实及分配上限。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

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

## Data model appendix

### machines 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 8 |
| `machine_name` | `db.Column(db.String(120), unique=True, nullable=False, index=True)` | 9 |
| `machine_ip` | `db.Column(db.String(120), unique=True, nullable=False, index=True)` | 10 |
| `port` | `db.Column(db.Integer, nullable=True)` | 14 |
| `machine_type` | `db.Column(db.Enum(MachineTypes), nullable=False)` | 15 |
| `machine_status` | `db.Column(db.Enum(MachineStatus, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=MachineStatus.ONLINE)` | 16 |
| `is_maintenance` | `db.Column(db.Boolean, nullable=False, default=False)` | 21 |
| `cpu_core_number` | `db.Column(db.Integer, nullable=True)` | 22 |
| `memory_size_gb` | `db.Column(db.Integer, nullable=True)` | 23 |
| `gpu_number` | `db.Column(db.Integer, nullable=True)` | 24 |
| `gpu_type` | `db.Column(db.String(120), nullable=True)` | 25 |
| `gpu_list` | `db.Column(db.JSON, nullable=True)` | 29 |
| `gpu_allow_list` | `db.Column(db.JSON, nullable=True)` | 30 |
| `max_shared_gb` | `db.Column(db.Integer, nullable=True)` | 31 |
| `disk_size_gb` | `db.Column(db.Integer, nullable=True)` | 32 |
| `machine_description` | `db.Column(db.String(500), nullable=True)` | 33 |
| `max_memory_gb` | `db.Column(db.Integer, nullable=True)` | 34 |
| `max_cpu_core_number` | `db.Column(db.Integer, nullable=True)` | 35 |
| `max_disk_size_gb` | `db.Column(db.Integer, nullable=True)` | 38 |
| `node_uid` | `db.Column(db.String(128), unique=True, nullable=True, index=True)` | 43 |
| `node_cert_fingerprint` | `db.Column(db.String(128), unique=True, nullable=True, index=True)` | 44 |
| `cert_pinned_at` | `db.Column(db.DateTime, nullable=True)` | 45 |
| `collect_error_at` | `db.Column(db.DateTime, nullable=True)` | 49 |
| `unavailable_since` | `db.Column(db.DateTime, nullable=True)` | 52 |
| `last_seen_at` | `db.Column(db.DateTime, nullable=True)` | 57 |

## Source references

- [models/machine.py](../../../models/machine.py)：Machine，第 5 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

