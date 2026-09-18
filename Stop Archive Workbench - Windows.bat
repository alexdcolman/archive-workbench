@echo off
setlocal
cd /d "%~dp0"
set "AW_AI_CMD="
if defined ARCHIVE_WORKBENCH_AI_EXECUTABLE set "AW_AI_CMD=%ARCHIVE_WORKBENCH_AI_EXECUTABLE%"
if not defined AW_AI_CMD for /f "delims=" %%I in ('where aw-ai 2^>nul') do if not defined AW_AI_CMD set "AW_AI_CMD=%%I"
if defined AW_AI_CMD "%AW_AI_CMD%" bridge stop --root "%CD%\ArchiveWorkbenchData\Settings\archive-workbench-ai-bridge" >nul 2>&1
docker compose --profile cpu --profile gpu down
pause
