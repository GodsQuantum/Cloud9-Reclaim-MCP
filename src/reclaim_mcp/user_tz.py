"""Resolve the user's IANA timezone for time-parsing in tools.

Precedence: RECLAIM_TIMEZONE env var > /api/timeschemes > system tz > UTC.
Results are cached so hot-path tools don't re-hit the API.
"""

from __future__ import annotations

from reclaim_mcp.cache import ttl_cache
from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.tools.context import _extract_tz_from_timeschemes, _system_tz


@ttl_cache(ttl=600)
async def get_user_tz() -> str:
    """Return the user's IANA timezone name (e.g., 'America/Los_Angeles').

    Checked in order: RECLAIM_TIMEZONE env var, Reclaim's /api/timeschemes,
    the system timezone, then UTC. Cached for 10 minutes.
    """
    settings = get_settings()
    if settings.timezone:
        return settings.timezone

    try:
        client = ReclaimClient(settings)
        timeschemes = await client.get("/api/timeschemes")
        tz = _extract_tz_from_timeschemes(timeschemes)
        if tz:
            return tz
    except Exception:
        pass

    return _system_tz()
