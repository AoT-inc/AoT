"""Site → zone (and deeper) GeoShape hierarchy resolution.

GeoShape.parent_id is the intended parent FK, but in production data it is
left NULL on every site/zone row (checked 2026-07-24) — the only real signal
that a zone belongs to a site is that the zone's polygon is drawn spatially
inside the site's polygon on the map. AIContextService.get_spatial_hierarchy
already has a spatial fallback, but it only tests Point-in-polygon (device
markers), never Polygon-in-polygon (a zone inside a site), so it silently
flattens site/zone into unrelated siblings. This module is the one place
that resolves that relationship properly, so every AI tool/service that
needs "which zones belong to this site" computes it the same way.
"""
import json as _json


def _parse_geometry(shape_row):
    try:
        from shapely.geometry import shape as _shapely_shape
    except Exception:
        return None
    try:
        feat = shape_row.feature if isinstance(shape_row.feature, dict) else _json.loads(shape_row.feature or '{}')
        geometry = feat.get('geometry')
        if not geometry:
            return None
        g = _shapely_shape(geometry)
        return g if g.is_valid else None
    except Exception:
        return None


def build_geo_parent_map(all_shapes):
    """Map every GeoShape.id -> its parent's id (or None), across the given
    shape rows. parent_id wins when set; otherwise the smallest site/zone
    polygon that spatially contains the shape (Point marker OR Polygon
    zone/site) is used.
    """
    geoms = {s.id: _parse_geometry(s) for s in all_shapes}
    containers = [(s.id, geoms[s.id]) for s in all_shapes
                  if s.type in ('site', 'zone') and geoms.get(s.id) is not None
                  and geoms[s.id].geom_type in ('Polygon', 'MultiPolygon')]

    def _find_parent(s):
        if s.parent_id:
            return s.parent_id
        g = geoms.get(s.id)
        if g is None or g.geom_type not in ('Point', 'Polygon', 'MultiPolygon'):
            return None
        matches = []
        for cid, cg in containers:
            if cid == s.id:
                continue
            try:
                if cg.contains(g):
                    matches.append((cid, cg.area))
            except Exception:
                continue
        if not matches:
            return None
        # Smallest containing polygon = most specific parent (a zone before
        # the site it sits in).
        matches.sort(key=lambda m: m[1])
        return matches[0][0]

    return {s.id: _find_parent(s) for s in all_shapes}


def geo_descendant_shapes(root_shape, all_shapes=None):
    """Every GeoShape nested under root_shape (e.g. a site's child zones),
    breadth-first, deepest levels included. Returns GeoShape rows.
    """
    if all_shapes is None:
        from aot.databases.models import GeoShape
        all_shapes = GeoShape.query.all()

    parent_map = build_geo_parent_map(all_shapes)
    children_map = {}
    for s in all_shapes:
        pid = parent_map.get(s.id)
        if pid is not None:
            children_map.setdefault(pid, []).append(s)

    out, seen, frontier = [], {root_shape.id}, [root_shape.id]
    while frontier:
        nxt = []
        for pid in frontier:
            for child in children_map.get(pid, []):
                if child.id in seen:
                    continue
                seen.add(child.id)
                nxt.append(child.id)
                out.append(child)
        frontier = nxt
    return out


def geo_descendant_unique_ids(root_shape, all_shapes=None):
    """Convenience wrapper: unique_ids of geo_descendant_shapes()."""
    return [s.unique_id for s in geo_descendant_shapes(root_shape, all_shapes=all_shapes) if s.unique_id]
