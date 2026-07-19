/**
 * aot-multi-source-manager.d.ts
 * TypeScript definitions for AoTMultiSourceManager
 */

/**
 * Source configuration for map providers
 */
interface AoTMultiSourceConfig {
    /** Unique source identifier */
    id: string;
    /** Display name for UI */
    name: string;
    /** Map provider: vworld, maptiler, osm, google */
    provider: string;
    /** Tile type: raster or vector */
    type: 'raster' | 'vector';
    /** Tile URL template */
    url: string;
    /** Tile layer options */
    options?: Record<string, any>;
    /** CDN subdomains */
    subdomains?: string[];
    /** Attribution text */
    attribution?: string;
    /** Set as default source */
    isDefault?: boolean;
    /** Force vector tile rendering */
    isVector?: boolean;
    /** Custom metadata */
    metadata?: Record<string, any>;
}

/**
 * Source status information
 */
interface AoTMultiSourceStatus {
    id: string;
    name: string;
    status: 'unloaded' | 'loaded' | 'active' | 'error';
    isActive: boolean;
    type: 'raster' | 'vector';
    provider: string;
}

/**
 * Switch options
 */
interface AoTMultiSourceSwitchOptions {
    /** Enable transition animation (default: true) */
    animate?: boolean;
    /** Preserve map view (default: true) */
    preserveView?: boolean;
    /** Callback after switch completes */
    onComplete?: (source: any) => void;
}

/**
 * Source change event data
 */
interface AoTMultiSourceChangeEvent {
    previous: string | null;
    current: string;
    source: any;
}

/**
 * Event callback types
 */
type AoTMultiSourceEventCallback = (data: any) => void;

/**
 * AoT Multi-Source Manager
 * Handles multiple map sources with unified API
 */
declare class AoTMultiSourceManager {
    /** Source type constants */
    SOURCE_TYPES: {
        RASTER: 'raster';
        VECTOR: 'vector';
    };

    /** Provider constants */
    PROVIDERS: {
        VWORLD: 'vworld';
        MAPTILER: 'maptiler';
        OSM: 'osm';
        GOOGLE: 'google';
    };

    /**
     * Initialize the manager with a Leaflet map instance
     * @param map - Leaflet map instance
     * @returns this manager instance
     */
    init(map: any): AoTMultiSourceManager;

    /**
     * Register a new map source
     * @param sourceConfig - Source configuration
     * @returns Success status
     */
    registerSource(sourceConfig: AoTMultiSourceConfig): boolean;

    /**
     * Unregister a map source
     * @param sourceId - Source ID to unregister
     * @returns Success status
     */
    unregisterSource(sourceId: string): boolean;

    /**
     * Get a registered source by ID
     * @param sourceId - Source ID
     * @returns Source config or null
     */
    getSource(sourceId: string): AoTMultiSourceConfig | null;

    /**
     * Get all registered sources
     * @returns Sources object
     */
    getAllSources(): Record<string, AoTMultiSourceConfig>;

    /**
     * Get sources by provider
     * @param provider - Provider name
     * @returns Array of source configs
     */
    getSourcesByProvider(provider: string): AoTMultiSourceConfig[];

    /**
     * Get sources by type
     * @param type - Source type (raster, vector)
     * @returns Array of source configs
     */
    getSourcesByType(type: 'raster' | 'vector'): AoTMultiSourceConfig[];

    /**
     * Switch to a different map source with animation
     * @param sourceId - Source ID to switch to
     * @param options - Switch options
     * @returns Promise that resolves when switch is complete
     */
    switchSource(sourceId: string, options?: AoTMultiSourceSwitchOptions): Promise<any>;

    /**
     * Get the currently active source
     * @returns Active source config or null
     */
    getActiveSource(): AoTMultiSourceConfig | null;

    /**
     * Get the currently active source ID
     * @returns Active source ID or null
     */
    getActiveSourceId(): string | null;

    /**
     * Set the default source
     * @param sourceId - Source ID
     * @param addToMap - Whether to add to map immediately
     */
    setDefaultSource(sourceId: string, addToMap?: boolean): void;

    /**
     * Create a basemap switcher control
     * @param options - Control options
     * @returns Leaflet control
     */
    createSwitcherControl(options?: { position?: string; maxHeight?: number }): any;

    /**
     * Register an event listener
     * @param event - Event name
     * @param callback - Callback function
     * @returns Unsubscribe function
     */
    on(event: string, callback: AoTMultiSourceEventCallback): () => void;

    /**
     * Remove an event listener
     * @param event - Event name
     * @param callback - Callback function
     */
    off(event: string, callback: AoTMultiSourceEventCallback): void;

    /**
     * Create a mixed layer configuration
     * @param config - Mixed layer config
     * @returns Promise resolving to layer group
     */
    createMixedLayers(config: {
        basemap?: string;
        overlays?: string[];
    }): Promise<any>;

    /**
     * Set transition animation duration
     * @param duration - Duration in milliseconds
     */
    setTransitionDuration(duration: number): void;

    /**
     * Update source API key
     * @param sourceId - Source ID
     * @param apiKey - New API key
     */
    setApiKey(sourceId: string, apiKey: string): void;

    /**
     * Get source status
     * @param sourceId - Source ID
     * @returns Status object
     */
    getSourceStatus(sourceId: string): AoTMultiSourceStatus | null;

    /**
     * Destroy the manager and clean up
     */
    destroy(): void;

    /**
     * Factory function to create a new manager instance
     * @param map - Leaflet map instance
     * @returns New manager instance
     */
    static create(map: any): AoTMultiSourceManager;
}

/**
 * Global AoT Multi-Source Manager instance
 */
declare const AoTMultiSourceManager: AoTMultiSourceManager;
