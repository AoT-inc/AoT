# coding=utf-8
"""App side of the Docker update handshake.

The app cannot update itself: `docker compose up -d` recreates the very
container that ran it, killing the command midway. So the privileged work lives
in a separate opt-in sidecar (docker/updater/), and the two talk through files
in the shared aot_data volume:

    update/request.json    app  -> updater   "please install <version>"
    update/status.json     updater -> app    state machine + result
    update/heartbeat.json  updater -> app    "I exist"  (freshness-checked)
    update/update.log      updater -> app    what the upgrade page tails

The request is DATA, not a command. It names a version; it cannot name an image,
a registry or a shell command. The updater re-validates everything and only ever
pulls the hardcoded AoT repository -- so write access to the volume does not
become "run any container I like on the host".

Everything here is app-side: writing a request, reading status, reading the log.
Nothing in this module can start, stop or pull anything.
"""
import datetime
import errno
import json
import logging
import os
import re
import time
import uuid

from aot.config import (DOCKER_UPDATE_HEARTBEAT_FILE, DOCKER_UPDATE_LOG_FILE,
                        DOCKER_UPDATE_PATH, DOCKER_UPDATE_REQUEST_FILE,
                        DOCKER_UPDATE_STATUS_FILE)

logger = logging.getLogger("aot.docker_update")

# The only shape a target version may take. Deliberately stricter than the
# registry's tag rules: no moving tags ('latest', 'YY.MM'), no digests, no
# path separators. Anything else is refused before it reaches a file.
TARGET_VERSION_RE = re.compile(r'^\d{2}\.\d{2}\.\d+$')

# States the updater reports. 'requested' is written by the app; the rest come
# from the sidecar. Terminal states are the last three.
STATE_REQUESTED = 'requested'
STATE_BACKING_UP = 'backing_up'
STATE_PULLING = 'pulling'
STATE_RESTARTING = 'restarting'
STATE_VERIFYING = 'verifying'
STATE_DONE = 'done'
STATE_FAILED = 'failed'
STATE_ROLLED_BACK = 'failed_rolled_back'

RUNNING_STATES = (STATE_REQUESTED, STATE_BACKING_UP, STATE_PULLING,
                  STATE_RESTARTING, STATE_VERIFYING)
TERMINAL_STATES = (STATE_DONE, STATE_FAILED, STATE_ROLLED_BACK)


def valid_target(version):
    return bool(version) and bool(TARGET_VERSION_RE.match(str(version)))


def _read_json(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception(f"_read_json({path})")
        return None


def read_status():
    """The updater's last reported status, or None if it never reported."""
    return _read_json(DOCKER_UPDATE_STATUS_FILE)


def read_request():
    return _read_json(DOCKER_UPDATE_REQUEST_FILE)


def update_in_progress():
    """True while an update is mid-flight.

    A request the updater has not picked up yet counts as in progress -- the
    page must not offer the button twice while the sidecar is between polls.
    """
    status = read_status()
    request = read_request()
    if request and (not status or status.get('id') != request.get('id')):
        return True
    return bool(status and status.get('state') in RUNNING_STATES)


def request_update(target_version, requested_by=None):
    """Ask the updater to install `target_version`.

    :return: (ok, message_or_request_id)
    """
    if not valid_target(target_version):
        # Refused here as well as in the updater. Two independent checks, since
        # this one runs with the user's identity attached and can say why.
        return False, f"Invalid target version: {target_version!r}"

    if update_in_progress():
        return False, "An update is already in progress."

    request = {
        'id': str(uuid.uuid4()),
        'action': 'update',
        'target': str(target_version),
        'requested_by': requested_by or 'unknown',
        'requested_at': time.time(),
    }

    try:
        os.makedirs(DOCKER_UPDATE_PATH, exist_ok=True)
        # Write-then-rename: the updater polls this path, and must never read a
        # half-written request and act on a truncated version string.
        tmp_path = f'{DOCKER_UPDATE_REQUEST_FILE}.partial'
        with open(tmp_path, 'w', encoding='utf-8') as fh:
            json.dump(request, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, DOCKER_UPDATE_REQUEST_FILE)
    except OSError as err:
        if err.errno == errno.EROFS:
            return False, "The update directory is read-only."
        logger.exception("request_update()")
        return False, str(err)
    except Exception as err:
        logger.exception("request_update()")
        return False, str(err)

    logger.info(f"Docker update requested: {target_version} "
                f"by {request['requested_by']} (id {request['id']})")
    return True, request['id']


def read_log(max_bytes=64000):
    """Tail of the updater log, for the upgrade page's live view.

    Returns None when there is no log yet, so the caller can tell "no updater
    has ever run" apart from "an updater ran and printed nothing".
    """
    try:
        size = os.path.getsize(DOCKER_UPDATE_LOG_FILE)
        with open(DOCKER_UPDATE_LOG_FILE, encoding='utf-8', errors='replace') as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # drop the partial first line
            return fh.read()
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("read_log()")
        return None


def heartbeat_path():
    """Exposed so the updater's own contract test can assert both sides agree
    on the path rather than each hardcoding its own copy."""
    return DOCKER_UPDATE_HEARTBEAT_FILE


#
# Scheduling -- "install it at this hour, unattended"
#

DEFAULT_SCHEDULE = '03:00'
SCHEDULE_RE = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')


def parse_schedule(value):
    """'HH:MM' -> (hour, minute), or None if it is not a time of day.

    Accepts '3:00' as well as '03:00' -- a browser time input always sends the
    padded form, but the column is also editable by hand.
    """
    if not value:
        return None
    match = SCHEDULE_RE.match(str(value).strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _resolve_tz(tz_name):
    """tzinfo for `tz_name`, or the configured local zone if not given.

    A named zone is resolved straight through pytz rather than via
    time_utils.get_local_now(): that helper reads the DB (so it needs a Flask
    app context, which the daemon does not have) and quietly returns UTC
    without one. When the caller already knows the zone, going through it adds
    a silent way to get the wrong answer.
    """
    if tz_name:
        try:
            import pytz
            return pytz.timezone(tz_name)
        except Exception:
            logger.warning(f"Unknown timezone {tz_name!r}; using the "
                           f"configured local zone instead")
    from aot.utils.time_utils import get_local_now
    return get_local_now().tzinfo


def _localize(naive, tz):
    """Attach `tz` to a naive local wall time. pytz needs localize() -- passing
    a pytz zone to replace(tzinfo=...) yields the zone's 19th-century LMT
    offset, which is minutes off."""
    if hasattr(tz, 'localize'):
        return tz.localize(naive)
    return naive.replace(tzinfo=tz)


def next_scheduled_run(schedule, after=None, tz_name=None):
    """Epoch seconds of the next occurrence of `schedule` in LOCAL time.

    Local, not UTC: a farm manager who types 03:00 means three in the morning
    where the farm is, and that is what the timezone setting is for
    (docs/design/timezone-management.md).

    Strictly after `after` (default: now). Equal-to would let a run that just
    finished immediately qualify again and update in a loop.

    :return: epoch seconds, or None if the schedule is unusable -- the caller
             must treat None as "do not run", never as "run now".
    """
    parsed = parse_schedule(schedule)
    if not parsed:
        return None
    hour, minute = parsed

    tz = _resolve_tz(tz_name)
    try:
        reference = datetime.datetime.fromtimestamp(
            time.time() if after is None else after, tz=tz)
    except (OverflowError, OSError, ValueError, TypeError):
        return None

    wall = reference.replace(tzinfo=None)
    candidate = wall.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= wall:
        candidate += datetime.timedelta(days=1)
    return _localize(candidate, tz).timestamp()


def format_local(timestamp, tz_name=None):
    """Epoch seconds -> 'YYYY-MM-DD HH:MM' in local time, for log lines."""
    if not timestamp:
        return 'never'
    try:
        return datetime.datetime.fromtimestamp(
            timestamp, tz=_resolve_tz(tz_name)).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return str(timestamp)
