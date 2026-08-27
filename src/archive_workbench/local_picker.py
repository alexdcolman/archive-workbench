from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def choose_local_directory(
    initial: str | Path,
    *,
    title: str = "Elegir carpeta",
) -> tuple[Path | None, str | None]:
    """Abre el selector gráfico de carpetas cuando está disponible.

    Devuelve ``(ruta, None)`` al elegir una carpeta, ``(None, None)`` al cancelar
    y ``(None, mensaje)`` cuando el selector gráfico no está disponible o falla.
    """

    initial_path = Path(initial).expanduser().resolve()
    if not initial_path.is_dir():
        initial_path = initial_path.parent if initial_path.parent.is_dir() else Path.home()

    zenity = shutil.which("zenity")
    if zenity is None:
        return None, (
            "No se encontró el selector de carpetas del sistema. "
            "Podés escribir o pegar la ruta manualmente."
        )
    try:
        result = subprocess.run(
            [
                zenity,
                "--file-selection",
                "--directory",
                f"--title={title}",
                f"--filename={initial_path}/",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None, (
            "No se pudo abrir el selector de carpetas del sistema. "
            "Podés escribir o pegar la ruta manualmente."
        )
    if result.returncode == 1:
        return None, None
    if result.returncode != 0 or not result.stdout.strip():
        return None, (
            "No se pudo completar la selección de carpeta. "
            "Podés escribir o pegar la ruta manualmente."
        )
    return Path(result.stdout.strip()).expanduser().resolve(), None


def choose_local_files(
    initial: str | Path,
    *,
    title: str = "Elegir archivos",
    extensions: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[Path] | None, str | None]:
    """Abre el selector gráfico de archivos y permite elegir varios elementos.

    Devuelve ``(rutas, None)`` al elegir archivos, ``(None, None)`` al cancelar
    y ``(None, mensaje)`` cuando el selector gráfico no está disponible o falla.
    """

    initial_path = Path(initial).expanduser().resolve()
    if initial_path.is_file():
        initial_path = initial_path.parent
    elif not initial_path.is_dir():
        initial_path = initial_path.parent if initial_path.parent.is_dir() else Path.home()

    zenity = shutil.which("zenity")
    if zenity is None:
        return None, "No se encontró el selector de archivos del sistema."

    command = [
        zenity,
        "--file-selection",
        "--multiple",
        "--separator=\n",
        f"--title={title}",
        f"--filename={initial_path}/",
    ]
    if extensions:
        patterns = []
        for extension in extensions:
            cleaned = str(extension).strip().lower()
            if not cleaned:
                continue
            if not cleaned.startswith("."):
                cleaned = "." + cleaned
            patterns.append(f"*{cleaned}")
        if patterns:
            command.append("--file-filter=Audio y video | " + " ".join(sorted(set(patterns))))

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None, "No se pudo abrir el selector de archivos del sistema."
    if result.returncode == 1:
        return None, None
    if result.returncode != 0 or not result.stdout.strip():
        return None, "No se pudo completar la selección de archivos."

    selected: list[Path] = []
    seen: set[Path] = set()
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        candidate = Path(raw.strip()).expanduser().resolve()
        if candidate not in seen:
            seen.add(candidate)
            selected.append(candidate)
    if not selected:
        return None, None
    return selected, None
