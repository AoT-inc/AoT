# coding=utf-8
"""Command-line entry point for the Docker-native backup in docker_backup.py.

The updater sidecar (docker/updater/aot_docker_update.sh) has to snapshot the
data *before* it swaps the image, and it can only reach the data the same way
anything else does -- by running inside a container that mounts the volumes:

    docker exec <app container> python -m aot.utils.docker_backup_cli --create

It prints the backup directory on stdout (and nothing else on success), so the
caller can capture it with a plain command substitution and hand it back to
--restore during a rollback. Everything else goes to stderr.

Rollback restores the DB *and* the uploaded files, which is the point: after a
migration has run, putting the old image back without putting the old schema
back leaves old code reading a future schema.
"""
import argparse
import logging
import sys


def _run(args):
    # Imported lazily so `--help` works even if the app config cannot load.
    from aot.utils.docker_backup import (docker_backup_create,
                                         docker_backup_restore,
                                         docker_can_perform_backup)

    # aot_client.py runs `logging.basicConfig(stream=sys.stdout, ...)` at
    # import time, and docker_backup pulls it in transitively (via
    # service_control). That is fine for the app itself (container logs go to
    # stdout on purpose) but it is exactly wrong here: this CLI's stdout is a
    # value the caller parses (a path), not a log stream. Force it back to
    # stderr for this process only -- force=True re-points the already
    # installed handler rather than adding a second one.
    logging.basicConfig(stream=sys.stderr, force=True)

    if args.estimate:
        size, free_before, free_after = docker_can_perform_backup()
        # Same floor the upgrade page uses (routes_admin.not_enough_space_upgrade):
        # under 50 MB left after the copy, refuse rather than fill the volume.
        ok = 1 if free_after / 1000000 >= 50 else 0
        print(f"{int(size)} {int(free_before)} {int(free_after)} {ok}")
        return 0

    if args.create:
        status, result = docker_backup_create()
        if status:
            sys.stderr.write(f"backup failed: {result}\n")
            return 1
        print(result)
        return 0

    if args.restore:
        status, result = docker_backup_restore(args.restore)
        if status:
            sys.stderr.write(f"restore failed: {result}\n")
            return 1
        sys.stderr.write(f"restored from {result}\n")
        return 0

    sys.stderr.write("nothing to do; pass --create, --restore or --estimate\n")
    return 2


def main():
    parser = argparse.ArgumentParser(
        description="Create or restore a Docker-native AoT backup.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--create', action='store_true',
                       help='Snapshot the data. Prints the backup directory.')
    group.add_argument('--restore', metavar='DIR',
                       help='Restore a backup directory created by --create.')
    group.add_argument('--estimate', action='store_true',
                       help='Print "<bytes> <free_before> <free_after> <ok>".')
    args = parser.parse_args()

    try:
        return _run(args)
    except Exception as err:
        sys.stderr.write(f"error: {err}\n")
        return 1


if __name__ == '__main__':
    sys.exit(main())
