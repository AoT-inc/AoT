# coding=utf-8
"""
GeoModelAsset CRUD manager.

All create/update operations store dimension values in metres.
The caller is responsible for converting user-input units before passing data.

Deletion follows the 4-step confirmation protocol (Constitution Art.5).
A hard delete is refused if the asset is referenced by any GeoFacility row.

@phase active
"""
import logging
import os
import uuid as _uuid
from datetime import datetime

from flask import current_app

from aot.databases.models import GeoFacility, GeoModelAsset
from aot.aot_flask.extensions import db

logger = logging.getLogger(__name__)

UPLOAD_SUBDIR = os.path.join('uploads', 'model_assets')
PREVIEW_SUBDIR = os.path.join('uploads', 'model_assets', 'previews')
ALLOWED_EXTENSIONS = {'.glb', '.gltf'}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


class ModelAssetManager:

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _upload_dir():
        return os.path.join(current_app.static_folder, UPLOAD_SUBDIR)

    @staticmethod
    def _preview_dir():
        return os.path.join(current_app.static_folder, PREVIEW_SUBDIR)

    @staticmethod
    def _ensure_dirs():
        for d in (ModelAssetManager._upload_dir(), ModelAssetManager._preview_dir()):
            os.makedirs(d, exist_ok=True)

    @staticmethod
    def _safe_ext(filename):
        _, ext = os.path.splitext(filename.lower())
        return ext if ext in ALLOWED_EXTENSIONS else None

    @staticmethod
    def _to_dict(row):
        return {
            'unique_id':      row.unique_id,
            'owner_user_id':  row.owner_user_id,
            'name':           row.name,
            'kind':           row.kind,
            'spec_json':      row.spec_json or {},
            'authored_unit':  row.authored_unit,
            'tags':           row.tags or '',
            'preview_png':    row.preview_png,
            'preview_status': row.preview_status,
            'source_file':    row.source_file,
            'notes':          row.notes or '',
            'sort_order':     row.sort_order,
            'created_at':     row.created_at.isoformat() if row.created_at else None,
            'updated_at':     row.updated_at.isoformat() if row.updated_at else None,
        }

    # ── List ───────────────────────────────────────────────────────────────────

    @staticmethod
    def list_assets(owner_user_id=None, kind=None, tag=None):
        try:
            q = GeoModelAsset.query
            if owner_user_id is not None:
                q = q.filter_by(owner_user_id=owner_user_id)
            if kind:
                q = q.filter_by(kind=kind)
            rows = q.order_by(GeoModelAsset.sort_order, GeoModelAsset.name).all()
            if tag:
                rows = [r for r in rows if tag in (r.tags or '').split(',')]
            return [ModelAssetManager._to_dict(r) for r in rows], None
        except Exception as e:
            logger.error("ModelAssetManager.list error: %s", e)
            return None, str(e)

    # ── Get ────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_asset(asset_uuid):
        try:
            row = GeoModelAsset.query.filter_by(unique_id=asset_uuid).first()
            if not row:
                return None, 'Asset not found'
            return ModelAssetManager._to_dict(row), None
        except Exception as e:
            logger.error("ModelAssetManager.get error: %s", e)
            return None, str(e)

    # ── Create ─────────────────────────────────────────────────────────────────

    @staticmethod
    def create_asset(data, file_storage=None, owner_user_id=None):
        """Create a new GeoModelAsset.

        data keys: name, kind, spec_json, authored_unit, tags, notes
        file_storage: werkzeug FileStorage object (imported_gltf only)
        """
        try:
            ModelAssetManager._ensure_dirs()

            kind = data.get('kind', 'primitive')
            source_path = None

            if kind == 'imported_gltf':
                if not file_storage:
                    return None, 'imported_gltf requires a file upload'
                ext = ModelAssetManager._safe_ext(file_storage.filename)
                if not ext:
                    return None, f'Invalid file type. Allowed: {ALLOWED_EXTENSIONS}'

                # Read and size-check
                content = file_storage.read()
                if len(content) > MAX_UPLOAD_BYTES:
                    return None, f'File exceeds 25 MB limit ({len(content)} bytes)'

                # Validate GLB magic bytes (first 4 bytes = b'glTF')
                if ext == '.glb' and content[:4] != b'glTF':
                    return None, 'Invalid GLB file (missing glTF magic header)'

                asset_uuid_str = str(_uuid.uuid4())
                filename = asset_uuid_str + ext
                save_path = os.path.join(ModelAssetManager._upload_dir(), filename)
                with open(save_path, 'wb') as f:
                    f.write(content)
                source_path = os.path.join(UPLOAD_SUBDIR, filename).replace(os.sep, '/')

            row = GeoModelAsset(
                owner_user_id=owner_user_id,
                name=data.get('name', 'New Asset'),
                kind=kind,
                spec_json=data.get('spec_json') or {},
                authored_unit=data.get('authored_unit', 'm'),
                tags=data.get('tags', ''),
                notes=data.get('notes', ''),
                source_file=source_path,
                preview_status='pending',
            )
            db.session.add(row)
            db.session.commit()

            # Trigger thumbnail generation (best-effort, non-blocking)
            try:
                from aot.aot_flask.geo.preview_renderer import render_preview
                render_preview(row)
            except Exception as preview_err:
                logger.warning("Preview render skipped: %s", preview_err)

            return ModelAssetManager._to_dict(row), None
        except Exception as e:
            db.session.rollback()
            logger.error("ModelAssetManager.create error: %s", e)
            return None, str(e)

    # ── Update ─────────────────────────────────────────────────────────────────

    @staticmethod
    def update_asset(asset_uuid, data):
        try:
            row = GeoModelAsset.query.filter_by(unique_id=asset_uuid).first()
            if not row:
                return None, 'Asset not found'

            for field in ('name', 'spec_json', 'authored_unit', 'tags', 'notes', 'sort_order'):
                if field in data:
                    setattr(row, field, data[field])

            row.updated_at = datetime.utcnow()
            db.session.commit()

            try:
                from aot.aot_flask.geo.preview_renderer import render_preview
                render_preview(row)
            except Exception as preview_err:
                logger.warning("Preview render skipped: %s", preview_err)

            return ModelAssetManager._to_dict(row), None
        except Exception as e:
            db.session.rollback()
            logger.error("ModelAssetManager.update error: %s", e)
            return None, str(e)

    # ── Delete ─────────────────────────────────────────────────────────────────

    @staticmethod
    def delete_asset(asset_uuid):
        """Hard delete. Refuses if any GeoFacility references this asset.

        Returns (None, None) on success, (None, error_str) on failure.
        Also returns referencing_facilities list if blocked (409 scenario).
        """
        try:
            row = GeoModelAsset.query.filter_by(unique_id=asset_uuid).first()
            if not row:
                return None, 'Asset not found', []

            refs = GeoFacility.query.filter_by(model_asset_uuid=asset_uuid).all()
            if refs:
                ref_names = [r.name for r in refs]
                return None, f'Asset is referenced by {len(refs)} facility/facilities', ref_names

            # Remove uploaded file
            if row.source_file:
                abs_path = os.path.join(current_app.static_folder, row.source_file)
                if os.path.isfile(abs_path):
                    os.remove(abs_path)

            # Remove preview
            if row.preview_png:
                abs_prev = os.path.join(current_app.static_folder, row.preview_png)
                if os.path.isfile(abs_prev):
                    os.remove(abs_prev)

            db.session.delete(row)
            db.session.commit()
            return None, None, []
        except Exception as e:
            db.session.rollback()
            logger.error("ModelAssetManager.delete error: %s", e)
            return None, str(e), []

    # ── Facility attach / detach ───────────────────────────────────────────────

    @staticmethod
    def attach_to_facility(facility_uuid, asset_uuid, transform=None):
        """Link a GeoModelAsset to a GeoFacility and switch render_mode='asset'."""
        try:
            facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
            if not facility:
                return None, 'Facility not found'
            asset = GeoModelAsset.query.filter_by(unique_id=asset_uuid).first()
            if not asset:
                return None, 'Asset not found'

            facility.model_asset_uuid = asset_uuid
            facility.model_transform = transform or {'position': [0, 0, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1]}
            facility.render_mode = 'asset'
            facility.updated_at = datetime.utcnow()
            db.session.commit()
            return {'facility_uuid': facility_uuid, 'asset_uuid': asset_uuid, 'render_mode': 'asset'}, None
        except Exception as e:
            db.session.rollback()
            logger.error("ModelAssetManager.attach error: %s", e)
            return None, str(e)

    @staticmethod
    def detach_from_facility(facility_uuid):
        """Remove asset link and revert render_mode to 'parametric'."""
        try:
            facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
            if not facility:
                return None, 'Facility not found'

            facility.model_asset_uuid = None
            facility.model_transform = None
            facility.render_mode = 'parametric'
            facility.updated_at = datetime.utcnow()
            db.session.commit()
            return {'facility_uuid': facility_uuid, 'render_mode': 'parametric'}, None
        except Exception as e:
            db.session.rollback()
            logger.error("ModelAssetManager.detach error: %s", e)
            return None, str(e)
