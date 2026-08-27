#!/bin/sh
set -eu

mkdir -p \
  /workspace/Projects \
  /workspace/Imports/Documents \
  /workspace/Imports/AudioVideo \
  /workspace/Settings

selected_project=${ARCHIVE_WORKBENCH_SELECTED_PROJECT_ROOT:-}
if [ -n "$selected_project" ]; then
  if [ ! -f "$selected_project/config/decisions.yaml" ]; then
    printf '%s\n' "La carpeta elegida no contiene un proyecto de Archive Workbench." >&2
    printf '%s\n' "Elegí la carpeta principal del proyecto, la que contiene config/decisions.yaml." >&2
    exit 64
  fi
  printf '%s\n' "Abriendo el proyecto elegido en esta computadora."
  exec archive-workbench review-app "$selected_project" --host 0.0.0.0 --port 8501 --no-browser
fi

exec archive-workbench review-app --host 0.0.0.0 --port 8501 --no-browser
