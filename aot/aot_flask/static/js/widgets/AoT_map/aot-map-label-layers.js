/**
 * AoT Map — Label Layer Registry & Priority Skeleton (P1)
 * ------------------------------------------------------------------
 * Central per-widget-instance registry for every label/marker drawn on the
 * map (site/zone/facility/equipment/device/sensor/measurement/drawn). Replaces
 * the scattered collections (inst.markers, inst.geoDeviceLabelMarkers,
 * STATE[uid].markers, ...) that each toggle path had to iterate separately.
 *
 * Two independent priority axes per entry:
 *   rank : collision winner   (higher wins; loser is pushed/hidden)
 *   pin  : zoom behavior       ('always' | 'gated' | 'cluster')
 *
 * The rank/pin values are NOT user settings. They come from one of two
 * code-constant presets, selected by a single boolean custom_option
 * (`label_priority_facility`). Default = outdoor-centric.
 *
 * P1 scope: skeleton + presets + lookup API only. No rendering behavior change
 * — renderers will call register() in a later phase (P4). Nothing consumes the
 * registry yet, so loading this file is inert.
 */
(function () {
    'use strict';

    // ── Category taxonomy ────────────────────────────────────────────────────
    // Single 1st-class classification axis. `source` (shape/facility/device/meas)
    // is kept on each entry as secondary info but never drives priority.
    var CATEGORIES = ['land', 'zone', 'facility', 'equipment', 'device', 'sensor', 'measurement', 'drawn'];

    // ── Priority presets (code constants, not settings) ──────────────────────
    // rank: higher = wins collisions. pin: zoom LOD behavior.
    //   always  → rendered at every zoom; never hidden by collision (pushes others)
    //   gated   → only shown at zoom >= minZoom (and <= maxZoom if set)
    //   cluster → merged into a count badge below clusterAtZoom
    var LABEL_PRESETS = {
        // label_priority_facility = false (default)
        outdoor: {
            land:        { rank: 90, pin: 'always' },
            zone:        { rank: 80, pin: 'always' },
            facility:    { rank: 50, pin: 'gated',   minZoom: 15 },
            sensor:      { rank: 40, pin: 'cluster', clusterAtZoom: 17 },
            device:      { rank: 30, pin: 'cluster', clusterAtZoom: 16 },
            equipment:   { rank: 20, pin: 'gated',   minZoom: 16 },
            measurement: { rank: 35, pin: 'cluster', clusterAtZoom: 16 },
            drawn:       { rank: 10, pin: 'gated',   minZoom: 15 }
        },
        // label_priority_facility = true
        facility: {
            facility:    { rank: 90, pin: 'always' },
            sensor:      { rank: 80, pin: 'always' },
            measurement: { rank: 70, pin: 'always' },
            device:      { rank: 60, pin: 'gated',   minZoom: 14 },
            equipment:   { rank: 50, pin: 'gated',   minZoom: 15 },
            zone:        { rank: 40, pin: 'gated',   minZoom: 15 },
            land:        { rank: 30, pin: 'cluster', clusterAtZoom: 13 },
            drawn:       { rank: 10, pin: 'gated',   minZoom: 16 }
        }
    };

    function presetFor(facilityCentric) {
        return facilityCentric ? LABEL_PRESETS.facility : LABEL_PRESETS.outdoor;
    }

    // Resolve the (rank, pin, ...) descriptor for a category under the active
    // preset. Falls back to a low-rank gated default for unknown categories so a
    // new category never silently outranks everything.
    function resolve(facilityCentric, category) {
        var p = presetFor(facilityCentric);
        return p[category] || { rank: 0, pin: 'gated', minZoom: 16 };
    }

    // ── Per-instance registry ────────────────────────────────────────────────
    // Stored keyed by widget uniqueId. Each category bucket carries TWO
    // independent visibility axes:
    //   shapeVisible : the MapLibre fill/line shape layers for the category
    //   labelVisible : the DOM text/marker labels for the category
    // These were historically a single `visible` flag, which coupled a category's
    // shape and its label into one toggle. The two axes are now separate so the
    // widget can show a shape while hiding its label (and vice versa).
    var REGISTRIES = {}; // uid -> { facilityCentric, categories: { cat: { shapeVisible, labelVisible, items[] } } }

    function _ensure(uid) {
        if (!REGISTRIES[uid]) {
            var cats = {};
            CATEGORIES.forEach(function (c) { cats[c] = { shapeVisible: true, labelVisible: true, items: [] }; });
            REGISTRIES[uid] = { facilityCentric: false, categories: cats };
        }
        return REGISTRIES[uid];
    }

    function _bucket(uid, category) {
        var reg = _ensure(uid);
        return reg.categories[category] || (reg.categories[category] = { shapeVisible: true, labelVisible: true, items: [] });
    }

    var Registry = {
        CATEGORIES: CATEGORIES,
        LABEL_PRESETS: LABEL_PRESETS,
        presetFor: presetFor,
        resolve: resolve,

        /** Initialize / reset a widget instance's registry with the active preset choice. */
        init: function (uid, opts) {
            var reg = _ensure(uid);
            reg.facilityCentric = !!(opts && opts.facilityCentric);
            return reg;
        },

        /**
         * Register one label/marker.
         *   uid       widget uniqueId
         *   category  one of CATEGORIES
         *   item      { layerKey, el, marker, kind:'label'|'shape'|'marker', source }
         * Returns the stored entry (with resolved rank/pin merged in).
         */
        register: function (uid, category, item) {
            var reg = _ensure(uid);
            var bucket = _bucket(uid, category);
            var desc = resolve(reg.facilityCentric, category);
            var entry = Object.assign({ category: category }, desc, item);
            bucket.items.push(entry);
            return entry;
        },

        /** Build a stable composite key. */
        makeKey: function (category, source, stableId) {
            return category + ':' + source + ':' + stableId;
        },

        /** All entries across categories, optionally filtered to shape-visible buckets. */
        all: function (uid, visibleOnly) {
            var reg = REGISTRIES[uid];
            if (!reg) return [];
            var out = [];
            Object.keys(reg.categories).forEach(function (c) {
                var b = reg.categories[c];
                if (visibleOnly && !b.shapeVisible) return;
                out.push.apply(out, b.items);
            });
            return out;
        },

        /** Entries for one category. */
        byCategory: function (uid, category) {
            var reg = REGISTRIES[uid];
            if (!reg || !reg.categories[category]) return [];
            return reg.categories[category].items;
        },

        // ── Shape axis ───────────────────────────────────────────────────────
        /** Toggle a category's SHAPE (fill/line layer) visibility flag. */
        setShapeVisible: function (uid, category, visible) {
            var b = _bucket(uid, category);
            b.shapeVisible = !!visible;
            return b.shapeVisible;
        },
        isShapeVisible: function (uid, category) {
            var reg = REGISTRIES[uid];
            return !reg || !reg.categories[category] ? true : reg.categories[category].shapeVisible;
        },

        // ── Label axis ───────────────────────────────────────────────────────
        /** Toggle a category's LABEL (DOM text/marker) visibility flag. */
        setLabelVisible: function (uid, category, visible) {
            var b = _bucket(uid, category);
            b.labelVisible = !!visible;
            return b.labelVisible;
        },
        isLabelVisible: function (uid, category) {
            var reg = REGISTRIES[uid];
            return !reg || !reg.categories[category] ? true : reg.categories[category].labelVisible;
        },

        // ── Back-compat aliases (pre-split callers) → shape axis ─────────────
        setCategoryVisible: function (uid, category, visible) {
            return Registry.setShapeVisible(uid, category, visible);
        },
        isCategoryVisible: function (uid, category) {
            return Registry.isShapeVisible(uid, category);
        },

        /** Swap preset at runtime (toggle change). Re-resolves rank/pin on existing entries. */
        setFacilityCentric: function (uid, facilityCentric) {
            var reg = _ensure(uid);
            reg.facilityCentric = !!facilityCentric;
            Object.keys(reg.categories).forEach(function (c) {
                var desc = resolve(reg.facilityCentric, c);
                reg.categories[c].items.forEach(function (e) {
                    e.rank = desc.rank; e.pin = desc.pin;
                    e.minZoom = desc.minZoom; e.maxZoom = desc.maxZoom;
                    e.clusterAtZoom = desc.clusterAtZoom;
                });
            });
            return reg.facilityCentric;
        },

        /** Drop a uid's registry (widget teardown). */
        clear: function (uid) { delete REGISTRIES[uid]; }
    };

    window.AoTMapLabelLayers = Registry;
})();
