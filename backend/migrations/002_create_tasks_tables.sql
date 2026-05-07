-- 创建 users 表
-- 执行方式：psql -U papertracker -d papertracker -f migrations/002_create_tasks_tables.sql

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(200) UNIQUE NOT NULL,
    hashed_password VARCHAR(200) NOT NULL,
    role VARCHAR(20) DEFAULT 'free' NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    is_superuser BOOLEAN DEFAULT FALSE NOT NULL,
    max_concurrent_tasks INTEGER DEFAULT 1 NOT NULL,
    max_papers_per_task INTEGER DEFAULT 500 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    last_login TIMESTAMP WITH TIME ZONE
);

-- 创建索引
CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);
CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);
CREATE INDEX IF NOT EXISTS ix_users_role ON users(role);

-- 添加注释
COMMENT ON TABLE users IS '系统用户表';
COMMENT ON COLUMN users.role IS '用户角色：free, pro, vip, admin';
COMMENT ON COLUMN users.max_concurrent_tasks IS '最大并发任务数';
COMMENT ON COLUMN users.max_papers_per_task IS '单个任务最大获取论文数';


-- 创建 tasks 表
CREATE TABLE IF NOT EXISTS tasks (
    id VARCHAR(36) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL,
    name VARCHAR(200),
    priority INTEGER DEFAULT 5 NOT NULL,
    params JSONB,
    status VARCHAR(20) DEFAULT 'PENDING' NOT NULL,
    progress JSONB,
    result JSONB,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- 创建索引
CREATE INDEX IF NOT EXISTS ix_tasks_user_id ON tasks(user_id);
CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS ix_tasks_type ON tasks(type);
CREATE INDEX IF NOT EXISTS ix_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS ix_tasks_user_status ON tasks(user_id, status);

-- 添加注释
COMMENT ON TABLE tasks IS '异步任务记录表';
COMMENT ON COLUMN tasks.type IS '任务类型：fetch_columns, fetch_papers, etc.';
COMMENT ON COLUMN tasks.status IS '任务状态：PENDING, STARTED, SUCCESS, FAILURE, REVOKED';
COMMENT ON COLUMN tasks.priority IS '优先级 1-10（数字越小优先级越高）';
