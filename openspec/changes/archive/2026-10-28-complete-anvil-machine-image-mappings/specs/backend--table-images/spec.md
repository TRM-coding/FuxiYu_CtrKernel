# Spec Delta

## MODIFIED Requirements

### Requirement: images 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `Image`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: images 生产职责与生命周期

系统 SHALL 以 disabled 表示模板停用；普通列表 SHALL 返回创建者自己的、EVERYONE 及 CUSTOM 名单授权的非停用模板，真实资源通配者的默认列表覆盖全部非停用模板。完整详情与编辑 SHALL 分别通过方法及资源权限校验；创建容器 SHALL 只使用 READY 模板并保存稳定 image_id。更新接口 MUST NOT 转让创建者归属。

#### Scenario: 模板停用
- **WHEN** 用户通过删除门户停用模板
- **THEN** 保留历史模板行及来源，普通列表和新建选择过滤 disabled

### Requirement: images 模板名称唯一性

模板名称的唯一性 SHALL 由应用层保证，且只约束「未停用」的模板之间：`name` 列 MUST NOT 依赖数据库唯一约束；创建与改名 SHALL 在写入前查重，命中未停用同名模板 SHALL 拒绝。

#### Scenario: 同名判定只看未停用

- **WHEN** 创建一个与某个已停用模板同名的模板
- **THEN** 允许创建；与未停用模板同名则拒绝

### Requirement: images 模板启停与构建记录失效

模板停用 SHALL 可逆，重新启用 SHALL 更新同一行的 status，归属标识 SHALL 在整个生命周期内保持不变。停用只阻止新建，管理与恢复仍能按主键读取历史模板。模板配方变化 SHALL 经统一的新鲜度判断使后续派发换代，不通过删掉所有机器缓存记录形成另一条换代路径；Node 仍按实际标签检查本机制品。

#### Scenario: 停用后可重新启用
- **WHEN** 管理员对已停用模板执行启用
- **THEN** 同一行回到可用状态、归属标识不变；旧容器与构建记录保持可读

#### Scenario: 模板更新促使机器重建
- **WHEN** 模板构建配方更新
- **THEN** 后续派发选择新版本并更新原配对缓存，Node 查不到新标签时构建；已有容器及旧版本制品不被删除

### Requirement: images 内置模板幂等收敛

内置模板 SHALL 由幂等 seed 写入：同名已存在 SHALL 跳过、MUST NOT 覆盖人工修改；内置模板改过名时 SHALL 按旧名集合找回那条系统行（限定 `created_by_user_id` 为空）就地改名并同步 FROM，MUST NOT 插入新行，且 MUST NOT 覆盖管理员已设置的停用状态；名称查重在此处 SHALL 使用不过滤停用的名称原语，以免停用行被查漏而插入第二个同名模板。

#### Scenario: 内置模板改名收敛

- **WHEN** 内置模板在代码中的名称变化后再次启动 seed
- **THEN** 按旧名找回那条系统行就地改名并同步 FROM，保留原归属标识与原停用状态，不新增行；重复执行结果不变

### Requirement: 平台注入改变构建缓存版本

平台注入 SHALL 是最终构建配方的一部分，其变化 SHALL 影响创建和恢复真正下发的构建缓存版本，不能只改变 Dockerfile 文本而复用旧标签。平台注入不作为镜像资源身份，也不直接改变镜像所有权、用户授权或运行中的旧容器。

#### Scenario: 注入变化后派发
- **WHEN** 基础镜像与业务片段不变，仅平台注入内容变化
- **THEN** 后续构建下发变化后的最终 Dockerfile 与新标签，相同新内容派发后可稳定命中

### Requirement: 镜像资源通配与方法权限分别生效

具备 bypass_resource 或直接镜像资源管理通配的用户 SHALL 在默认列表、详情资源门、编辑所有者门和创建镜像可用性中获得全部镜像资源范围；相应方法权限及 READY 等业务状态门 SHALL 独立校验。只有方法实体通配 MUST NOT 扩大资源范围。

#### Scenario: 资源通配者操作他人镜像
- **WHEN** 资源通配者拥有相应方法权限并操作他人的镜像
- **THEN** 能列出、读取详情、编辑并以 READY 镜像创建容器，不因缺少所有者绑定被拒绝

#### Scenario: 仅有方法通配或缺少方法能力
- **WHEN** 用户只有方法通配而无资源通配，或只有资源通配却缺少目标方法权限
- **THEN** 前者仍受资源可见范围约束，后者不能凭资源范围绕过方法鉴权

#### Scenario: 停用模板仍不能新建
- **WHEN** 资源通配者尝试以停用或草稿模板新建容器
- **THEN** 仍被业务状态校验拒绝

### Requirement: 仅看我的严格按创建者过滤

mine_only=true SHALL 只返回 created_by_user_id 等于当前用户的非停用模板，不被通配权限、全员可见或授权名单扩大。默认列表 SHALL 继续包含创建者自己的、全员可见及 CUSTOM 名单授权的镜像；资源通配只扩展默认列表。

#### Scenario: 通配者勾选仅看我的
- **WHEN** 资源通配者请求 mine_only=true
- **THEN** 仅返回自己创建的模板，不混入通过通配访问的他人模板

#### Scenario: 创建者不在可见名单
- **WHEN** 创建者不在某个自己创建的 CUSTOM 模板的 user_images 名单中
- **THEN** 该模板仍属于其“仅看我的”结果，授权名单不能改变所有权

### Requirement: images entrypoint 说明符合构建语义

`models/image.py` 与 `schemas/image.py` 的 entrypoint 说明 SHALL 表明它是镜像构建配方的一段：由构建器渲染为最终 Dockerfile 最后一行 `ENTRYPOINT`，空值默认由 Ctrl 的 `PLATFORM_DEFAULT_ENTRYPOINT` 持有，并参与配方指纹与落后判定。说明 MUST NOT 再称其不参与构建、只是运行期参数或不进 Dockerfile。`schemas/image.py` MUST NOT 再引用不存在的 `utils/Container.py` 说明，SHALL 指向实际渲染入口。该修正 MUST NOT 改变字段、接口或构建行为。

#### Scenario: 模型与 schema 说明一致

- **WHEN** 开发者依据 `models/image.py` 或 `schemas/image.py` 理解 entrypoint
- **THEN** 两处都描述为进入最终 Dockerfile 的构建段，且 schema 不再引用 `utils/Container.py`
