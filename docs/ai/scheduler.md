# Scheduler

The Scheduler is AoT's collaborative farm event ledger — a single timeline where AI-drafted proposals and human-entered work tasks (weeding, inspection, cleaning, device operations, etc.) are reviewed, approved, and tracked side by side. It is available under `Additional Features -> Schedule` in the main menu and requires the `edit_controllers` permission.

---

## Job States { #job-states }

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

## AI Proposals { #ai-proposals }

When an AI agent proposes a scheduling action (e.g. via `add_schedule` or `schedule_device_control`), it is saved as a `Draft` job and appears as a card under "Schedule proposals" on the **AI → Requests** screen. Each card shows the content, location, proposed time, and the agent's reasoning. The top of the Scheduler shows one line with the number of waiting proposals and a button to the Requests screen; clicking a proposal on the calendar takes you there too.

- **Approve** — moves the job to `Pending`; a device-control job registers its trigger at this point.
- **Reject** — moves the job to `Archived`.
- **Details** lets you adjust time, worker, content, or location before approving it.

Deciding on proposals requires permission to edit controllers. When groups are in use, you can only create, approve, edit or cancel a job whose target is inside your groups. Approving an AI proposal makes you the person responsible for it: every time the job runs it is checked again against that person's permission and groups, and it is recorded as failed instead of running if they no longer apply.

**Work tasks for people** (weeding, inspection and the like) follow the same rule wherever they are created — here, from a note passage, through the AI assistant or MCP, or imported from Google Calendar: creating, editing or cancelling one needs the Editor role (permission to edit controllers). Roles below Editor can see work tasks but cannot change them, even if they can edit settings.

**Jobs with no owner.** Some jobs have no responsible person — jobs created by functions or the system, jobs created before this check existed, and jobs whose owner's account was deleted or disabled. These jobs keep running as before; deleting or disabling a user does not stop the jobs they were responsible for. Re-enabling the account does not restore the owner — assign it again. In the Active Jobs list the owner column shows **No owner** for them. A user who can manage users can open the job's details, choose a person under **Owner** and press **Assign owner**. Disabled accounts cannot be chosen. Only people whose role could create that kind of job are offered, and the assignment is refused if the job's target is outside that person's permissions or groups, and it is recorded in the audit log. From then on every run is checked against that person.

---

## Manual Tasks { #manual-tasks }

Click **New Task** to create a job directly, without going through the AI:

1. Choose an action type — **Output Control**, **PID Adjustment**, **Trigger Function**, or **Abstract Plan (State)** — then the target it applies to: a device (with its channel and On/Off state), a PID controller (with the setting to change: setpoint, Kp, Ki, Kd), a Function, or a zone/site. Output control and PID adjustment also take an amount — seconds or PWM for a device, the new value for a PID.
2. Pick a date/time. The time you enter is interpreted as the **target's own local time** (device-local), not your browser's or the system's — below the field the same moment is shown in the target's timezone, in yours, and in UTC, so this is explicit. If the target has no location set, the line says so and the time is read with the system timezone instead.
3. Choose a recurrence — **One-time**, **Daily** (the same time every day), or **Interval**, where you give the number of minutes between runs.
4. Optionally set a duration in minutes and a task note.

Manual tasks skip the approval step and go straight to `Pending`.

---

## Ask AI { #ask-ai }

The New Task modal opens on the **Manual** tab. Its second, **Smart AI** tab lets you describe a task in natural language (e.g. "3구역 관수 밸브 내일 아침 6시에 5분만 열어줘") and pick which AI agent should interpret it — **Auto-Dispatch (AI Multi-Agent)**, which leaves the choice to the system, or one of the activated agents by name and role (the built-in AI must be running). Press **Ask AI** and the answer appears in the same tab: the agent's **Insight** and the list of proposed **Actions**. Anything that operates a device, books a schedule, or changes a setting becomes a `Draft` proposal that you decide on the **AI → Requests** screen — nothing of that kind executes without an explicit **Approve**. Read-only lookups the agent needed in order to answer have already run by the time you see the answer.

---

## Timeline & Device Timeline { #timeline-device-timeline }

- **Timeline** — a calendar view (week, month, or a week as a list) of the most recent 200 scheduled jobs, color-coded by state. It carries the same set as the lists above it: drafts, pending, running and completed jobs, with automated records left out unless you turn them on. Failed and archived jobs appear only in History. The calendar axis is your own clock; hovering an event shows its time in the target's own timezone, and clicking it opens the job's details (a proposal takes you to **AI → Requests**).
- **Device Timeline** (Beta) — one row per output device, showing each **Scheduled** reservation still waiting plus every actual run from the last 24 hours as a bar labeled with how long it ran. Clicking a bar shows its label and span. On a phone it collapses to one line per device with the number of reservations and of runs.

---

## History { #history }

Completed, failed, and archived jobs are kept in **History**. The 20 most recent are listed with their content, location, final state and the time they were created; **Details** opens the full record — action type, state, location, content, scheduled time, duration, who proposed it, and the reasoning behind it — for auditing what actually ran.

Records the system logged on its own (automated triggers) are hidden by default, so they do not bury the jobs people and agents created. The heading carries a **Show automated records (n)** link that says how many are hidden and brings them back; the same link hides them again. The Timeline follows this setting too.

---

## Time Display { #time-display }

Because farm devices can each have their own timezone, every timestamp shown in the Scheduler is labeled with the timezone it belongs to (device-local anchor). Where the target has no location set, the label does not claim device-local time — it says the time was estimated with the system timezone. See [Time & Timezones](../time-handling.md) for the full model.

---

## Related Pages

- [AI Overview](overview.md)
- [Environmental Control](env-control.md)
- [Time & Timezones](../time-handling.md)
