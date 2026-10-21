## MODIFIED Requirements

### Requirement: announcements 生产职责与生命周期

服务 SHALL 使用已校验的私有草稿内容创建 SENDING 公告并保存目标集合；后台顺序投递并回写 SENT/FAILED 及成功、失败计数，启动时收尾中断的发送。公告 SHALL 保留独立正文和当次目标快照，MUST NOT 依赖模板继续存在或在发送时重新套用模板。

#### Scenario: 批量发送受理
- **WHEN** 当前创建者的草稿和目标通过校验
- **THEN** 返回公告 id，后台投递通过计数与状态反馈；source_draft_id、target_snapshot 保留来源与当次解析快照

#### Scenario: 模板已删除
- **WHEN** 公告源自模板填充后的草稿且模板已删除
- **THEN** 仍按公告自身持久化的内容投递或重发，不要求恢复模板引用
