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
            html += '<div class="aot-viz-now" style="--aot-viz-pos:' +
                    p.toFixed(2) + '"></div>';
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
                          : ((os !== null && oe !== null) ? (os + oe) / 2 : null));
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
     *
     * segments[].name 을 주면 **트랙 위**에 구간 이름 줄이 생긴다(구간 폭에
     * 맞춰 늘어선다). 하나도 없으면 그 줄을 만들지 않는다.
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
        html += segNamesHtml(segs, total);
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
            html += '<div class="aot-viz-now" style="--aot-viz-pos:' +
                    p.toFixed(2) + '"></div>';
        }
        html += '</div>';
        // 기간 바의 기준은 오늘이다.
        html += scaleHtml(o.scale, p);
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

    global.AoTViz = {
        band: band,
        settle: settle,
        value: value,
        spark: spark,
        bullet: bullet,
        timeline: timeline,
        group: group,
        pct: pct,
        isOutside: isOutside
    };
})(typeof window !== 'undefined' ? window : this);
