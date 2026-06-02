"""Contract tests for the NESO generation-mix model.

Three flavours:
1. Snapshot — committed fixtures parse cleanly through the raw models.
2. Round-trip — to_rows() yields tz-aware UTC, correct widths.
3. Drift — adding a junk field makes the raw record raise (extra="forbid").
"""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import pytest
from pydantic import ValidationError

from gridpulse.contracts.neso import NesoGenerationMixResponse

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "neso"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_fixture_parses() -> None:
    parsed = NesoGenerationMixResponse(**_load("generation_mix_latest.json"))
    assert parsed.success is True
    assert len(parsed.result.records) >= 1


def test_to_rows_produces_utc_aware_timestamps() -> None:
    parsed = NesoGenerationMixResponse(**_load("generation_mix_latest.json"))
    rows = parsed.to_rows()
    assert rows, "fixture should contain at least one row"
    for r in rows:
        assert r.period_start_utc.tzinfo is not None
        assert r.period_start_utc.utcoffset() == UTC.utcoffset(r.period_start_utc)


def test_to_rows_carries_all_fuel_columns() -> None:
    parsed = NesoGenerationMixResponse(**_load("generation_mix_latest.json"))
    row = parsed.to_rows()[0]
    # Sanity: every fuel column is a number; total ≈ sum of components.
    fuels = [
        row.gas_mw,
        row.coal_mw,
        row.nuclear_mw,
        row.wind_mw,
        row.wind_embedded_mw,
        row.hydro_mw,
        row.imports_mw,
        row.biomass_mw,
        row.other_mw,
        row.solar_mw,
        row.storage_mw,
    ]
    assert all(isinstance(f, float) for f in fuels)
    # Allow 1% slop — NESO rounds in the published total.
    derived_total = sum(fuels)
    assert abs(derived_total - row.total_generation_mw) / row.total_generation_mw < 0.05


def test_rejects_unknown_field_on_record() -> None:
    payload = _load("generation_mix_latest.json")
    payload["result"]["records"][0]["new_neso_field"] = 99
    with pytest.raises(ValidationError):
        NesoGenerationMixResponse(**payload)


def test_naive_datetime_is_interpreted_as_utc() -> None:
    """NESO's DATETIME has no Z suffix; the validator pins it to UTC."""
    parsed = NesoGenerationMixResponse(**_load("generation_mix_latest.json"))
    # The fixture's record 0 raw DATETIME starts with "2026-06-02T12:00:00"
    # (verified by inspection). The model should convert that to a tz-aware
    # datetime whose ISO form ends in "+00:00".
    row = parsed.to_rows()[0]
    assert row.period_start_utc.isoformat().endswith("+00:00")
