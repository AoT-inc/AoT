Page: `Setup -> Input`

For a complete list of supported input devices, see [Supported Inputs](Supported-Inputs.md).

Inputs, such as sensors, ADC signals, or the responses of commands, measure conditions in the environment or at other locations and store them in the time-series database (InfluxDB). This database provides the measurements needed to operate [dashboard widgets](Data-Viewing.md#dashboard), [Functions](Functions.md), and other parts of AoT. Add, configure, and activate inputs to record measurements to the database and make them available throughout AoT.

### Custom Inputs

See the [Building a Custom Input Module](https://github.com/AoT-inc/AoT/wiki/Building-a-Custom-Input-Module) Wiki page.

AoT has a custom input import system that lets you create custom inputs and make them available for use in the AoT system. Custom inputs can be uploaded and imported on the `[Gear Icon] -> Configure -> Custom Inputs` page. Once imported, they become available on the `Setup -> Input` page.

If you have developed a working input module, please consider [creating a new GitHub issue](https://github.com/AoT-inc/AoT/issues/new?assignees=&labels=&template=feature-request.md&title=New%20Module) or a pull request. Your module may be included in the built-in set.

To see examples of the correct format, open the built-in modules in the directory [AoT/aot/inputs](https://github.com/AoT-inc/AoT/tree/master/aot/inputs/).

Additionally, custom input examples can be found in the directory [AoT/aot/inputs/examples](https://github.com/AoT-inc/AoT/tree/master/aot/inputs/examples).

Another GitHub repository dedicated to custom modules that are not included in the built-in set can be found at [aot-inc/AoT-custom](https://github.com/AoT-inc/AoT-custom).

### Input Commands

Input commands are functions within an input module that can be executed from the web UI. These are useful for tasks such as calibration or other functions specific to an input. By default, there is at least one action, "Acquire Measurements Now," which causes the input to acquire a measurement before the next period elapses.

!!! note
    Actions can only be executed while the input is active.

### Input Actions

During each period, the input acquires a measurement and stores it in the time-series database. After the measurement is acquired, one or more [Actions](Actions.md) can be executed to extend the input's functionality. For example, an MQTT publish action can be used to publish the measurement to an MQTT server.

### Input Options

For more information about the input options, refer to the table below.

| Setting                   | Description                                                                                                                                                                                            |
|---------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Activate                  | After a sensor is configured correctly, activating it begins acquiring measurements from the sensor. Any activated Conditional Functions also begin operating.                                        |
| Deactivate                | Deactivating stops the acquisition of measurements from the sensor. Any associated Conditional Functions also stop operating.                                                                         |
| Save                      | Saves the current configuration entered in the input boxes for a particular sensor.                                                                                                                   |
| Delete                    | Deletes a particular sensor.                                                                                                                                                                          |
| Acquire Measurements Now  | Forces the input to take a measurement and store it in the database.                                                                                                                                  |
| Up/Down                   | Moves a particular sensor up or down in the displayed order.                                                                                                                                          |
| Power Output              | Selects the output that powers the sensor. This enables power cycling—turning the power off and back on to resolve issues—when the sensor returns three consecutive errors. A transistor may also be used instead of a relay. |
| Location                  | Depending on the sensor in use, you must select a serial number, GPIO pin, I2C address, and so on.                                                                                                    |
| I2C Bus                   | The bus used to communicate with the I2C address.                                                                                                                                                    |
| Period (seconds)          | The time to wait before measuring the sensor again after it has been read successfully and a database entry has been created.                                                                         |
| Measurement Unit          | Selects the unit in which to store the measurement (applies only to selectable measurements).                                                                                                        |
| Pre-Output                | If an output must be activated before acquiring a measurement, specify the output number to be activated.                                                                                             |
| Pre-Output Duration (seconds) | The time the pre-output runs before a sensor measurement is taken.                                                                                                                                |
| Pre-Output During Measurement | If enabled, the pre-output remains on while the measurement is being acquired. If disabled, the pre-output turns off just before the measurement is acquired.                                      |
| Command                   | The return value of a Linux command (executed as the user 'root') becomes the measurement.                                                                                                            |
| Command Measurement       | The condition measured by the Linux command (e.g., temperature, humidity, etc.).                                                                                                                     |
| Command Unit              | The unit of the condition measured by the Linux command.                                                                                                                                             |

The table above includes only some of the options; refer to the original documentation for the complete list.
