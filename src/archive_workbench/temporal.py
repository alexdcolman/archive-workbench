from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
import re
import unicodedata


@dataclass(frozen=True, slots=True)
class TemporalRange:
    expression: str | None
    start: date | None
    end: date | None
    precision: str | None
    approximate: bool = False

    @property
    def is_empty(self) -> bool:
        return self.expression is None

    @property
    def display(self) -> str | None:
        return self.expression


_APPROX_PATTERN = re.compile(
    r"(?:\baprox(?:imadamente)?\.?\b|\bcirca\b|\bca\.?\b|\bc\.?\s+(?=\d)|~)",
    flags=re.IGNORECASE,
)
_RANGE_SPLIT = re.compile(r"\s+(?:-|–|—|a|hasta)\s+", flags=re.IGNORECASE)

_DECADE_WORDS = {
    "veinte": 1920,
    "treinta": 1930,
    "cuarenta": 1940,
    "cincuenta": 1950,
    "sesenta": 1960,
    "setenta": 1970,
    "ochenta": 1980,
    "noventa": 1990,
    "dos mil": 2000,
}


def _clean(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def _date_bounds(value: str) -> tuple[date, date, str]:
    text = _clean(value).casefold().strip(" .")
    if not text:
        raise ValueError("La expresión temporal está vacía")

    iso_day = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso_day:
        year, month, day = map(int, iso_day.groups())
        point = date(year, month, day)
        return point, point, "day"

    slash_day = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if slash_day:
        day, month, year = map(int, slash_day.groups())
        point = date(year, month, day)
        return point, point, "day"

    iso_month = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if iso_month:
        year, month = map(int, iso_month.groups())
        return date(year, month, 1), date(year, month, monthrange(year, month)[1]), "month"

    slash_month = re.fullmatch(r"(\d{1,2})/(\d{4})", text)
    if slash_month:
        month, year = map(int, slash_month.groups())
        return date(year, month, 1), date(year, month, monthrange(year, month)[1]), "month"

    year_match = re.fullmatch(r"(\d{4})", text)
    if year_match:
        year = int(year_match.group(1))
        return date(year, 1, 1), date(year, 12, 31), "year"

    decade_number = re.search(r"(?:d[eé]cada(?: de)?|a[nñ]os?)\s+(\d{4})", text)
    if decade_number:
        year = int(decade_number.group(1))
        base = year - (year % 10)
        return date(base, 1, 1), date(base + 9, 12, 31), "decade"

    compact_decade = re.fullmatch(r"(?:los\s+)?(\d{2})(?:s|'s)?", text)
    if compact_decade:
        short = int(compact_decade.group(1))
        base = 1900 + short if short >= 20 else 2000 + short
        return date(base, 1, 1), date(base + 9, 12, 31), "decade"

    for word, base in _DECADE_WORDS.items():
        if re.fullmatch(rf"(?:los\s+)?(?:a[nñ]os\s+|d[eé]cada(?: de)?\s+)?{re.escape(word)}", text):
            return date(base, 1, 1), date(base + 9, 12, 31), "decade"

    raise ValueError(
        "No pude interpretar la fecha. Usá, por ejemplo, 15/03/1975, 03/1975, "
        "1975, años setenta, desde 1974, hasta 03/1976 o 03/1974 - 03/1976."
    )


def parse_temporal_expression(value: str | None) -> TemporalRange:
    if value is None or not value.strip():
        return TemporalRange(None, None, None, None, False)

    original = _clean(value)
    approximate = bool(_APPROX_PATTERN.search(original))
    working = _APPROX_PATTERN.sub("", original).strip(" ,")
    folded = working.casefold()

    if folded.startswith("desde "):
        lower, _upper, precision = _date_bounds(working[6:])
        return TemporalRange(original, lower, None, f"open_start_{precision}", approximate)
    if folded.startswith("hasta "):
        _lower, upper, precision = _date_bounds(working[6:])
        return TemporalRange(original, None, upper, f"open_end_{precision}", approximate)

    parts = _RANGE_SPLIT.split(working, maxsplit=1)
    if len(parts) == 2:
        left_lower, _left_upper, left_precision = _date_bounds(parts[0])
        _right_lower, right_upper, right_precision = _date_bounds(parts[1])
        if left_lower > right_upper:
            raise ValueError("El inicio del rango temporal es posterior al final")
        precision = left_precision if left_precision == right_precision else "mixed"
        return TemporalRange(original, left_lower, right_upper, precision, approximate)

    lower, upper, precision = _date_bounds(working)
    return TemporalRange(original, lower, upper, precision, approximate)


def temporal_overlap(
    *,
    item_start: date | None,
    item_end: date | None,
    query_start: date | None,
    query_end: date | None,
    include_undated: bool = False,
) -> bool:
    if query_start is None and query_end is None:
        return True
    if item_start is None and item_end is None:
        return include_undated
    if query_start is not None and item_end is not None and item_end < query_start:
        return False
    if query_end is not None and item_start is not None and item_start > query_end:
        return False
    return True


def format_temporal_range(
    expression: str | None,
    start: date | None,
    end: date | None,
    approximate: bool = False,
) -> str | None:
    if expression:
        return expression
    if start is None and end is None:
        return None
    prefix = "aprox. " if approximate else ""
    if start is not None and end is not None:
        return f"{prefix}{start.isoformat()} – {end.isoformat()}"
    if start is not None:
        return f"{prefix}desde {start.isoformat()}"
    return f"{prefix}hasta {end.isoformat()}"
