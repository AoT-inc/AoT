/**
 * AoT Geo Image Overlay editor
 * --------------------------------------------------------------------------
 * Config-modal UI for the `gis_image_overlay` provider (drone/aerial photo).
 *
 * Responsibilities:
 *   - Upload a photo (POST /api/geo/overlay_image/upload). The backend tries to
 *     auto-georeference it from EXIF/XMP and returns 4 corner coordinates.
 *   - Render the image on the modal preview map (AoTGeoInputPreview.previewMaps)
 *     over a satellite reference layer, with four draggable corner handles for
 *     manual correction (rubber-sheeting).
 *   - Live opacity control.
 *   - Persist corrected corners/opacity (POST /api/geo/overlay_image/save) and
 *     mirror them into the form's hidden inputs so a generic Save also keeps them.
 *
 * Depends on: maplibregl (already loaded), AoTGeoInputPreview (creates the map),
 * jQuery (Bootstrap modal events, consistent with aot-geo-input-preview.js).
 */
(function (global) {
    'use strict';

    // Satellite reference base shown under the photo so the user has something to
    // align against (the preview map itself starts with an empty style).
    var REF_BASE_URL =
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

    var AoTGeoImageOverlay = {
        // Per-uuid editor state: { imageUrl, coords:[[lng,lat]x4], opacity, markers:[] }
        _state: {},
        _bound: {},

        init: function () {
            var self = this;
            document.addEventListener('DOMContentLoaded', function () {
                if (!global.jQuery) return;
                global.jQuery(document).on('shown.bs.modal', '.modal', function (e) {
                    var id = e.target.id;
                    if (!id || id.indexOf('modal_config_') !== 0) return;
                    var uuid = id.replace('modal_config_', '');
                    var panel = document.querySelector(
                        '.aot-image-overlay-panel[data-uuid="' + uuid + '"]');
                    if (!panel) return;  // not an image-overlay layer
                    self.setup(uuid, panel);
                });
            });
        },

        _csrf: function (panel) {
            var meta = document.querySelector('meta[name="csrf-token"]');
            if (meta && meta.getAttribute('content')) return meta.getAttribute('content');
            var form = panel.closest('form');
            var inp = form && form.querySelector('input[name="csrf_token"]');
            return inp ? inp.value : '';
        },

        _status: function (panel, msg) {
            var el = panel.querySelector('.aot-ov-status');
            if (el) el.textContent = msg;
        },

        _setHidden: function (panel, name, value) {
            var form = panel.closest('form');
            if (!form) return;
            var inp = form.querySelector('input[name="' + name + '"]');
            if (inp) inp.value = value;
        },

        setup: function (uuid, panel) {
            var self = this;

            // Initialise state from the panel data attributes (saved values).
            var coords = null;
            try {
                var rawC = panel.getAttribute('data-coordinates');
                if (rawC && rawC !== 'None') coords = JSON.parse(rawC);
            } catch (err) { coords = null; }
            var op = parseFloat(panel.getAttribute('data-opacity'));
            if (isNaN(op)) op = 0.85;
            // Aspect lock defaults ON (rigid scale+rotation); '0' opts out.
            var lock = panel.getAttribute('data-lock-aspect') !== '0';
            // Seed aspect (height/width) from saved metadata; refined from the
            // actual image's native pixel size on render.
            var aspect = 0.75;
            try {
                var m = JSON.parse(panel.getAttribute('data-meta') || '{}');
                if (m.width && m.height) aspect = m.height / m.width;
            } catch (e) { /* keep default */ }
            // Editor texture: prefer the downscaled preview (large images) so the
            // corner-drag map stays light; the original/tiles are used on the map.
            var previewUrl = panel.getAttribute('data-preview-url') || '';
            var originalUrl = panel.getAttribute('data-image-url') || '';
            this._state[uuid] = {
                imageUrl: previewUrl || originalUrl,
                coords: (coords && coords.length === 4) ? coords : null,
                opacity: op,
                aspect: aspect,
                lockAspect: lock,
                markers: [],
                centerMarker: null
            };

            // Bind controls once per panel.
            if (!this._bound[uuid]) {
                this._bound[uuid] = true;

                var fileInput = panel.querySelector('.aot-ov-file');
                if (fileInput) {
                    fileInput.addEventListener('change', function () {
                        if (this.files && this.files[0]) self._upload(uuid, panel, this.files[0]);
                    });
                }
                var opacityInput = panel.querySelector('.aot-ov-opacity');
                if (opacityInput) {
                    opacityInput.addEventListener('input', function () {
                        var v = parseFloat(this.value);
                        if (isNaN(v)) return;
                        self._state[uuid].opacity = v;
                        self._setHidden(panel, 'opacity', String(v));
                        var map = self._map(uuid);
                        var lyr = self._ids(uuid).lyrId;
                        if (map && map.getLayer(lyr)) map.setPaintProperty(lyr, 'raster-opacity', v);
                    });
                }
                var lockInput = panel.querySelector('.aot-ov-lock');
                if (lockInput) {
                    lockInput.checked = self._state[uuid].lockAspect;
                    lockInput.addEventListener('change', function () {
                        self._state[uuid].lockAspect = this.checked;
                        self._setHidden(panel, 'lock_aspect', this.checked ? '1' : '0');
                    });
                }
                var saveBtn = panel.querySelector('.aot-ov-save');
                if (saveBtn) saveBtn.addEventListener('click', function () { self._save(uuid, panel); });

                var resetBtn = panel.querySelector('.aot-ov-reset');
                if (resetBtn) resetBtn.addEventListener('click', function () { self._recenter(uuid, panel); });
            }

            // Render existing overlay once the preview map is ready, after the
            // image's native aspect ratio is known.
            if (this._state[uuid].imageUrl) {
                this._whenMapReady(uuid, function () {
                    self._applyImageAspect(uuid, function () { self._render(uuid, panel); });
                });
            }
        },

        // Resolve the image's true aspect (height/width) from its natural pixel
        // size so the default placement box matches the original proportions.
        _applyImageAspect: function (uuid, cb) {
            var st = this._state[uuid];
            if (!st || !st.imageUrl || st._aspectResolved) { if (cb) cb(); return; }
            var img = new Image();
            img.onload = function () {
                if (img.naturalWidth && img.naturalHeight) {
                    st.aspect = img.naturalHeight / img.naturalWidth;
                }
                st._aspectResolved = true;
                if (cb) cb();
            };
            img.onerror = function () { st._aspectResolved = true; if (cb) cb(); };
            img.src = st.imageUrl;
        },

        _preview: function () {
            // AoTGeoInputPreview is declared as a top-level `const` in a classic
            // script, so it lives in the global *lexical* scope — NOT as a
            // window property. Resolve the lexical binding (guarded), then fall
            // back to the window property for safety.
            if (typeof AoTGeoInputPreview !== 'undefined') return AoTGeoInputPreview;
            return global.AoTGeoInputPreview || null;
        },

        _map: function (uuid) {
            var P = this._preview();
            return (P && P.previewMaps && P.previewMaps[uuid]) || null;
        },

        _whenMapReady: function (uuid, cb) {
            var self = this;
            var tries = 0;
            (function poll() {
                var map = self._map(uuid);
                if (map && map.isStyleLoaded && map.isStyleLoaded()) { cb(map); return; }
                if (map && map.loaded && map.loaded()) { cb(map); return; }
                if (++tries > 60) return;  // ~6s give-up
                setTimeout(poll, 100);
            })();
        },

        _ids: function (uuid) {
            return {
                baseSrc: 'aot_ovedit_base_' + uuid,
                baseLyr: 'aot_ovedit_base_' + uuid + '_layer',
                srcId: 'aot_ovedit_' + uuid,
                lyrId: 'aot_ovedit_' + uuid + '_layer'
            };
        },

        _ensureRefBase: function (map, uuid) {
            var ids = this._ids(uuid);
            try {
                if (!map.getSource(ids.baseSrc)) {
                    map.addSource(ids.baseSrc, {
                        type: 'raster',
                        tiles: [REF_BASE_URL],
                        tileSize: 256,
                        attribution: '© Esri'
                    });
                }
                if (!map.getLayer(ids.baseLyr)) {
                    // Insert at the very bottom so the photo + handles stay on top.
                    map.addLayer({ id: ids.baseLyr, type: 'raster', source: ids.baseSrc });
                }
            } catch (e) { /* style not ready yet; caller retries */ }
        },

        _render: function (uuid, panel) {
            var self = this;
            var st = this._state[uuid];
            if (!st || !st.imageUrl) return;
            var map = this._map(uuid);
            if (!map) return;
            var ids = this._ids(uuid);

            this._ensureRefBase(map, uuid);

            // If we have no coordinates yet, drop a default box at the map centre.
            if (!st.coords) st.coords = this._defaultBox(map, st.aspect);

            try {
                if (map.getLayer(ids.lyrId)) map.removeLayer(ids.lyrId);
                if (map.getSource(ids.srcId)) map.removeSource(ids.srcId);
                map.addSource(ids.srcId, {
                    type: 'image',
                    url: st.imageUrl,
                    coordinates: st.coords
                });
                map.addLayer({
                    id: ids.lyrId,
                    type: 'raster',
                    source: ids.srcId,
                    paint: { 'raster-opacity': st.opacity, 'raster-fade-duration': 0 }
                });
            } catch (e) {
                self._status(panel, 'Render failed: ' + e.message);
                return;
            }

            this._buildHandles(uuid, panel);
            this._fit(map, st.coords);
            this._setHidden(panel, 'coordinates', JSON.stringify(st.coords));
        },

        // Corner + centre handles (maplibre markers). Corners: TL, TR, BR, BL.
        // With aspect-lock ON, dragging a corner scales+rotates the whole image
        // about its centre (shape preserved); OFF gives free per-corner warp.
        // The blue centre handle always translates the whole image.
        _buildHandles: function (uuid, panel) {
            var self = this;
            var st = this._state[uuid];
            var map = this._map(uuid);
            if (!map || !global.maplibregl) return;

            // Clear old markers (corners + centre).
            st.markers.forEach(function (m) { try { m.remove(); } catch (e) {} });
            st.markers = [];
            if (st.centerMarker) { try { st.centerMarker.remove(); } catch (e) {} st.centerMarker = null; }

            var labels = ['TL', 'TR', 'BR', 'BL'];
            st.coords.forEach(function (c, idx) {
                var el = document.createElement('div');
                el.className = 'aot-ov-handle';
                el.title = labels[idx];
                el.style.cssText =
                    'width:14px;height:14px;border-radius:50%;background:#ff5722;' +
                    'border:2px solid #fff;box-shadow:0 0 3px rgba(0,0,0,.5);cursor:move;';
                var marker = new global.maplibregl.Marker({ element: el, draggable: true })
                    .setLngLat(c).addTo(map);

                marker.on('dragstart', function () {
                    // Snapshot reference shape so rigid transforms don't compound.
                    var cen = self._centroid(st.coords);
                    st._dragRef = {
                        coords: st.coords.map(function (p) { return [p[0], p[1]]; }),
                        center: cen,
                        vOld: self._meters(cen, st.coords[idx])
                    };
                });
                marker.on('drag', function () {
                    var ll = marker.getLngLat();
                    if (st.lockAspect) {
                        self._applyRigid(uuid, [ll.lng, ll.lat], idx);
                    } else {
                        st.coords[idx] = [ll.lng, ll.lat];
                        self._updateSource(uuid);
                        self._syncMarkers(uuid, idx);
                    }
                });
                marker.on('dragend', function () {
                    st._dragRef = null;
                    self._syncMarkers(uuid, -1);
                    self._setHidden(panel, 'coordinates', JSON.stringify(st.coords));
                });
                st.markers.push(marker);
            });

            // Centre handle — drag to translate the whole image.
            var cEl = document.createElement('div');
            cEl.className = 'aot-ov-center';
            cEl.title = 'Move';
            cEl.style.cssText =
                'width:16px;height:16px;border-radius:50%;background:#2196f3;' +
                'border:2px solid #fff;box-shadow:0 0 3px rgba(0,0,0,.6);cursor:move;';
            var cMarker = new global.maplibregl.Marker({ element: cEl, draggable: true })
                .setLngLat(self._centroid(st.coords)).addTo(map);
            cMarker.on('dragstart', function () {
                st._moveRef = {
                    coords: st.coords.map(function (p) { return [p[0], p[1]]; }),
                    center: cMarker.getLngLat()
                };
            });
            cMarker.on('drag', function () {
                var ref = st._moveRef; if (!ref) return;
                var ll = cMarker.getLngLat();
                var dx = ll.lng - ref.center.lng, dy = ll.lat - ref.center.lat;
                st.coords = ref.coords.map(function (p) { return [p[0] + dx, p[1] + dy]; });
                self._updateSource(uuid);
                self._syncMarkers(uuid, -2); // move corners, not the centre being dragged
            });
            cMarker.on('dragend', function () {
                st._moveRef = null;
                self._setHidden(panel, 'coordinates', JSON.stringify(st.coords));
            });
            st.centerMarker = cMarker;
        },

        // --- geometry helpers ---
        _centroid: function (coords) {
            var lng = 0, lat = 0;
            coords.forEach(function (c) { lng += c[0]; lat += c[1]; });
            return [lng / coords.length, lat / coords.length];
        },
        // Local tangent-plane metres relative to `origin` [lng,lat].
        _meters: function (origin, pt) {
            var mlng = 111320 * Math.cos(origin[1] * Math.PI / 180);
            return { e: (pt[0] - origin[0]) * mlng, n: (pt[1] - origin[1]) * 111320 };
        },
        _lnglat: function (origin, e, n) {
            var mlng = 111320 * Math.cos(origin[1] * Math.PI / 180);
            return [origin[0] + e / mlng, origin[1] + n / 111320];
        },
        // Scale+rotate the snapshot shape about its (fixed) centre so the dragged
        // corner lands on `target`, keeping the image's aspect ratio.
        _applyRigid: function (uuid, target, idx) {
            var self = this;
            var st = this._state[uuid];
            var ref = st._dragRef; if (!ref) return;
            var cen = ref.center;
            var vNew = this._meters(cen, target);
            var oldLen = Math.hypot(ref.vOld.e, ref.vOld.n);
            if (oldLen < 1e-6) return;
            var scale = Math.hypot(vNew.e, vNew.n) / oldLen;
            var ang = Math.atan2(vNew.n, vNew.e) - Math.atan2(ref.vOld.n, ref.vOld.e);
            var cosA = Math.cos(ang), sinA = Math.sin(ang);
            st.coords = ref.coords.map(function (p) {
                var v = self._meters(cen, p);
                var e2 = scale * (v.e * cosA - v.n * sinA);
                var n2 = scale * (v.e * sinA + v.n * cosA);
                return self._lnglat(cen, e2, n2);
            });
            this._updateSource(uuid);
            this._syncMarkers(uuid, idx);
        },
        _updateSource: function (uuid) {
            var map = this._map(uuid);
            if (!map) return;
            var src = map.getSource(this._ids(uuid).srcId);
            if (src && src.setCoordinates) {
                try { src.setCoordinates(this._state[uuid].coords); } catch (e) {}
            }
        },
        // Reposition markers from st.coords. exceptIdx: corner index being dragged
        // (-1 = none; -2 = centre being dragged, so only corners are updated).
        _syncMarkers: function (uuid, exceptIdx) {
            var st = this._state[uuid];
            st.markers.forEach(function (m, i) {
                if (i === exceptIdx) return;
                try { m.setLngLat(st.coords[i]); } catch (e) {}
            });
            if (st.centerMarker && exceptIdx !== -2) {
                try { st.centerMarker.setLngLat(this._centroid(st.coords)); } catch (e) {}
            }
        },

        _fit: function (map, coords) {
            try {
                var b = new global.maplibregl.LngLatBounds();
                coords.forEach(function (c) { b.extend(c); });
                map.fitBounds(b, { padding: 40, duration: 0, maxZoom: 21 });
            } catch (e) { /* ignore */ }
        },

        // Build a north-aligned rectangle centred on the current view, sized so
        // its on-the-ground aspect (height/width in metres) equals the image's.
        _defaultBox: function (map, aspect) {
            var c = map.getCenter();
            // ~ a quarter of the current viewport width on the ground.
            var bounds = map.getBounds();
            var spanLng = Math.abs(bounds.getEast() - bounds.getWest());
            var halfW = (spanLng * 0.25) / 2;
            // 1° of longitude is cos(lat)× shorter than 1° of latitude in metres,
            // so multiply (not divide) to keep the metric aspect correct.
            var cosLat = Math.max(0.2, Math.cos(c.lat * Math.PI / 180));
            var halfH = halfW * (aspect || 0.75) * cosLat;
            return [
                [c.lng - halfW, c.lat + halfH], // TL
                [c.lng + halfW, c.lat + halfH], // TR
                [c.lng + halfW, c.lat - halfH], // BR
                [c.lng - halfW, c.lat - halfH]  // BL
            ];
        },

        _recenter: function (uuid, panel) {
            var st = this._state[uuid];
            var map = this._map(uuid);
            if (!st || !map) return;
            st.coords = this._defaultBox(map, st.aspect);
            this._render(uuid, panel);
            this._status(panel, 'Re-centred. Drag the corners to align, then Save.');
        },

        _upload: function (uuid, panel, file) {
            var self = this;
            this._status(panel, 'Uploading…');
            var fd = new FormData();
            fd.append('file', file);
            fd.append('layer_id', uuid);
            fetch('/api/geo/overlay_image/upload', {
                method: 'POST',
                headers: { 'X-CSRFToken': this._csrf(panel) },
                body: fd,
                credentials: 'same-origin'
            }).then(function (r) { return r.json(); }).then(function (data) {
                if (!data || !data.ok) {
                    self._status(panel, 'Upload failed: ' + ((data && data.error) || 'unknown'));
                    return;
                }
                var st = self._state[uuid];
                // Render the preview in the editor when present (large images);
                // the original/tiles drive the actual map.
                st.imageUrl = data.preview_url || data.image_url;
                st._aspectResolved = false; // re-resolve native aspect for the new image
                if (data.width && data.height) { st.aspect = data.height / data.width; st._aspectResolved = true; }
                // Coordinate precedence:
                //  - server returned 4 corners (kept on replacement, or auto-georef) → use them
                //  - nothing returned but we already have a placement → keep it (image-only swap)
                //  - otherwise → null, _render drops a default box at the map centre
                if (data.coordinates && data.coordinates.length === 4) {
                    st.coords = data.coordinates;
                } else if (!(st.coords && st.coords.length === 4)) {
                    st.coords = null;
                }
                self._setHidden(panel, 'image_url', data.image_url);
                if (data.meta) self._setHidden(panel, 'meta', JSON.stringify(data.meta));
                var baseMsg = data.preserved_coords
                    ? 'Image replaced — existing placement kept. Adjust corners if needed, then Save.'
                    : (data.auto_georeferenced
                        ? 'Auto-placed from photo GPS/EXIF. Drag corners to fine-tune, then Save.'
                        : 'No GPS metadata found — image placed at map centre. Drag corners to align, then Save.');
                if (data.tile_eligible) {
                    baseMsg += (data.tile_status === 'pending')
                        ? ' Large image — generating map tiles…'
                        : ' Large image — Save Placement to generate map tiles.';
                }
                self._status(panel, baseMsg);
                if (data.tile_status === 'pending') self._pollTiles(uuid, panel);
                self._whenMapReady(uuid, function () {
                    self._applyImageAspect(uuid, function () { self._render(uuid, panel); });
                });
            }).catch(function (e) {
                self._status(panel, 'Upload error: ' + e.message);
            });
        },

        _save: function (uuid, panel) {
            var self = this;
            var st = this._state[uuid];
            if (!st || !st.coords) { this._status(panel, 'Nothing to save yet.'); return; }
            this._status(panel, 'Saving…');
            fetch('/api/geo/overlay_image/save', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this._csrf(panel)
                },
                body: JSON.stringify({
                    layer_id: uuid,
                    coordinates: st.coords,
                    opacity: st.opacity
                }),
                credentials: 'same-origin'
            }).then(function (r) { return r.json(); }).then(function (data) {
                if (data && data.ok) {
                    self._setHidden(panel, 'coordinates', JSON.stringify(st.coords));
                    self._setHidden(panel, 'opacity', String(st.opacity));
                    if (data.tile_status === 'pending') {
                        self._status(panel, 'Placement saved. Generating map tiles…');
                        self._pollTiles(uuid, panel);
                    } else {
                        self._status(panel, 'Placement saved.');
                    }
                } else {
                    self._status(panel, 'Save failed: ' + ((data && data.error) || 'unknown'));
                }
            }).catch(function (e) {
                self._status(panel, 'Save error: ' + e.message);
            });
        },

        // Poll the server until the tile pyramid for this layer is ready (or
        // fails). Large image overlays are tiled in the background; this just
        // surfaces progress in the panel status line.
        _pollTiles: function (uuid, panel) {
            var self = this;
            var tries = 0;
            (function poll() {
                if (++tries > 600) return;  // ~10 min give-up
                fetch('/api/geo/overlay_image/tile_status/' + encodeURIComponent(uuid), {
                    credentials: 'same-origin'
                }).then(function (r) { return r.json(); }).then(function (d) {
                    if (!d || !d.ok) return;
                    if (d.tile_status === 'ready') {
                        self._status(panel, 'Map tiles ready (' + (d.tile_count || 0) +
                            ' tiles, zoom ' + d.minzoom + '–' + d.maxzoom + ').');
                    } else if (d.tile_status === 'error') {
                        self._status(panel, 'Tile generation failed: ' + (d.tile_error || 'unknown'));
                    } else {
                        setTimeout(poll, 1000);
                    }
                }).catch(function () { setTimeout(poll, 2000); });
            })();
        }
    };

    global.AoTGeoImageOverlay = AoTGeoImageOverlay;
    AoTGeoImageOverlay.init();

})(window);
