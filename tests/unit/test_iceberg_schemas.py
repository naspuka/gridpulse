"""Unit tests for the Iceberg schema + partition definitions.

No catalog or R2 required — these tests are pure object inspection. They
lock the field-id discipline (Iceberg's #1 footgun: reused ids corrupt the
table) and confirm every table has a sensible daily partition.
"""

from __future__ import annotations

from pyiceberg.transforms import DayTransform

from gridpulse.storage.iceberg_schemas import (
    AGILE_PRICE_SCHEMA,
    CARBON_INTENSITY_SCHEMA,
    GENERATION_MIX_SCHEMA,
    TABLES,
)


def test_registry_lists_three_tables() -> None:
    assert set(TABLES) == {"carbon_intensity", "generation_mix", "agile_price"}


def test_every_table_partitions_by_day_on_period_start() -> None:
    for name, (schema, spec) in TABLES.items():
        fields = list(spec.fields)
        assert len(fields) == 1, f"{name}: expected one partition field, got {len(fields)}"
        (field,) = fields
        assert isinstance(field.transform, DayTransform), name
        # The source column must be the timestamp we partition by.
        source = schema.find_column_name(field.source_id)
        assert source == "period_start_utc", name


def test_field_ids_are_unique_within_each_schema() -> None:
    """Iceberg requires field ids be unique within a table and never reused."""
    for name, (schema, _spec) in TABLES.items():
        ids = [f.field_id for f in schema.fields]
        assert len(ids) == len(set(ids)), f"{name}: duplicate field ids {ids}"


def test_carbon_intensity_actual_is_optional() -> None:
    actual = next(f for f in CARBON_INTENSITY_SCHEMA.fields if f.name == "actual_gco2_per_kwh")
    assert actual.required is False  # NULL for forecast-only + regional rows.


def test_carbon_intensity_required_fields() -> None:
    required = {f.name for f in CARBON_INTENSITY_SCHEMA.fields if f.required}
    assert required == {
        "region_id",
        "period_start_utc",
        "period_end_utc",
        "forecast_gco2_per_kwh",
        "intensity_index",
    }


def test_generation_mix_has_13_fuel_or_total_columns_plus_timestamp() -> None:
    # 11 fuels + 1 total + 1 NESO CI + 1 timestamp = 14 fields.
    assert len(GENERATION_MIX_SCHEMA.fields) == 14


def test_agile_price_keeps_both_vat_variants() -> None:
    columns = {f.name for f in AGILE_PRICE_SCHEMA.fields}
    assert "price_pence_per_kwh_inc_vat" in columns
    assert "price_pence_per_kwh_exc_vat" in columns


def test_partition_field_ids_start_at_1000() -> None:
    """Convention: partition-spec ids in the 1000+ range to avoid collision
    with column ids — also recommended by the Iceberg spec."""
    for _name, (_schema, spec) in TABLES.items():
        for field in spec.fields:
            assert field.field_id >= 1000
