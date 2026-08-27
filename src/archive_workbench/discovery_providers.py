from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from typing import Any, Iterable

LOCAL_PROVIDER_KEY = "local_deterministic"
LOCAL_PROVIDER_VERSION = "local_rules_v5"
LOCAL_PROVIDER_VERSIONS = ("local_rules_v1", "local_rules_v2", "local_rules_v3", "local_rules_v4", "local_rules_v5")
SPACY_PROVIDER_KEY = "spacy_ner"


@dataclass(frozen=True, slots=True)
class ProviderDetection:
    start: int
    end: int
    exact_text: str
    family: str
    subtype: str
    confidence: float | None
    explanation: str


@dataclass(frozen=True, slots=True)
class DiscoveryProviderContract:
    key: str
    version: str
    method: str
    model_name: str | None
    model_version: str | None
    supported_families: tuple[str, ...]
    available: bool
    availability_reason: str


_LOCAL_FAMILIES = (
    "actor",
    "space",
    "time",
    "event",
    "action_process",
    "work",
)
_SPACY_FAMILIES = (
    "actor",
    "space",
    "time",
    "event",
    "action_process",
    "work",
    "other",
)


def _spacy_reference(version: str) -> tuple[str, str]:
    clean = " ".join((version or "").split())
    if "@" not in clean:
        raise ValueError(
            "La versión de spacy_ner debe usar el formato modelo@versión, "
            "por ejemplo es_core_news_md@3.8.0"
        )
    model_name, model_version = clean.rsplit("@", 1)
    if not model_name or not model_version:
        raise ValueError(
            "La versión de spacy_ner debe usar el formato modelo@versión"
        )
    return model_name, model_version


def provider_contract(
    key: str,
    version: str,
    *,
    require_available: bool = False,
) -> DiscoveryProviderContract:
    if key == LOCAL_PROVIDER_KEY:
        if version not in LOCAL_PROVIDER_VERSIONS:
            raise ValueError(
                f"Versión no admitida para {LOCAL_PROVIDER_KEY}: {version}"
            )
        return DiscoveryProviderContract(
            key=key,
            version=version,
            method="conservative_regex_rules",
            model_name=None,
            model_version=None,
            supported_families=_LOCAL_FAMILIES,
            available=True,
            availability_reason=(
                "Proveedor local vigente incluido en Archive Workbench."
                if version == LOCAL_PROVIDER_VERSION
                else "Versión histórica preservada para reproducibilidad de perfiles y corridas."
            ),
        )

    if key == SPACY_PROVIDER_KEY:
        model_name, model_version = _spacy_reference(version)
        installed = importlib.util.find_spec("spacy") is not None
        if require_available and not installed:
            raise RuntimeError(
                "El adaptador spacy_ner requiere instalar el extra "
                "archive-workbench[discovery] y el modelo indicado."
            )
        return DiscoveryProviderContract(
            key=key,
            version=version,
            method="spacy_doc_ents",
            model_name=model_name,
            model_version=model_version,
            supported_families=_SPACY_FAMILIES,
            available=installed,
            availability_reason=(
                "spaCy está instalado; el modelo se verifica al ejecutar."
                if installed
                else "spaCy no está instalado en este entorno."
            ),
        )

    raise ValueError(f"Proveedor de descubrimiento no admitido: {key}")


def provider_catalog() -> tuple[DiscoveryProviderContract, ...]:
    return (
        provider_contract(LOCAL_PROVIDER_KEY, LOCAL_PROVIDER_VERSION),
        provider_contract(LOCAL_PROVIDER_KEY, "local_rules_v4"),
        provider_contract(LOCAL_PROVIDER_KEY, "local_rules_v3"),
        provider_contract(LOCAL_PROVIDER_KEY, "local_rules_v2"),
        provider_contract(LOCAL_PROVIDER_KEY, "local_rules_v1"),
        DiscoveryProviderContract(
            key=SPACY_PROVIDER_KEY,
            version="modelo@versión",
            method="spacy_doc_ents",
            model_name=None,
            model_version=None,
            supported_families=_SPACY_FAMILIES,
            available=importlib.util.find_spec("spacy") is not None,
            availability_reason=(
                "Adaptador disponible; cada perfil debe fijar modelo y versión."
                if importlib.util.find_spec("spacy") is not None
                else "Instalar archive-workbench[discovery] y un modelo de spaCy."
            ),
        ),
    )


def _load_spacy_pipeline(model_name: str) -> Any:
    try:
        import spacy
    except ImportError as exc:
        raise RuntimeError(
            "El adaptador spacy_ner requiere instalar el extra "
            "archive-workbench[discovery]."
        ) from exc
    try:
        return spacy.load(model_name)
    except OSError as exc:
        raise RuntimeError(
            f"No se encontró el modelo de spaCy {model_name}. "
            f"Instalalo antes de ejecutar el perfil."
        ) from exc


def _spacy_family(label: str) -> tuple[str, str] | None:
    normalized = label.upper()
    mapping = {
        "PERSON": ("actor", "person"),
        "PER": ("actor", "person"),
        "PERSONA": ("actor", "person"),
        "ORG": ("actor", "organization"),
        "ORGANIZATION": ("actor", "organization"),
        "NORP": ("actor", "collective"),
        "GPE": ("space", "place"),
        "LOC": ("space", "place"),
        "LUGAR": ("space", "place"),
        "FAC": ("space", "building"),
        "DATE": ("time", "temporal_expression"),
        "TIME": ("time", "temporal_expression"),
        "FECHA": ("time", "temporal_expression"),
        "EVENT": ("event", "event"),
        "ACONTECIMIENTO": ("event", "event"),
        "ACTION": ("action_process", "action"),
        "PROCESS": ("action_process", "process"),
        "PROCESO": ("action_process", "process"),
        "WORK_OF_ART": ("work", "work"),
        "OBRA": ("work", "work"),
        "MISC": ("other", "misc"),
    }
    return mapping.get(normalized)


def _detect_spacy(
    text: str,
    *,
    families: Iterable[str],
    contract: DiscoveryProviderContract,
) -> list[ProviderDetection]:
    assert contract.model_name is not None
    assert contract.model_version is not None
    nlp = _load_spacy_pipeline(contract.model_name)
    actual_version = str(getattr(nlp, "meta", {}).get("version") or "").strip()
    if actual_version != contract.model_version:
        raise RuntimeError(
            f"El perfil exige {contract.model_name}@{contract.model_version}, "
            f"pero el modelo cargado declara {actual_version or 'versión desconocida'}."
        )
    selected = set(families)
    detections: list[ProviderDetection] = []
    for entity in nlp(text).ents:
        mapped = _spacy_family(entity.label_)
        if mapped is None:
            continue
        family, subtype = mapped
        if family not in selected:
            continue
        start = int(entity.start_char)
        end = int(entity.end_char)
        if start < 0 or end <= start or end > len(text):
            continue
        exact = text[start:end]
        detections.append(
            ProviderDetection(
                start=start,
                end=end,
                exact_text=exact,
                family=family,
                subtype=subtype,
                confidence=None,
                explanation=(
                    f"Entidad {entity.label_} propuesta por "
                    f"{contract.model_name}@{contract.model_version}."
                ),
            )
        )
    return sorted(
        detections,
        key=lambda item: (item.start, item.end, item.family, item.subtype),
    )


def detect_with_provider(
    text: str,
    *,
    families: Iterable[str],
    provider_key: str,
    provider_version: str,
    allow_unsupported: bool = False,
) -> tuple[DiscoveryProviderContract, list[ProviderDetection]]:
    contract = provider_contract(
        provider_key,
        provider_version,
        require_available=provider_key == SPACY_PROVIDER_KEY,
    )
    selected = tuple(dict.fromkeys(families))
    unsupported = set(selected) - set(contract.supported_families)
    if unsupported and not allow_unsupported:
        raise ValueError(
            f"{contract.key}@{contract.version} no admite las familias: "
            + ", ".join(sorted(unsupported))
        )
    selected = tuple(
        family for family in selected if family in set(contract.supported_families)
    )

    if provider_key == LOCAL_PROVIDER_KEY:
        from archive_workbench.open_discovery import detect_local_candidates

        rows = detect_local_candidates(
            text,
            families=selected,
            provider_version=provider_version,
        )
        return contract, [
            ProviderDetection(
                start=row.start,
                end=row.end,
                exact_text=row.exact_text,
                family=row.family,
                subtype=row.subtype,
                confidence=row.confidence,
                explanation=row.explanation,
            )
            for row in rows
        ]

    if provider_key == SPACY_PROVIDER_KEY:
        return contract, _detect_spacy(text, families=selected, contract=contract)

    raise ValueError(f"Proveedor de descubrimiento no admitido: {provider_key}")
