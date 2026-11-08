@echo off
rem Start embedding (port 8081) and rerank (port 8082) llama-server instances.
rem Both run on CPU (-ngl 0) to keep VRAM free for the main brain. Pure ASCII.
setlocal
set "SERVER=D:\models\llama.cpp\build\bin\Release\llama-server.exe"
set "EMB=D:\models\models\text\Qwen3-Embedding-0.6B\Qwen3-Embedding-0.6B-Q8_0.gguf"
set "RRK=D:\models\models\text\Qwen3-Reranker-0.6B\Qwen3-Reranker-0.6B-Q8_0.gguf"

if "%~1"=="embed" goto :embed
if "%~1"=="rerank" goto :rerank
echo Starting embedding on :8081 and rerank on :8082 (CPU mode, -ngl 0)...
start "embed-8081" "%SERVER%" -m "%EMB%" --embedding -ngl 0 -c 8192 -t 6 --host 127.0.0.1 --port 8081
start "rerank-8082" "%SERVER%" -m "%RRK%" --reranking -ngl 0 -c 8192 -t 6 --host 127.0.0.1 --port 8082
echo Done. Close the two new windows to stop.
goto :eof

:embed
"%SERVER%" -m "%EMB%" --embedding -ngl 0 -c 8192 -t 6 --host 127.0.0.1 --port 8081
goto :eof

:rerank
"%SERVER%" -m "%RRK%" --reranking -ngl 0 -c 8192 -t 6 --host 127.0.0.1 --port 8082
endlocal
