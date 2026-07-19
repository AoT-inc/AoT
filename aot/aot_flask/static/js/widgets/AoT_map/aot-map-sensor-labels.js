// aot-map-sensor-labels.js — MapLibre marker labels for facility sensors.
//
// For each facility in the provided list, creates one MapLibre marker per
// fitting(kind=sensor), positioned using facility center + orientation_deg +
// local meters. Periodically polls /api/aot/facility/<uuid>/runtime to fetch
// the latest channel values, then renders via window.AoTSensorLabel.formatLabel.
//
// Public API:
//   window.AoTMapSensorLabels = {
//     attach(uniqueId, map, facilities, opts) — installs markers + starts polling
//     detach(uniqueId)
//   }
(function () {
  'use strict';

  // uniqueId → { markers, pollTimer, opts, facilities, unsubscribeCull, culled }
  var STATE = {};

  // ── Label color bands (5 stages) ────────────────────────────────────────────
  // Colors the label background using the per-measurement 5-stage upper bounds
  // from facility.view_options.sensor_ranges. Uses defaults when unset. Keeps the
  // same palette/defaults as the design panel (geo_facility.html) SensorRangesUI /
  // aot-facility-sensor-labels.js.
  // Global palette for the 5 measurement bands: reads --aot-band-1..5 CSS tokens
  // (settings/custom_ui band_1..5 로 사용자 정의 가능) with literal fallbacks.
  var BAND_PALETTE = (function () {
    var defaults = ['#2DB4FF', '#54BCC1', '#32c85a', '#FEAE5F', '#CF5C58'];
    try {
      var cs = getComputedStyle(document.documentElement);
      return defaults.map(function (c, i) {
        var v = cs.getPropertyValue('--aot-band-' + (i + 1)).trim();
        return v || c;
      });
    } catch (e) { return defaults; }
  })();
  var DEFAULT_RANGES = {
    T:       [10, 18, 26, 34, 45],
    RH:      [40, 55, 70, 85, 100],
    VPD:     [0.4, 0.8, 1.2, 1.6, 3.0],
    light:   [200, 400, 600, 800, 1200],
    wind_ms: [2, 4, 6, 9, 15]
  };

  // For items with inverted meaning (e.g. humidity), use the default palette in reverse order
  var REVERSE_KEYS = { RH: true };
  function _defColors(key) {
    return REVERSE_KEYS[key] ? BAND_PALETTE.slice().reverse() : BAND_PALETTE;
  }

  // Resolve key → { stages:[5], colors:[5] }. Supports the new format ({stages,colors}),
  // the legacy format (array), and unset (defaults). Returns null when no match.
  function _resolveBand(key, ranges) {
    var def = ranges && ranges[key];
    if (Array.isArray(def)) return { stages: def, colors: _defColors(key) };
    if (def && Array.isArray(def.stages)) {
      return {
        stages: def.stages,
        colors: (Array.isArray(def.colors) && def.colors.length) ? def.colors : _defColors(key)
      };
    }
    var d = DEFAULT_RANGES[key];
    return d ? { stages: d, colors: _defColors(key) } : null;
  }

  function _bandColor(key, value, ranges) {
    if (value == null || isNaN(value)) return null;
    var b = _resolveBand(key, ranges);
    if (!b || !b.stages.length) return null;
    for (var i = 0; i < b.stages.length; i++) {
      var hi = parseFloat(b.stages[i]);
      if (isNaN(hi)) continue;
      if (value <= hi) return b.colors[Math.min(i, b.colors.length - 1)];
    }
    return b.colors[b.colors.length - 1];
  }

  // Band color of the representative channel (first channel with a value and band defined) in the channel list.
  function _bandColorForChannels(channels, ranges) {
    for (var i = 0; i < (channels || []).length; i++) {
      var c = channels[i];
      if (!c || c.value == null) continue;
      var color = _bandColor(c.key, +c.value, ranges);
      if (color) return color;
    }
    return null;
  }

  // Readable text color based on background brightness (dark gray on light, white on dark).
  function _textOn(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return '#f8fafc';
    var n = parseInt(m[1], 16);
    var r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    var lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return lum > 0.6 ? '#1a1a1a' : '#f8fafc';
  }

  // facilityUuid → sensor_ranges (null if unset → defaults used)
  function _facilityRanges(st, facilityUuid) {
    var facs = (st && st.facilities) || [];
    for (var i = 0; i < facs.length; i++) {
      if (facs[i] && facs[i].unique_id === facilityUuid) {
        var vo = facs[i].view_options || {};
        return vo.sensor_ranges || null;
      }
    }
    return null;
  }

  function _posToXYZ(p) {
    if (!p) return null;
    if (Array.isArray(p)) {
      if (p.length < 3) return null;
      return [parseFloat(p[0]) || 0, parseFloat(p[1]) || 0, parseFloat(p[2]) || 0];
    }
    if (typeof p === 'object' && (p.x != null || p.y != null || p.z != null)) {
      return [parseFloat(p.x) || 0, parseFloat(p.y) || 0, parseFloat(p.z) || 0];
    }
    return null;
  }

  function _toLngLat(facility, fitting, offsetY) {
    var center = _facilityCenter(facility);
    if (!center) return null;
    var g3d = facility.geometry_3d || {};
    var cx  = parseFloat(g3d.span_width_m || 0) * 0; // placeholder; fittings use group-local coords
    var cz  = parseFloat(g3d.length_m || 0)     * 0;
    // Match aot-facility-map-3d.js: tCenter uses group.userData.cx/cz computed at
    // buildFacilityMesh time. Approximate cx, cz from geometry_3d (total width/length / 2).
    try {
      var spanW = parseFloat(g3d.span_width_m || 0);
      var length = parseFloat(g3d.length_m || 0);
      var bayCount = parseInt(facility.bay_count || 1, 10);
      var spacing = parseFloat(g3d.spacing_m || 0);
      var isConnected = facility.structure === 'connected';
      var unitCount = isConnected ? 1 : bayCount;
      var meshBayCount = isConnected ? bayCount : 1;
      var effSpacing = isConnected ? 0 : spacing;
      var unitWidth = meshBayCount * spanW + (meshBayCount - 1) * effSpacing;
      var totalWidth = unitCount * unitWidth + (unitCount - 1) * effSpacing;
      cx = totalWidth / 2;
      cz = length / 2;
    } catch (e) { /* keep zeros */ }

    var xyz = _posToXYZ(fitting.position);
    if (!xyz) return null;
    var x = xyz[0] - cx;
    var z = xyz[2] - cz;

    var orientDeg = parseFloat(g3d.orientation_deg) || 0;
    var theta = orientDeg * Math.PI / 180.0;
    // rotY (Three.js) applied via M*v: x' = x*cos + z*sin, z' = -x*sin + z*cos
    var rx = x * Math.cos(theta) + z * Math.sin(theta);
    var rz = -x * Math.sin(theta) + z * Math.cos(theta);

    // Mercator delta in 'meters' converted via maplibregl helper.
    if (!window.maplibregl) return null;
    var merc = window.maplibregl.MercatorCoordinate.fromLngLat(
      { lng: center[0], lat: center[1] }, 0);
    var unit = merc.meterInMercatorCoordinateUnits();
    var fittingMerc = new window.maplibregl.MercatorCoordinate(
      merc.x + rx * unit,
      merc.y + rz * unit,
      merc.z
    );
    var ll = fittingMerc.toLngLat();
    return [ll.lng, ll.lat];
  }

  function _facilityCenter(facility) {
    if (facility.lat != null && facility.lng != null) return [facility.lng, facility.lat];
    var g3d = facility.geometry_3d;
    if (g3d && g3d.center_lng != null && g3d.center_lat != null) {
      return [g3d.center_lng, g3d.center_lat];
    }
    var feat = facility.outer_feature;
    if (!feat) return null;
    var geom = feat.type === 'Feature' ? (feat.geometry || {}) : feat;
    if (geom.type === 'Polygon') {
      var ring = (geom.coordinates || [])[0];
      return ring && ring.length ? _ringCentroid(ring) : null;
    }
    return null;
  }

  function _ringCentroid(ring) {
    var area = 0, cx = 0, cy = 0, n = ring.length;
    for (var i = 0, j = n - 1; i < n; j = i++) {
      var xi = ring[i][0], yi = ring[i][1];
      var xj = ring[j][0], yj = ring[j][1];
      var cross = xi * yj - xj * yi;
      area += cross; cx += (xi + xj) * cross; cy += (yi + yj) * cross;
    }
    area /= 2;
    if (Math.abs(area) < 1e-12) {
      var sx = 0, sy = 0;
      for (var k = 0; k < n; k++) { sx += ring[k][0]; sy += ring[k][1]; }
      return [sx / n, sy / n];
    }
    return [cx / (6 * area), cy / (6 * area)];
  }

  function _applyStyle(el, opts) {
    el.style.background = opts.bg || 'rgba(15,23,42,0.78)';
    el.style.color      = opts.fg || '#f8fafc';
    el.style.fontSize   = (opts.size_em || 0.85) + 'em';
    el.style.opacity    = opts.opacity != null ? opts.opacity : 0.7;
  }

  function attach(uniqueId, map, facilities, opts) {
    detach(uniqueId);
    if (!map || !window.maplibregl) return;
    if (opts.show === false) return;
    if (!Array.isArray(facilities) || !facilities.length) return;

    var markers = [];

    facilities.forEach(function (facility) {
      var fittings = (facility.fittings || []).filter(function (f) {
        return f && f.kind === 'sensor' && _posToXYZ(f.position);
      });
      fittings.forEach(function (f) {
        var lngLat = _toLngLat(facility, f, opts.offset_y || 0);
        if (!lngLat) return;

        var el = document.createElement('div');
        el.className = 'aot-sensor-map-marker' +
          (opts.style === 'circle' ? ' aot-sensor-map-marker--circle' : '');
        el.dataset.fittingId  = f.id;
        el.dataset.facilityId = facility.unique_id;
        el.textContent = '—';
        _applyStyle(el, opts);
        // Stacking priority vs geo-design labels. MapLibre markers each form a
        // transform stacking context, so an explicit z-index is required — otherwise
        // (auto) these fall under zone labels (z-index 3) regardless of DOM order.
        if (opts.priority_z != null) el.style.zIndex = String(opts.priority_z);

        if (opts.popup !== false) {
          el.style.cursor = 'pointer';
          el.addEventListener('click', function (ev) {
            ev.stopPropagation();
            var st = STATE[uniqueId];
            if (!st) return;
            var key = facility.unique_id + ':' + f.id;
            var sensor = (st.sensorsByKey && st.sensorsByKey[key]) || _fallbackSensor(f);
            if (window.AoTSensorLabel) {
              // Map widget host: the map container element (DOM ancestor of MapLibre canvas).
              var host = map.getContainer ? map.getContainer() : null;
              window.AoTSensorLabel.openPopup(sensor, {
                decimals: opts.decimals,
                anchorEvent: ev,
                host: host,
                modal: true   // Render as a screen-centered modal, like the control label
              });
            }
          });
        }

        var marker = new window.maplibregl.Marker({ element: el, anchor: 'bottom' })
          .setLngLat(lngLat)
          .addTo(map);

        markers.push({
          marker: marker, el: el, fittingId: f.id,
          facilityUuid: facility.unique_id, fitting: f
        });
      });
    });

    STATE[uniqueId] = {
      markers: markers,
      opts: opts,
      facilities: facilities,
      sensorsByKey: {},
      pollTimer: null,
      unsubscribeCull: null,
      culled: false,
      map: map,
      spreadHandler: null
    };

    // Label collision avoidance: re-layout in screen coordinates when map move/zoom ends.
    if (opts.collision !== false) {
      var _spreadRaf = null;
      var spreadHandler = function () {
        if (_spreadRaf) return;
        _spreadRaf = requestAnimationFrame(function () {
          _spreadRaf = null;
          _spreadLabels(uniqueId);
        });
      };
      map.on('moveend', spreadHandler);
      map.on('zoomend', spreadHandler);
      STATE[uniqueId].spreadHandler = spreadHandler;
    }

    // Subscribe to facility 3D cull state — labels share visibility with the
    // facility meshes so the overlay stays consistent with the underlying scene.
    if (window.AoTFacilityMap3D && typeof window.AoTFacilityMap3D.onCullChange === 'function') {
      try {
        STATE[uniqueId].unsubscribeCull = window.AoTFacilityMap3D.onCullChange(map, function (hidden) {
          var st = STATE[uniqueId];
          if (!st) return;
          st.culled = !!hidden;
          st.markers.forEach(function (m) {
            m.el.style.display = (hidden || st._manualHidden) ? 'none' : '';
          });
        });
      } catch (e) {
      }
    }

    _refreshAll(uniqueId);
    var interval = Math.max(30, parseInt(opts.refresh_seconds || 60, 10)) * 1000;
    STATE[uniqueId].pollTimer = setInterval(function () { _refreshAll(uniqueId); }, interval);
  }

  function _fallbackSensor(fitting) {
    return {
      fitting_id: fitting.id,
      name: fitting.name || fitting.id,
      position: fitting.position,
      sensor_role: fitting.sensor_role || 'indoor',
      device_id: fitting.input_id || '',
      device_name: null,
      channels: []
    };
  }

  function _refreshAll(uniqueId) {
    var st = STATE[uniqueId];
    if (!st) return;
    var uniqueFacs = {};
    st.markers.forEach(function (m) { uniqueFacs[m.facilityUuid] = true; });

    Object.keys(uniqueFacs).forEach(function (uuid) {
      // 공용 런타임 프로바이더 — 액추에이터 라벨 폴러와 동일 /runtime 을
      // 공유(중복 요청 제거). 저사양 호스트에서 요청 다발을 줄인다.
      var _rt = window.AoTFacilityRuntime
        ? window.AoTFacilityRuntime.get(uuid)
        : fetch('/api/aot/facility/' + encodeURIComponent(uuid) + '/runtime')
            .then(function (r) { return r.ok ? r.json() : null; });
      _rt
        .then(function (data) {
          if (!data || !Array.isArray(data.fitting_sensors)) return;
          var st2 = STATE[uniqueId];
          if (!st2) return;
          data.fitting_sensors.forEach(function (s) {
            st2.sensorsByKey[uuid + ':' + s.fitting_id] = s;
          });
          _renderLabels(uniqueId, uuid, data.fitting_sensors);
        })
        .catch(function (e) { /* silent */ });
    });
  }

  function _renderLabels(uniqueId, facilityUuid, fittingSensors) {
    var st = STATE[uniqueId];
    if (!st) return;
    var byId = {};
    fittingSensors.forEach(function (s) { byId[s.fitting_id] = s; });
    var ranges  = _facilityRanges(st, facilityUuid);
    var defBg   = (st.opts && st.opts.bg) || 'rgba(15,23,42,0.78)';
    var defFg   = (st.opts && st.opts.fg) || '#f8fafc';
    st.markers.forEach(function (m) {
      if (m.facilityUuid !== facilityUuid) return;
      var sensor = byId[m.fittingId];
      if (!sensor || !sensor.channels) {
        m.el.textContent = '—';
        m.el.classList.remove('aot-stale');
        m.el.style.background = defBg;
        m.el.style.color      = defFg;
        return;
      }
      var color;
      if (st.opts.style === 'circle') {
        // Circle mode: integer value of the first channel only; band color from
        // the same channel. Full label text moves to the tooltip.
        var first = null;
        for (var ci = 0; ci < sensor.channels.length; ci++) {
          if (sensor.channels[ci] && sensor.channels[ci].value != null) { first = sensor.channels[ci]; break; }
        }
        m.el.textContent = first ? String(Math.round(+first.value)) : '—';
        var circleTitle = window.AoTSensorLabel
          ? sensor.name + ' ' + window.AoTSensorLabel.formatLabel(sensor.channels, { maxChannels: 9 })
          : (sensor.name || '');
        if (window.AoTSetTitle) window.AoTSetTitle(m.el, circleTitle); else m.el.title = circleTitle;
        color = first ? _bandColor(first.key, +first.value, ranges) : null;
      } else {
        m.el.textContent = window.AoTSensorLabel
          ? window.AoTSensorLabel.formatLabel(sensor.channels, {
              maxChannels: st.opts.max_channels || 1,
              decimals: st.opts.decimals
            })
          : '—';
        color = _bandColorForChannels(sensor.channels, ranges);
      }
      var anyValid = sensor.channels.some(function (c) { return c.valid; });
      m.el.classList.toggle('aot-stale', !anyValid);
      // Apply label background color based on the measurement band
      if (color) {
        m.el.style.background = color;
        m.el.style.color      = _textOn(color);
      } else {
        m.el.style.background = defBg;
        m.el.style.color      = defFg;
      }
    });
    // Label text (width) may have changed, so recompute collision avoidance.
    _spreadLabels(uniqueId);
  }

  // ── Label collision avoidance ───────────────────────────────────────────────
  // Instead of hiding overlapping labels, push them downward on screen to keep a
  // consistent gap. Applies a pixel offset via MapLibre Marker.setOffset([0, dy]),
  // so the relative position to the anchor is preserved even after the map moves.
  function _spreadLabels(uniqueId) {
    var st = STATE[uniqueId];
    if (!st || !st.markers || !st.markers.length) return;
    if (st.opts && st.opts.collision === false) return;
    var gap = (st.opts && !isNaN(parseFloat(st.opts.spacing))) ? parseFloat(st.opts.spacing) : 0;
    gap = Math.max(gap, 2);

    // 1) Reset existing offsets, then measure the original positions.
    st.markers.forEach(function (m) {
      if (m._offY) { try { m.marker.setOffset([0, 0]); } catch (e) {} m._offY = 0; }
    });

    requestAnimationFrame(function () {
      var st2 = STATE[uniqueId];
      if (!st2) return;
      var items = [];
      st2.markers.forEach(function (m) {
        if (m.el.style.display === 'none') return;
        var r = m.el.getBoundingClientRect();
        if (r.width < 1) return;
        items.push({ m: m, left: r.left, right: r.right, top: r.top, bottom: r.bottom });
      });
      // Process top to bottom, pushing downward whenever there is an overlap.
      items.sort(function (a, b) { return a.top - b.top; });
      var placed = [];
      items.forEach(function (it) {
        var dy = 0, moved = true, guard = 0;
        while (moved && guard < 200) {
          moved = false; guard++;
          for (var i = 0; i < placed.length; i++) {
            var p = placed[i];
            var horiz = !(it.right + gap <= p.left || it.left >= p.right + gap);
            var vTop = it.top + dy, vBot = it.bottom + dy;
            var vert = !(vBot + gap <= p.top || vTop >= p.bottom + gap);
            if (horiz && vert) { dy = (p.bottom + gap) - it.top; moved = true; }
          }
        }
        if (dy > 0) { try { it.m.marker.setOffset([0, dy]); } catch (e) {} it.m._offY = dy; }
        placed.push({ left: it.left, right: it.right, top: it.top + dy, bottom: it.bottom + dy });
      });
    });
  }

  function detach(uniqueId) {
    var st = STATE[uniqueId];
    if (!st) return;
    if (st.pollTimer) clearInterval(st.pollTimer);
    if (st.spreadHandler && st.map) {
      try { st.map.off('moveend', st.spreadHandler); } catch (e) {}
      try { st.map.off('zoomend', st.spreadHandler); } catch (e) {}
    }
    if (typeof st.unsubscribeCull === 'function') {
      try { st.unsubscribeCull(); } catch (e) {}
    }
    (st.markers || []).forEach(function (m) {
      try { m.marker.remove(); } catch (e) {}
    });
    delete STATE[uniqueId];
  }

  function setVisible(uniqueId, visible) {
    var st = STATE[uniqueId];
    if (!st) return;
    st._manualHidden = !visible;
    (st.markers || []).forEach(function (m) {
      if (visible) {
        m.el.style.display = st.culled ? 'none' : '';
      } else {
        m.el.style.display = 'none';
      }
    });
  }

  window.AoTMapSensorLabels = {
    attach: attach, detach: detach, setVisible: setVisible,
    // Shared helpers for the facility sensor summary chip (vector widget)
    bandColor: _bandColor, textOn: _textOn
  };
})();
