# 天地源 · 进阶版 —— 一键重跑
# 用法（在 PowerShell 中）：
#   .\scripts\run_all.ps1                 # 视频已存在则跳过，其余全跑
#   .\scripts\run_all.ps1 -ForceVideo     # 重新生成全部动态片段
#   .\scripts\run_all.ps1 -SkipVideo      # 只重做旁白/音效/画面/成片
param(
    [switch]$ForceVideo,
    [switch]$SkipVideo
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = "D:\models\.venv\Scripts\python.exe"
$sysPy = "python"

function Step($name, $block) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$name 失败（exit $LASTEXITCODE）" }
}

# 0. 检查 ComfyUI 服务
$up = $false
try { (Invoke-WebRequest "http://127.0.0.1:8188/system_stats" -UseBasicParsing -TimeoutSec 3) | Out-Null; $up = $true } catch {}
if (-not $up) { throw "ComfyUI 未运行。先执行 .\scripts\01_start_comfyui.ps1" }

# 1. 图生视频（本地 ComfyUI / MiniMax H3）
if (-not $SkipVideo) {
    $args = @("$root\scripts\comfy_i2v.py", "--all")
    if ($ForceVideo) { $args += "--force" }
    Step "图生视频" { & $py @args }
}

# 2. 旁白（分句韵律）
Step "旁白合成" { & $sysPy "$root\scripts\build_tts.py" }

# 3. 时间轴
Step "时间轴" { & $sysPy "$root\scripts\timeline.py" }

# 4. 环境音分层
Step "环境音" { & $sysPy "$root\scripts\env_audio.py" }

# 5. 画面合成
Step "画面合成" { & $sysPy "$root\scripts\render.py" }

# 6. 混音
Step "混音" { & $sysPy "$root\scripts\mix.py" }

# 7. 母带 + 封装
Step "母带与封装" { & $sysPy "$root\scripts\finish.py" }

Write-Host "`n完成 -> $root\out\天地源_进阶版_短片.mp4" -ForegroundColor Green
