import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  base: '/static/dist/notes/',
  build: {
    outDir: '../../js/notes',
    emptyOutDir: false,
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'index.html'),
      },
      output: {
        entryFileNames: `notes-widget.js`,
        chunkFileNames: `notes-widget.js`,
        assetFileNames: `notes-widget.[ext]`
      }
    }
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      'axios': path.resolve(__dirname, 'node_modules/axios/dist/esm/axios.js'),
    },
    extensions: ['.mjs', '.js', '.ts', '.jsx', '.tsx', '.json']
  },
  server: {
    proxy: {
        '/api': 'http://localhost:5000',
        '/notes': 'http://localhost:5000'
    }
  }
})
