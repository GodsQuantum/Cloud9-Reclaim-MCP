"""Schedule policy tools — read and update how Reclaim schedules each kind
of activity.

Schedule policies define which hours of which days are eligible for tasks,
focus blocks, habits, and meetings.
"""

from typing import Optional

from fastmcp.exceptions import ToolError

from reclaim_mcp.cache import ttl_cache
from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.exceptions import RateLimitError, ReclaimError


def _get_client() -> ReclaimClient:
    settings = get_settings()
    return ReclaimClient(settings)


@ttl_cache(ttl=300)
async def list_schedule_policies() -> list[dict]:
    """List all schedule policies (one per scheduling type)."""
    try:
        client = _get_client()
        return await client.get("/api/schedule-policy")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error listing schedule policies: {e}")


async def get_schedule_policy(policy_id: str) -> dict:
    """Get a single schedule policy by id."""
    try:
        client = _get_client()
        return await client.get(f"/api/schedule-policy/{policy_id}")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting schedule policy {policy_id}: {e}")


@ttl_cache(ttl=300)
async def list_available_policy_types() -> list[dict]:
    """List the policy types Reclaim can create on this account."""
    try:
        client = _get_client()
        return await client.get("/api/schedule-policy/available-types")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error listing policy types: {e}")


async def update_schedule_policy(
    policy_id: str,
    body: dict,
) -> dict:
    """Update a schedule policy with a raw body.

    The shape of `body` depends on the policy type — fetch the policy first
    with `get_schedule_policy` to inspect its current fields and then send a
    full replacement body. Refer to Reclaim's policy documentation for valid
    keys (e.g. `dayHours`, `priority`, `defenseAggression`).
    """
    try:
        client = _get_client()
        return await client.put(f"/api/schedule-policy/{policy_id}", data=body)
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error updating schedule policy {policy_id}: {e}")


@ttl_cache(ttl=600)
async def get_recommended_policy() -> dict:
    """Get Reclaim's recommended default schedule policy for new accounts."""
    try:
        client = _get_client()
        return await client.get("/api/schedule-policy/recommended")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting recommended policy: {e}")
