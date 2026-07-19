/**
 * aot-maplibre-patches.js
 * MapLibre GL 호환 패치를 한 곳에 모은 멱등(idempotent) 함수.
 *
 * 기존에는 aot-maplibre-loader.js 최상위 블록과 layout 인라인 스크립트에서
 * parse-time 에 maplibregl 을 직접 참조해 패치를 적용했다. 그 구조는 maplibre 가
 * head 에서 동기 로드되어 있어야만 동작하므로, maplibre 를 지연/온디맨드 로드하면
 * 패치가 누락된다.
 *
 * 이 파일은 패치를 window.AoTMapLibrePatches.apply() 로 노출한다. maplibre 가
 * (동기/지연 무관하게) 로드된 직후 호출하면 되고, 여러 번 불러도 안전하다.
 *
 * @requires maplibre-gl (apply 호출 시점에 존재해야 함)
 */
(function (global) {
    'use strict';

    /**
     * maplibregl 에 AoT 호환 패치를 적용한다. maplibregl 이 아직 없으면 false 반환.
     * 이미 적용된 항목은 건너뛰므로 반복 호출에 안전하다.
     * @returns {boolean} 적용(또는 이미 적용됨) 여부
     */
    function apply() {
        if (typeof maplibregl === 'undefined') {
            return false;
        }

        // Map.prototype.isStyleLoaded 폴리필
        if (maplibregl.Map && !maplibregl.Map.prototype.isStyleLoaded) {
            maplibregl.Map.prototype.isStyleLoaded = function () {
                return this.loaded();
            };
        }

        // Map.prototype.hasControl 헬퍼
        if (maplibregl.Map && !maplibregl.Map.prototype.hasControl) {
            maplibregl.Map.prototype.hasControl = function (control) {
                return this._controls && this._controls.has(control);
            };
        }

        // Evented.callInitHooks no-op (MapLibre 는 이 패턴을 쓰지 않음)
        if (maplibregl.Evented && !maplibregl.Evented.prototype.callInitHooks) {
            maplibregl.Evented.prototype.callInitHooks = function () {};
        }

        return true;
    }

    global.AoTMapLibrePatches = { apply: apply };

    // maplibre 가 이미 로드되어 있으면(현재의 동기 로드 경로) 즉시 적용.
    apply();
})(window);
