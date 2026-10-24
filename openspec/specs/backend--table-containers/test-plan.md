# containers 测试覆盖

规格：[spec.md](spec.md)

## 当前场景映射

| Requirement | Scenario | 覆盖状态 | 测试位置与 nodeid/参数 | 验证范围或缺口 |
| --- | --- | --- | --- | --- |
| containers 持久化结构 | 读取有效记录 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮只同步 entrypoint 说明契约，未复核持久化读取断言。 |
| containers 持久化结构 | 不新增观测列 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核磁盘观测列约束。 |
| containers 生产职责与生命周期 | 创建资源校验 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核创建资源上限断言。 |
| containers 生产职责与生命周期 | 共享内存双重上限 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核共享内存双重上限断言。 |
| containers 镜像归属与平台解析 | 运行镜像由平台解析 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核镜像归属断言。 |
| containers 构建版本戳与运行标签 | 落后判据只看版本戳 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核版本戳与落后判据断言。 |
| containers 构建版本戳与运行标签 | 标签推导不出时不编造 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核标签推导断言。 |
| containers 构建版本戳与运行标签 | 秒级版本递增不掩盖内容差异 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核配方内容差异断言。 |
| containers 构建配方留痕与运行基底展示 | 运行基底展示不随模板编辑失真 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核运行基底展示断言。 |
| containers 恢复内容来源选择 | 内容会变时先交回两份 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核恢复内容选择断言。 |
| containers 恢复挂载与数据位置 | 恢复来源与改名不迁移数据 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核恢复挂载路径断言。 |
| 镜像换代保持容器留痕与关联有效 | 缓存换代后读取旧容器 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核换代留痕断言。 |
| 镜像换代保持容器留痕与关联有效 | 恢复采用历史正文与当前注入 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核历史正文与当前注入组合断言。 |
| 名称缺席不构成删除依据 | 创建受理后快照缺席 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核快照缺席保护断言。 |
| 名称缺席不构成删除依据 | 运行中容器快照暂时缺席 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核待核实标记断言。 |
| 名称缺席不构成删除依据 | 旧代名称删除帧 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核旧代删除帧断言。 |
| 不可判定采集不制造消失 | Node 采集错误 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核采集错误处理断言。 |
| 正向观察清除待核实状态 | 容器重新出现在快照 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核待核实清除断言。 |
| 正向观察清除待核实状态 | 重新出现但状态仍未知 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核过渡态保护断言。 |
| 消失线索可追溯 | 两种线索先后到达 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核线索区分断言。 |
| Node 路径修正与业务路径 | resolved 路径修正 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核路径修正断言。 |
| Node 路径修正与业务路径 | 原有 bind 路径转为明确 no_bind | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核 no_bind 清空断言。 |
| Node 路径修正与业务路径 | unresolved 只保留路径不清空 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核 unresolved 保留断言。 |
| Node 路径修正与业务路径 | 旧 Node 不改写已校正路径 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核旧 Node 兼容断言。 |
| Node 路径修正与业务路径 | 旧 Node 首次建立路径 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核旧协议首次建立断言。 |
| Node 路径修正与业务路径 | no_bind 后旧 Node 不得重建路径 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核 no_bind 保护断言。 |
| Node 路径修正与业务路径 | 路径修正不批量改历史 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核历史记录隔离断言。 |
| 磁盘测量接收与路径一致性 | 错误样本不伪造零 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核错误样本拒绝断言。 |
| 磁盘测量接收与路径一致性 | 重复缓存帧不刷新测量时间 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核重复帧时间断言。 |
| 磁盘测量接收与路径一致性 | 已知旧测量不回退 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核旧测量拒绝断言。 |
| 磁盘测量接收与路径一致性 | 明确 no_bind 的 overlay 测量 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核 overlay-only 测量断言。 |
| 磁盘测量接收与路径一致性 | 无效 measured_at 只拒绝测量 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核 measured_at 校验断言。 |
| 路径变化清空旧测量 | 路径改变后旧样本晚到 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核路径变化样本隔离断言。 |
| 路径变化清空旧测量 | 路径变化先清空再回填 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核显式清空断言。 |
| 评估只使用当前可信测量 | 测量过期不动作 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核测量年龄门禁断言。 |
| 评估只使用当前可信测量 | unresolved 路径上的有效测量 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核 unresolved 下有效测量断言。 |
| 评估只使用当前可信测量 | resolved 但测量失败 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核 resolved 失败帧断言。 |
| 评估只使用当前可信测量 | 路径修正不等于删除授权 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核删除/清理授权断言。 |
| 容器详情返回既有宿主 bind 路径 | 有记录时原样返回 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核详情字段断言。 |
| 容器详情返回既有宿主 bind 路径 | 空值或旧响应按未记录处理 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核空值降级断言。 |
| 容器详情返回既有宿主 bind 路径 | 只读查询不写库 | 待复核 | —（本轮未审计） | 主规格既有场景；本轮未复核只读断言。 |
| containers entrypoint 留痕说明符合构建语义 | 容器模型与创建流程说明一致 | 已覆盖 | `../../../test/test_entrypoint_docs.py::test_entrypoint_docs_describe_build_stage_at_all_four_locations`；机械检查 `ENTRYPOINT_DOC_CHECK: PASS`（4 文件，5 个旧短语均不存在，必需构建语义短语存在）；`git grep -n 'utils/Container.py' -- models/containers.py services/container_module/creation.py` 无输出 | 测试断言 `models/containers.py` 与 `services/container_module/creation.py` 不含“不参与构建”，且含“参与构建”“ENTRYPOINT”与“模板侧的三项”；机械检查额外确认两文件不含“只是运行期参数”，创建流程含“平台注入不落库”“当下的系统设置”，覆盖“平台注入现取”。 |
| 容器创建与恢复生成一次性 root 密码 | 创建受理后返回 root 密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_create_restore_credentials_contract | 断言创建/恢复 accepted/credentials/no-store、失败无凭据、requires_choice、内部 root_password 非默认。 |
| 容器创建与恢复生成一次性 root 密码 | 创建失败不返回密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_create_restore_credentials_contract | 断言创建/恢复 accepted/credentials/no-store、失败无凭据、requires_choice、内部 root_password 非默认。 |
| 容器创建与恢复生成一次性 root 密码 | 恢复实际执行时生成新密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_create_restore_credentials_contract | 断言创建/恢复 accepted/credentials/no-store、失败无凭据、requires_choice、内部 root_password 非默认。 |
| 容器创建与恢复生成一次性 root 密码 | 内容二选一不生成密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_create_restore_credentials_contract | 断言创建/恢复 accepted/credentials/no-store、失败无凭据、requires_choice、内部 root_password 非默认。 |
| 容器创建与恢复生成一次性 root 密码 | 内部创建入口也不使用默认密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_create_restore_credentials_contract | 断言创建/恢复 accepted/credentials/no-store、失败无凭据、requires_choice、内部 root_password 非默认。 |
| 容器账号密码重置的权限与目标校验 | ROOT 绑定用户重置协作者 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_permission_contract | 断言方法/资源/机器三层守卫、绑定 login_name、目标/状态拒绝与错误 reason 映射。 |
| 容器账号密码重置的权限与目标校验 | ROOT 绑定固定使用 root 登录名 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_permission_contract | 断言方法/资源/机器三层守卫、绑定 login_name、目标/状态拒绝与错误 reason 映射。 |
| 容器账号密码重置的权限与目标校验 | 资源管理通配可重置 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_permission_contract | 断言方法/资源/机器三层守卫、绑定 login_name、目标/状态拒绝与错误 reason 映射。 |
| 容器账号密码重置的权限与目标校验 | 仅实体通配被资源层拒绝 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_permission_contract | 断言方法/资源/机器三层守卫、绑定 login_name、目标/状态拒绝与错误 reason 映射。 |
| 容器账号密码重置的权限与目标校验 | ADMIN 或 COLLABORATOR 不能重置 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_permission_contract | 断言方法/资源/机器三层守卫、绑定 login_name、目标/状态拒绝与错误 reason 映射。 |
| 容器账号密码重置的权限与目标校验 | 目标用户未绑定被拒绝 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_permission_contract | 断言方法/资源/机器三层守卫、绑定 login_name、目标/状态拒绝与错误 reason 映射。 |
| 容器账号密码重置的权限与目标校验 | 绑定登录名非法被拒绝 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_permission_contract | 断言方法/资源/机器三层守卫、绑定 login_name、目标/状态拒绝与错误 reason 映射。 |
| 容器账号密码重置的权限与目标校验 | 机器离线时不生成密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_permission_contract | 断言方法/资源/机器三层守卫、绑定 login_name、目标/状态拒绝与错误 reason 映射。 |
| 容器账号密码重置的权限与目标校验 | 容器非 online 时不生成密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_permission_contract | 断言方法/资源/机器三层守卫、绑定 login_name、目标/状态拒绝与错误 reason 映射。 |
| 容器账号密码重置的权限与目标校验 | 额外字段不能指定登录名 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_permission_contract | 断言方法/资源/机器三层守卫、绑定 login_name、目标/状态拒绝与错误 reason 映射。 |
| 容器账号密码重置的权限与目标校验 | 错误按现有 reason 映射且不拼原始错误体 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_permission_contract | 断言方法/资源/机器三层守卫、绑定 login_name、目标/状态拒绝与错误 reason 映射。 |
| 容器密码重置的后台执行与一次性响应 | 受理后立即返回并后台请求 Node | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_background_contract | 断言立即受理、客户端断开、后台 Node 调用、最小 guard、失败 oplog、no-store。 |
| 容器密码重置的后台执行与一次性响应 | 客户端断开不取消后台任务 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_background_contract | 断言立即受理、客户端断开、后台 Node 调用、最小 guard、失败 oplog、no-store。 |
| 容器密码重置的后台执行与一次性响应 | Node 失败只写失败 oplog | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_background_contract | 断言立即受理、客户端断开、后台 Node 调用、最小 guard、失败 oplog、no-store。 |
| 容器密码重置的后台执行与一次性响应 | 后台复核失败只写 oplog | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_background_contract | 断言立即受理、客户端断开、后台 Node 调用、最小 guard、失败 oplog、no-store。 |
| 容器密码重置的后台执行与一次性响应 | 密码响应不可缓存 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_reset_background_contract | 断言立即受理、客户端断开、后台 Node 调用、最小 guard、失败 oplog、no-store。 |
| 新增协作者的一次性账号密码 | 新增 ADMIN 协作者返回密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_add_collaborator_password_contract | 断言 ADMIN/COLLABORATOR config.password、后台绑定、既有 ADD_COLLABORATOR、失败/guard 不伪成功。 |
| 新增协作者的一次性账号密码 | 新增 COLLABORATOR 协作者返回密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_add_collaborator_password_contract | 断言 ADMIN/COLLABORATOR config.password、后台绑定、既有 ADD_COLLABORATOR、失败/guard 不伪成功。 |
| 新增协作者的一次性账号密码 | Node 或绑定失败不写成功 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_add_collaborator_password_contract | 断言 ADMIN/COLLABORATOR config.password、后台绑定、既有 ADD_COLLABORATOR、失败/guard 不伪成功。 |
| 新增协作者的一次性账号密码 | 前置校验失败不生成密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_add_collaborator_password_contract | 断言 ADMIN/COLLABORATOR config.password、后台绑定、既有 ADD_COLLABORATOR、失败/guard 不伪成功。 |
| 新增协作者的一次性账号密码 | 后台最小 guard 复核失败只写失败日志 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_add_collaborator_password_contract | 断言 ADMIN/COLLABORATOR config.password、后台绑定、既有 ADD_COLLABORATOR、失败/guard 不伪成功。 |
| 恢复协作者账号的瞬时密码兼容 | 恢复协作者账号使用瞬时随机密码 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_restore_accounts_password_contract | 断言 restore_accounts 瞬时 password、不写 snapshot、Node 失败不回退弱密码。 |
| 恢复协作者账号的瞬时密码兼容 | Node 拒绝瞬时密码时不回退弱默认值 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_restore_accounts_password_contract | 断言 restore_accounts 瞬时 password、不写 snapshot、Node 失败不回退弱密码。 |
| 容器密码不持久化且不可回查 | 一次性密码只在响应中出现 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_password_persistence_contract | 断言 DB/日志/审计无密码、无 GET 回查、错误脱敏。 |
| 容器密码不持久化且不可回查 | 失败响应与异常脱敏 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_password_persistence_contract | 断言 DB/日志/审计无密码、无 GET 回查、错误脱敏。 |
| 容器密码不持久化且不可回查 | 无密码回查入口 | 已覆盖 | ../../../test/container/test_password_contracts.py::test_password_persistence_contract | 断言 DB/日志/审计无密码、无 GET 回查、错误脱敏。 |

## 历史验证

- 时间：2026-10-21 03:03:42 +08:00（父任务最终 WSL 套件原始输出落盘时间）
- 版本：`f68d54bacc15ecd401c1d83d8030fe140696b9e1`；本次仅同步文档，未改源代码/测试，未重跑业务套件。
- 主 spec SHA256：`a703a52015c6faac21da5cecf193be55931d1c753af4dfdff7d6be12ee0801b4`
- 命令与环境：
  - WSL 完整默认安全套件：`PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:///:memory: DISABLE_BACKGROUND_TASKS=1 /home/chest/miniconda3/envs/fuxi/bin/python -m pytest test -q --no-header`
  - Windows 定向：`E:\Miniconda3\envs\lianjue\python.exe -m pytest test/operation_log test/settings test/test_entrypoint_docs.py test/container/test_container_entrypoint.py test/announcement/test_api.py -q --no-header`
- 结果：WSL 完整套件 1358 passed、0 failed、0 skipped、6 deselected、1 warning（既有 SAWarning），170.53s；Windows 定向 110 passed。原始输出：`.git/direct-q-final-suite.log`（本地记录，未提交）。
- 限制：6 项按 `integration/legacy` 策略排除，未运行真实 Docker/GPU/SMTP 或生产数据库；完整套件包含 Node 跨仓回放和真实 du 探针。entrypoint 说明场景为文档约束，使用现有文档扫描测试加静态机械检查验证；`test/container/test_container_entrypoint.py` 的构建/恢复回归在同次运行中通过，但不是该文档场景的专用断言。上表既有场景未在本轮重新审计。

## 附加合同证据（非新增 Scenario）

- `CollaboratorRequest.role` 公开大写枚举（ADMIN/COLLABORATOR），Node wire 小写；非法/ROOT 新增请求 400 且不下发 Node：`../../../test/container/test_container_api_collaborators.py::test_add_collaborator_api_rejects_root_and_unknown_role_before_node`、`::test_collaborator_openapi_role_enums_are_public_uppercase`。
- 真实 Node Pydantic/HTTP wire：`../../../test/container/test_account_wire_contracts.py`，13 passed；大写 role 被 Node 422 拒绝、helper 小写 wire 被接受且 no-store。

## 最近验证

- 时间：2026-10-24 17:30 +08:00
- 版本：4e6830dfa35e584d5232360d5c06b0ea0ed18f50（实现/测试提交）
- 主 spec SHA256：E960DBCD7B896660DB42EA5BF009E9CB341C399F0A873CFC95E3871AED352CE4
- 命令与环境：
  - WSL 离线 venv 根目录完整套件：`/home/chest/.cache/fuxi-password-tests-offline/bin/python -m pytest -q --no-header`
  - 真实 Node wire：`/home/chest/.cache/fuxi-password-tests-offline/bin/python -m pytest test/container/test_account_wire_contracts.py -q --no-header`
- 结果：完整套件 1431 passed、0 failed、6 deselected、24 subtests passed（224.04s）；Node wire 13 passed（19.72s）。
- 限制：6 项 integration/legacy 按策略排除；未运行真实生产 Docker/MySQL；上表旧场景沿用历史台账，未在本轮重新审计；新增场景由本轮契约测试覆盖。