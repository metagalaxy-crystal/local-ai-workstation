@echo off
rem Local Agent launcher (P0). Pure ASCII comments only.
rem Usage:
rem   start_agent.bat                 interactive session
rem   start_agent.bat --task "..."    one-shot task
rem   start_agent.bat --check         probe model server + tools
setlocal
cd /d D:\models\agent

set "PY=D:\models\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo [agent] python = %PY%
echo [agent] tip: start llama-server first (scripts\llama_cpp\qwen36\start.bat)
"%PY%" -m agent.cli %*
if errorlevel 1 (
  echo.
  echo [agent] exit code %errorlevel%
)
endlocal
