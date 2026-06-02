"""DST invariants for ingestion.

UK clocks switch in March (lose an hour: 23-hour day) and October
(gain an hour: 25-hour day). In *UK-local* time those days have 46
and 50 half-hour settlement periods respectively. In *UTC* — which
is what we store and what NESO/Octopus actually publish — every day
is exactly 24 hours and exactly 48 half-hours, regardless of UK
clock changes.

These tests lock that invariant: a synthetic 50-row response covering
a UK "long" Sunday in UTC parses cleanly, sorts to a strict 30-minute
grid, and the row count matches what the input said. If we ever
accidentally introduce a UK-local conversion in `to_rows()`, this
suite will catch it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gridpulse.contracts.neso import NesoGenerationMixResponse


def _synthetic_neso_response(start_utc: datetime, n_periods: int) -> dict:
    """Build a CKAN-shaped response with `n_periods` half-hour records,
    starting at `start_utc` and stepping forward 30 minutes each row."""
    records = []
    for i in range(n_periods):
        ts = start_utc + timedelta(minutes=30 * i)
        records.append(
            {
                "_id": 1_000_000 + i,
                # NESO uses naive ISO; the contract pins it to UTC.
                "DATETIME": ts.replace(tzinfo=None).isoformat(),
                "GAS": 7000.0,
                "COAL": 0.0,
                "NUCLEAR": 2000.0,
                "WIND": 3000.0,
                "WIND_EMB": 1000.0,
                "HYDRO": 100.0,
                "IMPORTS": 1500.0,
                "BIOMASS": 2000.0,
                "OTHER": 400.0,
                "SOLAR": 5000.0,
                "STORAGE": 0.0,
                "GENERATION": 22000.0,
                "CARBON_INTENSITY": 180.0,
                "LOW_CARBON": 12100.0,
                "ZERO_CARBON": 8100.0,
                "RENEWABLE": 11100.0,
                "FOSSIL": 7000.0,
                "GAS_perc": 31.8,
                "COAL_perc": 0.0,
                "NUCLEAR_perc": 9.1,
                "WIND_perc": 13.6,
                "WIND_EMB_perc": 4.5,
                "HYDRO_perc": 0.5,
                "IMPORTS_perc": 6.8,
                "BIOMASS_perc": 9.1,
                "OTHER_perc": 1.8,
                "SOLAR_perc": 22.7,
                "STORAGE_perc": 0.0,
                "GENERATION_perc": 100.0,
                "LOW_CARBON_perc": 55.0,
                "ZERO_CARBON_perc": 36.8,
                "RENEWABLE_perc": 50.5,
                "FOSSIL_perc": 31.8,
            }
        )
    return {
        "success": True,
        "result": {
            "records": records,
            "total": n_periods,
        },
    }


@pytest.mark.parametrize(
    ("label", "start_utc", "expected_periods"),
    [
        # Last UK DST event before V1: 2026-10-25, clocks back ⇒ UK day is 25h
        # (50 half-hours in UK local). UTC sees exactly 48 half-hours.
        ("october-long-day-utc", datetime(2026, 10, 25, 0, 0, tzinfo=UTC), 48),
        # 2026-03-29, clocks forward ⇒ UK day is 23h (46 half-hours UK local).
        # UTC: still 48.
        ("march-short-day-utc", datetime(2026, 3, 29, 0, 0, tzinfo=UTC), 48),
        # Sanity: a normal day.
        ("normal-day-utc", datetime(2026, 6, 1, 0, 0, tzinfo=UTC), 48),
        # A synthetic 50-row payload — the worst-case if NESO ever sends
        # uk-local values for an October Sunday. Our model must still parse
        # it cleanly and round-trip the 50 rows; it's the dbt mart's job to
        # de-duplicate by natural key.
        ("synthetic-50-row-payload", datetime(2026, 10, 25, 0, 0, tzinfo=UTC), 50),
    ],
)
def test_utc_day_parses_to_expected_row_count(
    label: str, start_utc: datetime, expected_periods: int
) -> None:
    payload = _synthetic_neso_response(start_utc, expected_periods)
    parsed = NesoGenerationMixResponse(**payload)
    rows = parsed.to_rows()
    assert len(rows) == expected_periods, label

    # Every row's period_start is tz-aware UTC.
    for r in rows:
        assert r.period_start_utc.tzinfo is not None
        assert r.period_start_utc.utcoffset() == UTC.utcoffset(r.period_start_utc)

    # Strictly increasing by exactly 30 minutes.
    gaps = [
        (rows[i + 1].period_start_utc - rows[i].period_start_utc).total_seconds()
        for i in range(len(rows) - 1)
    ]
    assert all(g == 30 * 60 for g in gaps), label
