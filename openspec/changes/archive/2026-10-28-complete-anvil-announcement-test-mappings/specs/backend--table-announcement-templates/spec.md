# Spec Delta

## MODIFIED Requirements

### Requirement: announcement_templates 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `AnnouncementTemplate`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: announcement_templates 生产职责与生命周期

模板 SHALL 按 category 分类且 name 唯一，SYSTEM 模板删除 SHALL 继续被拒绝。选模板 SHALL 仅提供 subject_template 和 body_template 初始内容，不建立草稿或公告对模板的持久依赖；删除自定义模板 SHALL 解除历史引用并保留已有内容快照。

#### Scenario: 读取模板
- **WHEN** 编辑器选取模板
- **THEN** 返回 subject_template 和 body_template 作为编辑初值；source_announcement_id 仅作模板来源追溯

#### Scenario: 删除被历史内容引用的自定义模板
- **WHEN** 已有草稿或公告仍带被删除模板的历史引用
- **THEN** 解除引用并成功删除模板，保留草稿与公告的主题、正文、目标和投递记录

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
