# Lakehouse design (Iceberg on Cloudflare R2)

Cold store. Apache Iceberg tables on R2, queried via PyIceberg + DuckDB. Holds full history (back to 2018 for Carbon Intensity) and exists for backtesting, ML training, and the architectural story.

## What Iceberg actually is

Three things stacked on cheap object storage:

1. **Data files** — Parquet, sitting in R2.
2. **Manifest files** — small Avro files listing which Parquet files belong to which snapshot, with column min/max stats per file.
3. **A catalog** — tiny database that says "the current version of table X is the manifest at path Y."

Querying:

- Catalog → "current snapshot is manifest M"
- M → "the table is these N Parquet files, here are their min/max stats"
- Engine (DuckDB) → reads only Parquet files whose stats overlap your `WHERE`

That's it. Iceberg is an indirection layer that makes a pile of Parquet files behave like a database table — with schema evolution, time travel, and atomic writes.

Every architectural choice reduces to three questions: **where does the catalog live, how do we partition the data, how often do we compact.**

## Catalog: SQL catalog in Postgres

PyIceberg's `SqlCatalog`, backed by our existing Postgres in schema `iceberg_catalog`. Zero new infrastructure.

```python
# gridpulse/storage/iceberg.py
from pyiceberg.catalog.sql import SqlCatalog

catalog = SqlCatalog(
    "gridpulse",
    **{
        "uri": os.environ["ICEBERG_CATALOG_URI"],   # postgresql://... (schema=iceberg_catalog)
        "warehouse": "s3://gridpulse-lake/",
        "s3.endpoint": os.environ["R2_ENDPOINT"],
        "s3.access-key-id": os.environ["R2_ACCESS_KEY_ID"],
        "s3.secret-access-key": os.environ["R2_SECRET_ACCESS_KEY"],
        "s3.region": "auto",
    },
)
```

Why this is good:

- Backups: `pg_dump` already covers the catalog. No separate backup story.
- Atomic writes: PyIceberg uses Postgres transactions to update catalog pointers. Parquet write succeeds but catalog update fails → table state unchanged. No half-committed snapshots.
- Disaster recovery: lose the VM, restore Postgres from R2, repoint at the same R2 bucket, table is back.

The trade-off: catalog is now coupled to Postgres uptime. For our workload (one writer, archival overnight) that's fine. At big-co scale you'd run Nessie or AWS Glue.

## Tables

We mirror the **raw** Postgres tables in Iceberg, not marts. Marts are derived; raw is the source of truth.

| Iceberg table | Mirrors | Purpose |
|---|---|---|
| `gridpulse.carbon_intensity` | `raw.carbon_intensity` | Historical record (2018→ backfill) |
| `gridpulse.generation_mix` | `raw.generation_mix` | Long-term renewable mix trends |
| `gridpulse.agile_price` | `raw.agile_price` | Battery arbitrage backtests (V2 use case) |

Schemas mirror the Postgres `raw` tables exactly, modulo Iceberg's type system: `TimestampType(with_timezone=True)`, `IntegerType`, `FloatType`, `StringType`.

We do **not** archive marts. Marts are deterministic functions of raw + dbt. Want a historical mart? Re-run dbt against Iceberg via the dbt-duckdb adapter (V2). Lakehouse stays pure: facts only, no derived columns.

## Partition spec

Partition by the column that 90% of queries filter on, at a granularity that gives **hundreds** of partitions, not millions.

For all three tables: `period_start_utc`, **daily** granularity, via Iceberg's `DayTransform`.

```python
from pyiceberg.partitioning import PartitionSpec, PartitionField
from pyiceberg.transforms import DayTransform

partition_spec = PartitionSpec(
    PartitionField(
        source_id=schema.find_field("period_start_utc").field_id,
        field_id=1000,
        transform=DayTransform(),
        name="period_start_utc_day",
    ),
)
```

Iceberg's *hidden partitioning* means we don't store a separate `partition_date` column — the engine derives it from `period_start_utc`. Queries like `WHERE period_start_utc >= '2024-01-01'` get partition-pruned automatically; users don't need to know about partitions.

Why daily, not monthly:

- Archival writes one day at a time → exactly one new partition per run, never modifies older partitions. Cleanest possible write pattern.
- 365 partitions/year × 8 years × 3 tables ≈ 9,000 files total. PyIceberg handles that comfortably.
- Monthly partitions would be too coarse for "last 7 days" point lookups.
- Hourly would generate tiny-file hell.

## Write semantics: partition overwrite

Naive "append nightly" works until you re-run a day (late-arriving data, bug fix, backfill). Then you get duplicates and Iceberg has no `ON CONFLICT`.

**Pattern: partition overwrite.** Each archival run targets one date and overwrites that partition wholesale.

```python
target_date = "2024-04-27"
rows = postgres.fetch(f"""
    SELECT *
    FROM raw.carbon_intensity
    WHERE period_start_utc >= '{target_date}'::date
      AND period_start_utc <  '{target_date}'::date + INTERVAL '1 day'
""")

table = catalog.load_table("gridpulse.carbon_intensity")
table.overwrite(
    df=rows,
    overwrite_filter=And(
        GreaterThanOrEqual("period_start_utc", target_date),
        LessThan("period_start_utc", next_day),
    ),
)
```

Why this is great:

- Re-running yesterday's archival produces the same result. Idempotent by construction.
- Late-arriving data picked up automatically — re-run yesterday, partition rewritten with corrected set.
- Iceberg handles atomically: new snapshot points at new file; old file dereferenced (GC'd by snapshot expiry).

Cost: rewriting a whole day instead of appending. At ~50 KB/day, irrelevant.

## Compaction (not in V1)

Tiny files are Iceberg's classic failure mode. With daily partitions and one writer, we generate exactly one Parquet file per partition per write. No compaction needed.

If we ever start appending multiple files per partition (e.g. intra-day archival), we'd add a weekly `table.rewrite_data_files(...)` job. **Out of V1 scope.**

## Snapshot management

Every write creates a snapshot. Snapshots accumulate forever and keep old data files alive (for time travel) — unbounded retention = unbounded R2 storage.

**Policy: keep 30 days of snapshots.** Weekly Dagster job calls `table.expire_snapshots(older_than=30 days)`. Dereferenced Parquet files get deleted from R2.

Only "maintenance" job the lakehouse needs.

## Backfill (the big one-off)

Carbon Intensity API has data back to 2018. Backfill once, then forget.

Strategy:

1. Dagster asset `backfill_carbon_intensity_iceberg` taking a date range as a partition.
2. Loops one **month** at a time (CI API supports up to 14 days per call; month is just our chunking convenience).
3. For each month: paginated API call → pydantic validation → write directly to Iceberg, **bypassing Postgres**.

Why bypass Postgres: 8 years × 365 days × 720 rows ≈ 2M rows. Postgres only retains 90 days — putting 2M rows through Postgres just to delete most of them is wasteful. Direct-to-Iceberg is cleaner.

Backfill is a **one-off Dagster job** (no schedule). Triggered manually from the UI when you want it. Safe to re-run any partition (overwrite semantics).

Backfill scope:

- Carbon Intensity from 2018 — yes
- NESO mix ~2 years — yes (older NESO data is messier)
- Octopus Agile — no (pre-April-2026 prices not directly comparable due to levy reform; flagged in [data-contracts.md](./data-contracts.md))

## Reading Iceberg in V1

For V1, hot path is Postgres. Iceberg is read by:

1. **DuckDB ad-hoc queries** from a Python REPL or notebook, for exploration.
2. **dbt-duckdb adapter** in V2 if/when we want historical marts.
3. **Nothing in the live serving path.** FastAPI never reads Iceberg directly — cold-storage latency on a small VM is unpredictable; keep it off the user request path.

```python
import duckdb
con = duckdb.connect()
con.execute("INSTALL iceberg; LOAD iceberg;")
con.execute("CREATE SECRET r2 (TYPE S3, KEY_ID '...', SECRET '...', ENDPOINT '...');")
df = con.execute("""
    SELECT date_trunc('month', period_start_utc) AS month,
           AVG(actual_gco2_per_kwh) AS avg_intensity
    FROM iceberg_scan('s3://gridpulse-lake/carbon_intensity')
    WHERE region_id = 0
    GROUP BY 1 ORDER BY 1
""").df()
```

Interview soundbite: *"I can query 8 years of half-hourly data in seconds, on a £7/month VM, because DuckDB pushes filters into Iceberg's partition stats."*

## R2 bucket layout

Single bucket, one warehouse path. Iceberg manages everything below — we don't curate paths by hand.

```
s3://gridpulse-lake/
├── carbon_intensity/
│   ├── data/period_start_utc_day=2024-01-01/00000-...parquet
│   └── metadata/...metadata.json, ...snap.avro
├── generation_mix/
└── agile_price/
```

Bucket settings:

- **Versioning:** off (Iceberg's snapshots *are* our versioning; bucket versioning would double-bill)
- **Lifecycle rules:** none (snapshot expiry handles GC)
- **CORS:** none (no browser access)
- **Access:** one R2 token, scoped read/write to this bucket only

## Sizing sanity check

| Source | Rows/year | Parquet B/row | Years | Total |
|---|---|---|---|---|
| Carbon Intensity (15 regions × 48 hh) | ~263k | ~30 | 8 | ~63 MB |
| Generation Mix (national) | ~17.5k | ~80 | 4 | ~6 MB |
| Agile Price (14 regions × 48 hh) | ~245k | ~30 | 2 | ~15 MB |
| **Total** | | | | **~85 MB** |

Comfortably inside R2's 10 GB free tier. Two orders of magnitude of headroom.

## Soundbite

> *"Hot store is Postgres + TimescaleDB on the VM, holding 90 days for sub-second user queries. Cold store is Iceberg on Cloudflare R2 — a real lakehouse format with schema evolution and snapshot-based time travel. The catalog is SQL-based, co-located in Postgres, so it's covered by the same backups. Each archival run does a partition overwrite, which makes idempotent re-runs trivial. R2's zero-egress pricing is the unlock that makes the lakehouse affordable on this budget — on S3 it would cost more in egress than everything else combined."*
