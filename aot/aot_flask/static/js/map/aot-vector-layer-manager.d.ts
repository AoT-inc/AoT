/**
 * TypeScript type definitions for AoTVectorLayerManager
 * @version 1.0.0
 */

declare namespace AoTVectorLayerManagerTypes {
    /**
     * Source configuration options
     */
    interface VectorSourceOptions {
        tiles: string[];
        minzoom?: number;
        maxzoom?: number;
        attribution?: string;
    }

    /**
     * GeoJSON source options
     */
    interface GeoJSONSourceOptions {
        cluster?: boolean;
        clusterRadius?: number;
        clusterMaxZoom?: number;
        clusterProperties?: Record<string, any>;
    }

    /**
     * Layer configuration
     */
    interface LayerConfig {
        id: string;
        sourceId: string;
        sourceLayer?: string;
        type?: 'fill' | 'line' | 'symbol' | 'circle' | 'heatmap' | 'raster' | 'background';
        paint?: Record<string, any>;
        layout?: Record<string, any>;
        filter?: any[];
        minzoom?: number;
        maxzoom?: number;
        styleType?: 'device' | 'facility' | 'facilityOutline' | 'zone' | 'zoneOutline' | 
                    'site' | 'siteOutline' | 'equipment' | 'equipmentOutline' | 
                    'reference' | 'referenceOutline' | 'polygon' | 'polygonOutline' | 
                    'line' | 'circle' | 'heatmap';
        interactive?: boolean;
    }

    /**
     * Style options for convenience methods
     */
    interface PolygonStyle {
        fillColor?: string;
        fillOpacity?: number;
        strokeColor?: string;
        strokeWidth?: number;
        interactive?: boolean;
    }

    interface LineStyle {
        color?: string;
        width?: number;
        dashArray?: number[];
        opacity?: number;
        interactive?: boolean;
    }

    interface CircleStyle {
        color?: string;
        radius?: number;
        opacity?: number;
        interactive?: boolean;
    }

    interface SymbolStyle {
        textField?: string;
        color?: string;
        size?: number;
        offset?: [number, number];
    }

    /**
     * Layer style object
     */
    interface LayerStyle {
        paint?: Record<string, any>;
        layout?: Record<string, any>;
    }

    /**
     * Manager options
     */
    interface ManagerOptions {
        clickTolerance?: number;
        cursorOnHover?: boolean;
        defaultLanguage?: string;
    }

    /**
     * Feature with location
     */
    interface FeatureInfo {
        feature: GeoJSON.Feature;
        lngLat: { lng: number; lat: number };
        layerId: string;
        point?: { x: number; y: number };
    }

    /**
     * Bounding box
     */
    type BoundingBox = [[number, number], [number, number]];
}

/**
 * AoTVectorLayerManager class
 * Manages vector sources and layers for MapLibre-GL
 */
declare class AoTVectorLayerManager {
    /**
     * Create a new AoTVectorLayerManager
     * @param map - MapLibre-GL map instance
     * @param options - Configuration options
     */
    constructor(map: any, options?: AoTVectorLayerManagerTypes.ManagerOptions);

    // Source Management
    addVectorSource(id: string, options: AoTVectorLayerManagerTypes.VectorSourceOptions): AoTVectorLayerManager;
    addGeoJSONSource(id: string, data: GeoJSON.GeoJSON | string, options?: AoTVectorLayerManagerTypes.GeoJSONSourceOptions): AoTVectorLayerManager;
    updateGeoJSONData(id: string, data: GeoJSON.GeoJSON): AoTVectorLayerManager;
    removeSource(id: string): AoTVectorLayerManager;
    getSource(id: string): { type: string; config: any; layers: string[]; clustered: boolean } | null;

    // Layer Management
    addLayer(config: AoTVectorLayerManagerTypes.LayerConfig): AoTVectorLayerManager;
    removeLayer(id: string): AoTVectorLayerManager;
    getLayer(id: string): { config: AoTVectorLayerManagerTypes.LayerConfig; layer: any; sourceId: string } | null;
    hasLayer(id: string): boolean;
    getAllLayers(): string[];

    // Style Management
    setLayerStyle(layerId: string, style: AoTVectorLayerManagerTypes.LayerStyle): AoTVectorLayerManager;
    getLayerStyle(layerId: string): AoTVectorLayerManagerTypes.LayerStyle | null;
    setLayerVisibility(layerId: string, visible: boolean): AoTVectorLayerManager;
    setLayerOpacity(layerId: string, opacity: number): AoTVectorLayerManager;

    // Filter Management
    setFilter(layerId: string, filter: any[]): AoTVectorLayerManager;
    clearFilter(layerId: string): AoTVectorLayerManager;
    getFilter(layerId: string): any[] | null;

    // Event Handling
    onLayerClick(callback: (feature: GeoJSON.Feature, lngLat: { lng: number; lat: number }, layerId: string) => void): () => void;
    onLayerHover(callback: (feature: GeoJSON.Feature, lngLat: { lng: number; lat: number }, layerId: string, type: 'enter' | 'leave') => void): () => void;

    // Convenience Methods
    addPolygonLayer(layerId: string, sourceId: string, style?: AoTVectorLayerManagerTypes.PolygonStyle): AoTVectorLayerManager;
    addLineLayer(layerId: string, sourceId: string, style?: AoTVectorLayerManagerTypes.LineStyle): AoTVectorLayerManager;
    addCircleLayer(layerId: string, sourceId: string, style?: AoTVectorLayerManagerTypes.CircleStyle): AoTVectorLayerManager;
    addSymbolLayer(layerId: string, sourceId: string, style?: AoTVectorLayerManagerTypes.SymbolStyle): AoTVectorLayerManager;

    // Vector Source Helpers
    addMapTilerSource(apiKey?: string, style?: string): AoTVectorLayerManager;
    addOSMVectorSource(id?: string): AoTVectorLayerManager;

    // Utility Methods
    getFeaturesAtPoint(layerIds: string[], point: [number, number]): GeoJSON.Feature[];
    getFeaturesInBounds(bounds: AoTVectorLayerManagerTypes.BoundingBox, layerIds?: string[]): GeoJSON.Feature[];
    fitToSource(sourceId: string, padding?: number): AoTVectorLayerManager;

    // Cleanup
    destroy(): void;
}

// GeoJSON namespace augmentation
declare namespace GeoJSON {
    interface Feature<G = Geometry, P = Record<string, any>> {
        type: 'Feature';
        geometry: G;
        properties: P;
        id?: string | number;
    }

    interface FeatureCollection<G = Geometry, P = Record<string, any>> {
        type: 'FeatureCollection';
        features: Feature<G, P>[];
    }

    type Geometry = Point | MultiPoint | LineString | MultiLineString | Polygon | MultiPolygon | GeometryCollection;
    
    interface Point {
        type: 'Point';
        coordinates: [number, number];
    }

    interface MultiPoint {
        type: 'MultiPoint';
        coordinates: [number, number][];
    }

    interface LineString {
        type: 'LineString';
        coordinates: [number, number][];
    }

    interface MultiLineString {
        type: 'MultiLineString';
        coordinates: [number, number][][];
    }

    interface Polygon {
        type: 'Polygon';
        coordinates: [number, number][][];
    }

    interface MultiPolygon {
        type: 'MultiPolygon';
        coordinates: [number, number][][][];
    }

    interface GeometryCollection {
        type: 'GeometryCollection';
        geometries: Geometry[];
    }
}

export = AoTVectorLayerManager;
export as namespace AoTVectorLayerManager;
