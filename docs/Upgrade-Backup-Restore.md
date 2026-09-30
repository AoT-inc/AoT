## Upgrading

Page\: `Manage -> Upgrade`

If you already have AoT installed, you can perform an upgrade to the latest [AoT Release](https://github.com/AoT-inc/AoT/releases) by either using the Upgrade option in the web interface (recommended) or by issuing the following command in a terminal. A log of the upgrade process is created at ``/var/log/aot/aotupgrade.log`` and is also available from the `Manage -> System Log` page.

```bash
sudo aot-commands upgrade-aot
```

## Upgrading a Docker deployment { #docker }

Page\: `Manage -> Upgrade`

A Docker deployment does not upgrade by replacing files on disk. It runs a published image, so upgrading means pulling a newer image and recreating the containers. The Upgrade page detects this and behaves differently.

**Availability comes from the container registry, not the release list.** A release tag appears on GitHub the moment it is pushed, but the image is only downloadable once the multi-architecture build finishes minutes later. So the page asks the registry which images actually exist. If it says an update is available, that update can be installed right now.

**No internet test.** The native Upgrade page first checks that the internet is reachable, using the *Internet Test IP Address / Port / Timeout* from [General Settings](Configuration-Settings.md#general-settings). The Docker Upgrade page does not run that check, so those three settings have no effect on Docker.

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
- **Update time** — checked once a day at this time, in your local timezone (the **System Timezone** set under `Manage -> System Management -> General Settings`).

When the time arrives, AoT checks the registry and, if a newer version has been published, installs it exactly as the button does. If there is nothing new it does nothing and writes a line to the log saying so.

**Pick an hour when nothing important is running.** There is no "postpone while busy" behaviour yet: at the configured time the containers are recreated whether or not an output is on.

### Data

Everything lives in Docker volumes and survives an image swap: the database, uploaded files, map overlay images, facility 3D models, backups, user scripts and measurements (InfluxDB). Rolling back to a previous version is a matter of setting ``AOT_IMAGE_TAG`` in ``docker/.env`` and recreating the containers — the updater records the last working tag there as ``AOT_IMAGE_TAG_PREV``.

## Backup-Restore

Page\: `Manage -> Backup Restore`

A backup is made to /var/AoT-backups when the system is upgraded or instructed to do so from the web interface on the ``Manage -> Backup Restore`` page.

If you need to restore a backup, this can be done on the ``Manage -> Backup Restore`` page (recommended). Find the backup
you would like restored and press the **Restore Backup** button beside it. If you're unable to access the web interface, a restore can also be initialized through the command line. Use the following command to initialize a restore. The \[backup_location\] must be the full path to the backup to be restored (e.g. "/var/AoT-backups/AoT-backup-2018-03-11\_21-19-15-5.6.4/" without quotes).

```bash
sudo aot-commands backup-restore [backup_location]
```

!!! note
    Downloading or restoring a backup from the web interface is limited to **administrators**. A backup contains the settings database with user accounts, roles and password hashes, and a restore also returns user accounts and roles to the state they were in when the backup was made. Other roles do not see the **Download Backup** and **Restore Backup** buttons.


## Backing up a Docker deployment { #docker-backup }

On Docker, `[Gear Icon] -> Backup Restore` writes to the ``aot_backups`` volume (not ``/var/AoT-backups``, which is for native installs). It is a **settings-level** backup, not a full-system one.

| | Included | Not included |
|---|---|---|
| **Docker** | Settings database (users, roles, devices, functions, dashboards), uploads (notes, notices, facility and zone photos), facility 3D models, map overlay images, user scripts | **InfluxDB measurements** (sensor history), logs, ``custom_*`` extension modules (host folders) |
| **Native** | The whole install folder except ``env`` and ``cameras`` (database, uploads, overlays, scripts) | **InfluxDB measurements** (a system service outside the install folder) |

The pre-update backup taken by the updater uses the same list.

!!! warning "A restore does not bring measurements back"
    Restoring a backup returns settings to that moment. Sensor history is left exactly as it is now. To keep history, back it up separately using one of the two methods below.

### Measurements

- **Per export (small to medium data):** `[Gear Icon] -> Export Import` exports the measurements as an InfluxDB ZIP (see [Export Import](Export-Import.md)). Simple, but slow and large on years of data.
- **Whole volumes (recommended before risky work, moves, or disk changes):** copy the Docker volumes as below. This captures **everything** including measurements.

### Copying the volumes

```bash
# 0) Find the real volume names. The prefix is the compose project name
#    (the folder name of the compose file, "docker" by default).
docker volume ls --format '{{.Name}}' | grep -E 'aot_|influxdb_'
P=docker            # <- set to the prefix you saw above
mkdir -p ~/aot-volume-backup && cd ~/aot-volume-backup

# 1) Stop everything that writes (InfluxDB must be stopped for a consistent copy).
docker compose -f /opt/AoT/docker/docker-compose.prod.yml stop

# 2) Archive each volume into its own .tgz.
for v in aot_data aot_uploads aot_model_assets aot_geo_overlays aot_user_scripts influxdb_data influxdb_config; do
  docker run --rm -v ${P}_$v:/v:ro -v "$PWD":/out alpine tar czf /out/$v.tgz -C /v .
done

# 3) Start again.
docker compose -f /opt/AoT/docker/docker-compose.prod.yml up -d
```

The copy lands in ``~/aot-volume-backup``. Move it off the machine — a backup on the same disk does not protect against disk failure.

### Restoring from the copy

```bash
cd ~/aot-volume-backup
P=docker
docker compose -f /opt/AoT/docker/docker-compose.prod.yml stop
docker compose -f /opt/AoT/docker/docker-compose.prod.yml create   # creates any missing (empty) volumes
for v in aot_data aot_uploads aot_model_assets aot_geo_overlays aot_user_scripts influxdb_data influxdb_config; do
  docker run --rm -v ${P}_$v:/v -v "$PWD":/out alpine sh -c "rm -rf /v/* /v/.[!.]* 2>/dev/null; tar xzf /out/$v.tgz -C /v"
done
docker compose -f /opt/AoT/docker/docker-compose.prod.yml up -d
```

### Test the restore before you need it

Run this on a spare machine or with a different project name (``docker compose -p restoretest ...``), never on the live stack:

1. Start the stack once so the volumes exist, then stop it.
2. Restore the ``.tgz`` files as above using that project's prefix.
3. Start it and log in with your normal account.
4. Confirm: dashboards and devices are there, a map overlay image shows, a chart shows old measurements.

!!! danger "Never run `docker compose down -v`"
    ``-v`` deletes every named volume of the stack: the database, uploads, backups (``aot_backups``) **and the measurements**, in one command and without a prompt. ``docker compose down`` (without ``-v``) and ``docker compose stop`` are safe. The backups live in a volume of the same stack, so ``down -v`` erases them too — keep a copy elsewhere.
