import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 3006,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8086',
        changeOrigin: true
      }
    }
  }
})