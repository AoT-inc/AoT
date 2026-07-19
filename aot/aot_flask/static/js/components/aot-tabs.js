
/**
 * AoTTabs - Unified Tab component for Dashboard and Map
 * Supports: Drag & Drop, Mobile Scroll Snap, Sticky Header, Transparency Fix
 */
class AoTTabs {
    constructor(options) {
        this.containerId = options.containerId; // e.g. 'dash-tabs' or 'map-tabs'
        this.saveEndpoint = options.saveEndpoint; // e.g. '/save_dashboard_order'
        this.activeClass = options.activeClass || 'active';
        this.stickyId = options.stickyId; // ID of the sticky header container
        this.storageKey = options.storageKey || 'aot_tabs_order';

        this.container = document.getElementById(this.containerId);
        if (!this.container) return;

        this.init();
    }

    init() {
        this.dragging = false;
        this.dragSrc = null;

        // Mobile scroll to active
        this.scrollToActive();

        // Sticky behavior
        if (this.stickyId) {
            this.initSticky();
        }

        // Drag & Drop
        this.initDragDrop();
    }

    scrollToActive() {
        const active = this.container.querySelector(`.${this.activeClass}`);
        if (!active) return;

        // Get all tabs to find index
        const tabs = Array.from(this.container.children).filter(el => el.classList.contains('dash-tab') || el.classList.contains('aot-tab-item'));
        const index = tabs.indexOf(active.closest('.dash-tab, .aot-tab-item'));

        const isMobile = window.innerWidth <= 768; // Common breakpoint

        try {
            // Use 'instant' to avoid visible scroll animation on page load
            if (isMobile) {
                if (index === 0) {
                    active.scrollIntoView({ behavior: 'instant', block: 'nearest', inline: 'start' });
                } else {
                    active.scrollIntoView({ behavior: 'instant', block: 'nearest', inline: 'center' });
                }
            } else {
                active.scrollIntoView({ behavior: 'instant', block: 'nearest', inline: 'center' });
            }
        } catch (e) {
            // Fallback
        }
    }

    initSticky() {
        const sticky = document.getElementById(this.stickyId);
        if (!sticky) return;

        let rafId = null;
        const computeTop = () => {
            try {
                const navbar = document.querySelector('.navbar.main-navbar');
                if (!navbar) return;
                const h = navbar.offsetHeight || 0;
                // body.aot-nav-hidden is toggled synchronously by the scroll-hide JS
                // before this rAF runs, so it reliably reflects the final intended state.
                // Reading getComputedStyle(navbar).top would give an in-transition value
                // (navbar has transition: top 0.3s) and produce desired≈50 even when hiding.
                const navHidden = document.body.classList.contains('aot-nav-hidden');
                const desired = navHidden ? 0 : h;

                if (sticky.__lastTop !== desired) {
                    sticky.style.top = desired + 'px';
                    sticky.__lastTop = desired;
                }

                const rect = sticky.getBoundingClientRect();
                const isStuck = (rect.top <= desired + 1);
                sticky.classList.toggle('is-stuck', isStuck);

                // Shadow only — let CSS variable handle background color
                sticky.classList.toggle('shadow-sm', isStuck);
                sticky.style.backgroundColor = '';

            } catch (e) { }
        };

        const schedule = () => {
            if (rafId) return;
            rafId = requestAnimationFrame(() => { rafId = null; computeTop(); });
        };

        window.addEventListener('scroll', schedule, { passive: true });
        window.addEventListener('resize', schedule, { passive: true });

        // Suppress transition for initial top positioning to prevent load-time animation
        const origTransition = sticky.style.transition;
        sticky.style.transition = 'none';
        computeTop();
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                sticky.style.transition = origTransition;
            });
        });
    }

    initDragDrop() {
        const that = this;
        const container = this.container;

        // Helper to get direct children only
        const getTabs = () => Array.from(container.children).filter(el => el.draggable || el.classList.contains('dash-tab') || el.classList.contains('map-tab'));

        container.addEventListener('dragstart', (ev) => {
            const tab = ev.target.closest('[draggable]');
            if (!tab || !container.contains(tab)) return;

            that.dragSrc = tab;
            that.dragging = true;
            tab.classList.add('dragging');

            ev.dataTransfer.effectAllowed = 'move';
            ev.dataTransfer.setData('text/plain', tab.dataset.id);
        });

        container.addEventListener('dragover', (ev) => {
            if (!that.dragSrc) return;
            ev.preventDefault();
            ev.dataTransfer.dropEffect = 'move';

            const over = ev.target.closest('[draggable]');
            getTabs().forEach(t => t.classList.remove('drop-target'));
            if (over && over !== that.dragSrc && container.contains(over)) {
                over.classList.add('drop-target');
            }
        });

        container.addEventListener('drop', (ev) => {
            ev.preventDefault();
            getTabs().forEach(t => t.classList.remove('drop-target'));
            const src = that.dragSrc;
            if (!src) return;

            const target = ev.target.closest('[draggable]');
            if (target && target !== src && container.contains(target)) {
                const rect = target.getBoundingClientRect();
                const next = (ev.clientX - rect.left) > (rect.width / 2);
                if (next) {
                    container.insertBefore(src, target.nextSibling);
                } else {
                    container.insertBefore(src, target);
                }
                that.saveOrder();
            }
        });

        container.addEventListener('dragend', () => {
            that.dragging = false;
            that.dragSrc = null;
            getTabs().forEach(t => {
                t.classList.remove('dragging');
                t.classList.remove('drop-target');
            });
        });
    }

    showToast(message, type = 'info') {
        if (typeof window.showToast !== 'undefined') {
            window.showToast(message, type);
            return;
        }

        const settings = window.AoTGlobalSettings || {};
        let shouldHide = false;
        if (type === 'success' && settings.hide_success) shouldHide = true;
        if (type === 'info' && settings.hide_info) shouldHide = true;
        
        if ((type === 'warning' || type === 'error') && settings.hide_warning) shouldHide = true;
        
        if (shouldHide) return;

        if (typeof toastr !== 'undefined' && toastr[type]) {
            toastr[type](message);
        } else {
            console.log(`[AoTTabs] ${type}: ${message}`);
        }
    }

    saveOrder() {
        if (!this.saveEndpoint) return;

        // Get IDs
        const ids = Array.from(this.container.children)
            .map(el => el.dataset.id)
            .filter(id => id); // filter empty

        // Local storage sync (optional)
        try { localStorage.setItem(this.storageKey, JSON.stringify(ids)); } catch (e) { }

        // Server save
        fetch(this.saveEndpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                // CSRF token: Robust retrieval
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || 
                               document.querySelector('input[name="csrf_token"]')?.value || ''
            },
            body: JSON.stringify({ tab_ids: ids })
        })
            .then(r => r.json())
            .then(data => {
                // notify success using standard wrapper
                this.showToast(_('order_saved'), 'success');
            })
            .catch(err => {
                console.error('Order save failed', err);
                this.showToast(_('order_save_fail'), 'error');
            });
    }
}

// Global expose
window.AoTTabs = AoTTabs;
