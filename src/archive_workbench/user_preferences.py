from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path


PALETTES = {
    "system": "Sistema",
    "blue": "Azul",
    "forest": "Bosque",
    "terracotta": "Terracota",
    "violet": "Violeta",
}

# Los temas personalizados se aplican mediante la configuración nativa de Streamlit
# al iniciar el servidor. No se intenta retematizar widgets nativos con CSS inyectado:
# los portales (calendarios, menús, etc.) no exponen una API estable para eso.
STREAMLIT_THEME_PRESETS = {
    "blue": {
        "base": "light",
        "primaryColor": "#2F6DB2",
        "backgroundColor": "#F5F8FC",
        "secondaryBackgroundColor": "#E6EEF7",
        "textColor": "#172536",
        "borderColor": "#91A7BE",
    },
    "forest": {
        "base": "light",
        "primaryColor": "#3F6B52",
        "backgroundColor": "#F5F7F2",
        "secondaryBackgroundColor": "#E5EBE1",
        "textColor": "#203027",
        "borderColor": "#95A595",
    },
    "terracotta": {
        "base": "light",
        "primaryColor": "#9A573F",
        "backgroundColor": "#FBF6F1",
        "secondaryBackgroundColor": "#F0E4DB",
        "textColor": "#3B2922",
        "borderColor": "#B79A8B",
    },
    "violet": {
        "base": "light",
        "primaryColor": "#73558F",
        "backgroundColor": "#F8F5FA",
        "secondaryBackgroundColor": "#ECE5F1",
        "textColor": "#30263A",
        "borderColor": "#A695B4",
    },
}


def streamlit_theme_cli_args(palette: str) -> list[str]:
    """Devuelve opciones de Streamlit para aplicar un tema nativo al arrancar."""

    values = STREAMLIT_THEME_PRESETS.get(palette)
    if values is None:
        return []
    output: list[str] = []
    for name, value in values.items():
        output.extend([f"--theme.{name}", value])
    return output


@dataclass(slots=True)
class UserPreferences:
    actor: str = ""
    palette: str = "system"


def preferences_path() -> Path:
    override = str(os.environ.get("ARCHIVE_WORKBENCH_PREFERENCES_PATH", "")).strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".config" / "archive-workbench" / "preferences.json"


def load_user_preferences(path: Path | None = None) -> UserPreferences:
    target = path or preferences_path()
    if not target.is_file():
        return UserPreferences()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return UserPreferences()
    actor = str(payload.get("actor") or "").strip()
    palette = str(payload.get("palette") or "system")
    if palette not in PALETTES:
        palette = "system"
    return UserPreferences(actor=actor, palette=palette)


def save_user_preferences(preferences: UserPreferences, path: Path | None = None) -> Path:
    target = path or preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(preferences)
    payload["actor"] = preferences.actor.strip()
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
