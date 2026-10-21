# Tasks

## 1. 实施与行为回归

- [x] 1.1 移除固定 8GB 检查及文案，核对机器配置更新仍有合法整数/非负/共享不超过内存的约束。
- [x] 1.2 增加服务及实际 API 回归：内存32GB且共享16GB可保存；共享超过内存/负数/非整数明确拒绝；既有创建约束仍有效。
- [x] 1.3 明确两份业务 SPEC 的机器共享限额及容器双重约束，修正过时8GB表述；结构严格校验（主代理 Ctrl strict 27/0 通过）。
- [x] 1.4 主审补修：只改 max_memory_gb 也必须满足组合后的 shared<=mem；不静默改用户的值、失败不落其它字段；NULL 内存上限保持空值语义。
- [x] 1.5 主审补修：服务层拒绝非整小数（3.5）且不截断取整，整数字符串兼容；补齐只降 mem 失败/成功、mem=shared、NULL 内存上限与 API 分层的回归。
- [x] 1.6 二轮补修：显式 null 对共享/内存沿用当前记录（与仓库跳过 None 一致），组合约束以实际落库后状态为准；两种 null 绕过均补服务层与真实 API 回归；NULL 记录的 unknown 语义保留。
- [x] 1.7 收尾：machines 共享限额 Requirement 正文缩短至 <=500 chars，细节与 400/422/invalid_config 分层移入 Scenario，主 SPEC 与 delta 逐字同步。

## 2. 主代理验收

- [x] 2.1 主代理运行定向测试与必要 Ctrl 默认套件，检查前后端联动并接受修复（Ctrl strict 27/0、资源定向 107 passed；Web Windows/Linux 各 28 文件 156 测试全过，覆盖四项资源需求；Ctrl 全套 1048 passed / 3 failed 为基线旧测试引用缺失 docs，见 Global Q31，不称全绿）。
