$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$message = @"
Podés abrir un proyecto que ya existe en esta computadora o abrir el inicio para crear uno nuevo.

No elijas como proyecto de trabajo una carpeta que se esté sincronizando en vivo con Google Drive, OneDrive o Dropbox. Para trasladar un proyecto, descargalo o copialo primero a una carpeta local.

Sí = elegir un proyecto existente
No = abrir el inicio de Archive Workbench
Cancelar = salir
"@

$result = [System.Windows.Forms.MessageBox]::Show(
    $message,
    "Archive Workbench",
    [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
    [System.Windows.Forms.MessageBoxIcon]::Information,
    [System.Windows.Forms.MessageBoxDefaultButton]::Button1
)

if ($result -eq [System.Windows.Forms.DialogResult]::Cancel) { exit 3 }
if ($result -eq [System.Windows.Forms.DialogResult]::No) { exit 2 }

$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = "Elegí la carpeta principal del proyecto de Archive Workbench"
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 3 }

$selected = $dialog.SelectedPath
$decisions = Join-Path $selected "config\decisions.yaml"
if (-not (Test-Path -LiteralPath $decisions -PathType Leaf)) {
    [System.Windows.Forms.MessageBox]::Show(
        "La carpeta elegida no contiene un proyecto de Archive Workbench.`n`nElegí la carpeta principal del proyecto, la que contiene config\decisions.yaml.",
        "Archive Workbench",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 4
}

Write-Output $selected
exit 0
