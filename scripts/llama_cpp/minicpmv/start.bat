@echo off
REM MiniCPM-V-4.6 full-parameter launcher (mmproj loaded, image+video understanding).
REM Edit the SET lines below to change defaults, or override from the command line
REM (command-line args are appended last and win over the SET values).
REM   Example:  start.bat --ctx 16384 --think on --port 8081
REM Stop the server with Ctrl+C.

setlocal enabledelayedexpansion
if "%SAMPLE_PY%"=="" set "SAMPLE_PY=python"
set "HERE=%~dp0"

REM === editable defaults (blank = fall back to models.json / llama.cpp default) ===
set HOST=0.0.0.0
set PORT=8080
set ALIAS=
set CTX=8192
set NGL=99
set THREADS=6
set KV_TYPE=
set N_CPU_MOE=
set THINK=
set THINK_EFFORT=
set THINK_BUDGET=
set THINK_FORMAT=
set EXTRA=

REM === build arg list ===
set ARGS=minicpmv --host %HOST% --port %PORT%
if not "%ALIAS%"=="" set ARGS=!ARGS! --alias %ALIAS%
if not "%CTX%"=="" set ARGS=!ARGS! --ctx %CTX%
if not "%NGL%"=="" set ARGS=!ARGS! --ngl %NGL%
if not "%THREADS%"=="" set ARGS=!ARGS! --threads %THREADS%
if not "%KV_TYPE%"=="" set ARGS=!ARGS! --kv-type %KV_TYPE%
if not "%N_CPU_MOE%"=="" set ARGS=!ARGS! --n-cpu-moe %N_CPU_MOE%
if not "%THINK%"=="" set ARGS=!ARGS! --think %THINK%
if not "%THINK_EFFORT%"=="" set ARGS=!ARGS! --think-effort %THINK_EFFORT%
if not "%THINK_BUDGET%"=="" set ARGS=!ARGS! --think-budget %THINK_BUDGET%
if not "%THINK_FORMAT%"=="" set ARGS=!ARGS! --think-format %THINK_FORMAT%
if not "%EXTRA%"=="" set ARGS=!ARGS! --extra %EXTRA%

"%SAMPLE_PY%" "%HERE%..\start_server.py" !ARGS! %*
pause
