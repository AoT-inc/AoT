// aot-facility-hotspot.js — IEC § A sensor/actuator hotspots on the 3D scene
// Adds spheres for sensors + disc indicators for actuators to an existing ctx.scene.
// Click via THREE.Raycaster highlights the matching § B env-cell or § D row.
(function () {
  'use strict';

  var _SENSOR_POS = {
    indoor_temp:     function (geo) { return new THREE.Vector3(geo.span / 2, geo.eave * 0.6, geo.length / 2); },
    indoor_humidity: function (geo) { return new THREE.Vector3(geo.span / 2, 0.5,            geo.length / 2); },
    indoor_co2:      function (geo) { return new THREE.Vector3(geo.span / 2, geo.ridge - 0.5, geo.length / 2); },
    outdoor_temp:    function (geo) { return new THREE.Vector3(geo.span + 2,  1.5,             geo.length / 2); },
    wind:            function (geo) { return new THREE.Vector3(geo.span + 2,  2.5,             geo.length / 2); },
    solar:           function (geo) { return new THREE.Vector3(geo.span / 2,  geo.ridge + 0.5, geo.length / 2); },
  };

  var _ACT_POS = {
    side_window:     function (geo) { return new THREE.Vector3(0,             geo.eave * 0.5, geo.length * 0.3); },
    roof_vent:       function (geo) { return new THREE.Vector3(geo.span / 2,  geo.ridge,      geo.length * 0.5); },
    thermal_curtain: function (geo) { return new THREE.Vector3(geo.span * 0.3, geo.eave,      geo.length * 0.5); },
    shade_curtain:   function (geo) { return new THREE.Vector3(geo.span * 0.7, geo.eave,      geo.length * 0.5); },
    fan_circ:        function (geo) { return new THREE.Vector3(geo.span * 0.5, 1.2,           geo.length * 0.8); },
    fan_exhaust:     function (geo) { return new THREE.Vector3(geo.span * 0.5, geo.ridge * 0.8, 0);             },
    heater:          function (geo) { return new THREE.Vector3(0.5,            0.3,            geo.length * 0.2); },
  };

  var _STATUS_COLOR = { valid: 0x43a047, stale: 0xfb8c00, degraded: 0xe53935 };

  function attach(ctx, facility, widgetId) {
    if (!ctx || !ctx.scene || !window.THREE) return;

    var scene   = ctx.scene;
    var camera  = ctx.camera;
    var renderer = ctx.renderer;

    var g3d   = facility.geometry_3d || {};
    var geoDim = {
      span:   g3d.span_width_m  || 8,
      eave:   g3d.eave_height_m || 2.5,
      ridge:  g3d.ridge_height_m || 3.5,
      length: g3d.length_m      || 20,
    };

    var markers = [];

    // Sensor markers
    Object.keys(_SENSOR_POS).forEach(function (key) {
      var pos    = _SENSOR_POS[key](geoDim);
      var color  = _STATUS_COLOR.valid;
      var geo    = new THREE.SphereGeometry(0.18, 10, 10);
      var mat    = new THREE.MeshBasicMaterial({ color: color });
      var mesh   = new THREE.Mesh(geo, mat);
      mesh.position.copy(pos);
      mesh.userData = { type: 'sensor', key: key, widgetId: widgetId };
      scene.add(mesh);
      markers.push(mesh);
    });

    // Actuator markers (disc)
    var actFallback = function (geo) { return new THREE.Vector3(0, 0, 0); };
    var actuators   = facility.actuators || [];
    var actList     = Array.isArray(actuators) ? actuators : Object.entries(actuators).map(function (kv) {
      return { kind: kv[0], device_uuid: kv[1] };
    });

    actList.forEach(function (act, i) {
      var kind    = act.kind || '';
      var posFn   = _ACT_POS[kind] || actFallback;
      var pos     = posFn(geoDim);
      // offset bays if connected
      pos.z += i * 0.1;

      var geo  = new THREE.CylinderGeometry(0.25, 0.25, 0.06, 12);
      var mat  = new THREE.MeshBasicMaterial({ color: 0x1976d2, transparent: true, opacity: 0.75 });
      var mesh = new THREE.Mesh(geo, mat);
      mesh.position.copy(pos);
      mesh.userData = { type: 'actuator', kind: kind, slotKey: _slotKey(act, i), widgetId: widgetId };
      scene.add(mesh);
      markers.push(mesh);
    });

    // Raycaster click handler on the canvas
    var canvas    = renderer.domElement;
    var raycaster = new THREE.Raycaster();
    var mouse     = new THREE.Vector2();

    canvas.addEventListener('click', function (e) {
      var rect = canvas.getBoundingClientRect();
      mouse.x =  ((e.clientX - rect.left)  / rect.width)  * 2 - 1;
      mouse.y = -((e.clientY - rect.top)   / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      var hits = raycaster.intersectObjects(markers, false);
      if (!hits.length) return;
      var hit = hits[0].object;
      _onHit(hit.userData);
    });
  }

  function updateSensorStatus(widgetId, sensors) {
    // sensors: { key: 'valid'|'stale'|'degraded' }
    // Traverse scene children and update material colors
    // (requires access to scene — stored per widgetId externally)
    // This is a best-effort update called from widget.js
    var scene = window._aotFacilityScenes && window._aotFacilityScenes[widgetId];
    if (!scene) return;
    scene.traverse(function (obj) {
      if (obj.userData && obj.userData.type === 'sensor' && sensors[obj.userData.key]) {
        var status = sensors[obj.userData.key];
        var col    = _STATUS_COLOR[status] || _STATUS_COLOR.valid;
        if (obj.material) obj.material.color.setHex(col);
      }
    });
  }

  function _onHit(userData) {
    var wid = userData.widgetId;
    _clearFocus(wid);

    if (userData.type === 'sensor') {
      var cell = document.querySelector(
        '#aot-facility-env-' + wid + ' [data-key="' + userData.key + '"]');
      if (cell) cell.classList.add('iec-focus');
    } else if (userData.type === 'actuator') {
      var row = document.querySelector(
        '#iec-ctrl-tbody-' + wid + ' [data-slot="' + userData.slotKey + '"]');
      if (row) row.classList.add('iec-focus');
    }
  }

  function _clearFocus(wid) {
    var els = document.querySelectorAll(
      '#aot-facility-' + wid + ' .iec-focus, #aot-facility-env-' + wid + ' .iec-focus');
    els.forEach(function (el) { el.classList.remove('iec-focus'); });
  }

  function _slotKey(act, i) {
    var k = act.kind || '';
    return k ? k + '_' + i : 'actuator_' + i;
  }

  window.AoTFacilityHotspot = { attach: attach, updateSensorStatus: updateSensorStatus };
})();
