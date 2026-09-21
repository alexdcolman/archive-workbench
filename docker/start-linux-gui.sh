#!/bin/sh
set -u
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MODE="${1:-cpu}"
case "$MODE" in
  cpu) LAUNCHER="$SCRIPT_DIR/Start Archive Workbench - Linux.sh" ;;
  gpu) LAUNCHER="$SCRIPT_DIR/Start Archive Workbench - GPU - Linux.sh" ;;
  *) exit 2 ;;
esac
LOG_FILE=$(mktemp "${TMPDIR:-/tmp}/archive-workbench-start.XXXXXX") || exit 2
if "$LAUNCHER" >"$LOG_FILE" 2>&1; then
  rm -f "$LOG_FILE"
  exit 0
fi
DETAIL=$(tail -n 40 "$LOG_FILE")
rm -f "$LOG_FILE"
if command -v zenity >/dev/null 2>&1; then
  zenity --error --width=640 --title="Archive Workbench" \
    --text="No se pudo iniciar Archive Workbench.\n\n$DETAIL" >/dev/null 2>&1 || true
elif command -v xmessage >/dev/null 2>&1; then
  xmessage -center "No se pudo iniciar Archive Workbench.\n\n$DETAIL" >/dev/null 2>&1 || true
fi
exit 1
