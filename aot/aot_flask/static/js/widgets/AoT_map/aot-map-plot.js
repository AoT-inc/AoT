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
 *
 * ── 초기 표시 상태 계약(반복해서 깨졌던 자리) ──────────────────────────────
 *
 * 이 모듈은 site/zone/facility/equipment/device/drawn 6개 도형·9개 라벨
 * 종류와 달리 **자기만의 fetch**(`/api/geo/plots`)로 따로 데이터를 받는다.
 * 위젯 본체(aot-map-widget-vector.js)의 `loadGeoJSONLayers`/
 * `loadGeoDesignLabels` 는 `await` 되지만, 이 모듈의 `load()`는 의도적으로
 * `await` 하지 않는다(느린 로더 하나가 식생까지 함께 막던 사고가 있었다) —
 * 그래서 이 fetch 는 위젯의 나머지 초기화와 **시간이 어긋난 채** 끝난다.
 *
 * 다른 종류는 이 문제가 없다: `loadGeoJSONLayers` 가 꺼진 카테고리의 레이어를
 * 아예 만들지 않거나(그 종류엔 "숨길 것"이 없다), 만들더라도 그 직후(같은
 * await 사슬 안, 재실행 지연 없이) `addLayerPanel` 의 시딩이 곧바로 뒤따른다.
 *
 * **그래서 이 모듈은 "누가 나중에 와서 내 상태를 알려주길" 기다리면 안 된다.**
 * `load(uid, map, opts)` 를 부를 때 넘기는 `opts` 가 이 종류의 전체 초기
 * 표시 상태(도형: `opts.visible`, 라벨: `opts.labelHidden`)를 **전부** 담고
 * 있어야 하고, 이 모듈은 fetch 를 걸기도 전에 그 값을 `STATE[uid]` 에 먼저
 * 적어 둬야 한다 — 그래야 나중에 무엇이 먼저 끝나든(이 fetch 대 위젯의
 * 다른 초기화) 결과가 같다. `addLayerPanel` 이 뒤이어 다시 한 번 적용하는
 * 것은 **확인(legacy 폴백 포함 정본과 대조)**이지 **최초 통보**가 아니다.
 *
 * 이 계약이 깨질 때마다(도형 축 2026-08, 라벨 축 2026-08) "설정은 꺼져
 * 있는데 로드하면 잠깐 켜졌다 꺼진다"가 재발했다 — 새 축을 추가하거나 이
 * 모듈을 고칠 때는 반드시 이 순서(opts 로 받기 → fetch 전에 STATE 에 적기)
 * 를 지킬 것.
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
            line: 'aot-plot-line-' + uid,
            // 계획(시작 전)은 **별도 레이어**다. `line-dasharray` 는 MapLibre 에서
            // data-driven 을 지원하지 않아 한 레이어에서 `['case', …]` 로 가를 수
            // 없다 — 실선/점선을 나누려면 레이어를 나누는 수밖에 없다.
            // 이름은 그대로 `aot-plot-` 으로 시작해야 한다(레이어 컨트롤이 이름을
            // 보고 켜고 끈다 — 위 주석 참조).
            linePlanned: 'aot-plot-line-planned-' + uid
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
                    // 아직 시작 전 — 레이어가 이 값으로 점선/옅은 채움을 고른다.
                    // (MapLibre 의 `['get']` 은 boolean 을 그대로 읽는다.)
                    planned: !!p.planned,
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
    var _programsInflight = {};

    // GET 은 공유 캐시(AoTGeoData)를 지난다 — **지도 위젯이 여러 개면 이 모듈도
    // 그 수만큼 돈다.** 한 대시보드에 같은 지도를 보는 위젯이 3개 있는 구성이
    // 실제로 있고(김제: 지도·위성·위성2), 그때 여기서 생 fetch 를 쓰면 완전히
    // 같은 요청이 3벌 나간다(라즈베리파이 실측: plots 3회·programs 3회).
    // AoTGeoData 는 진행 중인 요청을 합치고 짧은 TTL 로 캐시한다.
    function _geoGet(url) {
        if (window.AoTGeoData) {
            return window.AoTGeoData.get(url).then(function (r) {
                return r.ok ? r.json() : null;
            });
        }
        return fetch(url, { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; });
    }

    function _loadPrograms(kind) {
        kind = kind || 'vegetation';
        // **끝난 결과만이 아니라 진행 중인 요청도 걸러야 한다.** 예전에는
        // `_programs[kind]` 만 봤는데, 그것은 응답이 온 뒤에야 채워진다 —
        // 위젯 셋이 같은 순간에 부르면 셋 다 비어 있는 캐시를 보고 전부
        // 요청했다. 조회는 이제 AoTGeoData 를 지나므로 합쳐지지만, 이 함수가
        // 만드는 프로미스도 함께 재사용해야 파싱과 후처리까지 한 번으로 끝난다.
        if (_programs[kind]) return Promise.resolve(_programs[kind]);
        if (_programsInflight[kind]) return _programsInflight[kind];

        var p = _geoGet('/api/geo/programs?kind=' + encodeURIComponent(kind))
            .then(function (res) {
                _programs[kind] = (res && res.ok) ? (res.programs || []) : [];
                delete _programsInflight[kind];
                return _programs[kind];
            })
            .catch(function () {
                delete _programsInflight[kind];
                _programs[kind] = [];
                return _programs[kind];
            });
        _programsInflight[kind] = p;
        return p;
    }

    function load(uid, map, opts) {
        opts = opts || {};
        if (!map || !opts.mapUuid) return Promise.resolve([]);
        _loadPrograms();

        // ⚠ **두 축(도형·라벨) 모두 fetch 걸기 전에 미리 심어 둔다.** 파일
        // 머리말의 "초기 표시 상태 계약" 참조 — 이 모듈은 위젯의 나머지
        // 초기화와 시간이 어긋난 채 끝나므로, 외부(addLayerPanel)가 나중에
        // 와서 알려주길 기다리면 그 사이 잘못된 기본값(보임)으로 그려진다.
        // `opts.visible`/`opts.labelHidden` 은 위젯이 이 함수를 부르는 시점에
        // 이미 갖고 있는 값(흔한 경우만, legacy 폴백은 없음)이므로 여기서
        // 먼저 적어 두면 그 창이 아예 생기지 않는다. 이미 사용자가 그 사이에
        // 직접 정한 값이 있으면 건드리지 않는다(`typeof ... !== 'boolean'`
        // 가드 — 아직 안 정해졌을 때만 채운다). `addLayerPanel` 의
        // `_applyShapeVisible`/`_readLabelHidden`(legacy 폴백까지 갖춘
        // 정본)이 뒤이어 다시 한 번 적용하는 것은 **확인**이지 **최초
        // 통보**가 아니다 — 여기서 이미 옳았어야 한다.
        (function () {
            var st = STATE[uid] = STATE[uid] || {};
            if (opts.visible != null && typeof st.shapeVisible !== 'boolean') {
                st.shapeVisible = !!opts.visible;
            }
            if (opts.labelHidden != null && typeof st.labelVisible !== 'boolean') {
                st.labelVisible = !opts.labelHidden;
            }
        })();

        // **계획(시작 전)도 함께 받는다.** 자리를 정하는 일이 곧 계획이고,
        // 그 자리를 정하는 화면이 지도다 — 만들자마자 사라지면 무엇을 어디에
        // 두었는지 확인할 방법이 없다. 자라는 것과는 **점선**으로 가른다
        // (`planned` 속성 → 레이어 paint).
        return _geoGet('/api/geo/plots?include_planned=1&map_uuid=' +
                       encodeURIComponent(opts.mapUuid))
            .then(function (res) {
                if (!res || !res.ok) return [];
                var rows = res.plots || [];
                var st = STATE[uid] = STATE[uid] || {};
                st.plots = rows;
                st.mapUuid = opts.mapUuid;
                st.opts = opts;          // 스타일 전환 후 재생성에 그대로 쓴다
                _render(uid, map, rows, opts);
                return rows;
            })
            .catch(function () { return []; });
    }

    // ⚠ **주기 폴링을 두지 않는다** — 다른 도형과 같이 한 번만 받는다.
    //
    // 예전에는 여기 5분 주기 setInterval 이 있었다. 이유는 "식생은 geo/design 이나
    // 다른 브라우저에서 바뀌는데(새로 그리기·재배 종료) 한 번만 받으면 종료한
    // 구획이 지도에 계속 남는다" 였다. 그 증상 자체는 사실이지만, **다른 도형
    // 종류가 전부 그렇다** — 대지·구역·시설·설비는 `loadGeoJSONLayers` 가 위젯
    // 초기화에서 딱 한 번 받고 두 번 다시 받지 않는다(그 함수를 부르는 곳은
    // `aot-map-widget-vector.js` 한 자리뿐이다). 구획만 폴링을 가진 것은 근거
    // 없는 예외였고, 값은 그 예외로 다음을 치렀다:
    //
    //   `_render` 는 라벨을 **통째로 다시 만든다**(`_clearLabels` 로 마커를 전부
    //   지우고 구획 수만큼 `new maplibregl.Marker` + DOM + 클릭 리스너를 새로
    //   만든다). 다른 종류는 레이어를 한 번 만든 뒤 visibility 만 토글하거나
    //   기존 DOM 의 클래스만 바꾼다. 그 재생성이 위젯마다 5분마다 돌았다.
    //
    // 구획이 바뀌는 주기는 분·시가 아니라 **일·주** 단위다(사용자 확인,
    // 2026-08-29). 그 정도 신선도를 위해 5분마다 라벨을 다 버리고 다시 만들
    // 이유가 없다 — 새로고침하면 최신이고, 이 위젯 안에서 편집한 경우는
    // `_wireEdit` 의 `refresh()` 가 그 자리에서 `load()` 를 다시 불러 즉시
    // 반영한다(그 경로는 그대로 남아 있다).

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
                        // 계획은 한 번 더 옅다. **감추지는 않는다** — 자리를
                        // 잡아 둔 사실이 보여야 다음 구획을 어디에 둘지 정한다.
                        'fill-opacity': ['case', ['get', 'planned'], 0.10, 0.22]
                    }
                });
                map.addLayer({
                    id: id.line, type: 'line', source: id.src,
                    filter: ['!', ['to-boolean', ['get', 'planned']]],
                    paint: { 'line-color': ['get', 'color'], 'line-width': 1.5 }
                });
                // **점선이 "아직 아니다" 를 말한다.** 색을 바꾸거나 흐리게만
                // 하면 "멀리 있는 것"·"값이 낡은 것" 과 구별되지 않는다(이
                // 지도는 이미 흐림을 stale 에 쓰고 있다).
                map.addLayer({
                    id: id.linePlanned, type: 'line', source: id.src,
                    filter: ['to-boolean', ['get', 'planned']],
                    paint: {
                        'line-color': ['get', 'color'],
                        'line-width': 1.5,
                        'line-dasharray': [2, 2]
                    }
                });
                // **구획 도형에는 클릭을 걸지 않는다** — 모달을 여는 것은
                // 라벨뿐이고, 이는 지도 전체의 규칙이다(필지·구역·시설도
                // 라벨과 값 키로만 연다). 구획은 특히 겹치는 것이 정상이라
                // (간작·혼작) 도형 클릭은 무엇이 열릴지 예측할 수 없었고,
                // 팬을 시작하려고 짚은 것까지 창이 떴다. 커서도 pointer 로
                // 바꾸지 않는다 — 누를 수 없는 것을 누를 수 있다고 말하는 셈이다.
            }
        } catch (e) {
            console.warn('[AoT Map] 식생 레이어 렌더 실패:', e);
            return;
        }

        _renderLabels(uid, map, rows, opts);
        // ⚠ **도형 축만 적용한다.** 예전에는 `setVisible`(도형+라벨)을 불렀는데,
        // `opts.visible` 은 도형 옵션(`show_plots`, [도형] 그룹)이다. 그래서 렌더가
        // 돌 때마다 도형 옵션이 라벨 축을 덮어썼다 — **라벨 토글을 켜 두어도
        // 새로고침하면 라벨이 안 나오고**(도형이 꺼져 있으면), 5분 주기 갱신에서도
        // 같은 일이 반복됐다. 구획만 둘이 묶여 있던 마지막 자리다.
        //
        // 라벨 축의 주인은 위젯의 라벨 토글(`label_hidden_plot`)이고, 그 값은
        // `setLabelVisible` 로 들어와 `st.labelVisible` 에 남아 있다. 여기서
        // 건드리지 않으면 방금 만든 라벨에도 `_renderLabels` 안의
        // `_applyLabelVisibility` 가 그 값을 그대로 적용한다.
        //
        // ⚠ **`opts.visible` 은 위젯이 처음 로드될 때 찍힌 스냅샷이다** — 레이어
        // 패널·설정모달에서 [구획]을 껐다 켜면 `AoTMapPlot.setShapeVisible` 로
        // `st.shapeVisible` 만 바뀌고, `opts`(= `st.opts`, `load()` 때 넣은 그대로)는
        // 절대 갱신되지 않는다. 예전에는 이 자리에서 매번 `opts.visible` 로
        // 되썼기 때문에, `_render` 가 다시 돌 때마다(당시엔 5분 폴링도 있었고,
        // 지금은 베이스맵 전환 rehydrate·모달 저장 후 재로드) 방금 끈 도형이
        // 페이지 로드 당시 값으로 되살아났다("구획만 제멋대로 켜졌다 꺼졌다"의
        // 근본 원인).
        // 이미 사용자가 정한 값(`st.shapeVisible`)이 있으면 그것을 따른다 —
        // `load()` 앞머리의 선-시딩(파일 머리말 계약 참조) 덕에 첫 렌더에서도
        // 보통 이미 정해져 있고, 옵션 스냅샷(`opts.visible`)은 그 선-시딩이
        // 어떤 이유로든 안 됐을 때만 쓰는 마지막 폴백이다.
        var _stNow = STATE[uid] = STATE[uid] || {};
        var _wantShapeVisible = (typeof _stNow.shapeVisible === 'boolean')
            ? _stNow.shapeVisible : (opts.visible !== false);
        setShapeVisible(uid, map, _wantShapeVisible);
        _stNow.visible = _wantShapeVisible;

        // 도형 축 적용은 줌을 모른다(`setShapeVisible` 은 무조건 'visible' 을
        // 쓴다) — 위젯의 줌 LOD(`_applyShapeLOD`, [도형] 카테고리를
        // `equipment_cull_zoom` 아래에서 컬링한다)를 즉시 재적용하지 않으면,
        // 멀리 줌아웃한 채로 폴링/rehydrate 가 돌 때마다 컬링돼 있어야 할 구획
        // 도형이 다음 zoomend 까지 잠깐 다시 나타난다. 라벨의 `_applyZoomGate`
        // 노출(위 `_renderLabels`)과 같은 이유.
        //
        // ⚠ **첫 렌더(addLayerPanel 이 아직 카테고리 레지스트리를 못 시딩했을
        // 수 있는 시점)에는 이 함수가 아직 노출 전이라 `typeof` 가드가 자연히
        // 건너뛴다** — 그래서 안전하다. `addLayerPanel`(loadGeoJSONLayers 를
        // 기다린 뒤 실행)이 노출과 레지스트리 시딩을 항상 같은 동기 실행
        // 안에서 순서대로 하므로, 이 함수가 존재하는 시점에는 레지스트리도
        // 이미 옳다 — 노출 전 값(기본 true)을 읽어 방금 끈 도형을 되살리는
        // 일은 없다(실측: 콘솔 트레이스로 3개 위젯 전부 확인).
        try {
            var _inst2 = window.AoTWidgetInstances && window.AoTWidgetInstances[uid];
            if (_inst2 && typeof _inst2._applyShapeLOD === 'function') {
                _inst2._applyShapeLOD();
            }
        } catch (e) {}
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
        st.markers = [];
        // 위젯이 빌려주는 공용 라벨 배선(`_installZoomGate` 에서 노출).
        var inst = (window.AoTWidgetInstances || {})[uid];

        (rows || []).forEach(function (p) {
            var geom = _geomOf(p);
            if (!geom || !p.subject) return;
            var pos = _labelPoint(geom, p);
            if (!pos) return;

            var el = document.createElement('div');
            // 계획은 라벨에서도 갈린다 — 도형만 점선으로 두면 라벨이 자라는
            // 것과 똑같아, 라벨만 보고 읽는 사람에게는 아무 차이가 없다.
            el.className = 'aot-sensor-map-marker aot-bay-chip aot-plot-chip' +
                           (p.planned ? ' aot-plot-chip--planned' : '');
            el.innerHTML = '<div class="aot-bay-chip-name"></div>';
            el.querySelector('.aot-bay-chip-name').textContent = p.subject;
            el.style.fontSize = _labelEm(opts) + 'em';
            // **위젯의 라벨 관리에 등록한다.** 종류(`plot`)를 새기지 않으면
            // 위젯의 줌 게이트(`[data-label-kind]` 를 훑는다)·쌓임·충돌이 이
            // 라벨을 아예 못 본다 — 구획 라벨이 그동안 그 밖에 있었다.
            //
            // 배선은 **위젯 것을 그대로 빌려 쓴다**(`_wireLabelStacking`):
            // 종류 새기기 + 기준 z(LABEL_Z.plot) + 호버하면 앞으로 + 만든 즉시
            // 줌 게이트 적용. 예전에는 여기서 `dataset.labelKind` 만 손으로
            // 찍었는데, 그러면 종류는 새겨져도 **쌓임 순서와 호버 반응이
            // 없다** — 다른 라벨은 호버하면 앞으로 오는데 구획만 가만히 있었고,
            // z 도 안 정해져 CSS 가 정하는 순서에 맡겨졌다(그 CSS 는 이미
            // "z-index 는 JS 공용 표가 정한다" 고 비워 둔 자리다,
            // `aot-sensor-label.css` `.aot-bay-chip`).
            var restoreZ = null;
            if (inst && typeof inst._wireLabelStacking === 'function') {
                restoreZ = inst._wireLabelStacking(el, 'plot');
            } else {
                el.dataset.labelKind = 'plot';   // 위젯을 못 찾은 경우의 폴백
            }
            // 임시 표시(focus)가 이 칩을 uuid 로 찾는다 — 그 구획의 모달이
            // 열려 있는 동안은 라벨을 꺼 두었어도 보여야 한다.
            el.dataset.plotUuid = p.unique_id;
            // 배경은 그 구획의 색 — 어느 구획의 이름인지 색으로 드러난다.
            el.style.background = _color(p);
            el.style.color = _readableOn(_color(p));
            el.style.cursor = 'pointer';
            el.addEventListener('click', function (ev) {
                ev.stopPropagation();
                var popup = openModal(uid, map, p.unique_id, st.opts || opts);
                // 연 라벨은 **창이 닫힐 때까지** 앞에 남긴다 — 호버 복귀에만
                // 맡기면 팝업을 만지러 포인터가 라벨을 벗어나는 순간 뒤로
                // 돌아간다. 구역 칩과 같은 규약(`_openBayPopup` 호출부).
                if (restoreZ && inst && inst._pinLabelToFront) {
                    inst._pinLabelToFront(el, restoreZ);
                    if (popup && popup.on) {
                        popup.on('close', function () { inst._unpinLabel(el); });
                    }
                }
            });

            try {
                st.markers.push(new window.maplibregl.Marker({ element: el })
                    .setLngLat(pos).addTo(map));
            } catch (e) { /* 마커 하나 실패가 나머지를 막지 않는다 */ }
        });

        // 라벨 축(사용자 토글)을 새로 만든 요소에 적용한다 — 아래 setLabelVisible
        // 주석과 같은 이유로, 이 함수가 markers 를 다시 만들 때마다 저장된 값을
        // 다시 입힌다.
        _applyLabelVisibility(uid);

        // ⚠ **줌 게이트는 이 모듈이 갖지 않는다.** 예전에는 여기서 자체 줌
        // 임계(`AoTMapLabelLayers.resolve().minZoom`, 하드코딩 16)를 읽어
        // `style.display` 로 직접 숨겼다 — 위젯의 통합 줌 게이트
        // (`LABEL_ZOOM_GATED`/`label_min_zoom`, 기본 17)와 **다른 기준**이었다.
        // 둘이 갈리면 사용자가 `label_min_zoom` 을 올려도 구획 라벨은 안 따라
        // 오고, 내려도(0 = 안 숨김) 구획만 계속 숨는 식으로 "한 옵션을 고치면
        // 다른 옵션이 안 먹는다" 는 증상이 났다.
        //
        // 대신 다른 라벨 종류(입력·출력·시설…)와 **같은 클래스 축**을 쓴다 —
        // `.aot-zoom-hidden`, 위젯의 `_applyZoomGate` 가 `[data-label-kind]`
        // 전체를 훑어 매긴다(이 라벨은 `dataset.labelKind='plot'` 로 이미
        // 그 명부에 있다). 여기서는 방금 새로 만든 요소가 **다음 줌 이벤트를
        // 기다리지 않고** 바로 반영되도록 그 함수를 한 번 불러 주기만 한다.
        try {
            var _inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uid];
            if (_inst && typeof _inst._applyZoomGate === 'function') {
                _inst._applyZoomGate();
            }
        } catch (e) {}

        if (reg && reg.register) {
            try {
                reg.register(uid, 'plot',
                             { key: reg.makeKey('plot', 'shape', uid) });
            } catch (e) { /* 레지스트리는 보조 */ }
        }
    }

    /** 라벨 축(사용자 토글)만 요소에 반영한다 — **줌은 보지 않는다.**
     *
     * 줌 숨김은 `.aot-zoom-hidden` 클래스로 위젯의 통합 게이트가 맡고, 이
     * 함수는 `.aot-type-hidden` 클래스로 `label_hidden_plot` 하나만 맡는다.
     * 두 클래스는 각자 독립으로 `display:none` 을 걸 수 있고(위젯 CSS의
     * `.aot-type-hidden:not(.aot-focus-show)` / `.aot-zoom-hidden:not(...)`),
     * `.aot-focus-show` 가 붙으면 **둘 다** 비켜간다 — 모달이 열려 있는 동안은
     * 사용자가 껐든 줌이 가렸든 라벨이 보인다. 도형만 이 조합이 아니라
     * 인라인 스타일로 숨었을 때는 `.aot-focus-show` 가 아무 힘이 없었다
     * (그 결함이 이번 정리의 계기다 — 도형은 켜지는데 라벨은 안 켜졌다).
     */
    function _applyLabelVisibility(uid) {
        var st = STATE[uid];
        if (!st || !st.markers) return;
        var hidden = st.labelVisible === false;
        st.markers.forEach(function (m) {
            try { m.getElement().classList.toggle('aot-type-hidden', hidden); }
            catch (e) {}
        });
    }

    /** 배경색 위에서 읽히는 글자색 — 흰색/검정 중 대비가 큰 쪽. */
    function _readableOn(hex) {
        var rgb = _rgb(hex);
        if (!rgb) return '#ffffff';
        return _luminance(rgb) > 0.45 ? '#1a1a1a' : '#ffffff';
    }

    /**
     * 도형만 켜고 끈다.
     *
     * **라벨은 건드리지 않는다** — 다른 계층(대지·구역·시설)은 레이어 컨트롤에서
     * 도형과 라벨이 따로 있는데 구획만 하나로 묶여 있었다. 도형을 끄면 라벨까지
     * 사라져, "구획이 어디에 있는지는 감추되 이름은 남기고 싶다" 를 할 수 없었다.
     */
    function setShapeVisible(uid, map, visible) {
        var id = _ids(uid);
        var v = visible ? 'visible' : 'none';
        [id.fill, id.line, id.linePlanned].forEach(function (lid) {
            try {
                if (map.getLayer(lid)) map.setLayoutProperty(lid, 'visibility', v);
            } catch (e) { /* 아직 안 올라간 레이어 */ }
        });
        // 라벨과 같은 이유로 조건 없이 적어 둔다 — 레이어가 아직 없어도 뜻은
        // 남아야 `_render` 가 만들 때 그대로 따른다.
        (STATE[uid] = STATE[uid] || {}).shapeVisible = !!visible;
    }

    /** 라벨 축만 켜고 끈다. 줌 게이트와는 **다른 축**이다(둘 다 꺼야 보이지 않는다
     * — `_applyLabelVisibility` 주석 참조).
     *
     * ⚠ **아직 이 위젯을 모를 때 불릴 수 있다.** 위젯은 새로고침 직후 저장된
     * 라벨 상태를 되살리려고 500·1500·3000ms 에 이것을 부르는데, 구획은 그때까지
     * 서버에서 안 왔을 수 있다. 예전에는 `if (st)` 라 그 호출이 **조용히 버려졌고**,
     * 뒤늦게 렌더된 라벨은 아무도 끈 적 없다는 듯 켜진 채 나왔다 — "토글을 꺼
     * 두고 새로고침하면 되돌아온다" 가 그 증상이다. 상태 칸을 먼저 만들어 두면
     * 나중에 렌더될 때 `_renderLabels` 의 `_applyLabelVisibility` 호출이 그
     * 값을 그대로 따른다.
     */
    function setLabelVisible(uid, map, visible) {
        var st = STATE[uid] = STATE[uid] || {};
        st.labelVisible = !!visible;
        _applyLabelVisibility(uid);
    }

    /** 도형·라벨을 함께 내리는 큰 스위치.
     *
     * ⚠ **렌더 경로에서 부르지 말 것.** `show_plots` 는 [도형] 그룹의 옵션이라
     * 그것으로 라벨까지 내리면 라벨 토글이 매 렌더마다 지워진다. 둘을 한 번에
     * 다뤄야 하는 바깥 호출자를 위해 남겨 둔다. */
    function setVisible(uid, map, visible) {
        setShapeVisible(uid, map, visible);
        var st = STATE[uid];
        if (st) st.visible = !!visible;
        setLabelVisible(uid, map, visible);
    }

    function isVisible(uid) {
        var st = STATE[uid];
        return !st || st.shapeVisible !== false;
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
            // 그 컨트롤이 만지는 것은 **도형 레이어**뿐이다 — 라벨 축은 따로다.
            if (st) { st.visible = !!d.visible; st.shapeVisible = !!d.visible; }
            if (st && st.opts) st.opts.visible = !!d.visible;
        });
    });

    // ── 클릭 → 중앙 모달 ────────────────────────────────────────────────────

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

        // 열 탭: 명시 지정(저장 후 복귀) > 위젯 옵션 popup_default_tab.
        var want = opts.openTab || opts.defaultTab;

        // **껍데기를 먼저 띄운다.** 예전에는 조회가 끝난 뒤에야 창이 떴다 — 그
        // 왕복 동안 화면에는 아무 일도 일어나지 않아 누른 사람은 눌린 줄을
        // 모른다. 구역·시설 창은 이미 이렇게 한다.
        //
        // 이름은 목록에 있는 것을 그대로 쓴다(지도가 그 이름으로 라벨을 그리고
        // 있다) — 조회를 기다려 이름을 채우면 껍데기의 뜻이 없다.
        var known = ((STATE[uid] || {}).plots || []).filter(function (x) {
            return x.unique_id === uuid;
        })[0] || {};
        // 세 번째 인자 = **열려 있는 동안 보이게 할 대상**. 사용자가 구획
        // 라벨·도형을 꺼 두었어도 이 창이 떠 있는 동안은 보인다 — 어디
        // 이야기인지 지도에서 못 찾으면 창 안의 값이 어느 자리 것인지 알 수
        // 없다. (셸이 닫힐 때 스스로 거둔다.)
        var popup = shell(popupApi.buildPlotModalSkeleton(
            known.name || known.subject || '', { defaultTab: want }),
            uid, uuid);
        var el0 = popup && popup.getElement && popup.getElement();
        var body = el0 && el0.querySelector('.maplibregl-popup-content');
        if (!body) return;

        // 뒤로가기가 이 모달을 닫을 때 쓴다(`close()` 아래). 이 셸(`_showFacility
        // CenterOverlay`)은 같은 uid 의 다음 모달이 뜰 때 자기 DOM id 로 알아서
        // 갈아 끼우지만, 뒤로가기가 **다음 모달을 열지 않는 경우**(bay 1개 시설
        // 뒤로가기처럼 지도로 그냥 돌아가는 경로)에는 그 자동 교체가 안 일어나
        // 아무도 이 모달을 못 닫는다 — 참조가 이 함수 지역 변수뿐이었다.
        var st0 = STATE[uid] = STATE[uid] || {};
        st0.popup = popup;
        if (popup.on) {
            popup.on('close', function () {
                if (STATE[uid] && STATE[uid].popup === popup) STATE[uid].popup = null;
            });
        }

        // 뒤로가기를 **껍데기 단계에서** 세운다. 목록에 이미 있는 것(시설이면
        // 이름까지, 노지면 상위 uuid)으로 위젯이 지도에서 나머지를 푼다 —
        // 조회를 기다릴 이유가 없다. 못 풀면 조용히 넘어가고 상세가 오면
        // 그때 다시 부른다.
        if (typeof opts.wireUp === 'function') {
            try { opts.wireUp(uid, body, known); } catch (e) {}
        }

        // cache:'no-store' — 이 응답에는 Cache-Control 이 없어서 브라우저가
        // 휴리스틱 캐시를 걸 수 있다. 저장 직후 다시 여는 경로가 있는데
        // (일정 추가·작물 편집) 거기서 옛 사본이 나오면 "저장했는데 화면이
        // 그대로" 가 된다.
        fetch('/api/geo/plot/' + encodeURIComponent(uuid), { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (!res || !res.ok) return null;
                var p = res.plot;
                // 이 구획 종류의 목록이 아직 없으면 받아 온 뒤 그린다 — 없는
                // 채로 그리면 프로그램 줄이 통째로 빠진다(빌더는 선택지가 없으면
                // 줄을 내지 않는다).
                //
                // 여기서 `openModal` 을 다시 부르지 않는다: 껍데기가 이미 떠
                // 있으므로 다시 부르면 창이 둘이 된다.
                var _k = p.kind || 'vegetation';
                var ready = _programs[_k] ? Promise.resolve()
                                          : _loadPrograms(_k);
                return ready.then(function () { return p; });
            })
            .then(function (p) {
                if (!p || !body.isConnected) return;
                // 관리 프로그램 선택지를 실어 준다 — 모달 빌더는 순수 함수라
                // 스스로 조회하지 않는다(조회는 위젯의 일이다).
                p.program_choices = _programs[p.kind || 'vegetation'] || [];
                // 자리막이를 진짜 내용으로 바꾼다. 껍데기가 같은 골격이라
                // 헤더·탭은 그대로 있고 안쪽만 채워진다.
                body.innerHTML = popupApi.buildPlotModal(
                    p, { defaultTab: want });
                // 연 구획이 보이도록 지도를 옮긴다. 옮기는 것은 위젯의 일이라
                // (카메라 여백이 패널 폭을 알아야 한다) 콜백으로 위임한다.
                // 도형은 응답의 feature 에 실려 온다 — 구획 소스는 이 모듈이
                // 직접 붙여서 위젯의 소스 목록에는 없다.
                if (typeof opts.focus === 'function') {
                    try { opts.focus(p); } catch (e) {}
                }

                // 뒤로가기 — **여기서 배선한다.** 제어 배선(`attachControl`)은
                // `/contents` 를 기다리는데, 그 조회는 센서·환경·밸브를 함께
                // 끌어오는 무거운 것이라 제목줄의 화살표만 창이 다 그려진 뒤에도
                // 한참 늦게 튀어나왔다. 상위가 누구인지는 이 응답에 이미 있다.
                if (typeof opts.wireUp === 'function') {
                    try { opts.wireUp(uid, body, p); } catch (e) {}
                }

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

                // 최신 사진 — [현황] 맨 위. **이 구획의 노트만** 본다
                // (`descendants` 를 켜면 구역 사진이 구획 사진인 것처럼 보인다).
                // 사진이 없으면 자리 자체를 비워 둔다.
                _fillLatestPhoto(body, p.unique_id);

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
            .catch(function () {
                // 자리막이는 스스로 걷히지 않는다 — 실패하면 영영 도는 것처럼
                // 보인다. 무엇이 없는지 한 줄로 말하고 멈춘다.
                if (!body || !body.isConnected) return;
                var pane = body.querySelector(
                    '.aot-bay-popup-pane[data-pane="overview"]');
                if (pane) {
                    pane.innerHTML = '<div class="aot-ov-block aot-ov-muted">' +
                        _t('Failed to load data.') + '</div>';
                }
            });

        // 껍데기를 돌려준다 — 부른 쪽이 닫힘에 무언가를 걸 수 있어야 한다
        // (구획 칩은 여기에 라벨 핀 해제를 건다). 위 조회는 비동기라 이 반환을
        // 기다리지 않는다.
        return popup;
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
     * [현황] 맨 위의 최신 사진.
     *
     * 노트 목록은 이미 `AoTNotesBlock` 이 같은 엔드포인트로 받는다. 그래도 여기서
     * 한 번 더 부르는 이유는 그 블록이 자기 DOM 안에서만 그리기 때문이다 — 사진을
     * 카드 위로 올리려면 응답이 이쪽에도 있어야 한다. (한 번의 왕복을 아끼려고
     * 블록에 콜백을 뚫으면 노트 블록이 이 화면 전용 지식을 갖게 된다.)
     *
     * **같은 사진이면 노드를 그대로 둔다.** 이 pane 은 다시 그려질 수 있는데,
     * `<img>` 를 매번 새로 만들면 그때마다 사진이 한 번 깜빡인다.
     */
    function _fillLatestPhoto(body, plotUuid) {
        var slot = body && body.querySelector('[data-slot="photo"]');
        var P = window.AoTMapPopup;
        if (!slot || !P || !P.latestNotePhoto) return;
        fetch('/notes/target/' + encodeURIComponent(plotUuid),
              { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (notes) {
                if (!slot.isConnected) return;
                var photo = P.latestNotePhoto(notes);
                var cur = slot.querySelector('img');
                if (photo && cur && cur.getAttribute('src') === photo.url) return;
                slot.innerHTML = P.buildPhotoCardHtml(photo);
            })
            .catch(function () { /* 사진은 곁들이다 — 실패해도 나머지는 그대로 */ });
    }

    /**
     * 단계 일정 저장 (P8). 본문은 둘 중 하나다 —
     * `{days: {단계키: 일수}}`(화면의 기본 어휘) 또는
     * `{plan: {단계키: 'YYYY-MM-DD' | null}}`(날을 못박는 [연기]·[기본으로]).
     *
     * 성공하면 모달을 다시 연다. 경계 하나를 옮기면 뒤가 통째로 밀리고 단계·
     * 목표·예상 종료일이 전부 다시 계산되므로, 부분 갱신하면 어디는 새 일정
     * 어디는 옛 일정이 된다(승인과 같은 이유).
     */
    function _saveSchedule(plotUuid, payload, done) {
        return _api('POST', '/api/geo/plot/' + encodeURIComponent(plotUuid) +
                    '/schedule', payload).then(function (res) {
            if (res.status >= 400 || !res.data.ok) {
                if (window.showToast) {
                    window.showToast(res.data.message || _t('Save failed'),
                                     'error');
                }
                return false;
            }
            if (done) done();
            return true;
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

        // 날짜 [지우기] — 이 폼은 아직 공용 폼(`AoTPlotForm.wire`)을 지나지
        // 않으므로 배선을 직접 부른다. 마크업은 이미 공용 조각이다.
        if (window.AoTPlotForm && window.AoTPlotForm.wireDateClear) {
            window.AoTPlotForm.wireDateClear(form);
        }

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

        // [연기] — 같은 날짜 칸을 쓰지만 **사실이 아니라 계획**을 적는다(P8).
        // 확인은 "그 날 넘어갔다", 연기는 "그 날 넘어갈 것" 이다.
        var btnDefer = body.querySelector('.aot-ov-plot-stage-defer');
        if (askRow && btnDefer) {
            btnDefer.addEventListener('click', function () {
                var dateEl = askRow.querySelector('.aot-ov-plot-stage-date');
                var when = dateEl && dateEl.value;
                if (!when) {
                    if (window.showToast) {
                        window.showToast(_t('Pick a date first.'), 'warning');
                    }
                    return;
                }
                // 제안된 날짜 그대로 미루면 아무 일도 일어나지 않는다(그 날은
                // 이미 지난 계산상의 전환일이다). 조용히 지나가면 사용자는
                // 버튼이 고장 난 것으로 본다.
                if (when <= (dateEl.defaultValue || '')) {
                    if (window.showToast) {
                        window.showToast(_t('Pick a later date to postpone to.'),
                                         'warning');
                    }
                    return;
                }
                var plan = {};
                plan[askRow.dataset.stageKey] = when;
                _saveSchedule(p.unique_id, { plan: plan }, refresh);
            });
        }

        // ── 단계별 [편집] (P8) ──────────────────────────────────────
        //
        // 누르면 기간 입력과 지침 칸이 함께 열리고, [저장] 하나로 둘 다 보낸다.
        // 저장 버튼이 단계마다 둘이면 어느 것이 무엇을 저장하는지 매번 확인하게
        // 된다.
        body.querySelectorAll('.aot-ov-sched-edit').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var item = btn.closest('.aot-ov-sched-item');
                if (!item) return;
                var wrap = item.querySelector('.aot-ov-sched-edit-wrap');
                var view = item.querySelector('.aot-ov-sched-days-view');
                var edit = item.querySelector('.aot-ov-sched-days-edit');
                if (!wrap) return;
                var open = wrap.hidden;
                wrap.hidden = !open;
                if (edit) {
                    edit.hidden = !open;
                    if (view) view.hidden = open;
                }
                if (open) {
                    var first = (edit && edit.querySelector('input')) ||
                                wrap.querySelector('.aot-ov-sched-guide');
                    if (first) first.focus();
                }
            });
        });

        // 단계 [저장] — 기간과 지침을 함께. **바뀐 것만** 보낸다: 안 건드린
        // 기간까지 보내면 프로그램 기본이던 경계가 계획으로 굳는다.
        body.querySelectorAll('.aot-ov-sched-save').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var item = btn.closest('.aot-ov-sched-item');
                if (!item) return;
                var key = btn.getAttribute('data-stage-key');
                var ta = item.querySelector('.aot-ov-sched-guide');
                var dayEl = item.querySelector('.aot-ov-sched-days');
                var jobs = [];
                var moved = false;

                if (ta && ta.value !== (ta.defaultValue || '')) {
                    jobs.push(_api('POST', '/api/geo/plot/' +
                        encodeURIComponent(p.unique_id) + '/stage-guidance',
                        { stage_key: key, guidance: ta.value }));
                }
                if (dayEl && dayEl.value &&
                        dayEl.value !== (dayEl.defaultValue || '')) {
                    var days = {};
                    days[key] = dayEl.value;
                    moved = true;
                    jobs.push(_api('POST', '/api/geo/plot/' +
                        encodeURIComponent(p.unique_id) + '/schedule',
                        { days: days }));
                }
                if (!jobs.length) {
                    if (window.showToast) {
                        window.showToast(_t('Nothing changed.'), 'info');
                    }
                    return;
                }
                btn.disabled = true;
                Promise.all(jobs).then(function (res) {
                    btn.disabled = false;
                    var bad = res.filter(function (r) {
                        return r.status >= 400 || !r.data.ok;
                    })[0];
                    if (bad) {
                        if (window.showToast) {
                            window.showToast(bad.data.message ||
                                             _t('Save failed'), 'error');
                        }
                        return;
                    }
                    // 기간을 고쳤으면 뒤 단계의 날짜가 전부 다시 계산된다 —
                    // 부분 갱신하면 어디는 새 일정, 어디는 옛 일정이 된다.
                    if (moved) { refresh(); return; }
                    if (ta) ta.defaultValue = ta.value;
                    if (window.showToast) window.showToast(_t('Saved'), 'success');
                });
            });
        });

        // 단계 빼기 — 되돌리는 수단이 화면에 없으므로 한 번 묻는다.
        body.querySelectorAll('.aot-ov-sched-drop').forEach(function (btn) {
            btn.addEventListener('click', function () {
                if (!window.confirm(_t('Remove this stage from this plot?'))) {
                    return;
                }
                _api('DELETE', '/api/geo/plot/' +
                     encodeURIComponent(p.unique_id) + '/stages/' +
                     encodeURIComponent(btn.getAttribute('data-stage-key')))
                    .then(function (res) {
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
        });

        // 단계 더하기 — 여닫는 방식은 [편집]과 같다.
        var btnAddOpen = body.querySelector('.aot-ov-sched-addopen');
        if (btnAddOpen) btnAddOpen.addEventListener('click', function () {
            var wrap = body.querySelector('.aot-ov-sched-add-wrap');
            if (!wrap) return;
            wrap.hidden = !wrap.hidden;
            if (!wrap.hidden) {
                var el = wrap.querySelector('.aot-ov-sched-newname');
                if (el) el.focus();
            }
        });

        var btnAdd = body.querySelector('.aot-ov-sched-addgo');
        if (btnAdd) btnAdd.addEventListener('click', function () {
            var nameEl = body.querySelector('.aot-ov-sched-newname');
            var daysEl = body.querySelector('.aot-ov-sched-newdays');
            if (!nameEl || !nameEl.value.trim()) {
                if (window.showToast) {
                    window.showToast(_t('Stage name'), 'warning');
                }
                return;
            }
            _api('POST', '/api/geo/plot/' +
                 encodeURIComponent(p.unique_id) + '/stages', {
                name: nameEl.value,
                days: daysEl && daysEl.value
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


        // [프로그램으로 등록] — 등록은 **복사**다. 이 구획은 지금 따르던 것을
        // 그대로 따르므로 모달을 다시 열 필요가 없다.
        var btnRegOpen = body.querySelector('.aot-ov-sched-regopen');
        if (btnRegOpen) btnRegOpen.addEventListener('click', function () {
            var wrap = body.querySelector('.aot-ov-sched-reg-wrap');
            if (!wrap) return;
            wrap.hidden = !wrap.hidden;
            if (!wrap.hidden) {
                var el = wrap.querySelector('.aot-ov-sched-regname');
                if (el) el.focus();
            }
        });

        var btnReg = body.querySelector('.aot-ov-sched-reggo');
        if (btnReg) btnReg.addEventListener('click', function () {
            var nameEl = body.querySelector('.aot-ov-sched-regname');
            btnReg.disabled = true;
            _api('POST', '/api/geo/plot/' +
                 encodeURIComponent(p.unique_id) + '/save-as-program',
                 { name: nameEl && nameEl.value })
                .then(function (res) {
                    btnReg.disabled = false;
                    if (res.status >= 400 || !res.data.ok) {
                        if (window.showToast) {
                            window.showToast(res.data.message ||
                                             _t('Save failed'), 'error');
                        }
                        return;
                    }
                    // 만들어진 이름을 그대로 말한다 — 이름이 겹치면 서버가
                    // 번호를 붙이므로, 사용자가 적은 것과 다를 수 있다.
                    var nm = (res.data.program || {}).name || '';
                    if (window.showToast) {
                        window.showToast(
                            _t('Registered as a programme: %(name)s')
                                .replace('%(name)s', nm), 'success');
                    }
                    var wrap = body.querySelector('.aot-ov-sched-reg-wrap');
                    if (wrap) wrap.hidden = true;
                    if (nameEl) nameEl.value = '';
                    // 단계 일수는 실측으로 갱신되는데 목표값은 원본 그대로
                    // 복사된다. 무엇이 얼마나 달랐는지를 **등록한 자리에서**
                    // 보인다 — 고칠지는 사람이 정한다(화면은 판정하지 않는다).
                    if (window.AoTTargetReview) {
                        window.AoTTargetReview.render(
                            body.querySelector('.aot-ov-sched-reg-review'),
                            res.data.target_review);
                    }
                });
        });

        // 자동 승인 — 구획의 성질이다(P8). 켜면 확인 없이 기록되므로 바로 저장
        // 하고 모달을 다시 연다(단계가 그 자리에서 따라잡힐 수 있다).
        var togAuto = body.querySelector('.aot-ov-plot-auto');
        if (togAuto) togAuto.addEventListener('change', function () {
            _api('POST', '/api/geo/plot', {
                unique_id: p.unique_id,
                auto_advance: !!togAuto.checked
            }).then(function (res) {
                if (res.status >= 400 || !res.data.ok) {
                    togAuto.checked = !togAuto.checked;
                    if (window.showToast) {
                        window.showToast(res.data.message ||
                                         _t('Save failed'), 'error');
                    }
                    return;
                }
                refresh();
            });
        });

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
            // 몫(p6_50)은 서버가 dict 로 받는다. 수량인지 비율인지는 그 구역에
            // 총량이 적혀 있는지가 정한다 — 화면이 접미로 보인 것과 같은 기준이다.
            if ('allocation_value' in payload) {
                var _av = payload.allocation_value;
                delete payload.allocation_value;
                payload.allocation = (_av === '' || _av == null) ? null
                    : ((p.allocation && p.allocation.total != null)
                        ? { amount: _av } : { percent: _av });
            }
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
            // 창을 띄운다 — 끝내는 일과 **이어가는 일**을 함께 정한다.
            // (예전에는 confirm 한 줄이었고, 그 문구가 "도형이 지워진다" 로
            //  읽혀 사람이 종료를 못 눌렀다. 실제로는 아무것도 안 지워진다.)
            var P = window.AoTMapPopup;
            if (P && P.openPlotEnd && opts && typeof opts.shell === 'function') {
                P.openPlotEnd({
                    shell: opts.shell,
                    plot: p,
                    submit: function (url, body, done) {
                        _api('POST', url, body).then(function (res) {
                            if (res.status >= 400 || !res.data || !res.data.ok) {
                                done((res.data &&
                                      (res.data.message || res.data.error)) ||
                                     _t('Save failed'));
                                return;
                            }
                            done(null);
                        }).catch(function () { done(_t('Save failed')); });
                    },
                    onDone: function () {
                        // 목록·지도를 새로 받는다. 이어심기를 골랐으면 새 구획이
                        // 그 자리에 서 있어야 한다.
                        var st2 = STATE[uid] || {};
                        load(uid, map, st2.opts || opts || {});
                        var ov2 = document.getElementById(
                            'aot-facility-ctrl-overlay-' + uid);
                        if (ov2) ov2.remove();
                    }
                });
                return;
            }
            // 폴백 — 공용 모달이 없으면 예전 방식으로라도 끝낼 수 있어야 한다.
            if (!window.confirm(_t('End this plot?'))) return;
            btnEnd.disabled = true;
            _api('POST', '/api/geo/plot/' + p.unique_id + '/end',
                 { reason: 'harvested' }).then(function (res) {
                btnEnd.disabled = false;
                if (res.status >= 400 || !res.data || !res.data.ok) {
                    // **조용히 삼키지 않는다.** 권한 거부(edit_plots)나 검증
                    // 실패(종료일이 시작일보다 빠름)가 여기로 온다 — 아무 말이
                    // 없으면 사용자는 눌렀는데 아무 일도 안 일어난 것으로 읽고,
                    // 그때 원인을 알 방법이 없다.
                    var m = (res.data && (res.data.message || res.data.error)) ||
                            _t('Save failed');
                    if (window.showToast) window.showToast(m, 'error');
                    return;
                }
                // 종료하면 기본 목록에서 빠지므로 지도에서도 사라진다.
                var st = STATE[uid] || {};
                load(uid, map, st.opts || opts || {});

                // **상위로 되돌린다.** 시설·구역 목록에서 들어온 사람은 그
                // 목록으로 돌아가야 "빠졌구나" 를 본다 — 모달을 그냥 닫으면
                // 지도만 남아서 화면상으로는 아무 일도 안 일어난 것과 구별되지
                // 않는다. 뒤로가기 배선을 그대로 쓴다(복귀 경로가 두 벌이 되면
                // 갈라진다). 상위가 없으면(버튼이 숨겨져 있으면) 닫는다.
                var up = body.querySelector('.aot-modal-up');
                if (up && !up.hidden) { up.click(); return; }
                var ov = document.getElementById('aot-facility-ctrl-overlay-' + uid);
                if (ov) ov.remove();
            }).catch(function () {
                btnEnd.disabled = false;
                if (window.showToast) window.showToast(_t('Save failed'), 'error');
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

    // 지금 열려 있는 구획 모달을 닫는다 — 뒤로가기가 **다음 모달을 열지 않는**
    // 경로(bay 1개 시설처럼 지도로 그냥 돌아가는 경우)에서 쓴다. 다음 모달을
    // 여는 경로는 그 모달의 셸이 같은 DOM id 로 알아서 갈아 끼우므로 이 호출이
    // 필요 없다(무해하지만 중복이다).
    function close(uid) {
        var st = STATE[uid];
        if (st && st.popup) { try { st.popup.remove(); } catch (e) {} }
    }

    window.AoTMapPlot = {
        load: load,
        rehydrate: rehydrate,
        setVisible: setVisible,
        setShapeVisible: setShapeVisible,
        setLabelVisible: setLabelVisible,
        isVisible: isVisible,
        openModal: openModal,
        close: close,
        refreshProgramChoices: refreshProgramChoices,
        // 공용 폼(`AoTPlotForm.wire`)이 `loadPrograms(kind) -> Promise<list>` 를
        // 받는다. 목록 캐시가 여기 있으므로 조회는 계속 이 모듈이 맡는다 —
        // 화면마다 따로 받으면 같은 목록이 여러 벌 돌고, 종류를 바꿀 때마다
        // 화면 수만큼 왕복이 난다.
        loadPrograms: _loadPrograms,
        state: function (uid) { return STATE[uid]; }
    };
})();
