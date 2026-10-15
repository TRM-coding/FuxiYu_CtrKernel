## MODIFIED Requirements

### Requirement: user_images 生产职责与生命周期

user_images SHALL 保存唯一 user_id/image_id 的 CUSTOM 查看授权配对，名单仅在 custom 范围下可管理，private/everyone 不依该名单决定可见性。创建者保有自己的资源归属，名单增删 MUST NOT 转让所有权、授予编辑方法能力或扩大“仅看我的”结果。

#### Scenario: 整组更新名单
- **WHEN** 镜像范围为 custom 且用户 ids 均有效
- **THEN** 落定去重后的查看授权集合；非 custom 范围的名单变更仍被服务拒绝

#### Scenario: 授权别人查看
- **WHEN** 创建者把另一用户加入 CUSTOM 名单
- **THEN** 对方可在满足方法权限时查看或使用该镜像，但镜像不会成为对方创建的资源，原所有权不变
