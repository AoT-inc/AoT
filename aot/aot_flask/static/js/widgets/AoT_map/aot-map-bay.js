// aot-map-bay.js — facility bay(구역) shared helpers for AoT Map widgets.
//
// Stateless module (no markers, no polling). The vector widget composes these
// helpers with aot-map-popup.js builders to render per-bay chips and the bay
// monitoring/control modal.
//
// Server contract:
//   facility.bay_slices            — [{id, index, name, crop, x_min, x_max, x_center}]
//                                    (facility_bays.compute_bay_slices; [] when < 2 bays)
//   runtime.fitting_sensors[].bay_id        — sensor attribution (null = common)
//   runtime.actuator_states[*].bay_ids      — actuator attribution ([] = common)
//
// Public API:
//   window.AoTMapBay = {
//     slices(facility)                  → bay slice array ([] when zoning inactive)
//     centerLngLat(facility, slice)    → [lng, lat] of the bay center (null on failure)
//     filterSensors(sensors, bayId)    → fitting_sensors belonging to the bay
//     filterStates(states, bayId)      → actuator_states subset for the bay
//   }
(function () {
  'use strict';

  // 구역 슬라이스. 단동(bay 1개)도 서버가 슬라이스 1개를 주므로 칩이 생성된다.
  // 슬라이스 1개 = 단동 또는 모든 bay 를 한 구역으로 통합한 경우.
  function slices(facility) {
    var s = facility && facility.bay_slices;
    return Array.isArray(s) ? s : [];
  }

  // ── Local meters → lng/lat ──────────────────────────────────────────────────
  // Same transform as aot-map-sensor-labels.js _toLngLat: facility center +
  // orientation_deg rotation + Mercator meter offset. The bay center sits at
  // local (x_center, length/2).
  function _facilityCenter(facility) {
    if (facility.lat != null && facility.lng != null) return [facility.lng, facility.lat];
    var g3d = facility.geometry_3d;
    if (g3d && g3d.center_lng != null && g3d.center_lat != null) {
      return [g3d.center_lng, g3d.center_lat];
    }
    var feat = facility.outer_feature;
    if (!feat) return null;
    var geom = feat.type === 'Feature' ? (feat.geometry || {}) : feat;
    if (geom.type !== 'Polygon') return null;
    var ring = (geom.coordinates || [])[0];
    if (!ring || !ring.length) return null;
    var sx = 0, sy = 0;
    for (var k = 0; k < ring.length; k++) { sx += ring[k][0]; sy += ring[k][1]; }
    return [sx / ring.length, sy / ring.length];
  }

  function centerLngLat(facility, slice) {
    if (!facility || !slice || !window.maplibregl) return null;
    var center = _facilityCenter(facility);
    if (!center) return null;
    var g3d = facility.geometry_3d || {};
    var cx = 0, cz = 0;
    try {
      var spanW = parseFloat(g3d.span_width_m || 0);
      var length = parseFloat(g3d.length_m || 0);
      var bayCount = parseInt(facility.bay_count || 1, 10);
      var spacing = parseFloat(g3d.spacing_m || 0);
      var isConnected = facility.structure === 'connected';
      var effSpacing = isConnected ? 0 : spacing;
      var totalWidth = bayCount * spanW + (bayCount - 1) * effSpacing;
      cx = totalWidth / 2;
      cz = length / 2;
    } catch (e) { return null; }

    var x = (parseFloat(slice.x_center) || 0) - cx;
    var z = 0;   // bay center along length = cz → z offset 0

    var orientDeg = parseFloat(g3d.orientation_deg) || 0;
    var theta = orientDeg * Math.PI / 180.0;
    var rx = x * Math.cos(theta) + z * Math.sin(theta);
    var rz = -x * Math.sin(theta) + z * Math.cos(theta);

    var merc = window.maplibregl.MercatorCoordinate.fromLngLat(
      { lng: center[0], lat: center[1] }, 0);
    var unit = merc.meterInMercatorCoordinateUnits();
    var ll = new window.maplibregl.MercatorCoordinate(
      merc.x + rx * unit, merc.y + rz * unit, merc.z).toLngLat();
    return [ll.lng, ll.lat];
  }

  // ── Runtime data filters ───────────────────────────────────────────────────
  function filterSensors(sensors, bayId) {
    return (sensors || []).filter(function (s) {
      return s && s.bay_id === bayId;
    });
  }

  // Actuators attributed to the bay. includeCommon=true 면 시설 공통
  // (bay_ids = []) 액추에이터도 포함 — 단동(슬라이스 1개) 시설은 구역 칩이
  // 유일한 진입점이므로 공통 장치를 함께 보여준다.
  function filterStates(states, bayId, includeCommon) {
    var out = {};
    Object.keys(states || {}).forEach(function (sk) {
      var s = states[sk];
      if (!s) return;
      var ids = Array.isArray(s.bay_ids) ? s.bay_ids : [];
      if (ids.indexOf(bayId) !== -1 || (includeCommon && ids.length === 0)) {
        out[sk] = s;
      }
    });
    return out;
  }

  window.AoTMapBay = {
    slices: slices,
    centerLngLat: centerLngLat,
    filterSensors: filterSensors,
    filterStates: filterStates
  };
})();
