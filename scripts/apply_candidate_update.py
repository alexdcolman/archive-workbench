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
LOCAL_ONLY_TOP_LEVEL = {
    ".git",
    ".venv",
    "venv",
    "pilot_data",
    "pilot_data_2",
    "ArchiveWorkbenchData",
}

PACKAGE_ONLY_TOP_LEVEL = {"delivery"}


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
    rules = payload.get("verified_root_residue_rules", [])
    if not isinstance(rules, list):
        raise RuntimeError("El manifiesto de actualización no contiene reglas de residuos válidas.")
    authorized = payload.get("authorized_local_archivals", [])
    if not isinstance(authorized, list):
        raise RuntimeError("El manifiesto de actualización no contiene archivos locales autorizados válidos.")
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



def preflight_authorized_local_archivals(target: Path, items: list[dict]) -> list[dict]:
    """Prepara movimientos locales exactos autorizados expresamente, sin globs ni borrado previo."""

    actions: list[dict] = []
    problems: list[str] = []
    for item in items:
        old_rel = Path(str(item.get("from") or ""))
        archive_rel = Path(str(item.get("archive_dir") or ""))
        if len(old_rel.parts) != 1 or not old_rel.name or any(ch in old_rel.name for ch in "*?[]"):
            problems.append(f"La ruta local autorizada debe ser un nombre exacto de raíz: {old_rel}")
            continue
        if not archive_rel.parts or archive_rel.is_absolute() or ".." in archive_rel.parts:
            problems.append(f"Destino histórico inválido para {old_rel}: {archive_rel}")
            continue
        if archive_rel.parts[:3] != (".assistant", "project_docs", "historico"):
            problems.append(f"El archivo local autorizado sólo puede archivarse bajo historico/: {archive_rel}")
            continue
        local_old = target / old_rel
        if not local_old.exists():
            continue
        if not local_old.is_file():
            problems.append(f"La ruta local autorizada existe pero no es un archivo: {old_rel}")
            continue
        actions.append({
            "from": old_rel,
            "archive_dir": archive_rel,
            "sha256": sha256_file(local_old),
        })
    if problems:
        raise RuntimeError("\n".join(problems))
    return actions


def preflight_verified_root_residues(
    source: Path, target: Path, rules: list[dict], *, excluded_names: set[str] | None = None
) -> list[dict]:
    """Reconcilia residuos documentales de raíz sólo si coinciden por SHA con copias históricas."""

    actions: list[dict] = []
    problems: list[str] = []
    excluded_names = excluded_names or set()
    for rule in rules:
        pattern = str(rule.get("pattern") or "")
        archive_rel = Path(str(rule.get("archive_dir") or ""))
        if not pattern or not archive_rel.parts:
            problems.append(f"Regla de residuo incompleta: {rule!r}")
            continue
        if "/" in pattern or "\\" in pattern:
            problems.append(f"El patrón de residuo debe limitarse a la raíz: {pattern!r}")
            continue
        archive_root = source / archive_rel
        if not archive_root.is_dir():
            problems.append(f"Falta el archivo histórico declarado para residuos: {archive_rel}")
            continue
        known_by_hash: dict[str, list[Path]] = {}
        for canonical in archive_root.rglob("*"):
            if canonical.is_file():
                known_by_hash.setdefault(sha256_file(canonical), []).append(canonical.relative_to(source))
        for local_old in sorted(target.glob(pattern)):
            if local_old.name in excluded_names:
                continue
            if not local_old.is_file():
                problems.append(f"La ruta residual existe pero no es un archivo: {local_old.name}")
                continue
            local_hash = sha256_file(local_old)
            matches = known_by_hash.get(local_hash, [])
            if not matches:
                problems.append(
                    f"No se tocará {local_old.name}: su contenido no coincide con ninguna copia histórica conocida."
                )
                continue
            canonical_rel = sorted(matches, key=lambda path: path.as_posix())[0]
            actions.append({
                "from": Path(local_old.name),
                "to": canonical_rel,
                "sha256": local_hash,
            })
    if problems:
        raise RuntimeError("\n".join(problems))
    return actions


def reconcile_verified_root_residues(target: Path, actions: list[dict]) -> None:
    for item in actions:
        old_path = target / item["from"]
        canonical_path = target / item["to"]
        expected = item["sha256"]
        if not canonical_path.is_file() or sha256_file(canonical_path) != expected:
            raise RuntimeError(
                f"No se retira {item['from']}: no se pudo verificar la copia histórica en {item['to']}."
            )
        if old_path.is_file() and sha256_file(old_path) == expected:
            old_path.unlink()
            print(f"Residuo documental verificado: {item['from']} -> {item['to']}")


def archive_authorized_local_files(target: Path, actions: list[dict]) -> None:
    for item in actions:
        old_path = target / item["from"]
        if not old_path.is_file():
            continue
        expected = item["sha256"]
        if sha256_file(old_path) != expected:
            raise RuntimeError(f"No se archivó {item['from']}: cambió después del preflight.")
        archive_root = target / item["archive_dir"]
        archive_root.mkdir(parents=True, exist_ok=True)
        destination = archive_root / old_path.name
        if destination.exists() and (not destination.is_file() or sha256_file(destination) != expected):
            destination = archive_root / f"{old_path.stem}.local-{expected[:12]}{old_path.suffix}"
        if not destination.exists():
            shutil.copy2(old_path, destination)
        if not destination.is_file() or sha256_file(destination) != expected:
            raise RuntimeError(f"No se pudo verificar la copia histórica local de {item['from']}.")
        old_path.unlink()
        print(f"Archivo local autorizado archivado: {item['from']} -> {destination.relative_to(target)} [sha256={expected}]")

def copy_candidate(source: Path, target: Path) -> None:
    for child in source.iterdir():
        if child.name in LOCAL_ONLY_TOP_LEVEL or child.name in PACKAGE_ONLY_TOP_LEVEL:
            continue
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

    for rel in (
        Path("docs/historico"),
        Path("docs/operativos"),
        Path("docs/referencia"),
        Path(".assistant/project_docs/operativos/WEB01_CAPTURAS"),
        Path(".assistant/project_docs/operativos/WEB01_SITIO"),
    ):
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
    authorized_actions = preflight_authorized_local_archivals(
        target, manifest.get("authorized_local_archivals", [])
    )
    residue_actions = preflight_verified_root_residues(
        source,
        target,
        manifest.get("verified_root_residue_rules", []),
        excluded_names={item["from"].name for item in authorized_actions},
    )
    print(f"Candidata: {manifest.get('candidate', 'sin identificar')}")
    print(f"Destino: {target}")
    print(f"Reubicaciones conocidas a reconciliar: {len(actions)}")
    print(f"Residuos documentales verificados a reconciliar: {len(residue_actions)}")
    print(f"Archivos locales autorizados a archivar: {len(authorized_actions)}")
    copy_candidate(source, target)
    reconcile_relocations(target, actions)
    reconcile_verified_root_residues(target, residue_actions)
    archive_authorized_local_files(target, authorized_actions)
    prune_known_empty_directories(target)
    print("Actualización aplicada. Sólo se archivaron además las rutas locales exactas autorizadas en el manifiesto.")


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
