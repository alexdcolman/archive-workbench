#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME="${SURYA_VENV:-$ROOT/.venv-surya}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
MODE="${1:-install}"

case "$MODE" in
  install|--dry-run) ;;
  *)
    echo "Uso: $0 [--dry-run]" >&2
    exit 2
    ;;
esac

if [[ ! -x "$RUNTIME/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$RUNTIME"
fi

PIP=("$RUNTIME/bin/python" -m pip)
TARGET="${ROOT}[surya]"

if [[ "$MODE" == "--dry-run" ]]; then
  "${PIP[@]}" install --dry-run -e "$TARGET"
  echo
  echo "Resolución compatible. No se instalaron paquetes."
  exit 0
fi

"${PIP[@]}" install --upgrade pip
"${PIP[@]}" install -e "$TARGET"
"${PIP[@]}" check

echo
echo "Runtime Surya instalado en: $RUNTIME"
echo "Ejecutable: $RUNTIME/bin/surya_ocr"
echo "El entorno principal de Archive Workbench no fue modificado."
