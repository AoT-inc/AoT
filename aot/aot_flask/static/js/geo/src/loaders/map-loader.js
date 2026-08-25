/**
 * Map Dependency Loader
 * Handles parallel loading of Leaflet, Leaflet Draw, and internal map scripts.
 */
(function (window) {
    'use strict';

    window.aotScriptLoaders = window.aotScriptLoaders || {};
    window.aotCssLoaders = window.aotCssLoaders || {};

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
     * MapLibre-GL 을 로드한다. 필요하면 지도 번들도 함께.
     *
     * 예전에는 Leaflet·Leaflet Draw·MapClient 를 조건부로 함께 받았다. 그
     * 갈래를 2026-08-25 에 걷어냈다 — 지도가 MapLibre 로 옮겨 간 뒤 `loadLeaflet`
     * 을 켜는 호출부가 하나도 없었고(전수 확인), 그 안이 가리키던 것들도
     * 이미 없어진 것들이었다: Leaflet 은 외부 unpkg CDN 에서 받고 있었고
     * (폐쇄망 설치에서는 실패한다), MapClient 와 기본 번들 경로
     * `/static/js/map/bundles/` 는 디렉터리째 사라진 지 오래다.
     *
     * @param {Object} [config]
     * @param {string} [config.bundleUrl] - 함께 로드할 지도 번들(ES Module).
     *   기본값 없음 — 예전 기본값은 존재하지 않는 파일을 가리키고 있었다.
     * @returns {Promise} 모든 스크립트가 로드되면 resolve
     */
    function loadMapDependencies(config) {
        config = config || {};

        loadCss('/static/vendor/maplibre-gl-4.1.2/maplibre-gl.css?v=' + (window.AOT_ASSET_V || ''));
        var pMapLibre = loadScript('/static/vendor/maplibre-gl-4.1.2/maplibre-gl.js?v=' + (window.AOT_ASSET_V || ''));

        var pBundle = Promise.resolve();
        if (config.bundleUrl) {
            pBundle = pMapLibre.then(function() {
                return loadModule(config.bundleUrl);
            });
        }

        return Promise.all([pMapLibre, pBundle]);
    }

    /**
     * MapLibre-GL JS/CSS 를 적재한다. 이미 있으면 즉시 resolve 하고, 동시 호출은
     * 하나로 합친다.
     *
     * **기본은 동일 출처 반입본이다.** 예전 기본값은 unpkg 였는데, 같은 버전을
     * 이미 `static/vendor/maplibre-gl-4.1.2/` 에 두고도 외부에서 받고 있었다 —
     * 폐쇄망 설치에서는 지도가 아예 뜨지 않는다. layout.html 이 쓰는 정책과
     * 같게 맞춘다(로컬 기본, CDN 은 명시적으로 골랐을 때만).
     *
     * @param {Object} [config]
     * @param {string} [config.version='4.1.2'] - CDN 을 쓸 때의 버전
     * @param {string} [config.cdnBase] - 지정하면 그 CDN 에서 받는다(기본: 반입본)
     * @param {number} [config.timeout=15000]
     * @returns {Promise<boolean>} maplibregl 사용 가능하면 true, 실패 시 reject
     */
    function loadMapLibre(config) {
        config = config || {};
        var version = config.version || '4.1.2';
        var cdnBase = config.cdnBase || '';
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
                reject(new Error('[AOT_MAP_LOADER.loadMapLibre] load timed out after ' + timeout + 'ms'));
            }, timeout);

            var assetV = window.AOT_ASSET_V || '';
            var cssUrl = cdnBase
                ? cdnBase + '/maplibre-gl@' + version + '/dist/maplibre-gl.css'
                : '/static/vendor/maplibre-gl-4.1.2/maplibre-gl.css?v=' + assetV;
            var jsUrl = cdnBase
                ? cdnBase + '/maplibre-gl@' + version + '/dist/maplibre-gl.js'
                : '/static/vendor/maplibre-gl-4.1.2/maplibre-gl.js?v=' + assetV;

            // Load CSS first, then JS
            loadCss(cssUrl).then(function() {
                return loadScript(jsUrl);
            }).then(function() {
                clearTimeout(timer);
                if (typeof window.maplibregl === 'undefined') {
                    reject(new Error('[AOT_MAP_LOADER.loadMapLibre] Script loaded but window.maplibregl is undefined — the file served was not MapLibre'));
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
     * MapLibreDrawControl 이 이미 있으면 그것을 쓰고, 없으면 false 로 끝난다.
     *
     * 예전에는 CDN 에서 `@maplibre/maplibre-gl-draw` 를 받으려 했다. 존재하지 않는 npm 패키지였다. `@maplibre/maplibre-gl-draw` 는 레지스트리에
     * 없고(2026-08-25 확인: "Package not found"), 그래서 이 CDN 적재는 처음부터
     * 한 번도 성공한 적이 없다 — 매번 왕복 한 번을 버리고 실패로 떨어졌다.
     * 그리기는 실제로 자체 구현(AoTMapLibreDrawTool)이 하고 있고, 실행 중
     * MapLibreDrawControl·MapboxDraw·MapDraw 전역은 모두 undefined 다(실측).
     *
     * 함수는 남긴다 — 이 전역을 스스로 제공하는 설치가 있을 수 있으므로 위의
     * '이미 있음' 검사는 그대로 두고, 없을 때 네트워크를 두드리는 부분만 뺀다.
     *
     * @returns {Promise<boolean>} MapLibreDrawControl 사용 가능 여부
     */
    function loadMapLibreDraw() {
        if (typeof window.MapLibreDrawControl !== 'undefined') {
            return Promise.resolve(true);
        }
        return Promise.resolve(false);
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
