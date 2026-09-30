Page\: `Additional Features -> Import Export`

Measurements within a selected date/time range can be exported as a CSV along with their timestamps.

Additionally, the entire measurement database (influxdb) can be exported as a ZIP archive backup. The ZIP holds InfluxDB backup files made with `influxd backup -portable` (InfluxDB 1.x) or `influx backup` (InfluxDB 2.x). AoT has no screen for importing this ZIP; to restore the measurements, use InfluxDB's own restore tools as described in the InfluxDB documentation.

!!! note
    Measurements are associated with specific IDs that are linked to the inputs/outputs/etc. of a particular system. If you restore measurements without importing the associated inputs/outputs/etc., you will not be able to view these measurements (for example, in a dashboard graph). Therefore, it is recommended to export the measurements and settings at the same time, so that the devices associated with the measurements are available on the target system when you later restore them.

The AoT settings can be exported with **Export Settings** as a ZIP file containing the AoT settings database (sqlite) as well as custom inputs, outputs, functions, widgets, and uploaded files. This ZIP file can be restored to another AoT installation with **Import Settings**, provided the importing system runs the same or a newer AoT version. The import reads the AoT version from the file name (`AoT_<AoT version>_Settings_<database version>_<host>_<date>_<time>.zip`), so keep the name as it was exported, and it rejects a file from a newer AoT version than the one running. The imported database is then upgraded to the current version. For example, you can export settings from AoT 8.5.0 and import them into AoT 8.8.0 or 9.0.0, but you cannot import them into AoT 8.2.0 (an older version).

!!! warning
    Importing overwrites (that is, deletes) the current settings and custom controller data. It is recommended to create an AoT backup before attempting an import.

!!! note
    Only **administrators** can export or import settings (both in the web interface and through the API). The settings database holds user accounts, roles and password hashes, so an export by anyone else would leak account data and an import could be used to change their own permissions. Other roles do not see the settings export and import sections. Exporting measurements is unaffected.
