/**
 * aot-geo-migration.js
 * Client-side map schema migration transformer.
 * Converts legacy Leaflet/v1 GeoJSON exports to the current v2 format.
 *
 * Usage:
 *   const result = AoTGeoMigration.migrate(rawJson);
 *   // result: { data: <converted FeatureCollection>, migrated: true|false, from: 1, to: 2, report: [...] }
 */

const AoTGeoMigration = (() => {

    const CURRENT_VERSION = 2;

    // -----------------------------------------------------------------------
    // Version detection
    // -----------------------------------------------------------------------

    function detectVersion(json) {
        if (!json || typeof json !== 'object') return 0;
        const v = json.schema_version;
        if (typeof v === 'number') return v;
        if (typeof v === 'string' && !isNaN(parseInt(v, 10))) return parseInt(v, 10);
        // No schema_version → legacy Leaflet export (v1)
        return 1;
    }

    function needsMigration(json) {
        return detectVersion(json) < CURRENT_VERSION;
    }

    // -----------------------------------------------------------------------
    // v1 → v2 transformer
    // -----------------------------------------------------------------------

    function _migrateV1toV2(json) {
        const report = [];
        const features = (json.features || []);
        const nodeIds = new Set();
        const result = [];

        // First pass: collect all node_ids present (to detect orphan labels)
        features.forEach(f => {
            const nid = f.properties && f.properties.node_id;
            if (nid) nodeIds.add(nid);
        });

        let removedNoSave = 0;
        let removedConnection = 0;
        let removedOrphan = 0;
        let renamedDevice = 0;
        let labelNormalized = 0;
        let parentIdRemoved = 0;

        features.forEach(f => {
            const props = f.properties || {};
            const aotType = props.aot_type;

            // Rule 1: Remove features with no_save flag (label_dynamic, dynamic connections)
            if (props.no_save) {
                removedNoSave++;
                return;
            }

            // Rule 2: Remove connection-type features (regenerated dynamically)
            if (aotType === 'connection') {
                removedConnection++;
                return;
            }

            // Clone to avoid mutating original
            const newProps = Object.assign({}, props);
            const newFeature = Object.assign({}, f, { properties: newProps });

            // Rule 3: Normalize 'device' → 'aot_device'
            if (aotType === 'device') {
                newProps.aot_type = 'aot_device';
                // device_id → unique_id for aot_device consistency
                if (newProps.device_id && !newProps.unique_id) {
                    newProps.unique_id = newProps.device_id;
                }
                renamedDevice++;
            }

            // Rule 4: Remove legacy integer parent_id (DB row id) — keep parent_node_id
            if (newProps.parent_id !== undefined && typeof newProps.parent_id !== 'string') {
                delete newProps.parent_id;
                parentIdRemoved++;
            }

            // Rule 5: Normalize label fields — ensure label_name exists
            if (newProps.aot_type === 'site' || newProps.aot_type === 'zone' || newProps.aot_type === 'facility') {
                if (!newProps.label_name && newProps.label) {
                    newProps.label_name = newProps.label;
                    labelNormalized++;
                } else if (!newProps.label_name && newProps.name) {
                    newProps.label_name = newProps.name;
                    labelNormalized++;
                }
            }

            // Rule 6: label_aux orphan removal — parent_node_id must exist in this collection
            // [Safety] A DB row (has db_id) is user data, so preserve it even if matching fails.
            // Prevents accidental removal of valid labels in cases where legacy/parcel-import
            // sites do not have properties.node_id.
            if (aotType === 'label_aux' && newProps.parent_node_id && !newProps.db_id) {
                if (!nodeIds.has(newProps.parent_node_id)) {
                    removedOrphan++;
                    return;
                }
            }

            result.push(newFeature);
        });

        if (removedNoSave)    report.push(`Removed ${removedNoSave} no_save features (label_dynamic etc.)`);
        if (removedConnection) report.push(`Removed ${removedConnection} connection features (regenerated dynamically)`);
        if (renamedDevice)    report.push(`Renamed ${renamedDevice} 'device' → 'aot_device'`);
        if (parentIdRemoved)  report.push(`Removed ${parentIdRemoved} legacy integer parent_id fields`);
        if (labelNormalized)  report.push(`Normalized ${labelNormalized} label→label_name fields`);
        if (removedOrphan)    report.push(`Removed ${removedOrphan} orphan label_aux (no matching parent)`);

        const converted = Object.assign({}, json, {
            features: result,
            schema_version: CURRENT_VERSION,
            metadata: Object.assign({}, json.metadata || {}, {
                migrated_from_version: 1,
                migrated_at: new Date().toISOString()
            })
        });

        return { data: converted, report };
    }

    // -----------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------

    function migrate(json) {
        const from = detectVersion(json);

        if (from >= CURRENT_VERSION) {
            return { data: json, migrated: false, from, to: from, report: [] };
        }

        let current = json;
        const allReports = [];

        if (from <= 1) {
            const { data, report } = _migrateV1toV2(current);
            current = data;
            allReports.push(...report);
        }
        // Future: if (from <= 2) { ... }

        return {
            data: current,
            migrated: true,
            from,
            to: CURRENT_VERSION,
            report: allReports
        };
    }

    return { detectVersion, needsMigration, migrate, CURRENT_VERSION };

})();

// Allow CommonJS usage in test environments
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AoTGeoMigration;
}
