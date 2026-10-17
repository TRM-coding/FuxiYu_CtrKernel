# Design

## Context

见 proposal.md。当前三业务仓库为独立规范入口，Global QUESTIONS 仅作问题证据。

## Goals / Non-Goals

目标：完成明确授权的限额及交互修复。保持其它业务功能、权限和恢复流程。

## Decisions

机器修改以本次携带的非 null 值为准、未携带或显式传 null 沿用当前记录，按实际落库后的状态校验 max_shared_gb <= max_memory_gb；去掉固定 8GB 硬码，任一侧为 NULL（未知）时跳过比较。创建容器的现有 repositories/containers_repo.py 校验保持（共享同时受机器共享限额与本次申请内存约束），未发现需要修补的真实缺口。不能把 Node 的 shm_size 限定为 8GB。

## Risks / Trade-offs

- 未知 NULL 不伪造数值上限：当前记录该字段为 NULL 时跳过组合比较，保留旧记录的空值语义；代价是这类记录暂时不受该不变量约束。
- 显式 null 沿用持久值而非「本次不约束」：`max_shared_gb`/`max_memory_gb` 的 null 不写入（与仓库跳过 None 一致），因此按当前记录参与比较，避免用 null 绕过组合约束；代价是 null 与「未携带」在语义上等价。
- 只降内存不自动改动共享上限：组合不合法就明确拒绝（`update_failed`），由用户自行调整共享上限；代价是多一次往返，但绝不静默改写用户的值。
- 组合约束以实际落库后的状态为准并在写库前校验：失败时同请求其它字段一概不落；代价是校验需同时读取当前记录。
