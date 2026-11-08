@echo off
REM LLM -> MCP -> Blender demo: the local model writes bpy code and calls Blender MCP.
REM Requires llama-server on :8080 (scripts\llama_cpp\qwen36\start.bat).
python "%~dp0agent_demo.py" %*
pause
