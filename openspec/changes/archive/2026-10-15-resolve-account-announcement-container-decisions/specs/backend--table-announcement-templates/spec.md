## MODIFIED Requirements

### Requirement: announcement_templates 生产职责与生命周期

模板 SHALL 按 category 分类且 name 唯一，SYSTEM 模板删除 SHALL 继续被拒绝。选模板 SHALL 仅提供 subject_template 和 body_template 初始内容，不建立草稿或公告对模板的持久依赖；删除自定义模板 SHALL 解除历史引用并保留已有内容快照。

#### Scenario: 读取模板
- **WHEN** 编辑器选取模板
- **THEN** 返回 subject_template 和 body_template 作为编辑初值；source_announcement_id 仅作模板来源追溯

#### Scenario: 删除被历史内容引用的自定义模板
- **WHEN** 已有草稿或公告仍带被删除模板的历史引用
- **THEN** 解除引用并成功删除模板，保留草稿与公告的主题、正文、目标和投递记录
