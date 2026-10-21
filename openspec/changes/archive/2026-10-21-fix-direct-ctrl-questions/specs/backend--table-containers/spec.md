# Spec Delta

## ADDED Requirements

### Requirement: containers entrypoint 留痕说明符合构建语义

`models/containers.py` 与 `services/container_module/creation.py` 的 entrypoint 说明 SHALL 表明它与 FROM、业务片段一样属于构建配方，渲染为最终 Dockerfile 最后一行 `ENTRYPOINT`；创建流程落库模板侧三项（FROM、业务片段、启动命令），平台注入不落库。说明 MUST NOT 再称其不参与构建或只是运行期参数。该修正 MUST NOT 改变容器字段、恢复行为或构建行为。

#### Scenario: 容器模型与创建流程说明一致

- **WHEN** 开发者依据 `models/containers.py` 或创建流程理解 entrypoint
- **THEN** 两处都描述为构建配方的一段，创建流程明确模板侧三项落库、平台注入现取
