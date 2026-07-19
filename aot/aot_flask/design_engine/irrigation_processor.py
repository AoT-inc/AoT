# coding=utf-8
import math
import json
from shapely.geometry import shape, LineString, MultiLineString, mapping
from shapely.affinity import rotate, translate
from shapely.ops import unary_union

class IrrigationProcessor:
    """
    Engine for generating irrigation rows within a field boundary.
    """

    @staticmethod
    def generate_rows(boundary_geojson, spacing_meters=1.2, angle_degrees=0.0, offset_meters=0.0, baseline_geojson=None):
        """
        Generate rows based on boundary and settings.
        If baseline_geojson is provided, generates rows parallel to it.
        Otherwise, generates rows based on angle.
        
        Args:
           boundary_geojson: Polygon
           spacing_meters: float
           angle_degrees: float
           offset_meters: float
           baseline_geojson: LineString (Optional)
        """
        try:
             # If baseline provided, use parallel offset logic
            if baseline_geojson:
                return IrrigationProcessor._generate_from_line(boundary_geojson, baseline_geojson, spacing_meters, offset_meters, angle_degrees)
            
            # Default Angle Logic
            poly = shape(boundary_geojson)
            if not poly.is_valid:
                poly = poly.buffer(0)
                
            # Geographic (Lat/Lon) to Meter conversion approximation
            center = poly.centroid
            lat_scale = 111000.0
            lon_scale = 111000.0 * math.cos(math.radians(center.y))
            
            # 1. Project Polygon to Local Meter Grid
            scaled_coords = []
            if poly.geom_type == 'Polygon':
                for x, y in poly.exterior.coords:
                    scaled_coords.append(((x - center.x) * lon_scale, (y - center.y) * lat_scale))
                meter_poly = type(poly)(scaled_coords)
            else:
                 return {"type": "FeatureCollection", "features": []}

            # 2. Rotate Polygon
            rotated_poly = rotate(meter_poly, -angle_degrees, origin=(0, 0))
            
            minx, miny, maxx, maxy = rotated_poly.bounds
            
            # 3. Generate Horizontal Lines
            lines = []
            # Apply offset to phase
            current_y = miny + (spacing_meters / 2.0) + offset_meters
            
            while current_y < maxy:
                line = LineString([(minx - 100, current_y), (maxx + 100, current_y)])
                
                # Clip
                clipped = line.intersection(rotated_poly)
                
                if not clipped.is_empty:
                    if clipped.geom_type == 'MultiLineString':
                        lines.extend(clipped.geoms)
                    elif clipped.geom_type == 'LineString':
                        lines.append(clipped)
                
                current_y += spacing_meters
                
            # 4. Restore
            result_features = []
            for line in lines:
                restored_line = rotate(line, angle_degrees, origin=(0, 0))
                final_coords = []
                for x, y in restored_line.coords:
                    lon = (x / lon_scale) + center.x
                    lat = (y / lat_scale) + center.y
                    final_coords.append((lon, lat))
                    
                if line.length < 1.0:
                    continue

                result_features.append({
                    "type": "Feature",
                    "geometry": mapping(LineString(final_coords)),
                    "properties": {
                        "type": "row",
                        "length_m": line.length
                    }
                })
                
            return {
                "type": "FeatureCollection",
                "features": result_features
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    @staticmethod
    def _generate_from_line(boundary_geojson, baseline_geojson, spacing_meters, offset_meters, angle_degrees=0.0):
        """
        Generate rows parallel to a baseline.
        """
        try:
            poly = shape(boundary_geojson)
            baseline = shape(baseline_geojson)
            
            if not poly.is_valid: poly = poly.buffer(0)
            
            center = poly.centroid
            lat_scale = 111000.0
            lon_scale = 111000.0 * math.cos(math.radians(center.y))
            
            # Project Polygon
            scaled_coords = []
            if poly.geom_type == 'Polygon':
                for x, y in poly.exterior.coords:
                    scaled_coords.append(((x - center.x) * lon_scale, (y - center.y) * lat_scale))
                meter_poly = type(poly)(scaled_coords)
            else:
                return {"type": "FeatureCollection", "features": []}
                
            # Project Baseline
            # Baseline might be outside or inside.
            # Just project coords.
            base_coords = []
            if baseline.geom_type == 'LineString':
                for x, y in baseline.coords:
                    base_coords.append(((x - center.x) * lon_scale, (y - center.y) * lat_scale))
                meter_line = LineString(base_coords)
                
                # ROTATION LOGIC: Rotate baseline around its own centroid
                if abs(angle_degrees) > 1e-5:
                     meter_line = rotate(meter_line, angle_degrees, origin='centroid')

            else:
                return {"type": "FeatureCollection", "features": []}

            # Simplify baseline to remove noise (improves parallel_offset stability)
            meter_line = meter_line.simplify(0.3, preserve_topology=True)

            # Generate Offsets
            # We need to cover the polygon.
            # Strategy: Generate offsets in both directions (left/right) until outside coverage.
            # But which way is 'inside'? We cover both.
            # parallel_offset(distance, side='left'/'right')
            # Warning: parallel_offset can be complex with sharp turns.
            # Use 'resolution' and 'join_style' if needed.
            
            lines = []
            
            # Add adjusted baseline itself? 
            # Request says: "Draw the drawn line... offset and draw". 
            
            # Extension Helper
            def _extend_line(line, extension_distance):
                if line.geom_type != 'LineString': return line
                coords = list(line.coords)
                if len(coords) < 2: return line
                
                # Robust Vector Finding Helper
                # Look ahead up to 3 points to avoid jitter
                def get_extension_vector(idx_start, step):
                    p_start = coords[idx_start]
                    curr_idx = idx_start + step
                    while 0 <= curr_idx < len(coords):
                        p_next = coords[curr_idx]
                        dx = p_start[0] - p_next[0]
                        dy = p_start[1] - p_next[1]
                        norm = math.hypot(dx, dy)
                        if norm > 1e-1: # Non-zero distance (relaxed threshold)
                             return p_start, dx, dy, norm
                        curr_idx += step
                    return None
                
                # Extend Start (Backwards)
                vec_start = get_extension_vector(0, 1) # Start at 0, step +1
                if vec_start:
                    p, dx, dy, norm = vec_start
                    scale = (extension_distance) / norm
                    new_start = (p[0] + dx * scale, p[1] + dy * scale)
                else:
                    new_start = coords[0]

                # Extend End (Forwards)
                vec_end = get_extension_vector(len(coords)-1, -1) # Start at end, step -1
                if vec_end:
                    p, dx, dy, norm = vec_end
                    scale = (extension_distance) / norm
                    new_end = (p[0] + dx * scale, p[1] + dy * scale)
                else:
                    new_end = coords[-1]
                
                return LineString([new_start] + coords[1:-1] + [new_end])

            # Extend baseline significantly to cover field
            bounds = meter_poly.bounds
            diagonal = math.hypot(bounds[2] - bounds[0], bounds[3] - bounds[1])
            # Use 5x diagonal (10x was maybe overkill, 5x is safe)
            extended_line = _extend_line(meter_line, diagonal * 5)

            lines = []
            
            # Direction 1 (Positive/Left)
            current_dist = offset_meters # Start at offset
            while True:
                try:
                    if current_dist == 0:
                        cand = extended_line
                    else:
                        # Use mitre join_style=2 for sharper corners (prevents rounding shortening)
                        cand = extended_line.parallel_offset(abs(current_dist), 'left' if current_dist > 0 else 'right', join_style=2, mitre_limit=10.0)
                except:
                    break # Offset error (topology)
                
                # Clip
                try:
                    inter = cand.intersection(meter_poly)
                except:
                    inter = iter([]) # dummy

                if not inter.is_empty:
                    if inter.geom_type in ['LineString', 'MultiLineString']:
                        lines.append(inter)
                    elif inter.geom_type == 'GeometryCollection':
                        # Extract lines
                        parts = [g for g in inter.geoms if g.geom_type in ['LineString', 'MultiLineString']]
                        if parts:
                           lines.append(unary_union(parts))
                else:
                    if abs(current_dist) > diagonal:
                        break
                
                current_dist += spacing_meters
                if abs(current_dist) > diagonal * 1.5: break

            # Direction 2 (Negative/Right)
            current_dist = offset_meters - spacing_meters
            while True:
                try:
                    effective_dist = current_dist
                    side = 'left' if effective_dist > 0 else 'right'
                    if effective_dist == 0:
                        cand = extended_line
                    else:
                        cand = extended_line.parallel_offset(abs(effective_dist), side, join_style=2, mitre_limit=10.0)
                except:
                    break
                    
                try:
                    inter = cand.intersection(meter_poly)
                except:
                    inter = iter([]) # dummy

                if not inter.is_empty:
                    if inter.geom_type in ['LineString', 'MultiLineString']:
                        lines.append(inter)
                    elif inter.geom_type == 'GeometryCollection':
                        parts = [g for g in inter.geoms if g.geom_type in ['LineString', 'MultiLineString']]
                        if parts: lines.append(unary_union(parts))
                else:
                    if abs(current_dist) > diagonal: break
                    
                current_dist -= spacing_meters
                if abs(current_dist) > diagonal * 1.5: break

            
            # Unproject lines
            result_features = []
            for geom in lines:
                # geom might be MultiLineString or LineString
                final_parts = []
                total_len = geom.length
                
                if total_len < 1.0:
                    continue

                to_process = geom.geoms if hasattr(geom, 'geoms') else [geom]
                
                final_coords_list = []
                for part in to_process:
                     coords = []
                     for x, y in part.coords:
                         lon = (x / lon_scale) + center.x
                         lat = (y / lat_scale) + center.y
                         coords.append((lon, lat))
                     final_coords_list.append(coords)
                
                # Construct GeoJSON Geometry
                if len(final_coords_list) == 1:
                     geometry = mapping(LineString(final_coords_list[0]))
                else:
                     geometry = mapping(MultiLineString(final_coords_list))

                result_features.append({
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "type": "row",
                        "length_m": total_len # Sum of lengths
                    }
                })
            
            return {
                "type": "FeatureCollection",
                "features": result_features
            }
            
        except Exception as e:
            return {"error": str(e)}
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    @staticmethod
    def calculate_bom_lite(feature_collection):
        """
        Calculate generic BOM from generated rows.
        """
        total_length = 0
        row_count = 0
        
        features = feature_collection.get('features', [])
        for f in features:
            props = f.get('properties', {})
            length = props.get('length_m', 0)
            total_length += length
            row_count += 1
            
        return {
            "row_count": row_count,
            "total_row_length_m": round(total_length, 2),
            "estimated_dripper_count_20cm": int(total_length / 0.2), # Example
            "estimated_dripper_count_30cm": int(total_length / 0.3)
        }
