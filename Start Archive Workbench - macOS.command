#!/bin/bash
set -u
cd "$(dirname "$0")"
IMAGE="${ARCHIVE_WORKBENCH_CPU_IMAGE:-ghcr.io/alexdcolman/archive-workbench:1.3.0-rc1-cpu@sha256:b255f97530b0a896395cc283e8744b6b3386bbfbe6ed7231642c2a9074abb3fb}"
export ARCHIVE_WORKBENCH_CPU_IMAGE="$IMAGE"

if ! command -v docker >/dev/null 2>&1; then
  echo
  echo "Docker Desktop no está instalado o el comando docker no está disponible."
  echo "Se abrirá la página oficial de instalación para macOS."
  open "https://docs.docker.com/desktop/setup/install/mac-install/"
  echo
  echo "Instalá Docker Desktop, abrilo y volvé a ejecutar este archivo."
  read -r -p "Presioná Enter para cerrar..."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Iniciando Docker Desktop..."
  open -a Docker >/dev/null 2>&1 || true
  for _ in $(seq 1 60); do
    sleep 2
    if docker info >/dev/null 2>&1; then break; fi
  done
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop no quedó disponible. Abrilo manualmente y volvé a intentar."
  read -r -p "Presioná Enter para cerrar..."
  exit 1
fi

AW_SELECTED_PROJECT_HOST=""
AW_SELECTED_PROJECT_CONTAINER=""
selected=$("$PWD/docker/select-project-macos.sh")
selection_status=$?
case "$selection_status" in
  0)
    AW_SELECTED_PROJECT_HOST="$selected"
    AW_SELECTED_PROJECT_CONTAINER="/selected-project"
    export AW_SELECTED_PROJECT_HOST AW_SELECTED_PROJECT_CONTAINER
    echo "Proyecto elegido: $(basename "$selected")"
    ;;
  2)
    unset AW_SELECTED_PROJECT_HOST AW_SELECTED_PROJECT_CONTAINER
    ;;
  3)
    exit 0
    ;;
  *)
    echo "No se pudo elegir el proyecto. Volvé a abrir Archive Workbench e intentá nuevamente."
    read -r -p "Presioná Enter para cerrar..."
    exit 1
    ;;
esac

mkdir -p \
  ArchiveWorkbenchData/Projects \
  ArchiveWorkbenchData/Imports/Documents \
  ArchiveWorkbenchData/Imports/AudioVideo \
  ArchiveWorkbenchData/Settings

FALLBACK_AI_BRIDGE_ROOT="$PWD/ArchiveWorkbenchData/Settings/archive-workbench-ai-bridge"
mkdir -p "$FALLBACK_AI_BRIDGE_ROOT"
if AI_BRIDGE_ROOT=$("$PWD/docker/start-ai-companion.sh"); then
  AW_AI_BRIDGE_HOST="$AI_BRIDGE_ROOT"
else
  AW_AI_BRIDGE_HOST="$FALLBACK_AI_BRIDGE_ROOT"
fi
export AW_AI_BRIDGE_HOST

docker compose --profile cpu --profile gpu down >/dev/null 2>&1 || true

if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Usando la imagen CPU de Archive Workbench que ya está disponible en esta Mac."
else
  echo
  echo "Descargando la imagen CPU de Archive Workbench..."
  if ! docker pull "$IMAGE"; then
    read -r -p "No se pudo descargar la imagen. Revisá la conexión a Internet y presioná Enter para cerrar..."
    exit 1
  fi
fi

docker compose --profile cpu up -d --no-build app-cpu || { read -r -p "No se pudo iniciar. Presioná Enter para cerrar..."; exit 1; }

ready=0
for _ in $(seq 1 90); do
  if curl -fsS --max-time 2 http://localhost:8501/_stcore/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "La aplicación no respondió después de iniciarse."
  docker compose logs --tail=80 app-cpu || true
  read -r -p "Presioná Enter para cerrar..."
  exit 1
fi
open "http://localhost:8501"

echo
echo "Archive Workbench está abierto en el navegador con la imagen CPU."
echo "Para detenerlo al terminar, usá Cerrar Archive Workbench dentro de la aplicación."
