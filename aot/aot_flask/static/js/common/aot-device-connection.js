/**
 * aot-device-connection.js — 장치 접속정보 편집 폼(공용).
 *
 * 고장 교체의 정답은 장치를 지우고 새로 만드는 것이 아니라 접속정보(DevEUI·
 * 주소)만 갱신하는 것이다. 장치 uuid 가 그대로면 도형·바인딩 이력·함수 연결·
 * 측정 채널이 전부 살아 있고 시계열도 끊기지 않는다.
 *
 * 이 파일이 따로 있는 이유: 그 경로가 필요한 자리가 둘이다.
 *   - 지도(geo/design)의 슬롯 배정 모달 — 「교체」 1안
 *   - 시설 편집기의 설비 인스펙터 — 설비에 물린 장치의 교체
 * 두 화면은 서로 다른 번들에 있어 클래스를 공유할 수 없다. 그래서 **폼만**
 * 여기서 소유하고 모달 셸은 각자 소유한다 — 셸까지 공용화하면 두 페이지의
 * 모달 관례(부트스트랩 vs 인스펙터 오버레이)를 하나로 맞춰야 하고, 그건 이
 * 기능이 요구하는 것보다 훨씬 큰 변경이다.
 *
 * 서버 계약: GET/POST `/api/device/<id>/connection`
 * (aot/aot_flask/utils/utils_device_connection.py)
 */
(function () {
  'use strict';

  function _t(key) { return (window._ ? window._(key) : key); }

  function _esc(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _csrf() {
    var el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.getAttribute('content') : '';
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
    }).then(function (res) {
      return res.json().then(function (data) {
        return { status: res.status, data: data };
      });
    });
  }

  /** 이 장치에서 교체 시 갈아끼우는 필드들. 실패하면 null. */
  function fetchSchema(deviceId) {
    if (!deviceId) return Promise.resolve(null);
    return _api('GET', '/api/device/' + encodeURIComponent(deviceId) + '/connection')
      .then(function (r) { return (r.data && r.data.ok) ? r.data.schema : null; })
      .catch(function () { return null; });
  }

  /**
   * 폼 HTML. 필드가 없으면 "바꿀 접속정보가 없다"고 말한다 — 빈 폼을 보여주면
   * 사람은 뭔가 잘못됐다고 생각한다(가상 출력·계산 함수는 정상적으로 없다).
   */
  function formHtml(schema) {
    var fields = (schema && schema.fields) || [];
    if (!fields.length) {
      return '<div class="small text-muted">' +
        _t('This device has no connection settings to change.') + '</div>';
    }
    var html = fields.map(function (f) {
      return '<div class="mb-2">' +
        '<label class="small text-muted mb-1">' + _esc(f.label) + '</label>' +
        '<input type="text" class="form-control" data-conn-key="' + _esc(f.key) + '"' +
        ' value="' + _esc(f.value) + '"' + (f.readonly ? ' disabled' : '') +
        ' style="height: 38px; border-radius: 19px;">' +
        (f.help ? '<div class="small text-muted mt-1">' + _esc(f.help) + '</div>' : '') +
        '</div>';
    }).join('');
    if (schema.is_activated) {
      // 저장 도중 장치가 잠깐 멈추는 것은 놀랄 일이 아니라 절차다.
      html += '<div class="small text-muted mt-2">' +
        _t('The device will be restarted so the new settings take effect.') +
        '</div>';
    }
    return html;
  }

  /** 폼에서 값을 걷는다. 비활성(readonly) 필드는 보내지 않는다 — 서버가 거부한다. */
  function collect(rootEl) {
    var values = {};
    if (!rootEl) return values;
    rootEl.querySelectorAll('[data-conn-key]').forEach(function (el) {
      if (el.disabled) return;
      values[el.dataset.connKey] = el.value;
    });
    return values;
  }

  /**
   * 저장. 바인딩은 건드리지 않는다 — 장치가 그대로이므로 슬롯의 연결도
   * 그대로이고, 여기서 이력에 새 구간을 만들면 그것이 거짓말이 된다.
   *
   * onDone(ok, messages[]) 로 결과를 알린다. 경고는 성공에 묻히면 안 된다 —
   * 특히 "저장은 됐는데 다시 켜지지 않았다"는 사용자가 반드시 알아야 한다.
   */
  function save(deviceId, values) {
    return _api('POST', '/api/device/' + encodeURIComponent(deviceId) + '/connection',
                { values: values })
      .then(function (r) {
        var data = r.data || {};
        if (!data.ok) {
          return { ok: false, messages: [{ text: data.message || _t('Failed to save'),
                                           level: 'error' }] };
        }
        if (!data.changed || !data.changed.length) {
          return { ok: true, changed: 0,
                   messages: [{ text: _t('Nothing changed'), level: 'info' }] };
        }
        var msgs = [{ text: _t('Connection settings updated'), level: 'success' }];
        (data.warnings || []).forEach(function (w) {
          msgs.push({ text: w, level: 'error' });
        });
        return { ok: true, changed: data.changed.length, messages: msgs };
      })
      .catch(function () {
        return { ok: false, messages: [{ text: _t('Failed to save'), level: 'error' }] };
      });
  }

  window.AoTDeviceConnection = {
    fetchSchema: fetchSchema,
    formHtml: formHtml,
    collect: collect,
    save: save,
    esc: _esc
  };
})();
