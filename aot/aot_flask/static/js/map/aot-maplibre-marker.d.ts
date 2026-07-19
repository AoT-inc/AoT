/**
 * TypeScript type definitions for AoTMarkerManager
 * @version 1.0.0
 */

declare namespace AoTMarkerManagerTypes {
    /**
     * Marker configuration options
     */
    interface MarkerConfig {
        /** Coordinates [lng, lat] or {lng, lat} */
        lngLat: [number, number] | { lng: number; lat: number };
        /** Custom HTML element for marker */
        element?: HTMLElement;
        /** Custom marker ID */
        id?: string;
        /** Marker type (site, zone, facility, device, equipment) */
        type?: string;
        /** Marker color */
        color?: string;
        /** Marker scale */
        scale?: number;
        /** Custom HTML for marker */
        html?: string;
        /** Enable drag functionality */
        draggable?: boolean;
        /** Custom properties for events */
        properties?: Record<string, any>;
        /** Group ID to add marker to */
        groupId?: string;
        /** CSS class name(s) */
        className?: string;
        /** Anchor position */
        anchor?: 'center' | 'top' | 'bottom' | 'left' | 'right' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';
        /** Offset in pixels */
        offset?: [number, number];
    }

    /**
     * Marker data stored in registry
     */
    interface MarkerData {
        marker: maplibregl.Marker;
        element: HTMLElement;
        lngLat: { lng: number; lat: number };
        type: string;
        properties: Record<string, any>;
        groupId: string | null;
        visible: boolean;
        popup: string | null;
    }

    /**
     * Popup configuration
     */
    interface PopupConfig {
        /** HTML content */
        content?: string;
        /** Custom content element */
        element?: HTMLElement;
        /** MapLibre Popup options */
        options?: maplibregl.PopupOptions;
    }

    /**
     * Popup data stored in registry
     */
    interface PopupData {
        id: string;
        popup: maplibregl.Popup;
        markerId: string;
        content: string | HTMLElement;
    }

    /**
     * Marker group configuration
     */
    interface GroupConfig {
        /** Group name */
        name?: string;
        /** Initial visibility */
        visible?: boolean;
        /** Group type */
        type?: string;
        /** Custom properties */
        properties?: Record<string, any>;
    }

    /**
     * Marker group data
     */
    interface GroupData {
        id: string;
        name: string;
        type: string;
        markerIds: string[];
        visible: boolean;
        properties: Record<string, any>;
    }

    /**
     * Manager options
     */
    interface ManagerOptions {
        defaultMarkerColor?: string;
        defaultPopupOffset?: number;
        cursorOnHover?: boolean;
        autoPan?: boolean;
        closeButton?: boolean;
        closeOnClick?: boolean;
        maxWidth?: number;
        markerTypeDefaults?: Record<string, {
            color: string;
            scale: number;
            icon: string;
        }>;
    }

    /**
     * Site data for convenience method
     */
    interface SiteData {
        coordinates?: [number, number];
        lngLat?: { lng: number; lat: number };
        name?: string;
        description?: string;
        properties?: Record<string, any>;
    }

    /**
     * Zone data for convenience method
     */
    interface ZoneData {
        coordinates?: [number, number];
        lngLat?: { lng: number; lat: number };
        name?: string;
        description?: string;
        properties?: Record<string, any>;
    }

    /**
     * Facility data for convenience method
     */
    interface FacilityData {
        coordinates?: [number, number];
        lngLat?: { lng: number; lat: number };
        name?: string;
        description?: string;
        properties?: Record<string, any>;
    }

    /**
     * Device data for convenience method
     */
    interface DeviceData {
        coordinates?: [number, number];
        lngLat?: { lng: number; lat: number };
        name?: string;
        status?: string;
        color?: string;
        properties?: Record<string, any>;
    }
}

/**
 * AoTMarkerManager class
 * Manages markers, popups, and groups for MapLibre-GL
 */
declare class AoTMarkerManager {
    /**
     * Create a new AoTMarkerManager
     * @param map - MapLibre-GL map instance
     * @param options - Configuration options
     */
    constructor(map: any, options?: AoTMarkerManagerTypes.ManagerOptions);

    // Marker Management
    addMarker(config: AoTMarkerManagerTypes.MarkerConfig): string | null;
    removeMarker(markerId: string): AoTMarkerManager;
    getMarker(markerId: string): AoTMarkerManagerTypes.MarkerData | null;
    setMarkerPosition(markerId: string, lngLat: [number, number] | { lng: number; lat: number }): AoTMarkerManager;
    setMarkerVisible(markerId: string, visible: boolean): AoTMarkerManager;
    getAllMarkers(): string[];

    // Marker Group Management
    addMarkerGroup(groupId: string, options?: AoTMarkerManagerTypes.GroupConfig): AoTMarkerManager;
    removeMarkerGroup(groupId: string, removeMarkers?: boolean): AoTMarkerManager;
    setGroupVisible(groupId: string, visible: boolean): AoTMarkerManager;
    getGroup(groupId: string): AoTMarkerManagerTypes.GroupData | null;
    getAllGroups(): string[];

    // Popup Management
    addPopup(markerId: string, config: AoTMarkerManagerTypes.PopupConfig): string | null;
    removePopup(popupId: string): AoTMarkerManager;
    openPopup(popupId: string): AoTMarkerManager;
    closePopup(popupId: string): AoTMarkerManager;
    togglePopup(popupId: string): AoTMarkerManager;

    // Event Handling
    onMarkerClick(callback: (markerId: string, markerData: AoTMarkerManagerTypes.MarkerData, event: MouseEvent) => void): () => void;
    onMarkerHover(callback: (markerId: string, markerData: AoTMarkerManagerTypes.MarkerData, type: 'enter' | 'leave') => void): () => void;
    onMarkerDragEnd(callback: (markerId: string, markerData: AoTMarkerManagerTypes.MarkerData) => void): () => void;

    // Leaflet Compatibility
    createMarker(latLng: [number, number], options?: any): any;
    createLayerGroup(options?: AoTMarkerManagerTypes.GroupConfig): any;

    // AoT Convenience Methods
    addSiteMarkers(sites: AoTMarkerManagerTypes.SiteData[]): string[];
    addZoneMarkers(zones: AoTMarkerManagerTypes.ZoneData[]): string[];
    addFacilityMarkers(facilities: AoTMarkerManagerTypes.FacilityData[]): string[];
    addDeviceMarkers(devices: AoTMarkerManagerTypes.DeviceData[]): string[];

    // Utility Methods
    clearAll(): AoTMarkerManager;
    fitBounds(padding?: number, groupId?: string): AoTMarkerManager;
    getMarkerCount(): number;
    destroy(): void;
}

export = AoTMarkerManager;
export as namespace AoTMarkerManager;
