@echo off
setlocal
cd /d "%~dp0"
docker compose --profile cpu --profile gpu down
pause
