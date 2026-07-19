/**
 * TypeScript type definitions for AoT Marker Manager
 * @version 1.0.0
 */

/**
 * Marker type constants
 */
export declare const MARKER_TYPES: {
  readonly SITE: 'site';
  readonly ZONE: 'zone';
  readonly FACILITY: 'facility';
  readonly CUSTOM: 'custom';
};

/**
 * Default marker styles by type
 */
export interface MarkerStyle {
  color: string;
  size: number;
  icon: string;
  label: string;
}

/**
 * Marker manager options
 */
export interface MarkerManagerOptions {
  defaultIcons?: boolean;
  clusterMarkers?: boolean;
  clusterRadius?: number;
  showLabels?: boolean;
  defaultStyles?: Record<string, MarkerStyle>;
}

/**
 * Marker options
 */
export interface MarkerOptions {
  coordinates: [number, number];
  type?: 'site' | 'zone' | 'facility' | 'custom';
  label?: string;
  element?: HTMLElement;
  html?: string;
  className?: string;
  draggable?: boolean;
  clickable?: boolean;
  hoverable?: boolean;
  style?: Record<string, string>;
  popup?: PopupOptions;
  data?: Record<string, unknown>;
}

/**
 * Popup options
 */
export interface PopupOptions {
  content: string;
  maxWidth?: number;
  closeButton?: boolean;
  closeOnClick?: boolean;
}

/**
 * Marker data
 */
export interface MarkerData {
  markerId: string;
  coordinates: [number, number];
  options?: MarkerOptions;
  element?: HTMLElement;
}

/**
 * Group options
 */
export interface GroupOptions {
  label?: string;
  color?: string;
}

/**
 * Statistics
 */
export interface MarkerStats {
  totalMarkers: number;
  byType: Record<string, number>;
  byGroup: Record<string, number>;
  markers: Array<{
    id: string;
    type: string;
    coordinates: [number, number];
    groupId: string | null;
    hasPopup: boolean;
  }>;
}

/**
 * Fit bounds options
 */
export interface FitBoundsOptions {
  padding?: number;
  maxZoom?: number;
}

/**
 * Marker instance interface
 */
export interface IMarkerInstance {
  id: string;
  getCoordinates(): [number, number];
  setCoordinates(coordinates: [number, number]): void;
  getPopup(): IPopupInstance | null;
  setPopup(popup: IPopupInstance): void;
  on(eventType: string, handler: (data: MarkerData) => void): void;
  off(eventType: string, handler: (data: MarkerData) => void): void;
}

/**
 * Popup instance interface
 */
export interface IPopupInstance {
  popup: maplibregl.Popup;
  isOpen: boolean;
  open(markerId: string): void;
  close(): void;
  remove(): void;
}

/**
 * Marker manager interface
 */
export interface IMarkerManager {
  id: string;
  addMarker(id: string, options: MarkerOptions): IMarkerInstance;
  removeMarker(id: string): boolean;
  getMarker(id: string): IMarkerInstance | null;
  getAllMarkers(): IMarkerInstance[];
  hasMarker(id: string): boolean;
  updateMarkerCoordinates(id: string, coordinates: [number, number]): boolean;
  addMarkerGroup(groupId: string, markerIds: string[], options?: GroupOptions): boolean;
  removeFromGroup(markerId: string): boolean;
  removeGroup(groupId: string): boolean;
  getGroupMarkers(groupId: string): IMarkerInstance[];
  setGroupVisibility(groupId: string, visible: boolean): boolean;
  addPopup(id: string, options: PopupOptions): IPopupInstance;
  removePopup(id: string): boolean;
  updatePopupContent(id: string, content: string): boolean;
  showPopup(markerId: string): boolean;
  hidePopup(markerId: string): boolean;
  addCustomMarker(id: string, options: MarkerOptions): IMarkerInstance;
  addSiteMarker(id: string, options: MarkerOptions): IMarkerInstance;
  addZoneMarker(id: string, options: MarkerOptions): IMarkerInstance;
  addFacilityMarker(id: string, options: MarkerOptions): IMarkerInstance;
  addSiteMarkers(sites: Array<MarkerOptions & { id: string }>): string[];
  addZoneMarkers(zones: Array<MarkerOptions & { id: string }>): string[];
  addFacilityMarkers(facilities: Array<MarkerOptions & { id: string }>): string[];
  clearAllMarkers(): number;
  getMarkerCount(): number;
  getStats(): MarkerStats;
  fitBounds(options?: FitBoundsOptions): boolean;
  destroy(): void;
}

/**
 * AoT Marker Manager namespace
 */
export interface AoTMarkerManagerNamespace {
  MARKER_TYPES: typeof MARKER_TYPES;
  DEFAULT_MARKER_STYLES: Record<string, MarkerStyle>;
  instances: Map<string, IMarkerManager>;
  create(map: maplibregl.Map, options?: MarkerManagerOptions): IMarkerManager;
  get(id: string): IMarkerManager | null;
  getAll(): IMarkerManager[];
  destroyAll(): void;
  marker(coordinates: [number, number], options?: MarkerOptions): LeafletCompatibleMarker;
  icon(options: Record<string, unknown>): { options: Record<string, unknown> };
}

/**
 * Leaflet-compatible marker
 */
export interface LeafletCompatibleMarker {
  addTo(map: maplibregl.Map): LeafletCompatibleMarker;
  setLatLng(latlng: [number, number]): LeafletCompatibleMarker;
  getLatLng(): [number, number];
  setIcon(icon: { options: Record<string, unknown> }): LeafletCompatibleMarker;
  bindPopup(content: string): LeafletCompatibleMarker;
  openPopup(): LeafletCompatibleMarker;
  closePopup(): LeafletCompatibleMarker;
  on(type: string, handler: (data: MarkerData) => void): LeafletCompatibleMarker;
  off(type: string, handler: (data: MarkerData) => void): LeafletCompatibleMarker;
  draggable(): LeafletCompatibleMarker;
  remove(): void;
}

/**
 * Global declaration
 */
declare global {
  interface Window {
    AoTMarkerManager: AoTMarkerManagerNamespace;
  }
}

export {};
