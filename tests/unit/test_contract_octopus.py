"""Contract tests for Octopus Agile."""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import pytest
from pydantic import ValidationError

from gridpulse.contracts.octopus import AgileRatesResponse

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "octopus"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_fixture_parses() -> None:
    parsed = AgileRatesResponse(**_load("london_4.json"))
    assert parsed.count >= 4
    assert len(parsed.results) == 4


def test_to_rows_tags_region_id() -> None:
    parsed = AgileRatesResponse(**_load("london_4.json"))
    # London is region_id=13 in ref.dno_region.
    rows = parsed.to_rows(region_id=13)
    assert len(rows) == 4
    assert {r.region_id for r in rows} == {13}


def test_to_rows_utc_periods_are_thirty_minutes() -> None:
    parsed = AgileRatesResponse(**_load("london_4.json"))
    rows = parsed.to_rows(region_id=13)
    for r in rows:
        assert r.period_start_utc.tzinfo is not None
        assert r.period_start_utc.utcoffset() == UTC.utcoffset(r.period_start_utc)
        assert (r.period_end_utc - r.period_start_utc).total_seconds() == 30 * 60


def test_to_rows_keeps_both_vat_variants() -> None:
    parsed = AgileRatesResponse(**_load("london_4.json"))
    rows = parsed.to_rows(region_id=13)
    for r in rows:
        # VAT-inclusive is the higher number.
        assert r.price_pence_per_kwh_inc_vat > r.price_pence_per_kwh_exc_vat


def test_rejects_unknown_field_on_rate() -> None:
    bad = _load("london_4.json")
    bad["results"][0]["surprise_field"] = 1
    with pytest.raises(ValidationError):
        AgileRatesResponse(**bad)


def test_rejects_unknown_top_level_field() -> None:
    bad = _load("london_4.json") | {"extra_envelope": "yo"}
    with pytest.raises(ValidationError):
        AgileRatesResponse(**bad)
