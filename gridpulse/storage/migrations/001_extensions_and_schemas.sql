-- 001 — Extensions and schemas.
--
-- TimescaleDB enables hypertables for the time-series fact tables (added in
-- later migrations). Schemas separate raw landing, dbt staging, dbt marts,
-- reference / dimension tables, and the Iceberg SQL catalog.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS iceberg_catalog;
