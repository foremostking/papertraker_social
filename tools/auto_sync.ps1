# ScholarPilot 每日自动同步脚本
# 功能：自动检测变更、提交并推送到 GitHub

$GitPath = "D:\Software\Git\cmd\git.exe"
$ProjectDir = "d:\副业\2026\AI论文自动化工程\scholarpilot"
$LogFile = Join-Path $ProjectDir ".scholar\sync.log"
$Remote = "origin"
$Branch = "scholarpilot"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] [$Level] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
}

# 确保日志目录存在
$LogDir = Split-Path $LogFile -Parent
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# 1. git add -A
& $GitPath -C $ProjectDir add -A
if ($LASTEXITCODE -ne 0) {
    Write-Log "git add -A 失败 (exit=$LASTEXITCODE)" "ERROR"
    exit 1
}

# 2. 检查是否有变更
$status = & $GitPath -C $ProjectDir status --short
if ([string]::IsNullOrWhiteSpace($status)) {
    # 无变更，静默退出
    exit 0
}

# 3. 提交变更
$commitMsg = "auto sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
& $GitPath -C $ProjectDir commit -m "$commitMsg"
if ($LASTEXITCODE -ne 0) {
    Write-Log "git commit 失败 (exit=$LASTEXITCODE)" "ERROR"
    exit 1
}

# 4. 推送到远程
& $GitPath -C $ProjectDir push $Remote $Branch
if ($LASTEXITCODE -eq 0) {
    Write-Log "推送成功: $commitMsg" "INFO"
    exit 0
}

# 5. 推送失败，等待10秒后重试
Start-Sleep -Seconds 10
& $GitPath -C $ProjectDir push $Remote $Branch
if ($LASTEXITCODE -ne 0) {
    Write-Log "推送重试后仍然失败 (exit=$LASTEXITCODE)" "ERROR"
    exit 1
} else {
    Write-Log "重试后推送成功: $commitMsg" "INFO"
}
