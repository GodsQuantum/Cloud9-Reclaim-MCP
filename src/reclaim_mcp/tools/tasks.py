"""Task tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from reclaim_mcp.cache import invalidate_cache, ttl_cache
from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.exceptions import NotFoundError, RateLimitError, ReclaimError
from reclaim_mcp.models import ListLimit, TaskCreate, TaskId, TaskUpdate, TimeLog
from reclaim_mcp.responses import make_response, thin_task
from reclaim_mcp.time import TimeParseError, parse_when
from reclaim_mcp.user_tz import get_user_tz
from reclaim_mcp.utils import format_validation_errors

_ACTIVE = "NEW,SCHEDULED,IN_PROGRESS"
_COMPLETED = "COMPLETE,ARCHIVED"

# filter -> (api_status, client_predicate_name)
_FILTERS = {
    "active": _ACTIVE,
    "all": "NEW,SCHEDULED,IN_PROGRESS,COMPLETE,ARCHIVED",
    "unscheduled": "NEW",
    "in_progress": "IN_PROGRESS",
    "due_today": _ACTIVE,
    "overdue": _ACTIVE,
    "completed": _COMPLETED,
}


def _get_client() -> ReclaimClient:
    return ReclaimClient(get_settings())


def _duration_to_chunks(minutes: int) -> int:
    chunks = minutes // 15
    return chunks if chunks >= 1 else 1


async def _resolve(value: str, *, tz: Optional[str] = None) -> Any:
    zone = tz or await get_user_tz()
    try:
        return parse_when(value, tz=zone)
    except TimeParseError as e:
        raise ToolError(str(e))


def _apply_client_filter(tasks: list[dict[str, Any]], filter_name: str, tz: str) -> list[dict[str, Any]]:
    if filter_name not in {"due_today", "overdue"}:
        return tasks
    zone = ZoneInfo(tz)
    today = datetime.now(zone).date()
    out = []
    for t in tasks:
        due = t.get("due")
        if not isinstance(due, str):
            continue
        try:
            due_dt = datetime.fromisoformat(due.replace("Z", "+00:00")).astimezone(zone).date()
        except ValueError:
            continue
        if filter_name == "due_today" and due_dt == today:
            out.append(t)
        elif filter_name == "overdue" and due_dt < today and t.get("status") not in ("COMPLETE", "ARCHIVED"):
            out.append(t)
    return out


@ttl_cache(ttl=60)
async def list_tasks(
    filter: str = "active",
    limit: int = 50,
    detail: str = "thin",
) -> list[dict[str, Any]]:
    """List tasks.

    `filter` is one of:
    - 'active' (default): NEW + SCHEDULED + IN_PROGRESS
    - 'unscheduled': NEW only (no time block assigned yet)
    - 'in_progress': currently running (timer active)
    - 'due_today': active tasks whose due date is today in the user's tz
    - 'overdue': active tasks whose due date is in the past
    - 'completed': COMPLETE + ARCHIVED
    - 'all': everything
    """
    try:
        ListLimit(limit=limit)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    if filter not in _FILTERS:
        raise ToolError(f"filter must be one of: {sorted(_FILTERS)}. Got {filter!r}.")

    api_status = _FILTERS[filter]

    try:
        client = _get_client()
        tasks = await client.get("/api/tasks", params={"status": api_status, "limit": limit})
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error listing tasks: {e}")

    if not isinstance(tasks, list):
        return []

    tz = await get_user_tz()
    tasks = _apply_client_filter(tasks, filter, tz)[:limit]

    if detail == "thin":
        return [thin_task(t) for t in tasks]
    return tasks


async def get_task(task_id: int, detail: str = "full") -> dict[str, Any]:
    """Get a single task by ID."""
    try:
        validated = TaskId(task_id=task_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        task = await client.get(f"/api/tasks/{validated.task_id}")
    except NotFoundError:
        raise ToolError(f"Task {task_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting task {task_id}: {e}")

    if detail == "thin":
        return thin_task(task)
    return task


async def create_task(
    title: str,
    duration_minutes: int,
    due_at: Optional[str] = None,
    priority: str = "P2",
    notes: Optional[str] = None,
    min_chunk_minutes: int = 15,
    max_chunk_minutes: Optional[int] = None,
    snooze_until: Optional[str] = None,
) -> dict[str, Any]:
    """Create a task for Reclaim to auto-schedule.

    Args:
        title: Task title.
        duration_minutes: Total minutes needed.
        due_at: Deadline. Accepts NL ('next Friday'), date ('2026-04-24'), or ISO.
        priority: P1 (critical), P2 (high, default), P3 (medium), P4 (low).
        notes: Freeform notes.
        min_chunk_minutes: Smallest block Reclaim will schedule (default 15).
        max_chunk_minutes: Largest block Reclaim will schedule (default = duration).
        snooze_until: Don't schedule before this time. NL accepted.
    """
    tz = await get_user_tz()

    # due_at normalization — API wants YYYY-MM-DD on POST (deadline field).
    due_date = None
    resolved_due = None
    if due_at is not None:
        r = await _resolve(due_at, tz=tz)
        due_date = r.dt.strftime("%Y-%m-%d")
        resolved_due = r.iso

    snooze_iso = None
    resolved_snooze = None
    if snooze_until is not None:
        r = await _resolve(snooze_until, tz=tz)
        snooze_iso = r.iso_utc
        resolved_snooze = r.iso

    try:
        validated = TaskCreate(
            title=title,
            duration_minutes=duration_minutes,
            min_chunk_size_minutes=min_chunk_minutes,
            max_chunk_size_minutes=max_chunk_minutes,
            due_date=due_date,
            snooze_until=snooze_iso,
            priority=priority,  # type: ignore[arg-type]
        )
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    payload: dict[str, Any] = {
        "title": validated.title,
        "timeChunksRequired": _duration_to_chunks(validated.duration_minutes),
        "minChunkSize": validated.min_chunk_size_minutes,
        "maxChunkSize": validated.max_chunk_size_minutes or validated.duration_minutes,
        "eventCategory": "WORK",
        "priority": validated.priority.value,
    }
    if validated.due_date is not None:
        payload["deadline"] = validated.due_date
    if validated.snooze_until is not None:
        payload["snoozeUntil"] = validated.snooze_until
    if notes:
        payload["notes"] = notes

    try:
        client = _get_client()
        result = await client.post("/api/tasks", payload)
        invalidate_cache("list_tasks")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error creating task '{title}': {e}")

    resolved: dict[str, str] = {}
    if resolved_due:
        resolved["due_at"] = resolved_due
    if resolved_snooze:
        resolved["snooze_until"] = resolved_snooze

    return make_response(
        result,
        summary=f"Created task '{validated.title}' ({duration_minutes} min).",
        resolved=resolved or None,
    )


async def update_task(
    task_id: int,
    title: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    due_at: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    snooze_until: Optional[str] = None,
    notes: Optional[str] = None,
    min_chunk_minutes: Optional[int] = None,
    max_chunk_minutes: Optional[int] = None,
) -> dict[str, Any]:
    """Update any subset of task fields. Omit to leave unchanged.

    For "mark done" use `complete_task`. For snoozing use `snooze_task` (it
    handles "until=None" to clear).
    """
    try:
        validated_id = TaskId(task_id=task_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    tz = await get_user_tz()

    # Resolve due_at into YYYY-MM-DD (model expectation) + keep ISO for echo.
    due_date = None
    resolved_due = None
    if due_at is not None:
        r = await _resolve(due_at, tz=tz)
        due_date = r.dt.strftime("%Y-%m-%d")
        resolved_due = r.iso

    snooze_iso = None
    resolved_snooze = None
    if snooze_until is not None:
        r = await _resolve(snooze_until, tz=tz)
        snooze_iso = r.iso_utc
        resolved_snooze = r.iso

    try:
        v = TaskUpdate(
            title=title,
            duration_minutes=duration_minutes,
            due_date=due_date,
            status=status,  # type: ignore[arg-type]
            priority=priority,  # type: ignore[arg-type]
            snooze_until=snooze_iso,
            notes=notes,
            min_chunk_size_minutes=min_chunk_minutes,
            max_chunk_size_minutes=max_chunk_minutes,
        )
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    payload: dict[str, Any] = {}
    if v.title is not None:
        payload["title"] = v.title
    if v.duration_minutes is not None:
        payload["timeChunksRequired"] = _duration_to_chunks(v.duration_minutes)
    if v.due_date is not None:
        payload["due"] = f"{v.due_date}T15:00:00Z"
    if v.status is not None:
        payload["status"] = v.status.value
    if v.priority is not None:
        payload["priority"] = v.priority.value
    if v.snooze_until is not None:
        payload["snoozeUntil"] = v.snooze_until
    if v.notes is not None:
        payload["notes"] = v.notes
    if v.min_chunk_size_minutes is not None:
        payload["minChunkSize"] = v.min_chunk_size_minutes
    if v.max_chunk_size_minutes is not None:
        payload["maxChunkSize"] = v.max_chunk_size_minutes

    try:
        client = _get_client()
        result = await client.patch(f"/api/tasks/{validated_id.task_id}", payload)
        invalidate_cache("list_tasks")
    except NotFoundError:
        raise ToolError(f"Task {task_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error updating task {task_id}: {e}")

    resolved: dict[str, str] = {}
    if resolved_due:
        resolved["due_at"] = resolved_due
    if resolved_snooze:
        resolved["snooze_until"] = resolved_snooze

    return make_response(result, summary=f"Updated task {task_id}.", resolved=resolved or None)


async def complete_task(task_id: int) -> dict[str, Any]:
    """Mark a task complete."""
    return await _planner_action(task_id, "done", "Completed", invalidate_completed=True)


async def delete_task(task_id: int) -> dict[str, Any]:
    """Delete a task. This can't be undone — to pause instead, use `snooze_task`."""
    try:
        validated = TaskId(task_id=task_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        await client.delete(f"/api/tasks/{validated.task_id}")
        invalidate_cache("list_tasks")
    except NotFoundError:
        raise ToolError(f"Task {task_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error deleting task {task_id}: {e}")

    return make_response({"deleted": True, "task_id": task_id}, summary=f"Deleted task {task_id}.")


async def snooze_task(task_id: int, until: Optional[str] = None) -> dict[str, Any]:
    """Snooze a task until a given time, or clear an existing snooze.

    Args:
        task_id: Task ID from `list_tasks`.
        until: When to unsnooze. Accepts NL ('in 2 hours', 'tomorrow',
            'next Monday'), date, or ISO datetime. Pass None to clear an
            existing snooze.
    """
    try:
        validated = TaskId(task_id=task_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    client = _get_client()

    if until is None:
        try:
            result = await client.post(f"/api/planner/task/{validated.task_id}/clear-snooze", {})
            invalidate_cache("list_tasks")
        except NotFoundError:
            raise ToolError(f"Task {task_id} not found")
        except RateLimitError as e:
            raise ToolError(str(e))
        except ReclaimError as e:
            raise ToolError(f"Error clearing snooze on task {task_id}: {e}")
        return make_response(result, summary=f"Cleared snooze on task {task_id}.")

    tz = await get_user_tz()
    r = await _resolve(until, tz=tz)

    try:
        result = await client.patch(f"/api/tasks/{validated.task_id}", {"snoozeUntil": r.iso_utc})
        invalidate_cache("list_tasks")
    except NotFoundError:
        raise ToolError(f"Task {task_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error snoozing task {task_id}: {e}")

    return make_response(
        result,
        summary=f"Snoozed task {task_id} until {r.label}.",
        resolved={"until": r.iso},
    )


async def log_work(
    task_id: int,
    minutes: int,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Log time already spent on a task.

    This records work done; it does not schedule new time. To add more
    scheduled capacity, use `extend_task`.
    """
    try:
        validated_id = TaskId(task_id=task_id)
        validated_time = TimeLog(minutes=minutes)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        result = await client.post(
            f"/api/planner/log-work/task/{validated_id.task_id}",
            {},
            params={"minutes": validated_time.minutes},
        )
        if notes:
            await client.patch(f"/api/tasks/{validated_id.task_id}", {"notes": notes})
        invalidate_cache("list_tasks")
    except NotFoundError:
        raise ToolError(f"Task {task_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error logging work on task {task_id}: {e}")

    return make_response(result, summary=f"Logged {minutes} min on task {task_id}.")


async def extend_task(task_id: int, minutes: int) -> dict[str, Any]:
    """Add more scheduled capacity to a task. Does not log time worked."""
    try:
        validated_id = TaskId(task_id=task_id)
        validated_time = TimeLog(minutes=minutes)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        result = await client.post(
            f"/api/planner/add-time/task/{validated_id.task_id}",
            {},
            params={"minutes": validated_time.minutes},
        )
        invalidate_cache("list_tasks")
    except NotFoundError:
        raise ToolError(f"Task {task_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error extending task {task_id}: {e}")

    return make_response(result, summary=f"Extended task {task_id} by {minutes} min.")


async def plan_task_work(
    task_id: int,
    at: str,
    duration_minutes: int,
) -> dict[str, Any]:
    """Pin a block of task work to a specific time.

    Args:
        task_id: Task ID from `list_tasks`.
        at: When to schedule. NL, date+time, or ISO.
        duration_minutes: How long the block should be.
    """
    try:
        validated_id = TaskId(task_id=task_id)
        validated_time = TimeLog(minutes=duration_minutes)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    tz = await get_user_tz()
    r = await _resolve(at, tz=tz)

    try:
        client = _get_client()
        result = await client.post(
            f"/api/planner/plan-work/task/{validated_id.task_id}",
            {},
            params={"dateTime": r.iso_utc, "durationMinutes": validated_time.minutes},
        )
        invalidate_cache("list_tasks")
    except NotFoundError:
        raise ToolError(f"Task {task_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error planning work for task {task_id}: {e}")

    return make_response(
        result,
        summary=f"Scheduled {duration_minutes} min on task {task_id} at {r.label}.",
        resolved={"at": r.iso},
    )


async def start_task(task_id: int) -> dict[str, Any]:
    """Start the timer on this task (marks IN_PROGRESS and starts the clock)."""
    return await _planner_action(task_id, "start", "Started")


async def stop_task(task_id: int) -> dict[str, Any]:
    """Stop the timer without marking the task complete."""
    return await _planner_action(task_id, "stop", "Stopped")


async def restore_task(task_id: int) -> dict[str, Any]:
    """Revive a completed or archived task back into active scheduling.

    Figures out whether to restart or unarchive based on current status.
    """
    try:
        validated = TaskId(task_id=task_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        task = await client.get(f"/api/tasks/{validated.task_id}")
    except NotFoundError:
        raise ToolError(f"Task {task_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error restoring task {task_id}: {e}")

    current = task.get("status") if isinstance(task, dict) else None
    action = "unarchive" if current == "ARCHIVED" else "restart"

    try:
        result = await client.post(f"/api/planner/{action}/task/{validated.task_id}", {})
        invalidate_cache("list_tasks")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error restoring task {task_id}: {e}")

    verb = "Unarchived" if action == "unarchive" else "Restarted"
    return make_response(result, summary=f"{verb} task {task_id}.")


async def _planner_action(
    task_id: int,
    action: str,
    verb: str,
    *,
    invalidate_completed: bool = False,
) -> dict[str, Any]:
    try:
        validated = TaskId(task_id=task_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        result = await client.post(f"/api/planner/{action}/task/{validated.task_id}", {})
        invalidate_cache("list_tasks")
    except NotFoundError:
        raise ToolError(f"Task {task_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error on task {task_id}: {e}")

    return make_response(result, summary=f"{verb} task {task_id}.")
