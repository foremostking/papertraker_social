# ScholarPilot 每日自动推送脚本
# 静默执行：无变更则跳过；推送失败重试一次；仍失败才写错误日志
# 由 Windows 任务计划程序调用

$ErrorActionPreference = 'SilentlyContinue'
$ProjectDir = 'd:\副业\2026\AI论文自动化工程\scholarpilot'
$Branch     = 'scholarpilot'
$LogFile    = Join-Path $ProjectDir '.scholar\daily_sync_errors.log'

Set-Location $ProjectDir

git add -A
$status = git status --short
if ([string]::IsNullOrWhiteSpace($status)) { exit 0 }

$commitMsg = "auto sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git commit -m $commitMsg | Out-Null

$ok = $false
git push origin $Branch 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { $ok = $true }

if (-not $ok) {
    Start-Sleep -Seconds 10
    git push origin $Branch 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $ok = $true }
}

if (-not $ok) {
    $null = New-Item -ItemType Directory -Path (Split-Path $LogFile) -Force
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  PUSH FAILED (exit=$LASTEXITCODE)" |
        Out-File -FilePath $LogFile -Append -Encoding utf8
    exit 1
}
exit 0
