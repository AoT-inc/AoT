/**
 * TypeScript definitions for aot-maplibre-raster-bridge.js
 * Leaflet ↔ MapLibre Bridge Layer
 * @version 1.1.0
 */

declare namespace AoTMapBridge {
  /**
   * Bridge configuration options
   */
  interface BridgeConfig {
    /** Leaflet map instance */
    leaflet: L.Map;
    /** MapLibre map instance */
    maplibre: maplibregl.Map;
    /** Enable zoom synchronization (default: true) */
    syncZoom?: boolean;
    /** Enable pan synchronization (default: true) */
    syncPan?: boolean;
    /** Enable center synchronization (default: true) */
    syncCenter?: boolean;
    /** Leaflet is the master/source of truth (default: true) */
    leafletMaster?: boolean;
    /** Throttle delay for sync events in ms (default: 16) */
    throttle?: number;
  }

  /**
   * WMS layer options
   */
  interface WMSLayerOptions {
    /** WMS service URL */
    url: string;
    /** Comma-separated layer names */
    layers: string;
    /** Image format (default: 'image/png') */
    format?: string;
    /** Enable transparency (default: true) */
    transparent?: boolean;
    /** Layer opacity (default: 0.8) */
    opacity?: number;
    /** Attribution text */
    attribution?: string;
    /** Additional paint options */
    paintOptions?: Record<string, any>;
  }

  /**
   * Tile layer options
   */
  interface TileLayerOptions {
    /** Tile URL template */
    url: string;
    /** Attribution text */
    attribution?: string;
    /** Maximum zoom level */
    maxZoom?: number;
    /** Subdomains array */
    subdomains?: string[];
    /** Layer opacity */
    opacity?: number;
  }

  /**
   * Synchronization state
   */
  interface SyncState {
    leaflet: {
      center: { lat: number; lng: number };
      zoom: number;
    };
    maplibre: {
      center: { lat: number; lng: number };
      zoom: number;
    };
    isSynced: boolean;
    master: 'leaflet' | 'maplibre';
  }

  /**
   * Default tile layer templates
   */
  interface DefaultTileLayers {
    [key: string]: TileLayerOptions;
  }
}

/**
 * AoT Map Bridge - Leaflet ↔ MapLibre Bridge Layer
 */
declare class BridgeInstance {
  /** Bridge instance ID */
  id: string;

  // WMS Layer Management
  addWMSLayer(id: string, options: AoTMapBridge.WMSLayerOptions): string;
  removeWMSLayer(id: string): void;
  setWMSLayerVisibility(id: string, visible: boolean): void;
  setWMSLayerOpacity(id: string, opacity: number): void;

  // Leaflet.Draw Compatible Layer API
  addTileLayer(id: string, options: AoTMapBridge.TileLayerOptions, isBaseLayer?: boolean): string;
  switchBaseLayer(id: string): boolean;
  getActiveBaseLayer(): string | null;
  removeTileLayer(id: string): boolean;
  setOverlayVisibility(id: string, visible: boolean): void;
  setOverlayOpacity(id: string, opacity: number): void;
  addImageOverlay(id: string, url: string, bounds: number[][], options?: any): string;

  // Event Compatibility
  fire(eventType: string, data: any): void;
  on(eventType: string, callback: (data: any) => void): void;
  off(eventType: string, callback: (data: any) => void): void;

  // Coordinate Conversion
  leafletBoundsToMapLibre(bounds: L.LatLngBounds): number[][];
  maplibreBoundsToLeaflet(bounds: number[][]): L.LatLngBounds;

  // State & Control
  getSyncState(): AoTMapBridge.SyncState;
  forceSync(): void;
  destroy(): void;
}

/**
 * AoT Map Bridge Namespace
 */
declare const AoTMapBridge: {
  instances: Map<string, BridgeInstance>;
  DEFAULT_THROTTLE: number;
  DEFAULT_TILE_LAYERS: AoTMapBridge.DefaultTileLayers;

  create(config: AoTMapBridge.BridgeConfig): BridgeInstance;
  get(id: string): BridgeInstance | null;
  getAll(): BridgeInstance[];
  destroyAll(): void;
  leafletToMapLibre(latlng: L.LatLng): [number, number];
  maplibreToLeaflet(coords: [number, number]): L.LatLng;
  getDefaultTileLayers(): AoTMapBridge.DefaultTileLayers;
  registerTileLayer(name: string, config: AoTMapBridge.TileLayerOptions): void;
};

export = AoTMapBridge;
