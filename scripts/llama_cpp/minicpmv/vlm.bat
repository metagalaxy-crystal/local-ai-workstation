@echo off
REM MiniCPM-V-4.6 - image/video understanding client (mmproj). Start with start.bat first.
REM Usage:  vlm.bat [--image D:\pic.png] [--video D:\clip.mp4] [-p "describe this"] [--think off]
REM         (--image / --video can be given multiple times, mixed)
REM No arguments: uses the llama.cpp built-in test image.
setlocal
if "%SAMPLE_PY%"=="" set "SAMPLE_PY=python"
set "HERE=%~dp0"
"%SAMPLE_PY%" "%HERE%..\vlm_test.py" --model minicpmv %*
pause
