# registration_codes

## Purpose

邮箱注册验证码的哈希及有效期。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: registration_codes 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `RegistrationCode`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: registration_codes 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：验证码按邮箱和学校域控制申请；只存 code_hash；expires_at 控制校验，验证成功时写 consumed_at；当前验证码消费与最终注册分属独立事务，注册失败仍可能已经消费，差异登记在 Global QUESTIONS。

#### Scenario: 验证码过期

- **WHEN** 请求验证已超过 expires_at 的验证码
- **THEN** 拒绝验证；不把哈希字段作为明文验证码展示

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
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

