/**
 * 시설 그룹 부여 — 기본 정보(Specification) 안에 붙는 섹션.
 *
 * 정본 설계: docs/design/access-scope-groups.md
 *
 * ## 왜 자기 [적용] 버튼을 갖는가
 *
 * 시설의 [저장]은 `geo-facility` 번들 안에 있고, 그 번들은 지금 다른 미커밋
 * 작업(`common/aot-plot-form.js`)도 입력으로 갖는다. 거기 훅을 걸려면 소스를
 * 고치고 재빌드해야 하는데, 그러면 **커밋된 소스와 커밋된 번들이 어긋난다**
 * (`check_js_bundles` 가 잡는 그 드리프트) — 배포된 앱이 어떤 코드를 도는지
 * 말할 수 없게 된다.
 *
 * 탭·대시보드·지도는 [저장] 하나로 함께 나가는데 여기만 다른 것은 그 사정
 * 때문이다. 그쪽 작업이 커밋되면 시설 저장에 합치는 것이 정리다.
 */
(function () {
  'use strict';

  function t(key, fallback) {
    try {
      var d = window.AoTFacilityScopeI18n;
      if (d && d[key]) return d[key];
    } catch (e) { /* 번역이 없으면 영어로 */ }
    return fallback;
  }

  function csrf() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
    var input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : '';
  }

  function facilityUuid() {
    // 번들의 `FacilityIO.current()` 와 같은 정본을 본다. 없으면 페이지가 심어
    // 둔 JSON 으로 폴백한다 — 둘 중 하나는 항상 있다.
    try {
      if (window.FacilityIO && window.FacilityIO.current) {
        var v = window.FacilityIO.current();
        if (v) return v;
      }
    } catch (e) { /* 폴백 */ }
    var el = document.getElementById('facility-page-vars');
    if (!el) return null;
    try { return (JSON.parse(el.textContent) || {}).facility_uuid || null; }
    catch (e) { return null; }
  }

  function section() { return document.querySelector('.aot-fac-scope'); }

  function picked() {
    var sec = section();
    if (!sec) return [];
    return Array.prototype.map.call(
      sec.querySelectorAll('input[name="facility_groups"]:checked'),
      function (i) { return i.value; });
  }

  function setImpact(text) {
    var el = document.querySelector('.aot-fac-scope-impact');
    if (el) el.textContent = text;
  }

  function refreshImpact(uuid) {
    var groups = picked();
    if (!groups.length) {
      setImpact(t('everyone',
        'Everyone can operate this facility (no group assigned).'));
      return;
    }
    fetch('/api/scope/grant_impact/geo_facility/' + encodeURIComponent(uuid), {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
      body: JSON.stringify({groups: groups})
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (res) {
        if (!res || !res.success) return;
        var i = res.impact || {};
        if (i.locks_out_everyone) {
          setImpact(t('lockout',
            'Warning: nobody would be able to operate this facility.'));
        } else if (i.losing) {
          setImpact(t('losing', 'Losing operation') + ': '
            + (i.losing_names || []).join(', '));
        } else {
          setImpact(t('nobody', 'Nobody loses operation with this change.'));
        }
      }).catch(function () {
        // 조용히 "영향 없음" 으로 보이면 안 된다 — 모른다는 것을 말한다.
        setImpact(t('comm_error',
          'Error: Unable to communicate with server.'));
      });
  }

  function load() {
    var sec = section();
    if (!sec) return;
    var uuid = facilityUuid();
    sec.style.display = 'none';
    var host = sec.querySelector('.aot-fac-scope-groups');
    host.innerHTML = '';
    setImpact('');
    if (!uuid) return;                   // 아직 시설을 고르지 않았다

    fetch('/api/scope/grants/geo_facility/' + encodeURIComponent(uuid))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.success) return;    // 관리자가 아니다 — 숨긴 채 둔다
        if (!d.groups.length) {
          host.innerHTML = '<div class="aot-modal-body-text">'
            + t('no_groups',
                'No groups yet. Create one in Settings > Users > Groups.')
            + '</div>';
          sec.style.display = '';
          return;
        }
        d.groups.forEach(function (g) {
          var row = document.createElement('div');
          row.className = 'aot-modal-option-row';
          var label = document.createElement('label');
          label.className = 'aot-modal-option-label';
          label.textContent = g.name;
          var control = document.createElement('div');
          control.className = 'aot-modal-option-control';
          var toggle = document.createElement('label');
          toggle.className = 'btn-toggle mb-0';
          var input = document.createElement('input');
          input.type = 'checkbox';
          input.className = 'btn-toggle-input';
          input.name = 'facility_groups';
          input.value = g.unique_id;
          input.checked = !!g.granted;
          input.addEventListener('change', function () { refreshImpact(uuid); });
          var slider = document.createElement('div');
          slider.className = 'btn-toggle-slider';
          slider.innerHTML = '<div class="btn-toggle-thumb"></div>';
          toggle.appendChild(input);
          toggle.appendChild(slider);
          control.appendChild(toggle);
          row.appendChild(label);
          row.appendChild(control);
          host.appendChild(row);
        });
        sec.style.display = '';
        refreshImpact(uuid);
      })
      .catch(function () { /* 숨긴 채 둔다 */ });
  }

  function apply() {
    var uuid = facilityUuid();
    var sec = section();
    // **섹션이 실제로 로드됐을 때만 보낸다.** 비어 있는 상태에서 빈 목록을
    // 보내면 부여가 통째로 지워진다.
    if (!uuid || !sec || !sec.querySelectorAll('input[name="facility_groups"]').length) {
      return;
    }
    fetch('/api/scope/grants/geo_facility/' + encodeURIComponent(uuid), {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
      body: JSON.stringify({groups: picked()})
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (res) {
        if (res && res.success) {
          setImpact(t('saved', 'Saved'));
          refreshImpact(uuid);
        }
      }).catch(function () {
        setImpact(t('comm_error',
          'Error: Unable to communicate with server.'));
      });
  }

  document.addEventListener('DOMContentLoaded', function () {
    load();
    var btn = document.getElementById('fac_scope_apply');
    if (btn) btn.addEventListener('click', apply);
  });
})();
