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
                handle: '.panel-heading, .card-header, .widget-drag-handle',
                cancel: 'input, textarea, select, button, a, .no-drag, .modal, .dropdown-menu, .list-group, .table, .form-control'
            },
            alwaysShowResizeHandle: 'mobile',
            float: false,
            disableOneColumnMode: true, 
            oneColumnSize: 0
            // [Fix] Removed columnOpts to prevent automatic scaling conflicts
        };

        // Initialize GridStack
        window.grid = GridStack.init(options);

        // [Fix] Initial Layout Sync
        this.syncLayout();

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

            // 2. Sync data-desktop attributes (Handling Mobile 2 -> Desktop 24 mapping)
            if (window.grid.getColumn() === 24) {
                el.setAttribute('data-desktop-w', el.getAttribute('gs-w'));
                el.setAttribute('data-desktop-x', el.getAttribute('gs-x'));
                el.setAttribute('data-desktop-y', el.getAttribute('gs-y'));
            } else {
                // Mobile (2-column) to Desktop (24-column) mapping
                const w = parseInt(el.getAttribute('gs-w') || "1");
                const x = parseInt(el.getAttribute('gs-x') || "0");
                el.setAttribute('data-desktop-w', w * 12);
                el.setAttribute('data-desktop-x', x * 12);
                el.setAttribute('data-desktop-y', el.getAttribute('gs-y'));
            }
        });

        // Event: Drag Stop (Sync data-desktop-x/y & Trigger global resize)
        window.grid.on('dragstop', (event, el) => {
            if (window.grid.getColumn() === 24) {
                el.setAttribute('data-desktop-x', el.getAttribute('gs-x'));
                el.setAttribute('data-desktop-y', el.getAttribute('gs-y'));
            } else {
                const x = parseInt(el.getAttribute('gs-x') || "0");
                el.setAttribute('data-desktop-x', x * 12);
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

        if (!window.grid) return;

        const isMobile = window.innerWidth <= 768;
        const targetColumn = isMobile ? 2 : 24;
        const currentColumn = window.grid.getColumn();

        if (currentColumn === targetColumn) return;

        console.log(`Dashboard: Switching to ${targetColumn} columns using Gridstack engine...`);
        this.isSyncing = true;
        window.grid.batchUpdate(true);

        if (targetColumn === 2) {
            // [Fix v3] Transition to Mobile:
            // Use 'moveScale' strategy to let GridStack native scaling handle 2-column stacking.
            window.grid.column(targetColumn, 'moveScale');

            window.grid.getGridItems().forEach(el => {
                const dw = el.getAttribute('data-desktop-w');
                const desktopW = parseInt(dw || "24");
                if (desktopW > 12) {
                    window.grid.update(el, { w: 2 });
                }
            });
            window.grid.compact();
        } else {
            // [Fix v3] Transition to Desktop:
            // Use 'none' strategy and temporary 'float' mode to prevent collision cascades.
            window.grid.column(targetColumn, 'none');
            const prevFloat = window.grid.getFloat();
            window.grid.float(true);

            // Sort widgets to ensure predictable restoration order
            const items = window.grid.getGridItems().sort((a, b) => {
                const ay = parseInt(a.getAttribute('data-desktop-y') || "0");
                const by = parseInt(b.getAttribute('data-desktop-y') || "0");
                if (ay !== by) return ay - by;
                return parseInt(a.getAttribute('data-desktop-x') || "0") - parseInt(b.getAttribute('data-desktop-x') || "0");
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
        }

        window.grid.batchUpdate(false);
        // Clear syncing flag after a small delay to ensure any pending change events are ignored
        setTimeout(() => { this.isSyncing = false; }, 200);

        // [Fix] Trigger Global Resize:
        // Instead of calling individual reflows, firing a global resize event
        // is more robust as most libraries (Highcharts, Leaflet) listen to this by default.
        window.dispatchEvent(new Event('resize'));
    },

    enableEditing() {
        // Persist layout on change
        window.grid.on('change', (event, items) => {
            // Block saving only during initial sync/layout transition
            if (this.isSyncing) {
                console.log("Dashboard: Save suppressed (syncing).");
                return;
            }

            // [Fix] Sync data-desktop attributes for all changed items
            if (items) {
                items.forEach(item => {
                    const el = item.el;
                    if (window.grid.getColumn() === 24) {
                        el.setAttribute('data-desktop-w', item.w);
                        el.setAttribute('data-desktop-x', item.x);
                        el.setAttribute('data-desktop-y', item.y);
                    } else {
                        const w = parseInt(item.w || "1");
                        const x = parseInt(item.x || "0");
                        el.setAttribute('data-desktop-w', w * 12);
                        el.setAttribute('data-desktop-x', x * 12);
                        el.setAttribute('data-desktop-y', item.y);
                    }
                });
            }

            try {
                // [Fix] Map current layout back to Desktop coordinates for saving
                const savePayload = window.grid.getGridItems().map(el => ({
                    id: el.getAttribute('gs-id'),
                    x: parseInt(el.getAttribute('data-desktop-x') || el.getAttribute('gs-x')),
                    y: parseInt(el.getAttribute('gs-y')),
                    w: parseInt(el.getAttribute('data-desktop-w') || el.getAttribute('gs-w')),
                    h: parseInt(el.getAttribute('gs-h'))
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
            const active = this.container.querySelector('.btn.btn-aot-dash.active');
            if (!active) return;
            try {
                active.scrollIntoView({ behavior: 'auto', block: 'nearest', inline: 'center' });
            } catch (e) {
                // Fallback for older browsers
                const tab = active.closest('.dash-tab') || active;
                const tabRect = tab.getBoundingClientRect();
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
});
