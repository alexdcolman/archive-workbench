#!/bin/sh
set -u

TITLE="Archive Workbench"
PROMPT="Podés abrir un proyecto que ya existe en esta computadora o abrir el inicio para crear uno nuevo.\n\nNo elijas como proyecto de trabajo una carpeta que se esté sincronizando en vivo con Google Drive, OneDrive o Dropbox. Para trasladar un proyecto, descargalo o copialo primero a una carpeta local."

choose_with_zenity() {
  choice=$(zenity --list \
    --title="$TITLE" \
    --text="$PROMPT" \
    --column="Qué querés hacer" \
    "Abrir un proyecto existente" \
    "Abrir el inicio de Archive Workbench" \
    --width=620 --height=300 2>/dev/null) || exit 3
  case "$choice" in
    "Abrir el inicio de Archive Workbench") exit 2 ;;
    "Abrir un proyecto existente") ;;
    *) exit 3 ;;
  esac
  selected=$(zenity --file-selection --directory \
    --title="Elegir la carpeta del proyecto" 2>/dev/null) || exit 3
  printf '%s\n' "$selected"
}

choose_with_kdialog() {
  choice=$(kdialog --menu "$PROMPT" \
    open "Abrir un proyecto existente" \
    home "Abrir el inicio de Archive Workbench" 2>/dev/null) || exit 3
  [ "$choice" = "home" ] && exit 2
  selected=$(kdialog --getexistingdirectory "$HOME" 2>/dev/null) || exit 3
  printf '%s\n' "$selected"
}

choose_in_terminal() {
  tty=/dev/tty
  if [ ! -r "$tty" ]; then
    printf '%s\n' "No hay un selector gráfico de carpetas disponible. Instalá zenity o kdialog y volvé a intentar." >&2
    exit 4
  fi
  printf '\n%s\n\n%s\n\n' "$TITLE" "$PROMPT" >"$tty"
  printf '%s\n' "1. Abrir un proyecto existente" "2. Abrir el inicio de Archive Workbench" "3. Salir" >"$tty"
  printf '%s' "Elegí 1, 2 o 3: " >"$tty"
  IFS= read -r choice <"$tty"
  case "$choice" in
    2) exit 2 ;;
    3) exit 3 ;;
    1) ;;
    *) exit 3 ;;
  esac
  printf '%s' "Escribí la ruta completa de la carpeta del proyecto: " >"$tty"
  IFS= read -r selected <"$tty"
  printf '%s\n' "$selected"
}

if command -v zenity >/dev/null 2>&1; then
  selected=$(choose_with_zenity) || exit $?
elif command -v kdialog >/dev/null 2>&1; then
  selected=$(choose_with_kdialog) || exit $?
else
  selected=$(choose_in_terminal) || exit $?
fi

selected=${selected%/}
if [ -z "$selected" ]; then
  exit 3
fi
if [ ! -f "$selected/config/decisions.yaml" ]; then
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title="$TITLE" \
      --text="La carpeta elegida no contiene un proyecto de Archive Workbench. Elegí la carpeta principal del proyecto, la que contiene config/decisions.yaml." 2>/dev/null || true
  elif command -v kdialog >/dev/null 2>&1; then
    kdialog --error "La carpeta elegida no contiene un proyecto de Archive Workbench. Elegí la carpeta principal del proyecto, la que contiene config/decisions.yaml." 2>/dev/null || true
  else
    printf '%s\n' "La carpeta elegida no contiene un proyecto de Archive Workbench." >&2
  fi
  exit 4
fi

printf '%s\n' "$selected"
