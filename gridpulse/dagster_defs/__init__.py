"""Dagster `Definitions` — assets, schedules, sensors. Loaded by webserver and daemon."""

from dagster import Definitions

from .assets import stub_asset

defs = Definitions(assets=[stub_asset])
