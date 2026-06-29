"""FastMCP server for Reclaim.ai integration."""

from typing import Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from reclaim_mcp import __version__
from reclaim_mcp.tools import analytics, context, events, focus, habits, scheduling, tasks

INSTRUCTIONS = """\
This server exposes the user's Reclaim.ai tasks, calendar, smart habits, and
focus time via MCP tools.

Before using any tool that accepts a date, time, or relative phrase like
"today" or "this week", call `get_context` first. It returns the user's
current datetime, timezone, working hours, active timer, and a quick
summary of their task state. This prevents scheduling against the wrong
date or timezone.

Tools that accept a time parameter understand natural language
("tomorrow at 3pm", "in 2 hours", "next Tuesday"), date-only
("2026-04-20"), and full ISO 8601 ("2026-04-20T15:00:00-07:00"). Mutation
tools echo back the resolved value in their `resolved` field — confirm it
with the user if ambiguous.

Mutation tool responses use an envelope: `{data, summary, resolved?,
warnings?}`. Read tool responses return the underlying list/object directly.
"""

mcp = FastMCP("Reclaim.ai", instructions=INSTRUCTIONS)


@mcp.tool
def health_check() -> str:
    """Check if the server is running."""
    return f"OK (v{__version__})"


@mcp.tool
async def get_context() -> dict:
    """Anchor the current user/time state for any scheduling flow.

    Call this first before any tool that accepts a date, time, or relative
    phrase. It tells you the user's current datetime, timezone, working
    hours today, any running task timer, and a quick summary of their task
    state (due today, overdue, unscheduled, in progress).

    Returns:
        Context dict with `now`, `timezone`, `weekday`, `working_hours_today`,
        `current_moment`, `next_moment`, `active_timer`, and `task_counts`.
    """
    return await context.get_context()


@mcp.tool
async def verify_connection() -> dict:
    """Verify API connection by fetching current user info.

    Returns:
        Connection status with user details (id, email, name).
    """
    try:
        from reclaim_mcp.client import ReclaimClient
        from reclaim_mcp.config import get_settings

        settings = get_settings()
        client = ReclaimClient(settings)
        user = await client.get("/api/users/current")
        return {
            "status": "connected",
            "user_id": user.get("id"),
            "email": user.get("email"),
            "name": user.get("name"),
        }
    except Exception as e:
        raise ToolError(f"Connection failed: {e}")


# Task Tools


@mcp.tool
async def list_tasks(
    filter: str = "active",
    limit: int = 50,
    detail: str = "thin",
) -> list[dict]:
    """List your tasks.

    Args:
        filter: Which tasks to return. One of:
            active (default) — NEW + SCHEDULED + IN_PROGRESS
            unscheduled — NEW only (no time block yet)
            in_progress — timer currently running
            due_today — active and due today in your timezone
            overdue — active with due date in the past
            completed — COMPLETE + ARCHIVED
            all — everything
        limit: Max tasks to return.
        detail: 'thin' (default, ~9 fields) or 'full' (raw API object).
    """
    return await tasks.list_tasks(filter=filter, limit=limit, detail=detail)


@mcp.tool
async def get_task(task_id: int, detail: str = "full") -> dict:
    """Get a single task by ID.

    Args:
        task_id: Task ID from `list_tasks`.
        detail: 'thin' or 'full' (default).
    """
    return await tasks.get_task(task_id=task_id, detail=detail)


@mcp.tool
async def create_task(
    title: str,
    duration_minutes: int,
    due_at: Optional[str] = None,
    priority: str = "P2",
    notes: Optional[str] = None,
    min_chunk_minutes: int = 15,
    max_chunk_minutes: Optional[int] = None,
    snooze_until: Optional[str] = None,
) -> dict:
    """Create a new task for Reclaim to auto-schedule.

    Args:
        title: Task title.
        duration_minutes: Total minutes needed.
        due_at: Optional deadline. Accepts NL ('next Friday'), date
            ('2026-04-24'), or ISO.
        priority: P1 (critical), P2 (high, default), P3 (medium), P4 (low).
        notes: Freeform notes stored on the task.
        min_chunk_minutes: Smallest block Reclaim will schedule (default 15).
        max_chunk_minutes: Largest block; defaults to full duration.
        snooze_until: Optional — don't schedule before this time. NL accepted.
    """
    return await tasks.create_task(
        title=title,
        duration_minutes=duration_minutes,
        due_at=due_at,
        priority=priority,
        notes=notes,
        min_chunk_minutes=min_chunk_minutes,
        max_chunk_minutes=max_chunk_minutes,
        snooze_until=snooze_until,
    )


@mcp.tool
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
) -> dict:
    """Update any subset of fields on a task. Omit to leave unchanged.

    Prefer `complete_task` to mark done and `snooze_task` to snooze — both
    are simpler and safer than setting status/snoozeUntil via this tool.
    """
    return await tasks.update_task(
        task_id=task_id,
        title=title,
        duration_minutes=duration_minutes,
        due_at=due_at,
        status=status,
        priority=priority,
        snooze_until=snooze_until,
        notes=notes,
        min_chunk_minutes=min_chunk_minutes,
        max_chunk_minutes=max_chunk_minutes,
    )


@mcp.tool
async def complete_task(task_id: int) -> dict:
    """Mark a task complete."""
    return await tasks.complete_task(task_id=task_id)


@mcp.tool
async def delete_task(task_id: int) -> dict:
    """Delete a task. Can't be undone — use `snooze_task` to pause instead."""
    return await tasks.delete_task(task_id=task_id)


@mcp.tool
async def snooze_task(task_id: int, until: Optional[str] = None) -> dict:
    """Snooze a task until a given time, or clear an existing snooze.

    Args:
        task_id: Task ID from `list_tasks`.
        until: When to unsnooze. Accepts NL ('in 2 hours', 'tomorrow',
            'next Monday'), date, or ISO. Pass None to clear an existing
            snooze.
    """
    return await tasks.snooze_task(task_id=task_id, until=until)


@mcp.tool
async def log_work(
    task_id: int,
    minutes: int,
    notes: Optional[str] = None,
) -> dict:
    """Log time already spent on a task.

    This records retroactive work. To add more scheduled capacity, use
    `extend_task`. To start a live timer, use `start_task`.
    """
    return await tasks.log_work(task_id=task_id, minutes=minutes, notes=notes)


@mcp.tool
async def extend_task(task_id: int, minutes: int) -> dict:
    """Add more scheduled capacity to a task.

    Does not log time worked — see `log_work` for that.
    """
    return await tasks.extend_task(task_id=task_id, minutes=minutes)


@mcp.tool
async def plan_task_work(
    task_id: int,
    at: str,
    duration_minutes: int,
) -> dict:
    """Pin a block of task work to a specific time.

    Args:
        task_id: Task ID from `list_tasks`.
        at: When to schedule. NL ('tomorrow at 10am'), datetime, or ISO.
        duration_minutes: How long the block should be.
    """
    return await tasks.plan_task_work(task_id=task_id, at=at, duration_minutes=duration_minutes)


@mcp.tool
async def start_task(task_id: int) -> dict:
    """Start a live timer on this task (marks IN_PROGRESS)."""
    return await tasks.start_task(task_id=task_id)


@mcp.tool
async def stop_task(task_id: int) -> dict:
    """Stop the timer without marking the task complete."""
    return await tasks.stop_task(task_id=task_id)


@mcp.tool
async def restore_task(task_id: int) -> dict:
    """Revive a completed or archived task back into active scheduling.

    Picks the right underlying action (restart vs unarchive) based on the
    task's current status.
    """
    return await tasks.restore_task(task_id=task_id)


# Scheduling Tools


@mcp.tool
async def get_working_hours() -> list[dict]:
    """Return the user's full time-scheme definitions.

    For today's working hours only, prefer `get_context` which is cheaper and
    answers in one shot.
    """
    return await scheduling.get_working_hours()


@mcp.tool
async def find_available_times(
    attendees: list[str],
    duration_minutes: int,
    when: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """Find mutual availability across attendees.

    Args:
        attendees: List of email addresses.
        duration_minutes: Meeting length.
        when: Optional search window. Accepts NL ('next week', 'next 7 days')
            or explicit 'YYYY-MM-DD..YYYY-MM-DD'. Omit to let Reclaim pick.
        limit: Max suggested times to return.
    """
    return await scheduling.find_available_times(
        attendees=attendees,
        duration_minutes=duration_minutes,
        when=when,
        limit=limit,
    )


# Calendar & Event Tools


@mcp.tool
async def list_events(
    when: str = "this week",
    scope: str = "all",
    calendar_ids: Optional[list[int]] = None,
    limit: int = 50,
    detail: str = "thin",
) -> list[dict]:
    """List calendar events in a time range.

    Args:
        when: Natural language ('today', 'this week', 'next 7 days'), explicit
            range ('2026-04-20..2026-04-25'), or a single date. Defaults to
            'this week'. Always resolved in the user's timezone — call
            `get_context` first if you're unsure what 'today' is.
        scope: 'external' (your synced calendars), 'personal' (Reclaim-managed
            tasks, habits, focus blocks), or 'all' (default).
        calendar_ids: Optional list of calendar IDs to restrict external scope.
        limit: Max events to return (default 50).
        detail: 'thin' (default, ~7 fields per event) or 'full' (raw API object).
    """
    return await events.list_events(
        when=when,
        scope=scope,
        calendar_ids=calendar_ids,
        limit=limit,
        detail=detail,
    )


@mcp.tool
async def get_event(
    calendar_id: int,
    event_id: str,
    detail: str = "full",
) -> dict:
    """Get a single event by calendar+event ID.

    Args:
        calendar_id: Calendar ID from `list_events`.
        event_id: Event ID from `list_events`.
        detail: 'thin' for a compact object or 'full' (default) for all fields.

    Note: Works for events with `scope='external'`. Reclaim-managed personal
    events may 404 — use their planner-specific tools instead.
    """
    return await events.get_event(calendar_id=calendar_id, event_id=event_id, detail=detail)


@mcp.tool
async def rsvp_event(
    calendar_id: int,
    event_id: str,
    response: str,
    notify_attendees: bool = True,
) -> dict:
    """Set your RSVP on a calendar event.

    Args:
        calendar_id: Calendar ID from `list_events`.
        event_id: Event ID from `list_events`.
        response: One of 'accepted', 'declined', 'tentative', 'needs_action'.
        notify_attendees: Whether other attendees receive an update email (default True).
    """
    return await events.rsvp_event(
        calendar_id=calendar_id,
        event_id=event_id,
        response=response,
        notify_attendees=notify_attendees,
    )


@mcp.tool
async def reschedule_event(
    event_id: str,
    start_at: str,
    end_at: str,
) -> dict:
    """Move an event to a new time.

    Args:
        event_id: Event ID from `list_events`.
        start_at: New start. Accepts NL ('tomorrow at 3pm'), datetime, or ISO.
        end_at: New end. Same formats. Must be after start_at.

    Returns:
        Envelope with the planner action, a summary, and `resolved` echoing
        the parsed start/end so you can confirm with the user.
    """
    return await events.reschedule_event(event_id=event_id, start_at=start_at, end_at=end_at)


# Smart Habit Tools


_HABIT_FREQ = "DAILY | WEEKLY | MONTHLY | YEARLY"
_HABIT_DAYS = "MONDAY | TUESDAY | WEDNESDAY | THURSDAY | FRIDAY | SATURDAY | SUNDAY"
_HABIT_EVENT_TYPE = "FOCUS | SOLO_WORK | PERSONAL | MEETING | TEAM_MEETING | EXTERNAL_MEETING | ONE_ON_ONE"
_HABIT_DEFENSE = "DEFAULT | NONE | LOW | MEDIUM | HIGH | MAX"
_HABIT_POLICY = "WORK | PERSONAL | MEETING"


@mcp.tool
async def list_habits(detail: str = "thin") -> list[dict]:
    """List all smart habits.

    Args:
        detail: 'thin' (default, ~9 fields per habit) or 'full' (raw API object).
    """
    return await habits.list_habits(detail=detail)


@mcp.tool
async def get_habit(habit_id: int, detail: str = "full") -> dict:
    """Get one habit by ID.

    Args:
        habit_id: Habit ID from `list_habits`. (Reclaim calls this lineageId.)
        detail: 'thin' or 'full' (default).
    """
    return await habits.get_habit(habit_id=habit_id, detail=detail)


@mcp.tool
async def create_habit(
    title: str,
    ideal_time: str,
    duration_min_mins: int,
    frequency: str = "WEEKLY",
    ideal_days: Optional[list[str]] = None,
    event_type: str = "SOLO_WORK",
    defense_aggression: str = "DEFAULT",
    duration_max_mins: Optional[int] = None,
    description: Optional[str] = None,
    enabled: bool = True,
    time_policy_type: Optional[str] = None,
) -> dict:
    f"""Create a recurring smart habit for auto-scheduling.

    Args:
        title: Habit name.
        ideal_time: Preferred clock time, 'HH:MM' (e.g., '09:00').
        duration_min_mins: Minimum duration in minutes per occurrence.
        frequency: {_HABIT_FREQ}. Default WEEKLY.
        ideal_days: Days of week for WEEKLY frequency: {_HABIT_DAYS}.
        event_type: {_HABIT_EVENT_TYPE}. Default SOLO_WORK.
        defense_aggression: {_HABIT_DEFENSE}. Default DEFAULT (Reclaim's
            inherited policy).
        duration_max_mins: Max duration; defaults to min.
        description: Optional notes.
        enabled: Whether the habit starts active.
        time_policy_type: {_HABIT_POLICY}. Auto-inferred from event_type if omitted.
    """
    return await habits.create_habit(
        title=title,
        ideal_time=ideal_time,
        duration_min_mins=duration_min_mins,
        frequency=frequency,
        ideal_days=ideal_days,
        event_type=event_type,
        defense_aggression=defense_aggression,
        duration_max_mins=duration_max_mins,
        description=description,
        enabled=enabled,
        time_policy_type=time_policy_type,
    )


@mcp.tool
async def update_habit(
    habit_id: int,
    title: Optional[str] = None,
    ideal_time: Optional[str] = None,
    duration_min_mins: Optional[int] = None,
    duration_max_mins: Optional[int] = None,
    enabled: Optional[bool] = None,
    frequency: Optional[str] = None,
    ideal_days: Optional[list[str]] = None,
    event_type: Optional[str] = None,
    defense_aggression: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """Update an existing habit. Omit fields to leave them unchanged.

    To pause/resume a habit without deleting, prefer `set_habit_enabled`.
    """
    return await habits.update_habit(
        habit_id=habit_id,
        title=title,
        ideal_time=ideal_time,
        duration_min_mins=duration_min_mins,
        duration_max_mins=duration_max_mins,
        enabled=enabled,
        frequency=frequency,
        ideal_days=ideal_days,
        event_type=event_type,
        defense_aggression=defense_aggression,
        description=description,
    )


@mcp.tool
async def delete_habit(habit_id: int) -> dict:
    """Delete a habit entirely. Use `set_habit_enabled(habit_id, False)` to just pause."""
    return await habits.delete_habit(habit_id=habit_id)


@mcp.tool
async def set_habit_enabled(habit_id: int, enabled: bool) -> dict:
    """Enable or disable a habit without deleting it.

    Args:
        habit_id: Habit ID from `list_habits`.
        enabled: True to resume scheduling, False to pause.
    """
    return await habits.set_habit_enabled(habit_id=habit_id, enabled=enabled)


@mcp.tool
async def complete_habit_instance(event_id: str) -> dict:
    """Mark today's habit instance as done.

    Args:
        event_id: Event ID for the specific habit instance, from
            `list_events(scope='personal')`.
    """
    return await habits.complete_habit_instance(event_id=event_id)


@mcp.tool
async def skip_habit_instance(event_id: str) -> dict:
    """Skip today's habit instance without marking it done.

    Args:
        event_id: Event ID for the specific habit instance.
    """
    return await habits.skip_habit_instance(event_id=event_id)


@mcp.tool
async def set_habit_instance_locked(event_id: str, locked: bool) -> dict:
    """Lock or unlock a single habit instance.

    Args:
        event_id: Event ID for the habit instance.
        locked: True to prevent rescheduling, False to allow.
    """
    return await habits.set_habit_instance_locked(event_id=event_id, locked=locked)


@mcp.tool
async def start_habit(habit_id: int) -> dict:
    """Start this habit's timer right now.

    Args:
        habit_id: Habit ID from `list_habits`.
    """
    return await habits.start_habit(habit_id=habit_id)


@mcp.tool
async def stop_habit(habit_id: int) -> dict:
    """Stop a running habit timer."""
    return await habits.stop_habit(habit_id=habit_id)


@mcp.tool
async def convert_event_to_habit(
    calendar_id: int,
    event_id: str,
    title: str,
    ideal_time: str,
    duration_min_mins: int,
    frequency: str = "WEEKLY",
    ideal_days: Optional[list[str]] = None,
    event_type: str = "SOLO_WORK",
    defense_aggression: str = "DEFAULT",
    duration_max_mins: Optional[int] = None,
    description: Optional[str] = None,
    enabled: bool = True,
    time_policy_type: Optional[str] = None,
) -> dict:
    """Turn a calendar event into a recurring smart habit.

    Rejects recurring instances, all-day events, and multi-day events — use
    only with standalone timed events. See `create_habit` for parameter
    details.
    """
    return await habits.convert_event_to_habit(
        calendar_id=calendar_id,
        event_id=event_id,
        title=title,
        ideal_time=ideal_time,
        duration_min_mins=duration_min_mins,
        frequency=frequency,
        ideal_days=ideal_days,
        event_type=event_type,
        defense_aggression=defense_aggression,
        duration_max_mins=duration_max_mins,
        description=description,
        enabled=enabled,
        time_policy_type=time_policy_type,
    )


# Analytics Tools


@mcp.tool
async def get_user_analytics(when: str, metric_name: str) -> dict:
    """Productivity breakdown for a time range.

    Args:
        when: NL range ('this week', 'last month', 'next 7 days') or explicit
            'YYYY-MM-DD..YYYY-MM-DD'.
        metric_name: One of DURATION_BY_CATEGORY, DURATION_BY_DATE_BY_CATEGORY.
    """
    return await analytics.get_user_analytics(when=when, metric_name=metric_name)


@mcp.tool
async def get_focus_insights(when: str) -> dict:
    """Focus-time analytics (protected hours, interruptions, recommendations).

    Args:
        when: NL range or 'YYYY-MM-DD..YYYY-MM-DD'.
    """
    return await analytics.get_focus_insights(when=when)


# Focus Time Tools


@mcp.tool
async def get_focus_settings() -> list[dict]:
    """Get the user's focus-time configuration (one entry per focus type)."""
    return await focus.get_focus_settings()


@mcp.tool
async def update_focus_settings(
    settings_id: int,
    min_duration_mins: Optional[int] = None,
    ideal_duration_mins: Optional[int] = None,
    max_duration_mins: Optional[int] = None,
    defense_aggression: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> dict:
    """Update focus-time settings.

    Args:
        settings_id: Focus settings ID from `get_focus_settings`.
        min_duration_mins: Minimum focus block length.
        ideal_duration_mins: Preferred focus block length.
        max_duration_mins: Maximum focus block length.
        defense_aggression: One of NONE, LOW, MEDIUM, HIGH, MAX — how hard
            Reclaim defends these blocks from meetings.
        enabled: Whether focus time is active.
    """
    return await focus.update_focus_settings(
        settings_id=settings_id,
        min_duration_mins=min_duration_mins,
        ideal_duration_mins=ideal_duration_mins,
        max_duration_mins=max_duration_mins,
        defense_aggression=defense_aggression,
        enabled=enabled,
    )


@mcp.tool
async def set_focus_block_locked(
    calendar_id: int,
    event_id: str,
    locked: bool,
) -> dict:
    """Lock or unlock a focus block.

    Args:
        calendar_id: Calendar ID of the focus block.
        event_id: Event ID of the focus block.
        locked: True to prevent Reclaim from rescheduling it, False to allow.
    """
    return await focus.set_focus_block_locked(calendar_id=calendar_id, event_id=event_id, locked=locked)


@mcp.tool
async def reschedule_focus_block(
    calendar_id: int,
    event_id: str,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
) -> dict:
    """Reschedule a focus block, or ask Reclaim to pick a new slot.

    Args:
        calendar_id: Calendar ID of the focus block.
        event_id: Event ID of the focus block.
        start_at: New start (NL, datetime, or ISO). Omit both times to let
            Reclaim pick.
        end_at: New end, same formats.
    """
    return await focus.reschedule_focus_block(
        calendar_id=calendar_id,
        event_id=event_id,
        start_at=start_at,
        end_at=end_at,
    )


def main() -> None:
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
