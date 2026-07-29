from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5


def new_id() -> str:
    return str(uuid4())


def stable_id(namespace: UUID, *parts: object) -> str:
    normalized = "\x1f".join(str(part).strip() for part in parts)
    return str(uuid5(namespace, normalized))


def short_id(identifier: str, length: int = 8) -> str:
    compact = identifier.replace("-", "")
    if length < 4:
        raise ValueError("length debe ser >= 4")
    return compact[:length]


def sha256_file(path: str | Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def slugify(value: str, max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_value).strip("_").lower()
    slug = re.sub(r"_+", "_", slug)
    return (slug[:max_length].rstrip("_") or "sin_titulo")
