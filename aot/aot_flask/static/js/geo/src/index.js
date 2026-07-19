/**
 * AoT Geo JavaScript Bundle
 * Main Entry Point - Vector Transition Modules
 * 
 * IIFE 소스 파일을 직접 import하여 번들에 포함
 */

// MapLibre Core (Vector Tile Support) - IIFE 패턴
import './core/maplibre-core.js';

// Vector Layer Manager - IIFE 패턴
import './layers/vector-layer-manager.js';

// Raster Bridge - IIFE 패턴
import './layers/raster-bridge.js';

// MapLibre Draw - IIFE 패턴
import './draw/maplibre-draw.js';

// Map Loader - IIFE 패턴
import './loaders/map-loader.js';

// ============================================================
// Vector Transition Module Exports (window에서 참조)
// ============================================================
export const AoTMapLibre = window.AoTMapLibre;
export const VectorLayerManager = window.AoTVectorLayerManager;
export const RasterBridge = window.AoTRasterBridge;
export const MapBridge = window.AoTMapBridge;
export const MapLibreDraw = window.AoTMapLibreDraw;
export const AOT_MAP_LOADER = window.AOT_MAP_LOADER;
