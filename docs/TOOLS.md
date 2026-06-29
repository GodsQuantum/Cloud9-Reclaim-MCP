# Tool Reference

40 tools across system, tasks, events, habits, focus, scheduling, and
analytics. Every date/time parameter accepts natural language
(`tomorrow at 3pm`, `in 2 hours`, `next Tuesday`, `this week`), a date
(`2026-04-20`), or ISO 8601. The server instructs Claude to call
`get_context` first before any time-dependent tool, which anchors the
current datetime, timezone, working hours, and task state.

Mutation tools return an envelope:

```json
{
  "data": { ... },
  "summary": "Snoozed 'Draft plan' until Saturday, April 18 at 9:00 AM PDT",
  "resolved": { "until": "2026-04-18T09:00:00-07:00" }
}
```

Read tools return the underlying list or object directly.

---

## System (3)

| Tool | Description |
|------|-------------|
| `get_context` | Current datetime, timezone, working hours today, active timer, task counts. Call this first for any scheduling flow. |
| `health_check` | Server liveness check. |
| `verify_connection` | Verifies the API key resolves to a Reclaim user. |

## Tasks (13)

| Tool | Description |
|------|-------------|
| `list_tasks(filter, limit, detail)` | `filter`: `active`, `unscheduled`, `in_progress`, `due_today`, `overdue`, `completed`, `all`. |
| `get_task(task_id, detail)` | Fetch one task. |
| `create_task(title, duration_minutes, due_at?, priority, notes?, min_chunk_minutes?, max_chunk_minutes?, snooze_until?)` | Create for auto-scheduling. |
| `update_task(task_id, ...)` | Update any subset of fields. |
| `complete_task(task_id)` | Mark complete. |
| `delete_task(task_id)` | Delete permanently. |
| `snooze_task(task_id, until?)` | Snooze with NL/date/ISO, or `until=None` to clear. |
| `log_work(task_id, minutes, notes?)` | Log retrospective time spent. |
| `extend_task(task_id, minutes)` | Add scheduled capacity (not worked time). |
| `plan_task_work(task_id, at, duration_minutes)` | Pin a work block to a specific time. |
| `start_task(task_id)` | Start the timer. |
| `stop_task(task_id)` | Pause the timer. |
| `restore_task(task_id)` | Revive completed or archived task. |

## Events (4)

| Tool | Description |
|------|-------------|
| `list_events(when, scope, calendar_ids?, limit, detail)` | `scope`: `all`, `external`, `personal`. |
| `get_event(calendar_id, event_id, detail)` | Fetch one event. |
| `rsvp_event(calendar_id, event_id, response, notify_attendees)` | `response`: `accepted`, `declined`, `tentative`, `needs_action`. |
| `reschedule_event(event_id, start_at, end_at)` | Move an event. |

## Habits (12)

| Tool | Description |
|------|-------------|
| `list_habits(detail)` | All smart habits. |
| `get_habit(habit_id, detail)` | Fetch one habit. |
| `create_habit(title, ideal_time, duration_min_mins, frequency, ideal_days?, event_type, defense_aggression, duration_max_mins?, description?, enabled, time_policy_type?)` | Create a recurring habit. |
| `update_habit(habit_id, ...)` | Update any subset. |
| `delete_habit(habit_id)` | Delete. |
| `set_habit_enabled(habit_id, enabled)` | Pause/resume without deleting. |
| `complete_habit_instance(event_id)` | Mark today's occurrence done. |
| `skip_habit_instance(event_id)` | Skip today's occurrence. |
| `set_habit_instance_locked(event_id, locked)` | Lock/unlock a single instance. |
| `start_habit(habit_id)` | Start timer. |
| `stop_habit(habit_id)` | Stop timer. |
| `convert_event_to_habit(calendar_id, event_id, ...)` | Turn a calendar event into a recurring habit. |

## Focus Time (4)

| Tool | Description |
|------|-------------|
| `get_focus_settings()` | Current focus-time config. |
| `update_focus_settings(settings_id, ...)` | Update durations, defense, enabled. |
| `set_focus_block_locked(calendar_id, event_id, locked)` | Lock/unlock a block. |
| `reschedule_focus_block(calendar_id, event_id, start_at?, end_at?)` | Move, or let Reclaim pick if times omitted. |

## Scheduling (2)

| Tool | Description |
|------|-------------|
| `get_working_hours()` | All time-scheme definitions. For today only, prefer `get_context`. |
| `find_available_times(attendees, duration_minutes, when?, limit?)` | Mutual availability across attendees. |

## Analytics (2)

| Tool | Description |
|------|-------------|
| `get_user_analytics(when, metric_name)` | `metric_name`: `DURATION_BY_CATEGORY` or `DURATION_BY_DATE_BY_CATEGORY`. |
| `get_focus_insights(when)` | Focus-time analytics and recommendations. |

---

## Time parameter cheatsheet

| Parameter name | Shape | Examples |
|----------------|-------|----------|
| `when` | range | `today`, `this week`, `next 7 days`, `2026-04-20..2026-04-25` |
| `due_at`, `start_at`, `end_at`, `at`, `until`, `snooze_until` | datetime | `tomorrow at 3pm`, `in 2 hours`, `next Tuesday`, `2026-04-20T15:00:00-07:00` |
| `ideal_time` (habits only) | clock time | `09:00`, `14:30` |

All NL times resolve to the nearest future occurrence in the user's
timezone. Date-only inputs resolve to 9:00 AM local unless the phrase
contains an explicit time.
