# coding=utf-8
"""
Google Calendar API v3 — thin HTTP wrapper (plain `requests`, no vendor SDK).

Stateless: every function takes an already-valid access_token (the sync service
owns refreshing it). Each function returns (result_dict, error_str) so callers
branch on error without exceptions. AoT-originated events carry
extendedProperties.private.aot_job_id so the pull half can recognize and dedup
its own pushes instead of re-importing them as new AoT rows.
"""
import logging
from urllib.parse import quote

import requests

logger = logging.getLogger("aot.google_calendar_api")

_BASE = "https://www.googleapis.com/calendar/v3"


def _enc(seg):
    """URL-encode a path segment (calendar/event ids can contain '#', '@', '/',
    e.g. holiday calendars 'en.south_korea#holiday@...' or an email primary id).
    Without this the '#' is parsed as a URL fragment → 404."""
    return quote(str(seg), safe='')


_TIMEOUT = 15

AOT_JOB_ID_KEY = "aot_job_id"


def _headers(access_token):
    return {"Authorization": "Bearer {}".format(access_token),
            "Content-Type": "application/json"}


def list_events(access_token, calendar_id, sync_token=None, time_min=None,
                time_max=None, page_token=None):
    """List events. With sync_token → only changes since last sync (incremental).
    Without → a time-bounded window (timeMin/timeMax, RFC3339). Returns
    (data, error). data includes items[], and nextSyncToken or nextPageToken.

    A 410 GONE means the syncToken expired — caller must drop it and do a full
    re-list; surfaced as error='sync_token_expired'."""
    params = {
        "singleEvents": "true",
        "showDeleted": "true",   # so cancellations propagate on pull
        "maxResults": 250,
    }
    if sync_token:
        params["syncToken"] = sync_token
    else:
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        params["orderBy"] = "startTime"
    if page_token:
        params["pageToken"] = page_token

    url = "{}/calendars/{}/events".format(_BASE, _enc(calendar_id))
    try:
        resp = requests.get(url, headers=_headers(access_token), params=params, timeout=_TIMEOUT)
    except Exception as exc:
        return None, "list_events request failed: {}".format(exc)
    if resp.status_code == 410:
        return None, "sync_token_expired"
    if resp.status_code != 200:
        return None, "list_events {}: {}".format(resp.status_code, resp.text[:300])
    return resp.json(), None


def insert_event(access_token, calendar_id, body):
    url = "{}/calendars/{}/events".format(_BASE, _enc(calendar_id))
    try:
        resp = requests.post(url, headers=_headers(access_token), json=body, timeout=_TIMEOUT)
    except Exception as exc:
        return None, "insert_event request failed: {}".format(exc)
    if resp.status_code not in (200, 201):
        return None, "insert_event {}: {}".format(resp.status_code, resp.text[:300])
    return resp.json(), None


def update_event(access_token, calendar_id, event_id, body):
    url = "{}/calendars/{}/events/{}".format(_BASE, _enc(calendar_id), _enc(event_id))
    try:
        resp = requests.put(url, headers=_headers(access_token), json=body, timeout=_TIMEOUT)
    except Exception as exc:
        return None, "update_event request failed: {}".format(exc)
    if resp.status_code == 404:
        return None, "not_found"
    if resp.status_code != 200:
        return None, "update_event {}: {}".format(resp.status_code, resp.text[:300])
    return resp.json(), None


def delete_event(access_token, calendar_id, event_id):
    """Delete an event. 404/410 (already gone) is treated as success — the end
    state we wanted is reached either way."""
    url = "{}/calendars/{}/events/{}".format(_BASE, _enc(calendar_id), _enc(event_id))
    try:
        resp = requests.delete(url, headers=_headers(access_token), timeout=_TIMEOUT)
    except Exception as exc:
        return None, "delete_event request failed: {}".format(exc)
    if resp.status_code in (200, 204, 404, 410):
        return {}, None
    return None, "delete_event {}: {}".format(resp.status_code, resp.text[:300])


def list_calendars(access_token):
    """List the user's calendars (calendarList). Returns (items, error) where
    each item has id/summary/backgroundColor/primary/accessRole."""
    url = "{}/users/me/calendarList".format(_BASE)
    try:
        resp = requests.get(url, headers=_headers(access_token),
                            params={'minAccessRole': 'reader', 'maxResults': 250}, timeout=_TIMEOUT)
    except Exception as exc:
        return None, "list_calendars request failed: {}".format(exc)
    if resp.status_code != 200:
        return None, "list_calendars {}: {}".format(resp.status_code, resp.text[:200])
    return resp.json().get('items', []), None


def create_calendar(access_token, summary):
    """Create a new secondary calendar owned by the user. Returns (data, error);
    data.id is the calendar id to store and sync against."""
    url = "{}/calendars".format(_BASE)
    try:
        resp = requests.post(url, headers=_headers(access_token),
                             json={"summary": summary}, timeout=_TIMEOUT)
    except Exception as exc:
        return None, "create_calendar request failed: {}".format(exc)
    if resp.status_code not in (200, 201):
        return None, "create_calendar {}: {}".format(resp.status_code, resp.text[:300])
    return resp.json(), None


def build_event_body(summary, description, start_iso, end_iso, time_zone, aot_job_id=None):
    """Assemble an events.insert/update body from AoT fields. start_iso/end_iso
    are RFC3339 strings; time_zone is an IANA name (e.g. 'Asia/Seoul')."""
    body = {
        "summary": summary or "(untitled)",
        "start": {"dateTime": start_iso, "timeZone": time_zone},
        "end": {"dateTime": end_iso, "timeZone": time_zone},
    }
    if description:
        body["description"] = description
    if aot_job_id is not None:
        body["extendedProperties"] = {"private": {AOT_JOB_ID_KEY: str(aot_job_id)}}
    return body
