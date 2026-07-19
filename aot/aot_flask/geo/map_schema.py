# coding=utf-8
"""
map_schema.py
Server-side map schema migration transformer.
Mirrors the logic in aot-geo-migration.js for use in Flask CLI and import endpoints.

Usage:
    from aot.aot_flask.geo.map_schema import MapSchemaMigration

    result = MapSchemaMigration.migrate(feature_collection_dict)
    # result: MigrationResult(data=..., migrated=True, from_version=1, to_version=2, report=[...])
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


CURRENT_VERSION = 2


@dataclass
class MigrationResult:
    data: Dict[str, Any]
    migrated: bool
    from_version: int
    to_version: int
    report: List[str] = field(default_factory=list)


class MapSchemaMigration:

    @staticmethod
    def detect_version(json_data: Dict[str, Any]) -> int:
        if not json_data or not isinstance(json_data, dict):
            return 0
        v = json_data.get('schema_version')
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                pass
        # No schema_version → legacy Leaflet export (v1)
        return 1

    @staticmethod
    def needs_migration(json_data: Dict[str, Any]) -> bool:
        return MapSchemaMigration.detect_version(json_data) < CURRENT_VERSION

    @staticmethod
    def _migrate_v1_to_v2(json_data: Dict[str, Any]) -> MigrationResult:
        features = json_data.get('features') or []
        report: List[str] = []

        # Collect all node_ids for orphan detection
        node_ids = {
            f['properties']['node_id']
            for f in features
            if f.get('properties', {}).get('node_id')
        }

        result = []
        removed_no_save = 0
        removed_connection = 0
        removed_orphan = 0
        renamed_device = 0
        label_normalized = 0
        parent_id_removed = 0

        for feature in features:
            props = dict(feature.get('properties') or {})
            aot_type = props.get('aot_type')

            # Rule 1: Remove no_save features (label_dynamic, dynamic connections)
            if props.get('no_save'):
                removed_no_save += 1
                continue

            # Rule 2: Remove connection-type features (regenerated dynamically)
            if aot_type == 'connection':
                removed_connection += 1
                continue

            # Rule 3: Normalize 'device' → 'aot_device'
            if aot_type == 'device':
                props['aot_type'] = 'aot_device'
                if props.get('device_id') and not props.get('unique_id'):
                    props['unique_id'] = props['device_id']
                renamed_device += 1

            # Rule 4: Remove legacy integer parent_id
            if 'parent_id' in props and not isinstance(props['parent_id'], str):
                del props['parent_id']
                parent_id_removed += 1

            # Rule 5: Normalize label fields
            current_type = props.get('aot_type', aot_type)
            if current_type in ('site', 'zone', 'facility'):
                if not props.get('label_name'):
                    fallback = props.get('label') or props.get('name')
                    if fallback:
                        props['label_name'] = fallback
                        label_normalized += 1

            # Rule 6: Orphan label_aux removal
            if aot_type == 'label_aux' and props.get('parent_node_id'):
                if props['parent_node_id'] not in node_ids:
                    removed_orphan += 1
                    continue

            new_feature = dict(feature)
            new_feature['properties'] = props
            result.append(new_feature)

        if removed_no_save:
            report.append(f"Removed {removed_no_save} no_save features (label_dynamic etc.)")
        if removed_connection:
            report.append(f"Removed {removed_connection} connection features (regenerated dynamically)")
        if renamed_device:
            report.append(f"Renamed {renamed_device} 'device' → 'aot_device'")
        if parent_id_removed:
            report.append(f"Removed {parent_id_removed} legacy integer parent_id fields")
        if label_normalized:
            report.append(f"Normalized {label_normalized} label→label_name fields")
        if removed_orphan:
            report.append(f"Removed {removed_orphan} orphan label_aux (no matching parent)")

        metadata = dict(json_data.get('metadata') or {})
        metadata['migrated_from_version'] = 1
        metadata['migrated_at'] = datetime.now(timezone.utc).isoformat()

        converted = dict(json_data)
        converted['features'] = result
        converted['schema_version'] = CURRENT_VERSION
        converted['metadata'] = metadata

        return MigrationResult(
            data=converted,
            migrated=True,
            from_version=1,
            to_version=CURRENT_VERSION,
            report=report
        )

    @classmethod
    def migrate(cls, json_data: Dict[str, Any]) -> MigrationResult:
        from_version = cls.detect_version(json_data)

        if from_version >= CURRENT_VERSION:
            return MigrationResult(
                data=json_data,
                migrated=False,
                from_version=from_version,
                to_version=from_version,
                report=[]
            )

        current = json_data
        all_reports: List[str] = []

        if from_version <= 1:
            result = cls._migrate_v1_to_v2(current)
            current = result.data
            all_reports.extend(result.report)

        # Future: if from_version <= 2: result = cls._migrate_v2_to_v3(current) ...

        return MigrationResult(
            data=current,
            migrated=True,
            from_version=from_version,
            to_version=CURRENT_VERSION,
            report=all_reports
        )
