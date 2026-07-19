/**
 * AoT MapLibre Modules Index
 * 
 * Unified export for all MapLibre GL-based modules
 */

(function(global) {
  'use strict';

  // Export all modules to global namespace
  // The individual modules should be loaded in order:
  // 1. AoTMapLibreCore.js - Core map functionality
  // 2. AoTMapLibreLayer.js - Layer management
  // 3. AoTMapLibreFeatureGroup.js - Feature grouping
  // 4. AoTMapLibreDrawTool.js - Drawing tools
  // 5. AoTMapLibrePopup.js - Popup management
  // 6. AoTMapLibreTooltip.js - Tooltip management
  // 7. AoTGeoCompatibility.js - GeoJSON/CRS utilities

  /**
   * AoT MapLibre Module Registry
   */
  const AoTMapLibreModules = {
    version: '1.0.0',
    core: 'AoTMapLibreCore',
    layer: 'AoTMapLibreLayer',
    featureGroup: 'AoTMapLibreFeatureGroup',
    drawTool: 'AoTMapLibreDrawTool',
    popup: 'AoTMapLibrePopup',
    tooltip: 'AoTMapLibreTooltip',
    compatibility: 'AoTGeoCompatibility'
  };

  /**
   * Check if all required modules are loaded
   * @returns {Object} Status of each module
   */
  function checkModules() {
    const status = {};
    Object.entries(AoTMapLibreModules).forEach(([key, name]) => {
      if (key === 'version') return;
      status[key] = typeof global[name] !== 'undefined';
    });
    status.allLoaded = Object.values(status).every(v => v);
    return status;
  }

  /**
   * Get or create a map core instance
   * @param {string} id - Container ID
   * @param {Object} options - Configuration options
   * @returns {AoTMapLibreCore}
   */
  function getCore(id, options) {
    if (global.AoTMapLibreCore) {
      return new global.AoTMapLibreCore(id, options);
    }
    console.error('[AoTMapLibreModules] AoTMapLibreCore not loaded');
    return null;
  }

  /**
   * Create a layer from GeoJSON
   * @param {maplibregl.Map} map - Map instance
   * @param {Object} geojson - GeoJSON data
   * @param {Object} options - Layer options
   * @returns {AoTMapLibreLayer}
   */
  function createLayer(map, geojson, options) {
    if (global.AoTMapLibreLayer) {
      return global.AoTMapLibreLayer.fromGeoJSON(map, geojson, options);
    }
    console.error('[AoTMapLibreModules] AoTMapLibreLayer not loaded');
    return null;
  }

  /**
   * Create a feature group
   * @returns {AoTMapLibreFeatureGroup}
   */
  function createFeatureGroup() {
    if (global.AoTMapLibreFeatureGroup) {
      return new global.AoTMapLibreFeatureGroup();
    }
    console.error('[AoTMapLibreModules] AoTMapLibreFeatureGroup not loaded');
    return null;
  }

  /**
   * Create a draw tool
   * @param {maplibregl.Map} map - Map instance
   * @param {Object} options - Tool options
   * @returns {Promise<AoTMapLibreDrawTool>}
   */
  async function createDrawTool(map, options) {
    if (global.AoTMapLibreDrawTool) {
      return global.AoTMapLibreDrawTool.create(map, options);
    }
    console.error('[AoTMapLibreModules] AoTMapLibreDrawTool not loaded');
    return null;
  }

  /**
   * Create a popup
   * @param {Object} options - Popup options
   * @returns {AoTMapLibrePopup}
   */
  function createPopup(options) {
    if (global.AoTMapLibrePopup) {
      return new global.AoTMapLibrePopup(options);
    }
    console.error('[AoTMapLibreModules] AoTMapLibrePopup not loaded');
    return null;
  }

  /**
   * Create a tooltip
   * @param {Object} options - Tooltip options
   * @returns {AoTMapLibreTooltip}
   */
  function createTooltip(options) {
    if (global.AoTMapLibreTooltip) {
      return new global.AoTMapLibreTooltip(options);
    }
    console.error('[AoTMapLibreModules] AoTMapLibreTooltip not loaded');
    return null;
  }

  /**
   * Get compatibility utilities
   * @returns {AoTGeoCompatibility}
   */
  function getCompatibility() {
    if (global.AoTGeoCompatibility) {
      return new global.AoTGeoCompatibility();
    }
    console.error('[AoTMapLibreModules] AoTGeoCompatibility not loaded');
    return null;
  }

  // Create namespace
  const AoTMapLibre = {
    version: AoTMapLibreModules.version,
    modules: AoTMapLibreModules,
    checkModules: checkModules,
    getCore: getCore,
    createLayer: createLayer,
    createFeatureGroup: createFeatureGroup,
    createDrawTool: createDrawTool,
    createPopup: createPopup,
    createTooltip: createTooltip,
    getCompatibility: getCompatibility
  };

  // Export to global
  global.AoTMapLibre = AoTMapLibre;

  // Also export individual classes directly for convenience
  if (global.AoTMapLibreCore) global.AoTMapLibre.Core = global.AoTMapLibreCore;
  if (global.AoTMapLibreLayer) global.AoTMapLibre.Layer = global.AoTMapLibreLayer;
  if (global.AoTMapLibreFeatureGroup) global.AoTMapLibre.FeatureGroup = global.AoTMapLibreFeatureGroup;
  if (global.AoTMapLibreDrawTool) global.AoTMapLibre.DrawTool = global.AoTMapLibreDrawTool;
  if (global.AoTMapLibrePopup) global.AoTMapLibre.Popup = global.AoTMapLibrePopup;
  if (global.AoTMapLibreTooltip) global.AoTMapLibre.Tooltip = global.AoTMapLibreTooltip;
  if (global.AoTGeoCompatibility) global.AoTMapLibre.Compatibility = global.AoTGeoCompatibility;

})(typeof window !== 'undefined' ? window : global);
