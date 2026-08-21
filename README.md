# 伏羲 · Fuxi-Yu

Fuxi-Yu 是面向高校与实验室算力管理场景的容器化平台。CtrlKernel 是伏羲平台的控制端服务，负责用户、机器、容器、公告、审计日志、权限与 Node 通信编排。

当前版本使用 FastAPI 提供 HTTP API 与 Swagger 文档，使用 SQLAlchemy 管理数据库访问。

## 快速上手

### 1. 安装依赖

建议在项目约定的 Python 环境中安装：

```bash
pip install -r requirements.txt
```

### 2. 配置环境

可参考 `.env.example` 创建 `.env`。常用配置：

```bash
DATABASE_URL=sqlite:///app.db
CTRL_PORT=5000
SECRET_KEY=change-me
```

未设置 `DATABASE_URL` 时，默认使用当前目录下的 `app.db`。

### 3. 初始化基础数据

```bash
python -m FuxiYu_CtrKernel.seed
```

数据库表会在应用启动时按当前模型创建；手写迁移脚本位于 `migrations/`。

### 4. 启动服务

```bash
python -m FuxiYu_CtrKernel.run
```

默认访问地址：

```text
http://127.0.0.1:5000
```

Swagger 文档：

```text
http://127.0.0.1:5000/docs
```

### 5. 运行测试

默认测试不会访问真实 Node、Docker、SMTP 或生产数据库：

```bash
pytest
```

需要验证真实外部链路时，再单独运行集成测试：

```bash
pytest -m integration
```

## 目录结构

```text
api/                 # FastAPI 路由与依赖
schemas/             # API 请求与响应结构
models/              # 数据模型
repositories/        # 数据访问
services/            # 业务逻辑
schedulers/          # 后台任务
utils/               # 通用工具
migrations/          # 数据库迁移脚本
run.py               # 本地启动入口
asgi.py              # ASGI 应用入口
```

## 开发约定

数据库事务边界放在 service/tasks 层，repository 只接收显式传入的 session 并执行数据读写。这个约定主要是为了让 API、后台任务和 WSS 使用同一套数据库访问方式，降低排错成本。
