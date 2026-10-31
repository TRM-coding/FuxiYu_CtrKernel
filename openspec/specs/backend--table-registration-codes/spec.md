# registration_codes

## Purpose

定义邮箱验证码的哈希持久化、学校域与有效期校验、单次消费及成功注册事务。注册失败保留有效验证码，用户创建与必要身份关联成功提交时才完成消费，并防止同码重复成功。

## Requirements

### Requirement: registration_codes 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `RegistrationCode`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。

字段与成员见文末同名数据附录。

#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: registration_codes 生产职责与生命周期

验证码 SHALL 按邮箱和学校域申请，只持久化 code_hash 并按 expires_at 校验。验证码消费 SHALL 与最终用户注册成功处于同一事务；用户名或邮箱冲突、输入校验失败及持久化失败 MUST NOT 消费验证码。成功注册 SHALL 标记 consumed_at，后续不可重用；并发使用同一验证码至多成功一次。验证码有效期和错误码策略 SHALL 延续既有契约。

#### Scenario: 验证码过期
- **WHEN** 请求验证已超过 expires_at 的验证码
- **THEN** 拒绝验证，不把哈希字段作为明文验证码展示

#### Scenario: 注册冲突后修正重试
- **WHEN** 有效验证码对应的注册因用户名冲突失败，用户在有效期内修正用户名重试
- **THEN** 首次不消费验证码，再次提交可以成功，成功时才将验证码与新用户一并提交

#### Scenario: 注册持久化失败
- **WHEN** 注册事务中的数据库写入或提交失败
- **THEN** 用户创建与验证码消费共同回滚，不遗留已消费但未成功注册的状态

#### Scenario: 同码并发注册
- **WHEN** 两个事务同时使用同一有效验证码提交注册
- **THEN** 数据库条件消费或等效事务机制保证至多一个注册成功，失败事务不遗留用户或提前消费

### Requirement: 注册验证码邮件的基本防重复

系统 SHALL 在发送注册验证码前检查邮箱是否已注册；已注册时返回 `email_exists` 且不写验证码、不发送邮件。对同一邮箱忽略大小写检查已有验证码创建时间；60 秒内重复请求返回 `rate_limited`，不创建新验证码或发送邮件。同进程内检查与创建 SHALL 串行化；不新增数据库结构，不声称跨进程、跨机器或按 IP 完整限流。

#### Scenario: 已注册邮箱

- **WHEN** 已注册邮箱请求注册验证码
- **THEN** 返回 HTTP 409 `email_exists`，不创建验证码、不发邮件

#### Scenario: 同邮箱冷却

- **WHEN** 同一邮箱在上次创建验证码后 60 秒内再次请求
- **THEN** 返回 HTTP 429 `rate_limited`，不覆盖上次验证码、不重复发邮件

#### Scenario: 邮件发送失败

- **WHEN** 已创建验证码但邮件发送失败
- **THEN** 该验证码的创建时间仍参与冷却，不因发送失败立即重复投递

### Requirement: 验证码响应提供实际冷却时间

注册验证码请求 SHALL 仅在发送成功或返回 `rate_limited` 时，在响应体顶层提供非负整数 `retry_after_seconds`。其值 SHALL 由该邮箱同一条用于节流判断的创建时间和冷却期限计算，剩余不足一秒向上取整；成功发信所耗时间 SHALL 计入。其他失败响应 MUST NOT 包含该字段。

#### Scenario: 发送成功

- **WHEN** 验证码创建并成功发送
- **THEN** 成功响应提供该邮箱当前实际剩余冷却秒数，不固定返回完整 60 秒

#### Scenario: 请求命中冷却

- **WHEN** 同一邮箱再次请求并触发 `rate_limited`
- **THEN** HTTP 429 响应提供该邮箱当时的最新剩余冷却秒数，不刷新原冷却期限

#### Scenario: 发送失败后再次请求

- **WHEN** 验证码记录已创建但发信失败，随后同邮箱在冷却期内再次请求
- **THEN** 原失败响应不含 `retry_after_seconds`；后一次返回 `rate_limited` 和根据已有记录计算的剩余秒数

#### Scenario: 其他失败

- **WHEN** 请求因邮箱已注册、输入无效或其他错误失败，且不是 `rate_limited`
- **THEN** 响应不包含 `retry_after_seconds`

## Data model appendix

### registration_codes 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 9 |
| `email` | `db.Column(db.String(120), nullable=False, index=True)` | 10 |
| `school_domain` | `db.Column(db.String(80), nullable=False)` | 11 |
| `code_hash` | `db.Column(db.String(255), nullable=False)` | 12 |
| `expires_at` | `db.Column(db.DateTime, nullable=False)` | 13 |
| `consumed_at` | `db.Column(db.DateTime, nullable=True)` | 14 |
| `created_at` | `db.Column(db.DateTime, default=datetime.utcnow, nullable=False)` | 15 |

## Source references

- [models/registration_code.py](../../../models/registration_code.py)：RegistrationCode，第 6 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；运行结果以当前隔离安全套件为准。
