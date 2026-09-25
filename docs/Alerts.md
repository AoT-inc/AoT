Alerts let the system tell people about its state. With sensor monitoring, for example, a reading past a threshold may mean something needs attention.

Inputs and outputs do **not** send email by themselves. There is no email option on an input or output. An alert is sent by one of the following paths:

- **A Conditional function with a Send Email action.** This is the general-purpose path. The conditional's Python code checks a condition (for example, a measurement is missing or past a limit) and calls the [Send Email action](Actions.md) (or Send Email with Photo). See [Conditional Function](Functions.md#conditional).
- **The pH/EC regulator's own email field.** The [pH/EC regulator function](Supported-Functions.md) emails the addresses entered in its own field when pH leaves its danger range, when EC is too high, or when it finds no recent measurement. It keeps its own repeat timers.
- **AI anomaly alerts.** When AI autonomy is on, anomaly alerts of warning level or higher are emailed to the administrators.
- **Custom Python code** in the places that allow it can send messages any other way you want.

All of these use the SMTP account entered under [Alert Settings](Configuration-Settings.md#alert-settings), so configure that first and send a test email from the same page.

## The hourly email limit

The Send Email and Send Email with Photo actions share an hourly limit, set in Alert Settings as **Max Emails per Hour**. Emails over the limit are dropped, not queued, and are not sent later once the hour ends. Each dropped email leaves an error line in the daemon log ([Log Viewer](Log-Viewer.md)). If mail stops arriving while the limit is being hit, clear the counter with **Reset Email Counter** under [Diagnostic Settings](Configuration-Settings.md#diagnostic-settings). A failed SMTP connection or login is also logged under the **Daemon** source of the Log Viewer.

## Sending once until the condition clears { #send-once-latch }

A conditional runs on every check, so a condition that stays true sends an email on every check and quickly uses up the hourly limit. Until a built-in option exists, keep a flag on `self`, which survives from one run to the next, so the email is sent once and the flag is cleared only after the condition is over:

```python
measurement = self.condition("asdf1234")

if not hasattr(self, "alert_sent"):  # first run only
    self.alert_sent = False

if measurement is not None and measurement > 30:  # the alert condition
    if not self.alert_sent:
        self.run_all_actions()  # sends the email once
        self.alert_sent = True
elif measurement is not None:  # a valid reading back in range
    self.alert_sent = False  # re-arm for the next occurrence
```

Notes:

- Re-arm only on a valid reading. If the input stops reporting (`None`), the flag stays as it is, so a sensor dropout does not trigger a second email.
- The flag lives in memory. Deactivating and reactivating the function, or restarting the daemon, resets it, and the next true check sends one email again.
- To alert on a missing measurement instead, use `if measurement is None:` for the condition and re-arm when the value returns.

For more details on configuring email, see [Alert Settings](Configuration-Settings.md#alert-settings).
