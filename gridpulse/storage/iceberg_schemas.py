"""Iceberg table schemas + partition specs for the three V1 archive tables.

Mirrors the column shape of raw.{carbon_intensity, generation_mix, agile_price}
in Postgres. We deliberately drop `ingested_at_utc` from the Iceberg layer —
it's metadata about *us*, not about the data, and Iceberg's snapshot system
already records when each file was written.

Iceberg type notes:
- TimestamptzType(with_timezone=True) maps to Postgres TIMESTAMPTZ.
- IntegerType is 32-bit signed; LongType is 64-bit. We use Integer for the
  small-ish gCO2/kWh and region ids; Long would be wasteful.
- FloatType is 32-bit (matches Postgres REAL); use DoubleType only when you
  genuinely need 64-bit precision.

Field-id discipline:
- Field IDs MUST be unique within a schema AND never reused across schema
  evolutions. We start at 1 and increment; if you drop a column, leave its
  id retired forever.
- Partition-spec field ids start at 1000 by convention.
"""

from __future__ import annotations

from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import DayTransform
from pyiceberg.types import (
    FloatType,
    IntegerType,
    NestedField,
    StringType,
    TimestamptzType,
)
# Note: TimestampType is "no timezone"; TimestamptzType is "with UTC timezone".
# All our `period_start_utc` values are tz-aware (psycopg returns Postgres
# TIMESTAMPTZ as tz-aware datetime), so TimestamptzType matches at runtime.

# ---------------------------------------------------------------------------
# carbon_intensity
# ---------------------------------------------------------------------------

CARBON_INTENSITY_SCHEMA = Schema(
    NestedField(1, "region_id", IntegerType(), required=True),
    NestedField(2, "period_start_utc", TimestamptzType(), required=True),
    NestedField(3, "period_end_utc", TimestamptzType(), required=True),
    NestedField(4, "forecast_gco2_per_kwh", IntegerType(), required=True),
    # NULL for forecast-only periods (and always NULL for regional rows).
    NestedField(5, "actual_gco2_per_kwh", IntegerType(), required=False),
    NestedField(6, "intensity_index", StringType(), required=True),
)

CARBON_INTENSITY_PARTITION_SPEC = PartitionSpec(
    PartitionField(
        source_id=2,  # period_start_utc
        field_id=1000,
        transform=DayTransform(),
        name="period_start_utc_day",
    ),
)


# ---------------------------------------------------------------------------
# generation_mix (national-only, no region_id)
# ---------------------------------------------------------------------------

GENERATION_MIX_SCHEMA = Schema(
    NestedField(1, "period_start_utc", TimestamptzType(), required=True),
    NestedField(2, "gas_mw", FloatType(), required=True),
    NestedField(3, "coal_mw", FloatType(), required=True),
    NestedField(4, "nuclear_mw", FloatType(), required=True),
    NestedField(5, "wind_mw", FloatType(), required=True),
    NestedField(6, "wind_embedded_mw", FloatType(), required=True),
    NestedField(7, "hydro_mw", FloatType(), required=True),
    NestedField(8, "imports_mw", FloatType(), required=True),
    NestedField(9, "biomass_mw", FloatType(), required=True),
    NestedField(10, "other_mw", FloatType(), required=True),
    NestedField(11, "solar_mw", FloatType(), required=True),
    NestedField(12, "storage_mw", FloatType(), required=True),
    NestedField(13, "total_generation_mw", FloatType(), required=True),
    NestedField(14, "neso_carbon_intensity_gco2_per_kwh", FloatType(), required=True),
)

GENERATION_MIX_PARTITION_SPEC = PartitionSpec(
    PartitionField(
        source_id=1,  # period_start_utc
        field_id=1000,
        transform=DayTransform(),
        name="period_start_utc_day",
    ),
)


# ---------------------------------------------------------------------------
# agile_price
# ---------------------------------------------------------------------------

AGILE_PRICE_SCHEMA = Schema(
    NestedField(1, "region_id", IntegerType(), required=True),
    NestedField(2, "period_start_utc", TimestamptzType(), required=True),
    NestedField(3, "period_end_utc", TimestamptzType(), required=True),
    NestedField(4, "price_pence_per_kwh_inc_vat", FloatType(), required=True),
    NestedField(5, "price_pence_per_kwh_exc_vat", FloatType(), required=True),
)

AGILE_PRICE_PARTITION_SPEC = PartitionSpec(
    PartitionField(
        source_id=2,  # period_start_utc
        field_id=1000,
        transform=DayTransform(),
        name="period_start_utc_day",
    ),
)


# ---------------------------------------------------------------------------
# Registry — keyed by Iceberg table name (no namespace prefix here).
# ---------------------------------------------------------------------------

TABLES: dict[str, tuple[Schema, PartitionSpec]] = {
    "carbon_intensity": (CARBON_INTENSITY_SCHEMA, CARBON_INTENSITY_PARTITION_SPEC),
    "generation_mix": (GENERATION_MIX_SCHEMA, GENERATION_MIX_PARTITION_SPEC),
    "agile_price": (AGILE_PRICE_SCHEMA, AGILE_PRICE_PARTITION_SPEC),
}
