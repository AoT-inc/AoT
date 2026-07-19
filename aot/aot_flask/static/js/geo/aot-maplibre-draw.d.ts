/**
 * TypeScript type definitions for AoTDrawManager
 * @module AoTDrawManager
 * @version 1.0.0
 */

/**
 * Drawing instance configuration
 */
interface DrawConfig {
  polyline?: boolean;
  polygon?: boolean;
  rectangle?: boolean;
  circle?: boolean;
  marker?: boolean;
  trash?: boolean;
  combine?: boolean;
  uncombine?: boolean;
  stroke?: boolean;
  color?: string;
  fill?: string;
  fillOpacity?: number;
  lineWidth?: number;
  circleRadius?: number;
  edit?: {
    featureGroup?: any;
    allow_self_intersection?: boolean;
  };
  displayControls?: boolean;
  controlsPosition?: 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left';
}

/**
 * GeoJSON Feature
 */
interface GeoJSONFeature {
  type: 'Feature';
  id?: string;
  properties: Record<string, any>;
  geometry: {
    type: 'Point' | 'LineString' | 'Polygon' | 'MultiPoint' | 'MultiLineString' | 'MultiPolygon';
    coordinates: any;
  };
}

/**
 * GeoJSON FeatureCollection
 */
interface GeoJSONFeatureCollection {
  type: 'FeatureCollection';
  features: GeoJSONFeature[];
}

/**
 * Draw event callback function type
 */
type DrawEventCallback = (feature: GeoJSONFeature | GeoJSONFeature[]) => void;

/**
 * AoTDrawManager static methods
 */
declare interface AoTDrawManagerStatic {
  /**
   * Create a new draw instance
   * @param container - Container element or ID
   * @param map - MapLibre map instance
   * @param config - Configuration options
   */
  init(container: string | HTMLElement, map: any, config?: DrawConfig): DrawInstance;

  /**
   * Get draw instance by ID
   * @param id - Instance ID
   */
  get(id?: string): DrawInstance | null;

  /**
   * Get or create default instance
   * @param map - Map instance
   * @param config - Configuration
   */
  getDefault(map: any, config?: DrawConfig): DrawInstance;

  /**
   * Destroy all instances
   */
  destroyAll(): void;

  /**
   * Convert coordinates to GeoJSON Point
   * @param coords - [lng, lat] coordinates
   */
  toGeoJSON(coords: [number, number]): GeoJSONFeature;

  /**
   * Create circle GeoJSON (approximated polygon)
   * @param center - [lng, lat] center
   * @param radius - Radius in meters
   * @param steps - Number of polygon vertices
   */
  createCircle(center: [number, number], radius: number, steps?: number): GeoJSONFeature;

  /**
   * Create rectangle GeoJSON
   * @param bounds - [[sw_lng, sw_lat], [ne_lng, ne_lat]]
   */
  createRectangle(bounds: [[number, number], [number, number]]): GeoJSONFeature;

  /**
   * Convert Leaflet layer to GeoJSON
   * @param layer - Leaflet layer object
   */
  fromLeafletLayer(layer: any): GeoJSONFeature | null;

  /**
   * Active instances map
   */
  instances: Map<string, DrawInstance>;

  /**
   * Default instance ID
   */
  DEFAULT_ID: string;

  /**
   * Supported drawing types
   */
  DRAW_TYPES: {
    POLYLINE: 'polyline';
    POLYGON: 'polygon';
    RECTANGLE: 'rectangle';
    CIRCLE: 'circle';
    MARKER: 'marker';
  };
}

/**
 * Draw instance methods
 */
declare interface DrawInstance {
  /**
   * Enable polyline drawing mode
   */
  enablePolyline(): void;

  /**
   * Enable polygon drawing mode
   */
  enablePolygon(): void;

  /**
   * Enable rectangle drawing mode
   */
  enableRectangle(): void;

  /**
   * Enable circle drawing mode
   */
  enableCircle(): void;

  /**
   * Enable marker placement mode
   */
  enableMarker(): void;

  /**
   * Enable edit mode
   */
  enableEdit(): void;

  /**
   * Enable delete mode
   */
  enableDelete(): void;

  /**
   * Enable combine mode
   */
  enableCombine(): void;

  /**
   * Disable drawing mode
   */
  disableDraw(): void;

  /**
   * Get all features as GeoJSON
   */
  getGeoJSON(): GeoJSONFeatureCollection;

  /**
   * Get features as layer-like objects
   */
  getLayers(): Array<{
    feature: GeoJSONFeature;
    toGeoJSON: () => GeoJSONFeature;
    getLatLng: () => { lat: number; lng: number } | null;
  }>;

  /**
   * Add GeoJSON features
   * @param data - GeoJSON data
   * @returns Added feature IDs
   */
  addGeoJSON(data: GeoJSONFeatureCollection | string): string[];

  /**
   * Clear all features
   * @param silent - Suppress event emission
   */
  clearAll(silent?: boolean): void;

  /**
   * Delete selected features
   */
  deleteSelected(): void;

  /**
   * Select feature by ID
   * @param featureId - Feature ID
   */
  selectFeature(featureId: string): void;

  /**
   * Get selected feature IDs
   */
  getSelectedIds(): string[];

  /**
   * Register event callback
   * @param eventType - Event type
   * @param callback - Callback function
   */
  on(eventType: string, callback: DrawEventCallback): void;

  /**
   * Remove event callback
   * @param eventType - Event type
   * @param callback - Callback function
   */
  off(eventType: string, callback: DrawEventCallback): void;

  /**
   * Once event handler
   * @param eventType - Event type
   * @param callback - Callback function
   */
  once(eventType: string, callback: DrawEventCallback): void;

  /**
   * Add feature group
   * @param featureGroup - Leaflet-style feature group
   */
  addLayer(featureGroup: any): void;

  /**
   * Add draw control
   * @param options - Control options
   */
  addDrawControl(options?: any): void;

  /**
   * Get draw control
   */
  getDrawControl(): any;

  /**
   * Check if initialized
   */
  isReady(): boolean;

  /**
   * Check if drawing
   */
  isDrawing(): boolean;

  /**
   * Get current mode
   */
  getMode(): string | null;

  /**
   * Get feature count
   */
  getCount(): number;

  /**
   * Set drawing style
   * @param style - Style options
   */
  setStyle(style: {
    color?: string;
    fillColor?: string;
    fillOpacity?: number;
    weight?: number;
  }): void;

  /**
   * Destroy instance
   */
  destroy(): void;

  /**
   * Instance ID
   */
  id: string;

  /**
   * Map instance
   */
  map: any;
}

declare var AoTDrawManager: AoTDrawManagerStatic;
