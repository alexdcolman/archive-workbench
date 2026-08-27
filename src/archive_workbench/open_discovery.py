from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
import re
import unicodedata
from typing import Any, Iterable, Sequence

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
from archive_workbench.db.models import (
    AuthorityAlias,
    AuthorityRecord,
    DigitalObject,
    DiscoveryCandidate,
    DiscoveryDecision,
    DiscoveryProfile,
    DiscoveryRun,
    EditableObject,
    EditablePage,
    EntityMention,
    Project,
    SourceRegistration,
    utc_now,
)
from archive_workbench.discovery_providers import (
    LOCAL_PROVIDER_KEY,
    LOCAL_PROVIDER_VERSION,
    detect_with_provider,
    provider_contract,
)
from archive_workbench.exchange import current_editable_state_sha256
from archive_workbench.identity import new_id

DISCOVERY_FAMILIES = (
    "actor",
    "space",
    "time",
    "event",
    "action_process",
    "work",
    "other",
)
DISCOVERY_PROVIDER_KEY = LOCAL_PROVIDER_KEY
DISCOVERY_PROVIDER_VERSION = LOCAL_PROVIDER_VERSION
OBJECT_REVIEW_STATUSES = ("unreviewed", "needs_review", "reviewed", "approved")

_FAMILY_LABELS = {
    "actor": "Actor",
    "space": "Espacio",
    "time": "Tiempo",
    "event": "Acontecimiento",
    "action_process": "Acción o proceso",
    "work": "Obra / publicación",
    "other": "Otra clase",
}

_MONTHS = (
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|"
    "octubre|noviembre|diciembre"
)
_WORD = r"A-ZÁÉÍÓÚÜÑa-záéíóúüñ0-9"
_CAPITALIZED = rf"[A-ZÁÉÍÓÚÜÑ][{_WORD}'’-]*"
_CAPITALIZED_PHRASE = rf"{_CAPITALIZED}(?:\s+(?:de|del|la|las|los|y|e|{_CAPITALIZED})){{0,6}}"

_TIME_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "calendar_date",
        re.compile(r"\b(?:[0-3]?\d)[/-](?:[01]?\d)[/-](?:18|19|20)\d{2}\b", re.I),
        0.99,
        "Fecha numérica explícita.",
    ),
    (
        "calendar_date",
        re.compile(rf"\b(?:[0-3]?\d)\s+de\s+(?:{_MONTHS})(?:\s+de\s+(?:18|19|20)\d{{2}})?\b", re.I),
        0.99,
        "Fecha expresada con día y mes.",
    ),
    (
        "year",
        re.compile(r"\b(?:18|19|20)\d{2}\b"),
        0.95,
        "Año de cuatro cifras.",
    ),
    (
        "period",
        re.compile(
            r"\b(?:años?|década de los)\s+"
            r"(?:sesenta|setenta|ochenta|noventa|dos mil)\b",
            re.I,
        ),
        0.93,
        "Período histórico expresado léxicamente.",
    ),
    (
        "interval",
        re.compile(r"\bentre\s+(?:18|19|20)\d{2}\s+y\s+(?:18|19|20)\d{2}\b", re.I),
        0.97,
        "Intervalo temporal explícito.",
    ),
)

_ACTOR_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "person",
        re.compile(
            rf"\b(?:Sr\.?|Sra\.?|Dr\.?|Dra\.?|doctor|doctora|presidente|presidenta|"
            rf"ministro|ministra|general|coronel|profesor|profesora)\s+"
            rf"{_CAPITALIZED}(?:\s+{_CAPITALIZED}){{1,3}}\b"
        ),
        0.91,
        "Nombre propio introducido por un tratamiento o cargo explícito.",
    ),
    (
        "organization",
        re.compile(
            rf"\b(?:Ministerio|Secretaría|Universidad|Partido|Sindicato|Comisión|Junta|"
            rf"Asociación|Fundación|Instituto|Dirección|Departamento)\s+(?:de|del|la|las|los)?\s*"
            rf"{_CAPITALIZED}(?:\s+(?:de|del|la|las|los|y|e|{_CAPITALIZED})){{0,5}}\b"
        ),
        0.94,
        "Denominación institucional introducida por una clase organizacional explícita.",
    ),
    (
        "collective",
        re.compile(
            r"\b(?:los|las)\s+(?:trabajadores|estudiantes|familiares|vecinos|militantes|"
            r"detenidos|exiliados|docentes|investigadores)\b",
            re.I,
        ),
        0.82,
        "Grupo de personas expresado mediante una referencia nominal explícita.",
    ),
)

_SPACE_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "place",
        re.compile(
            rf"\b(?:ciudad|provincia|localidad|barrio|partido|departamento|municipio)\s+de\s+"
            rf"{_CAPITALIZED_PHRASE}\b"
        ),
        0.94,
        "Topónimo introducido por una clase espacial explícita.",
    ),
    (
        "building",
        re.compile(
            rf"\b(?:sede|edificio|cárcel|comisaría|hospital|escuela|universidad)"
            rf"\s+(?:de|del|la)?\s*"
            rf"{_CAPITALIZED_PHRASE}\b"
        ),
        0.88,
        "Espacio institucional o edificio introducido por un patrón explícito.",
    ),
)

_EVENT_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "event",
        re.compile(
            rf"\b(?i:golpe de Estado|huelga|manifestación|reunión|operativo|elección|juicio|"
            rf"detención|allanamiento|acto|congreso|asamblea)(?:\s+{_CAPITALIZED}){{0,3}}\b"
        ),
        0.86,
        "Construcción nominal que designa un acontecimiento explícito.",
    ),
)

_ACTION_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "process",
        re.compile(
            r"\b(?:investigación|persecución|organización|movilización|censura|represión|"
            r"vigilancia|clasificación|archivo|depuración|intervención|exilio|resistencia)"
            r"(?:\s+(?:política|social|documental|administrativa|estatal|clandestina))?\b",
            re.I,
        ),
        0.82,
        "Sustantivo de acción o proceso incluido en el vocabulario conservador del proveedor.",
    ),
)

_WORK_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "quoted_work",
        re.compile(r"[“\"]([^“”\"\n]{3,160})[”\"]"),
        0.9,
        "Secuencia entrecomillada tratada como posible título de obra.",
    ),
)


# DISC-03 conserva todas las versiones locales previas para reproducibilidad.
# RC69 agrega local_rules_v5 después de comprobar que una configuración persistida
# podía seguir ejecutando v3 aunque la aplicación ya tuviera reglas más nuevas.
_LOCAL_RULES_VERSIONS = ("local_rules_v1", "local_rules_v2", "local_rules_v3", "local_rules_v4", "local_rules_v5")

_TIME_PATTERNS_V2: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    _TIME_PATTERNS[0],
    _TIME_PATTERNS[1],
    (
        "year",
        re.compile(r"\b(?:18|19|20)\d{2}\b(?!\s*[/.-]\s*\d)"),
        0.95,
        "Año de cuatro cifras fuera de un identificador numérico compuesto.",
    ),
    _TIME_PATTERNS[3],
    _TIME_PATTERNS[4],
    (
        "temporal_expression",
        re.compile(r"\b(?:ayer|hoy|mañana|anteayer)\b", re.I),
        0.88,
        "Expresión temporal relativa explícita.",
    ),
    (
        "temporal_expression",
        re.compile(
            r"\b(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)\b",
            re.I,
        ),
        0.88,
        "Día de la semana explícito.",
    ),
)

_ACTOR_CAPTURE_PATTERNS_V2: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "person",
        re.compile(
            rf"\b(?i:según|declaró|declaró ante|testimonio de|firmado por|suscripto por)\s+"
            rf"({_CAPITALIZED}(?:\s+{_CAPITALIZED}){{1,3}})\b"
        ),
        0.88,
        "Nombre propio de persona en un contexto lingüístico explícito de atribución o firma.",
    ),
    (
        "organization",
        re.compile(
            r"\b(?i:agentes|personal|miembros|integrantes)\s+de\s+(?i:la|el)\s+"
            r"([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ0-9.-]{2,14})\b"
        ),
        0.88,
        "Sigla institucional en un contexto explícito de pertenencia organizacional.",
    ),
)

_SPACE_CAPTURE_PATTERNS_V2: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "place",
        re.compile(
            rf"\b(?i:viajó|viajo|llegó|llego|regresó|regreso|volvió|volvio|residió|residio|nació|nacio)"
            rf"\s+(?i:a|en|desde)\s+({_CAPITALIZED_PHRASE})\b"
        ),
        0.86,
        "Topónimo propuesto por un contexto espacial explícito de desplazamiento o residencia.",
    ),
)

_EVENT_PATTERNS_V2: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "event",
        re.compile(
            rf"\b(?i:golpe de Estado|huelga|reunión|operativo|elección|juicio|detención|"
            rf"allanamiento|congreso|asamblea)(?:\s+(?:{_CAPITALIZED}|(?i:general|estudiantil|"
            rf"policial|militar|clandestina|clandestino|pública|publica|público|publico))){{0,3}}\b"
        ),
        0.86,
        "Construcción nominal acotada que designa un acontecimiento explícito.",
    ),
    (
        "event",
        re.compile(
            r"\bmanifestación(?!\s+de\s+interés)(?:\s+(?:estudiantil|general|pública|publica))?\b",
            re.I,
        ),
        0.86,
        "Manifestación como acontecimiento, excluyendo la fórmula administrativa de interés.",
    ),
    (
        "event",
        re.compile(
            r"\bacto(?!\s+administrativo)(?:\s+(?:público|publico|político|politico|conmemorativo))?\b",
            re.I,
        ),
        0.84,
        "Acto como acontecimiento, excluyendo la categoría jurídica de acto administrativo.",
    ),
)

_ACTION_PATTERNS_V2: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "process",
        re.compile(
            r"\b(?:investigación|persecución|organización|movilización|censura|represión|"
            r"vigilancia|clasificación|depuración|intervención|exilio|resistencia)"
            r"(?:\s+(?:política|social|documental|administrativa|estatal|clandestina))?\b",
            re.I,
        ),
        0.82,
        "Sustantivo de acción o proceso incluido en el vocabulario conservador revisado.",
    ),
    (
        "action",
        re.compile(r"\b(?:clasificar|vigilar|reprimir|perseguir|censurar|archivar)\b", re.I),
        0.78,
        "Infinitivo que designa una acción explícita del vocabulario conservador revisado.",
    ),
)

_WORK_CAPTURE_PATTERNS_V2: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "quoted_work",
        re.compile(
            r"\b(?i:obra|película|pelicula|documental|libro|informe|artículo|articulo|poema|"
            r"canción|cancion|publicación|publicacion|revista)"
            r"(?:\s+(?i:titulada|titulado))?\s*[“\"]([^“”\"\n]{3,160})[”\"]"
        ),
        0.93,
        "Título entrecomillado introducido por una clase explícita de obra o publicación.",
    ),
)


# DISC-03 RC67: v3 is derived from an audit over a real 138-document export and
# a real audiovisual transcript. The real corpus itself is deliberately not
# embedded in the repository; only generalized, synthetic regression patterns
# are kept here and in the evaluation corpus.
_WEEKDAY_WORDS = "lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo"

_ABBREVIATED_YEAR_SEQUENCE_V3 = re.compile(
    r"\b(?:18|19|20)\d{2}(?:\s*[-/]\s*\d{2})+\b"
)
_MODEL_OR_IDENTIFIER_BEFORE_YEAR_V3 = re.compile(
    r"(?i)(?:modelo|equipo\s+modelo|expediente|legajo|código|codigo|identificador)\s*$"
)
_WEEKDAY_V3 = re.compile(rf"\b(?:{_WEEKDAY_WORDS})\b", re.I)
_RELATIVE_DAY_V3 = re.compile(r"\b(?:ayer|hoy|mañana|anteayer)\b", re.I)

# New v3 contextual captures deliberately require ordinary title-case tokens.
# Existing v1/v2 patterns remain available for all-caps OCR and explicit classes.
_PERSON_TOKEN_MIXED_V3 = r"[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ'’-]+"
_PERSON_NAME_MIXED_V3 = rf"{_PERSON_TOKEN_MIXED_V3}(?:[ \t]+{_PERSON_TOKEN_MIXED_V3}){{0,3}}"
_PERSON_NAME_MULTI_MIXED_V3 = rf"{_PERSON_TOKEN_MIXED_V3}(?:[ \t]+{_PERSON_TOKEN_MIXED_V3}){{1,3}}"
_PLACE_NAME_MIXED_V3 = (
    rf"{_PERSON_TOKEN_MIXED_V3}"
    rf"(?:[ \t]+(?:de|del|la|las|los|y|e|{_PERSON_TOKEN_MIXED_V3})){{0,4}}"
)

_ACTOR_CAPTURE_PATTERNS_V3: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "person",
        re.compile(
            rf"\b(?i:conocí\s+a|conoci\s+a|conocimos\s+a|conoció\s+a|conocio\s+a|"
            rf"entrevisté\s+a|entreviste\s+a|entrevistó\s+a|entrevisto\s+a|junto\s+con)[ \t]+"
            rf"({_PERSON_NAME_MIXED_V3})\b"
        ),
        0.89,
        "Nombre propio de persona introducido por un contexto testimonial explícito.",
    ),
    (
        "person",
        re.compile(
            rf"\b({_PERSON_NAME_MULTI_MIXED_V3})[ \t]+"
            rf"(?i:declaró|declaro|manifestó|manifesto|informó|informo|testificó|testifico|"
            rf"firmó|firmo|suscribió|suscribio)\b"
        ),
        0.89,
        "Nombre propio de persona seguido por un verbo explícito de declaración o firma.",
    ),
)

_SPACE_CAPTURE_PATTERNS_V3: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "place",
        re.compile(rf"\b(?i:acá|aca|aquí|aqui)[ \t]+en[ \t]+({_PLACE_NAME_MIXED_V3})\b"),
        0.88,
        "Topónimo introducido por una referencia deíctica espacial explícita.",
    ),
    (
        "place",
        re.compile(
            rf"\b(?i:envió|envio|envían|envian|enviado|enviada|enviados|enviadas|saluda|escribe|llegó|llego|vino|regresó|regreso|"
            rf"volvió|volvio|procedente|noticias?)[^.!?\n]{{0,48}}?\b(?i:desde)[ \t]+"
            rf"({_PLACE_NAME_MIXED_V3})\b"
        ),
        0.87,
        "Topónimo respaldado por un contexto explícito de procedencia o comunicación.",
    ),
    (
        "place",
        re.compile(
            rf"\b(?i:desde)[ \t]+({_PLACE_NAME_MIXED_V3})[ \t]+"
            rf"(?i:expresa|dice|escribe|informa|saluda|envía|envia|comunica)\b"
        ),
        0.87,
        "Topónimo respaldado por un contexto explícito de procedencia o comunicación.",
    ),
    (
        "place",
        re.compile(rf"\b(?i:barrio)[ \t]+({_PLACE_NAME_MIXED_V3})\b"),
        0.9,
        "Nombre de barrio introducido por una clase espacial explícita.",
    ),
    (
        "place",
        re.compile(
            rf"\b(?i:de)[ \t]+({_PLACE_NAME_MIXED_V3})[ \t]+"
            rf"(?i:venía|venia|vino|llegó|llego|regresó|regreso|volvió|volvio)\b"
        ),
        0.86,
        "Topónimo propuesto por un contexto explícito de procedencia y desplazamiento.",
    ),
)

_EVENT_PATTERNS_V3: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    *_EVENT_PATTERNS_V2,
    (
        "event",
        re.compile(
            r"\bmarcha\s+(?:estudiantil|obrera|sindical|política|politica|pública|publica)\b",
            re.I,
        ),
        0.85,
        "Marcha designada explícitamente como acontecimiento colectivo.",
    ),
)

_ACTION_CONTEXT_PATTERNS_V3: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "action",
        re.compile(
            r"\b(clasificar|clasificó|clasifico|archivar|archivó|archivo)\s+"
            r"(?:el|los?|las?|una?|unos?|unas?)?\s*"
            r"(?:documentos?|expedientes?|fichas?|legajos?|material(?:es)?|información|informacion)\b",
            re.I,
        ),
        0.82,
        "Acción documental explícita con un objeto compatible.",
    ),
    (
        "action",
        re.compile(
            r"\b(vigilar|vigiló|vigilo|perseguir|persiguió|persiguio|reprimir|reprimió|reprimio|"
            r"censurar|censuró|censuro)\s+(?:a\s+)?(?:los?|las?)?\s*"
            r"(?:militantes?|trabajadores?|estudiantes?|manifestantes?|organizaciones?|sindicatos?|"
            r"actividades?|manifestaciones?|huelgas?|protestas?)\b",
            re.I,
        ),
        0.82,
        "Acción de vigilancia, persecución, represión o censura con un objetivo explícito.",
    ),
)

_QUOTED_SPAN_PATTERNS_V3: tuple[re.Pattern[str], ...] = (
    re.compile(r'"([^"\n]{2,180})"'),
    re.compile(r"“([^”\n]{2,180})”"),
)
_WORK_CLASS_PREFIX_V3 = re.compile(
    r"(?i)(?:obra|pieza|comedia|drama|película|pelicula|film|documental|libro|informe|artículo|articulo|poema|"
    r"canción|cancion|publicación|publicacion|revista|diario|novela|cuento|sainete|zarzuela|"
    r"opereta|ballet)\b[^.!?\n\"“”]{0,80}$"
)
_WORK_VERB_PREFIX_V3 = re.compile(
    r"(?i)(?:estren(?:ó|o|ará|ara|aron)|represent(?:ó|o|ará|ara|aron)|"
    r"present(?:ó|o|ará|ara|aron)|escenific(?:ó|o|aron)|ley(?:ó|o|eron)|"
    r"public(?:ó|o|aron)|edit(?:ó|o|aron)|puesta(?:\s+en\s+escena)?(?:\s+de)?)"
    r"\b[^.!?\n\"“”]{0,65}$"
)
_WORK_LIST_CUE_V3 = re.compile(
    r"(?i)(?:repertorio|teatro\s+leído|teatro\s+leido|dirección\s+de\s+teatro|"
    r"direccion\s+de\s+teatro|títulos\s+escogidos|titulos\s+escogidos|"
    r"obras?\s+representadas|obras?\s+bajo\s+el\s+título|obras?\s+bajo\s+el\s+titulo|"
    r"terna\s+de\s+obras|programa(?:\s+[^.!?\n]{0,40})?\s+dividido\s+en)"
    r"\b[^.!?\n\"“”]{0,150}$"
)
_WORK_SUFFIX_CUE_V3 = re.compile(
    rf"^\s*(?:,\s*)?(?:de|por)\s+{_CAPITALIZED}(?:\s+{_CAPITALIZED}){{0,3}}\b"
)
_WORK_SUFFIX_TYPE_V3 = re.compile(
    r"^\s*(?:,|—|-)?\s*(?:obra|pieza|libro|poema|canción|cancion|novela|cuento|"
    r"documental|película|pelicula|sainete)\b",
    re.I,
)
_WORK_SUFFIX_TYPE_V4 = re.compile(
    r"^[ \t]*(?:,|—|-)?[ \t]*(?:obra|pieza|libro|poema|canción|cancion|novela|cuento|"
    r"documental|película|pelicula|sainete)\b",
    re.I,
)
_NON_WORK_PREFIX_V3 = re.compile(
    r"(?i)(?:grupo|conjunto|biblioteca|colegio|club|sala|local|instituto|escuela|centro|"
    r"apodado|apodada|conocido\s+como|conocida\s+como|denominado|denominada|expresión|expresion)\s*$"
)
_NON_WORK_CONTEXT_V3 = re.compile(
    r"(?i)\b(?:grupo|conjunto|biblioteca|colegio|club|instituto|escuela|centro|"
    r"jardín\s+de\s+infantes|jardin\s+de\s+infantes|frigoríficos?|frigorificos?|"
    r"peña(?:-[^.!?\n\"“”]{0,30})?|teatro(?:\s+(?:independiente|experimental|vocacional|"
    r"universitario|infantil|estudio))?)\b[^.!?\n\"“”]{0,64}$"
)
_NON_WORK_EXACT_V3 = re.compile(
    r"(?i)\b(?:grupo|teatro|conjunto|biblioteca|jardín\s+de\s+infantes|"
    r"jardin\s+de\s+infantes|colegio|club|frigorífico|frigorifico)\b"
)
_WORK_VENUE_PREFIX_V3 = re.compile(r"(?i)(?:teatro|sala)\s*$")
_WORK_THEATRICAL_CLASS_V3 = re.compile(r"(?i)obra\s+de\s+teatro\s*$")
_DIRECT_SPEECH_PREFIX_V3 = re.compile(
    r"(?i)(?:dijo|dice|expresó|expreso|agregó|agrego|respondió|respondio|preguntó|pregunto|"
    r"contestó|contesto|señaló|senalo|manifestó|manifesto|declaró|declaro)\s*:?\s*$"
)


# DISC-03 RC68: v4 tightens candidate precision and entity boundaries after
# manual review of RC67 on the pilot corpus. v1-v3 remain immutable historical
# versions so existing profiles, runs, and continuity operations stay reproducible.
_V4_NAME_WORD = (
    r"(?!(?i:de|del|la|las|los|y|e)\b)"
    r"[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑa-záéíóúüñ0-9'’]+"
)
_V4_INITIAL = r"[A-ZÁÉÍÓÚÜÑ]\."
_V4_INITIAL_SURNAME = rf"[A-ZÁÉÍÓÚÜÑ]\.{_V4_NAME_WORD}"
_V4_NAME_TOKEN = rf"(?:{_V4_INITIAL_SURNAME}|{_V4_INITIAL}|{_V4_NAME_WORD})"
_V4_NAME_CONNECTOR = r"(?:de|del|la|las|los|y|e)"
_V4_NAME_CHAIN = (
    rf"{_V4_NAME_TOKEN}"
    rf"(?:[ \t]+(?:(?:{_V4_NAME_CONNECTOR})[ \t]+)*{_V4_NAME_TOKEN}){{0,7}}"
)
_V4_NAME_CHAIN_MULTI = (
    rf"{_V4_NAME_TOKEN}"
    rf"(?:[ \t]+(?:(?:{_V4_NAME_CONNECTOR})[ \t]+)*{_V4_NAME_TOKEN}){{1,7}}"
)
_V4_ORG_CHAIN = (
    rf"(?:(?:{_V4_NAME_CONNECTOR})\s+)*{_V4_NAME_TOKEN}"
    rf"(?:\s+(?:(?:{_V4_NAME_CONNECTOR})\s+)*{_V4_NAME_TOKEN}){{0,9}}"
)
_PERSON_TITLE_V4 = (
    r"(?:Sr\.?|Sra\.?|Srta\.?|Dr\.?|Dra\.?|doctor|doctora|presidente|presidenta|"
    r"ministro|ministra|general|coronel|profesor|profesora)"
)
_ACTOR_PATTERNS_V4: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "person",
        re.compile(rf"\b{_PERSON_TITLE_V4}[ \t]+{_V4_NAME_CHAIN}(?![A-ZÁÉÍÓÚÜÑ]\.)"),
        0.93,
        "Nombre propio con tratamiento o cargo; conserva partículas e iniciales completas y corta antes de separadores de procedencia.",
    ),
    (
        "organization",
        re.compile(
            rf"\b(?:Ministerio|Secretaría|Universidad|Partido|Sindicato|Comisión|Junta|"
            rf"Asociación|Fundación|Instituto|Dirección|Departamento)\s+{_V4_ORG_CHAIN}"
        ),
        0.95,
        "Denominación institucional completa; las partículas internas no consumen el límite de palabras significativas.",
    ),
    _ACTOR_PATTERNS[2],
)

_ACTOR_CAPTURE_PATTERNS_V4: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "person",
        re.compile(
            rf"\b(?i:según|declaró|declaro|declaró ante|declaro ante|testimonio de|firmado por|suscripto por)\s+"
            rf"({_V4_NAME_CHAIN})(?![A-ZÁÉÍÓÚÜÑ]\.)"
        ),
        0.9,
        "Nombre propio completo en un contexto explícito de atribución o firma.",
    ),
    _ACTOR_CAPTURE_PATTERNS_V2[1],
    (
        "person",
        re.compile(
            rf"\b(?i:conocí\s+a|conoci\s+a|conocimos\s+a|conoció\s+a|conocio\s+a|"
            rf"entrevisté\s+a|entreviste\s+a|entrevistó\s+a|entrevisto\s+a|junto\s+con)[ \t]+"
            rf"({_V4_NAME_CHAIN})(?![A-ZÁÉÍÓÚÜÑ]\.)"
        ),
        0.9,
        "Nombre propio completo introducido por un contexto testimonial explícito.",
    ),
    (
        "person",
        re.compile(
            rf"\b({_V4_NAME_CHAIN_MULTI})[ \t]+"
            rf"(?i:declaró|declaro|manifestó|manifesto|informó|informo|testificó|testifico|"
            rf"firmó|firmo|suscribió|suscribio)\b"
        ),
        0.9,
        "Nombre propio completo seguido por un verbo explícito de declaración o firma.",
    ),
)

_WORK_CLASS_PREFIX_V4 = re.compile(
    r"(?i)\b(?:obra|pieza|comedia|drama|película|pelicula|film|documental|libro|informe|"
    r"artículo|articulo|poema|canción|cancion|publicación|publicacion|revista|diario|novela|"
    r"cuento|sainete|zarzuela|opereta|ballet|sketch)"
    r"(?:\s+(?:de|del|por)\s+[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑa-záéíóúüñ'’]+"
    r"(?:[ \t]+[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑa-záéíóúüñ'’]+){0,4})?"
    r"(?:\s+(?:titulad[oa]|llamad[oa]|antes\s+mencionad[oa]))?[ \t,:-]*$"
)
_WORK_VERB_PREFIX_V4 = re.compile(
    r"(?i)\b(?:estreno\s+de|estren(?:ó|o|ará|ara|aron)|represent(?:ó|o|ará|ara|aron|ar)|"
    r"present(?:ó|o|ará|ara|aron|ar)(?:\s+con)?|escenific(?:ó|o|aron|ar)|"
    r"ley(?:ó|o|eron)|public(?:ó|o|aron)|edit(?:ó|o|aron)|montaje\s+de|"
    r"puesta\s+en\s+escena\s+de|puesta\s+de)"
    r"(?:[ \t]+(?:la|el|una|un|esta|esa|su|nueva|nuevo|obra|pieza|trabajo|espectáculo|espectaculo))*"
    r"[ \t,:-]*$"
)
_WORK_LIST_CUE_V4 = re.compile(
    r"(?i)\b(?:repertorio|teatro\s+leído|teatro\s+leido|títulos\s+escogidos|titulos\s+escogidos|"
    r"obras?\s+presentadas|obras?\s+representadas|últimas\s+obras\s+dirigidas|ultimas\s+obras\s+dirigidas|"
    r"roles?\s+protagónicos?|roles?\s+protagonicos?|programa(?:\s+[^.!?\n]{0,40})?\s+dividido\s+en)"
    r"\b[^.!?\n]{0,160}$"
)

_NON_WORK_PREFIX_V4 = re.compile(
    r"(?i)(?:grupo|conjunto|teatro(?:\s+independiente)?|biblioteca(?:\s+popular)?|colegio|club|sala|local|instituto|escuela|centro|"
    r"apodado|apodada|conocido\s+como|conocida\s+como|denominado|denominada|"
    r"expresión|expresion|género\s+de|genero\s+de|técnica\s+del|tecnica\s+del|"
    r"manifestación\s+de|manifestacion\s+de)\s*$"
)
_WORK_CONTEXT_V4 = re.compile(
    r"(?i)\b(?:obra|pieza|repertorio|estreno|puesta(?:\s+en\s+escena)?|montaje|"
    r"roles?\s+protagónicos?|roles?\s+protagonicos?|labor\s+actoral|libro|poema|"
    r"diario|revista|publicación|publicacion|novela|cuento|film|película|pelicula|canción|"
    r"cancion|programa|representación|representacion|representad[oa]s?|escenificación|"
    r"escenificacion)\b"
)
_SPEECH_AFTER_WORK_CLASS_V4 = re.compile(
    r"(?i)\b(?:dijo|dice|expresó|expreso|agregó|agrego|respondió|respondio|preguntó|"
    r"pregunto|contestó|contesto|señaló|senalo|manifestó|manifesto|declaró|declaro)\b"
)


@dataclass(slots=True)
class DiscoveryProfileValues:
    name: str
    description: str | None = None
    families: tuple[str, ...] = DISCOVERY_FAMILIES[:-1]
    include_object_types: tuple[str, ...] = ()
    include_object_review_statuses: tuple[str, ...] = ()
    include_page_review_statuses: tuple[str, ...] = DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES
    minimum_confidence: float = 0.75
    provider_key: str = DISCOVERY_PROVIDER_KEY
    provider_version: str = DISCOVERY_PROVIDER_VERSION


@dataclass(frozen=True, slots=True)
class DiscoveryRunSummary:
    run_id: str
    profile_id: str
    profile_name: str
    object_count: int
    candidate_count: int
    family_counts: dict[str, int]
    corpus_state_sha256: str
    parameters_sha256: str


@dataclass(frozen=True, slots=True)
class DiscoveryRunRow:
    run_id: str
    profile_id: str
    profile_name: str
    status: str
    provider_key: str
    provider_version: str
    object_count: int
    candidate_count: int
    family_counts: dict[str, int]
    page_review_statuses: tuple[str, ...]
    corpus_state_sha256: str
    parameters_sha256: str
    created_by: str
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class DiscoveryCandidateRow:
    candidate_id: str
    run_id: str
    profile_id: str
    exact_text: str
    semantic_family: str
    family_label: str
    suggested_subtype: str
    confidence: float | None
    explanation: str
    source_key: str | None
    original_filename: str
    page_number: int
    editable_object_id: str
    editable_page_id: str
    object_revision_number: int
    page_revision_number: int
    start_offset: int
    end_offset: int
    context_before: str
    context_after: str
    provider_key: str
    provider_version: str
    method: str
    parameters_sha256: str
    status: str
    decision_count: int
    latest_decision_type: str | None
    effective_text: str
    effective_family: str
    effective_subtype: str
    is_stale: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class _Detection:
    start: int
    end: int
    exact_text: str
    family: str
    subtype: str
    confidence: float
    explanation: str


def family_label(value: str) -> str:
    return _FAMILY_LABELS.get(value, value)


def _clean_text(value: str, *, field: str, maximum: int) -> str:
    clean = " ".join((value or "").split())
    if not clean:
        raise ValueError(f"{field} no puede quedar vacío")
    if len(clean) > maximum:
        raise ValueError(f"{field} no puede superar {maximum} caracteres")
    return clean


def _normalize_surface(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_marks.casefold().split()).strip(" .,:;()[]{}\"'“”")


def _validate_profile(
    values: DiscoveryProfileValues,
    *,
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
) -> DiscoveryProfileValues:
    families = tuple(value for value in DISCOVERY_FAMILIES if value in set(values.families))
    if not families:
        raise ValueError("El perfil debe incluir al menos una familia semántica")
    invalid_families = set(values.families) - set(DISCOVERY_FAMILIES)
    if invalid_families:
        raise ValueError(
            "Familias semánticas inválidas: " + ", ".join(sorted(invalid_families))
        )
    invalid_object_statuses = set(values.include_object_review_statuses) - set(
        OBJECT_REVIEW_STATUSES
    )
    if invalid_object_statuses:
        raise ValueError(
            "Estados de revisión de objeto inválidos: "
            + ", ".join(sorted(invalid_object_statuses))
        )
    page_scope = validate_automatic_quality_scope(
        values.include_page_review_statuses,
        broader_scope_confirmed=broader_quality_scope_confirmed,
        confirmation_reason=quality_scope_reason,
    )
    confidence = float(values.minimum_confidence)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("La confianza mínima debe estar entre 0 y 1")
    contract = provider_contract(values.provider_key, values.provider_version)
    unsupported = set(families) - set(contract.supported_families)
    if unsupported:
        raise ValueError(
            f"{contract.key}@{contract.version} no admite las familias: "
            + ", ".join(sorted(unsupported))
        )
    return DiscoveryProfileValues(
        name=_clean_text(values.name, field="El nombre del perfil", maximum=200),
        description=(
            " ".join(values.description.split())
            if values.description and values.description.strip()
            else None
        ),
        families=families,
        include_object_types=tuple(sorted(set(values.include_object_types))),
        include_object_review_statuses=tuple(
            value
            for value in OBJECT_REVIEW_STATUSES
            if value in set(values.include_object_review_statuses)
        ),
        include_page_review_statuses=page_scope.page_review_statuses,
        minimum_confidence=confidence,
        provider_key=values.provider_key,
        provider_version=values.provider_version,
    )


def profile_values(profile: DiscoveryProfile) -> DiscoveryProfileValues:
    return DiscoveryProfileValues(
        name=profile.name,
        description=profile.description,
        families=tuple(profile.families_json or ()),
        include_object_types=tuple(profile.include_object_types_json or ()),
        include_object_review_statuses=tuple(
            profile.include_object_review_statuses_json or ()
        ),
        include_page_review_statuses=tuple(profile.include_page_review_statuses_json or ()),
        minimum_confidence=float(profile.minimum_confidence),
        provider_key=profile.provider_key,
        provider_version=profile.provider_version,
    )


def discovery_profile_authorization_parameters(
    profile: DiscoveryProfile,
) -> dict[str, Any]:
    payload = asdict(profile_values(profile))
    for key in (
        "families",
        "include_object_types",
        "include_object_review_statuses",
        "include_page_review_statuses",
    ):
        payload[key] = list(payload[key])
    contract = provider_contract(profile.provider_key, profile.provider_version)
    payload["method"] = contract.method
    if contract.model_name is not None:
        payload["model_name"] = contract.model_name
        payload["model_version"] = contract.model_version
    payload["analysis_quality"] = quality_scope_snapshot(
        analysis_kind="open_discovery",
        page_review_statuses=profile.include_page_review_statuses_json or (),
    )
    return payload


def profile_snapshot(profile: DiscoveryProfile) -> dict[str, Any]:
    payload = discovery_profile_authorization_parameters(profile)
    payload.update({"id": profile.id, "revision": profile.revision})
    return payload


def save_discovery_profile(
    session: Session,
    *,
    project_id: str,
    values: DiscoveryProfileValues,
    changed_by: str,
    profile_id: str | None = None,
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
    quality_scope_source: str = "api",
) -> DiscoveryProfile:
    actor = _clean_text(changed_by, field="La persona responsable", maximum=200)
    clean = _validate_profile(
        values,
        broader_quality_scope_confirmed=broader_quality_scope_confirmed,
        quality_scope_reason=quality_scope_reason,
    )
    profile = session.get(DiscoveryProfile, profile_id) if profile_id else None
    if profile is None:
        profile = session.scalar(
            select(DiscoveryProfile).where(
                DiscoveryProfile.project_id == project_id,
                DiscoveryProfile.name == clean.name,
            )
        )
    now = utc_now()
    if profile is None:
        profile = DiscoveryProfile(
            id=new_id(),
            project_id=project_id,
            name=clean.name,
            description=clean.description,
            provider_key=clean.provider_key,
            provider_version=clean.provider_version,
            families_json=list(clean.families),
            include_object_types_json=list(clean.include_object_types),
            include_object_review_statuses_json=list(
                clean.include_object_review_statuses
            ),
            include_page_review_statuses_json=list(clean.include_page_review_statuses),
            minimum_confidence=clean.minimum_confidence,
            lifecycle_status="active",
            created_by=actor,
            created_at=now,
            updated_by=actor,
            updated_at=now,
            revision=1,
        )
        session.add(profile)
    else:
        if profile.project_id != project_id:
            raise ValueError("El perfil pertenece a otro proyecto")
        if profile.lifecycle_status != "active":
            raise ValueError("El perfil está archivado")
        duplicate = session.scalar(
            select(DiscoveryProfile).where(
                DiscoveryProfile.project_id == project_id,
                DiscoveryProfile.name == clean.name,
                DiscoveryProfile.id != profile.id,
            )
        )
        if duplicate is not None:
            raise ValueError(f"Ya existe otro perfil llamado {clean.name}")
        profile.name = clean.name
        profile.description = clean.description
        profile.provider_key = clean.provider_key
        profile.provider_version = clean.provider_version
        profile.families_json = list(clean.families)
        profile.include_object_types_json = list(clean.include_object_types)
        profile.include_object_review_statuses_json = list(
            clean.include_object_review_statuses
        )
        profile.include_page_review_statuses_json = list(
            clean.include_page_review_statuses
        )
        profile.minimum_confidence = clean.minimum_confidence
        profile.updated_by = actor
        profile.updated_at = now
        profile.revision += 1
    session.flush()
    record_automatic_analysis_authorization(
        session,
        project_id=project_id,
        analysis_kind="open_discovery",
        page_review_statuses=clean.include_page_review_statuses,
        broader_scope_confirmed=broader_quality_scope_confirmed,
        confirmed_by=actor,
        confirmation_reason=quality_scope_reason,
        source=quality_scope_source,
        target_type="discovery_profile",
        target_id=profile.id,
        parameters=discovery_profile_authorization_parameters(profile),
    )
    return profile


def discovery_profile_rows(
    session: Session, *, project_id: str, include_archived: bool = False
) -> list[DiscoveryProfile]:
    query = select(DiscoveryProfile).where(DiscoveryProfile.project_id == project_id)
    if not include_archived:
        query = query.where(DiscoveryProfile.lifecycle_status == "active")
    return session.scalars(query.order_by(DiscoveryProfile.name, DiscoveryProfile.id)).all()


def resolve_discovery_profile(
    session: Session, *, project_id: str, profile_ref: str
) -> DiscoveryProfile:
    profile = session.scalar(
        select(DiscoveryProfile).where(
            DiscoveryProfile.project_id == project_id,
            (DiscoveryProfile.id == profile_ref) | (DiscoveryProfile.name == profile_ref),
        )
    )
    if profile is None:
        raise ValueError(f"Perfil de descubrimiento inexistente: {profile_ref}")
    if profile.lifecycle_status != "active":
        raise ValueError(f"El perfil de descubrimiento está archivado: {profile.name}")
    return profile


def _require_profile_authorization(
    session: Session, *, project_id: str, profile: DiscoveryProfile
) -> Any:
    return require_automatic_analysis_authorization(
        session,
        project_id=project_id,
        analysis_kind="open_discovery",
        page_review_statuses=tuple(profile.include_page_review_statuses_json or ()),
        target_type="discovery_profile",
        target_id=profile.id,
        parameters=discovery_profile_authorization_parameters(profile),
        remediation=(
            "Guardá nuevamente el perfil de descubrimiento para registrar su alcance "
            "y sus parámetros funcionales."
        ),
    )


def _candidate_from_match(
    text: str,
    *,
    match: re.Match[str],
    family: str,
    subtype: str,
    confidence: float,
    explanation: str,
    capture_group: int | None = None,
) -> _Detection | None:
    start, end = match.span(capture_group or 0)
    exact = text[start:end]
    if not exact.strip():
        return None
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    exact = text[start:end]
    return _Detection(
        start=start,
        end=end,
        exact_text=exact,
        family=family,
        subtype=subtype,
        confidence=confidence,
        explanation=explanation,
    )


def _pattern_detections(
    text: str,
    *,
    family: str,
    patterns: Sequence[tuple[str, re.Pattern[str], float, str]],
    quoted_capture: bool = False,
) -> Iterable[_Detection]:
    for subtype, pattern, confidence, explanation in patterns:
        for match in pattern.finditer(text):
            detection = _candidate_from_match(
                text,
                match=match,
                family=family,
                subtype=subtype,
                confidence=confidence,
                explanation=explanation,
                capture_group=1 if quoted_capture else None,
            )
            if detection is not None:
                yield detection



def _make_detection(
    text: str,
    *,
    start: int,
    end: int,
    family: str,
    subtype: str,
    confidence: float,
    explanation: str,
) -> _Detection | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    return _Detection(
        start=start,
        end=end,
        exact_text=text[start:end],
        family=family,
        subtype=subtype,
        confidence=confidence,
        explanation=explanation,
    )


def _time_detections_v3(text: str) -> list[_Detection]:
    detections: list[_Detection] = []
    # Explicit full dates, historical periods and explicit "entre X y Y" intervals.
    for pattern in (_TIME_PATTERNS[0], _TIME_PATTERNS[1], _TIME_PATTERNS[3], _TIME_PATTERNS[4]):
        detections.extend(_pattern_detections(text, family="time", patterns=(pattern,)))

    abbreviated_spans: list[tuple[int, int]] = []
    for match in _ABBREVIATED_YEAR_SEQUENCE_V3.finditer(text):
        detection = _make_detection(
            text,
            start=match.start(),
            end=match.end(),
            family="time",
            subtype="interval",
            confidence=0.96,
            explanation="Secuencia abreviada de años con año inicial explícito.",
        )
        if detection is not None:
            detections.append(detection)
            abbreviated_spans.append((detection.start, detection.end))

    for match in re.finditer(r"\b(?:18|19|20)\d{2}\b", text):
        start, end = match.span()
        if any(a <= start and end <= b for a, b in abbreviated_spans):
            continue
        before = text[max(0, start - 48):start]
        after = text[end:min(len(text), end + 12)]
        if _MODEL_OR_IDENTIFIER_BEFORE_YEAR_V3.search(before):
            continue
        # A one-digit suffix such as 1976/4 is treated as an identifier, not a year range.
        if re.match(r"\s*[/.-]\s*\d(?!\d)", after):
            continue
        detection = _make_detection(
            text,
            start=start,
            end=end,
            family="time",
            subtype="year",
            confidence=0.95,
            explanation="Año de cuatro cifras fuera de un identificador numérico o modelo explícito.",
        )
        if detection is not None:
            detections.append(detection)

    for match in _RELATIVE_DAY_V3.finditer(text):
        exact = match.group(0)
        start, end = match.span()
        if exact.casefold() == "mañana":
            before = text[max(0, start - 40):start]
            after = text[end:min(len(text), end + 32)]
            if re.search(r"(?i)(?:\bla\s+|\bpor\s+la\s+|\ba\s+la\s+|\bturnos?\s+)$", before):
                continue
            if re.match(r"(?i)\s+y\s+tarde\b", after):
                continue
        detection = _make_detection(
            text,
            start=start,
            end=end,
            family="time",
            subtype="temporal_expression",
            confidence=0.88,
            explanation="Expresión temporal relativa explícita en un contexto compatible.",
        )
        if detection is not None:
            detections.append(detection)

    quoted_spans = [(start, end) for start, end, _ in _quoted_spans_v3(text)]
    weekday_matches = list(_WEEKDAY_V3.finditer(text))
    for match in weekday_matches:
        start, end = match.span()
        if any(a <= start and end <= b for a, b in quoted_spans):
            continue
        before = text[max(0, start - 64):start]
        after = text[end:min(len(text), end + 64)]
        temporal_context = bool(
            re.search(
                r"(?i)(?:\bfecha\s*[:,\-]?\s*|\bel\s+|\beste\s+|\bese\s+|\baquel\s+|"
                r"\bentre\s+el\s+|\btarde\s+del\s+|\bnoche\s+del\s+|\bdel\s+)$",
                before,
            )
            or re.match(r"(?i)\s*,?\s*\d{1,2}(?:\s+de\b|[/-]|\s+horas?\b)", after)
            or re.match(
                r"(?i)\s+(?:próxim[oa]s?|proxim[oa]s?|pasad[oa]s?|últim[oa]s?|ultim[oa]s?|venider[oa]s?)\b",
                after,
            )
        )
        if not temporal_context:
            nearby = text[max(0, start - 52):min(len(text), end + 72)]
            weekday_count = len(_WEEKDAY_V3.findall(nearby))
            temporal_context = weekday_count >= 2 and bool(
                re.search(
                    r"(?i)(?:\bel\b|\bentre\b|\bhoras?\b|\bpróxim|\bproxim|\búltim|\bultim|\bvenider|\d{1,2})",
                    nearby,
                )
            )
        if not temporal_context:
            continue
        detection = _make_detection(
            text,
            start=start,
            end=end,
            family="time",
            subtype="temporal_expression",
            confidence=0.89,
            explanation="Día de la semana dentro de un contexto temporal explícito.",
        )
        if detection is not None:
            detections.append(detection)
    return detections


def _quoted_spans_v3(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for pattern in _QUOTED_SPAN_PATTERNS_V3:
        for match in pattern.finditer(text):
            start, end = match.span(1)
            exact = text[start:end]
            if exact.strip():
                spans.append((start, end, exact))
    spans.sort(key=lambda row: (row[0], row[1]))
    dedup: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int]] = set()
    for row in spans:
        key = (row[0], row[1])
        if key not in seen:
            seen.add(key)
            dedup.append(row)
    return dedup


def _work_detections_v3(text: str) -> list[_Detection]:
    detections: list[_Detection] = []
    accepted_spans: list[tuple[int, int]] = []
    previous_quote_span: tuple[int, int] | None = None
    previous_quote_accepted = False
    for start, end, _exact in _quoted_spans_v3(text):
        # _quoted_spans_v3 returns the capture inside the quotes. Context cues
        # therefore exclude the opening/closing quote themselves.
        cue_start = start - 1 if start > 0 and text[start - 1] in {'"', '“'} else start
        cue_end = end + 1 if end < len(text) and text[end] in {'"', '”'} else end
        before = text[max(0, cue_start - 180):cue_start]
        after = text[cue_end:min(len(text), cue_end + 120)]
        immediate_before = text[max(0, cue_start - 72):cue_start]
        if _DIRECT_SPEECH_PREFIX_V3.search(immediate_before):
            continue
        if _NON_WORK_PREFIX_V3.search(immediate_before):
            continue
        work_class_match = _WORK_CLASS_PREFIX_V3.search(before)
        work_verb_match = _WORK_VERB_PREFIX_V3.search(before)
        work_list_match = _WORK_LIST_CUE_V3.search(before)
        work_matches = [match for match in (work_class_match, work_verb_match, work_list_match) if match]
        latest_work_cue = max((match.start() for match in work_matches), default=-1)
        non_work_context = _NON_WORK_CONTEXT_V3.search(immediate_before)
        non_work_start = (
            len(before) - len(immediate_before) + non_work_context.start()
            if non_work_context
            else -1
        )
        if non_work_context and latest_work_cue <= non_work_start:
            continue
        if _NON_WORK_EXACT_V3.search(_exact) and latest_work_cue < 0:
            continue
        if _WORK_VENUE_PREFIX_V3.search(immediate_before) and not _WORK_THEATRICAL_CLASS_V3.search(
            immediate_before
        ):
            continue
        coordinated_prefix = bool(re.search(r"[\"”]\s*(?:,|y|e|o)\s*$", immediate_before, re.I))
        coordinated_with_work = False
        if accepted_spans:
            previous_start, previous_end = accepted_spans[-1]
            between = text[previous_end:cue_start]
            coordinated_with_work = bool(re.fullmatch(r"\s*[\"”]?\s*(?:,|y|e|o)\s*", between, re.I))
        if coordinated_prefix and not coordinated_with_work and latest_work_cue < 0:
            continue
        strong = bool(
            work_class_match
            or work_verb_match
            or work_list_match
            or _WORK_SUFFIX_CUE_V3.search(after)
            or _WORK_SUFFIX_TYPE_V3.search(after)
            or coordinated_with_work
        )
        if not strong:
            continue
        detection = _make_detection(
            text,
            start=start,
            end=end,
            family="work",
            subtype="quoted_work",
            confidence=0.92,
            explanation="Título entrecomillado respaldado por un contexto explícito de obra, publicación o repertorio.",
        )
        if detection is not None:
            detections.append(detection)
            accepted_spans.append((cue_start, cue_end))
    return detections



def _work_detections_v4(text: str) -> list[_Detection]:
    detections: list[_Detection] = []
    for start, end, exact_raw in _quoted_spans_v3(text):
        exact = exact_raw.strip()
        words = re.findall(r"[A-ZÁÉÍÓÚÜÑa-záéíóúüñ0-9]+", exact)
        if not words or len(exact) > 100 or len(words) > 10:
            continue
        first_letter = next((char for char in exact if char.isalpha()), "")
        if first_letter and first_letter.islower():
            continue

        cue_start = start - 1 if start > 0 and text[start - 1] in {'"', '“'} else start
        cue_end = end + 1 if end < len(text) and text[end] in {'"', '”'} else end
        before = text[max(0, cue_start - 200):cue_start]
        after = text[cue_end:min(len(text), cue_end + 120)]
        immediate_before = text[max(0, cue_start - 72):cue_start]
        immediate_after = text[cue_end:min(len(text), cue_end + 72)]

        if _DIRECT_SPEECH_PREFIX_V3.search(immediate_before):
            continue
        if _NON_WORK_PREFIX_V4.search(immediate_before):
            continue
        # A quoted nickname inside a personal name is not a work title.
        if (
            re.search(r"[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ'’]+[ \t]+$", immediate_before)
            and re.match(r"[ \t]+[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ'’]+\b", immediate_after)
            and len(words) <= 3
        ):
            continue
        # Quotation after a bare determiner is usually a nickname or quoted label.
        if re.search(r"(?i)\b(?:el|la|los|las)[ \t]+$", immediate_before):
            continue

        class_near = bool(_WORK_CLASS_PREFIX_V4.search(before))
        verb_near = bool(_WORK_VERB_PREFIX_V4.search(before))
        list_near = bool(_WORK_LIST_CUE_V4.search(before))
        suffix_type = bool(_WORK_SUFFIX_TYPE_V4.search(after))
        suffix_author = bool(_WORK_SUFFIX_CUE_V3.search(after))
        author_with_work_context = suffix_author and bool(
            _WORK_CONTEXT_V4.search(before[-150:])
        )

        if not (class_near or verb_near or list_near or suffix_type or author_with_work_context):
            continue
        detection = _make_detection(
            text,
            start=start,
            end=end,
            family="work",
            subtype="quoted_work",
            confidence=0.95,
            explanation=(
                "Título entrecomillado conservado sólo cuando la cita está unida de forma directa "
                "a una clase de obra/publicación, una acción de representación o publicación, un "
                "repertorio explícito, una indicación de tipo o una autoría respaldada por contexto de obra."
            ),
        )
        if detection is not None:
            detections.append(detection)
    return detections


# RC69: v5 treats quotation marks only as delimiters, never as evidence by
# themselves. A quoted span becomes Obra / publicación only when an explicit,
# nearby lexical construction identifies it as such. This deliberately favors
# precision over recall in the review queue.
def _work_detections_v5(text: str) -> list[_Detection]:
    detections: list[_Detection] = []
    for start, end, exact_raw in _quoted_spans_v3(text):
        exact = exact_raw.strip()
        words = re.findall(r"[A-ZÁÉÍÓÚÜÑa-záéíóúüñ0-9]+", exact)
        if not words or len(exact) > 100 or len(words) > 10:
            continue
        first_letter = next((char for char in exact if char.isalpha()), "")
        if first_letter and first_letter.islower():
            continue

        cue_start = start - 1 if start > 0 and text[start - 1] in {'"', '“'} else start
        cue_end = end + 1 if end < len(text) and text[end] in {'"', '”'} else end
        immediate_before = text[max(0, cue_start - 96):cue_start]
        immediate_after = text[cue_end:min(len(text), cue_end + 96)]

        if _DIRECT_SPEECH_PREFIX_V3.search(immediate_before):
            continue
        if _NON_WORK_PREFIX_V4.search(immediate_before):
            continue
        if (
            re.search(r"[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ'’]+[ \t]+$", immediate_before)
            and re.match(r"[ \t]+[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ'’]+\b", immediate_after)
            and len(words) <= 3
        ):
            continue
        if re.search(r"(?i)\b(?:el|la|los|las)[ \t]+$", immediate_before):
            continue

        # Every accepted title must have one direct cue. Broad author-context
        # propagation from v4 is intentionally removed because it made unrelated
        # quoted speech inherit an earlier mention of teatro/obra/publicación.
        class_direct = bool(_WORK_CLASS_PREFIX_V4.search(immediate_before))
        verb_direct = bool(_WORK_VERB_PREFIX_V4.search(immediate_before))
        list_direct = bool(_WORK_LIST_CUE_V4.search(immediate_before))
        suffix_type_direct = bool(_WORK_SUFFIX_TYPE_V4.search(immediate_after))
        if not (class_direct or verb_direct or list_direct or suffix_type_direct):
            continue

        detection = _make_detection(
            text,
            start=start,
            end=end,
            family="work",
            subtype="quoted_work",
            confidence=0.97,
            explanation=(
                "Título entrecomillado propuesto sólo porque una construcción inmediata "
                "lo identifica explícitamente como obra, publicación, repertorio o pieza representada. "
                "Las comillas por sí solas no generan una referencia."
            ),
        )
        if detection is not None:
            detections.append(detection)
    return detections

def detect_local_candidates(
    text: str,
    *,
    families: Iterable[str],
    provider_version: str = LOCAL_PROVIDER_VERSION,
) -> list[_Detection]:
    if provider_version not in _LOCAL_RULES_VERSIONS:
        raise ValueError(f"Versión local de descubrimiento no admitida: {provider_version}")
    selected = set(families)
    detections: list[_Detection] = []
    if provider_version == "local_rules_v1":
        if "actor" in selected:
            detections.extend(_pattern_detections(text, family="actor", patterns=_ACTOR_PATTERNS))
        if "space" in selected:
            detections.extend(_pattern_detections(text, family="space", patterns=_SPACE_PATTERNS))
        if "time" in selected:
            detections.extend(_pattern_detections(text, family="time", patterns=_TIME_PATTERNS))
        if "event" in selected:
            detections.extend(_pattern_detections(text, family="event", patterns=_EVENT_PATTERNS))
        if "action_process" in selected:
            detections.extend(
                _pattern_detections(text, family="action_process", patterns=_ACTION_PATTERNS)
            )
        if "work" in selected:
            detections.extend(
                _pattern_detections(
                    text,
                    family="work",
                    patterns=_WORK_PATTERNS,
                    quoted_capture=True,
                )
            )
    elif provider_version == "local_rules_v2":
        if "actor" in selected:
            detections.extend(_pattern_detections(text, family="actor", patterns=_ACTOR_PATTERNS))
            detections.extend(
                _pattern_detections(
                    text,
                    family="actor",
                    patterns=_ACTOR_CAPTURE_PATTERNS_V2,
                    quoted_capture=True,
                )
            )
        if "space" in selected:
            detections.extend(_pattern_detections(text, family="space", patterns=_SPACE_PATTERNS))
            detections.extend(
                _pattern_detections(
                    text,
                    family="space",
                    patterns=_SPACE_CAPTURE_PATTERNS_V2,
                    quoted_capture=True,
                )
            )
        if "time" in selected:
            detections.extend(_pattern_detections(text, family="time", patterns=_TIME_PATTERNS_V2))
        if "event" in selected:
            detections.extend(_pattern_detections(text, family="event", patterns=_EVENT_PATTERNS_V2))
        if "action_process" in selected:
            detections.extend(
                _pattern_detections(text, family="action_process", patterns=_ACTION_PATTERNS_V2)
            )
        v2_work_detections = list(
            _pattern_detections(
                text,
                family="work",
                patterns=_WORK_CAPTURE_PATTERNS_V2,
                quoted_capture=True,
            )
        ) if {"time", "work"} & selected else []
        if "work" in selected:
            detections.extend(v2_work_detections)
        work_spans = [(item.start, item.end) for item in v2_work_detections]
        detections = [
            item
            for item in detections
            if not (
                item.family == "time"
                and item.subtype == "year"
                and any(start <= item.start and end >= item.end for start, end in work_spans)
            )
        ]
    elif provider_version == "local_rules_v3":
        if "actor" in selected:
            detections.extend(_pattern_detections(text, family="actor", patterns=_ACTOR_PATTERNS))
            detections.extend(
                _pattern_detections(
                    text,
                    family="actor",
                    patterns=_ACTOR_CAPTURE_PATTERNS_V2,
                    quoted_capture=True,
                )
            )
            detections.extend(
                _pattern_detections(
                    text,
                    family="actor",
                    patterns=_ACTOR_CAPTURE_PATTERNS_V3,
                    quoted_capture=True,
                )
            )
        if "space" in selected:
            detections.extend(_pattern_detections(text, family="space", patterns=_SPACE_PATTERNS))
            detections.extend(
                _pattern_detections(
                    text,
                    family="space",
                    patterns=_SPACE_CAPTURE_PATTERNS_V2,
                    quoted_capture=True,
                )
            )
            detections.extend(
                _pattern_detections(
                    text,
                    family="space",
                    patterns=_SPACE_CAPTURE_PATTERNS_V3,
                    quoted_capture=True,
                )
            )
        if "time" in selected:
            detections.extend(_time_detections_v3(text))
        if "event" in selected:
            detections.extend(_pattern_detections(text, family="event", patterns=_EVENT_PATTERNS_V3))
        if "action_process" in selected:
            detections.extend(
                _pattern_detections(text, family="action_process", patterns=_ACTION_PATTERNS_V2[:1])
            )
            detections.extend(
                _pattern_detections(
                    text,
                    family="action_process",
                    patterns=_ACTION_CONTEXT_PATTERNS_V3,
                    quoted_capture=True,
                )
            )
        v3_work_detections = _work_detections_v3(text) if {"time", "work"} & selected else []
        if "work" in selected:
            detections.extend(v3_work_detections)
        work_spans = [(item.start, item.end) for item in v3_work_detections]
        detections = [
            item
            for item in detections
            if not (
                item.family == "time"
                and item.subtype == "year"
                and any(start <= item.start and end >= item.end for start, end in work_spans)
            )
        ]
    elif provider_version == "local_rules_v4":
        if "actor" in selected:
            detections.extend(_pattern_detections(text, family="actor", patterns=_ACTOR_PATTERNS_V4))
            detections.extend(
                _pattern_detections(
                    text,
                    family="actor",
                    patterns=_ACTOR_CAPTURE_PATTERNS_V4,
                    quoted_capture=True,
                )
            )
        if "space" in selected:
            detections.extend(_pattern_detections(text, family="space", patterns=_SPACE_PATTERNS))
            detections.extend(
                _pattern_detections(
                    text,
                    family="space",
                    patterns=_SPACE_CAPTURE_PATTERNS_V2,
                    quoted_capture=True,
                )
            )
            detections.extend(
                _pattern_detections(
                    text,
                    family="space",
                    patterns=_SPACE_CAPTURE_PATTERNS_V3,
                    quoted_capture=True,
                )
            )
        if "time" in selected:
            detections.extend(_time_detections_v3(text))
        if "event" in selected:
            detections.extend(_pattern_detections(text, family="event", patterns=_EVENT_PATTERNS_V3))
        if "action_process" in selected:
            detections.extend(
                _pattern_detections(text, family="action_process", patterns=_ACTION_PATTERNS_V2[:1])
            )
            detections.extend(
                _pattern_detections(
                    text,
                    family="action_process",
                    patterns=_ACTION_CONTEXT_PATTERNS_V3,
                    quoted_capture=True,
                )
            )
        v4_work_detections = _work_detections_v4(text) if {"time", "work"} & selected else []
        if "work" in selected:
            detections.extend(v4_work_detections)
        work_spans = [(item.start, item.end) for item in v4_work_detections]
        detections = [
            item
            for item in detections
            if not (
                item.family == "time"
                and item.subtype == "year"
                and any(start <= item.start and end >= item.end for start, end in work_spans)
            )
        ]
    else:
        if "actor" in selected:
            detections.extend(_pattern_detections(text, family="actor", patterns=_ACTOR_PATTERNS_V4))
            detections.extend(
                _pattern_detections(
                    text,
                    family="actor",
                    patterns=_ACTOR_CAPTURE_PATTERNS_V4,
                    quoted_capture=True,
                )
            )
        if "space" in selected:
            detections.extend(_pattern_detections(text, family="space", patterns=_SPACE_PATTERNS))
            detections.extend(
                _pattern_detections(
                    text,
                    family="space",
                    patterns=_SPACE_CAPTURE_PATTERNS_V2,
                    quoted_capture=True,
                )
            )
            detections.extend(
                _pattern_detections(
                    text,
                    family="space",
                    patterns=_SPACE_CAPTURE_PATTERNS_V3,
                    quoted_capture=True,
                )
            )
        if "time" in selected:
            detections.extend(_time_detections_v3(text))
        if "event" in selected:
            detections.extend(_pattern_detections(text, family="event", patterns=_EVENT_PATTERNS_V3))
        if "action_process" in selected:
            detections.extend(
                _pattern_detections(text, family="action_process", patterns=_ACTION_PATTERNS_V2[:1])
            )
            detections.extend(
                _pattern_detections(
                    text,
                    family="action_process",
                    patterns=_ACTION_CONTEXT_PATTERNS_V3,
                    quoted_capture=True,
                )
            )
        v5_work_detections = _work_detections_v5(text) if {"time", "work"} & selected else []
        if "work" in selected:
            detections.extend(v5_work_detections)
        work_spans = [(item.start, item.end) for item in v5_work_detections]
        detections = [
            item
            for item in detections
            if not (
                item.family == "time"
                and item.subtype == "year"
                and any(start <= item.start and end >= item.end for start, end in work_spans)
            )
        ]
    deduplicated: dict[tuple[int, int, str, str], _Detection] = {}
    for item in detections:
        key = (item.start, item.end, item.family, item.subtype)
        previous = deduplicated.get(key)
        if previous is None or item.confidence > previous.confidence:
            deduplicated[key] = item
    ordered = sorted(
        deduplicated.values(),
        key=lambda item: (-item.confidence, item.start, -(item.end - item.start), item.family),
    )
    kept: list[_Detection] = []
    for item in ordered:
        if any(
            existing.family == item.family
            and existing.start <= item.start
            and existing.end >= item.end
            for existing in kept
        ):
            continue
        kept.append(item)
    return sorted(
        kept,
        key=lambda item: (item.start, item.end, item.family, item.subtype),
    )


def _known_surfaces(session: Session, project_id: str) -> set[str]:
    values: set[str] = set()
    authorities = session.scalars(
        select(AuthorityRecord).where(
            AuthorityRecord.project_id == project_id,
            AuthorityRecord.lifecycle_status == "active",
        )
    ).all()
    authority_ids = [row.id for row in authorities]
    for row in authorities:
        values.add(_normalize_surface(row.preferred_name))
    if authority_ids:
        aliases = session.scalars(
            select(AuthorityAlias).where(AuthorityAlias.authority_id.in_(authority_ids))
        ).all()
        for row in aliases:
            values.add(_normalize_surface(row.alias))
    return {value for value in values if value}


def _existing_mention_keys(session: Session) -> set[tuple[str, int, int]]:
    rows = session.scalars(
        select(EntityMention).where(
            EntityMention.status != "rejected",
            EntityMention.start_offset.is_not(None),
            EntityMention.end_offset.is_not(None),
        )
    ).all()
    return {
        (row.editable_object_id, int(row.start_offset), int(row.end_offset))
        for row in rows
    }


def _source_keys(session: Session, digital_ids: Iterable[str]) -> dict[str, str]:
    ids = tuple(dict.fromkeys(digital_ids))
    if not ids:
        return {}
    rows = session.scalars(
        select(SourceRegistration)
        .where(SourceRegistration.digital_object_id.in_(ids))
        .order_by(SourceRegistration.source_key, SourceRegistration.id)
    ).all()
    result: dict[str, str] = {}
    for row in rows:
        if row.digital_object_id and row.digital_object_id not in result:
            result[row.digital_object_id] = row.source_key
    return result


def _eligible_objects(
    session: Session, *, project_id: str, profile: DiscoveryProfile
) -> list[tuple[EditableObject, EditablePage, DigitalObject]]:
    query = (
        select(EditableObject, EditablePage, DigitalObject)
        .join(EditablePage, EditablePage.id == EditableObject.editable_page_id)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .where(
            DigitalObject.project_id == project_id,
            EditableObject.lifecycle_status == "active",
            EditablePage.status == "active",
        )
    )
    page_statuses = tuple(profile.include_page_review_statuses_json or ())
    if page_statuses:
        query = query.where(EditablePage.review_status.in_(page_statuses))
    object_types = tuple(profile.include_object_types_json or ())
    if object_types:
        query = query.where(EditableObject.current_object_type.in_(object_types))
    object_statuses = tuple(profile.include_object_review_statuses_json or ())
    if object_statuses:
        query = query.where(EditableObject.review_status.in_(object_statuses))
    return list(
        session.execute(
            query.order_by(
                DigitalObject.original_filename,
                EditableObject.page_number,
                EditableObject.current_order_index,
                EditableObject.id,
            )
        ).all()
    )


def run_open_discovery(
    session: Session,
    *,
    project_id: str,
    profile: DiscoveryProfile,
    created_by: str,
) -> DiscoveryRunSummary:
    actor = _clean_text(created_by, field="La persona responsable", maximum=200)
    if profile.project_id != project_id:
        raise ValueError("El perfil pertenece a otro proyecto")
    authorization = _require_profile_authorization(
        session, project_id=project_id, profile=profile
    )
    parameters = discovery_profile_authorization_parameters(profile)
    parameters_sha256 = sha256(
        json.dumps(
            parameters,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    provider = provider_contract(
        profile.provider_key,
        profile.provider_version,
        require_available=profile.provider_key != DISCOVERY_PROVIDER_KEY,
    )
    started = utc_now()
    run = DiscoveryRun(
        id=new_id(),
        project_id=project_id,
        profile_id=profile.id,
        authorization_id=authorization.id,
        profile_name=profile.name,
        profile_snapshot_json=profile_snapshot(profile),
        provider_key=profile.provider_key,
        provider_version=profile.provider_version,
        method=provider.method,
        parameters_sha256=parameters_sha256,
        corpus_state_sha256=current_editable_state_sha256(session, project_id),
        page_review_statuses_json=list(profile.include_page_review_statuses_json or ()),
        status="running",
        object_count=0,
        candidate_count=0,
        family_counts_json={},
        created_by=actor,
        started_at=started,
        finished_at=None,
        error_message=None,
    )
    session.add(run)
    session.flush()

    rows = _eligible_objects(session, project_id=project_id, profile=profile)
    known_surfaces = _known_surfaces(session, project_id)
    existing_mentions = _existing_mention_keys(session)
    source_map = _source_keys(session, (row[2].id for row in rows))
    family_counts: dict[str, int] = {}
    candidate_count = 0
    try:
        for editable, page, digital in rows:
            text = editable.current_text or ""
            if not text.strip():
                continue
            runtime_provider, detections = detect_with_provider(
                text,
                families=profile.families_json or (),
                provider_key=profile.provider_key,
                provider_version=profile.provider_version,
            )
            if runtime_provider != provider:
                raise RuntimeError("El proveedor cambió durante la corrida")
            for detection in detections:
                if (
                    detection.confidence is not None
                    and detection.confidence < float(profile.minimum_confidence)
                ):
                    continue
                if detection.family in {"actor", "space", "event", "work"}:
                    normalized = _normalize_surface(detection.exact_text)
                    if normalized in known_surfaces:
                        continue
                mention_key = (editable.id, detection.start, detection.end)
                if mention_key in existing_mentions:
                    continue
                context_before = text[max(0, detection.start - 90) : detection.start]
                context_after = text[detection.end : min(len(text), detection.end + 90)]
                candidate = DiscoveryCandidate(
                    id=new_id(),
                    project_id=project_id,
                    run_id=run.id,
                    profile_id=profile.id,
                    editable_object_id=editable.id,
                    editable_page_id=page.id,
                    digital_object_id=digital.id,
                    document_part_id=editable.document_part_id,
                    source_key=source_map.get(digital.id),
                    original_filename=digital.original_filename,
                    page_number=editable.page_number,
                    object_revision_number=editable.revision_number,
                    page_revision_number=page.revision_number,
                    start_offset=detection.start,
                    end_offset=detection.end,
                    exact_text=detection.exact_text,
                    context_before=context_before,
                    context_after=context_after,
                    semantic_family=detection.family,
                    suggested_subtype=detection.subtype,
                    confidence=detection.confidence,
                    method=provider.method,
                    provider_key=profile.provider_key,
                    provider_version=profile.provider_version,
                    model_name=provider.model_name,
                    model_version=provider.model_version,
                    explanation=detection.explanation,
                    parameters_sha256=parameters_sha256,
                    status="pending",
                    created_at=utc_now(),
                )
                session.add(candidate)
                candidate_count += 1
                family_counts[detection.family] = family_counts.get(detection.family, 0) + 1
        run.status = "completed"
        run.object_count = len(rows)
        run.candidate_count = candidate_count
        run.family_counts_json = dict(sorted(family_counts.items()))
        run.finished_at = utc_now()
        session.flush()
    except Exception as exc:
        run.status = "failed"
        run.object_count = len(rows)
        run.candidate_count = candidate_count
        run.family_counts_json = dict(sorted(family_counts.items()))
        run.finished_at = utc_now()
        run.error_message = str(exc)
        session.flush()
        raise
    return DiscoveryRunSummary(
        run_id=run.id,
        profile_id=profile.id,
        profile_name=profile.name,
        object_count=run.object_count,
        candidate_count=run.candidate_count,
        family_counts=dict(run.family_counts_json or {}),
        corpus_state_sha256=run.corpus_state_sha256,
        parameters_sha256=run.parameters_sha256,
    )


def discovery_run_rows(
    session: Session, *, project_id: str, limit: int = 50
) -> list[DiscoveryRunRow]:
    rows = session.scalars(
        select(DiscoveryRun)
        .where(DiscoveryRun.project_id == project_id)
        .order_by(DiscoveryRun.started_at.desc(), DiscoveryRun.id.desc())
        .limit(max(1, int(limit)))
    ).all()
    return [
        DiscoveryRunRow(
            run_id=row.id,
            profile_id=row.profile_id,
            profile_name=row.profile_name,
            status=row.status,
            provider_key=row.provider_key,
            provider_version=row.provider_version,
            object_count=row.object_count,
            candidate_count=row.candidate_count,
            family_counts=dict(row.family_counts_json or {}),
            page_review_statuses=tuple(row.page_review_statuses_json or ()),
            corpus_state_sha256=row.corpus_state_sha256,
            parameters_sha256=row.parameters_sha256,
            created_by=row.created_by,
            started_at=row.started_at,
            finished_at=row.finished_at,
            error_message=row.error_message,
        )
        for row in rows
    ]


def discovery_candidate_rows(
    session: Session,
    *,
    project_id: str,
    run_id: str | None = None,
    families: Iterable[str] = (),
    limit: int | None = 500,
) -> list[DiscoveryCandidateRow]:
    query = select(DiscoveryCandidate).where(DiscoveryCandidate.project_id == project_id)
    if run_id:
        query = query.where(DiscoveryCandidate.run_id == run_id)
    selected_families = tuple(dict.fromkeys(families))
    if selected_families:
        invalid = set(selected_families) - set(DISCOVERY_FAMILIES)
        if invalid:
            raise ValueError("Familias inválidas: " + ", ".join(sorted(invalid)))
        query = query.where(DiscoveryCandidate.semantic_family.in_(selected_families))
    query = query.order_by(
        DiscoveryCandidate.created_at.desc(),
        DiscoveryCandidate.original_filename,
        DiscoveryCandidate.page_number,
        DiscoveryCandidate.start_offset,
        DiscoveryCandidate.id,
    )
    if limit is not None:
        query = query.limit(max(1, int(limit)))
    rows = session.scalars(query).all()
    object_ids = {row.editable_object_id for row in rows}
    objects = {
        row.id: row
        for row in session.scalars(
            select(EditableObject).where(EditableObject.id.in_(object_ids))
        ).all()
    } if object_ids else {}
    candidate_ids = [row.id for row in rows]
    decisions = session.scalars(
        select(DiscoveryDecision)
        .where(DiscoveryDecision.candidate_id.in_(candidate_ids))
        .order_by(
            DiscoveryDecision.candidate_id,
            DiscoveryDecision.decision_number,
        )
    ).all() if candidate_ids else []
    decisions_by: dict[str, list[DiscoveryDecision]] = {}
    for decision in decisions:
        decisions_by.setdefault(decision.candidate_id, []).append(decision)
    result: list[DiscoveryCandidateRow] = []
    for row in rows:
        current = objects.get(row.editable_object_id)
        stale = current is None or current.revision_number != row.object_revision_number
        if current is not None and not stale:
            stale = current.current_text[row.start_offset : row.end_offset] != row.exact_text
        candidate_decisions = decisions_by.get(row.id, [])
        latest_decision = candidate_decisions[-1] if candidate_decisions else None
        result.append(
            DiscoveryCandidateRow(
                candidate_id=row.id,
                run_id=row.run_id,
                profile_id=row.profile_id,
                exact_text=row.exact_text,
                semantic_family=row.semantic_family,
                family_label=family_label(row.semantic_family),
                suggested_subtype=row.suggested_subtype,
                confidence=row.confidence,
                explanation=row.explanation,
                source_key=row.source_key,
                original_filename=row.original_filename,
                page_number=row.page_number,
                editable_object_id=row.editable_object_id,
                editable_page_id=row.editable_page_id,
                object_revision_number=row.object_revision_number,
                page_revision_number=row.page_revision_number,
                start_offset=row.start_offset,
                end_offset=row.end_offset,
                context_before=row.context_before,
                context_after=row.context_after,
                provider_key=row.provider_key,
                provider_version=row.provider_version,
                method=row.method,
                parameters_sha256=row.parameters_sha256,
                status=row.status,
                decision_count=len(candidate_decisions),
                latest_decision_type=(
                    latest_decision.decision_type if latest_decision else None
                ),
                effective_text=(
                    latest_decision.reviewed_text if latest_decision else row.exact_text
                ),
                effective_family=(
                    latest_decision.semantic_family
                    if latest_decision
                    else row.semantic_family
                ),
                effective_subtype=(
                    latest_decision.reviewed_subtype
                    if latest_decision
                    else row.suggested_subtype
                ),
                is_stale=stale,
                created_at=row.created_at,
            )
        )
    return result


def discovery_audit_payload(
    session: Session, *, project_id: str, run_id: str
) -> dict[str, Any]:
    run = session.get(DiscoveryRun, run_id)
    if run is None or run.project_id != project_id:
        raise ValueError("La corrida de descubrimiento no existe en este proyecto")
    candidates = discovery_candidate_rows(
        session, project_id=project_id, run_id=run_id, limit=100_000
    )
    return {
        "run": {
            "id": run.id,
            "profile_id": run.profile_id,
            "profile_name": run.profile_name,
            "profile_snapshot": run.profile_snapshot_json,
            "authorization_id": run.authorization_id,
            "provider_key": run.provider_key,
            "provider_version": run.provider_version,
            "method": run.method,
            "parameters_sha256": run.parameters_sha256,
            "corpus_state_sha256": run.corpus_state_sha256,
            "page_review_statuses": list(run.page_review_statuses_json or ()),
            "status": run.status,
            "object_count": run.object_count,
            "candidate_count": run.candidate_count,
            "family_counts": dict(run.family_counts_json or {}),
            "created_by": run.created_by,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "error_message": run.error_message,
        },
        "candidates": [
            {
                "id": row.candidate_id,
                "exact_text": row.exact_text,
                "family": row.semantic_family,
                "subtype": row.suggested_subtype,
                "confidence": row.confidence,
                "source_key": row.source_key,
                "original_filename": row.original_filename,
                "page_number": row.page_number,
                "editable_object_id": row.editable_object_id,
                "object_revision_number": row.object_revision_number,
                "start_offset": row.start_offset,
                "end_offset": row.end_offset,
                "provider_key": row.provider_key,
                "provider_version": row.provider_version,
                "method": row.method,
                "explanation": row.explanation,
                "parameters_sha256": row.parameters_sha256,
                "status": row.status,
                "decision_count": row.decision_count,
                "latest_decision_type": row.latest_decision_type,
                "effective_text": row.effective_text,
                "effective_family": row.effective_family,
                "effective_subtype": row.effective_subtype,
                "is_stale": row.is_stale,
            }
            for row in candidates
        ],
    }


def single_project_id(session: Session) -> str:
    project_ids = session.scalars(select(Project.id).order_by(Project.id)).all()
    if len(project_ids) != 1:
        raise ValueError("El proyecto debe contener exactamente una fila en projects")
    return project_ids[0]
