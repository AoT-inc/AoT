/**
 * aot-widget-drawer.js — shared right-side drawer behaviour for setting modals.
 *
 * The dashboard widget-config modal opens as a right-side drawer that pushes the
 * page aside instead of covering it (see dashboard.js UIFixes.widgetDrawerMode).
 * This file is the page-agnostic half of that behaviour so the same drawer can be
 * reused on the Input / Output / Function / GIS-input setting modals, which all
 * share the same Bootstrap 4.6 `.aot-option-modal` shell.
 *
 * All positioning/animation lives in CSS scoped to `.aot-widget-drawer`
 * (aot-modal-modern.css). Here we only:
 *   - toggle `body.aot-widget-drawer-open` (the CSS page-push trigger),
 *   - keep one drawer open at a time (the page stays interactive behind it),
 *   - fire a window resize after the push transition so map/chart widgets reflow.
 *
 * IMPORTANT: do NOT load this on the dashboard — dashboard.js already runs its own
 * widgetDrawerMode (which additionally highlights the matching grid card). Loading
 * both would double-toggle the body class.
 */
(function () {
    'use strict';
    if (typeof window.jQuery === 'undefined') { return; }
    var $ = window.jQuery;

    var DESKTOP_MIN = 768;   // must match CSS @media (min-width: 768px)

    // Let the 0.4s page-push transition finish, then fire a resize so any
    // width-sensitive widget inside/behind the drawer (MapLibre on GIS input,
    // Highcharts, gridstack) re-measures against the changed page width.
    function nudgeResize() {
        setTimeout(function () {
            try { window.dispatchEvent(new Event('resize')); } catch (e) { /* ignore */ }
        }, 450);
    }

    // Resolve which entry-row uid a drawer belongs to. Most pages encode it in the
    // modal id (modal_config_<uid>); the AI-agent page uses one shared modal for every
    // card, so it stamps data-config-uid-target=<uid> on the modal before opening —
    // that explicit attribute wins when present.
    function rowByUid(uid) {
        if (!uid) { return null; }
        return document.querySelector('[data-config-uid="' + (window.CSS && CSS.escape ? CSS.escape(uid) : uid) + '"]');
    }
    function uidForModal(modal) {
        if (!modal) { return null; }
        var t = modal.getAttribute && modal.getAttribute('data-config-uid-target');
        if (t) { return t; }
        var m = /^modal_config_(.+)$/.exec(modal.id || '');
        return m ? m[1] : null;
    }
    function clearRows() {
        document.querySelectorAll('[data-config-uid].aot-config-active').forEach(function (el) {
            el.classList.remove('aot-config-active');
        });
    }
    // Highlight the row being edited, so the page (visible behind the backdrop-less
    // drawer) shows which card the open drawer belongs to.
    function activateRow(modal) {
        clearRows();
        var row = rowByUid(uidForModal(modal));
        if (row) { row.classList.add('aot-config-active'); }
    }
    function deactivateRow(modal) {
        // Remove the highlight from exactly this modal's row (a no-op if a different
        // card is now active — switching straight from card A to B fires B's show,
        // and A's late hidden event must not wipe B's fresh highlight).
        var row = rowByUid(uidForModal(modal));
        if (row) { row.classList.remove('aot-config-active'); }
    }

    // Exposed so a shared-modal page (AI agent) can move the highlight when it swaps
    // the drawer's content between cards without Bootstrap re-firing show.bs.modal.
    window.AoTWidgetDrawer = {
        activateByUid: function (uid) { clearRows(); var r = rowByUid(uid); if (r) { r.classList.add('aot-config-active'); } }
    };

    try {
        $(document).on('show.bs.modal', function (ev) {
            if (!ev.target.classList || !ev.target.classList.contains('aot-widget-drawer')) { return; }
            // One drawer at a time: the page stays interactive behind the drawer
            // (no backdrop), so close any other open drawer first instead of stacking.
            document.querySelectorAll('.aot-widget-drawer.show').forEach(function (other) {
                if (other !== ev.target) { $(other).modal('hide'); }
            });
            if (window.innerWidth >= DESKTOP_MIN) {
                document.body.classList.add('aot-widget-drawer-open');
                nudgeResize();
            }
            activateRow(ev.target);
        });
        $(document).on('hidden.bs.modal', function (ev) {
            if (!ev.target.classList || !ev.target.classList.contains('aot-widget-drawer')) { return; }
            // Release the page-push only once no drawer remains open.
            if (!document.querySelector('.aot-widget-drawer.show')) {
                document.body.classList.remove('aot-widget-drawer-open');
                nudgeResize();
            }
            deactivateRow(ev.target);
        });
    } catch (e) { /* ignore */ }
})();
