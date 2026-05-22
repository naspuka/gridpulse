"""Contract tests for Carbon Intensity API models.

Three flavours:
1. Snapshot — committed fixtures parse cleanly through the raw models.
2. Round-trip — `to_rows()` produces correctly-shaped, UTC-aware rows.
3. Drift — adding a junk field to a fixture makes the raw model raise. Proves
   `extra="forbid"` is doing its job.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from gridpulse.contracts.carbon_intensity import (
    CarbonIntensityNationalResponse,
    CarbonIntensityRegionalResponse,
    CarbonIntensityRow,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "carbon_intensity"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_national_fixture_parses() -> None:
    payload = _load("intensity_current.json")
    parsed = CarbonIntensityNationalResponse(**payload)
    assert len(parsed.data) >= 1


def test_regional_fixture_parses() -> None:
    payload = _load("regional_current.json")
    parsed = CarbonIntensityRegionalResponse(**payload)
    # CI returns 14 DNO regions + 4 rollups = 18 regions per period.
    assert len(parsed.data) >= 1
    assert len(parsed.data[0].regions) == 18


# ---------------------------------------------------------------------------
# Round-trip — to_rows()
# ---------------------------------------------------------------------------


def test_national_to_rows_yields_one_row_per_period() -> None:
    payload = _load("intensity_current.json")
    rows = CarbonIntensityNationalResponse(**payload).to_rows()
    assert len(rows) == 1
    row = rows[0]
    # National sentinel.
    assert row.region_id == 0
    # Tz-aware UTC.
    assert row.period_start_utc.tzinfo is not None
    assert row.period_start_utc.utcoffset() == UTC.utcoffset(datetime.now(UTC))
    # Period is 30 minutes.
    assert (row.period_end_utc - row.period_start_utc).total_seconds() == 30 * 60


def test_national_actual_can_be_null_for_future_periods() -> None:
    # Synthetic — a forecast-only response (actual=null).
    payload = {
        "data": [
            {
                "from": "2030-01-01T00:00Z",
                "to": "2030-01-01T00:30Z",
                "intensity": {"forecast": 200, "actual": None, "index": "moderate"},
            }
        ]
    }
    rows = CarbonIntensityNationalResponse(**payload).to_rows()
    assert rows[0].actual_gco2_per_kwh is None


def test_regional_to_rows_skips_rollups() -> None:
    payload = _load("regional_current.json")
    rows = CarbonIntensityRegionalResponse(**payload).to_rows()
    # 14 DNO regions only — England/Scotland/Wales/GB rollups dropped.
    assert len(rows) == 14
    # region_ids span the 14 DNOs.
    assert {r.region_id for r in rows} == set(range(1, 15))


def test_regional_rows_have_no_actual() -> None:
    payload = _load("regional_current.json")
    rows = CarbonIntensityRegionalResponse(**payload).to_rows()
    assert all(r.actual_gco2_per_kwh is None for r in rows)


def test_regional_rows_have_30_minute_periods() -> None:
    payload = _load("regional_current.json")
    rows = CarbonIntensityRegionalResponse(**payload).to_rows()
    for r in rows:
        assert (r.period_end_utc - r.period_start_utc).total_seconds() == 30 * 60


# ---------------------------------------------------------------------------
# Drift — extra=forbid must REJECT new fields. This is the "loud, not silent"
# contract per CLAUDE.md's data-contracts convention.
# ---------------------------------------------------------------------------


def test_national_rejects_unknown_top_level_field() -> None:
    bad = _load("intensity_current.json") | {"metadata": "junk"}
    with pytest.raises(ValidationError):
        CarbonIntensityNationalResponse(**bad)


def test_national_rejects_unknown_intensity_field() -> None:
    bad = _load("intensity_current.json")
    bad["data"][0]["intensity"]["new_field"] = 42
    with pytest.raises(ValidationError):
        CarbonIntensityNationalResponse(**bad)


def test_regional_rejects_unknown_region_field() -> None:
    bad = _load("regional_current.json")
    bad["data"][0]["regions"][0]["new_field"] = "surprise"
    with pytest.raises(ValidationError):
        CarbonIntensityRegionalResponse(**bad)


# ---------------------------------------------------------------------------
# Row model invariants
# ---------------------------------------------------------------------------


def test_row_model_uses_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        CarbonIntensityRow(
            region_id=0,
            period_start_utc=datetime(2026, 1, 1, tzinfo=UTC),
            period_end_utc=datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
            forecast_gco2_per_kwh=100,
            actual_gco2_per_kwh=None,
            intensity_index="low",
            mystery_field="boom",  # type: ignore[call-arg]
        )
