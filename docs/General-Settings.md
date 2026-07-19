# General Settings Manual

The General Settings page allows for system-wide configuration of the AoT (Agriculture of Things) environment.

Page Location: `[Manage] -> System Administration -> General Settings`

## User Interface & Language

| Setting | Description |
| :--- | :--- |
| **Language** | Set the language displayed in the web user interface. |
| **Force HTTPS** | Redirects all HTTP requests to HTTPS for security. |
| **Hide Status Notifications** | Options to hide Success, Info, or Warning notification boxes. |

## TimeSeries Database (TSDB)

AoT stores all measurement data in InfluxDB. 

- **InfluxDB 1.x**: Supported on 32-bit and 64-bit systems.
- **InfluxDB 2.x**: Supported on 64-bit systems only.
- **Docker note**: When running in Docker, the hostname should be set to `aot_influxdb`.

| Setting | Description |
| :--- | :--- |
| **Retention Policy** | Defines how long data is kept. Default is 'autogen' (v1) or 'infinite' (v2). |
| **Database/Bucket Name** | The target database for measurement storage. Default is `aot_db`. |

## Energy & Power Management

Configuring energy settings allows AoT to calculate electrical costs and protect hardware from overcurrent.

| Setting | Description |
| :--- | :--- |
| **Max Current (A)** | The safety limit for total current. If a new output would push the total current above this value, it will be blocked. |
| **Voltage (V)** | The AC voltage of the system (typically 120V or 240V). |
| **Cost per kWh** | Used to generate usage/cost reports. |

## Controller Sampling Periods

Each controller (Input, Output, Function) runs in a loop. The sampling period determines how often the controller checks for changes.

- **Fastest Response**: A 1-second period means the system reacts to changes within at most 1 second.
- **CPU Optimization**: Increasing the period reduces CPU load, which is recommended for lower-powered devices like the Pi Zero.

## Update & Maintenance

| Setting | Description |
| :--- | :--- |
| **Check for Updates** | Automatically checks for AoT system updates every 2 days. |
| **Internet Test IP** | Used to verify connectivity before attempting updates. |

## Diagnostics

The Diagnostics menu provides tools to reset specific parts of the system without a full reinstall.

> [!WARNING]
> Some diagnostic tools, such as "Delete Settings Database", will permanently remove all users and configurations. Use with caution.
