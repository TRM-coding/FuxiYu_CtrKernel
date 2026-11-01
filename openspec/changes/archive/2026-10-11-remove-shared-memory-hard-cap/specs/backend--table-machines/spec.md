# Spec Delta

## ADDED Requirements

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