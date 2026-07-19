
/**
 * aot-geo-export.js
 * Handles export functionality (CSV, Print/PDF) for Geo Design
 */

class AoTGeoExport {
    constructor(statsModule) {
        this.stats = statsModule; // Reference to AoTGeoStats to access Cached Data
    }

    printPage() {
        window.print();
    }

    bindActions() {
        // Bind to existing buttons in geo_design.html
        const btnCsv = document.getElementById('btn-download-csv');
        const btnPdf = document.getElementById('btn-download-pdf');
        
        // [New] JSON Actions
        const btnExp = document.getElementById('btn-export-json');
        const btnImp = document.getElementById('btn-import-json');
        const fileImp = document.getElementById('input-import-json');

        if (btnCsv) {
            btnCsv.onclick = (e) => {
                e.preventDefault();
                this.exportToCSV();
            };
        }

        if (btnPdf) {
            btnPdf.onclick = (e) => {
                e.preventDefault();
                this.printPage();
            };
        }

        if (btnExp) {
            btnExp.onclick = (e) => {
                e.preventDefault();
                this.exportMapJSON();
            };
        }

        if (btnImp && fileImp) {
            btnImp.onclick = (e) => {
                e.preventDefault();
                if (confirm(window._ ? window._('The file contents will be added to the current map.\n(Duplicate items may occur.)') : 'The file contents will be added to the current map.\n(Duplicate items may occur.)')) {
                    fileImp.click();
                }
            };

            fileImp.onchange = (e) => {
                const file = e.target.files[0];
                if (file) {
                    this.importMapJSON(file);
                    fileImp.value = ''; // Reset
                }
            };
        }
    }

    exportMapJSON() {
        const parent = this.stats.parent;
        if (!parent) return;

        const allFeatures = [];
        const savedIds = new Set();

        const collectLayer = (l) => {
            if (!l.feature) return;
            // Clean/Update Geometry similar to Save Logic
            if (l.toGeoJSON) {
                const geo = l.toGeoJSON();
                l.feature.geometry = geo.geometry;
            }
            // Circle Handling for Export - Pure MapLibre: Use _aotType check
            const geomType = l._aotType || (l.feature?.geometry?.type);
            if (geomType === 'Circle' || l.feature?.properties?.is_circle) {
                const center = l.getLatLng();
                l.feature.properties.is_circle = true;
                l.feature.properties.radius = l.getRadius();
                l.feature.properties.center_lat = center.lat;
                l.feature.properties.center_lng = center.lng;
            }

            // Dedupe
            const nid = l.feature.properties.node_id;
            if (nid) {
                if (savedIds.has(nid)) return;
                savedIds.add(nid);
            }
            allFeatures.push(l.feature);
        };

        // 1. From Storage
        Object.keys(parent.layerStorage).forEach(key => {
            parent.layerStorage[key].eachLayer(collectLayer);
        });

        // 2. From Editor
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            window.AoTMapEditor.featureGroup.eachLayer(collectLayer);
        }

        if (allFeatures.length === 0) {
            alert(window._ ? window._('There is no data to export.') : 'There is no data to export.');
            return;
        }

        const geoJSON = {
            type: "FeatureCollection",
            features: allFeatures,
            metadata: {
                exported_at: new Date().toISOString(),
                map_name: parent.currentMapName
            }
        };

        const str = JSON.stringify(geoJSON, null, 2);
        const blob = new Blob([str], { type: 'application/json' });
        const link = document.createElement("a");
        const url = URL.createObjectURL(blob);
        link.setAttribute("href", url);
        link.setAttribute("download", `map_export_${parent.currentMapUuid || 'data'}.json`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    importMapJSON(file) {
        const parent = this.stats.parent;
        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                let json = JSON.parse(e.target.result);
                if (!json || !json.features) throw new Error("Invalid GeoJSON Format");

                // Auto-migrate legacy Leaflet/v1 exports before importing
                if (window.AoTGeoMigration && AoTGeoMigration.needsMigration(json)) {
                    const migResult = AoTGeoMigration.migrate(json);
                    if (migResult.migrated) {
                        const summary = migResult.report.join('\n• ');
                        const proceed = confirm(
                            `${window._ ? window._('This file is in an older format (v') : 'This file is in an older format (v'}${migResult.from}).\n` +
                            `${window._ ? window._('It will be automatically converted to the current format (v') : 'It will be automatically converted to the current format (v'}${migResult.to}).\n\n` +
                            `${window._ ? window._('Conversion details:') : 'Conversion details:'}\n• ${summary}\n\n` +
                            `${window._ ? window._('Do you want to continue?') : 'Do you want to continue?'}`
                        );
                        if (!proceed) return;
                        json = migResult.data;
                    }
                }

                // Use AoTGeoLayer.fromGeoJSON to parse and distribute
                let count = 0;
                const layers = AoTGeoLayer.fromGeoJSON(json, {
                    onEachFeature: (f, l) => {
                        const type = f.properties.aot_type || 'feature';
                        // Use parent's processor to attach events and store validly
                        parent._processLoadedFeature(l, type);
                        count++;
                    }
                });

                // Refresh UI
                parent._switchLayerContext(null, parent.activeMode); // Ensure editor/storage sync
                parent._repairLoadedData(); // Fix connections
                parent.ui.showToast(`${count} ${window._ ? window._('elements imported.') : 'elements imported.'}`, 'success');

            } catch (err) {
                console.error(err);
                alert((window._ ? window._('Import failed: ') : 'Import failed: ') + err.message);
            }
        };
        reader.readAsText(file);
    }
}
