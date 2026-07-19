/**
 * Map Dependency Loader
 * Handles parallel loading of Leaflet, Leaflet Draw, and internal map scripts.
 */
(function (window) {
    'use strict';

    window.aotScriptLoaders = window.aotScriptLoaders || {};
    window.aotCssLoaders = window.aotCssLoaders || {};
    const DEFAULT_BUNDLE = '/static/js/map/bundles/aot-map-bundle.js?v=force_reload';

    function loadScript(src) {
        if (window.aotScriptLoaders[src]) {
            return window.aotScriptLoaders[src];
        }
        const promise = new Promise(function (resolve, reject) {
            if (document.querySelector('script[src="' + src + '"]')) {
                resolve();
                return;
            }
            const script = document.createElement('script');
            script.src = src;
            script.async = true;
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
        window.aotScriptLoaders[src] = promise;
        return promise;
    }

    function loadModule(src) {
        if (window.aotScriptLoaders[src]) {
            return window.aotScriptLoaders[src];
        }
        const promise = import(src).catch(function (err) {
            console.error('Failed to load module:', src, err);
            throw err;
        });
        window.aotScriptLoaders[src] = promise;
        return promise;
    }

    function loadCss(href) {
        if (window.aotCssLoaders[href]) return;
        if (document.querySelector('link[href*="' + href + '"]')) {
            window.aotCssLoaders[href] = true;
            return;
        }
        const css = document.createElement('link');
        css.rel = 'stylesheet';
        css.href = href;
        document.head.appendChild(css);
        window.aotCssLoaders[href] = true;
    }

    /**
     * Loads Leaflet, Leaflet Draw, MapLibre-GL, and optional internal scripts in sequence.
     * [GIS Pure MapLibre v4.0] Leaflet CSS is loaded in layout.html or not at all.
     * Leaflet Draw CSS not needed - MapLibre Draw is used instead.
     * @param {Object} config - Configuration object
     * @param {string} config.bundleUrl - URL for unified AoT map bundle (defaults to /static/js/map/bundles/aot-map-bundle.js)
     * @param {boolean} config.enableVector - Enable MapLibre-GL vector tile support (default: true)
     * @param {boolean} [config.loadLeaflet=false] - Load Leaflet (not required for MapLibre-only pages)
     * @returns {Promise} Resolves when all scripts are loaded
     */
    function loadMapDependencies(config) {
        config = config || {};
        var loadLeaflet = config.loadLeaflet === true;

        // 1. Start loading MapLibre-GL CSS (Priority for 3D)
        loadCss('/static/vendor/maplibre-gl-4.1.2/maplibre-gl.css');

        // 1b. [GIS Pure MapLibre v4.0] Leaflet CSS no longer loaded by default
        // If explicitly requested, load for backward compatibility only
        if (loadLeaflet) {
            loadCss('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
        }

        // 2. Load MapLibre-GL JS (Vector Tile Support - Required for 3D)
        var pMapLibre = loadScript('/static/vendor/maplibre-gl-4.1.2/maplibre-gl.js');

        // 2b. Load Leaflet only if explicitly requested (backward compatibility)
        var pLeaflet = Promise.resolve();
        if (loadLeaflet) {
            pLeaflet = loadScript('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js');
            // 3. After Leaflet, load Leaflet Draw (only if Leaflet is loaded)
            pLeaflet = pLeaflet.then(function() {
                return loadScript('https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js')
                    .catch(function(err) { console.error('Failed to load Leaflet.draw:', err); });
            }).catch(function(err) { console.error('Failed to load Leaflet:', err); });
        }

        // 5. Load MapClient (only if Leaflet is loaded)
        var pClient = Promise.resolve();
        if (loadLeaflet) {
            pClient = pLeaflet.then(function() {
                return loadScript('/static/js/map/bundles/aot-map-client.js')
                    .catch(function(err) { console.error('Failed to load MapClient:', err); });
            });
        }

        const bundleUrl = config.bundleUrl || DEFAULT_BUNDLE;
        // [GIS Pure MapLibre v4.0] ES Module Bundle may not be needed for MapLibre-only pages
        var pBundle = Promise.resolve();
        if (bundleUrl) {
            pBundle = Promise.all([pLeaflet, pClient, pMapLibre]).then(function() {
                return loadModule(bundleUrl);
            });
        }

        // 6. Wait for ALL scripts (MapLibre is now the priority)
        return Promise.all([pLeaflet, pClient, pBundle, pMapLibre]);
    }

    /**
     * Explicitly load MapLibre-GL JS and CSS from CDN.
     * Resolves immediately if already loaded; handles concurrent calls via deduplication.
     * Includes fallback handling when CDN load fails.
     *
     * @param {Object} [config] - Loader configuration
     * @param {string} [config.version='4.1.2'] - MapLibre version
     * @param {string} [config.cdnBase='https://unpkg.com'] - CDN base URL
     * @param {number} [config.timeout=15000] - Timeout in ms
     * @returns {Promise<boolean>} Resolves true when maplibregl is available; rejects on failure
     */
    function loadMapLibre(config) {
        config = config || {};
        var version = config.version || '4.1.2';
        var cdnBase = config.cdnBase || 'https://unpkg.com';
        var timeout = config.timeout || 15000;

        // Already loaded — resolve immediately
        if (typeof window.maplibregl !== 'undefined') {
            console.log('[AOT_MAP_LOADER.loadMapLibre] maplibregl already loaded (version: ' + window.maplibregl.version + ')');
            return Promise.resolve(true);
        }

        // Deduplicate concurrent calls
        if (window.__aotMapLibreLoadPromise) {
            return window.__aotMapLibreLoadPromise;
        }

        window.__aotMapLibreLoadPromise = new Promise(function(resolve, reject) {
            var timedOut = false;
            var timer = setTimeout(function() {
                timedOut = true;
                reject(new Error('[AOT_MAP_LOADER.loadMapLibre] CDN load timed out after ' + timeout + 'ms'));
            }, timeout);

            var cssUrl = cdnBase + '/maplibre-gl@' + version + '/dist/maplibre-gl.css';
            var jsUrl  = cdnBase + '/maplibre-gl@' + version + '/dist/maplibre-gl.js';

            // Load CSS first, then JS
            loadCss(cssUrl).then(function() {
                return loadScript(jsUrl);
            }).then(function() {
                clearTimeout(timer);
                if (typeof window.maplibregl === 'undefined') {
                    reject(new Error('[AOT_MAP_LOADER.loadMapLibre] Script loaded but window.maplibregl is undefined — CDN returned an invalid file'));
                } else {
                    console.log('[AOT_MAP_LOADER.loadMapLibre] Loaded maplibregl version: ' + window.maplibregl.version);
                    resolve(true);
                }
            }).catch(function(err) {
                clearTimeout(timer);
                reject(err);
            });
        });

        return window.__aotMapLibreLoadPromise;
    }

    /**
     * Load @maplibre/maplibre-gl-draw plugin from CDN.
     * Requires maplibregl to be loaded first (call loadMapLibre first).
     *
     * @param {Object} [config] - Loader configuration
     * @param {string} [config.version='1.4.3'] - Draw plugin version
     * @param {string} [config.cdnBase='https://unpkg.com'] - CDN base URL
     * @returns {Promise<boolean>} Resolves true when MapLibreDrawControl is available
     */
    function loadMapLibreDraw(config) {
        config = config || {};
        var version = config.version || '1.4.3';
        var cdnBase = config.cdnBase || 'https://unpkg.com';

        if (typeof window.MapLibreDrawControl !== 'undefined') {
            console.log('[AOT_MAP_LOADER.loadMapLibreDraw] MapLibreDrawControl already loaded');
            return Promise.resolve(true);
        }

        if (typeof window.maplibregl === 'undefined') {
            return Promise.reject(new Error('[AOT_MAP_LOADER.loadMapLibreDraw] maplibregl must be loaded first'));
        }

        if (window.__aotMapLibreDrawLoadPromise) {
            return window.__aotMapLibreDrawLoadPromise;
        }

        window.__aotMapLibreDrawLoadPromise = new Promise(function(resolve, reject) {
            var cssUrl = cdnBase + '/@maplibre/maplibre-gl-draw@' + version + '/dist/maplibre-gl-draw.css';
            var jsUrl  = cdnBase + '/@maplibre/maplibre-gl-draw@' + version + '/dist/maplibre-gl-draw.js';

            // Inject CSS (non-blocking)
            if (!document.querySelector('link[href*="maplibre-gl-draw"]')) {
                var link = document.createElement('link');
                link.rel = 'stylesheet';
                link.href = cssUrl;
                document.head.appendChild(link);
            }

            // Load JS
            var script = document.createElement('script');
            script.src = jsUrl;
            script.async = true;
            script.onload = function() {
                if (typeof window.MapLibreDrawControl !== 'undefined') {
                    console.log('[AOT_MAP_LOADER.loadMapLibreDraw] Loaded MapLibreDrawControl v' + version);
                    resolve(true);
                } else {
                    reject(new Error('[AOT_MAP_LOADER.loadMapLibreDraw] Script loaded but MapLibreDrawControl not found'));
                }
            };
            script.onerror = function() {
                reject(new Error('[AOT_MAP_LOADER.loadMapLibreDraw] Failed to load: ' + jsUrl));
            };
            document.head.appendChild(script);
        });

        return window.__aotMapLibreDrawLoadPromise;
    }

    /**
     * Load both MapLibre-GL core and the Draw plugin sequentially.
     * Resolves even if Draw fails (fallback mode will be used by MapLibreDraw).
     *
     * @param {Object} [config] - Combined loader config (same as loadMapLibre)
     * @param {boolean} [config.loadDraw=true] - Also load draw plugin
     * @returns {Promise<Object>} Resolves { maplibre: true, draw: true|false }
     */
    function loadVectorDependencies(config) {
        config = config || {};
        var loadDraw = config.loadDraw !== false;

        return loadMapLibre(config).then(function() {
            if (loadDraw) {
                return loadMapLibreDraw(config).catch(function(err) {
                    console.warn('[AOT_MAP_LOADER] MapLibreDraw load failed (fallback mode will be used):', err.message);
                    return false;
                });
            }
            return false;
        }).then(function(drawLoaded) {
            return { maplibre: true, draw: drawLoaded };
        });
    }

    window.AOT_MAP_LOADER = {
        loadMapDependencies: loadMapDependencies,
        loadMapLibre: loadMapLibre,
        loadMapLibreDraw: loadMapLibreDraw,
        loadVectorDependencies: loadVectorDependencies,
        loadScript: loadScript,
        loadCss: loadCss,
        loadModule: loadModule,
        isMapLibreLoaded: function() {
            return typeof window.maplibregl !== 'undefined';
        },
        isLeafletLoaded: function() {
            return typeof L !== 'undefined';
        }
    };

})(window);
