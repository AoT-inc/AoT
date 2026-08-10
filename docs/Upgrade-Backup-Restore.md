## Upgrading

Page\: `[Gear Icon] -> Upgrade`

If you already have AoT installed, you can perform an upgrade to the latest [AoT Release](https://github.com/AoT-inc/AoT/releases) by either using the Upgrade option in the web interface (recommended) or by issuing the following command in a terminal. A log of the upgrade process is created at ``/var/log/aot/aotupgrade.log`` and is also available from the `[Gear Icon] -> AoT Logs` page.

```bash
sudo aot-commands upgrade-aot
```

## Upgrading a Docker deployment { #docker }

Page\: `[Gear Icon] -> Upgrade`

A Docker deployment does not upgrade by replacing files on disk. It runs a published image, so upgrading means pulling a newer image and recreating the containers. The Upgrade page detects this and behaves differently.

**Availability comes from the container registry, not the release list.** A release tag appears on GitHub the moment it is pushed, but the image is only downloadable once the multi-architecture build finishes minutes later. So the page asks the registry which images actually exist. If it says an update is available, that update can be installed right now.

### The updater service (optional)

One-click and automatic updates need a small extra service. Without it the Upgrade page still shows accurate status, but you apply the update yourself on the host:

```bash
docker compose -f docker/docker-compose.prod.yml pull
docker compose -f docker/docker-compose.prod.yml up -d
```

The application cannot install its own update: recreating the containers would kill the very process running the command, halfway through. That is why the work is done by a separate service.

To enable it, add two values to ``docker/.env``:

```bash
AOT_PROJECT_DIR=/opt/AoT                  # absolute path of this checkout
AOT_HEALTH_KEY=$(openssl rand -hex 24)    # lets the updater verify the new build
```

then start the stack with the updater overlay:

```bash
docker compose -f docker/docker-compose.prod.yml \
               -f docker/docker-compose.updater.yml up -d
```

!!! warning "This service can control Docker on the host"
    The updater holds the Docker socket, which is equivalent to root on the host. It is deliberately tiny and only ever pulls the official AoT image, but enable it only if you accept that. If you would rather not run a privileged container, the same work can be done by a systemd timer on the host — see ``install/aot-docker-update.service``.

### What happens during an update

1. A backup of the database and uploaded files is taken first.
2. The new image is downloaded.
3. The daemon is stopped gracefully, so it can switch outputs to their shutdown state before it goes.
4. The containers are recreated on the new image and the schema is migrated automatically.
5. The new version has to report that it is serving *and* that the migration landed. Only then is the update considered done.
6. If it does not come up, the previous version is restored automatically — including the database, if the migration had already run. Restoring the image alone would leave old code running against a newer schema.

The Upgrade page shows progress live, and the result of the last attempt afterwards.

!!! note "Control pauses during the update"
    Outputs are not controlled while the containers restart — usually a few minutes. Anything running at that moment (irrigation, supplemental lighting, a sequence) stops.

### Automatic updates

With the updater service running, the Upgrade page offers:

- **Install updates automatically** — off by default.
- **Update time** — checked once a day at this time, in your local timezone (the one set under `[Gear Icon] -> Configuration`).

When the time arrives, AoT checks the registry and, if a newer version has been published, installs it exactly as the button does. If there is nothing new it does nothing and writes a line to the log saying so.

**Pick an hour when nothing important is running.** There is no "postpone while busy" behaviour yet: at the configured time the containers are recreated whether or not an output is on.

### Data

Everything lives in Docker volumes and survives an image swap: the database, uploaded files, facility 3D models, backups and user scripts. Rolling back to a previous version is a matter of setting ``AOT_IMAGE_TAG`` in ``docker/.env`` and recreating the containers — the updater records the last working tag there as ``AOT_IMAGE_TAG_PREV``.

## Backup-Restore

Page\: `[Gear Icon] -> Backup Restore`

A backup is made to /var/AoT-backups when the system is upgraded or instructed to do so from the web interface on the ``[Gear Icon] -> Backup Restore`` page.

If you need to restore a backup, this can be done on the ``[Gear Icon] -> Backup  Restore`` page (recommended). Find the backup
you would like restored and press the Restore button beside it. If you're unable to access the web interface, a restore can also be initialized through the command line. Use the following command to initialize a restore. The \[backup_location\] must be the full path to the backup to be restored (e.g. "/var/AoT-backups/AoT-backup-2018-03-11\_21-19-15-5.6.4/" without quotes).

```bash
sudo aot-commands backup-restore [backup_location]
```
