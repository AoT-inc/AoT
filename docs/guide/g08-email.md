---
guide_id: g08-email
title: Email alerts
level: 1
minutes: 30
needs: ["g07-functions"]
kind: 실습
---

# Email alerts

No one can watch the screen all the time. In this chapter you make AoT send an email when something happens,
such as "the greenhouse is too hot" or "a sensor has stopped sending values". Alerts in AoT are built with **functions**.
A conditional function checks a condition and, when the condition is met, runs a **Send Email action**.
The Input and Output pages have no alert settings of their own.

## When you finish this chapter { #goal }

- You have set up email sending and received a test email
- You get an email when a condition is met, and the same alert does not keep repeating

## Before you start { #prepare }

- An AoT system where you can create functions ([Functions](g07-functions.md#check))
- An account to send email from. For Gmail, **turn on 2-Step Verification for the Google account and create an "app password".**
  You cannot send with your normal sign-in password
- An email address to receive the alerts

## Steps { #steps }

### 1. Set up the mail server { #step-1 }

Open Manage → System Administration → **Alerts** (the page title is Alert Settings).

| Field | Gmail example | Description |
|---|---|---|
| SMTP Host | `smtp.gmail.com` | The server that sends the mail |
| SMTP Port | (leave empty) | If empty, the default port for the protocol is used (SSL 465, TLS 587) |
| SMTP Protocol | TLS | For a company mail server, ask the administrator |
| SMTP User | The Gmail address that sends | |
| SMTP Password | The 16-character app password | If left empty, the saved value is kept |
| From Email | The same address as SMTP User | Gmail may reject the mail if the two differ |
| Max Emails per Hour | 5 | The most emails that can be sent in one hour. Emails over the limit are **discarded** |

Click **Save**.

### 2. Send a test email { #step-2 }

On the same page, enter a recipient address under **Send Test Email** and click the button. You should receive an email
titled "AoT Notification (computer name)" in your inbox (check the spam folder too).

The test email is sent with the **saved settings**. If you changed any field, always click **Save** first, then test.
If it fails, the actual error is recorded in the **Daemon** log under Manage → System Log.

### 3. Create an alert function { #step-3 }

Example: send an email when the temperature inside the greenhouse goes above 35 ℃, or when no value arrives for 10 minutes.

1. In Settings → **Functions**, add a **Conditional Controller**.
   Click the gear icon to open the **Condition Settings** window and give it a name (for example, "Alert: Site B greenhouse high temp / dropout").
2. Set **Period (sec)** to 60. The condition is checked every minute.
3. In the **Add Condition** list, choose **Measurement (Single, Last)** and click **Add**. In the new condition,
   select the greenhouse indoor temperature sensor as the **Measurement**, set **Max Age (sec)** to 600, and click **Save** for that condition.
   Values older than 10 minutes are treated as "no value". In the description text under the condition row you will see a line to use in code, such as `self.condition("a1b2c3d4")`.
4. In the **Add Action** list, choose **Send Email** and click **Add**. Enter the recipient address (separate several addresses with commas)
   and click **Save** for that action.
5. Delete the example in **Python Code to Execute** and paste the code below. Replace `self.condition("…")` on the first line with the line you saw in item 3.

```python
temp = self.condition("a1b2c3d4")

if not hasattr(self, "alerted"):
    self.alerted = False

problem = (temp is None) or (temp > 35)

if problem and not self.alerted:
    if temp is None:
        self.message += "No greenhouse temperature value has arrived for more than 10 minutes.\n"
    else:
        self.message += f"The greenhouse temperature is {temp:.1f} ℃.\n"
    self.run_all_actions()
    self.alerted = True
elif not problem:
    self.alerted = False
```

6. Click **Save** at the bottom of the window, then **Activate** the function. When you save, a code check (pylint) may show warnings. If they are not errors, you can leave them.


!!! note "Why the code uses `alerted`"
    A conditional function checks its condition every period. Without a guard, you would get an email every minute while the problem lasts.
    `alerted` is a marker that means "already notified". The email is sent only the first time the problem appears. When the value returns
    to normal, the marker is cleared so that the next problem triggers a new alert.


### 4. Test the alert { #step-4 }

You cannot actually make the greenhouse hot, so temporarily switch the condition's sensor to a [test input](g05-sensors.md#step-6)
and enter 36. If an email arrives within 1 to 2 minutes, and **no more emails arrive** while the value stays at 36, the test has passed.
If you enter 25 and then 36 again, one more email arrives. When you finish testing, switch the condition back to the real sensor.

## Check { #check }

You are done when **one** email arrives the first time the condition is met, and no more arrive while the condition continues.

- Check that the email body states which sensor and which value caused the alert.
- If you have several alert functions, check that together they stay under Max Emails per Hour. Emails over the limit are discarded.

## Site A { #site-a }

Site A uses two alerts, one for the open field and one for the greenhouse.

- **Alert: open-field soil sensor dropout** — Set the max age of the 3-1 and 3-2 soil sensors to three times the sensor interval, and alert when there is no value.
  LoRaWAN sensors go silent without warning when their battery runs out, so this alert is the most useful one.
- **Alert: greenhouse high temperature** — Alert when the temperature inside the single-span greenhouse goes above 35 ℃.

## Site B { #site-b }

Site B first covers the case where environment control stops.

- **Alert: greenhouse high temp / dropout** — Exactly the example in [step 3](#step-3).
- **Alert: weather station dropout** — If the outdoor wind speed value stops, environment control will not open the vents any further. This alert tells you right away when that happens.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| The test email fails | Whether you used an app password, whether the protocol and port are correct, and whether you clicked **Save** before testing. Manage → System Log → Daemon |
| The test email arrives but alerts do not | Whether the function is **activated**, whether you replaced the condition ID in the code, and whether the Send Email action has an address |
| Alerts arrived for a while and then stopped | Max Emails per Hour was exceeded. Go to Settings → Diagnostics → **Reset Email Counter**, and add the repeat-prevention code |
| An email arrives every minute | The repeat-prevention code (`alerted`) is missing |
| Email is not sent only on the site network | The network is blocking mail ports ([Network connection](g03-network.md#step-4)) |

## Learn more { #more }

- [Alert settings](../Configuration-Settings.md#alert-settings)
- [Conditional functions](../Functions.md#conditional)
- [Actions](../Actions.md)
- [Alerts](../Alerts.md)
