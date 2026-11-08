@echo off
"D:\models\llama.cpp\build\bin\Release\llama-server.exe" ^
  -m "D:\models\models\text\Nanbeige4.2-3B\Nanbeige4.2-3B-Q4_K_M.gguf" ^
  --host 127.0.0.1 --port 8080 ^
  -c 8192 -ngl 99 --jinja
