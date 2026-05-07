# PaperTracker Social - 启动脚本

Write-Host "========================================"  -ForegroundColor Cyan
Write-Host "Starting PaperTracker Social Services..." -ForegroundColor Cyan
Write-Host "========================================"  -ForegroundColor Cyan
Write-Host ""

# 获取脚本所在目录
$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path

# 启动后端
Write-Host "[1/2] Starting Backend API..." -ForegroundColor Yellow
$Backend = Start-Process -FilePath "python" -ArgumentList "-m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" -WorkingDirectory "$ScriptPath\backend" -PassThru -NoNewWindow

Start-Sleep -Seconds 3

# 启动前端
Write-Host "[2/2] Starting Frontend..." -ForegroundColor Yellow
$Frontend = Start-Process -FilePath "npm" -ArgumentList "run dev" -WorkingDirectory "$ScriptPath\web" -PassThru -NoNewWindow

Write-Host ""
Write-Host "========================================"  -ForegroundColor Green
Write-Host "All services started!" -ForegroundColor Green
Write-Host "========================================"  -ForegroundColor Green
Write-Host ""
Write-Host "Backend API:  http://localhost:8000" -ForegroundColor White
Write-Host "Frontend:     http://localhost:5173" -ForegroundColor White
Write-Host "API Docs:     http://localhost:8000/docs" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C to stop all services..." -ForegroundColor Gray

# 等待用户中断
try {
    Wait-Process -Id $Backend.Id, $Frontend.Id
} finally {
    Write-Host ""
    Write-Host "Stopping services..." -ForegroundColor Yellow
    Stop-Process -Id $Backend.Id, $Frontend.Id -ErrorAction SilentlyContinue
    Write-Host "Services stopped." -ForegroundColor Green
}
