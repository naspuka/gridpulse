"""NESO Data Portal contract — generation mix.

The relevant dataset is `historic-generation-mix` (resource id
f93d1835-75bc-43e5-84ad-12472b180a98) on api.neso.energy, served via CKAN.
Each row is one half-hour of national generation by fuel type.

NESO surprises:
- The `DATETIME` field is naive ISO ("2026-06-02T12:00:00") but the dataset's
  own metadata explicitly states UTC. We parse it as UTC. DST has no effect
  in UTC — there are always 48 half-hours per day, no 46/50 weirdness.
- The wire payload has 35 fields. We capture all of them in the Raw model
  (extra="forbid", schema drift fails loudly) but only emit 14 into the row
  model: the 11 fuel MW columns, total generation, NESO's own carbon
  intensity (useful as a cross-check against the Carbon Intensity API), and
  the timestamp. The _perc and aggregate columns (LOW_CARBON, RENEWABLE, …)
  are derived — dbt recomputes them in the mart layer.
- WIND_EMB (embedded wind, smaller behind-the-meter farms) is reported
  separately from WIND (transmission-connected). We preserve the split in
  raw; sum in marts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _parse_neso_datetime(value: object) -> datetime:
    """NESO sends `"2026-06-02T12:00:00"` (naive ISO, but UTC by dataset spec)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        raise TypeError(f"expected str or datetime, got {type(value).__name__}")
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


NesoUtcDatetime = Annotated[datetime, BeforeValidator(_parse_neso_datetime)]


# ---------------------------------------------------------------------------
# Wire-shape model — what the CKAN datastore_search response looks like.
# ---------------------------------------------------------------------------


class _NesoGenerationMixRecord(BaseModel):
    """One half-hour record as NESO emits it. 35 fields."""

    model_config = ConfigDict(extra="forbid")

    # _id is CKAN's row id, useful for pagination if we ever need it.
    id: int = Field(alias="_id")
    DATETIME: NesoUtcDatetime

    # Fuel-type MW (transmission-connected unless noted).
    GAS: float
    COAL: float
    NUCLEAR: float
    WIND: float
    WIND_EMB: float  # embedded (small + behind-the-meter) wind
    HYDRO: float
    IMPORTS: float
    BIOMASS: float
    OTHER: float
    SOLAR: float
    STORAGE: float  # net battery / pumped-storage (can be negative)

    # Roll-ups (derived; we ignore in mart but parse to detect drift).
    GENERATION: float
    CARBON_INTENSITY: float  # NESO's own number (gCO2/kWh), distinct from CI API
    LOW_CARBON: float
    ZERO_CARBON: float
    RENEWABLE: float
    FOSSIL: float

    # Percentages — same derivations expressed as %. Captured for drift detection.
    GAS_perc: float
    COAL_perc: float
    NUCLEAR_perc: float
    WIND_perc: float
    WIND_EMB_perc: float
    HYDRO_perc: float
    IMPORTS_perc: float
    BIOMASS_perc: float
    OTHER_perc: float
    SOLAR_perc: float
    STORAGE_perc: float
    GENERATION_perc: float
    LOW_CARBON_perc: float
    ZERO_CARBON_perc: float
    RENEWABLE_perc: float
    FOSSIL_perc: float


class _NesoCkanResult(BaseModel):
    """The `result` wrapper inside a CKAN datastore_search response."""

    model_config = ConfigDict(extra="allow")  # CKAN's envelope has lots of fluff

    records: list[_NesoGenerationMixRecord]
    total: int | None = None


class NesoGenerationMixResponse(BaseModel):
    """Wire shape of `GET /api/3/action/datastore_search?resource_id=...`."""

    model_config = ConfigDict(extra="allow")  # CKAN: success, help, result

    success: bool
    result: _NesoCkanResult

    def to_rows(self) -> list[NesoGenerationMixRow]:
        if not self.success:
            raise ValueError("CKAN response success=false")
        return [
            NesoGenerationMixRow(
                period_start_utc=r.DATETIME,
                gas_mw=r.GAS,
                coal_mw=r.COAL,
                nuclear_mw=r.NUCLEAR,
                wind_mw=r.WIND,
                wind_embedded_mw=r.WIND_EMB,
                hydro_mw=r.HYDRO,
                imports_mw=r.IMPORTS,
                biomass_mw=r.BIOMASS,
                other_mw=r.OTHER,
                solar_mw=r.SOLAR,
                storage_mw=r.STORAGE,
                total_generation_mw=r.GENERATION,
                neso_carbon_intensity_gco2_per_kwh=r.CARBON_INTENSITY,
            )
            for r in self.result.records
        ]


# ---------------------------------------------------------------------------
# Our normalised row — what gets upserted into raw.generation_mix.
# ---------------------------------------------------------------------------


class NesoGenerationMixRow(BaseModel):
    """One row per half-hour. Natural key: (period_start_utc).

    NESO's generation mix is national-only; no region. The 14 fuel columns
    are MW (mean over the half-hour). `storage_mw` can be negative (charging).
    """

    model_config = ConfigDict(extra="forbid")

    period_start_utc: datetime

    gas_mw: float
    coal_mw: float
    nuclear_mw: float
    wind_mw: float
    wind_embedded_mw: float
    hydro_mw: float
    imports_mw: float
    biomass_mw: float
    other_mw: float
    solar_mw: float
    storage_mw: float

    total_generation_mw: float
    neso_carbon_intensity_gco2_per_kwh: float
