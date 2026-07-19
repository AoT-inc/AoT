// aot-facility-3d.js — AoT Facility 3D scene orchestrator
// Public API (unchanged): window.AoTFacility3D = { buildScene, buildFacilityMesh }
// New:  window.AoTFacilityState — pub/sub spec state (two-way binding)
//       GLTF asset render path (render_mode='asset')
//
// Module load order (templates must inject before this file):
//   three.min.js → OrbitControls.js → three-mesh-bvh.js → GLTFLoader.js
//   → core/materials.js → core/parametric.js → assets/gltf_loader.js
// Falls back to inline implementations if sub-modules are absent.
(function (global) {
  'use strict';

  // ── Force-WebGL1 helper ────────────────────────────────────────────────────────
  // On renderer init, three.js r160 uploads an empty placeholder 3D texture via
  // the WebGL2 texImage3D path, but with FLIP_Y/PREMULTIPLY_ALPHA set the WebGL2
  // spec strictly rejects it → INVALID_OPERATION (desktop) / renderer crash·white
  // screen (iOS Safari). WebGL1 has no texImage3D API at all, so it never takes that path.
  // facility 3D is simple mesh rendering (no IBL/3D texture), so WebGL1/2 differences
  // cause no functional/visual impact. (The WebGL1 deprecation warning is removed from the
  // vendored three.min.js — pinned to r160 locally, so the r163 removal has no effect.)
  function _createWebGL1Renderer(canvas) {
    var gl1 = null;
    try {
      gl1 = canvas.getContext('webgl', { antialias: true, alpha: true })
         || canvas.getContext('experimental-webgl', { antialias: true, alpha: true });
    } catch (e) { gl1 = null; }
    return gl1
      ? new THREE.WebGLRenderer({ canvas: canvas, context: gl1, antialias: true, alpha: true })
      : new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
  }

  // ── Module resolution (use extracted modules if present, else inline) ────────
  // Materials
  const MAT = (function () {
    if (global.AoTMaterials) return global.AoTMaterials;
    // Inline fallback (mirrors core/materials.js)
    // opacity=material property (simulation), renderOpacity=render-only
    const _CO = {
      vinyl_single:  { color: 0x9ecfef, opacity: 0.75, renderOpacity: 0.25 },
      vinyl_double:  { color: 0x9ecfef, opacity: 0.68, renderOpacity: 0.32 },
      po_film:       { color: 0xbcdff0, opacity: 0.72, renderOpacity: 0.28 },
      polycarbonate: { color: 0xdaeeff, opacity: 0.54, renderOpacity: 0.46 },
      glass:         { color: 0xc8eecc, opacity: 0.82, renderOpacity: 0.18 },
    };
    const _ro = o => o.renderOpacity != null ? o.renderOpacity : o.opacity;
    return {
      // depthWrite:false — the cover must not pollute the depth buffer, so interior elements stay visible.
      // renderOrder is set separately at mesh creation (cover 1000, inner 900).
      //
      // With MeshPhysicalMaterial, three.js auto-generates an IBL prefiltered radiance map
      // and uploads a 3D texture via WebGL2 texImage3D with FLIP_Y/PREMULTIPLY_ALPHA set
      // → iOS Safari WebGL spec strictly rejects it and throws.
      // Since we don't use Physical-only effects like clearcoat/sheen/transmission,
      // swap 1:1 to MeshStandardMaterial (identical look, no IBL generation).
      cover:          t => { const o=_CO[t]||_CO.vinyl_double; return new THREE.MeshStandardMaterial({color:o.color,transparent:true,opacity:_ro(o),side:THREE.DoubleSide,roughness:0.05,metalness:0,depthWrite:false}); },
      coverInner:     t => { const o=_CO[t]||{color:0xd0eaff,renderOpacity:0.18}; return new THREE.MeshStandardMaterial({color:o.color,transparent:true,opacity:Math.min(_ro(o)*0.65,0.22),side:THREE.DoubleSide,roughness:0.05,metalness:0,depthWrite:false}); },
      frame:          () => new THREE.MeshStandardMaterial({color:0x888888,roughness:0.6,metalness:0.4}),
      floor:          () => new THREE.MeshStandardMaterial({color:0xb8b8b8,roughness:0.85}),
      sashOpen:       () => new THREE.MeshStandardMaterial({color:0xffb300,transparent:true,opacity:0.75,side:THREE.DoubleSide}),
      sashClosed:     () => new THREE.MeshStandardMaterial({color:0x607d8b,transparent:true,opacity:0.55,side:THREE.DoubleSide}),
      curtainThermal: () => new THREE.MeshStandardMaterial({color:0xf5e6c8,transparent:true,opacity:0.10,side:THREE.DoubleSide}),
      curtainShade:   () => new THREE.MeshStandardMaterial({color:0x4a4a4a,transparent:true,opacity:0.10,side:THREE.DoubleSide}),
      fan:            () => new THREE.MeshStandardMaterial({color:0x546e7a}),
      fanOn:          () => new THREE.MeshStandardMaterial({color:0x29b6f6,emissive:0x0288d1,emissiveIntensity:0.6}),
      heater:         () => new THREE.MeshStandardMaterial({color:0xef9a9a}),
      heaterOn:       () => new THREE.MeshStandardMaterial({color:0xf44336,emissive:0xe53935,emissiveIntensity:0.8}),
      cooler:         () => new THREE.MeshStandardMaterial({color:0x80cbc4}),
      coolerOn:       () => new THREE.MeshStandardMaterial({color:0x00bcd4,emissive:0x0097a7,emissiveIntensity:0.6}),
      pump:           () => new THREE.MeshStandardMaterial({color:0x81c784}),
      pumpOn:         () => new THREE.MeshStandardMaterial({color:0x4caf50,emissive:0x388e3c,emissiveIntensity:0.6}),
      windArrow:      () => new THREE.MeshStandardMaterial({color:0x0288d1}),
      compass:        () => new THREE.MeshStandardMaterial({color:0xe53935}),
    };
  })();

  // Parametric builders
  const P = (function () {
    if (global.AoTParametric) return global.AoTParametric;
    // Inline fallback — delegates to local functions defined below
    return null;  // resolved after local defs
  })();

  // ── FacilityState — singleton pub/sub spec state ─────────────────────────────
  const FacilityState = (function () {
    let _spec = null;       // current facility spec dict
    let _runtime = null;
    let _subs = [];
    let _debounceTimer = null;

    function subscribe(fn) { _subs.push(fn); return () => { _subs = _subs.filter(s => s !== fn); }; }

    function _emit() {
      _subs.forEach(fn => { try { fn({ spec: _spec, runtime: _runtime }); } catch (e) {} });
    }

    function patch(delta, immediate) {
      if (!_spec) _spec = {};
      _deepMerge(_spec, delta);
      if (immediate) { _emit(); return; }
      clearTimeout(_debounceTimer);
      _debounceTimer = setTimeout(_emit, 150);
    }

    function setSpec(spec) { _spec = spec; _emit(); }
    function setRuntime(rt) { _runtime = rt; _emit(); }
    function getSpec() { return _spec; }
    function getRuntime() { return _runtime; }

    function _deepMerge(target, src) {
      if (!src || typeof src !== 'object') return;
      Object.keys(src).forEach(k => {
        if (src[k] && typeof src[k] === 'object' && !Array.isArray(src[k])) {
          if (!target[k] || typeof target[k] !== 'object') target[k] = {};
          _deepMerge(target[k], src[k]);
        } else {
          target[k] = src[k];
        }
      });
    }

    return { subscribe, patch, setSpec, setRuntime, getSpec, getRuntime };
  })();

  global.AoTFacilityState = FacilityState;

  // ── Parametric geometry helpers (inline — also available via core/parametric.js) ─

  function _buildMultiSpanShape(span, eaveH, ridgeH, roofType, bayCount, spacing) {
    if (P) return P.buildMultiSpanShape(span, eaveH, ridgeH, roofType, bayCount, spacing);
    const s = new THREE.Shape();
    s.moveTo(0, 0); s.lineTo(0, eaveH);
    for (let b = 0; b < bayCount; b++) {
      const lx = b * (span + spacing), rx = lx + span;
      if (roofType === 'gable') { s.lineTo(lx + span / 2, ridgeH); s.lineTo(rx, eaveH); }
      else if (roofType === 'flat' || roofType === 'box') { s.lineTo(lx, ridgeH); s.lineTo(rx, ridgeH); s.lineTo(rx, eaveH); }
      else { s.bezierCurveTo(lx, ridgeH, rx, ridgeH, rx, eaveH); }
      if (spacing > 0 && b < bayCount - 1) s.lineTo(rx + spacing, eaveH);
    }
    const tw = bayCount * span + (bayCount - 1) * spacing;
    s.lineTo(tw, 0); s.lineTo(0, 0);
    return s;
  }

  function buildSideVentSash(eaveH, length, openRatio, isRight) {
    if (P) return P.buildSideVentSash(eaveH, length, openRatio, isRight, MAT);
    const ventH = Math.min(eaveH * 0.40, 1.2);
    const geo = new THREE.PlaneGeometry(length * 0.85, ventH);
    geo.translate(0, -ventH / 2, 0);
    const isOpen = openRatio > 0.05;
    const mesh = new THREE.Mesh(geo, isOpen ? MAT.sashOpen() : MAT.sashClosed());
    mesh.name = 'side_vent_' + (isRight ? 'right' : 'left');
    mesh.rotation.y = isRight ? -Math.PI / 2 : Math.PI / 2;
    if (isOpen) mesh.rotation.x = -openRatio * (Math.PI / 3);
    return mesh;
  }

  function buildRoofVentIndicator(span, ridgeH, length, openRatio) {
    if (P) return P.buildRoofVentIndicator(span, ridgeH, length, openRatio, MAT);
    const ventW = span * 0.22, ventL = length * 0.75;
    const geo = new THREE.PlaneGeometry(ventW, ventL);
    const isOpen = openRatio > 0.05;
    const mesh = new THREE.Mesh(geo, isOpen ? MAT.sashOpen() : MAT.sashClosed());
    mesh.name = 'roof_vent';
    mesh.rotation.x = -(Math.PI / 2) + (isOpen ? openRatio * (Math.PI / 5) : 0);
    return mesh;
  }

  function buildCurtain(totalWidth, eaveH, length, type, deployRatio) {
    if (P) return P.buildCurtain(totalWidth, eaveH, length, type, deployRatio, MAT);
    const w = totalWidth * Math.max(deployRatio, 0.02);
    const geo = new THREE.PlaneGeometry(w, length);
    geo.rotateX(-Math.PI / 2);
    const mat = type === 'thermal' ? MAT.curtainThermal() : MAT.curtainShade();
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = 'curtain_' + type;
    mesh.position.set(w / 2, eaveH + 0.08, length / 2);
    return mesh;
  }

  function buildDeviceIcon(type, isOn, position) {
    if (P) return P.buildDeviceIcon(type, isOn, position, MAT);
    const g = new THREE.Group(); g.name = 'device_' + type; g.position.copy(position);
    let geo, mat;
    if (type === 'fan' || type === 'circulation_fan' || type === 'exhaust_fan') {
      geo = new THREE.TorusGeometry(0.18, 0.04, 8, 16); mat = isOn ? MAT.fanOn() : MAT.fan();
    } else if (type === 'heater') {
      geo = new THREE.BoxGeometry(0.4, 0.12, 0.12); mat = isOn ? MAT.heaterOn() : MAT.heater();
    } else if (type === 'cooler' || type === 'heat_pump') {
      geo = new THREE.BoxGeometry(0.4, 0.12, 0.12); mat = isOn ? MAT.coolerOn() : MAT.cooler();
    } else if (type === 'irrigation_valve') {
      geo = new THREE.CylinderGeometry(0.06, 0.06, 0.25, 8); mat = isOn ? MAT.pumpOn() : MAT.pump();
    } else {
      geo = new THREE.SphereGeometry(0.1, 8, 8); mat = new THREE.MeshStandardMaterial({color: isOn ? 0x4caf50 : 0x9e9e9e});
    }
    g.add(new THREE.Mesh(geo, mat));
    if (isOn) { const r = new THREE.Mesh(new THREE.TorusGeometry(0.25,0.015,8,16), new THREE.MeshStandardMaterial({color:0xffffff,transparent:true,opacity:0.5})); g.add(r); }
    return g;
  }

  function buildWindArrow(windDeg, length) {
    if (P) return P.buildWindArrow(windDeg, length, MAT);
    const group = new THREE.Group(); group.name = 'wind_arrow';
    group.add(new THREE.Mesh(new THREE.CylinderGeometry(0.04,0.04,1.2,8), MAT.windArrow()));
    const head = new THREE.Mesh(new THREE.ConeGeometry(0.12,0.35,8), MAT.windArrow());
    head.position.y = 0.77; group.add(head);
    group.position.set(0, 3.0, length / 2);
    group.rotation.y = THREE.MathUtils.degToRad(windDeg + 180);
    return group;
  }

  function buildCompass(orientationDeg, length) {
    if (P) return P.buildCompass(orientationDeg, length, MAT);
    const group = new THREE.Group(); group.name = 'compass';
    group.add(new THREE.Mesh(new THREE.ConeGeometry(0.08,0.45,8), MAT.compass()));
    group.position.set(0, 0.5, length + 1.2);
    group.rotation.y = THREE.MathUtils.degToRad(-orientationDeg);
    return group;
  }

  // Floor direction arrows (with N/E labels)
  // Uses only Three.js built-ins — Z=north (N), X=east (E)
  function buildFloorCompass(totalWidth, length) {
    if (P) return P.buildFloorCompass(totalWidth, length);
    const g = new THREE.Group(); g.name = 'floor_compass';
    const cx = totalWidth / 2, cz = length / 2;
    const arrowLen  = Math.min(totalWidth, length) * 0.25;
    const headLen   = arrowLen * 0.25;
    const headWidth = arrowLen * 0.12;
    // North arrow (blue: +Z direction)
    const nArrow = new THREE.ArrowHelper(
      new THREE.Vector3(0, 0, 1), new THREE.Vector3(cx, 0.05, cz),
      arrowLen, 0x1565c0, headLen, headWidth
    );
    nArrow.name = 'compass_north';
    g.add(nArrow);
    // East arrow (orange: +X direction)
    const eArrow = new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0), new THREE.Vector3(cx, 0.05, cz),
      arrowLen, 0xe65100, headLen, headWidth
    );
    eArrow.name = 'compass_east';
    g.add(eArrow);
    // Label sprites using canvas textures
    function _labelSprite(text, color) {
      const cv = document.createElement('canvas'); cv.width = 64; cv.height = 64;
      const ctx2d = cv.getContext('2d');
      ctx2d.clearRect(0, 0, 64, 64);
      ctx2d.fillStyle = color;
      ctx2d.font = 'bold 40px Arial';
      ctx2d.textAlign = 'center'; ctx2d.textBaseline = 'middle';
      ctx2d.fillText(text, 32, 32);
      const tex = new THREE.CanvasTexture(cv);
      const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true });
      const sp = new THREE.Sprite(mat);
      sp.scale.set(1.2, 1.2, 1);
      return sp;
    }
    const nLabel = _labelSprite('N', '#029ACF');
    nLabel.position.set(cx, 0.3, cz + arrowLen + 0.8);
    g.add(nLabel);
    const eLabel = _labelSprite('E', '#e65100');
    eLabel.position.set(cx + arrowLen + 0.8, 0.3, cz);
    g.add(eLabel);
    return g;
  }

  function buildPipe(pts, radius, color, opacity) {
    const curve = new THREE.CatmullRomCurve3(pts.map(([x,y,z]) => new THREE.Vector3(x,y,z)));
    const geo = new THREE.TubeGeometry(curve, Math.max(pts.length*4,8), radius, 6, false);
    const mat = new THREE.MeshStandardMaterial({color,roughness:0.55,metalness:0.35,transparent:opacity<1,opacity:opacity!=null?opacity:1});
    const m = new THREE.Mesh(geo, mat); m.name = 'pipe'; return m;
  }

  function buildIrrigationPipes(totalWidth, length, span, bayCount, effectiveSpacing, isOn) {
    if (P) return P.buildIrrigationPipes(totalWidth, length, span, bayCount, effectiveSpacing, isOn, MAT);
    const group = new THREE.Group(); group.name = 'irrigation_pipes';
    const color = isOn ? 0x29b6f6 : 0x607d8b, pH = 0.18, cx = totalWidth / 2;
    group.add(buildPipe([[cx,pH,0.5],[cx,pH,length-0.5]], 0.038, color, 1.0));
    for (let b = 0; b < bayCount; b++) {
      const bx = b*(span+effectiveSpacing)+span/2;
      [0.15,0.35,0.50,0.65,0.85].forEach(zf => {
        group.add(buildPipe([[bx-span*0.44,pH,length*zf],[cx,pH,length*zf],[bx+span*0.44,pH,length*zf]],0.020,color,0.82));
      });
    }
    return group;
  }

  function buildHeatingPipes(totalWidth, length, isOn) {
    if (P) return P.buildHeatingPipes(totalWidth, length, isOn);
    const group = new THREE.Group(); group.name = 'heating_pipes';
    const color = isOn ? 0xef5350 : 0x795548, pH = 0.22, inset = 0.35;
    [inset, totalWidth-inset].forEach(x => {
      group.add(buildPipe([[x,pH,0.4],[x,pH,length-0.4]], 0.030, color, 1.0));
    });
    return group;
  }

  // ── Axis-based side labels ─────────────────────────────────────────────────
  // Model uses pure XYZ identifiers, NOT compass directions. The 4 wall faces
  // are x_pos/x_neg (long side walls) and y_pos/y_neg (gable end walls).
  // Real-world compass orientation is applied only at placement time via
  // orientation_deg + center_lng/lat. Legacy compass strings ('south'/'north'/
  // 'east'/'west') are translated to axis labels on load for backward compat.
  var AXIS_NORMALS = {
    x_neg: [-1, 0, 0], x_pos: [1, 0, 0],
    y_neg: [0, 0, -1], y_pos: [0, 0, 1]
  };
  function _toAxisSide(s) {
    if (s === 'south') return 'y_pos';
    if (s === 'north') return 'y_neg';
    if (s === 'east')  return 'x_pos';
    if (s === 'west')  return 'x_neg';
    return s; // already axis-labeled or non-directional ('roof'/'ceiling'/'floor')
  }

  // ── Envelope fittings generator (pure function for the map context) ─────────────────────
  // Performs the same calculation as _renderEnvelopeFittings in geo_facility.html
  // using only the facility object, without DOM.
  // Returns: an array of fitting objects (marked with source:'envelope')
  function _generateEnvelopeFittings(facility) {
    var g3d = facility.geometry_3d || {};
    var env = facility.envelope || {};

    function _r(v) { return Math.round((v || 0) * 1000) / 1000; }

    var span      = parseFloat(g3d.span_width_m)   || 7;
    var L         = parseFloat(g3d.length_m)        || 30;
    var eaveH     = parseFloat(g3d.eave_height_m)   || 2;
    var ridgeH    = parseFloat(g3d.ridge_height_m)  || 4;
    var spacing   = parseFloat(g3d.spacing_m)       || 0;
    var roofType  = String(g3d.roof_type || 'arch').toLowerCase();
    var struct    = facility.structure || 'single';
    var rawBay    = Math.max(parseInt(facility.bay_count || 1, 10), 1);
    var isConn    = struct === 'connected';
    var effSp     = isConn ? 0 : spacing;
    var unitCount = isConn ? 1 : rawBay;
    var meshBayCount = isConn ? rawBay : 1;
    var unitWidth = meshBayCount * span + (meshBayCount - 1) * effSp;

    var UNITS = [];
    for (var ui = 0; ui < unitCount; ui++) {
      var ux = ui * (unitWidth + effSp);
      UNITS.push({ index: ui, leftX: ux, rightX: ux + unitWidth, centerX: ux + unitWidth / 2 });
    }

    // arch apex Y (cubic bezier vertex)
    var roofApexY = (roofType === 'gable' || roofType === 'flat' || roofType === 'box')
      ? ridgeH : (eaveH + 3 * ridgeH) / 4;

    function _roofYatT(t) {
      if (roofType === 'gable') return eaveH + (ridgeH - eaveH) * (1 - Math.abs(t - 0.5) * 2);
      if (roofType === 'flat' || roofType === 'box') return ridgeH;
      var u2 = 1 - t;
      return u2*u2*u2*eaveH + 3*u2*u2*t*ridgeH + 3*u2*t*t*ridgeH + t*t*t*eaveH;
    }
    function _roofNormalAtT(t) {
      if (roofType === 'flat' || roofType === 'box') return [0, 1, 0];
      var tx, ty;
      if (roofType === 'gable') {
        tx = span / 2; ty = (t < 0.5 ? 1 : -1) * (ridgeH - eaveH);
      } else {
        tx = (6*t - 3*t*t) * span;
        ty = 3 * (1 - 2*t) * (ridgeH - eaveH);
      }
      var nx = -ty, ny = tx, mag = Math.sqrt(nx*nx + ny*ny);
      return mag < 1e-6 ? [0, 1, 0] : [nx/mag, ny/mag, 0];
    }
    function _equalStages(n) {
      var m = 0.05, g = 0.10, cnt = Math.max(n | 0, 1);
      var avail = Math.max(eaveH - 2*m - (cnt-1)*g, 0.4);
      var stepH = avail / cnt;
      var out = [];
      for (var i = 0; i < cnt; i++) {
        var bot = m + i * (stepH + g), top = bot + stepH;
        out.push({ id: cnt === 1 ? 'single' : (i === 0 ? 'lower' : (i === cnt-1 ? 'upper' : 's'+i)), y: (bot+top)/2, h: top-bot });
      }
      return out;
    }

    var items = [];

    // ── Side reinforcement layers ────────────────────────────────────────────────────
    var _reinLayers = (Array.isArray(env.layers) ? env.layers : [])
      .filter(function (l) { return l && l.type === 'side_only'; });

    function _outermostReinfOffset(side) {
      var max = 0, has = false;
      _reinLayers.forEach(function (layer, li) {
        var sides = Array.isArray(layer.sides) ? layer.sides : [];
        if (sides.indexOf(side) < 0) return;
        var th = parseFloat(layer.thickness_m); if (!isFinite(th) || th <= 0) th = 1.0;
        var fo = th + li * 0.01; if (fo > max) max = fo; has = true;
      });
      return has ? max : null;
    }

    // ── Side vent (side vent outer) ────────────────────────────────────────────────
    var SV_DEPTH = 0.05;
    var sv = env.side_vent && env.side_vent.outer;
    if (sv && sv.enabled) {
      var nSt = (Array.isArray(sv.stages) && sv.stages.length) ? sv.stages.length : 1;
      var sideStages = _equalStages(nSt);
      var wOff = _outermostReinfOffset('west'), eOff = _outermostReinfOffset('east');
      sideStages.forEach(function (st, si) {
        UNITS.forEach(function (u) {
          [
            { id: 'left',  baseX: u.leftX,  sn: [-1,0,0], lbl: 'L', outSign: -1, reinOff: wOff },
            { id: 'right', baseX: u.rightX, sn: [1,0,0],  lbl: 'R', outSign: +1, reinOff: eOff }
          ].forEach(function (w) {
            // 측면 보강이 있는 면은 보강 외피에만 측창을 추가한다.
            // 보강이 없는 면만 기본 외피에 측창을 둔다(중복 방지).
            if (w.reinOff !== null) {
              var rfX = w.baseX + w.outSign * w.reinOff;
              var rvX = rfX + w.outSign * (SV_DEPTH / 2);
              items.push({ id: 'env_sv_reinf_u'+u.index+'_'+w.id+'_'+si, kind: 'side_window', source: 'envelope',
                position: { x: _r(rvX), y: _r(st.y), z: _r(L/2) },
                size: { w: _r(L * 0.97), h: _r(st.h), d: SV_DEPTH },
                surface_normal: w.sn });
            } else {
              var ventX = w.baseX + w.outSign * (SV_DEPTH / 2);
              items.push({ id: 'env_sv_u'+u.index+'_'+w.id+'_'+si, kind: 'side_window', source: 'envelope',
                position: { x: _r(ventX), y: _r(st.y), z: _r(L/2) },
                size: { w: _r(L * 0.97), h: _r(st.h), d: SV_DEPTH },
                surface_normal: w.sn });
            }
          });
        });
      });
    }

    // ── Roof vent (roof vent outer) ────────────────────────────────────────────────
    var rvCfg = env.roof_vent && env.roof_vent.outer;
    if (rvCfg && rvCfg.enabled) {
      var rvThick = 0.06;
      var placement = rvCfg.placement || 'center';
      for (var b = 0; b < meshBayCount; b++) {
        var bx = b * (span + effSp);
        if (placement === 'sides') {
          [{t:0.30,side:'left'},{t:0.70,side:'right'}].forEach(function (p) {
            items.push({ id: 'env_rv_b'+b+'_'+p.side, kind: 'window', source: 'envelope',
              position: { x: _r(bx + p.t * span), y: _r(_roofYatT(p.t)), z: _r(L/2) },
              size: { w: _r(L * 0.75), h: _r(span * 0.18), d: rvThick },
              surface_normal: _roofNormalAtT(p.t) });
          });
        } else {
          items.push({ id: 'env_rv_b'+b+'_center', kind: 'window', source: 'envelope',
            position: { x: _r(bx + span/2), y: _r(roofApexY - rvThick/2), z: _r(L/2) },
            size: { w: _r(span * 0.08), h: rvThick, d: _r(L * 0.75) },
            surface_normal: null });
        }
      }
    }

    // ── Shade/thermal ceiling curtains ───────────────────────────────────────────────────
    var SHADE_Y        = eaveH * 0.96;
    var THERMAL_BASE_Y = eaveH * 0.88;
    var sh = env.curtain && env.curtain.shade;
    var tc = env.curtain && env.curtain.thermal_ceiling;
    var tcLayers = (tc && tc.enabled) ? Math.max(parseInt(tc.layers, 10) || 1, 1) : 0;
    for (var b = 0; b < meshBayCount; b++) {
      var cbx = _r(b * (span + effSp) + span / 2);
      if (sh && sh.enabled) {
        items.push({ id: 'env_curtain_shade_b'+b, kind: 'shade_curtain', source: 'envelope',
          position: { x: cbx, y: _r(SHADE_Y), z: _r(L/2) },
          size: { w: _r(span), h: 0.04, d: _r(L) },
          surface_normal: null });
      }
      for (var lc = 0; lc < tcLayers; lc++) {
        items.push({ id: 'env_curtain_thermal_b'+b+'_l'+lc, kind: 'curtain', source: 'envelope',
          position: { x: cbx, y: _r(THERMAL_BASE_Y - lc * 0.10), z: _r(L/2) },
          size: { w: _r(span), h: 0.04, d: _r(L) },
          surface_normal: null });
      }
    }

    // ── Side reinforcement (reinforcement) ───────────────────────────────────────────
    // Model uses pure XYZ axis identifiers: x_pos/x_neg are the long side walls,
    // y_pos/y_neg are the gable end walls. Compass labels (north/south/east/west)
    // are translated on load for backward compatibility with existing data.
    _reinLayers.forEach(function (layer, li) {
      var sides = Array.isArray(layer.sides) ? layer.sides : [];
      var th = parseFloat(layer.thickness_m); if (!isFinite(th) || th <= 0) th = 1.0;
      var stackGap = li * 0.01, halfTh = th / 2, centreOff = halfTh + stackGap;
      sides.forEach(function (sdRaw) {
        var sd = _toAxisSide(sdRaw);
        var sn = AXIS_NORMALS[sd]; if (!sn) return;
        UNITS.forEach(function (u) {
          var pos, size;
          if (sd === 'x_neg') {
            pos  = { x: _r(u.leftX - centreOff),  y: _r(eaveH/2), z: _r(L/2) };
            size = { w: _r(L * 0.97), h: _r(eaveH), d: _r(th) };
          } else if (sd === 'x_pos') {
            pos  = { x: _r(u.rightX + centreOff), y: _r(eaveH/2), z: _r(L/2) };
            size = { w: _r(L * 0.97), h: _r(eaveH), d: _r(th) };
          } else {
            var apexH = Math.max(roofApexY, eaveH);
            // y_pos face is at z=L (outside extends to L+centreOff); y_neg at z=0 (outside at -centreOff).
            var zC = sd === 'y_pos' ? (_r(L) + centreOff) : -centreOff;
            pos  = { x: _r(u.centerX), y: _r(apexH/2), z: _r(zC) };
            size = { w: _r(unitWidth * 0.97), h: _r(apexH), d: _r(th) };
          }
          items.push({ id: 'env_reinf_'+layer.id+'_u'+u.index+'_'+sd, kind: 'reinforcement', source: 'envelope',
            position: pos, size: size, surface_normal: sn });
        });
      });
    });

    // ── Front reinforcement (front_only) ─────────────────────────────────────────────────
    var _frontLayers = (Array.isArray(env.layers) ? env.layers : [])
      .filter(function (l) { return l && l.type === 'front_only'; });
    _frontLayers.forEach(function (layer) {
      var sides = Array.isArray(layer.sides) ? layer.sides : [];
      var depth = parseFloat(layer.depth_m); if (!isFinite(depth) || depth <= 0) depth = 3.0;
      var apexH = Math.max(roofApexY, eaveH);
      sides.forEach(function (sdRaw) {
        var sd = _toAxisSide(sdRaw);
        if (sd !== 'y_pos' && sd !== 'y_neg') return;
        var sn = AXIS_NORMALS[sd];
        // y_pos center at z=L+depth/2, y_neg at -depth/2.
        var zC = sd === 'y_pos' ? _r(L + depth / 2) : _r(-depth / 2);
        UNITS.forEach(function (u) {
          items.push({ id: 'env_front_reinf_'+layer.id+'_u'+u.index+'_'+sd,
            kind: 'front_reinforcement', source: 'envelope',
            position: { x: _r(u.centerX), y: _r(apexH/2), z: zC },
            size: { w: _r(unitWidth), h: _r(apexH), d: _r(depth) },
            surface_normal: sn });
        });
      });
    });

    return items;
  }

  // ── Module-level fittings renderer (for the map context) ──────────────────────
  // Called from buildFacilityMesh (map overlay). Since it's outside the buildScene closure,
  // it only creates visual meshes without registering click targets.
  // opts: { totalWidth, length, actStates }
  function _buildFittingsIntoGroup(group, fittings, opts) {
    if (!Array.isArray(fittings) || !fittings.length) return;
    var totalWidth = (opts && opts.totalWidth) || 10;
    var length     = (opts && opts.length)     || 30;
    var actStates  = (opts && opts.actStates)  || {};
    // Sprinkler coverage circles: collection array for InstancedMesh batch
    var _irrigCovers = [];

    function _tc(key, fallback) {
      try {
        var cfg = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) || {};
        var hex = cfg[key];
        if (hex && typeof hex === 'string') return parseInt(hex.replace('#', ''), 16);
      } catch (e) {}
      return fallback;
    }

    function _quatFN(sn, spinDeg) {
      if (!sn || sn.length !== 3) return null;
      var N = new THREE.Vector3(sn[0], sn[1], sn[2]);
      if (N.lengthSq() < 0.0001) return null;
      N.normalize();
      var worldUp = new THREE.Vector3(0, 1, 0);
      var right = Math.abs(N.dot(worldUp)) > 0.99
        ? new THREE.Vector3(1, 0, 0)
        : new THREE.Vector3().crossVectors(worldUp, N).normalize();
      var up = new THREE.Vector3().crossVectors(N, right).normalize();
      var q = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(right, up, N));
      if (spinDeg) q.premultiply(new THREE.Quaternion().setFromAxisAngle(N, spinDeg * Math.PI / 180));
      return q;
    }

    function _orientFN(obj, sn, spinDeg) {
      var q = _quatFN(sn, spinDeg);
      if (!q) return false;
      obj.quaternion.copy(q);
      return true;
    }

    // Material settings for the map overlay.
    // opacity       — actual material property (simulation input, light transmittance/shading ratio, etc.)
    // renderOpacity — 3D-render-only transparency (visualization only, unrelated to simulation)
    //                 falls back to opacity when unspecified.
    var _FM = {
      window:        { color: 0x7ec8e3, opacity: 0.12, roughness: 0.05, renderOpacity: 0.28 },
      side_window:   { color: 0xb3dff5, opacity: 0.12, roughness: 0.05, renderOpacity: 0.22 },
      door:          { color: 0xa1887f, opacity: 0.95, roughness: 0.65, renderOpacity: 0.70 },
      curtain:       { color: 0xf0f0f0, opacity: 0.85, roughness: 0.85, renderOpacity: 0.10 },
      shade_curtain: { color: 0x1c1c1c, opacity: 0.92, roughness: 0.85, renderOpacity: 0.10 },
      reinforcement: { color: 0xb0bec5, opacity: 0.80, roughness: 0.60, renderOpacity: 0.55 },
      fan:           { color: 0x90caf9, opacity: 0.80, roughness: 0.50, renderOpacity: 0.80 },
      heater:        { color: 0xef9a9a, opacity: 0.80, roughness: 0.50, renderOpacity: 0.80 },
      sensor:        { color: 0xce93d8, opacity: 0.80, roughness: 0.50, renderOpacity: 0.80 },
      fixture:       { color: 0xc5e1a5, opacity: 0.80, roughness: 0.50, renderOpacity: 0.80 },
    };
    function _renderOp(m) { return m.renderOpacity != null ? m.renderOpacity : m.opacity; }
    // If a fitting is coplanar with the shell surface, depth-fighting makes it invisible.
    // Push it slightly along surface_normal so it always sits in front of the shell.
    var SURFACE_PUSH = 0.04; // m

    fittings.forEach(function (f) {
      if (!f) return;

      // ── Irrigation layer ──
      if (f.kind === 'irrigation_layer') {
        var h = parseFloat(f.height_m) || 2.0;
        var cHex = _tc('equipment', 0x007bff);
        var mg = new THREE.Group(); mg.name = 'fitting:' + f.id;
        var pts = [
          new THREE.Vector3(0, h, 0), new THREE.Vector3(totalWidth, h, 0),
          new THREE.Vector3(totalWidth, h, length), new THREE.Vector3(0, h, length),
          new THREE.Vector3(0, h, 0)
        ];
        mg.add(new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(pts),
          new THREE.LineBasicMaterial({ color: cHex, transparent: true, opacity: 0.5 })
        ));
        group.add(mg);
        return;
      }

      // ── Irrigation pipe ──
      if (f.kind === 'irrigation_pipe') {
        var layer = fittings.find(function (l) { return l.kind === 'irrigation_layer' && l.id === f.layer_id; });
        var layerH = layer ? (parseFloat(layer.height_m) || 2.0) : 2.0;
        var cHex = _tc('equipment', 0x007bff);
        var radius = parseFloat(f.radius) || 0.025;
        var pg = new THREE.Group(); pg.name = 'fitting:' + f.id;
        (Array.isArray(f.segments) ? f.segments : []).forEach(function (seg) {
          if (!seg.from || !seg.to) return;
          var p0 = new THREE.Vector3(seg.from[0], seg.from[1] != null ? seg.from[1] : layerH, seg.from[2]);
          var p1 = new THREE.Vector3(seg.to[0],   seg.to[1]   != null ? seg.to[1]   : layerH, seg.to[2]);
          if (p0.distanceTo(p1) < 0.05) return;
          pg.add(new THREE.Mesh(
            new THREE.TubeGeometry(new THREE.LineCurve3(p0, p1), 2, radius, 6, false),
            new THREE.MeshStandardMaterial({ color: cHex, roughness: 0.55, metalness: 0.35 })
          ));
        });
        if (!pg.children.length) {
          var s = new THREE.Mesh(
            new THREE.SphereGeometry(radius * 2, 6, 6),
            new THREE.MeshStandardMaterial({ color: cHex, transparent: true, opacity: 0.5 })
          );
          s.position.set(totalWidth / 2, layerH, length / 2);
          pg.add(s);
        }
        group.add(pg);
        return;
      }

      // ── Irrigation connection ──
      if (f.kind === 'irrigation_connection') {
        if (!f.position) return;
        var cMap = { mbT: 0xff9800, mT: 0xe65100, bT: 0xfdd835, mE: 0x000000, bE: 0x888888 };
        var mesh = new THREE.Mesh(
          new THREE.SphereGeometry(0.06, 12, 8),
          new THREE.MeshStandardMaterial({ color: cMap[f.sub_type || 'mbT'] || 0xff9800, roughness: 0.45, metalness: 0.4 })
        );
        mesh.position.set(parseFloat(f.position.x) || 0, parseFloat(f.position.y) || 2.0, parseFloat(f.position.z) || 0);
        mesh.name = 'fitting:' + f.id;
        group.add(mesh);
        return;
      }

      // ── Irrigation device (sprinkler head) ──
      if (f.kind === 'irrigation_device') {
        if (!f.position) return;
        var px = parseFloat(f.position.x) || 0, py = parseFloat(f.position.y) || 2.0, pz = parseFloat(f.position.z) || 0;
        var radiusM = parseFloat(f.radius_m) || 11;
        var tHex = _tc('equipment', 0x007bff);
        var _coneH = 0.18, _coneHalf = 0.09;
        var cone = new THREE.Mesh(
          new THREE.ConeGeometry(0.06, _coneH, 8),
          new THREE.MeshStandardMaterial({ color: tHex, roughness: 0.5, metalness: 0.3 })
        );
        // ConeGeometry: tip at local +Y, base at local -Y.
        // downward (down): base at pipe level (py), tip extends below → rotate π so tip → -Y,
        //               center at py - coneHalf → tip at py - coneH, base at py.
        // upward (up):   base at pipe level (py), tip extends above → no rotation,
        //               center at py + coneHalf → tip at py + coneH, base at py.
        if (f.orientation === 'up') {
          cone.position.set(px, py + _coneHalf, pz);
        } else {
          cone.rotation.z = Math.PI;
          cone.position.set(px, py - _coneHalf, pz);
        }
        cone.name = 'fitting:' + f.id;
        group.add(cone);
        // Sprinkler coverage circle: collected for the InstancedMesh batch (created in bulk after forEach).
        // Same single-draw-call principle as geo/design's single MapLibre fill layer.
        _irrigCovers.push({ px: px, pz: pz, radiusM: radiusM });
        return;
      }

      // ── General fittings (windows, curtains, doors, equipment, etc.) ──
      if (!f.size || !f.position) return;
      var w   = Math.max(parseFloat(f.size.w) || 0.1, 0.02);
      var fh  = Math.max(parseFloat(f.size.h) || 0.1, 0.02);
      var d   = Math.max(parseFloat(f.size.d) || 0.1, 0.02);
      var fpx = parseFloat(f.position.x) || 0;
      var fpy = parseFloat(f.position.y) || (fh / 2);
      var fpz = parseFloat(f.position.z) || 0;
      var rotDeg = parseFloat(f.rotation_deg) || 0;
      var _m  = _FM[f.kind] || _FM.fixture;
      var sn  = (Array.isArray(f.surface_normal) && f.surface_normal.length === 3) ? f.surface_normal : null;

      // Compute the push offset along surface_normal (prevents z-fighting).
      // For the ceiling (sn=null), push in the vertical (+Y) direction.
      var pushX = 0, pushY = 0, pushZ = 0;
      if (sn) {
        pushX = sn[0] * SURFACE_PUSH;
        pushY = sn[1] * SURFACE_PUSH;
        pushZ = sn[2] * SURFACE_PUSH;
      } else if (f.kind === 'curtain' || f.kind === 'shade_curtain') {
        pushY = -SURFACE_PUSH; // ceiling curtain: downward
      }

      // Ceiling curtain: folded or unfolded shape depending on actuator state
      var isCeilCurtain = (f.kind === 'curtain' || f.kind === 'shade_curtain') && !sn;
      if (isCeilCurtain) {
        var actKey = f.kind === 'shade_curtain' ? 'shade_curtain_motor' : 'thermal_curtain_motor';
        var isOpen = !!(actStates[actKey] && actStates[actKey].on);
        if (isOpen) {
          var foldW = Math.min(1.0, w * 0.22), foldH = Math.max(fh * 4, 0.14), foldD = d * 3;
          var offsetX = w / 2 - foldW / 2;
          ['L', 'R'].forEach(function (side) {
            var dx = side === 'L' ? -offsetX : offsetX;
            var fm = new THREE.Mesh(
              new THREE.BoxGeometry(foldW, foldH, foldD),
              new THREE.MeshStandardMaterial({ color: _m.color, transparent: true, opacity: _renderOp(_m), roughness: _m.roughness, depthWrite: false, side: THREE.DoubleSide })
            );
            fm.renderOrder = 1;
            fm.position.set(fpx + dx + pushX, fpy + pushY, fpz + pushZ);
            fm.name = 'fitting:' + (f.id || '') + ':' + side;
            group.add(fm);
          });
          return;
        }
      }

      // Front reinforcement: rendered directly in buildScene (extruded cross-section shape)
      if (f.kind === 'front_reinforcement') { return; }

      // Reinforcement: hollow shell (4-sided planes)
      if (f.kind === 'reinforcement') {
        var sMat = new THREE.MeshStandardMaterial({ color: _m.color, transparent: true, opacity: _renderOp(_m), roughness: _m.roughness, depthWrite: false, side: THREE.DoubleSide });
        var shell = new THREE.Group(); shell.name = 'fitting:' + (f.id || '');
        function _rp(pw, ph, lx, ly, lz, rx, ry) {
          var g = new THREE.PlaneGeometry(pw, ph);
          var m = new THREE.Mesh(g, sMat); m.renderOrder = 1; m.position.set(lx, ly, lz);
          if (rx) m.rotation.x = rx; if (ry) m.rotation.y = ry;
          shell.add(m);
          var e = new THREE.LineSegments(new THREE.EdgesGeometry(g), new THREE.LineBasicMaterial({ color: 0x546e7a }));
          e.position.copy(m.position); e.rotation.copy(m.rotation); shell.add(e);
        }
        _rp(w, fh, 0, 0, d / 2, 0, 0);
        _rp(w, d, 0, fh / 2, 0, -Math.PI / 2, 0);
        _rp(d, fh, -w / 2, 0, 0, 0, -Math.PI / 2);
        _rp(d, fh,  w / 2, 0, 0, 0,  Math.PI / 2);
        shell.position.set(fpx + pushX, fpy + pushY, fpz + pushZ);
        if (!_orientFN(shell, sn, rotDeg)) shell.rotation.y = rotDeg * Math.PI / 180;
        group.add(shell);
        return;
      }

      // Box fittings (windows, doors, fans, heaters, sensors, etc.)
      var geo = new THREE.BoxGeometry(w, fh, d);
      var mat = new THREE.MeshStandardMaterial({
        color: _m.color,
        transparent: true,
        opacity: _renderOp(_m),
        roughness: _m.roughness,
        depthWrite: false,
        side: THREE.DoubleSide,
      });
      var mesh = new THREE.Mesh(geo, mat);
      mesh.renderOrder = 1;
      mesh.position.set(fpx + pushX, fpy + pushY, fpz + pushZ);
      if (!_orientFN(mesh, sn, rotDeg)) mesh.rotation.y = rotDeg * Math.PI / 180;
      mesh.name = 'fitting:' + (f.id || '');
      group.add(mesh);
      var edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geo),
        new THREE.LineBasicMaterial({ color: 0x263238 })
      );
      edges.position.copy(mesh.position);
      edges.quaternion.copy(mesh.quaternion);
      edges.name = 'edges:fitting:' + (f.id || '');
      group.add(edges);
    });

    // ── Sprinkler coverage InstancedMesh batch flush ───────────────────────────────────
    // Like geo/design's single MapLibre fill layer, render all sprinkler radius circles
    // in one WebGL draw call (InstancedMesh: shared geometry/material).
    if (_irrigCovers.length) {
      var _tHex = (function () {
        try {
          var cfg = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) || {};
          var h = cfg['equipment'];
          if (h && typeof h === 'string') return parseInt(h.replace('#', ''), 16);
        } catch (e) {}
        return 0x007bff;
      })();
      var _cGeo = new THREE.CircleGeometry(1, 24); // radius=1 normalized, scaled per instance
      _cGeo.rotateX(-Math.PI / 2);                 // XZ horizontal plane (ground sprinkler footprint)
      var _cMat = new THREE.MeshBasicMaterial({
        color: _tHex, transparent: true, opacity: 0.15,
        side: THREE.DoubleSide, depthTest: false, depthWrite: false
      });
      var _iMesh = new THREE.InstancedMesh(_cGeo, _cMat, _irrigCovers.length);
      _iMesh.name = 'irrig_coverage_batch';
      _iMesh.renderOrder = 998;
      _iMesh.frustumCulled = false;
      var _dummy = new THREE.Object3D();
      _irrigCovers.forEach(function (c, i) {
        _dummy.position.set(c.px, 0.02, c.pz);
        _dummy.scale.setScalar(c.radiusM);
        _dummy.updateMatrix();
        _iMesh.setMatrixAt(i, _dummy.matrix);
      });
      _iMesh.instanceMatrix.needsUpdate = true;
      group.add(_iMesh);
    }
  }

  // ── GLB device icon loader (existing behaviour) ───────────────────────────────
  function _tryLoadGLB(type, position, parentGroup) {
    if (!window.THREE || !THREE.GLTFLoader) return;
    const loader = new THREE.GLTFLoader();
    loader.load('/static/models/aot_devices/' + type + '.glb',
      function (gltf) {
        const model = gltf.scene; model.scale.setScalar(0.42); model.position.copy(position);
        model.name = 'glb_' + type; if (parentGroup) parentGroup.add(model);
      }, undefined, function () {});
  }

  // ── GLTF user-asset scene builder (render_mode='asset') ──────────────────────
  function _buildAssetScene(canvas, facility, runtime, opts) {
    const W = opts.W, H = opts.H;
    const renderer = _createWebGL1Renderer(canvas);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(W, H, false);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf0f4f8);

    const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 1500);
    camera.position.set(8, 6, 12);
    camera.lookAt(0, 1, 0);

    const controls = new THREE.MapControls(camera, renderer.domElement);
    controls.target.set(0, 1, 0);
    controls.enableDamping = true; controls.dampingFactor = 0.12; controls.update();

    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const sun = new THREE.DirectionalLight(0xfff4d6, 0.85); sun.position.set(10, 20, 10); scene.add(sun);

    // Ground
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(100,100), new THREE.MeshStandardMaterial({color:0xffffff,roughness:0.9}));
    ground.rotation.x = -Math.PI/2; ground.position.y = -0.01; scene.add(ground);
    scene.add(Object.assign(new THREE.GridHelper(50,25,0xbbbbbb,0xdddddd), {position:{y:0.005}}));

    // Status label
    const statusEl = opts.statusEl;
    if (statusEl) statusEl.textContent = (window._ ? window._('Loading asset model…') : 'Loading asset model…');

    const transform = facility.model_transform;
    const assetInfo = opts.assetInfo;  // {unique_id, source_file}

    if (assetInfo && assetInfo.source_file && window.AoTGLTFLoader) {
      AoTGLTFLoader.loadAsset(
        assetInfo.unique_id, assetInfo.source_file, transform, scene,
        function (model) {
          // Auto-fit camera to bounding box
          const box = new THREE.Box3().setFromObject(model);
          const center = box.getCenter(new THREE.Vector3());
          const size = box.getSize(new THREE.Vector3());
          const maxDim = Math.max(size.x, size.y, size.z);
          camera.position.set(center.x + maxDim * 1.2, center.y + maxDim * 0.8, center.z + maxDim * 1.5);
          camera.lookAt(center);
          controls.target.copy(center);
          controls.update();
          if (statusEl) statusEl.textContent = '';
          requestRender();   // on-demand: render one frame for the async-loaded model
        },
        function (err) {
          console.warn('[AoT 3D] Asset load error:', err);
          if (statusEl) statusEl.textContent = (window._ ? window._('Model load failed') : 'Model load failed');
        }
      );
    } else if (statusEl) {
      statusEl.textContent = (window._ ? window._('No asset information') : 'No asset information');
    }

    // ─── Render-on-demand (CPU/battery savings) ──────────────────────────────────────
    // Instead of a constant 60fps RAF loop, render only on changes (camera ops, model load, resize, etc.).
    // Keep a short RAF loop only during interaction (MapControls start→end) for damping settle.
    // (same pattern as the parametric viewer _buildParametricScene)
    let animId = null;
    let _interacting = false;
    let _disposed = false;
    let _settleUntil = 0;            // damping settle: keep rendering for a while after 'end'

    function _renderOnce() {
      if (_disposed) return;
      controls.update();
      renderer.render(scene, camera);
    }
    function _loop() {
      if (_disposed) { animId = null; return; }
      const now = performance.now();
      if (!_interacting && now > _settleUntil) { animId = null; _renderOnce(); return; }
      animId = requestAnimationFrame(_loop);
      _renderOnce();
    }
    function _scheduleRender() {
      if (_disposed) return;
      if (animId == null) animId = requestAnimationFrame(_loop);
    }
    // Force re-render from external/async callbacks (model load complete, resize, etc.)
    function requestRender() { _settleUntil = performance.now() + 50; _scheduleRender(); }

    controls.addEventListener('start',  function () { _interacting = true;  _scheduleRender(); });
    controls.addEventListener('change', function () { _settleUntil = performance.now() + 80; _scheduleRender(); });
    controls.addEventListener('end',    function () { _interacting = false; _settleUntil = performance.now() + 400; _scheduleRender(); });

    const resizeObs = new ResizeObserver(() => {
      const cw = canvas.parentElement ? canvas.parentElement.clientWidth : canvas.clientWidth;
      const ch = canvas.parentElement ? canvas.parentElement.clientHeight : canvas.clientHeight;
      if (cw > 0 && ch > 0) {
        renderer.setSize(cw,ch,false); camera.aspect=cw/ch; camera.updateProjectionMatrix();
        requestRender();
      }
    });
    if (canvas.parentElement) resizeObs.observe(canvas.parentElement);

    // Tab visibility: stop pointless rendering in background tabs, draw one frame on return.
    function _onVisibilityChange() {
      if (document.hidden) {
        if (animId != null) cancelAnimationFrame(animId);
        animId = null; _interacting = false;
      } else if (!_disposed) {
        _settleUntil = performance.now() + 100;
        _scheduleRender();
      }
    }
    document.addEventListener('visibilitychange', _onVisibilityChange);

    // Initial frame + a short loop for the first ~1s (layout / async loading correction).
    _renderOnce();
    _settleUntil = performance.now() + 1000;
    _scheduleRender();

    function dispose() {
      _disposed = true;
      if (animId != null) cancelAnimationFrame(animId);
      animId = null;
      document.removeEventListener('visibilitychange', _onVisibilityChange);
      resizeObs.disconnect(); controls.dispose(); renderer.dispose();
    }
    return { renderer, scene, camera, controls, dispose, requestRender };
  }

  // ── Slot label map ────────────────────────────────────────────────────────────
  function _slotLabel(key) {
    var _t = (window._ ? window._ : function (s) { return s; });
    return ({
      outer_side_vent_motor:_t('Outer Side Vent Motor'), outer_roof_vent_motor:_t('Outer Roof Vent Motor'),
      inner_side_vent_motor:_t('Inner Side Vent Motor'), inner_roof_vent_motor:_t('Inner Roof Vent Motor'),
      thermal_curtain:_t('Thermal Curtain'), shade_curtain:_t('Shade Curtain'), irrigation_valve:_t('Irrigation Valve'),
      circulation_fan:_t('Circulation Fan'), exhaust_fan:_t('Exhaust Fan'), heater:_t('Heater'), cooler:_t('Cooler'), heat_pump:_t('Heat Pump'),
    })[key] || key;
  }

  // ── Render mode: post-build traversal ──────────────────────────────────────────
  // Applies 'solid' / 'wireframe' / 'performance' to a scene group after build.
  // 'default' is the untouched baseline. On the interactive canvas widget
  // 'performance' is handled separately via setFastMode; on the MAP overlay it is
  // handled here as a cheap cartoon look (see below).
  function _applyRenderMode(root, mode) {
    if (!mode || mode === 'default') return;

    // 'performance' (map overlay): cartoon/cel look that is CHEAPER than the default
    // transparent-PBR covers — opaque single-color faces (MeshBasicMaterial: no
    // lighting, no blending, no overdraw) with the pre-built edge lines darkened for
    // a strong outline. Each material keeps its own base color so parts stay distinct.
    if (mode === 'performance') {
      root.traverse(function (obj) {
        if (obj.isLineSegments || obj.isLine) {
          var lms = Array.isArray(obj.material) ? obj.material : [obj.material];
          lms.forEach(function (lm) {
            if (lm && lm.color) { lm.color.setHex(0x263238); lm.needsUpdate = true; }
          });
          return;
        }
        if (!obj.isMesh) return;
        var src = Array.isArray(obj.material) ? obj.material : [obj.material];
        var flat = src.map(function (mat) {
          if (!mat) return mat;
          var col = (mat.color && mat.color.clone) ? mat.color.clone() : new THREE.Color(0xcfd8dc);
          var basic = new THREE.MeshBasicMaterial({
            color: col,
            side: mat.side || THREE.FrontSide,
            transparent: false,
            opacity: 1
          });
          try { mat.dispose(); } catch (e) {}
          return basic;
        });
        obj.material = Array.isArray(obj.material) ? flat : flat[0];
      });
      return;
    }

    root.traverse(function (obj) {
      if (!obj.isMesh) return;
      var mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      mats.forEach(function (mat) {
        if (!mat) return;
        if (mode === 'wireframe') {
          mat.wireframe  = true;
          mat.transparent = false;
          mat.opacity    = 1;
          mat.depthWrite = true;
        } else if (mode === 'solid') {
          mat.wireframe  = false;
          mat.transparent = false;
          mat.opacity    = 1;
          mat.depthWrite = true;
          mat.side       = THREE.FrontSide;
        }
        mat.needsUpdate = true;
      });
    });
  }

  // ── Main builder (public, backward-compat) ───────────────────────────────────
  function buildScene(canvas, facility, runtime, opts) {
    // Update FacilityState
    FacilityState.setSpec(facility);
    if (runtime) FacilityState.setRuntime(runtime);

    const parent = canvas.parentElement;
    const W = (parent && parent.clientWidth) || canvas.clientWidth || 400;
    const H = (parent && parent.clientHeight) || canvas.clientHeight || 340;

    // ── GLTF asset render path ────────────────────────────────────────────────
    if (facility.render_mode === 'asset' && facility.model_asset_uuid) {
      // Fetch asset info then render
      const statusEl = parent && parent.querySelector('.aot-3d-asset-status');
      const opts = { W, H, statusEl, assetInfo: null };

      // If asset source already attached to facility object (pre-fetched)
      if (facility._asset_source_file) {
        opts.assetInfo = { unique_id: facility.model_asset_uuid, source_file: facility._asset_source_file };
        return _buildAssetScene(canvas, facility, runtime, opts);
      }

      // Otherwise fetch from API
      fetch('/api/geo/model_assets/' + facility.model_asset_uuid)
        .then(r => r.ok ? r.json() : null)
        .then(function (asset) {
          if (!asset || !asset.source_file) return;
          opts.assetInfo = { unique_id: asset.unique_id, source_file: asset.source_file };
          // Renderer already set up without model — add model now
          // (simplification: full rebuild with asset info)
          ctx.dispose && ctx.dispose();
        })
        .catch(() => {});

      // Render empty scene while fetching
      const ctx = _buildParametricScene(canvas, facility, runtime, W, H);
      return ctx;
    }

    const renderMode = (opts && opts.renderMode) || 'default';

    // ── Parametric render path (default) ─────────────────────────────────────
    return _buildParametricScene(canvas, facility, runtime, W, H, renderMode);
  }

  function _buildParametricScene(canvas, facility, runtime, W, H, renderMode) {
    const g3d = facility.geometry_3d || {};
    const envelope = facility.envelope || {};
    const actuators = facility.actuators || {};
    const actStates = (runtime && runtime.actuator_states) || {};
    const outdoor = (runtime && runtime.outdoor) || {};

    const span      = parseFloat(g3d.span_width_m)   || 7;
    const eaveH     = parseFloat(g3d.eave_height_m)  || 2;
    const ridgeH    = parseFloat(g3d.ridge_height_m) || 4;
    const length    = parseFloat(g3d.length_m)       || 30;
    const roofType  = String(g3d.roof_type || 'arch').toLowerCase();
    const orientDeg = parseFloat(g3d.orientation_deg) || 0;
    const rawBayCount = Math.max(parseInt(facility.bay_count||1,10),1);
    const isConnected = facility.structure === 'connected';
    // Connected → 1 house with N joined bays. Single → N separate single-bay
    // houses with a user-defined gap between each. unitCount drives how many
    // standalone house meshes are emitted; meshBayCount drives how many bays
    // are inside one of those meshes (always 1 for single-replicated).
    const unitCount     = isConnected ? 1 : rawBayCount;
    const meshBayCount  = isConnected ? rawBayCount : 1;
    // Connected bays share walls so spacing=0 always. For single replication,
    // spacing comes from the form (defaults to 0 if blank rather than 1 so the
    // preview matches the user-entered value precisely).
    const effectiveSpacing = isConnected ? 0 : (parseFloat(g3d.spacing_m)||0);
    const unitWidth = meshBayCount * span + (meshBayCount-1) * effectiveSpacing;
    const totalWidth = unitCount * unitWidth + (unitCount-1) * effectiveSpacing;
    // bayCount kept as alias for legacy references further down the function.
    const bayCount = meshBayCount;
    // layers[] format: inner layer present → double. Legacy: layer_count === 2.
    const isDouble  = Array.isArray(envelope.layers)
      ? envelope.layers.some(l => l.role === 'inner')
      : (envelope.layer_count || 1) === 2;

    const renderer = _createWebGL1Renderer(canvas);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, renderMode === 'performance' ? 1.5 : 2.0));
    renderer.setSize(W, H, false);
    // CPU savings — shadows are nearly meaningless for facility preview. Big single saving (-30~50% fragment cost).
    renderer.shadowMap.enabled = false;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf0f4f8);
    const _fogNear = Math.max(totalWidth, length) * 4;
    scene.fog = new THREE.Fog(0xf0f4f8, _fogNear, _fogNear * 2);

    const cx = totalWidth/2, cz = length/2, cy = ridgeH*0.5;
    const camera = new THREE.PerspectiveCamera(45, W/H, 0.1, 1500);

    // Initial camera: use the same formula as the cube-view 'iso' button so that
    // the initial view is identical to clicking iso — guaranteed to show the whole model.
    {
      const _hw = totalWidth/2, _hh = ridgeH/2, _hl = length/2;
      const _br = Math.sqrt(_hw*_hw + _hh*_hh + _hl*_hl);
      const _halfFovV = 45/2 * Math.PI / 180;
      const _dist = _br / Math.sin(_halfFovV) * 1.18;
      const _dir = new THREE.Vector3(0.55, 0.85, 0.65).normalize();
      camera.position.set(cx + _dir.x * _dist, cy + _dir.y * _dist, cz + _dir.z * _dist);
    }
    camera.lookAt(cx, cy, cz);

    const _origTarget = new THREE.Vector3(cx, cy, cz);
    const controls = new THREE.MapControls(camera, renderer.domElement);
    controls.target.copy(_origTarget);
    controls.enableDamping = true; controls.dampingFactor = 0.12;
    controls.panSpeed = 0.5; controls.rotateSpeed = 0.8;
    controls.minDistance = 2; controls.maxDistance = Math.max(totalWidth, length) * 20;
    controls.maxPolarAngle = Math.PI * 0.82;
    controls.update();
    renderer.domElement.style.cursor = 'crosshair';

    if (window.MeshBVHLib) {
      THREE.BufferGeometry.prototype.computeBoundsTree = MeshBVHLib.computeBoundsTree;
      THREE.BufferGeometry.prototype.disposeBoundsTree = MeshBVHLib.disposeBoundsTree;
      THREE.Mesh.prototype.raycast = MeshBVHLib.acceleratedRaycast;
    }

    let _dragged = false;
    renderer.domElement.addEventListener('mousedown', () => { _dragged = false; });
    renderer.domElement.addEventListener('mousemove', (e) => { if (e.buttons) _dragged = true; });

    function teleport(newCamPos) {
      if (window.gsap) {
        gsap.killTweensOf(camera.position); gsap.killTweensOf(controls.target);
        gsap.to(camera.position, {x:newCamPos.x,y:newCamPos.y,z:newCamPos.z,duration:0.65,ease:'power2.inOut',onUpdate:()=>controls.update()});
        gsap.to(controls.target, {x:_origTarget.x,y:_origTarget.y,z:_origTarget.z,duration:0.65,ease:'power2.inOut',onUpdate:()=>controls.update()});
      } else { controls.target.copy(_origTarget); camera.position.copy(newCamPos); controls.update(); }
    }
    function scaleDist(factor) {
      const dir = camera.position.clone().sub(controls.target);
      camera.position.copy(controls.target.clone().addScaledVector(dir.normalize(), dir.length()*factor));
      controls.update();
    }
    controls.teleport = teleport; controls.scaleDist = scaleDist; controls.isPanDragging = () => _dragged;

    const solarIntensity = outdoor.solar_wm2!=null ? 0.4+Math.min(outdoor.solar_wm2/1000,1)*0.8 : 0.85;
    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const sun = new THREE.DirectionalLight(0xfff4d6, solarIntensity);
    sun.position.set(30,60,40); sun.castShadow = true; scene.add(sun);

    // Support new layers[] format from EnvelopeUI.read() as well as legacy outer/inner flat format
    const _envLayers = Array.isArray(envelope.layers) ? envelope.layers : null;
    const _outerLayer = _envLayers ? (_envLayers.find(l => l.role === 'outer') || {}) : {};
    const _innerLayer = _envLayers ? (_envLayers.find(l => l.role === 'inner') || null) : null;
    const outerEnvSpec = envelope.outer || {};
    const innerEnvSpec = envelope.inner || {};
    const outerCoverMat = (_outerLayer.cover) || outerEnvSpec.cover_material || 'vinyl_double';
    const innerCoverMat = (_innerLayer && _innerLayer.cover) || innerEnvSpec.cover_material || 'non_woven_fabric';
    const ghGroup = new THREE.Group(); ghGroup.name = 'greenhouse'; scene.add(ghGroup);
    const clickTargets = [];

    // Outer cover + (optional) inner cover are extruded ONCE per unit shape
    // and then instanced per unit by offsetting along X. For connected mode
    // unitCount=1 so this loop becomes the same single-mesh path as before.
    const extrudeSettings = { steps:1, depth:length, bevelEnabled:false };
    // Outer cover: openable panels (side/end windows punch real holes). Openings
    // are derived from the SAME facility.fittings the vent overlays render from,
    // so holes and overlays stay consistent and never double up.
    if (P && P.buildOuterCoverPanels) {
      ghGroup.add(P.buildOuterCoverPanels({
        unitCount: unitCount, unitWidth: unitWidth, effectiveSpacing: effectiveSpacing,
        meshBayCount: meshBayCount, span: span, eaveH: eaveH, ridgeH: ridgeH,
        roofType: roofType, length: length, material: MAT.cover(outerCoverMat),
        openings: P.coverOpeningsFromFittings(Array.isArray(facility.fittings) ? facility.fittings : []),
      }));
    } else {
      const outerShape = _buildMultiSpanShape(span, eaveH, ridgeH, roofType, meshBayCount, effectiveSpacing);
      const outerGeo = new THREE.ExtrudeGeometry(outerShape, extrudeSettings);
      for (let u = 0; u < unitCount; u++) {
        const xOff = u * (unitWidth + effectiveSpacing);
        const outerMesh = new THREE.Mesh(outerGeo, MAT.cover(outerCoverMat));
        outerMesh.name = 'outer_cover_' + u;
        outerMesh.position.x = xOff;
        outerMesh.renderOrder = 1000;
        ghGroup.add(outerMesh);
        const edgeMesh = new THREE.LineSegments(new THREE.EdgesGeometry(outerGeo),
          new THREE.LineBasicMaterial({ color: 0x455a64 }));
        edgeMesh.position.x = xOff;
        ghGroup.add(edgeMesh);
      }
    }
    let innerGeo = null;
    if (isDouble) {
      const inset = 0.15;
      const innerShape = _buildMultiSpanShape(span-inset*2, eaveH-inset*0.5, ridgeH-inset, roofType, meshBayCount, effectiveSpacing);
      innerGeo = new THREE.ExtrudeGeometry(innerShape, {...extrudeSettings, depth:length-inset*2});
    }
    for (let u = 0; u < unitCount; u++) {
      const xOff = u * (unitWidth + effectiveSpacing);
      if (innerGeo) {
        const inset = 0.15;
        const innerMesh = new THREE.Mesh(innerGeo, MAT.coverInner(innerCoverMat));
        innerMesh.name = 'inner_cover_' + u;
        innerMesh.position.set(xOff + inset, 0, inset);
        innerMesh.renderOrder = 900;
        ghGroup.add(innerMesh);
      }
    }

    if (isConnected) {
      const gm = new THREE.MeshStandardMaterial({color:0x607d8b,roughness:0.5,metalness:0.5});
      for (let b=1; b<meshBayCount; b++) {
        [length*0.25, length*0.75].forEach(z => {
          const col = new THREE.Mesh(new THREE.BoxGeometry(0.05,eaveH,0.05), gm);
          col.position.set(b*span, eaveH/2, z); ghGroup.add(col);
        });
      }
    }

    const floorGeo = new THREE.BoxGeometry(totalWidth,0.06,length);
    const floorMesh = new THREE.Mesh(floorGeo, MAT.floor());
    floorMesh.position.set(totalWidth/2, 0.03, length/2);
    floorMesh.name = 'facility_floor';   // raycast target for device drag-place
    ghGroup.add(floorMesh);

    // Front reinforcement (front reinforcement) — env.layers[type=front_only]
    // Each layer adds an extension of the facility cross-section shape on the
    // south (z < 0) and/or north (z > length) end.
    // Uses the same outer cover material as the main facility so the extension
    // looks like a seamless annex. userData encodes snap geometry so window/door
    // placement on these faces uses the correct center, not the main-facility wall.
    {
      const _frontLayers = Array.isArray(envelope.layers)
        ? envelope.layers.filter(l => l && l.type === 'front_only')
        : [];
      if (_frontLayers.length > 0) {
        const frontEdgeMat = new THREE.LineBasicMaterial({ color: 0x455a64 });
        _frontLayers.forEach(layer => {
          const sides = Array.isArray(layer.sides) ? layer.sides : [];
          const depth = parseFloat(layer.depth_m);
          const d = (isFinite(depth) && depth > 0) ? depth : 3.0;
          const frontShape = _buildMultiSpanShape(span, eaveH, ridgeH, roofType, bayCount, effectiveSpacing);
          const frontGeo = new THREE.ExtrudeGeometry(frontShape,
            { steps: 1, depth: d, bevelEnabled: false });
          for (let u = 0; u < unitCount; u++) {
            const xOff = u * (unitWidth + effectiveSpacing);
            const xCenter = xOff + unitWidth / 2;
            // Axis-based: y_pos face at z=length, y_neg face at z=0.
            const _axSides = sides.map(_toAxisSide);
            if (_axSides.indexOf('y_pos') >= 0) {
              const sm = new THREE.Mesh(frontGeo, MAT.cover(outerCoverMat));
              sm.name = 'front_reinf_y_pos_' + layer.id + '_u' + u;
              sm.position.set(xOff, 0, length);
              sm.renderOrder = 1000;
              sm.userData.isFrontReinf  = true;
              sm.userData.frSide        = 'y_pos';
              sm.userData.frDepth       = d;
              sm.userData.frXCenter     = xCenter;
              sm.userData.frZOuter      = length + d;
              sm.userData.frZCenter     = length + d / 2;
              ghGroup.add(sm);
              const se = new THREE.LineSegments(new THREE.EdgesGeometry(frontGeo), frontEdgeMat);
              se.position.copy(sm.position);
              ghGroup.add(se);
            }
            if (_axSides.indexOf('y_neg') >= 0) {
              const nm = new THREE.Mesh(frontGeo, MAT.cover(outerCoverMat));
              nm.name = 'front_reinf_y_neg_' + layer.id + '_u' + u;
              nm.position.set(xOff, 0, -d);
              nm.renderOrder = 1000;
              nm.userData.isFrontReinf  = true;
              nm.userData.frSide        = 'y_neg';
              nm.userData.frDepth       = d;
              nm.userData.frXCenter     = xCenter;
              nm.userData.frZOuter      = -d;
              nm.userData.frZCenter     = -d / 2;
              ghGroup.add(nm);
              const ne = new THREE.LineSegments(new THREE.EdgesGeometry(frontGeo), frontEdgeMat);
              ne.position.copy(nm.position);
              ghGroup.add(ne);
            }
          }
        });
      }
    }

    // Wall reinforcement (side-wall reinforcement) is rendered EXCLUSIVELY via the
    // envelope-fitting system in geo_facility.html → _renderEnvelopeFittings
    // (kind='reinforcement'). The prior direct-render path used PlaneGeometry
    // which ignored thickness_m (width) — panels appeared as zero-depth slivers
    // and never showed up in the right-side fittings list. Routing through
    // FittingsUI keeps the side reinforcement consistent with all other
    // envelope-derived items (side_vent, roof_vent, curtain).

    // Envelope-driven elements (outer side vent / outer roof vent / thermal
    // ceiling curtain / shade curtain) are now rendered EXCLUSIVELY via the
    // envelope-fitting system in _renderEnvelopeFittings — no hardcoded
    // fallback. The old fallbacks created persistent ghost meshes (e.g. the
    // buildCurtain w=totalWidth*0.02 sliver) that survived envelope toggle-off
    // because fitting-removed only cleans up envelope-sourced fittings, not
    // arbitrary scene meshes. Inner vents stay on the fallback path because
    // EnvelopeUI exposes no UI for them yet.
    const _svOuter = (envelope.side_vent && envelope.side_vent.outer) || outerEnvSpec.side_vent || {};
    const _rvOuter = (envelope.roof_vent && envelope.roof_vent.outer) || outerEnvSpec.roof_vent || {};
    void _svOuter; void _rvOuter;   // referenced for legacy compute paths elsewhere

    // Inner vents — still hardcoded because no envelope-fitting equivalent yet.
    if (isDouble) {
      const inset = 0.18;
      const _svInner = innerEnvSpec.side_vent || {};
      const _rvInner = innerEnvSpec.roof_vent || {};
      if (_svInner.enabled) {
        const st = actStates['inner_side_vent_motor'], openR = st ? (st.on ? 0.65 : 0) : 0;
        const iL = buildSideVentSash(eaveH,length*0.82,openR,false); iL.position.set(inset,eaveH*0.45,length/2); ghGroup.add(iL);
        const iR = buildSideVentSash(eaveH,length*0.82,openR,true);  iR.position.set(totalWidth-inset,eaveH*0.45,length/2); ghGroup.add(iR);
        clickTargets.push({mesh:iL,slot:'inner_side_vent_motor'},{mesh:iR,slot:'inner_side_vent_motor'});
      }
      if (_rvInner.enabled) {
        const st = actStates['inner_roof_vent_motor'], openR = st ? (st.on ? 0.6 : 0) : 0;
        for (let b=0; b<bayCount; b++) {
          const bx = b*(span+effectiveSpacing)+span/2;
          const iv = buildRoofVentIndicator(span*0.8,ridgeH-inset,length,openR); iv.position.set(bx,ridgeH-inset+0.02,length/2); ghGroup.add(iv);
          clickTargets.push({mesh:iv,slot:'inner_roof_vent_motor'});
        }
      }
    }

    // Outer thermal / shade curtain hardcoded fallbacks REMOVED — they are
    // now rendered only via env_curtain_thermal_ceil_* / env_curtain_shade
    // envelope fittings. See _renderEnvelopeFittings in geo_facility.html.
    const curtain = envelope.curtain || {};
    void curtain;

    // Equipment
    const centerX = Math.floor(bayCount/2)*(span+effectiveSpacing)+span/2;
    [
      {key:'circulation_fan', pos:new THREE.Vector3(centerX,eaveH*0.65,length*0.25)},
      {key:'exhaust_fan',     pos:new THREE.Vector3(centerX,eaveH*0.65,length*0.75)},
      {key:'heater',          pos:new THREE.Vector3(centerX-span*0.3,0.35,length*0.2)},
      {key:'cooler',          pos:new THREE.Vector3(centerX-span*0.3,0.35,length*0.8)},
      {key:'heat_pump',       pos:new THREE.Vector3(centerX+span*0.3,0.35,length*0.5)},
      {key:'irrigation_valve',pos:new THREE.Vector3(centerX+span*0.2,0.35,length*0.4)},
    ].forEach(({key,pos}) => {
      const state = actStates[key]; if (!actuators[key] && !state) return;
      const icon = buildDeviceIcon(key, state ? state.on : false, pos); ghGroup.add(icon);
      clickTargets.push({mesh:icon.children[0],slot:key,group:icon});
      _tryLoadGLB(key, pos, ghGroup);
    });

    // Pipes
    if (actuators['irrigation_valve'] || actStates['irrigation_valve']) {
      const iOn = !!(actStates['irrigation_valve'] && actStates['irrigation_valve'].on);
      ghGroup.add(buildIrrigationPipes(totalWidth,length,span,bayCount,effectiveSpacing,iOn));
    }
    if (actuators['heater'] || actStates['heater']) {
      const hOn = !!(actStates['heater'] && actStates['heater'].on);
      ghGroup.add(buildHeatingPipes(totalWidth,length,hOn));
    }

    // Fittings (user-placed boxes: windows, doors, curtains, devices) ─────────
    const fittings = Array.isArray(facility.fittings) ? facility.fittings : [];
    // opacity       — actual material property (simulation input: light transmittance, shading ratio, etc.)
    // renderOpacity — 3D-render-only transparency (visualization only, independent of simulation)
    //                 falls back to opacity when unspecified.
    const _FIT_MAT = {
      window:        { color: 0x7ec8e3, opacity: 0.12, roughness: 0.05, renderOpacity: 0.28 },
      side_window:   { color: 0xb3dff5, opacity: 0.12, roughness: 0.05, renderOpacity: 0.22 },
      door:          { color: 0xa1887f, opacity: 0.95, roughness: 0.65, renderOpacity: 0.70 },
      curtain:       { color: 0xf0f0f0, opacity: 0.85, roughness: 0.85, renderOpacity: 0.10 },
      shade_curtain: { color: 0x1c1c1c, opacity: 0.92, roughness: 0.85, renderOpacity: 0.10 },
      // Reinforcement: opaque tinted layer on wall — distinct from the outer
      // cover (vinyl_double / vinyl_single) while still reading as a panel.
      reinforcement:       { color: 0xb0bec5, opacity: 0.80, roughness: 0.60, renderOpacity: 0.55 },
      front_reinforcement: { color: 0xb0bec5, opacity: 0.80, roughness: 0.60, renderOpacity: 0.55 },
      fan:           { color: 0x90caf9, opacity: 0.80, roughness: 0.50, renderOpacity: 0.80 },
      heater:        { color: 0xef9a9a, opacity: 0.80, roughness: 0.50, renderOpacity: 0.80 },
      sensor:        { color: 0xce93d8, opacity: 0.80, roughness: 0.50, renderOpacity: 0.80 },
      fixture:       { color: 0xc5e1a5, opacity: 0.80, roughness: 0.50, renderOpacity: 0.80 },
    };
    function _fitRenderOp(m) { return m.renderOpacity != null ? m.renderOpacity : m.opacity; }
    const _selFittingId = (window.FittingsUI && FittingsUI.getSelectedId)
      ? FittingsUI.getSelectedId() : null;
    // Build a full orthonormal basis from a surface normal so that:
    //   local +X (width)  → horizontal, perpendicular to the normal
    //   local +Y (height) → in-plane "up the slope" direction
    //   local +Z (depth)  → the surface normal itself
    // This avoids the "diamond/rhombus" artefact you get with setFromUnitVectors,
    // which leaves the rotation around the normal axis undefined.
    function _quatFromNormal(surfaceNormal, spinDeg) {
      if (!surfaceNormal || surfaceNormal.length !== 3) return null;
      const N = new THREE.Vector3(surfaceNormal[0], surfaceNormal[1], surfaceNormal[2]);
      if (N.lengthSq() < 0.0001) return null;
      N.normalize();

      const worldUp = new THREE.Vector3(0, 1, 0);
      let right;
      if (Math.abs(N.dot(worldUp)) > 0.99) {
        // Normal is (nearly) vertical: pick world +X as the width direction
        right = new THREE.Vector3(1, 0, 0);
      } else {
        // Width = worldUp × N → horizontal, perpendicular to N
        right = new THREE.Vector3().crossVectors(worldUp, N).normalize();
      }
      // Height = N × width → in the surface plane, pointing "up the slope"
      const up = new THREE.Vector3().crossVectors(N, right).normalize();

      const m = new THREE.Matrix4().makeBasis(right, up, N);
      const q = new THREE.Quaternion().setFromRotationMatrix(m);

      if (spinDeg) {
        // Spin around the normal (in-plane rotation)
        const spin = new THREE.Quaternion().setFromAxisAngle(N, spinDeg * Math.PI / 180);
        q.premultiply(spin);
      }
      return q;
    }

    function _orientFromNormal(meshObj, surfaceNormal, spinDeg) {
      const q = _quatFromNormal(surfaceNormal, spinDeg);
      if (!q) return false;
      meshObj.quaternion.copy(q);
      return true;
    }

    // ── Irrigation layer/pipe renderer ────────────────────────────────────────────────
    // Like the geo/design theme system, pull colors from AOT_GEO_CONFIG.theme_config.
    // All irrigation (equipment) elements must use the same theme key.
    function _themeColor(key, fallbackHex) {
      try {
        const cfg = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) || {};
        const hex = cfg[key];
        if (hex && typeof hex === 'string') {
          return parseInt(hex.replace('#', ''), 16);
        }
      } catch (e) {}
      return fallbackHex;
    }
    function _themeColorHex(key, fallbackHex) {
      try {
        const cfg = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) || {};
        const hex = cfg[key];
        if (hex && typeof hex === 'string') return hex;
      } catch (e) {}
      return fallbackHex;
    }

    function _buildIrrigationLayerMarker(f) {
      // thin disc at height_m as a visual layer reference
      const h = parseFloat(f.height_m) || 2.0;
      // Layer marker follows the equipment theme color (geo/design default #007bff).
      const colorHex = _themeColor('equipment', 0x007bff);
      const isSel = (f.id === (window.FittingsUI && FittingsUI.getSelectedId ? FittingsUI.getSelectedId() : null));
      const markerGroup = new THREE.Group();
      markerGroup.name = 'fitting:' + f.id;
      // horizontal dashed line across facility width at this height
      const pts = [];
      pts.push(new THREE.Vector3(0, h, 0));
      pts.push(new THREE.Vector3(totalWidth, h, 0));
      pts.push(new THREE.Vector3(totalWidth, h, length));
      pts.push(new THREE.Vector3(0, h, length));
      pts.push(new THREE.Vector3(0, h, 0));
      const lineGeo = new THREE.BufferGeometry().setFromPoints(pts);
      const lineMat = new THREE.LineBasicMaterial({
        color: isSel ? 0xffeb3b : colorHex,
        transparent: true, opacity: isSel ? 0.9 : 0.5,
        linewidth: 1
      });
      const line = new THREE.Line(lineGeo, lineMat);
      line.name = 'irr_layer_outline:' + f.id;
      markerGroup.add(line);
      // label plane (thin horizontal strip)
      const labelGeo = new THREE.PlaneGeometry(Math.min(totalWidth * 0.3, 2.0), 0.08);
      const labelMat = new THREE.MeshBasicMaterial({
        color: isSel ? 0xffeb3b : colorHex,
        transparent: true, opacity: isSel ? 0.85 : 0.45,
        side: THREE.DoubleSide
      });
      const labelMesh = new THREE.Mesh(labelGeo, labelMat);
      labelMesh.position.set(totalWidth * 0.15, h, 0.5);
      labelMesh.rotation.x = -Math.PI / 2;
      markerGroup.add(labelMesh);
      ghGroup.add(markerGroup);
      if (f.id) clickTargets.push({ mesh: labelMesh, slot: 'fitting:' + f.id, fittingId: f.id });
      return markerGroup;
    }

    function _buildIrrigationPipeMesh(f) {
      // fittings array may be stale for incremental adds — fall back to FittingsUI live data
      let layer = fittings.find(function (l) { return l.kind === 'irrigation_layer' && l.id === f.layer_id; });
      if (!layer && window.FittingsUI && FittingsUI.readAll) {
        const live = FittingsUI.readAll();
        layer = live.find(function (l) { return l.kind === 'irrigation_layer' && l.id === f.layer_id; });
      }
      const layerH = layer ? (parseFloat(layer.height_m) || 2.0) : 2.0;
      // Pipes ignore layer.color; use the equipment theme color, same as geo/design.
      const colorHex = _themeColor('equipment', 0x007bff);
      const isSel = (f.id === (window.FittingsUI && FittingsUI.getSelectedId ? FittingsUI.getSelectedId() : null));
      const radius = parseFloat(f.radius) || 0.025;
      const group = new THREE.Group();
      group.name = 'fitting:' + f.id;
      const segs = Array.isArray(f.segments) ? f.segments : [];
      segs.forEach(function (seg) {
        if (!seg.from || !seg.to) return;
        var fy = seg.from[1] != null ? seg.from[1] : layerH;
        var ty = seg.to[1]   != null ? seg.to[1]   : layerH;
        var p0 = new THREE.Vector3(seg.from[0], fy, seg.from[2]);
        var p1 = new THREE.Vector3(seg.to[0],   ty, seg.to[2]);
        if (p0.distanceTo(p1) < 0.05) return;
        var curve = new THREE.LineCurve3(p0, p1);
        var geo = new THREE.TubeGeometry(curve, 2, radius, 6, false);
        var mat = new THREE.MeshStandardMaterial({
          color: isSel ? 0xffeb3b : colorHex,
          roughness: 0.55, metalness: 0.35,
          emissive: isSel ? 0xf9a825 : 0x000000,
          emissiveIntensity: isSel ? 0.4 : 0
        });
        var mesh = new THREE.Mesh(geo, mat);
        mesh.name = 'irr_pipe_seg:' + f.id;
        group.add(mesh);
      });
      if (group.children.length === 0) {
        // fallback small sphere if no segments yet
        var sg = new THREE.SphereGeometry(radius * 2, 6, 6);
        var sm = new THREE.MeshStandardMaterial({ color: colorHex, transparent: true, opacity: 0.5 });
        var s = new THREE.Mesh(sg, sm);
        s.position.set(totalWidth / 2, layerH, length / 2);
        s.name = 'irr_pipe_marker:' + f.id;
        group.add(s);
      }
      ghGroup.add(group);
      if (f.id && group.children[0]) {
        clickTargets.push({ mesh: group.children[0], slot: 'fitting:' + f.id, fittingId: f.id });
      }
      return group;
    }

    // Pipe connection point (tee / elbow) — follows the same color codes as geo/design.
    // mbT (main-branch tee) orange, mT dark orange, bT yellow, mE black, bE gray.
    function _buildIrrigationConnectionMesh(f) {
      const px = parseFloat(f.position.x) || 0;
      const pz = parseFloat(f.position.z) || 0;
      const py = parseFloat(f.position.y) || 2.0;
      const sub = f.sub_type || 'mbT';
      const colorMap = {
        mbT: 0xff9800,  // main-branch tee
        mT:  0xe65100,
        bT:  0xfdd835,
        mE:  0x000000,
        bE:  0x888888
      };
      const colorHex = colorMap[sub] || 0xff9800;
      const isSel = (f.id === (window.FittingsUI && FittingsUI.getSelectedId ? FittingsUI.getSelectedId() : null));
      const g = new THREE.SphereGeometry(0.06, 12, 8);
      const m = new THREE.MeshStandardMaterial({
        color: isSel ? 0xffeb3b : colorHex,
        roughness: 0.45, metalness: 0.4
      });
      const mesh = new THREE.Mesh(g, m);
      mesh.position.set(px, py, pz);
      mesh.name = 'fitting:' + f.id;
      ghGroup.add(mesh);
      if (f.id) clickTargets.push({ mesh: mesh, slot: 'fitting:' + f.id, fittingId: f.id });
      return mesh;
    }

    function _buildIrrigationDeviceMesh(f) {
      const px = parseFloat(f.position.x) || 0;
      const pz = parseFloat(f.position.z) || 0;
      const py = parseFloat(f.position.y) || 2.0;
      const radiusM = parseFloat(f.radius_m) || 11;
      const orientation = (f.orientation === 'up') ? 'up' : 'down';   // 'up' = upward, 'down' = downward
      const subType = f.sub_type || 'sprinkler';                       // 'sprinkler' | 'drip'
      const isSel = (f.id === (window.FittingsUI && FittingsUI.getSelectedId ? FittingsUI.getSelectedId() : null));
      const themeHex = _themeColor('equipment', 0x007bff);

      // ── Nozzle body ──
      // ConeGeometry: tip at local +Y, base at local -Y.
      // downward (down): base at pipe level (py), tip extends BELOW pipe.
      //   → rotate.z = π (tip → -Y), center at py - coneH/2
      //   → tip world Y = py - coneH, base world Y = py ✓
      // upward (up):   base at pipe level (py), tip extends ABOVE pipe.
      //   → no rotation (tip = +Y), center at py + coneH/2
      //   → tip world Y = py + coneH, base world Y = py ✓
      // drip: small disc, direction irrelevant.
      let bodyMesh;
      const coneH = 0.30;
      if (subType === 'drip') {
        const dg = new THREE.CylinderGeometry(0.05, 0.05, 0.04, 12);
        const dm = new THREE.MeshStandardMaterial({
          color: isSel ? 0xffeb3b : themeHex, roughness: 0.55, metalness: 0.25
        });
        bodyMesh = new THREE.Mesh(dg, dm);
        bodyMesh.position.set(px, py - 0.02, pz);
      } else {
        const cg = new THREE.ConeGeometry(0.08, coneH, 10);
        const cm = new THREE.MeshStandardMaterial({
          color: isSel ? 0xffeb3b : themeHex, roughness: 0.5, metalness: 0.3
        });
        bodyMesh = new THREE.Mesh(cg, cm);
        if (orientation === 'down') {
          bodyMesh.rotation.z = Math.PI;                           // tip toward -Y (down)
          bodyMesh.position.set(px, py - coneH / 2, pz);           // base = py, tip = py - coneH
        } else {
          bodyMesh.position.set(px, py + coneH / 2, pz);           // base = py, tip = py + coneH (up)
        }
      }
      bodyMesh.name = 'fitting:' + f.id;
      ghGroup.add(bodyMesh);
      if (f.id) clickTargets.push({ mesh: bodyMesh, slot: 'fitting:' + f.id, fittingId: f.id });

      // ── Sprinkler coverage circle — collected for InstancedMesh batch ──
      // Rendered in a single draw call after fittings.forEach completes (see flush below).
      // Same batch principle as geo/design's single MapLibre fill layer.
      // The sprinkler coverage radius is drawn on the ground (0.02) regardless of direction (up/down).
      const ringY = (subType === 'sprinkler') ? 0.02 : py + 0.02;
      if (!ghGroup.userData._pendingCoverage) ghGroup.userData._pendingCoverage = [];
      ghGroup.userData._pendingCoverage.push({ px, ringY, pz, radiusM });

      return bodyMesh;
    }

    // ─── Category visibility (envelope / opening / climate / sensor / fixture / irrig) ─
    // Tag via mesh.userData.category → toggle in bulk with setCategoryVisibility.
    var _catVisibility = {
      envelope: true, opening: true, climate: true,
      sensor: true, fixture: true, irrig: true
    };
    function _categoryOf(f) {
      if (!f) return null;
      if (f.source === 'envelope') return 'envelope';
      var k = f.kind;
      if (k === 'window' || k === 'door' || k === 'side_window') return 'opening';
      if (k === 'fan' || k === 'heater' || k === 'curtain')      return 'climate';
      if (k === 'sensor')  return 'sensor';
      if (k === 'fixture') return 'fixture';
      if (k === 'irrigation_layer' || k === 'irrigation_pipe' ||
          k === 'irrigation_device' || k === 'irrigation_connection') return 'irrig';
      return null;
    }
    function setCategoryVisibility(cat, visible) {
      if (!_catVisibility.hasOwnProperty(cat)) return;
      _catVisibility[cat] = !!visible;
      ghGroup.traverse(function (o) {
        if (o.userData && o.userData.category === cat) o.visible = !!visible;
      });
      if (typeof requestRender === 'function') requestRender();
    }
    // Helper that attaches a category tag to the mesh/group returned by _addFittingToScene.
    function _tagCategory(meshOrGroup, f) {
      var cat = _categoryOf(f);
      if (!meshOrGroup || !cat) return meshOrGroup;
      meshOrGroup.userData = meshOrGroup.userData || {};
      meshOrGroup.userData.category = cat;
      meshOrGroup.visible = !!_catVisibility[cat];
      return meshOrGroup;
    }

    // Build & insert a single fitting (mesh + edges + clickTarget) into the
    // existing scene. Used both during initial render (forEach below) and for
    // in-place additions later via addFittingMesh — avoiding a full scene
    // rebuild (which would dispose/recreate the WebGL context, sometimes
    // leaving the canvas blank and exhausting the browser's context budget).
    function _addFittingToScene(f) {
      if (!f) return null;
      // Irrigation layer/pipe/connection/device use dedicated renderers
      if (f.kind === 'irrigation_layer')      return _tagCategory(_buildIrrigationLayerMarker(f), f);
      if (f.kind === 'irrigation_pipe')       return _tagCategory(_buildIrrigationPipeMesh(f), f);
      if (f.kind === 'irrigation_connection') return _tagCategory(_buildIrrigationConnectionMesh(f), f);
      if (f.kind === 'irrigation_device')     return _tagCategory(_buildIrrigationDeviceMesh(f), f);
      // Front reinforcement: rendered directly in buildScene — skipped in the fitting renderer
      if (f.kind === 'front_reinforcement') return null;
      if (!f.size || !f.position) return null;
      const w = Math.max(parseFloat(f.size.w)||0.1, 0.02);
      const h = Math.max(parseFloat(f.size.h)||0.1, 0.02);
      const d = Math.max(parseFloat(f.size.d)||0.1, 0.02);
      const px = parseFloat(f.position.x)||0;
      const py = parseFloat(f.position.y)||(h/2);
      const pz = parseFloat(f.position.z)||0;
      const rotDeg = parseFloat(f.rotation_deg)||0;
      const curSel = (window.FittingsUI && FittingsUI.getSelectedId) ? FittingsUI.getSelectedId() : null;
      const isSel  = (f.id && f.id === curSel);
      const _m   = _FIT_MAT[f.kind] || _FIT_MAT.fixture;
      const baseOpacity = _fitRenderOp(_m);
      const sn = (Array.isArray(f.surface_normal) && f.surface_normal.length === 3) ? f.surface_normal : null;

      // Ceiling curtains (no surface_normal = horizontal) render as folded
      // pile strips when the linked actuator motor is ON.  Each bay's curtain
      // folds from the centre outward — two ~1 m bundles at the bay edges,
      // empty space in the middle — matching the physical rail-draw mechanism.
      const isCeilCurtain = (f.kind === 'curtain' || f.kind === 'shade_curtain') && !sn;
      if (isCeilCurtain) {
        const actKey = (f.kind === 'shade_curtain') ? 'shade_curtain_motor' : 'thermal_curtain_motor';
        const isOpen = !!(actStates[actKey] && actStates[actKey].on);
        if (isOpen) {
          const foldW   = Math.min(1.0, w * 0.22);
          const foldH   = Math.max(h * 4, 0.14);   // stacked pile — taller
          const foldD   = d * 3;
          const offsetX = w / 2 - foldW / 2;
          var firstFoldMesh = null;
          ['L', 'R'].forEach(function (side) {
            const dx  = (side === 'L') ? -offsetX : offsetX;
            const fg  = new THREE.BoxGeometry(foldW, foldH, foldD);
            const fm  = new THREE.MeshStandardMaterial({
              color: _m.color, transparent: true,
              opacity: isSel ? Math.min(baseOpacity + 0.20, 0.92) : baseOpacity,
              roughness: _m.roughness, depthWrite: false, side: THREE.DoubleSide,
              emissive: isSel ? 0x1976d2 : 0x000000,
              emissiveIntensity: isSel ? 0.35 : 0,
            });
            const fmesh = new THREE.Mesh(fg, fm);
            fmesh.renderOrder = 1;
            fmesh.userData.baseOpacity = baseOpacity;
            fmesh.position.set(px + dx, py, pz);
            fmesh.name = 'fitting:' + (f.id || '') + ':' + side;
            ghGroup.add(fmesh);
            const fe = new THREE.LineSegments(
              new THREE.EdgesGeometry(fg),
              new THREE.LineBasicMaterial({ color: isSel ? 0x1565c0 : 0x37474f })
            );
            fe.position.copy(fmesh.position);
            fe.name = 'edges:fitting:' + (f.id || '') + ':' + side;
            ghGroup.add(fe);
            if (!firstFoldMesh) firstFoldMesh = fmesh;
          });
          if (f.id && firstFoldMesh) clickTargets.push({ mesh: firstFoldMesh, slot: 'fitting:' + f.id, fittingId: f.id });
          return firstFoldMesh;
        }
      }

      // ── Reinforcement: hollow shell (air gap), no inner face / no bottom ──
      // The reinforcement is an insulating air layer attached to the outside
      // of the outer wall. Only 4 faces are rendered:
      //   • outer face (local +Z, facing outdoors)
      //   • top face   (local +Y)
      //   • two end faces (local ±X, the short sides of the panel)
      // The inner face (local −Z, in contact with the outer cover) and the
      // bottom face (local −Y, on the ground) are intentionally omitted so
      // the structure reads as an open shell rather than a solid block.
      if (f.kind === 'reinforcement') {
        const sMat = new THREE.MeshStandardMaterial({
          color: _m.color, transparent: true,
          opacity: isSel ? Math.min(baseOpacity + 0.20, 0.92) : baseOpacity,
          roughness: _m.roughness,
          emissive: isSel ? 0x1976d2 : 0x000000,
          emissiveIntensity: isSel ? 0.35 : 0,
          depthWrite: false,
          side: THREE.DoubleSide,
        });
        const eMat = new THREE.LineBasicMaterial({
          color: isSel ? 0x1565c0 : 0x37474f, linewidth: isSel ? 2 : 1,
        });
        const shell = new THREE.Group();
        shell.name = 'fitting:' + (f.id || '');

        function _addPlane(planeW, planeH, lx, ly, lz, rotX, rotY) {
          const g = new THREE.PlaneGeometry(planeW, planeH);
          const m = new THREE.Mesh(g, sMat);
          m.position.set(lx, ly, lz);
          if (rotX) m.rotation.x = rotX;
          if (rotY) m.rotation.y = rotY;
          shell.add(m);
          const e = new THREE.LineSegments(new THREE.EdgesGeometry(g), eMat);
          e.position.copy(m.position);
          e.rotation.copy(m.rotation);
          shell.add(e);
          return m;
        }

        // Outer face — main visible panel (local +Z)
        const outerFace = _addPlane(w, h, 0, 0,  d / 2, 0, 0);
        // Top face (local +Y), flat horizontal
        _addPlane(w, d, 0,  h / 2, 0, -Math.PI / 2, 0);
        // End faces (local ±X) — short side caps
        _addPlane(d, h, -w / 2, 0, 0, 0, -Math.PI / 2);
        _addPlane(d, h,  w / 2, 0, 0, 0,  Math.PI / 2);

        shell.position.set(px, py, pz);
        if (!_orientFromNormal(shell, sn, rotDeg)) {
          shell.rotation.y = rotDeg * Math.PI / 180;
        }
        shell.renderOrder = 1;
        shell.userData.surface_normal = sn;
        shell.userData.baseOpacity = baseOpacity;
        shell.userData.fittingSpec = JSON.parse(JSON.stringify(f));
        ghGroup.add(shell);

        if (f.id) clickTargets.push({
          mesh: outerFace, slot: 'fitting:' + f.id, fittingId: f.id,
        });
        return shell;
      }

      const geo = new THREE.BoxGeometry(w, h, d);
      const mat = new THREE.MeshStandardMaterial({
        color: _m.color, transparent: true,
        opacity: isSel ? Math.min(baseOpacity + 0.20, 0.92) : baseOpacity,
        roughness: _m.roughness,
        emissive: isSel ? 0x1976d2 : 0x000000,
        emissiveIntensity: isSel ? 0.35 : 0,
        depthWrite: false,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.userData.baseOpacity = baseOpacity;
      mesh.renderOrder = 1;  // render after arch cover (renderOrder 0)
      mesh.position.set(px, py, pz);
      if (!_orientFromNormal(mesh, sn, rotDeg)) mesh.rotation.y = rotDeg * Math.PI / 180;
      mesh.name = 'fitting:' + (f.id || '');
      mesh.userData.surface_normal = sn;
      mesh.userData.fittingSpec = JSON.parse(JSON.stringify(f));
      ghGroup.add(mesh);

      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geo),
        new THREE.LineBasicMaterial({ color: isSel ? 0x1565c0 : 0x37474f, linewidth: isSel ? 2 : 1 })
      );
      edges.position.copy(mesh.position);
      edges.quaternion.copy(mesh.quaternion);
      edges.name = 'edges:fitting:' + (f.id || '');
      ghGroup.add(edges);

      if (f.id) clickTargets.push({ mesh: mesh, slot: 'fitting:' + f.id, fittingId: f.id });
      _tagCategory(mesh, f);
      _tagCategory(edges, f);
      return mesh;
    }

    fittings.forEach(_addFittingToScene);

    // ── Sprinkler coverage InstancedMesh batch flush ───────────────────────────────────
    // Like geo/design's single MapLibre fill layer, render all sprinkler radius circles
    // in one WebGL draw call (InstancedMesh: shared geometry/material).
    (function _flushIrrigCoverage() {
      const covers = ghGroup.userData._pendingCoverage;
      if (!covers || !covers.length) return;
      delete ghGroup.userData._pendingCoverage;
      const themeHex = _themeColor('equipment', 0x007bff);
      const cGeo = new THREE.CircleGeometry(1, 24); // radius=1 normalized, scaled per instance
      cGeo.rotateX(-Math.PI / 2);                   // XZ horizontal plane (ground sprinkler footprint)
      const cMat = new THREE.MeshBasicMaterial({
        color: themeHex, transparent: true, opacity: 0.15,
        side: THREE.DoubleSide, depthTest: false, depthWrite: false
      });
      const iMesh = new THREE.InstancedMesh(cGeo, cMat, covers.length);
      iMesh.name = 'irrig_coverage_batch';
      iMesh.renderOrder = 998;
      iMesh.frustumCulled = false;
      iMesh.userData.category = 'irrig';
      iMesh.visible = !!_catVisibility['irrig'];
      const dummy = new THREE.Object3D();
      covers.forEach(function (c, i) {
        dummy.position.set(c.px, c.ringY, c.pz);
        dummy.scale.setScalar(c.radiusM);
        dummy.updateMatrix();
        iMesh.setMatrixAt(i, dummy.matrix);
      });
      iMesh.instanceMatrix.needsUpdate = true;
      ghGroup.add(iMesh);
    })();

    // Wind & compass
    if (outdoor.wind_ms!=null || outdoor.wind_deg!=null) scene.add(buildWindArrow(outdoor.wind_deg||0, length));
    scene.add(buildCompass(orientDeg, length));

    // Ground & grid
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(200,200), new THREE.MeshStandardMaterial({color:0xffffff,roughness:0.90}));
    ground.rotation.x = -Math.PI/2; ground.position.y = -0.08; scene.add(ground);
    const grid = new THREE.GridHelper(100,50,0xbbbbbb,0xdddddd); grid.position.y = -0.04; scene.add(grid);

    // Floor compass — shows N (north) / E (east) directions regardless of camera angle
    scene.add(buildFloorCompass(totalWidth, length));

    // View cube
    const _halfFovV = camera.fov/2*Math.PI/180, _asp = camera.aspect||(W/H);
    const _halfFovH = Math.atan(Math.tan(_halfFovV)*_asp);
    const _ctr = new THREE.Vector3(cx,ridgeH/2,cz);
    const _hw=totalWidth/2, _hh=ridgeH/2, _hl=length/2, _PAD=1.18;
    function _fitD(eH,eV) { return Math.max(eH/Math.tan(_halfFovH),eV/Math.tan(_halfFovV))*_PAD; }
    const _br=Math.sqrt(_hw*_hw+_hh*_hh+_hl*_hl);
    const _dF=_fitD(_hw,_hh),_dS=_fitD(_hl,_hh),_dT=_fitD(_hw,_hl),_dC=_br/Math.sin(_halfFovV)*_PAD;
    const _vcp = {
      'back-left':_ctr.clone().addScaledVector(new THREE.Vector3(-1,1,1).normalize(),_dC),
      // Tiny +Z offset (~0.06°) avoids gimbal lock: fixes azimuth (theta) to 0 so top view is always axis-aligned.
      'top':_ctr.clone().add(new THREE.Vector3(0, _dT, _dT * 0.001)),
      'back-right':_ctr.clone().addScaledVector(new THREE.Vector3(1,1,1).normalize(),_dC),
      'left':_ctr.clone().addScaledVector(new THREE.Vector3(-1,0,0),_dS),
      'iso':_ctr.clone().addScaledVector(new THREE.Vector3(0.55,0.85,0.65).normalize(),_dC),
      'right':_ctr.clone().addScaledVector(new THREE.Vector3(1,0,0),_dS),
      'front-left':_ctr.clone().addScaledVector(new THREE.Vector3(-1,1,-1).normalize(),_dC),
      'front':_ctr.clone().addScaledVector(new THREE.Vector3(0,0,-1),_dF),
      'front-right':_ctr.clone().addScaledVector(new THREE.Vector3(1,1,-1).normalize(),_dC),
    };
    const _t = (window._ ? window._ : function (s) { return s; });
    const _vcL={'back-left':_t('Rear-L'),'top':_t('Top'),'back-right':_t('Rear-R'),'left':_t('W'),'iso':'●','right':_t('E'),'front-left':_t('SW'),'front':_t('S'),'front-right':_t('SE')};
    const _vcT={'back-left':_t('Northwest isometric (N-W)'),'top':_t('Top (plan)'),'back-right':_t('Northeast isometric (N-E)'),'left':_t('West side (West)'),'iso':_t('Default isometric (N-E direction)'),'right':_t('East side (East)'),'front-left':_t('Southwest isometric (S-W) — note: east is on the left'),'front':_t('South front (South) — note: east is on the left'),'front-right':_t('Southeast isometric (S-E) — note: east is on the left')};

    const vcEl = document.createElement('div');
    vcEl.style.cssText='position:absolute;top:18px;right:8px;z-index:15;display:grid;grid-template-columns:repeat(3,28px);grid-auto-rows:28px;gap:2px';
    ['back-left','top','back-right','left','iso','right','front-left','front','front-right'].forEach(key => {
      const btn = document.createElement('button');
      btn.textContent = _vcL[key]; btn.title = _vcT[key];
      const isCtr = key==='iso';
      const _bg0=isCtr?'rgba(2,154,207,0.14)':'rgba(255,255,255,0.88)', _c0=isCtr?'#029ACF':'#444', _b0=isCtr?'#029ACF':'rgba(0,0,0,0.14)';
      btn.style.cssText=`width:28px;height:28px;padding:0;cursor:pointer;line-height:1;font-size:${isCtr?'var(--aot-fs-label)':'var(--aot-fs-caption)'};border-radius:4px;border:1px solid ${_b0};background:${_bg0};backdrop-filter:blur(4px);color:${_c0}`;
      btn.addEventListener('mouseenter',()=>{btn.style.background='rgba(2,154,207,0.22)';btn.style.borderColor='#029ACF';btn.style.color='#13261B';});
      btn.addEventListener('mouseleave',()=>{btn.style.background=_bg0;btn.style.borderColor=_b0;btn.style.color=_c0;});
      btn.addEventListener('click',e=>{
        e.stopPropagation(); const base=_vcp[key]; if(!base) return;
        const dir=base.clone().sub(_ctr), dist=dir.length();
        const ff=Math.tan(22.5*Math.PI/180)/Math.tan(camera.fov/2*Math.PI/180);
        controls.teleport(_ctr.clone().addScaledVector(dir.normalize(),dist*ff));
      });
      vcEl.appendChild(btn);
    });

    let _isoProj = false;
    const projBtn = document.createElement('button');
    projBtn.style.cssText='grid-column:1/4;margin-top:3px;height:20px;padding:0;font-size:var(--aot-fs-caption);border-radius:4px;border:1px solid rgba(0,0,0,0.14);background:rgba(255,255,255,0.88);backdrop-filter:blur(4px);color:#444;cursor:pointer;width:86px';
    function _syncProjBtn() {
      projBtn.textContent=_isoProj?(window._ ? window._('▦ Iso → Persp') : '▦ Iso → Persp'):(window._ ? window._('▧ Persp → Iso') : '▧ Persp → Iso');
      projBtn.style.background=_isoProj?'rgba(2,154,207,0.14)':'rgba(255,255,255,0.88)';
      projBtn.style.color=_isoProj?'#029ACF':'#444';
    }
    _syncProjBtn();
    projBtn.addEventListener('click',e=>{
      e.stopPropagation(); _isoProj=!_isoProj;
      const oF=camera.fov, nF=_isoProj?5:45;
      controls.scaleDist(Math.tan(oF/2*Math.PI/180)/Math.tan(nF/2*Math.PI/180));
      camera.fov=nF; camera.updateProjectionMatrix();
      scene.fog=_isoProj?null:new THREE.Fog(0xf0f4f8,60,120); _syncProjBtn();
    });
    vcEl.appendChild(projBtn);
    if (canvas.parentElement) canvas.parentElement.appendChild(vcEl);

    // Resize observer
    const resizeObs = new ResizeObserver(() => {
      const cw=canvas.parentElement?canvas.parentElement.clientWidth:canvas.clientWidth;
      const ch=canvas.parentElement?canvas.parentElement.clientHeight:canvas.clientHeight;
      if (cw>0&&ch>0) { renderer.setSize(cw,ch,false); camera.aspect=cw/ch; camera.updateProjectionMatrix(); }
    });
    if (canvas.parentElement) resizeObs.observe(canvas.parentElement);

    if (window.MeshBVHLib) {
      clickTargets.forEach(t => { if(t.mesh&&t.mesh.geometry) { try{t.mesh.geometry.computeBoundsTree();}catch(e){} } });
    }

    const raycaster = new THREE.Raycaster(), mouse = new THREE.Vector2();
    let tooltip = null;

    // ── Tool mode ─────────────────────────────────────────────────────────
    //   _toolMode: null | wall-pick ('window'|'door'|'side_window')
    //                   | device-drag ('heater'|'fan'|'sensor'|'fixture')
    // On click while a tool is active → raycast appropriate surface →
    // dispatch 'aot-facility-add-fitting' with computed pos/normal/face.
    let _toolMode = null;
    const TOOL_DEFAULTS = {
      window:      { w: 1.2, h: 1.0, d: 0.05 },
      door:        { w: 1.0, h: 2.0, d: 0.05 },
      side_window: { w: 3.0, h: 0.8, d: 0.05 },
      heater:      { w: 0.6, h: 0.6, d: 0.4  },
      fan:         { w: 0.8, h: 0.8, d: 0.3  },
      sensor:      { w: 0.15,h: 0.15,d: 0.1  },
      fixture:     { w: 1.0, h: 1.0, d: 1.0  }
    };
    const WALL_PICK_TOOLS   = ['window', 'door', 'side_window'];
    const DEVICE_DRAG_TOOLS = ['heater', 'fan', 'sensor', 'fixture'];
    const IRR_FLOOR_TOOLS   = ['irr_vpipe'];                         // floor click — riser origin
    const IRR_PLANE_TOOLS   = ['irr_main_pipe', 'irr_branch_pipe'];  // layer plane click — main/branch
    const IRR_PICK_TOOLS    = ['irr_vconnect'];                      // pipe mesh click — level connection
    function _isWallPick()   { return WALL_PICK_TOOLS.indexOf(_toolMode) >= 0; }
    function _isDeviceDrag() { return DEVICE_DRAG_TOOLS.indexOf(_toolMode) >= 0; }
    function _isIrrFloor()   { return IRR_FLOOR_TOOLS.indexOf(_toolMode) >= 0; }
    function _isIrrPlane()   { return IRR_PLANE_TOOLS.indexOf(_toolMode) >= 0; }
    function _isIrrPick()    { return IRR_PICK_TOOLS.indexOf(_toolMode) >= 0; }

    // ── Orthogonal snap + rubber-band preview state ──────────────────────────
    let _orthoSnap = true;     // orthogonal snap toggle (default ON)
    let _shiftHeld = false;    // Shift temporary release (XOR)
    let _pipeAnchor = null;    // previous point while drawing (THREE.Vector3 | null)
    function _orthoActive() { return _orthoSnap !== _shiftHeld; }
    // Align to X or Z axis relative to the previous point (anchor) — fix the smaller-change axis to the anchor value.
    function _snapOrtho(v) {
      if (!_orthoActive() || !_pipeAnchor || !v) return v;
      const dx = Math.abs(v.x - _pipeAnchor.x);
      const dz = Math.abs(v.z - _pipeAnchor.z);
      if (dx >= dz) v.z = _pipeAnchor.z; else v.x = _pipeAnchor.x;
      return v;
    }
    window.addEventListener('keydown', function (e) {
      if (e.key === 'Shift' && !_shiftHeld) { _shiftHeld = true; if (_toolMode) requestRender(); }
    });
    window.addEventListener('keyup', function (e) {
      if (e.key === 'Shift' && _shiftHeld) { _shiftHeld = false; if (_toolMode) requestRender(); }
    });

    // Rubber-band preview (anchor → current snapped cursor)
    const _pipePreviewMat = new THREE.LineDashedMaterial({
      color: 0x1976d2, dashSize: 0.25, gapSize: 0.15,
      depthTest: false, transparent: true, opacity: 0.9
    });
    const _pipePreviewGeo = new THREE.BufferGeometry().setFromPoints(
      [new THREE.Vector3(), new THREE.Vector3()]
    );
    const _pipePreview = new THREE.Line(_pipePreviewGeo, _pipePreviewMat);
    _pipePreview.name = 'irr_pipe_preview';
    _pipePreview.renderOrder = 998;
    _pipePreview.visible = false;
    _pipePreview.frustumCulled = false;
    scene.add(_pipePreview);
    function _updatePipePreview(toVec) {
      if (!_pipeAnchor || !toVec) { _pipePreview.visible = false; return; }
      const pos = _pipePreview.geometry.attributes.position;
      pos.setXYZ(0, _pipeAnchor.x, _pipeAnchor.y, _pipeAnchor.z);
      pos.setXYZ(1, toVec.x, toVec.y, toVec.z);
      pos.needsUpdate = true;
      _pipePreview.geometry.computeBoundingSphere();
      _pipePreview.computeLineDistances();
      _pipePreview.visible = true;
    }

    // Intersection of the horizontal plane (y = h) with the mouse ray — used later for main/branch pipe and device clicks.
    // It's a virtual plane (not the floor raycast _floorRef), so the visual snap aligns to the layer height.
    function _hitLayerPlane(event, h) {
      const rect = canvas.getBoundingClientRect();
      mouse.x = ((event.clientX - rect.left) / rect.width)  * 2 - 1;
      mouse.y = -((event.clientY - rect.top)  / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -h);
      const target = new THREE.Vector3();
      const hit = raycaster.ray.intersectPlane(plane, target);
      return hit ? target : null;
    }

    // Hover highlight overlay
    const _hlGeo = new THREE.PlaneGeometry(1, 1);
    const _hlMat = new THREE.MeshBasicMaterial({
      color: 0x1976d2, transparent: true, opacity: 0.45, side: THREE.DoubleSide, depthTest: false
    });
    const _hlMesh = new THREE.Mesh(_hlGeo, _hlMat);
    _hlMesh.renderOrder = 999;
    _hlMesh.visible = false;
    scene.add(_hlMesh);

    function _faceFromNormal(n) {
      // Normals are the OUTWARD direction of each face. We label faces by where
      // they sit on the model, not where they "face":
      //   z = length face has outward normal +Z → 'north' (position.z = length)
      //   z = 0      face has outward normal -Z → 'south' (position.z = 0)
      //   x = totalW face has outward normal +X → 'east'  (position.x = totalW)
      //   x = 0      face has outward normal -X → 'west'  (position.x = 0)
      // Bug history: south/north were swapped, so clicks landed on the opposite
      // wall.
      if (n.y > 0.5) return 'roof';
      if (Math.abs(n.z) > Math.abs(n.x)) return n.z > 0 ? 'north' : 'south';
      return n.x > 0 ? 'east' : 'west';
    }
    const _flbl = (window._ ? window._ : function (s) { return s; });
    const _FACE_LABELS = { roof:_flbl('Roof'), south:_flbl('S'), north:_flbl('N'), east:_flbl('E'), west:_flbl('W') };

    // Outer cover mesh names are 'outer_cover_' + unit index (a suffix was added when
    // multi-unit support replaced the old single 'outer_cover'). Gather all outer meshes as raycast targets.
    function _resolveOuterMeshes() {
      const arr = [];
      ghGroup.traverse(function (o) {
        if (!o.isMesh || !o.name) return;
        if (o.name === 'outer_cover' || o.name.indexOf('outer_cover_') === 0) arr.push(o);
        if (o.name.indexOf('front_reinf_') === 0) arr.push(o);
      });
      return arr;
    }
    let _outerMeshes = _resolveOuterMeshes();
    // Keep a single reference too (used in alignment/highlight calculations)
    let _outerMesh = _outerMeshes[0] || null;

    // Floating tool status chip (shows active tool + face label on hover)
    const _toolChip = document.createElement('div');
    _toolChip.style.cssText =
      'position:absolute;top:8px;left:50%;transform:translateX(-50%);z-index:25;' +
      'background:#029ACF;color:#fff;padding:0.3rem 0.75rem;border-radius:14px;' +
      'font-size:var(--aot-fs-label);font-weight:var(--aot-fw-semibold);pointer-events:none;display:none;' +
      'box-shadow:0 2px 6px rgba(0,0,0,0.2);';
    if (canvas.parentElement) canvas.parentElement.appendChild(_toolChip);

    function _updateChip(faceLabel) {
      if (!_toolMode) { _toolChip.style.display = 'none'; return; }
      var _tc = (window._ ? window._ : function (s) { return s; });
      const meta = {
        window: _tc('Window'), door: _tc('Door'), side_window: _tc('Side Vent'),
        irr_main_pipe: _tc('Main Pipe'), irr_branch_pipe: _tc('Branch Pipe'),
        irr_vpipe: _tc('Vertical Pipe'), irr_vconnect: _tc('Level Connection')
      }[_toolMode] || _toolMode;
      _toolChip.textContent = faceLabel ? (meta + ' → ' + faceLabel + ' ' + _tc('face')) : (meta + ' (' + _tc('click a face') + ')');
      _toolChip.style.display = '';
    }

    function setTool(toolKind) {
      _toolMode = toolKind || null;
      // On tool switch, reset any in-progress drawing anchor/preview
      _pipeAnchor = null;
      _pipePreview.visible = false;
      if (_toolMode) {
        canvas.style.cursor = 'crosshair';
        _updateChip(null);
      } else {
        canvas.style.cursor = '';
        _hlMesh.visible = false;
        _toolChip.style.display = 'none';
      }
    }

    function _hitOuter(event) {
      if (!_outerMeshes.length) _outerMeshes = _resolveOuterMeshes();
      if (!_outerMeshes.length) return null;
      _outerMesh = _outerMeshes[0];
      const rect = canvas.getBoundingClientRect();
      mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(_outerMeshes, false);
      return hits.length ? hits[0] : null;
    }

    // ── Transform Gizmo (3-axis arrows for sensor/device repositioning) ────────
    let _gizmoGroup  = null;
    let _gizmoMeshes = [];
    let _gizmoFitId  = null;
    let _gizmoPos    = new THREE.Vector3();
    let _gizmoDragAxis  = null;       // 'x'|'y'|'z' while dragging
    let _gizmoDragPlane = new THREE.Plane();
    let _gizmoDragStartWorld = new THREE.Vector3();
    let _gizmoDragFitStart   = new THREE.Vector3();
    const _gizmoRay = new THREE.Raycaster();

    function _buildGizmo() {
      const g = new THREE.Group(); g.name = 'transform_gizmo';
      // Arrow dimensions — 4× scale so they're visible from the default camera distance (~40m)
      const S = 4;
      const SHAFT_R = 0.014 * S, SHAFT_L = 0.32 * S;
      const HEAD_R  = 0.038 * S, HEAD_L  = 0.11  * S;
      const OFF     = 0.16  * S;
      // Coordinate system: X=width, Y=depth (Three.js Z), Z=height (Three.js Y) — Z-up convention
      const AXES = [
        { axis: 'x', color: 0xff3333, rot: (m) => { m.rotation.z = -Math.PI/2; }, off: [OFF, 0,   0  ] },
        { axis: 'y', color: 0x33cc33, rot: (m) => { m.rotation.x =  Math.PI/2; }, off: [0,   0,   OFF] },
        { axis: 'z', color: 0x3399ff, rot: () => {},                               off: [0,   OFF, 0  ] },
      ];
      AXES.forEach(function (a) {
        const mat = new THREE.MeshBasicMaterial({ color: a.color, depthTest: false, transparent: true, opacity: 0.92 });
        const shaft = new THREE.Mesh(new THREE.CylinderGeometry(SHAFT_R, SHAFT_R, SHAFT_L, 8), mat);
        const head  = new THREE.Mesh(new THREE.ConeGeometry(HEAD_R, HEAD_L, 8), mat);
        a.rot(shaft); a.rot(head);
        const off = a.off;
        shaft.position.set(off[0], off[1], off[2]);
        head.position.set(off[0]*2.2, off[1]*2.2, off[2]*2.2);
        shaft.userData.gizmoAxis = a.axis;
        head.userData.gizmoAxis  = a.axis;
        shaft.renderOrder = 999;
        head.renderOrder  = 999;
        g.add(shaft, head);
        _gizmoMeshes.push(shaft, head);
      });
      g.visible = false;
      g.renderOrder = 999;
      ghGroup.add(g);
      return g;
    }

    function _gizmoAxisVec(axis) {
      if (axis === 'x') return new THREE.Vector3(1,0,0);
      if (axis === 'y') return new THREE.Vector3(0,0,1); // user Y = depth  = Three.js Z
      return new THREE.Vector3(0,1,0);                   // user Z = height = Three.js Y
    }

    function _gizmoNdcFromEvent(event) {
      const rect = canvas.getBoundingClientRect();
      return { x: ((event.clientX-rect.left)/rect.width)*2-1,
               y: -((event.clientY-rect.top)/rect.height)*2+1 };
    }

    function showGizmo(fittingId, posObj) {
      if (!_gizmoGroup) _gizmoGroup = _buildGizmo();
      _gizmoFitId = fittingId;
      _gizmoPos.set(posObj.x||0, posObj.y||0, posObj.z||0);
      _gizmoGroup.position.copy(_gizmoPos);
      _gizmoGroup.visible = true;
      requestRender();
    }

    function hideGizmo() {
      if (_gizmoGroup) _gizmoGroup.visible = false;
      _gizmoFitId = null; _gizmoDragAxis = null;
      requestRender();
    }

    canvas.addEventListener('mousedown', function (event) {
      if (event.button !== 0) return;
      if (!_gizmoGroup || !_gizmoGroup.visible) return;
      const ndc = _gizmoNdcFromEvent(event);
      _gizmoRay.setFromCamera(ndc, camera);
      const hits = _gizmoRay.intersectObjects(_gizmoMeshes, false);
      if (!hits.length) return;
      const axis = hits[0].object.userData.gizmoAxis;
      _gizmoDragAxis = axis;
      _gizmoDragFitStart.copy(_gizmoPos);
      // Build drag plane: contains axis, faces camera.
      const axisVec = _gizmoAxisVec(axis);
      const camDir = camera.position.clone().sub(_gizmoPos).normalize();
      const planeN = new THREE.Vector3().crossVectors(axisVec, camDir).cross(axisVec).normalize();
      _gizmoDragPlane.setFromNormalAndCoplanarPoint(planeN, _gizmoPos);
      _gizmoRay.ray.intersectPlane(_gizmoDragPlane, _gizmoDragStartWorld);
      controls.enabled = false;
      event.stopPropagation();
    });

    canvas.addEventListener('mousemove', function (event) {
      if (!_gizmoDragAxis) return;
      const ndc = _gizmoNdcFromEvent(event);
      _gizmoRay.setFromCamera(ndc, camera);
      const cur = new THREE.Vector3();
      if (!_gizmoRay.ray.intersectPlane(_gizmoDragPlane, cur)) return;
      const delta = cur.sub(_gizmoDragStartWorld);
      const axisVec = _gizmoAxisVec(_gizmoDragAxis);
      const move = axisVec.clone().multiplyScalar(delta.dot(axisVec));
      const newPos = _gizmoDragFitStart.clone().add(move);
      _gizmoPos.copy(newPos);
      _gizmoGroup.position.copy(newPos);
      document.dispatchEvent(new CustomEvent('aot-gizmo-moved', {
        detail: { id: _gizmoFitId, position: { x: +newPos.x.toFixed(3), y: +newPos.y.toFixed(3), z: +newPos.z.toFixed(3) } }
      }));
      requestRender();
    });

    document.addEventListener('mouseup', function (event) {
      if (!_gizmoDragAxis) return;
      _gizmoDragAxis = null;
      controls.enabled = true;
    });

    // For device drag-place tools: raycast outer cover + floor, pick first hit.
    let _floorRef = null;
    function _resolveFloor() {
      let f = null;
      ghGroup.traverse(function (o) { if (o.isMesh && o.name === 'facility_floor') f = o; });
      return f;
    }
    function _hitAnySurface(event, skipRoof) {
      if (!_outerMeshes.length) _outerMeshes = _resolveOuterMeshes();
      if (!_floorRef)  _floorRef  = _resolveFloor();
      const targets = _outerMeshes.concat([_floorRef]).filter(Boolean);
      if (targets.length === 0) return null;
      const rect = canvas.getBoundingClientRect();
      mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(targets, false);
      if (!hits.length) return null;
      if (!skipRoof) return hits[0];
      // skipRoof: return first non-roof hit (prefers floor when looking from above)
      for (let i = 0; i < hits.length; i++) {
        const h = hits[i];
        if (h.object.name === 'facility_floor') return h;
        const n = h.face.normal.clone().transformDirection(h.object.matrixWorld).normalize();
        if (_faceFromNormal(n) !== 'roof') return h;
      }
      return null;
    }

    function onCanvasMouseMove(event) {
      if (!_toolMode) return;

      // ── Main/branch pipe: ortho-snapped rubber-band preview on the layer plane ──────────
      if (_isIrrPlane()) {
        let layerH = 2.0;
        if (window.FittingsUI && FittingsUI.getActiveLayerId && FittingsUI.readAll) {
          const id = FittingsUI.getActiveLayerId();
          const layer = FittingsUI.readAll().find(x => x.id === id);
          if (layer) layerH = parseFloat(layer.height_m) || 2.0;
        }
        const ph = _hitLayerPlane(event, layerH);
        if (ph) {
          _snapOrtho(ph);
          _updatePipePreview(ph);
        } else {
          _pipePreview.visible = false;
        }
        _hlMesh.visible = false;
        _updateChip(_pipeAnchor ? (_orthoActive() ? (window._ ? window._('Ortho ON') : 'Ortho ON') : (window._ ? window._('Free') : 'Free')) : (window._ ? window._('Start point') : 'Start point'));
        return;
      }
      // ── Level connection: hover over pipe mesh (no preview) ──────────────────────────
      if (_isIrrPick()) {
        _pipePreview.visible = false;
        _hlMesh.visible = false;
        _updateChip(window._ ? window._('Click pipe') : 'Click pipe');
        return;
      }

      const hit = (_isDeviceDrag() || _isIrrFloor()) ? _hitAnySurface(event, _toolMode === 'sensor') : _hitOuter(event);
      if (!hit) { _hlMesh.visible = false; _updateChip(null); return; }
      const hitObj = hit.object || _outerMesh;
      const n = hit.face.normal.clone().transformDirection(hitObj.matrixWorld).normalize();
      const isFloor = hitObj.name === 'facility_floor';
      const face = isFloor ? 'floor' : _faceFromNormal(n);
      const def = TOOL_DEFAULTS[_toolMode] || TOOL_DEFAULTS.window;

      // Preview at the SAME location that placement would use:
      //   device on any surface → exact click point
      //   wall window/door → wall geometric center (snap)
      //   roof → hit X/Y (arch slope), Z snapped to center (length/2)
      //   front_reinf face → snap to that extension's face/center, not main-facility wall
      const _fr = hitObj.userData && hitObj.userData.isFrontReinf ? hitObj.userData : null;
      let cp;
      if (_isDeviceDrag() || face === 'floor') {
        cp = hit.point.clone();
      } else if (face === 'roof') {
        const zSnap = _fr ? _fr.frZCenter : length / 2;
        cp = new THREE.Vector3(hit.point.x, hit.point.y, zSnap);
      } else {
        let cy;
        if (_toolMode === 'door') cy = def.h / 2;
        else                      cy = Math.max(eaveH / 2, def.h / 2);
        if (_fr) {
          switch (face) {
            case 'south': cp = new THREE.Vector3(_fr.frXCenter, cy, _fr.frZOuter);  break;
            case 'north': cp = new THREE.Vector3(_fr.frXCenter, cy, _fr.frZOuter);  break;
            case 'east':  cp = new THREE.Vector3(totalWidth,    cy, _fr.frZCenter); break;
            case 'west':  cp = new THREE.Vector3(0,             cy, _fr.frZCenter); break;
            default:      cp = hit.point.clone();
          }
        } else {
          switch (face) {
            case 'south': cp = new THREE.Vector3(totalWidth / 2, cy, 0);          break;
            case 'north': cp = new THREE.Vector3(totalWidth / 2, cy, length);     break;
            case 'east':  cp = new THREE.Vector3(totalWidth,     cy, length / 2); break;
            case 'west':  cp = new THREE.Vector3(0,              cy, length / 2); break;
            default:      cp = hit.point.clone();
          }
        }
      }

      _hlMesh.scale.set(def.w * 1.1, def.h * 1.1, 1);
      _hlMesh.position.copy(cp).addScaledVector(n, 0.02);
      const hq = _quatFromNormal([n.x, n.y, n.z], 0);
      if (hq) _hlMesh.quaternion.copy(hq);
      else    _hlMesh.lookAt(cp.clone().add(n));
      _hlMesh.visible = true;
      _updateChip(_FACE_LABELS[face] || (isFloor ? (window._ ? window._('Floor') : 'Floor') : face));
    }
    canvas.addEventListener('mousemove', onCanvasMouseMove);

    function onCanvasClick(event) {
      if (event.button!==0 || _dragged) return;

      // Tool-active path: raycast appropriate surface(s) → spawn a fitting.
      //   wall-pick (window/door/side_window) → outer cover. Wall fittings snap
      //     to wall geometric center; roof fittings snap X/Y to click, Z to center.
      //   device-drag (heater/fan/sensor/fixture) → outer cover + floor. Always
      //     uses the click point. Floor hits keep the box upright (no normal).
      // For face-pick fittings rotation_deg=0 — basis-from-normal gives the
      // natural orientation; spin would tilt the box.
      if (_toolMode) {
        // ── Vertical pipe tool: floor click → create vertical pipe ─────────────────
        if (_isIrrFloor()) {
          if (!_floorRef) _floorRef = _resolveFloor();
          const targets = [_floorRef].filter(Boolean);
          if (targets.length === 0) return;
          const rect = canvas.getBoundingClientRect();
          mouse.x = ((event.clientX - rect.left) / rect.width)  * 2 - 1;
          mouse.y = -((event.clientY - rect.top)  / rect.height) * 2 + 1;
          raycaster.setFromCamera(mouse, camera);
          const hits = raycaster.intersectObjects(targets, false);
          if (!hits.length) return;
          const pt = hits[0].point;
          document.dispatchEvent(new CustomEvent('aot-facility-add-irr-pipe', {
            detail: { x: pt.x, z: pt.z, is_vertical: true }
          }));
          return;
        }
        // ── Main/branch pipe: click at layer height, multi-point polyline ─────────
        if (_isIrrPlane()) {
          // Get the active layer height (the active layer reported by FittingsUI)
          let layerH = 2.0;
          if (window.FittingsUI && FittingsUI.getActiveLayerId && FittingsUI.readAll) {
            const id = FittingsUI.getActiveLayerId();
            const layer = FittingsUI.readAll().find(x => x.id === id);
            if (layer) layerH = parseFloat(layer.height_m) || 2.0;
          }
          const hit = _hitLayerPlane(event, layerH);
          if (!hit) return;
          _snapOrtho(hit);   // ortho snap — same coordinates as the preview
          const isDouble = (event.detail && event.detail >= 2);
          const sub = (_toolMode === 'irr_main_pipe') ? 'main' : 'branch';
          document.dispatchEvent(new CustomEvent('aot-facility-irr-pipe-click', {
            detail: { x: hit.x, y: hit.y, z: hit.z, sub_type: sub, finish: !!isDouble }
          }));
          return;
        }
        // ── Level connection tool: pipe mesh click → pass pipe id + click point ─────────
        if (_isIrrPick()) {
          const rect = canvas.getBoundingClientRect();
          mouse.x = ((event.clientX - rect.left) / rect.width)  * 2 - 1;
          mouse.y = -((event.clientY - rect.top)  / rect.height) * 2 + 1;
          raycaster.setFromCamera(mouse, camera);
          // Target all pipe segment meshes (irr_pipe_seg:<id>)
          const pipeMeshes = [];
          ghGroup.traverse(function (o) {
            if (o.isMesh && o.name && o.name.indexOf('irr_pipe_seg:') === 0) pipeMeshes.push(o);
          });
          const hits = raycaster.intersectObjects(pipeMeshes, false);
          if (!hits.length) return;
          // Extract pipe id from the segment mesh name (irr_pipe_seg:<id>), walking up to parents
          let fid = null, o = hits[0].object;
          while (o && !fid) {
            if (o.name && o.name.indexOf('irr_pipe_seg:') === 0) fid = o.name.slice('irr_pipe_seg:'.length);
            o = o.parent;
          }
          if (!fid) return;
          const pt = hits[0].point;
          document.dispatchEvent(new CustomEvent('aot-facility-irr-vconnect-click', {
            detail: { pipe_id: fid, x: pt.x, y: pt.y, z: pt.z }
          }));
          return;
        }

        const isDevice = _isDeviceDrag();
        const hit = isDevice ? _hitAnySurface(event, _toolMode === 'sensor') : _hitOuter(event);
        if (!hit) return;
        const hitObj = hit.object || _outerMesh;
        const n = hit.face.normal.clone().transformDirection(hitObj.matrixWorld).normalize();
        const isFloor = hitObj.name === 'facility_floor';
        const face = isFloor ? 'floor' : _faceFromNormal(n);

        // Wall-only fittings: block roof.
        if (!isDevice && face === 'roof' && (_toolMode === 'door' || _toolMode === 'side_window')) return;

        const def = TOOL_DEFAULTS[_toolMode] || TOOL_DEFAULTS.window;
        let centerPos;
        let surfaceNormal = [n.x, n.y, n.z];

        const _frClick = hitObj.userData && hitObj.userData.isFrontReinf ? hitObj.userData : null;
        if (isDevice) {
          // Drag-place at exact hit point. Floor hits: lift box by h/2 and use
          // null surface_normal so the device stays upright.
          centerPos = { x: hit.point.x, y: hit.point.y, z: hit.point.z };
          if (isFloor) {
            centerPos.y = def.h / 2;
            surfaceNormal = null;
          }
        } else if (face === 'roof') {
          const zSnap = _frClick ? _frClick.frZCenter : length / 2;
          centerPos = { x: hit.point.x, y: hit.point.y, z: zSnap };
        } else {
          let cy;
          if (_toolMode === 'door') cy = def.h / 2;
          else                      cy = Math.max(eaveH / 2, def.h / 2);
          if (_frClick) {
            switch (face) {
              case 'south': centerPos = { x: _frClick.frXCenter, y: cy, z: _frClick.frZOuter };  break;
              case 'north': centerPos = { x: _frClick.frXCenter, y: cy, z: _frClick.frZOuter };  break;
              case 'east':  centerPos = { x: totalWidth,         y: cy, z: _frClick.frZCenter }; break;
              case 'west':  centerPos = { x: 0,                  y: cy, z: _frClick.frZCenter }; break;
              default:      centerPos = { x: hit.point.x, y: hit.point.y, z: hit.point.z };
            }
          } else {
            switch (face) {
              case 'south': centerPos = { x: totalWidth / 2, y: cy, z: 0 };               break;
              case 'north': centerPos = { x: totalWidth / 2, y: cy, z: length };          break;
              case 'east':  centerPos = { x: totalWidth,     y: cy, z: length / 2 };      break;
              case 'west':  centerPos = { x: 0,              y: cy, z: length / 2 };      break;
              default:      centerPos = { x: hit.point.x, y: hit.point.y, z: hit.point.z };
            }
          }
        }

        document.dispatchEvent(new CustomEvent('aot-facility-add-fitting', {
          detail: {
            kind: _toolMode,
            position: centerPos,
            rotation_deg: 0,
            surface_normal: surfaceNormal,
            size: def,
            face: _FACE_LABELS[face] || (isFloor ? (window._ ? window._('Floor') : 'Floor') : face),
            face_raw: face,            // for FittingsUI to know geometry context
            is_device: isDevice,       // skip symmetry replication for devices
            facility_dims: {
              totalWidth: totalWidth,
              length: length,
              span: span,
              effectiveSpacing: effectiveSpacing,
              bayCount: bayCount,
              structure: facility.structure || 'single'
            }
          }
        }));
        return;
      }

      const rect = canvas.getBoundingClientRect();
      mouse.x=((event.clientX-rect.left)/rect.width)*2-1;
      mouse.y=-((event.clientY-rect.top)/rect.height)*2+1;
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(clickTargets.map(t=>t.mesh).filter(Boolean), true);
      if (!hits.length) return;
      const hit = hits[0].object;
      const target = clickTargets.find(t=>t.mesh===hit||(t.group&&t.group.children.includes(hit)));
      if (!target) return;
      // Fittings: dispatch selection event to FittingsUI form, skip tooltip
      if (target.fittingId) {
        document.dispatchEvent(new CustomEvent('aot-fitting-clicked', { detail: { id: target.fittingId } }));
        return;
      }
      const state = actStates[target.slot]||{};
      if (tooltip) tooltip.remove();
      tooltip = document.createElement('div');
      tooltip.style.cssText='position:fixed;z-index:var(--aot-z-tooltip);background:#1e2a35;color:#fff;padding:0.5rem 0.75rem;border-radius:8px;font-size:var(--aot-fs-label);pointer-events:none;max-width:220px;box-shadow:0 4px 12px rgba(0,0,0,0.4)';
      var _tt = (window._ ? window._ : function (s) { return s; });
      tooltip.innerHTML='<b>'+_slotLabel(target.slot)+'</b><br>'+(state.name?_tt('Device')+': '+state.name+'<br>':'')+_tt('Status')+': '+(state.on?'<span style="color:#4fc3f7">ON</span>':'<span style="color:#9e9e9e">OFF</span>')+(state.percent!=null?' / '+state.percent+'%':'')+'<br><small style="color:#888">'+target.slot+'</small>';
      tooltip.style.left=(event.clientX+12)+'px'; tooltip.style.top=(event.clientY-8)+'px';
      document.body.appendChild(tooltip);
      setTimeout(()=>{ if(tooltip){tooltip.remove();tooltip=null;} },3500);
    }
    canvas.addEventListener('click', onCanvasClick);

    // Bounding-sphere fit — deferred until the canvas has a real size.
    // At buildScene() time the canvas may still be layout-pending (clientHeight=0),
    // so the initial camera position is a best-effort; we refit on the first frame
    // where the parent reports a valid height, matching exactly what the cube-view
    // iso button would produce.
    const _fitBr = Math.sqrt((totalWidth/2)**2 + (ridgeH/2)**2 + (length/2)**2);
    const _fitDir = new THREE.Vector3(0.55, 0.85, 0.65).normalize();
    let _fitted = false;
    function _tryFit() {
      const par = canvas.parentElement;
      const ch = (par && par.clientHeight) || canvas.clientHeight || 0;
      const cw = (par && par.clientWidth)  || canvas.clientWidth  || 0;
      if (ch <= 0 || cw <= 0) return;
      renderer.setSize(cw, ch, false);
      camera.aspect = cw / ch;
      const hfv = camera.fov / 2 * Math.PI / 180;
      const dist = _fitBr / Math.sin(hfv) * 1.18;
      camera.position.set(cx + _fitDir.x*dist, cy + _fitDir.y*dist, cz + _fitDir.z*dist);
      controls.target.copy(_origTarget);
      camera.updateProjectionMatrix();
      controls.update();
      _fitted = true;
    }
    _tryFit();

    // ─── Render-on-demand (CPU savings) ─────────────────────────────────────────
    // Render a single frame only on change, instead of a constant RAF loop.
    // Keep a short RAF loop for damping only during user interaction (MapControls start→end).
    let animId = null;
    let _interacting = false;
    let _disposed = false;
    let _settleUntil = 0;            // damping settle: keep rendering for 300ms after 'end'

    function _renderOnce() {
      if (_disposed) return;
      if (!_fitted) _tryFit();
      controls.update();
      renderer.render(scene, camera);
    }

    function _loop() {
      if (_disposed) { animId = null; return; }
      const now = performance.now();
      if (!_interacting && now > _settleUntil) {
        animId = null;            // everything settled — end loop
        _renderOnce();
        return;
      }
      animId = requestAnimationFrame(_loop);
      _renderOnce();
    }

    function _scheduleRender() {
      if (_disposed) return;
      if (animId == null) animId = requestAnimationFrame(_loop);
    }

    controls.addEventListener('start',  function () { _interacting = true;  _scheduleRender(); });
    controls.addEventListener('change', function () { _settleUntil = performance.now() + 80; _scheduleRender(); });
    controls.addEventListener('end',    function () { _interacting = false; _settleUntil = performance.now() + 400; _scheduleRender(); });

    // Tab visibility: stop pointless rendering in background tabs, draw one frame on return.
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) {
        if (animId != null) cancelAnimationFrame(animId);
        animId = null;
        _interacting = false;
      } else if (!_disposed) {
        _settleUntil = performance.now() + 100;
        _scheduleRender();
      }
    });

    // Trigger a forced re-render from outside (on fitting add/remove/tool change)
    function requestRender() { _settleUntil = performance.now() + 50; _scheduleRender(); }

    // ── Fast preview mode (Material Diet) ──────────────────────────────────────
    // MeshPhysicalMaterial / MeshStandardMaterial → MeshLambertMaterial (fragment cost -20~30%)
    // Pixel ratio 2.0 → 1.5 (resolution query reduced 56%)
    var _fastMode = false;
    function setFastMode(fast) {
      _fastMode = !!fast;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, _fastMode ? 1.5 : 2.0));
      ghGroup.traverse(function (o) {
        if (!o.isMesh || !o.material) return;
        var m = o.material;
        if (_fastMode) {
          if (m.type === 'MeshPhysicalMaterial' || m.type === 'MeshStandardMaterial') {
            var lm = new THREE.MeshLambertMaterial({
              color: m.color ? m.color.clone() : new THREE.Color(0xffffff),
              emissive: m.emissive ? m.emissive.clone() : new THREE.Color(0x000000),
              transparent: m.transparent,
              opacity: m.opacity,
              side: m.side,
              depthWrite: m.depthWrite,
            });
            lm._origMat = m;
            o.material = lm;
          }
        } else {
          if (o.material._origMat) {
            o.material.dispose();
            o.material = o.material._origMat;
          }
        }
      });
      requestRender();
    }

    // Apply initial render mode
    if (renderMode === 'performance') {
      setFastMode(true);
    } else if (renderMode === 'solid' || renderMode === 'wireframe') {
      _applyRenderMode(ghGroup, renderMode);
    }

    // Initial frame
    _renderOnce();
    // _tryFit keeps adjusting the camera position, so keep a short loop for the first ~1s
    _settleUntil = performance.now() + 1000;
    _scheduleRender();

    function dispose() {
      _disposed = true;
      if (animId != null) cancelAnimationFrame(animId);
      animId = null;
      resizeObs.disconnect(); controls.dispose();
      canvas.removeEventListener('click', onCanvasClick);
      canvas.removeEventListener('mousemove', onCanvasMouseMove);
      if (tooltip) tooltip.remove();
      if (_toolChip && _toolChip.parentElement) _toolChip.parentElement.removeChild(_toolChip);
      if (vcEl.parentElement) vcEl.parentElement.removeChild(vcEl);
      if (window.MeshBVHLib) {
        clickTargets.forEach(t=>{ if(t.mesh&&t.mesh.geometry&&t.mesh.geometry.boundsTree){try{t.mesh.geometry.disposeBoundsTree();}catch(e){}} });
      }
      renderer.dispose();
    }

    // In-place selection highlight update — avoids full scene rebuild on click.
    function updateFittingSelection(selectedId) {
      ghGroup.traverse(function (obj) {
        if (!obj || !obj.name) return;
        if (obj.name.indexOf('fitting:') !== 0) return;
        if (!obj.material) return;
        // Strip fold-variant suffix (":L" / ":R") to get the canonical fitting id
        var rawId = obj.name.slice('fitting:'.length);
        var colonIdx = rawId.indexOf(':');
        var id = colonIdx >= 0 ? rawId.slice(0, colonIdx) : rawId;
        var isSel = (id === selectedId);
        var base = (obj.userData && obj.userData.baseOpacity != null) ? obj.userData.baseOpacity : 0.55;
        obj.material.opacity = isSel ? Math.min(base + 0.20, 0.92) : base;
        if (obj.material.emissive) obj.material.emissive.setHex(isSel ? 0x1976d2 : 0x000000);
        obj.material.emissiveIntensity = isSel ? 0.35 : 0;
        obj.material.needsUpdate = true;
      });
    }

    function _findFittingPair(id) {
      var mesh = null, edges = null;
      var mp = 'fitting:' + id, ep = 'edges:fitting:' + id;
      ghGroup.traverse(function (obj) {
        if (!obj.name) return;
        // exact match first; fall back to first fold variant
        if (obj.name === mp || (!mesh && obj.name.indexOf(mp + ':') === 0)) mesh = obj;
        else if (obj.name === ep || (!edges && obj.name.indexOf(ep + ':') === 0)) edges = obj;
      });
      return { mesh: mesh, edges: edges };
    }

    // In-place position/rotation update for a fitting — no rebuild.
    // If the mesh was created with a surface_normal, we preserve the normal-based
    // orientation and apply rotation_deg as spin around the normal.
    function updateFittingTransform(id, position, rotation_deg) {
      var p = _findFittingPair(id);
      if (!p.mesh) return;
      if (position) {
        p.mesh.position.set(position.x || 0, position.y || 0, position.z || 0);
        if (p.edges) p.edges.position.copy(p.mesh.position);
      }
      if (rotation_deg != null) {
        var sn = p.mesh.userData && p.mesh.userData.surface_normal;
        var deg = rotation_deg || 0;
        var q = (sn && Array.isArray(sn) && sn.length === 3) ? _quatFromNormal(sn, deg) : null;
        if (q) {
          p.mesh.quaternion.copy(q);
          if (p.edges) p.edges.quaternion.copy(q);
        } else {
          p.mesh.rotation.set(0, deg * Math.PI / 180, 0);
          if (p.edges) p.edges.rotation.set(0, deg * Math.PI / 180, 0);
        }
      }
    }

    // In-place geometry replacement (box size change) — no rebuild.
    function updateFittingGeometry(id, size) {
      var p = _findFittingPair(id);
      if (!p.mesh || !size) return;
      var w = Math.max(parseFloat(size.w) || 0.1, 0.02);
      var h = Math.max(parseFloat(size.h) || 0.1, 0.02);
      var d = Math.max(parseFloat(size.d) || 0.1, 0.02);
      // Group-type fittings (reinforcement shell, folded curtain, etc.) have no
      // single geometry — remove and re-add using the stored fittingSpec snapshot.
      if (p.mesh.isGroup) {
        var spec = p.mesh.userData && p.mesh.userData.fittingSpec;
        if (!spec) return;
        spec = JSON.parse(JSON.stringify(spec));
        spec.size = { w: w, h: h, d: d };
        removeFittingMesh(id);
        _addFittingToScene(spec);
        return;
      }
      // Standard BoxGeometry mesh: replace geometry in-place.
      if (p.mesh.geometry) p.mesh.geometry.dispose();
      p.mesh.geometry = new THREE.BoxGeometry(w, h, d);
      if (p.edges) {
        if (p.edges.geometry) p.edges.geometry.dispose();
        p.edges.geometry = new THREE.EdgesGeometry(p.mesh.geometry);
      }
    }

    // In-place add for a single fitting — no scene rebuild.
    function addFittingMesh(f) {
      _addFittingToScene(f);
    }

    // In-place remove — find mesh + edges by name, dispose, drop click target.
    function removeFittingMesh(id) {
      if (!id) return;
      var meshPfx = 'fitting:' + id;
      var edgePfx = 'edges:fitting:' + id;
      var toRemove = [];
      ghGroup.traverse(function (o) {
        if (!o.name) return;
        // match exact name OR fold-variant names (fitting:{id}:L / fitting:{id}:R)
        if (o.name === meshPfx || o.name === edgePfx ||
            o.name.indexOf(meshPfx + ':') === 0 || o.name.indexOf(edgePfx + ':') === 0) {
          toRemove.push(o);
        }
      });
      toRemove.forEach(function (o) {
        if (o.geometry) o.geometry.dispose();
        if (o.material && o.material.dispose) o.material.dispose();
        ghGroup.remove(o);
      });
      for (var i = clickTargets.length - 1; i >= 0; i--) {
        if (clickTargets[i].fittingId === id) clickTargets.splice(i, 1);
      }
    }

    // ─── Externally-callable wrappers — trigger requestRender each time ────────────
    function addFittingMeshAndRender(f)  { var r = addFittingMesh(f);  requestRender(); return r; }
    function removeFittingMeshAndRender(id) { removeFittingMesh(id);   requestRender(); }
    function updateFittingSelectionAndRender(id) { updateFittingSelection(id); requestRender(); }
    function updateFittingTransformAndRender(id, position, rotation_deg) {
      updateFittingTransform(id, position, rotation_deg);
      requestRender();
    }
    function updateFittingGeometryAndRender(id, size) {
      updateFittingGeometry(id, size);
      requestRender();
    }
    function setToolAndRender(t) { setTool(t); requestRender(); }

    // On mousemove, render one frame when the highlight changes (only in tool mode)
    canvas.addEventListener('mousemove', function () { if (_toolMode) requestRender(); });

    return {
      renderer, scene, camera, controls, dispose,
      setTool: setToolAndRender,
      requestRender: requestRender,
      updateFittingSelection: updateFittingSelectionAndRender,
      updateFittingTransform: updateFittingTransformAndRender,
      updateFittingGeometry:  updateFittingGeometryAndRender,
      addFittingMesh:    addFittingMeshAndRender,
      removeFittingMesh: removeFittingMeshAndRender,
      showGizmo: showGizmo,
      hideGizmo: hideGizmo,
      getCategoryVisibility: function () { return Object.assign({}, _catVisibility); },
      setCategoryVisibility: setCategoryVisibility,
      setFastMode: setFastMode,
      getFastMode: function () { return _fastMode; },
      // Orthogonal snap toggle + pipe drawing anchor (for rubber-band preview)
      setOrthoSnap: function (on) { _orthoSnap = !!on; requestRender(); },
      getOrthoSnap: function () { return _orthoSnap; },
      setPipeAnchor: function (pt) {
        if (pt && pt.length >= 3) _pipeAnchor = new THREE.Vector3(pt[0], pt[1], pt[2]);
        else { _pipeAnchor = null; _pipePreview.visible = false; }
        requestRender();
      }
    };
  }

  // ── buildFacilityMesh (map-layer usage, backward-compat) ────────────────────
  function buildFacilityMesh(facility, opts) {
    var group;
    // Envelope-derived fittings drive the cover openings (side windows / end
    // windows punch real holes). Compute once and reuse for the fitting meshes.
    var envFittings = [];
    try { envFittings = _generateEnvelopeFittings(facility); } catch (e) {}
    if (P) {
      group = P.buildFacilityMeshGroup(facility, MAT, envFittings);
    } else {
      const g3d=facility.geometry_3d||{}, envelope=facility.envelope||{};
      const span=parseFloat(g3d.span_width_m)||7, eaveH=parseFloat(g3d.eave_height_m)||2;
      const ridgeH=parseFloat(g3d.ridge_height_m)||4, length=parseFloat(g3d.length_m)||30;
      const roofType=String(g3d.roof_type||'arch').toLowerCase();
      const orientDeg=parseFloat(g3d.orientation_deg)||0;
      const rawBayCount=Math.max(parseInt(facility.bay_count||1,10),1);
      const isConnected=facility.structure==='connected';
      const unitCount=isConnected?1:rawBayCount, meshBayCount=isConnected?rawBayCount:1;
      const isDouble=Array.isArray(envelope.layers)
        ? envelope.layers.some(l=>l.role==='inner')
        : (envelope.layer_count||1)===2;
      const effectiveSpacing=isConnected?0:(parseFloat(g3d.spacing_m)||0);
      const unitWidth=meshBayCount*span+(meshBayCount-1)*effectiveSpacing;
      const totalWidth=unitCount*unitWidth+(unitCount-1)*effectiveSpacing;
      const outerEnvSpec=envelope.outer||{}, innerEnvSpec=envelope.inner||{};
      const _envLayers2=Array.isArray(envelope.layers)?envelope.layers:null;
      const _outerLayer2=_envLayers2?(_envLayers2.find(l=>l.role==='outer')||{}):outerEnvSpec;
      const _innerLayer2=_envLayers2?(_envLayers2.find(l=>l.role==='inner')||null):null;
      const outerCoverMat=(_outerLayer2.cover)||outerEnvSpec.cover_material||'vinyl_double';
      const innerCoverMat=(_innerLayer2&&_innerLayer2.cover)||innerEnvSpec.cover_material||'non_woven_fabric';

      group=new THREE.Group(); group.name='facility_mesh_'+(facility.unique_id||'unknown');
      const es={steps:1,depth:length,bevelEnabled:false};
      const outerShape=_buildMultiSpanShape(span,eaveH,ridgeH,roofType,meshBayCount,effectiveSpacing);
      const outerGeo=new THREE.ExtrudeGeometry(outerShape,es);
      let innerGeo;
      if (isDouble) {
        const inset=0.15;
        const innerShape=_buildMultiSpanShape(span-inset*2,eaveH-inset*0.5,ridgeH-inset,roofType,meshBayCount,effectiveSpacing);
        innerGeo=new THREE.ExtrudeGeometry(innerShape,{steps:1,depth:length-inset*2,bevelEnabled:false});
      }
      for (let u=0; u<unitCount; u++) {
        const xOffset=u*(unitWidth+effectiveSpacing);
        const om=new THREE.Mesh(outerGeo,MAT.cover(outerCoverMat)); om.name='outer_cover_'+u; om.position.x=xOffset; group.add(om);
        const ed=new THREE.LineSegments(new THREE.EdgesGeometry(outerGeo),new THREE.LineBasicMaterial({color:0x455a64})); ed.position.x=xOffset; group.add(ed);
        if (isDouble&&innerGeo) { const inset=0.15; const im=new THREE.Mesh(innerGeo,MAT.coverInner(innerCoverMat)); im.position.set(xOffset+inset,0,inset); im.name='inner_cover_'+u; group.add(im); }
      }
      if (isConnected) {
        const gm=new THREE.MeshStandardMaterial({color:0x607d8b,roughness:0.5,metalness:0.5});
        for (let b=1;b<meshBayCount;b++) {
          [length*0.25,length*0.75].forEach(z=>{ const c=new THREE.Mesh(new THREE.BoxGeometry(0.05,eaveH,0.05),gm); c.position.set(b*span,eaveH/2,z); group.add(c); });
        }
      }
      // ── Front reinforcement (front_only) ─────────────────────────────────────────────
      {
        const _frontLayers2=(Array.isArray(envelope.layers)?envelope.layers:[])
          .filter(l=>l&&l.type==='front_only');
        if (_frontLayers2.length) {
          const fedgeMat=new THREE.LineBasicMaterial({color:0x455a64});
          _frontLayers2.forEach(layer=>{
            const sides=Array.isArray(layer.sides)?layer.sides:[];
            const depth=parseFloat(layer.depth_m);
            const d=(isFinite(depth)&&depth>0)?depth:3.0;
            const fShape=_buildMultiSpanShape(span,eaveH,ridgeH,roofType,meshBayCount,effectiveSpacing);
            const fGeo=new THREE.ExtrudeGeometry(fShape,{steps:1,depth:d,bevelEnabled:false});
            for (let u=0;u<unitCount;u++) {
              const xOff=u*(unitWidth+effectiveSpacing);
              // Axis-based: y_pos face at z=length, y_neg face at z=0.
              const _axSides = sides.map(_toAxisSide);
              if (_axSides.indexOf('y_pos')>=0) {
                const sm=new THREE.Mesh(fGeo,MAT.cover(outerCoverMat));
                sm.name='front_reinf_y_pos_'+layer.id+'_u'+u;
                sm.position.set(xOff,0,length); sm.renderOrder=1000; group.add(sm);
                const se=new THREE.LineSegments(new THREE.EdgesGeometry(fGeo),fedgeMat);
                se.position.copy(sm.position); group.add(se);
              }
              if (_axSides.indexOf('y_neg')>=0) {
                const nm=new THREE.Mesh(fGeo,MAT.cover(outerCoverMat));
                nm.name='front_reinf_y_neg_'+layer.id+'_u'+u;
                nm.position.set(xOff,0,-d); nm.renderOrder=1000; group.add(nm);
                const ne=new THREE.LineSegments(new THREE.EdgesGeometry(fGeo),fedgeMat);
                ne.position.copy(nm.position); group.add(ne);
              }
            }
          });
        }
      }
      // cx/cz is the main facility center — used as the map transform reference point
      group.userData={cx:totalWidth/2,cz:length/2,orientDeg,totalWidth,length};
    }

    // Fitting rendering: always added regardless of whether P is used (keeps parity with the geo/facility editor)
    // envFittings was computed above (reused here for the cover openings + fitting meshes).
    var allFittings = (facility.fittings || []).concat(envFittings);

    // Apply view_options.category_visibility
    var catVis = (facility.view_options && facility.view_options.category_visibility) || null;
    if (catVis && typeof catVis === 'object') {
      var _catOf = function (f) {
        if (!f) return null;
        if (f.source === 'envelope') return 'envelope';
        var k = f.kind;
        if (k === 'window' || k === 'door' || k === 'side_window') return 'opening';
        if (k === 'fan' || k === 'heater' || k === 'curtain')      return 'climate';
        if (k === 'sensor')  return 'sensor';
        if (k === 'fixture') return 'fixture';
        if (k === 'irrigation_layer' || k === 'irrigation_pipe' ||
            k === 'irrigation_device' || k === 'irrigation_connection') return 'irrig';
        return null;
      };
      allFittings = allFittings.filter(function (f) {
        var c = _catOf(f);
        return c == null || catVis[c] !== false;
      });
    }

    _buildFittingsIntoGroup(group, allFittings, {
      totalWidth: group.userData.totalWidth || 10,
      length: group.userData.length || 30,
      actStates: {}
    });

    var renderMode = (opts && opts.renderMode) || 'default';
    _applyRenderMode(group, renderMode);

    return group;
  }

  global.AoTFacility3D = { buildScene, buildFacilityMesh };
})(window);
