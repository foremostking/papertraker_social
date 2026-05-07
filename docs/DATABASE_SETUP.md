# 数据库配置指南

## 方案一：Docker Compose（推荐）

### 1. 启动数据库服务

```bash
# 在项目根目录运行
docker-compose up -d
```

这将启动：
- PostgreSQL 16 (端口 5432)
- Redis 7 (端口 6379)

### 2. 配置环境变量

复制 `.env.example` 到 `.env` 并修改数据库密码：

```bash
# backend/.env
DATABASE_URL=postgresql://postgres:password@localhost:5432/papertracker_social
REDIS_URL=redis://localhost:6379/0
```

### 3. 迁移数据

```bash
cd backend
python scripts/migrate_to_postgres.py
```

### 4. 验证连接

```bash
cd backend
python -c "from app.core.database import init_db; from app.models.journal import Base; from sqlalchemy import create_engine; engine = create_engine('postgresql://postgres:password@localhost:5432/papertracker_social'); print('✓ 连接成功')"
```

---

## 方案二：云数据库（生产环境推荐）

### Supabase（免费层）

1. 访问 https://supabase.com
2. 创建新项目
3. 获取数据库连接字符串
4. 配置 `.env`:

```bash
DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres
```

### 阿里云RDS / 腾讯云PostgreSQL

1. 创建PostgreSQL实例
2. 配置白名单（添加你的IP）
3. 获取连接信息
4. 配置 `.env`

---

## 数据库管理

### 查看表结构

```bash
# 连接到PostgreSQL
docker exec -it papertracker_postgres psql -U postgres -d papertracker_social

# 查看所有表
\dt

# 查看表结构
\d journals

# 退出
\q
```

### 数据迁移

```bash
# SQLite -> PostgreSQL
python backend/scripts/migrate_to_postgres.py

# 备份PostgreSQL
docker exec papertracker_postgres pg_dump -U postgres papertracker_social > backup.sql

# 恢复PostgreSQL
docker exec -i papertracker_postgres psql -U postgres papertracker_social < backup.sql
```

---

## 停止服务

```bash
docker-compose down
```

---

## 常见问题

### Q: 端口冲突？
A: 修改 `docker-compose.yml` 中的端口映射，如 `"5433:5432"`

### Q: 忘记密码？
A: 修改 `docker-compose.yml` 中的 `POSTGRES_PASSWORD`

### Q: 数据丢失？
A: Docker卷数据在 `docker-compose down` 后仍保留，如需完全清理：
```bash
docker-compose down -v
```
