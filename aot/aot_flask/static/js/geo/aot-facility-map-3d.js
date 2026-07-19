// aot-facility-map-3d.js — MapLibre Custom Layer: Three.js facility 3D overlay
// MapLibre GL JS v3/v4 compatible.
// Supports multiple simultaneous map instances (map widget + facility widget on same page).
// Each attach() returns an instance handle; global API operates on the last-attached map.
// Depends: THREE (r160+), AoTFacility3D.buildFacilityMesh, maplibregl
(function (global) {
  'use strict';

  var LAYER_ID = 'aot-facility-3d-layer';

  // Base fill-extrusion layers that the Three.js overlay replaces
  var _HIDDEN_LAYERS = ['facility-prod-3d', 'facility-preview-3d'];

  // ── Per-map instance registry ─────────────────────────────────────────────────
  // Keyed by nativeMap reference so each map has independent state.
  var _registry = [];        // [{map, inst}]
  var _lastInst = null;      // most recently attached — used by backward-compat API

  function _findInst(nativeMap) {
    for (var i = 0; i < _registry.length; i++) {
      if (_registry[i].map === nativeMap) return _registry[i].inst;
    }
    return null;
  }

  function _removeInst(nativeMap) {
    _registry = _registry.filter(function (r) { return r.map !== nativeMap; });
    if (_lastInst && _lastInst._map === nativeMap) {
      _lastInst = _registry.length ? _registry[_registry.length - 1].inst : null;
    }
  }

  // ── MapLibre v2/v3/v4 MVP matrix extraction ────────────────────────────────────
  function _getMVP(args) {
    if (!args) return null;
    if (typeof args === 'object' && !ArrayBuffer.isView(args) && !Array.isArray(args)) {
      return args.modelViewProjectionMatrix
          || (args.defaultProjectionData && args.defaultProjectionData.mainMatrix)
          || args.projectionMatrix
          || null;
    }
    // MapLibre v2 / plain array
    return args;
  }

  // ── Mercator helpers ──────────────────────────────────────────────────────────
  function _lngLatToMerc(lng, lat) {
    return maplibregl.MercatorCoordinate.fromLngLat({ lng: lng, lat: lat }, 0);
  }

  function _buildTransform(merc, scaleM, orientDeg, cx, cz) {
    // Convention: model +X = east, +Y = up, +Z = south (matches MapLibre's
    // mercator left-handed system: +X east, +Y south, +Z up).
    //
    // Pipeline (right-multiplied, applied in inverse order to vertices):
    //   tCenter:  center model in its own frame
    //   rotY:     rotate by +orientDeg around vertical (compass CW)
    //   rotX:     90° around X to lay the model down (Y up → Z up)
    //   scale Y=-: flip Y to convert Three.js right-handed → mercator
    //              left-handed (without this, model +Z lands at mercator -Y =
    //              north; with it, model +Z → mercator +Y = south).
    //   trans:    place at facility center mercator coord
    //
    // Net effect: model +X → mercator +X (east), model +Z → mercator +Y (south),
    // model +Y → mercator +Z (up). orientDeg semantics preserved vs old code
    // (rotY sign flip compensates the scale Y flip for compass-CW rotation).
    var tCenter = new THREE.Matrix4().makeTranslation(-(cx || 0), 0, -(cz || 0));
    var rotX    = new THREE.Matrix4().makeRotationX(Math.PI / 2);
    var rotY    = new THREE.Matrix4().makeRotationY(orientDeg * Math.PI / 180);
    var scale   = new THREE.Matrix4().makeScale(scaleM, -scaleM, scaleM);
    var trans   = new THREE.Matrix4().makeTranslation(merc.x, merc.y, merc.z);
    return new THREE.Matrix4()
      .multiply(trans)
      .multiply(scale)
      .multiply(rotX)
      .multiply(rotY)
      .multiply(tCenter);
  }

  // ── Per-instance layer/hide helpers ───────────────────────────────────────────
  function _hideMapLayers(map, inst) {
    (inst._activeHideLayers || []).forEach(function (id) {
      try { if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none'); }
      catch (e) {}
    });
    if (inst._scanHideExtrusions) {
      try {
        var style = map.getStyle();
        if (style && style.layers) {
          style.layers.forEach(function (l) {
            if (l.type === 'fill-extrusion') {
              try { map.setLayoutProperty(l.id, 'visibility', 'none'); } catch (e) {}
            }
          });
        }
      } catch (e) {}
    }
  }

  function _showMapLayers(map, inst) {
    (inst._activeHideLayers || []).forEach(function (id) {
      try { if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'visible'); }
      catch (e) {}
    });
    if (inst._scanHideExtrusions) {
      try {
        var style = map.getStyle();
        if (style && style.layers) {
          style.layers.forEach(function (l) {
            if (l.type === 'fill-extrusion') {
              try { map.setLayoutProperty(l.id, 'visibility', 'visible'); } catch (e) {}
            }
          });
        }
      } catch (e) {}
    }
  }

  // ── Per-facility scene builder ────────────────────────────────────────────────
  function _makeScene(entry) {
    var sc = new THREE.Scene();
    sc.add(new THREE.AmbientLight(0xffffff, 0.65));
    var sun = new THREE.DirectionalLight(0xfff4d6, 0.90);
    sun.position.set(1, 2, 1).normalize();
    sc.add(sun);
    sc.add(entry.mesh);
    entry.scene = sc;
  }

  function _facilityCenter(facility) {
    if (facility.lat != null && facility.lng != null) return [facility.lng, facility.lat];
    var g3d = facility.geometry_3d;
    if (g3d && g3d.center_lng != null && g3d.center_lat != null) {
      return [g3d.center_lng, g3d.center_lat];
    }
    var feat = facility.outer_feature;
    if (!feat) return null;
    var geom = feat.type === 'Feature'              ? (feat.geometry || {})
             : feat.type === 'Polygon' || feat.type === 'MultiPolygon' ? feat
             : (((feat.features || [])[0] || {}).geometry || {});
    if (geom.type === 'Polygon') {
      var ring = (geom.coordinates || [])[0];
      return ring && ring.length ? _ringCentroid(ring) : null;
    }
    if (geom.type === 'MultiPolygon') {
      var pts = [];
      (geom.coordinates || []).forEach(function (poly) {
        var r = poly && poly[0];
        if (r) { for (var i = 0; i < r.length; i++) pts.push(r[i]); }
      });
      return pts.length ? _ringCentroid(pts) : null;
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
      var m = (ring[0][0] === ring[n-1][0] && ring[0][1] === ring[n-1][1]) ? n - 1 : n;
      var sx = 0, sy = 0;
      for (var k = 0; k < m; k++) { sx += ring[k][0]; sy += ring[k][1]; }
      return [sx / m, sy / m];
    }
    return [cx / (6 * area), cy / (6 * area)];
  }

  function _buildEntry(facility, renderMode) {
    var center = _facilityCenter(facility);
    if (!center) {
      console.warn('[AoTFacilityMap3D] no center for', facility.unique_id);
      return null;
    }
    var group     = window.AoTFacility3D.buildFacilityMesh(facility, { renderMode: renderMode || 'default' });
    var merc      = _lngLatToMerc(center[0], center[1]);
    var scaleM    = merc.meterInMercatorCoordinateUnits();
    var orientDeg = (facility.geometry_3d && facility.geometry_3d.orientation_deg) || 0;
    var cx        = group.userData.cx || 0;
    var cz        = group.userData.cz || 0;
    return { mesh: group, scene: null, transform: _buildTransform(merc, scaleM, orientDeg, cx, cz) };
  }

  // ── Zoom threshold (uses the same AOT_GEO_CONFIG key) ─────────────────────────
  function _getCullZoom() {
    return (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.equipment_cull_zoom != null)
      ? window.AOT_GEO_CONFIG.equipment_cull_zoom : 15;
  }

  // ── Instance factory ──────────────────────────────────────────────────────────
  // Creates a self-contained instance that owns its own renderer/camera/state.
  // The MapLibre custom layer object is also per-instance so two instances never
  // share a renderer (which would happen with the old singleton pattern).
  function _createInstance(nativeMap, opts) {
    var inst = {
      _map:               nativeMap,
      _camera:            null,
      _renderer:          null,
      _meshes:            [],
      _preview:           null,
      _activeHideLayers:  _HIDDEN_LAYERS.concat((opts && opts.hideLayers) || []),
      _scanHideExtrusions: !!(opts && opts.scanHideExtrusions),
      _renderMode:        (opts && opts.renderMode) || 'default',
      _zoomHidden:        false,   // zoom < threshold → render skip
      _zoomListener:      null,
      _cullListeners:     [],      // subscribers notified on cull state changes
    };

    // Per-instance custom layer — captures `inst` in closure
    var _layer = {
      id:            LAYER_ID,
      type:          'custom',
      renderingMode: '3d',

      onAdd: function (map, gl) {
        inst._camera   = new THREE.Camera();
        inst._renderer = new THREE.WebGLRenderer({
          canvas:    map.getCanvas(),
          context:   gl,
          antialias: true,
        });
        inst._renderer.autoClear = false;
        inst._meshes.forEach(function (e) { if (!e.scene) _makeScene(e); });
        _hideMapLayers(map, inst);

        // zoom LOD: skip facility 3D rendering below equipment_cull_zoom.
        // Propagate the same threshold to facility-attached overlays (sensor labels, etc.)
        // so the 3D meshes and attached overlays always keep consistent visibility.
        function _applyZoomLOD() {
          var z = map.getZoom ? map.getZoom() : 99;
          var hidden = z < _getCullZoom();
          if (hidden !== inst._zoomHidden) {
            inst._zoomHidden = hidden;
            _notifyCullListeners(inst, hidden);
          } else {
            inst._zoomHidden = hidden;
          }
        }
        inst._zoomListener = _applyZoomLOD;
        map.on('zoom', _applyZoomLOD);
        _applyZoomLOD();  // apply the initial state immediately
      },

      onRemove: function (map) {
        _showMapLayers(map, inst);
        if (inst._zoomListener) {
          try { map.off('zoom', inst._zoomListener); } catch (e) {}
          inst._zoomListener = null;
        }
      },

      render: function (gl, args) {
        if (!inst._renderer || inst._zoomHidden) return;
        var mvp = _getMVP(args);
        if (!mvp || mvp.length < 16) return;
        var mapMatrix = new THREE.Matrix4().fromArray(mvp);
        inst._renderer.resetState();
        // MapLibre's 2D raster pass writes depth values that would cause Three.js
        // meshes to fail the depth test (Z-fighting at ground level). Clear the
        // depth buffer so the facility model always renders on top of map tiles.
        gl.clear(gl.DEPTH_BUFFER_BIT);
        inst._meshes.forEach(function (e) {
          if (!e.scene) return;
          inst._camera.projectionMatrix = mapMatrix.clone().multiply(e.transform);
          inst._renderer.render(e.scene, inst._camera);
        });
        if (inst._preview && inst._preview.scene) {
          inst._camera.projectionMatrix = mapMatrix.clone().multiply(inst._preview.transform);
          inst._renderer.render(inst._preview.scene, inst._camera);
        }
      },
    };
    inst._layer = _layer;
    return inst;
  }

  // ── Public instance API (returned from attach) ────────────────────────────────
  function _instSetPreview(inst, facility, center) {
    if (!inst._map) return;
    var fac = Object.assign({}, facility);
    if (center) { fac.lat = center[1]; fac.lng = center[0]; }
    try {
      var entry = _buildEntry(fac, inst._renderMode);
      if (!entry) { inst._preview = null; inst._map.triggerRepaint(); return; }
      _makeScene(entry);
      inst._preview = entry;
      _hideMapLayers(inst._map, inst);
      inst._map.triggerRepaint();
    } catch (e) {
      console.error('[AoTFacilityMap3D] setPreview error', e);
      inst._preview = null;
    }
  }

  function _instClearPreview(inst) {
    inst._preview = null;
    if (inst._map) inst._map.triggerRepaint();
  }

  function _instLoadProd(inst, facilities) {
    if (!inst._map) return;
    inst._meshes = [];
    (facilities || []).forEach(function (facility) {
      try {
        var entry = _buildEntry(facility, inst._renderMode);
        if (!entry) return;
        _makeScene(entry);
        inst._meshes.push(entry);
      } catch (e) {
        console.error('[AoTFacilityMap3D] loadProd error for', facility.unique_id, e);
      }
    });
    _hideMapLayers(inst._map, inst);
    inst._map.triggerRepaint();
  }

  function _instUpdateFacility(inst, facility) {
    if (!inst._map) return;
    inst._meshes = inst._meshes.filter(function (e) {
      return e.mesh.name !== 'facility_mesh_' + facility.unique_id;
    });
    try {
      var entry = _buildEntry(facility, inst._renderMode);
      if (!entry) return;
      _makeScene(entry);
      inst._meshes.push(entry);
      inst._map.triggerRepaint();
    } catch (e) {
      console.error('[AoTFacilityMap3D] updateFacility error', e);
    }
  }

  function _instDetach(inst) {
    var map = inst._map;
    if (map) {
      try { if (map.getLayer(LAYER_ID)) map.removeLayer(LAYER_ID); } catch (e) {}
      _showMapLayers(map, inst);
      if (inst._zoomListener) {
        try { map.off('zoom', inst._zoomListener); } catch (e) {}
        inst._zoomListener = null;
      }
    }
    inst._meshes   = [];
    inst._preview  = null;
    inst._map      = null;
    _removeInst(map);
  }

  // ── Global entry point ────────────────────────────────────────────────────────
  function attach(nativeMap, facilities, opts) {
    if (!nativeMap)            { console.error('[AoTFacilityMap3D] nativeMap required'); return null; }
    if (!window.THREE)         { console.error('[AoTFacilityMap3D] THREE not loaded'); return null; }
    if (!window.AoTFacility3D) { console.error('[AoTFacilityMap3D] AoTFacility3D not loaded'); return null; }

    // Detach any previous instance on this same map
    var existing = _findInst(nativeMap);
    if (existing) _instDetach(existing);

    var inst = _createInstance(nativeMap, opts);

    // Build initial prod meshes. Pass inst._renderMode so the configured
    // facility_render_mode (solid / wireframe / performance) is applied on first
    // render — the runtime-update rebuild paths already pass it, but this initial
    // build previously omitted it, so the load-time model always fell back to
    // 'default' regardless of the option.
    (facilities || []).forEach(function (facility) {
      try {
        var entry = _buildEntry(facility, inst._renderMode);
        if (!entry) return;
        _makeScene(entry);
        inst._meshes.push(entry);
      } catch (e) {
        console.error('[AoTFacilityMap3D] attach build error for', facility.unique_id, e);
      }
    });

    _registry.push({ map: nativeMap, inst: inst });
    _lastInst = inst;

    // Remove stale layer from this map if present (style-reload edge case)
    if (nativeMap.getLayer(LAYER_ID)) nativeMap.removeLayer(LAYER_ID);
    nativeMap.addLayer(inst._layer);

    // Return instance handle for callers that manage multiple maps
    return {
      setPreview:     function (f, c)  { _instSetPreview(inst, f, c); },
      clearPreview:   function ()      { _instClearPreview(inst); },
      loadProd:       function (fs)    { _instLoadProd(inst, fs); },
      updateFacility: function (f)     { _instUpdateFacility(inst, f); },
      detach:         function ()      { _instDetach(inst); },
      onCullChange:   function (cb)    { return _onCullChange(inst, cb); },
      isCulled:       function ()      { return !!inst._zoomHidden; },
    };
  }

  // ── Cull observer pub-sub ─────────────────────────────────────────────────
  // Facility-attached overlays (sensor labels, future device markers, etc.) must hide
  // together with the 3D meshes at the same zoom threshold. Use observer subscriptions
  // instead of hardcoding so that all attached overlays are applied uniformly.
  function _notifyCullListeners(inst, hidden) {
    (inst._cullListeners || []).forEach(function (cb) {
      try { cb(hidden); } catch (e) { console.warn('[AoTFacilityMap3D] cull listener error', e); }
    });
  }

  function _onCullChange(inst, cb) {
    if (typeof cb !== 'function') return function () {};
    inst._cullListeners.push(cb);
    // Notify the current state immediately (sync at subscription time)
    try { cb(!!inst._zoomHidden); } catch (e) {}
    return function unsubscribe() {
      var arr = inst._cullListeners;
      var idx = arr.indexOf(cb);
      if (idx >= 0) arr.splice(idx, 1);
    };
  }

  // map-instance lookup for the global API
  function _findInst(map) {
    for (var i = 0; i < _registry.length; i++) {
      if (_registry[i].map === map) return _registry[i].inst;
    }
    return null;
  }

  // ── Backward-compatible global API (operate on last-attached map) ─────────────
  function setPreview(facility, center) {
    if (!_lastInst) return;
    _instSetPreview(_lastInst, facility, center);
  }
  function clearPreview() {
    if (!_lastInst) return;
    _instClearPreview(_lastInst);
  }
  function loadProd(facilities) {
    if (!_lastInst) return;
    _instLoadProd(_lastInst, facilities);
  }
  function updateFacility(facility) {
    if (!_lastInst) return;
    _instUpdateFacility(_lastInst, facility);
  }
  function detach() {
    if (!_lastInst) return;
    _instDetach(_lastInst);
  }

  global.AoTFacilityMap3D = {
    attach: attach,
    setPreview: setPreview, clearPreview: clearPreview,
    loadProd: loadProd, updateFacility: updateFacility,
    detach: detach,
    // Generic cull observer: any module rendering facility-tied overlays
    // (sensor labels, future device markers, etc.) subscribes here to follow
    // the same zoom-LOD visibility as the 3D meshes — no per-overlay hardcoding.
    onCullChange: function (map, cb) {
      var inst = _findInst(map) || _lastInst;
      if (!inst) return function () {};
      return _onCullChange(inst, cb);
    },
    isCulled: function (map) {
      var inst = _findInst(map) || _lastInst;
      return inst ? !!inst._zoomHidden : false;
    },
  };

}(window));
