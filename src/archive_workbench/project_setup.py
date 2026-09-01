from __future__ import annotations

from importlib import resources
from pathlib import Path
import re

import yaml

from archive_workbench.contracts.decisions import ProjectDecisions

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.catalog import ensure_project
from archive_workbench.decisions import load_decisions
from archive_workbench.identity import slugify
from archive_workbench.project_init import initialize_project


def bundled_template_root() -> Path:
    return Path(resources.files("archive_workbench") / "default_config")


def suggested_project_id(project_name: str) -> str:
    value = slugify(project_name.strip())
    return value or "nuevo_proyecto"


def _replace_scalar(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(?P<prefix>{re.escape(key)}:\s*).*$", re.MULTILINE)
    replacement = rf'\g<prefix>"{value.replace(chr(34), "")}"'
    if not pattern.search(text):
        raise ValueError(f"No se encontró {key} en decisions.yaml")
    return pattern.sub(replacement, text, count=1)


def update_project_identity(decisions_path: Path, *, project_name: str, project_id: str) -> None:
    clean_name = project_name.strip()
    clean_id = project_id.strip()
    if not clean_name:
        raise ValueError("El nombre del proyecto no puede quedar vacío")
    if not clean_id:
        raise ValueError("El identificador del proyecto no puede quedar vacío")
    text = decisions_path.read_text(encoding="utf-8")
    text = _replace_scalar(text, "project_name", clean_name)
    text = _replace_scalar(text, "project_id", clean_id)
    decisions_path.write_text(text, encoding="utf-8")


def create_ready_project(destination: Path, *, project_name: str, project_id: str) -> Path:
    root = initialize_project(destination, bundled_template_root(), allow_existing=False)
    update_project_identity(
        root / "config" / "decisions.yaml",
        project_name=project_name,
        project_id=project_id,
    )
    upgrade_database(root)
    decisions = load_decisions(root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            ensure_project(session, decisions)
    finally:
        engine.dispose()
    return root


def project_is_ready(project_root: Path) -> bool:
    return (
        (project_root / "config" / "decisions.yaml").is_file()
        and database_path(project_root).is_file()
        and current_revision(project_root) is not None
    )


def discover_projects(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    rows: list[Path] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if (child / "config" / "decisions.yaml").is_file():
            rows.append(child.resolve())
    return rows


def update_archival_parent_keys(decisions_path: Path, updates: dict[str, list[str]]) -> None:
    text = decisions_path.read_text(encoding="utf-8")
    for key, parent_keys in updates.items():
        pattern = re.compile(
            rf"(?ms)(^\s*-\s+key:\s*{re.escape(key)}\s*$.*?^\s+parent_keys:\s*)\[[^\]]*\]"
        )
        match = pattern.search(text)
        if match is None:
            raise ValueError(f"No se encontró la configuración jerárquica del nivel {key}")
        replacement = match.group(1) + "[" + ", ".join(parent_keys) + "]"
        text = text[: match.start()] + replacement + text[match.end() :]
    decisions_path.write_text(text, encoding="utf-8")


_COLLECTION_FIELD_KEYS = {
    "reference_code",
    "attributed_title",
    "extreme_dates",
    "extent",
    "scope_content",
    "archivist_note",
    "description_date",
}


def add_standard_collection_level(decisions_path: Path) -> bool:
    """Agrega el nivel estándar Colección a un proyecto existente sin tocar otras decisiones.

    La operación es explícita desde la interfaz. Colección se clasifica semánticamente como
    un conjunto documental construido. En el árbol configurable puede usar Archivo como
    contexto de custodia, sin afirmar que el repositorio sea un nivel interno de la colección.
    Documento puede quedar directamente bajo Colección y los campos descriptivos generales
    de conjuntos documentales también pasan a ser aplicables a Colección.
    """
    text = decisions_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError("decisions.yaml no contiene una configuración válida")
    levels = raw.get("archival_levels")
    if not isinstance(levels, list):
        raise ValueError("decisions.yaml no contiene la lista archival_levels")
    if any(isinstance(item, dict) and item.get("key") == "coleccion" for item in levels):
        return False

    keys = [str(item.get("key")) for item in levels if isinstance(item, dict)]
    if "archivo" not in keys:
        raise ValueError(
            "Para agregar Colección automáticamente, el proyecto debe tener habilitado el nivel Archivo."
        )

    order_by_key = {
        str(item.get("key")): int(item.get("display_order", 0))
        for item in levels
        if isinstance(item, dict) and item.get("key") is not None
    }
    anchor_key = "fondo" if "fondo" in order_by_key else "archivo"
    insert_order = order_by_key[anchor_key] + 1
    for item in levels:
        if isinstance(item, dict) and int(item.get("display_order", 0)) >= insert_order:
            item["display_order"] = int(item.get("display_order", 0)) + 1

    collection = {
        "key": "coleccion",
        "label": "Colección",
        "plural_label": "Colecciones",
        "display_order": insert_order,
        "parent_keys": ["archivo"],
        "required_fields": ["title"],
        "optional": True,
        "semantic_kind": "record_set",
        "record_set_type": "collection",
    }
    insertion_index = keys.index(anchor_key) + 1
    levels.insert(insertion_index, collection)

    for item in levels:
        if isinstance(item, dict) and item.get("key") == "documento":
            parents = [str(value) for value in item.get("parent_keys", [])]
            if "coleccion" not in parents:
                parents.append("coleccion")
            item["parent_keys"] = parents
            break

    fields = raw.get("descriptive_fields")
    if isinstance(fields, list):
        for item in fields:
            if not isinstance(item, dict) or item.get("key") not in _COLLECTION_FIELD_KEYS:
                continue
            applies = [str(value) for value in item.get("applies_to_levels", [])]
            if "all" not in applies and "coleccion" not in applies:
                applies.append("coleccion")
            item["applies_to_levels"] = applies

    ProjectDecisions.model_validate(raw)
    rendered = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=1000)
    decisions_path.write_text(rendered, encoding="utf-8")
    return True
