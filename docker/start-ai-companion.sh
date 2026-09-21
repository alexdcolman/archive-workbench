#!/bin/sh
set -u

find_ai() {
  if [ -n "${ARCHIVE_WORKBENCH_AI_EXECUTABLE:-}" ] && [ -x "${ARCHIVE_WORKBENCH_AI_EXECUTABLE}" ]; then
    printf '%s\n' "$ARCHIVE_WORKBENCH_AI_EXECUTABLE"
    return 0
  fi

  case "$(uname -s 2>/dev/null || printf unknown)" in
    Darwin)
      for candidate in \
        "$HOME/Applications/Archive Workbench AI.app/Contents/MacOS/aw-ai" \
        "/Applications/Archive Workbench AI.app/Contents/MacOS/aw-ai"
      do
        if [ -x "$candidate" ]; then
          printf '%s\n' "$candidate"
          return 0
        fi
      done
      ;;
    *)
      data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
      candidate="$data_home/archive-workbench-ai/app/aw-ai"
      if [ -x "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
      fi
      ;;
  esac

  if command -v aw-ai >/dev/null 2>&1; then
    command -v aw-ai
    return 0
  fi
  return 1
}

AI_EXECUTABLE=$(find_ai) || {
  printf '%s\n' "Archive Workbench AI no está instalado; Archive Workbench abrirá sin análisis asistido local." >&2
  exit 2
}

AI_BRIDGE_ROOT=$("$AI_EXECUTABLE" bridge path 2>/dev/null) || {
  printf '%s\n' "Archive Workbench AI está instalado, pero no pudo resolver su carpeta de intercambio." >&2
  exit 3
}

if ! "$AI_EXECUTABLE" bridge start --root "$AI_BRIDGE_ROOT" >/dev/null 2>&1; then
  printf '%s\n' "Archive Workbench AI está instalado, pero su compañero local no pudo iniciarse." >&2
  exit 4
fi

printf '%s\n' "$AI_BRIDGE_ROOT"
