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
     * Loads Leaflet, Leaflet Draw, and optional internal scripts in sequence.
     * @param {Object} config - Configuration object
     * @param {string} config.bundleUrl - URL for unified AoT map bundle (defaults to /static/js/map/bundles/aot-map-bundle.js)
     * @returns {Promise} Resolves when all scripts are loaded
     */
    function loadMapDependencies(config) {
        config = config || {};

        // 1. Start loading CSS immediately
        loadCss('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
        loadCss('https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css');

        // 2. Load Leaflet core first
        const pLeaflet = loadScript('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js');

        // 4. After Leaflet, load Leaflet Draw
        const pDraw = pLeaflet.then(() => {
            return loadScript('https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js')
                .catch(err => console.error('Failed to load Leaflet.draw:', err));
        }).catch(err => console.error('Failed to load Leaflet:', err));

        // 5. Load MapClient
        const pClient = pLeaflet.then(() => {
            return loadScript('/static/js/map/bundles/aot-map-client.js')
                .catch(err => console.error('Failed to load MapClient:', err));
        });

        const bundleUrl = config.bundleUrl || DEFAULT_BUNDLE;
        const pBundle = Promise.all([pLeaflet, pDraw, pClient]).then(function () {
            return loadModule(bundleUrl);
        });

        // 6. Wait for ALL scripts
        return Promise.all([pLeaflet, pDraw, pClient, pBundle]);
    }

    window.AOT_MAP_LOADER = {
        loadMapDependencies: loadMapDependencies,
        loadScript: loadScript,
        loadCss: loadCss,
        loadModule: loadModule
    };

})(window);
