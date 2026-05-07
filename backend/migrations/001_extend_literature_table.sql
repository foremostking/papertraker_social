-- Literature 表扩展：添加论文获取和去重相关字段
-- 执行方式：psql -U papertracker -d papertracker -f migrations/001_extend_literature_table.sql

-- 添加新字段
ALTER TABLE literature
ADD COLUMN IF NOT EXISTS detail_url VARCHAR(500);

ALTER TABLE literature
ADD COLUMN IF NOT EXISTS year_issue VARCHAR(20);

ALTER TABLE literature
ADD COLUMN IF NOT EXISTS download_count INTEGER DEFAULT 0;

ALTER TABLE literature
ADD COLUMN IF NOT EXISTS column_name VARCHAR(200);

ALTER TABLE literature
ADD COLUMN IF NOT EXISTS cnki_id VARCHAR(100);

-- 创建索引
CREATE INDEX IF NOT EXISTS ix_literature_detail_url ON literature(detail_url);

-- 注意：cnki_id 需要创建唯一索引，但如果有重复数据会失败
-- 可以先创建非唯一索引，数据清理后再改为唯一索引
CREATE UNIQUE INDEX IF NOT EXISTS uq_literature_cnki_id ON literature(cnki_id);

-- 如果上面的唯一索引创建失败（因为已有重复），使用下面的语句：
-- CREATE INDEX ix_literature_cnki_id ON literature(cnki_id);

CREATE INDEX IF NOT EXISTS ix_literature_journal_column ON literature(journal_id, column_name);

-- 添加注释
COMMENT ON COLUMN literature.detail_url IS 'CNKI详情页URL';
COMMENT ON COLUMN literature.year_issue IS '年/期格式，如 2024/05';
COMMENT ON COLUMN literature.download_count IS '下载次数';
COMMENT ON COLUMN literature.column_name IS '来源栏目追溯';
COMMENT ON COLUMN literature.cnki_id IS 'CNKI唯一标识（用于去重）';
