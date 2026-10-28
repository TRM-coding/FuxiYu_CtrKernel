# Spec Delta

> 本 delta 为测试对账用途：完整复制 `openspec/specs/backend--table-user-images/spec.md` 中既有的 Requirement 块，Requirement 名、SHALL 语义、Scenario 名与 WHEN/THEN 原文均保持不变。不新增业务行为、不新增表或字段、不新增权限规则；不得为了迁就现有测试而削弱规格。

## MODIFIED Requirements

### Requirement: user_images 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `UserImage`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: user_images 生产职责与生命周期

user_images SHALL 保存唯一 user_id/image_id 的 CUSTOM 查看授权配对，名单仅在 custom 范围下可管理，private/everyone 不依该名单决定可见性。创建者保有自己的资源归属，名单增删 MUST NOT 转让所有权、授予编辑方法能力或扩大“仅看我的”结果。

#### Scenario: 整组更新名单
- **WHEN** 镜像范围为 custom 且用户 ids 均有效
- **THEN** 落定去重后的查看授权集合；非 custom 范围的名单变更仍被服务拒绝

#### Scenario: 授权别人查看
- **WHEN** 创建者把另一用户加入 CUSTOM 名单
- **THEN** 对方可在满足方法权限时查看或使用该镜像，但镜像不会成为对方创建的资源，原所有权不变
