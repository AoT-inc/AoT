# coding=utf-8
"""
Google OAuth2 authorization-code flow — plain `requests`, no vendor SDK
(matches the SGIS/OpenWeather/ChirpStack convention; google-api-python-client
is deliberately NOT a dependency).

Instance-wide client_id/client_secret come from Misc (admin-configured on
settings/integrations); the redirect_uri is built from Misc.oauth_public_base_url
so it deterministically matches what's registered in Google Cloud Console
(rather than trusting proxy request headers). Per-user tokens are stored,
encrypted, in UserCalendarConnection — this module never persists anything, it
only talks to Google's endpoints.
"""
import logging
import time

import requests

logger = logging.getLogger("aot.google_oauth")

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"

# calendar = two-way event read/write; userinfo.email = connected account label;
# drive.file = per-file access ONLY to files the user explicitly picks via the
# Google Picker (aot/aot_flask/routes_ai_library.py Google Drive knowledge
# source) or that this app creates — deliberately NOT drive.readonly/drive
# (whole-Drive access), which are Google "sensitive/restricted" scopes
# requiring OAuth app verification + an annual CASA security assessment.
# drive.file is a non-sensitive scope: no verification needed, safe for a
# self-hosted app where every operator registers their own Cloud Console
# OAuth client. See project_google_drive_source memory for the tradeoff.
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/drive.file",
    "openid",
]

# Refresh a bit before the real expiry so an in-flight sync never uses a token
# that expires mid-request (same safety-buffer idea as gis_sgis.py's 14000s).
_EXPIRY_SAFETY_SEC = 120


def _get_client_config():
    """(client_id, client_secret, public_base_url).

    Environment variables win over the Misc DB row, so a fleet of internal
    servers can share one Google OAuth client via a deployment template
    (docker-compose env) instead of each admin re-entering it in the UI:
      GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET / OAUTH_PUBLIC_BASE_URL
    Any unset env var falls back to the corresponding Misc column. Import is
    lazy so this module loads without an app context."""
    import os

    env_id = (os.environ.get('GOOGLE_OAUTH_CLIENT_ID') or '').strip()
    env_secret = (os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET') or '').strip()
    env_base = (os.environ.get('OAUTH_PUBLIC_BASE_URL') or '').strip().rstrip('/')

    cid = secret = base = None
    from aot.databases.models import Misc
    misc = Misc.query.first()
    if misc is not None:
        cid = (misc.google_oauth_client_id or '').strip() or None
        secret = (misc.google_oauth_client_secret or '').strip() or None
        base = (misc.oauth_public_base_url or '').strip().rstrip('/') or None

    return (env_id or cid, env_secret or secret, env_base or base)


def config_source():
    """Which fields are supplied by environment (vs DB) — for the settings UI
    to show 'configured via environment' and disable those inputs."""
    import os
    return {
        'client_id_env': bool((os.environ.get('GOOGLE_OAUTH_CLIENT_ID') or '').strip()),
        'client_secret_env': bool((os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET') or '').strip()),
        'base_url_env': bool((os.environ.get('OAUTH_PUBLIC_BASE_URL') or '').strip()),
    }


def is_configured():
    cid, secret, base = _get_client_config()
    return bool(cid and secret and base)


def redirect_uri():
    """The single redirect URI that must be registered verbatim in Google Cloud
    Console for this server. Returns None if the public base URL isn't set."""
    _cid, _secret, base = _get_client_config()
    if not base:
        return None
    return base + "/oauth/google/callback"


def build_consent_url(state):
    """Build the Google consent-screen URL. access_type=offline + prompt=consent
    ensures a refresh_token is returned (Google omits it on re-consent without
    prompt=consent). Returns None if unconfigured."""
    cid, _secret, _base = _get_client_config()
    ruri = redirect_uri()
    if not cid or not ruri:
        return None
    from urllib.parse import urlencode
    params = {
        "client_id": cid,
        "redirect_uri": ruri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return AUTH_ENDPOINT + "?" + urlencode(params)


def exchange_code(code):
    """Exchange an authorization code for tokens. Returns a dict:
      {access_token, refresh_token, expires_at (epoch), scope} on success,
      or {'error': msg} on failure. `expires_at` is absolute epoch seconds so
      callers can store it directly as token_expiry."""
    cid, secret, _base = _get_client_config()
    ruri = redirect_uri()
    if not (cid and secret and ruri):
        return {"error": "Google OAuth is not configured."}
    try:
        resp = requests.post(TOKEN_ENDPOINT, data={
            "code": code,
            "client_id": cid,
            "client_secret": secret,
            "redirect_uri": ruri,
            "grant_type": "authorization_code",
        }, timeout=10)
    except Exception as exc:
        return {"error": "Token request failed: {}".format(exc)}
    if resp.status_code != 200:
        return {"error": "Token exchange rejected ({}): {}".format(resp.status_code, resp.text[:300])}
    data = resp.json()
    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),   # may be absent if user re-consented without prompt=consent
        "expires_at": time.time() + int(data.get("expires_in", 3600)) - _EXPIRY_SAFETY_SEC,
        "scope": data.get("scope"),
    }


def refresh_access_token(refresh_token):
    """Trade a refresh_token for a fresh access_token. Returns
    {access_token, expires_at} or {'error': msg}. Google does not return a new
    refresh_token here — the stored one keeps being reused until revoked."""
    cid, secret, _base = _get_client_config()
    if not (cid and secret):
        return {"error": "Google OAuth is not configured."}
    if not refresh_token:
        return {"error": "No refresh token (re-authentication required)."}
    try:
        resp = requests.post(TOKEN_ENDPOINT, data={
            "refresh_token": refresh_token,
            "client_id": cid,
            "client_secret": secret,
            "grant_type": "refresh_token",
        }, timeout=10)
    except Exception as exc:
        return {"error": "Refresh request failed: {}".format(exc)}
    if resp.status_code != 200:
        # 400 invalid_grant here = refresh token revoked/expired → re-auth needed.
        return {"error": "Token refresh rejected ({}): {}".format(resp.status_code, resp.text[:300])}
    data = resp.json()
    return {
        "access_token": data.get("access_token"),
        "expires_at": time.time() + int(data.get("expires_in", 3600)) - _EXPIRY_SAFETY_SEC,
    }


def fetch_account_email(access_token):
    """Return the connected Google account's email (for display), or None."""
    try:
        resp = requests.get(USERINFO_ENDPOINT,
                            headers={"Authorization": "Bearer {}".format(access_token)},
                            timeout=10)
        if resp.status_code == 200:
            return resp.json().get("email")
    except Exception:
        pass
    return None


def revoke_token(token):
    """Best-effort revoke of a refresh/access token at Google. Returns True on
    2xx. A failure here is non-fatal — we still delete our local row."""
    if not token:
        return False
    try:
        resp = requests.post(REVOKE_ENDPOINT, data={"token": token}, timeout=10)
        return resp.status_code // 100 == 2
    except Exception:
        return False
