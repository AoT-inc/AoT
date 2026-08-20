/**
 * aot-map-plot.js — AoT_map 위젯의 식생 구획(작기) 레이어.
 *
 * 설계 정본: docs/design/geo-vegetation-planting.md
 *
 * 역할 분담: geo/design 은 구획을 **만들고 고치는** 곳이고, 여기는 **운영**
 * 이다 — 무엇이 심겨 있나, 이 자리에 뭐가 있었나, 노트. 다른 도형(구역·시설)과
 * 같은 분담이다.
 *
 * 라벨이 이미 많은 화면이라 공간을 아껴 쓴다:
 *   - 라벨은 줌 16 이상에서만(label-layers 프리셋의 plot.pin='gated').
 *   - 라벨 문구는 작물 이름 하나. 이름·품종·면적은 모달에서 본다.
 *   - 채움은 옅게(겹침이 정상이라 진하면 아래 구획이 안 보인다).
 */
(function () {
    'use strict';

    var STATE = {};       // uid → { plots, srcId, fillId, lineId, labels[] }

    function _t(k) { return (window._ ? window._(k) : k); }

    function _color(p) {
        if (p && p.color) return p.color;
        return window.AoTGeoTheme ? window.AoTGeoTheme.color('plot') : '#6a8f3c';
    }

    // 레이어 id 접두사는 'aot-plot-' 이어야 한다. 지도의 레이어 컨트롤이
    // `getLayerIdsByType('plot')` 로 **이름을 보고** 켜고 끄기 때문이다
    // (aot-map-custom-controls.js). 짧게 'aot-veg-' 로 줄이면 그 컨트롤이
    // 이 레이어를 찾지 못해 체크박스가 아무 일도 하지 않는다.
    function _ids(uid) {
        return {
            src:  'aot-plot-src-' + uid,
            fill: 'aot-plot-fill-' + uid,
            line: 'aot-plot-line-' + uid
        };
    }

    /** #rrggbb → [r,g,b] (0~255). 못 읽으면 null. */
    function _rgb(hex) {
        var h = String(hex || '').replace('#', '');
        if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
        if (h.length !== 6) return null;
        return [parseInt(h.substr(0, 2), 16),
                parseInt(h.substr(2, 2), 16),
                parseInt(h.substr(4, 2), 16)];
    }

    function _hex(rgb) {
        return '#' + rgb.map(function (c) {
            return ('0' + Math.max(0, Math.min(255, Math.round(c))).toString(16)).slice(-2);
        }).join('');
    }

    /** WCAG 상대 휘도 (0=검정, 1=흰색). */
    function _luminance(rgb) {
        var a = rgb.map(function (c) {
            c = c / 255;
            return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2];
    }

    /**
     * 글자색 — 도형색을 기준으로 **읽히는 쪽**을 고른다.
     *
     * 무조건 어둡게 하면 남색·진갈색처럼 원래 어두운 구획색에서 글자가 배경에
     * 묻힌다. 그래서 휘도를 보고 방향을 정한다: 밝은 색은 더 어둡게, 어두운
     * 색은 흰색 쪽으로 끌어올린다. 같은 계열을 유지하므로 어느 구획의 이름인지
     * 색으로 계속 알 수 있고, 테두리(halo) 없이도 읽힌다.
     */
    function _labelColor(hex) {
        var rgb = _rgb(hex);
        if (!rgb) return '#2b3a1c';
        if (_luminance(rgb) > 0.35) {
            // 밝은 구획색 → 같은 색을 진하게
            return _hex(rgb.map(function (c) { return c * 0.42; }));
        }
        // 어두운 구획색 → 흰색과 섞어 밝게 (채도를 남겨 계열은 유지)
        return _hex(rgb.map(function (c) { return c + (255 - c) * 0.72; }));
    }

    /**
     * 구획의 기하 — 자기 것이 없으면 서버가 실어 준 파생 기하를 쓴다.
     *
     * 시설 구획(온실)은 **기하를 그리지 않는다.** 위치의 정본이 구역 자체라
     * `feature` 가 비어 있고, 서버가 그 구역의 자리를 `derived_feature` 로
     * 함께 보낸다(docs/design/geo-vegetation-planting.md).
     *
     * ⚠ 파생이므로 **저장 쪽으로 되돌리지 말 것.** 되써 넣으면 그 순간
     * 정본으로 승격해, 시설을 옮겨도 구획만 옛 자리에 남는다.
     * 라벨 위치 저장(`label_lnglat`)은 `feature` 가 있는 구획에만 해당한다.
     */
    function _geomOf(p) {
        if (p && p.feature && p.feature.geometry) return p.feature.geometry;
        if (p && p.derived_feature && p.derived_feature.geometry) {
            return p.derived_feature.geometry;
        }
        return null;
    }

    function _featureCollection(rows) {
        return {
            type: 'FeatureCollection',
            features: (rows || []).map(function (p) {
                var geom = _geomOf(p);
                var f = geom
                    ? { type: 'Feature', geometry: geom, properties: {} }
                    : null;
                if (!f) return null;
                var c = _color(p);
                f.properties = {
                    plot_uuid: p.unique_id,
                    subject: p.subject || '',
                    color: c,
                    // 글자색은 여기서 함께 실어야 한다 — symbol 레이어의
                    // ['get','label_color'] 가 이 값을 읽는다. 빠뜨리면 글자가
                    // 기본 검정으로 떨어져 "도형색 하나로" 라는 규칙이 깨진다.
                    label_color: _labelColor(c)
                };
                return f;
            }).filter(Boolean)
        };
    }

    /**
     * 지도에 식생 레이어를 올린다. 이미 있으면 데이터만 갱신한다.
     *
     * 종료된 작기는 서버가 기본 목록에서 빼 준다 — 몇 년 지난 지도가 옛
     * 두둑으로 뒤덮이지 않게.
     */
    // 관리 프로그램 선택지 — 모달 빌더는 순수 함수라 스스로 조회하지 않는다.
    // 받아 두고 모달을 열 때 실어 준다(구획마다 다시 받을 이유가 없다).
    //
    // **종류별로 캐시한다.** 한 벌만 두면 종류를 바꾼 뒤 목록이 옛 종류의
    // 것으로 남고, 그것을 고른 저장을 서버가 거절한다 — 화면에 보이는 선택지가
    // 저장되지 않는 상태가 된다.
    var _programs = {};

    function _loadPrograms(kind) {
        kind = kind || 'vegetation';
        if (_programs[kind]) return Promise.resolve(_programs[kind]);
        return fetch('/api/geo/programs?kind=' + encodeURIComponent(kind),
                     { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                _programs[kind] = (res && res.ok) ? (res.programs || []) : [];
                return _programs[kind];
            })
            .catch(function () { _programs[kind] = []; return _programs[kind]; });
    }

    function load(uid, map, opts) {
        opts = opts || {};
        if (!map || !opts.mapUuid) return Promise.resolve([]);
        _loadPrograms();

        return fetch('/api/geo/plots?map_uuid=' + encodeURIComponent(opts.mapUuid))
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (!res || !res.ok) return [];
                var rows = res.plots || [];
                var st = STATE[uid] = STATE[uid] || {};
                st.plots = rows;
                st.mapUuid = opts.mapUuid;
                st.opts = opts;          // 스타일 전환 후 재생성에 그대로 쓴다
                _render(uid, map, rows, opts);
                _scheduleRefresh(uid, map, opts);
                return rows;
            })
            .catch(function () { return []; });
    }

    // 구획 목록을 주기적으로 다시 받는다.
    //
    // 식생은 geo/design 이나 다른 브라우저에서 바뀐다(새로 그리기·재배 종료).
    // 한 번만 받으면 위젯은 그때 상태에 머물러, **종료한 구획이 지도에 계속
    // 남는다** — 실제로 그렇게 보였다. 다만 자주 바뀌는 데이터가 아니므로
    // 센서값처럼 몇 초 주기로 돌 이유는 없다. 5분이면 충분하고, 그보다 급한
    // 갱신은 이 위젯 안에서 편집했을 때인데 그 경로는 즉시 load() 를 부른다.
    var REFRESH_MS = 300000;

    function _scheduleRefresh(uid, map, opts) {
        var st = STATE[uid] = STATE[uid] || {};
        if (st.timer) return;                    // 이미 걸려 있다
        st.timer = setInterval(function () {
            // 탭이 숨겨져 있으면 건너뛴다 — 안 보이는 화면을 위해 폴링할 이유가
            // 없고, 폰에서는 그 한 번이 라디오를 깨운다.
            if (document.hidden) return;
            var cur = STATE[uid];
            if (!cur || !cur.opts) return;
            fetch('/api/geo/plots?map_uuid=' +
                  encodeURIComponent(cur.opts.mapUuid || ''))
                .then(function (r) { return r.json(); })
                .then(function (res) {
                    if (!res || !res.ok) return;
                    cur.plots = res.plots || [];
                    _render(uid, map, cur.plots, cur.opts);
                })
                .catch(function () {});
        }, REFRESH_MS);
    }

    function _render(uid, map, rows, opts) {
        var id = _ids(uid);
        var data = _featureCollection(rows);

        try {
            if (map.getSource(id.src)) {
                map.getSource(id.src).setData(data);
            } else {
                map.addSource(id.src, { type: 'geojson', data: data });
                map.addLayer({
                    id: id.fill, type: 'fill', source: id.src,
                    paint: {
                        'fill-color': ['get', 'color'],
                        // 겹침(간작·혼작)이 정상이라 옅게 — 진하면 아래가 안 보인다.
                        'fill-opacity': 0.22
                    }
                });
                map.addLayer({
                    id: id.line, type: 'line', source: id.src,
                    paint: { 'line-color': ['get', 'color'], 'line-width': 1.5 }
                });
                _bindClick(uid, map, opts);
            }
        } catch (e) {
            console.warn('[AoT Map] 식생 레이어 렌더 실패:', e);
            return;
        }

        _renderLabels(uid, map, rows, opts);
        setVisible(uid, map, opts.visible !== false);
    }

    // ── 라벨 ────────────────────────────────────────────────────────────────
    //
    // 위젯의 다른 라벨과 **같은 방식**(DOM 마커 + `aot-sensor-map-marker` 칩)을
    // 쓴다. 예전에는 MapLibre symbol 텍스트로 그렸는데, 위성지도 위에서는
    // 배경 밝기가 제각각이라 **어떤 단색 글자도 읽히지 않았다** — 흰 테두리를
    // 두르면 지저분하고, 안 두르면 묻힌다. 배경 알약이 있는 기존 칩은 그
    // 문제가 없고 화면 전체의 라벨 생김새도 하나로 맞는다.
    //
    // 글자 크기는 위젯 옵션 'Label Text Size'(em)를 그대로 쓴다(bay 칩과 동일).
    function _labelEm(opts) {
        var em = parseFloat(opts && opts.labelSizeEm);
        return (isFinite(em) && em > 0) ? em : 1.0;
    }

    /**
     * 라벨 자리 [lng, lat].
     *
     * geo/design 에서 사람이 칩을 옮겨 두었으면 **그 자리를 그대로 쓴다** —
     * 겹치는 칩을 거기서 풀어 놓았는데 위젯이 도형 중앙으로 되돌리면 그 작업이
     * 무의미해진다. 없으면 폴리곤 대표점(오목한 두둑에서도 내부에 놓인다).
     */
    function _labelPoint(geom, plot) {
        var props = (plot && plot.feature && plot.feature.properties) || {};
        if (Array.isArray(props.label_lnglat) && props.label_lnglat.length === 2) {
            return props.label_lnglat;
        }
        // 시설 구획은 구역 중심에 **이미 구역 칩이 있다**(aot-map-bay). 파생
        // 기하의 대표점도 같은 중심이라 그대로 두면 두 칩이 정확히 포개져 둘 다
        // 못 읽는다. 구역 안쪽에서 아래로 비켜 놓는다 — 밖으로 내보내지 않는
        // 이유는 어느 구역의 작물인지가 자리로 드러나야 하기 때문이다.
        if (plot && plot.location_source === 'facility') {
            var off = _southOffsetPoint(geom);
            if (off) return off;
        }
        try {
            if (window.turf && window.turf.pointOnFeature) {
                var pt = window.turf.pointOnFeature({ type: 'Feature', properties: {},
                                                      geometry: geom });
                return pt.geometry.coordinates;
            }
        } catch (e) { /* turf 없으면 평균으로 */ }
        var ring = (geom.type === 'MultiPolygon') ? geom.coordinates[0][0]
                                                  : geom.coordinates[0];
        if (!ring || !ring.length) return null;
        var sx = 0, sy = 0;
        ring.forEach(function (c) { sx += c[0]; sy += c[1]; });
        return [sx / ring.length, sy / ring.length];
    }

    /** 폴리곤 중심에서 남쪽(아래)으로 높이의 1/4 만큼 내린 점. */
    function _southOffsetPoint(geom) {
        var rings = [];
        if (!geom) return null;
        if (geom.type === 'Polygon') rings = [geom.coordinates[0]];
        else if (geom.type === 'MultiPolygon') {
            rings = (geom.coordinates || []).map(function (p) { return p[0]; });
        }
        var pts = [];
        rings.forEach(function (r) { (r || []).forEach(function (c) { pts.push(c); }); });
        if (!pts.length) return null;
        var minLat = pts[0][1], maxLat = pts[0][1], sx = 0, sy = 0;
        pts.forEach(function (c) {
            if (c[1] < minLat) minLat = c[1];
            if (c[1] > maxLat) maxLat = c[1];
            sx += c[0]; sy += c[1];
        });
        var cx = sx / pts.length, cy = sy / pts.length;
        return [cx, cy - (maxLat - minLat) * 0.25];
    }

    function _clearLabels(uid) {
        var st = STATE[uid];
        if (!st || !st.markers) return;
        st.markers.forEach(function (m) { try { m.remove(); } catch (e) {} });
        st.markers = [];
    }

    function _renderLabels(uid, map, rows, opts) {
        var st = STATE[uid] = STATE[uid] || {};
        _clearLabels(uid);
        if (!window.maplibregl || !window.maplibregl.Marker) return;

        var reg = window.AoTMapLabelLayers;
        var desc = reg && reg.resolve
            ? reg.resolve(!!(opts && opts.facilityCentric), 'plot')
            : { minZoom: 16 };
        st.labelMinZoom = desc.minZoom || 16;
        st.markers = [];

        (rows || []).forEach(function (p) {
            var geom = _geomOf(p);
            if (!geom || !p.subject) return;
            var pos = _labelPoint(geom, p);
            if (!pos) return;

            var el = document.createElement('div');
            el.className = 'aot-sensor-map-marker aot-bay-chip aot-plot-chip';
            el.innerHTML = '<div class="aot-bay-chip-name"></div>';
            el.querySelector('.aot-bay-chip-name').textContent = p.subject;
            el.style.fontSize = _labelEm(opts) + 'em';
            // 배경은 그 구획의 색 — 어느 구획의 이름인지 색으로 드러난다.
            el.style.background = _color(p);
            el.style.color = _readableOn(_color(p));
            el.style.cursor = 'pointer';
            el.addEventListener('click', function (ev) {
                ev.stopPropagation();
                openModal(uid, map, p.unique_id, st.opts || opts);
            });

            try {
                st.markers.push(new window.maplibregl.Marker({ element: el })
                    .setLngLat(pos).addTo(map));
            } catch (e) { /* 마커 하나 실패가 나머지를 막지 않는다 */ }
        });

        _applyLabelZoom(uid, map);
        if (!st.zoomBound) {
            st.zoomBound = true;
            map.on('zoom', function () { _applyLabelZoom(uid, map); });
        }

        if (reg && reg.register) {
            try {
                reg.register(uid, 'plot',
                             { key: reg.makeKey('plot', 'shape', uid) });
            } catch (e) { /* 레지스트리는 보조 */ }
        }
    }

    /** 줌 게이트 — 라벨이 이미 많은 화면이라 당겨야 보인다. */
    function _applyLabelZoom(uid, map) {
        var st = STATE[uid];
        if (!st || !st.markers) return;
        var show = (st.visible !== false) &&
                   (map.getZoom() >= (st.labelMinZoom || 16));
        st.markers.forEach(function (m) {
            try { m.getElement().style.display = show ? '' : 'none'; } catch (e) {}
        });
    }

    /** 배경색 위에서 읽히는 글자색 — 흰색/검정 중 대비가 큰 쪽. */
    function _readableOn(hex) {
        var rgb = _rgb(hex);
        if (!rgb) return '#ffffff';
        return _luminance(rgb) > 0.45 ? '#1a1a1a' : '#ffffff';
    }

    /** 도형·라벨 표시 토글. custom option 과 레이어 컨트롤이 함께 쓴다. */
    function setVisible(uid, map, visible) {
        var id = _ids(uid);
        var v = visible ? 'visible' : 'none';
        [id.fill, id.line].forEach(function (lid) {
            try {
                if (map.getLayer(lid)) map.setLayoutProperty(lid, 'visibility', v);
            } catch (e) { /* 아직 안 올라간 레이어 */ }
        });
        var st = STATE[uid];
        if (st) st.visible = !!visible;
        _applyLabelZoom(uid, map);      // 라벨은 DOM 마커라 따로 숨긴다
    }

    function isVisible(uid) {
        var st = STATE[uid];
        return !st || st.visible !== false;
    }

    // 레이어 컨트롤(지도 우측 패널)의 '식생' 체크박스와 상태를 맞춘다.
    //
    // 그 컨트롤은 레이어 id 접두사로 직접 visibility 를 바꾸므로 화면은 바로
    // 반응하지만, 모듈의 상태(st.visible)를 모른다. 동기화하지 않으면 베이스
    // 지도를 바꿔 rehydrate 될 때 옵션 기본값으로 되돌아가 **꺼둔 레이어가
    // 되살아난다.**
    window.addEventListener('layer-toggle', function (ev) {
        var d = (ev && ev.detail) || {};
        if (d.layerId !== 'plot') return;
        Object.keys(STATE).forEach(function (uid) {
            var st = STATE[uid];
            if (st) st.visible = !!d.visible;
            if (st && st.opts) st.opts.visible = !!d.visible;
        });
    });

    // ── 클릭 → 중앙 모달 ────────────────────────────────────────────────────

    function _bindClick(uid, map, opts) {
        var st = STATE[uid] = STATE[uid] || {};
        // 베이스 지도를 바꾸면 레이어는 사라지지만 **핸들러는 남는다.**
        // 다시 바인딩하면 클릭 한 번에 모달이 두 번 열린다.
        if (st.clickBound) return;
        st.clickBound = true;
        var id = _ids(uid);
        map.on('click', id.fill, function (e) {
            var f = e.features && e.features[0];
            if (!f) return;
            var uuid = f.properties && f.properties.plot_uuid;
            if (uuid) openModal(uid, map, uuid, opts);
        });
        map.on('mouseenter', id.fill, function () {
            map.getCanvas().style.cursor = 'pointer';
        });
        map.on('mouseleave', id.fill, function () {
            map.getCanvas().style.cursor = '';
        });
    }

    /**
     * 구획 모달. 팝업 말풍선이 아니라 **중앙 모달**을 쓴다 — 작물·기간·센서
     * 출처·이력·노트가 함께 들어가야 해서 말풍선 폭으로는 부족하다.
     */
    /**
     * 탭 전환 — 구역·시설 모달과 **같은 마크업 계약**(`.aot-bay-popup-nav` 의
     * `[data-sec]` 버튼 ↔ `.aot-bay-popup-pane` 의 `[data-pane]`)을 쓴다.
     *
     * 위젯의 `_wireZoneTabs` 를 빌려 오지 않는다 — 그쪽은 구역 상태(센서 서브탭·
     * 이력 오버레이·복합장치 진입)에 묶여 있어서, 식생이 갖지 않은 것을 함께
     * 끌고 온다. 여기서 필요한 것은 pane 을 바꿔 다는 것뿐이다.
     *
     * `wantSec` 를 돌려주도록 활성 탭을 노출한다 — 저장 후 다시 열 때 사용자가
     * 보던 탭으로 돌아가야 한다(편집은 [개요]에서 하는데 [현황]으로 튕기면
     * 방금 무엇을 고쳤는지 확인할 수 없다).
     */
    function _wireTabs(body) {
        if (!body || body._plotTabsWired) return;
        body._plotTabsWired = true;
        body.addEventListener('click', function (ev) {
            var btn = ev.target.closest('.aot-bay-popup-nav .aot-act-tab-btn[data-sec]');
            if (!btn || !body.contains(btn)) return;
            var sec = btn.dataset.sec;
            body.querySelectorAll('.aot-bay-popup-nav .aot-act-tab-btn')
                .forEach(function (b) { b.classList.toggle('active', b === btn); });
            body.querySelectorAll('.aot-bay-popup-pane').forEach(function (pane) {
                pane.style.display = (pane.dataset.pane === sec) ? '' : 'none';
            });
        });
    }

    function _activeSec(body) {
        var on = body && body.querySelector(
            '.aot-bay-popup-nav .aot-act-tab-btn.active[data-sec]');
        return on ? on.dataset.sec : null;
    }

    /** 종류 select 가 바뀌면 프로그램 select 의 선택지만 갈아 끼운다.
     *
     * 폼 전체를 다시 그리지 않는다 — 이 모달은 5초 폴링이 도는 화면이라
     * 통째로 갈아끼우는 것이 그대로 깜빡임이 된다(이미 한 번 겪었다).
     */
    function refreshProgramChoices(selKind, selProgram, noneLabel) {
        if (!selKind || !selProgram) return;
        var kind = selKind.value || 'vegetation';
        _loadPrograms(kind).then(function (list) {
            if ((selKind.value || 'vegetation') !== kind) return;   // 그 사이 또 바뀜
            var html = '<option value="">' + (noneLabel || '') + '</option>';
            (list || []).forEach(function (x) {
                var label = x.name + (x.variety ? ' \u00b7 ' + x.variety : '');
                html += '<option value="' + x.unique_id + '">' + label + '</option>';
            });
            // 종류가 바뀌면 옛 종류의 프로그램은 더 못 쓴다 — 비워 둔다.
            if (selProgram.innerHTML !== html) selProgram.innerHTML = html;
        });
    }

    function openModal(uid, map, uuid, opts) {
        opts = opts || {};
        var shell = opts.shell;                 // 위젯의 _showFacilityCenterOverlay
        var popupApi = window.AoTMapPopup;
        if (!shell || !popupApi || !popupApi.buildPlotModal) return;

        // cache:'no-store' — 이 응답에는 Cache-Control 이 없어서 브라우저가
        // 휴리스틱 캐시를 걸 수 있다. 저장 직후 다시 여는 경로가 있는데
        // (일정 추가·작물 편집) 거기서 옛 사본이 나오면 "저장했는데 화면이
        // 그대로" 가 된다.
        fetch('/api/geo/plot/' + encodeURIComponent(uuid), { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (!res || !res.ok) return;
                var p = res.plot;
                // 이 구획 종류의 목록이 아직 없으면 받아 온 뒤 다시 연다 —
                // 없는 채로 그리면 프로그램 줄이 통째로 빠진다(빌더는 선택지가
                // 없으면 줄을 내지 않는다).
                var _k = p.kind || 'vegetation';
                if (!_programs[_k]) {
                    _loadPrograms(_k).then(function () {
                        openModal(uid, map, uuid, opts);
                    });
                    return;
                }
                // 관리 프로그램 선택지를 실어 준다 — 모달 빌더는 순수 함수라
                // 스스로 조회하지 않는다(조회는 위젯의 일이다).
                p.program_choices = _programs[_k] || [];
                // 열 탭: 명시 지정(저장 후 복귀) > 위젯 옵션 popup_default_tab.
                var want = opts.openTab || opts.defaultTab;
                var popup = shell(popupApi.buildPlotModal(
                    p, { defaultTab: want }), uid);
                var el = popup && popup.getElement && popup.getElement();
                var body = el && el.querySelector('.maplibregl-popup-content');
                if (!body) return;
                // [환경·제어] — 제어 배선은 위젯이 빌려준다. 여기서 다시
                // 구현하면 폴링·토글·예약이 두 벌이 된다.
                //
                // 위젯이 붙여 주면 **탭 전환도 그쪽 위임 핸들러가 맡는다**
                // (구역과 같은 것이라, [환경·제어]로 넘어갈 때 센서 차트 지연
                // 렌더까지 함께 따라온다). 그래서 우리 것은 안 붙인다 —
                // 둘을 다 붙이면 같은 클릭에 핸들러 두 개가 돈다.
                var attached = false;
                if (typeof opts.attachControl === 'function') {
                    try {
                        opts.attachControl(uid, popup, body, p.unique_id);
                        attached = true;
                    } catch (e) { /* 제어가 안 붙어도 나머지 탭은 살아야 한다 */ }
                }
                if (!attached) _wireTabs(body);

                _wireEdit(uid, map, body, p, opts);

                // 노트 — 공용 컴포넌트에 배선만 넘긴다(자체 노트 UI 금지).
                if (window.AoTNotesBlock && window.AoTNotesBlock.wire) {
                    window.AoTNotesBlock.wire(body, {
                        targetId: p.unique_id,
                        targetType: 'plot',
                        name: p.name || p.subject || ''
                    });
                }

                // 이 자리 이력 — 기하 교차라 POST 다(폴리곤이 URL 에 안 들어간다).
                var st = STATE[uid] || {};
                fetch('/api/geo/plots/history', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': _csrf()
                    },
                    body: JSON.stringify({ map_uuid: st.mapUuid || p.geo_id,
                                           plot_uuid: p.unique_id })
                })
                    .then(function (r) { return r.json(); })
                    .then(function (h) {
                        if (h && h.ok) {
                            popupApi.fillPlotHistory(body, h.history, p.unique_id);
                        }
                    })
                    .catch(function () {});
            })
            .catch(function () {});
    }

    function _csrf() {
        var m = document.querySelector('meta[name="csrf-token"]');
        return (m && m.getAttribute('content')) || '';
    }

    function _api(method, url, body) {
        return fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': _csrf()
            },
            body: body ? JSON.stringify(body) : undefined
        }).then(function (r) {
            return r.json().then(function (d) { return { status: r.status, data: d }; });
        });
    }

    /**
     * 모달의 정보 편집 배선 — 보기 ↔ 편집 토글, 저장, 재배 종료.
     *
     * 저장하면 지도 레이어도 함께 갱신한다(작물 이름이 라벨이고 색이 도형색이라
     * 화면과 데이터가 갈리면 바로 눈에 띈다).
     */
    function _wireEdit(uid, map, body, p, opts) {
        var view = body.querySelector('.aot-ov-plot-view');
        var form = body.querySelector('.aot-ov-plot-edit-wrap');
        var btnEdit = body.querySelector('.aot-ov-plot-edit');
        if (!view || !form || !btnEdit) return;

        // 숨기는 것은 버튼이 아니라 **버튼이 든 행**이다(.aot-ov-actions).
        // 버튼만 숨기면 빈 행이 남아 편집 중에만 블록 아래가 벌어진다.
        var editRow = btnEdit.closest('.aot-ov-actions') || btnEdit;
        function show(editing) {
            view.style.display = editing ? 'none' : '';
            form.style.display = editing ? '' : 'none';
            editRow.style.display = editing ? 'none' : '';
        }
        btnEdit.addEventListener('click', function () { show(true); });
        var btnCancel = body.querySelector('.aot-ov-plot-cancel');
        if (btnCancel) btnCancel.addEventListener('click', function () { show(false); });

        function refresh() {
            // 저장 뒤 목록을 다시 받아 레이어·라벨을 갱신하고 모달을 다시 연다.
            //
            // 보던 탭으로 되돌아간다 — 편집은 [개요]에서 하는데 저장하고 [현황]
            // 으로 튕기면 방금 무엇이 바뀌었는지 확인할 수 없다.
            var st = STATE[uid] || {};
            var base = st.opts || opts || {};
            var sec = _activeSec(body);
            var next = Object.assign({}, base, sec ? { openTab: sec } : {});
            load(uid, map, base).then(function () {
                openModal(uid, map, p.unique_id, next);
            });
        }

        // ── 단계 전환(P5) ────────────────────────────────────────────
        //
        // 승인은 기준점을 옮긴다 — 저장 뒤에는 단계·목표가 통째로 다시 계산되므로
        // 모달을 다시 연다(부분 갱신하면 어디는 새 기준, 어디는 옛 기준이 된다).
        var askRow = body.querySelector('.aot-ov-plot-stage-ask');
        var btnStage = body.querySelector('.aot-ov-plot-stage-ok');
        if (askRow && btnStage) {
            btnStage.addEventListener('click', function () {
                var dateEl = askRow.querySelector('.aot-ov-plot-stage-date');
                _api('POST', '/api/geo/plot/' +
                     encodeURIComponent(p.unique_id) + '/stage', {
                    stage_key: askRow.dataset.stageKey,
                    started_on: dateEl && dateEl.value,
                    source: askRow.dataset.stageSource
                }).then(function (res) {
                    if (res.status >= 400 || !res.data.ok) {
                        if (window.showToast) {
                            window.showToast(res.data.message ||
                                             _t('Save failed'), 'error');
                        }
                        return;
                    }
                    refresh();
                });
            });
        }

        // 자원 [적용] — 선언된 것만 켠다. 물이 나오는 일이라 한 번 묻는다.
        var btnRes = body.querySelector('.aot-ov-plot-res-apply');
        if (btnRes) btnRes.addEventListener('click', function () {
            if (!window.confirm(_t('Turn on the functions this stage declares?'))) {
                return;
            }
            _api('POST', '/api/geo/plot/' +
                 encodeURIComponent(p.unique_id) + '/resources')
                .then(function (res) {
                    if (res.status >= 400 || !res.data.ok) {
                        if (window.showToast) {
                            window.showToast(res.data.message ||
                                             _t('Save failed'), 'error');
                        }
                        return;
                    }
                    // 일부만 켜졌을 수 있다 — 조용히 지나가지 않는다.
                    var out = res.data.result || {};
                    if ((out.failed || []).length && window.showToast) {
                        window.showToast(
                            _t('Some functions could not be started.'),
                            'warning');
                    }
                    refresh();
                });
        });

        var btnUndo = body.querySelector('.aot-ov-plot-stage-undo');
        if (btnUndo) btnUndo.addEventListener('click', function () {
            // 되돌리기는 기록을 지우지 않지만 기준점은 되돌아간다 — 이후 단계가
            // 통째로 다시 계산되므로 한 번 묻는다.
            if (!window.confirm(_t('Undo the last confirmed stage change?'))) {
                return;
            }
            _api('DELETE', '/api/geo/plot/' +
                 encodeURIComponent(p.unique_id) + '/stage').then(function (res) {
                if (res.status >= 400 || !res.data.ok) {
                    if (window.showToast) {
                        window.showToast(res.data.message ||
                                         _t('Save failed'), 'error');
                    }
                    return;
                }
                refresh();
            });
        });

        // 종류를 바꾸면 프로그램 선택지가 따라와야 한다 — 안 따라오면 옛 종류의
        // 프로그램이 남고, 그것을 고른 저장을 서버가 거절한다.
        var _selKind = form.querySelector('[data-pf="kind"]');
        var _selProg = form.querySelector('[data-pf="program_uuid"]');
        if (_selKind) {
            _selKind.addEventListener('change', function () {
                refreshProgramChoices(_selKind, _selProg, _t('No program'));
            });
        }

        var btnSave = body.querySelector('.aot-ov-plot-save');
        if (btnSave) btnSave.addEventListener('click', function () {
            var payload = { unique_id: p.unique_id };
            form.querySelectorAll('[data-pf]').forEach(function (el) {
                payload[el.getAttribute('data-pf')] = el.value || '';
            });
            if (!payload.subject) return;
            _api('POST', '/api/geo/plot', payload).then(function (res) {
                if (res.status >= 400 || !res.data.ok) {
                    if (window.showToast) {
                        window.showToast(res.data.message || _t('Save failed'), 'error');
                    }
                    return;
                }
                refresh();
            });
        });

        // 재배 종료는 되돌리는 수단이 화면에 없다(지도에서 사라지고 기본
        // 목록에서도 빠진다). 버튼 하나로 끝나면 안 된다 — 무엇이 일어나는지
        // 말하고 한 번 더 묻는다.
        var btnEnd = body.querySelector('.aot-ov-plot-end');
        if (btnEnd) btnEnd.addEventListener('click', function () {
            var msg = _t('End this plot?') + '\n\n' +
                      _t('It disappears from the map and stays only as history. ' +
                         'This cannot be undone here.');
            if (!window.confirm(msg)) return;
            _api('POST', '/api/geo/plot/' + p.unique_id + '/end',
                 { reason: 'harvested' }).then(function (res) {
                if (res.status >= 400 || !res.data.ok) return;
                // 종료하면 기본 목록에서 빠지므로 지도에서도 사라진다.
                var st = STATE[uid] || {};
                load(uid, map, st.opts || opts || {});
                var ov = document.getElementById('aot-facility-ctrl-overlay-' + uid);
                if (ov) ov.remove();
            });
        });
    }


    /**
     * 베이스 지도 전환 후 레이어를 다시 올린다.
     *
     * `map.setStyle({diff:false})` 는 커스텀 소스·레이어를 **전부 지운다** —
     * 위젯의 `_rehydrateFromCache()` 가 다른 도형을 되살릴 때 이것도 함께 부른다.
     * 서버를 다시 부르지 않고 이미 받아 둔 목록으로 그린다(전환할 때마다
     * 네트워크를 다시 타면 베이스 전환이 느려진다).
     */
    function rehydrate(uid, map) {
        var st = STATE[uid];
        if (!st || !st.plots || !map) return;
        _render(uid, map, st.plots, st.opts || {});
    }

    window.AoTMapPlot = {
        load: load,
        rehydrate: rehydrate,
        setVisible: setVisible,
        isVisible: isVisible,
        openModal: openModal,
        refreshProgramChoices: refreshProgramChoices,
        state: function (uid) { return STATE[uid]; }
    };
})();
