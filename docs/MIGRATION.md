# 数据库迁移指南

本文档说明如何运行数据库迁移脚本以设置期刊栏目管理系统所需的数据库表。

## 前置条件

1. PostgreSQL 数据库已运行
2. 已创建数据库用户和数据库

## 迁移文件说明

### 001_extend_literature_table.sql

扩展 `literature` 表，添加论文获取和去重相关字段：

- `detail_url` - CNKI详情页URL
- `year_issue` - 年/期格式（如 "2024/05"）
- `download_count` - 下载次数
- `column_name` - 来源栏目追溯
- `cnki_id` - CNKI唯一标识（用于去重）

### 002_create_tasks_tables.sql

创建任务管理相关表：

- `users` - 系统用户表（支持角色权限）
- `tasks` - 异步任务记录表

## 运行迁移

### 使用 Docker Compose

```bash
# 启动数据库
docker-compose up -d postgres

# 等待数据库就绪
docker-compose logs -f postgres

# 在新终端中运行迁移
docker exec -i papertracker_postgres psql -U papertracker -d papertracker < backend/migrations/001_extend_literature_table.sql
docker exec -i papertracker_postgres psql -U papertracker -d papertracker < backend/migrations/002_create_tasks_tables.sql
```

### 使用本地 PostgreSQL

```bash
# 设置环境变量
export PGUSER=papertracker
export PGDATABASE=papertracker
export PGHOST=localhost
export PGPORT=15432

# 运行迁移
psql -f backend/migrations/001_extend_literature_table.sql
psql -f backend/migrations/002_create_tasks_tables.sql
```

### 使用 Windows psql

```cmd
REM 运行迁移
psql -U papertracker -d papertracker -h localhost -p 15432 -f backend\migrations\001_extend_literature_table.sql
psql -U papertracker -d papertracker -h localhost -p 15432 -f backend\migrations\002_create_tasks_tables.sql
```

## 验证迁移

运行以下 SQL 检查表结构：

```sql
-- 检查 literature 表新字段
\d literature

-- 检查 users 表
\d users

-- 检查 tasks 表
\d tasks

-- 检查索引
\di *literature*
\di *tasks*
```

## 回滚迁移

如需回滚，请手动执行以下操作：

### 回滚 001_extend_literature_table.sql

```sql
DROP INDEX IF EXISTS uq_literature_cnki_id;
DROP INDEX IF EXISTS ix_literature_journal_column;
DROP INDEX IF EXISTS ix_literature_detail_url;

ALTER TABLE literature DROP COLUMN IF EXISTS cnki_id;
ALTER TABLE literature DROP COLUMN IF EXISTS column_name;
ALTER TABLE literature DROP COLUMN IF EXISTS download_count;
ALTER TABLE literature DROP COLUMN IF EXISTS year_issue;
ALTER TABLE literature DROP COLUMN IF EXISTS detail_url;
```

### 回滚 002_create_tasks_tables.sql

```sql
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS users;
```

## 注意事项

1. **cnki_id 唯一索引**：如果 literature 表中已有数据，创建唯一索引可能因重复数据失败。此时可以先创建非唯一索引，清理重复数据后再改为唯一索引。

2. **权限问题**：确保运行迁移的用户有 CREATE TABLE、ALTER TABLE、CREATE INDEX 权限。

3. **备份数据**：在生产环境运行迁移前，请先备份数据库。

## 故障排除

### 错误：relation "literature" does not exist

说明 literature 表尚未创建，需要先运行基础表创建脚本。

### 错误：could not create unique index

说明 cnki_id 字段存在重复数据。可以：

1. 先创建非唯一索引：`CREATE INDEX ix_literature_cnki_id ON literature(cnki_id);`
2. 清理重复数据
3. 再创建唯一索引

### 错误：permission denied

确保数据库用户有足够权限，或者使用 postgres 超级用户运行迁移。
