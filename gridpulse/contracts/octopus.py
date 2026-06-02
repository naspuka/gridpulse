"""Octopus Energy contract — Agile tariff unit rates.

Endpoint shape:
    GET /v1/products/{product}/electricity-tariffs/E-1R-{product}-{REGION}/standard-unit-rates/

Where:
- `product` is the current Agile product code (live in 2026: AGILE-24-10-01).
  Octopus rotates this every few years; the previous AGILE-FLEX-22-11-25
  product was retired in late 2024 and now only serves historical data.
- `REGION` is the single-letter DNO code (A-P, with gaps) — stored in
  `ref.dno_region.octopus_code`.

Response shape (relevant fields per result):
- value_exc_vat / value_inc_vat : float, pence per kWh
- valid_from / valid_to         : ISO 8601 with Z suffix (UTC) — no naive
                                  conversions needed
- payment_method                : null for Agile (always)

The endpoint paginates with `?page=` and a `next` cursor URL in the body.
Half-hourly cadence: each /standard-unit-rates response has up to ~48 rows
per UK day, published in batches as Octopus settles them.

Region context lives in the URL, not the body. `to_rows()` therefore takes
the region's `region_id` as a parameter — that's how we tag the rows.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Wire-shape models
# ---------------------------------------------------------------------------


class _AgileRate(BaseModel):
    """One half-hourly unit-rate entry."""

    model_config = ConfigDict(extra="forbid")

    value_exc_vat: float
    value_inc_vat: float
    valid_from: datetime
    valid_to: datetime
    # Always null for Agile (no payment-method differentiation). Captured
    # explicitly so we hear about it if that ever changes.
    payment_method: str | None


class AgileRatesResponse(BaseModel):
    """Wire shape of `GET /standard-unit-rates/`."""

    model_config = ConfigDict(extra="forbid")

    count: int
    next: str | None
    previous: str | None
    results: list[_AgileRate]

    def to_rows(self, *, region_id: int) -> list[AgilePriceRow]:
        return [
            AgilePriceRow(
                region_id=region_id,
                period_start_utc=r.valid_from,
                period_end_utc=r.valid_to,
                price_pence_per_kwh_inc_vat=r.value_inc_vat,
                price_pence_per_kwh_exc_vat=r.value_exc_vat,
            )
            for r in self.results
        ]


# ---------------------------------------------------------------------------
# Our normalised row — what gets upserted into raw.agile_price.
# ---------------------------------------------------------------------------


class AgilePriceRow(BaseModel):
    """One row per (region, half-hour). Natural key: (region_id, period_start_utc).

    Prices are in pence per kWh as published by Octopus. We store both
    inc-VAT and exc-VAT explicitly — the UI usually shows inc-VAT, but
    interview folk may want exc-VAT for like-for-like comparison with
    wholesale, and storing both is cheaper than recomputing one from the
    other (VAT rates have changed in the past).
    """

    model_config = ConfigDict(extra="forbid")

    region_id: int  # FK to ref.dno_region (1..14 — no national)
    period_start_utc: datetime
    period_end_utc: datetime
    price_pence_per_kwh_inc_vat: float
    price_pence_per_kwh_exc_vat: float
