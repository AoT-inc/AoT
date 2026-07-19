# Sensor Calibration Manual

Calibration ensures that your sensors provide accurate and reliable measurements. This manual covers the procedure for the most common sensors in the AoT system, specifically Atlas Scientific EZO circuits.

## Atlas Scientific EZO Circuits (pH, EC, DO, ORP)

Atlas Scientific sensors support a structured one-, two-, or three-point calibration process.

> [!IMPORTANT]
> Always perform the calibration steps in the correct order: **Mid** -> **Low** -> **High**.

### Calibration Steps

1.  **Clear Calibration**: Before starting, it is recommended to clear any existing calibration data using the **Clear Calibration** button.
2.  **Temperature Compensation (Optional)**: If you have a separate temperature sensor, you can use it to compensate for temperature variations during calibration. This ensures the highest accuracy.
3.  **Mid-Point Calibration**: Place the probe in the Mid solution (e.g., pH 7.00). Wait for the reading to stabilize (1-2 minutes) and click **Calibrate Mid**.
4.  **Low-Point Calibration**: Rinse the probe and place it in the Low solution (e.g., pH 4.00). Wait for stabilization and click **Calibrate Low**.
5.  **High-Point Calibration**: Rinse the probe and place it in the High solution (e.g., pH 10.00). Wait for stabilization and click **Calibrate High**.

### Verification

You can verify the calibration status by checking the **Slope** and **Calibrated?** messages in the **Daemon Log** (`[Manage] -> AoT Logs -> Daemon Log`). 

- A slope near 100% indicates a healthy probe and successful calibration.
- The `Cal,?` command returns the number of points calibrated.

## Peristaltic Pump Calibration

Peristaltic pumps (dosing pumps) require calibration to determine how much liquid is moved per second or per rotation.

1.  Measure the amount of liquid pumped over a set duration (e.g., 60 seconds).
2.  Enter the measured volume into the **Calibration** field in the pump's output settings.
3.  This allows AoT to accurately dose by volume (e.g., "Pump 10ml").

---

> [!NOTE]
> For AI agents, structured calibration commands and procedure details are available in `ai_docs/calibration.json`.
