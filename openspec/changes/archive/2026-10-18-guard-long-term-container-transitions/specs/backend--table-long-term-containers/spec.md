# Spec Delta

## ADDED Requirements

### Requirement: 长期切换由服务端静态守卫裁决

实际在手工设置入口新增或移除长期标记时，服务端 SHALL 复用既有权限、`set_long_term` 状态矩阵、root 用户长期配额、容器实际状态、`disk_total_bytes` 与 `machine.max_disk_size_gb` 作出裁决。客户端页面、按钮状态和请求参数 MUST NOT 作为授权依据；该守卫不新增持久化状态、响应对象、Node 协议或库表变更。

#### Scenario: 不同客户端入口不能绕过

- **WHEN** Home、ManageMachine 或详情页分别发起同一容器的长期切换请求
- **THEN** 服务端都按同一份当前数据和同一套既有权限/状态矩阵裁决，客户端提交的额外字段不改变结果

#### Scenario: 既有权限与状态矩阵保留

- **WHEN** 调用方缺少 `container:operation`、`container:root` 或机器访问权，或容器处于 `failed`、不稳定、主机离线/维护、状态未知
- **THEN** 仍按既有 403/404/409/503 契约拒绝，不因本次收敛而放宽或删除原矩阵

#### Scenario: 守卫不依赖新增结构

- **WHEN** 实现或验收本变更
- **THEN** 只使用现有容器、长期标记、机器与冻结字段；不需要新增列、库表变更、资格对象或 Node 前置字段

### Requirement: 启用长期检查 root 用户配额

实际在手工设置入口从非长期设为长期时，系统 SHALL 按现有 root 用户长期容器计数与配置上限校验；已满时 MUST 拒绝并保留既有 `long_term_limit_reached` 原因及 used/limit 信息。

#### Scenario: 配额已满时拒绝启用

- **WHEN** root 用户的长期容器数量已达到配置上限，该用户的非长期容器申请启用
- **THEN** 服务端返回 409 和 `long_term_limit_reached`，不新增长期标记，不修改冻结字段

#### Scenario: 配额未满时继续检查磁盘

- **WHEN** root 用户配额未满
- **THEN** 服务端继续检查磁盘硬限制，而不是只凭配额通过

### Requirement: 启用长期检查磁盘硬限制

实际在手工设置入口从非长期设为长期时，系统 SHALL 在机器配置了 `max_disk_size_gb` 且已知 `disk_total_bytes` 达到现有硬限制百分比时拒绝。磁盘用量未知、机器未配置上限或未达阈值时 MUST NOT 因此拒绝；软阈值不阻断。

#### Scenario: 已知用量达到硬限制时拒绝

- **WHEN** 机器磁盘上限为 512 GiB、硬限制为 100%，容器 `disk_total_bytes` 为 600 GiB，其余门禁通过
- **THEN** 服务端返回 409 和 `disk_usage_over_limit`，不新增长期标记，不修改冻结锚点/宽限/累计

#### Scenario: 用量未知或未配置上限时不误拒

- **WHEN** `disk_total_bytes` 为空，或机器 `max_disk_size_gb` 未配置/不大于 0
- **THEN** 服务端不因该缺失额外拒绝启用；它只按配额、状态和权限继续判断

#### Scenario: 仅超过软阈值仍可启用

- **WHEN** 已知用量超过软阈值但低于硬限制，其余门禁通过
- **THEN** 启用成功，软提醒仍由既有磁盘展示负责，不写成拒绝原因

### Requirement: 取消长期按实际状态拦截冻结

实际在手工设置入口从长期改为非长期时，系统 SHALL 在实际状态为 `paused`（冻结中）时拒绝；`online`/`offline` 且通过既有状态矩阵时允许。系统 MUST NOT 以 `container_disk_freeze_state` 行的存在作为永久拒绝条件，MUST NOT 删除或重置该行；取消前后 `first_frozen_at`、`grace_until`、`deferral_seconds` 保持不变。该规则只约束取消长期标记，不约束删除容器；删除容器的冻结重置按 `backend--table-container-disk-freeze-state` 的删除要求执行。

#### Scenario: 冻结中取消被拒绝

- **WHEN** 长期容器的实际状态为 `paused`
- **THEN** 取消长期返回 409 和 `container_paused`，长期标记保留，冻结字段与 Q72 累计不变

#### Scenario: 已确认恢复后允许取消

- **WHEN** 旧冻结行仍存在，但实际状态已为 `online` 或 `offline`，且通过既有状态矩阵
- **THEN** 取消长期允许执行，不因冻结行存在而永久阻断，也不删除或重置该行

#### Scenario: 取消长期不等于删除容器

- **WHEN** 用户只取消长期标记，没有删除容器
- **THEN** 冻结行与 Q72 累计保持不变；只有真正删除容器才按删除要求清空冻结状态

#### Scenario: 状态矩阵优先于方向规则

- **WHEN** 容器实际状态为 `failed`、不稳定、主机离线/维护或状态未知
- **THEN** 仍按既有矩阵拒绝，不把方向规则当作绕过状态矩阵的通道

### Requirement: 同目标值请求无额外副作用

当实际写入前重读到的长期标记已等于请求目标，且在通过既有权限与状态矩阵后，系统 SHALL 返回当前状态且不新增或删除长期标记、不写成功审计、不修改冻结锚点/宽限/累计字段；实际切换失败时长期标记 MUST 保持不变。

#### Scenario: 重复启用不产生新标记

- **WHEN** 已是长期的容器再次提交 `is_long_term=true`
- **THEN** 返回当前长期状态，长期记录仍只有一条，不新增成功审计，不修改冻结字段

#### Scenario: 重复取消不产生删除

- **WHEN** 已是非长期的容器再次提交 `is_long_term=false`
- **THEN** 返回当前状态，不执行删除，不新增成功审计，不修改冻结字段

#### Scenario: 切换失败保留原标记

- **WHEN** 实际启用或取消被配额、磁盘或状态规则拒绝
- **THEN** 原长期标记不变，失败审计记录原因，冻结字段不变

### Requirement: 实际写入前重读既有事实

手工设置入口在实际写入前 SHALL 于同一会话/事务重读容器、账号绑定、长期标记、机器磁盘配置与当前状态，再执行判断和写入；写入使用既有长期仓储原语。并发改变目标状态时 MUST 按重读结果重新判断，不得沿用请求开始时的快照；本变更不声称修复跨容器配额并发。

#### Scenario: 重读后发现目标已变化

- **WHEN** 请求开始时长期标记与目标不同，但同一容器在写入前已被另一请求改成目标值
- **THEN** 本次按重读结果走同目标幂等，不重复写入或审计

#### Scenario: 重读后发现状态已冻结

- **WHEN** 请求开始时容器为 `online`，实际写入前已变为 `paused`
- **THEN** 取消长期按重读后的实际状态拒绝，不沿用请求开始时的判断

### Requirement: 错误原因与既有契约稳定

策略拒绝 SHALL 复用既有 `container_paused`、`long_term_limit_reached`、`container_busy`、`container_failed`、`container_host_offline`、`container_host_maintenance`、`container_status_unknown` 原因；磁盘硬超限使用 `disk_usage_over_limit`。策略拒绝默认映射 409，主机不可用沿用 503；权限 403、容器不存在 404、入参 400 不变。失败审计 MUST 记录实际原因且不改变长期标记。

#### Scenario: 策略阻断返回 409

- **WHEN** 启用因配额或磁盘硬限制被拒绝，或取消因实际冻结被拒绝
- **THEN** API 返回 409，`error_reason` 为对应稳定原因，长期标记保持原状

#### Scenario: 主机不可用沿用 503

- **WHEN** 主机离线或维护导致实际切换被拒绝
- **THEN** 返回既有 503 原因，不伪装成磁盘或配额超限

#### Scenario: 失败审计不改变状态

- **WHEN** 实际切换被拒绝
- **THEN** 记录失败审计与原因，长期标记、冻结锚点/宽限/累计字段均不变
