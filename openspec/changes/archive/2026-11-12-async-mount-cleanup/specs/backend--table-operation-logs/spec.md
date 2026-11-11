# Spec Delta

## ADDED Requirements

### Requirement: 挂载清理的异步结果日志

挂载清理（手动、定时与磁盘升级）在受理/提交时 MUST NOT 写结果日志。仅当 Node 任务明确 `succeeded` 且 Ctrl 的 `cleaned_at`/`mount_cleaned` 事务提交成功后，Ctrl SHALL 写恰好一条成功结果日志；Node `failed`、启动拒绝、轮询超时、任务丢失、坏响应等可观测失败或未知 SHALL 写失败结果日志，`success=false` 且 `error_reason` 稳定脱敏；自动/升级日志 SHALL 保留各自 trigger 与 escalation。MUST NOT 写成功日志；未知、Ctrl 重启和失败执行可能部分删除均不得被表述为清理成功。

#### Scenario: 受理时不写结果日志

- **WHEN** 手动清理已返回 `accepted=true`，或定时/升级清理提交成功，Node 任务仍在运行或尚未启动
- **THEN** `operation_logs` 不新增该次清理的成功或失败结果日志；此前已有的日志保持不变

#### Scenario: 明确成功后写一条成功日志

- **WHEN** Node 任务明确 `succeeded`，且 `cleaned_at` 与 `mount_cleaned` 在同一事务提交成功
- **THEN** `operation_logs` 恰新增一条成功日志，`operation` 为既有删除容器操作、`target_type="container_mount_cleanup"`、`target_id` 为清理记录 id；detail SHALL 含 `task_id`、trigger（手动/自动/升级分别为 `manual_clean_mount`/`auto_mount_cleanup`/`disk_escalation`）、`deleted_id`、`machine_id`、`mount_path`，升级记录同时保留 `escalation=true`，MUST NOT 含 Node 原始错误体

#### Scenario: 明确失败只写失败日志

- **WHEN** 任一入口的 Node 任务返回 `failed` 或启动被明确拒绝
- **THEN** `operation_logs` 恰新增一条 `success=false` 的失败日志，`error_reason` 为稳定原因；手动/自动/升级 trigger 与升级 escalation 保留；MUST NOT 新增成功日志，且数据库清理记录保持未清理

#### Scenario: 结果未知写失败或未知日志

- **WHEN** 任一入口的启动结果未知、状态查询达到连续通信失败上限、坏响应、任务丢失或 Node 重启导致结果无法确认
- **THEN** `operation_logs` 新增 `success=false` 的结果日志，`error_reason` 为稳定未知/失败原因；手动/自动/升级 trigger 与升级 escalation 保留；MUST NOT 写成成功，MUST NOT 标记已清理

#### Scenario: 成功落库失败不写成功日志

- **WHEN** Node 返回 `succeeded`，但 Ctrl 写 `cleaned_at`/`mount_cleaned` 的事务失败
- **THEN** 只写失败日志，`error_reason` 为稳定落库失败原因；MUST NOT 写成功日志，清理记录保持未清理

#### Scenario: Ctrl 重启不回填日志

- **WHEN** Ctrl 在任务进行中重启，进程内任务与轮询丢失
- **THEN** Ctrl MUST NOT 在启动后补写成功日志、失败日志或成功结果；用户通过数据库现状与既有列表状态判断，接受结果丢失

#### Scenario: 重复轮询不重复记账

- **WHEN** 同一任务被重复轮询到同一终态，或多个并发回调同时尝试记录终态
- **THEN** 该任务的结果日志最多一条；不因重复响应产生多条成功或失败日志

#### Scenario: 日志写入失败不影响真实清理结果

- **WHEN** Node 已明确成功且清理事务已提交，但写结果日志时数据库异常
- **THEN** 日志层不得抛回已结束的后台任务、不得伪造成功日志或改写清理状态；已提交的 `cleaned_at`/`mount_cleaned` 保持不变

#### Scenario: 已清理幂等不重复记账

- **WHEN** 对已清理记录再次发起手动清理
- **THEN** 返回既有幂等结果，不新增成功或失败结果日志，也不创建 Node 任务
