/**
 * aot-geo-stats.js
 * Statistics and Design Info Management for AoTGeoDesign
 */

class AoTGeoStats {
    constructor(parent) {
        this.parent = parent;
        this._selectedSiteIds = null;
        this._cachedDesignData = null;
        
        // [New] External Export Module
        if (typeof AoTGeoExport !== 'undefined') {
            this.export = new AoTGeoExport(this);
            this.export.bindActions();
        }
    }

    /**
     * Update Design Information Panel
     * Calculates stats for Site/Zone/Device and updates UI
     */
    updateDesignInfo() {
        if (this._updating) return; // Prevent re-entry
        this._updating = true;

        const data = {
            totals: {
                siteCount: 0, zoneCount: 0, deviceCount: 0,
                area: 0, pipeMainLen: 0, pipeBranchLen: 0,
                emitters: 0, waterUsage: 0,
                input: 0, output: 0, function: 0, totalPipeLen: 0
            },
            sites: []
        };

        try {
            // 1. Collect All Elements & Categorize in Single Pass
            const allSites = [];
            const allZones = [];
            const layersBySite = {}; // { siteId: [layers] }
            const layersByZone = {}; // { zoneId: [layers] }
            const spatiallyPending = [];

            const categorizeLayer = (l) => {
                if (!l.feature || !l.feature.properties) return;
                
                // [Cleanup] Remove temp flag to prevent persistence
                if (l.feature.properties._force_include) delete l.feature.properties._force_include;

                const props = l.feature.properties;
                const type = props.aot_type;

                if (type === 'site') {
                    allSites.push(l);
                    return;
                }
                if (type === 'zone') {
                    allZones.push(l);
                    return;
                }

                const pid = props.parent_node_id;
                const zid = props.zone_id;

                if (pid) {
                    if (!layersBySite[pid]) layersBySite[pid] = [];
                    layersBySite[pid].push(l);
                } else if (zid) {
                    if (!layersByZone[zid]) layersByZone[zid] = [];
                    layersByZone[zid].push(l);
                } else {
                    // Orphan or newly created - needs spatial resolution
                    spatiallyPending.push(l);
                }
            };

            // Collect across all possible groups
            const processedIds = new Set();
            const collectFromGroup = (group) => {
                if (!group) return;
                group.eachLayer(l => {
                    const id = l.feature?.properties?.node_id;
                    if (id && !processedIds.has(id)) {
                        processedIds.add(id);
                        categorizeLayer(l);
                    }
                });
            };

            collectFromGroup(window.AoTMapEditor?.featureGroup);
            ['site', 'zone', 'equipment', 'aot_device', 'connection'].forEach(k => collectFromGroup(this.parent.layerStorage[k]));

            // 2. Resolve Spatially Pending items (Nearest Neighbor with 2km Threshold)
            if (spatiallyPending.length > 0 && allSites.length > 0) {
                // Pre-calculate Site Boundaries for performance (convert Polygon to LineString)
                // If sites are huge, this might be heavy. But typically < 50 sites.
                const siteBoundaries = allSites.map(s => {
                    try {
                        let lines = window.turf.polygonToLine(s.feature);
                        // standardize to array of features
                        if (lines.type === 'Feature') return [lines];
                        if (lines.type === 'FeatureCollection') return lines.features;
                        return [];
                    } catch(e) { return []; }
                });

                spatiallyPending.forEach(l => {
                    if (!l.feature?.geometry) return;
                    
                    const pt = (l.feature.geometry.type === 'Point') ? l.feature.geometry.coordinates : window.turf.centroid(l.feature).geometry.coordinates;
                    const turfPt = window.turf.point(pt);

                    let found = false;

                    // A. Check containment in Zones
                    for (const z of allZones) {
                        try {
                            if (z.feature && z.feature.geometry && window.turf.booleanPointInPolygon(turfPt, z.feature)) {
                                const zid = z.feature.properties.node_id;
                                if (!layersByZone[zid]) layersByZone[zid] = [];
                                layersByZone[zid].push(l);
                                found = true; break;
                            }
                        } catch(e) {}
                    }
                    if (found) return;

                    // B. Check containment in Sites
                    for (const s of allSites) {
                        try {
                           if (s.feature && s.feature.geometry && window.turf.booleanPointInPolygon(turfPt, s.feature)) {
                               const sid = s.feature.properties.node_id;
                               if (!layersBySite[sid]) layersBySite[sid] = [];
                               layersBySite[sid].push(l);
                               found = true; break;
                           }
                        } catch(e) {}
                    }
                    if (found) return;

                    // C. Nearest Neighbor (Distance < 2km)
                    let minDist = Infinity;
                    let bestSiteIdx = -1;

                    allSites.forEach((s, idx) => {
                         const boundaries = siteBoundaries[idx];
                         if (!boundaries || boundaries.length === 0) return;
                         
                         // Find min distance to this site's boundary
                         let localMin = Infinity;
                         boundaries.forEach(line => {
                             const d = window.turf.pointToLineDistance(turfPt, line, { units: 'kilometers' });
                             if (d < localMin) localMin = d;
                         });

                         if (localMin < minDist) {
                             minDist = localMin;
                             bestSiteIdx = idx;
                         }
                    });

                    // Threshold: 2.0 km
                    if (bestSiteIdx !== -1 && minDist <= 2.0) {
                        const s = allSites[bestSiteIdx];
                        const sid = s.feature.properties.node_id;
                        
                        if (!layersBySite[sid]) layersBySite[sid] = [];
                        
                        // Mark for inclusion
                        l.feature.properties._force_include = true;
                        
                        layersBySite[sid].push(l);
                    }
                    // Else: Exclude from stats (Orphan > 2km)
                });
            }

            // 2b. [New] Pre-calculate Zone Ownership (Hierarchy: Device -> Zone -> Site)
            // Ensures 1-to-1 mapping and handles overlapping zones by assigning them to the 'best' site.
            const zoneOwnership = {}; // { zoneId: siteId }

            // Pass 1: Explicit Parent or Centroid Inclusion
            allZones.forEach(z => {
                const zid = z.feature.properties.node_id;
                const pid = z.feature.properties.parent_node_id;

                // A. Explicit Parent
                if (pid) {
                    zoneOwnership[zid] = pid;
                    return;
                }

                // B. Centroid Inclusion
                if (z.feature && z.feature.geometry) {
                    try {
                        const center = window.turf.centroid(z.feature);
                        for (const s of allSites) {
                            if (window.turf.booleanPointInPolygon(center, s.feature)) {
                                zoneOwnership[zid] = s.feature.properties.node_id;
                                break; // Belong to first containing site
                            }
                        }
                    } catch (e) {}
                }
            });

            // Pass 2: Overlap Inclusion (for Orphans)
            // If a zone's centroid is outside, assign it to the site with largest overlap.
            allZones.forEach(z => {
                const zid = z.feature.properties.node_id;
                if (zoneOwnership[zid]) return; // Already assigned

                if (z.feature && z.feature.geometry) {
                    let bestSiteId = null;
                    let maxOverlapArea = 0;

                    allSites.forEach(s => {
                        try {
                            // Quick check
                            if (window.turf.booleanIntersects(z.feature, s.feature)) {
                                const intersection = window.turf.intersect(z.feature, s.feature);
                                if (intersection) {
                                    const area = window.turf.area(intersection);
                                    if (area > maxOverlapArea) {
                                        maxOverlapArea = area;
                                        bestSiteId = s.feature.properties.node_id;
                                    }
                                }
                            }
                        } catch (e) {}
                    });

                    if (bestSiteId) {
                        zoneOwnership[zid] = bestSiteId;
                    }
                }
            });

            // 3. Process Sites and Zones using Categorized Data
            const findLabelName = (nodeId) => {
                if (!nodeId) return null;
                let label = null;
                if (this.parent.layerStorage['label_aux']) {
                    this.parent.layerStorage['label_aux'].eachLayer(l => {
                        if (l.feature?.properties?.parent_node_id === nodeId) {
                            label = l.feature.properties.label_name || l.feature.properties.name || l.feature.properties.text;
                        }
                    });
                }
                return label;
            };

            const isDefaultName = (name) => !name || /^(New site|Site|대지|구역|Zone)\s*\d*$/i.test(name);

            allSites.forEach(siteLayer => {
                const sitePoly = siteLayer.feature;
                const sid = sitePoly.properties.node_id;
                let siteName = sitePoly.properties.name;
                const label = findLabelName(sid);
                if (isDefaultName(siteName) && label) siteName = label;
                siteName = siteName || label || `${_('default_site_name')} ${data.sites.length + 1}`;

                // Determine Zones belonging to this Site
                const zonesInSite = allZones.filter(z => zoneOwnership[z.feature.properties.node_id] === sid);

                // Total layers for this site = site-level + all layers in embedded zones
                let siteTotalLayers = [...(layersBySite[sid] || [])];
                
                zonesInSite.forEach(z => {
                    const zid = z.feature.properties.node_id;
                    if (layersByZone[zid]) siteTotalLayers = siteTotalLayers.concat(layersByZone[zid]);
                    
                    // [Fix] Also include layers that explicitly parent to this Zone (stored in layersBySite map)
                    if (layersBySite[zid]) siteTotalLayers = siteTotalLayers.concat(layersBySite[zid]);
                });

                // [Fix] Force inclusion for Structural Child Zones (Hierarchy Rule)
                // Since we determined ownership (via Centroid or Overlap), EVERYTHING in the zone belongs to the site.
                siteTotalLayers.forEach(l => {
                    if (l.feature && l.feature.properties) {
                        l.feature.properties._force_include = true;
                    }
                });

                const siteStats = window.AoTMapUtils.calculatePolygonStats(sitePoly, siteTotalLayers);
                const siteData = { id: sid, name: siteName, stats: siteStats, zones: [], pipes: [] };

                const zoneAgg = { 
                    area: 0, 
                    pipeMainLen: 0, pipeBranchLen: 0, 
                    pipeMainCount: 0, pipeBranchCount: 0, // [Fix] Initialize counts
                    emitters: 0, waterUsage: 0, input: 0, output: 0, function: 0, 
                    pipeIds: new Set(), sprinklerIds: new Set() 
                };

                zonesInSite.forEach(zoneLayer => {
                    const zonePoly = zoneLayer.feature;
                    const zid = zonePoly.properties.node_id;
                    
                    // [Fix] Aggregate layers from both buckets:
                    // 1. layersByZone: Spatially assigned or via zone_id
                    // 2. layersBySite: Explicitly assigned via parent_node_id
                    const zoneLayers = (layersByZone[zid] || []).concat(layersBySite[zid] || []);
                    
                    const zoneStats = window.AoTMapUtils.calculatePolygonStats(zonePoly, zoneLayers);
                    
                    zoneAgg.area += zoneStats.area;
                    zoneAgg.pipeMainLen += zoneStats.pipeMainLen;
                    zoneAgg.pipeBranchLen += zoneStats.pipeBranchLen;
                    // [Fix] Aggregate Counts
                    zoneAgg.pipeMainCount += (zoneStats.pipeMainCount || 0);
                    zoneAgg.pipeBranchCount += (zoneStats.pipeBranchCount || 0);

                    zoneAgg.emitters += zoneStats.emitters;
                    zoneAgg.waterUsage += zoneStats.waterUsage;
                    zoneAgg.input += zoneStats.input;
                    zoneAgg.output += zoneStats.output;
                    zoneAgg.function += zoneStats.function;
                    zoneStats.pipeDetails.forEach(p => zoneAgg.pipeIds.add(p.uniqueId));
                    zoneStats.objects.sprinklers.forEach(s => zoneAgg.sprinklerIds.add(s.properties?.node_id));

                    let zName = zonePoly.properties.name;
                    const zLabel = findLabelName(zid);
                    if (isDefaultName(zName) && zLabel) zName = zLabel;

                    siteData.zones.push({
                        id: zid,
                        name: zName || zLabel || `${_('default_zone_name')} ${siteData.zones.length + 1}`,
                        stats: zoneStats,
                        pipes: window.AoTMapUtils.mapSprinklersToPipes(zoneStats.pipeDetails, zoneStats.objects.sprinklers)
                    });
                });

                // Calculate "Site Common" as leftover using robust Union (prevent freezing)
                let occupiedArea = 0;
                try {
                    // Robust Union Calculation to prevent infinite loop/crash
                    const polyList = [];
                    zonesInSite.forEach(z => {
                        if (z.feature && z.feature.geometry) polyList.push(z.feature);
                    });

                    if (polyList.length > 0) {
                        let unionPoly = polyList[0];
                        // Iterative union with error handling for each step
                        for (let i = 1; i < polyList.length; i++) {
                            try {
                                if (!polyList[i]) continue;
                                const res = window.turf.union(unionPoly, polyList[i]);
                                if (res) unionPoly = res;
                            } catch (err) {
                                // Specific polygon failed to union - skip it to keep app alive
                                console.warn("[DesignStats] Union failed for a zone, skipping:", err);
                            }
                        }
                        occupiedArea = window.turf.area(unionPoly);
                        occupiedArea = parseFloat(occupiedArea.toFixed(2));
                    }
                } catch (e) {
                    console.error("[DesignStats] Robust Union Fatal Error, fallback to sum:", e);
                    occupiedArea = zoneAgg.area; // Fallback to simple sum
                }

                if (siteData.zones.length > 0) {
                    const commonStats = {
                        area: Math.max(0, siteStats.area - occupiedArea),
                        pipeMainLen: Math.max(0, siteStats.pipeMainLen - zoneAgg.pipeMainLen),
                        pipeBranchLen: Math.max(0, siteStats.pipeBranchLen - zoneAgg.pipeBranchLen),
                        // [Fix] Calculate Common Counts
                        pipeMainCount: Math.max(0, (siteStats.pipeMainCount || 0) - zoneAgg.pipeMainCount),
                        pipeBranchCount: Math.max(0, (siteStats.pipeBranchCount || 0) - zoneAgg.pipeBranchCount),
                        
                        emitters: Math.max(0, siteStats.emitters - zoneAgg.emitters),
                        waterUsage: Math.max(0, siteStats.waterUsage - zoneAgg.waterUsage),
                        input: Math.max(0, siteStats.input - zoneAgg.input),
                        output: Math.max(0, siteStats.output - zoneAgg.output),
                        function: Math.max(0, siteStats.function - zoneAgg.function),
                        pipeDetails: siteStats.pipeDetails.filter(p => !zoneAgg.pipeIds.has(p.uniqueId)),
                        objects: { sprinklers: siteStats.objects.sprinklers.filter(s => !zoneAgg.sprinklerIds.has(s.properties?.node_id)) }
                    };

                    if (commonStats.pipeMainLen > 0.1 || commonStats.pipeBranchLen > 0.1 || commonStats.emitters > 0) {
                        siteData.zones.unshift({
                            name: _('site_common_name'),
                            stats: commonStats,
                            pipes: window.AoTMapUtils.mapSprinklersToPipes(commonStats.pipeDetails, commonStats.objects.sprinklers),
                            isCommon: true
                        });
                    }
                } else {
                    siteData.pipes = window.AoTMapUtils.mapSprinklersToPipes(siteStats.pipeDetails, siteStats.objects.sprinklers);
                }

                data.sites.push(siteData);
            });

            // Final Global Aggregation & Sorting
            this._aggregateMainPipes(data);
            this._sortDesignData(data);

            this._cachedDesignData = data;
            this._renderDesignInfoUI(data);

        } catch (e) {
            console.error("[DesignStats] Update Error:", e);
        } finally {
            this._updating = false;
        }
    }

    _aggregateMainPipes(data) {
        const mainPipeMap = {};
        const allPipes = [];
        data.sites.forEach(s => {
            (s.pipes || []).forEach(p => { allPipes.push(p); if (p.sub_type === 'pipe_main') mainPipeMap[p.uniqueId] = p; });
            (s.zones || []).forEach(z => {
                (z.pipes || []).forEach(p => { allPipes.push(p); if (p.sub_type === 'pipe_main') mainPipeMap[p.uniqueId] = p; });
            });
        });

        Object.values(mainPipeMap).forEach(m => { m._sprink = m.sprinklerCount || 0; m._water = m.waterUsage || 0; });
        allPipes.forEach(b => {
            if (b.sub_type === 'pipe_branch') {
                const mid = b.feature?.properties?.connected_main_id;
                if (mid && mainPipeMap[mid]) {
                    mainPipeMap[mid]._sprink += (b.sprinklerCount || 0);
                    mainPipeMap[mid]._water += (b.waterUsage || 0);
                }
            }
        });
        Object.values(mainPipeMap).forEach(m => { m.sprinklerCount = m._sprink; m.waterUsage = m._water; delete m._sprink; delete m._water; });
    }

    _sortDesignData(data) {
        if (!data.sites) return;
        data.sites.sort((a, b) => a.name.localeCompare(b.name, 'ko-KR', { numeric: true }));
        data.sites.forEach(s => {
            if (s.zones) s.zones.sort((a, b) => a.isCommon ? -1 : (b.isCommon ? 1 : a.name.localeCompare(b.name, 'ko-KR', { numeric: true })));
        });
    }
    
    _renderDesignInfoUI(data) {
        try {
            const container = document.getElementById('design-info-container');
            if (!container) return;
            
            if (!data || !data.sites) {
                container.innerHTML = `<div class="text-center text-danger py-3">${_('data_load_failed')}</div>`;
                return;
            }

            const sites = data.sites;
            
            // --- Selection Logic ---
            let displaySites = sites;

            // Initialize selection state
            if (!this._selectedSiteIds) {
                this._selectedSiteIds = sites.map(s => s.id); 
            } else {
                const currentIds = sites.map(s => s.id);
                this._selectedSiteIds = this._selectedSiteIds.filter(id => currentIds.includes(id));
                if (this._selectedSiteIds.length === 0 && sites.length > 0) {
                    this._selectedSiteIds = sites.map(s => s.id);
                }
            }

            const showSelector = (sites.length >= 2);
            if (showSelector) {
                 displaySites = sites.filter(s => this._selectedSiteIds.includes(s.id));
            } else {
                 displaySites = sites;
            }

            // Recalculate Totals based on DisplaySites
            const totals = {
                siteCount: displaySites.length, 
                zoneCount: 0, 
                deviceCount: 0, 
                totalPipeLen: 0,
                // Details
                area: 0, 
                pipeMainLen: 0, pipeMainCount: 0, // [New]
                pipeBranchLen: 0, pipeBranchCount: 0, // [New]
                emitters: 0, waterUsage: 0,
                input: 0, output: 0, function: 0
            };

            displaySites.forEach(s => {
                // If Orphans are in zones list, zoneCount increases.
                // Do we count "Site Common" as a zone?
                // Probably yes for iteration, but maybe confusing for User Count.
                // Just count 'real' zones?
                const realZones = s.zones.filter(z => !z.isCommon);
                totals.zoneCount += realZones.length;
                
                totals.area += s.stats.area;
                totals.pipeMainLen += s.stats.pipeMainLen;
                totals.pipeBranchLen += s.stats.pipeBranchLen;
                totals.pipeMainCount += s.stats.pipeMainCount; // [New]
                totals.pipeBranchCount += s.stats.pipeBranchCount; // [New]
                totals.emitters += s.stats.emitters;
                totals.waterUsage += s.stats.waterUsage;
                totals.input += s.stats.input;
                totals.output += s.stats.output;
                totals.function += s.stats.function;
            });
            totals.totalPipeLen = totals.pipeMainLen + totals.pipeBranchLen;
            totals.deviceCount = totals.emitters + totals.input + totals.output + totals.function; 

            const fmt = (n) => (n || 0).toFixed(1);
            const fmtInt = (n) => (n || 0).toFixed(0);

            let html = '';
            
            // --- 0. Site Selector ---
            if (showSelector) {
                html += `<div class="mb-3 d-flex justify-content-start align-items-center">`;
                html += `<div style="max-width: 240px; min-width: 150px;">`;
                html += `<select id="site-selector" class="selectpicker site-selector-dropdown" multiple data-live-search="true" 
                                 data-actions-box="true" data-style="btn-outline-secondary bg-white overflow-hidden text-truncate custom-select-btn" 
                                 data-width="100%" data-selected-text-format="count > 2" title="${_('design_info_site_select')}">`;
                displaySites.forEach(s => { // Bug: Dropdown should show ALL sites, not filtered ones.
                    // Fix: Use 'sites' (all) for dropdown options
                });
                sites.forEach(s => {
                     const isSel = this._selectedSiteIds.includes(s.id) ? 'selected' : '';
                     html += `<option value="${s.id}" ${isSel}>${s.name}</option>`;
                });
                html += `</select></div>`;
                html += `<button id="btn-site-filter" class="btn btn-sm btn-primary ml-2 shadow-sm" style="height: 32px; line-height: 1;">${_('design_info_select_btn')}</button>`;
                html += `</div>`;
                html += `<style>.custom-select-btn { height: 32px !important; line-height: 1.5 !important; padding-top: 4px !important; padding-bottom: 4px !important; } .bootstrap-select .dropdown-toggle .filter-option { height: 100%; display: flex; align-items: center; }</style>`;
            }

            // --- 1. Summary ---
            // Removed connection stats from Summary (as per request, Site/Zone specific)
            html += `<h6 class="font-weight-bold mb-2 pt-1 border-bottom pb-2">${_('design_info_summary')}</h6>`;
            html += `
            <table class="table table-bordered table-sm mb-4 text-center bg-white">
                <thead class="thead-light"><tr>
                    <th>${_('design_info_site_count')}</th><th>${_('design_info_zone_count')}</th><th>${_('design_info_pipe_len')}</th><th>${_('design_info_emitter_count')}</th><th>${_('design_info_aot_device_count')}</th>
                </tr></thead>
                <tbody><tr>
                    <td class="font-weight-bold">${totals.siteCount}</td>
                    <td class="font-weight-bold">${totals.zoneCount}</td>
                    <td class="font-weight-bold">${fmt(totals.totalPipeLen)}m</td>
                    <td class="font-weight-bold">${totals.emitters}</td>
                    <td class="font-weight-bold">${totals.input + totals.output + totals.function}</td>
                </tr></tbody>
            </table>`;

            // --- Helpers (Hoisted) ---
            // Helper to render pipe tables
            const renderPipeTables = (pipes, indentClass) => {
                if (!pipes || pipes.length === 0) return `<div class="text-center text-muted mb-3 small ${indentClass}">${_('design_info_no_pipe_data')}</div>`;
                
                const mains = pipes.filter(p => p.type === '주배관' || (p.type && p.type.includes('Main')));
                const branch = pipes.filter(p => !mains.includes(p));
                const pad = (num) => String(num).padStart(3, '0');

                let out = '';
                const tableHeader = `
                    <table class="table table-sm table-hover text-center bg-white mb-2" style="font-size:0.85rem;">
                    <thead class="thead-light"><tr>
                        <th style="width:20%">${_('design_info_th_no')}</th><th>${_('design_info_th_len')}</th><th>${_('design_info_th_emitter')}</th><th>${_('design_info_th_flow_lh')}</th><th>${_('design_info_th_flow_lmin')}</th>
                    </tr></thead><tbody>`;

                if (mains.length > 0) {
                     out += `<div class="font-weight-bold small text-dark mb-1 ${indentClass}">${_('design_info_pipe_type_main')}</div>`;
                     out += `<div class="${indentClass}"><div class="table-responsive mb-3">` + tableHeader;
                     mains.forEach((p, i) => {
                         const id = `M-${pad(i + 1)}`;
                         out += `<tr><td>${id}</td><td>${fmt(p.length)}</td><td>${p.sprinklerCount}</td><td>${fmt(p.waterUsage)}</td><td>${fmt(p.waterUsage/60)}</td></tr>`;
                     });
                     out += `</tbody></table></div></div>`;
                }
                
                if (branch.length > 0) {
                     out += `<div class="font-weight-bold small text-dark mb-1 ${indentClass}">${_('design_info_pipe_type_branch')}</div>`;
                     out += `<div class="${indentClass}"><div class="table-responsive mb-3">` + tableHeader;
                     branch.forEach((p, i) => {
                         const id = `B-${pad(i + 1)}`;
                         out += `<tr><td>${id}</td><td>${fmt(p.length)}</td><td>${p.sprinklerCount}</td><td>${fmt(p.waterUsage)}</td><td>${fmt(p.waterUsage/60)}</td></tr>`;
                     });
                     out += `</tbody></table></div></div>`;
                }
                return out;
            };

            // Helper to render rows conditionally (If value > 0)
            function renderRow(label, value, unit = '', force = false) {
                 if (!force && (value === 0 || value === '0.0')) return '';
                 const valStr = (typeof value === 'number') ? (Number.isInteger(value) ? value : value.toFixed(1)) : value;
                 return `<tr><th class="bg-light text-center">${label}</th><td>${valStr} ${unit}</td></tr>`;
            }

            // Helper to render connection stats (as separate rows)
            // Helper to render connection stats (new spec)
            const renderConnRows = (conn, category) => {
                if (!conn) return '';
                let rows = '';
                if (category === 'main') {
                    if (conn.mT > 0) rows += `<tr><th class="bg-light text-center">${_('fitting_main_tee')}</th><td>${conn.mT} ${_('unit_count')}</td></tr>`;
                    if (conn.mE > 0) rows += `<tr><th class="bg-light text-center">${_('fitting_main_elbow')}</th><td>${conn.mE} ${_('unit_count')}</td></tr>`;
                    if (conn.mC > 0) rows += `<tr><th class="bg-light text-center">${_('fitting_main_end')}</th><td>${conn.mC} ${_('unit_count')}</td></tr>`;
                    if (conn.mbT > 0) rows += `<tr><th class="bg-light text-center">${_('fitting_main_reducing_tee')}</th><td>${conn.mbT} ${_('unit_count')}</td></tr>`;
                    if (conn.mbE > 0) rows += `<tr><th class="bg-light text-center">${_('fitting_main_reducing_elbow')}</th><td>${conn.mbE} ${_('unit_count')}</td></tr>`; // [New] mbE
                } else {
                    if (conn.bT > 0) rows += `<tr><th class="bg-light text-center">${_('fitting_branch_tee')}</th><td>${conn.bT} ${_('unit_count')}</td></tr>`;
                    if (conn.bE > 0) rows += `<tr><th class="bg-light text-center">${_('fitting_branch_elbow')}</th><td>${conn.bE} ${_('unit_count')}</td></tr>`;
                    if (conn.bC > 0) rows += `<tr><th class="bg-light text-center">${_('fitting_branch_end')}</th><td>${conn.bC} ${_('unit_count')}</td></tr>`;
                }
                return rows;
            };

            // --- 2. Total Details (Only if > 1 site) ---
            if (displaySites.length > 1) {
                // Calculate Aggregated Connection Stats for Total Details
                // ... (Total calc omitted for brevity, logic remains same)
                const totalConn = { mT: 0, mE: 0, mC: 0, mbT: 0, mbE: 0, bT: 0, bE: 0, bC: 0 };
                displaySites.forEach(s => {
                    const c = s.stats.connections || { mT:0, mE:0, mC:0, mbT:0, mbE:0, bT:0, bE:0, bC:0 };
                    totalConn.mT += c.mT;
                    totalConn.mE += c.mE;
                    totalConn.mC += c.mC;
                    totalConn.mbT += c.mbT;
                    totalConn.mbE += c.mbE;
                    totalConn.bT += c.bT;
                    totalConn.bE += c.bE;
                    totalConn.bC += c.bC;
                });

                html += `<h6 class="font-weight-bold mb-2 border-bottom pb-2">${_('design_info_details')}</h6>`;
                html += `
                <table class="table table-bordered table-sm mb-4 text-right bg-white" style="font-size:0.9rem;">
                    <tbody>
                        ${renderRow(_('design_info_total_area'), totals.area, "m²", true)}
                        ${renderRow(_('design_info_main_pipe_len'), totals.pipeMainLen, "m")}
                        ${renderRow(_('design_info_main_pipe_count'), totals.pipeMainCount, _('unit_count'))}
                        ${renderRow(_('design_info_branch_pipe_len'), totals.pipeBranchLen, "m")}
                        ${renderRow(_('design_info_branch_pipe_count'), totals.pipeBranchCount, _('unit_count'))}
                        ${renderRow(_('design_info_emitter_count'), totals.emitters, _('unit_count'))}
                        ${renderRow(_('design_info_flow_lh'), totals.waterUsage, "L/h")}
                        ${renderRow(_('design_info_flow_lmin'), totals.waterUsage/60, "L/min")}
                        ${renderConnRows(totalConn, 'main')}
                        ${renderConnRows(totalConn, 'branch')}
                        ${renderRow(_('design_info_input_count'), totals.input, _('unit_count'))}
                        ${renderRow(_('design_info_output_count'), totals.output, _('unit_count'))}
                        ${renderRow(_('design_info_function_count'), totals.function, _('unit_count'))}
                    </tbody>
                </table>`;
            }



            // --- 3. Site Details (Filtered by DisplaySites) ---
            if (displaySites.length === 0) {
                 html += `<div class="text-center text-muted my-3">${_('design_info_no_sites')}</div>`;
            } else {
                displaySites.forEach((site, idx) => {
                    const ss = site.stats;
                    const c = ss.connections || { main: {elbow:0,tee:0,end:0}, branch: {elbow:0,tee:0,end:0} };
                    
                    html += `<h6 class="font-weight-bold mb-2 border-bottom pb-2 mt-4"><a href="#" onclick="window.geoDesign.panToShape('${site.id}'); return false;">3-${idx + 1}. ${site.name}</a></h6>`;
                    html += `
                    <table class="table table-bordered table-sm mb-3 text-right bg-white" style="font-size:0.9rem;">
                        <tbody>
                            ${renderRow(_('design_info_site_area'), ss.area, "m²", true)}
                            ${renderRow(_('design_info_main_pipe_len'), ss.pipeMainLen, "m")}
                            ${renderRow(_('design_info_main_pipe_count'), ss.pipeMainCount, _('unit_count'))}
                            ${renderRow(_('design_info_branch_pipe_len'), ss.pipeBranchLen, "m")}
                            ${renderRow(_('design_info_branch_pipe_count'), ss.pipeBranchCount, _('unit_count'))}
                            ${renderRow(_('design_info_emitter_count'), ss.emitters, _('unit_count'))}
                            ${renderRow(_('design_info_flow_lh'), ss.waterUsage, "L/h")}
                            ${renderRow(_('design_info_flow_lmin'), ss.waterUsage/60, "L/min")}
                            ${renderConnRows(c, 'main')}
                            ${renderConnRows(c, 'branch')}
                            ${renderRow(_('design_info_input_count'), ss.input, _('unit_count'))}
                            ${renderRow(_('design_info_output_count'), ss.output, _('unit_count'))}
                            ${renderRow(_('design_info_function_count'), ss.function, _('unit_count'))}
                        </tbody>
                    </table>`;

                    if (site.zones.length === 0) {
                        html += `<h6 class="font-weight-bold mb-2 ml-2 text-secondary" style="font-size:0.9rem;">${_('design_info_site_pipe_info')}</h6>`;
                        html += renderPipeTables(site.pipes, 'ml-2');
                    } else {
                        site.zones.forEach((zone, zIdx) => {
                            const zs = zone.stats;
                            const zc = zs.connections || { main: {elbow:0,tee:0,end:0}, branch: {elbow:0,tee:0,end:0} };
                            const titleColor = zone.isCommon ? 'text-secondary' : 'text-success';
                            
                            html += `<h6 class="font-weight-bold mb-2 ml-2" style="font-size:0.9rem;"><a href="#" class="${titleColor}" onclick="window.geoDesign.panToShape('${zone.id}'); return false;">- ${zone.name}</a></h6>`;
                            html += `
                            <table class="table table-bordered table-sm mb-2 ml-2 text-right bg-white" style="font-size:0.85rem; width:98%;">
                                <tbody>
                                    ${renderRow(_('design_info_area'), zs.area, "m²", true)}
                                    ${renderRow(_('design_info_main_pipe_len'), zs.pipeMainLen, "m")}
                                    ${renderRow(_('design_info_main_pipe_count'), zs.pipeMainCount, _('unit_count'))}
                                    ${renderRow(_('design_info_branch_pipe_len'), zs.pipeBranchLen, "m")}
                                    ${renderRow(_('design_info_branch_pipe_count'), zs.pipeBranchCount, _('unit_count'))}
                                    ${renderRow(_('design_info_emitter_count'), zs.emitters, _('unit_count'))}
                                    ${renderRow(_('design_info_flow_lh'), zs.waterUsage, "L/h")}
                                    ${renderRow(_('design_info_flow_lmin'), zs.waterUsage/60, "L/min")}
                                    ${renderConnRows(zc, 'main')}
                                    ${renderConnRows(zc, 'branch')}
                                    ${renderRow(_('design_info_input_count'), zs.input, _('unit_count'))}
                                    ${renderRow(_('design_info_output_count'), zs.output, _('unit_count'))}
                                    ${renderRow(_('design_info_function_count'), zs.function, _('unit_count'))}
                                </tbody>
                    </table>`;
                            html += `<h6 class="font-weight-bold mb-1 ml-4 text-muted small">${_('design_info_pipe_details')}</h6>`;
                            html += renderPipeTables(zone.pipes, 'ml-4');
                        });
                    }
                });
            }

            container.innerHTML = html;
            
            // Re-bind Events
            if (showSelector && typeof $ !== 'undefined') {
                 // Initialize Bootstrap Select
                 $('#site-selector').selectpicker();
                 
                 // [Logic] Button Click -> Filter
                 const btn = document.getElementById('btn-site-filter');
                 if (btn) {
                     btn.onclick = () => {
                         const val = $('#site-selector').val(); // array of strings
                         this._selectedSiteIds = val;
                         // console.log("[Stats] Filter applied:", this._selectedSiteIds);
                         // Re-render with cached data
                         if (this._cachedDesignData) this._renderDesignInfoUI(this._cachedDesignData);
                     };
                 }
            } 
        } catch (e) {
            // console.error("[DesignInfo] Render Error:", e);
        }
    }
}
