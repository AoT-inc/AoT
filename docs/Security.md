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
the System Log) records security-relevant activity:

- Login success, failure, and account lockout
- Logout
- User creation, modification, and deletion
- General settings changes
- Manual output/device control
- API key generation
- Remote Admin token issuance

Filter by action, user, or result, and set how many rows to show. **Export CSV**
downloads the currently filtered results.

Entries older than 1 year are removed automatically. This is not currently
configurable from the settings page.

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

!!! note "Existing remote hosts need to be re-added after upgrading"
    Instances upgrading from a version before this token-based scheme was introduced
    will find previously added remote hosts no longer connect. Removing and
    re-adding each one at `/remote/setup` re-establishes the connection with the
    new token.
