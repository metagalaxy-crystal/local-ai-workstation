# 天地源 · 电影版（v3）—— 一键重跑
# 用法（在 PowerShell 中）：
#   .\scripts\run_all.ps1                   # 已有产物则跳过，其余全跑
#   .\scripts\run_all.ps1 -ForceImages      # 重生成全部关键帧
#   .\scripts\run_all.ps1 -ForceVideo       # 重生成全部动态片段
#   .\scripts\run_all.ps1 -ForceMusic       # 重生成配乐
#   .\scripts\run_all.ps1 -SkipGenerate     # 跳过全部 AI 生成，只重做旁白/音效/画面/成片
param(
    [switch]$ForceImages,
    [switch]$ForceVideo,
    [switch]$ForceMusic,
    [switch]$SkipGenerate
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = "D:\models\.venv\Scripts\python.exe"

function Step($name, $block) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$name 失败（exit $LASTEXITCODE）" }
}

# 0. 检查 ComfyUI 服务（除旁白外所有生成步骤都需要）
$up = $false
try { (Invoke-WebRequest "http://127.0.0.1:8188/system_stats" -UseBasicParsing -TimeoutSec 3) | Out-Null; $up = $true } catch {}
if (-not $up -and -not $SkipGenerate) { throw "ComfyUI 未运行。先执行 .\scripts\01_start_comfyui.ps1" }

if (-not $SkipGenerate) {
    # 1. 关键帧（Z-Image-Turbo）
    $imgArgs = @("$root\scripts\gen_images.py")
    if ($ForceImages) { $imgArgs += "--force" }
    Step "关键帧生成" { & $py @imgArgs }

    # 2. 图生视频（MiniMax-H3）
    $clipArgs = @("$root\scripts\gen_clips.py", "--all")
    if ($ForceVideo) { $clipArgs += "--force" }
    Step "图生视频" { & $py @clipArgs }

    # 3. 配乐（ACE-Step）
    $musArgs = @("$root\scripts\gen_music.py")
    if ($ForceMusic) { $musArgs += "--force" }
    Step "配乐生成" { & $py @musArgs }
}

# 4. 旁白（MOSS-TTS 本地克隆，不依赖 ComfyUI）
Step "旁白合成" { & $py "$root\scripts\tts_moss.py" }

# 5. 时间轴
Step "时间轴" { & $py "$root\scripts\timeline.py" }

# 6. 环境音分层
Step "环境音" { & $py "$root\scripts\env_audio.py" }

# 7. 画面合成
Step "画面合成" { & $py "$root\scripts\render.py" }

# 8. 混音
Step "混音" { & $py "$root\scripts\mix.py" }

# 9. 母带 + 封装
Step "母带与封装" { & $py "$root\scripts\finish.py" }

# 10. 自检
Step "成片自检" { & $py "$root\build\verify.py" }

Write-Host "`n完成 -> $root\out\天地源_电影版_短片.mp4" -ForegroundColor Green
