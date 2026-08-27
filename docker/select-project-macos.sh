#!/bin/bash
set -u

choice=$(osascript <<'APPLESCRIPT'
set messageText to "Podés abrir un proyecto que ya existe en esta Mac o abrir el inicio para crear uno nuevo.\n\nNo elijas como proyecto de trabajo una carpeta que se esté sincronizando en vivo con Google Drive, OneDrive, Dropbox o iCloud Drive. Para trasladar un proyecto, descargalo o copialo primero a una carpeta local."
try
    set answer to display dialog messageText with title "Archive Workbench" buttons {"Salir", "Abrir inicio", "Elegir proyecto"} default button "Elegir proyecto" cancel button "Salir"
    return button returned of answer
on error number -128
    return "Salir"
end try
APPLESCRIPT
) || exit 3

case "$choice" in
  "Abrir inicio") exit 2 ;;
  "Salir") exit 3 ;;
  "Elegir proyecto") ;;
  *) exit 3 ;;
esac

selected=$(osascript <<'APPLESCRIPT'
try
    set selectedFolder to choose folder with prompt "Elegí la carpeta principal del proyecto de Archive Workbench"
    return POSIX path of selectedFolder
on error number -128
    return ""
end try
APPLESCRIPT
) || exit 3
selected=${selected%/}
[ -n "$selected" ] || exit 3

if [ ! -f "$selected/config/decisions.yaml" ]; then
  osascript -e 'display alert "La carpeta elegida no contiene un proyecto de Archive Workbench" message "Elegí la carpeta principal del proyecto, la que contiene config/decisions.yaml." as critical' >/dev/null 2>&1 || true
  exit 4
fi

printf '%s\n' "$selected"
