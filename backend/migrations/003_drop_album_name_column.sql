-- 迁移 003: 删除 album_name 字段
-- 原因: 专辑名称已同步到 field (一级学科)，避免数据冗余
-- 日期: 2025-03-25

-- 步骤1: 检查 field 是否已填充
DO $$
DECLARE
    empty_field_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO empty_field_count
    FROM journals
    WHERE field IS NULL AND album_name IS NOT NULL;

    IF empty_field_count > 0 THEN
        RAISE EXCEPTION '发现 % 条记录的 field 为空但 album_name 不为空。请先运行 fix_journal_field_mapping.py 脚本同步数据。', empty_field_count;
    END IF;

    RAISE NOTICE '数据完整性检查通过：所有有 album_name 的记录都已同步到 field';
END $$;

-- 步骤2: 显示统计信息
SELECT
    '删除前统计' as step,
    COUNT(*) as total,
    COUNT(field) as has_field,
    COUNT(album_name) as has_album_name
FROM journals;

-- 步骤3: 删除字段
ALTER TABLE journals DROP COLUMN IF EXISTS album_name;

-- 步骤4: 确认删除
SELECT
    '删除后统计' as step,
    COUNT(*) as total,
    COUNT(field) as has_field
FROM journals;

SELECT '✓ album_name 字段已成功删除' as result;
