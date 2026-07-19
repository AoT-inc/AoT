# AoT Marker Manager

MapLibre-GL Marker and Popup Management Module

## Features

- **Marker Lifecycle Management**: Add, remove, update markers with ease
- **Marker Types**: Built-in support for Site, Zone, Facility, and Custom markers
- **Custom HTML Markers**: Use your own HTML/CSS for marker visualization
- **Popup Management**: Built-in popup support with customizable content
- **Marker Grouping**: Group markers for batch operations and visibility control
- **Event Handling**: Click, hover, and drag event support
- **Leaflet API Compatibility**: L.marker() compatible interface for easy migration
- **Statistics**: Built-in marker counting and statistics

## Quick Start

```javascript
// Initialize map
const map = new maplibregl.Map({
  container: 'map',
  style: { /* your style */ },
  center: [127.0, 37.5],
  zoom: 10
});

// Create marker manager
const markerManager = AoTMarkerManager.create(map);

// Add a site marker
markerManager.addSiteMarker('site-1', {
  coordinates: [127.0, 37.5],
  label: 'Site A',
  popup: {
    content: '<h3>Site A</h3><p>Active</p>',
    maxWidth: 300
  }
});
```

## API Reference

### Creating Marker Manager

```javascript
const manager = AoTMarkerManager.create(map, {
  defaultIcons: true,     // Use default FontAwesome icons
  showLabels: true,       // Show marker labels
  clusterMarkers: false,  // Enable clustering (future)
  defaultStyles: {        // Customize default marker styles
    site: { color: '#2196F3', size: 32, icon: 'fa-map-marker' }
  }
});
```

### Adding Markers

```javascript
// Site marker
manager.addSiteMarker('site-1', {
  coordinates: [127.0, 37.5],
  label: 'Site A'
});

// Zone marker
manager.addZoneMarker('zone-1', {
  coordinates: [127.1, 37.6],
  label: 'Zone 1'
});

// Facility marker
manager.addFacilityMarker('facility-1', {
  coordinates: [127.2, 37.7],
  label: 'Facility 1'
});

// Custom HTML marker
manager.addCustomMarker('custom-1', {
  coordinates: [127.3, 37.8],
  html: '<div class="my-marker">🚜</div>',
  className: 'harvest-marker'
});

// Full options
manager.addMarker('marker-1', {
  coordinates: [127.0, 37.5],
  type: 'site',
  label: 'My Site',
  draggable: true,
  clickable: true,
  hoverable: true,
  popup: {
    content: '<b>Hello</b><br>Popup content',
    maxWidth: 300,
    closeButton: true,
    closeOnClick: false
  }
});
```

### Removing Markers

```javascript
// Remove single marker
manager.removeMarker('site-1');

// Clear all markers
manager.clearAllMarkers();
```

### Working with Popups

```javascript
// Show popup for marker
manager.showPopup('site-1');

// Hide popup for marker
manager.hidePopup('site-1');

// Update popup content
manager.updatePopupContent('site-1_popup', '<b>Updated!</b>');
```

### Marker Groups

```javascript
// Create a group
manager.addMarkerGroup('irrigation-group', ['zone-1', 'zone-2', 'zone-3'], {
  label: 'Irrigation Zones',
  color: '#4CAF50'
});

// Set group visibility
manager.setGroupVisibility('irrigation-group', false);

// Get markers in group
const markers = manager.getGroupMarkers('irrigation-group');

// Remove group (keeps markers)
manager.removeGroup('irrigation-group');
```

### Event Handling

```javascript
const marker = manager.getMarker('site-1');

// Click event
marker.on('click', function(data) {
  console.log('Clicked:', data.markerId, data.coordinates);
});

// Hover events
marker.on('mouseover', function(data) {
  console.log('Hovered:', data.markerId);
});

marker.on('mouseout', function(data) {
  console.log('Left:', data.markerId);
});

// Drag events (when draggable: true)
marker.on('dragstart', function(data) { /* ... */ });
marker.on('drag', function(data) { /* ... */ });
marker.on('dragend', function(data) { /* ... */ });

// Remove event handler
marker.off('click', myHandler);
```

### Bulk Operations

```javascript
// Add multiple markers at once
manager.addSiteMarkers([
  { id: 'site-1', coordinates: [127.0, 37.5], label: 'Site 1' },
  { id: 'site-2', coordinates: [127.1, 37.6], label: 'Site 2' },
  { id: 'site-3', coordinates: [127.2, 37.7], label: 'Site 3' }
]);

manager.addZoneMarkers([...]);
manager.addFacilityMarkers([...]);
```

### Statistics

```javascript
// Get all statistics
const stats = manager.getStats();
// Returns:
// {
//   totalMarkers: 10,
//   byType: { site: 3, zone: 4, facility: 3 },
//   byGroup: { 'group-1': 4 },
//   markers: [...]
// }

// Get marker count
manager.getMarkerCount();

// Fit map to all markers
manager.fitBounds({ padding: 50, maxZoom: 15 });
```

### Leaflet API Compatibility

```javascript
// Create Leaflet-style marker
const marker = AoTMarkerManager.marker([37.5, 127.0], {
  draggable: true
});

marker.addTo(map);
marker.bindPopup('<b>Hello!</b>');

marker.on('click', function() {
  marker.openPopup();
});
```

## Marker Types

| Type | Default Color | Default Size | Icon |
|------|---------------|--------------|------|
| site | #2196F3 (Blue) | 32px | fa-map-marker-alt |
| zone | #4CAF50 (Green) | 24px | fa-square |
| facility | #FF9800 (Orange) | 20px | fa-industry |
| custom | - | - | User defined |

## CSS Classes

```css
/* Marker container */
.aot-marker-container

/* Default marker icon */
.aot-marker-icon
.aot-marker-site
.aot-marker-zone
.aot-marker-facility
.aot-custom-marker

/* Marker label */
.aot-marker-label

/* Popup */
.aot-popup
```

## Files

- `aot-maplibre-marker.js` - Main module (1522 lines)
- `aot-maplibre-marker.d.ts` - TypeScript definitions
- `test_marker.html` - Interactive test page

## Testing

Open `test_marker.html` in a browser to test all functionality:

```bash
# Using Python simple server
cd /path/to/geo
python -m http.server 8080

# Or using Node.js
npx serve .
```

Then navigate to `http://localhost:8080/test_marker.html`

## Browser Compatibility

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

Requires MapLibre-GL JS 3.x
