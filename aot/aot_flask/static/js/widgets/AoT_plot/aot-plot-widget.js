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
        _api('POST', '/save_widget_custom_options',
             { widget_id: uid, options: { plot_uuid: uuid } });
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
               '><i>' + _esc(name) + '</i>' +
               (weak ? '<em>' + _esc(value) + '</em>'
                     : '<b>' + _esc(value) + '</b>') + '</span>';
    }

    // ── 1) 어디까지 왔나 ────────────────────────────────────────────────
    //
    // **한 줄이다.** 단계·일차·남은 날을 머리줄에 적고 그 아래 얇은 트랙 하나.
    // 구간 이름 줄과 눈금 줄은 뺐다(`compact`) — 좁은 카드에서 그 둘은 트랙보다
    // 자리를 더 먹는데, 여기서 답해야 하는 것은 "지금 어디쯤" 하나다.
    //
    // 구간은 **누를 수 있다.** 축이 현재 단계만 말하면 "다음엔 무엇을 하나" 를
    // 알 수 없는데, 그 답은 이미 응답에 있다(`stage_schedule` 이 모든 단계의
    // 기간·지침·목표를 싣는다) — 조회 없이 그 자리에서 보여 줄 수 있다.
    function blockProgress(uid, p) {
        var V = root.AoTViz;
        var tl = p.timeline;
        if (!V || !tl || !(tl.stages || []).length) return '';
        var picked = S[uid].picked;

        var segs = tl.stages.map(function (s) {
            return { key: s.key, span: Math.max(0, (s.to_pct || 0) - (s.from_pct || 0)),
                     name: s.name, current: !!s.current,
                     picked: !!picked && s.key === picked };
        });

        // 사건은 **단계의 시작 경계**에 찍는다 — 축의 경계는 서버가 계획·승인을
        // 반영해 이미 잡아 둔 것이라, 화면이 날짜 산술을 따로 하면 두 값이 갈린다.
        var byKey = {};
        tl.stages.forEach(function (s) { byKey[s.key] = s; });
        var events = (p.stage_history || []).filter(function (h) {
            return !h.undone && byKey[h.stage_key];
        }).map(function (h) {
            var s = byKey[h.stage_key];
            return { pct: s.from_pct,
                     label: (h.started_on || '') + ' ' + (s.name || '') };
        });

        var st = p.stage || {};
        var head = (st.state === 'running' && st.name) ? st.name : _t('Progress');
        // 오른쪽 값은 **일차 하나**다. 남은 날은 그 옆 작은 글씨로 — 둘을 같은
        // 크기로 적으면 어느 것이 지금인지 눈이 매번 고른다.
        var vt = (p.days_since_planted != null)
            ? _t('Day %(n)s').replace('%(n)s', String(p.days_since_planted))
            : '';
        if (tl.total_days) vt += ' / ' + tl.total_days;
        // 남은 날 — **음수는 "남음" 이 아니다.** 예정일을 지난 작기에서
        // "-2일 남음" 이 되던 자리다(2026-08-28 실측). 지났으면 지났다고 적는다.
        var left = (st.days_left != null) ? st.days_left : p.days_to_expected_end;
        var sub = '';
        if (left != null) {
            sub = (left < 0)
                ? _t('%(n)s days over').replace('%(n)s', String(-left))
                : _t('%(n)s days left').replace('%(n)s', String(left));
        }

        return V.timeline({
            compact: true, pickable: true,
            label: head, valueText: vt || null, valueSub: sub || null,
            segments: segs, events: events, positionPct: tl.today_pct
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

        var html = '<div class="aot-plotw-stage">' +
                   '<div class="aot-plotw-stage-head">' +
                   // 현재 단계의 이름은 **축의 머리줄이 이미 말한다** — 여기서
                   // 또 적으면 같은 글자가 두 줄 연달아 선다. 다른 단계를
                   // 골랐을 때만 이름을 적는다(그때는 머리줄과 다르다).
                   (isCur ? '' : '<b>' + _esc(row.name || key) + '</b>') +
                   '<span>' + _esc(bits.join(' \u00b7 ')) + '</span>' +
                   (isCur ? '' :
                    '<button type="button" class="aot-plotw-stage-back">' +
                    _esc(_t('Back to now')) + '</button>') +
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

        if (row.guidance) {
            html += '<div class="aot-plotw-guide" title="' + _esc(row.guidance) +
                    '">' + _esc(row.guidance) + '</div>';
        }
        return html + '</div>';
    }

    // ── 2) 지금 어떤가 — 게이지 하나 + 나머지는 글 ──────────────────────
    //
    // **지표 하나만 게이지로 세운다.** 여러 개를 한 그림에 몰면 라벨이 겹쳐
    // 읽히지 않는다(실제로 그렇게 만들어 봤다). 어느 것을 볼지는 작목마다
    // 다르므로 — 시설 토마토는 VPD, 노지는 토양수분 — 사용자가 고른다.
    //
    // 나머지는 **글로** 적는다. 게이지가 아니어도 값은 읽히고, 무엇보다
    // 겹치지 않는다.
    //
    // 판정(무엇이 목표이고 무엇이 한계인가, 적정 구간이 어디인가)은 **지도
    // 팝업 것을 그대로 쓴다**(`AoTMapPopup.envRowSpec`) — 온도·습도가 목표가
    // 아니라 한계라는 구분이 거기 하나로 있고, 화면이 다시 조립하면 "아무도
    // 정한 적 없는 숫자가 목표로 둔갑" 하는 실패로 되돌아간다.

    /** 고른 지표 → 실제 측정 key. `soil` 만 이름으로 찾는다.
     *
     * 토양수분은 **고정 어휘가 없다**(`facility_sensors._MTYPE_KEY` 에 없어
     * 측정명이 그대로 key 가 된다) — 설치마다 이름이 달라 목록으로 못 박을 수
     * 없다. 나머지 셋은 어휘가 고정이라 그대로 맞춘다. */
    function _matchKey(choice, keys) {
        if (choice === 'soil') {
            for (var i = 0; i < keys.length; i++) {
                if (/soil|moist|수분/i.test(keys[i])) return keys[i];
            }
            return null;
        }
        return (keys.indexOf(choice) >= 0) ? choice : null;
    }

    function blockEnv(uid) {
        var st = S[uid];
        var V = root.AoTViz;
        var P = root.AoTMapPopup;
        var c = st.contents;
        if (!V || !P || !P.envRowSpec || !c) return '';
        var plot = c.plot || {};
        var readings = ((plot.env || {}).readings) || [];
        // 감추는 항목은 **상위(시설·구역)의 설정을 물려받는다** — 서버가 어느
        // 상위인지 이미 골라 준다. 여기서 다시 고르면 규칙이 두 곳에 생긴다.
        var hidden = {};
        ((plot.hidden_rows || {}).now || []).forEach(function (k) { hidden[k] = 1; });

        var specs = [];
        readings.filter(function (r) { return !hidden[r.key]; }).forEach(function (r) {
            var sp = P.envRowSpec(r, { targets: plot.targets,
                                       limits: plot.limits,
                                       targetMethods: plot.target_methods });
            if (sp) specs.push(sp);
        });
        if (!specs.length) return '';

        var keys = specs.map(function (x) { return x.key; });
        var want = _matchKey(st.opts.gauge, keys);
        // 고른 것을 이 구획이 재지 않으면 **축을 그릴 수 있는 첫 지표**로
        // 대신한다. 빈 자리를 두면 사용자는 위젯이 고장 난 것으로 읽는데,
        // 실제로는 그 센서가 없는 것이다 — 게이지 라벨이 무엇을 보고 있는지
        // 이미 말하므로 바꿔치기가 거짓말이 되지 않는다.
        var main = null;
        for (var i = 0; i < specs.length; i++) {
            if (specs[i].key === want) { main = specs[i]; break; }
        }
        if (!main) {
            for (i = 0; i < specs.length; i++) {
                if (specs[i].hasAxis) { main = specs[i]; break; }
            }
        }

        // 게이지에도 방향을 붙인다 — 이 카드에서 제일 먼저 읽는 값이라 "지금
        // 어느 쪽으로 가는 중인가" 가 제일 필요한 자리다. 어느 지표인지는
        // 채우고 나서 알아야 하므로 상태에 남긴다.
        st.mainKey = main ? main.key : null;

        var html = '';
        if (main && main.hasAxis) {
            html += V.band({
                className: 'aot-plotw-main',
                label: main.name, value: main.value,
                valueText: main.valueText, valueSub: main.unit,
                min: main.min, max: main.max,
                okMin: main.okMin, okMax: main.okMax,
                stale: main.stale,
                // 축의 양 끝은 적지 않는다 — 5단계 색을 나누려고 정한 값이라
                // 사람이 읽을 뜻이 없다. 이 줄이 말하는 것은 기준과 지금 위치다.
                scale: main.anchorText
                    ? [{ text: main.anchorText, anchor: true, at: main.anchorAt }]
                    : [],
                scaleNote: main.trendNote || ''
            });
        } else if (main) {
            html += V.value({ className: 'aot-plotw-main',
                              label: main.name, valueText: main.valueText,
                              valueSub: main.unit, stale: main.stale });
        }

        // 나머지는 **한 행에 나열한다** — 단계 목표와 같은 줄 문법이다.
        //
        // ⚠ 항목마다 줄을 잡지 않는다. 한때 공용 라벨-값 행(`.aot-ov-row`)으로
        //   한 줄씩 세웠다가 되돌렸다 — 정렬은 맞았지만 값 두어 개에 카드가
        //   그만큼 커졌다. **핵심(게이지)만 한 줄이고 나머지는 나열이다**
        //   (2026-08-28 지적).
        var rest = specs.filter(function (x) { return x !== main; }).map(function (x) {
            return _pair(x.name, x.valueText + (x.unit ? ' ' + x.unit : ''),
                         false, x.key);
        });
        if (rest.length) {
            html += '<div class="aot-tag-list aot-plotw-list">' + rest.join('') + '</div>';
        }
        return html;
    }

    // ── 적산온도 ────────────────────────────────────────────────────────
    //
    // 이것은 "어디까지 왔나" 의 다른 자다(날이 아니라 쌓인 열). 그래서 환경이
    // 아니라 **진행 옆**에 붙인다 — 같은 질문의 답 둘을 떼어 놓으면 사람이
    // 둘을 오가며 읽는다.
    var _GDD_REASON = {
        'no-program': 'No programme is linked.',
        'no-t-base': 'The programme has no base temperature.',
        'no-start-date': 'No planting date yet.',
        'not-started': 'Not started yet.',
        'too-early': 'Too early to accumulate.',
        'no-temperature-sensor': 'No temperature sensor reaches this plot.',
        'low-coverage': 'Not enough daily temperature data.'
    };

    /** 적산온도 한 줄 — 이 단계의 전환 임계까지 얼마나 왔나. */
    function gddLine(p) {
        var V = root.AoTViz;
        var st = p.stage || {};
        var g = st.gdd;
        if (!V || (!g && st.source !== 'gdd')) return '';
        var label = _t('Accumulated heat');
        var unit = '\u00b0C\u00b7d';

        if (st.source === 'gdd' && st.gdd_in_stage != null) {
            // 이 단계의 길이 = 쌓인 것 + 남은 것. 마지막 "끝까지" 단계는 남은
            // 것이 없어(null) 축을 만들 수 없다 — 그때는 숫자만 낸다.
            var len = (st.gdd_left == null) ? null : (st.gdd_in_stage + st.gdd_left);
            if (len && len > 0) {
                return V.bullet({
                    label: label, value: st.gdd_in_stage,
                    valueText: String(st.gdd_in_stage), valueSub: unit,
                    min: 0, max: len, target: len,
                    scale: ['0', { text: _t('Next stage'), anchor: true }]
                });
            }
            return V.value({ label: label, valueText: String(st.gdd_in_stage),
                             valueSub: unit });
        }
        if (g && g.value != null) {
            return V.value({ label: label, valueText: String(g.value),
                             valueSub: unit });
        }
        var why = _GDD_REASON[(g || {}).reason];
        if (!why) return '';
        return V.value({ label: label, valueText: '\u2014', valueSub: _t(why) });
    }

    /** 편차 축의 라벨에 **방향**을 붙인다 — `↑`/`↓`.
     *
     * 이 표현에는 스파크라인이 설 자리가 없다(축이 하나뿐이다). 그런데 여기서
     * 정말 필요한 것은 모양이 아니라 **방향**이다: 습도가 구간 위로 벗어나
     * 있는데 더 오르는 중인지 내려오는 중인지가 다음 행동을 가른다.
     *
     * 덤이라 실패해도 값은 그대로 남는다. */
    function fillTrends(uid, host) {
        var st = S[uid];
        if (!st.opts.show.trend || !st.contents) return;
        // 붙일 자리 둘 — 곁들이는 값의 **칩**과, 게이지의 **값 옆**.
        var targets = [];
        [].forEach.call(host.querySelectorAll('.aot-plotw-list .aot-tag[data-viz-key]'),
            function (el) {
                targets.push({ el: el, key: el.getAttribute('data-viz-key') });
            });
        var gauge = st.mainKey &&
                    host.querySelector('.aot-plotw-main .aot-viz-value');
        if (gauge) targets.push({ el: gauge, key: st.mainKey });
        if (!targets.length) return;

        var chans = {};                    // key → {device_id, measurement_id}
        (st.contents.sensors || []).forEach(function (sen) {
            (sen.channels || []).forEach(function (ch) {
                if (ch.key && ch.measurement_id && !chans[ch.key]) {
                    chans[ch.key] = { device_id: sen.unique_id,
                                      measurement_id: ch.measurement_id };
                }
            });
        });

        var jobs = [];
        targets.forEach(function (t) {
            var ch = chans[t.key];
            if (ch) jobs.push({ el: t.el, ch: ch });
        });
        if (!jobs.length) return;

        var items = jobs.map(function (j) {
            return { kind: 'past', unique_id: j.ch.device_id,
                     measure_type: 'input',
                     measurement_id: j.ch.measurement_id,
                     period: String(_TREND_PAST_S) };
        });
        // 공유 코얼레서를 지난다 — 같은 대시보드의 다른 위젯과 항목이 겹치면
        // 한 번으로 합쳐진다.
        var sent = (root.AoTDataBatch && root.AoTDataBatch.postItems)
            ? root.AoTDataBatch.postItems(items).then(function (res) {
                  return res ? { results: res } : null;
              })
            : _api('POST', '/data_batch', { items: items }).then(function (r) {
                  return r.data;
              });

        sent.then(function (d) {
            var res = d && d.results;
            // 길이가 안 맞으면 짝짓기가 깨진 것이다 — 잘못 이으면 CO2 의 방향이
            // 습도 자리에 붙는다. 그럴 바에는 안 그린다.
            if (!Array.isArray(res) || res.length !== jobs.length) return;
            jobs.forEach(function (j, i) {
                var series = res[i];
                if (!Array.isArray(series) || series.length < 4) return;
                var v = series.map(function (x) {
                    return Array.isArray(x) ? Number(x[1]) : Number(x);
                }).filter(function (x) { return isFinite(x); });
                if (v.length < 4 || !j.el.isConnected) return;
                // 앞뒤 1/4 의 평균을 견준다 — 마지막 점 하나로 방향을 정하면
                // 센서가 한 번 튄 것이 곧 "오르는 중" 이 된다.
                var q = Math.max(1, Math.floor(v.length / 4));
                var avg = function (arr) {
                    return arr.reduce(function (a, b) { return a + b; }, 0) / arr.length;
                };
                var head = avg(v.slice(0, q)), tail = avg(v.slice(-q));
                var span = Math.max.apply(null, v) - Math.min.apply(null, v);
                // 흔들림 안쪽의 차이는 방향이 아니다 — "→ 0" 은 아무 말도 아니다.
                if (!span || Math.abs(tail - head) < span * 0.15) return;
                var mark = document.createElement('i');
                mark.className = 'aot-plotw-trend';
                mark.textContent = (tail > head) ? '\u2191' : '\u2193';
                j.el.appendChild(mark);
            });
        }).catch(function () { /* 덤이다 */ });
    }

    var _TREND_PAST_S = 10800;      // 3시간 — 방향을 말하기에 충분한 창

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
            html += '<div class="aot-ov-card-title">' + _esc(_t('Progress')) +
                    '</div><div class="aot-ov-block">' +
                    root.AoTViz.group([prog, gdd].filter(Boolean)) + '</div>';
        }

        // 지금 무엇이 어긋나 있나 — 지표 전부가 한 축에.
        var dev = show.env ? blockEnv(uid) : '';
        if (dev) {
            html += '<div class="aot-ov-card-title">' + _esc(_t('Environment')) +
                    '</div><div class="aot-ov-block">' + dev + '</div>';
        }

        // 지침 카드는 **없다.** 지침은 단계에 딸린 글이라 진행 카드의 단계
        // 세부 안에 있다(`stageDetail`) — 따로 카드를 두면 현재 단계의 지침이
        // 두 곳에 나온다.
        if (!prog && !gdd && !dev) {
            html += '<div class="aot-ov-muted aot-plotw-empty">' +
                    _esc(_t('All items in this card are hidden.')) + '</div>';
        }

        body.innerHTML = html;

        // 편집 버튼은 **서버가 판정한 권한**으로만 낸다 — 화면이 스스로 판단하면
        // 곧 갈라지고, 그 갈라짐은 "눌러도 403" 으로만 드러난다.
        var edit = _el(uid, '.aot-plotw-edit');
        if (edit) edit.hidden = !p.can_edit;

        fillTrends(uid, body);
        wireStagePick(uid, body);
        wireAsk(uid, body);
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
                S[uid].picked = (S[uid].picked === key) ? null : key;
                render(uid);
            });
        });
        var back = body.querySelector('.aot-plotw-stage-back');
        if (back) back.addEventListener('click', function () {
            S[uid].picked = null;
            render(uid);
        });
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
                gauge: opts.gauge || 'VPD',
                show: {
                    progress: opts.showProgress !== false,
                    env: opts.showEnv !== false,
                    trend: opts.showTrend !== false,
                    gdd: opts.showGdd !== false
                }
            },
            picked: null,          // 축에서 고른 단계(없으면 지금)
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

        loadPlots(uid).then(function () { return refresh(uid); });

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
