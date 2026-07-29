from __future__ import annotations

from pathlib import Path

import yaml

from archive_workbench.contracts.test_corpus import TestCorpus


def load_test_corpus(path: str | Path) -> TestCorpus:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError("El corpus de prueba debe contener un objeto YAML")
    return TestCorpus.model_validate(raw)
