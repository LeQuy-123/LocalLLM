@echo off
rem Runs Kokoro TTS (CPU) with output captured to data\kokoro.log
call "D:\AI\External\Kokoro-FastAPI\run_kokoro_cpu.bat" > "%~dp0data\kokoro.log" 2>&1
