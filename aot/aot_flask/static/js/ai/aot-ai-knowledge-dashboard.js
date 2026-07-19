/**
 * aot-ai-knowledge-dashboard.js
 * AI Knowledge Management Dashboard — client-side logic
 *
 * Phase 2: Context Records Live Data Integration
 * Ported from ai_context.html + routes_ai_context.py patterns.
 *
 * Phase 3: Domain Vocabulary Section
 * loadGlossary(), _renderVocabularyRows(), approveGlossaryTerm(),
 * rejectGlossaryTerm(), editGlossaryDefinition()
 */

const AoT_KnowledgeDashboard = (function () {

    // Internal state
    let _currentFilter = 'all';
    let _currentQuery = '';
    let _facilityId = '';
    // Phase 3: pending counts for combined #stat-pending card
    let _contextPendingCount = 0;
    let _glossaryPendingCount = 0;

    // ── _getFacilityId ────────────────────────────────────────
    // Resolve facility_id from URL param or meta tag
    function _getFacilityId() {
        if (_facilityId) return _facilityId;
        const urlParams = new URLSearchParams(window.location.search);
        const fromUrl = urlParams.get('facility_id');
        if (fromUrl) { _facilityId = fromUrl; return _facilityId; }
        const meta = document.querySelector('meta[name="facility-id"]');
        if (meta) { _facilityId = meta.getAttribute('content'); return _facilityId; }
        return '';
    }

    // ── _getCsrfToken ─────────────────────────────────────────
    function _getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    // ── loadOverviewStats ──────────────────────────────────────
    // Fetches counts for all 4 stat cards:
    //   GET /api/v1/ai/context/stats  → {confirmed, pending, system_generated}
    //   GET /api/v1/ai/knowledge/glossary?status=pending → counts.pending
    //   GET /api/v1/ai/library/sources (Phase 4 — graceful fallback if 404)
    // Updates: #stat-confirmed, #stat-pending, #stat-terms, #stat-sources
    function loadOverviewStats() {
        const facilityId = _getFacilityId();

        // Fetch context stats
        const contextStatsUrl = '/api/v1/ai/context/stats' + (facilityId ? '?facility_id=' + encodeURIComponent(facilityId) : '');
        fetch(contextStatsUrl, {
            headers: { 'X-CSRFToken': _getCsrfToken() }
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.status === 'success' && data.counts) {
                var el;
                el = document.getElementById('stat-confirmed');
                if (el) el.textContent = data.counts.user_confirmed || 0;
                // Phase 3: store context pending count and update combined card
                _contextPendingCount = data.counts.pending || 0;
                el = document.getElementById('stat-pending');
                if (el) el.textContent = _contextPendingCount + _glossaryPendingCount;
            }
        })
        .catch(function (err) {
            console.warn('[KnowledgeDashboard] context/stats fetch error:', err);
        });

        // Fetch glossary pending count (Phase 3 endpoint, graceful fallback)
        const glossaryUrl = '/api/v1/ai/knowledge/glossary?status=pending' + (facilityId ? '&facility_id=' + encodeURIComponent(facilityId) : '');
        fetch(glossaryUrl, {
            headers: { 'X-CSRFToken': _getCsrfToken() }
        })
        .then(function (res) {
            if (!res.ok) throw new Error('glossary not available');
            return res.json();
        })
        .then(function (data) {
            var el = document.getElementById('stat-terms');
            if (el && data.counts) {
                el.textContent = data.counts.approved || 0;
            } else if (el && Array.isArray(data.terms)) {
                el.textContent = data.terms.length;
            }
            // Phase 3: update glossary pending count and refresh combined #stat-pending
            if (data.counts) {
                _glossaryPendingCount = data.counts.pending || 0;
                var pendingEl = document.getElementById('stat-pending');
                if (pendingEl) pendingEl.textContent = _contextPendingCount + _glossaryPendingCount;
            }
        })
        .catch(function () {
            var el = document.getElementById('stat-terms');
            if (el && el.textContent === '-') el.textContent = '0';
        });

        // Fetch library sources count (Phase 4 endpoint, graceful fallback if 404)
        const libraryUrl = '/api/v1/ai/library/sources' + (facilityId ? '?facility_id=' + encodeURIComponent(facilityId) : '');
        fetch(libraryUrl, {
            headers: { 'X-CSRFToken': _getCsrfToken() }
        })
        .then(function (res) {
            if (res.status === 404) throw new Error('library not available');
            return res.json();
        })
        .then(function (data) {
            var el = document.getElementById('stat-sources');
            if (el) {
                var sources = data.sources || data;
                if (Array.isArray(sources)) {
                    el.textContent = sources.filter(function (s) { return s.is_active; }).length;
                }
            }
            // Populate library summary section if available
            _updateLibrarySummary(data.sources || data);
        })
        .catch(function () {
            var el = document.getElementById('stat-sources');
            if (el && el.textContent === '-') el.textContent = '0';
        });
    }

    // ── _updateLibrarySummary ─────────────────────────────────
    function _updateLibrarySummary(sources) {
        if (!Array.isArray(sources)) return;
        var activeCount = sources.filter(function (s) { return s.is_active; }).length;
        var errorCount = sources.filter(function (s) { return s.last_sync_status === 'error'; }).length;
        var lastSyncAt = null;
        sources.forEach(function (s) {
            if (s.last_synced_at) {
                var d = new Date(s.last_synced_at);
                if (!lastSyncAt || d > lastSyncAt) lastSyncAt = d;
            }
        });

        var elActive = document.getElementById('lib-active-count');
        var elError = document.getElementById('lib-error-count');
        var elSync = document.getElementById('lib-last-sync');
        if (elActive) elActive.textContent = activeCount;
        if (elError) elError.textContent = errorCount;
        if (elSync) elSync.textContent = lastSyncAt ? lastSyncAt.toLocaleString('ko-KR') : '-';
    }

    // ── loadContextRecords ────────────────────────────────────
    // GET /api/v1/ai/context?facility_id=...&status=...&q=...
    // Renders context-record-cards into #context-records-list
    // Supports filter: all/confirmed/pending review/system generated
    // Supports keyword search on parameter_name / raw_input
    function loadContextRecords(filter, query) {
        _currentFilter = filter || _currentFilter;
        _currentQuery = (query !== undefined) ? query : _currentQuery;

        const facilityId = _getFacilityId();
        let url = '/api/v1/ai/context';
        const params = [];
        if (facilityId) params.push('facility_id=' + encodeURIComponent(facilityId));
        if (_currentFilter && _currentFilter !== 'all') params.push('status=' + encodeURIComponent(_currentFilter));
        if (_currentQuery) params.push('q=' + encodeURIComponent(_currentQuery));
        if (params.length) url += '?' + params.join('&');

        const listEl = document.getElementById('context-records-list');
        if (listEl) listEl.innerHTML = '<div class="text-muted" style="padding:1.5rem 0;">' + window._('Loading...') + '</div>';

        fetch(url, {
            headers: { 'X-CSRFToken': _getCsrfToken() }
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            var records = data.records || (Array.isArray(data) ? data : []);
            _renderContextList(records);
        })
        .catch(function (err) {
            console.error('[KnowledgeDashboard] loadContextRecords error:', err);
            if (listEl) listEl.innerHTML = '<div class="text-danger" style="padding:1.5rem 0;">' + window._('Failed to load data.') + '</div>';
        });
    }

    // ── _renderContextList ────────────────────────────────────
    function _renderContextList(records) {
        const listEl = document.getElementById('context-records-list');
        if (!listEl) return;

        if (!records || records.length === 0) {
            listEl.innerHTML = '<p class="text-muted" style="padding:1.5rem 0;">' + window._('No context records registered.') + '</p>';
            return;
        }

        // Client-side keyword filter (parameter_name or value/raw_input)
        var filtered = records;
        if (_currentQuery) {
            var q = _currentQuery.toLowerCase();
            filtered = records.filter(function (r) {
                return (r.parameter_name || '').toLowerCase().includes(q) ||
                       (r.value || '').toLowerCase().includes(q) ||
                       (r.raw_input || '').toLowerCase().includes(q);
            });
        }
        // Client-side status filter (if API doesn't filter)
        if (_currentFilter && _currentFilter !== 'all') {
            filtered = filtered.filter(function (r) {
                return r.context_state === _currentFilter;
            });
        }

        if (filtered.length === 0) {
            listEl.innerHTML = '<p class="text-muted" style="padding:1.5rem 0;">' + window._('No records match the criteria.') + '</p>';
            return;
        }

        listEl.innerHTML = filtered.map(renderContextCard).join('');
    }

    // ── renderContextCard ─────────────────────────────────────
    // Build card HTML: parameter_name, context_state badge, source, raw_input (truncated 100 chars), confirmer/time
    // Card actions: confirm / reject / delete
    function renderContextCard(record) {
        var stateLabel = {
            'system_generated': window._('System default'),
            'pending': window._('Review needed'),
            'user_confirmed': window._('Confirmed')
        }[record.context_state] || record.context_state;

        var badgeClass = 'badge-' + (record.context_state || 'pending');

        var value = record.value || record.raw_input || '';
        var truncated = value.length > 100 ? value.substring(0, 100) + '...' : value;

        var confirmedLine = '';
        if (record.confirmed_at) {
            confirmedLine = '<div class="text-muted" style="font-size:0.85em;margin-top:0.5em;">' + window._('Confirmed') + ': ' + record.confirmed_at + '</div>';
        }

        var confirmRejectBtns = '';
        if (record.context_state !== 'user_confirmed') {
            confirmRejectBtns =
                '<button type="button" class="btn btn-sm btn-success" ' +
                'onclick="AoT_KnowledgeDashboard.confirmRecord(' + record.id + ')">' +
                window._('Confirm') + '</button> ' +
                '<button type="button" class="btn btn-sm btn-warning" ' +
                'onclick="AoT_KnowledgeDashboard.rejectRecord(' + record.id + ')">' +
                window._('Reject') + '</button> ';
        }

        return '<div class="context-record-card" id="kd-record-card-' + record.id + '">' +
            '<div class="context-record-header">' +
            '<div>' +
            '<strong>' + _escapeHtml(record.parameter_name) + '</strong>' +
            '<span class="context-state-badge ' + badgeClass + '" id="kd-badge-' + record.id + '">' +
            stateLabel + '</span>' +
            '</div>' +
            '</div>' +
            '<div class="context-value">' + _escapeHtml(truncated) + '</div>' +
            '<div class="context-source">' + _escapeHtml(record.source || '') + '</div>' +
            confirmedLine +
            '<div class="context-record-actions" style="margin-top:0.75em;">' +
            confirmRejectBtns +
            '<button type="button" class="btn btn-sm btn-danger" ' +
            'onclick="AoT_KnowledgeDashboard.deleteRecord(' + record.id + ')">' +
            window._('Delete') + '</button>' +
            '</div>' +
            '</div>';
    }

    // ── _escapeHtml ───────────────────────────────────────────
    function _escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // ── _apiAction ────────────────────────────────────────────
    // Shared PATCH/DELETE helper
    function _apiAction(method, url, body, onSuccess) {
        var opts = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': _getCsrfToken()
            }
        };
        if (body) opts.body = JSON.stringify(body);

        fetch(url, opts)
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.status === 'success' || data.data) {
                onSuccess(data);
                loadOverviewStats();
            } else {
                var msg = (data.messages && data.messages.error) ? data.messages.error.join(', ') : window._('An error occurred.');
                if (window.showToast) window.showToast(msg, 'error');
            }
        })
        .catch(function (err) {
            console.error('[KnowledgeDashboard] API action error:', err);
            if (window.showToast) window.showToast(window._('A server error occurred.'), 'error');
        });
    }

    // ── confirmRecord ─────────────────────────────────────────
    // PATCH /api/v1/ai/context/<record_id>  → {action: confirm}
    // On success: update badge + reload stats
    function confirmRecord(recordId) {
        _apiAction('PATCH', '/api/v1/ai/context/' + recordId, { action: 'confirm' }, function () {
            // Update badge inline
            var badge = document.getElementById('kd-badge-' + recordId);
            if (badge) {
                badge.className = 'context-state-badge badge-user_confirmed';
                badge.textContent = window._('Confirmed');
            }
            // Hide confirm/reject buttons
            var card = document.getElementById('kd-record-card-' + recordId);
            if (card) {
                var btns = card.querySelectorAll('.btn-success, .btn-warning');
                btns.forEach(function (b) { b.style.display = 'none'; });
            }
            if (window.showToast) window.showToast(window._('Confirmed successfully.'), 'success');
        });
    }

    // ── rejectRecord ──────────────────────────────────────────
    // PATCH /api/v1/ai/context/<record_id>  → {action: reject}
    // On success: update badge + reload stats
    function rejectRecord(recordId) {
        _apiAction('PATCH', '/api/v1/ai/context/' + recordId, { action: 'reject' }, function () {
            var badge = document.getElementById('kd-badge-' + recordId);
            if (badge) {
                badge.className = 'context-state-badge badge-pending';
                badge.textContent = window._('Review needed');
            }
            if (window.showToast) window.showToast(window._('Rejected successfully.'), 'info');
        });
    }

    // ── deleteRecord ──────────────────────────────────────────
    // DELETE /api/v1/ai/context/<record_id>
    // On success: remove card from DOM + reload stats
    function deleteRecord(recordId) {
        if (!confirm(window._('Delete this context record?'))) return;
        _apiAction('DELETE', '/api/v1/ai/context/' + recordId, null, function () {
            var card = document.getElementById('kd-record-card-' + recordId);
            if (card) {
                card.style.transition = 'opacity 0.3s';
                card.style.opacity = '0';
                setTimeout(function () { card.remove(); }, 310);
            }
            if (window.showToast) window.showToast(window._('Deleted successfully.'), 'success');
        });
    }

    // ── filterContextRecords ──────────────────────────────────
    // Public: called by filter button onclick
    function filterContextRecords(filter) {
        _currentFilter = filter;

        // Update active button style
        var filterBtns = document.querySelectorAll('.context-filter-bar .filter-btn');
        filterBtns.forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-filter') === filter);
        });

        loadContextRecords(filter, _currentQuery);
    }

    // ── searchContextRecords ──────────────────────────────────
    // Public: called by search input oninput
    function searchContextRecords(query) {
        _currentQuery = query;
        loadContextRecords(_currentFilter, query);
    }

    // ── initDashboard ─────────────────────────────────────────
    // Called on DOMContentLoaded
    // Wires filter buttons, search input, add-record button
    // Calls loadOverviewStats() + loadContextRecords()
    function initDashboard() {
        // Wire filter buttons
        var filterBtns = document.querySelectorAll('.context-filter-bar .filter-btn');
        filterBtns.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var filter = btn.getAttribute('data-filter') || 'all';
                filterContextRecords(filter);
            });
        });

        // Wire search input
        var searchInput = document.getElementById('context-search');
        if (searchInput) {
            searchInput.addEventListener('input', function () {
                searchContextRecords(this.value);
            });
        }

        // Initial load
        loadOverviewStats();
        loadContextRecords('all', '');
        loadGlossary();
    }

    // ──────────────────────────────────────────────────────────────
    // Phase 3: Domain Vocabulary Section
    // ──────────────────────────────────────────────────────────────

    // ── loadGlossary ──────────────────────────────────────────────
    // GET /api/v1/ai/knowledge/glossary
    // Renders terms into #vocabulary-tbody
    function loadGlossary() {
        var facilityId = _getFacilityId();
        var url = '/api/v1/ai/knowledge/glossary';
        var params = [];
        if (facilityId) params.push('facility_id=' + encodeURIComponent(facilityId));
        if (params.length) url += '?' + params.join('&');

        var tbody = document.getElementById('vocabulary-tbody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="5" class="vocabulary-empty">' + window._('Loading...') + '</td></tr>';
        }

        fetch(url, {
            headers: { 'X-CSRFToken': _getCsrfToken() }
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.status === 'success') {
                _renderVocabularyRows(data.terms || []);
                // Update pending count from glossary response counts
                if (data.counts) {
                    _glossaryPendingCount = data.counts.pending || 0;
                    var pendingEl = document.getElementById('stat-pending');
                    if (pendingEl) pendingEl.textContent = _contextPendingCount + _glossaryPendingCount;
                }
            }
        })
        .catch(function (err) {
            console.error('[KnowledgeDashboard] loadGlossary error:', err);
            var tbody = document.getElementById('vocabulary-tbody');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="5" class="vocabulary-empty text-danger">' + window._('Failed to load data.') + '</td></tr>';
            }
        });
    }

    // ── _renderVocabularyRows ─────────────────────────────────────
    // Builds table rows from terms array.
    // pending  → approve (inline definition edit) + reject buttons
    // approved → edit definition + delete buttons
    // rejected → delete button only
    function _renderVocabularyRows(terms) {
        var tbody = document.getElementById('vocabulary-tbody');
        if (!tbody) return;

        if (!terms || terms.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="vocabulary-empty">' + window._('No domain terms registered.') + '</td></tr>';
            return;
        }

        var rows = terms.map(function (t) {
            var badge = '';
            var actions = '';
            var termIdSafe = String(t.term_id);

            if (t.status === 'approved') {
                badge = '<span class="badge badge-success">' + window._('Approved') + '</span>';
                actions =
                    '<button type="button" class="btn btn-sm btn-outline-secondary" ' +
                    'onclick="AoT_KnowledgeDashboard.editGlossaryDefinition(\'' + termIdSafe + '\')">' +
                    window._('Edit definition') + '</button> ' +
                    '<button type="button" class="btn btn-sm btn-outline-danger" ' +
                    'onclick="AoT_KnowledgeDashboard.rejectGlossaryTerm(\'' + termIdSafe + '\')">' +
                    window._('Delete') + '</button>';
            } else if (t.status === 'pending') {
                badge = '<span class="badge badge-warning">' + window._('Pending review') + '</span>';
                actions =
                    '<button type="button" class="btn btn-sm btn-success" ' +
                    'onclick="AoT_KnowledgeDashboard.approveGlossaryTerm(\'' + termIdSafe + '\', null)">' +
                    window._('Approve') + '</button> ' +
                    '<button type="button" class="btn btn-sm btn-outline-danger" ' +
                    'onclick="AoT_KnowledgeDashboard.rejectGlossaryTerm(\'' + termIdSafe + '\')">' +
                    window._('Reject') + '</button>';
            } else {
                // rejected
                badge = '<span class="badge badge-secondary">' + window._('Rejected') + '</span>';
                actions =
                    '<button type="button" class="btn btn-sm btn-outline-danger" ' +
                    'onclick="AoT_KnowledgeDashboard.rejectGlossaryTerm(\'' + termIdSafe + '\')">' +
                    window._('Delete') + '</button>';
            }

            var createdAt = t.created_at ? t.created_at.replace('T', ' ').substring(0, 16) : '-';

            return '<tr id="vocab-row-' + termIdSafe + '">' +
                '<td><strong>' + _escapeHtml(t.term) + '</strong></td>' +
                '<td id="vocab-def-' + termIdSafe + '">' + _escapeHtml(t.definition || '') + '</td>' +
                '<td>' + badge + '</td>' +
                '<td>' + _escapeHtml(createdAt) + '</td>' +
                '<td>' + actions + '</td>' +
                '</tr>';
        });

        tbody.innerHTML = rows.join('');
    }

    // ── approveGlossaryTerm ───────────────────────────────────────
    // POST /api/v1/ai/knowledge/approve  {term_id, status: approved, definition}
    // If definition is null, prompt the user to enter or confirm existing definition.
    function approveGlossaryTerm(termId, definition) {
        var defCell = document.getElementById('vocab-def-' + termId);
        var existingDef = defCell ? defCell.textContent.trim() : '';
        var finalDef = definition;

        if (!finalDef) {
            finalDef = window.prompt(window._('Enter or confirm the definition to approve:'), existingDef);
            if (finalDef === null) return; // User cancelled
        }

        fetch('/api/v1/ai/knowledge/approve', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': _getCsrfToken()
            },
            body: JSON.stringify({ term_id: termId, status: 'approved', definition: finalDef })
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.status === 'success') {
                if (window.showToast) window.showToast(window._('Approved successfully.'), 'success');
                loadGlossary();
                loadOverviewStats();
            } else {
                if (window.showToast) window.showToast(window._('An error occurred during approval.'), 'error');
            }
        })
        .catch(function (err) {
            console.error('[KnowledgeDashboard] approveGlossaryTerm error:', err);
            if (window.showToast) window.showToast(window._('A server error occurred.'), 'error');
        });
    }

    // ── rejectGlossaryTerm ────────────────────────────────────────
    // POST /api/v1/ai/knowledge/approve  {term_id, status: rejected}
    // Also used as "delete" action for approved/rejected rows via status=rejected.
    function rejectGlossaryTerm(termId) {
        if (!confirm(window._('Reject this term?'))) return;

        fetch('/api/v1/ai/knowledge/approve', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': _getCsrfToken()
            },
            body: JSON.stringify({ term_id: termId, status: 'rejected' })
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.status === 'success') {
                if (window.showToast) window.showToast(window._('Rejected successfully.'), 'info');
                loadGlossary();
                loadOverviewStats();
            } else {
                if (window.showToast) window.showToast(window._('An error occurred during processing.'), 'error');
            }
        })
        .catch(function (err) {
            console.error('[KnowledgeDashboard] rejectGlossaryTerm error:', err);
            if (window.showToast) window.showToast(window._('A server error occurred.'), 'error');
        });
    }

    // ── editGlossaryDefinition ────────────────────────────────────
    // Prompts user for a new definition then re-approves with updated text.
    function editGlossaryDefinition(termId) {
        var defCell = document.getElementById('vocab-def-' + termId);
        var existingDef = defCell ? defCell.textContent.trim() : '';
        var newDef = window.prompt(window._('Enter a new definition:'), existingDef);
        if (newDef === null || newDef.trim() === '') return;
        approveGlossaryTerm(termId, newDef.trim());
    }

    return {
        init: initDashboard,
        loadOverviewStats: loadOverviewStats,
        loadContextRecords: loadContextRecords,
        filterContextRecords: filterContextRecords,
        searchContextRecords: searchContextRecords,
        renderContextCard: renderContextCard,
        confirmRecord: confirmRecord,
        rejectRecord: rejectRecord,
        deleteRecord: deleteRecord,
        // Phase 3: glossary actions
        loadGlossary: loadGlossary,
        approveGlossaryTerm: approveGlossaryTerm,
        rejectGlossaryTerm: rejectGlossaryTerm,
        editGlossaryDefinition: editGlossaryDefinition
    };

})();

document.addEventListener('DOMContentLoaded', function () {
    AoT_KnowledgeDashboard.init();
});
