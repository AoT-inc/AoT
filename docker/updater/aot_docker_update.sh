#!/bin/sh
# =============================================================================
# AoT Docker updater
#
# Applies an AoT update on a Docker deployment: back up, pull, swap the image
# tag, recreate the containers, verify, and roll back if verification fails.
#
# Why this is a separate process at all: `docker compose up -d` recreates the
# container that ran it, so the app cannot update itself -- the command dies
# halfway through. This runs either
#
#   * in the opt-in updater sidecar (docker/docker-compose.updater.yml), or
#   * directly on the host  (./aot_docker_update.sh --project-dir /opt/AoT ...)
#
# and in both cases it is deliberately NOT part of the set of services it
# recreates, so it survives its own work.
#
# The request it acts on is data, not a command: it carries a version number
# and nothing else. The image repository is fixed below and never comes from
# the request, so write access to the state volume cannot turn into "run any
# image you like on this host".
#
# Exit codes (one-shot mode): 0 success, 1 failure, 2 bad invocation.
# =============================================================================
set -u

# ---------------------------------------------------------------------------
# Configuration (env, all overridable; defaults match docker-compose.prod.yml)
# ---------------------------------------------------------------------------
PROJECT_DIR="${AOT_PROJECT_DIR:-/opt/AoT}"
COMPOSE_FILE="${AOT_COMPOSE_FILE:-docker/docker-compose.prod.yml}"
ENV_FILE="${AOT_ENV_FILE:-}"
STATE_DIR="${AOT_UPDATE_DIR:-/state/update}"
HEALTH_URL="${AOT_HEALTH_URL:-http://aot-app/health}"
HEALTH_KEY="${AOT_HEALTH_KEY:-}"
HEALTH_TIMEOUT="${AOT_HEALTH_TIMEOUT:-300}"
POLL_INTERVAL="${AOT_UPDATE_POLL:-15}"
APP_SERVICE="${AOT_APP_SERVICE:-aot-app}"
SERVICES="${AOT_UPDATE_SERVICES:-aot-app aot_daemon aot_mcp}"
DAEMON_SERVICE="${AOT_DAEMON_SERVICE:-aot_daemon}"
PRUNE="${AOT_UPDATE_PRUNE:-0}"

# The image repository. Overridable by the operator (private mirrors, and the
# end-to-end tests), but NEVER by the request file -- that is the whole point.
# Whoever can set this env var can already start containers on this host; the
# property being protected is that write access to the shared state volume
# cannot be escalated into running an arbitrary image.
IMAGE_REPO="${AOT_IMAGE_REPO:-ghcr.io/aot-inc/aot}"

REQUEST_FILE="$STATE_DIR/request.json"
STATUS_FILE="$STATE_DIR/status.json"
HEARTBEAT_FILE="$STATE_DIR/heartbeat.json"
LOG_FILE="$STATE_DIR/update.log"
LOCK_DIR="$STATE_DIR/updater.lock"

MODE="loop"

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
log() {
    _line="$(date '+%Y-%m-%d %H:%M:%S') $*"
    echo "$_line"
    [ -d "$STATE_DIR" ] && echo "$_line" >> "$LOG_FILE"
    return 0
}

json_escape() {
    # Escapes backslashes, quotes and newlines for embedding in JSON.
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n' ' '
}

# write_atomic <path>  (content on stdin)
write_atomic() {
    _dest="$1"
    _tmp="$_dest.partial"
    cat > "$_tmp" && mv -f "$_tmp" "$_dest"
}

# status <state> <message>
status() {
    _state="$1"
    _message="$(json_escape "${2:-}")"
    write_atomic "$STATUS_FILE" <<EOF
{
  "id": "$(json_escape "$REQUEST_ID")",
  "state": "$_state",
  "target": "$(json_escape "$TARGET")",
  "from_version": "$(json_escape "$FROM_VERSION")",
  "previous_tag": "$(json_escape "$PREVIOUS_TAG")",
  "backup": "$(json_escape "$BACKUP_DIR")",
  "message": "$_message",
  "updated_at": $(date +%s)
}
EOF
}

heartbeat() {
    write_atomic "$HEARTBEAT_FILE" <<EOF
{"timestamp": $(date +%s), "version": "1"}
EOF
}

compose() {
    # No --project-directory: compose resolves the relative bind mounts in
    # docker-compose.prod.yml (../aot/inputs/custom_inputs and friends) against
    # the compose file's own directory, and those paths are handed to the host
    # daemon verbatim. Overriding the project directory would silently bind the
    # wrong host directories. Run it exactly the way an admin would.
    ( cd "$PROJECT_DIR" && docker compose -f "$COMPOSE_FILE" "$@" )
}

app_container() {
    compose ps -q "$APP_SERVICE" 2>/dev/null | head -n 1
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
valid_target() {
    echo "$1" | grep -Eq '^[0-9]{2}\.[0-9]{2}\.[0-9]+$'
}

resolve_env_file() {
    if [ -n "$ENV_FILE" ]; then
        echo "$ENV_FILE"
        return
    fi
    # Compose reads .env from the project directory, which defaults to the
    # directory holding the compose file.
    echo "$PROJECT_DIR/$(dirname "$COMPOSE_FILE")/.env"
}

current_tag() {
    _env="$(resolve_env_file)"
    if [ -f "$_env" ]; then
        _tag="$(grep -E '^AOT_IMAGE_TAG=' "$_env" | tail -n 1 | cut -d= -f2-)"
        [ -n "$_tag" ] && { echo "$_tag"; return; }
    fi
    echo "latest"
}

# set_tag <new_tag> <second_key> <second_value>
#
# AOT_IMAGE_TAG_PREV must always name a version that WORKED -- somebody reading
# it to roll back by hand has to land somewhere safe. So a rollback records the
# version it fled as AOT_IMAGE_TAG_FAILED instead, and leaves PREV alone.
set_tag() {
    _new="$1"
    _key="$2"
    _val="$3"
    _env="$(resolve_env_file)"
    touch "$_env" 2>/dev/null || {
        log "ERROR: cannot write $_env"
        return 1
    }
    # The tag is the only record of what to go back to, and it has to survive
    # this process dying, so it lives in .env rather than in memory.
    _tmp="$_env.aot-update"
    grep -vE "^(AOT_IMAGE_TAG|$_key)=" "$_env" > "$_tmp" 2>/dev/null || true
    echo "AOT_IMAGE_TAG=$_new" >> "$_tmp"
    echo "$_key=$_val" >> "$_tmp"
    mv -f "$_tmp" "$_env"
}

# health_field <json> <key>   -- values are strings or null; no jq in docker:cli
health_field() {
    # shellcheck disable=SC2020  # intentional 1:1 map: , { } all become newlines
    printf '%s' "$1" | tr ',{}' '\n\n\n' \
        | grep "\"$2\"" | head -n 1 \
        | sed -e 's/^[^:]*: *//' -e 's/^"//' -e 's/"$//' -e 's/ *$//'
}

fetch_health() {
    if [ -n "$HEALTH_KEY" ]; then
        curl -fsS --max-time 10 -H "X-AOT-HEALTH-KEY: $HEALTH_KEY" "$HEALTH_URL" 2>/dev/null
    else
        curl -fsS --max-time 10 "$HEALTH_URL" 2>/dev/null
    fi
}

# wait_health <expected_version> <expected_alembic|"">
# Succeeds only when the app both serves AND reports the build we expect.
# "It answered 200" is not enough: during a rollback the old container answers
# 200 too, and during a failed migration the new one does.
wait_health() {
    _want_version="$1"
    _want_alembic="${2:-}"
    _deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
    _last=""

    while [ "$(date +%s)" -lt "$_deadline" ]; do
        _body="$(fetch_health)"
        if [ -n "$_body" ]; then
            _version="$(health_field "$_body" version)"
            _alembic="$(health_field "$_body" alembic_revision)"
            if [ -z "$_version" ]; then
                # Detail is gated; without it we cannot tell the new build from
                # the old one, so refusing here is the honest answer.
                _last="health responded but withheld version detail (set AOT_HEALTH_KEY)"
            elif [ "$_version" != "$_want_version" ]; then
                _last="serving $_version, waiting for $_want_version"
            elif [ -n "$_want_alembic" ] && [ "$_alembic" != "$_want_alembic" ]; then
                _last="schema at ${_alembic:-none}, expected $_want_alembic"
            else
                log "health OK: version=$_version schema=${_alembic:-unknown}"
                return 0
            fi
        else
            _last="no response yet"
        fi
        sleep 5
    done

    log "health gate FAILED after ${HEALTH_TIMEOUT}s: $_last"
    return 1
}

expected_alembic_for() {
    # Ask the new image what schema revision it targets, so a migration that
    # silently did not run is caught here instead of weeks later. Best effort:
    # a probe failure must not fail the update on its own.
    docker run --rm --entrypoint python \
        -e PYTHONPATH=/app -w /app "$IMAGE_REPO:$1" \
        -c 'from aot.config import ALEMBIC_VERSION; print(ALEMBIC_VERSION)' \
        2>/dev/null | tail -n 1
}

# ---------------------------------------------------------------------------
# The update itself
# ---------------------------------------------------------------------------
do_backup() {
    _cid="$(app_container)"
    if [ -z "$_cid" ]; then
        log "ERROR: could not find the $APP_SERVICE container; is the stack running?"
        return 1
    fi

    _space="$(docker exec "$_cid" python -m aot.utils.docker_backup_cli --estimate 2>/dev/null)"
    _ok="$(echo "$_space" | awk '{print $4}')"
    if [ "$_ok" = "0" ]; then
        log "ERROR: not enough free space for a pre-update backup ($_space)"
        return 1
    fi

    # docker_backup_cli.py's contract is one clean line on stdout, but this
    # value drives --restore during a rollback, so a stray line from anywhere
    # in that dependency chain must not become part of the path. Take the
    # last non-empty line rather than trusting the contract blindly.
    _backup_raw="$(docker exec "$_cid" python -m aot.utils.docker_backup_cli --create)"
    BACKUP_DIR="$(printf '%s\n' "$_backup_raw" | awk 'NF{line=$0} END{print line}')"
    if [ -z "$BACKUP_DIR" ]; then
        log "ERROR: backup failed"
        return 1
    fi
    log "backup created: $BACKUP_DIR"
}

restore_backup() {
    [ -n "$BACKUP_DIR" ] || return 1
    _cid="$(app_container)"
    [ -n "$_cid" ] || return 1
    log "restoring pre-update backup: $BACKUP_DIR"
    docker exec "$_cid" python -m aot.utils.docker_backup_cli --restore "$BACKUP_DIR"
}

recreate() {
    # Stop the daemon first and let it take its time: docker-compose.prod.yml
    # gives it stop_grace_period 180s so it can send Shutdown State to the
    # outputs and flush its audit trail. Killing that halfway is how a farm
    # ends up with a valve stuck open.
    log "stopping $DAEMON_SERVICE (graceful, may take up to 180s)"
    compose stop "$DAEMON_SERVICE" >/dev/null 2>&1 || true
    log "recreating: $SERVICES"
    # shellcheck disable=SC2086
    compose up -d $SERVICES
}

rollback() {
    _reason="$1"
    log "ROLLBACK: $_reason"
    status "restarting" "Rolling back to $PREVIOUS_TAG"

    set_tag "$PREVIOUS_TAG" AOT_IMAGE_TAG_FAILED "$TARGET" \
        || log "WARNING: could not rewrite the tag"
    recreate || log "WARNING: recreate during rollback reported an error"

    if wait_health "$FROM_VERSION" "$FROM_ALEMBIC"; then
        log "rolled back to $PREVIOUS_TAG"
        status "failed_rolled_back" "Update to $TARGET failed ($_reason). Rolled back to $PREVIOUS_TAG."
        return 0
    fi

    # The old image is back but the app still is not itself. The usual cause is
    # a migration that already ran: old code cannot read the new schema. The
    # image alone does not undo that -- the data has to go back too.
    log "old image is back but not healthy; restoring the pre-update database"
    if restore_backup; then
        recreate || true
        if wait_health "$FROM_VERSION" "$FROM_ALEMBIC"; then
            log "rolled back to $PREVIOUS_TAG with the pre-update database"
            status "failed_rolled_back" \
                "Update to $TARGET failed ($_reason). Rolled back to $PREVIOUS_TAG and restored the pre-update database."
            return 0
        fi
    fi

    log "ERROR: rollback did not restore a healthy system -- manual recovery needed"
    status "failed" \
        "Update to $TARGET failed ($_reason) AND rollback did not recover. Backup: ${BACKUP_DIR:-none}. Manual recovery required."
    return 1
}

prune_old_images() {
    [ "$PRUNE" = "1" ] || return 0
    _keep1="$TARGET"
    _keep2="$PREVIOUS_TAG"
    docker images --format '{{.Repository}}:{{.Tag}}' \
        | grep "^$IMAGE_REPO:" \
        | grep -v ":$_keep1\$" | grep -v ":$_keep2\$" \
        | while read -r _img; do
            log "pruning old image: $_img"
            docker image rm "$_img" >/dev/null 2>&1 || true
        done
}

run_update() {
    TARGET="$1"

    if ! valid_target "$TARGET"; then
        log "ERROR: refusing target '$TARGET' (expected YY.MM.P)"
        status "failed" "Refused target version '$TARGET'."
        return 1
    fi

    PREVIOUS_TAG="$(current_tag)"
    _health="$(fetch_health)"
    FROM_VERSION="$(health_field "$_health" version)"
    FROM_ALEMBIC="$(health_field "$_health" alembic_revision)"

    if [ -z "$FROM_VERSION" ]; then
        # Without a "before" we cannot tell a successful swap from a no-op, and
        # cannot verify a rollback either. Refuse rather than fly blind.
        log "ERROR: /health did not report a version. Set AOT_HEALTH_KEY on both"
        log "       the app and this updater so the health gate can identify builds."
        status "failed" "Cannot read the running version from /health (AOT_HEALTH_KEY not configured?)."
        return 1
    fi

    log "=== update $FROM_VERSION ($PREVIOUS_TAG) -> $TARGET ==="

    status "backing_up" "Creating a pre-update backup"
    if ! do_backup; then
        status "failed" "Pre-update backup failed; nothing was changed."
        return 1
    fi

    status "pulling" "Pulling $IMAGE_REPO:$TARGET"
    log "pulling $IMAGE_REPO:$TARGET"
    if ! docker pull "$IMAGE_REPO:$TARGET"; then
        log "ERROR: pull failed"
        status "failed" "Could not pull $IMAGE_REPO:$TARGET; nothing was changed."
        return 1
    fi

    EXPECTED_ALEMBIC="$(expected_alembic_for "$TARGET")"
    if [ -n "$EXPECTED_ALEMBIC" ]; then
        log "target schema revision: $EXPECTED_ALEMBIC"
    else
        log "WARNING: could not read the target's schema revision; will verify version only"
    fi

    status "restarting" "Recreating containers on $TARGET"
    if ! set_tag "$TARGET" AOT_IMAGE_TAG_PREV "$PREVIOUS_TAG"; then
        status "failed" "Could not write the image tag; nothing was changed."
        return 1
    fi
    if ! recreate; then
        rollback "containers failed to start"
        return 1
    fi

    status "verifying" "Verifying $TARGET"
    if ! wait_health "$TARGET" "$EXPECTED_ALEMBIC"; then
        rollback "health gate failed"
        return 1
    fi

    prune_old_images
    log "=== update complete: now on $TARGET ==="
    status "done" "Updated to $TARGET."
    return 0
}

# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------
json_value() {
    # shellcheck disable=SC2020  # intentional 1:1 map: , { } all become newlines
    printf '%s' "$1" | tr ',{}' '\n\n\n' \
        | grep "\"$2\"" | head -n 1 \
        | sed -e 's/^[^:]*: *//' -e 's/^"//' -e 's/"$//' -e 's/ *$//'
}

process_request() {
    _body="$(cat "$REQUEST_FILE" 2>/dev/null)"
    [ -n "$_body" ] || return 0

    # The app publishes the request with write-then-rename, so a partial read
    # should be impossible -- but "should be" is not a guarantee about a file
    # another process owns, and a read truncated just after a complete target
    # would look entirely valid. Require the closing brace and wait for the
    # next poll otherwise. (Observed for real against a test harness that wrote
    # the file with a plain redirect: the poller read it mid-write.)
    case "$_body" in
        *'}') ;;
        *)
            log "request file looks incomplete; waiting for the next poll"
            return 0
            ;;
    esac

    _id="$(json_value "$_body" id)"
    _target="$(json_value "$_body" target)"
    _by="$(json_value "$_body" requested_by)"
    [ -n "$_id" ] || return 0

    # Already handled? status.json carries the id of the last request acted on.
    _done_id=""
    [ -f "$STATUS_FILE" ] && _done_id="$(json_value "$(cat "$STATUS_FILE")" id)"
    [ "$_id" = "$_done_id" ] && return 0

    REQUEST_ID="$_id"
    TARGET="$_target"
    BACKUP_DIR=""
    PREVIOUS_TAG=""
    FROM_VERSION=""
    FROM_ALEMBIC=""

    log "request $_id from ${_by:-unknown}: install $_target"
    run_update "$_target"
}

acquire_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        return 0
    fi
    return 1
}

release_lock() {
    rmdir "$LOCK_DIR" 2>/dev/null || true
}

usage() {
    cat <<'EOF'
Usage:
  aot_docker_update.sh [--loop]            poll the state dir for requests
  aot_docker_update.sh --once              one poll, then exit (systemd timer)
  aot_docker_update.sh --update <version>  apply one update now and exit
  aot_docker_update.sh --check             print what is running and configured

Environment: AOT_PROJECT_DIR AOT_COMPOSE_FILE AOT_ENV_FILE AOT_UPDATE_DIR
             AOT_HEALTH_URL AOT_HEALTH_KEY AOT_HEALTH_TIMEOUT AOT_UPDATE_POLL
             AOT_UPDATE_SERVICES AOT_UPDATE_PRUNE
EOF
}

# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
ONESHOT_TARGET=""
while [ $# -gt 0 ]; do
    case "$1" in
        --loop) MODE="loop" ;;
        --once) MODE="once" ;;
        --update) MODE="oneshot"; ONESHOT_TARGET="${2:-}"; shift ;;
        --check) MODE="check" ;;
        --project-dir) PROJECT_DIR="${2:-}"; shift ;;
        --compose-file) COMPOSE_FILE="${2:-}"; shift ;;
        --state-dir) STATE_DIR="${2:-}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
    esac
    shift
done

REQUEST_FILE="$STATE_DIR/request.json"
STATUS_FILE="$STATE_DIR/status.json"
HEARTBEAT_FILE="$STATE_DIR/heartbeat.json"
LOG_FILE="$STATE_DIR/update.log"
LOCK_DIR="$STATE_DIR/updater.lock"

REQUEST_ID=""
TARGET=""
BACKUP_DIR=""
PREVIOUS_TAG=""
FROM_VERSION=""
FROM_ALEMBIC=""

mkdir -p "$STATE_DIR" 2>/dev/null || true

if ! docker info >/dev/null 2>&1; then
    log "ERROR: no access to the Docker daemon (is /var/run/docker.sock mounted?)"
    exit 1
fi
if [ ! -f "$PROJECT_DIR/$COMPOSE_FILE" ]; then
    log "ERROR: compose file not found: $PROJECT_DIR/$COMPOSE_FILE"
    log "       The project directory must be mounted at the SAME absolute path"
    log "       it has on the host, or the relative bind mounts inside the"
    log "       compose file will resolve to the wrong host directories."
    exit 1
fi

case "$MODE" in
    check)
        echo "project dir : $PROJECT_DIR"
        echo "compose file: $COMPOSE_FILE"
        echo "env file    : $(resolve_env_file)"
        echo "current tag : $(current_tag)"
        echo "state dir   : $STATE_DIR"
        echo "health url  : $HEALTH_URL (key $( [ -n "$HEALTH_KEY" ] && echo set || echo unset ))"
        _h="$(fetch_health)"
        echo "health      : ${_h:-<no response>}"
        ;;
    once)
        # One pass for a systemd timer: publish the heartbeat so the app knows
        # an updater exists, act on a pending request if there is one, exit.
        heartbeat
        if [ -f "$REQUEST_FILE" ]; then
            acquire_lock || { log "another updater run is in progress"; exit 1; }
            trap release_lock EXIT
            process_request
        fi
        exit $?
        ;;
    oneshot)
        acquire_lock || { log "another updater run is in progress"; exit 1; }
        trap release_lock EXIT
        REQUEST_ID="cli-$(date +%s)"
        run_update "$ONESHOT_TARGET"
        exit $?
        ;;
    loop)
        log "updater started (project $PROJECT_DIR, poll ${POLL_INTERVAL}s)"
        while true; do
            heartbeat
            if [ -f "$REQUEST_FILE" ]; then
                if acquire_lock; then
                    process_request
                    release_lock
                fi
            fi
            sleep "$POLL_INTERVAL"
        done
        ;;
esac
