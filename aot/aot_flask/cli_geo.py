# coding=utf-8
"""
cli_geo.py
Flask CLI commands for geo map management.

Usage:
    flask migrate-maps              — migrate all v1 overlays in DB to v2
    flask migrate-maps --dry-run    — report what would change without writing
    flask migrate-maps --map <uuid> — limit to a specific map UUID
"""

import json
import click
from datetime import datetime, timezone
from flask.cli import with_appcontext


def _has_migration_columns(db):
    """Check whether the migration tracking columns exist in geo_shape."""
    try:
        result = db.session.execute(
            db.text("SELECT schema_version FROM geo_shape LIMIT 1")
        )
        return True
    except Exception:
        return False


@click.command('migrate-maps')
@click.option('--dry-run', is_flag=True, default=False,
              help='Report changes without writing to DB')
@click.option('--map', 'map_uuid', default=None,
              help='Limit migration to a specific map UUID')
@with_appcontext
def migrate_maps_command(dry_run, map_uuid):
    """Migrate all legacy (v1) geo overlay data in the database to the current schema (v2)."""
    from aot.aot_flask.extensions import db
    from aot.databases.models.geo import GeoShape
    from aot.aot_flask.geo.map_schema import MapSchemaMigration

    prefix = '[DRY-RUN] ' if dry_run else ''
    has_cols = _has_migration_columns(db)

    if not has_cols:
        click.echo(
            'WARNING: Migration tracking columns not yet in DB. '
            'Run `alembic upgrade head` first to add them. '
            'Proceeding without tracking (original_data backup disabled).'
        )

    query = GeoShape.query
    if map_uuid:
        query = query.filter_by(geo_id=map_uuid)

    shapes = query.all()
    click.echo(f'{prefix}Scanning {len(shapes)} overlay records...')

    migrated_count = 0
    skipped_count = 0
    error_count = 0

    for shape in shapes:
        if shape.type == 'equipment_collection':
            did = _migrate_equipment_bundle(shape, dry_run, prefix, has_cols, db)
            if did:
                migrated_count += 1
            continue

        feat_raw = shape.feature
        if not feat_raw:
            skipped_count += 1
            continue

        if isinstance(feat_raw, str):
            try:
                feat = json.loads(feat_raw)
            except Exception:
                skipped_count += 1
                continue
        else:
            feat = dict(feat_raw)

        if not isinstance(feat, dict) or 'properties' not in feat:
            skipped_count += 1
            continue

        fc = {'type': 'FeatureCollection', 'features': [feat]}
        result = MapSchemaMigration.migrate(fc)

        if not result.migrated:
            skipped_count += 1
            continue

        if not result.data['features']:
            click.echo(f'  {prefix}Remove orphan row id={shape.id} type={shape.type}')
            if not dry_run:
                db.session.delete(shape)
            migrated_count += 1
            continue

        new_feat = result.data['features'][0]
        click.echo(f'  {prefix}Migrate row id={shape.id} type={shape.type}: {", ".join(result.report)}')

        if not dry_run:
            if has_cols:
                # Use raw SQL to avoid ORM column mismatch if model doesn't define them
                db.session.execute(
                    db.text(
                        "UPDATE geo_shape SET feature=:feat, schema_version=2, "
                        "original_data=COALESCE(original_data, :orig), "
                        "migrated_at=:mig_at, migrated_from_version=:mig_from "
                        "WHERE id=:id"
                    ),
                    {
                        'feat': json.dumps(new_feat),
                        'orig': json.dumps(feat),
                        'mig_at': datetime.now(timezone.utc).isoformat(),
                        'mig_from': result.from_version,
                        'id': shape.id
                    }
                )
            else:
                shape.feature = new_feat

        migrated_count += 1

    if not dry_run and migrated_count > 0:
        try:
            db.session.commit()
            click.echo(f'Committed {migrated_count} migrations.')
        except Exception as e:
            db.session.rollback()
            click.echo(f'ERROR committing: {e}', err=True)
            return

    click.echo(
        f'\n{prefix}Done. '
        f'Migrated: {migrated_count}, '
        f'Already current: {skipped_count}, '
        f'Errors: {error_count}'
    )


def _migrate_equipment_bundle(shape, dry_run, prefix, has_cols, db):
    from aot.aot_flask.geo.map_schema import MapSchemaMigration

    bundle = shape.feature
    if isinstance(bundle, str):
        try:
            bundle = json.loads(bundle)
        except Exception:
            return False

    if not isinstance(bundle, dict) or 'features' not in bundle:
        return False

    result = MapSchemaMigration.migrate(bundle)
    if not result.migrated:
        return False

    removed = len(bundle['features']) - len(result.data['features'])
    click.echo(
        f'  {prefix}Migrate equipment_collection id={shape.id} '
        f'({len(bundle["features"])} → {len(result.data["features"])} features, '
        f'removed {removed})'
    )

    if not dry_run:
        if has_cols:
            db.session.execute(
                db.text(
                    "UPDATE geo_shape SET feature=:feat, schema_version=2, "
                    "original_data=COALESCE(original_data, :orig), "
                    "migrated_at=:mig_at, migrated_from_version=:mig_from "
                    "WHERE id=:id"
                ),
                {
                    'feat': json.dumps(result.data),
                    'orig': json.dumps(bundle),
                    'mig_at': datetime.now(timezone.utc).isoformat(),
                    'mig_from': result.from_version,
                    'id': shape.id
                }
            )
        else:
            shape.feature = result.data

    return True


def register_geo_cli(app):
    """Register geo CLI commands with the Flask app."""
    app.cli.add_command(migrate_maps_command)
