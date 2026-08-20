/**
 * 공용 데이터 시각화 빌더 — 밴드 바 · 불릿 · 기간 바.
 *
 * 마크업과 색 규칙은 `static/css/components/aot-dataviz.css` 한 곳에 있고,
 * 이 모듈은 **값을 위치(%)로 바꾸는 계산**만 담당한다. 그 계산이 버그가 사는
 * 자리다 — 범위가 뒤집힌 경우, 폭이 0 인 경우, 값이 범위를 벗어난 경우,
 * 값이 아예 없는 경우. 화면마다 각자 나누기를 하면 그 네 가지를 각자 틀린다.
 *
 * 문구는 만들지 않는다. 라벨·값·눈금은 **이미 번역·서식된 문자열**을 받는다.
 *  - 서식(소수점 자릿수·단위·날짜)은 부르는 쪽이 이미 알고 있다.
 *  - 번역 문구를 여기서 만들면 msgid 가 이 파일에 갇힌다. 특히 '%' 는 babel
 *    이 python-format 으로 읽어 `pybabel compile` 이 그 언어 전체를 거부한다
 *    (CLAUDE.md 의 리터럴 % 금지 규칙).
 *
 * 반환은 HTML 문자열이다 — 지도 팝업 빌더(aot-map-popup.js)가 문자열을 이어
 * 붙이는 방식이라 거기에 그대로 섞을 수 있어야 한다.
 */
(function (global) {
    'use strict';

    if (global.AoTViz) return;

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function isNum(v) { return typeof v === 'number' && isFinite(v); }

    /* 값 → 0..100 (%). 범위가 없거나 폭이 0 이면 null 을 돌려주고, 부르는 쪽은
       마커를 그리지 않는다. 0 으로 떨어뜨리면 "값 없음" 이 "가장 낮은 값" 으로
       읽힌다. */
    function pct(value, min, max) {
        if (!isNum(value) || !isNum(min) || !isNum(max)) return null;
        if (max === min) return null;
        // 범위를 거꾸로 준 경우도 받아 준다(습도 역방향 밴드 등).
        var lo = Math.min(min, max), hi = Math.max(min, max);
        var p = ((value - lo) / (hi - lo)) * 100;
        return Math.max(0, Math.min(100, p));
    }

    /* 범위를 벗어났는가 — 클램프 전 값으로 판정한다. 클램프 뒤에는 0%/100% 에
       붙은 정상값과 구분되지 않는다. */
    function isOutside(value, lo, hi) {
        if (!isNum(value)) return false;
        if (isNum(lo) && value < lo) return true;
        if (isNum(hi) && value > hi) return true;
        return false;
    }

    function headHtml(label, value, valueSub) {
        if (label == null && value == null) return '';
        return '<div class="aot-viz-head">' +
               '<span class="aot-viz-label">' + esc(label) + '</span>' +
               '<span class="aot-viz-value">' + esc(value) +
               (valueSub ? ' <small>' + esc(valueSub) + '</small>' : '') +
               '</span></div>';
    }

    /* 눈금 줄. 양 끝은 축의 끝을 적고, `{ text: …, anchor: true }` 로 표시한
       가운데 항목은 **그 줄의 기준**을 적는다 — 밴드는 적정 범위, 불릿은 목표,
       기간 바는 오늘. 기준의 실제 위치(anchorPct)에 붙여 세우므로 세 줄이
       나란히 놓여도 같은 규칙으로 읽힌다.

       양 끝 12% 안쪽이면 끝에 붙여 세운다 — 그대로 두면 잘린다. 그 경우 같은
       쪽 축 라벨을 가리게 되는데, 가려도 되는 쪽이다(축의 끝은 트랙이 이미
       보여 주지만 기준은 이 라벨 말고 적을 자리가 없다). */
    function scaleHtml(items, anchorPct) {
        if (!items || !items.length) return '';
        var anchored = isNum(anchorPct);
        var html = '<div class="aot-viz-scale' + (anchored ? ' aot-viz-scale--anchored' : '') + '">';
        for (var i = 0; i < items.length; i++) {
            var it = items[i];
            var obj  = it && typeof it === 'object';
            var text = obj ? it.text : it;
            var attr = '';
            if (obj && it.anchor && anchored) {
                var style;
                if (anchorPct <= 12)      style = 'left:0';
                else if (anchorPct >= 88) style = 'right:0';
                else style = 'left:' + anchorPct.toFixed(2) + '%;transform:translateX(-50%)';
                attr = ' class="aot-viz-scale-anchor" style="' + style + '"';
            } else if (obj && it.anchor) {
                attr = ' class="aot-viz-scale-anchor"';
            }
            html += '<span' + attr + '>' + esc(text) + '</span>';
        }
        return html + '</div>';
    }

    function cls(base, opts) {
        var c = base;
        if (opts.stale) c += ' is-stale';
        if (opts.out)   c += ' is-out';
        if (opts.empty) c += ' is-empty';
        if (opts.className) c += ' ' + opts.className;
        return c;
    }

    /* ── 밴드 바 ─────────────────────────────────────────────────────────
     * "지금 값이 적정 범위 안인가" 하나만 답한다.
     *
     *   AoTViz.band({
     *     label: '기온', value: 26.4, valueText: '26.4 °C',
     *     min: 16, max: 32, okMin: 22, okMax: 28,
     *     scale: ['16', '32']
     *   })
     */
    function band(o) {
        o = o || {};
        var p  = pct(o.value, o.min, o.max);
        var os = pct(o.okMin, o.min, o.max);
        var oe = pct(o.okMax, o.min, o.max);
        var out = isOutside(o.value, o.okMin, o.okMax);

        var html = '<div class="' +
                   cls('aot-viz aot-viz--band', { stale: o.stale, out: out, empty: p === null,
                                                  className: o.className }) +
'">';
        html += headHtml(o.label, o.valueText != null ? o.valueText : o.value, o.valueSub);
        html += '<div class="aot-viz-track">';
        if (os !== null && oe !== null && oe > os) {
            html += '<div class="aot-viz-ok" style="left:' + os.toFixed(2) +
                    '%;width:' + (oe - os).toFixed(2) + '%"></div>';
        }
        if (p !== null) {
            html += '<div class="aot-viz-now" style="left:' + p.toFixed(2) + '%"></div>';
        }
        html += '</div>';
        // 밴드의 기준은 적정 범위다 — 구간이므로 그 중앙에 붙인다.
        html += scaleHtml(o.scale,
                          (os !== null && oe !== null) ? (os + oe) / 2 : null);
        return html + '</div>';
    }

    /* ── 불릿 ────────────────────────────────────────────────────────────
     * "목표 대비 얼마나 왔나".
     *
     *   AoTViz.bullet({
     *     label: '1일 관수량', value: 1.8, target: 2.4, max: 3.0,
     *     valueText: '1.8', valueSub: '/ 2.4 L'
     *   })
     *
     * **쌓아서 도달하는 목표에만 쓴다** — 관수량·시비량·누적 GDD·작업 진척처럼
     * 0 에서 출발해 목표까지 채우는 값. 채운 막대가 곧 "얼마나 왔나" 이고,
     * 달성 여부는 막대가 목표 눈금을 넘었는지로 읽는다 — 색을 바꾸지 않는다.
     * 색을 하나 더 쓰면 같은 화면의 밴드 바·기간 바와 톤이 갈린다.
     *
     * **상·하한 목표에는 쓰지 말 것** — "주간 최고온도 28°C 이하" 를 불릿으로
     * 그리면 채워질수록 잘하고 있는 것처럼 읽히는데 실제로는 그 반대다.
     * 그런 목표는 밴드 바(`band`)가 맞다. 그래서 이 함수에는 적정 구간을
     * 칠하는 인자가 없다 — 구간이 필요하다는 것 자체가 밴드 바여야 한다는 뜻이다.
     *
     * max 를 안 주면 목표의 1.25배를 축의 끝으로 삼는다 — 목표를 넘긴 값도
     * 축 안에 남아야 "얼마나 넘겼는지" 를 볼 수 있다.
     */
    function bullet(o) {
        o = o || {};
        var min = isNum(o.min) ? o.min : 0;
        var max = o.max;
        if (!isNum(max)) {
            var span = Math.max(isNum(o.target) ? o.target : 0,
                                isNum(o.value) ? o.value : 0);
            max = span > min ? min + (span - min) * 1.25 : min + 1;
        }
        var v = pct(o.value, min, max);
        var t = pct(o.target, min, max);
        var html = '<div class="' +
                   cls('aot-viz aot-viz--bullet', { stale: o.stale, empty: v === null,
                                                    className: o.className }) +
'">';
        html += headHtml(o.label, o.valueText != null ? o.valueText : o.value, o.valueSub);
        html += '<div class="aot-viz-track">';
        if (v !== null) {
            html += '<div class="aot-viz-fill" style="width:' + v.toFixed(2) + '%"></div>';
        }
        if (t !== null) {
            html += '<div class="aot-viz-target" style="left:' + t.toFixed(2) + '%"></div>';
        }
        html += '</div>';
        // 불릿의 기준은 목표다.
        html += scaleHtml(o.scale, t);
        return html + '</div>';
    }

    /* ── 기간 바 ─────────────────────────────────────────────────────────
     * "전체 일정에서 지금 어디인가". 밴드 바와 같은 골격이다 — 적정 구간이
     * 현재 단계 구간으로, 현재 값이 오늘로 바뀌었을 뿐이다.
     *
     *   AoTViz.timeline({
     *     label: '착과기', valueText: 'D22 / 98',
     *     segments: [{ span: 14 }, { span: 7 }, { span: 20, current: true }, …],
     *     positionPct: 41,
     *     scale: ['3/2', { text: '오늘', anchor: true }, '6/8']
     *   })
     *
     * segments 의 span 은 상대 비율이면 된다(일수를 그대로 넣으면 된다).
     * current 인 구간이 '적정' 색으로 칠해진다 — 단계마다 색을 주면 단계 수
     * 만큼 색이 늘어난다.
     */
    function timeline(o) {
        o = o || {};
        var segs = Array.isArray(o.segments) ? o.segments : [];
        var total = 0, i;
        for (i = 0; i < segs.length; i++) {
            var s = Number(segs[i] && segs[i].span);
            if (isNum(s) && s > 0) total += s;
        }

        var p = isNum(o.positionPct) ? Math.max(0, Math.min(100, o.positionPct)) : null;

        var html = '<div class="' +
                   cls('aot-viz aot-viz--timeline', { stale: o.stale, empty: !total,
                                                      className: o.className }) +
'">';
        html += headHtml(o.label, o.valueText, o.valueSub);
        html += '<div class="aot-viz-track">';

        if (total > 0) {
            // 현재 구간을 먼저 칠하고 경계를 나중에 얹는다. 순서를 바꾸면
            // 현재 구간의 시작 경계가 그 칠에 덮여 사라진다.
            var cursor = 0, edges = [], w;
            for (i = 0; i < segs.length; i++) {
                var span = Number(segs[i] && segs[i].span);
                if (!isNum(span) || span <= 0) continue;
                w = (span / total) * 100;
                if (segs[i].current) {
                    html += '<div class="aot-viz-ok" style="left:' + cursor.toFixed(2) +
                            '%;width:' + w.toFixed(2) + '%"></div>';
                }
                cursor += w;
                // 마지막 경계는 트랙의 끝이라 그리지 않는다.
                if (cursor < 99.9) edges.push(cursor);
            }
            for (i = 0; i < edges.length; i++) {
                html += '<div class="aot-viz-tick" style="left:' + edges[i].toFixed(2) + '%"></div>';
            }
        }
        if (p !== null) {
            html += '<div class="aot-viz-now" style="left:' + p.toFixed(2) + '%"></div>';
        }
        html += '</div>';
        // 기간 바의 기준은 오늘이다.
        html += scaleHtml(o.scale, p);
        return html + '</div>';
    }

    /* 여러 줄을 한 묶음으로. 사이 여백을 각 호출부가 인라인 style 로 넣지
       않게 하려는 것이 전부다. */
    function group(rows) {
        return '<div class="aot-viz-group">' +
               (Array.isArray(rows) ? rows.join('') : String(rows || '')) +
               '</div>';
    }

    global.AoTViz = {
        band: band,
        bullet: bullet,
        timeline: timeline,
        group: group,
        pct: pct,
        isOutside: isOutside
    };
})(typeof window !== 'undefined' ? window : this);
