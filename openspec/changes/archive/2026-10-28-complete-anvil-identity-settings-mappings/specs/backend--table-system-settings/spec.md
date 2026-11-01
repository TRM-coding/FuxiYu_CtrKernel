# Spec Delta

## MODIFIED Requirements

### Requirement: system_settings 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `SystemSetting`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: system_settings 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：key 唯一，value 为 Text；服务负责类型转换、允许键及约束；seed 补齐缺失默认，更新记录审计并影响读取方。

#### Scenario: 修改已知设置

- **WHEN** 有 settings:manage 权限且键和值通过服务校验
- **THEN** 保存 value，并在后续读取中通过该键取得新值

### Requirement: system_settings 设置输入不得静默改变语义

整数设置 MUST 拒绝小数、bool 和非整数文本，MUST NOT 以 `int()` 静默截断；既有 `min_value` / `max_value` 范围校验 SHALL 保留。清理提醒节点 MUST 是非空、逗号分隔的正整数列表；空项、非整数、0 或负数 MUST 使整次写入失败。非法输入 MUST NOT 写入设置，SHALL 返回可识别错误（API 使用 422 `invalid_setting`），失败审计 SHALL 保留请求值。合法整数（含整数值数字）及合法提醒节点 SHALL 继续可保存，读取口径不变。

#### Scenario: 小数设置

- **WHEN** 保存 `1.5` 作为整数设置
- **THEN** 保存失败并指出设置键；不转换为 `1`，原值保持不变

#### Scenario: 非法提醒节点

- **WHEN** 提醒节点包含空项、非数字、0 或负数
- **THEN** 整次写入失败并指出设置键/非法项；不得静默丢弃非法项后保存剩余值

#### Scenario: 合法输入与范围校验保留

- **WHEN** 保存合法整数或逗号分隔的正整数提醒节点
- **THEN** 按原值保存并可在后续读取；超出既有 min/max 的整数仍按原范围规则拒绝
