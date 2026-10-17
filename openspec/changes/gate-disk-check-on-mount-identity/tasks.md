# Tasks

## 1. 数据模型与接收

- [ ] 1.1 在 `models/containers.py` 增加 `disk_measurement_status`、`disk_measured_at`、`disk_received_at`、`disk_observation` 可空 JSON；不新增 `disk_identity_status/disk_identity_checked_at/disk_identity` 或 dev/inode/PID 列。新增迁移并扩展 `__init__` 幂等补列。验证：旧结构加列可重复执行、旧行默认 unverified、`disk_checked_at` 不被回填为测量时间、模型/迁移一致。
- [ ] 1.2 更新 `repositories/containers_repo.py` 的 allowed/nullable-clear 规则，允许状态/观测显式置空和错误样本落库，禁止通用 None 过滤丢掉 `disk_measurement_status`/`disk_received_at`；bytes/measured_at 仅在有效测量时更新。验证：正常→error/null 状态落库、历史数字保留、缺失不写 0、重复帧不刷新 measured_at。
- [ ] 1.3 实现 Node 路径修正接收：仅在当前认证机器/活跃容器/有效排序下，`resolved` 持久化校正路径；成功 Docker 明确 `no_bind` 同步清空 `containers.bind_mount_path`（返回 null + measurement_mount_path=null，overlay-only），unresolved/not_running/字段缺失/不可读只保留已有/最后确认路径，MUST NOT 清空或当 no_bind；不猜目录、不写 proc 路径、不按 inode 批量改历史快照/清理记录。验证：resolved 修正；原 bind 路径→明确 no_bind 清空且 overlay 有效；unresolved 不清空且同路径测量可有效；未知不当 no_bind；历史记录不被批量改写。

## 2. 测量有效性与写入口

- [ ] 2.1 实现统一测量有效性谓词：协议、`measurement_status=ok`、组成完整、`measured_at` 真实年龄/未来偏差、`measurement_mount_path` 与当前 `bind_mount_path` 一致、连接/epoch/seq 排序；明确 no_bind 时两者都为 null，按 overlay 组成判断；不检查 `mount_path_status` 或 dev/inode。验证：resolved/unresolved/not_running/no_bind 下的有效与无效组合；原 bind 路径→no_bind 清空后 overlay 有效且旧 bind bytes 不进入；unresolved/字段缺失不清空；旧 Node 缺 measured_at 标 unverified；旧路径样本被拒。
- [ ] 2.2 统一 WSS、手动 HTTP 刷新及其他写入口：路径修正/明确 no_bind 清空先落库，再要求 bind 测量路径匹配或 overlay-only 两边为 null；旧连接/旧 HTTP/同 epoch 倒序/同 seq 内容不同不得覆盖；手动刷新不得写零或用接收时间冒充 measured_at。验证：连接切换、旧刷新晚到不会恢复清空前的 bind 路径、错误样本、重复心跳和空值测试；路径与样本不交叉错配。
- [ ] 2.3 更新查询/详情返回业务路径、configured_mount_path、mount_path_status、mount_path_observed_at、测量状态、measured_at、received_at 和最后正常值；历史值明确标注，unresolved 与 measurement_error 分开。验证：序列化/日志测试覆盖 unresolved 但有效测量、error 历史值、路径修正；不把诊断失败显示成测量错误。

## 3. 调度、恢复与兼容

- [ ] 3.1 在 `schedulers/container_disk_check_task.py` 和动作前使用同一有效测量谓词；无效/过期/路径错配样本不 pause、不 reset、不 upsert 锚点、不发超限邮件、不升级删除、不清理挂载；no_bind 仅 overlay-only 时有效。验证：各无效原因与有效高/低用量、Q72 恢复、冻结锚点/宽限/补偿不变、路径 unresolved 不单独阻断。
- [ ] 3.2 保留 Q72：采集中断/路径诊断中断不新增顺延、不重开周期、不引入 review/invalid；恢复可信高用量按原累计升级，恢复低用量正常 reset。验证：冻结→无效超过阈值→恢复高/低用量、Ctrl 重启、机器不可用补偿和人工宽限用例。
- [ ] 3.3 处理旧 Node/HTTP/连接兼容：缺真实 measured_at 或协议标 unverified 并说明“测量时间/协议缺失”，不得说成目录身份缺失；新链路收到首个完整观测前旧数字只作历史；路径修正不授予删除/清理权限。验证：旧协议、旧 HTTP、退役连接、无 bind、路径 unresolved 混合版本。

## 4. 联合验收与部署

- [ ] 4.1 与 Node 路径/测量契约回放 resolved/unresolved/not_running/no_bind、Source 改变、路径修正、旧路径样本、手动刷新、乱序和旧 Node；确认 Ctrl 从不比较 dev/inode/PID，也不以 mount_path_status 作为业务门禁。验证：模拟 Node/WSS 与隔离 SQLite，不触达真实 Docker/生产库。
- [ ] 4.2 演练迁移与部署顺序：先 Ctrl 字段/接收，再逐机 Node 路径/测量，最后验证自动处置；旧 Node 覆盖率和 unverified 原因可见，回滚保留字段。验证：迁移重复执行、旧样本不误动作、路径修正只影响当前活跃容器。
- [ ] 4.3 运行 `openspec validate gate-disk-check-on-mount-identity` 与 `--strict`，并核对与 `guard-long-term-container-transitions`、`unify-disk-freeze-workflow` 的共享路径/测量契约；strict warning 记录为非致命，真实错误修复。验证：普通校验无 ERROR，文档不含旧身份门禁残留。

## Workflow follow-up

- 评审后按仓库流程 archive；归档时把本 delta 的测量/路径字段合并进正式 `backend--table-containers` 主规格，当前只改 change 目录。
- Node 只负责内部定位并回填业务路径；路径修正不是删除/清理授权，不新增 inode 清理门禁，也不宣称 Q70 跨进程原子。
