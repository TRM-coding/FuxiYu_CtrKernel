# backend--table-system-settings Test Plan

Spec: [spec.md](spec.md)

## Current Mapping

### Requirement: system_settings 持久化结构

#### Scenario: 读取有效记录

- Test/check:
  - [X] test/image/test_image_platform_injection_setting.py::test_system_settings_matrix_is_seeded
  - [X] test/image/test_image_platform_injection_setting.py::test_platform_injection_setting_can_be_updated
  - [X] test/image/test_image_platform_injection_setting.py::test_system_settings_api_update_roundtrip
- Assertion scope: seed 后可按 key 读取 value 等序列化设置；更新后读取方取得新字符串值；API 批量更新后 getter 返回新值。
- Coverage note: `created_at`/`updated_at` 由模型默认值与 onupdate 承载，`[X]` 行未逐字段核验时间戳。

### Requirement: system_settings 生产职责与生命周期

#### Scenario: 修改已知设置

- Test/check:
  - [X] test/image/test_image_platform_injection_setting.py::test_system_settings_api_update_roundtrip
  - [X] test/image/test_image_platform_injection_setting.py::test_platform_injection_setting_can_be_updated
  - [X] test/image/test_image_platform_injection_setting.py::test_system_settings_seed_removes_deprecated_parallel_keys
  - [X] test/image/test_image_platform_injection_setting.py::test_settings_batch_target_is_order_independent
- Assertion scope: 具备 `settings:manage` 的测试身份更新已知键后，API/getter 读取新值；审计记录 before/after 与 `setting_keys`；重复 seed 可执行并删除废弃键；批量更新 target_id 与键顺序无关。

### Requirement: system_settings 设置输入不得静默改变语义

#### Scenario: 小数设置

- Test/check:
  - [X] test/settings/test_settings_validation.py::test_integer_setting_rejects_non_integer_without_writing
  - [X] test/settings/test_settings_validation.py::test_single_setting_entrypoint_also_rejects_fractional_integer
  - [X] test/settings/test_settings_validation.py::test_settings_api_rejects_fractional_integer
- Assertion scope: `1.5`、`"1.5"`、`True`、`"abc"`、空串均被拒绝，原值不变；单键入口同样拒绝；API 返回 422 `invalid_setting`，message 指出设置键，不把值截断成 1。

#### Scenario: 非法提醒节点

- Test/check:
  - [X] test/settings/test_settings_validation.py::test_reminder_hours_rejects_malformed_input_without_writing
  - [X] test/settings/test_settings_validation.py::test_settings_api_rejects_malformed_reminder_hours
- Assertion scope: 空串、空白、空项、非整数、0、负数、`12.5` 均使整次写入失败，原值不变；审计保留 `requested`；API 返回 422 `invalid_setting`，message 含设置键与非法项。

#### Scenario: 合法输入与范围校验保留

- Test/check:
  - [X] test/settings/test_settings_validation.py::test_integer_setting_accepts_integral_number
  - [X] test/settings/test_settings_validation.py::test_reminder_hours_accepts_positive_values_and_stays_parser_compatible
  - [X] test/repository/test_anvil_identity_settings.py::test_integer_setting_rejects_values_outside_declared_range
- Assertion scope: `12.0` 保存为 `"12"`；`"72, 24,12"` 原样保存且可被提醒解析器解析为 `[72,24,12]`；`[ ]` 行对声明了 min/max 的整数键提交越界值，断言 `ValueError`、原值不变且不静默截断。
- Coverage note: 已列 `[X]` locator 覆盖合法值与格式校验；既有 `min_value`/`max_value` 越界拒绝未见直接断言，由 `[ ]` 行覆盖。
