/**
 * 지도 위젯 중심이동(`_focusMapOn`) 실측 하네스 — 브라우저에서 돌린다.
 *
 * ## 쓰는 법
 * 대시보드를 연 탭의 콘솔(또는 javascript_tool)에 이 파일을 통째로 실행한 뒤:
 *
 *     const r = await AoTFocusHarness.run({ widgetId: '<지도 위젯 id>' });
 *     console.table(r.summary);          // 대상 종류별 집계
 *     AoTFocusHarness.markdown(r)        // PR 설명에 붙일 표
 *
 * 옵션: panel:true(기본) 는 사이트 모달을 하나 열어 둔 채(오른쪽 패널) 한 번 더 잰다.
 *
 * ## 무엇을 재나
 * 대상마다 지도를 일부러 먼 곳에 두고 `_focusMap(target)` 을 부른 뒤 카메라가 멎으면
 *   - outcome / reason / via   `_focusOutcome` · `_focusReason` · `_focusVia`
 *   - dx, dy                   대상 중심과 가시 사각형 중심(rect.cx/cy)의 차이(px)
 *   - inside                   대상 상자가 패널·독을 뺀 가시 영역 안에 드는가(2px 허용)
 *   - zoom                     옮긴 뒤 줌
 * 을 남긴다. 도형이 가시 영역보다 크면(`oversize`) inside 대신 영역을 덮는지로 본다.
 *
 * 대상 종류: site · zone · facility(시설 도형) · device-shape(도형 있는 장치) ·
 * device-marker(마커만 있는 장치·센서) · label_aux · plot(노지 구획) · plot-facility
 * (시설 안 구획 — `feature` 가 비고 `derived_feature` 로 오는 것).
 *
 * 개발서버 실데이터에 의존하므로 숫자가 아니라 **판정 기준**(moved · inside)이 계약이다.
 */
(function (global) {
    'use strict';

    var TOL = 2;                 // px 허용 오차
    var POINT_PAD = 16;          // 점 대상의 반폭(코드의 POINT_PAD_PX 와 같다)

    function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

    async function settle(map) {
        await sleep(50);
        for (var i = 0; i < 60 && map.isMoving && map.isMoving(); i++) await sleep(30);
        await sleep(30);
    }

    function bboxOf(geom) {
        var w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
        (function walk(a) {
            if (!a) return;
            if (typeof a[0] === 'number') {
                if (a[0] < w) w = a[0]; if (a[0] > e) e = a[0];
                if (a[1] < s) s = a[1]; if (a[1] > n) n = a[1];
                return;
            }
            a.forEach(walk);
        })(geom.coordinates);
        return [[w, s], [e, n]];
    }

    // 화면(논리 px) 상자. geometry → 네 모서리, 점 → ±POINT_PAD.
    function screenBox(map, t) {
        var pts, pad = 0;
        if (t.geometry) {
            var b = bboxOf(t.geometry);
            pts = [[b[0][0], b[0][1]], [b[1][0], b[0][1]], [b[1][0], b[1][1]], [b[0][0], b[1][1]]];
            if (b[0][0] === b[1][0] && b[0][1] === b[1][1]) pad = POINT_PAD;
        } else { pts = [[t.lng, t.lat]]; pad = POINT_PAD; }
        var xs = [], ys = [];
        pts.forEach(function (p) { var q = map.project(p); xs.push(q.x); ys.push(q.y); });
        var l = Math.min.apply(null, xs) - pad, r = Math.max.apply(null, xs) + pad;
        var tp = Math.min.apply(null, ys) - pad, bt = Math.max.apply(null, ys) + pad;
        return { l: l, r: r, t: tp, b: bt, cx: (l + r) / 2, cy: (tp + bt) / 2, w: r - l, h: bt - tp };
    }

    function collectTargets(id, inst) {
        var host = document.getElementById('aot-map-' + id);
        var cache = inst._shapeCache || {};
        var out = [], seenEntry = new Set();
        Object.keys(cache).forEach(function (k) {
            var e = cache[k];
            if (seenEntry.has(e)) return;
            seenEntry.add(e);
            var kind = e.aot_type === 'aot_device'
                ? 'device-shape' : e.aot_type;
            out.push({ kind: kind, name: k.slice(0, 8), ref: k, geomType: e.geometry.type,
                       geometry: e.geometry });
        });
        // 마커만 있는 장치(도형이 없다) — DOM 마커 자리가 정답이다.
        var seenDev = {};
        host.querySelectorAll('.aot-sensor-map-marker[data-device-id]').forEach(function (el) {
            var d = el.dataset.deviceId;
            if (!d || seenDev[d] || cache[d] || !el._aotMarker) return;
            seenDev[d] = 1;
            var ll = el._aotMarker.getLngLat();
            out.push({ kind: 'device-marker', name: (el.dataset.labelName || d).slice(0, 12),
                       ref: d, lng: ll.lng, lat: ll.lat });
        });
        return out;
    }

    async function collectPlots(id, inst) {
        var feats = inst.map.getSource('aot-plot-src-' + id);
        feats = (feats && window.AoTMapSeam.sourceGeoJSON(feats) || {}).features || [];   // 5 는 _data 가 { geojson } 로 감싸여 있다
        var out = [];
        for (var i = 0; i < feats.length; i++) {
            var u = feats[i].properties.plot_uuid;
            var res = await fetch('/api/geo/plot/' + u, { cache: 'no-store' }).then(function (r) { return r.json(); });
            var p = res && res.plot;
            if (!p) continue;
            var g = (p.feature && p.feature.geometry) || (p.derived_feature && p.derived_feature.geometry);
            if (!g) continue;
            // 모달의 focus 콜백이 받는 것과 같은 모양(구획 응답)을 그대로 넘긴다.
            out.push({ kind: p.feature ? 'plot' : 'plot-facility',
                       name: (p.name || p.subject || u).slice(0, 12),
                       ref: { unique_id: p.unique_id, feature: p.feature,
                              derived_feature: p.derived_feature },
                       geometry: g });
        }
        return out;
    }

    async function measure(id, inst, t, startView) {
        var map = inst.map;
        map.jumpTo(startView);
        inst._autoZoom = null;
        await settle(map);
        var seq0 = inst._focusSeq || 0;
        inst._focusMap(t.ref, { highlight: false, transient: true });
        var ran = (inst._focusSeq || 0) > seq0;
        await settle(map);
        var row = { kind: t.kind, name: t.name, ran: ran, outcome: inst._focusOutcome,
                    reason: inst._focusReason || null, via: inst._focusVia || null,
                    zoom: +map.getZoom().toFixed(2) };
        var rect = inst._lastFitRect, ins = inst._lastFitInset;
        if (row.outcome === 'moved' && rect && ins) {
            var bx = screenBox(map, t.geometry ? { geometry: t.geometry } : t);
            var W = rect.W, H = rect.H;
            var area = { l: ins.left, r: W - ins.right, t: ins.top, b: H - ins.bottom };
            row.dx = Math.round(bx.cx - rect.cx);
            row.dy = Math.round(bx.cy - rect.cy);
            row.oversize = bx.w > (area.r - area.l) + TOL || bx.h > (area.b - area.t) + TOL;
            row.inside = row.oversize
                ? (bx.l <= area.l + TOL && bx.r >= area.r - TOL ||
                   bx.t <= area.t + TOL && bx.b >= area.b - TOL) &&
                  bx.cx > area.l && bx.cx < area.r && bx.cy > area.t && bx.cy < area.b
                : (bx.l >= area.l - TOL && bx.r <= area.r + TOL &&
                   bx.t >= area.t - TOL && bx.b <= area.b + TOL);
        } else { row.inside = false; }
        return row;
    }

    function summarize(rows) {
        var by = {};
        rows.forEach(function (r) {
            var k = r.kind;
            var o = by[k] || (by[k] = { kind: k, n: 0, moved: 0, none: 0, locked: 0, inside: 0,
                                         maxAbsDx: 0, maxAbsDy: 0, zmin: 99, zmax: -99 });
            o.n++;
            o[r.outcome] = (o[r.outcome] || 0) + 1;
            if (r.inside) o.inside++;
            if (r.outcome === 'moved') {
                if (!r.oversize) {
                    o.maxAbsDx = Math.max(o.maxAbsDx, Math.abs(r.dx));
                    o.maxAbsDy = Math.max(o.maxAbsDy, Math.abs(r.dy));
                }
                o.zmin = Math.min(o.zmin, r.zoom); o.zmax = Math.max(o.zmax, r.zoom);
            }
        });
        return Object.keys(by).map(function (k) {
            var o = by[k];
            if (o.zmin === 99) { o.zmin = null; o.zmax = null; }
            return o;
        });
    }

    async function pass(id, inst, targets, label) {
        var map = inst.map;
        var start = { center: map.getCenter(), zoom: 15.5, bearing: map.getBearing(), pitch: 0 };
        // 대상에서 확실히 먼 출발점 — 지금 중심에서 남서쪽으로 조금 비킨다.
        start.center = [start.center.lng - 0.01, start.center.lat - 0.006];
        var rows = [];
        for (var i = 0; i < targets.length; i++) {
            var r = await measure(id, inst, targets[i], start);
            r.pass = label;
            rows.push(r);
        }
        return rows;
    }

    async function run(opts) {
        opts = opts || {};
        var id = opts.widgetId;
        var inst = global.AoTWidgetInstances && global.AoTWidgetInstances[id];
        if (!inst || !inst.map) throw new Error('widget instance not found: ' + id);
        // 도형·마커가 다 올라올 때까지 기다린다(재시작 직후엔 늦다).
        for (var w = 0; w < 120 && !(Object.keys(inst._shapeCache || {}).length &&
                document.querySelectorAll('#aot-map-' + id + ' .aot-sensor-map-marker').length); w++) {
            await sleep(500);
        }
        var saved = { c: inst.map.getCenter(), z: inst.map.getZoom(), b: inst.map.getBearing() };
        // 열린 모달 대상으로 구도를 되돌리는 자동 재조정(`_refitCurrentFocus`)은 재는 동안 끈다 —
        // 도크 높이가 바뀔 때마다 카메라를 사이트 모달 쪽으로 당겨 측정을 어지럽힌다.
        // (그 동작 자체는 `refitCheck` 가 따로 잰다.)
        var savedRefit = inst._lastRefitAt;
        inst._lastRefitAt = Infinity;
        var targets = collectTargets(id, inst).concat(await collectPlots(id, inst));
        var all = [];
        all = all.concat(await pass(id, inst, targets, 'panel-closed'));
        if (opts.panel !== false) {
            // 오른쪽 패널(사이트 모달)을 연 채 — 패널 폭만큼 가시 영역이 줄어든다.
            var site = targets.filter(function (t) { return t.kind === 'site'; })[0];
            if (site && inst._openSiteModal) {
                inst._openSiteModal(site.ref, 'harness');
                await sleep(900);
                all = all.concat(await pass(id, inst, targets, 'panel-open'));
                var ov = document.getElementById('aot-facility-ctrl-overlay-' + id);
                var cb = ov && ov.querySelector('.aot-modal-close, .maplibregl-popup-close-button, [data-action="close"]');
                if (cb) cb.click(); else if (ov) ov.remove();
                await sleep(500);
            }
        }
        inst._lastRefitAt = savedRefit;
        inst.map.jumpTo({ center: saved.c, zoom: saved.z, bearing: saved.b });
        var summary = {};
        ['panel-closed', 'panel-open'].forEach(function (p) {
            summary[p] = summarize(all.filter(function (r) { return r.pass === p; }));
        });
        return { widgetId: id, rows: all, summary: summary };
    }

    function markdown(res) {
        var out = [];
        Object.keys(res.summary).forEach(function (p) {
            if (!res.summary[p].length) return;
            out.push('**' + p + '**', '',
                '| 종류 | n | moved | none | 가시영역 안 | 최대 dx | 최대 dy | 줌 |',
                '|---|---|---|---|---|---|---|---|');
            res.summary[p].forEach(function (o) {
                out.push('| ' + [o.kind, o.n, o.moved || 0, o.none || 0, o.inside,
                    o.maxAbsDx, o.maxAbsDy,
                    o.zmin == null ? '-' : (o.zmin === o.zmax ? o.zmin : o.zmin + '~' + o.zmax)].join(' | ') + ' |');
            });
            out.push('');
        });
        return out.join('\n');
    }

    global.AoTFocusHarness = { run: run, markdown: markdown, summarize: summarize };
})(window);
