Page\: `More -> Export Import`

Measurements within a selected date/time range can be exported as a CSV along with their timestamps.

Additionally, the entire measurement database (influxdb) can be exported as a ZIP archive backup. This ZIP file can be imported back into any AoT system to restore the measurements.

!!! note
    Measurements are associated with specific IDs that are linked to the inputs/outputs/etc. of a particular system. If you import measurements without importing the associated inputs/outputs/etc., you will not be able to view these measurements (for example, in a dashboard graph). Therefore, it is recommended to export the measurements and settings at the same time, so that the devices associated with the measurements are available on the importing system when you later import them.

!!! note
    Importing measurement data does not delete existing data; it is added to the current measurement data.

The AoT settings can be exported as a ZIP file containing the AoT settings database (sqlite) as well as custom inputs, outputs, functions, and widgets. This ZIP file can be used to restore to another AoT installation, provided the AoT and database versions are equal to or lower than those of the importing system. Additionally, it can only be imported into a system with the same major version number (the first number in the version format x.x.x). For example, you can export settings from AoT 8.5.0 and import them into AoT 8.8.0, but you cannot import them into AoT 8.2.0 (an earlier version of the same major version number), 7.0.0 (not the same major version number), or 9.0.0 (not the same major version number).

!!! warning
    Importing overwrites (that is, deletes) the current settings and custom controller data. It is recommended to create an AoT backup before attempting an import.