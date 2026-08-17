# Log Viewer

`[Gear Icon] -> AoT Logs` (`/logview`) shows the system's logs in the browser,
with filtering, live tail, and — when the AI service is enabled — a way to ask
the AI about the lines you are looking at.

Viewing logs requires the **view_logs** permission.

## Choosing a log

The **Log** dropdown groups the available sources:

| Group | Source | What it contains |
|-------|--------|------------------|
| AI | AI | Everything the AI services log (agent, planner, scheduler, MCP bridge, safety gate). |
| AI | MCP Server | The external MCP server process — the one AI assistants connect to. |
| System | Daemon | The full daemon log: inputs, outputs, functions, controllers. |
| System | Daemon (PID settings) | Only the PID controller setting lines, for tuning. |
| System | Daemon keepup | The keepup service. |
| Web | Web app | The web application's own log lines. |
| Web | Web login | Login attempts, successful and not. |
| Web | Web access / Web error | The web server's access and error logs. |
| Web | Web / Nginx | The service journals, where the host provides them. |
| Maintenance | Dependency, Import settings, AoT backup / restore / upgrade | One-off maintenance runs. |

A source that is not available on this installation is shown greyed out with
the reason — either the file does not exist yet, or the command needed to read
it (`journalctl`, `docker`) is not installed in this environment. That is not
an error; it tells you the log is genuinely unreachable here rather than empty.

!!! note "The AI and Web app sources are views of the daemon log"
    AI services and the web application do not write separate files — their
    lines go into the daemon log along with everything else. Those two entries
    filter the same file by logger name, which is why they can show lines that
    are far older than the last few hundred lines of the daemon log.

## Filtering

- **Minimum level** — show only entries at that level or above. Lines with no
  recognizable level (login records, access logs) are not shown when a minimum
  level is set, because they carry no level to compare.
- **Search** — case-insensitive substring match against the whole line.
- **Lines** — how many matching entries to keep on screen.

The filters are kept in the page URL, so a filtered view can be bookmarked or
pasted to someone else.

If the viewer reaches its scan limit before it finds the requested number of
lines, it says so. Older matching lines then exist but were not read — narrow
the search, or pick a source that is already scoped to what you want.

## Live tail

Tick **Live** to keep the view updated. It polls every few seconds, fetches only
what was appended since the last poll, and stays pinned to the newest line
unless you have scrolled up. Polling stops while the browser tab is in the
background and resumes when you return.

## Download

**Download** saves the currently filtered view as a plain text file — the same
lines you see, not the whole log.

## Asking the AI about a log

When the AI service is enabled, an action bar appears below the log.

1. Click a line to select it. Shift-click selects a range. With nothing
   selected, the errors and warnings currently on screen are used.
2. Choose **Explain**, **Diagnose the cause**, or **How do I fix it?**

The chat drawer opens with the selected lines attached, and the answer names
what the log actually shows and what to check next in this system. You can keep
asking follow-up questions in the drawer — the log lines stay in that
conversation's context.

!!! warning "The selected lines leave this machine"
    They are sent to whichever AI model you configured, which for most providers
    means an external service. Do not send lines that contain credentials, keys,
    or tokens.

The excerpt is capped in both line count and total size, so a very long line or
a large selection is truncated rather than sent whole.

## Where the files are

Logs live in `/var/log/aot/` on a normal installation. The path of the source
you are viewing is shown just under the toolbar, so you can find the same file
over SSH when you need the raw article.
