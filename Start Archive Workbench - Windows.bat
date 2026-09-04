@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "AW_SERVICE=app-cpu"
set "AW_PROFILE=cpu"
if defined ARCHIVE_WORKBENCH_CPU_IMAGE (
  set "AW_IMAGE=%ARCHIVE_WORKBENCH_CPU_IMAGE%"
) else (
  set "AW_IMAGE=ghcr.io/alexdcolman/archive-workbench:0.89.0-rc84-cpu"
)
set "ARCHIVE_WORKBENCH_CPU_IMAGE=%AW_IMAGE%"

where docker >nul 2>&1
if errorlevel 1 (
  echo.
  echo Docker Desktop no esta instalado o el comando docker no esta disponible.
  echo Se abrira la pagina oficial de instalacion para Windows.
  start "" "https://docs.docker.com/desktop/setup/install/windows-install/"
  echo.
  echo Instala Docker Desktop, inicia la aplicacion y vuelve a abrir este archivo.
  pause
  exit /b 1
)

call :wait_docker
if errorlevel 1 exit /b 1

set "AW_SELECTED_PROJECT_HOST="
set "AW_SELECTED_PROJECT_CONTAINER="
set "AW_SELECTION_FILE=%TEMP%\archive_workbench_selection_%RANDOM%_%RANDOM%.txt"
powershell -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0docker\select-project-windows.ps1" > "%AW_SELECTION_FILE%"
set "AW_PICK_RESULT=%ERRORLEVEL%"
if "%AW_PICK_RESULT%"=="3" (
  del /q "%AW_SELECTION_FILE%" >nul 2>&1
  exit /b 0
)
if "%AW_PICK_RESULT%"=="2" goto :selection_done
if not "%AW_PICK_RESULT%"=="0" goto :selection_failed
set /p "AW_SELECTED_PROJECT_HOST="<"%AW_SELECTION_FILE%"
set "AW_SELECTED_PROJECT_CONTAINER=/selected-project"
del /q "%AW_SELECTION_FILE%" >nul 2>&1
echo.
for %%I in ("%AW_SELECTED_PROJECT_HOST%") do echo Proyecto elegido: %%~nxI
goto :selection_done

:selection_failed
del /q "%AW_SELECTION_FILE%" >nul 2>&1
echo.
echo No se pudo elegir el proyecto. Vuelve a abrir Archive Workbench e intentalo nuevamente.
pause
exit /b 1

:selection_done
if exist "%AW_SELECTION_FILE%" del /q "%AW_SELECTION_FILE%" >nul 2>&1
if not exist "ArchiveWorkbenchData\Projects" mkdir "ArchiveWorkbenchData\Projects"
if not exist "ArchiveWorkbenchData\Imports\Documents" mkdir "ArchiveWorkbenchData\Imports\Documents"
if not exist "ArchiveWorkbenchData\Imports\AudioVideo" mkdir "ArchiveWorkbenchData\Imports\AudioVideo"
if not exist "ArchiveWorkbenchData\Settings" mkdir "ArchiveWorkbenchData\Settings"

docker compose --profile cpu --profile gpu down >nul 2>&1

set "AW_PORT_FILE=%TEMP%\archive_workbench_port_%RANDOM%_%RANDOM%.txt"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0docker\windows-runtime.ps1" -Action SelectPort -PortFile "%AW_PORT_FILE%"
if errorlevel 1 goto :port_failed
set /p "AW_HOST_PORT="<"%AW_PORT_FILE%"
del /q "%AW_PORT_FILE%" >nul 2>&1
if not defined AW_HOST_PORT goto :port_failed

docker image inspect "%AW_IMAGE%" >nul 2>&1
if not errorlevel 1 goto :image_ready

echo.
echo Descargando la imagen CPU de Archive Workbench...
docker pull "%AW_IMAGE%"
if errorlevel 1 goto :pull_failed
goto :image_ready

:image_ready
echo.
echo Iniciando Archive Workbench...
docker compose --profile %AW_PROFILE% up -d --no-build %AW_SERVICE%
if errorlevel 1 goto :failed

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0docker\windows-runtime.ps1" -Action WaitReady -Port %AW_HOST_PORT% -Service %AW_SERVICE%
if errorlevel 1 goto :failed
start "" "http://127.0.0.1:%AW_HOST_PORT%"

echo.
echo Archive Workbench esta abierto en el navegador con la imagen CPU.
echo Podes cerrar esta ventana. Para detener Archive Workbench al terminar, usa la opcion Cerrar Archive Workbench dentro de la aplicacion.
exit /b 0

:wait_docker
docker info >nul 2>&1
if not errorlevel 1 exit /b 0

echo Docker Desktop esta instalado pero todavia no esta listo.
echo Intentando iniciarlo...
start "" "docker-desktop://"
for /L %%I in (1,1,60) do (
  timeout /t 2 /nobreak >nul
  docker info >nul 2>&1
  if not errorlevel 1 exit /b 0
)
echo.
echo No se pudo iniciar Docker Desktop. Abrilo manualmente y volve a intentar.
pause
exit /b 1

:pull_failed
echo.
echo No se pudo descargar la imagen CPU preparada de Archive Workbench.
echo Verifica la conexion a Internet y volve a intentar.
pause
exit /b 1

:failed
echo.
echo No se pudo iniciar Archive Workbench.
echo.
docker compose logs --tail=80 %AW_SERVICE%
echo.
echo Copia el texto de esta ventana si necesitas informar el error.
pause
exit /b 1
