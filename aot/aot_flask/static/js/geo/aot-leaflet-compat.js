/**
 * AoT Leaflet Compatibility Layer (MapLibre Backend)
 * Provides Leaflet-compatible L.* API using MapLibre GL as the underlying engine.
 * 
 * @version 1.3 - Added L_Class.include, MapLibre polyfills at top
 */

(function(global) {
    'use strict';

    // ============================================================
    // INITIALIZE GLOBAL L NAMESPACE - MUST be first
    // ============================================================
    global.L = global.L || {};

    // ============================================================
    // MAPLIBRE PROTOTYPE POLYFILLS - MUST be at top before any L_Class usage
    // ============================================================
    
    if (typeof maplibregl !== 'undefined') {
        // Save native methods before patching so we can delegate to them
        var _nativeAddLayer = maplibregl.Map.prototype.addLayer;
        var _nativeRemoveLayer = maplibregl.Map.prototype.removeLayer;

        maplibregl.Map.prototype.eachLayer = function(fn, context) {
            var self = this;
            this.style && this.style._layers && Object.keys(this.style._layers).forEach(function(id) {
                var layer = self.style._layers[id];
                if (layer) {
                    fn.call(context, {
                        _maplibreLayer: layer,
                        _layerId: id,
                        remove: function() {
                            if (self.getLayer && self.getLayer(id)) {
                                _nativeRemoveLayer.call(self, id);
                            }
                        }
                    });
                }
            });
            return this;
        };

        maplibregl.Map.prototype.hasLayer = function(layer) {
            if (typeof layer === 'string') {
                return !!(this.getLayer && this.getLayer(layer));
            } else if (layer && layer._layerId) {
                return !!(this.getLayer && this.getLayer(layer._layerId));
            }
            return false;
        };

        maplibregl.Map.prototype.removeLayer = function(layerOrId) {
            var id = typeof layerOrId === 'string' ? layerOrId :
                     (layerOrId && (layerOrId._layerId || layerOrId.id));
            if (!id) return this;
            try {
                if (this.getLayer && this.getLayer(id)) {
                    _nativeRemoveLayer.call(this, id);
                }
            } catch(e) {
                console.warn('[aot-leaflet-compat] removeLayer error:', e.message);
            }
            return this;
        };

        maplibregl.Map.prototype.addLayer = function(layer, before) {
            if (!layer) return this;
            // AoT layer groups are not native MapLibre layer specs — skip
            if (layer._isAoTLayerGroup) return this;
            try {
                return _nativeAddLayer.call(this, layer, before);
            } catch(e) {
                console.warn('[aot-leaflet-compat] addLayer error:', e.message);
            }
            return this;
        };
    }

    // ============================================================
    // UTIL - Utility functions (MUST be defined before L_Class)
    // ============================================================
    
    var L_Util = {
        extend: function(dest) {
            var sources = Array.prototype.slice.call(arguments, 1);
            for (var i = 0; i < sources.length; i++) {
                var src = sources[i];
                for (var key in src) {
                    if (src.hasOwnProperty(key)) {
                        dest[key] = src[key];
                    }
                }
            }
            return dest;
        },
        bind: function(func, context) {
            return function() {
                return func.apply(context, arguments);
            };
        },
        stamp: function(obj) {
            if (!obj._leaflet_id) {
                obj._leaflet_id = ++L_Util._idCounter;
            }
            return obj._leaflet_id;
        },
        falseFn: function() { return false; },
        requestAnimFrame: function(fn, context, immediate) {
            if (immediate) {
                fn.call(context);
            } else {
                setTimeout(function() { fn.call(context); }, 0);
            }
        },
        cancelAnimFrame: function(id) {
            clearTimeout(id);
        },
        _idCounter: 0,
        setOptions: function(obj, options) {
            if (!obj.options) obj.options = {};
            obj.options = L_Util.extend({}, obj.options, options);
            return obj;
        },
        template: function(str, data) {
            return str.replace(/\{ *([\w_]+) *\}/g, function(match, key) {
                var value = data[key];
                return value !== undefined ? value : '';
            });
        }
    };
    
    global.L_Util = L_Util;
    global.L.Util = L_Util;
    global.L.bind = L_Util.bind;
    global.L.setOptions = L_Util.setOptions;

    // ============================================================
    // CLASS SYSTEM - Fixed implementation without infinite recursion
    // ============================================================
    
    function L_Class() {
        // Base class constructor - no-op
    }

    // L_Class.include - adds properties to prototype
    L_Class.include = function(props) {
        L_Util.extend(this.prototype, props);
        return this;
    };

    // L_Class.extend - creates a new class that inherits from this class
    // Uses Object.create to avoid circular references
    L_Class.extend = function(props) {
        // Create the constructor for the new class
        function ExtendedClass() {
            // Call parent constructor if it exists
            if (this.initialize) {
                this.initialize.apply(this, arguments);
            }
        }
        
        // Inherit prototype from parent using Object.create (no circular reference)
        ExtendedClass.prototype = Object.create(this.prototype);
        ExtendedClass.prototype.constructor = ExtendedClass;
        
        // Add __super__ reference to parent prototype
        ExtendedClass.__super__ = this.prototype;
        
        // Copy static properties (extend method)
        ExtendedClass.extend = this.extend;
        
        // Copy own properties from props to the new prototype
        for (var key in props) {
            if (props.hasOwnProperty(key)) {
                ExtendedClass.prototype[key] = props[key];
            }
        }
        
        return ExtendedClass;
    };

    // Add to global L namespace
    global.L_Class = L_Class;
    global.L = global.L || {};
    global.L.Class = L_Class;
    global.L.extend = L_Class.extend;

    // ============================================================
    // DomEvent - DOM event handling utilities
    // ============================================================
    
    var L_DomEvent = {
        on: function(el, types, fn, context) {
            if (typeof types === 'object') {
                for (var type in types) {
                    this._on(el, type, types[type], context);
                }
            } else {
                types = types.split(/\s+/);
                for (var i = 0; i < types.length; i++) {
                    this._on(el, types[i], fn, context);
                }
            }
            return this;
        },
        _on: function(el, type, fn, context) {
            el.addEventListener(type, fn, false);
        },
        off: function(el, types, fn, context) {
            if (typeof types === 'object') {
                for (var type in types) {
                    this._off(el, type, types[type], context);
                }
            } else {
                types = types.split(/\s+/);
                for (var i = 0; i < types.length; i++) {
                    this._off(el, types[i], fn, context);
                }
            }
            return this;
        },
        _off: function(el, type, fn, context) {
            el.removeEventListener(type, fn, false);
        },
        stopPropagation: function(e) {
            if (e.stopPropagation) {
                e.stopPropagation();
            } else {
                e.cancelBubble = true;
            }
            return e;
        },
        preventDefault: function(e) {
            if (e.preventDefault) {
                e.preventDefault();
            } else {
                e.returnValue = false;
            }
            return e;
        },
        stop: function(e) {
            return this.stopPropagation(e) && this.preventDefault(e);
        },
        disableClickPropagation: function(el) {
            this.on(el, 'click', this.stop);
            this.on(el, 'mousedown', this.stop);
            this.on(el, 'touchstart', this.stop);
            return this;
        },
        disableScrollPropagation: function(el) {
            this.on(el, 'mousewheel', this.stopPropagation);
            this.on(el, 'DOMMouseScroll', this.stopPropagation);
            return this;
        },
        addListener: function(el, type, fn, context) {
            return this.on(el, type, fn, context);
        },
        removeListener: function(el, type, fn, context) {
            return this.off(el, type, fn, context);
        }
    };
    
    global.L_DomEvent = L_DomEvent;
    global.L.DomEvent = L_DomEvent;

    // ============================================================
    // EVENTED - Base class for event handling
    // ============================================================
    
    var L_Evented = L_Class.extend({
        initialize: function() {
            this._eventHandlers = {};
        },
        
        on: function(eventName, handler, context) {
            if (!this._eventHandlers) this._eventHandlers = {};
            if (!this._eventHandlers[eventName]) {
                this._eventHandlers[eventName] = [];
            }
            this._eventHandlers[eventName].push({
                handler: handler,
                context: context || this
            });
            return this;
        },
        
        off: function(eventName, handler, context) {
            if (!this._eventHandlers || !this._eventHandlers[eventName]) return this;
            
            if (!handler) {
                delete this._eventHandlers[eventName];
                return this;
            }
            
            var handlers = this._eventHandlers[eventName];
            for (var i = handlers.length - 1; i >= 0; i--) {
                if (handlers[i].handler === handler && 
                    (!context || handlers[i].context === context)) {
                    handlers.splice(i, 1);
                }
            }
            return this;
        },
        
        fire: function(eventName, data) {
            if (!this._eventHandlers || !this._eventHandlers[eventName]) return this;
            var handlers = this._eventHandlers[eventName];
            for (var i = 0; i < handlers.length; i++) {
                handlers[i].handler.call(handlers[i].context, data || {});
            }
            return this;
        },
        
        listens: function(eventName) {
            return !!(this._eventHandlers && this._eventHandlers[eventName]);
        }
    });

    global.L.Evented = L_Evented;

    // ============================================================
    // LAYER - Base layer class
    // ============================================================
    
    var L_Layer = L_Evented.extend({
        addTo: function(map) {
            if (map && map.addLayer) {
                map.addLayer(this);
            }
            return this;
        },
        
        remove: function() {
            if (this._map && this._map.removeLayer) {
                this._map.removeLayer(this);
            }
            return this;
        },
        
        removeFrom: function(map) {
            if (map && map.removeLayer) {
                map.removeLayer(this);
            }
            return this;
        },
        
        onAdd: function(map) {
            this._map = map;
        },
        
        onRemove: function(map) {
            delete this._map;
        }
    });
    var L_Layer = L_Evented.extend({
        // Popup state
        _popup: null,
        _popupContent: null,
        _popupOptions: {},
        
        addTo: function(map) {
            if (map && map.addLayer) {
                map.addLayer(this);
            }
            return this;
        },
        
        remove: function() {
            if (this._map && this._map.removeLayer) {
                this._map.removeLayer(this);
            }
            return this;
        },
        
        removeFrom: function(map) {
            if (map && map.removeLayer) {
                map.removeLayer(this);
            }
            return this;
        },
        
        onAdd: function(map) {
            this._map = map;
        },
        
        onRemove: function(map) {
            delete this._map;
        },
        
        // Popup methods - Leaflet API compatibility
        bindPopup: function(content, options) {
            this._popupContent = content;
            this._popupOptions = options || {};
            return this;
        },
        
        unbindPopup: function() {
            this._popupContent = null;
            this._popupOptions = {};
            return this;
        },
        
        getPopup: function() {
            return this._popupContent ? { getContent: function() { return this._popupContent; }.bind(this) } : null;
        },
        
        setPopupContent: function(content) {
            this._popupContent = content;
            return this;
        },
        
        openPopup: function(latlng) {
            if (!this._popupContent || !this._map) return this;
            if (this._map._openPopup) {
                this._map._openPopup(this, latlng, this._popupContent, this._popupOptions);
            }
            return this;
        },
        
        closePopup: function() {
            if (this._map && this._map._closePopup) {
                this._map._closePopup(this);
            }
            return this;
        },
        
        // Tooltip methods - Leaflet API compatibility
        bindTooltip: function(content, options) {
            this._tooltipContent = content;
            this._tooltipOptions = options || {};
            return this;
        },
        
        unbindTooltip: function() {
            this._tooltipContent = null;
            this._tooltipOptions = {};
            return this;
        },
        
        openTooltip: function(latlng) {
            return this;
        },
        
        closeTooltip: function() {
            return this;
        }
    });

    global.L.Layer = L_Layer;

    // ============================================================
    // CONTROL - Base control class
    // ============================================================
    
    var L_Control = L_Class.extend({
        options: {
            position: 'topright'
        },
        
        initialize: function(options) {
            L.setOptions(this, options);
        },
        
        addTo: function(map) {
            this._map = map;
            map.addControl(this);
            return this;
        },
        
        remove: function() {
            if (this._map) {
                this._map.removeControl(this);
            }
            return this;
        },
        
        getContainer: function() {
            return this._container;
        }
    });

    // Static extend for L.Control
    L_Control.extend = L_Class.extend;

    global.L.Control = L_Control;

    // ============================================================
    // DOM UTIL - DOM manipulation utilities
    // ============================================================
    
    var L_DomUtil = {
        create: function(tagName, className, container) {
            var el = document.createElement(tagName);
            if (className) el.className = className;
            if (container) container.appendChild(el);
            return el;
        },
        
        get: function(id) {
            return typeof id === 'string' ? document.getElementById(id) : id;
        },
        
        addClass: function(el, className) {
            if (el.classList) {
                el.classList.add(className);
            } else {
                var classes = el.className.split(' ');
                if (classes.indexOf(className) < 0) {
                    el.className += ' ' + className;
                }
            }
        },
        
        removeClass: function(el, className) {
            if (el.classList) {
                el.classList.remove(className);
            } else {
                el.className = el.className.replace(new RegExp('\\b' + className + '\\b', 'g'), '');
            }
        },
        
        setStyle: function(el, style) {
            for (var prop in style) {
                el.style[prop] = style[prop];
            }
        },
        
        getStyle: function(el, prop) {
            return window.getComputedStyle(el)[prop];
        },
        
        setOpacity: function(el, opacity) {
            el.style.opacity = opacity;
        },
        
        hasClass: function(el, className) {
            return el.classList ? el.classList.contains(className) : false;
        }
    };

    global.L.DomUtil = L_DomUtil;

    // ============================================================
    // DOM EVENT - Event handling utilities
    // ============================================================
    
    var L_DomEvent = {
        addListener: function(el, type, handler, context) {
            var wrappedHandler = function(e) {
                handler.call(context || this, e || window.event);
            };
            el.addEventListener(type, wrappedHandler);
            return {
                element: el,
                type: type,
                handler: wrappedHandler
            };
        },
        
        removeListener: function(listener) {
            listener.element.removeEventListener(listener.type, listener.handler);
        },
        
        on: function(el, types, handler, context) {
            var listeners = [];
            var typesArr = types.split(' ');
            for (var i = 0; i < typesArr.length; i++) {
                if (typesArr[i]) {
                    listeners.push(this.addListener(el, typesArr[i], handler, context));
                }
            }
            return listeners;
        },
        
        off: function(el, type, handler, context) {
            el.removeEventListener(type, handler);
        },
        
        stopPropagation: function(e) {
            if (e.stopPropagation) {
                e.stopPropagation();
            } else {
                e.cancelBubble = true;
            }
        },
        
        preventDefault: function(e) {
            if (e.preventDefault) {
                e.preventDefault();
            } else {
                e.returnValue = false;
            }
        },
        
        disableScrollPropagation: function(el) {
            // No-op polyfill
        },
        
        disableClickPropagation: function(el) {
            // No-op polyfill
        }
    };

    global.L.DomEvent = L_DomEvent;

    // ============================================================
    // BROWSER - Browser detection
    // ============================================================
    
    var L_Browser = {
        ie: false,
        ie6: false,
        ie7: false,
        edge: false,
        chrome: !!window.chrome,
        firefox: typeof InstallTrigger !== 'undefined',
        safari: Object.prototype.toString.call(window.HTMLElement).indexOf('Constructor') > 0,
        opera: !!window.opera || navigator.userAgent.indexOf('Opera') >= 0,
        webkit: navigator.userAgent.indexOf('AppleWebKit/') >= 0
    };

    Object.defineProperty(L_Browser, 'retina', {
        get: function() {
            return window.devicePixelRatio && window.devicePixelRatio >= 2;
        }
    });

    global.L.Browser = L_Browser;

    // ============================================================
    // FORMAT - Number formatting utilities
    // ============================================================
    
    global.L.format = {
        bind: function(func, context) {
            return L_Util.bind(func, context);
        }
    };

    // ============================================================
    // TRANSITION - Animation utilities
    // ============================================================
    
    var L_Transition = {
        addTransition: function(el, props, duration) {
            // No-op polyfill for transitions
        },
        
        removeTransition: function(el) {
            // No-op polyfill
        }
    };

    global.L.Transition = L_Transition;

    // ============================================================
    // DIV ICON - Custom HTML icon
    // ============================================================
    
    var L_DivIcon = L_Class.extend({
        options: {
            className: '',
            html: '',
            iconSize: [30, 30],
            iconAnchor: [15, 15]
        },
        
        initialize: function(options) {
            L.setOptions(this, options);
        },
        
        createIcon: function() {
            var div = document.createElement('div');
            div.innerHTML = this.options.html;
            if (this.options.className) {
                div.className = this.options.className;
            }
            return div;
        }
    });

    global.L.DivIcon = L_DivIcon;

    // ============================================================
    // TOOLTIP - Tooltip class
    // ============================================================
    
    var L_Tooltip = L_Class.extend({
        options: {
            className: 'leaflet-tooltip'
        }
    });

    global.L.Tooltip = L_Tooltip;

    // ============================================================
    // POPUP - Popup class
    // ============================================================
    
    var L_Popup = L_Class.extend({
        options: {
            className: 'leaflet-popup'
        }
    });

    global.L.Popup = L_Popup;

    // ============================================================
    // HANDLER - Base handler class
    // ============================================================
    
    var L_Handler = L_Class.extend({
        initialize: function(map) {
            this._map = map;
        },
        
        enable: function() {
            this._enabled = true;
            this.addHooks();
        },
        
        disable: function() {
            this._enabled = false;
            this.removeHooks();
        },
        
        enabled: function() {
            return !!this._enabled;
        }
    });

    global.L.Handler = L_Handler;

    // ============================================================
    // TILE LAYER - Tile layer class
    // ============================================================
    
    var L_TileLayer = L_Layer.extend({
        options: {
            attribution: '',
            minZoom: 0,
            maxZoom: 18,
            tileSize: 256,
            subdomains: 'abc',
            errorTileUrl: '',
            zoomOffset: 0,
            opacity: 1,
            zoomInverse: false,
            maxNativeZoom: null,
            minNativeZoom: null,
            bounds: null,
            continuousWorld: false,
            noWrap: false,
            pane: 'tilePane'
        },
        
        initialize: function(urlTemplate, options) {
            this._url = urlTemplate;
            L.setOptions(this, options);
        },
        
        getTileUrl: function(coords) {
            var data = {
                r: L_Browser.retina ? '@2x' : '',
                s: this._getSubdomain(coords),
                x: coords.x,
                y: coords.y,
                z: this._getZoomForUrl()
            };
            return L.Util.template(this._url, data);
        },
        
        _getZoomForUrl: function() {
            var zoom = this._map.getZoom();
            if (this.options.zoomReverse) {
                zoom = this.options.maxZoom - zoom;
            }
            return zoom + this.options.zoomOffset;
        },
        
        _getSubdomain: function(coords) {
            var index = (coords.x + coords.y) % this.options.subdomains.length;
            return this.options.subdomains[index];
        },
        
        onAdd: function(map) {
            L_Layer.prototype.onAdd.call(this, map);
            this._map = map;
        },
        
        onRemove: function(map) {
            L_Layer.prototype.onRemove.call(this, map);
            delete this._map;
        }
    });

    // Static extend for L.TileLayer
    L_TileLayer.extend = L_Class.extend;

    global.L.TileLayer = L_TileLayer;

    // ============================================================
    // TILE LAYER FACTORY - L.tileLayer() function
    // ============================================================
    
    global.L.tileLayer = function(urlTemplate, options) {
        return new L_TileLayer(urlTemplate, options);
    };

    // ============================================================
    // LAYER GROUP - Group of layers
    // ============================================================
    
    var L_LayerGroup = L_Layer.extend({
        initialize: function(layers) {
            this._layers = {};
            if (layers) {
                for (var i = 0; i < layers.length; i++) {
                    this.addLayer(layers[i]);
                }
            }
        },
        
        addLayer: function(layer) {
            var id = this._getLayerId(layer);
            this._layers[id] = layer;
            if (this._map) {
                layer.addTo(this._map);
            }
            return this;
        },
        
        removeLayer: function(layer) {
            var id = layer in this._layers ? layer : this._getLayerId(layer);
            delete this._layers[id];
            if (this._map && layer.remove) {
                layer.remove();
            }
            return this;
        },
        
        clearLayers: function() {
            for (var id in this._layers) {
                this.removeLayer(this._layers[id]);
            }
            return this;
        },
        
        eachLayer: function(fn, context) {
            for (var id in this._layers) {
                fn.call(context, this._layers[id]);
            }
            return this;
        },
        
        hasLayer: function(layer) {
            var id = layer in this._layers ? layer : this._getLayerId(layer);
            return !!this._layers[id];
        },
        
        getLayer: function(id) {
            return this._layers[id];
        },
        
        getLayers: function() {
            var layers = [];
            for (var id in this._layers) {
                layers.push(this._layers[id]);
            }
            return layers;
        },
        
        _getLayerId: function(layer) {
            return L_Util.stamp(layer);
        },
        
        onAdd: function(map) {
            L_Layer.prototype.onAdd.call(this, map);
            for (var id in this._layers) {
                var layer = this._layers[id];
                if (layer.addTo) {
                    layer.addTo(map);
                }
            }
        },
        
        onRemove: function(map) {
            L_Layer.prototype.onRemove.call(this, map);
            for (var id in this._layers) {
                var layer = this._layers[id];
                if (layer.remove) {
                    layer.remove();
                }
            }
        }
    });

    global.L.LayerGroup = L_LayerGroup;

    // ============================================================
    // LAYER GROUP FACTORY - L.layerGroup() function
    // ============================================================
    
    global.L.layerGroup = function(layers) {
        return new L_LayerGroup(layers);
    };

    // ============================================================
    // GEO JSON - GeoJSON layer
    // ============================================================
    
    var L_GeoJSON = L_Layer.extend({
        options: {
            style: function() { return {}; },
            pointToLayer: function(geoJsonPoint, latlng) {
                return L.marker(latlng);
            },
            onEachFeature: function() {},
            filter: function() { return true; }
        },
        
        initialize: function(geojson, options) {
            L.setOptions(this, options);
            this._geojson = geojson;
        },
        
        addData: function(geojson) {
            if (geojson && this.options.filter(geojson)) {
                this.fire('data', { layer: geojson });
            }
        },
        
        setStyle: function(style) {
            this.options.style = style;
        }
    });

    global.L.GeoJSON = L_GeoJSON;

    // ============================================================
    // GEO JSON FACTORY - L.geoJSON() function
    // ============================================================
    
    global.L.geoJSON = function(geojson, options) {
        return new L_GeoJSON(geojson, options);
    };

    // ============================================================
    // MARKER - Marker class
    // ============================================================
    
    var L_Marker = L_Layer.extend({
        options: {
            icon: undefined,
            title: '',
            alt: '',
            clickable: true,
            draggable: false
        },
        
        initialize: function(latlng, options) {
            L.setOptions(this, options);
            this._latlng = latlng;
        },
        
        setLatLng: function(latlng) {
            this._latlng = latlng;
            if (this._map) {
                this.update();
            }
            return this;
        },
        
        getLatLng: function() {
            return this._latlng;
        },
        
        setIcon: function(icon) {
            this.options.icon = icon;
            if (this._map) {
                this.update();
            }
            return this;
        },
        
        getElement: function() {
            return this._icon;
        }
    });

    global.L.Marker = L_Marker;

    // ============================================================
    // MARKER FACTORY - L.marker() function
    // ============================================================
    
    global.L.marker = function(latlng, options) {
        return new L_Marker(latlng, options);
    };

    // ============================================================
    // CIRCLE MARKER - Circle marker class
    // ============================================================
    
    var L_CircleMarker = L_Layer.extend({
        options: {
            radius: 10,
            color: '#3388ff',
            weight: 2,
            opacity: 1,
            fillColor: undefined,
            fillOpacity: 0.2
        },

        initialize: function(latlng, options) {
            L.setOptions(this, options);
            this._latlng = latlng;
        },

        setLatLng: function(latlng) {
            this._latlng = latlng;
            return this;
        },

        getLatLng: function() {
            return this._latlng;
        },

        setStyle: function(options) {
            L.setOptions(this, options);
            return this;
        },

        // ----- Popup Methods -----
        bindPopup: function(content, options) {
            this._popupContent = content;
            this._popupOptions = options || {};
            return this;
        },

        unbindPopup: function() {
            this._popupContent = null;
            return this;
        },

        getPopup: function() {
            if (!this._popupContent) return null;
            var self = this;
            return { getContent: function() { return self._popupContent; } };
        },

        openPopup: function(latlng) {
            if (!this._popupContent || !this._map) return this;
            if (this._map._openPopup) {
                this._map._openPopup(this, latlng, this._popupContent, this._popupOptions);
            }
            return this;
        },

        closePopup: function() {
            if (this._map && this._map._closePopup) {
                this._map._closePopup(this);
            }
            return this;
        },

        // ----- Tooltip Methods -----
        bindTooltip: function(content, options) {
            this._tooltipContent = content;
            this._tooltipOptions = options || {};
            return this;
        },

        unbindTooltip: function() {
            this._tooltipContent = null;
            return this;
        },

        getTooltip: function() {
            if (!this._tooltipContent) return null;
            var self = this;
            return { getContent: function() { return self._tooltipContent; } };
        },

        // ----- GeoJSON Conversion -----
        toGeoJSON: function() {
            return {
                type: 'Feature',
                properties: this.options || {},
                geometry: {
                    type: 'Point',
                    coordinates: [this._latlng.lng, this._latlng.lat]
                }
            };
        }
    });

    global.L.CircleMarker = L_CircleMarker;

    // ============================================================
    // CIRCLE MARKER FACTORY - L.circleMarker() function
    // ============================================================
    
    global.L.circleMarker = function(latlng, options) {
        return new L_CircleMarker(latlng, options);
    };

    // ============================================================
    // CIRCLE - Circle class
    // ============================================================
    
    var L_Circle = L_Layer.extend({
        options: {
            radius: 100
        },

        initialize: function(latlng, radius, options) {
            L.setOptions(this, options);
            this._latlng = latlng;
            this._mRadius = radius;
        },

        setLatLng: function(latlng) {
            this._latlng = latlng;
            return this;
        },

        getLatLng: function() {
            return this._latlng;
        },

        setRadius: function(radius) {
            this._mRadius = radius;
            return this;
        },

        getRadius: function() {
            return this._mRadius;
        },

        setStyle: function(style) {
            L.setOptions(this, style);
            return this;
        },

        // ----- Popup Methods -----
        bindPopup: function(content, options) {
            this._popupContent = content;
            this._popupOptions = options || {};
            return this;
        },

        unbindPopup: function() {
            this._popupContent = null;
            return this;
        },

        getPopup: function() {
            if (!this._popupContent) return null;
            var self = this;
            return { getContent: function() { return self._popupContent; } };
        },

        openPopup: function(latlng) {
            if (!this._popupContent || !this._map) return this;
            if (this._map._openPopup) {
                this._map._openPopup(this, latlng, this._popupContent, this._popupOptions);
            }
            return this;
        },

        closePopup: function() {
            if (this._map && this._map._closePopup) {
                this._map._closePopup(this);
            }
            return this;
        },

        // ----- Tooltip Methods -----
        bindTooltip: function(content, options) {
            this._tooltipContent = content;
            this._tooltipOptions = options || {};
            return this;
        },

        unbindTooltip: function() {
            this._tooltipContent = null;
            return this;
        },

        getTooltip: function() {
            if (!this._tooltipContent) return null;
            var self = this;
            return { getContent: function() { return self._tooltipContent; } };
        },

        // ----- GeoJSON Conversion -----
        toGeoJSON: function() {
            return {
                type: 'Feature',
                properties: this.options || {},
                geometry: {
                    type: 'Point',
                    coordinates: [this._latlng.lng, this._latlng.lat]
                }
            };
        }
    });

    global.L.Circle = L_Circle;

    // ============================================================
    // CIRCLE FACTORY - L.circle() function
    // ============================================================
    
    global.L.circle = function(latlng, radius, options) {
        return new L_Circle(latlng, radius, options);
    };

    // ============================================================
    // POLYLINE - Polyline class
    // ============================================================
    
    var L_Polyline = L_Layer.extend({
        options: {
            smoothFactor: 1,
            noClip: false,
            color: '#3388ff',
            weight: 3,
            opacity: 1
        },
        
        initialize: function(latlngs, options) {
            L.setOptions(this, options);
            this._latlngs = latlngs;
        },
        
        setLatLngs: function(latlngs) {
            this._latlngs = latlngs;
            return this;
        },
        
        getLatLngs: function() {
            return this._latlngs;
        },
        
        addLatLng: function(latlng) {
            this._latlngs.push(latlng);
            return this;
        },

        // ----- Popup Methods -----
        bindPopup: function(content, options) {
            this._popupContent = content;
            this._popupOptions = options || {};
            return this;
        },

        unbindPopup: function() {
            this._popupContent = null;
            this._popupOptions = {};
            return this;
        },

        getPopup: function() {
            if (!this._popupContent) return null;
            var self = this;
            return {
                getContent: function() { return self._popupContent; }
            };
        },

        setPopupContent: function(content) {
            this._popupContent = content;
            return this;
        },

        openPopup: function(latlng) {
            if (!this._popupContent || !this._map) return this;
            if (this._map._openPopup) {
                this._map._openPopup(this, latlng, this._popupContent, this._popupOptions);
            }
            return this;
        },

        closePopup: function() {
            if (this._map && this._map._closePopup) {
                this._map._closePopup(this);
            }
            return this;
        },

        // ----- Tooltip Methods -----
        bindTooltip: function(content, options) {
            this._tooltipContent = content;
            this._tooltipOptions = options || {};
            return this;
        },

        unbindTooltip: function() {
            this._tooltipContent = null;
            this._tooltipOptions = {};
            return this;
        },

        getTooltip: function() {
            if (!this._tooltipContent) return null;
            var self = this;
            return {
                getContent: function() { return self._tooltipContent; }
            };
        },

        openTooltip: function(latlng) {
            return this;
        },

        closeTooltip: function() {
            return this;
        },

        // ----- Style Methods -----
        setStyle: function(style) {
            if (!style) return this;
            if (style.color !== undefined) this.options.color = style.color;
            if (style.fillColor !== undefined) this.options.fillColor = style.fillColor;
            if (style.weight !== undefined) this.options.weight = style.weight;
            if (style.opacity !== undefined) this.options.opacity = style.opacity;
            if (style.fillOpacity !== undefined) this.options.fillOpacity = style.fillOpacity;
            if (style.dashArray !== undefined) this.options.dashArray = style.dashArray;
            if (style.radius !== undefined) this.options.radius = style.radius;
            return this;
        },

        // ----- GeoJSON Conversion -----
        toGeoJSON: function() {
            var coords = [];
            if (this._latlngs && this._latlngs.length > 0) {
                var isPolygon = this instanceof L_Polygon;
                coords = this._latlngs.map(function(ll) {
                    return [ll.lng, ll.lat];
                });
                // Close polygon ring if not already closed
                if (isPolygon && coords.length > 0) {
                    var first = coords[0];
                    var last = coords[coords.length - 1];
                    if (first[0] !== last[0] || first[1] !== last[1]) {
                        coords.push([first[0], first[1]]);
                    }
                }
            }

            var geomType = 'LineString';
            if (this instanceof L_Polygon) {
                geomType = 'Polygon';
                coords = [coords]; // Wrap in array for polygon
            }

            return {
                type: 'Feature',
                properties: this.options || {},
                geometry: {
                    type: geomType,
                    coordinates: coords
                }
            };
        }
    });

    global.L.Polyline = L_Polyline;

    // ============================================================
    // POLYLINE FACTORY - L.polyline() function
    // ============================================================
    
    global.L.polyline = function(latlngs, options) {
        return new L_Polyline(latlngs, options);
    };

    // ============================================================
    // POLYGON - Polygon class
    // ============================================================
    
    var L_Polygon = L_Polyline.extend({
        options: {
            fillColor: undefined,
            fillOpacity: 0.2
        }
    });

    global.L.Polygon = L_Polygon;

    // ============================================================
    // POLYGON FACTORY - L.polygon() function
    // ============================================================
    
    global.L.polygon = function(latlngs, options) {
        return new L_Polygon(latlngs, options);
    };

    // ============================================================
    // CONTROL.DRAW - Draw control
    // ============================================================
    
    var L_Control_Draw = L_Control.extend({
        options: {
            position: 'topright',
            draw: {},
            edit: false
        }
    });

    global.L.Control.Draw = L_Control_Draw;

    // ============================================================
    // DRAW - Draw module
    // ============================================================
    
    global.L.Draw = {
        Event: {
            CREATED: 'draw:created',
            EDITED: 'draw:edited',
            DELETED: 'draw:deleted',
            DRAWSTART: 'draw:drawstart',
            DRAWSTOP: 'draw:drawstop',
            DRAWVERTEX: 'draw:drawvertex'
        }
    };

    // ============================================================
    // OPTIONS - Set options helper
    // ============================================================
    
    L_Class.include({
        setOptions: function(options) {
            if (!this.options) this.options = {};
            this.options = L_Util.extend({}, this.options, options);
            return this;
        }
    });

    // ============================================================
    // LATLng - Geographic point
    // ============================================================
    
    var L_LatLng = function(lat, lng, alt) {
        if (Array.isArray(lat)) {
            this.lat = parseFloat(lat[0]);
            this.lng = parseFloat(lat[1]);
            this.alt = alt !== undefined ? alt : (lat[2] !== undefined ? parseFloat(lat[2]) : undefined);
        } else if (lat !== undefined && lat !== null) {
            this.lat = parseFloat(lat);
            this.lng = parseFloat(lng);
            this.alt = alt !== undefined ? parseFloat(alt) : undefined;
        }
    };
    
    L_LatLng.prototype = {
        equals: function(other) {
            if (!other) return false;
            return Math.abs(this.lat - other.lat) < 1e-9 && Math.abs(this.lng - other.lng) < 1e-9;
        },
        toString: function() {
            return 'LatLng(' + this.lat + ', ' + this.lng + ')';
        },
        distanceTo: function(other) {
            var R = 6371000; // Earth radius in meters
            var dLat = (other.lat - this.lat) * Math.PI / 180;
            var dLng = (other.lng - this.lng) * Math.PI / 180;
            var a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                    Math.cos(this.lat * Math.PI / 180) * Math.cos(other.lat * Math.PI / 180) *
                    Math.sin(dLng/2) * Math.sin(dLng/2);
            var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            return R * c;
        }
    };
    
    global.L.LatLng = L_LatLng;
    global.L.latLng = function(lat, lng, alt) {
        return new L_LatLng(lat, lng, alt);
    };

    // ============================================================
    // LATLngBounds - Geographic bounds
    // ============================================================
    
    var L_LatLngBounds = function(corner1, corner2) {
        if (!corner1) return this;
        var latlngs = corner2 ? [corner1, corner2] : corner1;
        var minLat = Infinity, minLng = Infinity, maxLat = -Infinity, maxLng = -Infinity;
        for (var i = 0; i < latlngs.length; i++) {
            var latlng = latlngs[i];
            if (latlng.lat !== undefined) {
                minLat = Math.min(minLat, latlng.lat);
                minLng = Math.min(minLng, latlng.lng);
                maxLat = Math.max(maxLat, latlng.lat);
                maxLng = Math.max(maxLng, latlng.lng);
            } else if (latlng[0] !== undefined) {
                minLat = Math.min(minLat, latlng[0]);
                minLng = Math.min(minLng, latlng[1]);
                maxLat = Math.max(maxLat, latlng[0]);
                maxLng = Math.max(maxLng, latlng[1]);
            }
        }
        this._southWest = { lat: minLat, lng: minLng };
        this._northEast = { lat: maxLat, lng: maxLng };
    };
    
    L_LatLngBounds.prototype = {
        extend: function(latlng) {
            if (latlng.lat !== undefined) {
                if (latlng.lat < this._southWest.lat) this._southWest.lat = latlng.lat;
                if (latlng.lng < this._southWest.lng) this._southWest.lng = latlng.lng;
                if (latlng.lat > this._northEast.lat) this._northEast.lat = latlng.lat;
                if (latlng.lng > this._northEast.lng) this._northEast.lng = latlng.lng;
            }
            return this;
        },
        getSouthWest: function() { return this._southWest; },
        getNorthEast: function() { return this._northEast; },
        getWest: function() { return this._southWest.lng; },
        getSouth: function() { return this._southWest.lat; },
        getEast: function() { return this._northEast.lng; },
        getNorth: function() { return this._northEast.lat; },
        isValid: function() { return !isNaN(this._southWest.lat); },
        contains: function(latlng) {
            var lat = latlng.lat !== undefined ? latlng.lat : latlng[0];
            var lng = latlng.lng !== undefined ? latlng.lng : latlng[1];
            return lat >= this._southWest.lat && lat <= this._northEast.lat &&
                   lng >= this._southWest.lng && lng <= this._northEast.lng;
        },
        intersects: function(other) {
            return this._southWest.lat <= other._northEast.lat &&
                   this._northEast.lat >= other._southWest.lat &&
                   this._southWest.lng <= other._northEast.lng &&
                   this._northEast.lng >= other._southWest.lng;
        },
        getCenter: function() {
            return {
                lat: (this._southWest.lat + this._northEast.lat) / 2,
                lng: (this._southWest.lng + this._northEast.lng) / 2
            };
        }
    };
    
    global.L.LatLngBounds = L_LatLngBounds;
    global.L.latLngBounds = function(corner1, corner2) {
        return new L_LatLngBounds(corner1, corner2);
    };
    
    // ============================================================
    // Icon factory functions
    // ============================================================
    
    var L_Icon = L_Class.extend({
        options: {
            iconUrl: '',
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [0, -41]
        },
        createIcon: function() {
            return null;
        }
    });
    
    var L_DivIcon = L_Icon.extend({
        options: {
            html: '',
            className: '',
            iconSize: null,
            iconAnchor: null,
            popupAnchor: null
        },
        createIcon: function() {
            var div = document.createElement('div');
            if (this.options.html) {
                div.innerHTML = this.options.html;
            }
            if (this.options.className) {
                div.className = this.options.className;
            }
            return div;
        }
    });
    
    global.L.Icon = L_Icon;
    global.L.DivIcon = global.L.DivIcon || L_DivIcon;
    global.L.icon = function(options) {
        return new L_Icon(options);
    };
    global.L.divIcon = function(options) {
        return new L_DivIcon(options);
    };
    
    // ============================================================
    // ADDITIONAL COMMON APIs
    // ============================================================
    
    // Leaflet version stub
    global.L.version = '1.9.4-compat';
    
    // Control.Layers - Basic implementation
    var L_Control_Layers = L_Control.extend({
        options: {
            collapsed: true,
            autoZIndex: true
        }
    });
    global.L.Control.Layers = L_Control_Layers;
    
    // Control.Zoom - Basic implementation
    var L_Control_Zoom = L_Control.extend({
        options: {
            position: 'topright'
        }
    });
    global.L.Control.Zoom = L_Control_Zoom;
    
    // Control.Scale - Basic implementation
    var L_Control_Scale = L_Control.extend({
        options: {
            position: 'bottomleft',
            maxWidth: 100,
            metric: true,
            imperial: true
        }
    });
    global.L.Control.Scale = L_Control_Scale;
    
    // Control.Attribution - Basic implementation
    var L_Control_Attribution = L_Control.extend({
        options: {
            position: 'bottomright',
            prefix: 'Powered by Leaflet'
        }
    });
    global.L.Control.Attribution = L_Control_Attribution;
    
    // ============================================================
    // INITIALIZATION COMPLETE
    // ============================================================
    

})(window);

