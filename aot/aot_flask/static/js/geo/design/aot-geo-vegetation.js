/**
 * aot-geo-vegetation.js
 *
 * 식생 구획(작기) UI — geo/design 의 "식생" 모드.
 * 설계 정본: docs/design/geo-vegetation-planting.md
 *
 * 다른 도형과 저장처가 다르다. 식생은 GeoShape 가 아니라 별도 테이블
 * (geo_planting)이고, 그래서 이 모듈은 saveDesign()/saveOverlays() 를 **쓰지
 * 않는다.** typesToSync 에 'vegetation' 을 넣지 말 것 — 넣으면 기존 전량교체
 * 저장 경로가 식생을 GeoShape 로 착각해 지운다.
 *
 * 겹침은 정상이다(간작·혼작). 그래서 클릭하면 최상단 하나를 고르는 대신
 * **후보 목록을 띄운다** — 이 페이지가 이미 겹친 도형 클릭으로 사고를 낸 적이
 * 있고(전량삭제), 식생에서는 그 상황이 예외가 아니라 기본이다.
 */

class AoTGeoVegetation {
    constructor(parent) {
        this.parent = parent;
        this._modalId = 'geoVegetationModal';
        this.layers = new Map();      // unique_id → layer
        this.data = new Map();        // unique_id → planting dict
        this._loaded = false;

        // 분할 미리보기 — 저장되지 않는 제안 하나. 지도에는 자기 GL 소스로만
        // 올라가므로 layerStorage 에도, 저장 경로에도 실리지 않는다.
        this._splitSrc = '_aot_split_preview_src';
        this._splitFill = '_aot_split_preview_fill';
        this._splitLine = '_aot_split_preview_line';
        this._split = null;
    }

    _t(key) { return (window._ ? window._(key) : key); }

    _toast(msg, level) {
        if (this.parent && this.parent.ui && this.parent.ui.showToast) {
            this.parent.ui.showToast(msg, level || 'info');
        } else if (window.showToast) {
            window.showToast(msg, level || 'info');
        }
    }

    _csrf() {
        const el = document.querySelector('meta[name="csrf-token"]');
        return el ? el.getAttribute('content') : '';
    }

    _api(method, url, body) {
        return fetch(url, {
            method,
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': this._csrf()
            },
            body: body ? JSON.stringify(body) : undefined
        }).then(res => res.json().then(data => ({ status: res.status, data })));
    }

    _mapUuid() {
        return (this.parent && this.parent.currentMapUuid) ||
               (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.map_uuid) || null;
    }

    _today() {
        // 로컬 날짜. toISOString() 은 UTC 로 변환하므로 한국 오전에는 하루
        // 전 날짜가 나온다 — 파종일이 하루 어긋나면 생육일수가 통째로 밀린다.
        const d = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    }

    /** 구획 색 — 개별 지정이 이기고, 없으면 테마의 vegetation. */
    colorOf(planting) {
        if (planting && planting.color) return planting.color;
        return window.AoTGeoTheme
            ? window.AoTGeoTheme.color('vegetation')
            : '#6a8f3c';
    }

    // ── 로드 ────────────────────────────────────────────────────────────

    /**
     * 지도의 재배 중인 구획을 불러와 레이어로 올린다.
     *
     * 종료된 작기는 불러오지 않는다(`include_ended` 없음). 몇 년 지난 지도에서
     * 옛 두둑까지 그리면 화면이 이력으로 뒤덮인다 — 이력은 "이 자리 이력"
     * 으로 따로 본다.
     */
    load(force) {
        const mapUuid = this._mapUuid();
        if (!mapUuid) return Promise.resolve([]);
        if (this._loaded && !force) return Promise.resolve([...this.data.values()]);

        return fetch(`/api/geo/plantings?map_uuid=${encodeURIComponent(mapUuid)}`)
            .then(r => r.json())
            .then(res => {
                if (!res || !res.ok) return [];
                this._clearLayers();
                (res.plantings || []).forEach(p => this._addLayer(p));
                this._loaded = true;
                this._renderChips();
                this._verifyAttached();
                return res.plantings || [];
            })
            .catch(() => []);
    }

    /** 칩을 전부 다시 그린다 (식생 모드에서만 띄운다). */
    _renderChips() {
        this._clearChips();
        this.data.forEach(p => this._renderChip(p));
    }

    _clearLayers() {
        this.layers.forEach(layer => {
            try {
                if (this.parent.map && this.parent.map.hasLayer &&
                    this.parent.map.hasLayer(layer)) {
                    this.parent.map.removeLayer(layer);
                }
                if (window.AoTMapEditor && window.AoTMapEditor.featureGroup &&
                    window.AoTMapEditor.featureGroup.hasLayer &&
                    window.AoTMapEditor.featureGroup.hasLayer(layer)) {
                    window.AoTMapEditor.featureGroup.removeLayer(layer);
                }
            } catch (e) { /* 이미 제거됨 */ }
        });
        this.layers.clear();
        this.data.clear();
    }

    /** planting dict → 지도 레이어. 이미 있으면 갱신. */
    _addLayer(planting) {
        if (!planting || !planting.feature) return null;
        this.data.set(planting.unique_id, planting);

        const existing = this.layers.get(planting.unique_id);
        if (existing) {
            this._ensureOnMap(existing);
            this._styleLayer(existing, planting);
            return existing;
        }

        let layer = null;
        try {
            const feature = JSON.parse(JSON.stringify(planting.feature));
            feature.properties = feature.properties || {};
            // aot_type 은 렌더·스타일 라우팅용 표시일 뿐 저장되지 않는다
            // (이 레이어는 saveOverlays 경로에 실리지 않는다).
            feature.properties.aot_type = 'vegetation';
            feature.properties.planting_uuid = planting.unique_id;
            feature.properties.name = planting.name || planting.crop;

            layer = this._layerFromFeature(feature);
            if (!layer) return null;
            layer.feature = feature;
            layer._aotPlantingUuid = planting.unique_id;

            if (this.parent.map && layer.addTo) layer.addTo(this.parent.map);
            // 편집 도구가 찾을 수 있도록 layerStorage 에도 등록한다
            // (_onDrawEdited 가 layerStorage 를 순회해 편집된 레이어를 찾는다).
            // 저장은 이 그룹을 통하지 않는다 — typesToSync 에 없으므로
            // saveOverlays 는 이 레이어를 보지 못한다.
            const store = this.parent.layerStorage &&
                          this.parent.layerStorage['vegetation'];
            if (store && store.addLayer) store.addLayer(layer);

            // `addTo()` 는 대상이 레이어 그룹이면 그룹에 위임하고 **`_map` 을
            // 설정하지 않는다**(aot-geo-layer.js:339). 그런데 `setStyle()` 은
            // 첫 줄에서 `if (!this._map) return` 이다 — 그래서 색·굵기가
            // _styleCache 에만 쌓이고 화면은 어댑터 기본 파랑(#3388ff)으로
            // 남는다. GL 레이어는 멀쩡히 올라가 있어서 "도형은 보이는데 색만
            // 안 먹는" 모양이 된다(실측으로 확인).
            if (!layer._map) layer._map = this.parent.map;

            // 붙었는지 확인하고 아니면 다시 붙인다. 레이어 그룹에 넣는 위
            // 단계가 어떤 조건에서는 방금 만든 GL 소스를 남기지 않는다 —
            // 두 구획을 연달아 그리면 뒤엣것만 소스 없이 남는 것을 실측했다.
            // 원인이 어느 쪽이든 화면에 안 그려지는 것은 조용한 실패라
            // 여기서 확인하고 복구한다.
            this._ensureOnMap(layer);

            this._styleLayer(layer, planting);
            if (this._emphasis !== false && layer.bringToFront) {
                try { layer.bringToFront(); } catch (e) {}
            }
            this._bindClick(layer, planting.unique_id);
        } catch (e) {
            console.error('[Vegetation] 레이어 생성 실패:', e);
            return null;
        }

        this.layers.set(planting.unique_id, layer);
        return layer;
    }

    /**
     * GeoJSON Feature → 레이어. 이 페이지의 지도 어댑터(AoTGeoLayer)를 그대로
     * 쓴다 — `fromGeoJSON` 은 레이어 **배열**을 돌려주므로 첫 번째를 취한다
     * (aot-map-editor-v2.js 의 사용법과 같다).
     *
     * 어댑터가 없으면 null 을 돌려주고 호출자가 조용히 건너뛴다. 여기서
     * 예외를 던지면 지도 로드 전체가 멈춘다.
     */
    _layerFromFeature(feature) {
        if (window.AoTGeoLayer && typeof window.AoTGeoLayer.fromGeoJSON === 'function') {
            const layers = window.AoTGeoLayer.fromGeoJSON(feature);
            return (layers && layers[0]) || null;
        }
        console.warn('[Vegetation] AoTGeoLayer 를 찾지 못해 구획을 그리지 못했다');
        return null;
    }

    /**
     * 레이어가 지도에서 빠졌으면 다시 붙인다.
     *
     * 모드를 전환하면 `_switchLayerContext` 가 layerStorage 그룹을 지도에서
     * 떼는데, 우리 `layers` 맵에는 객체가 그대로 남는다. 그러면 `_addLayer` 의
     * `existing` 분기가 "이미 있다" 고 판단해 **다시 붙이지 않아 그 구획만
     * 영영 안 그려진다** — 소스조차 없는 상태로 남는다(실측: 두 구획 중 하나만
     * srcExists=false).
     *
     * `_map` 을 비우고 addTo 를 다시 부르는 이유는, addTo 가 그 값으로 조기
     * 판단하지는 않지만 재부착 경로를 명확히 하기 위해서다.
     */
    /**
     * 스타일 로딩이 끝난 뒤 부착 상태를 한 번 더 확인한다.
     *
     * MapLibre 는 `isStyleLoaded()` 가 false 인 동안 addSource/addLayer 가
     * 조용히 실패한다(예외도 안 난다). 지도 로드 직후 구획을 그리면 **뒤엣것만
     * 소스 없이 남아 그 구획이 화면에서 통째로 사라진다** — 실측으로 확인했다.
     * 스타일이 준비된 시점에 다시 훑어 빠진 것을 붙인다.
     */
    _verifyAttached() {
        const map = this.parent.map;
        if (!map) return;
        const ml = map._originalMap || map;
        const run = () => this.layers.forEach((layer, uuid) => {
            this._ensureOnMap(layer);
            this._styleLayer(layer, this.data.get(uuid));
        });

        if (ml.isStyleLoaded && ml.isStyleLoaded()) { run(); return; }
        if (ml.once) ml.once('idle', run);
        else setTimeout(run, 1200);
    }

    _ensureOnMap(layer) {
        if (!layer || !layer._layerId || !this.parent.map) return;
        const mlMap = this.parent.map._originalMap || this.parent.map;
        try {
            if (mlMap.getSource && mlMap.getSource('aot-source-' + layer._layerId)) {
                return;                       // 이미 붙어 있다
            }
            layer._map = null;
            if (layer.addTo) layer.addTo(this.parent.map);
            if (!layer._map) layer._map = this.parent.map;
        } catch (e) { /* 지도가 아직 준비 전 */ }
    }

    /**
     * 구획 스타일. **식생 모드일 때 눈에 띄어야 한다.**
     *
     * 다른 도형(필지·구역)이 같은 자리에 겹쳐 그려지므로, 옅은 채움 하나로는
     * 어느 것이 식생인지 구분되지 않는다 — 그리려는 대상이 안 보이면 그릴 수가
     * 없다. 그래서 활성 모드에서는 진하게·굵게 그리고, 다른 모드에서는 배경으로
     * 물러난다(zone 을 그릴 때 식생이 시야를 가리면 그쪽이 방해가 된다).
     */
    _styleLayer(layer, planting) {
        if (!layer || !layer.setStyle) return;
        const color = this.colorOf(planting);
        const on = this._emphasis !== false;
        layer.setStyle({
            color: color,
            fillColor: color,
            // 위성 배경 위에서도 읽혀야 한다 — 반투명 채움만으로는 묻힌다.
            // 비활성 모드에서도 **존재는 보여야 한다**: 장치·배관을 배치할 때
            // 어디에 무엇이 심겨 있는지가 배치의 근거이기 때문이다. 아주 옅게
            // 두면(0.12) 위성 위에서는 사실상 사라져 참고가 되지 않는다.
            fillOpacity: on ? 0.45 : 0.20,
            weight: on ? 4 : 2,
            opacity: on ? 1 : 0.75,
            dashArray: planting && planting.active === false ? '4,4' : null
        });
    }

    /**
     * 모드 전환 시 호출 — 식생 모드면 강조, 아니면 배경으로.
     *
     * 색과 두께만으로는 부족하다: 관수 커버리지 원처럼 **나중에 추가된 레이어가
     * 위에 깔리면** 식생은 그 아래에서 회색빛으로 비친다(실측에서 정확히 그렇게
     * 보였다). 그래서 강조할 때는 맨 앞으로 올린다.
     */
    setEmphasis(on) {
        // 같은 값이라고 건너뛰지 않는다 — site→zone 처럼 둘 다 비활성인
        // 전환에서도 `_switchLayerContext` 는 레이어를 떼기 때문에, 여기서
        // 재부착을 확인하지 않으면 그 뒤로 식생이 영영 사라진다.
        this._emphasis = !!on;
        // 식생 모드를 벗어나면 분할 미리보기를 걷는다. 저장되지 않은 제안인데
        // 다른 모드에 점선만 남으면 적용·취소할 버튼이 화면에서 사라진 채로
        // 지도에 계속 떠 있는다 — 무엇인지 알 길이 없는 도형이 된다.
        if (!this._emphasis && this.hasSplitPreview()) this.clearSplitPreview();
        // 칩은 **모든 모드에서** 띄운다 — 장치·배관을 배치할 때 어디에 무엇이
        // 심겨 있는지가 배치의 근거라, 도형만 옅게 남기면 무엇인지 알 수 없다.
        // 대신 활성 모드가 아니면 살짝 흐리게 해 작업 대상과 구분한다.
        this._renderChips();
        this.layers.forEach((layer, uuid) => {
            // **모드와 무관하게 항상 다시 붙인다.** 모드를 바꾸면
            // `_switchLayerContext` 가 layerStorage 그룹을 지도에서 떼는데,
            // 식생까지 함께 사라지면 다른 모드에서 배치를 조정할 때 참고할
            // 것이 없어진다(실측: 다른 모드에서 전혀 안 보였다).
            this._ensureOnMap(layer);
            this._styleLayer(layer, this.data.get(uuid));
            if (on && layer.bringToFront) {
                try { layer.bringToFront(); } catch (e) { /* 어댑터에 따라 없을 수 있다 */ }
            }
        });
    }

    // ── 라벨 칩 ─────────────────────────────────────────────────────────
    //
    // 위젯과 **같은 칩**(aot-bay-chip)을 geo/design 에도 띄운다. 장치·구역
    // 라벨과 나란히 놓여야 겹침을 눈으로 보고 피할 수 있기 때문이다 —
    // 지도에 배치하는 화면에서 식생만 라벨이 없으면 무엇과 겹치는지 알 수 없다.
    //
    // 위치는 site/zone 라벨과 같은 방식으로 **드래그해서 옮긴다.** 다만 저장처는
    // `label_aux` GeoShape 가 아니라 구획 자신의 feature.properties 다 —
    // label_aux 는 GeoShape 라 식생을 지워도 남아 고아가 되고(부모 매칭이
    // node_id 기반이라 식생과 이어지지 않는다), 라벨 위치는 그 구획의 정보이지
    // 별도 도형이 아니다.
    _labelPoint(planting) {
        const props = (planting.feature && planting.feature.properties) || {};
        if (Array.isArray(props.label_lnglat) && props.label_lnglat.length === 2) {
            return props.label_lnglat;              // 사람이 옮긴 자리
        }
        const geom = planting.feature && planting.feature.geometry;
        if (!geom) return null;
        try {
            if (window.turf && window.turf.pointOnFeature) {
                return window.turf.pointOnFeature(
                    { type: 'Feature', properties: {}, geometry: geom }
                ).geometry.coordinates;
            }
        } catch (e) { /* 평균으로 */ }
        const ring = (geom.type === 'MultiPolygon') ? geom.coordinates[0][0]
                                                    : geom.coordinates[0];
        if (!ring || !ring.length) return null;
        let sx = 0, sy = 0;
        ring.forEach(c => { sx += c[0]; sy += c[1]; });
        return [sx / ring.length, sy / ring.length];
    }

    _readableOn(hex) {
        const h = String(hex || '').replace('#', '');
        const f = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
        if (f.length !== 6) return '#ffffff';
        const v = [0, 2, 4].map(i => {
            const c = parseInt(f.substr(i, 2), 16) / 255;
            return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        });
        const lum = 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
        return lum > 0.45 ? '#1a1a1a' : '#ffffff';
    }

    _clearChips() {
        (this._chips || []).forEach(m => { try { m.remove(); } catch (e) {} });
        this._chips = [];
    }

    _renderChip(planting) {
        if (!window.maplibregl || !window.maplibregl.Marker) return;
        const pos = this._labelPoint(planting);
        if (!pos || !planting.crop) return;
        const map = this.parent.map;
        const native = map._originalMap || (map.getNativeMap && map.getNativeMap()) ||
                       map._mlMap || map;

        const el = document.createElement('div');
        el.className = 'aot-sensor-map-marker aot-bay-chip aot-vegetation-chip';
        el.innerHTML = '<div class="aot-bay-chip-name"></div>';
        el.querySelector('.aot-bay-chip-name').textContent = planting.crop;
        const color = this.colorOf(planting);
        el.style.background = color;
        el.style.color = this._readableOn(color);
        el.style.cursor = 'move';
        // 이 페이지의 다른 라벨(geo-label-marker)이 12px 이다 — 식생만 크거나
        // 작으면 같은 화면에서 글자 크기가 들쭉날쭉해진다.
        el.style.fontSize = '12px';
        el.style.lineHeight = '1.2';
        // 활성 모드가 아니면 살짝 흐리게 — 존재는 알리되 작업 대상과 구분한다.
        el.style.opacity = (this._emphasis === false) ? '0.72' : '1';

        let marker;
        try {
            marker = new window.maplibregl.Marker(
                { element: el, anchor: 'center', draggable: true })
                .setLngLat(pos).addTo(native);
        } catch (e) { return; }

        // 클릭 = 선택, 더블클릭 = 기본 정보 편집.
        // 다른 라벨(site/zone)도 더블클릭으로 이름을 바꾼다 — 같은 손버릇이
        // 통해야 한다. 노트·이력 같은 운영 정보는 여전히 위젯 몫이고, 여기서
        // 고치는 것은 작물·품종·기간·색 같은 **도형의 기본 정보**다.
        el.addEventListener('click', (ev) => {
            ev.stopPropagation();
            this.select(planting.unique_id);
        });
        el.addEventListener('dblclick', (ev) => {
            ev.stopPropagation();
            ev.preventDefault();
            this.openEditForm(planting.unique_id);
        });

        // 드래그로 옮긴 자리를 저장한다 — 겹치는 칩을 사람이 풀 수 있어야 한다.
        marker.on('dragend', () => {
            const ll = marker.getLngLat();
            const feature = JSON.parse(JSON.stringify(planting.feature || {}));
            feature.properties = feature.properties || {};
            feature.properties.label_lnglat = [ll.lng, ll.lat];
            this._api('POST', '/api/geo/planting',
                      { unique_id: planting.unique_id, feature })
                .then(({ status, data }) => {
                    if (status >= 400 || !data.ok) {
                        this._toast(data.message || this._t('Save failed'), 'error');
                        return;
                    }
                    this.data.set(planting.unique_id, data.planting);
                });
        });

        (this._chips = this._chips || []).push(marker);
    }

    _bindClick(layer, uuid) {
        if (!layer || !layer.on) return;
        layer.on('click', (ev) => {
            if (ev && ev.originalEvent) {
                // 아래 도형(zone 등)의 클릭 핸들러까지 함께 터지면 엉뚱한
                // 모달이 겹쳐 열린다.
                if (ev.originalEvent.stopPropagation) ev.originalEvent.stopPropagation();
            }
            const latlng = ev && ev.latlng;
            this.handleClick(uuid, latlng);
        });
    }

    /**
     * 기본 정보 편집 — 칩 더블클릭으로 연다.
     *
     * 생성 폼과 **같은 골격**을 쓴다(_formHtml). 만들 때와 고칠 때 화면이
     * 다르면 같은 값을 두 군데서 배워야 한다.
     */
    openEditForm(uuid) {
        const p = this.data.get(uuid);
        if (!p) return;

        const body = this._shell(this._t('Planting'));
        body.innerHTML = this._formHtml(p);

        this._wireForm(body, (values) => {
            if (!values.crop) {
                this._toast(this._t('Crop is required'), 'warning');
                return;
            }
            this._api('POST', '/api/geo/planting',
                      Object.assign({ unique_id: uuid }, values))
                .then(({ status, data }) => {
                    if (status >= 400 || !data.ok) {
                        this._toast(data.message || this._t('Save failed'), 'error');
                        return;
                    }
                    this.data.set(uuid, data.planting);
                    const layer = this.layers.get(uuid);
                    if (layer) this._styleLayer(layer, data.planting);
                    this._renderChips();          // 이름·색이 바뀌면 칩도 바뀐다
                    this._close();
                    this._toast(this._t('Saved'), 'success');
                });
        });
    }

    // ── 편집 모드 — 다른 도형과 같은 도구로 고친다 ───────────────────────

    /**
     * 정점 편집이 끝나면 바뀐 기하를 저장한다.
     *
     * 편집 자체는 공용 편집 도구(그리기 컨트롤 패널의 편집 버튼)가 한다 —
     * 식생만 다른 편집 방식을 만들지 않는다. 다만 **저장처가 다르므로**
     * 그 완료 신호(`aot:editor:edited`)를 듣고 자기 API 로 보낸다.
     * design-v3 의 같은 리스너는 saveDesign() 을 부르지만 식생은
     * typesToSync 에 없어 거기서는 무시된다.
     *
     * 종료된 작기는 서버가 거부한다(VP-6 — 기하가 바뀌면 과거 이력이
     * 거짓말이 된다). 그래서 여기서도 보내지 않고 원래 모양으로 되돌린다.
     */
    bindEditHook() {
        if (this._editHookBound) return;
        this._editHookBound = true;

        window.addEventListener('aot:editor:edited', (ev) => {
            const detail = (ev && ev.detail) || {};
            const list = detail.features || detail.layers || [];
            const seen = new Set();

            const handle = (item) => {
                if (!item) return;
                const uuid = item._aotPlantingUuid ||
                             (item.properties && item.properties.planting_uuid) ||
                             (item.feature && item.feature.properties &&
                              item.feature.properties.planting_uuid);
                if (!uuid || seen.has(uuid)) return;
                seen.add(uuid);
                this._saveEditedGeometry(uuid, item);
            };

            if (typeof list.forEach === 'function') list.forEach(handle);
            else if (typeof list.eachLayer === 'function') list.eachLayer(handle);
        });
    }

    _saveEditedGeometry(uuid, item) {
        const known = this.data.get(uuid);
        if (known && known.active === false) {
            this._toast(this._t('Ended plantings cannot be reshaped.'), 'warning');
            this.load(true);          // 화면을 서버 상태로 되돌린다
            return;
        }

        const layer = this.layers.get(uuid) || item;
        let geom = null;
        try {
            const gj = (layer && layer.toGeoJSON) ? layer.toGeoJSON()
                     : (item && item.geometry ? item : null);
            geom = gj && (gj.geometry || gj);
        } catch (e) { geom = null; }
        if (!geom || !geom.type) return;

        this._api('POST', '/api/geo/planting', {
            unique_id: uuid,
            feature: { type: 'Feature', properties: {}, geometry: geom }
        }).then(({ status, data }) => {
            if (status >= 400 || !data.ok) {
                this._toast(data.message || this._t('Save failed'), 'error');
                this.load(true);      // 실패했으면 화면도 서버를 따라가야 한다
                return;
            }
            this.data.set(uuid, data.planting);
            this._toast(this._t('Saved'), 'success');
        });
    }

    // ── 클릭 — 겹침이 기본이라 후보를 고르게 한다 ────────────────────────

    /**
     * 구획을 **선택**한다. 다른 도형과 같은 방식이다 — 클릭하면 활성화되고,
     * 편집·삭제는 오른쪽 그리기 컨트롤 패널의 버튼이 그 활성 도형에 작용한다.
     *
     * 예전에는 클릭이 곧바로 편집 모달을 열었다. 그러면 이 페이지에서 도형을
     * 다루는 방식이 식생만 달라지고, 편집 도구로 정점을 고치려면 먼저 모달을
     * 닫아야 했다.
     *
     * 작물·기간 같은 **운영 정보 편집은 여기가 아니라** 대시보드 지도 위젯의
     * 구획 모달이 맡는다.
     */
    handleClick(uuid, latlng) {
        const hits = latlng ? this._hitsAt(latlng) : [];
        if (hits.length > 1) {
            this._openPicker(hits);      // 겹친 자리 — 어느 것을 고를지 묻는다
            return;
        }
        this.select(uuid);
    }

    /** 구획 레이어를 활성 도형으로 만든다. */
    select(uuid) {
        const layer = this.layers.get(uuid);
        if (!layer) return;
        if (this.parent && this.parent._setActiveLayer) {
            this.parent._setActiveLayer(layer);
        }
    }

    /** 클릭 지점을 포함하는 구획 전부 (겹침). */
    _hitsAt(latlng) {
        const out = [];
        if (!window.turf || !latlng) return out;
        const pt = window.turf.point([latlng.lng, latlng.lat]);
        this.data.forEach((planting) => {
            try {
                const geom = planting.feature && planting.feature.geometry;
                if (!geom) return;
                // 열린 링에서 turf.booleanPointInPolygon 이 예외를 던지는
                // 사례가 있어 방어한다 — 실패하면 그 구획만 후보에서 빠진다.
                if (window.turf.booleanPointInPolygon(pt, geom)) out.push(planting);
            } catch (e) { /* skip */ }
        });
        return out;
    }
    /**
     * 겹친 자리에서 어느 구획을 열지 고른다.
     *
     * 목록 행은 설정 모달의 옵션 행과 같은 골격(`aot-modal-option-row`)을 쓴다 —
     * 새 목록 CSS 를 만들지 않는다.
     */
    _openPicker(candidates) {
        const body = this._shell(this._t('Select a planting'), false);
        let html = `<div class="aot-modal-container">`;
        candidates.forEach(p => {
            html += `
                <div class="aot-modal-option-row">
                    <div class="aot-modal-option-label">
                        <span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${
                            this._esc(this.colorOf(p))};margin-right:8px;"></span>
                        ${this._esc(p.crop)}${p.variety ? ' · ' + this._esc(p.variety) : ''}
                        ${p.name ? `<div class="aot-modal-body-text">${this._esc(p.name)}</div>` : ''}
                    </div>
                    <div class="aot-modal-option-control">
                        <button type="button" class="btn aot-pill-btn" data-veg-pick="${
                            this._esc(p.unique_id)}">${this._t('Open')}</button>
                    </div>
                </div>`;
        });
        html += `</div>`;
        body.innerHTML = html;

        body.querySelectorAll('[data-veg-pick]').forEach(el => {
            el.addEventListener('click', () => {
                const id = el.getAttribute('data-veg-pick');
                this._close();
                setTimeout(() => this.select(id), 200);
            });
        });
    }

    // ── 그리기 → 저장 ───────────────────────────────────────────────────

    /**
     * 그리기 완료 처리. modules.onShapeCreated 가 식생 모드일 때 위임한다.
     */
    onShapeCreated(layer) {
        const mapUuid = this._mapUuid();
        if (!mapUuid) {
            this._toast(this._t('No map selected'), 'error');
            this._removeDrawn(layer);
            return;
        }

        let feature;
        try {
            feature = layer.toGeoJSON ? layer.toGeoJSON() : layer.feature;
        } catch (e) {
            feature = layer.feature;
        }
        if (!feature || !feature.geometry) {
            this._removeDrawn(layer);
            return;
        }
        const gtype = feature.geometry.type;
        if (gtype !== 'Polygon' && gtype !== 'MultiPolygon') {
            this._toast(this._t('Draw an area (polygon) for a planting.'), 'warning');
            this._removeDrawn(layer);
            return;
        }

        // 그리기 레이어는 지운다 — 저장 응답으로 다시 그린다. 두 벌이 남으면
        // 편집이 어느 쪽에 걸릴지 알 수 없다.
        this._removeDrawn(layer);
        this._openCreateForm(feature);
    }

    _removeDrawn(layer) {
        try {
            if (window.AoTMapEditor && window.AoTMapEditor.featureGroup &&
                window.AoTMapEditor.featureGroup.hasLayer &&
                window.AoTMapEditor.featureGroup.hasLayer(layer)) {
                window.AoTMapEditor.featureGroup.removeLayer(layer);
            }
            if (this.parent.map && this.parent.map.hasLayer &&
                this.parent.map.hasLayer(layer)) {
                this.parent.map.removeLayer(layer);
            }
        } catch (e) { /* 이미 없음 */ }
    }

    _openCreateForm(feature) {
        const body = this._shell(this._t('New planting'));
        const themeColor = this.colorOf(null);
        body.innerHTML = this._formHtml({ planted_on: this._today(),
                                          color: themeColor });
        this._wireForm(body, (values) => {
            // 색을 손대지 않았으면 저장하지 않는다 — 각인해 두면 나중에 테마
            // 색을 바꿔도 그 구획만 옛 색으로 남는다(색 정본은 theme_config).
            if (values.color && values.color.toLowerCase() === themeColor.toLowerCase()) {
                delete values.color;
            }
            if (!values.crop) {
                this._toast(this._t('Crop is required'), 'warning');
                return;
            }
            // 상위 zone 을 보내지 않는다 — 그냥 그리면 되고 소속은 서버가
            // 공간 포함으로 판정한다(equipment 와 같은 모델).
            const payload = Object.assign(
                { map_uuid: this._mapUuid(), feature: feature }, values);

            this._api('POST', '/api/geo/planting', payload).then(({ status, data }) => {
                if (status >= 400 || !data.ok) {
                    this._toast(data.message || this._t('Save failed'), 'error');
                    return;
                }
                this._addLayer(data.planting);
                this._close();
                this._toast(this._t('Saved'), 'success');
            });
        });
    }

    /**
     * 입력 폼 — 설정 모달과 같은 골격을 쓴다:
     * `aot-modal-group-title` > `aot-modal-container` > `aot-modal-option-row`
     * (label / control) + `aot-modern-input`.
     *
     * 인라인으로 크기·모서리·색을 주지 말 것. 공용 CSS(aot-modal-modern.css)가
     * 정본이고, 인라인 오버라이드는 모바일 미디어쿼리를 덮어써 폰에서 레이아웃이
     * 깨진다.
     */
    _formHtml(p) {
        p = p || {};
        const v = (x) => this._esc(x == null ? '' : x);
        const row = (label, control) => `
            <div class="aot-modal-option-row">
                <div class="aot-modal-option-label">${label}</div>
                <div class="aot-modal-option-control">${control}</div>
            </div>`;

        return `
            <div class="aot-modal-group-title">${this._t('Crop')}</div>
            <div class="aot-modal-container">
                ${row(this._t('Crop'),
                      `<input type="text" class="aot-modern-input form-control"
                              data-veg-field="crop" value="${v(p.crop)}" autocomplete="off">`)}
                ${row(this._t('Variety'),
                      `<input type="text" class="aot-modern-input form-control"
                              data-veg-field="variety" value="${v(p.variety)}">`)}
                ${row(this._t('Plot name'),
                      `<input type="text" class="aot-modern-input form-control"
                              data-veg-field="name" value="${v(p.name)}">`)}
            </div>

            <div class="aot-modal-group-title">${this._t('Growing period')}</div>
            <div class="aot-modal-container">
                ${row(this._t('Planted on'),
                      `<input type="date" class="aot-modern-input form-control"
                              data-veg-field="planted_on" value="${v(p.planted_on)}">`)}
                ${row(this._t('Expected end'),
                      `<input type="date" class="aot-modern-input form-control"
                              data-veg-field="expected_end_on" value="${v(p.expected_end_on)}">`)}
                ${row(this._t('Colour'),
                      `<input type="color" class="aot-modern-input form-control aot-detail-field-color"
                              data-veg-field="color" value="${v(p.color || this.colorOf(p))}">`)}
            </div>`;
    }

    /** 폼 값을 모아 저장 콜백에 넘긴다. 저장 버튼은 모달 푸터에 있다. */
    _wireForm(root, onSave) {
        const content = root.closest('.modal-content');
        const btn = content && content.querySelector('[data-veg-save]');
        if (!btn) return;
        btn.onclick = () => {
            const values = {};
            root.querySelectorAll('[data-veg-field]').forEach(el => {
                values[el.getAttribute('data-veg-field')] = el.value || '';
            });
            onSave(values);
        };
    }

    /**
     * 삭제 도구로 지운 구획을 서버에서도 지운다.
     *
     * 삭제 자체는 공용 삭제 도구(그리기 컨트롤 패널)가 한다 — 식생만 다른
     * 삭제 방식을 만들지 않는다. 저장처가 다르므로 그 신호를 듣고 자기 API 로
     * 보낼 뿐이다. design-v3 의 같은 리스너는 GeoShape 삭제 목록에 넣지만
     * 식생은 typesToSync 밖이라 거기서는 아무 일도 일어나지 않는다.
     */
    bindDeleteHook() {
        if (this._deleteHookBound) return;
        this._deleteHookBound = true;

        window.addEventListener('aot:editor:deleted', (ev) => {
            const detail = (ev && ev.detail) || {};
            const list = detail.features || detail.layers || [];
            const handle = (item) => {
                if (!item) return;
                const uuid = item._aotPlantingUuid ||
                             (item.properties && item.properties.planting_uuid) ||
                             (item.feature && item.feature.properties &&
                              item.feature.properties.planting_uuid);
                if (!uuid || !this.data.has(uuid)) return;
                this._api('DELETE', `/api/geo/planting/${uuid}`)
                    .then(() => {
                        this._dropLayer(uuid);
                        this._toast(this._t('Deleted'), 'success');
                    })
                    .catch(() => {
                        this._toast(this._t('Failed'), 'error');
                        this.load(true);   // 서버가 안 지웠으면 화면도 되돌린다
                    });
            };
            if (typeof list.forEach === 'function') list.forEach(handle);
            else if (typeof list.eachLayer === 'function') list.eachLayer(handle);
        });
    }

    _dropLayer(uuid) {
        const layer = this.layers.get(uuid);
        if (layer) {
            try {
                if (this.parent.map && this.parent.map.hasLayer &&
                    this.parent.map.hasLayer(layer)) {
                    this.parent.map.removeLayer(layer);
                }
            } catch (e) { /* noop */ }
        }
        this.layers.delete(uuid);
        this.data.delete(uuid);
        this._renderChips();
    }

    // ── 분할 — 구역 하나를 여러 구획으로 나눈다 ──────────────────────────
    //
    // 서버(`planting_split`)가 도형의 **긴 변을 따라** 조각을 낸다. 여기서는
    // 그 제안을 점선으로 그려 보여주기만 하고, 만들 때는 apply 가 **같은
    // 파라미터로 다시 계산**한다 — 화면이 본 폴리곤을 되돌려보내지 않는다.
    // 그러면 한 번 계산하고 다른 것을 저장하는 경로가 생기기 때문이고,
    // 분할은 결정적이라 재계산이 "본 것과 저장된 것이 같다" 를 구조로
    // 보장한다(routes_geo_planting.py 의 같은 주석).
    //
    // **진입은 지도 클릭이 아니라 목록이다.** 식생 모드에서 zone 도형은 클릭
    // 대상이 아니고(설계 정본: 겹침이 기본이라 클릭은 식생 후보만 고른다),
    // 이 페이지에는 "선택된 zone" 상태 자체가 없다. 클릭으로 고르게 하려면
    // 그 상태부터 만들어야 하는데, 그것은 예전에 사고를 낸 자리다.

    _nativeMap() {
        const m = this.parent && this.parent.map;
        return (m && (m._originalMap || m._mlMap)) || m || null;
    }

    /**
     * 지도에 올라와 있는 **나눌 수 있는 도형**(구역·대지) 목록.
     *
     * `shape_uuid` 가 GeoShape.unique_id 다(get_overlays 가 항상 싣는다).
     * 아직 저장되지 않은 도형에는 그것이 없다 — 서버가 찾지 못하므로 목록에
     * 올리지 않는다. 그리자마자 나누려면 먼저 저장해야 한다.
     */
    _areaShapes() {
        const out = [];
        const seen = new Set();
        const scan = (kind) => {
            const group = this.parent && this.parent.layerStorage &&
                          this.parent.layerStorage[kind];
            if (!group || typeof group.eachLayer !== 'function') return;
            try {
                group.eachLayer((layer) => {
                    const feature = layer && layer.feature;
                    const props = (feature && feature.properties) || {};
                    const uuid = props.shape_uuid;
                    if (!uuid || seen.has(uuid)) return;
                    const gtype = feature.geometry && feature.geometry.type;
                    if (gtype !== 'Polygon' && gtype !== 'MultiPolygon') return;
                    seen.add(uuid);
                    out.push({ uuid: uuid, kind: kind, name: props.name || '' });
                });
            } catch (e) { /* 그룹이 아직 준비 전 */ }
        };
        scan('zone');       // 구역이 먼저다 — 나누는 대상은 거의 구역이다
        scan('site');
        return out;
    }

    hasSplitPreview() { return !!(this._split && this._split.info); }

    /** 미리보기 요약 한 줄 — 패널 막대와 토스트가 같은 문구를 쓴다. */
    splitSummaryText() {
        if (!this.hasSplitPreview()) return '';
        const info = this._split.info;
        const parts = [];
        parts.push(`${this._t('Pieces')} ${info.count}`);
        parts.push(`${this._t('Piece width')} ${info.strip_width_m} m`);
        const lens = (this._split.strips || [])
            .map(s => s.length_m).filter(n => typeof n === 'number');
        if (lens.length) {
            const lo = Math.min.apply(null, lens);
            const hi = Math.max.apply(null, lens);
            parts.push(`${this._t('Length')} ${lo === hi ? lo : lo + '–' + hi} m`);
        }
        parts.push(`${this._t('Direction')} ${info.orientation_deg}°`);
        // 버린 조각을 숨기지 않는다 — 개수가 요청과 다른 이유가 그것이다.
        if (info.dropped) {
            parts.push(`${this._t('Dropped as too short')} ${info.dropped}`);
        }
        return parts.join(' · ');
    }

    /**
     * 패널 막대를 지금 상태로 다시 그린다.
     *
     * `render()` 를 인자 없이 부르면 `selectedFeature` 가 지워지고 파이프
     * 설정이 기본값으로 리셋된다. 지금 값을 그대로 넘겨 다시 그린다.
     */
    _refreshPanel() {
        const panel = this.parent && this.parent.panel;
        if (!panel || typeof panel.render !== 'function') return;
        try { panel.render(panel.currentMode, panel.selectedFeature); } catch (e) {}
    }

    /** 분할 입력 폼을 연다. 이미 미리보기가 있으면 그 값으로 채운다. */
    openSplitForm() {
        const areas = this._areaShapes();
        if (!areas.length) {
            this._toast(this._t('No zones or sites on this map. Draw one first.'),
                        'warning');
            return;
        }
        const prev = (this._split && this._split.args) || {};
        const prevValues = (this._split && this._split.values) || {};
        const themeColor = this.colorOf(null);

        const body = this._shell(this._t('Split into plots'), true,
                                 this._t('Preview'));
        // 작물·기간 칸은 생성 폼과 **같은 골격**을 쓴다. 만들 때와 나눌 때
        // 같은 값을 두 군데서 배우게 하지 않는다.
        body.innerHTML = this._splitFormHtml(areas, prev) +
                         this._formHtml(Object.assign(
                             { planted_on: this._today(), color: themeColor },
                             prevValues));

        const modeEl = body.querySelector('[data-veg-split="mode"]');
        const labelEl = body.querySelector('[data-veg-split-amount]');
        const amountEl = body.querySelector('[data-veg-split="amount"]');
        const syncMode = () => {
            const byWidth = modeEl && modeEl.value === 'width';
            if (labelEl) {
                labelEl.textContent = byWidth ? this._t('Piece width (cm)')
                                              : this._t('Number of pieces');
            }
            if (amountEl) {
                amountEl.min = byWidth ? '1' : '2';
                amountEl.step = byWidth ? '10' : '1';
            }
        };
        if (modeEl) {
            modeEl.addEventListener('change', () => {
                // 값을 지운다 — "3" 이 3등분에서 3cm 로 조용히 바뀌면
                // 사용자가 말하지 않은 굵기로 나뉜 제안을 보게 된다.
                if (amountEl) amountEl.value = '';
                syncMode();
            });
        }
        syncMode();

        this._wireForm(body, (values) => {
            if (!values.crop) {
                this._toast(this._t('Crop is required'), 'warning');
                return;
            }
            // 색을 손대지 않았으면 저장하지 않는다 — 생성 폼과 같은 규칙
            // (각인해 두면 나중에 테마 색을 바꿔도 그 구획만 옛 색으로 남는다).
            if (values.color &&
                values.color.toLowerCase() === themeColor.toLowerCase()) {
                delete values.color;
            }
            const parsed = this._splitArgsFrom(body);
            if (parsed.error) {
                this._toast(parsed.error, 'warning');
                return;
            }
            this._previewSplit(parsed.args, values);
        });
    }

    _splitFormHtml(areas, prev) {
        const row = (label, control, labelAttr) => `
            <div class="aot-modal-option-row">
                <div class="aot-modal-option-label"${labelAttr || ''}>${label}</div>
                <div class="aot-modal-option-control">${control}</div>
            </div>`;

        // 구역과 대지를 optgroup 으로 가른다 — 이름 뒤에 종류를 이어붙이면
        // 한 칸이 두 가지를 말하게 된다.
        const group = (kind, label) => {
            const items = areas.filter(a => a.kind === kind);
            if (!items.length) return '';
            return `<optgroup label="${this._esc(label)}">` + items.map(a =>
                `<option value="${this._esc(a.uuid)}"${
                    a.uuid === prev.zone_id ? ' selected' : ''}>${
                    this._esc(a.name || this._t('Unnamed'))}</option>`).join('') +
                `</optgroup>`;
        };

        const byWidth = prev.strip_width_cm != null;
        const amount = byWidth ? prev.strip_width_cm
                               : (prev.parts != null ? prev.parts : '');

        return `
            <div class="aot-modal-group-title">${this._t('Split into plots')}</div>
            <div class="aot-modal-container">
                ${row(this._t('Area to split'),
                      `<select class="aot-modern-input form-control"
                               data-veg-split="zone_id">${
                          group('zone', this._t('Zone'))}${
                          group('site', this._t('Site'))}</select>`)}
                ${row(this._t('Split by'),
                      `<select class="aot-modern-input form-control"
                               data-veg-split="mode">
                           <option value="parts"${byWidth ? '' : ' selected'}>${
                               this._t('Equal parts')}</option>
                           <option value="width"${byWidth ? ' selected' : ''}>${
                               this._t('Strip width')}</option>
                       </select>`)}
                ${row(this._t('Number of pieces'),
                      `<input type="number" min="2" step="1"
                              class="aot-modern-input form-control"
                              data-veg-split="amount" value="${this._esc(amount)}">`,
                      ' data-veg-split-amount')}
                ${row(this._t('Edge margin (cm)'),
                      `<input type="number" min="0" step="10"
                              class="aot-modern-input form-control"
                              data-veg-split="edge_margin_cm"
                              value="${this._esc(prev.edge_margin_cm || 0)}">`)}
                <div class="aot-modal-body-text">${
                    this._t('Room to turn machinery along the edge.')}</div>
                <div class="aot-modal-body-text">${
                    this._t('Pieces follow the longest side of the shape, and irregular edges are clipped.')}</div>
                <div class="aot-modal-body-text">${
                    this._t('Each piece is numbered after the plot name.')}</div>
                <div class="aot-modal-body-text">${
                    this._t('Nothing is saved until you create the plots.')}</div>
            </div>`;
    }

    /** 폼 → 서버 파라미터. 등분과 폭은 **한 칸**이라 둘 다 보낼 수 없다. */
    _splitArgsFrom(body) {
        const get = (key) => {
            const el = body.querySelector(`[data-veg-split="${key}"]`);
            return el ? String(el.value || '').trim() : '';
        };
        const zoneId = get('zone_id');
        if (!zoneId) {
            return { error: this._t('Pick a zone or site to split.') };
        }
        const amount = parseFloat(get('amount'));
        if (!isFinite(amount) || amount <= 0) {
            return { error: this._t('Enter how many pieces, or how wide each piece is.') };
        }
        const args = { zone_id: zoneId };
        if (get('mode') === 'width') args.strip_width_cm = amount;
        else args.parts = Math.round(amount);

        const margin = parseFloat(get('edge_margin_cm'));
        if (isFinite(margin) && margin > 0) args.edge_margin_cm = margin;
        return { args: args };
    }

    /**
     * 제안을 받아 지도에 그리고 모달을 닫는다.
     *
     * 모달을 닫는 이유는 그것이 지도 가운데를 덮기 때문이다 — 보라고 그린
     * 점선을 볼 수 없으면 미리보기가 아니다. 적용·취소는 지도를 가리지 않는
     * 위 패널 막대로 넘어간다.
     */
    _previewSplit(args, values) {
        const q = new URLSearchParams();
        q.set('zone_id', args.zone_id);
        if (args.parts != null) q.set('parts', args.parts);
        if (args.strip_width_cm != null) q.set('strip_width_cm', args.strip_width_cm);
        if (args.edge_margin_cm != null) q.set('edge_margin_cm', args.edge_margin_cm);

        return this._api('GET', '/api/geo/planting/split-preview?' + q.toString())
            .then(({ status, data }) => {
                if (status >= 400 || !data || !data.ok) {
                    this._toast((data && data.message) || this._t('Split failed'),
                                'error');
                    return;
                }
                this._split = { args: args, values: values,
                                info: data.info, strips: data.strips || [] };
                if (!this._drawSplitPreview(this._split.strips)) {
                    this._split = null;
                    this._toast(this._t('Could not draw the preview.'), 'error');
                    return;
                }
                this._close();
                this._refreshPanel();
                this._toast(this.splitSummaryText(), 'info');
            })
            .catch(() => this._toast(this._t('Split failed'), 'error'));
    }

    /**
     * 제안 폴리곤을 **점선**으로 그린다 — 실제 구획(굵은 실선 + 진한 채움)과
     * 한눈에 갈려야 한다. 클릭 핸들러를 붙이지 않고, 이 페이지의 도형 선택은
     * 전부 `layers:` 를 명시한 `queryRenderedFeatures` 라 이 레이어는 잡히지
     * 않는다 — 미리보기를 선택하거나 지울 수 있으면 그것부터 사고다.
     */
    _drawSplitPreview(strips) {
        const map = this._nativeMap();
        if (!map || typeof map.addSource !== 'function') return false;
        const color = this.colorOf(null);
        const data = {
            type: 'FeatureCollection',
            features: (strips || []).map(s => ({
                type: 'Feature',
                properties: { index: s.index },
                geometry: s.geometry
            }))
        };
        try {
            if (map.getSource(this._splitSrc)) {
                map.getSource(this._splitSrc).setData(data);
            } else {
                map.addSource(this._splitSrc, { type: 'geojson', data: data });
            }
            if (!map.getLayer(this._splitFill)) {
                map.addLayer({
                    id: this._splitFill, type: 'fill', source: this._splitSrc,
                    paint: { 'fill-color': color, 'fill-opacity': 0.15 }
                });
            }
            if (!map.getLayer(this._splitLine)) {
                map.addLayer({
                    id: this._splitLine, type: 'line', source: this._splitSrc,
                    paint: {
                        'line-color': color,
                        'line-width': 3,
                        'line-opacity': 0.95,
                        'line-dasharray': [2, 2]
                    }
                });
            }
        } catch (e) {
            console.error('[Vegetation] 분할 미리보기 그리기 실패:', e);
            return false;
        }
        return true;
    }

    /** 미리보기를 걷는다. 아무것도 저장되지 않았으므로 되돌릴 것이 없다. */
    clearSplitPreview() {
        const map = this._nativeMap();
        if (map) {
            [this._splitLine, this._splitFill].forEach(id => {
                try { if (map.getLayer && map.getLayer(id)) map.removeLayer(id); }
                catch (e) { /* 이미 없음 */ }
            });
            try {
                if (map.getSource && map.getSource(this._splitSrc)) {
                    map.removeSource(this._splitSrc);
                }
            } catch (e) { /* 이미 없음 */ }
        }
        this._split = null;
        this._refreshPanel();
    }

    /**
     * 제안을 실제 구획으로 만든다 — 서버가 **같은 파라미터로 다시 계산**한다.
     *
     * 일부만 저장된 것을 성공이라 말하지 않는다. 지도에는 몇 개만 뜨는데
     * 응답이 성공이면 나머지가 어디 갔는지 알 방법이 없다.
     */
    applySplit() {
        if (!this.hasSplitPreview() || this._splitBusy) return;
        const pending = this._split;
        this._splitBusy = true;

        this._api('POST', '/api/geo/planting/split-apply',
                  Object.assign({}, pending.args, pending.values))
            .then(({ status, data }) => {
                this._splitBusy = false;
                if (status >= 400) {
                    // 하나도 만들어지지 않았다 — 미리보기는 남겨 둔다.
                    this._toast((data && data.message) || this._t('Split failed'),
                                'error');
                    return;
                }
                const created = (data && data.created) || [];
                const errors = (data && data.errors) || [];
                // 무엇이든 저장됐으면 화면의 점선은 이미 사실과 다르다.
                this.clearSplitPreview();
                this.load(true);
                if (errors.length) {
                    this._toast(`${this._t('Some pieces could not be saved.')} (${
                        errors.length}/${errors.length + created.length})`, 'error');
                    return;
                }
                if (!created.length) {
                    this._toast((data && data.message) || this._t('Split failed'),
                                'error');
                    return;
                }
                this._toast(`${this._t('Plots created')} (${created.length})`,
                            'success');
            })
            .catch(() => {
                this._splitBusy = false;
                this._toast(this._t('Split failed'), 'error');
            });
    }

    // ── 모달 셸 ─────────────────────────────────────────────────────────
    //
    // AoT 현대화 모달 구조를 그대로 쓴다(정본: layout_default.html 의
    // `modal_config_theme`, 스타일: aot-modal-modern.css):
    //
    //   .modal.aot-option-modal > .modal-dialog.aot-modal-dialog
    //     > .modal-content > .modal-header / .modal-body / .modal-footer
    //
    // 본문은 `aot-modal-group-title` + `aot-modal-container` +
    // `aot-modal-option-row`(label/control) 로 쌓고, 입력은 `aot-modern-input`,
    // 버튼은 `btn aot-pill-btn` 을 쓴다.
    //
    // ⚠ 인라인 style 로 크기·모서리·배경을 주지 말 것. 공용 CSS 가 정본이고,
    // 인라인 오버라이드는 모바일 미디어쿼리(전체화면 전환)를 덮어써 폰에서
    // 레이아웃이 깨진다.

    /**
     * `withSave=false` 면 저장 버튼을 두지 않는다 (고르기만 하는 창).
     * `saveLabel` 로 그 버튼의 문구를 바꾼다 — 분할 창에서는 누르는 순간
     * 저장되는 것이 아니라 미리보기를 계산할 뿐이라 "저장" 이면 거짓말이다.
     */
    _shell(title, withSave, saveLabel) {
        const save = (withSave === false) ? '' : `
                            <button type="button" class="btn aot-pill-btn aot-pill-btn-primary"
                                    data-veg-save>${saveLabel || this._t('Save')}</button>`;
        $('#' + this._modalId).remove();
        document.body.insertAdjacentHTML('beforeend', `
            <div class="modal fade aot-option-modal" id="${this._modalId}"
                 tabindex="-1" role="dialog" aria-hidden="true">
                <div class="modal-dialog aot-modal-dialog" role="document">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">${title}</h5>
                            <button type="button" class="close" data-dismiss="modal"
                                    aria-label="Close"><span aria-hidden="true">&times;</span></button>
                        </div>
                        <div class="modal-body" id="geo-vegetation-body"></div>
                        <div class="modal-footer">
                            <button type="button" class="btn aot-pill-btn"
                                    data-dismiss="modal">${this._t('Cancel')}</button>${save}
                        </div>
                    </div>
                </div>
            </div>
        `);
        $('#' + this._modalId).modal('show');
        return document.getElementById('geo-vegetation-body');
    }

    _close() { $('#' + this._modalId).modal('hide'); }

    _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
}

window.AoTGeoVegetation = AoTGeoVegetation;
