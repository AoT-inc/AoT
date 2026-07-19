## Error Codes

AoT can return a number of errors. Below is information about the numbered errors that may occur and how to diagnose the problem.

### Error 100

> Cannot set the type ***Y*** of value '***X***'. The value must be a float or a string representing a float.

 - Examples:
  - Cannot set the type ***str*** of value '***1.33.4***'.
  - Cannot set the type ***str*** of value '***Output: 1.2***'.
  - Cannot set the type ***list*** of value '***[1.3, 2.4]***'.
  - Cannot set the type ***dict*** of value '***{"output": 1.99}***'.
  - Cannot set the type ***Nonetype*** of value '***None***'.

This error occurs when the value you are trying to store in the InfluxDB time-series database is not a numeric value (an integer or a decimal/float), nor a string representing a float (for example, "5", "3.14"). The most common reason this error occurs is that an Input returns no measurement when reading a sensor, or returns data that does not represent a numeric value, indicating that the sensor is not working. This can happen for many reasons, such as faulty wiring, insufficient power supply, a faulty sensor, the I2C bus not being enabled, or incorrect settings. Often a sensor fails during Input initialization when the daemon starts, or is not configured correctly, which can cause this error to occur on every measurement cycle. You should review the daemon log (`Manage -> System Logs`) back to the point when the daemon started to check for initialization errors. Enabling Log Level: Debug in the controller settings can provide additional debugging log lines (if available), which may be useful for troubleshooting.

### Error 101

> ***X*** is not set up properly.

 - Examples:
  - Device is not set up
  - Output channel ***Y*** is not set up

This error occurs when a controller (Input/Output/Function, etc.) failed to properly initialize a device or channel when it started, and now an attempt is being made to access the uninitialized device or channel. In the case of an Input, a problem may occur while loading the 3rd-party library used to communicate with the sensor. If there is an error loading the library, the sensor cannot be communicated with. You should review the daemon log (`Manage -> System Logs`) to check for related errors that occurred when the controller was first activated. Try disabling and then re-enabling the device to check for initialization errors again. Enabling Log Level: Debug in the controller settings can provide additional debugging log lines (if available), which may be useful for troubleshooting.