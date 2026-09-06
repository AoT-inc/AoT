# Integrations

Page: `Settings -> Integrations`

The Integrations page connects AoT to external services. Today it holds one integration: two-way sync between the [Scheduler](ai/scheduler.md) and a personal Google Calendar. Each user connects their own Google account; an administrator first has to register AoT as an OAuth application in the Google Cloud Console and enter the resulting client credentials on this page.

---

## Admin Setup: Google OAuth Client { #google-oauth-setup }

Before any user can connect an account, an administrator must configure an instance-wide Google OAuth client under **Google OAuth Configuration** (Admin) on this page. Until this is done, other users only see: "Google Calendar is not configured yet. Ask an administrator to configure it."

1. In the [Google Cloud Console](https://console.cloud.google.com/), create (or pick) a project and enable the **Google Calendar API**.
2. Create credentials of type **OAuth 2.0 Client ID**, application type **Web application**.
3. On this page, enter the **Public Base URL** first (e.g. `https://your-aot-domain`) — AoT uses it to compute the fixed callback address it will use, shown right below the field as `<Public Base URL>/oauth/google/callback`.
4. Copy that exact URL into the OAuth client's **Authorized redirect URIs** in the Google Cloud Console.
5. Paste the **OAuth Client ID** and **OAuth Client Secret** from the Google Cloud Console into the matching fields here, then **Save**.

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Public Base URL</td>
<td>The externally reachable base URL of this AoT instance. Used only to build the OAuth redirect URI — it must match the address registered in the Google Cloud Console exactly.</td>
</tr>
<tr>
<td>OAuth Client ID / OAuth Client Secret</td>
<td>The credential pair issued for the Web application OAuth client created above.</td>
</tr>
<tr>
<td>Google Picker API Key</td>
<td>Optional. Only needed to enable the Google Drive source (file picker) in the AI Library — a separate, non-secret Cloud Console API key with the Picker API enabled. Not the OAuth Client Secret.</td>
</tr>
</tbody>
</table>

These three values can also be supplied instance-wide via environment variables (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `OAUTH_PUBLIC_BASE_URL`), which take precedence over the fields above — useful when the same client is shared across a fleet of servers via deployment config. When a value comes from the environment, the page marks it as such.

Connecting an account requests these scopes: full **Calendar** access (to read and write events), **email** (to label the connected account), **openid**, and Drive access limited to files the user explicitly picks (`drive.file`, used only by the AI Library's Google Drive source, not by calendar sync).

---

## Connecting Your Account { #connecting }

Once an administrator has completed the setup above, click **Connect Google Calendar** under **Google Calendar** on this page. You are sent to Google's consent screen; after granting access you are returned here as **Connected**, with the connected account's email shown.

Google must return a refresh token for AoT to keep syncing unattended. If it doesn't (this can happen if your account previously granted — and never fully revoked — access), AoT shows an error asking you to remove AoT from your Google account's third-party access and connect again.

---

## What Syncs, and How { #sync-direction }

AoT creates three separate Google calendars for your account, one per [Scheduler](ai/scheduler.md) job category, so personal events never mix with AoT's:

<table>
<thead>
<tr class="header">
<th>Google calendar</th>
<th>AoT category</th>
<th>New events in Google become AoT jobs?</th>
</tr>
</thead>
<tbody>
<tr>
<td>AoT · AI</td>
<td>AI-drafted jobs</td>
<td>No — the AI authors its own jobs; only edits/cancellations sync back.</td>
</tr>
<tr>
<td>AoT · User</td>
<td>Human tasks</td>
<td>Yes — becomes a plain human task (Pending).</td>
</tr>
<tr>
<td>AoT · Device</td>
<td>Device-control jobs</td>
<td>Yes — becomes a device-control job created as a Draft, requiring the normal Scheduler approval before it can execute. A Google event can never fire a device directly.</td>
</tr>
</tbody>
</table>

Each event carries its schedule content — location, device, state, notes — as a structured, human-editable `Label: Value` text block in the event description, written and read in your interface language. Editing that text (or the event's time) in Google and syncing brings the change back into the matching AoT job.

- **AoT → Google (push)**: every pushable job (Pending, Running, Completed, or Failed) is written or updated on its category's calendar.
- **Google → AoT (pull)**: edits, reschedules, and cancellations on a previously synced event update or archive the matching AoT job; new events on the User/Device calendars create new jobs as described above.
- **Direction toggles**: sync direction shown as **AoT → Google** / **Google → AoT** — both are on by default, giving true two-way sync.
- **Conflicts**: if the same job/event changed on both sides, the more recently modified side wins.

Sync runs automatically in the background roughly every 15 minutes, or immediately on **Sync Now**. **Last Synced** shows the time (UTC) of the most recent run, and an **Error** badge appears if it failed (for example, if you revoked access from the Google side).

---

## Disconnecting { #disconnecting }

**Disconnect** under Google Calendar stops the background sync, best-effort revokes AoT's access at Google, and removes AoT's local record of the connection and its event links. Events already created in your Google calendars are **not** deleted — remove them from Google Calendar directly if you no longer want them there.

---

## Security { #security }

Google refresh and access tokens are stored encrypted at rest, per user — no plaintext credential ever appears in the database. The OAuth client credentials configured by an administrator are instance-wide and shared by everyone connecting an account; each user's own connection and tokens remain private to that user.

---

## Related Pages

- [Scheduler](ai/scheduler.md) — the job ledger this integration syncs with.
