# 启动 Nanbeige 3B llama-server（OpenAI 兼容 API on 127.0.0.1:8080）
$exe = 'D:\models\llama.cpp\build\bin\Release\llama-server.exe'
$model = 'D:\models\models\text\Nanbeige4.2-3B\Nanbeige4.2-3B-Q4_K_M.gguf'
& $exe -m $model --host 127.0.0.1 --port 8080 -c 8192 -ngl 99 --jinja
