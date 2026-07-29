from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def iter_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSON inválido en {source}, línea {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Se esperaba un objeto JSON en {source}, línea {line_number}")
            yield value


def read_models(path: str | Path, model: type[ModelT]) -> list[ModelT]:
    return [model.model_validate(item) for item in iter_jsonl(path)]


def write_models_atomic(path: str | Path, models: Iterable[BaseModel]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            first = True
            for model in models:
                if not first:
                    handle.write("\n")
                handle.write(model.model_dump_json(exclude_none=True))
                first = False
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
