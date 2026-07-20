# coding=utf-8
"""Docker-native backup/restore for admin/backup.

aot/scripts/aot_backup_create.sh and aot_backup_restore.sh assume a
bare-metal install (/var/aot-root, /opt/AoT, systemd) and rsync the whole
install directory -- meaningless inside a container, where the live data
(SQLite DB, uploaded files, facility 3D model assets) instead lives in
named Docker volumes (aot_data, aot_uploads, aot_model_assets; see
docker/docker-compose.prod.yml). This module snapshots/restores that data
directly, without needing docker.sock or any host-level access.
"""
import glob
import logging
import os
import shutil
import sqlite3
import time

from aot.config import AOT_VERSION, BACKUP_PATH, PATH_USER_SCRIPTS, SQL_DATABASE_AOT
from aot.utils.service_control import reload_frontend
from aot.utils.system_pi import (assure_path_exists, get_directory_free_space,
                                    get_directory_size)
from aot.utils.tools import UPLOAD_DIRECTORIES
from aot.utils.widget_generate_html import generate_widget_html

logger = logging.getLogger("aot.docker_backup")

# Same shared list create_settings_export()/import_settings() use (see
# aot/utils/tools.py), plus PATH_USER_SCRIPTS: real user-authored scripts
# with no regeneration path, which the ZIP export/import flow already
# covers via its (separate, pre-existing) custom-code directory handling,
# but which Docker admin/backup must capture itself since nothing else
# does for that flow.
UPLOAD_DIRS = UPLOAD_DIRECTORIES + [(PATH_USER_SCRIPTS, "user_scripts")]

BACKUP_DIR_PREFIX = "AoT-backup-"

# How many pre-restore DB safety copies to keep. Each restore leaves one
# behind (see docker_backup_restore()); without a cap they accumulate
# forever in the aot_data volume.
_PRE_RESTORE_RETENTION = 3


def backup_dir_name():
    now = time.strftime("%Y-%m-%d_%H-%M-%S")
    return f"{BACKUP_DIR_PREFIX}{now}-{AOT_VERSION}"


def docker_backup_estimate_size():
    """Bytes docker_backup_create() would actually copy -- the DB plus the
    upload directories, NOT the whole install directory (can_perform_backup()
    in aot/utils/system_pi.py walks INSTALL_DIRECTORY, which isn't what gets
    copied here)."""
    total = 0
    if os.path.isfile(SQL_DATABASE_AOT):
        total += os.path.getsize(SQL_DATABASE_AOT)
    for src_dir, _subfolder in UPLOAD_DIRS:
        if os.path.isdir(src_dir):
            total += get_directory_size(src_dir)
    return total


def docker_can_perform_backup():
    """Docker analogue of can_perform_backup() (system_pi.py), scoped to
    what docker_backup_create() actually copies and checked against
    BACKUP_PATH's own filesystem (the aot_backups volume) rather than the
    bare-metal-only '/var/AoT-backups' path. Returns (size, free_before,
    free_after) in bytes, same shape as can_perform_backup()."""
    assure_path_exists(BACKUP_PATH)
    backup_size = docker_backup_estimate_size()
    free_before = get_directory_free_space(BACKUP_PATH)
    free_after = free_before - backup_size
    return backup_size, free_before, free_after


def _hot_copy_sqlite(src_path, dest_path):
    """Point-in-time copy of a live SQLite DB via SQLite's own backup API,
    instead of a raw file copy -- a raw copy of just the .db file can
    silently miss transactions still sitting in an unmerged -wal file."""
    src_conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(dest_path)
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()


def _replace_dir_contents(target_dir, src_dir):
    """Replace the CONTENTS of target_dir with src_dir's, without removing
    target_dir itself. Docker volumes (e.g. aot_model_assets) are mounted
    directly onto some of these target_dirs, and rmtree()-ing a mount point
    fails with "Device or resource busy" -- only its children can be removed."""
    os.makedirs(target_dir, exist_ok=True)
    for entry in os.listdir(target_dir):
        entry_path = os.path.join(target_dir, entry)
        if os.path.islink(entry_path):
            os.remove(entry_path)
        elif os.path.isdir(entry_path):
            shutil.rmtree(entry_path)
        else:
            os.remove(entry_path)
    # Copy, not move: src_dir is the persistent backup snapshot itself (not a
    # throwaway extraction), and it must still be usable for a later restore.
    for entry in os.listdir(src_dir):
        src_entry = os.path.join(src_dir, entry)
        dest_entry = os.path.join(target_dir, entry)
        if os.path.islink(src_entry):
            # Recreate the symlink itself rather than following it --
            # shutil.copy2()/copytree() on a directory symlink otherwise
            # raises IsADirectoryError and aborts the whole restore.
            os.symlink(os.readlink(src_entry), dest_entry)
        elif os.path.isdir(src_entry):
            shutil.copytree(src_entry, dest_entry)
        else:
            shutil.copy2(src_entry, dest_entry)


def _terminate_daemon_sync(timeout=15):
    """Synchronously stop the aot_daemon and wait for it to fully exit.

    The daemon's own terminate_daemon() RPC handler (aot/aot_daemon.py)
    blocks until stop_all_controllers() has run and self.terminated is set,
    so this call only returns once the daemon has released its DB handle.
    The daemon container then exits and restarts itself via the compose
    `restart: always` policy -- there's no docker.sock mounted into aot-app
    to start it back up directly, and none is needed since the policy
    already does that.

    Best-effort: if Pyro is unreachable the daemon is presumably already
    down (which is the state we want anyway), so failures here are logged
    but never abort the caller.
    """
    try:
        from aot.aot_client import DaemonControl
        DaemonControl(pyro_timeout=timeout).terminate_daemon()
    except Exception:
        logger.warning("Could not confirm daemon stop (may already be down)", exc_info=True)


def _prune_pre_restore_backups():
    """Keep only the _PRE_RESTORE_RETENTION most recent pre-restore DB
    safety copies. Filenames are timestamp-suffixed, so lexical sort order
    matches chronological order."""
    copies = sorted(glob.glob(f"{SQL_DATABASE_AOT}.pre_restore_*"))
    stale = copies[:-_PRE_RESTORE_RETENTION] if len(copies) > _PRE_RESTORE_RETENTION else []
    for path in stale:
        try:
            os.remove(path)
        except OSError:
            logger.warning(f"Could not remove stale pre-restore copy: {path}")


def docker_backup_create():
    """Snapshot the DB + uploaded files + 3D model assets into a new
    directory under BACKUP_PATH. Returns (status, dest_dir_or_error).

    Built under a hidden ".<name>.partial" directory and published via a
    single atomic os.rename() only once every copy has succeeded -- so a
    failure partway through (disk full, permission error) never leaves a
    half-written directory that admin_backup() would list as a normal,
    restorable backup (it only lists names starting with "AoT-backup-").
    """
    try:
        assure_path_exists(BACKUP_PATH)

        tmp_dir = None
        final_name = None
        for _attempt in range(5):
            candidate_name = backup_dir_name()
            candidate_tmp = os.path.join(BACKUP_PATH, f".{candidate_name}.partial")
            try:
                os.makedirs(candidate_tmp, exist_ok=False)
                tmp_dir = candidate_tmp
                final_name = candidate_name
                break
            except FileExistsError:
                # Same-second collision (e.g. a double-click) -- wait for
                # backup_dir_name()'s second-resolution timestamp to advance
                # rather than fail outright.
                time.sleep(1.1)
        if tmp_dir is None:
            return 1, "Could not allocate a unique backup directory name"

        try:
            if os.path.isfile(SQL_DATABASE_AOT):
                _hot_copy_sqlite(
                    SQL_DATABASE_AOT,
                    os.path.join(tmp_dir, os.path.basename(SQL_DATABASE_AOT)))
            else:
                logger.warning(f"Database file not found at {SQL_DATABASE_AOT}, skipping")

            for src_dir, subfolder in UPLOAD_DIRS:
                if not os.path.isdir(src_dir):
                    continue
                shutil.copytree(src_dir, os.path.join(tmp_dir, subfolder))
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        dest_dir = os.path.join(BACKUP_PATH, final_name)
        os.rename(tmp_dir, dest_dir)

        logger.info(f"Docker backup created: {dest_dir}")
        return 0, dest_dir
    except Exception as err:
        logger.exception("Error creating Docker backup")
        return 1, str(err)


def docker_backup_delete(dest_dir):
    """Delete a backup directory previously created by docker_backup_create()."""
    try:
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir)
        return 0, dest_dir
    except Exception as err:
        logger.exception("Error deleting Docker backup")
        return 1, str(err)


def docker_backup_restore(src_dir):
    """Restore a backup directory created by docker_backup_create().

    The daemon is stopped synchronously before ANY file is touched, so it
    can't be mid-write when the DB is swapped. Because the compose
    `restart: always` policy revives the daemon the instant it exits, it
    can race back up during the swap itself and reopen the pre-restore
    file/WAL in that window -- so it's stopped a second time right after
    the swap, forcing it to restart cleanly against the just-restored DB.
    This narrows the unsynchronized-write window from "the whole restore"
    to a few milliseconds around the swap; a fully atomic pause would need
    docker.sock access this container doesn't have.

    The DB swap itself uses copy-to-temp + os.replace() (atomic on the same
    filesystem) rather than deleting the live file first, so there is no
    window where SQL_DATABASE_AOT doesn't exist on disk.
    """
    try:
        _terminate_daemon_sync()

        backup_db = os.path.join(src_dir, os.path.basename(SQL_DATABASE_AOT))
        if os.path.isfile(backup_db):
            if os.path.isfile(SQL_DATABASE_AOT):
                pre_restore_backup = (
                    f"{SQL_DATABASE_AOT}.pre_restore_"
                    f"{time.strftime('%Y-%m-%d_%H-%M-%S')}")
                shutil.copy2(SQL_DATABASE_AOT, pre_restore_backup)
                _prune_pre_restore_backups()

            tmp_restored = f"{SQL_DATABASE_AOT}.restoring"
            shutil.copy2(backup_db, tmp_restored)
            os.replace(tmp_restored, SQL_DATABASE_AOT)

            # Stale WAL/SHM sidecar files from the pre-restore DB no longer
            # match the swapped-in main file's content; drop them so the
            # next connection starts clean instead of replaying old frames.
            for suffix in ("-wal", "-shm"):
                sidecar = SQL_DATABASE_AOT + suffix
                if os.path.isfile(sidecar):
                    os.remove(sidecar)

        for target_dir, subfolder in UPLOAD_DIRS:
            extract_dir = os.path.join(src_dir, subfolder)
            if not os.path.isdir(extract_dir):
                continue
            _replace_dir_contents(target_dir, extract_dir)

        # Force a clean restart against the just-restored DB in case
        # restart:always already revived the daemon mid-swap against the
        # pre-restore file (see docstring).
        _terminate_daemon_sync()

        # PATH_TEMPLATE_USER (generated widget_template_*.html) isn't part of
        # any Docker volume -- it's a cache derived from DB widget rows +
        # widget .py modules, not independent data. Without regenerating it,
        # a dashboard with restored widgets renders them blank instead of
        # erroring, because routes_dashboard.py only includes a widget's
        # template file if it already happens to exist on disk. Mirrors the
        # generate_widget_html() call thread_import_settings() makes after a
        # ZIP-based settings import (utils_export.py), and upgrade_post.sh's
        # post-restore step for bare-metal. Best-effort: a failure here
        # shouldn't be reported as the (already-succeeded) DB/file restore
        # failing -- it's recoverable via Settings > Regenerate Widget HTML.
        try:
            generate_widget_html()
        except Exception:
            logger.exception("Failed to regenerate widget HTML after restore")

        reload_frontend(delay_sec=2, logger=logger)

        logger.info(f"Docker backup restored from: {src_dir}")
        return 0, src_dir
    except Exception as err:
        logger.exception("Error restoring Docker backup")
        return 1, str(err)
