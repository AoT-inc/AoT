/**
 * aot-geo-device-split.js
 * 장치 모드의 **구역 나누기** — site/zone 을 잘라 장치 담당 구역을 만든다.
 *
 * 설계 정본: docs/design/geo-device-area-split.md
 *
 * 식생 분할(`aot-geo-vegetation.js`)과 **같은 흐름**이다: 나눌 도형을 고르고,
 * 조건을 바꾸면 지도에 점선 제안이 따라오고, 만들기를 누르면 서버가 같은
 * 파라미터로 다시 계산해 저장한다. 다른 것은 결과물뿐이다 —
 * 식생은 작기(GeoPlanting), 여기서는 장치 담당 구역(GeoShape type='device')
 * 이고, 만들어진 구역 안에 장치 마커가 하나면 그 장치에 자동 배정된다.
 *
 * 미리보기는 식생과 **같은 엔드포인트**를 쓴다(`/api/geo/planting/split-preview`).
 * 그쪽은 도형을 잘라 조각만 돌려줄 뿐 작기와 무관하므로 하나 더 만들 이유가 없다.
 */
class AoTGeoDeviceSplit {
    constructor(parent) {
        this.parent = parent;
        // 미리보기 전용 GL 레이어 — 식생 것과 id 가 겹치면 서로를 지운다.
        this._src = '_aot_devsplit_src';
        this._fill = '_aot_devsplit_fill';
        this._line = '_aot_devsplit_line';
        this._label = '_aot_devsplit_label';
        this._axisSrc = '_aot_devsplit_axis_src';
        this._axisLine = '_aot_devsplit_axis_line';
        this._state = null;      // { args, info, strips }
        this._busy = false;
    }

    _t(key) { return (window._ ? window._(key) : key); }

    _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    _csrf() {
        const el = document.querySelector('meta[name="csrf-token"]');
        return el ? el.getAttribute('content') : '';
    }

    _toast(msg, level) {
        if (window.AoTToast && window.AoTToast.show) window.AoTToast.show(msg, level);
        else if (window.toastr && window.toastr[level === 'error' ? 'error' : 'success']) {
            window.toastr[level === 'error' ? 'error' : 'success'](msg);
        }
    }

    _nativeMap() {
        const m = this.parent && this.parent.map;
        return m ? (m._originalMap || m) : null;
    }

    /** 나눌 수 있는 도형 — 식생과 같은 기준(저장된 site/zone). */
    _areaShapes() {
        const out = [];
        const scan = (kind) => {
            const group = this.parent.layerStorage && this.parent.layerStorage[kind];
            if (!group || typeof group.eachLayer !== 'function') return;
            group.eachLayer(l => {
                const props = (l.feature && l.feature.properties) || {};
                const uuid = props.shape_uuid || props.node_id;
                if (!uuid) return;          // 아직 저장 안 된 도형은 나눌 수 없다
                out.push({ uuid, kind, name: props.name || props.label_name });
            });
        };
        scan('zone');
        scan('site');
        return out;
    }

    _findAreaFeature(uuid) {
        let found = null;
        ['zone', 'site'].forEach(kind => {
            const group = this.parent.layerStorage && this.parent.layerStorage[kind];
            if (!group || typeof group.eachLayer !== 'function' || found) return;
            group.eachLayer(l => {
                if (found) return;
                const props = (l.feature && l.feature.properties) || {};
                if ((props.shape_uuid || props.node_id) === uuid) found = l.feature;
            });
        });
        return found;
    }

    // ── 폼 ─────────────────────────────────────────────────────────────────

    /** 장치 모드 드로어에 붙는 분할 폼. 패널이 이것을 tier 끝에 이어 붙인다. */
    panelHtml() {
        const areas = this._areaShapes();
        if (!areas.length) {
            return `<div class="aot-modal-group-title">${this._t('Split into device areas')}</div>
                    <div class="aot-modal-container">
                        <div class="aot-modal-body-text">${
                            this._t('No zones or sites on this map. Draw one first.')}</div>
                    </div>`;
        }
        const row = (label, control, labelAttr) => `
            <div class="aot-modal-option-row">
                <div class="aot-modal-option-label"${labelAttr || ''}>${label}</div>
                <div class="aot-modal-option-control">${control}</div>
            </div>`;
        const group = (kind, label) => {
            const items = areas.filter(a => a.kind === kind);
            if (!items.length) return '';
            return `<optgroup label="${this._esc(label)}">` + items.map(a =>
                `<option value="${this._esc(a.uuid)}">${
                    this._esc(a.name || this._t('Unnamed'))}</option>`).join('') +
                `</optgroup>`;
        };

        return `
            <div class="aot-modal-group-title">${this._t('Split into device areas')}</div>
            <div class="aot-modal-container">
                ${row(this._t('Area to split'),
                      `<select class="aot-modern-input form-control"
                               data-devsplit="zone_id">${
                          group('zone', this._t('Zone'))}${
                          group('site', this._t('Site'))}</select>`)}
                ${row(this._t('Split by'),
                      `<select class="aot-modern-input form-control" data-devsplit="mode">
                           <option value="parts" selected>${this._t('Equal parts')}</option>
                           <option value="width">${this._t('Strip width')}</option>
                       </select>`)}
                ${row(this._t('Number of pieces'),
                      `<input type="number" min="1" step="1"
                              class="aot-modern-input form-control"
                              data-devsplit="amount" value="">`,
                      ' data-devsplit-amount')}
                ${row(this._t('Direction'),
                      `<select class="aot-modern-input form-control" data-devsplit="orientation">
                           <option value="long" selected>${this._t('Long side (default)')}</option>
                           <option value="short">${this._t('Short side (squarer pieces)')}</option>
                           <option value="custom">${this._t('Custom angle')}</option>
                       </select>`)}
                ${row(`${this._t('Angle')}: <span data-devsplit-angle-value>0</span>°`,
                      `<input type="range" min="0" max="179" step="1"
                              class="form-control-range" data-devsplit="angle_deg" value="0">`)}
                ${row(this._t('Edge margin (cm)'),
                      `<input type="number" min="0" step="10"
                              class="aot-modern-input form-control"
                              data-devsplit="edge_margin_cm" value="0">`)}
                ${row(this._t('Area name'),
                      `<input type="text" class="aot-modern-input form-control"
                              data-devsplit="name" value="" autocomplete="off">`)}
                ${row(this._t('Link only this device kind'),
                      `<select class="aot-modern-input form-control" data-devsplit="device_kind">
                           <option value="">${this._t('Any kind')}</option>
                           <option value="input">${this._t('Input')}</option>
                           <option value="output">${this._t('Output')}</option>
                           <option value="function">${this._t('Function')}</option>
                           <option value="device_unit">${this._t('Device Unit')}</option>
                       </select>`)}
                <div class="aot-modal-body-text">${
                    this._t('Each new area is linked to the device whose marker falls inside it. Areas with no device — or more than one — are left unlinked and reported.')}</div>
                <div class="aot-modal-body-text">${
                    this._t('Nothing is saved until you create the areas.')}</div>
                <div class="aot-modal-body-text" data-devsplit-summary></div>
                <button type="button" class="btn aot-pill-btn aot-pill-btn-primary"
                        data-devsplit-create>${this._t('Create device areas')}</button>
            </div>`;
    }

    // ── 배선 ───────────────────────────────────────────────────────────────

    bindPanel(root) {
        const body = root;
        if (!body.querySelector('[data-devsplit="zone_id"]')) return;

        const get = (k) => {
            const el = body.querySelector(`[data-devsplit="${k}"]`);
            return el ? String(el.value || '').trim() : '';
        };
        const modeEl = body.querySelector('[data-devsplit="mode"]');
        const labelEl = body.querySelector('[data-devsplit-amount]');
        const amountEl = body.querySelector('[data-devsplit="amount"]');
        const orientationEl = body.querySelector('[data-devsplit="orientation"]');
        const angleEl = body.querySelector('[data-devsplit="angle_deg"]');
        const angleRow = angleEl && angleEl.closest('.aot-modal-option-row');
        const angleValEl = body.querySelector('[data-devsplit-angle-value]');

        // `.aot-modal-option-row` 는 공용 CSS 가 flex 로 못 박아 둔다 —
        // !important 로 덮어야 실제로 숨겨진다(식생 폼과 같은 함정).
        const showRow = (el, show) => {
            if (!el) return;
            if (show) el.style.removeProperty('display');
            else el.style.setProperty('display', 'none', 'important');
        };
        const syncAngle = () => showRow(angleRow,
            orientationEl && orientationEl.value === 'custom');
        const syncMode = () => {
            const byWidth = modeEl && modeEl.value === 'width';
            if (labelEl) {
                labelEl.textContent = byWidth ? this._t('Piece width (cm)')
                                              : this._t('Number of pieces');
            }
            if (amountEl) amountEl.step = byWidth ? '10' : '1';
            syncAngle();
        };

        let timer = null;
        const schedule = () => {
            const parsed = this._argsFrom(body);
            // 기준선은 서버 없이 즉시 — 슬라이더를 끄는 동안 매 프레임 요청이
            // 나가지 않게 조각만 디바운스한다(식생과 같은 규칙).
            if (parsed.args && parsed.args.angle_deg != null) {
                const f = this._findAreaFeature(parsed.args.zone_id);
                if (f) this._drawAxis(f, parsed.args.angle_deg); else this._clearAxis();
            } else {
                this._clearAxis();
            }
            clearTimeout(timer);
            if (parsed.error) { this.clearPreview(); this._renderSummary(body); return; }
            timer = setTimeout(() => this._runPreview(parsed.args, body), 250);
        };

        if (modeEl) modeEl.addEventListener('change', () => {
            if (amountEl) amountEl.value = '';   // "3" 이 3등분→3cm 로 조용히 바뀌지 않게
            syncMode(); schedule();
        });
        if (orientationEl) orientationEl.addEventListener('change', () => { syncAngle(); schedule(); });
        if (angleEl) angleEl.addEventListener('input', () => {
            if (angleValEl) angleValEl.textContent = angleEl.value;
            schedule();
        });
        ['zone_id', 'amount', 'edge_margin_cm'].forEach(k => {
            const el = body.querySelector(`[data-devsplit="${k}"]`);
            if (el) el.addEventListener(k === 'zone_id' ? 'change' : 'input', schedule);
        });
        syncMode();
        schedule();

        const btn = body.querySelector('[data-devsplit-create]');
        if (btn) btn.onclick = () => {
            const parsed = this._argsFrom(body);
            if (parsed.error) { this._toast(parsed.error, 'warning'); return; }
            this.apply(parsed.args, {
                name: get('name'), device_kind: get('device_kind')
            });
        };
    }

    /** 폼 → 서버 파라미터. 식생과 같은 규약(등분/폭은 한 칸). */
    _argsFrom(body) {
        const get = (k) => {
            const el = body.querySelector(`[data-devsplit="${k}"]`);
            return el ? String(el.value || '').trim() : '';
        };
        const zoneId = get('zone_id');
        if (!zoneId) return { error: this._t('Pick a zone or site to split.') };
        const amount = parseFloat(get('amount'));
        if (!isFinite(amount) || amount <= 0) {
            return { error: this._t('Enter how many pieces, or how wide each piece is.') };
        }
        const args = { zone_id: zoneId };
        if (get('mode') === 'width') args.strip_width_cm = amount;
        else args.parts = Math.round(amount);

        const orientation = get('orientation');
        if (orientation === 'custom') {
            const a = parseFloat(get('angle_deg'));
            args.angle_deg = isFinite(a) ? a : 0;
        } else if (orientation === 'short') {
            args.orientation = 'short';
        }
        // 입력칸은 cm 다 — 서버 edge_margin_m 는 m 이므로 여기서만 ÷100 한다
        // (식생 분할과 같은 규칙, aot-geo-vegetation.js 참조).
        const marginCm = parseFloat(get('edge_margin_cm'));
        if (isFinite(marginCm) && marginCm > 0) args.edge_margin_m = marginCm / 100;

        // 장치 구역은 두둑이 아니다 — 서버 기본 하한(2m)을 그대로 쓰면 좁은
        // 구역이 조용히 사라진다. **미리보기와 적용이 같은 값을 보내야**
        // 화면에서 본 조각 수와 실제로 만들어지는 수가 갈리지 않는다.
        args.min_length_cm = 50;
        return { args };
    }

    _query(args) {
        const q = new URLSearchParams();
        q.set('zone_id', args.zone_id);
        if (args.parts != null) q.set('parts', args.parts);
        if (args.strip_width_cm != null) q.set('strip_width_cm', args.strip_width_cm);
        if (args.edge_margin_m != null) q.set('edge_margin_m', args.edge_margin_m);
        if (args.orientation) q.set('orientation', args.orientation);
        if (args.angle_deg != null) q.set('angle_deg', args.angle_deg);
        if (args.min_length_cm != null) q.set('min_length_cm', args.min_length_cm);
        return q;
    }

    _runPreview(args, root) {
        return fetch('/api/geo/planting/split-preview?' + this._query(args).toString())
            .then(r => r.json().then(data => ({ status: r.status, data })))
            .then(({ status, data }) => {
                if (status >= 400 || !data || !data.ok) {
                    this.clearPreview();
                    const el = root && root.querySelector('[data-devsplit-summary]');
                    if (el) {
                        el.textContent = (data && data.message) || '';
                        el.classList.add('text-warning');
                    }
                    return;
                }
                this._state = { args, info: data.info, strips: data.strips || [] };
                this._drawPreview(this._state.strips);
                this._renderSummary(root);
            })
            .catch(() => { /* 편집 중 — 다음 입력에서 다시 시도된다 */ });
    }

    _renderSummary(root) {
        const el = root && root.querySelector('[data-devsplit-summary]');
        if (!el) return;
        if (!this._state || !this._state.info) { el.textContent = ''; return; }
        const i = this._state.info;
        const parts = [`${this._t('Pieces')} ${i.count}`,
                       `${this._t('Piece width')} ${i.strip_width_m} m`,
                       `${this._t('Direction')} ${i.orientation_deg}°`];
        if (i.dropped) parts.push(`${this._t('Dropped as too short')} ${i.dropped}`);
        el.textContent = parts.join(' · ');
        el.classList.remove('text-warning');
    }

    // ── 지도 미리보기 ──────────────────────────────────────────────────────

    _drawPreview(strips) {
        const map = this._nativeMap();
        if (!map || typeof map.addSource !== 'function') return;
        const color = (window.AoTGeoTheme && window.AoTGeoTheme.deviceColor)
            ? window.AoTGeoTheme.deviceColor('output') : '#995aff';
        const data = {
            type: 'FeatureCollection',
            features: (strips || []).map(s => ({
                type: 'Feature', properties: { index: s.index }, geometry: s.geometry
            }))
        };
        try {
            if (map.getSource(this._src)) map.getSource(this._src).setData(data);
            else map.addSource(this._src, { type: 'geojson', data });

            if (!map.getLayer(this._fill)) {
                map.addLayer({ id: this._fill, type: 'fill', source: this._src,
                    paint: { 'fill-color': color, 'fill-opacity': 0.15 } });
            }
            if (!map.getLayer(this._line)) {
                map.addLayer({ id: this._line, type: 'line', source: this._src,
                    paint: { 'line-color': color, 'line-width': 3,
                             'line-opacity': 0.95, 'line-dasharray': [2, 2] } });
            }
            // 조각 번호 — 만들어질 구역 순서를 눈으로 확인할 수 있게.
            if (!map.getLayer(this._label)) {
                map.addLayer({ id: this._label, type: 'symbol', source: this._src,
                    layout: { 'text-field': ['to-string', ['get', 'index']],
                              'text-size': 14, 'text-allow-overlap': true,
                              'text-ignore-placement': true },
                    paint: { 'text-color': color, 'text-halo-color': '#ffffff',
                             'text-halo-width': 1.5 } });
            }
        } catch (e) {
            console.error('[DeviceSplit] 미리보기 그리기 실패:', e);
        }
    }

    /** 구역 중심을 지나는 기준선 — 서버 없이 turf 로 즉시 계산한다. */
    _drawAxis(feature, angleDeg) {
        const map = this._nativeMap();
        const turf = window.turf;
        if (!map || typeof map.addSource !== 'function' || !turf || !feature) return;
        try {
            const centroid = turf.centroid(feature);
            const bbox = turf.bbox(feature);
            const diag = turf.distance(turf.point([bbox[0], bbox[1]]),
                                       turf.point([bbox[2], bbox[3]]), { units: 'meters' });
            const reach = Math.max(diag * 0.6, 5);
            const bearing = (90 - angleDeg + 360) % 360;
            const p1 = turf.destination(centroid, reach, bearing, { units: 'meters' });
            const p2 = turf.destination(centroid, reach, bearing + 180, { units: 'meters' });
            const line = { type: 'Feature', properties: {}, geometry: { type: 'LineString',
                coordinates: [p1.geometry.coordinates, p2.geometry.coordinates] } };
            if (map.getSource(this._axisSrc)) map.getSource(this._axisSrc).setData(line);
            else map.addSource(this._axisSrc, { type: 'geojson', data: line });
            if (!map.getLayer(this._axisLine)) {
                map.addLayer({ id: this._axisLine, type: 'line', source: this._axisSrc,
                    paint: { 'line-color': '#13261B', 'line-width': 2,
                             'line-opacity': 0.85, 'line-dasharray': [3, 2] } });
            }
        } catch (e) { /* 기준선은 보조 표시라 실패해도 흐름을 막지 않는다 */ }
    }

    _clearAxis() {
        const map = this._nativeMap();
        if (!map) return;
        try { if (map.getLayer(this._axisLine)) map.removeLayer(this._axisLine); } catch (e) {}
        try { if (map.getSource(this._axisSrc)) map.removeSource(this._axisSrc); } catch (e) {}
    }

    /** 미리보기를 걷는다 — 저장된 것이 없으므로 되돌릴 것도 없다. */
    clearPreview() {
        const map = this._nativeMap();
        if (map) {
            [this._label, this._line, this._fill].forEach(id => {
                try { if (map.getLayer(id)) map.removeLayer(id); } catch (e) {}
            });
            try { if (map.getSource(this._src)) map.removeSource(this._src); } catch (e) {}
        }
        this._clearAxis();
        this._state = null;
    }

    // ── 적용 ───────────────────────────────────────────────────────────────

    /**
     * 제안을 실제 장치 구역으로 만든다 — 서버가 **같은 파라미터로 다시 계산**한다.
     * 일부만 배정된 것을 성공이라고만 말하지 않는다.
     */
    apply(args, values) {
        if (!args || this._busy) return;
        this._busy = true;
        fetch('/api/geo/device/split-apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json',
                       'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': this._csrf() },
            body: JSON.stringify(Object.assign({}, args, values))
        }).then(r => r.json().then(data => ({ status: r.status, data })))
          .then(({ status, data }) => {
              this._busy = false;
              if (status >= 400 || !data.ok) {
                  this._toast((data && data.message) || this._t('Split failed'), 'error');
                  return;
              }
              const created = data.created || [];
              this.clearPreview();
              // 새 구역은 GeoShape 라 도면을 다시 읽어야 지도에 뜬다.
              if (this.parent.loadMap) {
                  this.parent.loadMap(this.parent.currentMapUuid, this.parent.currentMapName);
              }
              const unlinked = (data.unassigned || []).length;
              if (unlinked) {
                  // 몇 개가 장치 없이 남았는지 숨기지 않는다 — 모르면 그 구역은
                  // 아무 일도 하지 않으면서 있는 것처럼 보인다.
                  this._toast(`${this._t('Areas created')} ${created.length} · ${
                      this._t('linked')} ${data.assigned} · ${
                      this._t('not linked')} ${unlinked}`, 'warning');
              } else {
                  this._toast(`${this._t('Areas created')} ${created.length} · ${
                      this._t('linked')} ${data.assigned}`, 'success');
              }
          })
          .catch(() => { this._busy = false; this._toast(this._t('Split failed'), 'error'); });
    }
}

window.AoTGeoDeviceSplit = AoTGeoDeviceSplit;
