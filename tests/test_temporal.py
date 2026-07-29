from __future__ import annotations

from datetime import date

import pytest

from archive_workbench.temporal import parse_temporal_expression, temporal_overlap


@pytest.mark.parametrize(
    ("expression", "start", "end", "precision", "approximate"),
    [
        ("15/03/1975", date(1975, 3, 15), date(1975, 3, 15), "day", False),
        ("03/1975", date(1975, 3, 1), date(1975, 3, 31), "month", False),
        ("1975", date(1975, 1, 1), date(1975, 12, 31), "year", False),
        ("años setenta", date(1970, 1, 1), date(1979, 12, 31), "decade", False),
        ("03/1974 - 03/1976", date(1974, 3, 1), date(1976, 3, 31), "month", False),
        ("desde 1974", date(1974, 1, 1), None, "open_start_year", False),
        ("hasta 03/1976", None, date(1976, 3, 31), "open_end_month", False),
        ("ca. 1975", date(1975, 1, 1), date(1975, 12, 31), "year", True),
    ],
)
def test_parse_temporal_expression(expression, start, end, precision, approximate) -> None:
    parsed = parse_temporal_expression(expression)
    assert parsed.expression == expression
    assert parsed.start == start
    assert parsed.end == end
    assert parsed.precision == precision
    assert parsed.approximate is approximate


def test_temporal_overlap_respects_open_ranges_and_undated() -> None:
    assert temporal_overlap(
        item_start=date(1974, 3, 1),
        item_end=date(1976, 3, 31),
        query_start=date(1975, 1, 1),
        query_end=date(1975, 12, 31),
    )
    assert not temporal_overlap(
        item_start=date(1980, 1, 1),
        item_end=None,
        query_start=date(1975, 1, 1),
        query_end=date(1975, 12, 31),
    )
    assert not temporal_overlap(
        item_start=None,
        item_end=None,
        query_start=date(1975, 1, 1),
        query_end=date(1975, 12, 31),
    )
    assert temporal_overlap(
        item_start=None,
        item_end=None,
        query_start=date(1975, 1, 1),
        query_end=date(1975, 12, 31),
        include_undated=True,
    )
