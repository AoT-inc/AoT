---
guide_id: g04-map
title: Building the Map
level: 1
minutes: 50
needs: ["g02-settings"]
kind: 실습
---

# Building the Map

AoT can do more when it knows **where** your sensors and devices are. It can gather values by zone,
group the windows and sensors of one greenhouse to control its environment, and record what was started in each plot and when.
In this chapter you transfer your site onto the map. AoT works without a map, but if your site has several
zones or facilities, drawing them first makes the later chapters easier.

You draw four kinds of things on the map.

| What you draw | Meaning | Example |
|---|---|---|
| Site | The boundary of the whole site | All of Site A |
| Zone | An area of land that divides the site | Open field 3-1, 3-2 |
| Facility | A building or greenhouse. You create it by entering its size and structure | Single-span greenhouse, 6-bay multi-span greenhouse |
| Plot | A place inside a zone or facility where you grow or manage one subject | Bean plot in 3-1, 3 lettuce beds inside the greenhouse |

**You can put every site and facility you manage on one map.** You do not need a separate map for each site.
Dividing maps is a choice made for easier management. The cases where dividing helps are described in [step 5](#step-5).

## When you finish this chapter { #goal }

- You register a base map (MapTiler) so the map screens show a background
- You draw the site boundary, zones, and facilities on the map
- You keep open-field zones and facilities apart, and create plots inside them

## Before you start { #prepare }

- AoT with the first setup finished ([Main Settings](g02-settings.md#check))
- The site location (an address or approximate coordinates), how you want to divide the zones, and the size of each facility (width, length, height, number of bays)
- One email address: you use it to create a base map (MapTiler) account
- A VWorld key, if you want to import parcel boundaries as they are (optional)

## Steps { #steps }

A fresh AoT installation has **no maps at all.** If you open a map screen, you see an empty background
with little more than country borders. So first you register a source for the base map (a **GIS input**).

At present, the source of vector maps in AoT is **MapTiler**. The map screens (map design, the dashboard map widget, the
journal map) show an active MapTiler map as the background when they first open, and you can switch to another background
with the map's **Layers** button. So the first step is to get a MapTiler key and create one MapTiler Vector input.

### 1. Get a MapTiler key { #step-1 }

You can also open the MapTiler key page through the **API key** link in the input settings window of [step 2](#step-2).

1. Create an account at [cloud.maptiler.com](https://cloud.maptiler.com/) (sign up with email; you can start on the free plan).
2. After you sign in, open the **API keys** page ([cloud.maptiler.com/account/keys](https://cloud.maptiler.com/account/keys/)).
   A default key is already there. To make a new one, click **New key** and give it a name (for example, "AoT Site A").
3. Copy the key string and keep it.
4. If you enter the addresses you use to open AoT under the key's allowed addresses (Allowed HTTP origins), other sites
   cannot use the key even if it leaks. Enter **both** the local network address (`http://192.168.x.x:8084`) and the
   outside access address (the one you set up in [Network Connection](g03-network.md)). If you open AoT from an address that is
   missing from the list, the map does not load at that address only.

!!! note "Usage on the free plan"
    The MapTiler free plan has a fixed monthly usage limit. A few people viewing one site is
    usually well within it, but if you go over, the map background does not load for the rest of that month. You can see your usage on your MapTiler account page.

### 2. Add a MapTiler map to GIS Input { #step-2 }

1. In AoT, open Settings → **GIS Input** (page title: GIS Input Manager). The list is empty at first.
2. In the **Select GIS Service** list, choose `GL: MapTiler Vector` and click **Add**.
3. Click the gear icon on the new card to open the **Input Settings: GL: MapTiler Vector** window.
   - **MapTiler API Key**: the key you copied in step 1
   - **Map Channel Settings**: each channel (Streets, Outdoor, Satellite, Hybrid, Ocean, Topo) has a **Status** switch. Turn on
     the backgrounds you will use. If you turn on several, you can switch between them with the map's **Layers** button; when the map first opens,
     the first of the active channels is shown. **Streets** suits a regular map, and **Hybrid** suits satellite imagery with roads and place names.
   - **Label Language**: `ko` (Korean place names). If you leave it empty or set `auto`, it follows the browser language.
   - Click **Save**.
4. Click **Activate** on the card. A newly added GIS input is **created in the off state**, so this step is easy to miss.

### 3. Overlay other maps (optional) { #step-3 }

If you add more maps from the same **Select GIS Service** list and **Activate** them, they appear under the **Layers** button on the map screen.
In the layers window, you choose only one **Base Map** at a time, and you can turn on several **Overlay** maps on top of the background.
The background you chose last is remembered and appears again the next time you open the map.

| Map | Key | Use |
|---|---|---|
| Esri World Imagery | Not needed | To compare with other satellite imagery |
| OpenStreetMap | Not needed | Road map |
| VWorld | Needed (issued at [vworld.kr](https://www.vworld.kr/)) | Korean aerial photos and cadastral maps, importing parcel boundaries by address |

### 4. Set the start location { #step-4 }

1. Open Settings → **Map** (page title: Spatial Design Studio).
2. Click the **Settings** button at the top right → under **Default Start Location**, enter latitude, longitude, and zoom, or move the map to your site,
   click **Get Location**, and then click **Save**.

The start location is used only for **maps you create from now on**. An existing map opens where you last viewed it.

### 5. Create and divide maps { #step-5 }

When you open the map screen for the first time, one map named **My design** already exists. Click **Edit** and change **Name**
in the **Map Settings** dialog to a name that is easy to recognize. You can draw every site and facility you manage on this one map.

When there is one map, you move between sites with the **Site List**. Click **Site List** in the tools on the left of the map to see
the site names, and click a name to move the map to that site. The dashboard map widget has the same button
([Dashboard setup](g10-dashboard.md#step-5)).

Dividing maps helps in these cases.

| Case | If you divide maps |
|---|---|
| Each person must be able to operate different sites | Use **Select Group** in **Map Settings** to choose the groups that can operate that map. The data is visible to everyone; only operations such as saving and deleting shapes are limited to those groups |
| You need to exchange one site separately | **Export Map** / **Import Map** under **Data Processing** below the map screen work per map |
| You want a separate map for each site on the dashboard | A map widget shows one map |

To create more maps, choose **Create New Map** in the **Select a Map** box. A new map is saved right away
with the name "New Design Map" and opens at the start location from [step 4](#step-4). Click the **Edit** button and rename it.

### 6. Draw the site { #step-6 }

1. In the row of tabs along the bottom edge of the map (Site, Zone, Facility, Plot, Equipment, A), choose **Site**.
2. In the drawing tools on the right, choose **Polygon** and click the corners of the site boundary one by one.
   Press the **right mouse button** to join the last point to the first and complete the shape (if you placed three or more points, you can also finish with a double-click or Esc).
   While drawing, remove a wrongly placed point with Backspace. There are also rectangle and circle tools.
3. **Double-click** the name text in the middle of the shape to open the name window. Enter the site name and click **Save**.
   A newly drawn site is named "New Site" at first.

**Changing the shape**: click **Edit Layers** in the tools on the right and select the shape; points appear at the corners and at the middle of each side.
Drag a corner to move it. **Clicking or dragging the point in the middle of a side creates a new corner there**, so you can make the shape you want.
When you are done, click **Save**; to undo, click **Cancel**. Changes are not saved automatically while you edit.

**Importing a site by address (Republic of Korea)**: if you have registered and activated a VWorld map in GIS Input ([step 3](#step-3)), you can use
**Add from Address → Search** in the site drawer to turn parcel boundaries into a site as they are.

- **Address Input** tab: you can enter several addresses, one per line (**+ Add Address** or Enter). Click **Search** to show the parcels found on the map.
- **CSV Batch** tab: find many at once from a CSV file (UTF-8, no header row) with one address per line in the first column, using **Choose CSV File** → **Upload and Process**.
- When search results appear, **Merge Adjacent Parcels**, **Site Name**, and **Save as Site** show up below. With **Merge Adjacent Parcels** on, the parcels found are **all merged into one site**; with it off, one site is created for each parcel.
- Check the **Site Name** and click **Save as Site**. Parcels that already exist on the same map are skipped.

### 7. Divide the zones { #step-7 }

On the **Zone** tab, draw zones the same way as the site and give them names.

- Draw zones **inside the site**. AoT decides which site a zone belongs to from the position of the shape.
- Draw zones so that they **do not overlap**. A sensor or plot placed where two zones overlap is treated as belonging to the
  **smaller zone** of the two, which may not be what you intended.
- You do not need to make a zone for land where you will place no sensors, devices, or plots.

### 8. Create facilities { #step-8 }

Buildings with a structure, such as greenhouses, barns, and storehouses, are not drawn with lines. You create them on the **Facility screen**.

1. Open Settings → **Facility**. The step bar at the top shows Basics · Position & Structure · Envelope · Equipment Layout · Connections · Plot · Review, in that order.
2. **Basics**: click **+ New Facility** → enter the name, preset, span (width), eave height, ridge height, length, and roof type.
3. **Position & Structure**: choose the map and the site. For a greenhouse with several joined bays, set the structure to **Multi-span** and enter the number of bays.
   Click **Place on Map**, click the center of the facility on the map, then drag to fit it and adjust the rotation angle.
   On a map with no site, the **Place on Map** button does not appear. Draw a site first ([step 6](#step-6)).
4. Click **Save Facility**.

!!! note "Do not draw on the Facility tab of the map screen"
    If you draw a facility outline with lines on the map screen, you get only a shape with no size or structure, and clicking it does not open
    a facility. Always create facilities on the Facility screen.

### 9. Create plots { #step-9 }

**Open-field plots**: draw a rectangle or polygon on the **Plot** tab of the map screen, and the **New plot** window opens.
Enter the kind, item, variety, plot name, program, start date, and expected end date, then save. To divide one zone into
several plots of the same size, use **Split into plots**.

**Facility plots**: the **Plot** step of the Facility screen has a box for each zone you divided in **Position & Structure**. In the box of the zone
where the plot goes, click **Add a plot**, enter the kind, item and so on, then enter a **Share** (the percentage of that zone it takes up) instead of an area and click **Save**.
This step opens only after you save the facility.

!!! note "End the plot after its expected end date passes"
    A plot stays "in progress" until someone ends it. If you leave a finished plot as it is, an environment control that uses
    that plot's stage targets can keep following an old target.

## Check { #check }

You are done when the map screen shows **zones inside the site and plots inside the zones**, and clicking a facility opens its facility information.

- Check that both map design and the dashboard map widget show the map background you turned on.
- Check that the **Design Information** card below the map shows as many sites and zones as you drew.
- Check that no shape is still left with its initial name, such as "New Site" or "New Zone".
- If the zone areas add up to more than the site area, something overlaps. Fix the overlap.

## Site A { #site-a }

Site A is a site of about 30,000 ㎡ with both open fields and a facility.

| What you draw | Contents |
|---|---|
| Site | All of Site A |
| Zone | Open field 3-1 (about 10,000 ㎡), 3-2 (about 12,000 ㎡) |
| Facility | 1 single-span greenhouse (339 ㎡), pump house, office building, storehouse |
| Plot | Beans in 3-1, black beans in 3-2, lettuce in the greenhouse (3 of 12 beds) |

The rest of the land, which has no sensors or plots, was not divided into zones.

## Site B { #site-b }

At Site B, one facility is the whole site.

| What you draw | Contents |
|---|---|
| Site | The lot where the greenhouse stands |
| Zone | None |
| Facility | 1 six-bay multi-span greenhouse (1,596 ㎡, vent area 642 ㎡) |
| Plot | 1 plot that uses half of the greenhouse |

There is no open field, so no zones are drawn. The time goes into entering the number of bays, width, and length accurately on the Facility screen.
Environment control uses these dimensions to calculate the window area and the greenhouse volume.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| The map shows only country borders | There is no MapTiler Vector input, or you added it but did not **Activate** it ([step 2](#step-2)) |
| The map background is gray or blank | The MapTiler key is wrong, the address you are using is missing from the key's allowed addresses, or this month's usage is over the limit ([step 1](#step-1)) |
| A shape you drew disappears after reloading | Its lines cross. Draw it again |
| Clicking a facility does not open it | It is a facility drawn with lines on the map screen. Delete it and create it again on the Facility screen |
| The facility Plot step is empty | Save the facility first |
| Several "New Site" entries appear in the site list or the facility's site selection | You did not rename the sites. Double-click the label to rename it ([step 6](#step-6)) |
| A polygon does not finish | Clicking the first point again does not close it. Finish with the right mouse button (or a double-click, or Esc) |
| Importing by address does not work | Check that a VWorld input is registered and activated and that its key is correct |

## Learn more { #more }

- [Getting started with GIS](../geo/getting-started.md)
- [Map design tool](../geo/design-tool.md)
- [Facility management](../geo/facility.md)
- [Plots](../geo/plots.md)
- [GIS layers](../geo/layers.md)
- [GIS settings](../geo/settings.md)
