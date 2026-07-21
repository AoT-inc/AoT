# coding=utf-8
"""
Google Drive API v3 — thin HTTP wrapper (plain `requests`, no vendor SDK),
matching the convention in aot/utils/google_calendar_api.py.

Stateless: every function takes an already-valid access_token (the caller —
aot/ai/services/context_source_service.py's google_drive branch — owns
refreshing it, reusing aot.ai.services.calendar_sync_service.get_valid_access_token
against the SAME UserCalendarConnection the Calendar sync uses; Drive access is
just an additional scope on that one per-user Google connection, not a
separate credential).

Only `drive.file` scope is assumed — i.e. only files the user picked via the
Google Picker (or that this app created) are visible. There is deliberately no
"list arbitrary Drive contents" function here for that reason.
"""
import logging

import requests

logger = logging.getLogger("aot.google_drive_api")

_FILES_BASE = "https://www.googleapis.com/drive/v3/files"
_TIMEOUT = 20

# Google's native (non-binary) formats can't be downloaded as raw bytes —
# they must be EXPORTED to a real file format first. Maps mimeType -> the
# export mimeType + a matching file extension (so the downstream parser,
# which dispatches on extension, treats it correctly).
_EXPORT_FORMATS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
    # Sheets export to CSV is single-sheet only (the first/active sheet) —
    # a real Drive API limitation, not something this wrapper can work around.
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
}


def _headers(access_token):
    return {"Authorization": "Bearer {}".format(access_token)}


def get_file_metadata(access_token, file_id):
    """Returns ({id, name, mimeType, size}, error). `size` is absent/None for
    native Google formats (Docs/Sheets/Slides have no fixed byte size)."""
    try:
        resp = requests.get(
            "{}/{}".format(_FILES_BASE, file_id),
            headers=_headers(access_token),
            params={"fields": "id,name,mimeType,size"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        return None, "Drive metadata request failed: {}".format(exc)
    if resp.status_code != 200:
        return None, "Drive metadata rejected ({}): {}".format(resp.status_code, resp.text[:300])
    return resp.json(), None


def fetch_file_content(access_token, file_id):
    """Fetch one Drive file's content as bytes, choosing export vs raw
    download based on its mimeType. Returns (content_bytes, filename, error) —
    `filename` already carries the right extension for the downstream parser
    (aot.ai.services.context_source_service._parse_document dispatches on
    suffix), including for exported Google-native files."""
    meta, err = get_file_metadata(access_token, file_id)
    if err:
        return None, None, err
    mime = meta.get("mimeType", "")
    name = meta.get("name") or file_id

    if mime in _EXPORT_FORMATS:
        export_mime, ext = _EXPORT_FORMATS[mime]
        try:
            resp = requests.get(
                "{}/{}/export".format(_FILES_BASE, file_id),
                headers=_headers(access_token),
                params={"mimeType": export_mime},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            return None, None, "Drive export request failed: {}".format(exc)
        if resp.status_code != 200:
            return None, None, "Drive export rejected ({}): {}".format(resp.status_code, resp.text[:300])
        base_name = name if name.lower().endswith(ext) else name + ext
        return resp.content, base_name, None

    if mime.startswith("application/vnd.google-apps."):
        # Some other native Google type (Form, Drawing, Site, ...) with no
        # useful text export — fail clearly instead of returning garbage.
        return None, None, "'{}' is a Google {} — not a supported document type for knowledge sync".format(
            name, mime.rsplit(".", 1)[-1])

    try:
        resp = requests.get(
            "{}/{}".format(_FILES_BASE, file_id),
            headers=_headers(access_token),
            params={"alt": "media"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        return None, None, "Drive download request failed: {}".format(exc)
    if resp.status_code != 200:
        return None, None, "Drive download rejected ({}): {}".format(resp.status_code, resp.text[:300])
    return resp.content, name, None
