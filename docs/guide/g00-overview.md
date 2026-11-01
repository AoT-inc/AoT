---
guide_id: g00-overview
title: Getting Started Guide
level: 1
minutes: 20
needs: []
kind: 설명
---

# Getting Started Guide

AoT puts your space on a map and connects the records and devices in it. It then lets AI look at that space,
make judgements and carry out work together with people. It is open source, and anything that moves a device runs
only after the user approves it.

This guide is meant to be followed in order when you first install and start using AoT. It covers installation,
setting up the map, sensors and outputs, making things move automatically under conditions, getting an email when
something goes wrong, watching your site from a single screen, and connecting AI. The other parts of the manual
explain each feature in detail. This guide explains in what order to combine those features. If you want to know
what an option means, follow the **Learn more** links at the end of each chapter.

## When you finish this chapter { #goal }

- You know how each chapter connects, from installation to connecting AI
- You know how the two example sites used in this guide (Site A and Site B) are set up

## Before you start { #prepare }

Before you read the guide, note the following.

| Item | Details |
|---|---|
| Format | Provided as documents. The same content is also being prepared as videos |
| Reference version | AoT 26.09.07. The explanations and screen captures are based on this version |
| Where to read | The **User Guide** in the online manual ([aot-inc.github.io/AoT](https://aot-inc.github.io/AoT)). Korean, English and Japanese editions are available |
| Source | The AoT source code and manual are published on GitHub ([github.com/AoT-inc/AoT](https://github.com/AoT-inc/AoT)), and this guide is part of that manual |
| More detailed explanations | Feature-by-feature explanations are in other parts of the same manual. Follow **Learn more** at the end of each chapter |

## Steps { #steps }

### 1. The overall flow { #step-1 }

| Chapter | What you do | When it is done |
|---|---|---|
| [Installation](g01-install.md) | Start AoT with Docker and create an administrator account | You can log in from a browser |
| [Key settings](g02-settings.md) | Set the timezone, language, units and users | Each person logs in with the right permissions |
| [Network connection](g03-network.md) | Connect from outside without opening ports, and build a firewall allowlist | The on-site AoT opens from the office or a phone |
| [Map setup](g04-map.md) | Register a base map and draw sites, zones, facilities and plots | Your site is represented on the map |
| [Sensor connection](g05-sensors.md) | Bring in sensor values and link them to the map and facilities | Live values come in |
| [Output connection](g06-outputs.md) | Register valves, pumps, windows and curtains as outputs | You can switch them on and off by hand from the screen |
| [Functions](g07-functions.md) | Create rules that connect sensors and devices | Devices move on their own under the conditions you set |
| [Email alerts](g08-email.md) | Get an email when something goes wrong | One email arrives when the condition is met |
| [Monitoring](g09-monitoring.md) | Decide what to check every day | You quickly find disconnected sensors and stopped functions |
| [Dashboard setup](g10-dashboard.md) | Arrange screens for the people who view them | You watch your site from a single screen |
| [AI & MCP connection](g12-ai-mcp.md) | Connect the AI assistant you already use to AoT through MCP | You ask the AI about the site's status and hand it tasks |
| [Help and reporting problems](g13-help.md) | Learn where to find the manual, the API and error reporting | When you get stuck, you look things up yourself and report the problem |
| [Cautions](g11-cautions.md) | Review the points that most easily lead to incidents | You are prepared for backups, updates and power outages |

If your site does not need a map, you can skip Map setup. If you do not need remote access, you can do Network
connection later. You can read AI & MCP connection and Help at any time. For the rest, each chapter must be
finished before you can do the next one.

### 2. Try it first without equipment { #step-2 }

You can follow this guide to the end without real sensors or devices. A **test input**, where you enter values
directly, stands in for sensors ([Sensor connection](g05-sensors.md#step-6)), and a **virtual output**, which only
imitates switching on and off, stands in for devices ([Output connection](g06-outputs.md#step-1)). After you check
your settings with virtual equipment, you can switch to real equipment.

## Check { #check }

Note down the two points below. You will use them to choose which sections to follow from the next chapter on.

- Is my site closer to Site A or to Site B?
- How is each of my sensors and devices connected (LoRaWAN, MQTT, PLC, weather API, direct connection)?

## Site A { #site-a }

**A site with both open fields and a facility.** It has about 30,000 m² of land with two open-field zones and one
single-span greenhouse.

- Sensors: open-field temperature/humidity and soil moisture (LoRaWAN wireless), outside weather (weather API), temperature/humidity inside the greenhouse (MQTT)
- Devices: 8 open-field valves and a pump (LoRaWAN valve controller), left and right greenhouse side windows, a mister
- Automatic control: **sequential irrigation** by day of week and time of day for the open fields, **environment control** for the greenhouse

Because several connection methods are mixed at one site, it is used as the example in the Sensor connection and
Output connection chapters.

## Site B { #site-b }

**A facility-focused site.** AoT was added to the existing control equipment of a 6-bay multi-span greenhouse.

- Sensors: temperature/humidity at 5 points inside the greenhouse and an outside weather station (received over MQTT from the existing equipment)
- Devices: side windows, roof windows and thermal curtains (using the existing control panel's open and close relays as they are), a mister
- Automatic control: a single **environment control** handles the whole greenhouse

It is used as an example of how to connect without changing existing equipment.

## Troubleshooting { #trouble }

If a screen name or button in this guide differs from what you see, check the version of AoT you installed. You
can find the version under Manage → System Information. The guide is based on AoT 26.09.07.

## Learn more { #more }

- [About AoT](../About.md)
- [Manual home](../index.md)
