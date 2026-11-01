# Spec Delta

## ADDED Requirements

### Requirement: images entrypoint 说明符合构建语义

`models/image.py` 与 `schemas/image.py` 的 entrypoint 说明 SHALL 表明它是镜像构建配方的一段：由构建器渲染为最终 Dockerfile 最后一行 `ENTRYPOINT`，空值默认由 Ctrl 的 `PLATFORM_DEFAULT_ENTRYPOINT` 持有，并参与配方指纹与落后判定。说明 MUST NOT 再称其不参与构建、只是运行期参数或不进 Dockerfile。`schemas/image.py` MUST NOT 再引用不存在的 `utils/Container.py` 说明，SHALL 指向实际渲染入口。该修正 MUST NOT 改变字段、接口或构建行为。

#### Scenario: 模型与 schema 说明一致

- **WHEN** 开发者依据 `models/image.py` 或 `schemas/image.py` 理解 entrypoint
- **THEN** 两处都描述为进入最终 Dockerfile 的构建段，且 schema 不再引用 `utils/Container.py`
