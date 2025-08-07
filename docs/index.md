description: Documentation for AoT, an open-source environmental monitoring and control system.

## AoT Environmental Monitoring and Control System

AoT is an open-source software designed to run on [Raspberry Pi](https://en.wikipedia.org/wiki/Raspberry_Pi) and other single-board computers (SBCs). It combines inputs and outputs in interesting ways to sense and manipulate the environment.

### Information

For details about AoT's features, projects using it, screenshots, and more, refer to the [README](https://github.com/aot-inc/AoT#uses).

### Prerequisites

*   Single-board computer (Recommended: [Raspberry Pi](https://www.raspberrypi.org/), any version: Zero, 1, 2, 3, or 4)
*   Debian-based operating system
*   Internet connection

### Installation

After booting and logging in, run the following command to start the AoT installation:

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

> ⚠️ The above command will automatically install AoT and its dependencies.  
> Ensure you trust the source before executing remote scripts.

Once the installation is complete, enter the SBC's IP address in a web browser to complete the setup:

```
https://<your-device-ip>
```

For example, if the SBC's IP is `192.168.0.101`, enter:
```
https://192.168.0.101
```

### Support

*   [AoT on GitHub](https://github.com/aot-inc/AoT)
*   [AoT Wiki](https://github.com/aot-inc/AoT/wiki)
*   [AoT API](https://aot-inc.github.io/AoT/aot-api.html)

### Donations

Become a sponsor: [github.com/sponsors/aot-inc](https://github.com/sponsors/aot-inc)

---

### Based Project

AoT is a fork and modification of the open-source project [Mycodo](https://github.com/kizniche/Mycodo) developed by Kyle Gabriel.  
This project is distributed under the [MIT License](https://github.com/aot-inc/AoT/blob/main/LICENSE).