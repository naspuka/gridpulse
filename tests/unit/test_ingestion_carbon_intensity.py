"""Tests for the Carbon Intensity ingestion functions.

Mocks the HTTP layer with our captured fixtures so we exercise the full
fetch → validate → row pipeline against real API shapes, without ever
hitting the live API in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from gridpulse.ingestion.carbon_intensity import (
    BASE_URL,
    fetch_national,
    fetch_regional,
)
from gridpulse.ingestion.http import TransientHttpError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "carbon_intensity"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_fetch_national_returns_one_row(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/intensity", json=_fixture("intensity_current.json"))
    rows = fetch_national()
    assert len(rows) == 1
    assert rows[0].region_id == 0  # NATIONAL sentinel


def test_fetch_regional_returns_14_dno_rows(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/regional", json=_fixture("regional_current.json"))
    rows = fetch_regional()
    assert len(rows) == 14
    assert {r.region_id for r in rows} == set(range(1, 15))


def test_fetch_national_retries_on_503(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/intensity", status_code=503)
    httpx_mock.add_response(url=f"{BASE_URL}/intensity", status_code=503)
    httpx_mock.add_response(url=f"{BASE_URL}/intensity", json=_fixture("intensity_current.json"))
    rows = fetch_national()
    assert len(rows) == 1


def test_fetch_national_gives_up_after_max_attempts(httpx_mock: HTTPXMock) -> None:
    for _ in range(3):
        httpx_mock.add_response(url=f"{BASE_URL}/intensity", status_code=503)
    with pytest.raises(TransientHttpError):
        fetch_national()


def test_fetch_regional_drops_rollups(httpx_mock: HTTPXMock) -> None:
    # Sanity check that the 18→14 filter survives the integration boundary.
    httpx_mock.add_response(url=f"{BASE_URL}/regional", json=_fixture("regional_current.json"))
    rows = fetch_regional()
    # No rollup region_ids (15..18) should appear.
    assert all(1 <= r.region_id <= 14 for r in rows)
