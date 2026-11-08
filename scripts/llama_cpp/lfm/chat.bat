@echo off
REM LFM2.5-8B-A1B - send a prompt to the running llama-server (start.bat first).
REM Usage:  chat.bat "your prompt" [extra args: --stream --temp 0.8 ...]
REM Double-click with no arguments to type the prompt interactively.
setlocal
if "%SAMPLE_PY%"=="" set "SAMPLE_PY=python"
set "HERE=%~dp0"
if "%~1"=="" goto :ask
"%SAMPLE_PY%" "%HERE%..\chat.py" %*
goto :done
:ask
set /p CHAT_PROMPT=Prompt:
if "%CHAT_PROMPT%"=="" goto :eof
"%SAMPLE_PY%" "%HERE%..\chat.py" -p "%CHAT_PROMPT%"
:done
pause
