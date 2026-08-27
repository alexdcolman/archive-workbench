from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class ManagedWorkspace:
    root: Path
    projects: Path
    document_imports: Path
    audiovisual_imports: Path
    settings: Path


def _environment_path(name: str) -> Path | None:
    value = str(os.environ.get(name, "")).strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def managed_workspace() -> ManagedWorkspace | None:
    """Devuelve el espacio de trabajo montado por una distribución administrada.

    La variable ARCHIVE_WORKBENCH_WORKSPACE_ROOT no se define en una instalación
    nativa. En contenedores permite que la interfaz trabaje con carpetas visibles
    desde Windows, macOS o Linux sin depender del selector gráfico del servidor.
    """

    root = _environment_path("ARCHIVE_WORKBENCH_WORKSPACE_ROOT")
    if root is None:
        return None
    projects = _environment_path("ARCHIVE_WORKBENCH_PROJECTS_ROOT") or root / "Projects"
    document_imports = (
        _environment_path("ARCHIVE_WORKBENCH_DOCUMENT_IMPORT_ROOT")
        or root / "Imports" / "Documents"
    )
    audiovisual_imports = (
        _environment_path("ARCHIVE_WORKBENCH_AUDIOVISUAL_IMPORT_ROOT")
        or root / "Imports" / "AudioVideo"
    )
    settings = _environment_path("ARCHIVE_WORKBENCH_SETTINGS_ROOT") or root / "Settings"
    return ManagedWorkspace(
        root=root,
        projects=projects,
        document_imports=document_imports,
        audiovisual_imports=audiovisual_imports,
        settings=settings,
    )



def managed_runtime_variant() -> Literal["cpu", "gpu"] | None:
    """Devuelve la variante de ejecución declarada por la distribución administrada."""

    value = str(os.environ.get("ARCHIVE_WORKBENCH_RUNTIME_VARIANT", "")).strip().casefold()
    if value == "cpu":
        return "cpu"
    if value == "gpu":
        return "gpu"
    return None

def workspace_display_path(path: str | Path) -> str:
    """Muestra una ruta administrada con el nombre que ve la persona en su equipo."""

    candidate = Path(path).expanduser().resolve()
    workspace = managed_workspace()
    if workspace is None:
        return str(candidate)
    try:
        relative = candidate.relative_to(workspace.root)
    except ValueError:
        return str(candidate)
    return (Path("ArchiveWorkbenchData") / relative).as_posix()
