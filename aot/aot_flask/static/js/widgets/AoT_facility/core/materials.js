// core/materials.js — AoT Facility material palette (moved from aot-facility-3d.js)
// Exposes window.AoTMaterials. Requires THREE.
(function (global) {
  'use strict';

  // opacity       — actual covering material property (based on light transmittance, simulation input)
  // renderOpacity — 3D-rendering-only transparency (falls back to opacity when unset)
  const _COVER_OPTS = {
    vinyl_single:  { color: 0x9ecfef, opacity: 0.75, renderOpacity: 0.25 },
    vinyl_double:  { color: 0x9ecfef, opacity: 0.68, renderOpacity: 0.32 },
    po_film:       { color: 0xbcdff0, opacity: 0.72, renderOpacity: 0.28 },
    polycarbonate: { color: 0xdaeeff, opacity: 0.54, renderOpacity: 0.46 },
    glass:         { color: 0xc8eecc, opacity: 0.82, renderOpacity: 0.18 },
  };
  function _ro(o) { return o.renderOpacity != null ? o.renderOpacity : o.opacity; }

  const MAT = {
    cover: function (type) {
      const o = _COVER_OPTS[type] || _COVER_OPTS.vinyl_double;
      // depthWrite:false — the envelope must not pollute the depth buffer, so interior elements stay visible.
      // renderOrder is set separately at mesh creation (envelope 1000, interior 900).
      return new THREE.MeshPhysicalMaterial({ color: o.color, transparent: true, opacity: _ro(o), side: THREE.DoubleSide, roughness: 0.05, metalness: 0, depthWrite: false });
    },
    coverInner: function (type) {
      const o = _COVER_OPTS[type] || { color: 0xd0eaff, renderOpacity: 0.18 };
      return new THREE.MeshPhysicalMaterial({ color: o.color, transparent: true, opacity: Math.min(_ro(o) * 0.65, 0.22), side: THREE.DoubleSide, roughness: 0.05, metalness: 0, depthWrite: false });
    },
    frame:           () => new THREE.MeshStandardMaterial({ color: 0x888888, roughness: 0.6, metalness: 0.4 }),
    floor:           () => new THREE.MeshStandardMaterial({ color: 0xb8b8b8, roughness: 0.85 }),
    sashOpen:        () => new THREE.MeshStandardMaterial({ color: 0xffb300, transparent: true, opacity: 0.75, side: THREE.DoubleSide }),
    sashClosed:      () => new THREE.MeshStandardMaterial({ color: 0x607d8b, transparent: true, opacity: 0.55, side: THREE.DoubleSide }),
    curtainThermal:  () => new THREE.MeshStandardMaterial({ color: 0xf5e6c8, transparent: true, opacity: 0.10, side: THREE.DoubleSide }),
    curtainShade:    () => new THREE.MeshStandardMaterial({ color: 0x4a4a4a, transparent: true, opacity: 0.10, side: THREE.DoubleSide }),
    fan:             () => new THREE.MeshStandardMaterial({ color: 0x546e7a }),
    fanOn:           () => new THREE.MeshStandardMaterial({ color: 0x29b6f6, emissive: 0x0288d1, emissiveIntensity: 0.6 }),
    heater:          () => new THREE.MeshStandardMaterial({ color: 0xef9a9a }),
    heaterOn:        () => new THREE.MeshStandardMaterial({ color: 0xf44336, emissive: 0xe53935, emissiveIntensity: 0.8 }),
    cooler:          () => new THREE.MeshStandardMaterial({ color: 0x80cbc4 }),
    coolerOn:        () => new THREE.MeshStandardMaterial({ color: 0x00bcd4, emissive: 0x0097a7, emissiveIntensity: 0.6 }),
    pump:            () => new THREE.MeshStandardMaterial({ color: 0x81c784 }),
    pumpOn:          () => new THREE.MeshStandardMaterial({ color: 0x4caf50, emissive: 0x388e3c, emissiveIntensity: 0.6 }),
    windArrow:       () => new THREE.MeshStandardMaterial({ color: 0x0288d1 }),
    compass:         () => new THREE.MeshStandardMaterial({ color: 0xe53935 }),
  };

  global.AoTMaterials = MAT;
})(window);
