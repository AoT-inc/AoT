/**
 * geo 테마 색 해석 — 단일 정본.
 *
 * 색의 정본은 `GeoSetting.theme_config`(전역 싱글톤) 하나다. 이 파일은 그
 * 값을 읽어 "이 종류의 도형/마커/라벨은 무슨 색인가"를 답하는 유일한 함수를
 * 제공한다.
 *
 * 왜 하나로 모았나 — 예전에는 같은 질문에 네 곳이 제각기 답했다:
 *   ① 전역 theme_config            (정본)
 *   ② GeoMap.state_json.theme_config (지도별 override, 부분 dict로 굳어 전역을 이김)
 *   ③ GeoShape.feature.properties.color (도형에 각인된 색, 테마 변경을 무시)
 *   ④ localStorage.aot_config_color_*   (브라우저마다 다른 값이 남음)
 * 그 결과 같은 도형이 geo/design 화면과 AoT_map 위젯에서 서로 다른 색으로
 * 그려졌다. ②③④는 전부 제거했고(정리 스크립트: aot/scripts/fix_geo_theme_drift.py),
 * 읽기 경로는 모두 이 모듈을 거친다.
 *
 * 기본값은 여기 DEFAULTS 한 벌뿐이다. input/output/function 은 별도 기본값을
 * 두지 않는다 — 설정이 없으면 장치 공통색(device)으로 수렴시킨다. 예전에는
 * 위젯이 output '#dd4444' / function '#28a745' 를, geo/design 이 '#995aff' 를
 * 폴백으로 써서 미설정 종류의 색이 화면마다 달랐다.
 */
(function (global) {
    'use strict';

    // 번들 두 곳(geo-design, aot-map-widget)에 함께 들어가므로 재정의 방지.
    if (global.AoTGeoTheme) return;

    var DEFAULTS = {
        site: '#DF5353',
        zone: '#28a745',
        facility: '#82898f',
        equipment: '#007bff',
        device: '#995aff'
    };

    // Function 계열 세부 타입. DB 의 GeoShape.feature.properties.device_type 은
    // 대개 'function' 으로 정규화돼 들어오지만, 마커(collect_devices)나 예전
    // 도형에는 세부 타입이 그대로 남아 있을 수 있다.
    var FUNCTION_TYPES = [
        'function', 'trigger', 'pid', 'conditional',
        'custom', 'generic_function', 'trigger_sequence'
    ];

    var DEVICE_KEYS = ['input', 'output', 'function'];

    function themeOf(theme) {
        if (theme && typeof theme === 'object') return theme;
        var g = global.AOT_GEO_CONFIG;
        return (g && g.theme_config) || {};
    }

    /** 장치 세부 타입 → 테마 키('input'|'output'|'function'). 모르면 null. */
    function normalizeDeviceType(devType) {
        if (!devType) return null;
        var t = String(devType).toLowerCase();
        if (FUNCTION_TYPES.indexOf(t) !== -1) return 'function';
        if (t === 'input' || t === 'output') return t;
        return null;
    }

    /** site/zone/facility/equipment/device 색. theme 생략 시 AOT_GEO_CONFIG 사용. */
    function color(key, theme) {
        var t = themeOf(theme);
        return t[key] || DEFAULTS[key] || DEFAULTS.device;
    }

    /**
     * 장치(Input/Output/Function) 색.
     * 종류별 설정 → 장치 공통색(device) → 기본값 순으로 내려간다.
     * devType 을 모르는 도형(백필 전 레거시)도 공통색으로 수렴해, 화면마다
     * 다른 색이 나오는 일이 없다.
     */
    function deviceColor(devType, theme) {
        var t = themeOf(theme);
        var k = normalizeDeviceType(devType);
        return (k && t[k]) || t.device || DEFAULTS.device;
    }

    global.AoTGeoTheme = {
        DEFAULTS: DEFAULTS,
        FUNCTION_TYPES: FUNCTION_TYPES,
        DEVICE_KEYS: DEVICE_KEYS,
        normalizeDeviceType: normalizeDeviceType,
        color: color,
        deviceColor: deviceColor
    };
})(typeof window !== 'undefined' ? window : this);
