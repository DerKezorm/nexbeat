import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Wohin der Proxy zeigt. Ueber NEXBEAT_API laesst es sich umbiegen.
const apiTarget = process.env.NEXBEAT_API || 'http://127.0.0.1:8030'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        // React, Router, Abfragen und i18next aendern sich selten. In einer
        // eigenen Datei bleiben sie nach einem Update im Browser liegen.
        manualChunks(id) {
          if (id.includes('node_modules')) return 'vendor'
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    exclude: ['node_modules/**', 'dist/**'],
  },
  server: {
    // Fester Port: Ist er belegt, bricht Vite ab, statt still auf einen anderen auszuweichen.
    port: 5182,
    strictPort: true,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
