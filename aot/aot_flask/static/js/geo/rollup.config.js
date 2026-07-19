import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import terser from '@rollup/plugin-terser';

const production = process.env.NODE_ENV === 'production';

// ============================================================
// Custom plugin: Wrap IIFE as ES Module
// ============================================================
function wrapIIFEAsESModule() {
  return {
    name: 'wrap-iife-as-es-module',
    transform(code, id) {
      // Only process our target IIFE modules
      const targets = [
        'src/core/maplibre-core.js',
        'src/layers/vector-layer-manager.js',
        'src/layers/raster-bridge.js',
        'src/draw/maplibre-draw.js',
        'src/loaders/map-loader.js'
      ];
      
      const shouldProcess = targets.some(t => id.endsWith(t));
      if (!shouldProcess) return null;
      
      // Remove JSDoc comments that might cause issues
      let converted = code;
      
      // Replace IIFE pattern with export wrapper
      // Pattern 1: (function(global) { ... })(typeof window !== 'undefined' ? window : this);
      converted = converted.replace(
        /\(function\(global\)\s*\{([\s\S]*)\}\)\(typeof window !== 'undefined' \? window : this\);?$/,
        'export default (function(global) {$1})(typeof window !== "undefined" ? window : this);'
      );
      
      // Pattern 2: })(window);
      if (!converted.includes('export default')) {
        converted = converted.replace(
          /\}\)\(window\);?$/,
          'return __exports__;})(window);'
        );
      }
      
      return {
        code: converted,
        map: null
      };
    }
  };
}

export default [
  // Development bundle (with sourcemap)
  {
    input: 'src/index.js',
    output: {
      file: 'dist/aot-geo-all.bundle.js',
      format: 'iife',
      name: 'AoTGeo',
      sourcemap: true,
      globals: {
        'leaflet': 'L',
        'jquery': '$'
      }
    },
    external: ['leaflet', 'jquery'],
    plugins: [
      resolve({
        browser: true
      }),
      commonjs({
        transformMixedEsModules: true
      }),
      production && terser()
    ]
  },
  
  // Production bundle (minified)
  {
    input: 'src/index.js',
    output: {
      file: 'dist/aot-geo-all.bundle.min.js',
      format: 'iife',
      name: 'AoTGeo',
      sourcemap: true,
      globals: {
        'leaflet': 'L',
        'jquery': '$'
      }
    },
    external: ['leaflet', 'jquery'],
    plugins: [
      resolve({
        browser: true
      }),
      commonjs({
        transformMixedEsModules: true
      }),
      terser({
        compress: {
          drop_console: production,
          drop_debugger: true,
          passes: 2
        },
        mangle: {
          properties: false
        },
        format: {
          comments: false
        }
      })
    ]
  },
  
  // MCP Servers Management bundle
  {
    input: 'src/mcp_servers.js',
    output: {
      file: 'dist/mcp_servers.bundle.js',
      format: 'iife',
      globals: {
        'jquery': '$'
      }
    },
    external: ['jquery'],
    plugins: [
      resolve({ browser: true }),
      commonjs(),
      production && terser()
    ]
  }
];
