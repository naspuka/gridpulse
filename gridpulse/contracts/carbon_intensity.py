"""Carbon Intensity API contract.

Two endpoints, three layers:
- `CarbonIntensityNationalResponse` mirrors `GET /intensity`.
- `CarbonIntensityRegionalResponse` mirrors `GET /regional`.
- `CarbonIntensityRow` is our normalised row, written to `raw.carbon_intensity`.

The wire shape of national and regional differ in a load-bearing way:
- National includes `actual` (int, nullable until realised).
- Regional has `forecast` and `index` only — no `actual` field.

Both source responses produce rows of the SAME shape (`CarbonIntensityRow`),
with `actual_gco2_per_kwh` always `None` for regional rows. The `region_id`
distinguishes them: 0 = NATIONAL sentinel, 1..14 = DNO regions.

We deliberately ignore the per-region `generationmix` for V1 — generation mix
at national grain comes from the NESO Data Portal source. The CI regional
generation mix could be added in V2 if we want regional fuel breakdowns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Carbon Intensity API enumeration. Matches the `intensity.index` field exactly.
CIIndex = Literal["very low", "low", "moderate", "high", "very high"]

# The four "rollup" regionids returned by /regional that aren't DNO regions.
# We skip these in to_rows() — the National data comes from /intensity which
# also includes `actual`, so the GB rollup (regionid 18) would be redundant
# and forecast-only.
_ROLLUP_REGION_IDS: frozenset[int] = frozenset({15, 16, 17, 18})

# Our internal sentinel for the national rollup. See ref.dno_region.
_NATIONAL_REGION_ID: int = 0


# ---------------------------------------------------------------------------
# Wire-shape models — what the API actually sends.
# ---------------------------------------------------------------------------


class _NationalIntensity(BaseModel):
    """`intensity` block inside a national period."""

    model_config = ConfigDict(extra="forbid")

    forecast: int
    # `actual` is `null` for future half-hours. Pydantic represents that as None.
    actual: int | None
    index: CIIndex


class _NationalPeriod(BaseModel):
    """One half-hour period in the /intensity response."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # `from` is a Python keyword; alias keeps the wire name but lets us
    # use `from_` in code.
    from_: datetime = Field(alias="from")
    to: datetime
    intensity: _NationalIntensity


class CarbonIntensityNationalResponse(BaseModel):
    """Wire shape of `GET /intensity` (and `GET /intensity/{from}/{to}`)."""

    model_config = ConfigDict(extra="forbid")

    data: list[_NationalPeriod]

    def to_rows(self) -> list[CarbonIntensityRow]:
        return [
            CarbonIntensityRow(
                region_id=_NATIONAL_REGION_ID,
                period_start_utc=p.from_,
                period_end_utc=p.to,
                forecast_gco2_per_kwh=p.intensity.forecast,
                actual_gco2_per_kwh=p.intensity.actual,
                intensity_index=p.intensity.index,
            )
            for p in self.data
        ]


class _RegionalIntensity(BaseModel):
    """`intensity` block inside a regional period. Note: no `actual`."""

    model_config = ConfigDict(extra="forbid")

    forecast: int
    index: CIIndex


class _RegionalGenerationMixEntry(BaseModel):
    """One fuel-percent pair inside a region's generationmix."""

    model_config = ConfigDict(extra="forbid")

    fuel: str
    perc: float


class _Region(BaseModel):
    """One DNO region (or rollup) inside a regional period."""

    model_config = ConfigDict(extra="forbid")

    # 1..14 = DNO regions; 15-18 = rollups (England/Scotland/Wales/GB).
    regionid: int
    dnoregion: str
    shortname: str
    intensity: _RegionalIntensity
    # Captured for shape fidelity; we don't write it to Postgres in V1.
    generationmix: list[_RegionalGenerationMixEntry]


class _RegionalPeriod(BaseModel):
    """One half-hour period in /regional, holding all 18 region entries."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: datetime = Field(alias="from")
    to: datetime
    regions: list[_Region]


class CarbonIntensityRegionalResponse(BaseModel):
    """Wire shape of `GET /regional`."""

    model_config = ConfigDict(extra="forbid")

    data: list[_RegionalPeriod]

    def to_rows(self) -> list[CarbonIntensityRow]:
        rows: list[CarbonIntensityRow] = []
        for period in self.data:
            for region in period.regions:
                # Skip rollups — we get the national-level data from /intensity
                # (which carries `actual`); the rollups are forecast-only and
                # would duplicate columns without adding value.
                if region.regionid in _ROLLUP_REGION_IDS:
                    continue
                rows.append(
                    CarbonIntensityRow(
                        region_id=region.regionid,
                        period_start_utc=period.from_,
                        period_end_utc=period.to,
                        forecast_gco2_per_kwh=region.intensity.forecast,
                        actual_gco2_per_kwh=None,  # regional API has no actual
                        intensity_index=region.intensity.index,
                    )
                )
        return rows


# ---------------------------------------------------------------------------
# Our normalised row — what gets upserted into raw.carbon_intensity.
# ---------------------------------------------------------------------------


class CarbonIntensityRow(BaseModel):
    """One row per (region, half-hour). Natural key: (region_id, period_start_utc)."""

    model_config = ConfigDict(extra="forbid")

    # 0 = NATIONAL sentinel; 1..14 = DNO regions. See ref.dno_region.
    region_id: int
    period_start_utc: datetime
    period_end_utc: datetime
    forecast_gco2_per_kwh: int
    # `None` always for regional rows; carries the realised value for national
    # half-hours that have already happened.
    actual_gco2_per_kwh: int | None
    intensity_index: CIIndex
