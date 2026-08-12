// map-zoom.js — zoom limits for the facility page's map, read from the global
// geo settings (GeoSetting.max_zoom / digital_zoom, served as AOT_GEO_CONFIG).
//
// The facility map used to hardcode 19 for both ceilings, so it stopped zooming
// where /geo/design kept going and the two pages felt like different maps.
// There are two different ceilings and they are not the same number:
//
//   • source maxzoom — the deepest level the tile server actually has. Past it
//     MapLibre upscales the last real tile instead of requesting a 404.
//   • camera maxZoom — how far the user is allowed to zoom in.
//
// digital_zoom on  → camera goes to max_zoom, tiles upscale past their native
//                    level (this is what "digital zoom" means here).
// digital_zoom off → camera stops at the layer's own native level.
(function (global) {
  'use strict';

  var DEFAULT_NATIVE = 19;   // the standard XYZ raster ceiling

  // AOT_GEO_CONFIG comes from JSON, but the same keys arrive as form strings
  // elsewhere — treat only an explicit false/'false'/0 as off.
  function _isTrue(v, dflt) {
    if (v === false || v === 'false' || v === 0 || v === '0') return false;
    if (v === true  || v === 'true'  || v === 1 || v === '1') return true;
    return dflt;
  }

  function _int(v) {
    var n = parseInt(v, 10);
    return isNaN(n) ? null : n;
  }

  /** Deepest zoom the layer's tile server actually serves. */
  function nativeMaxZoom(layer) {
    var o = (layer && (layer.options || layer)) || {};
    return _int(o.maxNativeZoom) || _int(o.max_native_zoom) ||
           _int(o.maxzoom)       || _int(o.maxZoom)         ||
           DEFAULT_NATIVE;
  }

  /** Camera ceiling: max_zoom with digital zoom on, the native level with it off. */
  function cameraMaxZoom(layer) {
    var cfg = global.AOT_GEO_CONFIG || {};
    var native = nativeMaxZoom(layer);
    if (!_isTrue(cfg.digital_zoom, true)) return native;
    // Never go below native: a max_zoom set lower than the tiles on hand would
    // throw away detail the server is already serving.
    return Math.max(_int(cfg.max_zoom) || 22, native);
  }

  /** Starting zoom, clamped so it can never sit above the camera ceiling. */
  function initialZoom(layer, fallback) {
    var cfg = global.AOT_GEO_CONFIG || {};
    var z = parseFloat(cfg.zoom);
    if (!isFinite(z)) z = fallback;
    return Math.min(z, cameraMaxZoom(layer));
  }

  global.FacilityMapZoom = {
    DEFAULT_NATIVE: DEFAULT_NATIVE,
    nativeMaxZoom:  nativeMaxZoom,
    cameraMaxZoom:  cameraMaxZoom,
    initialZoom:    initialZoom,
  };
}(window));
