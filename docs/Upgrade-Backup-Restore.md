## Upgrading

Page\: `[Gear Icon] -> Upgrade`

If you already have AoT installed, you can perform an upgrade to the latest [AoT Release](https://github.com/aot-inc/AoT/releases) by either using the Upgrade option in the web interface (recommended) or by issuing the following command in a terminal. A log of the upgrade process is created at ``/var/log/aot/aotupgrade.log`` and is also available from the `[Gear Icon] -> AoT Logs` page.

```bash
sudo aot-commands upgrade-aot
```

## Backup-Restore

Page\: `[Gear Icon] -> Backup Restore`

A backup is made to /var/AoT-backups when the system is upgraded or instructed to do so from the web interface on the ``[Gear Icon] -> Backup Restore`` page.

If you need to restore a backup, this can be done on the ``[Gear Icon] -> Backup  Restore`` page (recommended). Find the backup
you would like restored and press the Restore button beside it. If you're unable to access the web interface, a restore can also be initialized through the command line. Use the following command to initialize a restore. The \[backup_location\] must be the full path to the backup to be restored (e.g. "/var/AoT-backups/AoT-backup-2018-03-11\_21-19-15-5.6.4/" without quotes).

```bash
sudo aot-commands backup-restore [backup_location]
```
