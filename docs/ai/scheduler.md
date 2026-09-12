# Scheduler

The Scheduler is AoT's collaborative farm event ledger — a single timeline where AI-drafted proposals and human-entered work tasks (weeding, inspection, cleaning, device operations, etc.) are reviewed, approved, and tracked side by side. It is available under `Scheduler` in the main menu and requires the `edit_controllers` permission.

---

## Job States

Every scheduler entry (job) moves through one of these states:

| State | Meaning |
|-------|---------|
| Draft | AI-proposed job awaiting human approval or rejection |
| Pending | Approved / manually created job waiting for its scheduled time |
| Running | Currently executing (device-control jobs only) |
| Completed | Finished successfully |
| Failed | Execution failed |
| Archived | Cancelled/deleted job, kept for history |

---

## AI Proposals

When an AI agent proposes a scheduling action (e.g. via `add_schedule` or `schedule_device_control`), it is saved as a `Draft` job and appears as a card under "Schedule proposals" on the **AI → Requests** screen. Each card shows the content, location, proposed time, and the agent's reasoning. The top of the Scheduler shows one line with the number of waiting proposals and a button to the Requests screen; clicking a proposal on the calendar takes you there too.

- **Approve** — moves the job to `Pending`; a device-control job registers its trigger at this point.
- **Reject** — moves the job to `Archived`.
- **Details** lets you adjust time, worker, content, or location before approving it.

Deciding on proposals requires permission to edit controllers.

---

## Manual Tasks

Click **New Task** to create a job directly, without going through the AI:

1. Choose a target — an output/channel, PID, Function, or a zone.
2. Pick a date/time. The time you enter is interpreted as the **target's own local time** (device-local), not your browser's or the system's — the form shows the target's timezone next to the field so this is explicit.
3. Optionally set a duration and a note.

Manual tasks skip the approval step and go straight to `Pending`.

---

## Ask AI

The New Task modal opens on the **Manual** tab. Its second, **AI** tab lets you describe a task in natural language (e.g. "3구역 관수 밸브 내일 아침 6시에 5분만 열어줘") and pick which AI agent should interpret it (the built-in AI must be running). The agent's response becomes a `Draft` proposal that you decide on the **AI → Requests** screen — nothing executes without an explicit **Approve**.

---

## Timeline & Device Timeline

- **Timeline** — a calendar (week/month) view of all scheduled jobs, color-coded by state.
- **Device Timeline** — the same calendar filtered to a single device, useful for checking a device's full task history and upcoming jobs at a glance.

---

## History

Completed, failed, and archived jobs are kept in **History** with their final execution result and timestamps, for auditing what actually ran.

---

## Time Display

Because farm devices can each have their own timezone, every timestamp shown in the Scheduler is labeled with the timezone it belongs to (device-local anchor). See [Time & Timezones](../time-handling.md) for the full model.

---

## Related Pages

- [AI Overview](overview.md)
- [Environmental Control](env-control.md)
- [Time & Timezones](../time-handling.md)
