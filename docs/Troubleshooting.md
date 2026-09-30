!!! note
    Except for the section titled "Troubleshooting on Docker", this page describes the native (direct) install. On Docker, use that section first: there is no `/opt/AoT` on the host, and there are no `aotflask` services or `upgrade_post.sh` to run.

## Cannot Access the Web UI Following an Upgrade

There are many reasons why the web UI would be inaccessible following an upgrade. Bugs are also continually fixed as they are discovered. Therefore, do not rely on old GitHub Issues or forum posts that have a solution for a similar effect, since the cause of the effect can be something completely different. The first thing that should be done is to review the upgrade log (/var/log/aot/aotupgrade.log) for any errors. Next, you can attempt to rerun the upgrade by issuing the following command:

```bash
sudo /opt/AoT/aot/scripts/upgrade_post.sh
```

## Daemon Not Running

- Look at the brand (logo) area at the top left of the navigation bar. It is tinted only when something is wrong: no tint means the daemon and the web app are both fine, a **red** tint means the daemon is down, and a **gray** tint means the browser cannot reach the web app at all. The page asks `/daemonactive` every 60 seconds, so the tint can lag by up to a minute after a change.
- Determine if the Daemon is Running: Execute `ps aux | grep aot_daemon.py` in a terminal and look for an entry to be returned.
- Check the Logs: From the `Manage -> System Log` page or /var/log/aot/, check the daemon log for any errors. If the issue began after an upgrade, also check the upgrade log for indications of an issue.
- If a solution could not be found after investigating the above suggestions, search the GitHub issues for any open issues or the forum for any recent issues.

## Incorrect Database Version

- Check the `Manage -> System Information` page.
- If the "Database Version" is shown in normal text, it is the correct version. An incorrect version is shown in red, followed by "Incorrect Version. Should be" and the version it should be.
- An incorrect database version means the version stored in the AoT settings database (`/opt/AoT/databases/aot.db`) is not correct for the latest version of AoT, determined in the AoT config file (`/opt/AoT/aot/config.py`).
- This can be caused by an error in the upgrade process from an older database version to a newer version, or from a database that did not upgrade during the AoT upgrade process.
- Check the Upgrade Log for any issues that may have occurred. The log is located at `/var/log/aot/aotupgrade.log` but may also be accessed from the web UI (if you're able to): open `Manage -> System Log` and choose **AoT upgrade** in the **Log** list.
- Sometimes issues may not immediately present themselves. It is not uncommon to be experiencing a database issue that was actually introduced several AoT versions ago, before the latest upgrade.
- Because of the nature of how many versions the database can be in, correcting a database issue may be very difficult.

It may be much easier to delete your database and start fresh without any configuration. Use the following commands to rename your database and restart the web UI. If both commands are successful, refresh your web UI page in your browser in order to generate a new database and create a new Admin user.

```bash
mv /opt/AoT/databases/aot.db /opt/AoT/databases/aot.db.backup
sudo service aotflask restart
```

## Restoring a Backup Without the UI

If the web UI is inaccessible, because of an error, for example, you can restore a backup from the command line. See [Backup and Restore](https://github.com/AoT-inc/AoT/wiki/Backup-and-Restore) for more information.

## More on Diagnosing issues

Check out the [Diagnosing Issues](https://github.com/AoT-inc/AoT/wiki/Diagnosing-Issues) for more information about diagnosing issues.

## Troubleshooting on Docker { #docker }

A Docker install has nothing to inspect on the host except Docker itself. Run these from the checkout directory (the one containing `docker/`).

**Are the containers up?**

```bash
docker compose -f docker/docker-compose.prod.yml ps
```

Four services matter: `aot-app` (web UI), `aot_daemon` (control daemon), `aot_mcp` (external MCP server), and `influxdb` (measurements). A service that is restarting or exited is the place to look. The brand tint described above maps to them: red means `aot_daemon` is down, gray means `aot-app` cannot be reached.

**Read the logs**

```bash
docker compose -f docker/docker-compose.prod.yml logs --tail 200 aot-app
docker compose -f docker/docker-compose.prod.yml logs --tail 200 aot_daemon
```

Add `-f` to follow. The same logs are also under `Manage -> System Log` when the web UI is reachable.

**Web UI does not open: port conflict.** If another program already uses the host port, `aot-app` fails to start with "port is already allocated". Set a free port in `docker/.env` and recreate:

```bash
# docker/.env
AOT_PORT=8090
docker compose -f docker/docker-compose.prod.yml up -d
```

Then browse to `http://<host IP address>:8090`.

**Wrong architecture.** Official images exist only for `linux/amd64` and `linux/arm64`. A 32-bit Raspberry Pi OS (`armhf`) cannot run them; use the direct install there. Check with `uname -m` (`x86_64` and `aarch64` are fine).

**Where the data lives.** The database, uploads, backups, logs, and user scripts are in Docker named volumes (`docker volume ls`), not in the checkout. They survive `docker compose down`, image updates, and container recreation.

!!! danger "Never run `docker compose down -v`"
    The `-v` flag deletes the named volumes, and with them the database, uploaded files, backups, and the InfluxDB measurement history. There is no undo. To stop the stack use `docker compose -f docker/docker-compose.prod.yml down` (no `-v`); to restart one service use `docker compose -f docker/docker-compose.prod.yml restart aot_daemon`. Take a backup first (see [Upgrade/Backup/Restore](Upgrade-Backup-Restore.md)) before any experiment with volumes.

**After an upgrade.** Rolling back is a matter of setting `AOT_IMAGE_TAG` in `docker/.env` to the previous version and running `up -d` again. See [Upgrade/Backup/Restore](Upgrade-Backup-Restore.md#docker).
