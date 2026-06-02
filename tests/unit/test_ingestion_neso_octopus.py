"""Ingestion tests for NESO + Octopus — mock the wire with pytest-httpx
using captured fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from gridpulse.ingestion.http import TransientHttpError
from gridpulse.ingestion.neso import (
    BASE_URL as NESO_BASE_URL,
)
from gridpulse.ingestion.neso import (
    GENERATION_MIX_RESOURCE_ID,
    fetch_recent_generation_mix,
)
from gridpulse.ingestion.octopus import (
    AGILE_PRODUCT,
    fetch_agile_rates_all_regions,
    fetch_agile_rates_for_region,
)
from gridpulse.ingestion.octopus import (
    BASE_URL as OCTO_BASE_URL,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _fixture(rel: str) -> dict:
    return json.loads((FIX / rel).read_text())


# ---------------------------------------------------------------------------
# NESO
# ---------------------------------------------------------------------------


def test_fetch_neso_returns_rows(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=(
            f"{NESO_BASE_URL}/api/3/action/datastore_search"
            f"?resource_id={GENERATION_MIX_RESOURCE_ID}&limit=96&sort=DATETIME+desc"
        ),
        json=_fixture("neso/generation_mix_latest.json"),
    )
    rows = fetch_recent_generation_mix()
    assert len(rows) >= 1


def test_fetch_neso_retries_on_503(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=(
            f"{NESO_BASE_URL}/api/3/action/datastore_search"
            f"?resource_id={GENERATION_MIX_RESOURCE_ID}&limit=96&sort=DATETIME+desc"
        ),
        status_code=503,
    )
    httpx_mock.add_response(
        url=(
            f"{NESO_BASE_URL}/api/3/action/datastore_search"
            f"?resource_id={GENERATION_MIX_RESOURCE_ID}&limit=96&sort=DATETIME+desc"
        ),
        status_code=503,
    )
    httpx_mock.add_response(
        url=(
            f"{NESO_BASE_URL}/api/3/action/datastore_search"
            f"?resource_id={GENERATION_MIX_RESOURCE_ID}&limit=96&sort=DATETIME+desc"
        ),
        json=_fixture("neso/generation_mix_latest.json"),
    )
    rows = fetch_recent_generation_mix()
    assert len(rows) >= 1


def test_fetch_neso_gives_up(httpx_mock: HTTPXMock) -> None:
    for _ in range(3):
        httpx_mock.add_response(
            url=(
                f"{NESO_BASE_URL}/api/3/action/datastore_search"
                f"?resource_id={GENERATION_MIX_RESOURCE_ID}&limit=96&sort=DATETIME+desc"
            ),
            status_code=503,
        )
    with pytest.raises(TransientHttpError):
        fetch_recent_generation_mix()


# ---------------------------------------------------------------------------
# Octopus
# ---------------------------------------------------------------------------


def _octo_url(region_letter: str, page_size: int = 96) -> str:
    return (
        f"{OCTO_BASE_URL}/v1/products/{AGILE_PRODUCT}"
        f"/electricity-tariffs/E-1R-{AGILE_PRODUCT}-{region_letter}/standard-unit-rates/"
        f"?page_size={page_size}"
    )


def test_fetch_agile_one_region(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=_octo_url("C", page_size=4),
        json=_fixture("octopus/london_4.json"),
    )
    rows = fetch_agile_rates_for_region(region_id=13, octopus_code="C", page_size=4)
    assert len(rows) == 4
    assert {r.region_id for r in rows} == {13}


def test_fetch_agile_all_regions_loops(httpx_mock: HTTPXMock) -> None:
    # Two regions, same fixture body — proves we make 2 calls and tag the
    # right region_id on each batch.
    for letter in ("C", "A"):
        httpx_mock.add_response(
            url=_octo_url(letter, page_size=4),
            json=_fixture("octopus/london_4.json"),
        )
    rows = fetch_agile_rates_all_regions(
        regions=[(13, "C"), (10, "A")],
        page_size=4,
    )
    # 4 rows per call × 2 calls = 8 rows.
    assert len(rows) == 8
    assert {r.region_id for r in rows} == {10, 13}
