# users

## Purpose

平台用户身份、登录凭据哈希和毕业年份。本文件是 d6d0d0e26fb6（chester-next）在 2026-10-11 的代码逆向基线，以表结构为单位记录已实现的契约。字段声明、外键、唯一约束以模型和服务为依据；已知缺陷及迁移风险统一登记在 [Global QUESTIONS](../../../../FuxiYu_Global/QUESTIONS.md)，不代表修复已完成。

## Requirements

### Requirement: users 持久化结构

系统 SHALL 使用数据附录的字段声明持久化 `User`，遵守模型声明的主键、非空、唯一键、外键及默认值；Python 默认值与数据库 server_default 必须分别理解。


字段与成员见文末同名数据附录。


#### Scenario: 读取有效记录

- **WHEN** 服务按该表主键读取一条已经持久化的有效记录
- **THEN** 返回字段 SHALL 遵守上述类型及空值语义，不把关联展示名替代稳定主键

### Requirement: users 生产职责与生命周期

系统 SHALL 按以下已实现的生命周期使用本表：username/email 各自唯一；身份由有效 token 和 RBAC 组派生，已不使用 users.permission；用户删除先处理容器归属与绑定。

#### Scenario: 创建用户

- **WHEN** 用户名和邮箱未占用且注册校验通过
- **THEN** 保存 password_hash 和用户信息，不在返回数据中暴露口令哈希

## Data model appendix

### users 持久化结构

| 字段 | 模型声明 | 源码行 |
| --- | --- | --- |
| `id` | `db.Column(db.Integer, primary_key=True)` | 10 |
| `username` | `db.Column(db.String(80), unique=True, nullable=False, index=True)` | 11 |
| `email` | `db.Column(db.String(120), unique=True, nullable=False, index=True)` | 12 |
| `password_hash` | `db.Column(db.String(255), nullable=False)` | 13 |
| `created_at` | `db.Column(db.DateTime, default=datetime.utcnow)` | 14 |
| `graduation_year` | `db.Column(db.String(120), unique=False, nullable=False)` | 15 |

## Source references

- [models/user.py](../../../models/user.py)：User，第 7 行。
- 数据库初始化：[`__init__.py`](../../../__init__.py)、[`extensions.py`](../../../extensions.py)；`create_all` 只创建缺失表，不推定已替旧表完成列迁移。
- 回归验证：[`test/`](../../../test/) 中该单元对应的仓储、服务、API 用例；本次默认安全套件 992 passed、6 deselected。

