/**
 * Dashboard Utility Functions & Logic
 * Refactored for modularity and modern ES6+ standards.
 */

// Global utility: Return formatted timestamp from epoch
// Used in multiple widgets
window.epoch_to_timestamp = function (epoch) {
    const date = new Date(parseFloat(epoch));
    const pad = (n) => n.toString().padStart(2, '0');

    // Format: M/D H:mm:ss
    return `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};


/**
 * Module: Sticky Header Logic
 * Handles the sticky behavior of the dashboard toolbar and surface color synchronization.
 */
const StickyHeader = {
    init() {
        this.stickyEl = document.getElementById('dash-sticky');
        this.rafId = null;

        if (!this.stickyEl) return;

        // Initial setup
        this.computeTop();
        this.setSurfaceBg();

        // Event listeners
        window.addEventListener('resize', () => {
            this.scheduleCompute();
            this.setSurfaceBg();
        }, { passive: true });

        window.addEventListener('scroll', () => this.scheduleCompute(), { passive: true });

        // Boostrap collapse events can change page height/layout
        document.addEventListener('shown.bs.collapse', () => this.scheduleCompute());
        document.addEventListener('hidden.bs.collapse', () => this.scheduleCompute());
    },

    computeTop() {
        try {
            // Toggle roomier padding if scrolled down (roughly when navbar might hide or we are "stuck")
            const scrollY = window.pageYOffset || document.documentElement.scrollTop;
            const nowStuck = scrollY > 50;

            if (this.stickyEl.__aot_is_stuck !== nowStuck) {
                this.stickyEl.classList.toggle('is-stuck', nowStuck);
                this.stickyEl.__aot_is_stuck = nowStuck;
            }
        } catch (e) { console.warn('StickyHeader compute error:', e); }
    },

    scheduleCompute() {
        if (this.rafId) return;
        this.rafId = requestAnimationFrame(() => {
            this.rafId = null;
            this.computeTop();
        });
    },

    setSurfaceBg() {
        try {
            let bodyBg = window.getComputedStyle(document.body).backgroundColor;
            // Fallback if transparent: try html element background
            if (!bodyBg || bodyBg === 'rgba(0, 0, 0, 0)' || bodyBg === 'transparent') {
                const htmlBg = window.getComputedStyle(document.documentElement).backgroundColor;
                bodyBg = (htmlBg && htmlBg !== 'rgba(0, 0, 0, 0)' && htmlBg !== 'transparent') ? htmlBg : '#fff';
            }
            document.documentElement.style.setProperty('--aot-surface', bodyBg);
        } catch (e) { /* ignore */ }
    }
};

/**
 * Module: Dashboard Grid Logic
 * Wrapper around GridStack initialization and event handling.
 */
const DashboardGrid = {
    isSyncing: false,

    init() {
        // Configuration
        const cellHeight = (typeof window.AOT_GRID_CELL_HEIGHT !== 'undefined') ? window.AOT_GRID_CELL_HEIGHT : 150;
        const isLocked = (typeof window.AOT_DASHBOARD_LOCKED !== 'undefined') && window.AOT_DASHBOARD_LOCKED;
        
        const options = {
            cellHeight: cellHeight,
            column: 24, // Always boot in 24 to read original HTML attributes correctly
            resizable: { handles: 'se' },
            draggable: {
                // Limit dragging to the hamburger (grip) handle area only — prevent dragging the whole title/header
                handle: '.widget-drag-handle',
                cancel: 'input, textarea, select, button, a, .no-drag, .modal, .dropdown-menu, .list-group, .table, .form-control'
            },
            alwaysShowResizeHandle: isLocked ? 'mobile' : true,
            float: false,
            disableOneColumnMode: true, 
            oneColumnSize: 0
            // [Fix] Removed columnOpts to prevent automatic scaling conflicts
        };

        // Initialize GridStack
        window.grid = GridStack.init(options);

        // [Fix] Initial Layout Sync
        this.syncLayout();

        // Reveal grid after layout is applied to avoid FOUC (squished -> expand flash)
        if (window.grid && window.grid.el) {
            window.grid.el.style.visibility = 'visible';
        }

        // [Fix] Manual Resize Handling (Debounced)
        let resizeTimer;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => this.syncLayout(), 100);
        });

        // Event: Resize Stop (Trigger Global Resize & Sync data-desktop attributes)
        window.grid.on('resizestop', (event, el) => {
            const widgetId = el.getAttribute('gs-id');
            console.log(`Dashboard: Widget ${widgetId} resized. Triggering global resize...`);
            
            // 1. Trigger global resize to tell all libraries (Highcharts, etc) to reflow
            window.dispatchEvent(new Event('resize'));

            // 2. Sync data-desktop attributes — desktop layout is the source of truth,
            //    so only update it from genuine 24-column edits. Mobile (2-col) positions
            //    are a derived view and must never overwrite the saved desktop layout.
            if (window.grid.getColumn() === 24) {
                el.setAttribute('data-desktop-w', el.getAttribute('gs-w'));
                el.setAttribute('data-desktop-h', el.getAttribute('gs-h'));
                el.setAttribute('data-desktop-x', el.getAttribute('gs-x'));
                el.setAttribute('data-desktop-y', el.getAttribute('gs-y'));
            }
        });

        // Event: Drag Stop (Sync data-desktop-x/y & Trigger global resize)
        window.grid.on('dragstop', (event, el) => {
            // Only persist desktop coords from genuine 24-column edits (see resizestop).
            if (window.grid.getColumn() === 24) {
                el.setAttribute('data-desktop-x', el.getAttribute('gs-x'));
                el.setAttribute('data-desktop-y', el.getAttribute('gs-y'));
            }
            window.dispatchEvent(new Event('resize'));
        });

        // If not locked, enable save and UI interactions
        if (!isLocked) {
            this.enableEditing();
        }
    },

    /**
     * [Fix] Synchronize layout between Desktop (24) and Mobile (2)
     * Handles column switching and width mapping without relying on Gridstack scaling.
     */
    syncLayout() {
        if (!window.grid) return;

        const isMobile = window.innerWidth <= 768;
        const targetColumn = isMobile ? 2 : 24;
        const currentColumn = window.grid.getColumn();

        if (currentColumn === targetColumn) return;

        this.isSyncing = true;

        if (targetColumn === 2) {
            // Mobile transition.
            // batchUpdate + float manipulation causes a flash where the DOM is exposed in an intermediate state.
            // Hide the grid during the transition and replace it with direct packing that applies immediately without batchUpdate.
            const gridEl = window.grid.el;
            const wasVisible = gridEl.style.visibility !== 'hidden';
            if (wasVisible) gridEl.style.visibility = 'hidden';

            window.grid.column(2, 'none');

            // Sort by desktop reading order (y→x)
            const mobileItems = window.grid.getGridItems().sort((a, b) => {
                const ay = parseInt(a.getAttribute('data-desktop-y') || '0');
                const by = parseInt(b.getAttribute('data-desktop-y') || '0');
                if (ay !== by) return ay - by;
                return parseInt(a.getAttribute('data-desktop-x') || '0') -
                       parseInt(b.getAttribute('data-desktop-x') || '0');
            });

            // 2-column direct packing: since there is no overlap, GridStack collision resolution does not intervene.
            // Calling update() without batchUpdate places each widget at the correct position immediately.
            let cursorY = 0, cursorX = 0, rowMaxH = 0;
            mobileItems.forEach(el => {
                const forceFullWidth = el.getAttribute('data-mobile-full-width') === '1';
                const desktopW = parseInt(el.getAttribute('data-desktop-w') || '24');
                const h = parseInt(el.getAttribute('gs-h') || '1');
                const isFull = forceFullWidth || desktopW > 12;

                if (isFull) {
                    // If a partial row is in progress, close it and move to the next row
                    if (cursorX !== 0) { cursorY += rowMaxH; cursorX = 0; rowMaxH = 0; }
                    window.grid.update(el, { x: 0, y: cursorY, w: 2, h: h });
                    cursorY += h;
                } else if (cursorX === 0) {
                    // Left cell of the row
                    window.grid.update(el, { x: 0, y: cursorY, w: 1, h: h });
                    cursorX = 1;
                    rowMaxH = h;
                } else {
                    // Right cell of the row → close the row
                    window.grid.update(el, { x: 1, y: cursorY, w: 1, h: h });
                    cursorY += Math.max(rowMaxH, h);
                    cursorX = 0;
                    rowMaxH = 0;
                }
            });

            // If the last row only has a left widget, update cursorY
            if (cursorX !== 0) { cursorY += rowMaxH; }

            if (wasVisible) gridEl.style.visibility = 'visible';
        } else {
            // Desktop transition: restore positions in float mode, then disable float.
            window.grid.batchUpdate(true);
            window.grid.column(24, 'none');
            const prevFloat = window.grid.getFloat();
            window.grid.float(true);

            const items = window.grid.getGridItems().sort((a, b) => {
                const ay = parseInt(a.getAttribute('data-desktop-y') || '0');
                const by = parseInt(b.getAttribute('data-desktop-y') || '0');
                if (ay !== by) return ay - by;
                return parseInt(a.getAttribute('data-desktop-x') || '0') -
                       parseInt(b.getAttribute('data-desktop-x') || '0');
            });

            items.forEach(el => {
                const dx = el.getAttribute('data-desktop-x');
                const dy = el.getAttribute('data-desktop-y');
                const dw = el.getAttribute('data-desktop-w');
                const dh = el.getAttribute('data-desktop-h');

                if (dx !== null && dy !== null && dw !== null) {
                    window.grid.update(el, {
                        x: parseInt(dx),
                        y: parseInt(dy),
                        w: parseInt(dw),
                        h: dh ? parseInt(dh) : parseInt(el.getAttribute('gs-h'))
                    });
                }
            });

            window.grid.float(prevFloat);
            window.grid.batchUpdate(false);
        }
        // Clear syncing flag after a small delay to ensure any pending change events are ignored
        setTimeout(() => { this.isSyncing = false; }, 200);

        // [Fix] Trigger Global Resize after GridStack CSS transition completes (0.3s).
        // Firing immediately catches mid-animation widths; Highcharts reflows to the wrong size.
        setTimeout(() => window.dispatchEvent(new Event('resize')), 350);
    },

    enableEditing() {
        // Mark grid as editable so CSS can show resize handles
        if (window.grid && window.grid.el) {
            window.grid.el.classList.add('dashboard-unlocked');
        }

        // Persist layout on change
        window.grid.on('change', (event, items) => {
            // Block saving during the sync/layout transition.
            if (this.isSyncing) {
                console.log("Dashboard: Save suppressed (syncing).");
                return;
            }

            // Mobile (2-col) is a derived view, not a saved state. Never overwrite the
            // desktop source-of-truth or persist anything while not in 24-column mode —
            // doing so jumbles the layout when the window is restored to desktop width.
            if (window.grid.getColumn() !== 24) {
                console.log("Dashboard: Save suppressed (mobile layout).");
                return;
            }

            // Sync data-desktop attributes for all changed items (desktop mode only)
            if (items) {
                items.forEach(item => {
                    const el = item.el;
                    el.setAttribute('data-desktop-w', item.w);
                    el.setAttribute('data-desktop-h', item.h);
                    el.setAttribute('data-desktop-x', item.x);
                    el.setAttribute('data-desktop-y', item.y);
                });
            }

            try {
                // Save desktop coordinates (we are guaranteed to be in 24-column mode here).
                const savePayload = window.grid.getGridItems().map(el => ({
                    id: el.getAttribute('gs-id'),
                    x: parseInt(el.getAttribute('data-desktop-x') || el.getAttribute('gs-x')),
                    y: parseInt(el.getAttribute('data-desktop-y') || el.getAttribute('gs-y')),
                    w: parseInt(el.getAttribute('data-desktop-w') || el.getAttribute('gs-w')),
                    h: parseInt(el.getAttribute('data-desktop-h') || el.getAttribute('gs-h'))
                }));

                const payload = JSON.stringify(savePayload, null, '  ');
                $.ajax({
                    url: "/save_dashboard_layout",
                    type: "POST",
                    data: payload,
                    contentType: "application/json; charset=utf-8",
                    success: () => { /* silent success */ },
                    error: () => {
                        window.showToast(_('layout_save_fail'), 'error');
                    }
                });
            } catch (e) {
                window.showToast(_('layout_serialize_error'), 'error');
            }
        });

        // Widget Add Hook
        const widgetTypeSelect = document.getElementById('widget_type');
        if (widgetTypeSelect) {
            widgetTypeSelect.addEventListener('change', function () {
                const containers = document.getElementsByClassName("add_dashboard_widget");
                Array.from(containers).forEach(el => el.style.display = "none");

                if (this.value) {
                    const target = document.getElementById(this.value);
                    if (target) {
                        target.style.display = "block";
                        // Lazy-hydrate the option-heavy add-widget body on first reveal
                        // (kept in a <template> so its hidden selects/options stay out of
                        // the live DOM — see UIFixes.hydrateLazyModalBodies for rationale).
                        const tpl = target.querySelector('template.aot-lazy-add-body');
                        if (tpl) {
                            tpl.parentNode.insertBefore(tpl.content.cloneNode(true), tpl);
                            tpl.remove();
                            if (window.jQuery && window.jQuery.fn.selectpicker) {
                                window.jQuery(target).find('.selectpicker').selectpicker();
                            }
                        }
                        target.scrollIntoView({ behavior: 'smooth' });
                    }
                }
            });
        }
    }
};

/**
 * Module: Dashboard Tabs Logic
 * Handles tab ordering, drag-and-drop reordering, and visibility.
 */
const DashboardTabs = {
    key: 'dashboard_order_v1',
    containerId: 'dash-tabs',

    init() {
        const container = document.getElementById(this.containerId);
        if (!container) return;
        this.container = container;

        this.syncOrder();
        this.initDragAndDrop();
        this.ensureActiveTabVisible();
    },

    // Server order is source of truth; sync localStorage to match DOM
    syncOrder() {
        const domIds = this.getDirectTabs().map(ch => ch.dataset.id);
        try { localStorage.setItem(this.key, JSON.stringify(domIds)); } catch (e) { /* ignore */ }
    },

    getDirectTabs() {
        return Array.from(this.container.querySelectorAll(':scope > .dash-tab'));
    },

    initDragAndDrop() {
        let dragSrc = null;
        let isDragging = false;

        // Prevent click events while dragging
        this.container.addEventListener('click', (ev) => {
            if (isDragging) {
                ev.preventDefault();
                ev.stopPropagation();
            }
        }, true);

        // Drag Start
        this.container.addEventListener('dragstart', (ev) => {
            const tab = ev.target.closest('.dash-tab');
            if (!tab || !this.container.contains(tab)) return;
            if (!this.getDirectTabs().includes(tab)) return;

            dragSrc = tab;
            isDragging = true;
            tab.classList.add('dragging');

            // Ghost image
            const anchor = tab.querySelector('a');
            const imgEl = anchor || tab;
            if (ev.dataTransfer) {
                try {
                    ev.dataTransfer.setDragImage(imgEl, imgEl.offsetWidth / 2, imgEl.offsetHeight / 2);
                } catch (e) { }
                ev.dataTransfer.setData('text/plain', tab.dataset.id || 'drag');
                ev.dataTransfer.effectAllowed = 'move';
            }
        });

        // Drag Over
        this.container.addEventListener('dragover', (ev) => {
            if (!dragSrc) return;
            ev.preventDefault();
            if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'move';

            const over = ev.target.closest('.dash-tab');
            this.getDirectTabs().forEach(t => t.classList.remove('drop-target'));
            if (over && over !== dragSrc) over.classList.add('drop-target');
        });

        // Drop
        this.container.addEventListener('drop', (ev) => {
            if (!dragSrc) return;
            ev.preventDefault();
            this.getDirectTabs().forEach(t => t.classList.remove('drop-target'));

            const target = ev.target.closest('.dash-tab');
            if (!target || target === dragSrc || !this.getDirectTabs().includes(target)) return;

            const rect = target.getBoundingClientRect();
            // Determine insertion point (before or after)
            const insertBefore = (ev.clientX - rect.left) < (rect.width / 2);
            this.container.insertBefore(dragSrc, insertBefore ? target : target.nextSibling);

            // Save new order
            const ids = this.getDirectTabs().map(ch => ch.dataset.id);
            try { localStorage.setItem(this.key, JSON.stringify(ids)); } catch (e) { }

            $.ajax({
                url: "/save_dashboard_order",
                type: "POST",
                data: JSON.stringify(ids),
                contentType: "application/json; charset=utf-8"
            })
                .fail(() => { window.showToast(_('dashboard_order_save_fail'), 'error'); })
                .always(() => { setTimeout(() => { isDragging = false; }, 80); });
        });

        // Drag End
        this.container.addEventListener('dragend', () => {
            this.getDirectTabs().forEach(t => t.classList.remove('drop-target'));
            if (dragSrc) dragSrc.classList.remove('dragging');

            setTimeout(() => { isDragging = false; }, 50);
            dragSrc = null;
        });
    },

    ensureActiveTabVisible() {
        setTimeout(() => {
            const active = this.container.querySelector('.dash-tab.active');
            if (!active) return;
            try {
                active.scrollIntoView({ behavior: 'instant', block: 'nearest', inline: 'center' });
            } catch (e) {
                // Fallback for older browsers
                const tabRect = active.getBoundingClientRect();
                const contRect = this.container.getBoundingClientRect();
                const current = this.container.scrollLeft;
                const target = current + (tabRect.left - contRect.left) + (tabRect.width / 2) - (contRect.width / 2);
                this.container.scrollLeft = Math.max(0, target);
            }
        }, 0);
    }
};

/**
 * Module: UI Fixes
 * Miscellaneous UI adjustments.
 */
const UIFixes = {
    init() {
        this.fixModalZIndex();
        this.hydrateLazyModalBodies();
        this.fixSelectpickerInHiddenModal();
        this.widgetDrawerMode();
    },

    // Widget settings modals (.aot-widget-drawer) open as a right-side drawer that
    // pushes the dashboard aside instead of covering it, so a widget can be watched
    // updating live while its options change. The CSS does the positioning; here we
    // just toggle body.aot-widget-drawer-open (which applies the page push) and,
    // after the push transition, fire a resize so Highcharts widgets reflow to the
    // narrower dashboard. Mirrors the AI chat drawer (aot-ai-global.js).
    widgetDrawerMode() {
        var DESKTOP_MIN = 768;   // must match the CSS @media (min-width: 768px)
        var self = this;
        try {
            $(document).on('show.bs.modal', function (ev) {
                if (!ev.target.classList || !ev.target.classList.contains('aot-widget-drawer')) { return; }
                // One drawer at a time: the dashboard stays interactive behind the
                // drawer (no backdrop), so a user can click another widget's gear
                // while one is open. Close any other open widget drawer first so they
                // don't stack and need closing one by one.
                document.querySelectorAll('.aot-widget-drawer.show').forEach(function (other) {
                    if (other !== ev.target) { $(other).modal('hide'); }
                });
                if (window.innerWidth >= DESKTOP_MIN) {
                    document.body.classList.add('aot-widget-drawer-open');
                    self._nudgeResize();
                }
            });
            $(document).on('hidden.bs.modal', function (ev) {
                if (!ev.target.classList || !ev.target.classList.contains('aot-widget-drawer')) { return; }
                // Only release the push once no widget drawer remains open.
                if (!document.querySelector('.aot-widget-drawer.show')) {
                    document.body.classList.remove('aot-widget-drawer-open');
                    self._nudgeResize();
                }
            });
        } catch (e) { /* ignore */ }
    },

    // Let the 0.4s page-push transition finish, then trigger a window resize so
    // Highcharts (gauge/graph) reflow to the changed dashboard width.
    _nudgeResize() {
        setTimeout(function () {
            try { window.dispatchEvent(new Event('resize')); } catch (e) { /* ignore */ }
        }, 450);
    },

    // Lazy-hydrate option-heavy widget-config modal bodies. Each body is shipped
    // inside <template class="aot-lazy-modal-body"> so its hundreds of hidden
    // <select>/<option> nodes stay OUT of the live DOM until the modal is opened.
    // Chrome's built-in autofill re-scans every form field in the live DOM on each
    // keystroke; with ~2600 hidden option nodes across all widget modals, typing in
    // any field (e.g. the global AI chat box) stalled badly. Cloning on first open
    // keeps at most one modal's worth of options live at a time. The bodies contain
    // no inline <script> (verified across all *_configure_options templates), so a
    // plain clone suffices; inline onchange/onclick attributes survive the clone.
    // selectpicker is initialised on the injected content (the shown.bs.modal
    // handler below then refreshes it).
    hydrateLazyModalBodies() {
        try {
            $(document).on('show.bs.modal', (ev) => {
                const tpl = ev.target.querySelector('template.aot-lazy-modal-body');
                if (!tpl) return;                       // not lazy, or already hydrated
                tpl.parentNode.appendChild(tpl.content.cloneNode(true));
                tpl.remove();
                if ($.fn.selectpicker) {
                    $(ev.target).find('.selectpicker').selectpicker();
                }
            });
        } catch (e) { /* ignore */ }
    },

    // Ensure widget/dashboard modals are attached to body to prevent z-index clipping
    fixModalZIndex() {
        const moveModals = () => {
            if (typeof $ === 'undefined') return;
            $('.modal').each(function () {
                const $m = $(this);
                if (!$m.parent().is('body')) { $m.appendTo('body'); }
            });
        };

        try {
            moveModals();
            $(document).on('shown.bs.modal', (ev) => {
                const $m = $(ev.target);
                if ($m.length && !$m.parent().is('body')) { $m.appendTo('body'); }
            });
        } catch (e) { /* ignore */ }
    },

    // bootstrap-select builds its dropdown <li> list at init time; if the .selectpicker()
    // call in document.ready runs while the widget-options modal is still display:none
    // (the normal Bootstrap modal state before first show), the built list stays empty
    // and only a manual refresh repopulates it. Refresh every selectpicker in a modal
    // each time it's shown so Input/Output/Function (and similar) selects aren't empty.
    fixSelectpickerInHiddenModal() {
        try {
            $(document).on('shown.bs.modal', (ev) => {
                const $m = $(ev.target);
                if ($m.length && $.fn.selectpicker) {
                    $m.find('.selectpicker').selectpicker('refresh');
                }
            });
        } catch (e) { /* ignore */ }
    }
};

// =========================================================
// Main Initialization
// =========================================================

// Initialize Sticky Header immediately (visual stability)
StickyHeader.init();

// Initialize Grid logic
DashboardGrid.init();

// Document Ready for interactions
$(document).ready(function () {
    UIFixes.init();
    DashboardTabs.init();

    // Init Bootstrap Select if available
    if ($.fn.selectpicker) {
        $('.selectpicker').selectpicker();
    }

    // #widget_type type selector: dynamically align after detecting viewport overflow
    $('#widget_type').on('shown.bs.select', function () {
        var menu = $(this).closest('.bootstrap-select').find('> .dropdown-menu')[0];
        if (!menu) return;
        var rect = menu.getBoundingClientRect();
        if (rect.right > window.innerWidth - 4) {
            menu.style.setProperty('left', 'auto', 'important');
            menu.style.setProperty('right', '0', 'important');
        } else {
            menu.style.removeProperty('left');
            menu.style.removeProperty('right');
        }
    });

});
