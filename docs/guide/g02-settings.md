---
guide_id: g02-settings
title: Key Settings
level: 1
minutes: 30
needs: ["g01-install"]
kind: 실습
---

# Key Settings

A few settings should be made right after installation so they do not cause confusion later. This chapter separates
**what to do on the first day** from **what can wait**. Most settings are under Manage → **System Management**.

## When you finish this chapter { #goal }

- You complete the settings that must be done on the first day, in order
- You create accounts with the right permissions for the people who will use AoT with you

## Before you start { #prepare }

- AoT installed and logged in as an administrator ([Installation](g01-install.md#check))
- Your site's timezone (for example `Asia/Seoul`)
- A list of the people who will use AoT and what each of them will do (who also changes settings, who only views)

## Steps { #steps }

### 1. Timezone and language { #step-1 }

In Manage → System Management → **General Settings**:

- **Language**: with **Browser Default**, each person sees their own browser language. To set it differently per person, each person sets it in Manage → **User Settings**.
- **Landing Page**: the screen shown first after login (Real-time Measurement at first). Once you have built a dashboard, switching this to the dashboard is convenient.
- **Index Page**: the screen shown when you click the logo at the top left (**Same as Landing Page** at first).
- **System Timezone**: enter your site's timezone (in Region/City format, such as `Asia/Seoul`).
  This is the last fallback used when a device or zone has no timezone of its own.

System Timezone is already filled in with the `TZ` value you set during installation. If it matches your site's timezone, leave it as is. If you changed it, click **Save** at the top.

!!! note "Why time is set in more than one place"
    So that AoT works even when equipment is spread across several timezones, it determines the time in this order:
    device → zone/site → System Timezone. If you use only one site, only System Timezone needs to be correct. Sunrise and
    sunset times are calculated from the site location drawn on the map, so also complete [Map setup](g04-map.md).

### 2. Create users { #step-2 }

Click Manage → System Management → **Users** to open the **User Settings** page (tabs: **Users**, **Roles**, **Groups**, **General**).
On the **Users** tab, click **Add User** and enter the login account, name, email, password and role.
The login account cannot be changed later.

| Role | What it can do | Who it is for |
|---|---|---|
| Admin | Everything, including user management and access to all groups | 1 or 2 people responsible for the system |
| Editor | Everything except user management (including operating devices and changing settings) | Site managers |
| Monitor | View and ask AI questions | Inspectors, people who only watch the situation |
| Guest | Nothing | Not used |
| Kiosk | View cameras and statistics | Wall-mounted screens and similar |

**AoT System (internal AI)**, which is in the list from the start, is an internal account used by the AI features. You cannot
log in with this account. Leave it as it is.

Do not share an administrator account among several people. Only when each person has their own account does
**Manage → Audit Log** record who did what.

### 3. Divide control scope with groups (when needed) { #step-3 }

If there are several sites and different people are responsible for different sites, use **Groups**. A group narrows
what people can **operate**. It does not block viewing. When you assign a group in the settings of a dashboard, map
or facility, from that moment only people in that group can operate it. If you use only one site, skip this step.

### 4. Login protection { #step-4 }

- After 5 wrong passwords, the account is locked for 10 minutes. You do not need to do anything for this.
- If you plan to allow access from outside ([Network connection](g03-network.md)), use long passwords for every account.
- Two-factor authentication (TOTP) currently cannot be turned on from the screen. An administrator has to set it in the database ([Two-factor authentication](../Security.md#totp)).

### 5. What can wait { #step-5 }

| Setting | When |
|---|---|
| Alert Settings (mail server) | When you do [Email alerts](g08-email.md) |
| User API key | When you connect an AI tool. Manage → System Management → Users → click the user's gear icon to open **Edit User** → in the **API Keys** section, type a name in the **Issue New Key** row and click **Generate** |
| External service keys (weather, map, LoRaWAN) | When you use that feature. Manage → System Management → **API Key Management** |
| Site name display | Custom UI → Brand Text |
| Adding and converting measurement units | When the default units are not enough. Manage → System Management → Measurement |
| Update check and statistics collection | The defaults (update check on) are enough. At sites that block outside connections, turn them off in General Settings |

**User API key** and **API Key Management** are different things. The first is the key an AI tool uses to get into AoT.
The second is the key AoT uses to get into outside services (weather, map, ChirpStack).

## Check { #check }

- If the times shown in Live Measurements or the System Log match your site's time, the timezone is correct.
- Log in with a newly created account and check that menus are shown or blocked according to the role (for example, a Monitor role must not be able to turn on an output).

## Site A { #site-a }

Site A is used by staff of the managing organization together with on-site workers.

- 1 Admin (responsible for the system), 2 Editors (site managers), several Monitors (inspectors and visitors)
- There is only one site, so groups are not used.

## Site B { #site-b }

Site B is used by one or two operators. One Admin and one Editor are enough. On the wall-mounted screen next to the
greenhouse, the dashboard is shown with a Monitor account that has no permission to operate anything.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| Times are off by several hours | System Timezone, and Manage → User Settings → Timezone (for personal display) |
| The password is rejected when creating a new user | Whether it has at least 8 characters and is not a common password |
| The account is locked | Try again after 10 minutes, or have an administrator unlock it on the Users screen |
| A person cannot operate only one specific dashboard | A group is assigned to that dashboard ([Step 3](#step-3)) |

## Learn more { #more }

- [General settings](../Configuration-Settings.md#general-settings)
- [Users, roles and groups](../Configuration-Settings.md#users)
- [Time and timezones](../time-handling.md)
- [Security](../Security.md)
