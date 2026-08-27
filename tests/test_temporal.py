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


def test_discontinuous_periods_keep_the_gap_outside_the_match() -> None:
    from archive_workbench.temporal import parse_temporal_periods, temporal_expression_overlap

    periods = parse_temporal_periods("1946 - 2015; desde 2024")
    assert len(periods) == 2
    assert periods[0].start == date(1946, 1, 1)
    assert periods[0].end == date(2015, 12, 31)
    assert periods[1].start == date(2024, 1, 1)
    assert periods[1].end is None
    assert not temporal_expression_overlap(
        expression="1946 - 2015; desde 2024",
        item_start=date(1946, 1, 1),
        item_end=None,
        query_start=date(2018, 1, 1),
        query_end=date(2018, 12, 31),
    )
    assert temporal_expression_overlap(
        expression="1946 - 2015; desde 2024",
        item_start=date(1946, 1, 1),
        item_end=None,
        query_start=date(2025, 1, 1),
        query_end=date(2025, 12, 31),
    )


def test_bracketed_period_remains_filterable() -> None:
    from archive_workbench.temporal import parse_temporal_periods

    period = parse_temporal_periods("[1969]-[1989]")[0]
    assert period.start == date(1969, 1, 1)
    assert period.end == date(1989, 12, 31)
