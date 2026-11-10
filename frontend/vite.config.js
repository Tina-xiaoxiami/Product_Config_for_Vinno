import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

function preserveOpenTabs() {
  return {
    name: 'preserve-open-tabs-on-deploy',
    configureServer(server) {
      server.middlewares.use((request, _response, next) => {
        // Older Vite clients reload after any successful fetch of this probe.
        if (request.headers.accept === 'text/x-vite-ping') return request.socket.destroy()
        next()
      })
    }
  }
}

export default defineConfig(({ mode }) => {
  const keepTabs = loadEnv(mode, process.cwd(), 'VINNO_').VINNO_KEEP_OPEN_TABS === '1'
  return {
    plugins: keepTabs ? [preserveOpenTabs(), vue()] : [vue()],
    server: {
      host: '127.0.0.1',
      port: 3006,
      strictPort: true,
      hmr: keepTabs ? false : undefined,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8086',
          changeOrigin: true
        },
        '/release-workbench': {
          target: 'http://127.0.0.1:8086',
          changeOrigin: true
        }
      }
    }
  }
})
