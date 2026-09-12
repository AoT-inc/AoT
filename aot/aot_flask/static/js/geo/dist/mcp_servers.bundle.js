(function () {
    'use strict';

    /**
     * MCP 브리지 서버 목록 — 내장 AI 가 도구로 부르는 MCP 서버 프로세스를 보고 켜고 끈다.
     *
     * 2026-09-10 재구성: 공용 설정 카드·행(.aot-settings-row)·알약 버튼·상태 배지로
     * 그린다. 예전의 전용 카드 체계(pages/mcp_servers.css)와 아이콘만 있는 버튼, 영문
     * 상태 원문을 걷었고, 동작이 없던 삭제를 서버 편집 모달의 [삭제]로 연결했다.
     * 문구는 템플릿이 window.AOT_MCP.t 로 넘긴다(번역).
     */

    /**
     * 서버·도구 값(이름·명령·설명·스키마)은 사용자나 외부 MCP 서버가 정한
     * 문자열이다. innerHTML 로 끼워 넣기 전에 반드시 이스케이프한다.
     */
    function _escHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    $(document).ready(function () {
        const API_BASE = '/api/v1/mcp';
        const CFG = window.AOT_MCP || { csrf: '', t: {} };
        const T = CFG.t;
        const $list = $('#mcp-server-list');
        const $tools = $('#tools-container');
        const $modal = $('#modal-mcp-server');
        let servers = [];

        function toast(msg, type) {
            if (typeof window.showToast === 'function') { window.showToast(msg, type); }
        }

        function call(url, method, body) {
            const opts = { method: method, headers: { 'X-CSRFToken': CFG.csrf } };
            if (body !== undefined) {
                opts.headers['Content-Type'] = 'application/json';
                opts.body = JSON.stringify(body);
            }
            return fetch(url, opts).then(function (r) {
                return r.json().catch(function () { return {}; }).then(function (d) {
                    return { ok: r.ok && d.status !== 'error', data: d };
                });
            });
        }

        // 상태는 글자로 말한다 — 색만으로 가르지 않는다(§4-11).
        function statusBadge(status) {
            if (status === 'running') { return '<span class="aot-status-badge aot-status-ok">' + _escHtml(T.running) + '</span>'; }
            if (status === 'cooldown') { return '<span class="aot-status-badge aot-status-warn">' + _escHtml(T.cooldown) + '</span>'; }
            return '<span class="aot-status-badge">' + _escHtml(T.stopped) + '</span>';
        }

        function btn(act, label, primary) {
            return '<button type="button" class="btn aot-pill-btn ' + (primary ? 'aot-pill-btn-primary' : 'aot-pill-btn-secondary')
                + '" data-act="' + act + '">' + _escHtml(label) + '</button>';
        }

        // 한 서버 = 한 행. 1행 [이름][상태] · 2행 오른쪽 [행동].
        // 읽을 것이 여러 줄이라 행동은 오른쪽 아래다(§3-2 ②).
        //
        // 실행 명령(command)은 행에 싣지 않는다 — 이 서버 파일시스템 경로·런타임
        // 버전(예: /usr/local/bin/python3.11 /app/aot/aot_mcp_server.py)이 로그인만
        // 하면(관리자가 아니어도) 보이는 목록에 그대로 노출됐다(2026-09-11). 값 자체는
        // 지우지 않는다 — [편집] 을 누른 사람만 보는 설정 창(server-command 입력칸)에
        // 그대로 있다.
        //
        // `aot-settings-row-item` 을 함께 건다 — 이름이 길면(예: "AoT System Expert
        // Server") 라벨이 배지와 한 줄을 못 나눠 배지만 아랫줄에 홀로 떨어져 왼쪽에
        // 빈 칸이 생겼다(375px 실측). row-item 은 라벨을 그 줄 안에서 줄이거나 접어
        // 배지와 같은 줄에 남긴다(aot-settings.css 참고).
        function renderServers(rows) {
            servers = rows || [];
            if (!servers.length) {
                $list.html('<div class="aot-settings-sub">' + _escHtml(T.none) + '</div>');
                return;
            }
            $list.html(servers.map(function (s) {
                const running = s.status === 'running';
                const acts = btn('tools', T.tools) + btn('edit', T.edit)
                    + (running ? btn('stop', T.stop) + btn('restart', T.restart) : btn('start', T.start, true));
                return '<div class="aot-settings-row aot-settings-row-full aot-settings-row-item" data-id="' + _escHtml(s.unique_id) + '">'
                    + '<div class="aot-settings-label">' + _escHtml(s.name) + '</div>'
                    + '<div class="aot-settings-control">' + statusBadge(s.status) + '</div>'
                    + '<div class="aot-settings-full aot-btn-group">' + acts + '</div>'
                    + '</div>';
            }).join(''));
        }

        function loadServers() {
            fetch(API_BASE + '/servers')
                .then(function (r) { return r.json(); })
                .then(renderServers)
                .catch(function () {
                    $list.html('<div class="aot-notice-box aot-notice-box-danger">' + _escHtml(T.loadFailed) + '</div>');
                });
        }

        function serverById(id) {
            return servers.find(function (s) { return String(s.unique_id) === String(id); });
        }

        // ── 행 동작 ──────────────────────────────────────────────────────────
        $list.on('click', 'button[data-act]', function () {
            const act = this.getAttribute('data-act');
            const id = $(this).closest('[data-id]').attr('data-id');
            if (act === 'edit') { openEditor(serverById(id)); return; }
            if (act === 'tools') { openTools(serverById(id)); return; }
            // 시작은 별도 엔드포인트가 없다 — 멈춘 서버에 restart 를 부르면 띄운다(서버 동작).
            const path = (act === 'stop') ? 'stop' : 'restart';
            this.disabled = true;
            call(API_BASE + '/servers/' + encodeURIComponent(id) + '/' + path, 'POST').then(function (res) {
                // 실패 응답은 {error: ...} 로 온다(routes_mcp_api) — message 만 보면 이유가 사라진다.
                toast(res.data.message || res.data.error || (res.ok ? '' : T.failed), res.ok ? 'success' : 'error');
                loadServers();
            });
        });

        function openTools(server) {
            if (!server) { return; }
            $('#tools-modal-title').text(T.tools + ': ' + server.name);
            $tools.html('<div class="aot-modal-body-text">' + _escHtml(T.loading) + '</div>');
            $('#modal-mcp-tools').modal('show');
            fetch(API_BASE + '/servers/' + encodeURIComponent(server.unique_id) + '/tools')
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    const tools = (data && data.tools) || [];
                    if (!tools.length) {
                        $tools.html('<div class="aot-modal-body-text">' + _escHtml(T.noTools) + '</div>');
                        return;
                    }
                    // 한 도구 = 한 행: 이름(핵심) · 설명(부연, 셋째 자식) · 입력 형식은 접어 둔다.
                    $tools.html(tools.map(function (tool) {
                        return '<div class="aot-modal-option-row">'
                            + '<div class="aot-modal-option-label">' + _escHtml(tool.name) + '</div>'
                            + '<div class="aot-modal-body-text">' + _escHtml(tool.description || '')
                            + '<details><summary>' + _escHtml(T.schema) + '</summary>'
                            + '<pre class="aot-pre-wrap aot-break-word">' + _escHtml(JSON.stringify(tool.inputSchema, null, 2)) + '</pre>'
                            + '</details></div>'
                            + '</div>';
                    }).join(''));
                })
                .catch(function () {
                    $tools.html('<div class="aot-notice-box aot-notice-box-danger">' + _escHtml(T.failed) + '</div>');
                });
        }

        // ── 추가·편집 모달 ───────────────────────────────────────────────────
        function setSelect($sel, value) {
            if ($sel.data('selectpicker')) { $sel.selectpicker('val', value); } else { $sel.val(value); }
        }

        function openEditor(server) {
            $('#form-mcp-server')[0].reset();
            $('#server-unique-id').val(server ? server.unique_id : '');
            $('#server-name').val(server ? server.name : '');
            $('#server-command').val(server ? server.command : '');
            $('#server-env').val(server ? (server.env_json || '') : '');
            setSelect($('#server-scope'), server ? (server.scope || 'general') : 'general');
            $('#server-is-activated').prop('checked', !!(server && server.is_activated));
            $('#btn-delete-server').prop('hidden', !server);
            $modal.modal('show');
        }

        $('#btn-add-server').on('click', function () { openEditor(null); });

        $('#btn-save-server').on('click', function () {
            const id = $('#server-unique-id').val();
            const body = {
                name: $('#server-name').val(),
                command: $('#server-command').val(),
                env_json: $('#server-env').val(),
                scope: $('#server-scope').val(),
                is_activated: $('#server-is-activated').prop('checked')
            };
            call(id ? API_BASE + '/servers/' + encodeURIComponent(id) : API_BASE + '/servers', id ? 'PUT' : 'POST', body)
                .then(function (res) {
                    if (!res.ok) { toast(res.data.message || res.data.error || T.failed, 'error'); return; }
                    toast(id ? T.updated : T.added, 'success');
                    $modal.modal('hide');
                    loadServers();
                });
        });

        // 삭제는 되돌릴 수 없다 — 앱 공용 확인창으로 묻는다.
        $('#btn-delete-server').on('click', function () {
            const id = $('#server-unique-id').val();
            if (!id) { return; }
            window.aotConfirm(T.deleteQ, function () {
                call(API_BASE + '/servers/' + encodeURIComponent(id), 'DELETE').then(function (res) {
                    if (!res.ok) { toast(res.data.message || res.data.error || T.failed, 'error'); return; }
                    toast(T.deleted, 'success');
                    $modal.modal('hide');
                    loadServers();
                });
            });
        });

        loadServers();
    });

})();
