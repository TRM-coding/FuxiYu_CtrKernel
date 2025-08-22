# 伏羲-御

## 伏羲・御・Fuxi-Yu

面向算力平台的 Docker 化集群管理与自助使用系统。将物理服务器纳入统一 “控制面”，用户以申请到的 Docker 实例直控实体机，配套可视化的基础环境配置（网络、用户等），免去繁琐安装与踩坑，友好地面向 Linux 新手与多用户场景。

```
config.py            # 配置
extensions.py        # 第三方扩展初始化
__init__.py          # create_app 工厂
run.py               # 开发直接运行入口
wsgi.py              # 生产/WSGI 入口
models/              # 数据模型层
repositories/        # 数据访问仓储层
services/            # 业务服务层
schemas/             # 序列化/反序列化层 (Marshmallow)
blueprints/          # 路由蓝图 (接口层)
```

## 功能点
- App 工厂模式 (`create_app`)
- 配置分环境 (development / production / testing)
- SQLAlchemy + Migrate 数据迁移能力
- Caching / LoginManager 预置
- 用户模型 + 仓储 + 服务 + Schema + API 示例
- Marshmallow 进行序列化

## 快速开始

### 1. 克隆与安装依赖
```bash
pip install -r requirements.txt
```

### 2. 初始化数据库
```bash
# 生成迁移仓库
flask --app compute_cluster_manage_web:create_app db init
# 生成迁移脚本
flask --app compute_cluster_manage_web:create_app db migrate -m "init"
# 应用迁移
flask --app compute_cluster_manage_web:create_app db upgrade
```
> 若你直接使用 sqlite，默认文件为 `app.db`。

### 3. 运行开发服务器
```bash
python -m compute_cluster_manage_web.run
# 或
flask --app compute_cluster_manage_web:create_app run --debug
```
访问: http://127.0.0.1:5000/api/users

### 4. 示例 API

#### 创建用户
```bash
curl -X POST http://127.0.0.1:5000/api/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"123456"}'
```
响应:
```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com",
  "created_at": "2025-01-01T00:00:00"
}
```

#### 列表用户
```bash
curl http://127.0.0.1:5000/api/users
```

### 5. 目录/分层说明
| 层 | 说明 | 关注点 |
|----|------|--------|
| model | `models/` | ORM 定义，仅包含字段和关系 |
| repository | `repositories/` | 封装数据库 CRUD |
| service | `services/` | 业务逻辑、组合多个仓储 |
| schema | `schemas/` | 输入校验与输出序列化 |
| blueprint(API) | `blueprints/` | HTTP 路由 / 参数获取 / 返回 |

## 配置
环境通过环境变量 `FLASK_ENV` / 自定义传入 `create_app("production")` 选择。
可用变量:
- `DATABASE_URL` (默认 sqlite:///app.db)
- `SECRET_KEY`
- `CACHE_TYPE` (默认 SimpleCache)

## 部署 (Gunicorn 示例)
```bash
gunicorn 'compute_cluster_manage_web.wsgi:app' -b 0.0.0.0:8000 --workers 4
```

## 后续可扩展建议
- 使用 `python-dotenv` 加载 `.env`
- 引入 Alembic 版本号命名策略 / 预置 seed 脚本
- 集成单元测试 (pytest + factory-boy)
- 使用真实密码哈希: `from werkzeug.security import generate_password_hash`
- 增加 JWT 或 Session 认证流程


