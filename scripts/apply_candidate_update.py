#!/usr/bin/env python3
"""Apply an Archive Workbench candidate without leaving known moved files behind."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

MANIFEST_NAME = "candidate_update_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(source: Path) -> dict:
    path = source / "scripts" / MANIFEST_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError(f"Esquema de actualización no soportado: {payload.get('schema_version')!r}")
    if not isinstance(payload.get("relocations"), list):
        raise RuntimeError("El manifiesto de actualización no contiene relocations válidas.")
    return payload


def validate_roots(source: Path, target: Path) -> None:
    if not (source / "pyproject.toml").is_file():
        raise RuntimeError(f"La fuente no parece un paquete de Archive Workbench: {source}")
    if not (target / "pyproject.toml").is_file():
        raise RuntimeError(f"El destino no parece el repositorio de Archive Workbench: {target}")
    if source.resolve() == target.resolve():
        raise RuntimeError("La fuente y el destino de la actualización no pueden ser la misma carpeta.")


def preflight_relocations(source: Path, target: Path, relocations: list[dict]) -> list[dict]:
    actions: list[dict] = []
    problems: list[str] = []
    for item in relocations:
        old_rel = Path(item["from"])
        new_rel = Path(item["to"])
        old_expected = str(item.get("from_sha256") or item.get("sha256") or "")
        new_expected = str(item.get("to_sha256") or item.get("sha256") or "")
        if not old_expected or not new_expected:
            problems.append(f"La reubicación no declara huellas válidas: {old_rel} -> {new_rel}")
            continue
        package_new = source / new_rel
        if not package_new.is_file():
            problems.append(f"Falta en el paquete el destino esperado: {new_rel}")
            continue
        package_hash = sha256_file(package_new)
        if package_hash != new_expected:
            problems.append(
                f"La copia nueva del paquete no coincide con el SHA-256 declarado: {new_rel}"
            )
            continue
        local_old = target / old_rel
        if not local_old.exists():
            continue
        if not local_old.is_file():
            problems.append(f"La ruta obsoleta existe pero no es un archivo: {old_rel}")
            continue
        local_hash = sha256_file(local_old)
        if local_hash != old_expected:
            problems.append(
                f"No se tocará {old_rel}: su contenido local difiere de la copia conocida."
            )
            continue
        actions.append({
            "from": old_rel,
            "to": new_rel,
            "from_sha256": old_expected,
            "to_sha256": new_expected,
        })
    if problems:
        raise RuntimeError("\n".join(problems))
    return actions


def copy_candidate(source: Path, target: Path) -> None:
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir():
            shutil.copytree(child, destination, dirs_exist_ok=True, copy_function=shutil.copy2)
        else:
            shutil.copy2(child, destination)


def reconcile_relocations(target: Path, actions: list[dict]) -> None:
    for item in actions:
        old_path = target / item["from"]
        new_path = target / item["to"]
        old_expected = item["from_sha256"]
        new_expected = item["to_sha256"]
        if not new_path.is_file() or sha256_file(new_path) != new_expected:
            raise RuntimeError(
                f"No se retira {item['from']}: no se pudo verificar la copia histórica en {item['to']}."
            )
        if old_path.is_file() and sha256_file(old_path) == old_expected:
            old_path.unlink()
            print(f"Reubicación verificada: {item['from']} -> {item['to']}")


def prune_known_empty_directories(target: Path) -> None:
    """Retira sólo directorios obsoletos autorizados cuando ya quedaron vacíos."""

    for rel in (Path("docs/historico"), Path("docs/operativos"), Path("docs/referencia")):
        root = target / rel
        if not root.is_dir():
            continue
        for directory in sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            root.rmdir()
        except OSError:
            pass


def apply_update(source: Path, target: Path) -> None:
    validate_roots(source, target)
    manifest = load_manifest(source)
    actions = preflight_relocations(source, target, manifest["relocations"])
    print(f"Candidata: {manifest.get('candidate', 'sin identificar')}")
    print(f"Destino: {target}")
    print(f"Reubicaciones conocidas a reconciliar: {len(actions)}")
    copy_candidate(source, target)
    reconcile_relocations(target, actions)
    prune_known_empty_directories(target)
    print("Actualización aplicada. No se modificaron archivos locales ajenos al paquete ni otras rutas.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()
    try:
        apply_update(args.source.expanduser().resolve(), args.target.expanduser().resolve())
    except Exception as exc:  # diagnostic CLI: print the actual blocking reason
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
