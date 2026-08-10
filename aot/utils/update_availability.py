# -*- coding: utf-8 -*-
"""One answer to "is an upgrade available?", from the source that governs how
*this* install actually upgrades.

There are two sources and they disagree, on purpose:

  bare-metal  -> git tags   (aot/utils/github_release_info.py). The upgrade
                 scripts check out a tag, so a tag existing is sufficient.
  Docker      -> GHCR tags  (aot/utils/registry_release_info.py). The upgrade
                 pulls an image, which is published minutes *after* the tag.

Before this module every caller asked git tags, so a Docker install was told an
upgrade existed while `docker pull` would still 404 -- and had no way to act on
it either way. Three callers share this: the daemon's periodic check
(aot_daemon.check_aot_upgrade_exists), the Admin -> Upgrade page, and the
`get_system_update_status` MCP tool.

Read-only.
"""
import json
import logging
import os
import time

from aot.config import (AOT_VERSION, DOCKER_CONTAINER, DOCKER_IMAGE,
                        DOCKER_IMAGE_TAG, DOCKER_UPDATE_HEARTBEAT_FILE,
                        DOCKER_UPDATE_HEARTBEAT_MAX_AGE,
                        DOCKER_UPDATE_STATUS_FILE)

logger = logging.getLogger("aot.update_availability")


def is_docker_install():
    return DOCKER_CONTAINER


def check_upgrade_exists():
    """Ask the right source whether a newer version is available.

    :return: (upgrade_exists, releases, all_tags, latest_release, errors)
             -- the tuple shape AoTRelease.github_upgrade_exists() returns, so
             callers can stay source-agnostic.
    """
    if DOCKER_CONTAINER:
        from aot.utils.registry_release_info import RegistryRelease
        return RegistryRelease().upgrade_exists()

    from aot.utils.github_release_info import AoTRelease
    return AoTRelease().github_upgrade_exists()


def running_image_reference():
    """How to name the running build in the UI, or None if we cannot.

    Only the host knows which image it started; the container learns it from
    AOT_IMAGE_TAG (docker-compose.prod.yml passes it through). Without that we
    say nothing rather than guessing `<registry image>:<AOT_VERSION>` -- that
    guess is wrong for a locally built image and for a moving tag, and a wrong
    image reference is worse than no image reference when someone is deciding
    what to pull.
    """
    if not DOCKER_CONTAINER or not DOCKER_IMAGE_TAG:
        return None
    return f'{DOCKER_IMAGE}:{DOCKER_IMAGE_TAG}'


def _read_json(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception(f"_read_json({path})")
        return None


def updater_status():
    """State of the (opt-in) updater sidecar.

    Phase 1 ships no updater, so this reports absent everywhere -- the upgrade
    page uses it to choose between a one-click button and the manual host
    instructions, and must not offer a button that nothing would answer.

    :return: dict with 'present' (bool), 'last_seen' (epoch or None) and
             'state' (the updater's own last reported state, or None)
    """
    result = {'present': False, 'last_seen': None, 'state': None}
    if not DOCKER_CONTAINER:
        return result

    heartbeat = _read_json(DOCKER_UPDATE_HEARTBEAT_FILE)
    if not heartbeat:
        return result

    last_seen = heartbeat.get('timestamp')
    try:
        last_seen = float(last_seen)
    except (TypeError, ValueError):
        # A heartbeat we cannot date is a heartbeat we cannot trust.
        return result

    result['last_seen'] = last_seen
    # Stale heartbeat means the sidecar is gone, not idle. Treating "gone" as
    # "present" would offer a button whose request file nothing ever reads.
    if time.time() - last_seen <= DOCKER_UPDATE_HEARTBEAT_MAX_AGE:
        result['present'] = True

    status = _read_json(DOCKER_UPDATE_STATUS_FILE)
    if status:
        result['state'] = status.get('state')
    return result


def alembic_revision():
    """The schema revision the live database is stamped with, or None.

    Read straight from the alembic_version table rather than through the ORM:
    this is used by health checks that must still answer while the app is only
    half-working.
    """
    try:
        from sqlalchemy import text

        from aot.aot_flask.extensions import db
        row = db.session.execute(
            text("SELECT version_num FROM alembic_version")).fetchone()
        return row[0] if row else None
    except Exception:
        logger.debug("alembic_revision() unavailable", exc_info=True)
        return None


def health_snapshot(detail=False):
    """Payload for /health.

    Without `detail` this deliberately says almost nothing -- it is a public
    liveness probe, and the version of a farm controller is not something to
    hand to anonymous callers.
    """
    snapshot = {'status': 'ok', 'docker': DOCKER_CONTAINER}
    if detail:
        snapshot.update({
            'version': AOT_VERSION,
            'alembic_revision': alembic_revision(),
            'image': running_image_reference(),
        })
    return snapshot


def health_detail_key():
    """Shared secret that lets a non-browser caller (the phase-2 updater) read
    the detailed health payload. Unset means "logged-in users only"."""
    return os.environ.get('AOT_HEALTH_KEY') or None
