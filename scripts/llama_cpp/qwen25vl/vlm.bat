@echo off
REM Qwen2.5-VL-7B-Instruct - image/video understanding client (mmproj). Start with start.bat first.
REM Usage:  vlm.bat [--image D:\pic.png] [--video D:\clip.mp4] [-p "describe this"]
REM         (--image / --video can be given multiple times, mixed)
REM No arguments: uses the llama.cpp built-in test image.
setlocal
if "%SAMPLE_PY%"=="" set "SAMPLE_PY=python"
set "HERE=%~dp0"
"%SAMPLE_PY%" "%HERE%..\vlm_test.py" --model qwen25vl %*
pause
