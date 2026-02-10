/**
 * map-option-starter.js
 * Handles the initialization of Map Options by waiting for dependencies
 * and then calling AoTMapInit with the provided configuration.
 * 
 * This file replaces the inline script in map_option.html.
 */
(function () {
    window.startMapOption = function (config) {
        function init() {
            // [Fix] Prefer Fixed version
            const initFn = window.AoTMapInitFixed || window.AoTMapInit;
            if (initFn) {
                // Ensure default_center is array if passed as such
                initFn(config);
            } else {
                console.error('AoTMapInit (Fixed/Legacy) not found after load');
            }
        }

        // [Fixed] Removed explicit lazy loading here because AotMapOption class (in controllers.js)
        // ALREADY implements lazy loading (waiting for shown.bs.modal).
        // Doubling this causes a deadlock (starter waits -> shown -> init -> controller waits -> never shown again).
        // Performance is solved by asset deduplication (map_assets.html).

        console.log('[MapOption] Initializing for', config.container_id);

        if (window.AOT_MAP_LOADER) {
            window.AOT_MAP_LOADER.loadMapDependencies().then(init);
        } else {
            // Fallback if loader script failed or sync load happened
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', init);
            } else {
                init();
            }
        }
    };
})();
