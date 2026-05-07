# PaperTracker Social Backend

学术论文写作自动化Web应用后端服务

## 技术栈

- FastAPI - Web框架
- SQLAlchemy - ORM
- PostgreSQL - 数据库
- Redis - 缓存和Celery broker
- Celery - 异步任务队列
- BeautifulSoup4 - HTML解析

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，配置数据库连接等
```

### 3. 初始化数据库

```bash
alembic upgrade head
```

### 4. 启动服务

```bash
# 启动API服务
uvicorn app.main:app --reload --port 8000

# 启动Celery worker
celery -A app.tasks.celery_app worker --loglevel=info
```

## 项目结构

```
backend/
├── app/
│   ├── api/v1/         # API路由
│   ├── core/           # 核心配置
│   ├── models/         # 数据模型
│   ├── schemas/        # Pydantic模式
│   ├── services/       # 业务逻辑
│   ├── tasks/          # Celery任务
│   └── utils/          # 工具函数
├── tests/              # 测试
├── alembic/            # 数据库迁移
└── requirements.txt    # 依赖
```

## API文档

启动服务后访问：http://localhost:8000/docs
