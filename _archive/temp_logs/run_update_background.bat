@echo off
chcp 65001 >nul
cd /d %~dp0
echo ========================================
echo 批量更新期刊详情 - 后台任务
echo ========================================
echo 开始时间: %date% %time%
echo.
echo 任务将在后台运行，即使关闭此窗口也会继续执行
echo 日志文件: update_details.log
echo.
echo 按 Ctrl+C 可中断任务
echo ========================================
echo.

python scripts/update_journal_details.py --verbose > update_details.log 2>&1

echo.
echo ========================================
echo 完成时间: %date% %time%
echo ========================================
pause
