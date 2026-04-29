# Data contracts

Every external API response goes through a pydantic v2 model before any other code touches it. The model is **the** contract: schema drift fails loudly here, not silently downstream.

## Why contracts come first

Most data bugs aren't logic bugs — they're assumptions about input that quietly stopped being true. Field renamed. Nullable field starts being null. Timestamp changes from UTC to local. Without contracts, those changes propagate and you find out via a wrong dashboard number, weeks later.

Contracts force three things:

1. **Explicit field names + types** — drift = exception, not wrong number.
2. **Normalisation at the edge** — the model is where "their format" becomes "our format" (parse their ISO string into a `datetime` with `tzinfo=UTC`).
3. **A single place** to look when onboarding to the codebase. `gridpulse/contracts/` *is* the data dictionary.

## Two-layer pattern (per source)

Every source has two pydantic models:

| Layer | Job | Lifetime |
|---|---|---|
| `RawXxxResponse` | Validate the wire format exactly as the API sends it | Validation only — never stored |
| `XxxRow` | Our normalised, UTC-aware row, ready for Postgres insert | Goes to the storage layer |

`RawXxxResponse.to_rows()` is the conversion. All time-zone handling, settlement-period math, and region-code lookups happen there and nowhere else.

```python
# gridpulse/contracts/<source>.py
class RawXxxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    # ... wire-shape fields ...

    def to_rows(self) -> list[XxxRow]:
        # all normalisation lives here
        ...

class XxxRow(BaseModel):
    # our shape: UTC datetimes, our column names, natural keys
    ...
```

## Cross-cutting conventions

These apply to all three V1 sources. Locking them in saves churn.

1. **`extra="forbid"` on raw models.** New API field → noisy CI failure on the next captured fixture, not silent ignoring. Loud > silent for a learning project.
2. **All `datetime` fields in `XxxRow` are tz-aware UTC.** The model rejects naive datetimes via a validator.
3. **`ingested_at_utc` is set by the storage layer, not the contract.** The contract is the *source* shape; ingestion timestamp is metadata about *us*.
4. **Fixtures live in `tests/fixtures/`** — one captured JSON per endpoint, committed. Tests parse them through the raw model. CI catches regressions when an API quietly changes.
5. **No dbt logic leaks into contracts.** Contracts know nothing about marts, joins, or business caveats (e.g. the April 2026 Octopus levy reform). They're the API → row boundary, full stop.
6. **One file per source.** No shared "common" module — duplication is fine; coupling is not.

## V1 sources

### Carbon Intensity API — `gridpulse/contracts/carbon_intensity.py`

- **Endpoints:** `/intensity` (national), `/regional` (14 DNOs), `/intensity/{from}/{to}` (historical backfill)
- **Auth:** none
- **Wire timestamps:** ISO 8601 with `Z` (UTC) — easy
- **Nullable:** `intensity.actual` is null for future half-hours; model as `int | None`
- **Natural key (row):** `(region_id, period_start_utc)`
- **Notes:** `forecast` and `actual` are separate columns on `XxxRow`. Re-ingesting the same period updates both.

### NESO Data Portal (generation mix) — `gridpulse/contracts/neso.py`

- **Endpoint:** CKAN dataset (e.g. `historic-generation-mix` / `gb-fuel-type-production` — confirm exact dataset at integration time)
- **Auth:** API token (free, since June 2024)
- **Wire timestamps:** *naive* UK local time — convert to UTC in `to_rows()` using `zoneinfo.ZoneInfo("Europe/London")`
- **Wire shape:** wide (one column per fuel: `GAS`, `WIND`, `SOLAR`, …)
- **Format choice:** store wide in `raw` and `staging`; pivot to long in dbt mart layer. Deliberate — gives a textbook dbt example.
- **Natural key:** `(period_start_utc)` — national only, no region
- **DST trap:** UK clocks change in March/October; those days have 46 or 50 settlement periods. Tests must cover both.

### Octopus Energy (Agile prices) — `gridpulse/contracts/octopus.py`

- **Endpoint:** `/v1/products/AGILE-FLEX-22-11-25/electricity-tariffs/E-1R-AGILE-FLEX-22-11-25-{REGION}/standard-unit-rates/` (confirm product code at integration)
- **Auth:** none for tariff data
- **Wire timestamps:** UTC with `Z` — easy
- **Region codes:** Octopus uses single letters (`A`–`P`, with gaps). Carbon Intensity uses different short codes. NESO is national. The canonical mapping lives in `ref.dno_region` in Postgres — see [database-design.md](./database-design.md).
- **Cadence:** daily after 16:00 UK; we loop all 14 regions
- **Caveat (April 2026 levy reform):** ~3.5p/kWh structural drop. **NOT encoded in the contract** — surfaced as a derived column `is_post_2026_levy_reform` in the dbt mart layer. Contract stays pure: it just records what the API returned.
- **Natural key:** `(region_id, period_start_utc)`

## What contracts are *not* responsible for

- Joining sources together (that's marts)
- Region-code lookups (that's the storage layer using `ref.dno_region`)
- Detecting historical discontinuities (that's marts)
- Caching API responses (that's the ingestion layer's HTTP client)
- Retries / backoff (that's `gridpulse/ingestion/http.py` with tenacity)

Keeping contracts narrow is what makes them durable. A Carbon Intensity API quirk should never require touching `marts/` or `api/`.

## Testing

Three flavours of test, all driven by fixtures under `tests/fixtures/`:

1. **Snapshot test:** every committed fixture parses through `RawXxxResponse` without error.
2. **Round-trip test:** `RawXxxResponse(...).to_rows()` produces N rows for an N-period response, with all timestamps tz-aware UTC.
3. **Drift test (the important one):** add a junk field to a fixture copy and assert that `RawXxxResponse(...)` raises. Proves `extra="forbid"` is doing its job.

Fixtures are refreshed manually when an API legitimately changes. The PR diff makes the change visible — that *is* the change-management process.
