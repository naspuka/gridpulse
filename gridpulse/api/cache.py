"""In-process TTL cache for hot read queries.

Why not Redis (per docs/api-design.md):
- One FastAPI process per VM. In-process is sufficient.
- If we ever go multi-worker and see cache stampedes, *then* Redis. Not before.
- Hot-cache misses still hit Postgres directly (no fall-through layer).

Default TTL of 30 s mirrors the half-hour data cadence — most "current"
queries answer the same question 60 times in a half-hour, all served from
cache after the first miss.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from cachetools import TTLCache

# Modest size; the API surface is small. Bump if we grow it.
_CURRENT_CACHE: TTLCache[tuple[Any, ...], Any] = TTLCache(maxsize=256, ttl=30)
# Range queries are heavier and less repetitive; cache for slightly longer.
_RANGE_CACHE: TTLCache[tuple[Any, ...], Any] = TTLCache(maxsize=128, ttl=120)


def _hashable_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, ...]:
    """Cache key derived from args/kwargs. All values must be hashable —
    we use this only for queries that take ints, strs, datetimes."""
    return args + tuple(sorted(kwargs.items()))


def cache_current[F: Callable[..., Any]](func: F) -> F:
    """Decorator: cache the wrapped function's return for 30 s, keyed on args."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        key = (func.__qualname__, _hashable_key(args, kwargs))
        if key in _CURRENT_CACHE:
            return _CURRENT_CACHE[key]
        result = func(*args, **kwargs)
        _CURRENT_CACHE[key] = result
        return result

    return wrapper  # type: ignore[return-value]


def cache_range[F: Callable[..., Any]](func: F) -> F:
    """Decorator: cache for 120 s. For range queries."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        key = (func.__qualname__, _hashable_key(args, kwargs))
        if key in _RANGE_CACHE:
            return _RANGE_CACHE[key]
        result = func(*args, **kwargs)
        _RANGE_CACHE[key] = result
        return result

    return wrapper  # type: ignore[return-value]


def clear_all() -> None:
    """Drop all cached values. Mostly for tests."""
    _CURRENT_CACHE.clear()
    _RANGE_CACHE.clear()
