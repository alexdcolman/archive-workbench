from __future__ import annotations

from pathlib import Path

import yaml

from archive_workbench.contracts.decisions import ProjectDecisions


def load_decisions(path: str | Path) -> ProjectDecisions:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError("El archivo de decisiones debe contener un objeto YAML")
    return ProjectDecisions.model_validate(raw)
