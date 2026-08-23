/**
 * 지도 설정 모달 — 이름 + 그룹 부여.
 *
 * 정본 설계: docs/design/access-scope-groups.md
 *
 * 예전에는 [편집] 버튼이 브라우저 `prompt()` 로 이름만 물었다. 부여를 붙이려면
 * 창이 필요하고, 탭·대시보드와 같은 자리에 같은 모양으로 두는 편이 배우기 쉽다.
 *
 * ## 왜 번들 소스가 아니라 여기인가
 *
 * 버튼을 바인딩하는 `geo/design/aot-geo-events.js` 는 `geo-design` 번들의
 * 입력이고, 그 번들은 다른 미커밋 작업(`common/aot-plot-form.js`)도 입력으로
 * 갖는다. 지금 그 소스를 고쳐 재빌드하면 **커밋된 소스와 커밋된 번들이 어긋난
 * 상태**가 되어(`check_js_bundles` 가 잡는 바로 그 드리프트) 배포된 앱이 어떤
 * 코드를 도는지 말할 수 없게 된다.
 *
 * 그래서 번들 밖에서 **capture 단계**로 가로챈다. 같은 요소에서 capture 는
 * bubble 보다 먼저 실행되고 jQuery 핸들러는 bubble 이므로, 바인딩 순서와
 * 무관하게 이쪽이 이긴다 — `off()` 로 떼어내는 방식은 상대가 나중에 다시
 * 바인딩하면 조용히 되돌아간다.
 *
 * 그쪽 작업이 커밋되면 이 파일을 `aot-geo-events.js` 안으로 옮기고 capture
 * 가로채기를 지우는 것이 정리다.
 */
(function () {
  'use strict';

  var MODAL_ID = 'modal_map_settings';

  function t(key, fallback) {
    try {
      if (window.AoTMapSettingsI18n && window.AoTMapSettingsI18n[key]) {
        return window.AoTMapSettingsI18n[key];
      }
    } catch (e) { /* 번역이 없으면 영어로 */ }
    return fallback;
  }

  function csrf() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
    var input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : '';
  }

  function currentMap() {
    // 디자인 페이지의 상태 객체가 정본이다 — 셀렉트 값만 믿으면 저장 전
    // 새 지도에서 uuid 가 비어 있는 것을 놓친다.
    var p = window.AoTGeoDesign || window.geoDesign || null;
    var uuid = (p && p.currentMapUuid) || document.getElementById('map-selector').value;
    var name = (p && p.currentMapName) || '';
    if (!name) {
      var opt = document.querySelector('#map-selector option[value="' + uuid + '"]');
      name = opt ? opt.textContent.trim() : '';
    }
    return {uuid: uuid, name: name, page: p};
  }

  function selectedGroups($sec) {
    return Array.prototype.map.call(
      $sec[0].querySelectorAll('input[name="map_groups"]:checked'),
      function (i) { return i.value; });
  }

  function refreshImpact($sec, uuid) {
    var $impact = $sec.find('.aot-map-scope-impact');
    var picked = selectedGroups($sec);
    if (!picked.length) {
      $impact.text(t('everyone',
        'Everyone can operate this map (no group assigned).'));
      return;
    }
    $.ajax({
      url: '/api/scope/grant_impact/geo_map/' + encodeURIComponent(uuid),
      method: 'POST', contentType: 'application/json',
      data: JSON.stringify({groups: picked})
    }).done(function (res) {
      if (!res || !res.success) return;
      var i = res.impact || {};
      if (i.locks_out_everyone) {
        $impact.text(t('lockout',
          'Warning: nobody would be able to operate this map.'));
      } else if (i.losing) {
        $impact.text(t('losing', 'Losing operation') + ': '
          + (i.losing_names || []).join(', '));
      } else {
        $impact.text(t('nobody', 'Nobody loses operation with this change.'));
      }
    }).fail(function () {
      // 조용히 "영향 없음" 으로 보이면 안 된다 — 모른다는 것을 말한다.
      $impact.text(t('comm_error',
        'Error: Unable to communicate with server.'));
    });
  }

  function loadScope($sec, uuid) {
    var $groups = $sec.find('.aot-map-scope-groups');
    $sec.hide();
    $groups.empty();
    $sec.find('.aot-map-scope-impact').text('');
    $.getJSON('/api/scope/grants/geo_map/' + encodeURIComponent(uuid))
      .done(function (d) {
        if (!d || !d.success) return;
        if (!d.groups.length) {
          $groups.html('<div class="aot-modal-body-text">'
            + t('no_groups',
                'No groups yet. Create one in Settings > Users > Groups.')
            + '</div>');
          $sec.show();
          return;
        }
        d.groups.forEach(function (g) {
          var $input = $('<input type="checkbox" class="btn-toggle-input" name="map_groups">')
            .val(g.unique_id).prop('checked', !!g.granted)
            .on('change', function () { refreshImpact($sec, uuid); });
          $groups.append(
            $('<div class="aot-modal-option-row">')
              .append($('<label class="aot-modal-option-label">').text(g.name))
              .append($('<div class="aot-modal-option-control">').append(
                $('<label class="btn-toggle mb-0">').append($input).append(
                  $('<div class="btn-toggle-slider">')
                    .append('<div class="btn-toggle-thumb"></div>')))));
        });
        $sec.show();
        refreshImpact($sec, uuid);
      })
      .fail(function () { /* 관리자가 아니다 — 섹션을 숨긴 채 둔다 */ });
  }

  function open() {
    var cur = currentMap();
    var $modal = $('#' + MODAL_ID);
    if (!$modal.length) return;

    if (!cur.uuid) {
      // 저장되지 않은 새 지도에는 부여할 대상이 없다.
      if (window.AoTGeoDesign && window.AoTGeoDesign.ui) {
        window.AoTGeoDesign.ui.showToast(
          t('unsaved', 'Save the map first.'), 'warning');
      }
      return;
    }

    $modal.find('#map_settings_name').val(cur.name);
    $modal.data('map-uuid', cur.uuid);
    loadScope($modal.find('.aot-map-scope'), cur.uuid);
    $modal.modal('show');
  }

  function save() {
    var $modal = $('#' + MODAL_ID);
    var uuid = $modal.data('map-uuid');
    var $sec = $modal.find('.aot-map-scope');
    var name = ($modal.find('#map_settings_name').val() || '').trim();
    if (!name) return;

    var jobs = [];

    // 이름 — 바뀐 경우에만 저장한다(지도 상태를 통째로 다시 쓰지 않기 위해).
    var cur = currentMap();
    if (name !== cur.name) {
      jobs.push(window.AoTMapData.saveMapDesign(uuid, name, {}).then(function (res) {
        if (res && res.ok) {
          var p = cur.page;
          if (p) { p.currentMapName = name; p.lastLoadedName = name; }
          var opt = $('#map-selector').find('option[value="' + uuid + '"]');
          if (opt.length) { opt.text(name); $('#map-selector').selectpicker('refresh'); }
        }
        return res;
      }));
    }

    // 부여 — **섹션이 실제로 로드됐을 때만.** 관리자가 아니거나 조회가
    // 실패해 비어 있는 상태에서 빈 목록을 보내면 부여가 통째로 지워진다.
    if ($sec.is(':visible') && $sec.find('input[name="map_groups"]').length) {
      jobs.push($.ajax({
        url: '/api/scope/grants/geo_map/' + encodeURIComponent(uuid),
        method: 'POST', contentType: 'application/json',
        headers: {'X-CSRFToken': csrf()},
        data: JSON.stringify({groups: selectedGroups($sec)})
      }));
    }

    $.when.apply($, jobs).always(function () {
      $modal.modal('hide');
    });
  }

  $(function () {
    var btn = document.getElementById('btn-edit-map-name');
    if (btn) {
      // capture 단계 — bubble 로 붙는 jQuery 핸들러(`prompt()`)보다 먼저
      // 실행되므로 바인딩 순서와 무관하게 이쪽이 이긴다.
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopImmediatePropagation();
        open();
      }, true);
    }
    $(document).on('click', '#map_settings_save', save);
  });
})();
