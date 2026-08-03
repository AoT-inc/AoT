#!/bin/bash

exec 2>&1

if [ "$EUID" -ne 0 ] ; then
    printf "Must be run as root.\n"
    exit 1
fi

INSTALL_DIRECTORY=$( cd -P /var/aot-root/.. && pwd -P )

function error_found {
    date
    printf "\n#### ERROR ####"
    printf "\nThere was an error detected while creating the backup. Please review the log at /var/log/aot/aotbackup.log"
    exit 1
}

CURRENT_VERSION=$("${INSTALL_DIRECTORY}"/AoT/env/bin/python "${INSTALL_DIRECTORY}"/AoT/aot/utils/github_release_info.py -c 2>&1)
NOW=$(date +"%Y-%m-%d_%H-%M-%S")
TMP_DIR="/var/tmp/AoT-backup-${NOW}-${CURRENT_VERSION}"
BACKUP_DIR="/var/AoT-backups/AoT-backup-${NOW}-${CURRENT_VERSION}"

printf "\n#### Create backup initiated %s ####\n" "${NOW}"

mkdir -p /var/AoT-backups

# node_modules/__pycache__ are build byproducts, not part of the state this
# backup exists to restore: node_modules only feeds the notes-widget vite build
# (whose output is already committed under static/js/notes/) and __pycache__ is
# regenerated from the .py files beside it. Together they were ~58% of every
# backup (192 MB of 333 MB on aot-005). Excluded here AND in can_perform_backup()
# (aot/utils/system_pi.py) — the two must agree or the pre-upgrade free-space
# check overestimates and can refuse an upgrade that would in fact fit.
printf "Backing up current AoT from %s/AoT to %s..." "${INSTALL_DIRECTORY}" "${TMP_DIR}"
if ! rsync -avq --exclude=cameras --exclude=env --exclude=.upgrade \
        --exclude=node_modules --exclude=__pycache__ \
        "${INSTALL_DIRECTORY}"/AoT "${TMP_DIR}" ; then
    printf "Failed: Error while trying to back up current AoT install from %s/AoT to %s.\n" "${INSTALL_DIRECTORY}" "${BACKUP_DIR}"
    error_found
fi
printf "Done.\n"

printf "Moving %s/AoT to %s..." "${TMP_DIR}" "${BACKUP_DIR}"
if ! mv "${TMP_DIR}"/AoT "${BACKUP_DIR}" ; then
    printf "Failed: Error while trying to move %s/AoT to %s.\n" "${TMP_DIR}" "${BACKUP_DIR}"
    error_found
fi
printf "Done.\n"

date
printf "Backup completed successfully without errors.\n"
