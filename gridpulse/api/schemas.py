"""API response models.

These are DELIBERATELY separate from the ingestion contracts in
`gridpulse.contracts.*`:
- Contracts validate INPUT shape (what the upstream API sends us).
- Schemas define OUR OUTPUT shape (what FastAPI serialises to clients).

Coupling the two means a wire-format change at one source would ripple
through every API consumer — which is the opposite of why we have
contracts. Decoupled, the API surface evolves on its own cadence.

All timestamps are ISO-8601 with `Z` (UTC). Pydantic emits them that way
by default for tz-aware datetimes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CIIndex = Literal["very low", "low", "moderate", "high", "very high"]


# ---------------------------------------------------------------------------
# Region dimension
# ---------------------------------------------------------------------------


class Region(BaseModel):
    """One DNO region (or NATIONAL sentinel)."""

    model_config = ConfigDict(extra="forbid")

    region_id: int = Field(description="0 = NATIONAL; 1..14 = DNO regions.")
    canonical_code: str = Field(description="e.g. NATIONAL, LONDON, NORTH_SCOTLAND.")
    slug: str = Field(description="URL slug, e.g. national, london, north-scotland.")
    name: str = Field(description="Human-readable name, e.g. London.")
    octopus_code: str | None = Field(
        default=None, description="Single-letter DNO code; null for NATIONAL."
    )


class RegionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regions: list[Region]


# ---------------------------------------------------------------------------
# Carbon intensity
# ---------------------------------------------------------------------------


class CarbonIntensityPoint(BaseModel):
    """One half-hour of carbon intensity for one region."""

    model_config = ConfigDict(extra="forbid")

    region_id: int
    period_start_utc: datetime
    period_end_utc: datetime
    forecast_gco2_per_kwh: int
    actual_gco2_per_kwh: int | None
    intensity_index: CIIndex


class CarbonIntensityCurrentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: Region
    current: CarbonIntensityPoint


class CarbonIntensityRangeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: Region
    points: list[CarbonIntensityPoint]


# ---------------------------------------------------------------------------
# Agile price
# ---------------------------------------------------------------------------


class AgilePricePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: int
    period_start_utc: datetime
    period_end_utc: datetime
    price_pence_per_kwh_inc_vat: float
    price_pence_per_kwh_exc_vat: float


class AgilePriceCurrentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: Region
    current: AgilePricePoint | None = Field(
        default=None,
        description=(
            "May be null if no price has been published for the current half-hour "
            "(common for periods outside the next-day window Octopus has released)."
        ),
    )


class AgilePriceRangeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: Region
    points: list[AgilePricePoint]


# ---------------------------------------------------------------------------
# Generation mix (national only)
# ---------------------------------------------------------------------------


class GenerationMixFuel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fuel: str = Field(
        description="gas / coal / nuclear / wind / wind_emb / hydro / imports / biomass / other / solar / storage."
    )
    mw: float
    is_renewable: bool
    share_of_generation_pct: float | None = Field(
        default=None, description="0-100, null when total generation is 0/null."
    )


class GenerationMixCurrentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_start_utc: datetime
    fuels: list[GenerationMixFuel]


# ---------------------------------------------------------------------------
# Best slots
# ---------------------------------------------------------------------------


class BestSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_start_utc: datetime
    period_end_utc: datetime
    price_pence_per_kwh_inc_vat: float | None
    forecast_gco2_per_kwh: int | None
    cheapest_rank: int | None
    greenest_rank: int | None


class BestSlotsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: Region
    computed_at_utc: datetime
    slots: list[BestSlot]


# ---------------------------------------------------------------------------
# Health / status
# ---------------------------------------------------------------------------


class LastIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    last_period_utc: datetime | None
    last_ingest_utc: datetime | None
    row_count: int


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_ok: bool
    last_ingests: list[LastIngest]
