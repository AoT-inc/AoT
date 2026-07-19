// assets/gltf_loader.js — GLTF/GLB user asset loader with cache
// Exposes window.AoTGLTFLoader. Requires THREE + THREE.GLTFLoader.
(function (global) {
  'use strict';

  const _cache = {};  // uuid → THREE.Group (cloned on each use)

  /**
   * Load a user GeoModelAsset into *parentGroup*.
   *
   * @param {string}       assetUuid   GeoModelAsset.unique_id
   * @param {string}       sourceFile  relative path under /static/
   * @param {object|null}  transform   {position:[x,y,z], rotation:[rx,ry,rz], scale:[sx,sy,sz]}
   * @param {THREE.Group}  parentGroup scene or group to add the model into
   * @param {function}     onLoad      called with the placed THREE.Group
   * @param {function}     onError     called with error message
   */
  function loadAsset(assetUuid, sourceFile, transform, parentGroup, onLoad, onError) {
    if (!window.THREE || !THREE.GLTFLoader) {
      if (onError) onError('THREE.GLTFLoader not available');
      return;
    }

    function _place(srcGroup) {
      const model = srcGroup.clone(true);
      model.name = 'user_asset_' + assetUuid;

      const t = transform || {};
      const pos = t.position || [0, 0, 0];
      const rot = t.rotation || [0, 0, 0];
      const scl = t.scale    || [1, 1, 1];

      model.position.set(pos[0], pos[1], pos[2]);
      model.rotation.set(rot[0], rot[1], rot[2]);
      model.scale.set(scl[0], scl[1], scl[2]);

      if (parentGroup) parentGroup.add(model);
      if (onLoad) onLoad(model);
    }

    if (_cache[assetUuid]) {
      _place(_cache[assetUuid]);
      return;
    }

    const url = '/static/' + sourceFile;
    const loader = new THREE.GLTFLoader();
    loader.load(
      url,
      function (gltf) {
        _cache[assetUuid] = gltf.scene;
        _place(gltf.scene);
      },
      undefined,
      function (err) {
        if (onError) onError('GLTF load failed: ' + (err && err.message ? err.message : String(err)));
      }
    );
  }

  function clearCache(assetUuid) {
    if (assetUuid) delete _cache[assetUuid];
    else Object.keys(_cache).forEach(k => delete _cache[k]);
  }

  global.AoTGLTFLoader = { loadAsset, clearCache };
})(window);
