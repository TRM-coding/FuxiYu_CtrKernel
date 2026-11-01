# Spec Delta

## ADDED Requirements

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
