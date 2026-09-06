Page\: `More -> Energy Usage`

There are two ways to calculate energy usage. The first method is based on the amount of time an output is on. If you have set the amount of current (in amperes) that an output consumes in the output settings, kWh and cost can be calculated from this. The way to determine how much current a device consumes is usually to calculate it from the watt (W) value printed on the device's label, or to measure it with a current clamp while the device is operating. A limitation of this method is that PWM outputs are not currently used in this calculation, because it is difficult to determine the current consumption of a device driven by a PWM signal.

The second method is more accurate and is the recommended approach when you want the most accurate estimate of energy consumption and cost. This method relies on an Input or Function that measures amperes. One way to do this is to use an analog-to-digital converter (ADC) that converts the voltage output of a transformer into current (amperes). One conductor of the AC line that powers the device passes through the transformer, and the device converts the current flowing through this line into a voltage. For example, the sensor below converts a 0-50 ampere input into a 0-5 volt output. The ADC takes this output as its input. Once you configure this conversion range in AoT, the calculated current is stored. Adding this ADC input measurement on the Energy Usage page generates a summary report. For the calculation of a specific period (for example, the past week) to be accurate, amperes must be measured periodically. The faster the measurement rate, the more accurate the calculation, because the ampere measurements are averaged over this period before kWh and cost are calculated. If no ampere measurements are collected during this period, the calculation is likely to be inaccurate if the device is actually consuming current.

[Greystone CS-650-50 AC Solid Core Current Sensor (Transformer)](https://shop.greystoneenergy.com/shop/cs-sensor-series-ac-solid-core-current-sensor)

The following settings are for calculating energy usage based on ampere measurements. For the method of calculating based on output duration, see [Energy Usage Settings](Configuration-Settings.md#energy-usage-settings).

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Select Ampere Measurement</td>
<td>The measurement, in amperes (A), to use for calculating energy usage.</td>
</tr>
</tbody>
</table>