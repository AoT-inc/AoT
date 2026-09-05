/* AoT_plot 위젯 — 구획 하나의 종합 상태.
 *
 * ## 지도 위젯과 무엇이 다른가
 *
 * 지도 위젯은 **다용도**다("어디에 무엇이 있나"). 구획은 눌러야 나오고, 팝업은
 * 하나씩 열렸다 닫힌다. 이 위젯은 **목적 기반**이다 — 재배·육종처럼 목적물
 * 하나를 계속 들여다보는 일에서, 그 구획의 지표를 대시보드에 상주시킨다.
 *
 * 그래서 **장치 제어는 담지 않는다.** 액추에이터·릴레이는 지도·시설 위젯의
 * 일이고, 여기 있는 것은 목적물의 상태와 그 일정뿐이다. 둘이 겹치면 같은 것을
 * 두 위젯이 다르게 말하게 된다.
 *
 * ## 네 묶음
 *
 *   1) 어디까지 왔나   기간 바(단계 구간 + 오늘 + 사건 표식)
 *   2) 목표 대비 지금  단계 목표·한계에 실측을 댄 밴드
 *   3) 추세           2)의 축 없는 줄을 스파크라인으로 채운다
 *   4) 누적           적산온도(GDD) — 이 단계의 전환 임계까지 얼마나 왔나
 *
 * ## 무엇을 다시 적지 않는가
 *
 * [환경] 블록은 **지도 팝업의 것을 그대로 부른다**(`AoTMapPopup.buildEnvNowHtml`).
 * 여기서 다시 짜면 안 되는 이유가 분명하다: 온도·습도는 목표가 아니라 **한계**
 * 이고(프로그램이 목표로 정한 것은 vpd·co2·dli 뿐이다), 그 구분을 화면이 다시
 * 조립하면 "아무도 정한 적 없는 숫자가 목표로 둔갑" 한다 — 그 실패가 실제로
 * 있었고 지금 그 판단은 팝업 빌더 한 곳에 있다.
 *
 * 편집도 마찬가지다. 기본 정보는 `AoTPlotForm`, 단계(기간·지침·목표)는
 * `AoTPlotStages` — `/plots` 페이지와 **같은 물건**이라 두 화면을 따로 배울
 * 일이 없다.
 *
 * ## 평소에는 읽기 전용이다
 *
 * 본체의 네 묶음에서는 아무것도 바뀌지 않는다. 고치는 일은 [편집]을 눌러 연
 * 모달 안에서만 일어나고, 거기서도 [저장]을 눌러야 나간다. 단계 목표는 제어가
 * 읽는 값이라(`effective_stages → stage_of → control_targets`) 대시보드에서
 * 스치듯 바뀌면 안 된다.
 */
(function (root) {
    'use strict';

    if (root.AoTPlotWidget) return;

    var S = {};        // uid → { opts, plots, plot, contents, timer }

    function _t(k) {
        var fn = root._;
        return (typeof fn === 'function') ? fn(k) : k;
    }

    function _esc(x) {
        return String(x == null ? '' : x).replace(/[&<>"']/g, function (c) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
                      '"': '&quot;', "'": '&#39;' })[c];
        });
    }

    function _csrf() {
        var el = document.querySelector('meta[name="csrf-token"]');
        return el ? el.getAttribute('content') : '';
    }

    /** 이 위젯의 쓰기 경로 하나. `{status, data}` 로 풀어 준다 — 호출부마다
     *  실패 판정을 다시 적으면 어느 한 곳이 조용히 빠진다. 공용 단계 편집기
     *  (`AoTPlotStages.save`)에도 이것을 그대로 넘긴다. */
    function _api(method, url, body) {
        return fetch(url, {
            method: method, credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json',
                       'X-Requested-With': 'XMLHttpRequest',
                       'X-CSRFToken': _csrf() },
            body: body === undefined ? undefined : JSON.stringify(body)
        }).then(function (r) {
            return r.json().catch(function () { return {}; })
                .then(function (d) { return { status: r.status, data: d || {} }; });
        }).catch(function () { return { status: 0, data: {} }; });
    }

    /** 읽기는 공유 캐시를 지난다 — 같은 대시보드의 지도 위젯이 **같은 URL**로
     *  구획 목록을 받으므로, 둘이 거의 같은 순간에 뜨면 한 번으로 합쳐진다. */
    function _get(url) {
        if (root.AoTGeoData) {
            return root.AoTGeoData.get(url).then(function (r) {
                return r.ok ? r.json() : null;
            }).catch(function () { return null; });
        }
        return fetch(url, { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .catch(function () { return null; });
    }

    function _toast(msg, level) {
        if (root.showToast) root.showToast(msg, level || 'info');
    }

    function _el(uid, sel) {
        var host = document.getElementById('aot-plot-' + uid);
        return host ? host.querySelector(sel) : null;
    }

    /** 구획 선택 상자 — **id 로 찾는다.**
     *
     * layout 이 로드 때 `.aot-modern-select` 를 전부 bootstrap-select 로 바꾸고,
     * 그때 클래스가 감싸는 `<div>` 에도 복사된다. 클래스로 찾으면 그 껍데기가
     * 잡혀서 `innerHTML` 이 옵션을 글자로 쏟아 놓고 `value`·`change` 는 아무
     * 일도 하지 않는다 — 2026-08-28 실제 대시보드에서 그랬다. */
    function _pick(uid) {
        return document.getElementById('aot-plot-pick-' + uid);
    }

    // ── 목록 ─────────────────────────────────────────────────────────────
    //
    // 선택지는 **재배중 + 계획**이다(종료는 싣지 않는다). 이 위젯은 지금 기르는
    // 것을 지켜보는 자리이고, 지나간 작기를 되짚는 일은 `/plots` 의 몫이다 —
    // 여기 섞으면 고르는 목록이 해마다 길어지기만 한다.
    function loadPlots(uid) {
        var st = S[uid];
        return _get('/api/geo/plots?include_planned=1').then(function (res) {
            st.plots = (res && res.ok) ? (res.plots || []) : [];
            fillPicker(uid);
            // 고른 것이 없거나 사라졌으면 첫 번째로 — 빈 위젯은 무엇을 해야
            // 하는지 말해 주지 않는다. 저장은 하지 않는다(사람이 고른 적이 없다).
            var cur = st.opts.plotUuid;
            var alive = st.plots.some(function (p) { return p.unique_id === cur; });
            if (!alive) {
                cur = st.plots.length ? st.plots[0].unique_id : null;
                st.opts.plotUuid = cur;
                var sel = _pick(uid);
                if (sel && cur) { sel.value = cur; _syncPicker(sel); }
            }
            return cur;
        });
    }

    function fillPicker(uid) {
        var st = S[uid];
        var sel = _pick(uid);
        if (!sel) return;
        var cur = st.opts.plotUuid;
        var html = st.plots.map(function (p) {
            // 사람이 기억하는 말로 고른다 — 작물 · 품종 · 어디.
            var bits = [p.subject || p.name || '—'];
            if (p.variety) bits.push(p.variety);
            var where = [p.facility_name, p.bay_name, p.map_name].filter(Boolean);
            var label = bits.join(' · ') +
                        (where.length ? ' (' + where[0] + ')' : '');
            // 고른 것은 **마크업에 `selected` 로** 박는다. `sel.value = …` 로
            // 나중에 지정하면 bootstrap-select 가 새로 고칠 때 마크업만 보고
            // 첫 항목으로 되돌린다 — 값은 멀쩡한데 버튼에 이름이 안 뜬다.
            return '<option value="' + _esc(p.unique_id) + '"' +
                   (p.unique_id === cur ? ' selected' : '') + '>' +
                   _esc(label) + '</option>';
        }).join('');
        sel.innerHTML = html ||
            '<option value="">' + _esc(_t('Nothing recorded yet.')) + '</option>';
        if (st.opts.plotUuid) sel.value = st.opts.plotUuid;
        _syncPicker(sel);
    }

    /** bootstrap-select 가 걸려 있으면 다시 그리게 한다. 그 컴포넌트는 **초기화
     *  시점의 옵션**으로 목록을 만드는데, 이 목록은 그 뒤에 조회로 채워진다 —
     *  알려 주지 않으면 버튼에 옛 목록(또는 빈 목록)이 그대로 남는다.
     *  안 걸려 있으면 아무 일도 하지 않는다(모달 안의 select 가 그렇다). */
    function _syncPicker(sel) {
        if (!root.jQuery || !root.jQuery.fn || !root.jQuery.fn.selectpicker) return;
        var $s = root.jQuery(sel);
        if (!$s.data('selectpicker')) return;
        try { $s.selectpicker('refresh'); } catch (e) { /* 덤이다 */ }
    }

    /** 고른 구획을 위젯에 남긴다. 실패해도 화면은 그대로 간다 — 저장 권한
     *  (`edit_controllers`)이 없는 사람도 **보는 동안은** 바꿔 볼 수 있어야
     *  하고, 그 사람에게 저장 실패를 알릴 이유는 없다(고치려던 것이 아니다). */
    function persistPick(uid, uuid) {
        persistOptions(uid, { plot_uuid: uuid });
    }

    /** 위젯에 옵션 몇 개를 남긴다. **부분 저장이다** — 서버가 기존 값 위에
     *  덮는다(`execute_at_modification` 이 "선언하지 않은 값을 지우지 않는다").
     *  그래서 단위를 저장해도 고른 구획이 살아남는다. */
    function persistOptions(uid, options) {
        _api('POST', '/save_widget_custom_options',
             { widget_id: uid, options: options });
    }

    // ── 조회 ─────────────────────────────────────────────────────────────
    function refresh(uid) {
        var st = S[uid];
        var uuid = st.opts.plotUuid;
        if (!uuid) { render(uid); return Promise.resolve(); }

        // 상세와 인벤토리를 함께 받는다. 상세에는 일정·단계·이력이, 인벤토리에는
        // 실측·목표·한계가 있다 — 한 화면이 둘 다 필요하고 둘은 다른 캐시를 탄다.
        //
        // cache:'no-store' — 저장 직후 다시 부르는 경로가 있다(모달 [저장]).
        // 브라우저 휴리스틱 캐시가 옛 사본을 주면 "저장했는데 화면이 그대로" 가 된다.
        var needEnv = st.opts.show.env || st.opts.show.trend;
        var jobs = [
            fetch('/api/geo/plot/' + encodeURIComponent(uuid),
                  { cache: 'no-store', credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .catch(function () { return null; }),
            needEnv
                ? fetch('/api/geo/plot/' + encodeURIComponent(uuid) + '/contents',
                        { cache: 'no-store', credentials: 'same-origin' })
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .catch(function () { return null; })
                : Promise.resolve(null)
        ];
        return Promise.all(jobs).then(function (out) {
            // 응답이 도는 사이에 다른 구획으로 옮겼으면 버린다 — 늦게 온 것이
            // 새로 고른 구획의 화면을 덮어쓰면 이름과 값이 어긋난다.
            if (S[uid] !== st || st.opts.plotUuid !== uuid) return;
            var det = out[0];
            st.plot = (det && det.ok) ? det.plot : null;
            st.contents = (out[1] && out[1].ok) ? out[1] : null;
            render(uid);
            // 오늘의 폭도 함께 늙는다. **버리지 않고 다시 받는다** — 버리면
            // [일] 을 펴 둔 사람의 도표가 새로고침마다 사라졌다가 다시 눌러야
            // 돌아온다(같은 창을 쓰기 때문이다).
            if (needEnv) loadTodayWindow(uid, true);
        });
    }

    /** 나열 줄의 한 쌍 — **칩 하나**(`.aot-tag`, 앱 공용 칩).
     *
     * 한 행에 나열하되 글자만 흘려 두지 않는다. 칩이 없으면 쌍의 경계가
     * 간격뿐이라 밋밋하게 이어져 읽히고, 실제로 그렇게 만들었다가 지적받았다.
     * 칩 배경(`--aot-color-brand-accent`)은 라이트·다크 모두 정의된 중립
     * 면이라 색을 새로 들이지 않는다.
     *
     * 칩 **안**에서 이름과 값을 다른 무게로 적는다(이름 보조색, 값 본문색
     * 반굵게) — 무게 차이가 없으면 어디까지가 이름인지 매번 끊어 읽어야 한다.
     * `weak` 는 곡선을 따르는 항목이다: 값 자리에 곡선 이름이 오므로 숫자와
     * 같은 무게로 세우면 이름이 값으로 읽힌다. */
    function _pair(name, value, weak, key) {
        return '<span class="aot-tag"' +
               // 값이 늦게 오는 것(추세 방향)을 이 칩에 이어 붙일 수 있어야 한다.
               (key ? ' data-viz-key="' + _esc(key) + '"' : '') +
               // 칩은 카드보다 넓어질 수 없어 끝이 잘릴 수 있다(CSS
               // `.aot-plotw-list .aot-tag`) — 전문은 `title` 이 진다.
               ' title="' + _esc(name + ' ' + value) + '"' +
               '><i>' + _esc(name) + '</i>' +
               (weak ? '<em>' + _esc(value) + '</em>'
                     : '<b>' + _esc(value) + '</b>') + '</span>';
    }

    // ── 1) 어디까지 왔나 ────────────────────────────────────────────────
    //
    // **지도 구획 모달과 같은 그림**을 쓴다(`AoTMapPopup.buildPlotProgressHtml`).
    //
    // 예전에는 이 위젯만 자기 축을 조립했고, 그러느라 공용 빌더에
    // `compact` 라는 **이 위젯 전용 모양**까지 만들었다(단계 이름줄과 눈금줄을
    // 빼고 6px 트랙만 남긴 것). 좁은 카드에서 줄을 아끼려던 것인데, 결과는
    // 같은 구획의 같은 축이 지도에서는 이름과 날짜를 달고 대시보드에서는
    // 맨 막대로 나오는 것이었다(2026-09-05 지적). 위젯 높이를 늘린 뒤로는
    // 자리를 아낄 이유도 없다.
    //
    // 다른 것은 **고를 수 있다는 것 하나**다(`pickable`) — 지도 모달은 읽기
    // 전용이고, 여기서는 축이 곧 "어느 단계를 볼까" 를 고르는 메뉴다.
    // 사건 표식(지나간 전환)도 이 위젯만 싣는다.
    function blockProgress(uid, p) {
        var P = root.AoTMapPopup;
        var tl = p.timeline;
        if (!P || !P.buildPlotProgressHtml) return '';

        // 사건은 **단계의 시작 경계**에 찍는다 — 축의 경계는 서버가 계획·승인을
        // 반영해 이미 잡아 둔 것이라, 화면이 날짜 산술을 따로 하면 두 값이 갈린다.
        var events = null;
        if (tl && (tl.stages || []).length) {
            var byKey = {};
            tl.stages.forEach(function (s) { byKey[s.key] = s; });
            events = (p.stage_history || []).filter(function (h) {
                return !h.undone && byKey[h.stage_key];
            }).map(function (h) {
                var s = byKey[h.stage_key];
                return { pct: s.from_pct,
                         label: (h.started_on || '') + ' ' + (s.name || '') };
            });
        }

        return P.buildPlotProgressHtml(p, {
            pickable: true, pickedKey: S[uid].picked, events: events
        }) + stageDetail(uid, p);
    }

    /** 단계의 내용 — 기본은 **현재 단계**다.
     *
     * 처음부터 보인다. 지금 무엇을 하는 시기인지가 이 카드의 본론인데, 그것을
     * 누르게 만들면 누르기 전까지 카드는 "며칠 됐다" 만 말한다.
     * 축에서 다른 구간을 누르면 그 단계로 바뀌고, 그때만 [지금 단계로]가 선다.
     *
     * **지침도 여기 있다.** 지침은 "이 단계에서 무엇을 하나" 라서 단계에 딸린
     * 글이다 — 따로 카드를 만들면 현재 단계의 지침이 두 곳에 나온다(실제로
     * 그랬다). 다른 단계를 고르면 그 단계의 지침으로 함께 바뀐다.
     */
    function stageDetail(uid, p) {
        var picked = S[uid].picked;
        var sched = p.stage_schedule || [];
        var cur = sched.filter(function (s) { return s.state === 'current'; })[0];
        var key = picked || (cur && cur.key) || (p.stage || {}).key;
        var row = sched.filter(function (s) { return s.key === key; })[0];
        if (!row) return '';
        var isCur = !!cur && row.key === cur.key;

        var bits = [];
        // 기간 — 마지막 단계는 길이가 없다("끝까지").
        bits.push(row.days != null
            ? _t('%(n)s days').replace('%(n)s', String(row.days))
            : _t('Open-ended'));
        if (row.starts_on) {
            bits.push(row.starts_on + (row.ends_on ? ' ~ ' + row.ends_on : ' ~'));
        }

        // 최소 높이도 같은 판단을 따른다 — 지침 상자를 안 내는 구획에서
        // 그 몫까지 예약하면 죽은 공간이 그대로 남는다(CSS `is-noguide`).
        var anyGuideNow = sched.some(function (x) { return !!x.guidance; });
        var html = '<div class="aot-plotw-stage' +
                   (anyGuideNow ? '' : ' is-noguide') + '">' +
                   '<div class="aot-plotw-stage-head">' +
                   // 현재 단계의 이름은 **축의 머리줄이 이미 말한다** — 여기서
                   // 또 적으면 같은 글자가 두 줄 연달아 선다. 다른 단계를
                   // 골랐을 때만 이름을 적는다(그때는 머리줄과 다르다).
                   (isCur ? '' : '<b>' + _esc(row.name || key) + '</b>') +
                   '<span>' + _esc(bits.join(' \u00b7 ')) + '</span>' +
                   // [지금 단계로]는 현재 단계에서 **감추되 자리는 남긴다**
                   // (`is-idle` → visibility:hidden). 예전에는 아예 안 그려서,
                   // 축을 눌러 다른 단계를 고르는 순간 이 버튼이 새로 생기며
                   // 머리줄이 밀렸다 — 그것이 "미세한 레이아웃 변화" 의 실체다.
                   // 이름을 함께 되살리지 않는 이유는 위 주석 그대로다(머리줄과
                   // 같은 글자가 두 줄 연달아 서는 쪽이 더 나쁘다).
                   '<button type="button" class="aot-plotw-stage-back' +
                   (isCur ? ' is-idle" tabindex="-1" aria-hidden="true"' : '"') +
                   '>' + _esc(_t('Back to now')) + '</button>' +
                   '</div>';

        // 목표 — **한 행에 나열한다.** 항목마다 줄을 잡으면 목표 넷에 카드가
        // 네 줄 커지는데, 여기서 필요한 것은 "무엇을 몇으로 잡았나" 를 훑는
        // 것뿐이다. 값이 있는 것만 낸다: 곡선이 걸린 항목은 숫자가 없으므로
        // 곡선 이름을 적는다(빈 칸으로 두면 아직 안 정한 것으로 읽힌다).
        var tg = (row.targets || []).map(function (t) {
            // 숫자에만 단위를 붙인다. 곡선이 걸린 항목은 값 자리에 **곡선
            // 이름**이 오는데 거기에 단위를 이으면 'vpd kPa' 처럼 값이 아닌
            // 것이 값처럼 읽힌다(2026-08-28 실측). 곡선 이름은 무게도 낮춰
            // 숫자와 구분한다 — 그 항목은 아직 숫자가 정해진 것이 아니다.
            if (t.value != null) {
                return _pair(t.label || t.key,
                             t.value + (t.unit ? ' ' + t.unit : ''));
            }
            if (t.method_name) {
                return _pair(t.label || t.key, t.method_name, true);
            }
            return '';
        }).filter(Boolean);
        if (tg.length) html += '<div class="aot-tag-list aot-plotw-list">' + tg.join('') + '</div>';

        // 지침 — **이 구획에 지침이 하나라도 있으면** 언제나 상자를 낸다
        // (그 단계가 비어 있어도).
        //
        // 단계마다 지침이 있고 없고, 길고 짧고가 다른데 그 차이가 카드 높이로
        // 새어 나가면 축을 한 번 누를 때마다 아래 카드가 밀린다. 상자가 높이를
        // 잠그고, 넘치는 글은 **상자 안에서만** 흐른다.
        //
        // ⚠ 예약은 **구획 단위**로 판단한다. 처음에는 무조건 냈는데, 어느
        //   단계에도 지침이 없는 구획에서는 그 두 줄이 통째로 죽은 공간이었다
        //   (2026-09-05 지적). 반대로 "그 단계에 있을 때만" 으로 하면 지침이
        //   있는 단계와 없는 단계를 오갈 때 카드가 두 줄씩 뛴다 — 고치려던
        //   그 흔들림이다. 그래서 **이 구획의 어느 단계든 지침을 가졌는가**로
        //   정한다: 가졌으면 전부 예약(흔들리지 않는다), 아니면 아무도 안
        //   낸다(빈 자리가 없다).
        //
        // `-webkit-line-clamp`(두 줄 자르기)는 뗐다 — 상자가 이미 높이를
        // 잠그므로 중복이고, 잘린 뒤를 읽을 길이 `title` 뿐이었다(폰에는
        // `title` 이 없다). 이제 스크롤로 전문을 읽는다.
        var anyGuide = sched.some(function (x) { return !!x.guidance; });
        if (anyGuide) {
            html += '<div class="aot-plotw-guidebox">' +
                    (row.guidance ? _esc(row.guidance) : '') + '</div>';
        }
        return html + '</div>';
    }

    // ── 2) 지금 어떤가 — **지도 구획 모달과 같은 카드** ────────────────
    //
    // 여기서 다시 짜지 않는다. `AoTMapPopup.buildEnvNowHtml` 을 그대로 부른다 —
    // 지도 위젯 구획 모달의 [현황] 환경 카드와 **같은 함수**라, 같은 구획을 두
    // 화면이 다르게 말할 수 없다.
    //
    // 예전에는 이 위젯만 자기 표현을 갖고 있었다(지표 하나만 게이지, 나머지는
    // 칩). 좁은 카드에서 줄을 아끼려던 것인데, 결과가 **"VPD 하나 + 칩 둘"**
    // 이라 정작 볼 것이 안 보였다(2026-09-05 지적). 지금은 모든 측정이 자기
    // 축을 갖고, DLI·적산온도도 함께 나온다 — 그 판정(무엇이 목표이고 무엇이
    // 한계인가, 광합성 지표가 쓸 만한가)이 전부 그 빌더 한 곳에 있다.
    //
    // 그래서 이 위젯에서 사라진 것: 게이지 지표 선택(`gauge`)과 방향 화살표
    // (`fillTrends`). 앞의 것은 **모든 줄이 축을 가지므로** 고를 것이 없어졌고,
    // 뒤의 것은 축 없는 줄을 스파크라인으로 채우는 공용 함수
    // (`fillEnvSparklines`)가 대신한다.

    /** 지금 볼 창 — **단위가 창을 정한다.**
     *
     * 7일 창에 주 버킷을 쓰면 점이 하나라 범위 도표가 성립하지 않는다
     * (`AoTViz.range` 규약: "기간이 하나면 이 그림을 쓰지 않는다"). 그래서
     * 단위를 고르는 것이 곧 창을 고르는 것이다 — 일이면 최근 7일, 주면 최근
     * 8주. 어느 쪽이든 점이 7~8개라 도표가 늘 성립한다.
     *
     * **축에서 단계를 고르면 그 단계가 창이 된다**(`picked`). 그때는 길이를
     * 여기서 정하지 않는다 — 서버가 일정에서 그 단계의 경계를 꺼내 쓰고
     * (`_stage_window`), 진행 중이면 오늘로 자른다. 화면이 날짜 산술을 다시
     * 하면 축의 구간과 그래프의 창이 갈린다.
     */
    var _ENV_WINDOW_DAYS = { day: 7, week: 56 };

    /* [오늘] 밴드가 그리는 **오늘의 최저~최고**가 나오는 창.
     *
     * 고른 단계와 무관하게 **언제나 최근 7일·일 단위**다 — [오늘] 줄의 숫자는
     * 지금 값이라(`plot.env.readings`), 지난 단계의 창에서 오늘을 찾으면 아무
     * 것도 안 나온다.
     *
     * 키가 `envQuery` 의 [일] 모드(단계를 안 고른 경우)와 **같다.** 일부러 그
     * 렇게 맞춘 것이다 — 같은 창을 두 번 묻지 않고, [일] 을 누르면 이미 받아
     * 둔 것이 즉시 뜬다. */
    function todayQuery() {
        return { key: 'recent:' + _ENV_WINDOW_DAYS.day + '|day',
                 qs: '?days=' + _ENV_WINDOW_DAYS.day + '&unit=day' };
    }

    function envQuery(uid) {
        var st = S[uid];
        var unit = st.envMode;                    // 'day' | 'week'
        if (st.picked) {
            return { key: 'stage:' + st.picked + '|' + unit,
                     qs: '?stage=' + encodeURIComponent(st.picked) +
                         '&unit=' + unit };
        }
        var days = _ENV_WINDOW_DAYS[unit] || 7;
        return { key: 'recent:' + days + '|' + unit,
                 qs: '?days=' + days + '&unit=' + unit };
    }

    // ── 2) 지금 어떤가 — **지도 구획 모달과 같은 카드** ────────────────
    //
    // 여기서 다시 짜지 않는다. `AoTMapPopup.buildEnvNowHtml` 을 그대로 부른다 —
    // 지도 위젯 구획 모달의 [현황] 환경 카드와 **같은 함수**라, 같은 구획을 두
    // 화면이 다르게 말할 수 없다.
    //
    // 다른 것은 **머리줄의 손잡이**뿐이다: 지도는 [오늘]↔[7일] 두 상태이고
    // 여기는 [오늘][일][주] 세 상태다(`rangeModes`). 위젯은 한 구획을 오래
    // 들여다보는 자리라 "지난 주와 견줘 지금이 어디인가" 만이 아니라 "이 단계
    // 동안 어땠나" 까지 묻게 된다.

    /** 환경 카드를 그 자리에 그린다. `render()` 가 만든 슬롯을 채운다.
     *
     * **본체를 다시 그리지 않는다.** 단위 손잡이는 이 카드만 바꾸므로, 여기서
     * `render()` 를 부르면 축에서 고른 단계가 함께 초기화된다.
     */
    function drawEnv(uid) {
        var st = S[uid];
        var slot = _el(uid, '[data-slot="envnow"]');
        var P = root.AoTMapPopup;
        if (!slot || !P || !P.buildEnvNowHtml) return;
        var c = st.contents;
        if (!c) return;
        var plot = c.plot || {};

        // 인자는 지도 구획 모달과 **같은 것을 같은 이름으로** 넘긴다
        // (`aot-map-widget-vector.js` 의 `_envArgs`). 하나라도 빠지면 이 위젯의
        // 카드만 다른 판정을 하게 된다.
        var opts = {
            // 감추는 항목은 **상위(시설·구역)의 설정을 물려받는다** — 서버가
            // 어느 상위인지 이미 골라 준다. 여기서 다시 고르면 규칙이 두 곳에
            // 생긴다. [설정] 손잡이는 두지 않는다(`configurable` 없음):
            // 저장이 상위에 있어 여기서 고치면 그 시설·구역을 보는 **다른
            // 사람의 화면**이 함께 바뀐다. 고치는 자리는 지도의 그 창이다.
            hidden: (plot.hidden_rows || {}).now,
            targets: plot.targets,
            // 한계(온도 주/야간 · 습도)는 목표와 다른 축이다.
            limits: plot.limits,
            // 목표가 곡선인 항목 — 숫자 대신 곡선 이름을 적는다.
            targetMethods: plot.target_methods,
            // 적산온도·광합성 지표 — 이 구획 자신 기준. 코디네이터 사이클 값
            // (`photo`)과는 다른 축이라 별도 키로 받는다(섞으면 안 된다).
            gdd: plot.gdd,
            dli: plot.dli,
            rangeModes: [{ key: 'day', label: _t('Daily'),
                           title: _t('Show the last 7 days') },
                         { key: 'week', label: _t('Weekly'),
                           title: _t('Show the last 8 weeks') }],
            rangeMode: st.envMode || '',
            weekExpanded: !!st.envMode,
            // 창이 "지난 7일" 이 아닐 수 있으므로(단계 기간·최근 8주) 빈 결과
            // 문구도 그에 맞게 — 기본 문구를 쓰면 화면이 거짓말을 한다.
            rangeEmptyText: _t('No data for this period.')
        };
        var q = envQuery(uid);
        var hit = st.envCache[q.key];
        if (st.envMode && hit !== undefined) {
            opts.week = hit;
            opts.weekToday = st.envEnd[q.key] || null;
        } else if (!st.envMode) {
            // ── [오늘] 도 계열이 필요하다 ────────────────────────────────
            //
            // 이 보기의 밴드 줄은 값 하나가 아니라 **오늘의 최저~최고 폭**을
            // 그린다(`_todaySpan`, aot-map-popup.js). 재료는 [일] 도표와 **같은
            // 버킷**이다 — 따로 계산하면 같은 하루를 두 보기가 다르게 말한다.
            //
            // 없으면 배경에서 받아 온다. 값은 `/contents` 에 이미 있어 즉시
            // 뜨고 폭만 한 박자 늦게 채워진다.
            var tq = todayQuery();
            var today = st.envCache[tq.key];
            if (today !== undefined) {
                opts.week = today;
                opts.weekToday = st.envEnd[tq.key] || null;
            } else {
                // 손잡이는 "받을 수 있다" 는 뜻으로 먼저 뜬다.
                opts.weekLazy = true;
                loadTodayWindow(uid);
            }
        } else opts.weekLazy = true;

        slot.innerHTML = P.buildEnvNowHtml(plot.env, opts);

        // 값 풍선은 붙인 **뒤에** 배선한다.
        if (root.AoTViz && root.AoTViz.tips) {
            try { root.AoTViz.tips(slot); } catch (e) { /* 덤이다 */ }
        }
        // 축이 없는 줄(CO2·토양수분·이슬점…)은 추세로 답한다.
        if (st.opts.show.trend && P.fillEnvSparklines) {
            P.fillEnvSparklines(slot, c.sensors, (plot.env || {}).readings);
        }
        wireRangeModes(uid, slot);
    }

    /** [오늘][일][주] — 누른 단위의 창을 받아 온다.
     *
     * 조회는 **누를 때만** 한다. 안 눌러도 매번 0.9~1.5초짜리 InfluxDB 조회가
     * 도는 것을 없앤 판단이고(2026-09-05), 위젯은 5분마다 다시 그려지므로
     * 그것을 미리 받아 두면 그 주기가 그대로 조회 주기가 된다.
     *
     * 받은 결과는 **창마다** 캐시한다(빈 배열이어도). 단위를 오가거나 축에서
     * 단계를 되짚을 때 같은 창을 다시 묻지 않는다.
     */
    function wireRangeModes(uid, slot) {
        var st = S[uid];
        slot.querySelectorAll('[data-range-mode]').forEach(function (btn) {
            btn.addEventListener('click', function (ev) {
                ev.stopPropagation();
                if (st.envFetching) return;
                var mode = btn.getAttribute('data-range-mode') || '';
                if (mode === (st.envMode || '')) return;     // 이미 그것이다
                st.envMode = mode;
                // 고른 단위를 위젯에 남긴다 — 다시 열었을 때 같은 보기로
                // 서게 하려는 것이다. 실패해도 화면은 그대로 간다(고른 구획을
                // 저장할 때와 같은 판단: 저장 권한이 없는 사람도 보는 동안은
                // 바꿔 볼 수 있어야 한다).
                persistOptions(uid, { env_mode: mode });
                if (!mode) { drawEnv(uid); return; }         // 접기 — 조회 없음
                loadEnvRange(uid, btn);
            });
        });
    }

    /** 지금 창의 계열을 받아 카드를 다시 그린다. 캐시에 있으면 바로 그린다. */
    function loadEnvRange(uid, btn) {
        var st = S[uid];
        var uuid = st.opts.plotUuid;
        var q = envQuery(uid);
        if (st.envCache[q.key] !== undefined) { drawEnv(uid); return; }

        st.envFetching = true;
        if (btn) { btn.disabled = true; btn.textContent = _t('Loading...'); }
        fetch('/api/geo/plot/' + encodeURIComponent(uuid) + '/env_series' + q.qs,
              { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (wk) {
                // 응답이 도는 사이에 다른 구획으로 옮겼으면 버린다 — 늦게 온
                // 것이 새 구획의 화면을 덮어쓰면 이름과 값이 어긋난다.
                if (!S[uid] || S[uid] !== st || st.opts.plotUuid !== uuid) return;
                st.envFetching = false;
                st.envCache[q.key] = (wk && wk.ok && wk.series) ? wk.series : [];
                // 계열의 **오늘**. 창의 끝이 늘 오늘은 아니라(지난 단계·주 단위)
                // 서버가 말한 것을 그대로 든다 — 여기서 날짜를 만들면 브라우저
                // 시간대로 잘라 시차가 있는 설치에서 하루 어긋난다.
                st.envEnd[q.key] = (wk && wk.window) ? wk.window.end : null;
                drawEnv(uid);
            })
            .catch(function () {
                if (!S[uid] || S[uid] !== st || st.opts.plotUuid !== uuid) return;
                st.envFetching = false;
                st.envCache[q.key] = [];
                drawEnv(uid);
            });
    }

    /** [오늘] 밴드가 쓸 창을 배경에서 받아 둔다.
     *
     * `st.envFetching`(모드 손잡이의 자물쇠)과 **다른 자물쇠**를 쓴다 — 같이
     * 쓰면 이 배경 조회가 도는 동안 [일]·[주] 클릭이 조용히 씹힌다.
     *
     * 인자 하나가 두 뜻을 가른다:
     *
     *   force 없음 — **없으면 채운다**(그리다가 부른다).
     *   force 있음 — **있으면 갱신한다**(새로고침 주기에서 부른다).
     *
     * 갱신이 필요한 이유: 안 하면 위젯이 살아 있는 내내 처음 받은 폭이 그대로
     * 남아 저녁에도 아침의 최고를 보게 된다.
     *
     * ⚠ **갱신은 이미 받아 둔 창에만 한다.** 보기 단위는 위젯 설정에 저장되므로
     * ([오늘]|[일]|[주]) 처음부터 [주] 로 열리는 위젯이 있는데, 그 사람은 [오늘]
     * 밴드를 한 번도 안 본다 — 거기까지 주기마다 물으면 아무도 안 보는 조회가
     * 5분마다 돈다. 눌러서 [오늘] 로 오면 그때 `force` 없이 채워진다.
     */
    function loadTodayWindow(uid, force) {
        var st = S[uid];
        if (!st || st.envTodayPending) return;
        var uuid = st.opts.plotUuid;
        if (!uuid) return;
        var q = todayQuery();
        var have = (st.envCache[q.key] !== undefined);
        if (force ? !have : have) return;

        st.envTodayPending = true;
        fetch('/api/geo/plot/' + encodeURIComponent(uuid) + '/env_series' + q.qs,
              { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .catch(function () { return null; })
            .then(function (wk) {
                if (!S[uid] || S[uid] !== st || st.opts.plotUuid !== uuid) return;
                st.envTodayPending = false;
                // 실패해도 빈 배열을 남긴다 — 안 남기면 그릴 때마다 다시 물어
                // 조회가 끝없이 돈다(끊긴 서버에서 특히).
                st.envCache[q.key] = (wk && wk.ok && wk.series) ? wk.series : [];
                st.envEnd[q.key] = (wk && wk.window) ? wk.window.end : null;
                drawEnv(uid);
            });
    }

    // ── 적산온도 ────────────────────────────────────────────────────────
    //
    // **이 카드가 말하는 것은 "이 단계" 하나다.** 작기 시작부터의 누적은 환경
    // 카드가 낸다(`buildEnvNowHtml` 의 GDD 불릿, 목표 대비 막대까지 함께).
    //
    // 예전에는 여기서 셋을 다 냈다 — 단계 진척 · 누적값 · 못 내는 이유. 뒤의
    // 둘은 **환경 카드와 같은 값·같은 문장**이었다: `stage.gdd` 는
    // `plot_context` 가 `gdd_accumulated()` 결과를 그대로 얹은 것이라
    // (`out['gdd'] = {…gdd…}`) `contents.plot.gdd` 와 **같은 숫자**다.
    // 그래서 화면에 "적산온도 930.5" 와 "GDD 930.5" 가 나란히 서서, 사용자가
    // 둘이 같은 것인지 다른 것인지 매번 따져야 했다(2026-09-05 정리).
    //
    // 남는 것은 **다른 값일 때뿐**이다 — `gdd_in_stage`(이 단계에 쌓인 것)와
    // `gdd_left`(다음 단계까지 남은 것)는 누적에서 파생되지만 답하는 물음이
    // 다르다("다음으로 언제 넘어가나"). 그것이 진행 카드의 물음이다.
    //
    // 라벨은 환경 카드와 **같은 `GDD`** 를 쓰고, 무엇이 다른지는 눈금 줄의
    // 덧말이 말한다(`scaleLead`: "이 단계" 대 "시작일부터 누적") — 시간창이
    // 다른 것을 덧말로 말하는 것은 그 카드가 DLI·GDD 에 이미 쓰는 규약이다.
    // 라벨을 다르게 적으면("적산온도" 대 "GDD") 같은 것을 다른 이름으로 부르게
    // 된다.

    /** 이 단계의 적산온도 진척 — 다음 단계까지 얼마나 왔나. 없으면 `''`.
     *
     * 단계 전환이 GDD 로 판정될 때만 낸다(`source === 'gdd'`). 날짜로 판정하는
     * 구획에서는 이 물음이 성립하지 않는다 — 그때 누적값을 대신 내면 환경
     * 카드와 같은 숫자를 두 번 적는 것이 된다.
     */
    function gddLine(p) {
        var V = root.AoTViz;
        var st = p.stage || {};
        if (!V || st.source !== 'gdd' || st.gdd_in_stage == null) return '';
        var unit = '\u00b0C\u00b7d';
        // 이 단계의 길이 = 쌓인 것 + 남은 것. 마지막 "끝까지" 단계는 남은 것이
        // 없어(null) 축을 만들 수 없다 — 그때는 숫자만 낸다.
        var len = (st.gdd_left == null) ? null : (st.gdd_in_stage + st.gdd_left);
        if (len && len > 0) {
            return V.bullet({
                label: _t('GDD'), value: st.gdd_in_stage,
                valueText: String(st.gdd_in_stage), valueSub: unit,
                min: 0, max: len, target: len,
                scaleLead: _t('This stage'),
                scale: ['0', { text: _t('Next stage'), anchor: true }]
            });
        }
        return V.value({ label: _t('GDD'),
                         valueText: String(st.gdd_in_stage), valueSub: unit,
                         scaleLead: _t('This stage') });
    }

    // 방향 화살표(`fillTrends`)는 없앴다 — 축 없는 줄을 스파크라인으로 채우는
    // 공용 함수(`AoTMapPopup.fillEnvSparklines`)가 그 일을 대신하고, 축이 있는
    // 줄은 빌더가 `scaleNote` 로 추세를 이미 적는다. 이 위젯만의 3시간 창을
    // 따로 두면 같은 값을 두 화면이 다른 창으로 말하게 된다.

    // ── 전환 승인 ────────────────────────────────────────────────────────
    //
    // 이 위젯에서 제일 자주 하는 행동이다. 목록의 다른 값과 달리 **놓치면 안
    // 되는 것**이라 맨 위에 세운다(P5 — 승인 전에는 목표가 넘어가지 않는다).
    function proposalHtml(p) {
        var pr = p.stage_proposal;
        if (!pr || !pr.stage_name) return '';
        // 카드 골격을 그대로 쓴다 — 테두리·배경을 따로 그리면 이 줄만 다른
        // 화면에서 온 것처럼 보인다. 색으로 경고하지도 않는다: 맨 위라는
        // 자리와 버튼이 이미 "지금 할 일" 이라고 말한다.
        return '<div class="aot-ov-block aot-plotw-ask">' +
               '<span class="aot-plotw-ask-text">' +
               _esc(_t('Moved on to %(name)s?').replace('%(name)s', pr.stage_name)) +
               '</span>' +
               '<input type="date" class="form-control aot-plotw-ask-date" ' +
               'value="' + _esc(pr.started_on || '') + '">' +
               '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm ' +
               'aot-pill-btn-primary aot-plotw-ask-ok">' +
               _esc(_t('Confirm')) + '</button>' +
               '</div>';
    }

    // ── 그리기 ───────────────────────────────────────────────────────────
    function render(uid) {
        var st = S[uid];
        var body = _el(uid, '.aot-plotw-body');
        if (!body) return;

        var p = st.plot;
        if (!p) {
            body.innerHTML = '<div class="aot-plotw-empty">' +
                _esc(st.opts.plotUuid ? _t('Loading…') : _t('Nothing recorded yet.')) +
                '</div>';
            return;
        }

        var show = st.opts.show;

        // **앱의 카드 골격을 쓴다** — 제목은 박스 밖(`.aot-ov-card-title`),
        // 내용은 박스 안(`.aot-ov-block`). 지도·시설 모달이 쓰는 것과 같은
        // 규약이라 여백·모서리·배경을 이 위젯이 따로 정하지 않는다. 카드마다
        // 자기 여백을 적어 넣으면 화면마다 테두리에서 첫 글자까지의 거리가
        // 달라지고, 그 어긋남이 곧 "정돈이 안 됐다" 로 보인다.
        var html = proposalHtml(p);

        // 어디까지 왔나 — 기간 바와 적산온도가 같은 카드에 산다(같은 질문의
        // 답 둘이다: 며칠 왔나 · 얼마나 쌓였나).
        var prog = show.progress ? blockProgress(uid, p) : '';
        var gdd = show.gdd ? gddLine(p) : '';
        if (prog || gdd) {
            html += '<div class="aot-ov-card-title">' +
                    _esc(_t('Program stages')) +
                    '</div><div class="aot-ov-block">' +
                    root.AoTViz.group([prog, gdd].filter(Boolean)) + '</div>';
        }

        // 지금 어떤가 — **자리만 잡는다.** 카드 자체(제목 + 박스)는
        // `buildEnvNowHtml` 이 통째로 만들고(`drawEnv`), [7일] 토글은 이
        // 슬롯만 다시 그린다. 본체 HTML 에 섞어 넣으면 토글 한 번에 축에서
        // 고른 단계까지 초기화된다.
        var dev = !!(show.env && st.contents);
        if (dev) html += '<div data-slot="envnow"></div>';

        // ── 노트 — **맨 아래**, 지도 구획 모달과 같은 블록 ────────────────
        //
        // 자체 마크업을 짜지 않는다. 예정과 노트가 한 블록이라는 것도, 목록의
        // 모양도, [노트 열기] 버튼의 문구도 전부 공용 컴포넌트가 정한다
        // (`buildRecordBlock` → `AoTNotesBlock`). 창마다 노트 버튼 모양과
        // 문구가 달랐던 것이 그것을 한 곳으로 모은 이유다.
        //
        // 맨 아래인 이유: 읽는 순서가 "지금 어떤가 → 그래서 무엇을 적나" 다.
        // 카드 안에서도 버튼은 목록 아래(`.aot-ov-actions`)에 선다.
        //
        // **최신 사진은 노트 바로 위**다. 지도 모달은 이것을 화면 맨 위에 두는데
        // (거기서 제일 먼저 보는 것이 "지금 어떻게 생겼나" 라서), 위젯에서는
        // 그 자리가 단계·환경을 아래로 밀어낸다 — 대시보드에 상주하는 물건이라
        // 먼저 읽히는 것은 지표다. 사진은 노트에서 온 것이므로 노트 옆에 둔다.
        var rec = (root.AoTMapPopup && root.AoTMapPopup.buildRecordBlock)
            ? root.AoTMapPopup.buildRecordBlock(
                  p.schedule, { addable: p.active !== false })
            : '';
        if (rec) html += '<div data-slot="photo"></div>';
        html += rec;

        // 지침 카드는 **없다.** 지침은 단계에 딸린 글이라 진행 카드의 단계
        // 세부 안에 있다(`stageDetail`) — 따로 카드를 두면 현재 단계의 지침이
        // 두 곳에 나온다.
        if (!prog && !gdd && !dev && !rec) {
            html += '<div class="aot-ov-muted aot-plotw-empty">' +
                    _esc(_t('All items in this card are hidden.')) + '</div>';
        }

        body.innerHTML = html;

        // 편집 버튼은 **서버가 판정한 권한**으로만 낸다 — 화면이 스스로 판단하면
        // 곧 갈라지고, 그 갈라짐은 "눌러도 403" 으로만 드러난다.
        var edit = _el(uid, '.aot-plotw-edit');
        if (edit) edit.hidden = !p.can_edit;

        if (dev) drawEnv(uid);
        wireStagePick(uid, body);
        wireAsk(uid, body);
        wireNotes(uid, body, p);
        fillLatestPhoto(uid, body, p);
    }

    /** 축의 구간을 눌러 그 단계를 편다. 같은 구간을 다시 누르면 접는다 —
     *  여는 것과 닫는 것이 같은 자리에 있어야 되돌리는 법을 따로 배우지 않는다.
     *
     *  **다시 조회하지 않는다.** 모든 단계가 이미 응답에 있으므로 화면만 다시
     *  그린다(`render`) — 누를 때마다 왕복이 나면 축을 훑어보는 일이 못 할 짓이
     *  된다. */
    function wireStagePick(uid, body) {
        body.querySelectorAll('.aot-viz-seg-hit').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var key = btn.getAttribute('data-viz-key');
                if (!key) return;
                var st = S[uid];
                st.picked = (st.picked === key) ? null : key;
                render(uid);
                // 고른 단계가 곧 **환경의 창**이다(`envQuery`). 펼쳐 둔 상태면
                // 그 창을 받아 온다 — `render` 는 캐시에 있는 것만 그리므로,
                // 처음 보는 창은 여기서 시작해야 카드가 빈 채로 남지 않는다.
                if (st.envMode) loadEnvRange(uid, null);
            });
        });
        var back = body.querySelector('.aot-plotw-stage-back');
        if (back) back.addEventListener('click', function () {
            S[uid].picked = null;
            render(uid);
        });
    }

    /** 노트 — 공용 컴포넌트에 **배선만 넘긴다**(자체 노트 UI 금지).
     *
     * 목록을 받아 채우는 것도, [노트 열기]가 여는 서랍도 전부 그쪽이 한다
     * (`AoTNotesBlock` → `open-notes` 이벤트 → layout 의 노트 앱). 위젯은
     * "무엇의 노트인가" 만 말한다.
     *
     * `targetType: 'plot'` — 지도 구획 모달과 **같은 값**이다(`aot-map-plot.js`).
     * 다르게 적으면 같은 구획의 노트가 두 화면에서 다른 목록이 된다.
     *
     * ⚠ `descendants` 를 켜지 않는다. 구획은 컨테이너가 아니라 **참조**라
     *   (설계 §256) 자손을 펴면 구역·시설의 노트가 이 구획 것처럼 보인다 —
     *   지도 구획 모달이 최신 사진에 대해 같은 판단을 한다.
     *
     * 본체는 5분마다 다시 그려진다. `cache` 를 넘겨 그때마다 목록이 자리막이
     * (…)로 스쳐 보이지 않게 한다 — 캐시는 **위젯 상태**에 둔다(본체 DOM 은
     * 교체된다).
     */
    function wireNotes(uid, body, p) {
        var N = root.AoTNotesBlock;
        if (!N || !N.wire || !p || !p.unique_id) return;
        var st = S[uid];
        st.notesCache = st.notesCache || {};
        N.wire(body, { targetId: p.unique_id, targetType: 'plot',
                       name: p.subject || p.name || '' },
               { cache: st.notesCache });
    }

    /** 최신 사진 — 노트에 붙은 사진 중 가장 최근 것 하나.
     *
     * 고르는 규칙도 카드 모양도 지도 모달의 것을 그대로 쓴다
     * (`latestNotePhoto` · `buildPhotoCardHtml`) — 동영상을 빼고 사진만 고르는
     * 판단이 거기 하나로 있다.
     *
     * ⚠ **이 구획의 노트만 본다.** 자손을 펴면 구역 사진이 이 구획 사진인 것처럼
     *   보인다(`wireNotes` 의 같은 이유).
     *
     * 사진은 **곁들이다** — 실패해도 나머지는 그대로 간다. 응답은 노트 목록과
     * 같은 것이라 캐시를 함께 쓴다(본체는 5분마다 다시 그려진다).
     */
    function fillLatestPhoto(uid, body, p) {
        var slot = body.querySelector('[data-slot="photo"]');
        var P = root.AoTMapPopup;
        if (!slot || !P || !P.latestNotePhoto || !P.buildPhotoCardHtml) return;
        var st = S[uid];
        var uuid = p && p.unique_id;
        if (!uuid) return;

        var draw = function (notes) {
            if (!slot.isConnected) return;
            var photo = P.latestNotePhoto(notes);
            var cur = slot.querySelector('img');
            // 같은 사진이면 DOM 을 건드리지 않는다 — 5분마다 다시 그리는데
            // 매번 새 `<img>` 를 넣으면 그때마다 다시 받아 깜빡인다.
            if (photo && cur && cur.getAttribute('src') === photo.url) return;
            slot.innerHTML = P.buildPhotoCardHtml(photo);
        };

        // ⚠ 노트 블록의 캐시(`st.notesCache`)를 같이 쓰지 않는다. 그것은
        //   공용 컴포넌트가 `{html: '…'}` 한 벌로 쓰는 물건이라(sensor-label.js),
        //   여기서 uuid 키를 얹으면 두 용도가 한 객체에서 섞인다.
        var cached = st.photoCache[uuid];
        if (cached) { draw(cached); return; }
        fetch('/notes/target/' + encodeURIComponent(uuid), { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (notes) {
                if (!S[uid] || S[uid] !== st || st.opts.plotUuid !== uuid) return;
                if (!Array.isArray(notes)) return;
                st.photoCache[uuid] = notes;
                draw(notes);
            })
            .catch(function () { /* 사진은 곁들이다 */ });
    }

    function wireAsk(uid, body) {
        var btn = body.querySelector('.aot-plotw-ask-ok');
        if (!btn) return;
        var st = S[uid];
        var pr = (st.plot || {}).stage_proposal || {};
        btn.addEventListener('click', function () {
            var dateEl = body.querySelector('.aot-plotw-ask-date');
            btn.disabled = true;
            _api('POST', '/api/geo/plot/' +
                 encodeURIComponent(st.opts.plotUuid) + '/stage', {
                     stage_key: pr.stage_key,
                     started_on: (dateEl && dateEl.value) || pr.started_on,
                     source: pr.source
                 }).then(function (res) {
                btn.disabled = false;
                if (res.status >= 400 || !res.data.ok) {
                    _toast(res.data.message || _t('Save failed'), 'error');
                    return;
                }
                // 승인은 기준점을 옮긴다 — 단계·목표·축이 통째로 다시 계산되므로
                // 부분 갱신하지 않고 다시 받는다.
                refresh(uid);
            });
        });
    }

    // ── 편집 모달 ────────────────────────────────────────────────────────
    //
    // 본문은 `/plots` 드로어와 **같은 두 컴포넌트**다. 다른 것은 셸뿐이다 —
    // 대시보드는 자기 드로어 모드를 돌리고 있어(dashboard.js) 여기서
    // `.aot-widget-drawer` 를 쓰면 body 클래스가 이중으로 토글된다. 그래서
    // 가운데 모달로 연다.
    function openEdit(uid) {
        var st = S[uid];
        var p = st.plot;
        if (!p || !p.can_edit) return;
        var F = root.AoTPlotForm, G = root.AoTPlotStages;
        if (!F || !G) return;

        var host = document.getElementById('aot-plot-modal-' + uid);
        var bodyEl = host && host.querySelector('.modal-body');
        var titleEl = host && host.querySelector('.modal-title');
        if (!bodyEl) return;

        var facUuid = p.facility_uuid || null;
        loadFacility(uid, facUuid).then(function (fac) {
            var ctx = {
                attr: 'data-pf',
                target: facUuid ? 'facility' : 'ground',
                values: p,
                kind: p.kind || 'vegetation',
                bays: fac ? fac.bays : [],
                capacities: fac ? fac.capacities : {},
                bayId: p.bay_id || null,
                programs: st.programs[p.kind || 'vegetation'] || [],
                include: ['name'],
                canDesign: !!p.can_design,
                today: _today(),
                loadPrograms: function (kind) { return loadPrograms(uid, kind); }
            };

            var basics = '<div class="aot-modal-group-title">' +
                         _esc(_t('Basics')) + '</div>' +
                         '<div class="aot-modal-container">' +
                         F.rowsHtml(ctx) + '</div>';
            G.load(p);
            bodyEl.innerHTML = basics + G.html();
            if (titleEl) titleEl.textContent = p.subject || p.name || _t('Plot');

            var form = bodyEl.querySelector('.aot-modal-container');
            bodyEl._ctx = ctx;
            F.wire(form, ctx);
            G.wire(bodyEl);

            if (root.jQuery) root.jQuery(host).modal('show');
        });
    }

    /** 기본 정보 + 단계 일정을 **한 번에** 저장한다(`/plots` 와 같은 약속). */
    function saveEdit(uid) {
        var st = S[uid];
        var host = document.getElementById('aot-plot-modal-' + uid);
        var bodyEl = host && host.querySelector('.modal-body');
        if (!bodyEl) return Promise.resolve(false);

        var F = root.AoTPlotForm, G = root.AoTPlotStages;
        var ctx = bodyEl._ctx || { attr: 'data-pf' };
        var form = bodyEl.querySelector('.aot-modal-container');
        var payload = F.collect(form, ctx);
        if (!payload.subject) {
            _toast(_t('Enter what is planted.'), 'warning');
            return Promise.resolve(false);
        }
        payload.unique_id = st.opts.plotUuid;

        var extra = G.plotFields();
        Object.keys(extra).forEach(function (k) { payload[k] = extra[k]; });

        // 프로그램을 바꾸면 일정이 통째로 그 프로그램의 것으로 바뀐다 — 옛 단계
        // 키를 가리키는 편집을 함께 보내면 서버가 없는 키로 거절한다.
        var progChanged = (payload.program_uuid || '') !==
                          (((st.plot || {}).program || {}).unique_id || '');

        var btn = host.querySelector('.aot-plotw-save');
        if (btn) btn.disabled = true;
        return _api('POST', '/api/geo/plot', payload).then(function (res) {
            if (res.status >= 400 || !res.data.ok) {
                // 서버가 거절한 이유를 그대로 보인다 — 화면이 지어내지 않는다.
                return { ok: false, message: res.data.message || _t('Save failed') };
            }
            if (progChanged) return { ok: true };
            return G.save(bodyEl, _api);
        }).then(function (out) {
            if (btn) btn.disabled = false;
            if (!out.ok) {
                _toast(out.message || _t('Save failed'), 'error');
                return false;
            }
            _toast(_t('Saved.'), 'success');
            return refresh(uid).then(function () { return true; });
        });
    }

    function loadPrograms(uid, kind) {
        var st = S[uid];
        kind = kind || 'vegetation';
        if (st.programs[kind]) return Promise.resolve(st.programs[kind]);
        return _get('/api/geo/programs?kind=' + encodeURIComponent(kind))
            .then(function (res) {
                st.programs[kind] = (res && res.ok) ? (res.programs || []) : [];
                return st.programs[kind];
            });
    }

    /** 시설 구획을 편집하려면 그 시설의 구역·총량이 필요하다(몫 접미). */
    function loadFacility(uid, uuid) {
        var st = S[uid];
        if (!uuid) return Promise.resolve(null);
        if (st.facilities[uuid]) return Promise.resolve(st.facilities[uuid]);
        return _get('/api/geo/facility/' + encodeURIComponent(uuid))
            .then(function (res) {
                var f = (res && (res.facility || res)) || {};
                st.facilities[uuid] = {
                    bays: (f.bay_slices || []).map(function (s) {
                        return { id: s.id, name: s.name };
                    }),
                    capacities: f.bay_capacities || {}
                };
                return st.facilities[uuid];
            });
    }

    function _today() {
        var d = new Date();
        var z = function (n) { return (n < 10 ? '0' : '') + n; };
        return d.getFullYear() + '-' + z(d.getMonth() + 1) + '-' + z(d.getDate());
    }

    // ── 배선 ─────────────────────────────────────────────────────────────
    function init(uid, opts) {
        opts = opts || {};
        // 대시보드가 같은 위젯을 다시 그리는 경로가 있다(장치 추가 직후의 조각
        // 삽입, 설정 저장 뒤 새로고침). 옛 타이머를 거두지 않으면 위젯 하나에
        // 폴링이 겹쳐 쌓인다 — 화면은 멀쩡해 보이고 요청만 배로 는다.
        if (S[uid] && S[uid].timer) clearInterval(S[uid].timer);

        var st = S[uid] = {
            opts: {
                plotUuid: opts.plotUuid || null,
                refreshMin: Math.max(1, parseInt(opts.refreshMin, 10) || 5),
                show: {
                    progress: opts.showProgress !== false,
                    env: opts.showEnv !== false,
                    trend: opts.showTrend !== false,
                    gdd: opts.showGdd !== false
                }
            },
            picked: null,          // 축에서 고른 단계(없으면 지금)
            // 환경 카드의 단위. `''`(오늘) | `'day'` | `'week'`.
            //
            // **재렌더를 넘어 산다** — 위젯은 5분마다 다시 그려지는데 그때마다
            // 접히면 펼쳐 두고 보는 일이 성립하지 않는다. 그리고 위젯에
            // 저장돼 있어(`env_mode`) 페이지를 다시 열어도 같은 보기로 선다.
            //
            // ⚠ 모르는 값은 `''` 로 눕힌다. 저장된 옵션은 사람이 손으로 고칠
            //   수 있는 자리이고(설정 JSON), 엉뚱한 값이 오면 손잡이 어느
            //   것도 켜지지 않은 채 카드만 비어 보인다.
            envMode: (opts.envMode === 'day' || opts.envMode === 'week')
                ? opts.envMode : '',
            envFetching: false,
            // 창(단위 + 고른 단계)마다 계열을 따로 들고 있는다. 단위를 오가거나
            // 축에서 단계를 되짚을 때 같은 창을 다시 묻지 않는다.
            envCache: {},
            envEnd: {},            // 창 → 그 계열의 마지막 날(`window.end`)
            envTodayPending: false,
            notesCache: {},        // 재렌더 때 목록이 자리막이로 스치지 않게
            photoCache: {},        // 최신 사진 — 노트 응답을 구획별로 들고 있는다
            plots: [], plot: null, contents: null,
            programs: {}, facilities: {}, timer: null
        };

        var sel = _pick(uid);
        if (sel) {
            sel.addEventListener('change', function () {
                st.opts.plotUuid = sel.value || null;
                st.picked = null;      // 다른 구획의 단계 키는 뜻이 없다
                st.plot = null;
                st.contents = null;
                // 계열은 **구획마다 다른 값**이다 — 안 버리면 옮긴 뒤에도 앞
                // 구획의 그림이 그대로 남는다(에러 없이). 고른 단위는 남긴다:
                // 그것은 "어떻게 보나" 라 구획이 바뀌어도 뜻이 이어진다.
                st.envFetching = false;
                st.envCache = {};
                st.envEnd = {};
                st.envTodayPending = false;
                st.notesCache = {};    // 다른 구획의 노트를 보여 주면 안 된다
                st.photoCache = {};
                render(uid);              // 고른 즉시 자리막이로 바뀐다
                persistPick(uid, st.opts.plotUuid);
                refresh(uid);
            });
        }

        var edit = _el(uid, '.aot-plotw-edit');
        if (edit) edit.addEventListener('click', function () { openEdit(uid); });

        var host = document.getElementById('aot-plot-modal-' + uid);
        var save = host && host.querySelector('.aot-plotw-save');
        if (save) {
            save.addEventListener('click', function () {
                saveEdit(uid).then(function (ok) {
                    if (ok && root.jQuery) root.jQuery(host).modal('hide');
                });
            });
        }

        loadPlots(uid).then(function () { return refresh(uid); }).then(function () {
            // 저장된 단위가 있으면 그 창을 받아 온다. "조회는 누를 때만" 규칙의
            // 예외가 아니다 — 사람이 그 보기를 골라 **저장해 둔 것**이라 그것이
            // 곧 누른 것이다. 기본값(`''`)에서는 아무 조회도 일어나지 않는다.
            if (S[uid] && S[uid].envMode) loadEnvRange(uid, null);
        });

        // 단계는 하루 단위로 변하고 환경은 분 단위로 변한다 — 그 사이 어딘가면
        // 되므로 기본 5분이다. **숨은 탭에서는 건너뛴다**: 안 보이는 화면을
        // 위해 폴링할 이유가 없고, 폰에서는 그 한 번이 라디오를 깨운다.
        st.timer = setInterval(function () {
            if (document.hidden) return;
            if (!S[uid]) return;
            refresh(uid);
        }, st.opts.refreshMin * 60000);
    }

    root.AoTPlotWidget = { init: init, refresh: refresh };
})(window);
