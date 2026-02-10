(function (factory) {
  if (typeof define === 'function' && define.amd) {
    define(['leaflet'], factory);
  } else if (typeof module !== 'undefined' && typeof module.exports !== 'undefined') {
    module.exports = factory(require('leaflet'));
  } else if (typeof window !== 'undefined' && window.L) {
    factory(window.L);
  }
}(function (L) {
  if (!L) { return null; }

  var defaultParams = {
    service: 'WMTS',
    request: 'GetTile',
    version: '1.0.0',
    layer: '',
    style: 'default',
    tilematrixset: 'GoogleMapsCompatible',
    format: 'image/png'
  };

  L.TileLayer.WMTS = L.TileLayer.extend({
    defaultWmtsParams: defaultParams,
    initialize: function (url, options) {
      this._url = url;
      var opts = options || {};
      var wmtsParams = L.extend({}, this.defaultWmtsParams);
      L.setOptions(this, opts);
      for (var i in opts) {
        if (!Object.prototype.hasOwnProperty.call(this.options, i) && i !== 'tileMatrixLabels' && i !== 'tileMatrixCallback') {
          wmtsParams[i.toLowerCase()] = opts[i];
        }
      }
      wmtsParams.width = wmtsParams.height = (this.options.tileSize && this.options.tileSize.x) ? this.options.tileSize.x : (this.options.tileSize || 256);
      this.wmtsParams = wmtsParams;
    },
    getTileUrl: function (coords) {
      var tileMatrix = coords.z;
      if (Array.isArray(this.options.tileMatrixLabels) && this.options.tileMatrixLabels[coords.z] !== undefined) {
        tileMatrix = this.options.tileMatrixLabels[coords.z];
      } else if (typeof this.options.tileMatrixCallback === 'function') {
        tileMatrix = this.options.tileMatrixCallback(coords.z, coords);
      }
      var url = this._url + (this._url.indexOf('?') === -1 ? '?' : '&');
      var params = L.extend({}, this.wmtsParams, {
        tilematrix: tileMatrix,
        tilerow: coords.y,
        tilecol: coords.x
      });
      return url + L.Util.getParamString(params, this._url);
    },
    setParams: function (params, noRedraw) {
      L.extend(this.wmtsParams, params);
      if (!noRedraw) {
        this.redraw();
      }
      return this;
    }
  });

  L.tileLayer.wmts = function (url, options) {
    return new L.TileLayer.WMTS(url, options);
  };

  return L.TileLayer.WMTS;
}));
