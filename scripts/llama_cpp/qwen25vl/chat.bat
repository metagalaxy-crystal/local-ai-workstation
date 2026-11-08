@echo off
REM Qwen2.5-VL-7B-Instruct - text chat client (for images use vlm.bat). Start with start.bat first.
REM Usage:  chat.bat "your prompt" [extra args: --stream ...]
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
