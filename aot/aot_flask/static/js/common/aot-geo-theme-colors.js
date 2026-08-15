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
        device: '#995aff',
        // 식생 구획(작기)의 기본색.
        //
        // **초록 계열을 쓰지 말 것.** 식생 구획은 대부분 위성지도 위에서 그린다.
        // 배경이 이미 초록·갈색인 밭이라 올리브(#6a8f3c)로 두었더니 도형이
        // 통째로 묻혀 어디를 그렸는지조차 보이지 않았다. zone 초록(#28a745)과도
        // 구분되지 않는다.
        //
        // 그래서 배경의 보색 쪽인 마젠타를 기본으로 한다 — 항공·위성 기반 GIS 가
        // 작물 구획에 관행적으로 쓰는 색이기도 하다. 브랜드 노랑은 액션 색이라
        // 쓰지 않는다. 구획마다 사용자가 고른 색(GeoPlanting.color)이 있으면
        // 그것이 이긴다.
        vegetation: '#e0409a'
    };

    // Function 계열 세부 타입. DB 의 GeoShape.feature.properties.device_type 은
    // 대개 'function' 으로 정규화돼 들어오지만, 마커(collect_devices)나 예전
    // 도형에는 세부 타입이 그대로 남아 있을 수 있다.
    var FUNCTION_TYPES = [
        'function', 'trigger', 'pid', 'conditional',
        'custom', 'generic_function', 'trigger_sequence'
    ];

    // 테마 키. 복합장치(Device)는 'device' 가 아니라 'device_unit' 이다 —
    // 'device' 는 종류별 색이 미설정일 때 수렴하는 **장치 공통색**이라, 거기에
    // 복합장치 색을 쓰면 복합장치를 바꾼 것이 나머지 종류의 폴백까지 바꾼다.
    var DEVICE_KEYS = ['input', 'output', 'function', 'device_unit'];

    /**
     * 쓸 테마 객체 — **넘어온 테마를 전역 테마 위에 얹는다.**
     *
     * 예전에는 인자가 객체이기만 하면 그것을 **그대로** 썼다. 그래서 부분적으로만
     * 채워진 테마(또는 빈 `{}`)를 넘기는 소비처에서는, 빠진 키가 전역 설정으로
     * 내려가지 못하고 곧장 하드코딩 기본값으로 떨어졌다.
     *
     * 실제로 지도 위젯이 그랬다: `wOpts.theme_config || vars.theme || {}` 를
     * 넘기는데 그 안에 장치 색이 없으면 `t.output` 이 undefined 라 **출력에
     * 연결된 도형도 장치 공통색**으로 칠해졌다. 같은 도형이 geo/design 에서는
     * (테마를 안 넘겨 전역 설정을 그대로 읽으므로) 제 색으로 나와서, 두 화면의
     * 색이 갈렸다.
     *
     * 병합이면 명시한 값은 그대로 이기고, 안 준 값만 전역 설정 → 기본값 순으로
     * 내려간다. 화면마다 색이 달라지지 않는다.
     */
    function themeOf(theme) {
        var g = global.AOT_GEO_CONFIG;
        var base = (g && g.theme_config) || {};
        if (!theme || typeof theme !== 'object') return base;
        var out = {}, k;
        for (k in base) { if (Object.prototype.hasOwnProperty.call(base, k)) out[k] = base[k]; }
        for (k in theme) {
            // 빈 문자열/null 은 "설정 안 함" 으로 본다 — 그것까지 덮어쓰면
            // 위젯이 값을 비워 둔 것만으로 전역 설정이 무시된다.
            if (!Object.prototype.hasOwnProperty.call(theme, k)) continue;
            if (theme[k] === null || theme[k] === undefined || theme[k] === '') continue;
            out[k] = theme[k];
        }
        return out;
    }

    /** 장치 세부 타입 → 테마 키(DEVICE_KEYS 중 하나). 모르면 null. */
    function normalizeDeviceType(devType) {
        if (!devType) return null;
        var t = String(devType).toLowerCase();
        // 복합장치 먼저 — FUNCTION_TYPES 에 'custom' 이 있어 순서가 바뀌면
        // 복합장치가 Function 색을 따라간다(둘 다 custom_controller 행이다).
        if (t === 'device') return 'device_unit';
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
