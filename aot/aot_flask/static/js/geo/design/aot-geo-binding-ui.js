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
                            <button class="btn btn-aot-pill btn-aot-outline" data-bind-replace="${b.unique_id}" data-bind-channel="${b.channel_id}">${this._t('Replace')}</button>
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
            el.onclick = () => this._replaceNotice(el.dataset.bindChannel);
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
            item.onclick = () => this._assign(d.id, isReplace, channelId);
            box.appendChild(item);
        });
    }

    /**
     * 교체 안내 — 고장 교체의 정답은 대개 삭제-재생성이 아니라 접속정보 갱신이다.
     * DevEUI·주소만 바꾸면 도형·이력·함수 연결이 전부 유지된다. 사람들이
     * "새로 만들고 옛것 삭제"로 가는 것은 이 경로가 화면에 없기 때문이므로,
     * 교체를 누르면 먼저 이 길을 보여준다.
     */
    _replaceNotice(channelId) {
        this._setTitle(this._t('Replace device'));
        this._setBody(`
            <div class="alert alert-light border mb-3">
                <div class="font-weight-bold mb-1">${this._t('Is this a like-for-like hardware swap?')}</div>
                <div class="small text-muted">
                    ${this._t('If you are replacing broken hardware with the same model, update the connection settings (DevEUI, address) on the existing device instead. The shape, the history and every function link stay intact.')}
                </div>
                <div class="mt-2">
                    <a class="btn btn-aot-pill btn-aot-outline" href="/input" target="_blank">${this._t('Open Input settings')}</a>
                    <a class="btn btn-aot-pill btn-aot-outline" href="/output" target="_blank">${this._t('Open Output settings')}</a>
                </div>
            </div>
            <div class="small text-muted mb-1">${this._t('Or move this slot to a different device')}</div>
            <input type="text" class="form-control mb-2" id="geo-binding-search"
                   placeholder="${this._t('Search Device...')}" style="height: 38px; border-radius: 19px;">
            <div id="geo-binding-devices" class="list-group"></div>
            <button class="btn btn-aot-pill btn-aot-outline mt-3" id="geo-binding-back">${this._t('Back')}</button>
        `);
        const search = document.getElementById('geo-binding-search');
        if (search) search.oninput = () => this._renderDeviceList(search.value, true, channelId);
        this._renderDeviceList('', true, channelId);
        const back = document.getElementById('geo-binding-back');
        if (back) back.onclick = () => this._refreshSlot();
    }

    _assign(deviceId, isReplace, channelId) {
        const s = this.slot;
        const chEl = document.getElementById('geo-binding-channel');
        const ch = channelId || (chEl && chEl.value.trim()) || '0';
        const body = {
            spatial_kind: s.spatial_kind,
            spatial_id: s.spatial_id,
            device_id: deviceId,
            channel_id: ch
        };
        if (s.role) body.role = s.role;

        const method = isReplace ? 'PUT' : 'POST';
        this._api(method, '/api/geo/binding', body).then(({ status, data }) => {
            if (data && data.ok) {
                this._toast(this._t('Device assigned'), 'success');
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
                this._afterChange();
                this._refreshSlot();
            } else {
                this._toast((data && data.message) || this._t('Failed to save'), 'error');
            }
        });
    }

    /** 배정이 바뀌면 지도에 반영한다 — 도형 색·라벨이 장치를 따르기 때문. */
    _afterChange() {
        this._devices = null;
        try {
            if (this.parent && this.parent.loadOverlays) {
                this.parent.loadOverlays();
            } else if (this.parent && this.parent.devices) {
                this.parent.devices.loadMapDevices();
            }
        } catch (e) { /* 지도 갱신 실패가 배정 성공을 덮지 않도록 */ }
    }

    // ── C. 미배정 슬롯 ──────────────────────────────────────────────────
    openUnboundSlots() {
        this._shell(this._t('Unassigned slots'));
        this._setBody(`<div class="text-muted">${this._t('Loading...')}</div>`);

        const mapUuid = this.parent && this.parent.currentMapUuid;
        Promise.all([
            this._api('GET', '/api/geo/binding/unbound'),
            this._loadDevices()
        ]).then(([res]) => {
            const payload = (res && res.data) || {};
            if (!payload.ok) {
                this._setBody(`<div class="text-danger">${payload.message || this._t('Failed to load')}</div>`);
                return;
            }
            // 다른 지도의 구역까지 섞이면 여기서 배정해도 지금 화면에 안 보인다.
            const slots = (payload.slots || []).filter(
                s => !s.map_uuid || !mapUuid || s.map_uuid === mapUuid);

            if (!slots.length) {
                this._setBody(`<div class="text-muted text-center py-4">${this._t('Every slot has a device.')}</div>`);
                return;
            }

            let html = `<div class="small text-muted mb-2">${this._t('Places that lost their device, or were never assigned one. Click one to assign a device.')}</div>`;
            slots.forEach((s, i) => {
                const where = s.facility ? s.facility : this._t('Map area');
                const what = s.name || s.item_kind || s.item_id || s.spatial_id.slice(0, 8);
                html += `
                    <div class="list-group-item d-flex justify-content-between align-items-center mb-1 border rounded-pill px-4"
                         data-slot-index="${i}" style="cursor:pointer;">
                        <span class="font-weight-600">${what}</span>
                        <span class="small text-muted">${where}</span>
                    </div>`;
            });
            const body = this._setBody(`<div class="list-group">${html}</div>`);
            if (!body) return;
            body.querySelectorAll('[data-slot-index]').forEach(el => {
                el.onclick = () => this.openForSlot(slots[parseInt(el.dataset.slotIndex, 10)]);
            });
        });
    }
}

window.AoTGeoBinding = AoTGeoBinding;
