"""End-to-end pipeline integration test.

Confirms that — given a real Postgres (the CI service container or the local
docker-compose one) and a mocked Carbon Intensity API — running the Dagster
assets writes the expected rows and is safely re-runnable.

Skipped unless `DATABASE_URL` is set, so it doesn't break unit-only runs.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dagster import materialize
from pytest_httpx import HTTPXMock

from gridpulse.dagster_defs.assets import (
    carbon_intensity_national,
    carbon_intensity_regional,
)
from gridpulse.ingestion.carbon_intensity import BASE_URL
from gridpulse.storage.postgres import close_pool, get_pool

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "carbon_intensity"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _synthetic_national(period_start: datetime) -> dict:
    """A national /intensity response for a controllable period — lets us write
    deterministic rows without depending on the wall clock."""
    end = period_start + timedelta(minutes=30)
    return {
        "data": [
            {
                "from": period_start.strftime("%Y-%m-%dT%H:%MZ"),
                "to": end.strftime("%Y-%m-%dT%H:%MZ"),
                "intensity": {"forecast": 123, "actual": None, "index": "moderate"},
            }
        ]
    }


@pytest.fixture(scope="module", autouse=True)
def _require_database_url() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; integration tests need a Postgres")


@pytest.fixture(scope="module", autouse=True)
def _apply_migrations() -> None:
    """Apply migrations against the integration database before tests run."""
    subprocess.run(
        ["python", "-m", "gridpulse.storage.migrate"],
        check=True,
        env=os.environ.copy(),
    )


@pytest.fixture(autouse=True)
def _clean_carbon_intensity_table() -> None:
    """Each test starts from an empty raw.carbon_intensity. We don't TRUNCATE
    the hypertable directly (Timescale wants `DELETE` on chunks) but a wide
    `DELETE FROM` is fine at this row count."""
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM raw.carbon_intensity")
    yield


@pytest.fixture(scope="module", autouse=True)
def _close_pool_at_end() -> None:
    yield
    close_pool()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_national_asset_writes_one_row(httpx_mock: HTTPXMock) -> None:
    period = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    httpx_mock.add_response(url=f"{BASE_URL}/intensity", json=_synthetic_national(period))

    result = materialize([carbon_intensity_national])
    assert result.success

    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT region_id, forecast_gco2_per_kwh, intensity_index FROM raw.carbon_intensity"
        )
        rows = cur.fetchall()

    assert len(rows) == 1
    assert rows[0]["region_id"] == 0  # NATIONAL sentinel
    assert rows[0]["forecast_gco2_per_kwh"] == 123
    assert rows[0]["intensity_index"] == "moderate"


def test_regional_asset_writes_14_dno_rows(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/regional", json=_load("regional_current.json"))

    result = materialize([carbon_intensity_regional])
    assert result.success

    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT region_id FROM raw.carbon_intensity ORDER BY region_id")
        region_ids = [row["region_id"] for row in cur.fetchall()]

    assert region_ids == list(range(1, 15))


def test_rerunning_national_is_idempotent(httpx_mock: HTTPXMock) -> None:
    period = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    fixture = _synthetic_national(period)
    # Same response served on both materialisations.
    httpx_mock.add_response(url=f"{BASE_URL}/intensity", json=fixture)
    httpx_mock.add_response(url=f"{BASE_URL}/intensity", json=fixture)

    assert materialize([carbon_intensity_national]).success
    assert materialize([carbon_intensity_national]).success

    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM raw.carbon_intensity")
        n = cur.fetchone()["n"]

    # Still exactly one row — natural-key upsert collapsed both writes.
    assert n == 1


def test_realised_actual_is_preserved_when_later_fetch_returns_null(
    httpx_mock: HTTPXMock,
) -> None:
    """A second fetch with actual=NULL must NOT wipe a previously stored
    realised value. This is the COALESCE in the upsert doing its job."""
    period = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    # 1st pass: actual realised at 80.
    realised = _synthetic_national(period)
    realised["data"][0]["intensity"]["actual"] = 80
    httpx_mock.add_response(url=f"{BASE_URL}/intensity", json=realised)
    assert materialize([carbon_intensity_national]).success

    # 2nd pass: actual is null again (same period, fresh forecast).
    forecast_only = _synthetic_national(period)
    httpx_mock.add_response(url=f"{BASE_URL}/intensity", json=forecast_only)
    assert materialize([carbon_intensity_national]).success

    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT actual_gco2_per_kwh FROM raw.carbon_intensity WHERE region_id = 0")
        row = cur.fetchone()

    assert row["actual_gco2_per_kwh"] == 80  # preserved
