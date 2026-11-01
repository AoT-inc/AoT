---
guide_id: g13-help
title: Help and Reporting Problems
level: 1
minutes: 15
needs: ["g01-install"]
kind: 설명
---

# Help and Reporting Problems

If you get stuck while using AoT, first open the **Help** menu at the top right of the screen. From there you can go straight to the manual for the screen you are viewing,
the whole online manual, the API documentation and the AoT GitHub. If an error occurs, gather information from the error screen and the System Log
and report it as an issue on the AoT GitHub. AoT has had this path from the start, and it is still the most basic one.

## When you finish this chapter { #goal }

- You find the explanation of the screen you are viewing, and the API documentation, on your own
- When an error occurs, you gather the information needed and report it on GitHub

## Before you start { #prepare }

- AoT that you can log in to ([Installation](g01-install.md#check))
- A GitHub account, if you want to report problems

## Steps { #steps }

### 1. The Help menu { #step-1 }

Click **Help** at the top right of the screen to see the items below. They all open in a new tab.

| Item | What it opens |
|---|---|
| **Help: &lt;screen name&gt;** | The manual section that explains the screen you are viewing. It appears only on screens that have an explanation |
| **Online Manual** | The manual's front page |
| **User Guide** | The first page of this guide |
| **API Info** | The API section of the manual |
| **API Documentation** | The API list screen built into this AoT (`/api`). You can see request formats and responses directly |
| **AoT Github** | AoT's source code and issue board |
| **AoT Homepage** | The AoT introduction site |
| **Privacy Policy**, **Terms of Service** | The corresponding documents |

The manual opens in the Korean, Japanese or English edition, following the screen language.

Click the **?** mark next to an item name on a settings screen to go to the manual section that explains just that item.

### 2. Gather information from the error screen { #step-2 }

If an error occurs while opening a screen, the **Error 500: Internal Server Error** screen appears. It shows the AoT version,
the database version, board information and the full error trace.

1. Copy all the information shown on the screen.
2. Click the **submit a new issue on GitHub** link to open the issue form on the AoT GitHub.
   First check the **GitHub Issues** link to see whether the same problem has already been posted.
3. Paste the copied information, write what you were doing when the error occurred, and submit.

AoT never sends error information anywhere on its own. To report it, you must post an issue yourself.

!!! warning "Remove secret information before posting"
    Anyone can see GitHub issues. If the content you paste includes API keys, passwords, email addresses, site addresses or
    IP addresses, remove them before posting.

### 3. Download the system log { #step-3 }

If something behaves strangely without an error screen, look at the logs.

1. Open **Manage** → **System Log** (the screen title is **Log View**).
2. Choose the log type (daemon, web app, etc.) and the minimum level, and look around the time the problem occurred.
3. Click **Download** to save the selected log as a text file (up to 2000 lines). Attach this file to the issue.

If you have connected AI, you can also ask what the selected lines mean with the **Explain**, **Diagnose the cause** and **How do I fix it?** buttons
on the log screen ([AI & MCP Connection](g12-ai-mcp.md)).

### 4. Check the version and status { #step-4 }

In **Manage** → **System Information**, look at the **AoT Version**, the daemon status and disk usage. When you post an issue,
include the AoT version and the installation method (Docker or direct install). This is needed to judge whether a version
that already fixes the same problem exists.

### 5. Use the API { #step-5 }

To read AoT's values or handle devices from another program, use the API.

1. Find the requests you can use in **Help** → **API Documentation**. **API Info** explains usage examples and rules.
2. When making a request, put a user API key in the `X-API-KEY` header (`Authorization: Bearer <key>` also works).
3. You create a user API key in **Manage** → **System Management** → **Users** → edit the user → **API Key** by entering
   a name in the **Issue New Key** row and clicking **Generate**. The key is shown **only once, when it is created**, so write it down somewhere safe right away.

The **API Key Management** menu is different from this. It is where AoT stores the keys it uses for outside services, such as weather and map services;
user API keys are created only on the user edit screen.

## Check { #check }

You are done when the online manual and the API documentation open from the **Help** menu, and you know where to get the information to post when a problem occurs.

- Open a settings screen: does **Help: &lt;screen name&gt;** lead to the explanation of that screen?
- Can you download a log in **Manage** → **System Log**?
- Can you find the AoT version in **Manage** → **System Information**?

## Site A { #site-a }

At Site A, one administrator collects problems and posts them on GitHub. When people on site notice something odd, they capture the screen,
note the time and pass it to the administrator, who downloads the daemon log for that time and attaches it to the issue.

## Site B { #site-b }

Site B is connected to existing control equipment, so the first step is to tell whether a problem is on the AoT side or the existing equipment side. Before posting an issue,
it first checks in **Manage** → **Audit Log** whether the output command went out, and in **Live Measurement** whether AoT received the values.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| There is no **Help: &lt;screen name&gt;** item | That screen has no linked explanation. Look in the **Online Manual** |
| The manual does not open | The manual is at `aot-inc.github.io` on the internet. Check that you can reach the internet and that it is on your firewall allow list ([Network Connection](g03-network.md#step-4)) |
| API requests are rejected | Check that you put a user API key in the `X-API-KEY` header and that the key's permissions fit the request |
| You lost a user API key | It cannot be shown again. Create a new one and delete the old key |

## Learn more { #more }

- [API](../API.md)
- [Log viewer](../Log-Viewer.md)
- [System information](../System-Information.md)
- [Troubleshooting](../Troubleshooting.md)
