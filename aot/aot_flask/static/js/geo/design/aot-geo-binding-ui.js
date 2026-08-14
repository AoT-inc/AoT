/**
 * aot-geo-binding-ui.js
 *
 * 공간 슬롯 ↔ 장치 배정 UI (Phase B-2).
 * 계약: docs/design/geo-device-placement-ui-contract.md
 *
 * 여기서 다루는 것은 "이 자리를 지금 어느 장치가 맡는가"이지 좌표가 아니다.
 * 마커 좌표는 계속 /api/geo/device/location(place_device)이 담당하며, 구역
 * 배정을 그 엔드포인트에 얹지 않는다 — 마커는 좌표, 구역은 소속이라 뜻이
 * 다르고, 한 곳에 섞으면 "좌표 없는 배정"과 "배정 없는 좌표"를 구분할 수
 * 없게 된다.
 *
 * 쓰기는 전부 /api/geo/binding 을 지나간다(게이트웨이 device_binding.py).
 * 도형에 device_id 를 각인하는 레거시 경로(save_overlays 의 device_id)는
 * 쓰지 않는다.
 */

class AoTGeoBinding {
    constructor(parent) {
        this.parent = parent;
        this._devices = null;        // /api/geo/devices 캐시
        this._modalId = 'geoBindingModal';
    }

    // ── 유틸 ────────────────────────────────────────────────────────────
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

    _loadDevices() {
        if (this._devices) return Promise.resolve(this._devices);
        return fetch('/api/geo/devices?include_all=true')
            .then(r => r.json())
            .then(res => {
                this._devices = (res && res.ok && res.devices) ? res.devices : [];
                return this._devices;
            });
    }

    /** 장치 종류 라벨 — 패널 탭과 같은 어휘를 쓴다(새 msgid 를 만들지 않는다). */
    _typeLabel(type) {
        const t = String(type || '').toLowerCase();
        if (t === 'input') return this._t('Input');
        if (t === 'output') return this._t('Output');
        if (t === 'device') return this._t('Device');
        if (['function', 'pid', 'trigger', 'conditional', 'custom'].includes(t)) {
            return this._t('Function');
        }
        return '';
    }

    /** 장치 uuid → 표시 이름. 목록에 없으면 uuid 앞자리로 대신한다. */
    _deviceName(deviceId) {
        if (!deviceId) return '';
        const list = this._devices || [];
        const hit = list.find(d => String(d.unique_id).split('::')[0] === deviceId);
        return (hit && (hit.name || hit.device_name)) || deviceId.slice(0, 8);
    }

    // ── 모달 셸 ─────────────────────────────────────────────────────────
    // 이 페이지의 기존 모달(_openDeviceModal)과 같은 부트스트랩 구조를 쓴다.
    // 새 커스텀 CSS 를 만들지 않는다 — 공용 클래스 재사용이 규칙이다.
    //
    // 목록에 자체 스크롤 컨테이너(max-height + overflow-y)를 두지 않는다.
    // 그러면 그 안에 브라우저 기본 스크롤바가 그려진다. 스크롤은 modal-body 가
    // 맡고, aot-modal-modern.css 가 거기 스크롤바를 숨겨 둔다(동작은 유지).
    _shell(title) {
        $('#' + this._modalId).remove();
        document.body.insertAdjacentHTML('beforeend', `
            <div class="modal fade" id="${this._modalId}" tabindex="-1">
                <div class="modal-dialog" style="max-width: 600px; width: calc(100% - 30px); margin: 30px auto;">
                    <div class="modal-content" style="border-radius: 20px; overflow: hidden; height: auto;">
                        <div class="modal-header border-0 bg-light">
                            <h5 class="modal-title font-weight-bold" id="geo-binding-title">${title}</h5>
                            <button type="button" class="close" data-dismiss="modal">&times;</button>
                        </div>
                        <div class="modal-body p-4" id="geo-binding-body" style="max-height: 60vh;"></div>
                    </div>
                </div>
            </div>
        `);
        $('#' + this._modalId).modal('show');
        return document.getElementById('geo-binding-body');
    }

    _close() { $('#' + this._modalId).modal('hide'); }

    _setBody(html) {
        const body = document.getElementById('geo-binding-body');
        if (body) body.innerHTML = html;
        return body;
    }

    _setTitle(text) {
        const el = document.getElementById('geo-binding-title');
        if (el) el.textContent = text;
    }

    // ── B/D. 도형(구역) 슬롯 배정·교체·해제 ─────────────────────────────
    /**
     * @param {string} shapeUid  GeoShape.unique_id (feature.properties.node_id)
     * @param {object} opts      {name}
     */
    openForShape(shapeUid, opts) {
        if (!shapeUid) {
            this._toast(this._t('Select an area on the map first'), 'error');
            return;
        }
        this.slot = { spatial_kind: 'shape', spatial_id: shapeUid,
                      label: (opts && opts.name) || '' };
        this._shell(this._t('Device assignment'));
        this._setBody(`<div class="text-muted">${this._t('Loading...')}</div>`);
        this._refreshSlot();
    }

    /** fitting/actuator 슬롯(시설) 배정 — 미배정 목록에서 진입한다. */
    openForSlot(slot) {
        this.slot = Object.assign({}, slot);
        this._shell(this._t('Device assignment'));
        this._setBody(`<div class="text-muted">${this._t('Loading...')}</div>`);
        this._refreshSlot();
    }

    _refreshSlot() {
        const s = this.slot;
        const q = `spatial_kind=${encodeURIComponent(s.spatial_kind)}` +
                  `&spatial_id=${encodeURIComponent(s.spatial_id)}` +
                  (s.role ? `&role=${encodeURIComponent(s.role)}` : '');
        Promise.all([
            this._api('GET', '/api/geo/binding?' + q),
            this._loadDevices()
        ]).then(([res]) => {
            const payload = (res && res.data) || {};
            if (!payload.ok) {
                this._setBody(`<div class="text-danger">${payload.message || this._t('Failed to load')}</div>`);
                return;
            }
            this._renderSlot(payload.bindings || [], payload.history || []);
        });
    }

    _renderSlot(bindings, history) {
        const s = this.slot;
        const title = s.label
            ? `${this._t('Device assignment')} — ${s.label}`
            : this._t('Device assignment');
        this._setTitle(title);

        let html = '';

        if (bindings.length) {
            html += `<div class="mb-3">
                <div class="small text-muted mb-1">${this._t('Currently assigned')}</div>`;
            bindings.forEach(b => {
                const ch = (b.channel_id && b.channel_id !== '0')
                    ? ` · ${this._t('Channel')} ${b.channel_id}` : '';
                html += `
                    <div class="d-flex justify-content-between align-items-center border rounded-pill px-4 py-2 mb-1">
                        <span class="font-weight-600">${this._deviceName(b.device_id)}${ch}</span>
                        <span>
                            <button class="btn btn-aot-pill btn-aot-outline" data-bind-replace="${b.unique_id}" data-bind-channel="${b.channel_id}" data-bind-device="${b.device_id}">${this._t('Replace')}</button>
                            <button class="btn btn-aot-pill btn-aot-outline" data-bind-release="${b.unique_id}">${this._t('Unassign')}</button>
                        </span>
                    </div>`;
            });
            html += `</div>`;
        } else {
            html += `<div class="alert alert-light border mb-3 py-2 px-3">
                        ${this._t('No device is assigned to this slot.')}
                     </div>`;
        }

        // 교체 이력 — 이 슬롯을 언제 어떤 장치가 맡았나. 시계열이 장치 교체를
        // 관통해 이어지는 근거이고, 사람에게는 "왜 예전 데이터가 다른가"의 답이다.
        if (history && history.length) {
            html += `<div class="mb-3">
                <div class="small text-muted mb-1">${this._t('Previous devices')}</div>
                <ul class="list-unstyled small text-muted mb-0">`;
            history.slice(-5).forEach(b => {
                const from = (b.valid_from || '').slice(0, 10);
                const to = (b.valid_to || '').slice(0, 10);
                html += `<li>${this._deviceName(b.device_id)} · ${from} ~ ${to}</li>`;
            });
            html += `</ul></div>`;
        }

        // 아래 목록은 항상 **새 배정**(bind)이다. 이미 찬 슬롯을 고르면 서버가
        // 409 로 거부하고 교체 플로우로 안내한다 — 조용히 덮어쓰면 교체 이력이
        // 사라지기 때문이다. 채널이 다른 여러 배정은 정상이므로(다채널 릴레이)
        // 채널을 여기서 지정할 수 있게 둔다.
        const usedChannels = bindings.map(b => b.channel_id);
        html += `
            <div class="small text-muted mb-1">${bindings.length ? this._t('Assign another channel') : this._t('Select a device')}</div>
            <div class="d-flex mb-2">
                <input type="text" class="form-control mr-2" id="geo-binding-search"
                       placeholder="${this._t('Search Device...')}" style="height: 38px; border-radius: 19px;">
                <input type="text" class="form-control" id="geo-binding-channel"
                       value="${this._firstFreeChannel(usedChannels)}"
                       title="${this._t('Channel')}"
                       style="height: 38px; width: 84px; border-radius: 19px; text-align: center;">
            </div>
            <div id="geo-binding-devices" class="list-group"></div>`;

        const body = this._setBody(html);
        if (!body) return;

        body.querySelectorAll('[data-bind-release]').forEach(el => {
            el.onclick = () => this._release(el.dataset.bindRelease);
        });
        body.querySelectorAll('[data-bind-replace]').forEach(el => {
            el.onclick = () => this._replaceNotice(el.dataset.bindChannel,
                                                   el.dataset.bindDevice);
        });

        const search = body.querySelector('#geo-binding-search');
        if (search) search.oninput = () => this._renderDeviceList(search.value, false);
        this._renderDeviceList('', false);
    }

    /** 이미 찬 채널을 기본값으로 제시하지 않는다 — 누르자마자 409 가 된다. */
    _firstFreeChannel(used) {
        const taken = new Set((used || []).map(String));
        for (let i = 0; i < 64; i++) {
            if (!taken.has(String(i))) return String(i);
        }
        return '0';
    }

    _renderDeviceList(filter, isReplace, channelId) {
        const box = document.getElementById('geo-binding-devices');
        if (!box) return;
        const needle = (filter || '').toLowerCase();

        // 장치 단위로 접는다 — 채널별 항목은 같은 장치를 여러 번 보여준다.
        const seen = new Map();
        (this._devices || []).forEach(d => {
            const id = String(d.unique_id).split('::')[0];
            if (!seen.has(id)) {
                seen.set(id, { id, name: d.name || d.device_name || id, type: d.type });
            }
        });

        const rows = Array.from(seen.values())
            .filter(d => !needle || d.name.toLowerCase().includes(needle));

        if (!rows.length) {
            box.innerHTML = `<div class="text-muted text-center py-3">${this._t('No devices found')}</div>`;
            return;
        }

        box.innerHTML = '';
        rows.forEach(d => {
            const item = document.createElement('div');
            item.className = 'list-group-item d-flex justify-content-between align-items-center mb-1 border rounded-pill px-4';
            item.innerHTML = `
                <span class="font-weight-600">${d.name}</span>
                <span class="small text-muted">${this._typeLabel(d.type)}</span>`;
            item.style.cursor = 'pointer';
            item.onclick = () => this._assign(d.id, isReplace, channelId, d.type);
            box.appendChild(item);
        });
    }

    /**
     * 교체 화면 — 고장 교체의 정답은 대개 삭제-재생성이 아니라 접속정보 갱신이다.
     * DevEUI·주소만 바꾸면 장치 uuid 가 그대로라 도형·이력·함수 연결·측정 채널이
     * 전부 유지되고 시계열도 끊기지 않는다.
     *
     * 예전에는 그 안내 아래에 /input · /output 새 탭 링크만 있었다. 그건 길을
     * 가리키기만 하고 걷게 하지는 않는다 — 사람은 설정 페이지에서 그 장치를 다시
     * 찾고, 수십 개 필드 사이에서 접속정보를 골라내고, 활성 상태면 껐다 켜기까지
     * 해야 한다. 그 왕복이 "새로 만들고 옛것 삭제"보다 번거로우면 안내문은 아무
     * 효과가 없다. 그래서 여기서 바로 고치게 한다.
     */
    _replaceNotice(channelId, deviceId) {
        this._setTitle(this._t('Replace device'));
        this._setBody(`<div class="text-muted">${this._t('Loading...')}</div>`);
        if (!deviceId) {
            this._renderReplace(channelId, deviceId, null);
            return;
        }
        // 폼 자체는 공용 모듈이 소유한다(common/aot-device-connection.js) —
        // 같은 폼이 시설 편집기에도 뜨므로, 두 벌이면 두 번 다르게 틀린다.
        window.AoTDeviceConnection.fetchSchema(deviceId)
            .then(schema => this._renderReplace(channelId, deviceId, schema));
    }

    _renderReplace(channelId, deviceId, schema) {
        const fields = (schema && schema.fields) || [];

        // 1안 — 같은 기계로 교체(접속정보만 갱신).
        let first = `
            <div class="font-weight-bold mb-1">${this._t('Is this a like-for-like hardware swap?')}</div>
            <div class="small text-muted mb-3">
                ${this._t('If you are replacing broken hardware with the same model, update the connection settings (DevEUI, address) on the existing device instead. The shape, the history and every function link stay intact.')}
            </div>`;

        if (fields.length) {
            first += window.AoTDeviceConnection.formHtml(schema);
            first += `
                <button class="btn btn-aot-pill btn-aot-action mt-2" id="geo-conn-save">
                    ${this._t('Update connection settings')}
                </button>`;
        } else {
            // 접속정보가 없는 장치(가상 출력·계산 함수 등)에서는 1안이 성립하지
            // 않는다. 빈 폼을 보여주는 대신 그렇다고 말하고 설정 페이지를 준다.
            first += `
                <div class="small text-muted">${this._t('This device has no connection settings to change.')}</div>
                <div class="mt-2">
                    <a class="btn btn-aot-pill btn-aot-outline" href="/input" target="_blank">${this._t('Open Input settings')}</a>
                    <a class="btn btn-aot-pill btn-aot-outline" href="/output" target="_blank">${this._t('Open Output settings')}</a>
                </div>`;
        }

        this._setBody(`
            <div class="alert alert-light border mb-3">${first}</div>
            <div class="small text-muted mb-1">${this._t('Or move this slot to a different device')}</div>
            <input type="text" class="form-control mb-2" id="geo-binding-search"
                   placeholder="${this._t('Search Device...')}" style="height: 38px; border-radius: 19px;">
            <div id="geo-binding-devices" class="list-group"></div>
            <button class="btn btn-aot-pill btn-aot-outline mt-3" id="geo-binding-back">${this._t('Back')}</button>
        `);

        const save = document.getElementById('geo-conn-save');
        if (save) save.onclick = () => this._saveConnection(deviceId, save);

        const search = document.getElementById('geo-binding-search');
        if (search) search.oninput = () => this._renderDeviceList(search.value, true, channelId);
        this._renderDeviceList('', true, channelId);
        const back = document.getElementById('geo-binding-back');
        if (back) back.onclick = () => this._refreshSlot();
    }

    /**
     * 접속정보만 저장한다. 바인딩은 건드리지 않는다 — 장치가 그대로이므로
     * 슬롯의 연결도 그대로이고, 이력에 새 구간을 만들면 오히려 거짓말이 된다.
     */
    _saveConnection(deviceId, button) {
        const body = document.getElementById('geo-binding-body');
        if (!body) return;

        button.disabled = true;
        const label = button.textContent;
        button.textContent = this._t('Saving...');

        window.AoTDeviceConnection
            .save(deviceId, window.AoTDeviceConnection.collect(body))
            .then(result => {
                button.disabled = false;
                button.textContent = label;
                result.messages.forEach(m => this._toast(m.text, m.level));
                if (result.ok && result.changed) {
                    this._afterChange();
                    this._refreshSlot();
                }
            });
    }

    _assign(deviceId, isReplace, channelId, deviceType) {
        const s = this.slot;
        const chEl = document.getElementById('geo-binding-channel');
        const ch = channelId || (chEl && chEl.value.trim()) || '0';
        const body = {
            spatial_kind: s.spatial_kind,
            spatial_id: s.spatial_id,
            device_id: deviceId,
            channel_id: ch,
            // 아직 저장 전이라 spatial_id 가 클라이언트 node_id 일 수 있다 —
            // 서버가 이 지도 안에서 찾아 실제 도형으로 해석한다.
            map_uuid: this.parent ? this.parent.currentMapUuid : null
        };
        if (s.role) body.role = s.role;

        const method = isReplace ? 'PUT' : 'POST';
        this._api(method, '/api/geo/binding', body).then(({ status, data }) => {
            if (data && data.ok) {
                this._toast(this._t('Device assigned'), 'success');
                // 배정된 장치의 테마색을 **즉시** 도형에 입힌다. 서버는 도형을
                // 읽을 때 device_type 을 주입해 주지만, 그건 다음 로드 때 일이라
                // 그때까지 도형이 옛 색으로 남는다(= 새로고침해야 색이 바뀜).
                this._stampBinding(s.spatial_id, deviceId, ch, deviceType);
                this._afterChange();
                this._refreshSlot();
                return;
            }
            if (status === 409) {
                // 슬롯이 이미 점유돼 있다 — 거부가 아니라 교체 플로우로 안내한다.
                this._toast(this._t('This slot already has a device. Use Replace to swap it.'), 'error');
                this._refreshSlot();
                return;
            }
            this._toast((data && data.message) || this._t('Failed to save'), 'error');
        });
    }

    _release(bindingUid) {
        this._api('DELETE', '/api/geo/binding/' + encodeURIComponent(bindingUid),
                  { reason: 'unbound' }).then(({ data }) => {
            if (data && data.ok) {
                // 도형은 지우지 않는다 — 미배정 슬롯으로 남는다(설계 원칙 B4).
                this._toast(this._t('Device released. The area is now unassigned.'), 'success');
                this._stampBinding(this.slot && this.slot.spatial_id, null, null, null);
                this._afterChange();
                this._refreshSlot();
            } else {
                this._toast((data && data.message) || this._t('Failed to save'), 'error');
            }
        });
    }

    /**
     * 배정 결과를 **그 도형에 바로 입힌다** — 색이 장치 종류를 따르기 때문.
     *
     * 도형의 `device_id`/`device_type` 은 저장되는 값이 아니라 서버가 도형을
     * 읽어 줄 때 바인딩에서 파생해 주입하는 값이다(geo_overlays 의 GB-5 규약).
     * 그래서 배정 직후에는 화면의 도형이 그 값을 아직 모르고, **새로고침해야
     * 색이 바뀌는** 것처럼 보였다. 여기서 같은 값을 미리 채워 넣고 다시 칠해
     * 즉시 반영한다 — 다음 로드 때 서버가 주는 값과 같은 값이라 어긋나지 않는다.
     *
     * `deviceId` 가 null 이면 해제로 보고 지운다(미배정 색으로 돌아간다).
     */
    _stampBinding(spatialId, deviceId, channelId, deviceType) {
        const p = this.parent;
        if (!spatialId || !p) return;
        const match = (l) => {
            const props = (l && l.feature && l.feature.properties) || {};
            return (props.shape_uuid || props.node_id) === spatialId;
        };
        const stamp = (l) => {
            const props = l.feature.properties = l.feature.properties || {};
            if (deviceId) {
                props.device_id = deviceId;
                props.channel_id = channelId || '0';
                if (deviceType) props.device_type = deviceType;
            } else {
                delete props.device_id;
                delete props.channel_id;
                delete props.device_type;
            }
            // 색은 스타일 파이프라인 한 곳이 정한다 — 여기서 직접 칠하면
            // 모드 전환 때 다시 칠해지며 원래대로 돌아간다.
            if (p.ui && p.ui._setLayerStyle) p.ui._setLayerStyle(l, l === p.activeLayer);
        };
        let done = false;
        ['device', 'aot_device'].forEach(k => {
            const g = p.layerStorage && p.layerStorage[k];
            if (!g || typeof g.eachLayer !== 'function') return;
            g.eachLayer(l => { if (!done && match(l)) { stamp(l); done = true; } });
        });
        if (!done && window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            window.AoTMapEditor.featureGroup.eachLayer(l => {
                if (!done && match(l)) { stamp(l); done = true; }
            });
        }
    }

    /** 배정이 바뀌면 지도에 반영한다 — 도형 색·라벨이 장치를 따르기 때문. */
    _afterChange() {
        this._devices = null;
        try {
            // ⚠ 예전에는 `parent.loadOverlays()` 를 먼저 시도했는데 **그런 함수가
            // 없다** — 늘 아래 폴백으로 떨어져 장치 **마커만** 다시 읽었다.
            // 도형(담당 구역)은 갱신되지 않아 배정해도 색이 그대로였다.
            // 도형 쪽은 `_stampBinding` 이 즉시 반영하므로, 여기서는 마커만
            // 다시 읽으면 된다(도면 전체를 다시 읽으면 배정 한 번에 화면이
            // 통째로 깜빡인다).
            if (this.parent && this.parent.devices) {
                this.parent.devices.loadMapDevices();
            }
        } catch (e) { /* 지도 갱신 실패가 배정 성공을 덮지 않도록 */ }
    }

    // ── C. 장치가 연결되지 않은 자리 ────────────────────────────────────
    //
    // 처음 만들었을 때는 목록에 'New aot_device / 지도 구역' 같은 줄이 떴다.
    // 기계는 uuid 로 구분하지만 **사람은 그게 어디의 무엇인지 알 방법이
    // 없었다.** 그래서 각 줄이 세 가지에 답하게 한다: 무엇인가 · 어디인가 ·
    // 왜 비어 있나. 이름이 기본값인 구역에서는 면적과 이전 장치가 사실상
    // 유일한 단서다.

    /** 종류 라벨 — 이름이 없을 때 "이게 뭔지"를 대신 말한다. */
    _slotKindLabel(slot) {
        if (slot.spatial_kind === 'shape') return this._t('Zone');
        const k = String(slot.item_kind || '').toLowerCase();
        const map = {
            window: 'Window', curtain: 'Curtain', shade: 'Shade',
            fan: 'Fan', heater: 'Heater', cooler: 'Cooler',
            fogger: 'Fogger', lighting: 'Lighting', sensor: 'Sensor',
        };
        return map[k] ? this._t(map[k]) : (slot.item_kind || this._t('Fitting'));
    }

    /** 첫 줄 — 무엇인가. 이름이 있으면 이름, 없으면 종류 + 크기. */
    _slotTitle(slot) {
        if (slot.what) return slot.what;
        const kind = this._slotKindLabel(slot);
        if (slot.size) return `${kind} ${Number(slot.size).toLocaleString()} m²`;
        return kind;
    }

    /** 둘째 줄 — 왜 비어 있나. 이전 장치가 있으면 그게 가장 강한 단서다. */
    _slotStory(slot) {
        if (slot.never_bound) return this._t('No device has ever been linked here');
        const when = (slot.ended_at || '').slice(0, 10);
        if (slot.last_device_name) {
            return `${this._t('Was')}: ${slot.last_device_name}${when ? ' · ' + when : ''}`;
        }
        // 이름이 안 나오면 그 장치는 삭제된 것이다 — 그 사실이 곧 답이다.
        return `${this._t('The device that was here has been deleted')}${when ? ' · ' + when : ''}`;
    }

    openUnboundSlots() {
        this._shell(this._t('Places with no device'));
        this._setBody(`<div class="text-muted">${this._t('Loading...')}</div>`);

        // **구역만 본다.** 시설 설비(천창·팬 등)의 장치 배정은 시설 편집기의
        // 인스펙터가 정본 입력 수단이고 그쪽은 시설 JSON 에 쓴다. 여기서
        // 바인딩을 직접 만들면 다음 시설 저장이 그 배정을 지운다(실측 확인).
        // 관할이 다른 것을 한 화면에 섞으면 지도에서 천창이 나온다.
        const mapUuid = this.parent && this.parent.currentMapUuid;
        const q = '/api/geo/binding/unbound?kinds=shape'
                + (mapUuid ? '&map_uuid=' + encodeURIComponent(mapUuid) : '');
        Promise.all([
            this._api('GET', q),
            this._loadDevices()
        ]).then(([res]) => {
            const payload = (res && res.data) || {};
            if (!payload.ok) {
                this._setBody(`<div class="text-danger">${payload.message || this._t('Failed to load')}</div>`);
                return;
            }
            // 다른 지도의 구역까지 섞이면 여기서 연결해도 지금 화면에 안 보인다.
            const slots = (payload.slots || []).filter(
                s => !s.map_uuid || !mapUuid || s.map_uuid === mapUuid);

            if (!slots.length) {
                this._setBody(
                    `<div class="text-muted text-center py-4">${this._t('Every area on this map has a device linked.')}</div>`);
                return;
            }

            let html = `<div class="alert alert-light border mb-3 py-2 px-3 small text-muted">
                    ${this._t('Areas you have drawn on this map with no device assigned yet. Click one to link a device.')}
                </div><div class="list-group">`;
            slots.forEach((s, i) => {
                const locatable = s.spatial_kind === 'shape' && s.at;
                html += `
                    <div class="list-group-item border rounded mb-2 px-4 py-3">
                        <div class="d-flex justify-content-between align-items-center">
                            <span class="font-weight-600">${this._slotTitle(s)}</span>
                            <span class="small text-muted">${s.where || ''}</span>
                        </div>
                        <div class="d-flex justify-content-between align-items-center mt-1">
                            <span class="small text-muted">${this._slotStory(s)}</span>
                            <span>
                                ${locatable ? `<button class="btn btn-aot-pill btn-aot-outline" data-slot-locate="${i}">${this._t('Show on map')}</button>` : ''}
                                <button class="btn btn-aot-pill btn-aot-action" data-slot-link="${i}">${this._t('Link a device')}</button>
                            </span>
                        </div>
                    </div>`;
            });
            html += `</div>`;

            const body = this._setBody(html);
            if (!body) return;
            body.querySelectorAll('[data-slot-link]').forEach(el => {
                el.onclick = () => this.openForSlot(
                    slots[parseInt(el.dataset.slotLink, 10)]);
            });
            body.querySelectorAll('[data-slot-locate]').forEach(el => {
                el.onclick = () => this._locate(
                    slots[parseInt(el.dataset.slotLocate, 10)]);
            });
        });
    }

    /** 지도에서 그 자리로 이동한다 — "이게 어디지?" 가 첫 질문이기 때문이다.
     *
     * 이 페이지가 이미 갖고 있는 `panToShape` 를 쓴다. 지도를 화면 안으로
     * 스크롤하고, 도형에 맞춰 확대하고, **그 도형을 선택 상태로 만든다** —
     * 선택되면 패널에 '장치 배정' 버튼이 그대로 나타나므로 목록으로 돌아올
     * 필요가 없다. 직접 flyTo 를 부르면 이 셋 중 둘을 잃는다(실제로 처음엔
     * 그렇게 짰다가 지도가 아예 움직이지 않았다 — 호출 규약이 다르다).
     */
    _locate(slot) {
        const nodeId = slot && (slot.node_id || slot.spatial_id);
        if (!nodeId || !this.parent || typeof this.parent.panToShape !== 'function') {
            return;
        }
        this._close();
        try {
            this.parent.panToShape(nodeId);
            // panToShape 는 선택까지 해 주지만, 폴리곤은 fitBounds 경로가
            // 이 지도 구현에서 조건을 못 넘겨 화면이 그대로일 때가 있다.
            // 서버가 준 대표 좌표로 한 번 더 확실히 이동한다 — 선택만 되고
            // 화면은 안 움직이면 사용자는 아무 일도 안 일어난 줄 안다.
            const at = slot.at;
            if (at && this.parent.map && typeof this.parent.map.jumpTo === 'function') {
                this.parent.map.jumpTo({ center: [at[1], at[0]], zoom: 18 });
            }
        } catch (e) {
            this._toast(this._t('Failed to load'), 'error');
        }
    }
}

window.AoTGeoBinding = AoTGeoBinding;
