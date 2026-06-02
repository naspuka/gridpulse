"""Region lookups against the canonical `ref.dno_region` table.

We deliberately keep these as runtime SQL rather than hard-coding a Python
constant for the 14 DNOs — `ref.dno_region` is the source of truth, and if
we ever add a region (or correct a code) we don't want to keep two lists
in sync. The result is cached per process to avoid hammering the DB.
"""

from __future__ import annotations

import functools

from gridpulse.storage.postgres import get_pool


@functools.cache
def dno_regions_with_octopus_code() -> tuple[tuple[int, str], ...]:
    """Return the 14 DNO regions as `(region_id, octopus_code)` pairs.

    Excludes the NATIONAL sentinel (region_id=0) and anything else whose
    octopus_code is NULL. Cached for the life of the process — the table
    only changes via a migration, never at runtime.
    """
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT region_id, octopus_code FROM ref.dno_region "
            "WHERE octopus_code IS NOT NULL ORDER BY region_id"
        )
        return tuple((row["region_id"], row["octopus_code"]) for row in cur.fetchall())
