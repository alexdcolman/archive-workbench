from __future__ import annotations

import hashlib
import json
import posixpath
import re
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.analysis_quality import (
    ANALYSIS_QUALITY_POLICY_VERSION,
    analysis_quality_scope,
    automatic_analysis_parameters_sha256,
)
from archive_workbench.db.models import (
    AutomaticAnalysisAuthorization,
    CorpusExportRun,
    EditablePage,
)

HANDOFF_PACKAGE_TYPE = "archive_workbench_ai_result_handoff"
HANDOFF_SCHEMA_VERSION = "0.1"
HANDOFF_PROTOCOL = "archive-workbench-ai/0.1"
SUPPORTED_EXP01_SCHEMA_VERSION = "1.1"
SUPPORTED_OUTPUT_SCHEMAS = frozenset({"vision_describe/0.1"})

HANDOFF_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
HANDOFF_MAX_MEMBERS = 4
HANDOFF_MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
HANDOFF_MAX_MANIFEST_BYTES = 1024 * 1024
HANDOFF_MAX_PROPOSALS_BYTES = 64 * 1024 * 1024
HANDOFF_MAX_JSONL_LINE_BYTES = 2 * 1024 * 1024
HANDOFF_MAX_PROPOSALS = 10_000

EXP01_MAX_MEMBERS = 100_000
EXP01_MAX_DECLARED_UNCOMPRESSED_BYTES = 100 * 1024 * 1024 * 1024
EXP01_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
EXP01_MAX_ASSET_BYTES = 512 * 1024 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_VISION_OUTPUT_KEYS = frozenset(
    {"description", "visible_text_notes", "document_features", "uncertainties"}
)


class AIHandoffError(ValueError):
    """Paquete de resultados AI inválido, inseguro o no soportado."""


@dataclass(frozen=True)
class AIHandoffProposal:
    proposal_id: str
    result_id: str
    request_id: str | None
    target_id: str
    target_type: str
    digital_object_id: str | None
    page_number: int | None
    source_key: str | None
    original_filename: str | None
    asset_path: str | None
    output_schema_id: str
    output: dict[str, Any]
    output_sha256: str
    warnings: tuple[str, ...]
    provenance: dict[str, Any]


@dataclass(frozen=True)
class AIHandoffPreview:
    sha256: str
    package_type: str
    schema_version: str
    protocol: str
    producer_id: str | None
    producer_version: str | None
    created_at: str | None
    request_id: str | None
    model_id: str | None
    model: dict[str, Any]
    runtime: dict[str, Any]
    prompt: dict[str, Any]
    exp01_sha256: str
    exp01_schema_version: str | None
    result_bundle_sha256: str
    proposal_count: int
    proposals: tuple[AIHandoffProposal, ...]
    automatic_apply: bool
    human_review_required: bool
    manifest: dict[str, Any]


@dataclass(frozen=True)
class AIHandoffAuthorizationEvidence:
    scope_key: str
    page_review_statuses: tuple[str, ...]
    broader_scope: bool
    parameters_sha256: str | None
    compatible_authorization_ids: tuple[str, ...]
    resolved_authorization_id: str | None


@dataclass(frozen=True)
class AIHandoffSourceMatch:
    export_run_id: str
    output_relative_path: str
    output_format: str
    output_sha256: str
    created_at: datetime
    materialization_status: str
    issue: str | None
    authorization: AIHandoffAuthorizationEvidence
    usable_for_incorporation: bool


@dataclass(frozen=True)
class AIHandoffProposalResolution:
    proposal_id: str
    editable_page_id: str | None
    target_status: str
    asset_status: str
    source_asset_sha256: str | None
    source_asset_path: str | None
    verified_export_run_ids: tuple[str, ...]
    acceptance_ready: bool
    issue: str | None


@dataclass(frozen=True)
class AIHandoffResolution:
    source_matches: tuple[AIHandoffSourceMatch, ...]
    proposal_resolutions: tuple[AIHandoffProposalResolution, ...]
    incorporation_allowed: bool
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedAIHandoffAsset:
    proposal_id: str
    path: str
    sha256: str
    byte_size: int
    mime_type: str | None
    width: int | None
    height: int | None
    payload: bytes


@dataclass(frozen=True)
class _VerifiedExp01:
    export_run_id: str
    path: Path
    manifest: dict[str, Any]
    asset_by_id: dict[str, dict[str, Any]]
    info_by_name: dict[str, zipfile.ZipInfo]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(name: str) -> bool:
    if not name or "\\" in name:
        return False
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        return False
    normalized = posixpath.normpath(name)
    return normalized not in {"", ".", ".."} and not normalized.startswith("../")


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return bool(mode and stat.S_ISLNK(mode))


def _validate_zip_infos(
    infos: list[zipfile.ZipInfo],
    *,
    label: str,
    max_members: int,
    max_uncompressed: int,
) -> dict[str, zipfile.ZipInfo]:
    if not infos:
        raise AIHandoffError(f"{label} está vacío")
    if len(infos) > max_members:
        raise AIHandoffError(f"{label} supera el límite de miembros permitido")
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise AIHandoffError(f"{label} contiene miembros duplicados")
    total_uncompressed = 0
    by_name: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        name = info.filename
        if not _safe_member(name):
            raise AIHandoffError(f"{label} contiene rutas internas inseguras")
        if info.is_dir() or _is_symlink(info):
            raise AIHandoffError(f"{label} contiene miembros no regulares")
        if info.flag_bits & 0x1:
            raise AIHandoffError(f"{label} contiene miembros cifrados no soportados")
        if info.compress_type not in _ALLOWED_COMPRESSION:
            raise AIHandoffError(f"{label} usa un método de compresión no soportado")
        total_uncompressed += info.file_size
        if total_uncompressed > max_uncompressed:
            raise AIHandoffError(f"{label} supera el tamaño descomprimido permitido")
        by_name[name] = info
    return by_name


def _read_member_limited(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    label: str,
    max_bytes: int,
) -> bytes:
    if info.file_size > max_bytes:
        raise AIHandoffError(f"{label} supera el tamaño permitido")
    payload = bytearray()
    with archive.open(info, "r") as handle:
        while True:
            chunk = handle.read(min(1024 * 1024, max_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > max_bytes:
                raise AIHandoffError(f"{label} supera el tamaño permitido")
    if len(payload) != info.file_size:
        raise AIHandoffError(f"{label} no pudo leerse de forma íntegra")
    return bytes(payload)


def _hash_member_limited(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    label: str,
    max_bytes: int,
) -> str:
    if info.file_size > max_bytes:
        raise AIHandoffError(f"{label} supera el tamaño permitido")
    digest = hashlib.sha256()
    read_bytes = 0
    with archive.open(info, "r") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            read_bytes += len(chunk)
            if read_bytes > max_bytes:
                raise AIHandoffError(f"{label} supera el tamaño permitido")
            digest.update(chunk)
    if read_bytes != info.file_size:
        raise AIHandoffError(f"{label} no pudo leerse de forma íntegra")
    return digest.hexdigest()


def _require_dict(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AIHandoffError(f"{label} debe ser un objeto JSON")
    return value


def _optional_dict(value: object, *, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    return dict(_require_dict(value, label=label))


def _require_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AIHandoffError(f"{label} debe ser un texto no vacío")
    return value


def _require_sha256(value: object, *, label: str) -> str:
    text = _require_string(value, label=label).lower()
    if not _SHA256_RE.fullmatch(text):
        raise AIHandoffError(f"{label} no es una huella SHA-256 válida")
    return text


def _load_json(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AIHandoffError(f"{label} no contiene JSON UTF-8 válido") from exc
    return _require_dict(value, label=label)


def _load_jsonl(payload: bytes, *, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(payload.splitlines(), start=1):
        if len(raw_line) > HANDOFF_MAX_JSONL_LINE_BYTES:
            raise AIHandoffError(f"{label} supera el límite de longitud en la línea {line_number}")
        if not raw_line.strip():
            continue
        if len(rows) >= HANDOFF_MAX_PROPOSALS:
            raise AIHandoffError(f"{label} supera el límite de propuestas permitido")
        try:
            line = raw_line.decode("utf-8")
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIHandoffError(
                f"{label} contiene JSON inválido en la línea {line_number}"
            ) from exc
        rows.append(_require_dict(value, label=f"{label}, línea {line_number}"))
    return rows


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _validate_vision_output(output: dict[str, Any], *, proposal_id: str) -> None:
    if set(output) != _VISION_OUTPUT_KEYS:
        raise AIHandoffError(f"{proposal_id}.output no cumple el schema vision_describe/0.1")
    if not isinstance(output.get("description"), str):
        raise AIHandoffError(f"{proposal_id}.output.description debe ser texto")
    for field in ("visible_text_notes", "document_features", "uncertainties"):
        value = output.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise AIHandoffError(f"{proposal_id}.output.{field} debe ser una lista de textos")


def _proposal_from_row(
    row: dict[str, Any],
    *,
    manifest_request_id: str | None,
    source_exp01_sha256: str,
    source_result_bundle_sha256: str,
) -> AIHandoffProposal:
    proposal_id = _require_string(row.get("proposal_id"), label="proposal_id")
    result_id = _require_string(row.get("result_id"), label=f"{proposal_id}.result_id")
    target_id = _require_string(row.get("target_id"), label=f"{proposal_id}.target_id")
    target_type = _require_string(row.get("target_type"), label=f"{proposal_id}.target_type")
    if target_type not in {"page", "region", "figure"}:
        raise AIHandoffError(f"{proposal_id}.target_type no está soportado: {target_type}")
    output_schema_id = _require_string(
        row.get("output_schema_id"), label=f"{proposal_id}.output_schema_id"
    )
    if output_schema_id not in SUPPORTED_OUTPUT_SCHEMAS:
        raise AIHandoffError(
            f"{proposal_id}.output_schema_id no está soportado: {output_schema_id}"
        )
    output = _require_dict(row.get("output"), label=f"{proposal_id}.output")
    if output_schema_id == "vision_describe/0.1":
        _validate_vision_output(output, proposal_id=proposal_id)
    provenance = _require_dict(row.get("provenance"), label=f"{proposal_id}.provenance")
    proposal_exp01 = _require_sha256(
        provenance.get("exp01_sha256"), label=f"{proposal_id}.provenance.exp01_sha256"
    )
    proposal_result = _require_sha256(
        provenance.get("result_bundle_sha256"),
        label=f"{proposal_id}.provenance.result_bundle_sha256",
    )
    if proposal_exp01 != source_exp01_sha256:
        raise AIHandoffError(f"{proposal_id} no corresponde al EXP-01 declarado por el handoff")
    if proposal_result != source_result_bundle_sha256:
        raise AIHandoffError(
            f"{proposal_id} no corresponde al result bundle declarado por el handoff"
        )

    request_id = _optional_string(row.get("request_id"))
    if manifest_request_id is not None and request_id != manifest_request_id:
        raise AIHandoffError(f"{proposal_id}.request_id no coincide con el manifest")

    page_number = row.get("page_number")
    if page_number is not None and (not isinstance(page_number, int) or page_number < 1):
        raise AIHandoffError(f"{proposal_id}.page_number debe ser un entero positivo o null")

    asset_path = _optional_string(row.get("asset_path"))
    if asset_path is not None and not _safe_member(asset_path):
        raise AIHandoffError(f"{proposal_id}.asset_path contiene una ruta insegura")

    digital_object_id = _optional_string(row.get("digital_object_id"))
    if target_type == "page" and (digital_object_id is None or page_number is None):
        raise AIHandoffError(
            f"{proposal_id} no conserva digital_object_id + page_number para el target de página"
        )
    if target_type == "page" and asset_path is None:
        raise AIHandoffError(f"{proposal_id} no conserva asset_path para el target de página")

    warnings_value = row.get("warnings", [])
    if not isinstance(warnings_value, list) or any(
        not isinstance(item, str) for item in warnings_value
    ):
        raise AIHandoffError(f"{proposal_id}.warnings debe ser una lista de textos")

    return AIHandoffProposal(
        proposal_id=proposal_id,
        result_id=result_id,
        request_id=request_id,
        target_id=target_id,
        target_type=target_type,
        digital_object_id=digital_object_id,
        page_number=page_number,
        source_key=_optional_string(row.get("source_key")),
        original_filename=_optional_string(row.get("original_filename")),
        asset_path=asset_path,
        output_schema_id=output_schema_id,
        output=dict(output),
        output_sha256=_canonical_json_sha256(output),
        warnings=tuple(warnings_value),
        provenance=dict(provenance),
    )


def inspect_ai_handoff_bytes(payload: bytes) -> AIHandoffPreview:
    """Valida y lee un handoff 0.1 sin escribir en el proyecto."""

    if not payload:
        raise AIHandoffError("El paquete AI está vacío")
    if len(payload) > HANDOFF_MAX_ARCHIVE_BYTES:
        raise AIHandoffError("El paquete AI supera el tamaño comprimido permitido")
    package_sha256 = _sha256_bytes(payload)
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            info_by_name = _validate_zip_infos(
                archive.infolist(),
                label="El paquete AI",
                max_members=HANDOFF_MAX_MEMBERS,
                max_uncompressed=HANDOFF_MAX_UNCOMPRESSED_BYTES,
            )
            manifest_info = info_by_name.get("manifest.json")
            if manifest_info is None:
                raise AIHandoffError("El paquete AI no contiene manifest.json")
            manifest = _load_json(
                _read_member_limited(
                    archive,
                    manifest_info,
                    label="manifest.json",
                    max_bytes=HANDOFF_MAX_MANIFEST_BYTES,
                ),
                label="manifest.json",
            )

            if manifest.get("package_type") != HANDOFF_PACKAGE_TYPE:
                raise AIHandoffError("El ZIP no es un handoff de resultados AI soportado")
            if manifest.get("schema_version") != HANDOFF_SCHEMA_VERSION:
                raise AIHandoffError("La versión del schema de handoff no está soportada")
            if manifest.get("protocol") != HANDOFF_PROTOCOL:
                raise AIHandoffError("El protocolo del handoff no está soportado")

            producer = _require_dict(manifest.get("producer"), label="manifest.producer")
            producer_id = _require_string(producer.get("id"), label="manifest.producer.id")
            producer_version = _require_string(
                producer.get("version"), label="manifest.producer.version"
            )
            policy = _require_dict(manifest.get("policy"), label="manifest.policy")
            if policy.get("application") != "proposed_only":
                raise AIHandoffError("El handoff no declara application=proposed_only")
            if policy.get("automatic_apply") is not False:
                raise AIHandoffError(
                    "Archive Workbench no acepta handoffs con aplicación automática"
                )
            if policy.get("human_review_required") is not True:
                raise AIHandoffError("El handoff debe requerir revisión humana")

            source = _require_dict(manifest.get("source"), label="manifest.source")
            source_exp01_sha256 = _require_sha256(
                source.get("exp01_sha256"), label="manifest.source.exp01_sha256"
            )
            source_result_bundle_sha256 = _require_sha256(
                source.get("result_bundle_sha256"),
                label="manifest.source.result_bundle_sha256",
            )
            exp01_schema_version = _optional_string(source.get("exp01_schema_version"))
            if (
                exp01_schema_version is not None
                and exp01_schema_version != SUPPORTED_EXP01_SCHEMA_VERSION
            ):
                raise AIHandoffError("La versión EXP-01 declarada por el handoff no está soportada")

            proposals_path = _require_string(
                manifest.get("proposals_path"), label="manifest.proposals_path"
            )
            if not _safe_member(proposals_path) or proposals_path == "manifest.json":
                raise AIHandoffError("manifest.proposals_path no es una ruta segura")
            allowed_members = {"manifest.json", proposals_path}
            if set(info_by_name) != allowed_members:
                raise AIHandoffError("El handoff contiene miembros fuera de la allowlist 0.1")
            proposals_info = info_by_name.get(proposals_path)
            if proposals_info is None:
                raise AIHandoffError("El handoff no contiene el archivo de propuestas declarado")
            proposals_payload = _read_member_limited(
                archive,
                proposals_info,
                label=proposals_path,
                max_bytes=HANDOFF_MAX_PROPOSALS_BYTES,
            )
            expected_proposals_sha256 = _require_sha256(
                manifest.get("proposals_sha256"), label="manifest.proposals_sha256"
            )
            if _sha256_bytes(proposals_payload) != expected_proposals_sha256:
                raise AIHandoffError("La huella SHA-256 del archivo de propuestas no coincide")

            rows = _load_jsonl(proposals_payload, label=proposals_path)
            proposal_count = manifest.get("proposal_count")
            if not isinstance(proposal_count, int) or proposal_count < 1:
                raise AIHandoffError("manifest.proposal_count debe ser un entero positivo")
            if proposal_count > HANDOFF_MAX_PROPOSALS:
                raise AIHandoffError("manifest.proposal_count supera el límite permitido")
            if proposal_count != len(rows):
                raise AIHandoffError("manifest.proposal_count no coincide con las propuestas")

            request_id = _optional_string(manifest.get("request_id"))
            proposals = tuple(
                _proposal_from_row(
                    row,
                    manifest_request_id=request_id,
                    source_exp01_sha256=source_exp01_sha256,
                    source_result_bundle_sha256=source_result_bundle_sha256,
                )
                for row in rows
            )
            proposal_ids = [row.proposal_id for row in proposals]
            if len(set(proposal_ids)) != len(proposal_ids):
                raise AIHandoffError("El handoff contiene proposal_id duplicados")
            result_ids = [row.result_id for row in proposals]
            if len(set(result_ids)) != len(result_ids):
                raise AIHandoffError("El handoff contiene result_id duplicados")

            model = _optional_dict(manifest.get("model"), label="manifest.model")
            runtime = _optional_dict(manifest.get("runtime"), label="manifest.runtime")
            prompt = _optional_dict(manifest.get("prompt"), label="manifest.prompt")
            return AIHandoffPreview(
                sha256=package_sha256,
                package_type=HANDOFF_PACKAGE_TYPE,
                schema_version=HANDOFF_SCHEMA_VERSION,
                protocol=HANDOFF_PROTOCOL,
                producer_id=producer_id,
                producer_version=producer_version,
                created_at=_optional_string(manifest.get("created_at")),
                request_id=request_id,
                model_id=_optional_string(model.get("model_id")),
                model=model,
                runtime=runtime,
                prompt=prompt,
                exp01_sha256=source_exp01_sha256,
                exp01_schema_version=exp01_schema_version,
                result_bundle_sha256=source_result_bundle_sha256,
                proposal_count=len(proposals),
                proposals=proposals,
                automatic_apply=False,
                human_review_required=True,
                manifest=dict(manifest),
            )
    except zipfile.BadZipFile as exc:
        raise AIHandoffError("El paquete AI no es un ZIP válido") from exc


def _project_file(project_root: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise AIHandoffError("La exportación de origen registra una ruta inválida")
    root = project_root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AIHandoffError("La exportación de origen sale de la carpeta del proyecto") from exc
    return candidate


def _profile_parameters_from_run(run: CorpusExportRun) -> tuple[dict[str, Any], tuple[str, ...]]:
    snapshot = dict(run.profile_snapshot_json or {})
    statuses_raw = snapshot.get("include_page_review_statuses")
    statuses = (
        tuple(str(value) for value in statuses_raw) if isinstance(statuses_raw, list) else tuple()
    )
    for key in ("id", "revision", "execution_scope", "execution"):
        snapshot.pop(key, None)
    return snapshot, statuses


def _authorization_evidence(
    session: Session,
    *,
    project_id: str,
    run: CorpusExportRun,
) -> AIHandoffAuthorizationEvidence:
    parameters, statuses = _profile_parameters_from_run(run)
    scope = analysis_quality_scope(statuses)
    parameters_sha256 = automatic_analysis_parameters_sha256(parameters)
    snapshot = dict(run.profile_snapshot_json or {})
    profile_id = snapshot.get("id")
    if not isinstance(profile_id, str) or not profile_id:
        return AIHandoffAuthorizationEvidence(
            scope_key=scope.key,
            page_review_statuses=scope.page_review_statuses,
            broader_scope=scope.is_broader_than_default,
            parameters_sha256=parameters_sha256,
            compatible_authorization_ids=(),
            resolved_authorization_id=None,
        )
    rows = session.scalars(
        select(AutomaticAnalysisAuthorization)
        .where(
            AutomaticAnalysisAuthorization.project_id == project_id,
            AutomaticAnalysisAuthorization.policy_version == ANALYSIS_QUALITY_POLICY_VERSION,
            AutomaticAnalysisAuthorization.analysis_kind == "corpus_export",
            AutomaticAnalysisAuthorization.target_type == "corpus_export_profile",
            AutomaticAnalysisAuthorization.target_id == profile_id,
            AutomaticAnalysisAuthorization.parameters_sha256 == parameters_sha256,
            AutomaticAnalysisAuthorization.created_at <= run.created_at,
        )
        .order_by(
            AutomaticAnalysisAuthorization.created_at.desc(),
            AutomaticAnalysisAuthorization.id.desc(),
        )
    ).all()
    compatible = tuple(
        row.id
        for row in rows
        if tuple(row.page_review_statuses_json or ()) == scope.page_review_statuses
    )
    return AIHandoffAuthorizationEvidence(
        scope_key=scope.key,
        page_review_statuses=scope.page_review_statuses,
        broader_scope=scope.is_broader_than_default,
        parameters_sha256=parameters_sha256,
        compatible_authorization_ids=compatible,
        resolved_authorization_id=compatible[0] if len(compatible) == 1 else None,
    )


def _normalized_run_profile_snapshot(run: CorpusExportRun) -> dict[str, Any]:
    snapshot = dict(run.profile_snapshot_json or {})
    snapshot.pop("execution", None)
    return snapshot


def _inspect_exp01_run(
    *,
    project_root: Path,
    project_id: str,
    run: CorpusExportRun,
    expected_sha256: str,
) -> _VerifiedExp01:
    if run.output_format != "visual_zip":
        raise AIHandoffError("La corrida local coincidente no es una exportación visual")
    path = _project_file(project_root, run.output_relative_path)
    if not path.is_file():
        raise AIHandoffError("El EXP-01 registrado ya no está disponible")
    if path.stat().st_size != run.byte_size:
        raise AIHandoffError("El tamaño actual del EXP-01 no coincide con la corrida registrada")
    digest = _sha256_path(path)
    if digest != expected_sha256 or digest != run.output_sha256:
        raise AIHandoffError("La huella SHA-256 actual del EXP-01 no coincide")
    try:
        with zipfile.ZipFile(path) as archive:
            info_by_name = _validate_zip_infos(
                archive.infolist(),
                label="EXP-01",
                max_members=EXP01_MAX_MEMBERS,
                max_uncompressed=EXP01_MAX_DECLARED_UNCOMPRESSED_BYTES,
            )
            manifest_info = info_by_name.get("manifest.json")
            if manifest_info is None:
                raise AIHandoffError("EXP-01 no contiene manifest.json")
            manifest = _load_json(
                _read_member_limited(
                    archive,
                    manifest_info,
                    label="manifest.json de EXP-01",
                    max_bytes=EXP01_MAX_MANIFEST_BYTES,
                ),
                label="manifest.json de EXP-01",
            )
    except zipfile.BadZipFile as exc:
        raise AIHandoffError("El EXP-01 registrado no es un ZIP válido") from exc

    if manifest.get("package_type") != "archive_workbench_text_and_images":
        raise AIHandoffError("La exportación local coincidente no es un EXP-01 soportado")
    if manifest.get("schema_version") != SUPPORTED_EXP01_SCHEMA_VERSION:
        raise AIHandoffError("El EXP-01 local usa un schema no soportado")
    if manifest.get("project_id") != project_id:
        raise AIHandoffError("El EXP-01 local pertenece a otro proyecto")
    if manifest.get("corpus_state_sha256") != run.corpus_state_sha256:
        raise AIHandoffError("El estado de corpus del EXP-01 no coincide con la corrida registrada")
    manifest_profile = manifest.get("profile")
    if not isinstance(manifest_profile, dict):
        raise AIHandoffError("EXP-01 no conserva el snapshot del perfil")
    if manifest_profile != _normalized_run_profile_snapshot(run):
        raise AIHandoffError("El snapshot del perfil EXP-01 no coincide con la corrida registrada")

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise AIHandoffError("EXP-01 no declara una lista de assets válida")
    asset_by_id: dict[str, dict[str, Any]] = {}
    seen_paths: set[str] = set()
    for raw_asset in assets:
        asset = _require_dict(raw_asset, label="EXP-01 asset")
        asset_id = _require_string(asset.get("asset_id"), label="EXP-01 asset.asset_id")
        asset_path = _require_string(asset.get("path"), label=f"EXP-01 {asset_id}.path")
        if asset_id in asset_by_id:
            raise AIHandoffError("EXP-01 contiene asset_id duplicados")
        if asset_path in seen_paths:
            raise AIHandoffError("EXP-01 contiene rutas de asset duplicadas")
        if not _safe_member(asset_path):
            raise AIHandoffError("EXP-01 contiene una ruta de asset insegura")
        info = info_by_name.get(asset_path)
        if info is None:
            raise AIHandoffError(f"EXP-01 no contiene el asset declarado {asset_path}")
        asset_sha = _require_sha256(asset.get("sha256"), label=f"EXP-01 {asset_id}.sha256")
        byte_size = asset.get("byte_size")
        if not isinstance(byte_size, int) or byte_size < 0 or byte_size != info.file_size:
            raise AIHandoffError(f"EXP-01 {asset_id}.byte_size no coincide con el ZIP")
        if info.file_size > EXP01_MAX_ASSET_BYTES:
            raise AIHandoffError(f"EXP-01 {asset_id} supera el tamaño de asset permitido")
        asset_by_id[asset_id] = {**asset, "sha256": asset_sha}
        seen_paths.add(asset_path)

    return _VerifiedExp01(
        export_run_id=run.id,
        path=path,
        manifest=manifest,
        asset_by_id=asset_by_id,
        info_by_name=info_by_name,
    )


def _verify_proposal_asset(
    source: _VerifiedExp01,
    proposal: AIHandoffProposal,
) -> tuple[str, str]:
    asset = source.asset_by_id.get(proposal.target_id)
    if asset is None:
        raise AIHandoffError(f"EXP-01 no contiene el target {proposal.target_id}")
    asset_path = _require_string(asset.get("path"), label=f"{proposal.target_id}.path")
    if proposal.asset_path != asset_path:
        raise AIHandoffError(f"{proposal.proposal_id}.asset_path no coincide con EXP-01")
    if asset.get("kind") != proposal.target_type:
        raise AIHandoffError(f"{proposal.proposal_id}.target_type no coincide con EXP-01")
    if asset.get("digital_object_id") != proposal.digital_object_id:
        raise AIHandoffError(f"{proposal.proposal_id}.digital_object_id no coincide con EXP-01")
    if asset.get("page_number") != proposal.page_number:
        raise AIHandoffError(f"{proposal.proposal_id}.page_number no coincide con EXP-01")
    asset_sha = _require_sha256(asset.get("sha256"), label=f"EXP-01 {proposal.target_id}.sha256")
    with zipfile.ZipFile(source.path) as archive:
        info = archive.getinfo(asset_path)
        actual_sha = _hash_member_limited(
            archive,
            info,
            label=f"asset {proposal.target_id}",
            max_bytes=EXP01_MAX_ASSET_BYTES,
        )
    if actual_sha != asset_sha:
        raise AIHandoffError(f"El asset {proposal.target_id} no coincide con su SHA-256 EXP-01")
    return asset_path, asset_sha


def resolve_ai_handoff(
    session: Session,
    *,
    project_root: Path,
    project_id: str,
    preview: AIHandoffPreview,
) -> AIHandoffResolution:
    """Resuelve procedencia, autorización, targets y assets exactos sin persistir nada."""

    runs = session.scalars(
        select(CorpusExportRun)
        .where(
            CorpusExportRun.project_id == project_id,
            CorpusExportRun.output_sha256 == preview.exp01_sha256,
        )
        .order_by(CorpusExportRun.created_at.desc(), CorpusExportRun.id.desc())
    ).all()

    verified_sources: list[_VerifiedExp01] = []
    source_matches: list[AIHandoffSourceMatch] = []
    for run in runs:
        authorization = _authorization_evidence(
            session,
            project_id=project_id,
            run=run,
        )
        status = "verified"
        issue: str | None = None
        source: _VerifiedExp01 | None = None
        try:
            source = _inspect_exp01_run(
                project_root=project_root,
                project_id=project_id,
                run=run,
                expected_sha256=preview.exp01_sha256,
            )
        except (AIHandoffError, OSError) as exc:
            status = "unavailable"
            issue = str(exc)
        authorization_ok = bool(authorization.compatible_authorization_ids)
        if source is not None:
            verified_sources.append(source)
        source_matches.append(
            AIHandoffSourceMatch(
                export_run_id=run.id,
                output_relative_path=run.output_relative_path,
                output_format=run.output_format,
                output_sha256=run.output_sha256,
                created_at=run.created_at,
                materialization_status=status,
                issue=issue,
                authorization=authorization,
                usable_for_incorporation=source is not None and authorization_ok,
            )
        )

    page_keys = {
        (proposal.digital_object_id, proposal.page_number)
        for proposal in preview.proposals
        if proposal.target_type == "page"
        and proposal.digital_object_id is not None
        and proposal.page_number is not None
    }
    page_by_key: dict[tuple[str, int], EditablePage] = {}
    digital_ids = {digital_id for digital_id, _page in page_keys}
    if digital_ids:
        pages = session.scalars(
            select(EditablePage).where(EditablePage.digital_object_id.in_(digital_ids))
        ).all()
        page_by_key = {(row.digital_object_id, row.page_number): row for row in pages}

    usable_source_ids = {
        row.export_run_id for row in source_matches if row.usable_for_incorporation
    }
    usable_sources = [
        source for source in verified_sources if source.export_run_id in usable_source_ids
    ]
    proposal_resolutions: list[AIHandoffProposalResolution] = []
    for proposal in preview.proposals:
        if proposal.target_type != "page":
            proposal_resolutions.append(
                AIHandoffProposalResolution(
                    proposal_id=proposal.proposal_id,
                    editable_page_id=None,
                    target_status="unsupported_target_type",
                    asset_status="not_checked",
                    source_asset_sha256=None,
                    source_asset_path=None,
                    verified_export_run_ids=(),
                    acceptance_ready=False,
                    issue="P3 inicial incorpora vision_describe/0.1 sólo a nivel de página.",
                )
            )
            continue
        assert proposal.digital_object_id is not None and proposal.page_number is not None
        page = page_by_key.get((proposal.digital_object_id, proposal.page_number))
        if page is None:
            proposal_resolutions.append(
                AIHandoffProposalResolution(
                    proposal_id=proposal.proposal_id,
                    editable_page_id=None,
                    target_status="missing",
                    asset_status="not_checked",
                    source_asset_sha256=None,
                    source_asset_path=proposal.asset_path,
                    verified_export_run_ids=(),
                    acceptance_ready=False,
                    issue="La página indicada por digital_object_id + page_number no existe.",
                )
            )
            continue

        verified_run_ids: list[str] = []
        asset_path: str | None = proposal.asset_path
        asset_sha: str | None = None
        asset_issue: str | None = None
        for source in usable_sources:
            try:
                candidate_path, candidate_sha = _verify_proposal_asset(source, proposal)
            except (AIHandoffError, OSError) as exc:
                asset_issue = str(exc)
                continue
            if asset_sha is not None and (
                candidate_path != asset_path or candidate_sha != asset_sha
            ):
                asset_issue = (
                    "Las copias EXP-01 con el mismo hash resolvieron assets incompatibles."
                )
                verified_run_ids = []
                asset_sha = None
                break
            asset_path = candidate_path
            asset_sha = candidate_sha
            verified_run_ids.append(source.export_run_id)

        acceptance_ready = bool(verified_run_ids and asset_sha)
        proposal_resolutions.append(
            AIHandoffProposalResolution(
                proposal_id=proposal.proposal_id,
                editable_page_id=page.id,
                target_status="resolved",
                asset_status="verified" if acceptance_ready else "unverified",
                source_asset_sha256=asset_sha,
                source_asset_path=asset_path,
                verified_export_run_ids=tuple(verified_run_ids),
                acceptance_ready=acceptance_ready,
                issue=None
                if acceptance_ready
                else (asset_issue or "No hay un EXP-01 local utilizable."),
            )
        )

    blocking: list[str] = []
    if not runs:
        blocking.append("No existe un CorpusExportRun local con el SHA-256 EXP-01 del handoff.")
    elif not usable_sources:
        blocking.append(
            "Ninguna corrida local coincidente conserva un EXP-01 verificable con autorización de corpus compatible."
        )
    for resolution in proposal_resolutions:
        if not resolution.acceptance_ready:
            blocking.append(
                f"{resolution.proposal_id}: {resolution.issue or 'propuesta no resoluble'}"
            )
    return AIHandoffResolution(
        source_matches=tuple(source_matches),
        proposal_resolutions=tuple(proposal_resolutions),
        incorporation_allowed=not blocking,
        blocking_reasons=tuple(blocking),
    )


def read_verified_ai_handoff_asset(
    *,
    project_root: Path,
    project_id: str,
    run: CorpusExportRun,
    proposal: AIHandoffProposal,
    expected_exp01_sha256: str,
) -> VerifiedAIHandoffAsset:
    """Revalida EXP-01 y devuelve un asset exacto para mostrarlo durante la revisión."""

    source = _inspect_exp01_run(
        project_root=project_root,
        project_id=project_id,
        run=run,
        expected_sha256=expected_exp01_sha256,
    )
    asset_path, asset_sha = _verify_proposal_asset(source, proposal)
    asset = source.asset_by_id[proposal.target_id]
    with zipfile.ZipFile(source.path) as archive:
        info = archive.getinfo(asset_path)
        payload = _read_member_limited(
            archive,
            info,
            label=f"asset {proposal.target_id}",
            max_bytes=EXP01_MAX_ASSET_BYTES,
        )
    if _sha256_bytes(payload) != asset_sha:
        raise AIHandoffError("El asset cambió durante su lectura")
    width = asset.get("width")
    height = asset.get("height")
    return VerifiedAIHandoffAsset(
        proposal_id=proposal.proposal_id,
        path=asset_path,
        sha256=asset_sha,
        byte_size=len(payload),
        mime_type=_optional_string(asset.get("mime_type")),
        width=width if isinstance(width, int) else None,
        height=height if isinstance(height, int) else None,
        payload=payload,
    )
