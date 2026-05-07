# PaperTracker 后端启动脚本

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  PaperTracker 后端服务启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 设置环境变量
$env:DATABASE_URL = "postgresql://papertracker:password@localhost:15432/papertracker_social"
$env:CELERY_BROKER_URL = "redis://localhost:6379/0"
$env:CELERY_RESULT_BACKEND = "redis://localhost:6379/1"

Write-Host "环境变量已设置:" -ForegroundColor Green
Write-Host "  DATABASE_URL = $env:DATABASE_URL"
Write-Host "  CELERY_BROKER_URL = $env:CELERY_BROKER_URL"
Write-Host ""

Write-Host "启动 FastAPI 服务..." -ForegroundColor Yellow
Write-Host "访问地址: http://localhost:8000" -ForegroundColor Cyan
Write-Host "API 文档: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "按 Ctrl+C 停止服务" -ForegroundColor Red
Write-Host ""

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
