"""People tools — your Reclaim.ai people directory.

Reclaim builds an internal directory of collaborators based on calendar and
meeting history. These tools expose that directory for context and for
seeding 1:1s.
"""

from fastmcp.exceptions import ToolError

from reclaim_mcp.cache import ttl_cache
from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.exceptions import RateLimitError, ReclaimError


def _get_client() -> ReclaimClient:
    settings = get_settings()
    return ReclaimClient(settings)


@ttl_cache(ttl=300)
async def list_people() -> list[dict]:
    """List all people in the Reclaim directory."""
    try:
        client = _get_client()
        return await client.get("/api/people")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error listing people: {e}")


async def sync_people() -> dict:
    """Trigger a sync of the people directory from connected calendars."""
    try:
        client = _get_client()
        return await client.post("/api/people/sync", data={})
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error syncing people: {e}")


@ttl_cache(ttl=300)
async def list_people_subscriptions() -> list[dict]:
    """List people you're subscribed to (calendar shares / smart meetings)."""
    try:
        client = _get_client()
        return await client.get("/api/people/subscriptions")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error listing people subscriptions: {e}")
