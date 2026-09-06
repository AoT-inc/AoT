# Security

This page covers login protection, API keys, and the audit log. For encrypting the
web connection itself, see [Force HTTPS](Configuration-Settings.md#general-settings)
in General Settings.

## Password requirements { #password-requirements }

A password must be at least 8 characters and may contain only letters, numbers, and
symbols. Common passwords (`password`, `qwerty123`, and similar lists used in
credential-stuffing attacks) are rejected even if they meet the length requirement.

AoT does not force periodic password changes. Forcing regular changes is no longer
recommended practice — it tends to push people toward small predictable variations
("Password1", "Password2") rather than a genuinely different password, and is not
required here.

## Account lockout { #account-lockout }

After 5 failed login attempts on an account, that account is locked for 10 minutes,
regardless of which device or browser the attempts came from. The counter resets on a
successful login. This applies to the password login, the keypad login, and the
two-factor code (below) — a wrong code counts the same as a wrong password.

These limits are fixed and not currently exposed as a setting.

## Two-factor authentication (TOTP) { #totp }

AoT supports a second login factor using the standard 6-digit, 30-second codes
produced by apps such as Google Authenticator, Authy, or 1Password (RFC 6238 TOTP —
the same standard those apps already implement for other services).

When enabled for a user, logging in requires the password first and then the current
code from the authenticator app; neither one alone is enough.

!!! note "No self-service enrollment screen yet"
    There is currently no page in AoT where a user can turn this on for themselves —
    that is planned but not yet built. Until then, enabling it requires an
    administrator to set it up directly (generating a secret with
    `aot.utils.totp.generate_secret()` and setting `totp_secret` /
    `totp_enabled = True` on the account). Once enabled, the login behavior above
    applies immediately with no other configuration.

## API keys { #api-keys }

An API key authenticates requests to the [HTTP API](API.md) without a browser
session. Generate one under **Manage → System Management → Users**, editing the
user, then **Generate API Key**.

**The key is shown only once, at the moment it is generated.** AoT does not store
the key itself — only a one-way hash of it — so the settings page cannot display an
existing key again later. Copy it somewhere safe immediately after generating it. If
it is lost, generate a new one; there is no way to recover the old value, and doing
so immediately invalidates the previous key.

The key can be presented three ways: the `X-API-KEY` header, HTTP Basic
authentication, or (deprecated, see [API.md](API.md#authentication)) an `api_key`
query parameter. Regenerating a key immediately invalidates the previous one — update
any script or integration using the old key before generating a replacement.

## Audit log { #audit-log }

**Manage → Audit Log** (requires the "View Logs" permission — the same one used for
the System Log; on the default roles that means Admin, Editor, and Monitor, not
Guest or Kiosk — see [Roles](Configuration-Settings.md#roles)) is a browsable,
filterable record of who did what, when, from where, and whether it succeeded.

### What gets recorded

- Login success, failure, and account lockout; logout
- User creation, modification, and deletion
- Group creation, modification, deletion, and changes to a group's membership or
  resource grants
- General settings changes
- Device control — a person switching an output from the dashboard, an AI agent
  doing so on their behalf, and an irrigation sequence opening or closing a valve.
  Continuous automatic control by PID/PWM controllers and the environment
  coordinator is deliberately **not** included here: it runs far too often for a
  row-per-action table, and is tracked instead as tags on the time-series
  measurement data. A driver's own startup, shutdown, or removal is recorded too,
  since that can change hardware state directly.
- API key generation and revocation, and use of the deprecated URL-query-string
  key auth
- Remote Admin token issuance
- Exporting this audit log as CSV, and requesting a software update (from the
  Upgrade page, or from the scheduled auto-update check)

The **Action** filter lists the everyday ones; a few less common actions (such as
the update-request one above) are not in that dropdown but still show up when the
filter is left on **All**.

AI tool calls and their approvals are **not** part of this log — they go through a
separate approval trail described in [Safety & Approval Model](ai/overview.md#safety-approval-model).
This page only records the resulting device-control action, attributed to the AI.

### Reading the table

| Column | Meaning |
|---|---|
| Timestamp | When it happened, shown in your local time zone (stored internally in UTC) |
| Action | The event, as a `domain.verb` string — e.g. `login.failure`, `output.control` |
| Result | `success` or `failure`. A denied or failed attempt is recorded too, not only what went through |
| User | The account name, when the action came from a logged-in person. For device control specifically, this can instead show what triggered it — a sequence, a driver lifecycle phase (`startup`/`shutdown`), or (for the scheduled update check) `auto-update` |
| IP Address | The address the request came from. Blank when there was no browser request to read one from — an AI agent's command, or a driver lifecycle event |
| Target Object | What was acted on: its type and, where known, its name (an output's name, a setting's name, and so on) |
| Detail | A short free-text note. For device control this includes the channel, the requested state, and the determined origin (`user`, `ai`, `sequence`, `lifecycle`, or `unknown` if no code path claimed it — worth a look if you see it) |

**Export CSV** adds columns not shown on screen — `user_id`, `target_id`, and the
`before`/`after` values as JSON, populated for actions where the changed value
matters (currently settings changes).

### Filtering and export

Filter by **Action**, **User** (a partial, case-insensitive match), and **Result**,
and choose how many rows to display (**Rows**, up to 1000). **Export CSV**
downloads every row matching the current Action/User/Result filters — it ignores
the Rows limit, so the file can hold more than what is shown on screen.

### Retention

Entries older than 1 year (`AUDIT_LOG_RETENTION_DAYS`) are removed automatically by
a daily background job. This is not currently configurable from the settings page.

Passwords, password hashes, and API keys themselves are never written to the audit
log — only the fact that an action occurred and who performed it.

## Remote Admin { #remote-admin }

Remote Admin lets one AoT instance display data from other AoT instances. It is
reached directly at `/remote/setup` — it is not currently linked from the main menu.

Adding a remote host asks for that host's username and password, but only to
authenticate once. What is actually stored afterward is a dedicated access token
issued by the remote host for this purpose — not the account's password or its hash.
If that stored token were ever exposed, only Remote Admin access to that one host is
affected; the account's real login credentials are not.

That one-time password is sent only over a connection verified against the
remote's certificate. The certificate is fetched and pinned *first*, without
sending any credentials; the password then travels only over a connection that
this pinned certificate verifies. Earlier versions did the opposite — the
password went out over an unverified connection and the certificate was taken
from the reply body, so anyone in the middle could read the password and pin
their own certificate for every connection that followed.

Trust on first contact still rests with you: a certificate seen for the first
time cannot be checked against anything. The SHA-256 fingerprint of what was
pinned is therefore shown when a host is added — compare it out of band (on the
remote machine itself) before trusting the connection.

If the certificate later stops matching what was pinned, enrollment stops and
nothing is sent. Should the remote genuinely have replaced its certificate,
delete the remote host and add it again; deleting it also drops the old pin.

!!! note "Existing remote hosts need to be re-added after upgrading"
    Instances upgrading from a version before this token-based scheme was introduced
    will find previously added remote hosts no longer connect. Removing and
    re-adding each one at `/remote/setup` re-establishes the connection with the
    new token.
