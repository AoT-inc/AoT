/**
 * aot-geo-modules.js
 * Device, Equipment, and Specialty Module Management for AoTGeoDesign
 */

class AoTGeoModules {
    constructor(parent) {
        this.parent = parent;
    }

    /**
     * Handle Shape Creation Logic (Association, Automatic Generation, etc.)
     */
    onShapeCreated(layer, type, drawingType) {
        console.log(`[GeoModules] onShapeCreated Entry. Type: ${type}, PendingOp:`, this.parent.pendingOp);
        // [V7 Fix] Absolute safety: clear loading flag immediately to allow saving.
        this.parent.isLoading = false;

        // [Safety Fix] Immediate Geometry Validation & Auto-Delete
        // Prevents tiny/invalid geometries from causing Backend 500 errors and state corruption.
        if (window.turf) {
            try {
                let geojson = layer.toGeoJSON ? layer.toGeoJSON() : layer.feature;
                if (layer instanceof L.Circle) {
                    const center = layer.getLatLng();
                    const radius = layer.getRadius();
                    geojson = window.turf.circle([center.lng, center.lat], radius, { steps: 64, units: 'meters' });
                }

                if (geojson && geojson.geometry) {
                    const gType = geojson.geometry.type;
                    let isTooSmall = false;
                    let errorMsg = "";

                    if (gType === 'Polygon' || gType === 'MultiPolygon') {
                        const area = window.turf.area(geojson);
                        if (area < 0.01) { // 0.01m2
                            isTooSmall = true;
                            errorMsg = `도형이 너무 작습니다 (${area.toFixed(4)}m²). 최소 0.01m² 이상이어야 합니다.`;
                        }
                        // Check for self-intersection (kinks)
                        const kinks = window.turf.kinks(geojson);
                        if (kinks.features.length > 0) {
                            isTooSmall = true;
                            errorMsg = "도형이 자기 자신과 교차합니다 (Self-intersection). 유효하지 않은 기하구조입니다.";
                        }
                    } else if (gType === 'LineString' || gType === 'MultiLineString') {
                        const lengthM = window.turf.length(geojson, { units: 'meters' });
                        if (lengthM < 0.1) { // 10cm
                            isTooSmall = true;
                            errorMsg = `선이 너무 짧습니다 (${lengthM.toFixed(3)}m). 최소 10cm 이상이어야 합니다.`;
                        }
                    } 
                    if (isTooSmall) {
                        // console.warn(`[GeoDesign] Blocking Invalid Shape: ${errorMsg}`);
                        if (this.parent.ui) this.parent.ui.showToast(errorMsg, 'warning');
                        
                        // Immediate Cleanup
                        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup.hasLayer(layer)) {
                            window.AoTMapEditor.featureGroup.removeLayer(layer);
                        }
                        if (this.parent.map.hasLayer(layer)) this.parent.map.removeLayer(layer);
                        return; // ABORT
                    }
                }
            } catch (e) {
                console.error("[GeoDesign] Validation Error:", e);
                // Continue if validation itself fails, better to save than to block everything, 
                // but usually turf is reliable.
            }
        }

        // 0. Initial Property Setup for Pipes
        if (this.parent.pendingOp) {
            const drawId = window.uuidv4 ? window.uuidv4() : 'draw-' + Math.random().toString(36).substr(2, 9);
            const opType = this.parent.pendingOp.type;

            if (opType === 'create_ref_line') {
                layer.feature = layer.feature || { properties: {} };
                layer.feature.properties.aot_type = 'reference';
                layer.feature.properties.sub_type = 'reference_line';
                layer.feature.properties.name = 'Reference Line';
                layer.feature.properties._aot_draw_id = drawId;
                // this.parent._resetPendingOp(); // [Fix V11] Moved to DRAWSTOP for Repeat Mode
            } else if (opType === 'create_main_pipe') {
                layer.feature = layer.feature || { properties: {} };
                layer.feature.properties.aot_type = 'equipment';
                layer.feature.properties.sub_type = 'pipe_main';
                layer.feature.properties.name = 'Main Pipe';
                layer.feature.properties._aot_draw_id = drawId;
                // this.parent._resetPendingOp();
            } else if (opType === 'create_branch_pipe') {
                layer.feature = layer.feature || { properties: {} };
                layer.feature.properties.aot_type = 'equipment';
                layer.feature.properties.sub_type = 'pipe_branch';
                layer.feature.properties.name = 'Branch Pipe';
                layer.feature.properties._aot_draw_id = drawId;
                // this.parent._resetPendingOp();
            } else if (opType === 'create_valve') {
                layer.feature = layer.feature || { properties: {} };
                layer.feature.properties.aot_type = 'equipment';
                layer.feature.properties.sub_type = 'valve';
                layer.feature.properties.name = 'Valve';
                if (this.parent.geometry) this.parent.geometry.handleValvePlacement(layer);
                // this.parent._resetPendingOp();
            }
        }

        // [Logic Fix] Unified Pipe Processing (Splitting, UUID, Connections)
        const subType = layer.feature?.properties?.sub_type;
        if (subType && subType.startsWith('pipe')) {
            if (this.parent.geometry) {
                // 1. Check for selective splitting (80-110 deg elbows)
                const newPipes = this.parent.geometry.processSelectiveSplitting(layer);
                
                if (newPipes && newPipes.length > 0) {
                    console.log(`[PipeSystem] Pipe split into ${newPipes.length} segments.`);
                    newPipes.forEach(p => {
                        this._ensurePipeProperties(p, type);
                        this.parent._processLoadedFeature(p, type);
                        this.parent.geometry.updatePipeLabels(p);
                    });
                    // Rebuild all to find Elbows between split segments
                    this.parent.geometry.rebuildConnections();
                    
                    // [Fix] Save immediately because we return early
                    this.parent.saveDesign([type], true);
                    return; // Done
                }
                
                // [Fix] Normal Pipe Label Update (if not split)
                this.parent.geometry.updatePipeLabels(layer);
            }
        }

        // --- Standard Logic for non-split or non-pipe shapes ---

        // [New] AoT Device Shape Linking (Activation Mode)
        // Check active device status via Parent (aot-geo-design -> aot-geo-devices)
        if (this.parent.devices && this.parent.devices.activeDevice) {
            const activeDev = this.parent.devices.activeDevice;
            layer.feature = layer.feature || { properties: {} };
            layer.feature.properties = layer.feature.properties || {};
            
            // Set Critical Properties for Backend Logic
            layer.feature.properties.aot_type = 'device';
            
            // [Fix] Handle Composite IDs (uuid::ch)
            let devId = activeDev.unique_id;
            let chanId = activeDev.channel_id;
            if (devId && devId.includes('::')) {
                const parts = devId.split('::');
                devId = parts[0];
                if (chanId === undefined || chanId === null) chanId = parts[1];
            }
            
            layer.feature.properties.device_id = devId;
            layer.feature.properties.channel_id = chanId;
            layer.feature.properties.device_type = activeDev.type;
            
            // [Fix] Explicitly assign device name to prevent "New aot_device" override
            if (activeDev.name) {
                layer.feature.properties.name = activeDev.name;
                layer.feature.properties.label_name = activeDev.name; // Keep label in sync
            } 

            // Apply Theme Color Immediately
            const devType = activeDev.type;
            let themeColor = '#995aff'; // Default
            if (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) {
                 // Try specific device theme first? Or generic device?
                 // Usually device shapes use global device theme or specific type theme
                 themeColor = window.AOT_GEO_CONFIG.theme_config['device'] || themeColor;
            }
            
            if (layer.setStyle) {
                layer.setStyle({ color: themeColor, fillColor: themeColor, fillOpacity: 0.5 });
            }
            
            // Force type override so it saves to correct 'device' slot
            type = 'device'; 
        }

        this._ensurePipeProperties(layer, type);
        
        // [Fix] Orphan Reference Line Check
        const fType = layer.feature.properties.aot_type;
        if (fType === 'reference') {
            if (!layer.feature.properties.parent_node_id) {
                const refGeo = layer.toGeoJSON();
                let foundParent = false;

                // 1. Check Zones
                if (this.parent.layerStorage['zone']) {
                    this.parent.layerStorage['zone'].eachLayer(z => {
                        if (foundParent) return;
                        const zGeo = z.toGeoJSON();
                        if (window.turf.booleanIntersects(refGeo, zGeo) || window.turf.booleanContains(zGeo, refGeo)) {
                            layer.feature.properties.parent_node_id = z.feature.properties.node_id;
                            foundParent = true;
                        }
                    });
                }

                // 2. Check Sites (if not found in zone)
                if (!foundParent && this.parent.layerStorage['site']) {
                    this.parent.layerStorage['site'].eachLayer(s => {
                        if (foundParent) return;
                        const sGeo = s.toGeoJSON();
                        if (window.turf.booleanIntersects(refGeo, sGeo) || window.turf.booleanContains(sGeo, refGeo)) {
                            layer.feature.properties.parent_node_id = s.feature.properties.node_id;
                            foundParent = true;
                        }
                    });
                }

                if (!foundParent) {
                    this.parent.ui.showToast(_('reference_line_auto_delete_warning'), 'warning');
                    if (window.AoTMapEditor && window.AoTMapEditor.featureGroup.hasLayer(layer)) window.AoTMapEditor.featureGroup.removeLayer(layer);
                    if (this.parent.map.hasLayer(layer)) this.parent.map.removeLayer(layer);
                    return; 
                }
            }
        }

        // 1. Label Tool
        if (drawingType === 'label') {
            const text = prompt("Enter Label Text:", "New Label");
            if (!text) {
                window.AoTMapEditor.featureGroup.removeLayer(layer);
                return;
            }
            layer.feature.properties.label_name = text;
            layer.feature.properties.label_area = '';
            layer.feature.properties.aot_type = 'label_aux';
            if (this.parent.labels) this.parent.labels.convertToLabel(layer);
            return;
        }

        // 2. Area & Auto-Label for Site/Zone
        // [Fix] Ensure we rely on the actual assigned type (e.g. pendingOp might have set it to equipment)
        const finalType = layer.feature?.properties?.aot_type || type;

        if (finalType === 'site' || finalType === 'zone') {
            if (!(layer instanceof L.Polyline && !(layer instanceof L.Polygon))) {
                let areaDisplay = '';
                try {
                    let geojson = layer.toGeoJSON();
                    if (layer instanceof L.Circle) {
                        const center = layer.getLatLng();
                        const radius = layer.getRadius();
                        geojson = window.turf.circle([center.lng, center.lat], radius, { steps: 64, units: 'meters' });
                    }
                    const area = window.turf.area(geojson);
                    areaDisplay = Math.round(area) + ' m²';
                    layer.feature.properties.area = area;
                    if (this.parent.labels) this.parent.labels.createAutoLabel(layer, "New " + type, areaDisplay);
                } catch (e) {
                    console.error("Area Calculation Failed:", e);
                    if (this.parent.labels) this.parent.labels.createAutoLabel(layer, "New " + type, "0 m²");
                }
            }
            if (this.parent.geometry) this.parent.geometry.updateMeasurementLabels(layer);
        } 
        // Auto Save
        // Auto Save & Storage Management
        // console.log("[AutoSave] Shape Created. Saving Design...");
        const targetType = layer.feature.properties.aot_type || type;
        if (targetType !== this.parent.activeMode) {
            const group = this.parent.layerStorage[targetType];
            if (group) {
                // [Fix] Ensure group is visible
                if (!this.parent.map.hasLayer(group)) {
                    this.parent.map.addLayer(group);
                }
                
                // [Fix] Move layer to correct storage (Critical for Reference Lines)
                if (window.AoTMapEditor && window.AoTMapEditor.featureGroup.hasLayer(layer)) {
                    window.AoTMapEditor.featureGroup.removeLayer(layer);
                    group.addLayer(layer);
                    
                    // [Fix] Re-apply style for the new context (e.g. Reference Line Style)
                    if (this.parent.ui && this.parent.ui._setLayerStyle) {
                        this.parent.ui._setLayerStyle(layer);
                    }
                } else if (!group.hasLayer(layer)) {
                    // Safety: Add if not in editor but not in group either
                    group.addLayer(layer);
                }
            }
        }

        // [V9 Fix] Immediate Save with Dependency Check
        // Ensure dirtyNodeIds is populated before saveDesign is triggered.
        const nid = layer.feature?.properties?.node_id;
        if (nid) this.parent.dirtyNodeIds.add(nid);

        if (this.parent.saveDesign) {
            // Slight delay to ensure labels and other properties are settled in the dirty set.
            setTimeout(() => {
                this.parent.saveDesign([type, 'label_aux'], true);
            }, 50);
        }

        // Activate
        setTimeout(() => {
            if (this.parent.map.hasLayer(layer) || (window.AoTMapEditor && window.AoTMapEditor.featureGroup.hasLayer(layer))) {
                if (typeof this.parent._setActiveLayer === 'function') {
                    this.parent._setActiveLayer(layer);
                }
            }
        }, 100);

        // 6. Update Design Stats & Connections
        this.parent.updateDesignInfo();
        if (this.parent.geometry) this.parent.geometry.rebuildConnections();
    }


    async generatePipes(parentFeature, config) {
        if (!parentFeature) {
            // console.warn("[GeoGen] Parent not found");
            if (this.parent && this.parent.ui) this.parent.ui.showToast('Parent feature (Site/Zone) not found', 'error');
            return;
        }

        // [Fix] Per-Feature Race Condition Protection
        const parentId = parentFeature.properties?.node_id;
        const requestId = Date.now();
        if (!this._pipeRequests) this._pipeRequests = {};
        this._pipeRequests[parentId] = requestId;

        // [Logic] Determine Reference Line (Priority: Config > Linked Layer > Auto Edge)
        let refLineGeo = config && config.refLine ? config.refLine.toGeoJSON() : null; 
        // 1. Search for user-drawn reference line linked to this parent
        if (!refLineGeo) {
            // console.log("[GeoGen] Searching for user-drawn reference line...");
            const findRef = (group) => {
                if (!group) return;
                group.eachLayer(l => {
                    if (refLineGeo) return;
                    const props = l.feature?.properties;
                    // Check for explicit 'reference' type and parent linkage
                    if (props && props.aot_type === 'reference' && props.parent_node_id === parentId) {
                        refLineGeo = l.toGeoJSON();
                        console.log(`[GeoGen] Using linked reference line: ${props.node_id}`);
                    }
                });
            };
            findRef(this.parent.layerStorage['reference']);
            if (!refLineGeo && window.AoTMapEditor) findRef(window.AoTMapEditor.featureGroup);
        } 
        
        // [New] 1.5. Spatial Fallback: Check for Orphan Reference Lines INSIDE the Parent
        if (!refLineGeo && window.turf) {
            console.log("[GeoGen] No linked reference line. Searching spatially for internal reference lines...");
            const findSpatialRef = (group) => {
                if (!group) return;
                group.eachLayer(l => {
                    if (refLineGeo) return; // Found already
                    const props = l.feature?.properties;
                    // Strict Type Check
                    if (props && props.aot_type === 'reference') {
                         try {
                             const lGeo = l.toGeoJSON();
                             // Check Intersection or Containment
                             // Usually Ref Line is fully inside or crosses it.
                             if (window.turf.booleanIntersects(lGeo, parentFeature) || window.turf.booleanContains(parentFeature, lGeo)) {
                                 refLineGeo = lGeo;
                                 console.log(`[GeoGen] Spatially found reference line: ${props.node_id}. Auto-linking...`);
                                 
                                 // Auto-Link to fix future persistence
                                 l.feature.properties.parent_node_id = parentId;
                                 // Mark dirty
                                 if (this.parent.dirtyNodeIds && props.node_id) this.parent.dirtyNodeIds.add(props.node_id);
                             }
                         } catch(e) { /* ignore geometry errors */ }
                    }
                });
            };
            findSpatialRef(this.parent.layerStorage['reference']);
            if (!refLineGeo && window.AoTMapEditor) findSpatialRef(window.AoTMapEditor.featureGroup);
        }
 
        // 2. Fallback: Longest Edge
        if (!refLineGeo) {
            // console.log("[GeoGen] No linked reference line found. Attempting to use longest edge...");
            if (parentFeature.geometry && parentFeature.geometry.type === 'Polygon' && window.turf) {
                try {
                    let maxLenKm = 0;
                    let bestSegment = null;
                    const coords = parentFeature.geometry.coordinates[0]; // Outer ring

                    for (let i = 0; i < coords.length - 1; i++) {
                        const start = coords[i];
                        const end = coords[i + 1];
                        const line = window.turf.lineString([start, end]);
                        const lenKm = window.turf.length(line, { units: 'kilometers' });
                        const lenM = lenKm * 1000;
                        
                        // Ignore artifacts / tiny segments (< 1m)
                        if (lenKm > maxLenKm && lenM > 1.0) {
                            maxLenKm = lenKm;
                            bestSegment = line;
                        }
                    }

                    if (bestSegment) {
                        refLineGeo = bestSegment;
                        console.log(`[GeoGen] Auto-selected longest valid edge (${(maxLenKm * 1000).toFixed(2)}m) as reference.`);
                    }
                } catch (e) {
                    console.error("Longest edge calculation failed:", e);
                }
            }
        } 
        if (!config || !refLineGeo) {
            // console.warn("[GeoGen] No Ref Line");
            if (this.parent && this.parent.ui) this.parent.ui.showToast('No reference line available. Please draw a reference line.', 'warning');
            return;
        }

        const mapUuid = this.parent.currentMapUuid;

        // Prepare Payload
        const payload = {
            parent_feature: parentFeature, // GeoJSON feature
            ref_line: refLineGeo,
            config: config,
            map_uuid: mapUuid
        };

        try {
            // Show Loading?
            // [Fix V11 Hotfix] Prioritize META tag because it's server-rendered fresh each page load.
            // window.csrf_token might be stale or undefined in some contexts.
            let csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
            let tokenSource = "meta";
            
            if (!csrfToken) {
                 csrfToken = window.csrf_token;
                 tokenSource = "window";
            }
            
            console.log(`[GeoModules] Generating Pipes. CSRF Source: ${tokenSource}, Token: ${csrfToken ? "Found (Length " + csrfToken.length + ")" : "Missing"}`);

            const response = await fetch('/api/geo/generate-pipes', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                console.error("[GeoModules] GenPipe Error Status:", response.status);
                const errText = await response.text();
                console.error("[GeoModules] GenPipe Error Body:", errText); // Debug body
                if (response.status === 400 && errText.includes('CSRF')) {
                     alert(_('session_expired'));
                }
                throw new Error(`Server Error: ${response.status} ${errText}`);
            }

            const data = await response.json();

            // [Fix] Race Condition: Discard if a newer request was sent for THIS parent
            if (this._pipeRequests[parentId] !== requestId) {
                // console.log(`[GeoGen] Discarding stale pipe generation result for ${parentId}.`);
                return;
            }

            // [Fix] Backend returns FeatureCollection directly or {ok:false, message:...}
            // Check for error explicitly first
            if (data.ok === false || (data.message && !data.features)) {
                alert('Error generating pipes: ' + (data.message || 'Unknown error'));
                return;
            }

            // Extract pipes (Backend returns 'features' list in FeatureCollection)
            const createdPipes = data.features || data.pipes;
            if (createdPipes && createdPipes.length > 0) {
                // [Auto-Update] Check for existing Sprinklers
                const parentId = parentFeature.properties.node_id;
                let hasSprinklers = false;

                const checkSpr = (l) => {
                    const p = l.feature?.properties;
                    if (p && p.sub_type === 'sprinkler') {
                        // 1. ID Check
                        if (p.parent_node_id === parentId || p.zone_id === parentId) {
                            hasSprinklers = true;
                            return;
                        }
                        // 2. Spatial Check (Fallback - matching clearEquipments logic)
                        if (window.turf && l.feature.geometry) {
                            try {
                                const center = window.turf.center(l.feature);
                                if (window.turf.booleanPointInPolygon(center, parentFeature)) {
                                    hasSprinklers = true;
                                }
                            } catch (e) { }
                        }
                    }
                };
                if (this.parent.layerStorage['equipment']) this.parent.layerStorage['equipment'].eachLayer(checkSpr);
                if (!hasSprinklers && window.AoTMapEditor.featureGroup) window.AoTMapEditor.featureGroup.eachLayer(checkSpr);

                // [Fix] Retrieve Config Robustly (Handle Stale Feature or String Data)
                let sprConfig = parentFeature.properties.gen_config_sprinkler;

                // Fallback: Look in Layer Storage if not found on passed feature
                if (!sprConfig && this.parent.layerStorage['zone']) {
                    this.parent.layerStorage['zone'].eachLayer(l => {
                        if (l.feature?.properties?.node_id === parentId && l.feature.properties.gen_config_sprinkler) {
                            sprConfig = l.feature.properties.gen_config_sprinkler;
                        }
                    });
                }

                // Parse if string (DB serialization quirk check)
                if (typeof sprConfig === 'string') {
                    try { sprConfig = JSON.parse(sprConfig); } catch (e) { /* console.warn("Failed to parse sprConfig", e); */ }
                }

                const shouldRegen = hasSprinklers && sprConfig;

                console.log(`[GeoModules] generated ${createdPipes.length} pipes. Auto-Sprinkler: ${shouldRegen}`, sprConfig);

                // [Fix] Clear existing pipes/sprinklers for this parent before adding new ones
                this.clearEquipments(parentFeature, 'all');

                // Add to Map
                createdPipes.forEach(f => {
                    // Convert to Layer
                    const l = L.geoJSON(f).getLayers()[0];
                    l.feature = f;

                    // [V13 Fix] Use centralized helper to ensure UUID and Dirty marking
                    // This guarantees that even if backend didn't provide a node_id, it is created and marked for save.
                    this._ensurePipeProperties(l, 'equipment');
                    l.feature.properties.sub_type = 'pipe_branch';
                    l.feature.properties.parent_node_id = parentFeature.properties.node_id;

                    // Add to Editor/Storage
                    window.AoTMapEditor.featureGroup.addLayer(l);
                    if (this.parent.layerStorage['equipment']) {
                        this.parent.layerStorage['equipment'].addLayer(l);
                    }

                    // Style
                    this.parent.ui._setLayerStyle(l, false);

                    // [Fix] Generate Length Label
                    if (this.parent.geometry) this.parent.geometry.updatePipeLabels(l);
                });


                // Process Trimming if main pipe exists?
                // The backend might not do trimming against MAIN pipe if it wasn't sent.
                // We can trigger trimming here if needed, but let's assume generated pipes are raw branch lines.

                // Post-Process: Trim generated branches against Main Pipe if it exists
                // Find main pipe connected to this zone? Or just all main pipes?
                // Checking local geometry...
                if (this.parent.geometry) {
                    // Find main pipes
                    const mains = [];
                    if (this.parent.layerStorage['equipment']) {
                        this.parent.layerStorage['equipment'].eachLayer(l => {
                            if (l.feature?.properties?.sub_type === 'pipe_main') mains.push(l);
                        });
                    }
                    mains.forEach(main => this.parent.geometry.processPipeTrimming(main));
                }

                // [New] Rebuild Connections for Auto-Generated Pipes (Tee/Elbow)
                if (this.parent.geometry) {
                    this.parent.geometry.rebuildConnections();
                }

                // [V14 Fix] Synchronous Sprinkler Generation
                if (shouldRegen && this.generateSprinklers) {
                    this.generateSprinklers(parentFeature, sprConfig, false);
                }

                // [V13/V14 Fix] Consolidate Property Updates and Save
                // Save Config to Parent Site/Zone
                const parentLayer = this.parent.geometry._findLayerByUuid(parentId);
                if (parentLayer) {
                    parentLayer.feature.properties.gen_config_pipe = config;
                    if (this.parent.dirtyNodeIds) this.parent.dirtyNodeIds.add(parentId);
                }

                // Trigger single robust save for all modified/new features
                this.parent.saveDesign(null, true);
                this.parent.updateDesignInfo();


            } else {
                alert('No pipes generated. Check configuration.');
            }

            return createdPipes;
 
        } catch (e) {
            // console.error("Pipe Gen Error:", e);
            if (this.parent && this.parent.ui) this.parent.ui.showToast("Error interfacing with server", 'error');
        }
    }

    generateSprinklers(targetFeature, config, doSave = true) {
        if (!window.turf) return;

        if (!targetFeature || !targetFeature.properties) {
            console.warn("[GeoGen] generateSprinklers called without targetFeature!");
            return;
        } 
        const targetId = targetFeature.properties.node_id;
        // console.log("[GeoGen] Generating Sprinklers for Target:", targetId, config);
 
        // 1. Find Targets (Active 'equipment' lines that are 'pipe_branch' AND belong to targetId)
        const pipes = [];
        const candidates = [];
        const seenCandidateIds = new Set();

        const addCandidate = (l) => {
            const nid = l.feature?.properties?.node_id;
            // [Fix] Deduplicate candidates (Same layer might be in Editor AND Storage)
            if (nid && !seenCandidateIds.has(nid)) {
                seenCandidateIds.add(nid);
                candidates.push(l);
            }
        };

        window.AoTMapEditor.featureGroup.eachLayer(addCandidate);
        if (this.parent.layerStorage['equipment']) this.parent.layerStorage['equipment'].eachLayer(addCandidate);

        candidates.forEach(l => {
            const props = l.feature?.properties;
            if (props && props.aot_type === 'equipment' && props.sub_type === 'pipe_branch') {
                // Strict Parent Check
                if (props.parent_node_id === targetId) {
                    if (l.toGeoJSON) pipes.push(l.toGeoJSON());
                }
                // Fallback: Geometric Check
                else if (!props.parent_node_id && targetFeature.geometry) {
                    try {
                        const pipeGeo = l.toGeoJSON();
                        // If pipe intersects target (zone)
                        if (window.turf.booleanIntersects(pipeGeo, targetFeature) ||
                            window.turf.booleanContains(targetFeature, pipeGeo)) {

                            // Auto-link found pipe!
                            console.log(`[GeoGen] Auto-linking orphan pipe ${props.node_id} to zone ${targetId}`);
                            l.feature.properties.parent_node_id = targetId;
                            pipes.push(pipeGeo);
                        }
                    } catch (e) {
                        console.warn("[GeoGen] Pipe geometry check failed:", e);
                    }
                }
            }
        });

        if (pipes.length === 0) {
            if (this.parent && this.parent.ui) this.parent.ui.showToast("No branch pipes found. Generate pipes first.", 'warning');
            return;
        }

        // 2. Auto-Clear Existing Sprinklers for this Zone
        const zoneId = pipes[0].properties.parent_node_id;
        const pipeIds = new Set(pipes.map(p => p.properties.node_id)); // Collect all pipe IDs

        if (zoneId || pipeIds.size > 0) {
            this.clearEquipments(targetFeature, 'sprinkler', doSave);
        }

        let count = 0;
        const interval = config.interval; // meters

        pipes.forEach(pipe => {
            // pipe is GeoJSON LineString
            let len = window.turf.length(pipe, { units: 'meters' });

            // [Fix] Align Start to Tee/Connection if exists
            // Find if Start or End is connected to a Main Pipe or has a Connection Dot
            if (window.turf) {
                const getDistToMain = (pt) => {
                    let minDist = Infinity;
                    let bestType = null;
                    // Check Main Pipes & Connections (Dots)
                    const targetGroups = ['equipment', 'connection'];
                    targetGroups.forEach(groupName => {
                        const group = this.parent.layerStorage[groupName];
                        if (group) {
                            group.eachLayer(l => {
                                const p = l.feature?.properties;
                                if (!p) return;

                                // mbT / mT: Point, pipe_main: LineString
                                const isTarget = (p.sub_type === 'pipe_main' ||
                                    ['mbT', 'mT', 'mbE', 'mE', 'connection'].includes(p.sub_type) ||
                                    p.aot_type === 'connection');

                                if (isTarget && l.feature.geometry) {
                                    try {
                                        let d;
                                        if (l.feature.geometry.type === 'Point') {
                                            d = window.turf.distance(pt, l.feature, { units: 'meters' });
                                        } else {
                                            d = window.turf.pointToLineDistance(pt, l.feature, { units: 'meters' });
                                        }

                                        if (d < minDist) {
                                            minDist = d;
                                            bestType = p.sub_type;
                                        }
                                    } catch (err) { /* Silent fail for geometry mismatch */ }
                                }
                            });
                        }
                    });
                    return { dist: minDist, type: bestType };
                };

                const startPt = window.turf.point(pipe.geometry.coordinates[0]);
                const endPt = window.turf.point(pipe.geometry.coordinates[pipe.geometry.coordinates.length - 1]);

                const startInfo = getDistToMain(startPt);
                const endInfo = getDistToMain(endPt);

                // console.log(`[GeoGen] Pipe Alignment Check: Start(${startInfo.type}, ${startInfo.dist.toFixed(2)}m), End(${endInfo.type}, ${endInfo.dist.toFixed(2)}m)`);

                // Priority Logic:
                // 1. If End is mbT and Start is not, reverse.
                // 2. If both or neither are mbT, use distance.
                let shouldReverse = false;
                if (endInfo.type === 'mbT' && startInfo.type !== 'mbT') {
                    shouldReverse = true;
                    // console.log("[GeoGen] Reversing pipe: End is mbT, Start is not.");
                } else if (endInfo.dist < 0.1 && (startInfo.dist > endInfo.dist || startInfo.dist > 0.1)) {
                    shouldReverse = true;
                    // console.log("[GeoGen] Reversing pipe: End is closer to connection.");
                }

                if (shouldReverse) {
                    const newCoords = [...pipe.geometry.coordinates].reverse();
                    pipe = window.turf.lineString(newCoords, pipe.properties);
                }
            }

            // Step along line
            for (let d = interval / 2; d < len; d += interval) {
                // Determine Distance based on Reverse Flag
                let dist = d;
                if (config.isReverse) {
                    dist = len - d;
                }

                const pos = window.turf.along(pipe, dist, { units: 'meters' });
                const coords = pos.geometry.coordinates; // [lng, lat]

                // 1. Position Dot (L.circleMarker - Pixels)
                const marker = L.circleMarker([coords[1], coords[0]], {
                    radius: 3,
                    aotType: 'site',
                    color: 'var(--theme-site, #DF5353)', // Use Theme Variable or Default
                    fillColor: 'var(--theme-site, #DF5353)',
                    fillOpacity: 0.21,
                    interactive: false // Disable Selection for Sprinklers
                });

                marker.feature = {
                    type: 'Feature',
                    geometry: { type: 'Point', coordinates: coords },
                    properties: {
                        node_id: window.uuidv4 ? window.uuidv4() :
                            'mmmm-mmmm-mmmm-mmmm'.replace(/[m]/g, () => (Math.random() * 16 | 0).toString(16)),
                        aot_type: 'equipment',
                        sub_type: 'sprinkler',
                        radius: config.radius,
                        flow: config.flow,
                        parent_node_id: pipe.properties.node_id,
                        zone_id: pipe.properties.parent_node_id
                    }
                };

                // 2. Coverage Circle (L.circle - Meters)
                const coverage = L.circle([coords[1], coords[0]], {
                    radius: config.radius, // Meters
                    color: '#007bff',
                    weight: 1,
                    opacity: 0.2,     // Stroke Opacity
                    fillOpacity: 0.2, // Fill Opacity
                    dashArray: '5, 5', // Standard Dash
                    interactive: false // Disable Selection for Coverage
                });

                coverage.feature = {
                    type: 'Feature',
                    geometry: { type: 'Point', coordinates: coords },
                    properties: {
                        node_id: window.uuidv4 ? window.uuidv4() :
                            'mmmm-mmmm-mmmm-mmmm'.replace(/[m]/g, () => (Math.random() * 16 | 0).toString(16)),
                        aot_type: 'equipment',
                        sub_type: 'sprinkler_coverage', // Differentiate
                        radius: config.radius,
                        parent_node_id: pipe.properties.node_id,
                        zone_id: pipe.properties.parent_node_id
                    }
                };

                // Add Both to Editor & Storage
                window.AoTMapEditor.featureGroup.addLayer(coverage); // Add coverage first (behind dot)
                window.AoTMapEditor.featureGroup.addLayer(marker);

                if (this.parent.layerStorage['equipment']) {
                    this.parent.layerStorage['equipment'].addLayer(coverage);
                    this.parent.layerStorage['equipment'].addLayer(marker);
                }

                // [V14 Fix] Mark for Save
                if (this.parent.dirtyNodeIds) {
                    if (marker.feature.properties.node_id) this.parent.dirtyNodeIds.add(marker.feature.properties.node_id);
                    if (coverage.feature.properties.node_id) this.parent.dirtyNodeIds.add(coverage.feature.properties.node_id);
                }


                count++;
             }
        });
 
        // console.log(`[GeoGen] Created ${count} sprinklers.`);
 
        // Save Config to Target Zone (Directly)
         if (targetFeature && targetFeature.properties) {
            // console.log("[GeoGen] Saving sprinkler config to target:", targetFeature.properties.node_id);
            targetFeature.properties.gen_config_sprinkler = JSON.parse(JSON.stringify(config));
        }

        if (doSave) {
            this.parent.saveDesign(['equipment', 'site', 'zone'], true);
            this.parent.updateDesignInfo();
        }
    }

    // [New] Generate Drip Irrigation Logic
    generateDrip(targetFeature, config) {
        if (!targetFeature || !targetFeature.properties) {
            if (this.parent.ui) this.parent.ui.showToast('Select a Zone or Site first.', 'warning');
            return;
        }

        const targetId = targetFeature.properties.node_id;
        console.log(`[GeoGen] Generating Drip for Target: ${targetId}`, config);

        // 1. Identify Target Pipes (Branch Pipes belonging to this Zone/Site)
        const targetPipes = [];
        const processLayer = (l) => {
            const props = l.feature?.properties;
            if (props && props.aot_type === 'equipment' && props.sub_type === 'pipe_branch') {
                // Check Extent/Ownership
                let isTarget = (props.parent_node_id === targetId || props.zone_id === targetId);
                
                // Spatial Fallback if no ID link
                if (!isTarget && !props.parent_node_id && window.turf && l.feature.geometry) {
                     try {
                         const center = window.turf.center(l.feature);
                         if (window.turf.booleanPointInPolygon(center, targetFeature)) {
                             isTarget = true;
                             l.feature.properties.parent_node_id = targetId; // Auto-link
                         }
                     } catch(e) {}
                }

                if (isTarget) {
                    targetPipes.push(l);
                }
            }
        };

        if (window.AoTMapEditor.featureGroup) window.AoTMapEditor.featureGroup.eachLayer(processLayer);
        if (this.parent.layerStorage['equipment']) this.parent.layerStorage['equipment'].eachLayer(processLayer);

        if (targetPipes.length === 0) {
            if (this.parent.ui) this.parent.ui.showToast('No branch pipes found in selected area.', 'warning');
            return;
        }

        // 2. Clear Existing Sprinklers (Drip replaces Sprinklers conceptually on these pipes)
        // We do separate clear call to ensure visual cleanup
        this.clearEquipments(targetFeature, 'sprinkler', false); // No auto-save yet

        // 3. Apply Drip Logic
        let count = 0;
        targetPipes.forEach(l => {
            const props = l.feature.properties;
            
            // Mark as Drip
            props.is_drip = true;
            props.drip_config = JSON.parse(JSON.stringify(config)); // Clone config
            
            // Force Style Update
            if (this.parent.ui && this.parent.ui._setLayerStyle) {
                this.parent.ui._setLayerStyle(l, false);
            }
            
            // Mark Dirty
            if (this.parent.dirtyNodeIds) this.parent.dirtyNodeIds.add(props.node_id);
            count++;
        });

        // 4. Save Config to Zone/Site
        targetFeature.properties.gen_config_drip = JSON.parse(JSON.stringify(config));
        if (this.parent.dirtyNodeIds) this.parent.dirtyNodeIds.add(targetId);

        console.log(`[GeoGen] Converted ${count} pipes to Drip System.`);

        // 5. Final Save & Update
        this.parent.saveDesign(['equipment', 'site', 'zone'], true);
        this.parent.updateDesignInfo();

        if (this.parent.ui) this.parent.ui.showToast(`점적 관수 적용 완료 (${count}개 배관)`, 'success');
    }

    clearEquipments(parentFeature, clearMode = 'all', doSave = true) {
        if (!parentFeature) {
            // console.warn("[GeoDesign] clearEquipments called without parentFeature");
            return;
        } 
        const parentId = parentFeature.properties.node_id;
        // console.log(`[GeoDesign] Clearing Equipment for Parent: ${parentId} (Mode: ${clearMode})`);

        const layersToRemove = [];
        // [New] List of pipes to revert from Drip -> Normal
        const pipesToRevert = [];

        // Define Check Logic
        // Match Target Types based on clearMode
        const checkLayer = (l) => {
            const props = l.feature?.properties || {};

            // 1. Determine allowed types for this mode
            let allowedTypes = ['pipe_branch', 'sprinkler', 'sprinkler_coverage', 'connection'];
            if (clearMode === 'sprinkler') {
                allowedTypes = ['sprinkler', 'sprinkler_coverage'];
            } else if (clearMode === 'drip') { // New mode for drip-specific clearing
                allowedTypes = []; // Only target drip pipes for reversion, not deletion
            }

            // 2. Filter by type (Protect critical infrastructure)
            if (props.sub_type === 'pipe_main' || props.sub_type === 'reference') return;

            // 3. Strict Type Check
            let itemType = props.sub_type || props.aot_type;
            if (props.aot_type === 'connection') itemType = 'connection';

            // [New] Special Case: Drip Pipes (pipe_branch with is_drip=true)
            // If they are Drip Pipes, we never 'remove' them in clearMode='all' or 'drip' (?)
            // We REVERT them.
            // But if clearMode='pipe', we might delete them? (Wait, user usually just clears equipment)
            // Assuming clearMode='all' (Initialize) means: Delete Sprinklers, Revert Drip Pipes.
            const isDripPipe = (props.sub_type === 'pipe_branch' && props.is_drip);

            const isAllowed = allowedTypes.includes(itemType) || isDripPipe;
            if (!isAllowed) return;

            // 4. Match Parent Link (Robust)
            const isLinked = (props.parent_node_id === parentId) || (props.zone_id === parentId);
            let shouldRemove = isLinked;

            // [Fix] Defensive Check: Ensure geometry exists for spatial check
            if (!shouldRemove && window.turf && l.feature && l.feature.geometry && parentFeature.geometry) {
                // Spatially check items if link is missing
                try {
                    let center;
                    if (l.feature.geometry.type === 'Point') {
                        center = l.feature;
                    } else {
                        center = window.turf.center(l.feature);
                    }
                    if (window.turf.booleanPointInPolygon(center, parentFeature)) {
                        shouldRemove = true;
                    }
                } catch (e) { }
            }

            if (shouldRemove) {
                if (isDripPipe && (clearMode === 'all' || clearMode === 'drip')) {
                    // Do NOT remove, but Revert
                    pipesToRevert.push(l);
                } else {
                    // Standard Removal (Sprinklers, Connections, or Pipes if explicit)
                    // Note: If clearMode='all', 'pipe_branch' is in allowedTypes.
                    // If it is NOT a drip pipe, it is removed?
                    // user says: "Corresponding pipes treated as drip revert to branch pipes".
                    // Does 'Initialize' usually Delete Branch Pipes too?
                    // Let's check original allowedTypes: ['pipe_branch', 'sprinkler', 'sprinkler_coverage', 'connection']
                    // Yes, standard "Initialize" (Clear Equipment) deletes Branch Pipes too!
                    // Wait. If the user spent time drawing/generating pipes, does 'Reset' mean *Delete Everything* or just *Reset Irrigation*?
                    // The prompt says: "When initialization button is clicked... drip pipes revert to branch pipes".
                    // This IMPLIES that the "branch pipes" themselves should SURVIVE the reset, just losing the drip status.
                    // BUT currently 'pipe_branch' IS in `allowedTypes` for deletion.
                    // THIS IS A CONFLICT with existing logic if `clearMode='all'` usually deletes pipes.
                    
                    // RE-READ CAREFULLY: "점적 생성 후 초기화 버튼을 누르면 해당 도형에서 점적으로 처리된 배관은 다시 가지관으로 복귀하고"
                    // Translation: "When the initialize button is pressed after creating drip, pipes treated as drip in that shape should return to branch pipes."
                    // This strongly suggests that for Drip scenarios, the pipes should NOT be deleted.
                    
                    // However, if I have plain branch pipes (no irrigation), does 'Initialize' delete them?
                    // Existing logic `allowedTypes = ['pipe_branch'...]` suggests YES, it deletes them.
                    // If so, "Reverting to branch pipe" then immediately deleting it is pointless.
                    // UNLESS the user means "Clear Irrigation" button, not "Clear All Equipment" button?
                    // Let's look at `aot-geo-panel.js`: `btn.dataset.clearMode || 'all'`.
                    // The button usually clears *everything* generated inside the zone.
                    
                    // HYPOTHESIS: The user wants a "Reset Irrigation" capability, OR they interpret "Initialize" as "Reset to just Pipes".
                    // OR, they assume "Drip" is a layer on top, so "Reset" should remove Drip but keep Pipe.
                    // BUT since Drip *IS* the Pipe, "Resetting" means Keeping the Pipe.
                    // So, for Drip Pipes, we MUST exempt them from deletion and instead Revert them.
                    // What about non-drip pipes? If I have a zone with just pipes, and I click Clear... they get deleted.
                    // If I have Drip Pipes, and I click Clear... they revert to pipes... and stay?
                    // That seems inconsistent if normal pipes get deleted.
                    
                    // ALTERNATIVE INTERPRETATION:
                    // Maybe the user is talking about a SPECIFIC "Clear Sprinkler/Drip" button?
                    // `btn-clear-equip` can have modes? 
                    // `aot-geo-panel.js` line 591: `mode = btn.dataset.clearMode || 'all'`.
                    // Is there a button that sends `clearMode='sprinkler'`? Yes, maybe?
                    // Let's assume the user presses the main trash can.
                    
                    // DECISION:
                    // I will prioritize the User's explicitly stated behavior: "Revert to Branch Pipe".
                    // This implies the pipe remains.
                    // So, checks:
                    // If `isDripPipe`: Add to `pipesToRevert`. Do NOT add to `layersToRemove`.
                    // If `pipe_branch` (normal): Standard logic (likely delete).
                    // This effectively means "Clear" on a Drip System acts as "Downgrade to Standard System" (and potentially deletes if I hit Clear AGAIN? No, if I hit Clear again, `isDripPipe` is false, so it falls to standard `pipe_branch` handling -> Deletion).
                    // This feels like a robust 2-stage clear.
                    // 1st Click (Drip): Revert to Pipes.
                    // 2nd Click (Normal): Delete Pipes.
                    
                    if (isDripPipe && (clearMode === 'all' || clearMode === 'drip')) {
                         pipesToRevert.push(l);
                    } else {
                         layersToRemove.push(l);
                    }
                }
            }
        };

        // 1. Scan All Storage Groups (Equipment, Connection, etc.)
        Object.keys(this.parent.layerStorage).forEach(type => {
            if (['equipment', 'connection', 'aot_device'].includes(type)) {
                this.parent.layerStorage[type].eachLayer(checkLayer);
            }
        });

        // 2. Scan Editor
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            window.AoTMapEditor.featureGroup.eachLayer(checkLayer);
        }

        // 3. Force Scan Map for Ghost Layers
        if (this.parent.map) {
            this.parent.map.eachLayer(l => {
                if (l._url || l._tiles || (l.options && l.options.attribution)) return;
                if (l.feature && l.feature.properties) {
                    // Check if already marked
                    const id = l.feature.properties.node_id;
                    const alreadyMarked = layersToRemove.some(r => r.feature.properties.node_id === id) ||
                                          pipesToRevert.some(r => r.feature.properties.node_id === id);
                    if (!alreadyMarked) checkLayer(l);
                }
            });
        }

    if (layersToRemove.length === 0 && pipesToRevert.length === 0 && clearMode !== 'sprinkler') return;

    // [V15 Fix] Clear Sprinkler Config from Zone if clearing sprinklers
    if (clearMode === 'sprinkler' || clearMode === 'all') {
        if (parentFeature.properties) {
            // console.log(`[GeoGen] Clearing config for zone ${parentId}`);
            delete parentFeature.properties.gen_config_sprinkler;
            if (this.parent.dirtyNodeIds) this.parent.dirtyNodeIds.add(parentId);
        }
    }

    // [New] Execute Drip Revert
    let revertCount = 0;
    pipesToRevert.forEach(l => {
         const props = l.feature.properties;
         delete props.is_drip;
         delete props.drip_config;
         
         // Style Update
         if (this.parent.ui && this.parent.ui._setLayerStyle) {
             this.parent.ui._setLayerStyle(l, false);
         }
         
         // Mark Dirty
         if (this.parent.dirtyNodeIds) this.parent.dirtyNodeIds.add(props.node_id);
         revertCount++;
    });

    // 3. Delete & Mark for Persistence (Remaining Deletions)
    layersToRemove.forEach(l => {
        const id = l.feature?.properties?.node_id;
        
        // [V14/V15 Fix] Push to Deletion Set for Delta Save
        if (id && this.parent.deletedNodeIds) {
            this.parent.deletedNodeIds.add(id);
            // Also remove from dirty to avoid resurrecting
            if (this.parent.dirtyNodeIds) this.parent.dirtyNodeIds.delete(id);
        }

        // Remove from editor
        if (window.AoTMapEditor.featureGroup.hasLayer(l)) window.AoTMapEditor.featureGroup.removeLayer(l);

        // Remove from ALL storage groups (to handle connection/device dots correctly)
        Object.values(this.parent.layerStorage).forEach(group => {
            if (group.hasLayer(l)) group.removeLayer(l);
        });

        // Remove from map explicitly
        if (this.parent.map.hasLayer(l)) this.parent.map.removeLayer(l);
    });
 
    // console.log(`[GeoDesign] Deleted ${layersToRemove.length} equipment items.`);
 
    // Clear Config from Parent
    if (parentFeature && parentFeature.properties) {
         delete parentFeature.properties.gen_config_sprinkler;
         // [New] Reset Drip Config
         delete parentFeature.properties.gen_config_drip;
    }

    // 5. Save Changes (Must be robust to capture deletions)
    if (doSave) {
        this.parent.saveDesign(null, true);
    }
}

    /**
     * Helper: Centralized Property and UUID Assignment
     */
    _ensurePipeProperties(layer, type) {
        layer.feature = layer.feature || { type: 'Feature', properties: {} };
        layer.feature.properties = layer.feature.properties || {};

        if (!layer.feature.properties.node_id) {
            layer.feature.properties.node_id = window.uuidv4 ? window.uuidv4() :
                'mmmm-mmmm-mmmm-mmmm'.replace(/[m]/g, () => (Math.random() * 16 | 0).toString(16));
            // console.log(`[Shape] Assigned New UUID: ${layer.feature.properties.node_id}`);
        }

        // [V7 Critical] Force add to dirty set IMMEDIATELY
        if (this.parent.dirtyNodeIds) {
            this.parent.dirtyNodeIds.add(layer.feature.properties.node_id);
        }

        // [Fix] Protect Reference Type
        if (layer.feature.properties.aot_type === 'reference') {
             // Keep existing type
        } else if (!layer.feature.properties.aot_type && type) {
            layer.feature.properties.aot_type = type;
        }

        // Auto-Link Parent
        if (['reference', 'equipment'].includes(layer.feature.properties.aot_type) && this.parent.activeLayer) {
            const activeProps = this.parent.activeLayer.feature?.properties;
            if (activeProps && (activeProps.aot_type === 'zone' || activeProps.aot_type === 'site')) {
                layer.feature.properties.parent_node_id = activeProps.node_id;
            }
        }
    }
}

window.AoTGeoModules = AoTGeoModules;
