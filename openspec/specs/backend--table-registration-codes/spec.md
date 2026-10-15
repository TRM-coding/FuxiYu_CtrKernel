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
