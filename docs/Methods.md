Page\: `Setup -> Method`

Methods enable Setpoint Tracking in PIDs and time-based duty cycle changes in timers. Typically, a PID controller adjusts an environmental condition to a specific setpoint. When you allow the setpoint to change over time, this is called Setpoint Tracking. Setpoint Tracking is useful for applications such as reflow ovens, thermal cyclers (DNA replication), mimicking natural daily cycles, and more. Methods can also be used to change a duty cycle over time when used with the Run PWM Method Conditional.

## Method Options

These options are shared by several method types.

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td>Start Time/Date</td>
<td>The start time of the time range.</td>
</tr>
<tr>
<td>End Time/Date</td>
<td>The end time of the time range.</td>
</tr>
<tr>
<td>Start Setpoint</td>
<td>The starting setpoint of the setpoint range.</td>
</tr>
<tr>
<td>End Setpoint</td>
<td>The ending setpoint of the setpoint range.</td>
</tr>
</tbody>
</table>

## Time/Date Method

The Time/Date Method allows a specific time/date range to be set to a setpoint. This is useful for long-running methods that span several days, weeks, or months.

## Duration Method

The Duration Method allows a **setpoint** (in the case of a PID) or a **duty cycle** (in the case of a Conditional) to be set after a specific duration. Each new duration added stacks after the previous one, so the newly added **Start Setpoint** begins after the **End Setpoint** of the previous entry.

The "Repeat Method" option causes the method to repeat when it reaches the end. When this option is in use, no further durations can be added to the method. If the repeat option is removed, more durations can be added. For example, if a method totals 200 seconds and the repeat duration is set to 600 seconds, the method will repeat 3 times before automatically shutting off the PID or Conditional.

## Daily (Time-Based) Method

The Daily Time-Based Method is similar to the Time/Date Method but repeats every day. Therefore, only a single day's range needs to be set for this method. Set the start time to 00:00:00 and the end time to 23:59:59 (or 00:00:00, i.e., 24 hours from the start time). The start time must be greater than or equal to the previous end time.

## Daily (Sine Wave) Method

The Daily Sine Wave Method defines a setpoint over the course of a day based on a sine wave. The sine wave is defined as y = [A \* sin(B \* x + C)] + D, where A is the amplitude, B is the frequency, C is the angular shift, and D is the y-axis shift. This method repeats every day.

## Daily (Bezier Curve) Method

The Daily Bezier Curve Method defines a setpoint over the course of a day based on a cubic Bezier curve. If you are not familiar with Bezier curves, it is recommended to use the [graphical Bezier curve generator](https://www.desmos.com/calculator/cahqdxeshd) to generate the 8 variables for the 4 points (each an x and y set). The x-axis start (x3) and end (x0) are automatically scaled or distorted to fit within 24 hours, and this method repeats every day.

## Cascade Method

This method combines multiple methods and outputs the average of the methods. For example, suppose you combine a Duration Method set to 100 for 60 seconds and a Duration Method set to 0 for 60 seconds (set to repeat forever) with a Daily Method that rises from 0 to 50 at 00:00:00 and falls back to 0 at 12:00:00. At 00:00:00, the combined method oscillates every 60 seconds from 0 ((0 / 100) \* (0 / 100) = 0) to 0 ((100 / 100) \* (0 / 100) = 0), gradually increasing until, at 12:00:00, it oscillates every 60 seconds from 0 ((0 / 100) \* (50 / 100)) to 50 ((100 / 100) \* (50 / 100)). This is a simple example, but combinations can become quite complex.
