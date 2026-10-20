# Spec Delta

## ADDED Requirements

### Requirement: announcement_templates 列表分页参数有界且可分页

`GET /api/announcements/templates` SHALL 接受 `limit` 1..200、`offset >= 0`，默认值保持 100/0；Web 正常使用的 100 或 200 SHALL 继续通过。越界或非整数的 `limit`/`offset` MUST 以 400 和 `error_reason=invalid_payload` 拒绝。`total` SHALL 保持过滤后的完整数量；查询 SHALL 在排序后应用 `offset` 和 `limit`，因此超过 200 条的模板仍可通过 `offset` 到达。该修正 MUST NOT 修改数据库结构或模板字段。

#### Scenario: 界内分页参数

- **WHEN** 请求 `limit=100`、`limit=200` 或 `offset=0`
- **THEN** 正常返回按既有顺序分页的模板及完整 `total`

#### Scenario: 越界或非整数参数

- **WHEN** 请求 `limit=0`、`limit=201`、`offset=-1` 或非整数 `limit`
- **THEN** 返回 400，`error_reason=invalid_payload`

#### Scenario: 205 条模板分页

- **WHEN** 存在 205 条模板，请求 `limit=200&offset=0` 后再请求 `limit=200&offset=200`
- **THEN** 第一次返回 200 条且 `total=205`，第二次返回剩余 5 条且 `total=205`
