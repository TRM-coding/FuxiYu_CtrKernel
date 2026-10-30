# Proposal

## Why

机器共享内存配置已有 max_shared_gb 和内存约束，但 Update_machine 额外拒绝超过 8GB 的值。用户明确要求移除该硬编码，并在 SPEC 明确仍有效的 shared <= mem 契约。

## What Changes

- 删除固定 8GB 配置上限和歧义错误文案，保留非负整数及共享内存不得大于目标机器内存限额。
- 明确创建容器共享内存同时受机器共享限额与本次申请内存约束；保持该已有校验。
- 补充 8GB 以上有效配置、越界配置及真实 API 错误信息回归。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend--table-machines`：明确本次资源限额及输入/错误契约。
- `backend--table-containers`：明确本次资源限额及输入/错误契约。

## Impact

仅修改本仓库对应实现、业务规格和回归测试；不修改其它仓库或凭据。
