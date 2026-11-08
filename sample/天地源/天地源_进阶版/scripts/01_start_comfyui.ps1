# 启动本地 ComfyUI（图生视频服务）
# 说明：ComfyUI 装在 D:\models\ComfyUI，使用 D:\models\.venv 的 Python；
#       system python 缺 pyyaml/alembic，不要用它启动。
$py = "D:\models\.venv\Scripts\python.exe"
$script = "D:\models\scripts\comfyui\start_comfyui.py"

$up = $false
try { (Invoke-WebRequest "http://127.0.0.1:8188/system_stats" -UseBasicParsing -TimeoutSec 2) | Out-Null; $up = $true } catch {}
if ($up) { Write-Host "ComfyUI 已在 8188 运行"; exit 0 }

Start-Process -FilePath $py -ArgumentList $script -WorkingDirectory "D:\models" -WindowStyle Minimized
Write-Host "正在启动 ComfyUI（约 20s）…"
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    try {
        (Invoke-WebRequest "http://127.0.0.1:8188/system_stats" -UseBasicParsing -TimeoutSec 2) | Out-Null
        Write-Host "ComfyUI 就绪：http://127.0.0.1:8188" -ForegroundColor Green
        exit 0
    } catch {}
}
throw "ComfyUI 启动超时，请查看控制台日志"
