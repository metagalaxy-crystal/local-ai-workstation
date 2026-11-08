@echo off
REM Qwen3.6-35B-A3B - chat with thinking ON by default (start.bat first).
REM Usage:  chat.bat "your prompt" [extra args: --stream ...]
REM Append --think off to disable thinking for this request.
REM Double-click with no arguments to type the prompt interactively.
setlocal
if "%SAMPLE_PY%"=="" set "SAMPLE_PY=python"
set "HERE=%~dp0"
if "%~1"=="" goto :ask
"%SAMPLE_PY%" "%HERE%..\chat.py" --think on %*
goto :done
:ask
set /p CHAT_PROMPT=Prompt:
if "%CHAT_PROMPT%"=="" goto :eof
"%SAMPLE_PY%" "%HERE%..\chat.py" --think on -p "%CHAT_PROMPT%"
:done
pause
