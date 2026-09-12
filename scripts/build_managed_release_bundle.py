from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIRNAME = "Archive Workbench"
ARCHIVE_NAME = "Archive-Workbench.zip"
CHECKSUM_NAME = f"{ARCHIVE_NAME}.sha256"

RUNTIME_FILES = (
    ".dockerignore",
    "Dockerfile",
    "Dockerfile.gpu",
    "compose.yaml",
    "FIRST_START.txt",
    "LICENSE",
    "NOTICE",
    "Start Archive Workbench - Windows.bat",
    "Start Archive Workbench - GPU - Windows.bat",
    "Stop Archive Workbench - Windows.bat",
    "Start Archive Workbench - macOS.command",
    "Stop Archive Workbench - macOS.command",
    "Start Archive Workbench - Linux.sh",
    "Start Archive Workbench - GPU - Linux.sh",
    "Stop Archive Workbench - Linux.sh",
    "docker/container-entrypoint.sh",
    "docker/select-project-linux.sh",
    "docker/select-project-macos.sh",
    "docker/select-project-windows.ps1",
    "docker/windows-runtime.ps1",
    "docker/image-tag.txt",
    "docker/gpu-image-tag.txt",
)


def _release_version() -> str:
    cpu = (ROOT / "docker" / "image-tag.txt").read_text(encoding="utf-8").strip()
    gpu = (ROOT / "docker" / "gpu-image-tag.txt").read_text(encoding="utf-8").strip()
    if not cpu.endswith("-cpu") or not gpu.endswith("-gpu"):
        raise SystemExit("Los tags de imagen administrada no usan los sufijos -cpu/-gpu esperados.")
    cpu_version = cpu.removesuffix("-cpu")
    gpu_version = gpu.removesuffix("-gpu")
    if cpu_version != gpu_version:
        raise SystemExit("Los tags CPU y GPU no corresponden a la misma versión.")
    return cpu_version


def _zip_info(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def _write_file(archive: zipfile.ZipFile, source: Path, arcname: str) -> None:
    mode = stat.S_IMODE(source.stat().st_mode)
    archive.writestr(_zip_info(arcname, mode), source.read_bytes())


def build(output_dir: Path, *, expected_release_tag: str | None = None) -> tuple[Path, Path]:
    version = _release_version()
    if expected_release_tag:
        expected = expected_release_tag.strip().removeprefix("v")
        if expected != version:
            raise SystemExit(
                f"El release solicitado es {expected_release_tag}, pero los launchers usan imágenes {version}."
            )

    missing = [relative for relative in RUNTIME_FILES if not (ROOT / relative).is_file()]
    if missing:
        raise SystemExit("Faltan archivos requeridos para la distribución: " + ", ".join(missing))

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / ARCHIVE_NAME
    checksum_path = output_dir / CHECKSUM_NAME

    with zipfile.ZipFile(archive_path, "w") as archive:
        version_text = (
            f"Archive Workbench {version}\n"
            f"Imagen CPU: {(ROOT / 'docker' / 'image-tag.txt').read_text(encoding='utf-8').strip()}\n"
            f"Imagen GPU: {(ROOT / 'docker' / 'gpu-image-tag.txt').read_text(encoding='utf-8').strip()}\n"
        )
        archive.writestr(
            _zip_info(f"{BUNDLE_DIRNAME}/VERSION.txt", 0o644),
            version_text.encode("utf-8"),
        )
        for relative in RUNTIME_FILES:
            source = ROOT / relative
            _write_file(archive, source, f"{BUNDLE_DIRNAME}/{relative}")

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  {ARCHIVE_NAME}\n", encoding="utf-8")
    return archive_path, checksum_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Construye el ZIP administrado que se adjunta a GitHub Releases."
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "release-assets")
    parser.add_argument("--release-tag", default=None)
    args = parser.parse_args()
    archive_path, checksum_path = build(
        args.output_dir,
        expected_release_tag=args.release_tag,
    )
    print(archive_path)
    print(checksum_path)


if __name__ == "__main__":
    main()
