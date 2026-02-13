import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    open: true,
    proxy: {
      '/sec-api': {
        target: 'https://efts.sec.gov',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/sec-api/, ''),
        headers: { 'User-Agent': 'WhaleWatch admin@seesaw.io' }
      },
      '/sec-data': {
        target: 'https://data.sec.gov',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/sec-data/, ''),
        headers: { 'User-Agent': 'WhaleWatch admin@seesaw.io' }
      },
      '/sec-archives': {
        target: 'https://www.sec.gov',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/sec-archives/, ''),
        headers: { 'User-Agent': 'WhaleWatch admin@seesaw.io' }
      }
    }
  },
  base: '/whalewatch/',
  build: {
    outDir: '../whalewatch-app',
    emptyOutDir: true,
    sourcemap: false
  }
})
