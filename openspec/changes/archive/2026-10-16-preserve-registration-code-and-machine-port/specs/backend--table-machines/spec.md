## ADDED Requirements

### Requirement: 机器详情保留配置端口

机器详情响应 SHALL 提供 port: int | null，非空取值范围为 1–65535，保留机器实际配置的 Node 端口；配置为空时 SHALL 表达使用全局默认端口，MUST NOT 将默认值硬编码写入机器记录或伪装成逐机配置。接口响应模型 MUST NOT 丢弃服务返回的端口，现有机器读取与资源权限 SHALL 保持生效。

#### Scenario: 自定义端口可读取
- **WHEN** 已登记机器配置 port=6789，用户具备该机器详情读取权限
- **THEN** 实际 API 响应保留 6789，不被模型过滤或默认端口覆盖

#### Scenario: 空配置仍使用平台默认
- **WHEN** 机器记录 port 为空
- **THEN** 响应保留空配置语义，出站解析仍按现行全局默认配置执行
