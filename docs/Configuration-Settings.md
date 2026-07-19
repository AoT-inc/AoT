Page\: `[Admin] -> Configure`

The Configure menu is accessed by clicking Admin in the top right and selecting the "Configure" link. It is the area where you can set up a variety of system-wide settings.

## General Settings { #general-settings }

Page\: `[Admin] -> System Configuration -> General Settings`

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Language</td>
<td>Sets the language displayed in the web user interface.</td>
</tr>
<tr>
<td>Force HTTPS</td>
<td>Requires the web browser to use SSL/HTTPS. <a href="http://">http://</a> requests are redirected to <a href="https://">https://</a>.</td>
</tr>
<tr>
<td>Hide Success Alerts</td>
<td>Hides all success alert boxes shown at the top of the page.</td>
</tr>
<tr>
<td>Hide Info Alerts</td>
<td>Hides all info alert boxes shown at the top of the page.</td>
</tr>
<tr>
<td>Hide Warning Alerts</td>
<td>Hides all warning alert boxes shown at the top of the page.</td>
</tr>
<tr>
<td>Opt out of Statistics</td>
<td>Disables the sending of anonymous usage statistics. This feature helps with development, so please keep it enabled if possible.</td>
</tr>
</tbody>
</table>

## Time Series Database Settings

Page\: `[Admin] -> System Configuration -> General Settings`

Measurements are stored in a time series database. The options currently available in AoT are InfluxDB 1.x and InfluxDB 2.x. InfluxDB 1.x works on both 32-bit and 64-bit operating systems, but 2.x only works on 64-bit operating systems. Therefore, if you are using a 32-bit operating system, you must use InfluxDB 1.x. During AoT installation, you can choose InfluxDB 1.x, 2.x, or no installation. If InfluxDB is not installed, you must specify a separate installation address and credentials so that AoT can store and retrieve measurements.

If installing with Docker, after installation you must change the host name to "aot_influxdb" in order to connect to the InfluxDB Docker container.

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Database</td>
<td>Select the influxdb version to use.</td>
</tr>
<tr>
<td>Retention Policy</td>
<td>Select the retention policy. The default is "autogen" for v1.x and "infinite" for v2.x.</td>
</tr>
<tr>
<td>Host Name</td>
<td>The host name used to connect to the time series server. The default is "localhost".</td>
</tr>
<tr>
<td>Port</td>
<td>The port of the time series database. The default is 8086.</td>
</tr>
<tr>
<td>Database Name</td>
<td>The name of the database (v1.x) or bucket (v2.x) that AoT stores to and retrieves from. The default is "aot_db".</td>
</tr>
<tr>
<td>User Name</td>
<td>The user name for accessing the database (if authentication is required). The default is "aot".</td>
</tr>
<tr>
<td>Password</td>
<td>The password for accessing the database (if authentication is required).</td>
</tr>
</tbody>
</table>

## Dashboard Settings

Page\: `[Admin] -> System Configuration -> General Settings`

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Grid Cell Height (px)</td>
<td>Sets the height of each widget cell in pixels.</td>
</tr>
</tbody>
</table>

## Upgrade Settings

Page\: `[Admin] -> System Configuration -> General Settings`

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Internet Test IP Address</td>
<td>The IP address used to test whether an internet connection is active.</td>
</tr>
<tr>
<td>Internet Test Port</td>
<td>The port used to test whether an internet connection is active.</td>
</tr>
<tr>
<td>Internet Test Timeout</td>
<td>The timeout duration used when testing the internet connection.</td>
</tr>
<tr>
<td>Check for Updates</td>
<td>Automatically checks for updates every 2 days and displays a notification through the web interface. If a new update is available, the Configure (Admin) and Upgrade menus are shown in red.</td>
</tr>
</tbody>
</table>

## Energy Usage Settings

Page\: `[Admin] -> System Configuration -> General Settings`

To calculate accurate energy usage statistics, you need to know a few characteristics of your electrical system. These variables should describe the characteristics of the electrical system that operates electrical devices through relays.

!!! note
    If you are not using a current sensor, you must set the accurate current usage for each output in order to accurately calculate energy usage (see [Output Settings](Outputs.md)).

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Max Amps (A)</td>
<td>Sets the maximum current allowed at one time. If turning an output on would cause the total of the active devices to exceed this value, the output cannot be turned on, to prevent damage.</td>
</tr>
<tr>
<td>Voltage (V)</td>
<td>The AC voltage that is switched through the output. Typically 120 or 240.</td>
</tr>
<tr>
<td>Cost per kWh</td>
<td>Enter the electricity cost per kWh.</td>
</tr>
<tr>
<td>Currency Unit</td>
<td>The currency unit used for the electricity cost.</td>
</tr>
<tr>
<td>Day of Month for Meter Reading</td>
<td>The day (1–30) on which the electricity meter is checked. This should match the electricity billing date.</td>
</tr>
<tr>
<td>Generate Usage/Cost Report</td>
<td>Defines when the energy usage report is generated. Currently only output time-based calculation is supported.</td>
</tr>
<tr>
<td>Report Generation Frequency</td>
<td>Sets the frequency at which the usage/cost report is automatically generated.</td>
</tr>
<tr>
<td>Report Generation Day of Week/Month</td>
<td>Sets the day of the week (Daily: 1–7, Monday=1) or the day of the month (1–28) on which the report is generated.</td>
</tr>
<tr>
<td>Report Generation Hour</td>
<td>Sets the hour at which the report is generated, from 0 to 23.</td>
</tr>
</tbody>
</table>

## Controller Sampling Period Settings { #controller-settings }
 
Page\: `[Admin] -> System Configuration -> General Settings`
 
Each controller for Inputs, Outputs, and Functions operates periodically. The fastest speed at which each controller can respond is determined by that controller's sampling period. The controller pauses its loop for the duration of the period. For example, if the Output controller's sampling period is set to 1 second, an output on/off command will react within at most 1 second.
 
<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Max Amps</td>
<td>Sets the maximum current (A) allowed at one time. If a command to turn an output on would, combined with the devices currently on, exceed this value, the output will not turn on, to prevent damage.</td>
</tr>
<tr>
<td>Voltage</td>
<td>The AC voltage that is switched through the output. Typically 120 or 240.</td>
</tr>
<tr>
<td>Cost per kWh</td>
<td>Enter the electricity cost per kWh.</td>
</tr>
<tr>
<td>Currency Unit</td>
<td>The currency unit used when paying the electricity cost.</td>
</tr>
<tr>
<td>Day of Month for Meter Reading</td>
<td>The day (1–30) on which the electricity meter is checked. This should match the electricity billing date.</td>
</tr>
<tr>
<td>Generate Usage/Cost Report</td>
<td>Defines when the energy usage report is generated. Currently only output time-based calculation is supported.</td>
</tr>
</tbody>
</table>

## Input Settings { #input-settings }

Page\: `[Admin] -> System Configuration -> Custom Inputs`

Input modules can be imported into AoT for use. These modules must follow a specific format. For details, see [Custom Inputs](Inputs.md#custom-inputs).

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Import Input Module</td>
<td>Select the input module file, then click this button to start the import.</td>
</tr>
</tbody>
</table>

## Output Settings { #output-settings }

Page\: `[Admin] -> System Configuration -> Custom Outputs`

Output modules can be imported into AoT for use. These modules must follow a specific format. For details, see [Custom Outputs](Outputs.md#custom-outputs).

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Import Output Module</td>
<td>Select the output module file, then click this button to start the import.</td>
</tr>
</tbody>
</table>

## Function Settings

Page\: `[Admin] -> System Configuration -> Custom Functions`

Function modules can be imported into AoT for use. These modules must follow a specific format. For details, see [Custom Functions](Functions.md#custom-functions).

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Import Function Module</td>
<td>Select the function module file, then click this button to start the import.</td>
</tr>
</tbody>
</table>

## Action Settings { #action-settings }

Page\: `[Admin] -> System Configuration -> Custom Actions`

Action modules can be imported into AoT for use. These modules must follow a specific format. For details, see [Custom Actions](Actions.md#custom-actions).

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Import Action Module</td>
<td>Select the action module file, then click this button to start the import.</td>
</tr>
</tbody>
</table>

## Widget Settings { #widget-settings }

Page\: `[Admin] -> System Configuration -> Custom Widgets`

Widget modules can be imported into AoT for use. These modules must follow a specific format. For details, see [Custom Widgets](Data-Viewing.md#custom-widgets).

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Import Widget Module</td>
<td>Select the widget module file, then click this button to start the import.</td>
</tr>
</tbody>
</table>

## Measurement Settings { #measurement-settings }

Page\: `[Admin] -> System Configuration -> Measurements`

You can create new measurements, units, and conversions to extend functionality beyond AoT's built-in types and formulas. Before creating a measurement, you must first create the unit, because you need to select a unit when creating a measurement. You can also assign additional units to a measurement that already exists. For example: `altitude` already exists, but if you want to add the `fathom` unit, first create the `fathom` unit, then create the `altitude` measurement with `fathom` selected.

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Measurement ID</td>
<td>The ID of the measurement to use in the measurements_dict of the input module (e.g. &quot;length&quot;, &quot;width&quot;, &quot;speed&quot;)</td>
</tr>
<tr>
<td>Measurement Name</td>
<td>The common name of the measurement (e.g. &quot;Length&quot;, &quot;Weight&quot;, &quot;Speed&quot;)</td>
</tr>
<tr>
<td>Measurement Units</td>
<td>Select all units associated with the measurement.</td>
</tr>
<tr>
<td>Unit ID</td>
<td>The ID of the unit to use in the measurements_dict of the input module (e.g. &quot;K&quot;, &quot;g&quot;, &quot;m&quot;)</td>
</tr>
<tr>
<td>Unit Name</td>
<td>The common name of the unit (e.g. &quot;Kilogram&quot;, &quot;Meter&quot;)</td>
</tr>
<tr>
<td>Unit Abbreviation</td>
<td>The abbreviation of the unit (e.g. &quot;kg&quot;, &quot;m&quot;)</td>
</tr>
<tr>
<td>Convert From Unit</td>
<td>The unit that the conversion is based on</td>
</tr>
<tr>
<td>Convert To Unit</td>
<td>The unit to convert to</td>
</tr>
<tr>
<td>Conversion Equation</td>
<td>The equation used to convert one unit to another. It must contain a lowercase &quot;x&quot; (e.g. &quot;x/1000+20&quot;, &quot;250*(x/3)&quot;), and the actual measurement value replaces that x.</td>
</tr>
</tbody>
</table>

## User Settings { #users }

Page\: `[Admin] -> System Configuration -> Users`

At least one Admin user is required for AoT's login system to be enabled. If no Admin user exists, the web server redirects to the Admin creation form. This is the first page shown when AoT is started for the first time. After the Admin user has been created, additional users can be created on the User Settings page.

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>User Name</td>
<td>Choose a user name between 2 and 64 characters. It is case-insensitive and converted to all lowercase.</td>
</tr>
<tr>
<td>Email</td>
<td>The email address to associate with the account.</td>
</tr>
<tr>
<td>Password/Repeat</td>
<td>Choose a password between 6 and 64 characters, containing only letters, numbers, and symbols.</td>
</tr>
<tr>
<td>Keypad Code</td>
<td>A numeric code of 4 or more digits used to log in with a keypad (optional).</td>
</tr>
<tr>
<td>Role</td>
<td>The role used to set the user's permissions. See the descriptions of the 4 default roles below.</td>
</tr>
<tr>
<td>Theme</td>
<td>The theme applied to the web user interface. Includes colors, design elements, and so on.</td>
</tr>
</tbody>
</table>

### Roles { #roles }

Roles define the permissions of each user. Four default roles are provided that determine whether a user can view or edit specific areas of AoT. In addition to the default roles, you can create custom roles.

<table>
<thead>
<tr class="header">
<th>Role</th>
<th>Admin</th>
<th>Editor</th>
<th>Monitor</th>
<th>Guest</th>
</tr>
</thead>
<tbody>
<tr>
<td>Edit Users</td>
<td>X</td>
<td></td>
<td></td>
<td></td>
</tr>
<tr>
<td>Edit Controllers</td>
<td>X</td>
<td>X</td>
<td></td>
<td></td>
</tr>
<tr>
<td>Edit Settings</td>
<td>X</td>
<td>X</td>
<td></td>
<td></td>
</tr>
<tr>
<td>View Settings</td>
<td>X</td>
<td>X</td>
<td>X</td>
<td></td>
</tr>
<tr>
<td>View Camera</td>
<td>X</td>
<td>X</td>
<td>X</td>
<td></td>
</tr>
<tr>
<td>View Stats</td>
<td>X</td>
<td>X</td>
<td>X</td>
<td></td>
</tr>
<tr>
<td>View Logs</td>
<td>X</td>
<td>X</td>
<td>X</td>
<td></td>
</tr>
</tbody>
</table>

The `Edit Controllers` permission protects editing of Conditionals, Graphs, LCDs, Methods, PIDs, Outputs, and Inputs.

The `View Stats` permission protects viewing of the Usage Statistics, System Information, and Energy Usage pages.

## Raspberry Pi Settings { #pi-settings }

Page\: `[Admin] -> System Configuration -> Raspberry Pi`

The Raspberry Pi settings configure part of the Linux system on which AoT runs.

pigpiod is required to use PWM outputs and PWM, RPM, DHT22, DHT11, and HTU21D inputs.

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Enable/Disable Features</td>
<td>System interfaces that can be enabled and disabled from the web UI via the <code>raspi-config</code> command.</td>
</tr>
<tr>
<td>pigpiod Sampling Rate</td>
<td>The sampling rate at which the pigpiod service operates. A lower number allows a faster PWM frequency, but can significantly increase the processor load on a Pi Zero. pigpiod can also be completely disabled if it is not needed (see the note above).</td>
</tr>
</tbody>
</table>

## Alert Settings { #alert-settings }

Page\: `[Admin] -> System Configuration -> Alerts`

The Alert settings configure the credentials for sending email notifications.

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>SMTP Host</td>
<td>The SMTP server used to send email.</td>
</tr>
<tr>
<td>SMTP Port</td>
<td>The port used to communicate with the SMTP server (465 for SSL, 587 for TSL).</td>
</tr>
<tr>
<td>Enable SSL</td>
<td>Check to enable SSL, or uncheck to enable TSL.</td>
</tr>
<tr>
<td>SMTP User</td>
<td>The user name used to send email. You can enter just the name or the full email address.</td>
</tr>
<tr>
<td>SMTP Password</td>
<td>The user's password.</td>
</tr>
<tr>
<td>From Email</td>
<td>The value to set as the sending email address. This value must be an actual user email address.</td>
</tr>
<tr>
<td>Max Emails (per Hour)</td>
<td>Sets the maximum number of emails that can be sent per hour. If more alerts than this number occur within one hour, the excess alerts are discarded.</td>
</tr>
<tr>
<td>Send Test Email</td>
<td>Sends a test email to test the email configuration.</td>
</tr>
</tbody>
</table>

## Camera Settings

Page\: `[Admin] -> System Configuration -> Camera`

AoT can use multiple cameras simultaneously. Each camera can be used throughout the software after being configured in the Camera settings.

!!! note
    Due to manufacturer-specific hardware and software differences, some options (e.g. hue or white balance) may not be available on certain cameras.

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Type</td>
<td>Select whether the camera is a Raspberry Pi camera or a USB camera.</td>
</tr>
<tr>
<td>Library</td>
<td>Select the library used to communicate with the camera. Raspberry Pi cameras use picamera, and USB cameras should be set to fswebcam.</td>
</tr>
<tr>
<td>Device</td>
<td>Specify the device to connect the camera to. Only the fswebcam library uses this option.</td>
</tr>
<tr>
<td>Output</td>
<td>Sets the output that is activated during still image capture (including time-lapse).</td>
</tr>
<tr>
<td>Output Duration</td>
<td>Sets the duration for which the output is activated before capturing an image.</td>
</tr>
<tr>
<td>Rotate Image</td>
<td>Sets the angle by which to rotate the image.</td>
</tr>
<tr>
<td>...</td>
<td>Image Width, Image Height, Brightness, Contrast, Exposure, Gain, Hue, Saturation, White Balance. These options are self-explanatory. Not all options may work on all cameras.</td>
</tr>
<tr>
<td>Pre Command</td>
<td>A command to run as the 'root' user before a still image is captured.</td>
</tr>
<tr>
<td>Post Command</td>
<td>A command to run as the 'root' user after a still image is captured.</td>
</tr>
<tr>
<td>Flip Horizontally</td>
<td>Flips or mirrors the image horizontally.</td>
</tr>
<tr>
<td>Flip Vertically</td>
<td>Flips or mirrors the image vertically.</td>
</tr>
</tbody>
</table>

## Diagnostic Settings { #diagnostic-settings }

Page\: `[Admin] -> System Configuration -> Diagnostics`

Problems can occur in the system due to incompatible configurations. These can result from a part of the system (Input, Output, etc.) being misconfigured, an update in which the database upgrade was not handled properly, or other unexpected issues. There are times when you need to perform diagnostics to identify the cause of a problem or to resolve the problem itself. The options below are intended to mitigate problems. For example, if the `Data -> Dashboard` page cannot be accessed because of a misconfigured dashboard element that causes an error, deleting all dashboard elements may be the most economical way to regain access. Note, however, that in this case you will have to re-add all existing dashboard elements.

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Delete All Dashboards</td>
<td>Deletes all dashboards saved on the Data -> Dashboard page.</td>
</tr>
<tr>
<td>Delete All Inputs</td>
<td>Deletes all inputs on the Setup -> Input page.</td>
</tr>
<tr>
<td>Delete All Notes and Tags</td>
<td>Deletes all notes and tags on the More -> Note page.</td>
</tr>
<tr>
<td>Delete All Outputs</td>
<td>Deletes all outputs on the Setup -> Output page.</td>
</tr>
<tr>
<td>Delete Settings Database</td>
<td>Deletes the aot.db settings database (Warning: this deletes all settings and users).</td>
</tr>
<tr>
<td>Delete File: .dependency</td>
<td>Deletes the .dependency file. Try this if you have trouble accessing the dependency installation page.</td>
</tr>
<tr>
<td>Delete File: .upgrade</td>
<td>Deletes the .upgrade file. Try this if you have trouble accessing the upgrade page or running an upgrade.</td>
</tr>
<tr>
<td>Recreate InfluxDB 1.x Database</td>
<td>Deletes and then recreates the InfluxDB 1.x measurement database. This deletes all measurement data!</td>
</tr>
<tr>
<td>Recreate InfluxDB 2.x Database</td>
<td>Deletes and then recreates the InfluxDB 2.x measurement database. This deletes all measurement data!</td>
</tr>
<tr>
<td>Reset Email Counter</td>
<td>Resets the hourly email counter.</td>
</tr>
<tr>
<td>Install Dependencies</td>
<td>Starts the script that installs all dependencies required across the entire AoT system.</td>
</tr>
<tr>
<td>Set Upgrade to Master</td>
<td>Changes FORCE_UPGRADE_MASTER to True in config.py. This is a way to instruct the upgrade system to upgrade to the master branch on GitHub, without having to log in and manually edit the config.py file.</td>
</tr>
</tbody>
</table>
