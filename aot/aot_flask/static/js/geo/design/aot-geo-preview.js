/**
 * aot-geo-preview.js
 *
 * Client-side, transient preview overlay for Equipment-mode generation.
 * Mirrors the backend (geo_overlays.GeoOverlays.generate_pipes) parallel-offset
 * sweep using turf.js so the user sees branch pipes / sprinklers / drip pipes
 * update in real time while dragging sliders or typing into the panel inputs,
 * with no per-keystroke server round-trip.
 *
 * Lifecycle:
 *   - Live edit (oninput / slider drag)  -> show()  (debounced from panel)
 *   - Edit released (onchange) / button -> hide() then call the real
 *     geoDesign.generatePipes / generateSprinklers / modules.generateDrip,
 *     which is responsible for the persistent layers + server save.
 *
 * The preview never mutates layerStorage, dirtyNodeIds, or the editor
 * featureGroup. It only touches its own MapLibre sources and layers
 * (prefix "_aot_preview_") so it cannot leak into the saved design.
 */

class AoTGeoPreview {
    constructor(parent) {
        this.parent = parent; // AoTGeoDesign

        this.SRC_PIPE = '_aot_preview_pipes_src';
        this.SRC_SPR_PT = '_aot_preview_sprinklers_pt_src';
        this.SRC_SPR_COV = '_aot_preview_sprinklers_cov_src';

        this.LYR_PIPE = '_aot_preview_pipes_line';
        this.LYR_SPR_PT = '_aot_preview_sprinklers_pt';
        this.LYR_SPR_COV = '_aot_preview_sprinklers_cov';

        this._visible = false;
    }

    _native() {
        const m = this.parent && this.parent.map;
        return (m && m._originalMap) || (m && m._mlMap) || m || null;
    }

    _isReady() {
        const m = this._native();
        return !!(m && typeof m.isStyleLoaded === 'function' && m.isStyleLoaded());
    }

    /* -------------------------------------------------- Public API -------- */

    /**
     * Render a live preview for the given parent (Site/Zone) using the supplied
     * pipe / irrigation configuration. Either irrigation arg may be omitted.
     *
     * @param {GeoJSON.Feature} parentFeature  Site or Zone
     * @param {Object} pipeConfig              { spacing, angle, offset, is90Deg }
     * @param {Object|null} irrigationConfig   sprinkler or drip config, optional
     * @param {'sprinkler'|'drip'|null} irrigationType
     */
    show(parentFeature, pipeConfig, irrigationConfig, irrigationType) {
        if (!window.turf || !this._isReady()) return false;
        if (!parentFeature || !parentFeature.geometry) return false;

        const refLine = this._findRefLine(parentFeature);
        if (!refLine) return false;

        let pipes = [];
        try {
            pipes = this._computePipes(parentFeature, refLine, pipeConfig || {});
        } catch (e) {
            // Bad geometry — surface nothing rather than throw inside an input handler.
            // console.warn('[GeoPreview] computePipes failed', e);
            return false;
        }
        if (pipes.length === 0) {
            this._setPipeData([]);
            this._setSprinklerData([], []);
            return false;
        }

        // Apply drip styling hint by tagging features (used by paint expression).
        const isDrip = irrigationType === 'drip';
        if (isDrip) pipes.forEach(p => { p.properties = p.properties || {}; p.properties._preview_drip = true; });

        this._setPipeData(pipes);

        if (irrigationType === 'sprinkler' && irrigationConfig) {
            const { points, coverage } = this._computeSprinklers(pipes, irrigationConfig);
            this._setSprinklerData(points, coverage);
        } else {
            this._setSprinklerData([], []);
        }

        this._visible = true;
        return true;
    }

    hide() {
        if (!this._visible) return;
        this._setPipeData([]);
        this._setSprinklerData([], []);
        this._visible = false;
    }

    /**
     * Promote the previewed pipes to real, persisted layers — same client-side
     * compute as show(), but written through the canonical _processLoadedFeature
     * pipeline + saveDesign. Bypasses /api/geo/generate-pipes entirely so the
     * commit can never disagree with what the user just saw on screen.
     *
     * Returns a promise that resolves after save+reload settle.
     *
     * @param {GeoJSON.Feature} parentFeature
     * @param {Object} pipeConfig          { spacing, angle, offset, is90Deg }
     * @param {Object} [opts]              { sprinklerConfigFallback, reloadAfter }
     */
    async commitPipes(parentFeature, pipeConfig, opts = {}) {
        if (!window.turf) return null;
        if (!parentFeature || !parentFeature.geometry || !parentFeature.properties) return null;
        const parent = this.parent;
        if (!parent) return null;

        const parentId = parentFeature.properties.node_id;
        if (!parentId) {
            if (parent.ui && parent.ui.showToast) parent.ui.showToast('Selected feature is missing node_id.', 'error');
            return null;
        }

        const refLine = this._findRefLine(parentFeature);
        if (!refLine) {
            if (parent.ui && parent.ui.showToast) {
                parent.ui.showToast('No reference line available. Please draw a reference line.', 'warning');
            }
            return null;
        }

        // Snapshot existing main pipes BEFORE any mutation — we need them
        // both to clip new pipes (so they obey the "split by main" rule the
        // backend enforces) and to invoke processPipeTrimming after add.
        const mainPipeFeatures = [];
        const mainPipeLayers = [];
        const collectMain = (l) => {
            const sub = l && l.feature && l.feature.properties && l.feature.properties.sub_type;
            if (sub === 'pipe_main' && !mainPipeLayers.includes(l)) {
                mainPipeLayers.push(l);
                try {
                    const g = l.toGeoJSON ? l.toGeoJSON() : l.feature;
                    if (g && g.geometry) mainPipeFeatures.push(g);
                } catch (e) {}
            }
        };
        if (parent.layerStorage) {
            ['equipment'].forEach(k => {
                const g = parent.layerStorage[k];
                if (g && typeof g.eachLayer === 'function') {
                    try { g.eachLayer(collectMain); } catch (e) {}
                }
            });
        }
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            try { window.AoTMapEditor.featureGroup.eachLayer(collectMain); } catch (e) {}
        }

        // 1. Compute parallel pipes, then split each by main pipes (mirrors
        //    backend's split + stub filter rules) so new pipes never overlap
        //    main pipes and tiny stubs are dropped.
        let pipes = [];
        try {
            pipes = this._computePipes(parentFeature, refLine, pipeConfig || {});
        } catch (e) {
            if (parent.ui && parent.ui.showToast) parent.ui.showToast('Pipe computation failed', 'error');
            return null;
        }
        if (mainPipeFeatures.length > 0) {
            pipes = this._splitPipesByMains(pipes, mainPipeFeatures);
        }
        if (!pipes || pipes.length === 0) {
            if (parent.ui && parent.ui.showToast) parent.ui.showToast('No pipes generated. Check configuration.', 'warning');
            return null;
        }

        // 2. Detect existing sprinklers + sprinkler config BEFORE wiping anything.
        const sprinklerInfo = this._collectSprinklerContext(parentFeature, opts);
        const hasSprinklers = sprinklerInfo.hasSprinklers;
        const sprConfig = sprinklerInfo.sprConfig;

        // Hide preview overlay before mutating real layers so the user doesn't
        // see ghost duplicates during the swap.
        this.hide();

        // 3. EXPLICIT cleanup. Walks every container and removes every branch
        //    pipe / sprinkler / sprinkler_coverage / connection that belongs
        //    to this parent (by parent_node_id, zone_id, OR spatial midpoint
        //    inside parent). Does NOT depend on modules.clearEquipments —
        //    earlier user feedback confirmed that path was leaving layers
        //    behind. Marks each removed node_id in deletedNodeIds so the
        //    delta save persists the deletions.
        const removedCount = this._removeOldEquipmentForParent(parentFeature);

        // Reset stored irrigation configs on the parent so a stale config
        // doesn't get re-applied later. Sprinkler regen below will re-set
        // gen_config_sprinkler if needed.
        if (parentFeature.properties) {
            delete parentFeature.properties.gen_config_sprinkler;
            delete parentFeature.properties.gen_config_drip;
        }

        // 4. Add each computed pipe as a real layer through the canonical
        //    pipeline. Each gets a fresh node_id so it can never collide with
        //    a just-deleted one.
        const newLayers = [];
        pipes.forEach(f => {
            try {
                const arr = (window.AoTGeoLayer && window.AoTGeoLayer.fromGeoJSON)
                    ? window.AoTGeoLayer.fromGeoJSON(f) : [];
                const l = arr && arr[0];
                if (!l) return;
                l.feature = f;
                l.feature.properties = l.feature.properties || {};
                // Always assign a fresh UUID — never carry one from the
                // preview feature object.
                l.feature.properties.node_id = (window.crypto && window.crypto.randomUUID)
                    ? window.crypto.randomUUID()
                    : (window.uuidv4 ? window.uuidv4()
                        : ('xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
                            const r = Math.random() * 16 | 0;
                            return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
                        })));
                l.feature.properties.aot_type = 'equipment';
                l.feature.properties.sub_type = 'pipe_branch';
                l.feature.properties.parent_node_id = parentId;
                if (l.feature.properties._preview_drip) delete l.feature.properties._preview_drip;
                if (parent.dirtyNodeIds) parent.dirtyNodeIds.add(l.feature.properties.node_id);

                if (typeof parent._processLoadedFeature === 'function') {
                    parent._processLoadedFeature(l, 'equipment');
                }
                newLayers.push(l);
            } catch (e) { /* swallow per-feature failure, continue */ }
        });

        // 5. Post-process: rebuild Tee/Elbow connections (the geometry
        //    helper handles main-pipe interactions correctly here).
        if (parent.geometry && typeof parent.geometry.rebuildConnections === 'function') {
            try { parent.geometry.rebuildConnections(); } catch (e) {}
        }

        // 6. Auto-regenerate sprinklers if they existed before.
        if (hasSprinklers && sprConfig && parent.modules
            && typeof parent.modules.generateSprinklers === 'function') {
            try { parent.modules.generateSprinklers(parentFeature, sprConfig, false); } catch (e) {}
        }

        // 7. Persist pipe config on parent so the panel restores the right
        //    values on reload.
        try {
            const parentLayer = (parent.geometry && parent.geometry._findLayerByUuid)
                ? parent.geometry._findLayerByUuid(parentId) : null;
            const targetProps = (parentLayer && parentLayer.feature && parentLayer.feature.properties)
                || parentFeature.properties;
            targetProps.gen_config_pipe = JSON.parse(JSON.stringify(pipeConfig || {}));
            if (parent.dirtyNodeIds) parent.dirtyNodeIds.add(parentId);
        } catch (e) {}

        if (parent.updateDesignInfo) try { parent.updateDesignInfo(); } catch (e) {}

        // 8. Atomically replace all equipment on the server, then optionally reload.
        // saveDesign delta path is throttled by isSaving and fragmented (individual rows
        // vs equipment_collection bundle). Use saveOverlays for a clean atomic replace.
        if (parent.currentMapUuid && window.AoTMapData &&
            typeof window.AoTMapData.saveOverlays === 'function') {
            const eqFeatures = [];
            const seenIds = new Set();
            const collectEq = (l) => {
                const f = l && l.feature;
                if (!f || !f.properties) return;
                if (f.properties.no_save) return;
                if (f.properties.aot_type !== 'equipment') return;
                const nid = f.properties.node_id;
                if (nid && seenIds.has(nid)) return;
                if (nid) seenIds.add(nid);
                if (!f.geometry && typeof l.toGeoJSON === 'function') {
                    try { f.geometry = l.toGeoJSON().geometry; } catch (e) {}
                }
                eqFeatures.push(f);
            };
            if (parent.layerStorage && parent.layerStorage['equipment']) {
                try { parent.layerStorage['equipment'].eachLayer(collectEq); } catch (e) {}
            }
            if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
                try { window.AoTMapEditor.featureGroup.eachLayer(collectEq); } catch (e) {}
            }
            // Authoritative atomic replace (runs after a user-triggered generation with
            // equipment already loaded). allowEmpty lets an intentional "clear all
            // equipment" through the server's empty-wipe guard.
            try { await window.AoTMapData.saveOverlays(parent.currentMapUuid, 'equipment', eqFeatures, { allowEmpty: true }); } catch (e) {}
        } else {
            // Fallback: delta save (may be throttled).
            let savePromise = null;
            try { savePromise = parent.saveDesign(null, true); } catch (e) {}
            try { await Promise.resolve(savePromise); } catch (e) {}
        }
        // Persist gen_config on parent zone/site.
        try { await Promise.resolve(parent.saveDesign(['site', 'zone'], true)); } catch (e) {}

        if (opts.reloadAfter && parent.currentMapUuid && typeof parent._loadAllFeatures === 'function') {
            try { await parent._loadAllFeatures(parent.currentMapUuid); } catch (e) {}
        }

        return { added: newLayers.length, removed: removedCount };
    }

    /**
     * Direct, unconditional removal of every branch pipe / sprinkler /
     * sprinkler-coverage / connection that belongs to the given parent.
     * Replaces the previous reliance on modules.clearEquipments which was
     * silently leaving layers behind in production.
     *
     * Returns the number of layers actually removed.
     */
    _removeOldEquipmentForParent(parentFeature) {
        const parent = this.parent;
        const parentId = parentFeature.properties.node_id;
        const turf = window.turf;

        const isCleanable = (props) => {
            if (!props) return false;
            // Protect critical infrastructure
            if (props.sub_type === 'pipe_main') return false;
            if (props.aot_type === 'reference') return false;
            return (
                props.sub_type === 'pipe_branch' ||
                props.sub_type === 'sprinkler' ||
                props.sub_type === 'sprinkler_coverage' ||
                props.aot_type === 'connection'
            );
        };

        const matchesParent = (l, props) => {
            if (props && (props.parent_node_id === parentId || props.zone_id === parentId)) return true;
            // Spatial fallback: midpoint-in-parent.
            if (turf && l.feature && l.feature.geometry && parentFeature.geometry) {
                try {
                    let center;
                    if (l.feature.geometry.type === 'Point') {
                        center = l.feature;
                    } else {
                        center = turf.center(l.feature);
                    }
                    return turf.booleanPointInPolygon(center, parentFeature);
                } catch (e) {}
            }
            return false;
        };

        const collected = [];
        const seen = new Set();
        const visit = (l) => {
            if (!l || !l.feature) return;
            const props = l.feature.properties || {};
            if (!isCleanable(props)) return;
            if (!matchesParent(l, props)) return;
            const id = props.node_id || `_addr_${collected.length}`;
            if (seen.has(id)) return;
            seen.add(id);
            collected.push(l);
        };

        // Scan all storage groups (not just equipment — connections may be in
        // their own group, and a stale layer could be anywhere).
        if (parent.layerStorage) {
            Object.values(parent.layerStorage).forEach(group => {
                if (group && typeof group.eachLayer === 'function') {
                    try { group.eachLayer(visit); } catch (e) {}
                }
            });
        }
        // Scan editor.
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            try { window.AoTMapEditor.featureGroup.eachLayer(visit); } catch (e) {}
        }
        // Belt-and-suspenders: scan the map itself for any orphan rendered layer.
        if (parent.map && typeof parent.map.eachLayer === 'function') {
            try {
                parent.map.eachLayer(l => {
                    // Skip basemap tile layers / controls.
                    if (!l || !l.feature) return;
                    if (l._url || l._tiles) return;
                    visit(l);
                });
            } catch (e) {}
        }

        // Remove each from every container + mark for deletion in delta save.
        collected.forEach(l => {
            const id = l.feature && l.feature.properties && l.feature.properties.node_id;
            if (id) {
                if (parent.deletedNodeIds) parent.deletedNodeIds.add(id);
                if (parent.dirtyNodeIds) parent.dirtyNodeIds.delete(id);
            }
            try {
                if (window.AoTMapEditor && window.AoTMapEditor.featureGroup &&
                    window.AoTMapEditor.featureGroup.hasLayer &&
                    window.AoTMapEditor.featureGroup.hasLayer(l)) {
                    window.AoTMapEditor.featureGroup.removeLayer(l);
                }
            } catch (e) {}
            if (parent.layerStorage) {
                Object.values(parent.layerStorage).forEach(group => {
                    try { if (group && group.hasLayer && group.hasLayer(l)) group.removeLayer(l); } catch (e) {}
                });
            }
            try { if (parent.map && parent.map.hasLayer && parent.map.hasLayer(l)) parent.map.removeLayer(l); } catch (e) {}

            // Direct MapLibre GL removal — featureGroup.removeLayer only removes from the JS
            // layers array and does NOT touch the GL source/layer. Orphaned GL objects would
            // survive _clearLayers() because that loop only iterates featureGroup.layers (already
            // emptied) and layerStorage._layers (also empty after _swapStorageLayers).
            const mlMap = parent.map && (parent.map._originalMap || parent.map._mlMap || parent.map);
            if (mlMap && l._layerId) {
                const lid = l._layerId;
                const sid = 'aot-source-' + lid;
                try { if (typeof mlMap.getLayer === 'function' && mlMap.getLayer(lid)) mlMap.removeLayer(lid); } catch (e) {}
                try { if (typeof mlMap.getSource === 'function' && mlMap.getSource(sid)) mlMap.removeSource(sid); } catch (e) {}
            }
            if (l._mlDomMarker) {
                try { l._mlDomMarker.remove(); l._mlDomMarker = null; } catch (e) {}
            }
        });

        return collected.length;
    }

    /**
     * Split each generated pipe by every main pipe, drop tiny stubs.
     * Mirrors the backend rule:
     *   - if a segment is < 1m, drop it.
     *   - if a segment is < 10m AND < 50% of the largest split-part, drop it.
     */
    _splitPipesByMains(pipes, mainPipeFeatures) {
        const turf = window.turf;
        if (!turf || !mainPipeFeatures || mainPipeFeatures.length === 0) return pipes;
        const out = [];

        const splitOnce = (line, splitter) => {
            try {
                const sp = turf.lineSplit(line, splitter);
                if (sp && sp.features && sp.features.length > 0) return sp.features;
            } catch (e) {}
            return [line];
        };

        pipes.forEach(pipe => {
            let parts = [pipe];
            for (const main of mainPipeFeatures) {
                const next = [];
                for (const p of parts) {
                    next.push(...splitOnce(p, main));
                }
                parts = next;
            }
            // Compute lengths once.
            const lengths = parts.map(p => {
                try { return turf.length(p, { units: 'meters' }); } catch (e) { return 0; }
            });
            const maxLen = lengths.length ? Math.max(...lengths) : 0;
            parts.forEach((part, i) => {
                const len = lengths[i];
                if (len < 1.0) return;                 // backend rule
                if (parts.length > 1 && len < 10.0 && len < maxLen * 0.5) return; // stub rule
                // Preserve preview-only properties; commit code will overwrite
                // node_id / parent_node_id / etc.
                if (!part.properties) part.properties = {};
                Object.assign(part.properties, pipe.properties || {});
                out.push(part);
            });
        });

        return out;
    }

    /** Internal: find existing sprinkler state + best-effort sprinkler config. */
    _collectSprinklerContext(parentFeature, opts) {
        const parent = this.parent;
        const parentId = parentFeature && parentFeature.properties && parentFeature.properties.node_id;
        let hasSprinklers = false;

        const checkSpr = (l) => {
            if (hasSprinklers) return;
            const p = l.feature && l.feature.properties;
            if (!p || p.sub_type !== 'sprinkler') return;
            if (p.parent_node_id === parentId || p.zone_id === parentId) {
                hasSprinklers = true;
                return;
            }
            if (window.turf && l.feature.geometry) {
                try {
                    const center = window.turf.center(l.feature);
                    if (window.turf.booleanPointInPolygon(center, parentFeature)) hasSprinklers = true;
                } catch (e) {}
            }
        };
        if (parent.layerStorage && parent.layerStorage['equipment']) {
            try { parent.layerStorage['equipment'].eachLayer(checkSpr); } catch (e) {}
        }
        if (!hasSprinklers && window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            try { window.AoTMapEditor.featureGroup.eachLayer(checkSpr); } catch (e) {}
        }

        let sprConfig = parentFeature.properties.gen_config_sprinkler;
        if (!sprConfig && parent.layerStorage) {
            ['zone', 'site'].forEach(k => {
                if (sprConfig || !parent.layerStorage[k]) return;
                try {
                    parent.layerStorage[k].eachLayer(l => {
                        if (sprConfig) return;
                        const p = l.feature && l.feature.properties;
                        if (p && p.node_id === parentId && p.gen_config_sprinkler) {
                            sprConfig = p.gen_config_sprinkler;
                        }
                    });
                } catch (e) {}
            });
        }
        if (!sprConfig && hasSprinklers && opts && opts.sprinklerConfigFallback) {
            sprConfig = opts.sprinklerConfigFallback;
        }
        if (typeof sprConfig === 'string') {
            try { sprConfig = JSON.parse(sprConfig); } catch (e) {}
        }
        return { hasSprinklers, sprConfig };
    }

    /** Hard tear-down: removes layers and sources entirely. */
    destroy() {
        const map = this._native();
        if (!map) return;
        [this.LYR_SPR_PT, this.LYR_SPR_COV, this.LYR_PIPE].forEach(id => {
            try { if (map.getLayer(id)) map.removeLayer(id); } catch (e) {}
        });
        [this.SRC_SPR_PT, this.SRC_SPR_COV, this.SRC_PIPE].forEach(id => {
            try { if (map.getSource(id)) map.removeSource(id); } catch (e) {}
        });
        this._visible = false;
    }

    /* ----------------------------------------------- Source / layer mgmt -- */

    _ensurePipeLayer() {
        const map = this._native();
        if (!map) return;
        if (!map.getSource(this.SRC_PIPE)) {
            map.addSource(this.SRC_PIPE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
        }
        if (!map.getLayer(this.LYR_PIPE)) {
            map.addLayer({
                id: this.LYR_PIPE,
                type: 'line',
                source: this.SRC_PIPE,
                paint: {
                    'line-color': [
                        'case',
                        ['boolean', ['get', '_preview_drip'], false], '#16a34a',
                        '#007bff'
                    ],
                    'line-width': 2.5,
                    'line-opacity': 0.85,
                    'line-dasharray': [2, 2]
                }
            });
        }
    }

    _ensureSprinklerLayers() {
        const map = this._native();
        if (!map) return;
        if (!map.getSource(this.SRC_SPR_COV)) {
            map.addSource(this.SRC_SPR_COV, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
        }
        if (!map.getLayer(this.LYR_SPR_COV)) {
            map.addLayer({
                id: this.LYR_SPR_COV,
                type: 'fill',
                source: this.SRC_SPR_COV,
                paint: {
                    'fill-color': '#007bff',
                    'fill-opacity': 0.15,
                    'fill-outline-color': '#007bff'
                }
            });
        }
        if (!map.getSource(this.SRC_SPR_PT)) {
            map.addSource(this.SRC_SPR_PT, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
        }
        if (!map.getLayer(this.LYR_SPR_PT)) {
            map.addLayer({
                id: this.LYR_SPR_PT,
                type: 'circle',
                source: this.SRC_SPR_PT,
                paint: {
                    'circle-radius': 3.5,
                    'circle-color': '#DF5353',
                    'circle-opacity': 0.9,
                    'circle-stroke-color': '#ffffff',
                    'circle-stroke-width': 1
                }
            });
        }
    }

    _setPipeData(features) {
        const map = this._native();
        if (!map) return;
        this._ensurePipeLayer();
        const src = map.getSource(this.SRC_PIPE);
        if (src) src.setData({ type: 'FeatureCollection', features });
    }

    _setSprinklerData(points, coverage) {
        const map = this._native();
        if (!map) return;
        this._ensureSprinklerLayers();
        const sp = map.getSource(this.SRC_SPR_PT);
        const sc = map.getSource(this.SRC_SPR_COV);
        if (sp) sp.setData({ type: 'FeatureCollection', features: points });
        if (sc) sc.setData({ type: 'FeatureCollection', features: coverage });
    }

    /* ------------------------------------------------------ Geometry ------ */

    /** Same projected-meter sweep as backend generate_pipes. */
    _computePipes(parentFeature, refLineGeo, config) {
        const turf = window.turf;
        const boundaryGeom = parentFeature.geometry;
        if (!boundaryGeom || (boundaryGeom.type !== 'Polygon' && boundaryGeom.type !== 'MultiPolygon')) return [];

        // Use only outer ring of first polygon for boundary projection.
        const outer = boundaryGeom.type === 'Polygon'
            ? boundaryGeom.coordinates[0]
            : boundaryGeom.coordinates[0][0];

        const centroid = turf.centroid(parentFeature);
        const [originLng, originLat] = centroid.geometry.coordinates;
        const M_PER_DEG_LAT = 111320.0;
        const M_PER_DEG_LNG = M_PER_DEG_LAT * Math.cos(originLat * Math.PI / 180);
        if (!isFinite(M_PER_DEG_LNG) || M_PER_DEG_LNG <= 0) return [];

        const project = ([lng, lat]) => [(lng - originLng) * M_PER_DEG_LNG, (lat - originLat) * M_PER_DEG_LAT];
        const unproject = ([x, y]) => [x / M_PER_DEG_LNG + originLng, y / M_PER_DEG_LAT + originLat];

        const projBoundaryCoords = outer.map(project);
        // Ensure ring is closed
        const first = projBoundaryCoords[0];
        const last = projBoundaryCoords[projBoundaryCoords.length - 1];
        if (!first || !last || first[0] !== last[0] || first[1] !== last[1]) {
            projBoundaryCoords.push([first[0], first[1]]);
        }
        const projBoundary = turf.polygon([projBoundaryCoords]);

        // Pull ref line coords (LineString or first segment of MultiLineString)
        let refCoords = refLineGeo.geometry.coordinates;
        if (refLineGeo.geometry.type === 'MultiLineString') refCoords = refCoords[0];
        if (!refCoords || refCoords.length < 2) return [];
        const projRefCoords = refCoords.map(project);

        // Local helper: compute meter distance using projected bbox diagonal.
        const bbox = turf.bbox(projBoundary); // [minX, minY, maxX, maxY] in meters
        const diag = Math.hypot(bbox[2] - bbox[0], bbox[3] - bbox[1]);
        if (!isFinite(diag) || diag <= 0) return [];

        // Apply rotation (angle + 90 if 90deg toggle).
        const userAngle = parseFloat(config.angle || 0) || 0;
        const is90 = !!config.is90Deg;
        const totalRotation = userAngle + (is90 ? 90 : 0);

        // Manual rotation around projected ref-line centroid (planar, since we're already in meters).
        let rotatedRefCoords = projRefCoords;
        if (Math.abs(totalRotation) > 1e-9) {
            // Centroid of ref line in meter space (mean of vertices is fine for short lines).
            let cx = 0, cy = 0;
            projRefCoords.forEach(([x, y]) => { cx += x; cy += y; });
            cx /= projRefCoords.length; cy /= projRefCoords.length;
            const rad = totalRotation * Math.PI / 180;
            const cos = Math.cos(rad), sin = Math.sin(rad);
            rotatedRefCoords = projRefCoords.map(([x, y]) => {
                const dx = x - cx, dy = y - cy;
                return [cx + dx * cos - dy * sin, cy + dx * sin + dy * cos];
            });
        }

        // Extend ref line by 2*diag at both ends so sweeping covers full bbox.
        const extLen = diag * 2.0;
        const extended = rotatedRefCoords.slice();
        if (extended.length >= 2) {
            const p1 = extended[0], p2 = extended[1];
            const dxs = p2[0] - p1[0], dys = p2[1] - p1[1];
            const mags = Math.hypot(dxs, dys);
            if (mags > 0) extended[0] = [p1[0] - dxs / mags * extLen, p1[1] - dys / mags * extLen];

            const pn1 = extended[extended.length - 2];
            const pn = extended[extended.length - 1];
            const dxe = pn[0] - pn1[0], dye = pn[1] - pn1[1];
            const mage = Math.hypot(dxe, dye);
            if (mage > 0) extended[extended.length - 1] = [pn[0] + dxe / mage * extLen, pn[1] + dye / mage * extLen];
        }

        // Build planar (meter) refLine as a *geographic* lineString placeholder so that
        // turf.lineOffset can operate on it. lineOffset uses the rhumb method internally
        // and works in degrees, so we instead implement parallel offset manually below.
        const spacing = Math.max(0.1, parseFloat(config.spacing || 14.0) || 14.0);
        const userOffset = parseFloat(config.offset || 0) || 0;
        const maxIter = Math.floor(diag / spacing) + 10;

        // Compute unit perpendicular (normal) of the (extended) ref line direction.
        const nx0 = extended[extended.length - 1][0] - extended[0][0];
        const ny0 = extended[extended.length - 1][1] - extended[0][1];
        const nmag = Math.hypot(nx0, ny0);
        if (nmag < 1e-9) return [];
        // Normal is perpendicular to direction. Backend uses parallel_offset with
        // side='left' for positive offset; left side is (-dy, dx) when walking p1->p2.
        const normalX = -ny0 / nmag;
        const normalY =  nx0 / nmag;

        // Pre-build boundary geographic polygon (used only for clipping back in lng/lat space).
        const boundaryLngLat = turf.polygon([projBoundaryCoords.map(unproject)]);

        const out = [];
        for (let i = -maxIter; i <= maxIter; i++) {
            const totalOffset = userOffset + (i * spacing);
            // Offset every vertex by totalOffset along the normal.
            const offsetCoords = extended.map(([x, y]) => [
                x + normalX * totalOffset,
                y + normalY * totalOffset
            ]);
            // Unproject back to lng/lat for turf clipping in geographic space.
            const lngLatCoords = offsetCoords.map(unproject);
            let line;
            try { line = turf.lineString(lngLatCoords); } catch (e) { continue; }

            const clipped = this._clipLineToPoly(line, boundaryLngLat);
            for (const seg of clipped) {
                try {
                    if (turf.length(seg, { units: 'meters' }) > 1.0) {
                        seg.properties = { aot_type: 'equipment', sub_type: 'pipe_branch' };
                        out.push(seg);
                    }
                } catch (e) { /* ignore */ }
            }
        }
        return out;
    }

    /**
     * Clip a LineString to a polygon, keeping the inside parts.
     * Uses turf.lineSplit on the polygon outline, then filters by midpoint.
     */
    _clipLineToPoly(line, polygon) {
        const turf = window.turf;
        try {
            const splits = turf.lineSplit(line, polygon);
            const inside = [];
            const features = (splits && splits.features) ? splits.features : [];
            const candidates = features.length > 0 ? features : [line];
            candidates.forEach(f => {
                if (!f || !f.geometry || !f.geometry.coordinates || f.geometry.coordinates.length < 2) return;
                let mid;
                try {
                    const len = turf.length(f, { units: 'meters' });
                    if (len <= 0) return;
                    mid = turf.along(f, len / 2, { units: 'meters' });
                } catch (e) {
                    return;
                }
                if (turf.booleanPointInPolygon(mid, polygon)) inside.push(f);
            });
            return inside;
        } catch (e) {
            return [];
        }
    }

    _computeSprinklers(pipes, config) {
        const turf = window.turf;
        const interval = Math.max(0.1, parseFloat(config.interval || 14.0) || 14.0);
        const radius = Math.max(0.05, parseFloat(config.radius || 11.0) || 11.0);
        const points = [];
        const coverage = [];

        for (const pipe of pipes) {
            let len = 0;
            try { len = turf.length(pipe, { units: 'meters' }); } catch (e) { continue; }
            if (len <= 0) continue;
            for (let d = interval / 2; d < len; d += interval) {
                let pos;
                try { pos = turf.along(pipe, d, { units: 'meters' }); } catch (e) { continue; }
                points.push({ type: 'Feature', geometry: pos.geometry, properties: {} });
                try {
                    coverage.push(turf.circle(pos, radius, { steps: 24, units: 'meters' }));
                } catch (e) { /* skip ring on bad geometry */ }
            }
        }
        return { points, coverage };
    }

    /* ----------------------------------------------- Reference detection -- */

    _findRefLine(parentFeature) {
        const parent = this.parent;
        const parentId = parentFeature && parentFeature.properties && parentFeature.properties.node_id;
        if (!parentId) return null;
        let refGeo = null;

        const linked = (group) => {
            if (!group || refGeo) return;
            try {
                group.eachLayer(l => {
                    if (refGeo) return;
                    const props = l.feature && l.feature.properties;
                    if (props && props.aot_type === 'reference' && props.parent_node_id === parentId) {
                        if (l.toGeoJSON) refGeo = l.toGeoJSON();
                    }
                });
            } catch (e) { /* ignore iter errors */ }
        };
        linked(parent.layerStorage && parent.layerStorage['reference']);
        if (!refGeo && window.AoTMapEditor) linked(window.AoTMapEditor.featureGroup);

        // Spatial fallback: ref line geometrically inside parent.
        if (!refGeo && window.turf && parentFeature.geometry) {
            const spatial = (group) => {
                if (!group || refGeo) return;
                try {
                    group.eachLayer(l => {
                        if (refGeo) return;
                        const props = l.feature && l.feature.properties;
                        if (props && props.aot_type === 'reference') {
                            try {
                                const lGeo = l.toGeoJSON();
                                if (window.turf.booleanIntersects(lGeo, parentFeature) ||
                                    window.turf.booleanContains(parentFeature, lGeo)) {
                                    refGeo = lGeo;
                                }
                            } catch (e) { /* ignore */ }
                        }
                    });
                } catch (e) { /* ignore */ }
            };
            spatial(parent.layerStorage && parent.layerStorage['reference']);
            if (!refGeo && window.AoTMapEditor) spatial(window.AoTMapEditor.featureGroup);
        }

        // Final fallback: longest edge of the parent polygon.
        if (!refGeo && window.turf && parentFeature.geometry &&
            parentFeature.geometry.type === 'Polygon') {
            try {
                const coords = parentFeature.geometry.coordinates[0];
                let maxLen = 0;
                let best = null;
                for (let i = 0; i < coords.length - 1; i++) {
                    const line = window.turf.lineString([coords[i], coords[i + 1]]);
                    const len = window.turf.length(line, { units: 'meters' });
                    if (len > maxLen && len > 1.0) { maxLen = len; best = line; }
                }
                refGeo = best;
            } catch (e) { /* ignore */ }
        }
        return refGeo;
    }
}

window.AoTGeoPreview = AoTGeoPreview;
