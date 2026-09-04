/**
 * 일지 문서의 지도 한 장.
 *
 * ⚠ **편집 지도(`/geo/design`)가 지도를 세우는 방법을 그대로 따른다.**
 *   `AoTGeoDesign._initMap()` 을 보면 그것도 `new maplibregl.Map(...)` 을 직접
 *   만들고(바탕 = 설정의 첫 `vector` 레이어 style.json, 실패하면 demotiles),
 *   `ScaleControl`·`AttributionControl` 을 붙인 뒤 공용 모듈을 bind 한다
 *   (`AoTVectorLayerManager`·`AoTRasterBridge`·`AoTMapCustomControls`).
 *   여기서도 같은 순서를 쓴다 — 그리기·편집만 뺀다.
 *
 *   `AoTMapLoader.initMap()` 은 쓰지 않는다. 이름이 그럴듯해 한 번 갈아탔다가
 *   되돌렸다 — 그것은 leaflet 셸(`L.control.layers`)을 전제로 하는데 그 셸은
 *   이 저장소 어디에도 없고, 편집 지도도 그 함수를 쓰지 않는다(옛 `AoTGeoView`
 *   전용이다). 실측: 로더를 부르면 `L.control.layers is not a function` 에서
 *   멈춘다.
 *
 * 이 파일이 하는 일은 **문서가 말하는 자리를 얹는 것**뿐이다 — 구획 도형과
 * 이름, 그 구획이 든 대지·구역의 도형과 이름, 센서 자리. 색·채움·선 굵기·
 * 이름표 모양은 전부 편집 지도의 값과 클래스를 그대로 쓴다(각 자리 주석 참조).
 */
(function () {
  'use strict';

  var MOUNT = 'journal-map';
  var DATA = 'journal-map-data';

  /** 종류별 테마색 — 편집 지도와 **같은 출처**다. */
  function themeColor(key, fallback) {
    if (window.AoTGeoTheme && window.AoTGeoTheme.color) {
      var c = window.AoTGeoTheme.color(key);
      if (c) { return c; }
    }
    var tc = (window.AOT_GEO_CONFIG || {}).theme_config || {};
    var v = tc[key];
    return (typeof v === 'string' && v.charAt(0) === '#') ? v : fallback;
  }

  /** 배경색 위에서 읽히는 글자색 (design/aot-geo-plot.js `_readableOn`). */
  function readableOn(hex) {
    var h = String(hex || '').replace('#', '');
    var f = h.length === 3 ? h.split('').map(function (c) { return c + c; }).join('') : h;
    if (f.length !== 6) { return '#ffffff'; }
    var v = [0, 2, 4].map(function (i) {
      var c = parseInt(f.substr(i, 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    var lum = 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
    return lum > 0.45 ? '#1a1a1a' : '#ffffff';
  }

  /** GeoJSON 기하 → `[w, s, e, n]`. 이름표를 도형 한가운데 놓는 데 쓴다. */
  function bboxOf(geometry) {
    var box = null;
    var stack = [(geometry || {}).coordinates];
    while (stack.length) {
      var item = stack.pop();
      if (!Array.isArray(item) || !item.length) { continue; }
      if (typeof item[0] === 'number' && typeof item[1] === 'number') {
        box = box ? [Math.min(box[0], item[0]), Math.min(box[1], item[1]),
                     Math.max(box[2], item[0]), Math.max(box[3], item[1])]
                  : [item[0], item[1], item[0], item[1]];
        continue;
      }
      stack.push.apply(stack, item);
    }
    return box;
  }

  function init() {
    var mount = document.getElementById(MOUNT);
    var holder = document.getElementById(DATA);
    if (!mount || !holder) { return; }
    if (typeof maplibregl === 'undefined') {
      // 지도가 없다고 문서가 망가지면 안 된다 — 자리만 접는다.
      if (mount.parentNode) { mount.parentNode.removeChild(mount); }
      return;
    }

    var d;
    try { d = JSON.parse(holder.textContent || '{}'); } catch (e) { return; }
    if (!d || !d.geometry) { return; }

    // ── 지도 세우기 (AoTGeoDesign._initMap 과 같은 순서) ────────────────
    //   바탕은 설정에 켜진 **첫 벡터 레이어의 style.json** 이다 — 편집 지도가
    //   고르는 것과 같은 것이라 두 화면의 바탕이 어긋나지 않는다. 벡터 스타일은
    //   글리프도 함께 주므로 지도 글자(도로·지명)가 제대로 나온다.
    var cfg = window.AOT_GEO_CONFIG || {};
    var vectors = (cfg.layers || []).filter(function (l) {
      return l.type === 'vector' && l.url;
    });
    var DEMO = 'https://demotiles.maplibre.org/style.json';
    var styleUrl = vectors.length ? vectors[0].url : DEMO;

    var map = new maplibregl.Map({
      container: MOUNT,
      style: styleUrl,
      center: [(d.bbox[0] + d.bbox[2]) / 2, (d.bbox[1] + d.bbox[3]) / 2],
      zoom: parseFloat(cfg.zoom) || 16,
      maxZoom: parseInt(cfg.max_zoom, 10) || 22,
      attributionControl: false,
      antialias: true,
      // ⚠ 인쇄. 꺼져 있으면 브라우저가 인쇄하려고 캔버스를 읽는 순간 이미
      //   지워진 뒤라 **지도 자리가 백지로 나온다**. 편집 지도가 이것을 끈
      //   이유(GPU stall)는 3D 시설과 상호작용이 많은 화면의 사정이고, 여기는
      //   정지된 그림 한 장이라 해당하지 않는다.
      preserveDrawingBuffer: true
    });
    var native = map;

    // 바탕 style.json 이 죽어 있으면(키 만료·403) 편집 지도와 **같은 폴백**으로.
    var onStyleFail = function (e) {
      var st = (e && e.error && e.error.status) || 0;
      var url = (e && e.error && e.error.url) || '';
      if ((url === styleUrl || url.indexOf('style.json') !== -1)
          && (st === 401 || st === 403 || st === 404 || st >= 500)) {
        map.off('error', onStyleFail);
        try { map.setStyle(DEMO); } catch (err) { /* 더 할 수 있는 것이 없다 */ }
      }
    };
    map.on('error', onStyleFail);
    map.once('load', function () { map.off('error', onStyleFail); });

    // ── 확대/축소·나침반은 **왼쪽 묶음**에 — 편집 지도와 같은 방식 ──────
    //   `AoTGeoDesign._initMap()` 이 하는 그대로다: 네이티브 컨트롤은
    //   **나침반만**(showZoom: false) 만들어 `.map-tools-left .tool-group`
    //   안으로 옮겨 붙이고, 확대/축소는 그 묶음의 앱 단추가 맡는다. 오른쪽
    //   위에 maplibre 기본 컨트롤을 세우면 이 앱의 지도가 아닌 것이 된다.
    //
    //   회전·기울임은 켠 채로 둔다 — 비닐하우스 줄처럼 밭이 정북을 향하지 않는
    //   자리에서는 돌려 봐야 모양이 읽히고, 나침반으로 언제든 북으로 되돌린다.
    var navCtrl = new maplibregl.NavigationControl({
      showCompass: true, showZoom: false, visualizePitch: true});
    try {
      var navEl = navCtrl.onAdd(map);
      var group = document.querySelector('#geo-design-wrapper .map-tools-left'
                                         + ' .tool-group');
      if (navEl && group) {
        navEl.style.cssText = 'background:transparent;box-shadow:none;'
          + 'border-radius:0;overflow:visible;';
        group.appendChild(navEl);
      }
    } catch (e) { /* 나침반이 없어도 지도는 읽힌다 */ }

    var zin = document.getElementById('tool-zoom-in');
    var zout = document.getElementById('tool-zoom-out');
    if (zin) { zin.addEventListener('click', function (ev) {
      ev.preventDefault(); map.zoomIn(); }); }
    if (zout) { zout.addEventListener('click', function (ev) {
      ev.preventDefault(); map.zoomOut(); }); }

    map.addControl(new maplibregl.ScaleControl({maxWidth: 100, unit: 'metric'}),
                   'bottom-left');
    // 저작권 표시 — 편집 지도와 같은 컨트롤·같은 자리다. 빼면 안 된다.
    map.addControl(new maplibregl.AttributionControl({compact: true}),
                   'bottom-right');

    map.once('load', function () {
      // 공용 레이어 모듈 bind — 편집 지도가 하는 것과 같다.
      try {
        if (window.AoTVectorLayerManager && window.AoTVectorLayerManager.bind) {
          window.AoTVectorLayerManager.bind(map);
        }
        if (window.AoTRasterBridge && window.AoTRasterBridge.create) {
          window.AoTRasterBridge.create(map);
        }
      } catch (e) { /* 없으면 바탕만으로 충분하다 */ }
      // ── 레이어 패널 — **편집 지도의 것을 그대로 쓴다** ────────────────
      //   `AoTGeoUI._toggleLayerPanel()` 이 바탕(래스터·벡터·벡터 채널)과
      //   오버레이를 전부 다루고 마지막 선택도 기억한다. 그 코드는 `parent`
      //   에서 네 가지만 읽으므로(map · _baseStyleLayerIds ·
      //   _activeVectorStyleUrl · _activeRasterBaseId) 그 넷만 채운 껍데기를
      //   넘긴다 — 편집기(AoTGeoDesign)를 통째로 세울 필요가 없다.
      //
      //   ⚠ 공용 `AoTMapCustomControls.createLayerControl` 을 쓰지 말 것.
      //     이름은 같아 보여도 **다른 물건**이다 — 장비·구조·경계 같은 내용
      //     레이어를 켜고 끄는 것이라 바탕 지도를 고를 수 없다(그것을 붙였다가
      //     되돌렸다, 지적 2026-09-04).
      try {
        if (typeof AoTGeoUI !== 'undefined') {
          var shim = {
            map: map,
            // 바탕 스타일이 원래 갖고 있던 레이어 id — 래스터 바탕으로 바꿀 때
            // 이것들을 숨긴다. 우리가 나중에 얹는 도형은 여기 없으므로 남는다.
            _baseStyleLayerIds: ((map.getStyle() || {}).layers || [])
                .map(function (l) { return l.id; }),
            _activeVectorStyleUrl: styleUrl,
            _activeRasterBaseId: null
          };
          var ui = new AoTGeoUI(shim);
          ui.initLegacyLayerButtons();
          var btn = document.getElementById('tool-layers');
          if (btn) {
            btn.addEventListener('click', function (ev) {
              ev.preventDefault();
              ev.stopPropagation();
              ui._toggleLayerPanel();
            });
          }
          // 바탕을 바꾸면 스타일이 통째로 갈리므로 우리 도형을 다시 얹는다.
          map.on('styledata', function () {
            if (map.isStyleLoaded() && !markers.length) { draw(); }
          });
        }
      } catch (e) { /* 패널이 없어도 지도는 읽힌다 */ }
    });

    // ── 쌓임 순서 ────────────────────────────────────────────────────────
    //   지도 위젯에도 같은 성격의 표가 있다(`aot-map-widget-vector.js` 의
    //   `LABEL_Z`: site 9 > zone 8 > plot 5 > sensor 1). 여기서는 **일부러
    //   뒤집는다** — 그 지도는 농장 전체를 훑는 화면이라 큰 것이 위에 서는 것이
    //   맞지만, 이 문서는 **구획 하나에 대한 것**이라 그 이름이 다른 라벨에
    //   가려지면 안 된다(지적 2026-09-04). 대지·구역 이름표는 어차피 화면
    //   가장자리에 붙어 맥락만 알려 준다.
    var Z = {plot: 9, sensor: 5, dot: 4, zone: 3, site: 2};

    var markers = [];        // 전부 (다시 그릴 때 지우려고 들고 있는다)
    var keepAlways = [];     // 대지·구역·구획 — 절대 감추지 않는다
    var sensorMarkers = [];  // 센서 — 남는 자리에만 선다
    var areaLabels = [];

    function plotChip(name, color) {
      var el = document.createElement('div');
      el.className = 'aot-sensor-map-marker aot-bay-chip aot-plot-chip';
      var row = document.createElement('div');
      row.className = 'aot-bay-chip-name';
      row.textContent = name;
      el.appendChild(row);
      el.style.background = color;
      el.style.color = readableOn(color);
      el.style.fontSize = '12px';
      el.style.lineHeight = '1.2';
      el.style.cursor = 'default';
      el.style.zIndex = Z.plot;
      return el;
    }

    /** site/zone 이름표 — `design/aot-geo-label.js` 의 `updateLabelIcon` 과
     *  같은 모양이다(배경 = 도형색, 흰 글자, 1px 테두리, 12px 굵게). */
    function areaLabel(name, color, kind) {
      var host = document.createElement('div');
      host.className = 'geo-label-marker aot-' + kind + '-label';
      host.style.cssText = 'width:0;height:0;overflow:visible;z-index:'
        + (kind === 'site' ? Z.site : Z.zone) + ';';
      var box = document.createElement('div');
      box.className = 'p-1 rounded shadow-sm text-center';
      box.style.cssText = 'width:max-content;font-size:12px;line-height:1.2;'
        + 'white-space:nowrap;border:1px solid;transform:translate(-50%,-50%);'
        + 'background-color:' + color + ';color:#fff;border-color:' + color + ';';
      var b = document.createElement('div');
      b.style.fontWeight = 'bold';
      b.textContent = name;
      box.appendChild(b);
      host.appendChild(box);
      return host;
    }

    function sensorPin(name, color) {
      var el = document.createElement('div');
      el.className = 'aot-sensor-map-marker';
      el.textContent = name;
      el.style.background = color;
      el.style.color = readableOn(color);
      el.style.cursor = 'default';
      el.style.zIndex = Z.sensor;
      return el;
    }

    /** 센서 **자리** 표시. 이름표와 달리 **절대 감추지 않는다** — 이름이 자리를
     *  못 잡아도 "여기 센서가 있다" 는 남아야 한다. 글자를 덮지 않을 만큼 작다. */
    function sensorDot(color) {
      var el = document.createElement('div');
      el.className = 'aot-journal-map-dot';
      el.style.background = color;
      el.style.zIndex = Z.dot;
      return el;
    }

    // 대지·구역은 구획보다 훨씬 커서, 구획에 맞춘 화면에서는 **한가운데가
    // 화면 밖**이다 — 그러면 이름표가 영영 안 보인다. 밖으로 나가면 가장자리
    // 안쪽으로 끌어다 붙인다(도형이 화면을 가로지르고 있으므로 가장자리에
    // 붙은 이름표가 그 도형을 가리키는 것이 맞다).
    function pinLabels() {
      if (!areaLabels.length) { return; }
      var w = native.getContainer().clientWidth;
      var h = native.getContainer().clientHeight;
      var pad = 46;
      areaLabels.forEach(function (it) {
        var p = native.project(it.home);
        var x = Math.min(Math.max(p.x, pad), Math.max(pad, w - pad));
        var y = Math.min(Math.max(p.y, pad), Math.max(pad, h - pad));
        it.marker.setLngLat((x === p.x && y === p.y)
                            ? it.home : native.unproject([x, y]));
      });
    }

    function addShape(geometry, color, opts) {
      var id = 'journal-shape-' + Math.random().toString(36).slice(2, 9);
      native.addSource(id, {
        type: 'geojson',
        data: {type: 'Feature', geometry: geometry, properties: {}}
      });
      if (opts.fill) {
        native.addLayer({id: id + '-fill', type: 'fill', source: id,
                         paint: {'fill-color': color, 'fill-opacity': opts.fill}});
      }
      native.addLayer({
        id: id + '-line', type: 'line', source: id,
        paint: Object.assign({'line-color': color, 'line-width': opts.width},
                             opts.dash ? {'line-dasharray': opts.dash} : {})
      });
    }

    function draw() {
      var plotColor = d.color || themeColor('plot', '#92d676');
      var sensorColor = themeColor('input', '#f08a8a');

      // 대지 → 구역 → 구획 순으로 얹는다(큰 것이 아래).
      // 색과 선 굵기(2)는 편집 지도 그대로다(aot-geo-layer.js). 다만 **채움은
      // 넣지 않는다** — 편집 지도는 농장 전체를 놓고 보므로 옅은 채움이 도형을
      // 고르는 데 도움이 되지만, 이 지도는 구획 하나에 맞춰 들어가 있어서 대지
      // 채움이 화면을 통째로 덮는다(실측). 여기서 채움이 하던 일(고르기)은
      // 아예 없다 — 조작하는 지도가 아니다.
      (d.containers || []).forEach(function (c) {
        var color = c.color || themeColor(c.kind, c.kind === 'site'
                                          ? '#ad1a00' : '#0f8290');
        addShape(c.geometry, color, {width: 2});
      });

      // 채움 0.45 · 선 4 — 편집 지도에서 **강조된 구획**과 같은 값이다
      // (design/aot-geo-plot.js). 이 문서의 주인공이므로 강조 쪽을 쓴다.
      // 끝난 작기는 점선 — 이것도 편집 지도와 같은 약속이다.
      addShape(d.geometry, plotColor,
               {fill: 0.45, width: 4, dash: d.ended ? [4, 4] : null});

      markers.forEach(function (m) { try { m.remove(); } catch (e) {} });
      markers = [];
      keepAlways = [];
      sensorMarkers = [];
      areaLabels = [];

      (d.containers || []).forEach(function (c) {
        var box = bboxOf(c.geometry);
        if (!box || !c.name) { return; }
        var color = c.color || themeColor(c.kind, c.kind === 'site'
                                          ? '#ad1a00' : '#0f8290');
        var home = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
        var m = new maplibregl.Marker(
          {element: areaLabel(c.name, color, c.kind), anchor: 'center'})
          .setLngLat(home).addTo(native);
        markers.push(m);
        keepAlways.push(m);
        areaLabels.push({marker: m, home: home});
      });

      if (d.name) {
        var pbox = bboxOf(d.geometry) || d.bbox;
        var chip = new maplibregl.Marker(
          {element: plotChip(d.name, plotColor), anchor: 'center'})
          .setLngLat([(pbox[0] + pbox[2]) / 2, (pbox[1] + pbox[3]) / 2])
          .addTo(native);
        markers.push(chip);
        keepAlways.push(chip);
      }

      (d.sensors || []).forEach(function (s) {
        // 자리(점)와 이름표는 **따로** 둔다 — 점은 늘 남고, 이름표만 겹침
        // 정리의 대상이 된다.
        markers.push(new maplibregl.Marker(
          {element: sensorDot(sensorColor), anchor: 'center'})
          .setLngLat([s.lng, s.lat]).addTo(native));
        var el = sensorPin(s.name, sensorColor);
        el.dataset.name = s.name;      // `+N` 을 붙였다 지우려면 원문이 필요하다
        var m = new maplibregl.Marker({element: el, anchor: 'bottom'})
          .setLngLat([s.lng, s.lat]).addTo(native);
        markers.push(m);
        sensorMarkers.push(m);
      });

      pinLabels();
      scheduleDeclutter();
    }

    // ── 이름표 겹침 정리 ────────────────────────────────────────────────
    //   좁은 밭에 센서가 몰리면 이름표가 서로를 덮어 아무것도 못 읽는다.
    //
    //   ⚠ **줄이는 것은 센서 이름표뿐이다.** 대지·구역·구획 이름표는 이 문서가
    //     무엇에 대한 것인지를 말하는 글자라 어떤 경우에도 감추지 않는다. 처음에
    //     전부를 한 줄에 세워 겨루게 했더니 구획 이름이 센서에 밀려 사라졌다
    //     (지적 2026-09-04). 그 셋은 먼저 자리를 차지하고, 센서는 남는 자리에만
    //     선다.
    //
    //   ⚠ 합칠 때 **별도 배지를 띄우지 않는다.** 중심점에 배지를 새로 세우면
    //     지도를 조금만 움직여도 배지가 생겼다 사라졌다 하며 자리까지 옮겨
    //     다녀 불안하다("매우 불안함"). 대신 **살아남은 이름표 뒤에 `+N` 을
    //     붙인다** — 자리가 움직이지 않고, 무엇이 몇 개인지도 그대로 읽힌다.
    //
    //   같은 성격의 구현이 지도 위젯에도 있다(`AoT_map/aot-map-widget-vector.js`
    //   의 `runLabelCollisionWithClustering`). 다만 그것은 위젯 IIFE 안에 갇혀
    //   있어 밖에서 부를 수 없다. 세 번째 호출자가 생기면 공용 모듈로 뺄 것.

    function overlaps(a, b) {
      return !(a.right <= b.left || a.left >= b.right ||
               a.bottom <= b.top || a.top >= b.bottom);
    }

    //: 살아남은 센서 이름표 뒤에 붙는 ` +N` 이 차지할 만큼의 폭(px). 겹침을
    //  잴 때 **미리 비워 둔다** — 재고 나서 글자를 늘리면 그 늘어난 만큼이
    //  구획 이름을 덮는다(실측: 구획 칩과 센서 칩이 겹친 채 둘 다 보였다).
    var SUFFIX_ROOM = 30;

    function padded(el, extraRight) {
      var r = el.getBoundingClientRect();
      if (r.width < 1) { return null; }
      return {left: r.left - 3, right: r.right + 3 + (extraRight || 0),
              top: r.top - 3, bottom: r.bottom + 3};
    }

    function declutter() {
      // 항상 보이는 것들이 먼저 자리를 잡는다.
      var taken = [];
      keepAlways.forEach(function (mk) {
        var el = mk.getElement();
        el.style.visibility = 'visible';
        var r = padded(el);
        if (r) { taken.push(r); }
      });

      var shown = null;
      var absorbed = 0;
      sensorMarkers.forEach(function (mk) {
        var el = mk.getElement();
        el.style.visibility = 'visible';
        el.textContent = el.dataset.name || el.textContent;   // 지난 `+N` 지우기
        // 첫 번째로 서는 것에만 ` +N` 이 붙을 수 있으므로 그 자리만 넉넉히 잡는다.
        var r = padded(el, shown ? 0 : SUFFIX_ROOM);
        if (!r) { return; }
        if (taken.some(function (t) { return overlaps(r, t); })) {
          el.style.visibility = 'hidden';
          absorbed += 1;
          return;
        }
        taken.push(r);
        if (!shown) { shown = el; }
      });

      // ⚠ **전부 가려져도 아무 이름표를 되살리지 않는다.** 예전에는 "센서가
      //   있다는 사실이 사라지면 안 된다" 며 첫 하나를 무조건 되살렸는데, 그
      //   되살린 이름표가 바로 **구획 이름을 덮었다**(지적 2026-09-04). 자리는
      //   점(`sensorDot`)이 이미 말하고 있으므로 글자를 억지로 세울 이유가 없다
      //   — 확대하면 자리가 생겨 이름이 다시 선다.
      if (absorbed > 0 && shown) {
        shown.textContent = (shown.dataset.name || '') + ' +' + absorbed;
      }
    }

    // 겹침 판정은 **다음 프레임에** 한다. 지도가 마커의 transform 을 적용하기
    // 전에 재면 아직 옛 자리라 "안 겹친다" 로 나오고, 그 결과가 그대로 굳는다
    // (실측: 구획 칩과 센서 칩이 뚜렷이 겹치는데 둘 다 보였다).
    var declutterPending = false;
    function scheduleDeclutter() {
      if (declutterPending) { return; }
      declutterPending = true;
      var run = function () {
        declutterPending = false;
        declutter();
      };
      if (window.requestAnimationFrame) {
        window.requestAnimationFrame(function () { window.requestAnimationFrame(run); });
      } else {
        setTimeout(run, 32);
      }
    }

    function frame() {
      native.fitBounds([[d.bbox[0], d.bbox[1]], [d.bbox[2], d.bbox[3]]],
                       {padding: 44, maxZoom: 19, duration: 0});
      pinLabels();
      scheduleDeclutter();
    }

    function start() {
      draw();
      frame();
    }

    if (native.isStyleLoaded && native.isStyleLoaded()) { start(); }
    else { native.once('load', start); }

    native.on('move', pinLabels);
    native.on('resize', pinLabels);
    // 겹침 정리는 **움직임이 끝난 뒤**에만 — 매 프레임 돌리면 이름표가 떨린다.
    native.on('moveend', scheduleDeclutter);
    native.on('zoomend', scheduleDeclutter);
    // ⚠ `idle` 도 듣는다. `fitBounds({duration: 0})` 직후에 바로 재면 마커가
    //   아직 옛 자리에 있어 **겹치지 않는 것으로 잰다** — 그래서 센서 이름표가
    //   구획 이름 위에 그대로 얹혀 있었다(실측: 두 상자가 겹치는데 둘 다
    //   보임). 그리기가 가라앉은 뒤 한 번 더 잰다. 여러 번 불려도 결과는
    //   같다(원문은 `dataset.name` 에 있어 `+N` 이 겹쳐 붙지 않는다).
    native.on('idle', scheduleDeclutter);

    if (window.ResizeObserver) {
      new ResizeObserver(function () { native.resize(); }).observe(mount);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
