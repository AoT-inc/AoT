# coding=utf-8
"""Server-side thumbnail renderer for GeoModelAsset.

Tier 1: trimesh + pyrender (headless EGL/osmesa) → 256×256 PNG
Tier 2: trimesh Scene.save_image() (Pyglet headless)
Tier 3: grey placeholder PNG (always succeeds)

trimesh and pyrender are optional dependencies. If unavailable, the renderer
falls straight through to Tier 3 and marks preview_status='ok' with a
placeholder so the asset library can show something immediately.

@phase active
"""
import logging
import os
import struct
import zlib

from flask import current_app

logger = logging.getLogger(__name__)

PREVIEW_SUBDIR = os.path.join('uploads', 'model_assets', 'previews')
PREVIEW_SIZE = 256


def _preview_dir():
    return os.path.join(current_app.static_folder, PREVIEW_SUBDIR)


def _placeholder_png(size=PREVIEW_SIZE):
    """Generate a minimal grey PNG using only stdlib (no Pillow required)."""
    def _pack_chunk(chunk_type, data):
        crc = zlib.crc32(chunk_type + data) & 0xffffffff
        return struct.pack('>I', len(data)) + chunk_type + data + struct.pack('>I', crc)

    # Raw image: size×size grey pixels (RGB 8-bit)
    raw_rows = b''
    for _ in range(size):
        raw_rows += b'\x00' + bytes([0x88, 0x88, 0x88] * size)  # filter=None + grey

    compressed = zlib.compress(raw_rows)

    signature = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    ihdr = _pack_chunk(b'IHDR', ihdr_data)
    idat = _pack_chunk(b'IDAT', compressed)
    iend = _pack_chunk(b'IEND', b'')
    return signature + ihdr + idat + iend


def render_preview(asset_row):
    """Generate a thumbnail for *asset_row* and persist it.

    Updates asset_row.preview_png and asset_row.preview_status in-place,
    then commits to DB.  Must be called within a Flask application context.
    """
    from aot.aot_flask.extensions import db

    os.makedirs(_preview_dir(), exist_ok=True)
    out_filename = asset_row.unique_id + '.png'
    out_path = os.path.join(_preview_dir(), out_filename)
    rel_path = os.path.join(PREVIEW_SUBDIR, out_filename).replace(os.sep, '/')

    rendered = False

    # ── Tier 1: pyrender (EGL/osmesa headless) ────────────────────────────────
    if not rendered and asset_row.kind == 'imported_gltf' and asset_row.source_file:
        try:
            import trimesh
            import pyrender
            import numpy as np

            abs_source = os.path.join(current_app.static_folder, asset_row.source_file)
            scene = trimesh.load(abs_source)
            pyscene = pyrender.Scene.from_trimesh_scene(
                scene if isinstance(scene, trimesh.Scene) else trimesh.Scene([scene])
            )
            camera = pyrender.PerspectiveCamera(yfov=0.8)
            nc = pyscene.add(camera, pose=np.eye(4))
            light = pyrender.DirectionalLight(color=np.ones(3), intensity=3.0)
            pyscene.add(light, pose=np.eye(4))
            r = pyrender.OffscreenRenderer(PREVIEW_SIZE, PREVIEW_SIZE)
            color, _ = r.render(pyscene)
            r.delete()
            from PIL import Image
            Image.fromarray(color).save(out_path)
            rendered = True
        except Exception as e:
            logger.debug("Tier 1 render failed: %s", e)

    # ── Tier 2: trimesh headless ──────────────────────────────────────────────
    if not rendered and asset_row.kind == 'imported_gltf' and asset_row.source_file:
        try:
            import trimesh
            abs_source = os.path.join(current_app.static_folder, asset_row.source_file)
            scene = trimesh.load(abs_source)
            if isinstance(scene, trimesh.Trimesh):
                scene = trimesh.Scene([scene])
            png_bytes = scene.save_image(resolution=(PREVIEW_SIZE, PREVIEW_SIZE))
            with open(out_path, 'wb') as f:
                f.write(png_bytes)
            rendered = True
        except Exception as e:
            logger.debug("Tier 2 render failed: %s", e)

    # ── Tier 3: stdlib grey placeholder ──────────────────────────────────────
    if not rendered:
        with open(out_path, 'wb') as f:
            f.write(_placeholder_png(PREVIEW_SIZE))
        rendered = True

    asset_row.preview_png = rel_path
    asset_row.preview_status = 'ok' if rendered else 'failed'
    try:
        db.session.commit()
    except Exception as e:
        logger.warning("preview_renderer: DB commit failed: %s", e)
