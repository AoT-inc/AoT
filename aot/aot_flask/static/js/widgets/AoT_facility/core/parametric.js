// core/parametric.js — Parametric greenhouse geometry builders (moved from aot-facility-3d.js)
// Exposes window.AoTParametric. Requires THREE.
(function (global) {
  'use strict';

  function buildMultiSpanShape(span, eaveH, ridgeH, roofType, bayCount, spacing) {
    const s = new THREE.Shape();
    s.moveTo(0, 0);
    s.lineTo(0, eaveH);

    for (let b = 0; b < bayCount; b++) {
      const lx = b * (span + spacing);
      const rx = lx + span;

      if (roofType === 'gable') {
        s.lineTo(lx + span / 2, ridgeH);
        s.lineTo(rx, eaveH);
      } else if (roofType === 'flat' || roofType === 'box') {
        s.lineTo(lx, ridgeH);
        s.lineTo(rx, ridgeH);
        s.lineTo(rx, eaveH);
      } else {
        s.bezierCurveTo(lx, ridgeH, rx, ridgeH, rx, eaveH);
      }

      if (spacing > 0 && b < bayCount - 1) {
        s.lineTo(rx + spacing, eaveH);
      }
    }

    const totalWidth = bayCount * span + (bayCount - 1) * spacing;
    s.lineTo(totalWidth, 0);
    s.lineTo(0, 0);
    return s;
  }

  function buildSideVentSash(eaveH, length, openRatio, isRight, MAT) {
    const ventH = Math.min(eaveH * 0.40, 1.2);
    const geo   = new THREE.PlaneGeometry(length * 0.85, ventH);
    geo.translate(0, -ventH / 2, 0);
    const isOpen = openRatio > 0.05;
    const mesh = new THREE.Mesh(geo, isOpen ? MAT.sashOpen() : MAT.sashClosed());
    mesh.name = 'side_vent_' + (isRight ? 'right' : 'left');
    mesh.rotation.y = isRight ? -Math.PI / 2 : Math.PI / 2;
    if (isOpen) mesh.rotation.x = -openRatio * (Math.PI / 3);
    return mesh;
  }

  function buildRoofVentIndicator(span, ridgeH, length, openRatio, MAT) {
    const ventW = span * 0.22;
    const ventL = length * 0.75;
    const geo   = new THREE.PlaneGeometry(ventW, ventL);
    const isOpen = openRatio > 0.05;
    const mesh = new THREE.Mesh(geo, isOpen ? MAT.sashOpen() : MAT.sashClosed());
    mesh.name = 'roof_vent';
    mesh.rotation.x = -(Math.PI / 2) + (isOpen ? openRatio * (Math.PI / 5) : 0);
    return mesh;
  }

  function buildCurtain(totalWidth, eaveH, length, type, deployRatio, MAT) {
    const w   = totalWidth * Math.max(deployRatio, 0.02);
    const geo = new THREE.PlaneGeometry(w, length);
    geo.rotateX(-Math.PI / 2);
    const mat  = type === 'thermal' ? MAT.curtainThermal() : MAT.curtainShade();
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name  = 'curtain_' + type;
    mesh.position.set(w / 2, eaveH + 0.08, length / 2);
    return mesh;
  }

  function buildDeviceIcon(type, isOn, position, MAT) {
    const g = new THREE.Group();
    g.name = 'device_' + type;
    g.position.copy(position);

    let geo, mat;
    if (type === 'fan' || type === 'circulation_fan' || type === 'exhaust_fan') {
      geo = new THREE.TorusGeometry(0.18, 0.04, 8, 16);
      mat = isOn ? MAT.fanOn() : MAT.fan();
    } else if (type === 'heater') {
      geo = new THREE.BoxGeometry(0.4, 0.12, 0.12);
      mat = isOn ? MAT.heaterOn() : MAT.heater();
    } else if (type === 'cooler' || type === 'heat_pump') {
      geo = new THREE.BoxGeometry(0.4, 0.12, 0.12);
      mat = isOn ? MAT.coolerOn() : MAT.cooler();
    } else if (type === 'irrigation_valve') {
      geo = new THREE.CylinderGeometry(0.06, 0.06, 0.25, 8);
      mat = isOn ? MAT.pumpOn() : MAT.pump();
    } else {
      geo = new THREE.SphereGeometry(0.1, 8, 8);
      mat = new THREE.MeshStandardMaterial({ color: isOn ? 0x4caf50 : 0x9e9e9e });
    }

    const mesh = new THREE.Mesh(geo, mat);
    g.add(mesh);

    if (isOn) {
      const ringGeo = new THREE.TorusGeometry(0.25, 0.015, 8, 16);
      const ringMat = new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.5 });
      g.add(new THREE.Mesh(ringGeo, ringMat));
    }
    return g;
  }

  function buildWindArrow(windDeg, length, MAT) {
    const group = new THREE.Group();
    group.name = 'wind_arrow';
    const shaftGeo = new THREE.CylinderGeometry(0.04, 0.04, 1.2, 8);
    group.add(new THREE.Mesh(shaftGeo, MAT.windArrow()));
    const headGeo = new THREE.ConeGeometry(0.12, 0.35, 8);
    const head = new THREE.Mesh(headGeo, MAT.windArrow());
    head.position.y = 0.77;
    group.add(head);
    group.position.set(0, 3.0, length / 2);
    group.rotation.y = THREE.MathUtils.degToRad(windDeg + 180);
    return group;
  }

  function buildCompass(orientationDeg, length, MAT) {
    const group = new THREE.Group();
    group.name = 'compass';
    const geo = new THREE.ConeGeometry(0.08, 0.45, 8);
    const needle = new THREE.Mesh(geo, MAT.compass());
    group.add(needle);
    group.position.set(0, 0.5, length + 1.2);
    group.rotation.y = THREE.MathUtils.degToRad(-orientationDeg);
    return group;
  }

  // Build a 3-axis gizmo using the user-facing Z-up convention (matches the
  // sensor/fitting transform gizmo built in aot-facility-3d.js _buildGizmo):
  //   user X (red)   → Three.js +X  (width / horizontal)
  //   user Y (green) → Three.js +Z  (depth)
  //   user Z (blue)  → Three.js +Y  (height)
  // This way the design-viewport axis gizmo and the per-fitting gizmo speak
  // the same language; users don't have to mentally translate between two
  // different XYZ conventions.
  function buildFloorCompass(totalWidth, length) {
    const g = new THREE.Group(); g.name = 'axis_gizmo';
    const cx = totalWidth / 2, cz = length / 2;
    const arrowLen  = Math.min(totalWidth, length) * 0.25;
    const headLen   = arrowLen * 0.25;
    const headWidth = arrowLen * 0.12;
    const origin = new THREE.Vector3(cx, 0.05, cz);
    // X (red, width) — Three.js +X
    const xArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), origin,
      arrowLen, 0xff3333, headLen, headWidth); xArrow.name = 'axis_x';
    // Y (green, depth) — Three.js +Z
    const yArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), origin,
      arrowLen, 0x33cc33, headLen, headWidth); yArrow.name = 'axis_y';
    // Z (blue, height) — Three.js +Y
    const zArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), origin,
      arrowLen, 0x3399ff, headLen, headWidth); zArrow.name = 'axis_z';
    g.add(xArrow); g.add(yArrow); g.add(zArrow);
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
    const xLabel = _labelSprite('X', '#ff3333');
    xLabel.position.set(cx + arrowLen + 0.8, 0.3, cz); g.add(xLabel);
    const yLabel = _labelSprite('Y', '#33cc33');
    yLabel.position.set(cx, 0.3, cz + arrowLen + 0.8); g.add(yLabel);
    const zLabel = _labelSprite('Z', '#3399ff');
    zLabel.position.set(cx, arrowLen + 0.8, cz); g.add(zLabel);
    return g;
  }

  function buildPipe(pts, radius, color, opacity, MAT) {
    const curve = new THREE.CatmullRomCurve3(pts.map(([x, y, z]) => new THREE.Vector3(x, y, z)));
    const geo   = new THREE.TubeGeometry(curve, Math.max(pts.length * 4, 8), radius, 6, false);
    const mat   = new THREE.MeshStandardMaterial({
      color, roughness: 0.55, metalness: 0.35,
      transparent: opacity < 1, opacity: opacity != null ? opacity : 1,
    });
    const m = new THREE.Mesh(geo, mat);
    m.name = 'pipe';
    return m;
  }

  function buildIrrigationPipes(totalWidth, length, span, bayCount, effectiveSpacing, isOn, MAT) {
    const group = new THREE.Group();
    group.name  = 'irrigation_pipes';
    const color = isOn ? 0x29b6f6 : 0x607d8b;
    const pH    = 0.18;
    const cx    = totalWidth / 2;

    const header = buildPipe([[cx, pH, 0.5], [cx, pH, length - 0.5]], 0.038, color, 1.0);
    header.name  = 'pipe_header';
    group.add(header);

    for (let b = 0; b < bayCount; b++) {
      const bx  = b * (span + effectiveSpacing) + span / 2;
      const lx0 = bx - span * 0.44;
      const lx1 = bx + span * 0.44;
      [0.15, 0.35, 0.50, 0.65, 0.85].forEach(function (zf) {
        const lat = buildPipe([[lx0, pH, length * zf], [cx, pH, length * zf], [lx1, pH, length * zf]], 0.020, color, 0.82);
        lat.name  = 'pipe_lateral';
        group.add(lat);
      });
    }
    return group;
  }

  function buildHeatingPipes(totalWidth, length, isOn) {
    const group = new THREE.Group();
    group.name  = 'heating_pipes';
    const color = isOn ? 0xef5350 : 0x795548;
    const pH    = 0.22;
    const inset = 0.35;

    [inset, totalWidth - inset].forEach(function (x) {
      const curve = new THREE.CatmullRomCurve3([
        new THREE.Vector3(x, pH, 0.4), new THREE.Vector3(x, pH, length - 0.4),
      ]);
      const geo = new THREE.TubeGeometry(curve, 8, 0.030, 6, false);
      const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.35 });
      const rail = new THREE.Mesh(geo, mat);
      rail.name = 'pipe_heat_rail';
      group.add(rail);
    });
    return group;
  }

  // ── Openable outer cover (panel decomposition) ───────────────────────────────
  // The legacy outer cover was a single ExtrudeGeometry (a closed shell), so a
  // window/vent could never punch a real opening through it — it only floated a
  // tinted overlay on a sealed skin. To make "the model itself opens" when a
  // 창호 is created, the outer cover is decomposed into flat panels:
  //   · side walls (x=const)  → ShapeGeometry(z,y) with side-window holes
  //   · end caps   (z=const)  → cross-section ShapeGeometry(x,y) with end-window holes
  //   · roof                  → swept profile surface (kept solid; roof vents stay overlay)
  // Walls and caps are flat, so THREE.Path holes cut clean openings there. The
  // curved roof keeps its current overlay treatment by design.

  // Map cover-relevant fittings to opening rectangles in absolute facility coords.
  //   walls: { x, z0,z1, y0,y1 }  opening on a vertical side wall at world x≈`x`
  //   caps : { z, x0,x1, y0,y1 }  opening on an end wall at world z≈`z`
  // Roof openings (surface_normal dominated by ±Y) are intentionally skipped.
  function coverOpeningsFromFittings(fittings) {
    var walls = [], caps = [];
    (Array.isArray(fittings) ? fittings : []).forEach(function (f) {
      if (!f) return;
      var k = f.kind;
      if (k !== 'side_window' && k !== 'window' && k !== 'door') return;
      var sn = f.surface_normal, p = f.position, s = f.size;
      if (!sn || !p || !s) return;
      var ax = Math.abs(sn[0] || 0), ay = Math.abs(sn[1] || 0), az = Math.abs(sn[2] || 0);
      if (ax >= 0.9 && ax >= az && ax >= ay) {
        // Side wall (±X). Box w runs along Z (length), h along Y (height).
        var hZ = (s.w || 0) / 2, hY = (s.h || 0) / 2;
        walls.push({ x: p.x || 0, z0: (p.z || 0) - hZ, z1: (p.z || 0) + hZ, y0: (p.y || 0) - hY, y1: (p.y || 0) + hY });
      } else if (az >= 0.9 && az >= ay) {
        // End cap (±Z). Box w runs along X, h along Y.
        var cX = (s.w || 0) / 2, cY = (s.h || 0) / 2;
        caps.push({ z: p.z || 0, x0: (p.x || 0) - cX, x1: (p.x || 0) + cX, y0: (p.y || 0) - cY, y1: (p.y || 0) + cY });
      }
    });
    return { walls: walls, caps: caps };
  }

  function _remapShapeToYZ(geo, wx) {
    // ShapeGeometry lies in local XY (x→length/Z, y→height/Y, z=0). Re-place it
    // on the vertical plane x=wx: local x → world Z, local y → world Y.
    var p = geo.attributes.position;
    for (var i = 0; i < p.count; i++) {
      var lx = p.getX(i), ly = p.getY(i);
      p.setXYZ(i, wx, ly, lx);
    }
    p.needsUpdate = true;
  }

  function _roofProfilePoints(span, eaveH, ridgeH, roofType, bayCount, spacing) {
    // Roof-top polyline (eave→…→eave) in cross-section (x,y), matching buildMultiSpanShape.
    var pts = [];
    for (var b = 0; b < bayCount; b++) {
      var lx = b * (span + spacing), rx = lx + span;
      if (roofType === 'gable') {
        pts.push([lx, eaveH]); pts.push([lx + span / 2, ridgeH]); pts.push([rx, eaveH]);
      } else if (roofType === 'flat' || roofType === 'box') {
        pts.push([lx, eaveH]); pts.push([lx, ridgeH]); pts.push([rx, ridgeH]); pts.push([rx, eaveH]);
      } else {
        var N = 18;
        for (var i = 0; i <= N; i++) {
          var t = i / N, u = 1 - t;
          var x = u * u * u * lx + 3 * u * u * t * lx + 3 * u * t * t * rx + t * t * t * rx;
          var y = u * u * u * eaveH + 3 * u * u * t * ridgeH + 3 * u * t * t * ridgeH + t * t * t * eaveH;
          pts.push([x, y]);
        }
      }
      if (spacing > 0 && b < bayCount - 1) pts.push([rx + spacing, eaveH]);
    }
    return pts;
  }

  function _sweepProfileAlongZ(pts, length, xOff) {
    var positions = [];
    for (var i = 0; i < pts.length - 1; i++) {
      var ax = pts[i][0] + xOff, ay = pts[i][1];
      var bx = pts[i + 1][0] + xOff, by = pts[i + 1][1];
      positions.push(ax, ay, 0, bx, by, 0, bx, by, length);
      positions.push(ax, ay, 0, bx, by, length, ax, ay, length);
    }
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    g.computeVertexNormals();
    return g;
  }

  // Build the openable outer cover for all units. Returns a group whose meshes
  // are all named with the 'outer_cover_' prefix so existing surface raycasts
  // (window/door/device placement) keep working.
  function buildOuterCoverPanels(opts) {
    var unitCount = opts.unitCount, unitWidth = opts.unitWidth, spacing = opts.effectiveSpacing || 0;
    var meshBayCount = opts.meshBayCount, span = opts.span, eaveH = opts.eaveH, ridgeH = opts.ridgeH;
    var roofType = opts.roofType, length = opts.length, mat = opts.material;
    var openings = opts.openings || { walls: [], caps: [] };
    var EDGE = new THREE.LineBasicMaterial({ color: 0x455a64 });
    var group = new THREE.Group(); group.name = 'outer_cover_panels';
    var EPS = 0.02;

    for (var u = 0; u < unitCount; u++) {
      var xOff = u * (unitWidth + spacing);

      // Side walls
      [{ wx: xOff, side: 'x_neg' }, { wx: xOff + unitWidth, side: 'x_pos' }].forEach(function (wall) {
        var shape = new THREE.Shape();
        shape.moveTo(0, 0); shape.lineTo(length, 0); shape.lineTo(length, eaveH); shape.lineTo(0, eaveH); shape.lineTo(0, 0);
        openings.walls.forEach(function (o) {
          if (Math.abs(o.x - wall.wx) > 0.25) return;
          var z0 = Math.max(EPS, o.z0), z1 = Math.min(length - EPS, o.z1);
          var y0 = Math.max(EPS, o.y0), y1 = Math.min(eaveH - EPS, o.y1);
          if (z1 - z0 < EPS || y1 - y0 < EPS) return;
          var h = new THREE.Path();
          h.moveTo(z0, y0); h.lineTo(z1, y0); h.lineTo(z1, y1); h.lineTo(z0, y1); h.lineTo(z0, y0);
          shape.holes.push(h);
        });
        var geo = new THREE.ShapeGeometry(shape);
        _remapShapeToYZ(geo, wall.wx);
        geo.computeVertexNormals();
        var m = new THREE.Mesh(geo, mat); m.name = 'outer_cover_u' + u + '_' + wall.side; m.renderOrder = 1000;
        group.add(m);
        group.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), EDGE));
      });

      // End caps
      [{ z: 0, side: 'y_neg' }, { z: length, side: 'y_pos' }].forEach(function (cap) {
        var shape = buildMultiSpanShape(span, eaveH, ridgeH, roofType, meshBayCount, spacing);
        openings.caps.forEach(function (o) {
          if (Math.abs(o.z - cap.z) > 0.25) return;
          var lx0 = Math.max(EPS, o.x0 - xOff), lx1 = Math.min(unitWidth - EPS, o.x1 - xOff);
          var y0 = Math.max(EPS, o.y0), y1 = o.y1;
          if (lx1 - lx0 < EPS || y1 - y0 < EPS) return;
          var h = new THREE.Path();
          h.moveTo(lx0, y0); h.lineTo(lx1, y0); h.lineTo(lx1, y1); h.lineTo(lx0, y1); h.lineTo(lx0, y0);
          shape.holes.push(h);
        });
        var geo = new THREE.ShapeGeometry(shape);
        geo.translate(xOff, 0, cap.z);
        var m = new THREE.Mesh(geo, mat); m.name = 'outer_cover_u' + u + '_' + cap.side; m.renderOrder = 1000;
        group.add(m);
        group.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), EDGE));
      });

      // Roof (kept solid)
      var roofGeo = _sweepProfileAlongZ(_roofProfilePoints(span, eaveH, ridgeH, roofType, meshBayCount, spacing), length, xOff);
      var rm = new THREE.Mesh(roofGeo, mat); rm.name = 'outer_cover_u' + u + '_roof'; rm.renderOrder = 1000;
      group.add(rm);
    }
    return group;
  }

  function buildFacilityMeshGroup(facility, MAT, extraFittings) {
    const g3d      = facility.geometry_3d || {};
    const envelope = facility.envelope    || {};

    const span      = parseFloat(g3d.span_width_m)   || 7;
    const eaveH     = parseFloat(g3d.eave_height_m)  || 2;
    const ridgeH    = parseFloat(g3d.ridge_height_m) || 4;
    const length    = parseFloat(g3d.length_m)       || 30;
    const roofType  = String(g3d.roof_type || 'arch').toLowerCase();
    const orientDeg = parseFloat(g3d.orientation_deg) || 0;
    const rawBayCount = Math.max(parseInt(facility.bay_count || 1, 10), 1);
    const isConnected = facility.structure === 'connected';
    const unitCount = isConnected ? 1 : rawBayCount;
    const meshBayCount = isConnected ? rawBayCount : 1;
    const isDouble = Array.isArray(envelope.layers)
      ? envelope.layers.some(l => l.role === 'inner')
      : (envelope.layer_count || 1) === 2;
    const effectiveSpacing = isConnected ? 0 : (parseFloat(g3d.spacing_m) || 0);
    const unitWidth = meshBayCount * span + (meshBayCount - 1) * effectiveSpacing;
    const totalWidth = unitCount * unitWidth + (unitCount - 1) * effectiveSpacing;

    const _envLayers = Array.isArray(envelope.layers) ? envelope.layers : null;
    const _outerLayer = _envLayers ? (_envLayers.find(l => l.role === 'outer') || {}) : {};
    const _innerLayer = _envLayers ? (_envLayers.find(l => l.role === 'inner') || null) : null;
    const outerEnvSpec  = envelope.outer || {};
    const innerEnvSpec  = envelope.inner || {};
    const outerCoverMat = (_outerLayer.cover) || outerEnvSpec.cover_material || 'vinyl_double';
    const innerCoverMat = (_innerLayer && _innerLayer.cover) || innerEnvSpec.cover_material || 'non_woven_fabric';

    const group = new THREE.Group();
    group.name = 'facility_mesh_' + (facility.unique_id || 'unknown');

    // Outer cover as openable panels (side-window / end-window holes are real).
    const _coverFittings = (Array.isArray(facility.fittings) ? facility.fittings : [])
      .concat(Array.isArray(extraFittings) ? extraFittings : []);
    group.add(buildOuterCoverPanels({
      unitCount: unitCount, unitWidth: unitWidth, effectiveSpacing: effectiveSpacing,
      meshBayCount: meshBayCount, span: span, eaveH: eaveH, ridgeH: ridgeH,
      roofType: roofType, length: length, material: MAT.cover(outerCoverMat),
      openings: coverOpeningsFromFittings(_coverFittings),
    }));

    let innerGeo;
    if (isDouble) {
      const inset = 0.15;
      const innerShape = buildMultiSpanShape(
        span - inset * 2, eaveH - inset * 0.5, ridgeH - inset, roofType, meshBayCount, effectiveSpacing
      );
      innerGeo = new THREE.ExtrudeGeometry(innerShape,
        { steps: 1, depth: length - inset * 2, bevelEnabled: false });
    }

    for (let u = 0; u < unitCount; u++) {
      const xOffset = u * (unitWidth + effectiveSpacing);
      if (isDouble && innerGeo) {
        const inset = 0.15;
        const innerMesh = new THREE.Mesh(innerGeo, MAT.coverInner(innerCoverMat));
        innerMesh.position.set(xOffset + inset, 0, inset);
        innerMesh.name = 'inner_cover_' + u;
        innerMesh.renderOrder = 900;
        group.add(innerMesh);
      }
    }

    if (isConnected) {
      const gutterMat = new THREE.MeshStandardMaterial({ color: 0x607d8b, roughness: 0.5, metalness: 0.5 });
      for (let b = 1; b < meshBayCount; b++) {
        const col = new THREE.Mesh(new THREE.BoxGeometry(0.05, eaveH, 0.05), gutterMat);
        col.position.set(b * span, eaveH / 2, length * 0.25);
        group.add(col);
        const col2 = col.clone();
        col2.position.set(b * span, eaveH / 2, length * 0.75);
        group.add(col2);
      }
    }

    // Front reinforcement — env.layers[type=front_only]
    {
      const _envLayers = Array.isArray(envelope.layers) ? envelope.layers : [];
      const frontLayers = _envLayers.filter(l => l && l.type === 'front_only');
      if (frontLayers.length) {
        const edgeMat = new THREE.LineBasicMaterial({ color: 0x455a64, linewidth: 1 });
        frontLayers.forEach(layer => {
          const sides = Array.isArray(layer.sides) ? layer.sides : [];
          const depth = parseFloat(layer.depth_m);
          const d = (isFinite(depth) && depth > 0) ? depth : 3.0;
          const fShape = buildMultiSpanShape(span, eaveH, ridgeH, roofType, meshBayCount, effectiveSpacing);
          const fGeo = new THREE.ExtrudeGeometry(fShape, { steps: 1, depth: d, bevelEnabled: false });
          for (let u = 0; u < unitCount; u++) {
            const xOff = u * (unitWidth + effectiveSpacing);
            // Axis-based: y_pos face at z=length, y_neg face at z=0. Accepts
            // both new axis labels and legacy compass labels (south/north).
            const _axSides = sides.map(function (s) {
              if (s === 'south') return 'y_pos';
              if (s === 'north') return 'y_neg';
              if (s === 'east')  return 'x_pos';
              if (s === 'west')  return 'x_neg';
              return s;
            });
            if (_axSides.indexOf('y_pos') >= 0) {
              const sm = new THREE.Mesh(fGeo, MAT.cover(outerCoverMat));
              sm.name = 'front_reinf_y_pos_' + (layer.id || u) + '_u' + u;
              sm.position.set(xOff, 0, length);
              sm.renderOrder = 1000;
              group.add(sm);
              const se = new THREE.LineSegments(new THREE.EdgesGeometry(fGeo), edgeMat);
              se.position.copy(sm.position);
              group.add(se);
            }
            if (_axSides.indexOf('y_neg') >= 0) {
              const nm = new THREE.Mesh(fGeo, MAT.cover(outerCoverMat));
              nm.name = 'front_reinf_y_neg_' + (layer.id || u) + '_u' + u;
              nm.position.set(xOff, 0, -d);
              nm.renderOrder = 1000;
              group.add(nm);
              const ne = new THREE.LineSegments(new THREE.EdgesGeometry(fGeo), edgeMat);
              ne.position.copy(nm.position);
              group.add(ne);
            }
          }
        });
      }
    }

    group.userData.cx = totalWidth / 2;
    group.userData.cz = length / 2;
    group.userData.orientDeg = orientDeg;
    group.userData.totalWidth = totalWidth;
    group.userData.length = length;
    return group;
  }

  global.AoTParametric = {
    buildMultiSpanShape,
    buildOuterCoverPanels,
    coverOpeningsFromFittings,
    buildSideVentSash,
    buildRoofVentIndicator,
    buildCurtain,
    buildDeviceIcon,
    buildWindArrow,
    buildCompass,
    buildFloorCompass,
    buildPipe,
    buildIrrigationPipes,
    buildHeatingPipes,
    buildFacilityMeshGroup,
  };
})(window);
