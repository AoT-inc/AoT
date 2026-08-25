// facility-3d-bridge.js — extracted from templates/pages/geo/geo_facility.html (2026-07-31).
// Bridges the page form to the 3D scene: rebuilds on edits, wires the tool rail/flyouts, the fitting list toggle, step navigation, export/import and the irrigation helpers.
// Loaded as part of the geo-facility bundle, after aot-facility-design.js,
// so FittingsUI/EnvelopeUI and the _IEC/_COMM string catalogs already exist.

(function () {
  'use strict';

  var _ctx = null;
  var _debounceTimer = null;

  // ── Move history (undo) ──────────────────────────────────────────────────
  // Only position moves are tracked — the case the button exists for is a
  // careless drag, and everything else (add/remove/kind changes) already has
  // its own explicit, deliberate control (Delete button, "Back to automatic").
  var _historyStack = [];
  var MAX_HISTORY = 50;
  var _dragTrackingId = null;   // id of the fitting the in-progress drag is moving
  var _dragFromPos    = null;   // its position before that drag began

  // ── Which fittings the user may move by hand ────────────────────────────────
  // Exactly the ones listed as components in step 4: everything the envelope
  // generates (curtains, windows and doors derived from the cover settings) is
  // positioned by the envelope geometry, so a hand-drag there would be undone on
  // the next rebuild. This is derived from the data on purpose — the earlier
  // hardcoded kind list silently excluded every kind added after it was written.
  function _isMovableFitting(f) {
    // Envelope-derived items are movable too — the drag detaches them from
    // automatic geometry (FittingsUI.updateFittingPosition), and the placement
    // panel offers a way back. Before, they could only be toggled on and off.
    return !!(f && f.position);
  }

  function _findFitting(id) {
    if (!id || !window.FittingsUI) return null;
    return FittingsUI.readAll().find(function (x) { return x.id === id; }) || null;
  }

  function _pushHistory(entry) {
    _historyStack.push(entry);
    if (_historyStack.length > MAX_HISTORY) _historyStack.shift();
    _syncUndoButton();
  }

  function _syncUndoButton() {
    var btn = document.getElementById('btn-3d-undo');
    if (btn) btn.disabled = _historyStack.length === 0;
  }

  // Reverts the most recent recorded move. Only reaches into the pieces that
  // a live drag itself updates (data, inspector fields, mesh, arrows) — same
  // set as the aot-gizmo-moved handler above, just applied once instead of
  // per mouse-move.
  function undoLastMove() {
    var entry = _historyStack.pop();
    _syncUndoButton();
    if (!entry || entry.type !== 'move') return;
    var p = entry.from;
    if (window.FittingsUI && typeof FittingsUI.updateFittingPosition === 'function') {
      FittingsUI.updateFittingPosition(entry.id, p);
    }
    if (_ctx && typeof _ctx.updateFittingTransform === 'function') {
      _ctx.updateFittingTransform(entry.id, p, null);
    }
    // Only touch the inspector/arrows if this fitting is still the one selected.
    if (window.FittingsUI && FittingsUI.getSelectedId() === entry.id) {
      var fx = document.getElementById('fi-x');
      var fy = document.getElementById('fi-y');
      var fz = document.getElementById('fi-z');
      if (fx) fx.value = p.x.toFixed(3);
      if (fy) fy.value = p.z.toFixed(3); // user Y = depth = Three.js Z
      if (fz) fz.value = p.y.toFixed(3); // user Z = height = Three.js Y
      if (_ctx && typeof _ctx.showGizmo === 'function') _ctx.showGizmo(entry.id, p);
    }
    document.dispatchEvent(new CustomEvent('fittings-data-changed'));
  }

  // Lets the 3D scene ask whether a mesh may be dragged, without teaching it
  // anything about facility semantics.
  function _installFittingProbe() {
    if (!_ctx || typeof _ctx.setFittingProbe !== 'function') return;
    _ctx.setFittingProbe(function (id) {
      var f = _findFitting(id);
      if (!f) return null;
      return {
        movable: _isMovableFitting(f),
        position: f.position,
        selected: window.FittingsUI ? FittingsUI.getSelectedId() === id : false
      };
    });
  }

  // ── Read current form values into a facility-like object ─────────────────────
  function _formFacility() {
    var structure = (document.querySelector('input[name="structure"]:checked') || {}).value || 'single';
    return {
      unique_id:  'preview',
      name:       (document.getElementById('facility-name') || {}).value || 'Preview',
      preset:     (document.getElementById('facility-preset') || {}).value || 'standard_arch',
      structure:  structure,
      bay_count:  Math.max(parseInt((document.getElementById('bay-count') || {}).value || '1', 10), 1),
      geometry_3d: {
        span_width_m:    parseFloat((document.getElementById('span-width')   || {}).value) || 7,
        eave_height_m:   parseFloat((document.getElementById('eave-height')  || {}).value) || 2,
        ridge_height_m:  parseFloat((document.getElementById('ridge-height') || {}).value) || 4,
        length_m:        parseFloat((document.getElementById('length-m')     || {}).value) || 30,
        spacing_m:       parseFloat((document.getElementById('spacing-m')    || {}).value) || 0,
        roof_type:       (document.getElementById('roof-type') || {}).value || 'arch',
        orientation_deg: parseInt((document.getElementById('orientation-input') || {}).value || '0', 10),
      },
      envelope: window.EnvelopeUI ? EnvelopeUI.read() : {},
      actuators: window.ActuatorUI ? ActuatorUI.read() : [],
      fittings:  window.FittingsUI ? FittingsUI.readAll() : [],
      computed:  null,
      bays:      [],
    };
  }

  // ── Build / rebuild the Three.js scene ───────────────────────────────────────
  function _doRebuild(preserveCamera) {
    if (!window.AoTFacility3D) return;
    var canvas = document.getElementById('facility-3d-canvas');
    if (!canvas) return;

    var activeTool = (document.querySelector('#facility-3d-tools .tool-btn.active') || {}).dataset || {};
    var keepTool = activeTool.tool || '';

    var camState = null;
    if (preserveCamera && _ctx && _ctx.camera && _ctx.controls) {
      camState = {
        position: _ctx.camera.position.clone(),
        target:   _ctx.controls.target.clone(),
        fov:      _ctx.camera.fov,
        zoom:     _ctx.camera.zoom
      };
    }

    if (_ctx) { _ctx.dispose(); _ctx = null; }
    var newCtx = null;
    try {
      newCtx = window.AoTFacility3D.buildScene(canvas, _formFacility(), null);
    } catch (err) {
      console.error('[facility] buildScene failed:', err);
      setTimeout(function () {
        try {
          _ctx = window.AoTFacility3D.buildScene(canvas, _formFacility(), null);
          _installFittingProbe();
          if (camState && _ctx && _ctx.camera && _ctx.controls) {
            _ctx.camera.position.copy(camState.position);
            _ctx.controls.target.copy(camState.target);
            _ctx.camera.updateProjectionMatrix();
            _ctx.controls.update();
          }
          if (keepTool && _ctx && _ctx.setTool) _ctx.setTool(keepTool);
        } catch (e2) {
          console.error('[facility] buildScene retry failed:', e2);
        }
      }, 50);
      return;
    }
    _ctx = newCtx;
    _installFittingProbe();

    // Reapply saved category visibility after scene rebuild
    if (_ctx && typeof _ctx.setCategoryVisibility === 'function' &&
        window.FittingsUI && FittingsUI.getCategoryVisibility) {
      var vs = FittingsUI.getCategoryVisibility();
      Object.keys(vs).forEach(function (k) { _ctx.setCategoryVisibility(k, vs[k]); });
    }

    if (camState && _ctx && _ctx.camera && _ctx.controls) {
      _ctx.camera.position.copy(camState.position);
      _ctx.controls.target.copy(camState.target);
      if (camState.fov)  _ctx.camera.fov  = camState.fov;
      if (camState.zoom) _ctx.camera.zoom = camState.zoom;
      _ctx.camera.updateProjectionMatrix();
      _ctx.controls.update();
    }

    if (keepTool && _ctx && typeof _ctx.setTool === 'function') {
      _ctx.setTool(keepTool);
    }
  }

  // rebuild() preserves the user's camera angle; rebuildFit() re-fits the camera
  // to the facility dimensions (called after loading a new facility spec).
  function rebuild() { _doRebuild(true); }

  function rebuildFit() {
    _doRebuild(false);
    if (!_ctx || !_ctx.camera || !_ctx.controls) return;
    // Compute camera position from actual form values — no canvas-size dependency.
    var fac = _formFacility();
    var g   = fac.geometry_3d || {};
    var span = parseFloat(g.span_width_m)  || 7;
    var rH   = parseFloat(g.ridge_height_m)|| 4;
    var ln   = parseFloat(g.length_m)      || 30;
    var bc   = (fac.structure === 'connected') ? Math.max(parseInt(fac.bay_count || 1, 10), 1) : 1;
    var sp   = (fac.structure === 'connected') ? 0 : (parseFloat(g.spacing_m) || 0);
    var tw   = bc * span + (bc - 1) * sp;
    var br   = Math.sqrt((tw/2)*(tw/2) + (rH/2)*(rH/2) + (ln/2)*(ln/2));
    var hfv  = _ctx.camera.fov / 2 * Math.PI / 180;
    var dist = br / Math.sin(hfv) * 1.18;
    var norm = Math.sqrt(0.55*0.55 + 0.85*0.85 + 0.65*0.65);
    var dx = 0.55/norm, dy = 0.85/norm, dz = -0.65/norm;
    _ctx.camera.position.set(tw/2 + dx*dist, rH/2 + dy*dist, ln/2 + dz*dist);
    _ctx.controls.target.set(tw/2, rH/2, ln/2);
    _ctx.camera.updateProjectionMatrix();
    _ctx.controls.update();
  }

  // ── Debounced rebuild (300 ms after last input) ───────────────────────────────
  function scheduleRebuild() {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(rebuild, 300);
  }

  // ── Sync envelope-activated items into the fittings list ─────────────────────
  // Generates structurally-correct virtual fittings from envelope settings.
  // Key design rules (per user feedback):
  //   • Side window/wall curtain 2-stage: ignore stage value and split available wall height evenly
  //   • Fix floating roof vents: compute the actual roof apex Y per roof_type
  //     - flat/box → y = ridgeH
  //     - gable    → y = ridgeH
  //     - arch     → bezier curve apex y = (eaveH + 3·ridgeH) / 4
  //   • Roof vent placement: 'center' (ridge) or 'sides' (mid of left/right slope)
  //   • Ceiling stacking: shade (top) → thermal L1 → thermal L2 (going down)
  // Envelope component names come from the page's server catalog: they need
  // context-specific msgids (see the _IEC block in geo_facility.html) rather
  // than bare words like "Lower" that already mean something else app-wide.
  function _EL(key, fallback) {
    var d = window._IEC || {};
    return (d[key] != null && d[key] !== '') ? d[key] : fallback;
  }

  function _renderEnvelopeFittings() {
    if (!window.FittingsUI) return;
    var env = window.EnvelopeUI ? EnvelopeUI.read() : null;
    if (!env) { FittingsUI.syncEnvelopeItems([]); return; }

    function _r(v) { return Math.round((v || 0) * 100) / 100; }

    // Facility dimensions
    var span     = parseFloat((document.getElementById('span-width')   || {}).value) || 7;
    var L        = parseFloat((document.getElementById('length-m')     || {}).value) || 30;
    var eaveH    = parseFloat((document.getElementById('eave-height')  || {}).value) || 2;
    var ridgeH   = parseFloat((document.getElementById('ridge-height') || {}).value) || 4;
    var bayCount = Math.max(parseInt((document.getElementById('bay-count') || {}).value, 10) || 1, 1);
    var spacing  = parseFloat((document.getElementById('spacing-m')    || {}).value) || 0;
    var struct   = ((document.querySelector('input[name="structure"]:checked') || {}).value) || 'single';
    var roofType = (document.getElementById('roof-type') || {}).value || 'arch';
    var effSp    = (struct === 'connected') ? 0 : spacing;
    var W        = bayCount * span + (bayCount - 1) * effSp;

    // ── Unit / mesh-bay decomposition ────────────────────────────────────────
    // Connected mode = 1 house with N joined bays (shared walls between bays).
    // Single   mode = N standalone single-bay houses with a gap between each.
    // unitCount  = number of standalone house meshes
    // meshBayCount = number of bays inside each unit
    // unitWidth  = span of one unit
    // UNITS      = pre-computed list of { index, leftX, rightX, centerX } for
    //              each unit so the per-side blocks below can emit fittings
    //              against EACH house's own walls rather than only the outermost.
    var isConnected  = (struct === 'connected');
    var unitCount    = isConnected ? 1 : bayCount;
    var meshBayCount = isConnected ? bayCount : 1;
    var unitWidth    = meshBayCount * span + (meshBayCount - 1) * effSp;
    var UNITS = [];
    for (var __u = 0; __u < unitCount; __u++) {
      var __ux = __u * (unitWidth + effSp);
      UNITS.push({
        index:   __u,
        leftX:   __ux,
        rightX:  __ux + unitWidth,
        centerX: __ux + unitWidth / 2
      });
    }
    function _unitLabel(idx) { return (unitCount > 1) ? (' #' + (idx + 1)) : ''; }

    // Actual roof apex Y depending on roof_type — critical for non-floating
    // placement of roof vents. The arch is drawn as a cubic Bezier (P0=eaveH,
    // P1=P2=ridgeH, P3=eaveH); at t=0.5 the curve is at y = (eaveH + 3·ridgeH)/4,
    // NOT y=ridgeH. Earlier versions placed boxes at y=ridgeH which floated
    // up to (ridgeH − apex_y) above the surface.
    var roofApexY;
    if (roofType === 'gable' || roofType === 'gable2' ||
        roofType === 'flat'  || roofType === 'box') {
      roofApexY = ridgeH;
    } else {
      // arch (default)
      roofApexY = (eaveH + 3 * ridgeH) / 4;
    }

    // gable2 is a gable repeated twice across the bay, so its profile is the
    // gable profile evaluated on a t that runs 0→1 twice. Folding it here keeps
    // the vent-placement maths below identical for both.
    function _gableT(t) { return roofType === 'gable2' ? (t * 2) % 1 : t; }

    // Roof surface Y at a normalised slope position t ∈ [0,1] (0 = left eave,
    // 0.5 = ridge, 1 = right eave). Used for the 'sides' roof-vent placement.
    function _roofYatT(t) {
      if (roofType === 'gable' || roofType === 'gable2') {
        // Linear from eaveH → ridgeH → eaveH (twice over, for gable2)
        var g = _gableT(t);
        return eaveH + (ridgeH - eaveH) * (1 - Math.abs(g - 0.5) * 2);
      }
      if (roofType === 'flat' || roofType === 'box') {
        return ridgeH;
      }
      // Cubic bezier B(t).y = (1−t)^3·eaveH + 3(1−t)^2·t·ridgeH + 3(1−t)·t^2·ridgeH + t^3·eaveH
      var u  = 1 - t;
      return u*u*u * eaveH + 3*u*u*t * ridgeH + 3*u*t*t * ridgeH + t*t*t * eaveH;
    }

    // Outward surface normal at slope position t (in world XY plane).
    // Computed as a 90° CCW rotation of the tangent — so the normal points
    // away from the greenhouse interior. Used to ANGLE the roof-vent box to
    // the slope on 'sides' placement, otherwise a flat box on a curved arch
    // would always look like it's floating above the surface.
    function _roofNormalAtT(t) {
      if (roofType === 'flat' || roofType === 'box') return [0, 1, 0];
      var tx, ty;
      if (roofType === 'gable' || roofType === 'gable2') {
        // Half the run of one gable — a quarter span when the bay carries two.
        var g  = _gableT(t);
        var hx = (roofType === 'gable2') ? span / 4 : span / 2;
        if (g < 0.5) { tx = hx; ty = ridgeH - eaveH; }
        else         { tx = hx; ty = -(ridgeH - eaveH); }
      } else {
        // Cubic bezier derivative
        tx = (6 * t - 3 * t * t) * span;
        ty = 3 * (1 - 2 * t) * (ridgeH - eaveH);
      }
      var nx = -ty, ny = tx;  // CCW rotation = outward normal
      var mag = Math.sqrt(nx * nx + ny * ny);
      if (mag < 1e-6) return [0, 1, 0];
      return [nx / mag, ny / mag, 0];
    }

    // Equal-split stages within the side wall with a small visible gap so the
    // two stages render as distinct boxes (touching boxes look like one tall
    // panel). Overrides EnvelopeUI's raw stage values per user request:
    // "for 2 stages, split the two heights equally".
    // Returns an array of { id, y, h } stage descriptors.
    function _equalStages(stageCount, margin, gap) {
      var m = margin == null ? 0.05 : margin;
      var g = gap    == null ? 0.10 : gap;   // 10 cm gap between stages
      var n = Math.max(stageCount | 0, 1);
      var avail = Math.max(eaveH - 2 * m - (n - 1) * g, 0.4);
      var stepH = avail / n;
      var out = [];
      for (var i = 0; i < n; i++) {
        var bottom = m + i * (stepH + g);
        var top    = bottom + stepH;
        var sid    = (n === 1) ? 'single' : (i === 0 ? 'lower' : (i === n - 1 ? 'upper' : 's' + i));
        out.push({ id: sid, y: (bottom + top) / 2, h: top - bottom });
      }
      return out;
    }

    function _stageLbl(sid, i) {
      if (sid === 'lower') return _EL('env_stage_lower', 'Lower stage');
      if (sid === 'upper') return _EL('env_stage_upper', 'Upper stage');
      if (sid === 'single') return '';
      return _EL('env_stage_n', 'Stage') + ' ' + (i + 1);
    }

    // (SIDES/_sideX replaced by per-unit WALLS arrays — see UNITS above.)

    var items = [];

    // ── Reinforcement geometry helpers (need values here for vent overlay) ──
    // side_only layers use 'west'/'east'/'south'/'north' values. For each
    // unit (house) we compute the OUTERMOST reinforcement face offset per
    // side so the side-vent block can mirror its strips onto the exposed
    // face of the reinforcement (requirement: "side windows created by outer side ventilation
    // are created with the same type and size").
    var _reinLayers = (Array.isArray(env.layers) ? env.layers : [])
      .filter(function (l) { return l && l.type === 'side_only'; });
    // Translate legacy compass side names to axis labels (no-op if already axis).
    function _toAxisSideEarly(s) {
      if (s === 'south') return 'y_pos'; if (s === 'north') return 'y_neg';
      if (s === 'east')  return 'x_pos'; if (s === 'west')  return 'x_neg';
      return s;
    }
    function _outermostReinfFaceOffset(reinSide) {
      // Returns positive offset (m) from a unit wall to the outermost
      // reinforcement face on `reinSide`, or null when none is enabled.
      // Accepts either axis label ('x_neg'/'x_pos'/...) or legacy compass.
      var target = _toAxisSideEarly(reinSide);
      var maxOffset = 0, hasAny = false;
      _reinLayers.forEach(function (layer, li) {
        var sides = (Array.isArray(layer.sides) && layer.sides.length > 0)
          ? layer.sides : [];
        var axisSides = sides.map(_toAxisSideEarly);
        if (axisSides.indexOf(target) < 0) return;
        var th = parseFloat(layer.thickness_m);
        if (!isFinite(th) || th <= 0) th = 1.0;
        var stackGap = li * 0.01;
        var faceOffset = th + stackGap;
        if (faceOffset > maxOffset) maxOffset = faceOffset;
        hasAny = true;
      });
      return hasAny ? maxOffset : null;
    }

    // ── Side vent (outer): equal-split stages × each unit's left + right ────
    // Connected mode: unitCount=1 → vents only at the outermost walls (x=0,W).
    // Single   mode: unitCount=N → each house gets its own pair of vents at
    //                u.leftX / u.rightX so internal walls of replicated
    //                houses also carry side windows (user requirement:
    //                "when separated, each house gets side windows on its left and right").
    // Side vent depth (the box thickness along the wall normal). Used to
    // shift the box so it sits ENTIRELY outside the wall (inner face flush
    // with the cover, outer face protruding by SV_DEPTH).
    var SV_DEPTH = 0.05;
    var sv = env.side_vent && env.side_vent.outer;
    if (sv && sv.enabled) {
      var nStages = (Array.isArray(sv.stages) && sv.stages.length > 0) ? sv.stages.length : 1;
      var sideStages = _equalStages(nStages, 0.05);
      var _reinWestOff = _outermostReinfFaceOffset('x_neg');
      var _reinEastOff = _outermostReinfFaceOffset('x_pos');

      sideStages.forEach(function (st, i) {
        UNITS.forEach(function (u) {
          // Per-unit left (west) and right (east) walls
          var WALLS = [
            { id: 'left',  baseX: u.leftX,  sn: [-1, 0, 0], lbl: _EL('env_side_left', 'Left side'),
              reinOff: _reinWestOff,
              outwardSign: -1 },
            { id: 'right', baseX: u.rightX, sn: [ 1, 0, 0], lbl: _EL('env_side_right', 'Right side'),
              reinOff: _reinEastOff,
              outwardSign: +1 }
          ];
          WALLS.forEach(function (w) {
            // OUTSIDE the wall: shift the box by half-depth along the outward
            // normal so the inner face sits flush with the outer cover and
            // the entire vent protrudes beyond the wall plane.
            // Side windows belong to the OUTERMOST envelope of the wall. When a
            // side reinforcement is present on this side, the side window is
            // created ONLY on the reinforcement face (requirement: "측창은 보강
            // 외피에만 추가되어야 한다"). The base cover keeps its side window
            // only on sides without reinforcement.
            if (w.reinOff !== null) {
              var reinFaceX = w.baseX + w.outwardSign * w.reinOff;
              var reinVentX = reinFaceX + w.outwardSign * (SV_DEPTH / 2);
              items.push({
                id:         'env_side_vent_outer_reinf_u' + u.index + '_' + w.id + '_' + st.id,
                kind:       'side_window',
                label:      (_EL('env_side_window', 'Side window') + _unitLabel(u.index) + ' ' + w.lbl + ' ' + _stageLbl(st.id, i) + ' (' + _EL('env_reinf_face', 'reinforcement face') + ')').trim(),
                position:   { x: _r(reinVentX), y: _r(st.y), z: _r(L / 2) },
                size:       { w: _r(L * 0.97), h: _r(st.h), d: SV_DEPTH },
                surface_normal: w.sn,
                // Left and right are the same window mirrored, so they are one
                // instance: the side is deliberately NOT part of the key. With
                // it, a house with one unit put each wall in a group of one —
                // the Linked row never appeared and resizing one wall's window
                // left the opposite wall untouched.
                link_group: 'env_side_vent_outer_reinf_' + st.id
              });
            } else {
              var ventX = w.baseX + w.outwardSign * (SV_DEPTH / 2);
              items.push({
                id:         'env_side_vent_outer_u' + u.index + '_' + w.id + '_' + st.id,
                kind:       'side_window',
                label:      (_EL('env_side_window', 'Side window') + _unitLabel(u.index) + ' ' + w.lbl + ' ' + _stageLbl(st.id, i)).trim(),
                position:   { x: _r(ventX), y: _r(st.y), z: _r(L / 2) },
                size:       { w: _r(L * 0.97), h: _r(st.h), d: SV_DEPTH },
                surface_normal: w.sn,
                // Linked group: every copy of this stage's side window — both
                // walls, all units — is one instance, so editing any of them
                // updates the rest (default inheritance, detachable per item).
                // The side is not in the key on purpose: left and right are the
                // same window mirrored, and each keeps its own position and
                // surface normal because _syncGroup copies neither.
                link_group: 'env_side_vent_outer_' + st.id
              });
            }
          });
        });
      });
    }

    // ── Roof vent (outer): center (apex strip) or sides (slope-aligned) ─────
    // The cover for an 'arch' roof is a cubic Bezier whose actual peak Y is
    //   (eaveH + 3·ridgeH)/4  ≠  ridgeH
    // so the strip Y must be computed from _roofYatT / roofApexY, and the
    // strip itself kept narrow so a flat box doesn't float at its edges
    // where the curve has already descended.
    //
    // 'sides' placement uses surface_normal = slope outward normal so each
    // strip is ROTATED to lie flush with the slope (axis-aligned boxes on a
    // tilted slope always float on one side).
    var rv = env.roof_vent && env.roof_vent.outer;
    if (rv && rv.enabled) {
      var rvThick = 0.06;
      var placement = rv.placement || 'center';

      for (var b = 0; b < bayCount; b++) {
        var baseX = b * (span + effSp);

        if (placement === 'sides') {
          // Two angled strips per bay — one on each slope. surface_normal
          // remaps the local axes so that with N pointing outward from a
          // tilted slope: local +X → world Z (length), local +Y → up the
          // slope, local +Z → out of the slope (panel thickness).
          [
            { t: 0.30, sideId: 'left',  lbl: _EL('env_side_left', 'Left side') },
            { t: 0.70, sideId: 'right', lbl: _EL('env_side_right', 'Right side') }
          ].forEach(function (p) {
            var sx = baseX + p.t * span;
            var sy = _roofYatT(p.t);
            var sn = _roofNormalAtT(p.t);
            items.push({
              id:       'env_roof_vent_outer_b' + b + '_' + p.sideId,
              kind:     'window',
              label:    _EL('env_roof_vent', 'Roof vent') + ' ' + p.lbl + (bayCount > 1 ? ' #' + (b + 1) : ''),
              position: { x: _r(sx), y: _r(sy), z: _r(L / 2) },
              // size axes follow the surface_normal basis:
              //   w → along facility length (Z), h → up the slope, d → out
              size:     { w: _r(L * 0.75), h: _r(span * 0.18), d: rvThick },
              surface_normal: sn,
              // Every slope vent is the same vent repeated — across bays and
              // across the two slopes, which are mirror images of each other.
              // They form ONE instance group so editing any of them updates the
              // rest; the slope used to be part of the key, which left the two
              // sides unable to follow one another. Each member keeps its own
              // position and surface_normal (_syncGroup copies neither), so the
              // mirrored geometry survives the shared size.
              link_group: 'env_roof_vent_outer_slope'
            });
          });
        } else {
          // Center strip along the ridge. Width is intentionally very small
          // (8 % of span) so the box stays flush with the curved apex —
          // wider boxes would float at the strip edges where the bezier
          // already descends below the apex Y. Box top sits exactly at the
          // computed apex (roofApexY) by offsetting center Y by thickness/2.
          items.push({
            id:       'env_roof_vent_outer_b' + b + '_center',
            kind:     'window',
            label:    _EL('env_roof_vent', 'Roof vent') + (bayCount > 1 ? ' #' + (b + 1) : ''),
            position: { x: _r(baseX + span / 2),
                        y: _r(roofApexY - rvThick / 2),
                        z: _r(L / 2) },
            size:     { w: _r(span * 0.08), h: rvThick, d: _r(L * 0.75) },
            surface_normal: null,
            link_group: 'env_roof_vent_outer_center'
          });
        }
      }
    }

    // ── Ceiling stack: shade (top, dark) → thermal L1 → thermal L2 (bottom) ─
    // The shade curtain uses kind='shade_curtain' (dark grey #4a4a4a) so it is
    // visually distinct from thermal curtains (cream #f5e6c8). Without that
    // distinction the user reported they could not tell whether a single
    // visible cream box was thermal or shade — making shade-alone "invisible".
    //
    // Slot Y assignment uses absolute heights (not a generic stack index) so
    // shade is ALWAYS at the topmost reserved position (just under the eave)
    // and thermal layers always sit at clearly lower fixed positions —
    // regardless of which toggles are active. This guarantees:
    //   shade Y  =  eaveH × 0.96
    //   thermal Lk Y  =  eaveH × 0.88 − k × 0.10
    // (≈ 16 cm gap between shade and the topmost thermal so the two never
    // visually merge.)
    //
    // Geometry: centred on the facility centre (x=W/2, z=L/2) with symmetric
    // inset so edges sit clear of the cover.
    var SHADE_Y         = eaveH * 0.96;
    var THERMAL_BASE_Y  = eaveH * 0.88;
    var THERMAL_GAP     = 0.10;

    var sh = env.curtain && env.curtain.shade;
    var tc = env.curtain && env.curtain.thermal_ceiling;
    var tcLayers = (tc && tc.enabled) ? Math.max(parseInt(tc.layers, 10) || 1, 1) : 0;

    // Ceiling shade / thermal curtains span the FULL facility footprint
    // (per user requirement "must match the facility width"). One curtain per bay
    // so connected multi-bay structures can fold each bay independently, but
    // each panel matches its bay's full width — no edge inset.
    var bayCovW = span;
    var dCov    = L;

    if (sh && sh.enabled) {
      for (var b = 0; b < bayCount; b++) {
        var bx = _r(b * (span + effSp) + span / 2);
        items.push({
          id:        'env_curtain_shade_b' + b,
          kind:      'shade_curtain',
          label:     (window._ ? window._('Shade curtain') : 'Shade curtain') + (bayCount > 1 ? ' #' + (b + 1) : ''),
          position:  { x: bx, y: _r(SHADE_Y), z: _r(L / 2) },
          size:      { w: _r(bayCovW), h: 0.04, d: _r(dCov) },
          surface_normal: null,
          link_group: 'env_curtain_shade'
        });
      }
    }
    for (var lc = 0; lc < tcLayers; lc++) {
      for (var b = 0; b < bayCount; b++) {
        var bx = _r(b * (span + effSp) + span / 2);
        items.push({
          id:        'env_curtain_thermal_ceil_L' + lc + '_b' + b,
          kind:      'curtain',
          label:     _EL('env_ceiling_thermal', 'Ceiling thermal curtain') + (tcLayers > 1 ? ' L' + (lc + 1) : '') + (bayCount > 1 ? ' #' + (b + 1) : ''),
          position:  { x: bx, y: _r(THERMAL_BASE_Y - lc * THERMAL_GAP), z: _r(L / 2) },
          size:      { w: _r(bayCovW), h: 0.04, d: _r(dCov) },
          surface_normal: null,
          link_group: 'env_curtain_thermal_ceil_L' + lc
        });
      }
    }

    // ── Wall reinforcement (side reinforcement) — env.layers[type=side_only] ──
    // Each side_only/reinforcement layer renders as a panel per checked side.
    // The panel protrudes OUTWARD from the outer wall — thickness_m (width) is
    // the protrusion length measured from the wall surface, NOT the in-plane
    // height/width. To achieve this with the fitting renderer (BoxGeometry
    // centred at position, local +Z = surface_normal), we offset the box
    // CENTRE outward by thickness_m/2 so the inner face sits flush with the
    // outer cover and the outer face is at distance thickness_m from the wall.
    // _reinLayers was pre-computed earlier (alongside side-vent overlay logic).
    // Model uses pure XYZ axis labels. Compass concepts apply only at placement.
    var AXIS_NORMALS = {
      x_neg: [-1, 0, 0], x_pos: [ 1, 0, 0],
      y_pos: [ 0, 0, 1], y_neg: [ 0, 0,-1]
    };
    var AXIS_LBL = { x_neg: 'X−', x_pos: 'X+', y_pos: 'Y+', y_neg: 'Y−' };
    function _toAxisSide(s) {
      if (s === 'south') return 'y_pos';
      if (s === 'north') return 'y_neg';
      if (s === 'east')  return 'x_pos';
      if (s === 'west')  return 'x_neg';
      return s;
    }

    _reinLayers.forEach(function (layer, li) {
      var sides = (Array.isArray(layer.sides) && layer.sides.length > 0)
        ? layer.sides : [];
      var th = parseFloat(layer.thickness_m);
      if (!isFinite(th) || th <= 0) th = 1.0;
      // Stack multiple reinforcement layers outward (each li step adds 1 cm gap)
      var stackGap = li * 0.01;
      var halfTh   = th / 2;
      var centreOffset = halfTh + stackGap;

      sides.forEach(function (sdRaw) {
        var sd = _toAxisSide(sdRaw);
        var sn = AXIS_NORMALS[sd];
        if (!sn) return;
        // Group by AXIS, not by side: the two side walls (x_neg/x_pos) are one
        // mirrored panel and so are the two gable ends (y_pos/y_neg) — but a
        // side wall and a gable end are not, their sizes come from different
        // dimensions (L×eaveH vs unitWidth×apexH). Merging all four would make
        // an edit on one wall resize a panel it has nothing to do with.
        var axisGroup = 'env_reinforcement_' + layer.id + '_' +
                        (sd === 'x_neg' || sd === 'x_pos' ? 'x' : 'y');
        // Connected: one shared facility — reinforcement spans the whole envelope.
        // Single+N: each unit gets its own reinforcement panel on its own wall.
        UNITS.forEach(function (u) {
          var item;
          if (sd === 'x_neg') {
            item = {
              id:        'env_reinforcement_' + layer.id + '_u' + u.index + '_' + sd,
              kind:      'reinforcement',
              label:     (window._ ? window._('Side reinforcement') : 'Side reinforcement') + _unitLabel(u.index) + ' ' + AXIS_LBL[sd],
              position:  { x: _r(u.leftX - centreOffset), y: _r(eaveH / 2), z: _r(L / 2) },
              size:      { w: _r(L * 0.97), h: _r(eaveH), d: _r(th) },
              surface_normal: sn,
              link_group: axisGroup
            };
          } else if (sd === 'x_pos') {
            item = {
              id:        'env_reinforcement_' + layer.id + '_u' + u.index + '_' + sd,
              kind:      'reinforcement',
              label:     (window._ ? window._('Side reinforcement') : 'Side reinforcement') + _unitLabel(u.index) + ' ' + AXIS_LBL[sd],
              position:  { x: _r(u.rightX + centreOffset), y: _r(eaveH / 2), z: _r(L / 2) },
              size:      { w: _r(L * 0.97), h: _r(eaveH), d: _r(th) },
              surface_normal: sn,
              link_group: axisGroup
            };
          } else {
            // Gable end wall (y_pos/y_neg) — per-unit width = unitWidth.
            // y_pos outside at z=L+centreOffset, y_neg at -centreOffset.
            var zCenter = (sd === 'y_pos')
              ? (_r(L) + centreOffset)
              : (-centreOffset);
            var apexH = Math.max(roofApexY, eaveH);
            item = {
              id:        'env_reinforcement_' + layer.id + '_u' + u.index + '_' + sd,
              kind:      'reinforcement',
              label:     (window._ ? window._('Side reinforcement') : 'Side reinforcement') + _unitLabel(u.index) + ' ' + AXIS_LBL[sd],
              position:  { x: _r(u.centerX), y: _r(apexH / 2), z: _r(zCenter) },
              size:      { w: _r(unitWidth * 0.97), h: _r(apexH), d: _r(th) },
              surface_normal: sn,
              link_group: axisGroup
            };
          }
          items.push(item);
        });
      });
    });

    // ── Front reinforcement (front reinforcement) — env.layers[type=front_only] ──
    // Each front_only layer adds an extension space matching the facility
    // cross-section on the south and/or north gable end. Rendered in the 3D
    // scene as an extruded shape (handled in aot-facility-3d.js buildScene).
    // Here we emit label-only fitting items so the right-side panel lists them.
    var _frontLayers = (Array.isArray(env.layers) ? env.layers : [])
      .filter(function (l) { return l && l.type === 'front_only'; });

    var FRONT_LBL = { y_pos: 'Y+', y_neg: 'Y−' };
    _frontLayers.forEach(function (layer) {
      var sides = (Array.isArray(layer.sides) && layer.sides.length > 0)
        ? layer.sides : [];
      var depth = parseFloat(layer.depth_m);
      if (!isFinite(depth) || depth <= 0) depth = 3.0;
      var apexH = Math.max(roofApexY, eaveH);
      sides.forEach(function (sdRaw) {
        var sd = _toAxisSide(sdRaw);
        if (sd !== 'y_pos' && sd !== 'y_neg') return;
        // y_pos center at z=L+depth/2, y_neg at -depth/2.
        var zCenter = (sd === 'y_pos') ? _r(L + depth / 2) : _r(-depth / 2);
        UNITS.forEach(function (u) {
          items.push({
            id:        'env_front_reinf_' + layer.id + '_u' + u.index + '_' + sd,
            kind:      'front_reinforcement',
            label:     (window._ ? window._('Front reinforcement') : 'Front reinforcement') + _unitLabel(u.index) + ' ' + FRONT_LBL[sd],
            position:  { x: _r(u.centerX), y: _r(apexH / 2), z: zCenter },
            size:      { w: _r(unitWidth), h: _r(apexH), d: _r(depth) },
            // Outward normal of y_pos face = +Z; y_neg = -Z.
            surface_normal: (sd === 'y_pos') ? [0, 0, 1] : [0, 0, -1],
            // Both gable ends carry the same extension (unitWidth × apexH ×
            // depth) mirrored front to back — one group, so an edit on one end
            // reaches the other. Each keeps its own z and outward normal.
            link_group: 'env_front_reinf_' + layer.id
          });
        });
      });
    });

    // ── Wall thermal curtain: INSIDE the wall, inset 0.1 m ──────────────────
    // Per user requirement, the wall curtain hangs INSIDE the facility and is
    // separated from the outer cover by a 0.1 m air gap so it never coincides
    // with the (outward-protruding) side vent. The box centre is therefore
    // shifted INWARD by (TW_INSET + TW_DEPTH/2) along the wall normal.
    var TW_INSET = 0.1;
    var TW_DEPTH = 0.04;
    var tw = env.curtain && env.curtain.thermal_wall;
    if (tw && tw.enabled) {
      var nStagesTW = (sv && Array.isArray(sv.stages) && sv.stages.length > 0)
        ? sv.stages.length : 1;
      var twStages = _equalStages(nStagesTW, 0.05);
      twStages.forEach(function (st, i) {
        UNITS.forEach(function (u) {
          var WALLS_TW = [
            { id: 'left',  baseX: u.leftX,  sn: [-1, 0, 0], lbl: _EL('env_side_left', 'Left side'), inwardSign: +1 },
            { id: 'right', baseX: u.rightX, sn: [ 1, 0, 0], lbl: _EL('env_side_right', 'Right side'), inwardSign: -1 }
          ];
          WALLS_TW.forEach(function (w) {
            var twX = w.baseX + w.inwardSign * (TW_INSET + TW_DEPTH / 2);
            items.push({
              id:        'env_curtain_thermal_wall_u' + u.index + '_' + w.id + '_' + st.id,
              kind:      'curtain',
              label:     (_EL('env_wall_thermal', 'Wall thermal curtain') + _unitLabel(u.index) + ' ' + w.lbl + ' ' + _stageLbl(st.id, i)).trim(),
              position:  { x: _r(twX), y: _r(st.y), z: _r(L / 2) },
              size:      { w: _r(L * 0.97), h: _r(st.h), d: TW_DEPTH },
              surface_normal: w.sn,
              // Mirror pair, same as the side window it hangs behind — one
              // group for both walls (see env_side_vent_outer_).
              link_group: 'env_curtain_thermal_wall_' + st.id
            });
          });
        });
      });
    }

    FittingsUI.syncEnvelopeItems(items);
  }

  // ── Resize handle drag ────────────────────────────────────────────────────────
  function initResizeHandle() {
    var panel  = document.getElementById('facility-3d-panel');
    var handle = document.getElementById('facility-3d-resize-handle');
    if (!panel || !handle) return;

    var startY, startH;

    function startResize(clientY) {
      startH = panel.getBoundingClientRect().height;
      startY = clientY;

      function onMove(e) {
        var y = e.touches ? e.touches[0].clientY : e.clientY;
        panel.style.height = Math.max(180, startH + (y - startY)) + 'px';
      }
      function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.removeEventListener('touchmove', onMove);
        document.removeEventListener('touchend', onUp);
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      document.addEventListener('touchmove', onMove, { passive: true });
      document.addEventListener('touchend', onUp);
    }

    handle.addEventListener('mousedown', function (e) {
      e.preventDefault();
      startResize(e.clientY);
    });
    handle.addEventListener('touchstart', function (e) {
      startResize(e.touches[0].clientY);
    }, { passive: true });
  }

  // ── Wire up form inputs for auto-refresh ─────────────────────────────────────
  function wireInputs() {
    var ids = [
      'span-width', 'eave-height', 'ridge-height', 'length-m',
      'spacing-m', 'bay-count', 'roof-type',
      'orientation-input', 'orientation-slider',
    ];
    // Facility-dimension fields that affect envelope-fitting geometry
    // (sizes/positions are derived from span/length/eaveH/ridgeH/bay/spacing,
    // and roof-type changes the apex Y for roof vents — arch vs gable vs flat).
    var DIM_IDS = ['span-width', 'eave-height', 'ridge-height', 'length-m',
                   'spacing-m', 'bay-count', 'roof-type'];
    ids.forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('input', scheduleRebuild);
      if (DIM_IDS.indexOf(id) >= 0) {
        // Recompute envelope fitting geometry on dimension change so size/pos
        // tracks the facility shape (incremental update via aot-fitting-*).
        el.addEventListener('input', _renderEnvelopeFittings);
      }
    });
    // Structure (single/connected) radio change reshapes the floorplan → also
    // re-derive envelope fittings.
    document.querySelectorAll('input[name="structure"]').forEach(function (r) {
      r.addEventListener('change', _renderEnvelopeFittings);
    });
    // EnvelopeUI / ActuatorUI cause full geometry/material rebuilds.
    // FittingsUI uses incremental add/remove (see fitting-added/removed below)
    // instead of full rebuild. Triggering scheduleRebuild on every fitting
    // placement was disposing and recreating the WebGL context, which sometimes
    // left the canvas blank and risked the browser's WebGL context limit.
    // envelope-data-changed (vent stage count/heights) does NOT affect 3D geometry
    // and must NOT trigger a rebuild — only compute runs for that event.
    document.addEventListener('envelope-changed',      scheduleRebuild);
    document.addEventListener('envelope-changed',      _renderEnvelopeFittings);
    // envelope-data-changed: vent stage heights changed — update fitting geometry
    // without a full scene rebuild (no structural change, just size update).
    document.addEventListener('envelope-data-changed', _renderEnvelopeFittings);
    document.addEventListener('actuator-changed',      scheduleRebuild);
    // ORDER MATTERS: _renderEnvelopeFittings must run BEFORE rebuildFit so
    // that the initial scene is built WITH envelope fittings present.
    // Otherwise rebuildFit builds the scene first (no env items in
    // facility.fittings yet), the hardcoded fallback renders the curtain as a
    // thin sliver, _renderEnvelopeFittings then adds the env box on top, and
    // the orphan fallback mesh persists in the scene even after the user
    // toggles the envelope feature off.
    document.addEventListener('facility-loaded',       _renderEnvelopeFittings);
    document.addEventListener('facility-loaded',       rebuildFit);
    // A freshly loaded facility has no relationship to whatever was on the
    // undo stack a moment ago — drop it rather than let Ctrl+Z reach back
    // into a different facility's edits.
    document.addEventListener('facility-loaded', function () {
      _historyStack = [];
      _syncUndoButton();
    });

    document.addEventListener('fitting-added', function (e) {
      if (_ctx && typeof _ctx.addFittingMesh === 'function' && e.detail && e.detail.fitting) {
        var f = e.detail.fitting;
        _ctx.addFittingMesh(f);
        var selId = window.FittingsUI ? FittingsUI.getSelectedId() : null;
        if (typeof _ctx.updateFittingSelection === 'function' && window.FittingsUI) {
          _ctx.updateFittingSelection(selId);
        }
        // Arrows up immediately on placement, for anything the user may move —
        // but only when the fitting that just arrived is the one the user
        // actually selected (add/addAt select before dispatching this event).
        // syncEnvelopeItems() also fires fitting-added, every time an envelope
        // item's id is regenerated (e.g. a cover-dimension tweak), without
        // touching the selection — without this check the arrows would jump
        // to that unrelated item instead of staying on what the user picked.
        if (typeof _ctx.showGizmo === 'function' && f.id === selId && _isMovableFitting(f)) {
          _ctx.showGizmo(f.id, f.position);
        }
      }
    });
    document.addEventListener('fitting-removed', function (e) {
      if (_ctx && typeof _ctx.removeFittingMesh === 'function' && e.detail && e.detail.id) {
        _ctx.removeFittingMesh(e.detail.id);
      }
    });

    // Selection is a visual-only change → update materials in place, NO rebuild.
    document.addEventListener('fitting-selection-changed', function (e) {
      var selId = e.detail && e.detail.id;
      if (_ctx && typeof _ctx.updateFittingSelection === 'function') {
        _ctx.updateFittingSelection(selId);
      }
      // Arrows follow the selection, for anything the user may move.
      if (_ctx && typeof _ctx.showGizmo === 'function') {
        var f = _findFitting(selId);
        if (_isMovableFitting(f)) _ctx.showGizmo(selId, f.position);
        else _ctx.hideGizmo();
      }
    });

    // Gizmo drag → update fitting position + reflect inspector coordinates in real time
    document.addEventListener('aot-gizmo-moved', function (e) {
      var d = e.detail; if (!d || !d.id || !d.position) return;
      var p = d.position;
      // First move of a drag: snapshot the position it started from, so
      // aot-fitting-drag-end can record an undo step. Must run before the
      // update below overwrites it.
      if (_dragTrackingId !== d.id) {
        var before = _findFitting(d.id);
        _dragFromPos = (before && before.position)
          ? { x: before.position.x, y: before.position.y, z: before.position.z } : null;
        _dragTrackingId = d.id;
      }
      // Reflect internal _fittings data immediately (readAll() is a deep copy, so update directly)
      if (window.FittingsUI && typeof FittingsUI.updateFittingPosition === 'function') {
        FittingsUI.updateFittingPosition(d.id, p);
      }
      // Update inspector coordinate fields in real time
      var fx = document.getElementById('fi-x');
      var fy = document.getElementById('fi-y');
      var fz = document.getElementById('fi-z');
      if (fx) fx.value = p.x.toFixed(3);
      if (fy) fy.value = p.z.toFixed(3); // user Y = depth = Three.js Z
      if (fz) fz.value = p.y.toFixed(3); // user Z = height = Three.js Y
      // Reflect 3D mesh position immediately too
      if (_ctx && typeof _ctx.updateFittingTransform === 'function') {
        _ctx.updateFittingTransform(d.id, p, null);
      }
      // No fittings-data-changed here: it redraws the component table, and a
      // drag fires this handler on every mouse move. Everything a move touches
      // is updated above; the broadcast waits for the end of the drag.
    });

    document.addEventListener('aot-fitting-drag-end', function (e) {
      var id = e.detail && e.detail.id;
      if (id && _dragTrackingId === id && _dragFromPos) {
        var f = _findFitting(id);
        var to = f && f.position;
        if (to) {
          var moved = Math.abs(to.x - _dragFromPos.x) > 1e-6 ||
                      Math.abs(to.y - _dragFromPos.y) > 1e-6 ||
                      Math.abs(to.z - _dragFromPos.z) > 1e-6;
          if (moved) {
            _pushHistory({ type: 'move', id: id, from: _dragFromPos,
                           to: { x: to.x, y: to.y, z: to.z } });
          }
        }
      }
      _dragTrackingId = null;
      _dragFromPos = null;
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
    });

    var undoBtn = document.getElementById('btn-3d-undo');
    if (undoBtn) undoBtn.addEventListener('click', undoLastMove);
    _syncUndoButton();
    document.addEventListener('keydown', function (e) {
      if (!e.ctrlKey && !e.metaKey) return;
      if (e.key !== 'z' && e.key !== 'Z') return;
      // Don't hijack undo while the user is editing a text field.
      var tag = (document.activeElement && document.activeElement.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      e.preventDefault();
      undoLastMove();
    });

    // "Back to automatic" — hand the item back to the envelope generator and
    // recompute, so it snaps to wherever the current cover settings put it.
    var autoBtn = document.getElementById('fi-auto-restore');
    if (autoBtn) {
      autoBtn.addEventListener('click', function () {
        if (!window.FittingsUI || !FittingsUI.setAutoGeom) return;
        var id = FittingsUI.getSelectedId && FittingsUI.getSelectedId();
        if (!id || !FittingsUI.setAutoGeom(id, true)) return;
        _renderEnvelopeFittings();
        document.dispatchEvent(new CustomEvent('fittings-data-changed'));
      });
    }

    // Inspector edits — in-place updates, no scene rebuild.
    document.addEventListener('aot-fitting-transform', function (e) {
      var d = e.detail; if (!d) return;
      if (_ctx && typeof _ctx.updateFittingTransform === 'function') {
        _ctx.updateFittingTransform(d.id, d.position, d.rotation_deg);
      }
    });
    document.addEventListener('aot-fitting-geometry', function (e) {
      var d = e.detail; if (!d) return;
      if (_ctx && typeof _ctx.updateFittingGeometry === 'function') {
        _ctx.updateFittingGeometry(d.id, d.size);
      }
    });
    // Data-only change (name, etc.) — no 3D effect, no rebuild
    document.addEventListener('fittings-data-changed', function () { /* compute happens via fittings-changed only */ });
    // Toggles still on the main form (roof-vent, shade managed outside EnvelopeUI _notify)
    var _outerRoofVentEl = document.getElementById('outer-roof-vent');
    if (_outerRoofVentEl) _outerRoofVentEl.addEventListener('change', scheduleRebuild);
    // curtain-shade: add _renderEnvelopeFittings directly so toggle reliably
    // adds/removes the shade fitting even when the onchange→_notify()→
    // envelope-changed chain is interrupted (e.g. EnvelopeUI not yet ready).
    var _curtainShadeEl = document.getElementById('curtain-shade');
    if (_curtainShadeEl) {
      _curtainShadeEl.addEventListener('change', _renderEnvelopeFittings);
      _curtainShadeEl.addEventListener('change', scheduleRebuild);
    }
    document.querySelectorAll('input[name="structure"]').forEach(function (r) {
      r.addEventListener('change', scheduleRebuild);
    });

    // ── Show spacing field only for Single (replicated) structure ───────────
    // Connected bays share walls so spacing is meaningless. For Single mode
    // each "bay" is a separate house and the spacing field defines the gap
    // between them. This handler matches the visibility behaviour the user
    // expects from prior versions of the form.
    function _syncSpacingVisibility() {
      var struct = (document.querySelector('input[name="structure"]:checked') || {}).value || 'single';
      var box = document.getElementById('spacing-container');
      if (!box) return;
      box.classList.toggle('d-none', struct !== 'single');
    }
    document.querySelectorAll('input[name="structure"]').forEach(function (r) {
      r.addEventListener('change', _syncSpacingVisibility);
    });
    _syncSpacingVisibility();
    // Re-apply after facility-loaded fills in the saved structure value
    document.addEventListener('facility-loaded', _syncSpacingVisibility);

    var btn = document.getElementById('btn-3d-refresh');
    if (btn) btn.addEventListener('click', rebuild);

    var fastBtn = document.getElementById('btn-fast-mode');
    if (fastBtn) {
      fastBtn.addEventListener('click', function () {
        if (!_ctx || typeof _ctx.setFastMode !== 'function') return;
        var nowFast = _ctx.getFastMode();
        _ctx.setFastMode(!nowFast);
        fastBtn.textContent = nowFast ? (window._ ? window._('High Quality') : 'High Quality') : (window._ ? window._('Fast Preview') : 'Fast Preview');
        fastBtn.classList.toggle('ctrl-active', !nowFast);
      });
    }

    // Bottom save button mirrors top button
    var saveBottom = document.getElementById('btn-save-facility-bottom');
    var saveTop    = document.getElementById('btn-save-facility');
    if (saveBottom && saveTop) {
      saveBottom.addEventListener('click', function () { saveTop.click(); });
    }
  }

  // ── Asset library integration ─────────────────────────────────────────────────
  var _attachedAsset = null;  // { unique_id, name, source_file }

  function _syncAssetUI() {
    var badge   = document.getElementById('facility-3d-asset-badge');
    var detach  = document.getElementById('btn-3d-asset-detach');
    if (_attachedAsset) {
      badge.textContent = '📦 ' + _attachedAsset.name;
      badge.style.display = '';
      detach.style.display = '';
    } else {
      badge.style.display = 'none';
      detach.style.display = 'none';
    }
  }

  window.facilityOpenAssetLib = function () {
    if (!window.AoTAssetLibrary) return;
    AoTAssetLibrary.openModal(function (asset) {
      _attachedAsset = asset;
      _syncAssetUI();
      // Rebuild 3D with asset render mode
      var fac = _formFacility();
      fac.render_mode = 'asset';
      fac.model_asset_uuid = asset.unique_id;
      fac._asset_source_file = asset.source_file;
      var canvas = document.getElementById('facility-3d-canvas');
      if (!canvas || !window.AoTFacility3D) return;
      if (_ctx) { _ctx.dispose(); _ctx = null; }
      _ctx = window.AoTFacility3D.buildScene(canvas, fac, null);
      _installFittingProbe();
    });
  };

  window.facilityDetachAsset = function () {
    _attachedAsset = null;
    _syncAssetUI();
    rebuild();  // back to parametric
  };

  // ── Export / Import ──────────────────────────────────────────────────────────

  window.facilityExportPNG = function () {
    if (!_ctx || !_ctx.renderer || !_ctx.scene || !_ctx.camera) {
      alert(window._ ? window._('3D preview is not ready.') : '3D preview is not ready.');
      return;
    }
    // Render one fresh frame then capture (avoids preserveDrawingBuffer overhead)
    _ctx.renderer.render(_ctx.scene, _ctx.camera);
    var url = _ctx.renderer.domElement.toDataURL('image/png');
    var a = document.createElement('a');
    a.href = url;
    a.download = (_formFacility().name || 'facility') + '_3d.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  window.facilityExportSpec = function () {
    var spec = _formFacility();
    var blob = new Blob([JSON.stringify(spec, null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (spec.name || 'facility') + '_spec.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  };

  window.facilityExportGLB = function () {
    if (!_ctx || !_ctx.scene) {
      alert(window._ ? window._('3D preview is not ready.') : '3D preview is not ready.');
      return;
    }
    var scene = _ctx.scene;
    var name = _formFacility().name || 'facility';
    var btn = document.getElementById('btn-3d-export-glb');
    if (btn) { btn.disabled = true; btn.textContent = (window._ ? window._('Exporting…') : 'Exporting…'); }
    // 로컬 자립 빌드. CDN 직행은 bare specifier 'three' 를 풀지 못해
    // 이 버튼이 줄곧 깨져 있었다 — three-gltf-exporter.js 헤더 참조.
    import('/static/js/widgets/AoT_facility/three-gltf-exporter.js?v=' + (window.AOT_ASSET_V || ''))
      .then(function (module) {
        var exporter = new module.GLTFExporter();
        exporter.parse(
          scene,
          function (result) {
            var blob = new Blob([result], { type: 'application/octet-stream' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = name + '.glb';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
          },
          function (err) {
            alert((window._ ? window._('GLB export failed: ') : 'GLB export failed: ') + err);
          },
          { binary: true }
        );
      })
      .catch(function (err) {
        alert((window._ ? window._('Failed to load GLTFExporter: ') : 'Failed to load GLTFExporter: ') + err);
      })
      .finally(function () {
        if (btn) { btn.disabled = false; btn.textContent = '📤 GLB'; }
      });
  };

  window.facilityDelete = function (uuid, name) {
    var msg =
      (window._ ? window._('Delete facility "%(name)s"?') : 'Delete facility "%(name)s"?').replace('%(name)s', name) + '\n\n' +
      (window._ ? window._('Deleting removes all facility data and linked geometry information, and cannot be undone.') : 'Deleting removes all facility data and linked geometry information, and cannot be undone.');

    function _doDelete() {
      fetch('/api/geo/facility/' + uuid, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm_name: name })
      })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) {
          var item = document.querySelector('.facility-list-item[data-uuid="' + uuid + '"]');
          if (item) item.remove();
          var list = document.getElementById('facility-list');
          if (list && !list.querySelector('.facility-list-item')) {
            var _noFac = (window._IEC && _IEC.no_facilities) || 'No facilities yet.';
            list.innerHTML = '<div class="text-muted small p-2">' + _noFac + '</div>';
          }
          // Deleting the facility that is open used to navigate to a bare
          // /geo/facility, which closed the drawer. A blank form in place is the
          // same destination without losing the workspace.
          var pageVars = JSON.parse(document.getElementById('facility-page-vars').textContent || '{}');
          if (pageVars.facility_uuid === uuid && window.FacilityIO) FacilityIO.create();
        } else {
          alert((window._ ? window._('Delete failed: ') : 'Delete failed: ') + (d.message || (window._ ? window._('Unknown error') : 'Unknown error')));
        }
      })
      .catch(function (err) {
        alert((window._ ? window._('An error occurred while deleting: ') : 'An error occurred while deleting: ') + err);
      });
    }

    // Shared confirm modal (layout_default.html) — styled like the rest of the
    // app and callback-based, unlike the blocking native dialog.
    if (typeof window.aotConfirm === 'function') window.aotConfirm(msg, _doDelete);
    else if (window.confirm(msg)) _doDelete();
  };

  window.facilityImportSpec = function (file) {
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function (e) {
      try {
        var spec = JSON.parse(e.target.result);
        var setVal = function (id, v) {
          var el = document.getElementById(id);
          if (el && v != null) el.value = v;
        };
        var setChk = function (id, v) {
          var el = document.getElementById(id);
          if (el && v != null) el.checked = !!v;
        };
        setVal('facility-name',   spec.name);
        setVal('facility-preset', spec.preset);
        setVal('bay-count',       spec.bay_count);
        var g = spec.geometry_3d || {};
        setVal('span-width',   g.span_width_m);
        setVal('eave-height',  g.eave_height_m);
        setVal('ridge-height', g.ridge_height_m);
        setVal('length-m',     g.length_m);
        setVal('spacing-m',    g.spacing_m);
        setVal('roof-type',    g.roof_type);
        if (g.orientation_deg != null) {
          setVal('orientation-input',  g.orientation_deg);
          setVal('orientation-slider', g.orientation_deg);
        }
        if (spec.structure) {
          var r = document.querySelector('input[name="structure"][value="' + spec.structure + '"]');
          if (r) r.checked = true;
        }
        if (window.EnvelopeUI) EnvelopeUI.fill(spec.envelope || {});
        if (window.ActuatorUI) ActuatorUI.fill(spec.actuators || []);
        if (window.FittingsUI) FittingsUI.fill(spec.fittings  || []);
        rebuild();
      } catch (err) {
        alert((window._ ? window._('Spec JSON parse error: ') : 'Spec JSON parse error: ') + err);
      }
    };
    reader.readAsText(file);
  };

  window.facilityImportGLTF = function (file) {
    if (!file) return;
    if (!window.THREE || !THREE.GLTFLoader) {
      alert(window._ ? window._('THREE.GLTFLoader is not available.') : 'THREE.GLTFLoader is not available.');
      return;
    }
    var blobUrl = URL.createObjectURL(file);
    var canvas = document.getElementById('facility-3d-canvas');
    if (!canvas) return;
    if (_ctx) { _ctx.dispose(); _ctx = null; }

    var parent = canvas.parentElement;
    var W = (parent && parent.clientWidth) || 400;
    var H = (parent && parent.clientHeight) || 340;
    var statusEl = parent && parent.querySelector('.aot-3d-asset-status');

    var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(W, H, false);

    var scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf0f4f8);

    var camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 1500);
    camera.position.set(8, 6, 12);
    camera.lookAt(0, 1, 0);

    var controls = new THREE.MapControls(camera, renderer.domElement);
    controls.target.set(0, 1, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controls.update();

    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    var sun = new THREE.DirectionalLight(0xfff4d6, 0.85);
    sun.position.set(10, 20, 10);
    scene.add(sun);
    var ground = new THREE.Mesh(
      new THREE.PlaneGeometry(100, 100),
      new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.9 })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.01;
    scene.add(ground);
    scene.add(new THREE.GridHelper(50, 25, 0xbbbbbb, 0xdddddd));

    if (statusEl) statusEl.textContent = (window._ ? window._('Loading model…') : 'Loading model…');

    var loader = new THREE.GLTFLoader();
    loader.load(
      blobUrl,
      function (gltf) {
        var model = gltf.scene;
        scene.add(model);
        var box = new THREE.Box3().setFromObject(model);
        var center = box.getCenter(new THREE.Vector3());
        var size = box.getSize(new THREE.Vector3());
        var maxDim = Math.max(size.x, size.y, size.z) || 5;
        camera.position.set(
          center.x + maxDim * 1.2,
          center.y + maxDim * 0.8,
          center.z + maxDim * 1.5
        );
        camera.lookAt(center);
        controls.target.copy(center);
        controls.update();
        if (statusEl) statusEl.textContent = '';
        URL.revokeObjectURL(blobUrl);
      },
      undefined,
      function (err) {
        if (statusEl) statusEl.textContent = (window._ ? window._('Model load failed') : 'Model load failed');
        console.error('[facilityImportGLTF]', err);
        URL.revokeObjectURL(blobUrl);
      }
    );

    var resizeObs = new ResizeObserver(function () {
      var cw = canvas.parentElement ? canvas.parentElement.clientWidth : canvas.clientWidth;
      var ch = canvas.parentElement ? canvas.parentElement.clientHeight : canvas.clientHeight;
      if (cw > 0 && ch > 0) {
        renderer.setSize(cw, ch, false);
        camera.aspect = cw / ch;
        camera.updateProjectionMatrix();
      }
    });
    if (canvas.parentElement) resizeObs.observe(canvas.parentElement);

    var animId;
    function animate() { animId = requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }
    animate();

    _ctx = {
      renderer: renderer, scene: scene, camera: camera, controls: controls,
      dispose: function () {
        cancelAnimationFrame(animId);
        resizeObs.disconnect();
        controls.dispose();
        renderer.dispose();
      }
    };
  };

  // ── Tool palette wiring ─────────────────────────────────────────────────────
  // Three action types per button (via data-action attribute):
  //   "select"  → Select tool (deactivate face-pick)
  //   "face"    → Face-pick tool (window/door/side_window) — activate _ctx.setTool
  //   "add"     → Immediate add (curtain/fan/heater/sensor/fixture) — FittingsUI.add
  //   "catalog" → Open catalog import modal
  function _setToolBtnActive(toolName) {
    document.querySelectorAll(
      '#facility-3d-tools .tool-btn[data-action="select"],' +
      '#facility-3d-tools .tool-btn[data-action="face"],' +
      '#facility-3d-tools .tool-btn[data-action="place"]'
    ).forEach(function (b) {
      b.classList.toggle('active', (b.dataset.tool || '') === (toolName || ''));
    });
  }

  function _applyFaceTool(toolName) {
    if (_ctx && typeof _ctx.setTool === 'function') {
      _ctx.setTool(toolName || null);
    }
    _vconnectFirst = null;   // cancel the first selection of an in-progress level connection
    _setToolBtnActive(toolName);
  }

  // ── Tool flyouts ────────────────────────────────────────────────────────────
  // The rail stays visible; each group's buttons live in a flyout that is only
  // rendered over the viewport while that group is open.
  function _closeFlyouts() {
    document.querySelectorAll('#facility-3d-tools .fac-flyout.open').forEach(function (p) {
      p.classList.remove('open');
    });
    document.querySelectorAll('#facility-3d-tools .rail-btn.open').forEach(function (b) {
      b.classList.remove('open');
    });
  }

  function _toggleFlyout(name) {
    var panel = document.querySelector('#facility-3d-tools .fac-flyout[data-flyout-panel="' + name + '"]');
    var rail  = document.querySelector('#facility-3d-tools .rail-btn[data-flyout="' + name + '"]');
    var willOpen = !!panel && !panel.classList.contains('open');
    _closeFlyouts();
    if (willOpen) {
      panel.classList.add('open');
      if (rail) rail.classList.add('open');
    }
  }

  // Keep the rail marked for whichever group holds the currently armed tool,
  // so a collapsed flyout still shows where the active tool came from.
  function _syncRailActive() {
    document.querySelectorAll('#facility-3d-tools .rail-btn').forEach(function (rb) {
      var panel = document.querySelector(
        '#facility-3d-tools .fac-flyout[data-flyout-panel="' + (rb.dataset.flyout || '') + '"]'
      );
      var armed = !!(panel && panel.querySelector('.tool-btn.active[data-tool]:not([data-tool=""])'));
      rb.classList.toggle('has-active', armed);
    });
  }

  function wireFlyouts() {
    document.querySelectorAll('#facility-3d-tools .rail-btn').forEach(function (rb) {
      rb.addEventListener('click', function () { _toggleFlyout(rb.dataset.flyout); });
    });
    // Openings/fixtures arm a click-to-place tool, so collapse the flyout to
    // free the viewport. Irrigation keeps its panel open — its forms are inputs
    // the user adjusts between actions.
    document.querySelectorAll('#facility-3d-tools .fac-flyout:not(.fac-flyout-wide) .tool-btn')
      .forEach(function (b) { b.addEventListener('click', _closeFlyouts); });
  }

  // ── Fitting list panel toggle ───────────────────────────────────────────────
  var FITLIST_KEY = 'aot_fac_fitlist_open';

  function _setFitListOpen(open, persist) {
    var panel = document.getElementById('facility-3d-fittings-list');
    var btn   = document.getElementById('btn-3d-fitlist');
    if (panel) panel.classList.toggle('open', !!open);
    if (btn)   btn.classList.toggle('ctrl-active', !!open);
    if (persist) {
      try { localStorage.setItem(FITLIST_KEY, open ? '1' : '0'); } catch (e) { /* storage blocked */ }
    }
  }

  function wireFitListToggle() {
    var btn = document.getElementById('btn-3d-fitlist');
    if (btn) {
      btn.addEventListener('click', function () {
        var panel = document.getElementById('facility-3d-fittings-list');
        _setFitListOpen(!(panel && panel.classList.contains('open')), true);
      });
    }
    var saved = null;
    try { saved = localStorage.getItem(FITLIST_KEY); } catch (e) { /* storage blocked */ }
    _setFitListOpen(saved === '1', false);

    // Mirror the in-panel count onto the toolbar badge so the list stays
    // discoverable while hidden.
    var src = document.getElementById('fit-list-count');
    var dst = document.getElementById('fit-list-count-badge');
    if (src && dst && window.MutationObserver) {
      // Empty means "nothing hidden" — the old '(0)' fallback turned that into
      // a count that read as "zero categories".
      var sync = function () { dst.textContent = src.textContent || ''; };
      sync();
      new MutationObserver(sync).observe(src, { childList: true, characterData: true, subtree: true });
    }
  }

  function wireTools() {
    wireFlyouts();
    wireFitListToggle();
    document.querySelectorAll('#facility-3d-tools .tool-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var action = btn.dataset.action;
        if (action === 'select') {
          _applyFaceTool('');
        } else if (action === 'face' || action === 'place') {
          // face → outer cover only (wall fittings)
          // place → outer cover + floor (device drag-place)
          _applyFaceTool(btn.dataset.tool || '');
        } else if (action === 'add') {
          // Immediate add — deactivate face-pick first so cursor returns to normal
          _applyFaceTool('');
          if (window.FittingsUI) FittingsUI.add(btn.dataset.kind);
        } else if (action === 'catalog') {
          _applyFaceTool('');
          var geoId = (document.getElementById('map-selector') || {}).value || '';
          document.dispatchEvent(new CustomEvent('aot-facility-need-center', {
            detail: { cb: function (center, orient) {
              if (window.FittingsUI) FittingsUI.importFromCatalog(geoId, center, orient || 0);
            }}
          }));
        } else if (action === 'irr-add-layer') {
          _applyFaceTool('');
          if (window.FittingsUI && FittingsUI.addIrrigationLayer) {
            FittingsUI.addIrrigationLayer();
            ['btn-irr-vpipe','btn-irr-main','btn-irr-branch','btn-irr-add-valve'].forEach(function (id) {
              var el = document.getElementById(id);
              if (el) el.disabled = false;
            });
          }
        } else if (action === 'irr-gen-pipe') {
          _applyFaceTool('');
          _autoGenPipes();
        } else if (action === 'irr-clear') {
          _applyFaceTool('');
          var layerToClear = _getActiveLayer();
          if (layerToClear && window.FittingsUI && FittingsUI.readAll) {
            // Remove only branch pipes + sprinklers/drip + joints (main pipes preserved)
            FittingsUI.readAll().filter(function (f) {
              return f.layer_id === layerToClear.id && (
                (f.kind === 'irrigation_pipe' && f.sub_type !== 'main' && !f.is_vertical) ||
                f.kind === 'irrigation_device' ||
                f.kind === 'irrigation_connection'
              );
            }).forEach(function (f) { FittingsUI.remove(f.id); });
          }
        } else if (action === 'irr-clear-sprinkler') {
          _applyFaceTool('');
          var layerSp = _getActiveLayer();
          if (layerSp && window.FittingsUI && FittingsUI.readAll) {
            FittingsUI.readAll().filter(function (f) {
              return f.layer_id === layerSp.id && f.kind === 'irrigation_device';
            }).forEach(function (f) { FittingsUI.remove(f.id); });
          }
        } else if (action === 'irr-add-valve') {
          _applyFaceTool('');
          var layerForValve = _getActiveLayer();
          if (!layerForValve) { alert(window._ ? window._('Select or add an irrigation layer first.') : 'Select or add an irrigation layer first.'); return; }
          if (!window.FittingsUI || !FittingsUI.addIrrigationValve) return;
          var selId = FittingsUI.getSelectedId && FittingsUI.getSelectedId();
          var selFit = selId && FittingsUI.readAll
            ? FittingsUI.readAll().find(function (f) { return f.id === selId; })
            : null;
          var pipeId = (selFit && selFit.kind === 'irrigation_pipe' && selFit.layer_id === layerForValve.id)
            ? selFit.id : null;
          var vType = (document.getElementById('irr-valve-type')    || {}).value || 'on_off';
          var vDef  = (document.getElementById('irr-valve-default') || {}).value || 'closed';
          FittingsUI.addIrrigationValve(layerForValve.id, pipeId, null, {
            valve_type: vType,
            default_state: vDef
          });
        } else if (action === 'irr-delete-mode') {
          _applyFaceTool('');
          _setDeleteMode(!_deleteMode);
        } else if (action === 'irr-gen-irrigation') {
          _applyFaceTool('');
          _autoGenSprinklers();
        } else if (action === 'irr-vpipe' || action === 'irr-pipe') {
          var activeLayerId = (window.FittingsUI && FittingsUI.getActiveLayerId) ? FittingsUI.getActiveLayerId() : null;
          if (!activeLayerId) {
            _applyFaceTool('');
            alert(window._ ? window._('Select or add an irrigation layer first.') : 'Select or add an irrigation layer first.');
            return;
          }
          // Auto-finish in-progress polyline on tool switch (tool-state isolation)
          if (_activeDrawingPipeId && window.FittingsUI && FittingsUI.finishPipe) {
            FittingsUI.finishPipe(_activeDrawingPipeId);
            _activeDrawingPipeId = null;
          }
          var t = btn.dataset.tool || '';
          if (_ctx && typeof _ctx.setTool === 'function') _ctx.setTool(t);
          document.querySelectorAll('#facility-3d-tools .tool-btn').forEach(function (b) {
            b.classList.toggle('active', b === btn);
          });
        } else if (action === 'irr-ortho') {
          // Ortho snap toggle (independent of tool mode — toggles active state only)
          var orthoOn = !btn.classList.contains('active');
          btn.classList.toggle('active', orthoOn);
          if (_ctx && typeof _ctx.setOrthoSnap === 'function') _ctx.setOrthoSnap(orthoOn);
        } else if (action === 'irr-vconnect') {
          // Finish in-progress polyline, then activate the level connection tool
          if (_activeDrawingPipeId && window.FittingsUI && FittingsUI.finishPipe) {
            FittingsUI.finishPipe(_activeDrawingPipeId);
            _activeDrawingPipeId = null;
          }
          _vconnectFirst = null;
          var tv = btn.dataset.tool || '';
          if (_ctx && typeof _ctx.setTool === 'function') _ctx.setTool(tv);
          document.querySelectorAll('#facility-3d-tools .tool-btn').forEach(function (b) {
            b.classList.toggle('active', b === btn);
          });
        }
      });
      // Registered after the action handler so it reads the settled state
      btn.addEventListener('click', _syncRailActive);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        _applyFaceTool('');
        _closeFlyouts();
        _syncRailActive();
      }
    });
  }

  // ── Step navigation ─────────────────────────────────────────────────────────
  // Steps drive two things: which panes show inside the drawer (several
  // sections may share one data-step) and which stage view is behind it.
  // The drawer itself is the shared shell (aot-widget-drawer.js), so it pushes
  // the page aside and leaves the stage clickable.
  // 'plot' 은 connect 와 check 사이다 — 설비를 다 붙인 뒤, 검토 전에 "여기에
  // 무엇이 심겨 있나" 를 적는 자리다. 필수 단계가 아니라 data-issue 가 없다
  // (작물을 적지 않아도 시설은 완성된다).
  var STEPS = ['basic', 'position', 'envelope', 'fittings', 'connect',
               'plot', 'check'];
  var _step = null;

  // Every step can show either view — the model and the map are two ways of
  // looking at the same facility, and which one helps depends on what the user
  // is checking, not on which step they happen to be in.
  //
  // The default is per step: the three steps that describe where and what the
  // building physically is open on the map (it carries the site, the
  // neighbouring facilities and the real orientation), the rest open on the
  // isolated 3D scene. A choice made by hand is remembered for the session, so
  // the default only decides the first visit to each step.
  var _DEFAULT_STAGE = { position: 'map', envelope: 'map', fittings: 'map' };
  var _stagePick     = {};   // step → '3d' | 'map', once the user picks

  function _stageFor(step) {
    return _stagePick[step] || _DEFAULT_STAGE[step] || '3d';
  }

  function _showStage(which) {
    document.querySelectorAll('.fac-stage-view').forEach(function (v) {
      v.classList.toggle('active', v.id === 'fac-stage-' + which);
    });
    // Let the newly visible canvas measure itself. The map needs an explicit
    // resize: it is built while hidden, so its canvas keeps a stale size until
    // told to re-measure (FacilityMapAPI exposes just that from the bundle).
    setTimeout(function () {
      window.dispatchEvent(new Event('resize'));
      if (which === 'map' && window.FacilityMapAPI) {
        FacilityMapAPI.resize();
        // Arriving at the map with the camera parked somewhere else shows bare
        // tiles and reads as a broken preview. Only moves if it is off screen.
        if (FacilityMapAPI.focusFacility) FacilityMapAPI.focusFacility();
      }
      // The 3D viewer renders on demand and its buffer does not survive being
      // hidden — ask for a frame rather than trusting whatever the resize
      // observer happens to see (identical size = no callback = blank panel).
      if (which === '3d' && _ctx && typeof _ctx.requestRender === 'function') {
        _ctx.requestRender();
      }
    }, 30);
  }

  // Sync the 3D/Map picker to the step.
  function _syncStageToggle(step) {
    var box = document.getElementById('fac-stage-toggle');
    if (!box) return;
    box.hidden = false;
    var cur = _stageFor(step);
    box.querySelectorAll('[data-stage]').forEach(function (b) {
      var sel = (b.dataset.stage === cur);
      b.classList.toggle('active', sel);
      b.classList.toggle('aot-pill-btn-primary', sel);
      b.setAttribute('aria-pressed', sel ? 'true' : 'false');
    });
  }

  function wireStageToggle() {
    var box = document.getElementById('fac-stage-toggle');
    if (!box) return;
    box.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-stage]');
      if (!btn || !_step) return;
      _stagePick[_step] = btn.dataset.stage;
      _showStage(_stageFor(_step));
      _syncStageToggle(_step);
    });
  }

  function _stepLabel(step) {
    var btn = document.querySelector('.fac-step[data-step="' + step + '"]');
    return btn ? btn.textContent.trim() : '';
  }

  function setStep(step, opts) {
    if (STEPS.indexOf(step) === -1) return;
    _step = step;
    document.querySelectorAll('.fac-step').forEach(function (b) {
      var on = (b.dataset.step === step);
      b.classList.toggle('active', on);
      // Selected state is the shared button's own variant, not a page-local look.
      b.classList.toggle('aot-pill-btn-primary', on);
    });
    document.querySelectorAll('.fac-step-pane').forEach(function (p) {
      p.classList.toggle('active', p.dataset.step === step);
    });
    var title = document.getElementById('fac-step-title');
    if (title) title.textContent = _stepLabel(step);

    var i = STEPS.indexOf(step);
    var prev = document.getElementById('fac-step-prev');
    var next = document.getElementById('fac-step-next');
    if (prev) prev.disabled = (i <= 0);
    if (next) next.disabled = (i >= STEPS.length - 1);

    if (step === 'check') _refreshCheckLock();
    refreshStepStatus();
    _syncStageToggle(step);
    _showStage(_stageFor(step));

    // Scroll the drawer body back to the top on step change
    var body = document.querySelector('#modal_fac_step .modal-body');
    if (body) body.scrollTop = 0;

    // One signal for every entry point (step bar, Next/Prev, 3D auto-focus)
    document.dispatchEvent(new CustomEvent('fac-step-changed', { detail: { step: step } }));

    if (!opts || opts.open !== false) openStepDrawer();
  }

  function openStepDrawer() {
    if (window.jQuery) jQuery('#modal_fac_step').modal('show');
  }

  var PHONE_MAX = 767.98;
  function _isPhone() { return window.innerWidth <= PHONE_MAX; }

  // On a phone the settings are a bottom sheet under the pinned model band, so
  // the page needs to know whether the sheet is up (band shrinks to make room)
  // or down (model takes the whole screen).
  function _syncSheetState(open) {
    document.body.classList.toggle('fac-sheet-open', !!open);
    if (!open) document.body.classList.remove('fac-band-collapsed');
    setTimeout(function () {
      window.dispatchEvent(new Event('resize'));
      if (window.FacilityMapAPI) FacilityMapAPI.resize();
    }, 60);
  }

  function wireBandToggle() {
    var btn = document.getElementById('fac-band-toggle');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var collapsed = document.body.classList.toggle('fac-band-collapsed');
      btn.textContent = collapsed
        ? (btn.dataset.labelShow || 'Show model')
        : (btn.dataset.labelHide || 'Hide model');
      setTimeout(function () {
        window.dispatchEvent(new Event('resize'));
        if (window.FacilityMapAPI) FacilityMapAPI.resize();
      }, 60);
    });
  }

  // ── Step status ─────────────────────────────────────────────────────────────
  // Flag steps that are still missing something required, rather than claiming
  // "done" — most steps ship usable defaults, so only genuinely empty ones are
  // worth pointing at.
  function _val(id) { var el = document.getElementById(id); return el ? String(el.value || '').trim() : ''; }

  // Only the condition lives here; the wording comes from the button's
  // data-issue attribute so it goes through the server-side catalog.
  function _stepIncomplete(step) {
    // The map/site pickers moved to the position step — choosing where the
    // facility sits belongs with placing it, not with naming it.
    if (step === 'basic')    return !_val('facility-name');
    if (step === 'position') {
      if (!_val('map-selector')) return true;
      return window.FacilityMapAPI ? !FacilityMapAPI.hasCenter() : false;
    }
    if (step === 'fittings') {
      // Envelope-derived items (covers, reinforcements, vents) come along with
      // the envelope settings. This step is about what the user places, which
      // is the same set the list counter shows.
      try {
        var all = (window.FittingsUI && FittingsUI.readAll) ? FittingsUI.readAll() : [];
        return !all.filter(function (f) { return f.source !== 'envelope'; }).length;
      } catch (e) { return false; }
    }
    if (step === 'check') {
      var integ = document.getElementById('integ-panel');
      return !(integ && integ.style.display !== 'none');
    }
    return false;   // envelope / connect ship working defaults
  }

  // The step bar shows which step is open, nothing else — the system marks an
  // active control by filling it and uses no per-item progress markers. What a
  // step still needs is said in its tooltip (and listed in Review).
  function refreshStepStatus() {
    STEPS.forEach(function (s) {
      var btn = document.querySelector('.fac-step[data-step="' + s + '"]');
      if (!btn) return;
      if (_stepIncomplete(s) && btn.dataset.issue) btn.setAttribute('title', btn.dataset.issue);
      else btn.removeAttribute('title');
    });
  }

  // ── Unsaved changes ─────────────────────────────────────────────────────────
  // Saving posts the whole facility at once, so auto-save would commit
  // half-filled forms and rebuild the scene on every keystroke. Instead the page
  // tracks that something changed and says so.
  var _dirty = false;

  function _setDirty(on) {
    if (_dirty === !!on) return;
    _dirty = !!on;
    document.body.classList.toggle('fac-dirty', _dirty);
    var badge = document.getElementById('fac-dirty-badge');
    if (badge) badge.style.display = _dirty ? '' : 'none';
  }

  function wireDirtyTracking() {
    var mark = function () { _setDirty(true); refreshStepStatus(); };
    // Form edits anywhere in the drawer, plus scene edits from the 3D tools
    document.addEventListener('input', function (e) {
      if (e.target && e.target.closest && e.target.closest('#modal_fac_step')) mark();
    });
    document.addEventListener('change', function (e) {
      if (e.target && e.target.closest && e.target.closest('#modal_fac_step')) mark();
    });
    document.addEventListener('fittings-data-changed', mark);
    // Adding or deleting a component changes whether the layout step still has
    // an outstanding requirement, and neither path goes through
    // fittings-data-changed.
    document.addEventListener('fitting-added',   mark);
    document.addEventListener('fitting-removed', mark);
    // Placing or dragging the facility on the map moves it without touching a
    // single form field, so nothing else here would notice the change.
    document.addEventListener('facility-placed', mark);

    document.addEventListener('facility-saved', function () { _setDirty(false); });
    // Loading a facility populates every field — that is not a user edit
    document.addEventListener('facility-loaded', function () {
      setTimeout(function () { _setDirty(false); refreshStepStatus(); }, 50);
    });

    window.addEventListener('beforeunload', function (e) {
      if (!_dirty) return;
      e.preventDefault();
      e.returnValue = '';
      return '';
    });
  }

  // The integration summary and device check need a saved facility; when there
  // is none, show why instead of leaving step 6 looking empty. Those two panels
  // are revealed by the save/load path, so their visibility is the signal.
  function _refreshCheckLock() {
    var integ = document.getElementById('integ-panel');
    var saved = !!(integ && integ.style.display !== 'none');
    var hint  = document.getElementById('check-locked-hint');
    if (hint) hint.style.display = saved ? 'none' : '';
  }

  // Picking a fitting in the 3D scene fills the inspector, which now lives in
  // the drawer's layout step — surface that step so the properties are visible
  // instead of silently updating a hidden pane.
  function wireInspectorFocus() {
    var content = document.getElementById('fi-content');
    if (!content || !window.MutationObserver) return;
    new MutationObserver(function () {
      if (content.style.display === 'none') return;
      if (_step !== 'fittings') setStep('fittings');
      else openStepDrawer();
    }).observe(content, { attributes: true, attributeFilter: ['style'] });
  }


  // ── Segmented toggles ───────────────────────────────────────────────────────
  // The btn-groups on this page are plain Bootstrap markup without
  // data-toggle="buttons", so nothing kept `.active` in sync except one
  // hand-written case — which is why the raw radio dots had to stay visible to
  // show the selection. Sync every group here, then the CSS can hide the input.
  function _syncSegmented(group) {
    group.querySelectorAll('.btn > input[type="radio"], .btn > input[type="checkbox"]').forEach(function (i) {
      if (i.parentElement) i.parentElement.classList.toggle('active', i.checked);
    });
  }

  function wireSegmentedToggles() {
    document.addEventListener('change', function (e) {
      var el = e.target;
      if (!el || !el.matches) return;
      if (!el.matches('.btn-group .btn > input[type="radio"], .btn-group .btn > input[type="checkbox"]')) return;
      _syncSegmented(el.closest('.btn-group'));
    });
    // Initial state, plus anything the scripts render later
    document.querySelectorAll('.btn-group').forEach(_syncSegmented);
    document.addEventListener('fittings-data-changed', function () {
      document.querySelectorAll('.btn-group').forEach(_syncSegmented);
    });
  }

  function wireSteps() {
    wireInspectorFocus();
    wireSegmentedToggles();
    wireBandToggle();
    wireStageToggle();
    wireDirtyTracking();
    refreshStepStatus();
    // Placing/removing things and loading a facility both change step status
    document.addEventListener('fittings-data-changed', refreshStepStatus);
    document.addEventListener('facility-loaded', function () {
      setTimeout(refreshStepStatus, 60);
    });
    document.querySelectorAll('.fac-step').forEach(function (btn) {
      btn.addEventListener('click', function () { setStep(btn.dataset.step); });
    });
    var prev = document.getElementById('fac-step-prev');
    var next = document.getElementById('fac-step-next');
    if (prev) prev.addEventListener('click', function () {
      var i = STEPS.indexOf(_step); if (i > 0) setStep(STEPS[i - 1]);
    });
    if (next) next.addEventListener('click', function () {
      var i = STEPS.indexOf(_step); if (i < STEPS.length - 1) setStep(STEPS[i + 1]);
    });

    // Start on the first step with the drawer closed: the stage is the first
    // thing to look at, and the step bar shows where the settings live. A new
    // facility has nothing to look at yet, so open the drawer for it. On a
    // phone the sheet is the primary surface, so start with it up either way.
    var isNew = true;
    try {
      var pv = JSON.parse((document.getElementById('facility-page-vars') || {}).textContent || '{}');
      isNew = !pv.facility_uuid;
    } catch (e) { /* keep the onboarding default */ }
    setStep('basic', { open: false });
    if (isNew || _isPhone()) openStepDrawer();

    // Keep the stage sized when the drawer slides in/out (it pushes the page on
    // desktop, and resizes the band on a phone).
    if (window.jQuery) {
      jQuery('#modal_fac_step')
        .on('shown.bs.modal', function () {
          _syncSheetState(true);
          setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 480);
        })
        .on('hidden.bs.modal', function () {
          _syncSheetState(false);
          setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 480);
        });
    }
  }

  // Selecting something in the 3D scene belongs to the layout step — bring the
  // user there rather than leaving the inspector under an unrelated step.
  window.FacilityStep = {
    set: setStep,
    current: function () { return _step; },
    refreshCheckLock: _refreshCheckLock
  };

  // ── Irrigation pipe event handlers ────────────────────────────────────────
  var _activeDrawingPipeId = null;
  var _vconnectFirst = null;   // Level connection: the first-clicked pipe { pipe_id, pt }
  var _deleteMode = false;

  function _setDeleteMode(on) {
    _deleteMode = !!on;
    var btn  = document.getElementById('btn-irr-delete-mode');
    var hint = document.getElementById('irr-delete-mode-hint');
    if (btn)  btn.classList.toggle('active', _deleteMode);
    if (hint) hint.style.display = _deleteMode ? '' : 'none';
    if (_ctx && _ctx.renderer && _ctx.renderer.domElement) {
      _ctx.renderer.domElement.style.cursor = _deleteMode ? 'crosshair' : '';
    }
  }

  function _refreshIrrButtons() {
    var all = (window.FittingsUI && FittingsUI.readAll) ? FittingsUI.readAll() : [];
    var hasLayer = all.some(function (f) { return f.kind === 'irrigation_layer'; });
    var activeLayerId = (window.FittingsUI && FittingsUI.getActiveLayerId) ? FittingsUI.getActiveLayerId() : null;
    var enable = hasLayer && !!activeLayerId;
    ['btn-irr-vpipe','btn-irr-main','btn-irr-branch','btn-gen-pipe','btn-clear-irr',
     'btn-gen-irrigation','btn-clear-sprinkler','btn-irr-delete-mode','btn-irr-add-valve'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.disabled = !enable;
    });
    // Level connection: enabled only when there are 2+ horizontal pipes (layer-agnostic)
    var horizPipes = all.filter(function (f) { return f.kind === 'irrigation_pipe' && !f.is_vertical; }).length;
    var vcBtn = document.getElementById('btn-irr-vconnect');
    if (vcBtn) vcBtn.disabled = horizPipes < 2;
    // If the active layer disappears, delete mode is auto-released
    if (!enable && _deleteMode) _setDeleteMode(false);
    _renderIrrStats();
  }

  // ── Read facility local coordinate-system dimensions ──────────────────────
  function _getFacilityDims() {
    var span     = parseFloat(document.getElementById('span-width')  ? document.getElementById('span-width').value  : '') || 7;
    var bayCount = Math.max(parseInt( document.getElementById('bay-count')   ? document.getElementById('bay-count').value   : '1', 10) || 1, 1);
    var spacingM = parseFloat(document.getElementById('spacing-m')   ? document.getElementById('spacing-m').value   : '') || 1;
    var length   = parseFloat(document.getElementById('length-m')    ? document.getElementById('length-m').value    : '') || 30;
    // Facility structure is a radio (name="structure") — uses the same selector as `_facilityDims()`
    var structure = ((document.querySelector('input[name="structure"]:checked') || {}).value) || 'single';
    var isConnected = (structure === 'connected');
    var unitCount   = isConnected ? 1 : bayCount;
    var meshBayCount= isConnected ? bayCount : 1;
    var effSpacing  = isConnected ? 0 : spacingM;
    var unitWidth   = meshBayCount * span + (meshBayCount - 1) * effSpacing;
    var totalWidth  = unitCount * unitWidth + (unitCount - 1) * effSpacing;
    return { totalWidth: Math.max(totalWidth, 0.1), length: Math.max(length, 0.1) };
  }

  // ── Clip a segment to the rectangle [0..W] x [0..L] (XZ plane) ────────────
  function _clipLineToRect(px, pz, dx, dz, W, L) {
    var tMin = -1e9, tMax = 1e9, t1, t2, tmp;
    if (Math.abs(dx) > 1e-9) {
      t1 = (0 - px) / dx; t2 = (W - px) / dx;
      if (t1 > t2) { tmp = t1; t1 = t2; t2 = tmp; }
      tMin = Math.max(tMin, t1); tMax = Math.min(tMax, t2);
    } else if (px < -1e-6 || px > W + 1e-6) return null;
    if (Math.abs(dz) > 1e-9) {
      t1 = (0 - pz) / dz; t2 = (L - pz) / dz;
      if (t1 > t2) { tmp = t1; t1 = t2; t2 = tmp; }
      tMin = Math.max(tMin, t1); tMax = Math.min(tMax, t2);
    } else if (pz < -1e-6 || pz > L + 1e-6) return null;
    if (tMin >= tMax - 1e-4) return null;
    return [[px + dx * tMin, pz + dz * tMin], [px + dx * tMax, pz + dz * tMax]];
  }

  // ── Facility bay rectangle list (multi-bay structure: gaps between bays are not facility) ──
  function _getBayRects() {
    var span     = parseFloat((document.getElementById('span-width')  || {}).value) || 7;
    var bayCount = Math.max(parseInt((document.getElementById('bay-count') || {}).value, 10) || 1, 1);
    var spacingM = parseFloat((document.getElementById('spacing-m')   || {}).value) || 1;
    var length   = parseFloat((document.getElementById('length-m')    || {}).value) || 30;
    // Facility structure is a radio (name="structure") — uses the same selector as `_facilityDims()`
    var structure= ((document.querySelector('input[name="structure"]:checked') || {}).value) || 'single';
    if (structure === 'connected' || bayCount <= 1) {
      var W = bayCount * span;
      return [{ x0: 0, x1: W, z0: 0, z1: length }];
    }
    var rects = [];
    for (var i = 0; i < bayCount; i++) {
      var x0 = i * (span + spacingM);
      rects.push({ x0: x0, x1: x0 + span, z0: 0, z1: length });
    }
    return rects;
  }

  // ── Auto branch pipe generation ───────────────────────────────────────────
  // sweep center = layer.position.(x,z) — moving the layer moves the pipe pattern too
  // In multi-bay structures the gaps between bays are outside the facility, so clip per bay
  // and generate separate branch pipes (same concept as the boundary polygon clip in geo/design).
  function _autoGenPipes() {
    var layer = _getActiveLayer(); if (!layer) return;
    var spacing = parseFloat((document.getElementById('irr-pipe-spacing') || {}).value) || 3;
    var angleDeg= parseFloat((document.getElementById('irr-pipe-angle')   || {}).value) || 0;
    var userOff = parseFloat((document.getElementById('irr-pipe-offset')  || {}).value) || (spacing / 2);
    var dims = _getFacilityDims();
    var W = dims.totalWidth, L = dims.length;
    var h = parseFloat(layer.height_m) || 2.0;
    var bays = _getBayRects();

    // Snapshot (preserve main pipes + for collinear check)
    var snapshot = (window.FittingsUI && FittingsUI.readAll) ? FittingsUI.readAll() : [];

    // Reset only existing branch pipes + joints (main pipes + sprinklers/drip preserved).
    // Per the policy that branch generation only creates branch pipes, nozzles (devices) are untouched.
    snapshot.filter(function (f) {
      return f.layer_id === layer.id && (
        (f.kind === 'irrigation_pipe' && f.sub_type !== 'main' && !f.is_vertical) ||
        f.kind === 'irrigation_connection'
      );
    }).forEach(function (f) { if (window.FittingsUI) FittingsUI.remove(f.id); });

    // Main pipe list — used for sweep-line collinear check
    var mainPipes = snapshot.filter(function (f) {
      return f.layer_id === layer.id && f.kind === 'irrigation_pipe'
          && f.sub_type === 'main' && !f.is_vertical;
    });

    var a   = angleDeg * Math.PI / 180;
    var dx  = Math.cos(a), dz = Math.sin(a);
    var px  = -dz, pz = dx;
    var cx  = (layer.position && layer.position.x != null) ? parseFloat(layer.position.x) : W / 2;
    var cz  = (layer.position && layer.position.z != null) ? parseFloat(layer.position.z) : L / 2;
    var diag = Math.sqrt(W * W + L * L);
    var maxIter = Math.ceil(diag / spacing) + 2;

    // Check whether the sweep line is parallel and collinear with a main segment (xz plane).
    // If collinear, a branch pipe would visually overlap the main and look "skipped", so skip it.
    function _sweepLineCollinearWithMain(lx, lz) {
      for (var pi = 0; pi < mainPipes.length; pi++) {
        var segs = mainPipes[pi].segments || [];
        for (var si = 0; si < segs.length; si++) {
          var ms = segs[si];
          var msdx = ms.to[0] - ms.from[0], msdz = ms.to[2] - ms.from[2];
          var mlen = Math.sqrt(msdx * msdx + msdz * msdz);
          if (mlen < 0.01) continue;
          var ndx = msdx / mlen, ndz = msdz / mlen;
          // Parallel: |cross product| ≈ 0
          var cross = dx * ndz - dz * ndx;
          if (Math.abs(cross) > 0.02) continue;
          // Perpendicular distance: from the main start point to the sweep line
          var vx = ms.from[0] - lx, vz = ms.from[2] - lz;
          var perpDist = Math.abs(vx * dz - vz * dx);
          if (perpDist < 0.5) return true;   // within 0.5m is treated as collinear
        }
      }
      return false;
    }

    for (var i = -maxIter; i <= maxIter; i++) {
      var offset = userOff + i * spacing;
      var startX = cx + px * offset, startZ = cz + pz * offset;
      // Skip sweep lines collinear with a main pipe (avoid visual overlap)
      if (mainPipes.length && _sweepLineCollinearWithMain(startX, startZ)) continue;
      // Clip per bay individually → no pipes in gaps, generating pipes broken per bay
      bays.forEach(function (b) {
        var bW = b.x1 - b.x0, bL = b.z1 - b.z0;
        var seg = _clipLineToRect(startX - b.x0, startZ - b.z0, dx, dz, bW, bL);
        if (!seg) return;
        var x0 = seg[0][0] + b.x0, z0 = seg[0][1] + b.z0;
        var x1 = seg[1][0] + b.x0, z1 = seg[1][1] + b.z0;
        var len = Math.sqrt(Math.pow(x1 - x0, 2) + Math.pow(z1 - z0, 2));
        if (len < 0.1) return;   // relaxed minimum length (0.5 → 0.1m) — avoid missing edge cases
        var segments = [{ from: [x0, h, z0], to: [x1, h, z1] }];
        window.FittingsUI.addIrrigationPipe(layer.id, segments, { sub_type: 'branch' });
      });
    }
    // Cross-check the new branches against existing mains → trim + insert tee
    if (window.FittingsUI && FittingsUI.rebuildIrrigationConnections) {
      FittingsUI.rebuildIrrigationConnections(layer.id);
    }
    _refreshIrrButtons();
  }

  // ── Auto sprinkler placement ──────────────────────────────────────────────
  function _autoGenSprinklers(silent) {
    var layer = _getActiveLayer();
    if (!layer) { if (!silent) alert(window._ ? window._('Select an irrigation layer first.') : 'Select an irrigation layer first.'); return; }
    var interval   = parseFloat((document.getElementById('irr-sp-interval')    || {}).value) || 1.5;
    var radiusM    = parseFloat((document.getElementById('irr-sp-radius')      || {}).value) || 2;
    var flowLph    = parseFloat((document.getElementById('irr-sp-flow')        || {}).value) || 40;
    var subType    = ((document.getElementById('irr-sp-subtype')      || {}).value) || 'sprinkler';
    var orientation= ((document.getElementById('irr-sp-orientation')  || {}).value) || 'down';
    var h = parseFloat(layer.height_m) || 2.0;

    // 1. Remove existing devices (keep pipes)
    var snapshot = (window.FittingsUI && FittingsUI.readAll) ? FittingsUI.readAll() : [];
    snapshot.filter(function (f) { return f.layer_id === layer.id && f.kind === 'irrigation_device'; })
            .forEach(function (f) { if (window.FittingsUI) FittingsUI.remove(f.id); });

    // 2. After removal, get the pipe list from a fresh snapshot — branch pipes only
    //    (main pipes are for supply, so no nozzles placed)
    var pipes = (window.FittingsUI && FittingsUI.readAll ? FittingsUI.readAll() : []).filter(function (f) {
      return f.layer_id === layer.id
          && f.kind === 'irrigation_pipe'
          && !f.is_vertical
          && (f.sub_type || 'branch') === 'branch';
    });
    if (pipes.length === 0) { if (!silent) alert(window._ ? window._('No branch pipes. Generate branch pipes first.') : 'No branch pipes. Generate branch pipes first.'); return; }

    // 3. Place sprinklers at interval spacing along each pipe
    // Cumulative arc length (cumLen) approach: convert the segs array into a point chain [p0, p1, p2, ...]
    // to compute the distance between each segment precisely.
    pipes.forEach(function (pipe) {
      var segs = Array.isArray(pipe.segments) ? pipe.segments : [];
      if (segs.length === 0) return;

      // Point chain: seg[0].from, seg[0].to, seg[1].to, seg[2].to, ...
      // (for a connected polyline seg[k].to === seg[k+1].from, so it is built without duplicates)
      var pts = [segs[0].from];
      for (var si = 0; si < segs.length; si++) { pts.push(segs[si].to); }

      // Cumulative distance array
      var cumLen = [0];
      for (var pi = 0; pi < pts.length - 1; pi++) {
        var ddx = pts[pi+1][0] - pts[pi][0];
        var ddz = pts[pi+1][2] - pts[pi][2];
        cumLen.push(cumLen[pi] + Math.sqrt(ddx*ddx + ddz*ddz));
      }
      var totalLen = cumLen[cumLen.length - 1];
      if (totalLen < 0.1) return;

      // Leave radiusM margin from the start/end points — so spray does not extend past the pipe ends
      // If the pipe is too short (< 2R), place just one at the center; if even shorter, skip.
      var startDist = radiusM;
      var endDist   = totalLen - radiusM;
      if (startDist > endDist) {
        if (totalLen >= radiusM) {
          startDist = endDist = totalLen / 2;     // one at center
        } else {
          return;                                  // too short
        }
      }
      for (var dist = startDist; dist <= endDist + 1e-6; dist += interval) {
        // Find the segment that dist falls in
        var segIdx = pts.length - 2; // default: last segment
        for (var ki = 0; ki < cumLen.length - 1; ki++) {
          if (cumLen[ki + 1] >= dist - 1e-6) { segIdx = ki; break; }
        }
        var spanLen = cumLen[segIdx + 1] - cumLen[segIdx];
        var frac = spanLen > 1e-9 ? (dist - cumLen[segIdx]) / spanLen : 0;
        frac = Math.min(1, Math.max(0, frac));
        var ix = pts[segIdx][0] + (pts[segIdx+1][0] - pts[segIdx][0]) * frac;
        var iz = pts[segIdx][2] + (pts[segIdx+1][2] - pts[segIdx][2]) * frac;
        window.FittingsUI.addIrrigationDevice(layer.id,
          { x: ix, y: h, z: iz },
          { pipe_id: pipe.id, flow_lph: flowLph, radius_m: radiusM,
            sub_type: subType, orientation: orientation });
      }
    });
    _renderIrrStats();
  }

  // ── Flow statistics table rendering ───────────────────────────────────────
  function _renderIrrStats() {
    var wrap = document.getElementById('irr-stats-wrap');
    var tbody = document.getElementById('irr-stats-body');
    if (!wrap || !tbody) return;
    var layer = _getActiveLayer();
    if (!layer || !window.FittingsUI || !FittingsUI.getIrrigationStats) { wrap.style.display = 'none'; return; }
    var stats = FittingsUI.getIrrigationStats(layer.id);
    if (!stats || stats.length === 0) { wrap.style.display = 'none'; return; }
    var rows = stats.map(function (s) {
      return '<tr>' +
        '<td class="text-center">' + s.no + '</td>' +
        '<td class="text-right">' + s.length_m + '</td>' +
        '<td class="text-right">' + s.emitters + '</td>' +
        '<td class="text-right">' + s.flow_lph + '</td>' +
        '<td class="text-right">' + s.flow_lpm + '</td>' +
      '</tr>';
    });
    // Total row
    var totLen  = Math.round(stats.reduce(function (a, s) { return a + s.length_m;  }, 0) * 10) / 10;
    var totEmt  = stats.reduce(function (a, s) { return a + s.emitters; }, 0);
    var totLph  = stats.reduce(function (a, s) { return a + s.flow_lph; }, 0);
    var totLpm  = Math.round(totLph / 60 * 10) / 10;
    rows.push('<tr class="fac-total-row">' +
      '<td class="text-center">' + (window._ ? window._('Total') : 'Total') + '</td>' +
      '<td class="text-right">' + totLen + '</td>' +
      '<td class="text-right">' + totEmt + '</td>' +
      '<td class="text-right">' + totLph + '</td>' +
      '<td class="text-right">' + totLpm + '</td>' +
    '</tr>');
    tbody.innerHTML = rows.join('');
    wrap.style.display = '';
  }

  function _getActiveLayer() {
    var id = (window.FittingsUI && FittingsUI.getActiveLayerId) ? FittingsUI.getActiveLayerId() : null;
    if (!id || !window.FittingsUI || !FittingsUI.readAll) return null;
    return FittingsUI.readAll().find(function (f) { return f.id === id; });
  }

  function wireIrrigation() {
    // Vertical riser (single click) — keep existing behavior
    document.addEventListener('aot-facility-add-irr-pipe', function (e) {
      var d = e.detail; if (!d) return;
      var layer = _getActiveLayer(); if (!layer) return;
      var layerH = parseFloat(layer.height_m) || 2.0;
      var x = parseFloat(d.x) || 0, z = parseFloat(d.z) || 0;
      var segments = [{ from: [x, 0, z], to: [x, layerH, z], is_vertical_seg: true }];
      if (window.FittingsUI && FittingsUI.addIrrigationPipe) {
        FittingsUI.addIrrigationPipe(layer.id, segments, { is_vertical: true });
      }
      _applyFaceTool('');
      _refreshIrrButtons();
    });

    // Main / branch pipe multi-click
    document.addEventListener('aot-facility-irr-pipe-click', function (e) {
      var d = e.detail; if (!d) return;
      var layer = _getActiveLayer(); if (!layer) return;
      var layerH = parseFloat(layer.height_m) || 2.0;
      var pt = [parseFloat(d.x) || 0, layerH, parseFloat(d.z) || 0];
      if (d.finish) {
        if (_activeDrawingPipeId && window.FittingsUI && FittingsUI.finishPipe) {
          FittingsUI.finishPipe(_activeDrawingPipeId);
        }
        _activeDrawingPipeId = null;
        if (_ctx && _ctx.setPipeAnchor) _ctx.setPipeAnchor(null);
        _applyFaceTool('');
        return;
      }
      if (!_activeDrawingPipeId) {
        if (window.FittingsUI && FittingsUI.startPipe) {
          _activeDrawingPipeId = FittingsUI.startPipe(layer.id, d.sub_type || 'branch', pt);
        }
      } else {
        if (window.FittingsUI && FittingsUI.extendPipe) {
          FittingsUI.extendPipe(_activeDrawingPipeId, pt);
        }
      }
      // Update ortho-snap/preview anchor to the just-placed point
      if (_ctx && _ctx.setPipeAnchor) _ctx.setPipeAnchor(pt);
    });

    // Level connection: click two pipes in turn → auto-create a vertical pipe
    document.addEventListener('aot-facility-irr-vconnect-click', function (e) {
      var d = e.detail; if (!d || !d.pipe_id) return;
      if (!_vconnectFirst) {
        _vconnectFirst = { pipe_id: d.pipe_id, pt: [d.x, d.y, d.z] };
        if (window.FittingsUI && FittingsUI.select) FittingsUI.select(d.pipe_id);
        return;
      }
      if (d.pipe_id === _vconnectFirst.pipe_id) return;  // ignore clicking the same pipe twice
      if (window.FittingsUI && FittingsUI.connectPipesVertical) {
        var rid = FittingsUI.connectPipesVertical(
          _vconnectFirst.pipe_id, _vconnectFirst.pt,
          d.pipe_id, [d.x, d.y, d.z]
        );
        if (!rid) {
          alert(window._ ? window._('The two pipes are at the same height (level), so they cannot be connected vertically.\nSelect pipes on different levels.') : 'The two pipes are at the same height (level), so they cannot be connected vertically.\nSelect pipes on different levels.');
        }
      }
      _vconnectFirst = null;
      _applyFaceTool('');   // end the tool after connecting
      _refreshIrrButtons();
    });

    // Enter / Escape to finish drawing / Delete to remove the selected fitting
    document.addEventListener('keydown', function (e) {
      if ((e.key === 'Enter' || e.key === 'Escape') && _activeDrawingPipeId) {
        if (window.FittingsUI && FittingsUI.finishPipe) FittingsUI.finishPipe(_activeDrawingPipeId);
        _activeDrawingPipeId = null;
        if (_ctx && _ctx.setPipeAnchor) _ctx.setPipeAnchor(null);
        if (e.key === 'Escape') _applyFaceTool('');
        return;
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        // Keep default delete behavior in text input fields
        var tag = (document.activeElement || {}).tagName || '';
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        var selId = window.FittingsUI && FittingsUI.getSelectedId ? FittingsUI.getSelectedId() : null;
        if (!selId) return;
        var all = window.FittingsUI && FittingsUI.readAll ? FittingsUI.readAll() : [];
        var sel = all.find(function (f) { return f.id === selId; });
        if (!sel) return;
        var deletable = ['irrigation_pipe', 'irrigation_device', 'irrigation_connection',
                         'window', 'door', 'side_window', 'curtain', 'fan', 'heater', 'sensor', 'fixture'];
        if (deletable.indexOf(sel.kind) !== -1) {
          e.preventDefault();
          FittingsUI.remove(selId);
        }
      }
    });

    document.addEventListener('fitting-selection-changed', function (e) {
      _refreshIrrButtons();
      // Delete-unit mode: clicking an irrigation item (pipe/nozzle/joint) removes it immediately
      if (!_deleteMode) return;
      var id = e.detail && e.detail.id;
      if (!id || !window.FittingsUI || !FittingsUI.readAll) return;
      var sel = FittingsUI.readAll().find(function (x) { return x.id === id; });
      if (!sel) return;
      if (sel.kind !== 'irrigation_pipe'
          && sel.kind !== 'irrigation_device'
          && sel.kind !== 'irrigation_connection') return;
      FittingsUI.remove(id);
    });
    document.addEventListener('fittings-changed', function () { _refreshIrrButtons(); });

    // ── Category visibility → 3D viewport bridge ──────────────────────────────
    document.addEventListener('aot-facility-cat-visibility-changed', function (e) {
      if (!_ctx || typeof _ctx.setCategoryVisibility !== 'function') return;
      var d = e.detail; if (!d) return;
      _ctx.setCategoryVisibility(d.category, d.visible);
    });

    // ── Real-time preview (debounced) ─────────────────────────────────────────
    // On spacing change, auto-sync offset to spacing/2
    var _spacingEl = document.getElementById('irr-pipe-spacing');
    var _offsetEl  = document.getElementById('irr-pipe-offset');
    if (_spacingEl && _offsetEl) {
      _spacingEl.addEventListener('input', function () {
        var spacing = parseFloat(_spacingEl.value);
        if (!isNaN(spacing) && spacing > 0) {
          _offsetEl.value = (spacing / 2).toFixed(2);
        }
      });
    }
  }

  // ── Init ─────────────────────────────────────────────────────────────────────
  function init() {
    initResizeHandle();
    wireInputs();
    wireTools();
    wireSteps();
    wireIrrigation();

    var _pageVars = JSON.parse((document.getElementById('facility-page-vars') || {}).textContent || '{}');
    var _hasFacility = !!_pageVars.facility_uuid;

    // If a facility is being loaded, skip the default-values render entirely.
    // facility-loaded → rebuildFit() will fire once the real spec arrives.
    if (_hasFacility) return;

    if (window.AoTFacility3D) {
      rebuild();
    } else {
      var tries = 0;
      var poll = setInterval(function () {
        if (window.AoTFacility3D || ++tries > 30) {
          clearInterval(poll);
          if (window.AoTFacility3D) rebuild();
        }
      }, 100);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
