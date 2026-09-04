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
    /* note: 눈금 줄 **오른쪽 끝**에 붙는 짧은 덧말(추세·면적 등).
       lead: 같은 줄 **왼쪽 끝**의 덧말(마지막 작동 등).
       눈금이 하나도 없어도 덧말만으로 줄을 만든다 — 축을 못 그리는 지표도
       방향은 말할 수 있기 때문이다.

       ⚠ **덧말을 `items` 로 넣지 말 것.** items 는 *축의 눈금*이라, 기준이 축
       끝에 붙는 줄에서는 그쪽 끝 항목이 CSS 로 감춰진다(is-anchor-start/end).
       거기에 덧말을 넣으면 목표가 0% 나 100% 인 장치에서만 그 글자가 조용히
       사라진다 — 2026-08-26 에 실제로 그랬다(창이 100% 로 열린 동안에만
       '마지막 작동' 이 안 보였다). 덧말은 축이 아니므로 자기 슬롯을 쓴다. */
    function scaleHtml(items, anchorPct, note, lead) {
        items = items || [];
        if (!items.length && !note && !lead) return '';
        var anchored = isNum(anchorPct);
        // 끝에 붙는 경우 그쪽 축 라벨을 **감춘다.** 예전에는 배경만 깔았는데,
        // 기준 라벨이 짧으면(예: '오늘') 그 옆으로 축 라벨이 삐져나와
        // "오늘 08/14" 처럼 한 덩어리로 읽혔다. 축의 끝은 트랙이 이미 보여
        // 주지만 기준은 이 라벨 말고 적을 자리가 없다.
        var edge = '';
        if (anchored) {
            if (anchorPct <= 12) edge = ' is-anchor-start';
            else if (anchorPct >= 88) edge = ' is-anchor-end';
        }
        var html = '<div class="aot-viz-scale' +
                   (anchored ? ' aot-viz-scale--anchored' : '') + edge + '">';
        if (lead) {
            html += '<span class="aot-viz-scale-lead">' + esc(lead) + '</span>';
        }
        for (var i = 0; i < items.length; i++) {
            var it = items[i];
            var obj  = it && typeof it === 'object';
            var text = obj ? it.text : it;
            var attr = '';
            if (obj && it.anchor && anchored) {
                var style;
                // 끝으로 밀 때는 **left 를 반드시 풀어 준다.** 공용 규칙이
                // `left: calc(...)` 를 갖고 있어, right 만 주면 좌우가 동시에
                // 고정돼 라벨이 트랙 폭만큼 늘어난다.
                if (anchorPct <= 12)      style = 'left:0';
                else if (anchorPct >= 88) style = 'right:0;left:auto';
                // 마커와 **같은 식**이다(캡 보정은 CSS 의 left 가 한다).
                else style = '--aot-viz-pos:' + anchorPct.toFixed(2) +
                             ';transform:translateX(-50%)';
                attr = ' class="aot-viz-scale-anchor" style="' + style + '"';
            } else if (obj && it.anchor) {
                attr = ' class="aot-viz-scale-anchor"';
            }
            html += '<span' + attr + '>' + esc(text) + '</span>';
        }
        if (note) {
            html += '<span class="aot-viz-scale-note">' + esc(note) + '</span>';
        }
        return html + '</div>';
    }

    /* 구간 이름 줄 (기간 바). 트랙 위에 **구간 폭 그대로** 늘어선다 —
       flex-basis 를 구간 비율로 주므로 이름과 그 아래 구간이 어긋나지 않는다.
       이름이 하나도 없으면 줄 자체를 만들지 않는다. */
    function segNamesHtml(segs, total) {
        if (!total) return '';
        var any = false, i;
        for (i = 0; i < segs.length; i++) {
            if (segs[i] && segs[i].name) { any = true; break; }
        }
        if (!any) return '';
        var html = '<div class="aot-viz-segs">';
        for (i = 0; i < segs.length; i++) {
            var span = Number(segs[i] && segs[i].span);
            if (!isNum(span) || span <= 0) continue;
            var w = (span / total) * 100;
            var name = segs[i].name || '';
            html += '<div class="aot-viz-seg' +
                    (segs[i].current ? ' is-current' : '') +
                    '" style="flex:0 0 ' + w.toFixed(2) + '%"' +
                    (name ? ' title="' + esc(name) + '"' : '') + '>' +
                    esc(name) + '</div>';
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
     *     spanMin: 22.8, spanMax: 33.7,   // 그 기간의 최저~최고(선택)
     *     scale: ['16', '32']
     *   })
     *
     * **초록 = 실측, 직각선 = 목표.** `okMin`/`okMax` 는 이름 그대로 목표
     * 범위이고, 이제 초록 면이 아니라 **선 둘**로 그려진다. 부르는 쪽은
     * 그대로 두고 그림만 바뀐다.
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
        /* ── 예외: on/off 장치의 가동시간 줄 ───────────────────────────
         *
         * `okZone: true` 면 **옛 그림 그대로** 그린다(초록 면 + 세로선 마커).
         * 그 줄에서는 초록이 "목표" 가 아니라 **평소 가동시간**이고 왼쪽 끝에서
         * 자라며, 마커는 오늘이다 — 길이 자체가 뜻이라 선 둘로는 못 옮긴다
         * (aot-map-popup.js `_rowOf` 의 binary 분기).
         *
         * ⚠ 이 손잡이를 다른 자리에 쓰지 말 것. 한 화면에 두 어휘가 서면
         * 이 파일이 2026-09-04 에 겪은 일이 그대로 되돌아온다. */
        if (o.okZone) {
            if (os !== null && oe !== null && oe > os) {
                html += '<div class="aot-viz-ok" style="left:' + os.toFixed(2) +
                        '%;width:' + (oe - os).toFixed(2) + '%"></div>';
            }
            if (p !== null) {
                html += '<div class="aot-viz-now" style="--aot-viz-pos:' +
                        p.toFixed(2) + '"></div>';
            }
        } else {
        /* ── 실측은 초록, 목표는 직각선 ────────────────────────────────
         *
         * 예전에는 반대였다 — 초록 면이 적정 범위(목표)였고 세로선이 지금
         * 값이었다. 그런데 불릿은 처음부터 "초록 = 실측(누적), 선 = 목표"
         * 였고, 두 줄이 한 카드에 나란히 서면 초록과 선의 뜻이 줄마다
         * 뒤집혔다(2026-09-04 신고). 밴드 바를 불릿 쪽에 맞춘다.
         *
         * 실측은 **폭**으로 그린다(그 기간의 최저~최고). 값 하나뿐이면
         * 그 자리에 최소 두께로 선다 — CSS `min-width` 가 그 몫이다. */
        var sLo = pct(o.spanMin, o.min, o.max);
        var sHi = pct(o.spanMax, o.min, o.max);
        if (sLo !== null && sHi !== null && sHi > sLo) {
            html += '<div class="aot-viz-span" style="left:' + sLo.toFixed(2) +
                    '%;width:' + (sHi - sLo).toFixed(2) + '%"></div>';
        } else if (p !== null) {
            html += '<div class="aot-viz-span" style="left:' + p.toFixed(2) +
                    '%;width:0"></div>';
        }
        // 목표 — 하나면 선 하나, 범위면 양 끝 둘. 맨 위에 선다(CSS z-index).
        if (os !== null) {
            html += '<div class="aot-viz-target" style="--aot-viz-pos:' +
                    os.toFixed(2) + '"></div>';
        }
        if (oe !== null && (os === null || oe > os)) {
            html += '<div class="aot-viz-target" style="--aot-viz-pos:' +
                    oe.toFixed(2) + '"></div>';
        }
        }
        html += '</div>';
        // 밴드의 기준은 적정 범위이므로 눈금 라벨을 그 **중앙**에 붙인다.
        // 다만 눈금의 기준 항목이 `at`(축 위의 값)을 주면 그 자리를 쓴다 —
        // 사람이 정한 목표가 있으면 그것이 이 줄의 기준이고, 라벨이 가리키는
        // 곳과 실제 위치가 달라서는 안 된다.
        var at = null;
        for (var k = 0; k < (o.scale || []).length; k++) {
            var it = o.scale[k];
            if (it && typeof it === 'object' && it.anchor && isNum(it.at)) {
                at = pct(it.at, o.min, o.max);
                break;
            }
        }
        html += scaleHtml(o.scale,
                          (at !== null) ? at
                          : ((os !== null && oe !== null) ? (os + oe) / 2 : null),
                          o.scaleNote, o.scaleLead);
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
        // 0 이면 막대를 그리지 않는다. min-width 때문에 점이 남으면 "조금
        // 열려 있다" 로 읽힌다 — 꺼져 있는 장치가 켜진 것처럼 보이는 것은
        // 여백보다 나쁘다. "값 없음" 과는 여전히 구분된다: 그쪽은 값 글자가
        // '—' 이고 트랙이 흐려진다(is-empty).
        if (v !== null && v > 0) {
            html += '<div class="aot-viz-fill" style="width:' + v.toFixed(2) + '%"></div>';
        }
        if (t !== null) {
            html += '<div class="aot-viz-target" style="--aot-viz-pos:' +
                    t.toFixed(2) + '"></div>';
        }
        html += '</div>';
        // 불릿의 기준은 목표다.
        html += scaleHtml(o.scale, t, o.scaleNote, o.scaleLead);
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
     *
     * segments[].name 을 주면 **트랙 위**에 구간 이름 줄이 생긴다(구간 폭에
     * 맞춰 늘어선다). 하나도 없으면 그 줄을 만들지 않는다.
     *
     * events 는 축 위에 찍는 **사건**이다 — `[{ pct, label }]`.
     *
     *   events: [{ pct: 22.4, label: '2026-04-03 정식 확인' }, …]
     *
     * 단계 경계(tick)와 다른 것을 말한다: 경계는 "계획이 여기서 갈린다" 이고
     * 사건은 "그날 실제로 무엇을 했다" 이다. 둘이 겹칠 수는 있지만 같지 않다 —
     * 승인을 미루면 경계는 그대로인데 사건만 뒤로 간다.
     *
     * **색을 늘리지 않는다.** 사건은 '이 지점' 이므로 오늘 마커와 같은 마커
     * 색이고, 구분은 모양이 한다(오늘=세로 선, 사건=점). 색으로 가르면 이
     * 파일의 세 색 규칙이 넷이 되고, 나란히 놓인 밴드·불릿과 톤이 갈린다.
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

        // compact — 구간 이름 줄과 눈금 줄을 뺀다. 좁은 카드에서는 그 둘이
        // 트랙보다 자리를 더 먹는데, 정작 답해야 하는 것은 "지금 어디쯤" 하나다.
        // 단계 이름은 머리줄이 이미 말하고(부르는 쪽이 넣는다), 구간 이름은
        // 트랙의 title 로 남는다.
        var compact = !!o.compact;

        var html = '<div class="' +
                   cls('aot-viz aot-viz--timeline', { stale: o.stale, empty: !total,
                                                      className: o.className }) +
                   (compact ? ' aot-viz--compact' : '') +
'">';
        html += headHtml(o.label, o.valueText, o.valueSub);
        if (!compact) html += segNamesHtml(segs, total);
        html += '<div class="aot-viz-track"' +
                (compact ? ' title="' + esc(segs.map(function (x) {
                    return x && x.name;
                }).filter(Boolean).join(' \u203a ')) + '"' : '') + '>';

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
        // 사건은 **오늘 마커보다 먼저** 얹는다. 같은 날 전환을 확인했으면 둘이
        // 정확히 겹치는데, 그때 가려져야 하는 쪽은 사건이다 — 오늘이 어디인지는
        // 축 전체를 읽는 기준이라 무엇에도 가려지면 안 된다.
        var evs = Array.isArray(o.events) ? o.events : [];
        for (i = 0; i < evs.length; i++) {
            var ep = Number(evs[i] && evs[i].pct);
            if (!isNum(ep)) continue;
            ep = Math.max(0, Math.min(100, ep));
            html += '<div class="aot-viz-event" style="--aot-viz-pos:' +
                    ep.toFixed(2) + '"' +
                    (evs[i].label ? ' title="' + esc(evs[i].label) + '"' : '') +
                    '></div>';
        }
        if (p !== null) {
            html += '<div class="aot-viz-now" style="--aot-viz-pos:' +
                    p.toFixed(2) + '"></div>';
        }

        /* 구간을 **누를 수 있게** 한다(`pickable`). 축은 지금까지 "현재 단계"
           하나만 말했는데, 다음에 무엇이 오는지가 궁금한 것이 정상이다.

           표적은 트랙보다 **훨씬 크다.** 압축 축의 트랙은 6px 이라 손가락으로
           정확히 누를 수 없다 — 보이지 않는 칸을 위아래로 넉넉히 얹는다.
           칸은 구간 폭 그대로라, 누른 자리와 고른 단계가 어긋나지 않는다. */
        if (o.pickable && total > 0) {
            var cur2 = 0;
            for (i = 0; i < segs.length; i++) {
                var sp2 = Number(segs[i] && segs[i].span);
                if (!isNum(sp2) || sp2 <= 0) continue;
                var w2 = (sp2 / total) * 100;
                html += '<button type="button" class="aot-viz-seg-hit' +
                        (segs[i].picked ? ' is-picked' : '') + '"' +
                        (segs[i].key ? ' data-viz-key="' + esc(segs[i].key) + '"' : '') +
                        (segs[i].name ? ' title="' + esc(segs[i].name) + '"' +
                                        ' aria-label="' + esc(segs[i].name) + '"' : '') +
                        ' style="left:' + cur2.toFixed(2) + '%;width:' +
                        w2.toFixed(2) + '%"></button>';
                cur2 += w2;
            }
        }
        html += '</div>';
        // 기간 바의 기준은 오늘이다.
        if (!compact) html += scaleHtml(o.scale, p);
        return html + '</div>';
    }

    /* ── 값만 ────────────────────────────────────────────────────────────
     * 트랙 없이 머리줄(라벨 + 값)만. **축을 모르는 값**에 쓴다 — 적정 범위가
     * 정의돼 있지 않은 지표(예: 기본 범위가 없는 CO2)에 억지로 축을 그리면
     * 그 축의 끝이 무슨 근거인지 아무도 답할 수 없다.
     *
     * 밴드 바와 같은 머리줄을 쓰므로 한 목록에 섞여도 줄이 어긋나지 않는다.
     */
    function value(o) {
        o = o || {};
        var html = '<div class="' +
                   cls('aot-viz aot-viz--value', { stale: o.stale, out: !!o.out,
                                                   className: o.className }) +
                   '">';
        html += headHtml(o.label, o.valueText != null ? o.valueText : o.value,
                         o.valueSub);
        return html + '</div>';
    }

    /* ── 스파크라인 ──────────────────────────────────────────────────────
     * 최근 값들의 **모양**만 낸다 — 축도 눈금도 없다.
     *
     * 적정 범위를 만들 수 없는 지표(CO2·토양수분·이슬점…)는 값 하나로는 좋은지
     * 나쁜지 말할 수 없다. 그런데 **추세는 범위를 몰라도 그릴 수 있다** — "지금
     * 612ppm" 은 판단할 수 없지만 "오르는 중" 은 값 몇 개면 보인다.
     *
     * 그래서 세로축에 숫자를 붙이지 않는다. 붙이면 그 축이 판단 기준처럼
     * 읽히는데, 여기서는 **최소~최대에 맞춰 늘린 상대 모양**일 뿐이다(값 두
     * 개짜리도 화면을 가득 채운다). 판단은 하지 않고 방향만 말한다.
     *
     *   AoTViz.spark({ label: 'CO2', valueText: '612', valueSub: 'ppm',
     *                  points: [612, 604, 598, …] })   // 오래된 것 → 최신 순
     */
    function spark(o) {
        o = o || {};
        var pts = (o.points || []).filter(isNum);
        var html = '<div class="' +
                   cls('aot-viz aot-viz--spark', { stale: o.stale,
                                                   className: o.className }) +
                   '">';
        html += headHtml(o.label, o.valueText != null ? o.valueText : o.value,
                         o.valueSub);
        // 점이 둘 미만이면 선이 아니라 점이다 — 방향을 말할 수 없으므로 그리지
        // 않는다(빈 칸이 "아직 모른다" 를 정직하게 말한다).
        if (pts.length >= 2) {
            var lo = Math.min.apply(null, pts), hi = Math.max.apply(null, pts);
            var span = (hi - lo) || 1;          // 평평한 구간도 그린다(가운데 선)
            var n = pts.length;
            var d = pts.map(function (v, i) {
                var x = (i / (n - 1)) * 100;
                // viewBox 높이 24, 위아래 3 여백 — 선 굵기가 잘리지 않게.
                var y = 21 - ((v - lo) / span) * 18;
                return x.toFixed(2) + ',' + y.toFixed(2);
            }).join(' ');
            html += '<svg class="aot-viz-spark" viewBox="0 0 100 24" ' +
                    'preserveAspectRatio="none" aria-hidden="true">' +
                    '<polyline points="' + d + '"/></svg>';
        }
        return html + '</div>';
    }

    /* ── 추세 띠 ─────────────────────────────────────────────────────────
     * 기간에 걸친 값의 **범위와 목표 대비 위치**. `spark` 와 다른 것 —
     * 스파크는 판단 없이 모양만 말하고, 이것은 밴드 바(`band`)를 시간축으로
     * 늘인 것이라 목표·적정 구간을 함께 그린다(반복되는 일별 표를 대신해
     * 여러 날을 한 줄로 요약하려고 만들었다 — 구획 일지의 §4).
     *
     *   AoTViz.trend({
     *     label: '기온', valueText: '28.7 °C', valueSub: '어제',
     *     points: [{ k: '08-15', min: 22.1, max: 34.8, avg: 27.6 }, …],
     *     band: { lo: 20, hi: 25 },      // 적정 구간(범위 목표)
     *     target: 25                     // 또는 단일 목표(범위가 없을 때)
     *   })
     *
     * `points` 는 **오래된 것 → 최신 순**이고 자리마다 하루(또는 한 구간)를
     * 가리킨다. `avg` 가 `null`(또는 없음)인 자리는 **결측**이다 — 그 자리는
     * 이어 그리지 않는다(선을 그으면 없는 값을 지어낸 것으로 읽힌다). 결측
     * 앞뒤로 값이 있어도 서로 잇지 않고, 끊어진 조각(run)마다 띠·선을 따로
     * 그린다 — x 위치는 항상 **전체 점 수 기준**이라 결측이 있어도 날짜
     * 간격이 어긋나지 않는다.
     *
     * `min`/`max` 가 있으면 그 구간의 **범위 띠**(트랙과 같은 중립색)를
     * 함께 그린다 — 평균 하나보다 그날의 변동폭이 함께 보이는 편이 낫다.
     * 없으면(둘 다 `avg` 로 접힌다) 선만 그려진다.
     *
     * `band`(범위) 와 `target`(단일 값)은 **있는 쪽 하나만** 그린다 —
     * `band` 가 우선이다. 관측 범위 밖의 목표도 세로 범위 계산에 넣으므로
     * (아래) 목표를 벗어난 기간이 통째로도 그림이 안 잘린다.
     *
     * ⚠ **세로축에 숫자를 붙이지 않는다**(스파크와 같은 이유) — 실제
     *   값·목표는 머리줄(`valueText`)이 말하고, 그림은 "그 값이 목표 대비
     *   어디 있었나" 라는 **모양**만 말한다.
     */
    function trend(o) {
        o = o || {};
        var pts = Array.isArray(o.points) ? o.points : [];
        var n = pts.length;
        var html = '<div class="' +
                   cls('aot-viz aot-viz--trend', { stale: o.stale,
                                                   className: o.className }) +
                   '">';
        html += headHtml(o.label, o.valueText != null ? o.valueText : o.value,
                         o.valueSub);

        // ── 세로 범위 ────────────────────────────────────────────────────
        // 관측값뿐 아니라 목표·밴드도 범위 안에 들어와야 한다 — 안 그러면
        // 목표를 계속 못 채운 기간에서 목표선 자체가 그림 밖으로 사라진다.
        var lo = Infinity, hi = -Infinity, i;
        for (i = 0; i < n; i++) {
            var p = pts[i] || {};
            if (isNum(p.min)) { lo = Math.min(lo, p.min); hi = Math.max(hi, p.min); }
            if (isNum(p.max)) { lo = Math.min(lo, p.max); hi = Math.max(hi, p.max); }
            if (isNum(p.avg)) { lo = Math.min(lo, p.avg); hi = Math.max(hi, p.avg); }
        }
        var band = o.band;
        if (band) {
            if (isNum(band.lo)) { lo = Math.min(lo, band.lo); hi = Math.max(hi, band.lo); }
            if (isNum(band.hi)) { lo = Math.min(lo, band.hi); hi = Math.max(hi, band.hi); }
        }
        if (isNum(o.target)) { lo = Math.min(lo, o.target); hi = Math.max(hi, o.target); }

        // 그릴 값이 없다 — 빈 칸이 "아직 모른다" 를 정직하게 말한다(스파크와
        // 같은 규칙). 점이 하나뿐이면 방향도 범위도 말할 수 없다.
        if (!isFinite(lo) || !isFinite(hi) || n < 2) {
            return html + '</div>';
        }
        var span = (hi - lo) || 1;         // 평평한 구간도 그린다(가운데 선)
        // viewBox 높이 24, 위아래 3 여백 — spark 와 같은 수치라 나란히 놓여도
        // 리듬이 갈리지 않는다.
        function y(v) { return 21 - ((v - lo) / span) * 18; }
        function x(idx) { return (idx / (n - 1)) * 100; }

        var svg = '';
        // band 가 우선이다 — 둘 다 오면 범위 쪽이 더 많은 것을 말한다.
        if (band && (isNum(band.lo) || isNum(band.hi))) {
            var bLo = isNum(band.lo) ? band.lo : lo;
            var bHi = isNum(band.hi) ? band.hi : hi;
            var yTop = y(Math.max(bLo, bHi)), yBot = y(Math.min(bLo, bHi));
            svg += '<rect class="aot-viz-trend-band" x="0" y="' +
                   yTop.toFixed(2) + '" width="100" height="' +
                   Math.max(0, yBot - yTop).toFixed(2) + '"/>';
        } else if (isNum(o.target)) {
            var yt = y(o.target);
            svg += '<line class="aot-viz-trend-target" x1="0" x2="100" y1="' +
                   yt.toFixed(2) + '" y2="' + yt.toFixed(2) + '"/>';
        }

        // ── 결측으로 갈라진 조각(run)마다 띠·선을 따로 그린다 ────────────
        var run = [];
        function flushRun() {
            if (run.length < 2) { run = []; return; }
            var top = [], bottom = [], line = [], j, k;
            for (j = 0; j < run.length; j++) {
                var idx = run[j], pt = pts[idx] || {};
                var hiV = isNum(pt.max) ? pt.max : pt.avg;
                top.push(x(idx).toFixed(2) + ',' + y(hiV).toFixed(2));
                line.push(x(idx).toFixed(2) + ',' + y(pt.avg).toFixed(2));
            }
            for (k = run.length - 1; k >= 0; k--) {
                var idx2 = run[k], pt2 = pts[idx2] || {};
                var loV = isNum(pt2.min) ? pt2.min : pt2.avg;
                bottom.push(x(idx2).toFixed(2) + ',' + y(loV).toFixed(2));
            }
            svg += '<polygon class="aot-viz-trend-ribbon" points="' +
                   top.join(' ') + ' ' + bottom.join(' ') + '"/>';
            svg += '<polyline class="aot-viz-trend-line" points="' +
                   line.join(' ') + '"/>';
            run = [];
        }
        for (i = 0; i < n; i++) {
            if (isNum((pts[i] || {}).avg)) run.push(i); else flushRun();
        }
        flushRun();

        html += '<svg class="aot-viz-trend" viewBox="0 0 100 24" ' +
                'preserveAspectRatio="none" aria-hidden="true">' + svg + '</svg>';
        return html + '</div>';
    }

    /* 여러 줄을 한 묶음으로. 사이 여백을 각 호출부가 인라인 style 로 넣지
       않게 하려는 것이 전부다. */
    function group(rows) {
        return '<div class="aot-viz-group">' +
               (Array.isArray(rows) ? rows.join('') : String(rows || '')) +
               '</div>';
    }

    /* **끝 라벨을 감출지는 글자 폭이 정한다.** `scaleHtml` 의 12%/88% 는
       그릴 때 위치만 보고 내리는 짐작이라, 기준이 한가운데에서 조금 비켜난
       정도(예: 18%)면 감추지 않는데 글자가 길면 그래도 부딪힌다 — 기준 라벨의
       불투명 바탕이 축 라벨을 반만 덮어 "2026/0[오늘]" 처럼 잘린 채 읽혔다.

       그래서 붙인 뒤에 실제로 잰다. 기준과 겹치는 축 라벨만 감춘다 — 축의
       끝은 트랙이 이미 보여 주지만 기준은 이 라벨 말고 적을 자리가 없다.
       레이아웃이 잡힌 뒤(모달이 화면에 붙은 뒤) 불러야 한다. */
    function settle(root) {
        var scope = root || (global.document && global.document.body);
        if (!scope || !scope.querySelectorAll) return;
        var scales = scope.querySelectorAll('.aot-viz-scale--anchored');
        for (var i = 0; i < scales.length; i++) {
            var el = scales[i];
            var a  = el.querySelector('.aot-viz-scale-anchor');
            if (!a) continue;
            var ar = a.getBoundingClientRect();
            if (!ar.width) continue;   // 아직 그려지지 않았다
            for (var j = 0; j < el.children.length; j++) {
                var kid = el.children[j];
                if (kid === a) continue;
                kid.style.visibility = '';
                var kr = kid.getBoundingClientRect();
                if (kr.width && kr.right > ar.left - 4 && kr.left < ar.right + 4) {
                    kid.style.visibility = 'hidden';
                }
            }
        }
    }

    /* ── 범위 도표 ───────────────────────────────────────────────────────
     * **밴드 바를 세로로 돌려 기간마다 하나씩** 세운 것이다. 그것뿐이다.
     *
     *   .aot-viz-track  회색 필   축 전체 범위
     *   .aot-viz-ok     초록      목표대
     *   .aot-viz-now    어두운 선 그 기간의 값
     *
     * 값이 '크기' 인 계열(DLI 하루 적산·장치 가동시간)은 밴드 바가 아니라
     * **불릿**을 돌린다 — 트랙 + 채운 양(`.aot-viz-fill`, 바닥에서 올라온다).
     *
     * ⚠ **여기서 새로 만드는 것은 없다.** 색도 라운드도 클래스가 이미 갖고
     *   있다 — 돌리는 것은 좌표뿐이다(가로 → 세로). 이 자리에서 세 번
     *   어겼다: 투명도(`45%`·`55%`·`18%`)를 만들었고, 구간(초록)을 마커
     *   색으로 칠했고, 라운드를 없앴다. 전부 되돌렸다.
     *
     * ⚠ **눈금 글자는 만들지 않는다**(이 파일의 규약). 서버가
     *   `plot_journal.value_scale()` 로 축과 눈금 문자열을 함께 보낸다.
     *
     * ⚠ **기간이 하나면 이 그림을 쓰지 않는다** — 그 자리는 밴드 바 자체가
     *   맞다(가로 한 줄). 부르는 쪽이 고른다.
     *
     * **그 기간의 최저~최고를 그린다**(`min`·`max`가 오면). 평균 하나만
     * 찍던 때는 "그날 얼마나 튀었나" 를 짚어야만 알 수 있었다 — 그런데
     * 하루 평균은 낮과 밤을 섞은 값이라, 34도까지 오른 날과 종일 25도인
     * 날이 같은 자리에 선다. 진폭이 곧 그 줄이 답해야 할 것이다.
     *
     * ⚠ 진폭을 그리면 **평균 마커는 그리지 않는다.** 셋(최저·평균·최고)을
     *   한 칸에 세우면 칸 폭이 38px 인 화면에서 무엇이 기준인지 모양이
     *   말해 주지 못한다 — 한계선 셋을 세웠다가 되돌린 것과 같은 이유다
     *   (aot-dataviz.css `.aot-viz-limit` 주석). 값은 풍선이 말한다.
     *
     *   AoTViz.range({
     *     label: '온도', valueText: '21.0 °C',
     *     scale: {lo: 10, hi: 40, ticks: [{v: 10, text: '10'}, …]},
     *     targets: [{v: 25, text: '주간 25'}, {v: 12, text: '야간 12'}],
     *     points: [{label: '08-26', min: 17.4, max: 29.8, avg: 21.0}, …]
     *   })
     */
    function range(o) {
        o = o || {};
        var pts = Array.isArray(o.points) ? o.points : [];
        var sc = o.scale || {};
        var lo = sc.lo, hi = sc.hi;
        /* 막대 굵기는 **밀도가 정한다.** 8px 로 못박아 두면 기간이 51 개인
           문서에서 트랙이 칸보다 굵어 서로 붙어 한 덩어리로 뭉갠다(실측).
           칸 수로 단을 나눈다 — 이 빌더는 문자열만 만들어 돌려주므로(지도
           팝업이 이어 붙이는 방식) 폭을 재서 정할 수 없다. */
        var barW = pts.length <= 24 ? 8 : (pts.length <= 60 ? 4 : 2);
        var html = '<div class="' +
                   cls('aot-viz aot-viz--range', { stale: o.stale,
                                                   className: o.className }) +
                   '" style="--aot-viz-range-bar:' + barW + 'px">';
        html += headHtml(o.label, o.valueText != null ? o.valueText : o.value,
                         o.valueSub);
        // 그릴 축이 없다 — 빈 칸이 "아직 모른다" 를 정직하게 말한다(밴드 바와
        // 같은 규칙).
        if (!isNum(lo) || !isNum(hi) || hi === lo || !pts.length) {
            return html + '</div>';
        }
        var i, p;
        // '크기' 인가(불릿을 돌린다) '값' 인가(밴드 바를 돌린다).
        var bars = o.bars == null ? false : o.bars;

        // 아래에서부터의 거리(%). 세로로 돌렸으므로 큰 값이 위다.
        function bottom(v) {
            return pct(v, lo, hi);
        }

        // 목표대 — 값이 하나면 얇은 띠, 주간·야간처럼 둘이면 그 사이.
        var tv = [];
        (o.targets || []).forEach(function (t) {
            if (t && isNum(t.v)) tv.push(t.v);
        });
        var okLo = tv.length ? bottom(Math.min.apply(null, tv)) : null;
        var okHi = tv.length ? bottom(Math.max.apply(null, tv)) : null;
        var okTitle = (o.targets || []).map(function (t) { return t.text; })
                        .filter(Boolean).join(' · ');
        /* 가운데 눈금 하나. 양 끝만 적으면 막대가 어느 정도 규모인지 가늠할
           수 없다(실사용 지적 2026-09-04). **눈금표에서 고른다** — 축의
           산술 중간(예: 22.5)이 아니라 서버가 만든 눈금 중 가운데에 가장
           가까운 것이라야 사람이 읽는 숫자가 된다. 격자로 여러 줄을 깔지
           않는 이유는 같은 자리에서 이미 "너무 산만하다" 는 지적을 받았기
           때문이다. */
        var ticks = Array.isArray(sc.ticks) ? sc.ticks : [];
        var mid = null;
        if (ticks.length > 2) {
            var want = (lo + hi) / 2, best = Infinity;
            for (i = 1; i < ticks.length - 1; i++) {
                var d = Math.abs(ticks[i].v - want);
                if (d < best) { best = d; mid = ticks[i]; }
            }
        }
        var midPos = mid ? bottom(mid.v) : null;

        /* 목표를 그리는 방식은 **범위형과 누적형이 다르다.**
         *
         *   범위형(밴드): 목표는 "이 사이에 있어라" 는 **면**이다(.aot-viz-ok).
         *   누적형(막대): 목표는 "여기까지 쌓아라" 는 **지점**이다.
         *
         * 누적형에 면을 쓰면 한 트랙 안에서 같은 초록이 '목표대' 와 '쌓인 양'
         * 두 뜻으로 서고, 어느 초록이 무엇인지 모양이 말해 주지 못한다. 그래서
         * 가로 도표의 불릿과 **같은 어휘**(목표 = 깃발 마커)로 그린다. */
        /* 목표는 **선**이다 — 누적형이든 범위형이든 같다(밴드 바와 같은 규칙).
         * 초록 면으로 그리던 때는 한 트랙 안에서 초록이 '목표대' 와 '실측'
         * 두 뜻으로 섰고, 도표를 가로지르는 긴 선으로도 그려 봤지만 "시선이
         * 너무 끌린다" 는 지적을 받았다(2026-09-04). 지금은 트랙 폭만큼의
         * 짧은 가로선이고 맨 위에 선다(CSS z-index) — 초록이 트랙 두께를
         * 꽉 채워도 가려지지 않는다.
         *
         * 열마다 반복해 그린다. 자기 열 안에서만 서므로 도표 전체를 가르는
         * 규칙선처럼 보이지 않는다. */
        var goalHtml = '';
        tv.forEach(function (v) {
            var gb = bottom(v);
            if (gb === null) return;
            goalHtml += '<div class="aot-viz-target" style="--aot-viz-pos:' +
                        gb.toFixed(2) + '"' +
                        (okTitle ? ' title="' + esc(okTitle) + '"' : '') +
                        '></div>';
        });

        var cols = '';
        for (i = 0; i < pts.length; i++) {
            p = pts[i] || {};
            // **마크업도 밴드 바 그대로다** — 트랙 안에 구간과 마커가 든다.
            // 형제로 빼면 `border-radius: inherit`(구간이 트랙의 라운드를
            // 물려받는 규칙)이 끊긴다.
            var col = '';
            var b = bottom(p.avg);
            var spLo = bottom(p.min), spHi = bottom(p.max);
            if (b !== null || (spLo !== null && spHi !== null)) {
                if (bars) {
                    // 채운 양 — 바닥에서 올라온다. **0 이면 아예 그리지
                    // 않는다**: 최소 높이로 남긴 조각이 "조금 돌았다" 로
                    // 읽혀 꺼진 장치가 켜진 것처럼 보였다(오랜 규칙).
                    if (b > 0) {
                        col += '<div class="aot-viz-fill" style="height:' +
                               b.toFixed(2) + '%"></div>';
                    }
                } else if (spLo !== null && spHi !== null) {
                    // 그 기간의 진폭 — 최저에서 최고까지. 면이라 캡 보정을
                    // 하지 않는다(.aot-viz-ok 와 같은 규칙). 폭이 0 이어도
                    // 그린다 — 최소 두께는 CSS 가 준다(값이 하나뿐인 기간).
                    col += '<div class="aot-viz-span" style="bottom:' +
                           spLo.toFixed(2) + '%;height:' +
                           (spHi - spLo).toFixed(2) + '%"></div>';
                } else {
                    // 진폭을 모르거나(최저·최고 없음) 폭이 0 이면(값이 하나뿐인
                    // 기간) **아는 만큼만** 그린다 — 최소 높이를 줘서 진폭이
                    // 있는 것처럼 보이게 하지 않는다.
                    //
                    // 위치는 밴드 바와 **같은 방식**으로 넘긴다 — 트랙의
                    // 둥근 캡만큼 안쪽에 매핑하는 보정이 CSS 에 있고,
                    // 캡 크기는 트랙 굵기에서 파생된다.
                    var at = (b !== null) ? b : spLo;
                    col += '<div class="aot-viz-now" style="--aot-viz-pos:' +
                           at.toFixed(2) + '"></div>';
                }
            }
            // 누적형의 목표는 **쌓인 막대 위**에 얹는다 — 먼저 깔면 막대가
            // 목표를 넘었을 때 그 위를 덮어 "넘었는지" 를 볼 수 없다.
            col += goalHtml;
            // ⚠ 네이티브 `title` 을 쓰지 않는다 — **터치에서는 뜨지 않고**
            //   데스크톱에서도 1 초 넘게 걸린다. 값을 확인하려고 짚는
            //   동작에는 맞지 않는다. 문구는 부르는 쪽이 `tip` 으로 준다
            //   (이 파일은 문구를 만들지 않는다).
            cols += '<div class="aot-viz-col"' +
                    (p.tip ? ' data-tip="' + esc(p.tip) + '"' : '') +
                    '><div class="aot-viz-track">' + col + '</div></div>';
        }

        // 세로 눈금은 **양 끝 두 글자 + 가운데 하나**다(밴드 바의 `scale` 과
        // 같은 어휘에 가이드 한 줄만 더한다).
        var vscale = '';
        if (ticks.length) {
            vscale = '<div class="aot-viz-vscale">' +
                     '<span>' + esc(ticks[ticks.length - 1].text) + '</span>' +
                     (midPos !== null
                       ? '<span class="is-mid" style="bottom:' +
                         midPos.toFixed(2) + '%">' + esc(mid.text) + '</span>'
                       : '') +
                     '<span>' + esc(ticks[0].text) + '</span></div>';
        }
        // 가이드는 막대 **뒤에** 온다(앞에 두면 값을 가로지른다).
        var guide = midPos !== null
          ? '<i class="aot-viz-guide" style="bottom:' + midPos.toFixed(2) + '%"></i>'
          : '';
        // 값 풍선은 **그리는 자리 안**에 둔다. 도표 위(바깥)에 띄우면 바로
        // 위 도표의 제목 옆에 떠서 어느 그래프의 값인지 헷갈린다(실측).
        // 붙인 뒤 `AoTViz.tips(root)` 가 배선한다.
        html += '<div class="aot-viz-plot">' + vscale + guide +
                '<div class="aot-viz-cols">' + cols + '</div>' +
                '<div class="aot-viz-tip" hidden></div></div>';

        // 가로 눈금 — 처음·가운데·끝만. 전부 적으면 글자가 겹쳐 아무것도
        // 못 읽는다(기간이 65 개인 문서가 실제로 있다).
        var first = pts[0] && pts[0].label;
        var last = pts[pts.length - 1] && pts[pts.length - 1].label;
        var mid = pts.length > 2 ? pts[Math.floor(pts.length / 2)].label : null;
        if (first || last) {
            html += '<div class="aot-viz-scale aot-viz-xaxis">' +
                    '<span>' + esc(first || '') + '</span>' +
                    (pts.length > 2 ? '<span>' + esc(mid || '') + '</span>' : '') +
                    '<span>' + esc(last || '') + '</span></div>';
        }
        return html + '</div>';
    }

    /* ── 값 풍선 배선 ────────────────────────────────────────────────────
     * 붙인 뒤 한 번 부른다: `AoTViz.tips(mountElement)`.
     *
     * ⚠ **포인터 이벤트 하나로 마우스·터치·펜을 함께 받는다.** mouse/touch
     *   를 따로 걸면 터치 기기에서 둘 다 발화해 풍선이 두 번 뜬다.
     *
     * 문구는 만들지 않는다 — 칸의 `data-tip` 을 그대로 보인다(이 파일의 규약).
     */
    /* 열려 있는 값 풍선을 닫는 문서 단위 배선. **한 번만** 건다 —
     * 예전에는 도표마다 `document` 에 걸어서, 일지 한 장(범위 도표 19개)을
     * 열면 같은 일을 하는 리스너가 19개 쌓였다. */
    var _tipCharts = [];
    var _tipDismissBound = false;

    function _bindTipDismiss() {
        if (_tipDismissBound || !global.document) return;
        _tipDismissBound = true;
        global.document.addEventListener('pointerdown', function (ev) {
            for (var i = 0; i < _tipCharts.length; i++) {
                var c = _tipCharts[i];
                if (c.contains(ev.target)) continue;
                var t = c.querySelector('.aot-viz-tip');
                if (t) t.hidden = true;
            }
        });
    }

    function tips(root) {
        var scope = root || (global.document && global.document.body);
        if (!scope || !scope.querySelectorAll) return;
        var charts = scope.querySelectorAll('.aot-viz--range');
        for (var i = 0; i < charts.length; i++) bindOne(charts[i]);

        function bindOne(chart) {
            // 두 번 걸지 않는다 — 다시 그리지 않고 `tips()` 만 다시 부르는
            // 호출부가 있으면 핸들러가 쌓인다.
            if (chart.getAttribute('data-tips') === '1') return;
            chart.setAttribute('data-tips', '1');
            var tip = chart.querySelector('.aot-viz-tip');
            if (!tip) return;

            function hide() { tip.hidden = true; }

            function show(col) {
                var text = col.getAttribute('data-tip');
                if (!text) { hide(); return; }
                tip.textContent = text;
                tip.hidden = false;
                // 칸 가운데에 놓되 **도표 밖으로 나가지 않게** 자른다 —
                // 첫 칸·끝 칸에서 글자가 카드를 넘어가면 잘려 읽히지 않는다.
                var cr = col.getBoundingClientRect();
                var pr = tip.parentNode.getBoundingClientRect();
                var half = tip.offsetWidth / 2;
                var x = cr.left + cr.width / 2 - pr.left;
                tip.style.left =
                    Math.max(half, Math.min(pr.width - half, x)) + 'px';
            }

            function at(ev) {
                var el = ev.target;
                while (el && el !== chart && !(el.classList &&
                       el.classList.contains('aot-viz-col'))) {
                    el = el.parentNode;
                }
                return (el && el !== chart) ? el : null;
            }

            /* 마우스는 **따라다니고**, 터치는 **머문다.**
             *
             * 손가락은 값 위에 머무를 수 없다 — 짚은 순간 그 자리를 가리고,
             * 떼면 볼 것이 사라진다. 그래서 터치에서는 다음에 짚을 때까지
             * 그대로 둔다(사용자 지적: *"터치를 떼면 바로 사라져서 불편함"*).
             *
             * ⚠ **`pointerleave` 로 닫는 것은 마우스뿐이다.** 터치도 손을 떼면
             *   그 이벤트가 온다(포인터가 사라지므로) — 구분하지 않으면 떼는
             *   순간 닫힌다. 이것이 그 증상의 원인이었다. */
            function isMouse(ev) {
                return !ev.pointerType || ev.pointerType === 'mouse';
            }

            chart.addEventListener('pointermove', function (ev) {
                var col = at(ev);
                // 짚은 채 움직이면 칸을 훑어 값을 읽는다(마우스·터치 공용).
                if (col) { show(col); return; }
                // 칸 밖으로 나가면 마우스만 닫는다 — 터치는 머문다.
                if (isMouse(ev)) hide();
            });
            chart.addEventListener('pointerdown', function (ev) {
                var col = at(ev);
                if (col) show(col);
            });
            chart.addEventListener('pointerleave', function (ev) {
                if (isMouse(ev)) hide();
            });
            _tipCharts.push(chart);
            _bindTipDismiss();
        }
    }

    global.AoTViz = {
        band: band,
        settle: settle,
        value: value,
        spark: spark,
        trend: trend,
        range: range,
        tips: tips,
        bullet: bullet,
        timeline: timeline,
        group: group,
        pct: pct,
        isOutside: isOutside
    };
})(typeof window !== 'undefined' ? window : this);
