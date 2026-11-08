# vlm_server.ps1 - 启停图生文 VLM 服务（llama-server + mmproj）
# 用法:
#   .\vlm_server.ps1 -Action start -Vlm minicpm -Ngl 999 -Port 8081   # 独占显存时 Ngl 999
#   .\vlm_server.ps1 -Action start -Vlm qwenvl -Ngl 16                # 与 ComfyUI 共存时分层卸载
#   .\vlm_server.ps1 -Action stop
param(
    [string]$Action = "start",
    [ValidateSet("minicpm", "qwenvl")]
    [string]$Vlm = "minicpm",
    [int]$Ngl = 999,
    [int]$Port = 8081
)

$ErrorActionPreference = "Stop"
$base = "D:\models"
$exe = "$base\llama.cpp\build\bin\Release\llama-server.exe"
$here = "$base\铁锈海的女儿\08_image_pipeline"
$pidFile = "$here\vlm_server.pid"
$logDir = "$here\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if ($Action -eq "stop") {
    if (Test-Path $pidFile) {
        $p = Get-Content $pidFile -Raw
        Stop-Process -Id $p.Trim() -Force -ErrorAction SilentlyContinue
        Remove-Item $pidFile -Force
        Write-Host "VLM 服务已停止 (pid=$($p.Trim()))"
    } else {
        Write-Host "无 pid 文件，未停止任何进程"
    }
    exit 0
}

$models = @{
    minicpm = @{
        m  = "$base\models\text\MiniCPM-V-4_6\MiniCPM-V-4.6-Q4_K_M.gguf"
        mm = "$base\models\text\MiniCPM-V-4_6\mmproj-MiniCPM-V-4.6-Q8_0.gguf"
    }
    qwenvl = @{
        m  = "$base\models\text\Qwen2.5-VL-7B\Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf"
        mm = "$base\models\text\Qwen2.5-VL-7B\mmproj-Qwen2.5-VL-7B-Instruct-Q8_0.gguf"
    }
}
foreach ($f in $models[$Vlm].Values) {
    if (-not (Test-Path $f)) { Write-Host "缺少模型文件: $f"; exit 1 }
}
$sel = $models[$Vlm]

$proc = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput "$logDir\vlm_$Vlm.out.log" `
    -RedirectStandardError "$logDir\vlm_$Vlm.err.log" `
    -ArgumentList @(
        "-m", $sel.m, "--mmproj", $sel.mm,
        "--host", "127.0.0.1", "--port", "$Port",
        "-ngl", "$Ngl", "-c", "8192", "--no-webui"
    )
$proc.Id | Out-File $pidFile -Encoding ascii
Write-Host "llama-server 启动中: $Vlm ngl=$Ngl port=$Port pid=$($proc.Id)"

for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep 1
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2
        if ($r.status -eq "ok") { Write-Host "READY"; exit 0 }
    } catch {}
    if ($proc.HasExited) { Write-Host "进程已退出，查看 $logDir\vlm_$Vlm.err.log"; exit 1 }
}
Write-Host "等待超时（180s），查看 $logDir"
exit 1
