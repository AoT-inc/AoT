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

        // AttributionControl.prototype._updateAttributions 패치: MapTiler 등
        // 외부 스타일이 소스에 심어놓는 장문 "OpenStreetMap contributors" 표기를
        // AoT 자체 레이어가 쓰는 "OpenStreetMap" 표기로 통일한다. 그 문자열
        // 자체는 고칠 수 없는 원격 style.json 안에 있으므로, 컨트롤이 DOM에
        // 쓰기 직전(호출될 때마다) 소스 attribution을 정규화한다. MapLibre가
        // 서로 부분 문자열로 겹치는 attribution은 자체적으로 중복 제거하므로
        // 표기만 통일하면 "OpenStreetMap"이 중복 표시되는 문제도 함께 없어진다.
        // 지도를 만드는 모든 코드(위젯/geo-design/옵션모달 등)를 일일이 고칠
        // 필요 없이 여기 한 곳에서 전역 적용된다.
        if (maplibregl.AttributionControl && !maplibregl.AttributionControl.prototype._aotOsmAttrPatched) {
            const origUpdateAttributions = maplibregl.AttributionControl.prototype._updateAttributions;
            maplibregl.AttributionControl.prototype._updateAttributions = function () {
                const map = this._map;
                if (map && map.style && map.style.sourceCaches) {
                    const caches = map.style.sourceCaches;
                    Object.keys(caches).forEach(function (id) {
                        const source = caches[id] && caches[id]._source;
                        if (source && typeof source.attribution === 'string' &&
                            /openstreetmap contributors/i.test(source.attribution)) {
                            source.attribution = source.attribution.replace(/openstreetmap contributors/gi, 'OpenStreetMap');
                        }
                    });
                }
                return origUpdateAttributions.apply(this, arguments);
            };
            maplibregl.AttributionControl.prototype._aotOsmAttrPatched = true;
        }

        return true;
    }

    global.AoTMapLibrePatches = { apply: apply };

    // maplibre 가 이미 로드되어 있으면(현재의 동기 로드 경로) 즉시 적용.
    apply();
})(window);
