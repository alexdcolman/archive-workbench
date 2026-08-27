from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any, Protocol, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.analysis_audit import (
    record_automatic_analysis_authorization,
    require_automatic_analysis_authorization,
)
from archive_workbench.analysis_quality import (
    DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES,
    quality_scope_snapshot,
    validate_automatic_quality_scope,
)
from archive_workbench.corpus_export import (
    AGGREGATION_LEVELS,
    CorpusExportProfile,
    build_export_rows,
)
from archive_workbench.db.models import (
    SemanticIndexRun,
    SemanticSearchProfile,
    utc_now,
)
from archive_workbench.identity import new_id
from archive_workbench.search import object_ids_matching_temporal

DEFAULT_MODEL_NAME = "intfloat/multilingual-e5-small"
DEFAULT_MODEL_REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"
SEMANTIC_AGGREGATION_LEVELS = ("object", "page", "document_part", "document", "archival_unit")
REVIEW_STATUSES = ("unreviewed", "needs_review", "reviewed", "approved")


class EmbeddingBackend(Protocol):
    def encode_documents(self, texts: Sequence[str], *, batch_size: int) -> list[list[float]]: ...

    def encode_queries(self, texts: Sequence[str], *, batch_size: int) -> list[list[float]]: ...


@dataclass(slots=True)
class SemanticProfileValues:
    name: str
    description: str | None = None
    model_name: str = DEFAULT_MODEL_NAME
    model_revision: str | None = DEFAULT_MODEL_REVISION
    aggregation_level: str = "object"
    include_object_types: tuple[str, ...] = ()
    include_review_statuses: tuple[str, ...] = ()
    include_page_review_statuses: tuple[str, ...] = DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES
    chunk_size: int = 1800
    chunk_overlap: int = 200
    query_prefix: str = "query: "
    document_prefix: str = "passage: "
    normalize_embeddings: bool = True


@dataclass(slots=True)
class SemanticChunk:
    chunk_id: str
    record_id: str
    title: str
    text: str
    source_key: str | None
    source_keys: list[str]
    object_ids: list[str]
    page_start: int
    page_end: int
    document_part_key: str | None
    hierarchy_path: str | None
    chunk_number: int
    character_start: int
    character_end: int


@dataclass(slots=True)
class SemanticIndexStatus:
    profile_id: str
    profile_name: str
    latest_run_id: str | None
    vector_count: int
    dimensions: int
    indexed_at: datetime | None
    corpus_state_sha256: str | None
    current_corpus_state_sha256: str
    profile_revision: int
    indexed_profile_revision: int | None
    files_valid: bool
    is_current: bool
    reason: str


@dataclass(slots=True)
class SemanticIndexSummary:
    run_id: str
    profile_id: str
    vector_count: int
    dimensions: int
    vectors_path: Path
    metadata_path: Path
    manifest_path: Path
    corpus_state_sha256: str


@dataclass(slots=True)
class SemanticSearchResult:
    chunk_id: str
    score: float
    title: str
    excerpt: str
    query_text: str
    source_key: str | None
    object_ids: list[str]
    page_start: int
    page_end: int
    document_part_key: str | None
    hierarchy_path: str | None
    record_id: str


class SentenceTransformerBackend:
    """Backend opcional. La importación y la descarga del modelo son diferidas."""

    def __init__(
        self,
        *,
        model_name: str,
        model_revision: str | None,
        device: str = "auto",
        query_prefix: str = "",
        document_prefix: str = "",
        normalize_embeddings: bool = True,
    ) -> None:
        if importlib.util.find_spec("sentence_transformers") is None:
            raise RuntimeError(
                "La búsqueda semántica requiere la dependencia opcional. Ejecutá: "
                'pip install -e ".[semantic]"'
            )
        from sentence_transformers import SentenceTransformer

        kwargs: dict[str, Any] = {"trust_remote_code": False}
        if model_revision:
            kwargs["revision"] = model_revision
        if device != "auto":
            kwargs["device"] = device
        self.model = SentenceTransformer(model_name, **kwargs)
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix
        self.normalize_embeddings = normalize_embeddings

    def _encode(self, texts: Sequence[str], *, kind: str, batch_size: int) -> list[list[float]]:
        prefix = self.query_prefix if kind == "query" else self.document_prefix
        prepared = [prefix + value for value in texts]
        encoder = self.model.encode_query if kind == "query" else self.model.encode_document
        values = encoder(
            prepared,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=len(prepared) > batch_size,
        )
        if getattr(values, "ndim", 1) == 1:
            values = values.reshape(1, -1)
        return [[float(item) for item in row] for row in values]

    def encode_documents(self, texts: Sequence[str], *, batch_size: int) -> list[list[float]]:
        return self._encode(texts, kind="document", batch_size=batch_size)

    def encode_queries(self, texts: Sequence[str], *, batch_size: int) -> list[list[float]]:
        return self._encode(texts, kind="query", batch_size=batch_size)


def semantic_dependencies_available() -> bool:
    return importlib.util.find_spec("sentence_transformers") is not None


def _clean_text(value: str, *, field: str, maximum: int) -> str:
    clean = " ".join(value.split())
    if not clean:
        raise ValueError(f"{field} no puede quedar vacío")
    if len(clean) > maximum:
        raise ValueError(f"{field} no puede superar {maximum} caracteres")
    return clean


def _validate_profile(
    values: SemanticProfileValues,
    *,
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
) -> SemanticProfileValues:
    name = _clean_text(values.name, field="El nombre", maximum=200)
    model_name = _clean_text(values.model_name, field="El modelo", maximum=500)
    if values.aggregation_level not in SEMANTIC_AGGREGATION_LEVELS:
        raise ValueError("Nivel de agrupación semántica inválido")
    if not 200 <= values.chunk_size <= 20_000:
        raise ValueError("El tamaño de fragmento debe estar entre 200 y 20000 caracteres")
    if not 0 <= values.chunk_overlap < values.chunk_size:
        raise ValueError("La superposición debe ser menor que el tamaño del fragmento")
    if len(values.query_prefix) > 200 or len(values.document_prefix) > 200:
        raise ValueError("Los prefijos no pueden superar 200 caracteres")
    invalid_object = set(values.include_review_statuses) - set(REVIEW_STATUSES)
    if invalid_object:
        raise ValueError("El perfil contiene estados de revisión de objeto inválidos")
    page_scope = validate_automatic_quality_scope(
        values.include_page_review_statuses,
        broader_scope_confirmed=broader_quality_scope_confirmed,
        confirmation_reason=quality_scope_reason,
    )
    return SemanticProfileValues(
        name=name,
        description=values.description.strip() if values.description and values.description.strip() else None,
        model_name=model_name,
        model_revision=(values.model_revision.strip() if values.model_revision and values.model_revision.strip() else None),
        aggregation_level=values.aggregation_level,
        include_object_types=tuple(sorted(set(values.include_object_types))),
        include_review_statuses=tuple(sorted(set(values.include_review_statuses))),
        include_page_review_statuses=page_scope.page_review_statuses,
        chunk_size=int(values.chunk_size),
        chunk_overlap=int(values.chunk_overlap),
        query_prefix=values.query_prefix,
        document_prefix=values.document_prefix,
        normalize_embeddings=bool(values.normalize_embeddings),
    )


def profile_values(profile: SemanticSearchProfile) -> SemanticProfileValues:
    return SemanticProfileValues(
        name=profile.name,
        description=profile.description,
        model_name=profile.model_name,
        model_revision=profile.model_revision,
        aggregation_level=profile.aggregation_level,
        include_object_types=tuple(profile.include_object_types_json or []),
        include_review_statuses=tuple(profile.include_review_statuses_json or []),
        include_page_review_statuses=tuple(profile.include_page_review_statuses_json or []),
        chunk_size=profile.chunk_size,
        chunk_overlap=profile.chunk_overlap,
        query_prefix=profile.query_prefix,
        document_prefix=profile.document_prefix,
        normalize_embeddings=bool(profile.normalize_embeddings),
    )


def semantic_profile_authorization_parameters(
    profile: SemanticSearchProfile,
) -> dict[str, Any]:
    """Parámetros funcionales cuya autorización habilita el índice y la búsqueda."""

    payload = asdict(profile_values(profile))
    for key in (
        "include_object_types",
        "include_review_statuses",
        "include_page_review_statuses",
    ):
        payload[key] = list(payload[key])
    payload["analysis_quality"] = quality_scope_snapshot(
        analysis_kind="semantic_index",
        page_review_statuses=profile.include_page_review_statuses_json or [],
    )
    return payload


def profile_snapshot(profile: SemanticSearchProfile) -> dict[str, Any]:
    payload = semantic_profile_authorization_parameters(profile)
    payload.update({"id": profile.id, "revision": profile.revision})
    return payload


def _require_semantic_profile_authorization(
    session: Session, *, project_id: str, profile: SemanticSearchProfile
) -> None:
    require_automatic_analysis_authorization(
        session,
        project_id=project_id,
        analysis_kind="semantic_index",
        page_review_statuses=tuple(profile.include_page_review_statuses_json or ()),
        target_type="semantic_search_profile",
        target_id=profile.id,
        parameters=semantic_profile_authorization_parameters(profile),
        remediation=(
            "Abrí Preparar búsqueda y guardá el perfil nuevamente para "
            "registrar su alcance de calidad."
        ),
    )


def save_semantic_profile(
    session: Session,
    *,
    project_id: str,
    values: SemanticProfileValues,
    changed_by: str,
    profile_id: str | None = None,
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
    quality_scope_source: str = "api",
) -> SemanticSearchProfile:
    clean = _validate_profile(
        values,
        broader_quality_scope_confirmed=broader_quality_scope_confirmed,
        quality_scope_reason=quality_scope_reason,
    )
    profile = session.get(SemanticSearchProfile, profile_id) if profile_id else None
    if profile is None:
        profile = session.scalar(
            select(SemanticSearchProfile).where(
                SemanticSearchProfile.project_id == project_id,
                SemanticSearchProfile.name == clean.name,
            )
        )
    now = utc_now()
    if profile is None:
        profile = SemanticSearchProfile(
            id=new_id(),
            project_id=project_id,
            name=clean.name,
            description=clean.description,
            model_name=clean.model_name,
            model_revision=clean.model_revision,
            aggregation_level=clean.aggregation_level,
            include_object_types_json=list(clean.include_object_types),
            include_review_statuses_json=list(clean.include_review_statuses),
            include_page_review_statuses_json=list(clean.include_page_review_statuses),
            chunk_size=clean.chunk_size,
            chunk_overlap=clean.chunk_overlap,
            query_prefix=clean.query_prefix,
            document_prefix=clean.document_prefix,
            normalize_embeddings=clean.normalize_embeddings,
            created_by=changed_by,
            created_at=now,
            updated_by=changed_by,
            updated_at=now,
            revision=1,
        )
        session.add(profile)
    else:
        if profile.project_id != project_id:
            raise ValueError("El perfil pertenece a otro proyecto")
        duplicate = session.scalar(
            select(SemanticSearchProfile).where(
                SemanticSearchProfile.project_id == project_id,
                SemanticSearchProfile.name == clean.name,
                SemanticSearchProfile.id != profile.id,
            )
        )
        if duplicate is not None:
            raise ValueError(f"Ya existe otro perfil llamado {clean.name}")
        profile.name = clean.name
        profile.description = clean.description
        profile.model_name = clean.model_name
        profile.model_revision = clean.model_revision
        profile.aggregation_level = clean.aggregation_level
        profile.include_object_types_json = list(clean.include_object_types)
        profile.include_review_statuses_json = list(clean.include_review_statuses)
        profile.include_page_review_statuses_json = list(clean.include_page_review_statuses)
        profile.chunk_size = clean.chunk_size
        profile.chunk_overlap = clean.chunk_overlap
        profile.query_prefix = clean.query_prefix
        profile.document_prefix = clean.document_prefix
        profile.normalize_embeddings = clean.normalize_embeddings
        profile.updated_by = changed_by
        profile.updated_at = now
        profile.revision += 1
    session.flush()
    record_automatic_analysis_authorization(
        session,
        project_id=project_id,
        analysis_kind="semantic_index",
        page_review_statuses=clean.include_page_review_statuses,
        broader_scope_confirmed=broader_quality_scope_confirmed,
        confirmed_by=changed_by,
        confirmation_reason=quality_scope_reason,
        source=quality_scope_source,
        target_type="semantic_search_profile",
        target_id=profile.id,
        parameters=semantic_profile_authorization_parameters(profile),
    )
    return profile


def ensure_default_semantic_profile(
    session: Session, *, project_id: str, changed_by: str
) -> SemanticSearchProfile:
    existing = session.scalar(
        select(SemanticSearchProfile).where(
            SemanticSearchProfile.project_id == project_id,
            SemanticSearchProfile.name == "Multilingüe E5 — objetos",
        )
    )
    if existing is not None:
        return existing
    return save_semantic_profile(
        session,
        project_id=project_id,
        values=SemanticProfileValues(
            name="Multilingüe E5 — objetos",
            description="Perfil inicial para recuperar objetos textuales por afinidad semántica.",
            include_page_review_statuses=DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES,
        ),
        changed_by=changed_by,
    )


def semantic_profile_rows(session: Session, *, project_id: str) -> list[SemanticSearchProfile]:
    return session.scalars(
        select(SemanticSearchProfile)
        .where(SemanticSearchProfile.project_id == project_id)
        .order_by(SemanticSearchProfile.name, SemanticSearchProfile.id)
    ).all()


def resolve_semantic_profile(
    session: Session, *, project_id: str, profile_ref: str
) -> SemanticSearchProfile:
    profile = session.scalar(
        select(SemanticSearchProfile).where(
            SemanticSearchProfile.project_id == project_id,
            (SemanticSearchProfile.id == profile_ref) | (SemanticSearchProfile.name == profile_ref),
        )
    )
    if profile is None:
        raise ValueError(f"Perfil semántico inexistente: {profile_ref}")
    return profile


def _export_profile_for_semantics(profile: SemanticSearchProfile) -> CorpusExportProfile:
    return CorpusExportProfile(
        id=f"semantic:{profile.id}",
        project_id=profile.project_id,
        name=profile.name,
        aggregation_level=profile.aggregation_level,
        text_policy="corrected_fallback_original",
        output_format="jsonl",
        include_object_types_json=list(profile.include_object_types_json or []),
        include_review_statuses_json=list(profile.include_review_statuses_json or []),
        include_page_review_statuses_json=list(profile.include_page_review_statuses_json or []),
        object_separator="\n\n",
        page_separator="\n\n",
        include_page_markers=True,
        created_by=profile.created_by,
        updated_by=profile.updated_by,
        revision=profile.revision,
    )


def _cut_position(text: str, start: int, target: int) -> int:
    if target >= len(text):
        return len(text)
    minimum = start + max(80, int((target - start) * 0.6))
    for separator in ("\n\n", "\n", ". ", "; ", ", "):
        found = text.rfind(separator, minimum, target + 1)
        if found >= minimum:
            return found + len(separator)
    return target


def _chunk_record(record, *, chunk_size: int, overlap: int) -> list[SemanticChunk]:
    text = record.texto.strip()
    if not text:
        return []
    chunks: list[SemanticChunk] = []
    start = 0
    number = 1
    while start < len(text):
        end = _cut_position(text, start, min(len(text), start + chunk_size))
        if end <= start:
            end = min(len(text), start + chunk_size)
        fragment = text[start:end].strip()
        if fragment:
            chunks.append(
                SemanticChunk(
                    chunk_id=f"{record.record_id}:chunk:{number}",
                    record_id=record.record_id,
                    title=record.titulo,
                    text=fragment,
                    source_key=record.source_key,
                    source_keys=list(record.source_keys),
                    object_ids=list(record.object_ids),
                    page_start=record.page_start,
                    page_end=record.page_end,
                    document_part_key=record.document_part_key,
                    hierarchy_path=record.hierarchy_path,
                    chunk_number=number,
                    character_start=start,
                    character_end=end,
                )
            )
            number += 1
        if end >= len(text):
            break
        next_start = max(start + 1, end - overlap)
        start = next_start
    return chunks


def build_semantic_chunks(
    session: Session, *, project_id: str, profile: SemanticSearchProfile
) -> list[SemanticChunk]:
    export_profile = _export_profile_for_semantics(profile)
    records = build_export_rows(session, project_id=project_id, profile=export_profile)
    chunks: list[SemanticChunk] = []
    for record in records:
        chunks.extend(
            _chunk_record(record, chunk_size=profile.chunk_size, overlap=profile.chunk_overlap)
        )
    return chunks


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("El backend produjo un vector vacío o no finito")
    return [float(value) / norm for value in vector]


def _validate_vectors(
    vectors: Sequence[Sequence[float]], *, expected_count: int, normalize: bool
) -> tuple[list[list[float]], int]:
    if len(vectors) != expected_count:
        raise ValueError(
            f"El backend devolvió {len(vectors)} vectores para {expected_count} fragmentos"
        )
    dimensions = len(vectors[0]) if vectors else 0
    if dimensions <= 0:
        raise ValueError("El backend no produjo dimensiones")
    validated: list[list[float]] = []
    for row in vectors:
        if len(row) != dimensions:
            raise ValueError("El backend produjo vectores con dimensiones inconsistentes")
        values = [float(item) for item in row]
        if not all(math.isfinite(item) for item in values):
            raise ValueError("El backend produjo valores no finitos")
        validated.append(_normalize(values) if normalize else values)
    return validated, dimensions


def _write_vectors(path: Path, vectors: Sequence[Sequence[float]]) -> None:
    values = array("f")
    for row in vectors:
        values.extend(float(item) for item in row)
    if sys.byteorder != "little":
        values.byteswap()
    with path.open("wb") as handle:
        values.tofile(handle)


def _read_vectors(path: Path, *, count: int, dimensions: int) -> list[list[float]]:
    values = array("f")
    with path.open("rb") as handle:
        values.fromfile(handle, count * dimensions)
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != count * dimensions:
        raise ValueError("El archivo de vectores está truncado")
    return [
        [float(item) for item in values[index * dimensions : (index + 1) * dimensions]]
        for index in range(count)
    ]




def _semantic_corpus_sha256(chunks: Sequence[SemanticChunk]) -> str:
    """Huella del corpus que realmente alimenta el índice semántico."""
    digest = hashlib.sha256()
    for chunk in chunks:
        payload = json.dumps(
            asdict(chunk),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def build_semantic_index(
    session: Session,
    *,
    project_root: Path,
    project_id: str,
    profile: SemanticSearchProfile,
    created_by: str,
    backend: EmbeddingBackend | None = None,
    device: str = "auto",
    batch_size: int = 32,
) -> SemanticIndexSummary:
    if profile.project_id != project_id:
        raise ValueError("El perfil pertenece a otro proyecto")
    _require_semantic_profile_authorization(
        session, project_id=project_id, profile=profile
    )
    if batch_size < 1 or batch_size > 2048:
        raise ValueError("El tamaño de lote debe estar entre 1 y 2048")
    chunks = build_semantic_chunks(session, project_id=project_id, profile=profile)
    if not chunks:
        raise ValueError("No hay textos que cumplan los filtros del perfil")
    selected_backend = backend or SentenceTransformerBackend(
        model_name=profile.model_name,
        model_revision=profile.model_revision,
        device=device,
        query_prefix=profile.query_prefix,
        document_prefix=profile.document_prefix,
        normalize_embeddings=profile.normalize_embeddings,
    )
    encoded = selected_backend.encode_documents([row.text for row in chunks], batch_size=batch_size)
    vectors, dimensions = _validate_vectors(
        encoded, expected_count=len(chunks), normalize=profile.normalize_embeddings
    )
    run_id = new_id()
    directory = project_root / "semantic" / "indexes" / profile.id / run_id
    directory.mkdir(parents=True, exist_ok=False)
    vectors_path = directory / "vectors.f32"
    metadata_path = directory / "chunks.jsonl"
    manifest_path = directory / "manifest.json"
    try:
        _write_vectors(vectors_path, vectors)
        with metadata_path.open("w", encoding="utf-8", newline="\n") as handle:
            for index, chunk in enumerate(chunks):
                payload = asdict(chunk)
                payload["vector_index"] = index
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        vectors_sha256 = _sha256(vectors_path)
        metadata_sha256 = _sha256(metadata_path)
        corpus_state = _semantic_corpus_sha256(chunks)
        manifest = {
            "schema_version": "1.0",
            "run_id": run_id,
            "profile": profile_snapshot(profile),
            "corpus_state_sha256": corpus_state,
            "model_name": profile.model_name,
            "model_revision": profile.model_revision,
            "vector_count": len(chunks),
            "dimensions": dimensions,
            "normalized": bool(profile.normalize_embeddings),
            "byte_order": "little",
            "vectors_sha256": vectors_sha256,
            "metadata_sha256": metadata_sha256,
            "created_by": created_by,
            "created_at": utc_now().isoformat(),
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception:
        for path in (vectors_path, metadata_path, manifest_path):
            path.unlink(missing_ok=True)
        try:
            directory.rmdir()
        except OSError:
            pass
        raise
    run = SemanticIndexRun(
        id=run_id,
        project_id=project_id,
        profile_id=profile.id,
        profile_snapshot_json=profile_snapshot(profile),
        corpus_state_sha256=corpus_state,
        model_name=profile.model_name,
        model_revision=profile.model_revision,
        vectors_relative_path=_relative(project_root, vectors_path),
        metadata_relative_path=_relative(project_root, metadata_path),
        manifest_relative_path=_relative(project_root, manifest_path),
        vector_count=len(chunks),
        dimensions=dimensions,
        vectors_sha256=vectors_sha256,
        metadata_sha256=metadata_sha256,
        status="completed",
        error_message=None,
        created_by=created_by,
        created_at=utc_now(),
    )
    session.add(run)
    session.flush()
    return SemanticIndexSummary(
        run_id=run.id,
        profile_id=profile.id,
        vector_count=run.vector_count,
        dimensions=run.dimensions,
        vectors_path=vectors_path,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        corpus_state_sha256=corpus_state,
    )


def latest_semantic_index_run(
    session: Session, *, profile_id: str
) -> SemanticIndexRun | None:
    return session.scalar(
        select(SemanticIndexRun)
        .where(SemanticIndexRun.profile_id == profile_id, SemanticIndexRun.status == "completed")
        .order_by(SemanticIndexRun.created_at.desc(), SemanticIndexRun.id.desc())
    )


def semantic_index_status(
    session: Session,
    *,
    project_root: Path,
    project_id: str,
    profile: SemanticSearchProfile,
) -> SemanticIndexStatus:
    current_state = _semantic_corpus_sha256(
        build_semantic_chunks(session, project_id=project_id, profile=profile)
    )
    run = latest_semantic_index_run(session, profile_id=profile.id)
    if run is None:
        return SemanticIndexStatus(
            profile_id=profile.id,
            profile_name=profile.name,
            latest_run_id=None,
            vector_count=0,
            dimensions=0,
            indexed_at=None,
            corpus_state_sha256=None,
            current_corpus_state_sha256=current_state,
            profile_revision=profile.revision,
            indexed_profile_revision=None,
            files_valid=False,
            is_current=False,
            reason="Todavía no se construyó el índice",
        )
    vectors_path = project_root / run.vectors_relative_path
    metadata_path = project_root / run.metadata_relative_path
    snapshot_revision = int(run.profile_snapshot_json.get("revision", 0))
    files_valid = (
        vectors_path.is_file()
        and metadata_path.is_file()
        and _sha256(vectors_path) == run.vectors_sha256
        and _sha256(metadata_path) == run.metadata_sha256
    )
    if not files_valid:
        reason = "Faltan archivos del índice o no coinciden sus checksums"
    elif snapshot_revision != profile.revision:
        reason = "El perfil cambió después de construir el índice"
    elif run.corpus_state_sha256 != current_state:
        reason = "El corpus cambió después de construir el índice"
    else:
        reason = "Índice actualizado"
    return SemanticIndexStatus(
        profile_id=profile.id,
        profile_name=profile.name,
        latest_run_id=run.id,
        vector_count=run.vector_count,
        dimensions=run.dimensions,
        indexed_at=run.created_at,
        corpus_state_sha256=run.corpus_state_sha256,
        current_corpus_state_sha256=current_state,
        profile_revision=profile.revision,
        indexed_profile_revision=snapshot_revision,
        files_valid=files_valid,
        is_current=(files_valid and snapshot_revision == profile.revision and run.corpus_state_sha256 == current_state),
        reason=reason,
    )


def _load_metadata(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Metadatos semánticos inválidos en línea {line_number}") from exc
    return rows


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def semantic_search(
    session: Session,
    *,
    project_root: Path,
    project_id: str,
    profile: SemanticSearchProfile,
    query: str,
    top_k: int = 20,
    minimum_score: float = 0.0,
    exclude_chunk_ids: Sequence[str] = (),
    exclude_object_ids: Sequence[str] = (),
    temporal_start: date | None = None,
    temporal_end: date | None = None,
    temporal_include_undated: bool = False,
    backend: EmbeddingBackend | None = None,
    device: str = "auto",
) -> list[SemanticSearchResult]:
    _require_semantic_profile_authorization(
        session, project_id=project_id, profile=profile
    )
    clean_query = " ".join(query.split())
    if not clean_query:
        raise ValueError("Escribí una consulta semántica")
    if not 1 <= top_k <= 500:
        raise ValueError("top_k debe estar entre 1 y 500")
    if not -1.0 <= minimum_score <= 1.0:
        raise ValueError("El puntaje mínimo debe estar entre -1 y 1")
    status = semantic_index_status(
        session, project_root=project_root, project_id=project_id, profile=profile
    )
    if not status.is_current or status.latest_run_id is None:
        raise ValueError(f"El índice no está listo: {status.reason}. Reconstruí el índice.")
    run = session.get(SemanticIndexRun, status.latest_run_id)
    if run is None:
        raise ValueError("El registro del índice ya no existe")
    selected_backend = backend or SentenceTransformerBackend(
        model_name=profile.model_name,
        model_revision=profile.model_revision,
        device=device,
        query_prefix=profile.query_prefix,
        document_prefix=profile.document_prefix,
        normalize_embeddings=profile.normalize_embeddings,
    )
    query_vectors = selected_backend.encode_queries([clean_query], batch_size=1)
    validated, query_dimensions = _validate_vectors(
        query_vectors, expected_count=1, normalize=profile.normalize_embeddings
    )
    if query_dimensions != run.dimensions:
        raise ValueError(
            f"El modelo devolvió {query_dimensions} dimensiones, pero el índice tiene {run.dimensions}"
        )
    vectors = _read_vectors(
        project_root / run.vectors_relative_path,
        count=run.vector_count,
        dimensions=run.dimensions,
    )
    metadata = _load_metadata(project_root / run.metadata_relative_path)
    if len(metadata) != len(vectors):
        raise ValueError("El índice y sus metadatos tienen cantidades diferentes")
    query_vector = validated[0]
    scored: list[tuple[float, dict[str, Any]]] = []
    excluded = {str(value) for value in exclude_chunk_ids}
    excluded_objects = {str(value) for value in exclude_object_ids}
    for vector, row in zip(vectors, metadata, strict=True):
        if str(row.get("chunk_id", "")) in excluded:
            continue
        if excluded_objects.intersection(str(value) for value in row.get("object_ids", [])):
            continue
        if profile.normalize_embeddings:
            score = _dot(query_vector, vector)
        else:
            left_norm = math.sqrt(_dot(query_vector, query_vector))
            right_norm = math.sqrt(_dot(vector, vector))
            score = _dot(query_vector, vector) / (left_norm * right_norm) if left_norm and right_norm else 0.0
        if score >= minimum_score:
            scored.append((float(score), row))
    scored.sort(key=lambda item: (-item[0], item[1].get("chunk_id", "")))
    if temporal_start is not None or temporal_end is not None:
        candidate_object_ids = {
            str(object_id)
            for _score, row in scored
            for object_id in row.get("object_ids", [])
        }
        matching_object_ids = object_ids_matching_temporal(
            session,
            object_ids=candidate_object_ids,
            temporal_start=temporal_start,
            temporal_end=temporal_end,
            include_undated=temporal_include_undated,
        )
        scored = [
            (score, row)
            for score, row in scored
            if matching_object_ids.intersection(
                str(object_id) for object_id in row.get("object_ids", [])
            )
        ]
    results: list[SemanticSearchResult] = []
    for score, row in scored[:top_k]:
        text_value = str(row.get("text", ""))
        excerpt = text_value if len(text_value) <= 600 else text_value[:597].rstrip() + "…"
        results.append(
            SemanticSearchResult(
                chunk_id=str(row["chunk_id"]),
                score=score,
                title=str(row.get("title") or "Sin título"),
                excerpt=excerpt,
                query_text=text_value,
                source_key=row.get("source_key"),
                object_ids=[str(value) for value in row.get("object_ids", [])],
                page_start=int(row.get("page_start") or 1),
                page_end=int(row.get("page_end") or row.get("page_start") or 1),
                document_part_key=row.get("document_part_key"),
                hierarchy_path=row.get("hierarchy_path"),
                record_id=str(row.get("record_id") or row["chunk_id"]),
            )
        )
    return results
