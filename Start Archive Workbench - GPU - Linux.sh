#!/bin/sh
set -u
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
IMAGE="${ARCHIVE_WORKBENCH_GPU_IMAGE:-ghcr.io/alexdcolman/archive-workbench:0.89.0-rc84-gpu}"
export ARCHIVE_WORKBENCH_GPU_IMAGE="$IMAGE"

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' "Docker no está instalado. Instalá Docker Engine o Docker Desktop y volvé a ejecutar este archivo."
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' "Docker Compose no está disponible. Actualizá Docker y volvé a intentar."
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  printf '%s\n' "Docker está instalado pero todavía no está disponible. Abrí Docker y volvé a intentar."
  exit 1
fi

printf '%s\n' "Comprobando acceso de Docker a la placa NVIDIA..."
if ! docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi >/dev/null 2>&1; then
  printf '%s\n' "Docker no puede usar una placa NVIDIA en este equipo. Abrí Archive Workbench con el lanzador CPU o configurá NVIDIA Container Toolkit."
  exit 1
fi

AW_SELECTED_PROJECT_HOST=""
AW_SELECTED_PROJECT_CONTAINER=""
selected=$("$SCRIPT_DIR/docker/select-project-linux.sh")
selection_status=$?
case "$selection_status" in
  0)
    AW_SELECTED_PROJECT_HOST="$selected"
    AW_SELECTED_PROJECT_CONTAINER="/selected-project"
    export AW_SELECTED_PROJECT_HOST AW_SELECTED_PROJECT_CONTAINER
    printf '%s\n' "Proyecto elegido: $(basename -- "$selected")"
    ;;
  2)
    unset AW_SELECTED_PROJECT_HOST AW_SELECTED_PROJECT_CONTAINER
    ;;
  3)
    exit 0
    ;;
  *)
    printf '%s\n' "No se pudo elegir el proyecto. Volvé a abrir Archive Workbench e intentá nuevamente."
    exit 1
    ;;
esac

mkdir -p \
  ArchiveWorkbenchData/Projects \
  ArchiveWorkbenchData/Imports/Documents \
  ArchiveWorkbenchData/Imports/AudioVideo \
  ArchiveWorkbenchData/Settings
export AW_UID="$(id -u)"
export AW_GID="$(id -g)"

docker compose --profile cpu --profile gpu down >/dev/null 2>&1 || true

if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  printf '%s\n' "Usando la imagen GPU de Archive Workbench que ya está disponible en esta computadora."
else
  printf '%s\n' "Descargando la imagen GPU de Archive Workbench..."
  docker pull "$IMAGE" || { printf '%s\n' "No se pudo descargar la imagen. Revisá la conexión a Internet."; exit 1; }
fi

docker compose --profile gpu up -d --no-build app-gpu || exit 1

count=0
ready=0
while [ "$count" -lt 90 ]; do
  if docker compose --profile gpu exec -T app-gpu python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2).read()" >/dev/null 2>&1; then
    ready=1
    break
  fi
  count=$((count + 1))
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  printf '%s\n' "La aplicación no respondió después de iniciarse."
  docker compose logs --tail=80 app-gpu || true
  exit 1
fi

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost:8501" >/dev/null 2>&1 || true
fi
printf '%s\n' "Archive Workbench está disponible en http://localhost:8501 con acceso NVIDIA."
