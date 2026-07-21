@echo off
REM ScholarPilot Web UI 启动脚本
REM
REM 用法：双击运行 或 在终端执行 start_web.bat
REM 依赖已安装在 Anaconda Python (D:\Software\anaconda3_)

cd /d "D:\副业\2026\AI论文自动化工程\scholarpilot"

REM 设置 PYTHONPATH
set PYTHONPATH=src

echo ========================================
echo  ScholarPilot Web UI 启动中...
echo  访问地址: http://localhost:8501
echo  按 Ctrl+C 停止
echo ========================================
echo.

streamlit run src/scholarpilot/web/app.py --server.port 8501 --server.headless true

pause
